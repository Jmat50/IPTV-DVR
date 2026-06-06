package ccextractor

import (
	"os/exec"
	"path/filepath"
	"strings"
)

// Mode selects how captions are produced.
type Mode string

const (
	ModeOff             Mode = "off"
	ModePostOnly        Mode = "post_only"
	ModeLiveCCExtractor Mode = "live_ccextractor"
	ModeAuto            Mode = "auto"
)

// PostProcessor selects which tool handles post-record caption extraction.
type PostProcessor string

const (
	PostProcessorFFmpeg      PostProcessor = "ffmpeg"
	PostProcessorCCExtractor PostProcessor = "ccextractor"
)

// NormalizeMode maps CLI/config strings to a known mode.
func NormalizeMode(raw string) Mode {
	switch strings.ToLower(strings.TrimSpace(raw)) {
	case "", "off", "none":
		return ModeOff
	case "post", "post_only":
		return ModePostOnly
	case "live", "live_ccextractor", "ccextractor":
		return ModeLiveCCExtractor
	case "auto":
		return ModeAuto
	default:
		return ModeOff
	}
}

// MigrateMode applies legacy --captions when caption-mode is unset.
func MigrateMode(captionMode string, captionsFlag bool) Mode {
	if strings.TrimSpace(captionMode) != "" {
		m := NormalizeMode(captionMode)
		if m != ModeOff || strings.EqualFold(captionMode, "off") {
			return m
		}
	}
	if captionsFlag {
		return ModePostOnly
	}
	return ModeOff
}

// CaptionsEnabled reports whether any caption work should run.
func CaptionsEnabled(m Mode) bool {
	return m != ModeOff
}

// Available reports whether a CCExtractor binary can be launched.
func Available(exePath string) bool {
	return fileExists(ResolveExe(exePath))
}

// ResolveEffectiveMode picks the runtime mode for a given output file.
func ResolveEffectiveMode(m Mode, outputPath, ccExe string) Mode {
	switch m {
	case ModeAuto:
		return ModePostOnly
	case ModeLiveCCExtractor:
		if strings.EqualFold(filepath.Ext(outputPath), ".ts") && Available(ccExe) {
			if ok, _ := LiveSupported(ccExe); ok {
				return ModeLiveCCExtractor
			}
		}
		return ModePostOnly
	default:
		return m
	}
}

// UseLiveCCExtractor reports whether the live sidecar worker should run.
func UseLiveCCExtractor(m Mode, outputPath, ccExe string) bool {
	return ResolveEffectiveMode(m, outputPath, ccExe) == ModeLiveCCExtractor
}

// NormalizePostProcessor maps CLI/config strings to a known post processor.
func NormalizePostProcessor(raw string) PostProcessor {
	switch strings.ToLower(strings.TrimSpace(raw)) {
	case "ccextractor", "cc":
		return PostProcessorCCExtractor
	default:
		return PostProcessorFFmpeg
	}
}

// ModeAllowsPostProcessor reports whether the UI/CLI selector should apply for a mode.
func ModeAllowsPostProcessor(m Mode) bool {
	return m == ModeAuto || m == ModePostOnly
}

// ResolvePostProcessorForMode applies selector gating based on caption mode.
func ResolvePostProcessorForMode(m Mode, requested string) PostProcessor {
	if !ModeAllowsPostProcessor(m) {
		return PostProcessorFFmpeg
	}
	return NormalizePostProcessor(requested)
}

func execLookPath(name string) (string, error) {
	return exec.LookPath(name)
}
