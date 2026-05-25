package ffmpeg

import (
	"fmt"
	"os"
	"os/exec"
	"path/filepath"
	"strings"

	"iptv-dvr/internal/winffmpeg"
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
	candidates := []string{
		base + ".vtt",
		base + ".ass",
		base + ".srt",   // legacy naming
		outputPath + ".srt", // current naming
	}
	for _, p := range candidates {
		if SidecarHasContent(p) {
			return true
		}
	}
	return false
}

// ProbeURLHasSubtitles reports whether a live input URL exposes subtitle streams.
func ProbeURLHasSubtitles(ffprobePath, inputURL, userAgent, referer string) bool {
	if ffprobePath == "" {
		ffprobePath = "ffprobe"
	}
	args := []string{
		"-v", "error",
		"-select_streams", "s",
		"-show_entries", "stream=index",
		"-of", "csv=p=0",
	}
	if userAgent != "" {
		args = append([]string{"-user_agent", userAgent}, args...)
	}
	if referer != "" {
		args = append([]string{"-headers", fmt.Sprintf("Referer: %s\r\n", referer)}, args...)
	}
	args = append(args, inputURL)
	cmd := exec.Command(ffprobePath, args...)
	out, err := cmd.Output()
	if err != nil {
		return false
	}
	return strings.TrimSpace(string(out)) != ""
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
	if err := winffmpeg.Run(argv); err != nil {
		return false, err
	}
	outPath := argv[len(argv)-1]
	return SidecarHasContent(outPath), nil
}

// Embedded608SidecarPath returns the .srt path alongside a recording (broadcast CC in H.264).
func Embedded608SidecarPath(outputPath string) string {
	ext := filepath.Ext(outputPath)
	if ext == "" {
		return outputPath + ".srt"
	}
	return strings.TrimSuffix(outputPath, ext) + ".srt"
}

func movieBasenameForLavfi(name string) string {
	return strings.ReplaceAll(name, "'", `\'`)
}

// BuildExtractEmbedded608Argv builds ffmpeg argv to extract ATSC/EIA-608 from H.264 in a .ts file.
// Run with working directory set to the recording's parent and basenames in argv (lavfi movie= parsing).
func BuildExtractEmbedded608Argv(ffmpegPath, tsPath string) ([]string, string, error) {
	if tsPath == "" {
		return nil, "", fmt.Errorf("missing input path")
	}
	exe := ffmpegPath
	if exe == "" {
		exe = "ffmpeg"
	}
	dir := filepath.Dir(tsPath)
	base := filepath.Base(tsPath)
	ext := filepath.Ext(base)
	outBase := strings.TrimSuffix(base, ext) + ".srt"
	lavfi := fmt.Sprintf("movie='%s'[out+subcc]", movieBasenameForLavfi(base))
	argv := []string{
		exe,
		"-hide_banner",
		"-loglevel", "warning",
		"-f", "lavfi",
		"-i", lavfi,
		"-map", "s",
		"-c:s", "srt",
		"-y",
		outBase,
	}
	return argv, dir, nil
}

// TryExtractEmbedded608FromTS extracts CEA-608 carried in the video elementary stream to .srt.
func TryExtractEmbedded608FromTS(ffmpegPath, tsPath string) (bool, error) {
	if !strings.EqualFold(filepath.Ext(tsPath), ".ts") {
		return false, nil
	}
	if SidecarHasContent(Embedded608SidecarPath(tsPath)) {
		return true, nil
	}
	argv, dir, err := BuildExtractEmbedded608Argv(ffmpegPath, tsPath)
	if err != nil {
		return false, err
	}
	if err := winffmpeg.RunInDir(dir, argv); err != nil {
		return false, err
	}
	return SidecarHasContent(Embedded608SidecarPath(tsPath)), nil
}

// PostExtractCaptions runs after a successful .ts record when --captions is enabled.
func PostExtractCaptions(ffmpegPath, ffprobePath, outputPath string) (bool, error) {
	if AnyCaptionSidecar(outputPath) {
		return true, nil
	}
	if !strings.EqualFold(filepath.Ext(outputPath), ".ts") {
		return false, nil
	}
	ok, err := TryExtractCaptionsFromTS(ffmpegPath, ffprobePath, outputPath)
	if err != nil {
		return false, err
	}
	if ok {
		return true, nil
	}
	return TryExtractEmbedded608FromTS(ffmpegPath, outputPath)
}
