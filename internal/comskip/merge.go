package comskip

import (
	"bufio"
	"fmt"
	"os"
	"path/filepath"
	"regexp"
	"sort"
	"strconv"
	"strings"
)

// CommercialBreak is a detected commercial interval in seconds.
type CommercialBreak struct {
	StartSec     float64
	EndSec       float64
	EpisodeIndex int
}

// EpisodeSegment is a detected episode block in a long recording.
type EpisodeSegment struct {
	Index    int
	StartSec float64
	EndSec   float64
}

var (
	edlLineRe = regexp.MustCompile(`^\s*([0-9]+(?:\.[0-9]+)?)\s+([0-9]+(?:\.[0-9]+)?)\s+([0-9]+)\s*$`)
	framePair = regexp.MustCompile(`^\s*(\d+)\s+(\d+)\s*$`)
	txtV2Re   = regexp.MustCompile(`(?i)FILE PROCESSING COMPLETE\s+(\d+)\s+FRAMES AT\s+(\d+)`)
)

// ParseEDL reads MPlayer-style commercial breaks from a Comskip .edl file.
func ParseEDL(path string) ([]CommercialBreak, error) {
	f, err := os.Open(path)
	if err != nil {
		return nil, err
	}
	defer f.Close()
	var out []CommercialBreak
	sc := bufio.NewScanner(f)
	for sc.Scan() {
		m := edlLineRe.FindStringSubmatch(sc.Text())
		if m == nil {
			continue
		}
		start, _ := strconv.ParseFloat(m[1], 64)
		end, _ := strconv.ParseFloat(m[2], 64)
		if end <= start {
			continue
		}
		out = append(out, CommercialBreak{StartSec: start, EndSec: end})
	}
	return out, sc.Err()
}

// ParseTXT reads frame-based commercial markers; returns fps and frame pairs.
func ParseTXT(path string) (float64, [][2]int, error) {
	data, err := os.ReadFile(path)
	if err != nil {
		return 0, nil, err
	}
	lines := strings.Split(string(data), "\n")
	fps := 0.0
	pastHeader := false
	var pairs [][2]int
	for _, line := range lines {
		if !pastHeader {
			if m := txtV2Re.FindStringSubmatch(line); m != nil {
				framesAt, _ := strconv.Atoi(m[2])
				if framesAt > 0 {
					fps = float64(framesAt) / 100.0
				}
			}
			if strings.HasPrefix(strings.TrimSpace(line), "---") {
				pastHeader = true
			}
			continue
		}
		m := framePair.FindStringSubmatch(line)
		if m == nil {
			continue
		}
		startF, _ := strconv.Atoi(m[1])
		endF, _ := strconv.Atoi(m[2])
		if endF <= startF {
			continue
		}
		pairs = append(pairs, [2]int{startF, endF})
	}
	return fps, pairs, nil
}

func breaksFromTXT(path string, fps float64) ([]CommercialBreak, error) {
	parsedFPS, pairs, err := ParseTXT(path)
	if err != nil {
		return nil, err
	}
	useFPS := fps
	if useFPS <= 0 {
		useFPS = parsedFPS
	}
	if useFPS <= 0 {
		useFPS = 29.97
	}
	var out []CommercialBreak
	for _, p := range pairs {
		out = append(out, CommercialBreak{
			StartSec: float64(p[0]) / useFPS,
			EndSec:   float64(p[1]) / useFPS,
		})
	}
	return out, nil
}

type segmentSidecars struct {
	Segment EpisodeSegment
	EDL     string
	TXT     string
}

// MergeCommercialBreaks merges per-segment sidecars onto the master timeline.
func MergeCommercialBreaks(inputs []segmentSidecars, totalSec float64) []CommercialBreak {
	var merged []CommercialBreak
	for _, in := range inputs {
		var local []CommercialBreak
		if in.EDL != "" {
			local, _ = ParseEDL(in.EDL)
		} else if in.TXT != "" {
			local, _ = breaksFromTXT(in.TXT, 0)
		}
		for _, br := range local {
			merged = append(merged, CommercialBreak{
				StartSec:     br.StartSec + in.Segment.StartSec,
				EndSec:       br.EndSec + in.Segment.StartSec,
				EpisodeIndex: in.Segment.Index,
			})
		}
	}
	return NormalizeBreaks(merged, totalSec)
}

