package ffmpeg

import (
	"fmt"
	"os"
	"os/exec"
	"path/filepath"
	"strings"
)

// CaptionsSidecarPath returns the .vtt path alongside a recording file.
func CaptionsSidecarPath(outputPath string) string {
	ext := filepath.Ext(outputPath)
	if ext == "" {
		return outputPath + ".vtt"
	}
	return strings.TrimSuffix(outputPath, ext) + ".vtt"
}

// SidecarHasContent reports whether path exists and is non-empty.
func SidecarHasContent(path string) bool {
	st, err := os.Stat(path)
	if err != nil {
		return false
	}
	return st.Size() > 0
}

// AnyCaptionSidecar reports whether a .vtt, .srt, or .ass file exists beside outputPath.
func AnyCaptionSidecar(outputPath string) bool {
	ext := filepath.Ext(outputPath)
	base := strings.TrimSuffix(outputPath, ext)
	for _, sfx := range []string{".vtt", ".srt", ".ass"} {
		if SidecarHasContent(base + sfx) {
			return true
		}
	}
	return false
}

// ProbeSubtitleCodec returns the codec_name of the first subtitle stream in path, or "".
func ProbeSubtitleCodec(ffprobePath, mediaPath string) (string, error) {
	if ffprobePath == "" {
		ffprobePath = "ffprobe"
	}
	cmd := exec.Command(ffprobePath,
		"-v", "error",
		"-select_streams", "s:0",
		"-show_entries", "stream=codec_name",
		"-of", "default=noprint_wrappers=1:nokey=1",
		mediaPath,
	)
	out, err := cmd.Output()
	if err != nil {
		return "", nil
	}
	return strings.TrimSpace(string(out)), nil
}

func captionExtForCodec(codec string) string {
	switch strings.ToLower(codec) {
	case "webvtt":
		return ".vtt"
	case "subrip":
		return ".srt"
	case "ass":
		return ".ass"
	default:
		if codec != "" {
			return ".srt"
		}
		return ".vtt"
	}
}

// BuildExtractArgv builds ffmpeg argv to extract the first subtitle from a finished file.
func BuildExtractArgv(ffmpegPath, inputPath, codec string) ([]string, error) {
	if inputPath == "" {
		return nil, fmt.Errorf("missing input path")
	}
	exe := ffmpegPath
	if exe == "" {
		exe = "ffmpeg"
	}
	ext := captionExtForCodec(codec)
	outPath := strings.TrimSuffix(inputPath, filepath.Ext(inputPath)) + ext
	return []string{
		exe,
		"-hide_banner",
		"-loglevel", "warning",
		"-i", inputPath,
		"-map", "0:s:0?",
		"-c", "copy",
		"-y",
		outPath,
	}, nil
}

// TryExtractCaptionsFromTS probes a .ts file and extracts embedded subtitles when present.
func TryExtractCaptionsFromTS(ffmpegPath, ffprobePath, tsPath string) (bool, error) {
	codec, err := ProbeSubtitleCodec(ffprobePath, tsPath)
	if err != nil {
		return false, err
	}
	if codec == "" {
		return false, nil
	}
	argv, err := BuildExtractArgv(ffmpegPath, tsPath, codec)
	if err != nil {
		return false, err
	}
	cmd := exec.Command(argv[0], argv[1:]...)
	if err := cmd.Run(); err != nil {
		return false, err
	}
	outPath := argv[len(argv)-1]
	return SidecarHasContent(outPath), nil
}
