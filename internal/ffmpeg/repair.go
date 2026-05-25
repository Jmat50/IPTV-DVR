package ffmpeg

import (
	"bytes"
	"io"
	"os"
	"os/exec"
	"path/filepath"
	"strings"
)

// TryRepairTSFile remuxes a TS into a temporary file and atomically replaces it.
// This helps strict players decode recordings from non-graceful stops.
func TryRepairTSFile(ffmpegPath, outputPath string, stderr io.Writer) bool {
	if strings.ToLower(filepath.Ext(outputPath)) != ".ts" {
		return false
	}
	st, err := os.Stat(outputPath)
	if err != nil || st.Size() <= 0 {
		return false
	}
	exe := ffmpegPath
	if strings.TrimSpace(exe) == "" {
		exe = "ffmpeg"
	}

	repaired := outputPath + ".repair.tmp.ts"
	_ = os.Remove(repaired)
	bsf := ""
	if rate := probeVideoFrameRate(ffmpegPath, outputPath); rate != "" {
		bsf = "setts=pts=N/(" + rate + "*TB):dts=N/(" + rate + "*TB)"
	}
	cmd := exec.Command(
		exe,
		"-hide_banner",
		"-loglevel", "warning",
		"-fflags", "+genpts+discardcorrupt",
		"-err_detect", "ignore_err",
		"-avoid_negative_ts", "make_zero",
		"-i", outputPath,
		"-map", "0",
		"-c", "copy",
	)
	if bsf != "" {
		cmd.Args = append(cmd.Args, "-bsf:v", bsf)
	}
	cmd.Args = append(cmd.Args,
		"-y",
		repaired,
	)
	cmd.Stdout = io.Discard
	cmd.Stderr = stderr
	if err := cmd.Run(); err != nil {
		_ = os.Remove(repaired)
		return false
	}
	if rst, err := os.Stat(repaired); err != nil || rst.Size() <= 0 {
		_ = os.Remove(repaired)
		return false
	}
	if err := os.Rename(repaired, outputPath); err != nil {
		_ = os.Remove(repaired)
		return false
	}
	return true
}

func ffprobeFromFFmpeg(ffmpegPath string) string {
	if strings.TrimSpace(ffmpegPath) == "" {
		return "ffprobe"
	}
	return filepath.Join(filepath.Dir(ffmpegPath), "ffprobe"+filepath.Ext(ffmpegPath))
}

func probeVideoFrameRate(ffmpegPath, mediaPath string) string {
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
		return ""
	}
	for _, raw := range strings.Split(out.String(), "\n") {
		rate := strings.TrimSpace(raw)
		if rate == "" || rate == "0/0" {
			continue
		}
		return rate
	}
	return ""
}