// NormalizeBreaks clamps, sorts, and de-overlaps commercial breaks.
func NormalizeBreaks(breaks []CommercialBreak, totalSec float64) []CommercialBreak {
	if len(breaks) == 0 {
		return nil
	}
	var clipped []CommercialBreak
	for _, br := range breaks {
		start := br.StartSec
		end := br.EndSec
		if start < 0 {
			start = 0
		}
		if end > totalSec {
			end = totalSec
		}
		if end <= start {
			continue
		}
		clipped = append(clipped, CommercialBreak{
			StartSec:     start,
			EndSec:       end,
			EpisodeIndex: br.EpisodeIndex,
		})
	}
	sort.Slice(clipped, func(i, j int) bool {
		if clipped[i].StartSec == clipped[j].StartSec {
			return clipped[i].EndSec < clipped[j].EndSec
		}
		return clipped[i].StartSec < clipped[j].StartSec
	})
	var out []CommercialBreak
	for _, br := range clipped {
		if len(out) > 0 && br.StartSec < out[len(out)-1].EndSec {
			prev := out[len(out)-1]
			if br.EndSec > prev.EndSec {
				prev.EndSec = br.EndSec
			}
			if prev.EpisodeIndex == 0 {
				prev.EpisodeIndex = br.EpisodeIndex
			}
			out[len(out)-1] = prev
			continue
		}
		out = append(out, br)
	}
	return out
}

// WriteMergedEDL writes Kodi-compatible commercial EDL sidecar.
func WriteMergedEDL(path string, breaks []CommercialBreak) error {
	var b strings.Builder
	for _, br := range breaks {
		b.WriteString(fmt.Sprintf("%.2f\t%.2f\t3\n", br.StartSec, br.EndSec))
	}
	return os.WriteFile(path, []byte(b.String()), 0o644)
}

// WriteMergedTXT writes Comskip v2 frame cutlist for the master timeline.
func WriteMergedTXT(path string, breaks []CommercialBreak, fps, totalSec float64) error {
	if fps <= 0 {
		fps = 29.97
	}
	totalFrames := int(totalSec * fps)
	if totalFrames < 1 {
		totalFrames = 1
	}
	fpsX100 := int(fps * 100)
	var b strings.Builder
	b.WriteString(fmt.Sprintf("FILE PROCESSING COMPLETE %d FRAMES AT %d\n", totalFrames, fpsX100))
	b.WriteString("-------------\n")
	for _, br := range breaks {
		startF := int(br.StartSec * fps)
		endF := int(br.EndSec * fps)
		if endF <= startF {
			continue
		}
		b.WriteString(fmt.Sprintf("%d %d\n", startF, endF))
	}
	return os.WriteFile(path, []byte(b.String()), 0o644)
}

func masterEDL(outputPath string) string {
	return filepath.Join(ArtifactDir(outputPath), basenameStem(outputPath)+".edl")
}

func masterTXT(outputPath string) string {
	return filepath.Join(ArtifactDir(outputPath), basenameStem(outputPath)+".txt")
}

func masterChapters(outputPath string) string {
	return filepath.Join(ArtifactDir(outputPath), basenameStem(outputPath)+".chapters.ffmeta")
}

func masterManifest(outputPath string) string {
	return filepath.Join(ArtifactDir(outputPath), basenameStem(outputPath)+".comskip.json")
}

func sidecarsExist(outputPath string) bool {
	if fileSize(masterManifest(outputPath)) > 0 {
		return true
	}
	return fileSize(masterEDL(outputPath)) > 0
}

func breaksFromSidecars(edlPath, txtPath string, fps float64) ([]CommercialBreak, error) {
	if edlPath != "" && fileExists(edlPath) {
		return ParseEDL(edlPath)
	}
	if txtPath != "" && fileExists(txtPath) {
		return breaksFromTXT(txtPath, fps)
	}
	return nil, nil
}

func basenameStem(path string) string {
	return filepath.Base(stringsTrimSuffixExt(path))
}
