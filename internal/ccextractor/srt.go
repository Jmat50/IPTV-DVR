package ccextractor

import (
	"os"
	"path/filepath"
	"regexp"
	"strings"
)

var srtTimestampRE = regexp.MustCompile(`(?m)^\d{2}:\d{2}:\d{2},\d{3}\s+-->\s+\d{2}:\d{2}:\d{2},\d{3}`)

// SidecarSRTPath returns the .srt path beside a recording.
func SidecarSRTPath(outputPath string) string {
	ext := filepath.Ext(outputPath)
	if ext == "" {
		return outputPath + ".srt"
	}
	return strings.TrimSuffix(outputPath, ext) + ".srt"
}

// PartialSRTPath is the in-progress live worker output.
func PartialSRTPath(outputPath string) string {
	ext := filepath.Ext(outputPath)
	if ext == "" {
		return outputPath + ".srt.partial"
	}
	return strings.TrimSuffix(outputPath, ext) + ".srt.partial"
}

// ValidateSRT reports whether path looks like a non-empty SubRip file.
func ValidateSRT(path string) bool {
	data, err := os.ReadFile(path)
	if err != nil || len(data) < 4 {
		return false
	}
	text := string(data)
	if !strings.Contains(text, "-->") {
		return false
	}
	return srtTimestampRE.MatchString(text)
}

// FinalizePartial atomically promotes a validated partial SRT to the final sidecar.
func FinalizePartial(partial, final string) bool {
	if !ValidateSRT(partial) {
		return false
	}
	if err := os.Rename(partial, final); err != nil {
		_ = os.Remove(final)
		if err2 := os.Rename(partial, final); err2 != nil {
			return false
		}
	}
	return ValidateSRT(final)
}
