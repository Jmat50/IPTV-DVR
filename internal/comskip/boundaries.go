package comskip

import (
	"bytes"
	"fmt"
	"io"
	"math"
	"os/exec"
	"path/filepath"
	"regexp"
	"sort"
	"strconv"
	"strings"
)

const (
	minEpisodeSec     = 10 * 60
	maxEpisodeSec     = 90 * 60
	minBlackDuration  = 2.0
)

var (
	blackLineRe    = regexp.MustCompile(`black_start:([0-9.]+)\s+black_end:([0-9.]+)\s+black_duration:([0-9.]+)`)
	silenceStartRe = regexp.MustCompile(`silence_start:\s*([0-9.]+)`)
	silenceEndRe   = regexp.MustCompile(`silence_end:\s*([0-9.]+)`)
)

type gapCandidate struct {
	TimeSec float64
	Score   float64
}

func candidateLengths() []float64 {
	return []float64{22 * 60, 30 * 60, 44 * 60, 60 * 60}
}

func bestFitLength(totalSec float64, jobDurationSec int) float64 {
	if jobDurationSec > 0 {
		return float64(jobDurationSec)
	}
	best := candidateLengths()[0]
	bestErr := math.Abs(totalSec - best)
	for _, length := range candidateLengths() {
		err := math.Abs(totalSec - length)
		if err < bestErr {
			best = length
			bestErr = err
		}
	}
	return best
}

func estimateEpisodeCount(totalSec float64, jobDurationSec int) int {
	slot := bestFitLength(totalSec, jobDurationSec)
	if slot <= 0 {
		return 1
	}
	count := int(math.Round(totalSec / slot))
	if count < 1 {
		count = 1
	}
	return count
}

func runFFmpegFilter(ffmpegPath, tsPath, vf, af string, log io.Writer) string {
	if ffmpegPath == "" {
		ffmpegPath = "ffmpeg"
	}
	args := []string{"-hide_banner", "-i", tsPath}
	if vf != "" {
		args = append(args, "-map", "0:v:0", "-vf", vf, "-an")
	} else if af != "" {
		args = append(args, "-af", af)
	} else {
		return ""
	}
	args = append(args, "-f", "null", "-")
	cmd := exec.Command(ffmpegPath, args...)
	var buf bytes.Buffer
	cmd.Stdout = &buf
	cmd.Stderr = &buf
	_ = cmd.Run()
	out := buf.String()
	if log != nil {
		_, _ = fmt.Fprintf(log, "\n---\n$ %s %s\n%s", ffmpegPath, strings.Join(args, " "), out)
	}
	return out
}

func parseBlackDetect(text string) []gapCandidate {
	var out []gapCandidate
	for _, m := range blackLineRe.FindAllStringSubmatch(text, -1) {
		start, _ := strconv.ParseFloat(m[1], 64)
		end, _ := strconv.ParseFloat(m[2], 64)
		duration, _ := strconv.ParseFloat(m[3], 64)
		if duration < minBlackDuration {
			continue
		}
		out = append(out, gapCandidate{TimeSec: (start + end) / 2, Score: 1.0})
	}
	return out
}

func parseSilenceDetect(text string) []gapCandidate {
	var starts, ends []float64
	for _, m := range silenceStartRe.FindAllStringSubmatch(text, -1) {
		v, _ := strconv.ParseFloat(m[1], 64)
		starts = append(starts, v)
	}
	for _, m := range silenceEndRe.FindAllStringSubmatch(text, -1) {
		v, _ := strconv.ParseFloat(m[1], 64)
		ends = append(ends, v)
	}
	var out []gapCandidate
	for _, start := range starts {
		var end float64
		for _, e := range ends {
			if e >= start {
				end = e
				break
			}
		}
		if end <= start || (end-start) < 1.0 {
			continue
		}
		out = append(out, gapCandidate{TimeSec: (start + end) / 2, Score: 0.6})
	}
	return out
}

