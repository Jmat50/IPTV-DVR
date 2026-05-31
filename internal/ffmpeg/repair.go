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
	rate := probeVideoFrameRate(ffmpegPath, outputPath)
	for _, useSetTS := range []bool{true, false} {
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
		if useSetTS && rate != "" {
			bsf := "setts=pts=N/(" + rate + "*TB):dts=N/(" + rate + "*TB)"
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
			continue
		}
		if rst, err := os.Stat(repaired); err != nil || rst.Size() <= 0 {
			_ = os.Remove(repaired)
			continue
		}
		if err := os.Rename(repaired, outputPath); err != nil {
			_ = os.Remove(repaired)
			continue
		}
		if validateRepairedTS(exe, outputPath, stderr) {
			return true
		}
		if stderr != nil {
			mode := "plain-remux"
			if useSetTS {
				mode = "setts"
			}
			_, _ = io.WriteString(stderr, "captions: TS repair validation failed after "+mode+", trying fallback\n")
		}
	}
	return false
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

func validateRepairedTS(ffmpegPath, mediaPath string, stderr io.Writer) bool {
	cmd := exec.Command(
		ffmpegPath,
		"-hide_banner",
		"-v", "warning",
		"-i", mediaPath,
		"-map", "0",
		"-t", "20",
		"-f", "null",
		"-",
	)
	cmd.Stdout = io.Discard
	var errBuf bytes.Buffer
	cmd.Stderr = &errBuf
	if err := cmd.Run(); err != nil {
		if stderr != nil {
			_, _ = stderr.Write(errBuf.Bytes())
		}
		return false
	}
	out := strings.ToLower(errBuf.String())
	if stderr != nil && strings.TrimSpace(out) != "" {
		_, _ = io.WriteString(stderr, out+"\n")
	}
	if strings.Contains(out, "non-monoton") ||
		strings.Contains(out, "invalid dts") ||
		strings.Contains(out, "error while decoding") ||
		strings.Contains(out, "packet corrupt") {
		return false
	}
	return true
}