func mergeCandidates(black, silence []gapCandidate) []gapCandidate {
	merged := map[float64]float64{}
	for _, c := range append(black, silence...) {
		key := math.Round(c.TimeSec*10) / 10
		merged[key] += c.Score
	}
	for _, b := range black {
		for _, s := range silence {
			if math.Abs(b.TimeSec-s.TimeSec) <= 1.0 {
				key := math.Round(((b.TimeSec+s.TimeSec)/2)*10) / 10
				merged[key] += 0.5
			}
		}
	}
	var out []gapCandidate
	for k, v := range merged {
		out = append(out, gapCandidate{TimeSec: k, Score: v})
	}
	return out
}

func scoreBoundary(timeSec, totalSec float64, expectedCount int, base float64) float64 {
	if expectedCount <= 1 {
		return base
	}
	score := base
	for k := 1; k < expectedCount; k++ {
		ideal := (totalSec * float64(k)) / float64(expectedCount)
		dist := math.Abs(timeSec - ideal)
		tolerance := totalSec / (float64(expectedCount) * 2)
		if tolerance > 0 {
			score += math.Max(0, 1.0-(dist/tolerance))
		}
	}
	return score
}

func pickBoundaries(candidates []gapCandidate, totalSec float64, expectedCount int) []float64 {
	if expectedCount <= 1 {
		return nil
	}
	type scored struct {
		Time  float64
		Score float64
	}
	var list []scored
	for _, c := range candidates {
		if c.TimeSec <= minEpisodeSec || c.TimeSec >= (totalSec-minEpisodeSec) {
			continue
		}
		list = append(list, scored{
			Time:  c.TimeSec,
			Score: scoreBoundary(c.TimeSec, totalSec, expectedCount, c.Score),
		})
	}
	sort.Slice(list, func(i, j int) bool {
		if list[i].Score == list[j].Score {
			return list[i].Time < list[j].Time
		}
		return list[i].Score > list[j].Score
	})
	var chosen []float64
	for _, item := range list {
		if item.Score < 1.0 {
			continue
		}
		tooClose := false
		for _, existing := range chosen {
			if math.Abs(item.Time-existing) < minEpisodeSec {
				tooClose = true
				break
			}
		}
		if tooClose {
			continue
		}
		chosen = append(chosen, item.Time)
		if len(chosen) >= expectedCount-1 {
			break
		}
	}
	sort.Float64s(chosen)
	return chosen
}

func segmentsFromBoundaries(boundaries []float64, totalSec float64) []EpisodeSegment {
	if len(boundaries) == 0 {
		return []EpisodeSegment{{Index: 1, StartSec: 0, EndSec: totalSec}}
	}
	points := append([]float64{0}, boundaries...)
	points = append(points, totalSec)
	var segments []EpisodeSegment
	for i := 0; i < len(points)-1; i++ {
		start := points[i]
		end := points[i+1]
		if end-start < minEpisodeSec/2 {
			continue
		}
		if end-start > maxEpisodeSec {
			continue
		}
		segments = append(segments, EpisodeSegment{
			Index:    len(segments) + 1,
			StartSec: start,
			EndSec:   end,
		})
	}
	if len(segments) == 0 {
		return []EpisodeSegment{{Index: 1, StartSec: 0, EndSec: totalSec}}
	}
	return segments
}

// DetectEpisodeBoundaries finds likely episode seams in a long TS recording.
func DetectEpisodeBoundaries(ffmpegPath, tsPath string, jobDurationSec int, log io.Writer) []EpisodeSegment {
	total, ok := probeStreamDuration(ffmpegPath, tsPath, "v:0")
	if !ok || total <= 0 {
		return []EpisodeSegment{{Index: 1, StartSec: 0, EndSec: 0}}
	}
	blackText := runFFmpegFilter(ffmpegPath, tsPath, "blackdetect=d=2.5:pic_th=0.98:pix_th=0.10", "", log)
	silenceText := runFFmpegFilter(ffmpegPath, tsPath, "", "silencedetect=noise=-35dB:d=1.2", log)
	candidates := mergeCandidates(parseBlackDetect(blackText), parseSilenceDetect(silenceText))
	expected := estimateEpisodeCount(total, jobDurationSec)
	boundaries := pickBoundaries(candidates, total, expected)
	segments := segmentsFromBoundaries(boundaries, total)
	if log != nil {
		if len(segments) == 1 {
			_, _ = fmt.Fprintln(log, "comskip: episode detection found single segment (whole file)")
		} else {
			_, _ = fmt.Fprintf(log, "comskip: episode detection found %d segments (expected_count=%d)\n", len(segments), expected)
		}
	}
	return segments
}

func probeStreamDuration(ffmpegPath, mediaPath, stream string) (float64, bool) {
	ffprobe := ffprobeFromFFmpeg(ffmpegPath)
	cmd := exec.Command(
		ffprobe,
		"-v", "error",
		"-select_streams", stream,
		"-show_entries", "stream=duration",
		"-of", "default=noprint_wrappers=1:nokey=1",
		mediaPath,
	)
	var out bytes.Buffer
	cmd.Stdout = &out
	cmd.Stderr = io.Discard
	if err := cmd.Run(); err != nil {
		return 0, false
	}
	for _, raw := range strings.Split(out.String(), "\n") {
		text := strings.TrimSpace(raw)
		if text == "" {
			continue
		}
		v, err := strconv.ParseFloat(text, 64)
		if err != nil || v <= 0 {
			continue
		}
		return v, true
	}
	return 0, false
}

func probeVideoFPS(ffmpegPath, mediaPath string) float64 {
	ffprobe := ffprobeFromFFmpeg(ffmpegPath)
	cmd := exec.Command(
		ffprobe,
		"-v", "error",
		"-select_streams", "v:0",
		"-show_entries", "stream=avg_frame_rate",
		"-of", "default=noprint_wrappers=1:nokey=1",
		mediaPath,
	)
	var out bytes.Buffer
	cmd.Stdout = &out
	cmd.Stderr = io.Discard
	if err := cmd.Run(); err != nil {
		return 29.97
	}
	rate := strings.TrimSpace(out.String())
	if rate == "" || rate == "0/0" {
		return 29.97
	}
	if strings.Contains(rate, "/") {
		parts := strings.SplitN(rate, "/", 2)
		num, err1 := strconv.ParseFloat(parts[0], 64)
		den, err2 := strconv.ParseFloat(parts[1], 64)
		if err1 == nil && err2 == nil && den != 0 {
			return num / den
		}
	}
	if v, err := strconv.ParseFloat(rate, 64); err == nil && v > 0 {
		return v
	}
	return 29.97
}

func ffprobeFromFFmpeg(ffmpegPath string) string {
	if ffmpegPath == "" {
		return "ffprobe"
	}
	return filepath.Join(filepath.Dir(ffmpegPath), "ffprobe"+filepath.Ext(ffmpegPath))
}

func extractSegment(ffmpegPath, tsPath string, startSec, endSec float64, outSeg string, log io.Writer) bool {
	if ffmpegPath == "" {
		ffmpegPath = "ffmpeg"
	}
	args := []string{
		"-y",
		"-ss", fmt.Sprintf("%.3f", startSec),
		"-to", fmt.Sprintf("%.3f", endSec),
		"-i", tsPath,
		"-map", "0",
		"-c", "copy",
		outSeg,
	}
	cmd := exec.Command(ffmpegPath, args...)
	var buf bytes.Buffer
	cmd.Stdout = &buf
	cmd.Stderr = &buf
	if log != nil {
		_, _ = fmt.Fprintf(log, "\n---\n$ %s %s\n", ffmpegPath, strings.Join(args, " "))
	}
	if err := cmd.Run(); err != nil {
		return false
	}
	if log != nil && buf.Len() > 0 {
		_, _ = log.Write(buf.Bytes())
	}
	return fileSize(outSeg) > 0
}
