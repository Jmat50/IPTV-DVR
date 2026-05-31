package ffmpeg

import (
	"fmt"
	"io"

	"iptv-dvr/internal/ccextractor"
)

// FinalizeCaptions runs post-extract when captions are enabled and no sidecar exists.
// liveOK indicates the live CCExtractor worker already produced a valid .srt.
func FinalizeCaptions(
	ffmpegPath,
	ffprobePath,
	outputPath string,
	mode ccextractor.Mode,
	postProcessor ccextractor.PostProcessor,
	ccExe string,
	liveOK bool,
	log io.Writer,
) (bool, error) {
	if !ccextractor.CaptionsEnabled(mode) {
		return false, nil
	}
	if AnyCaptionSidecar(outputPath) {
		return true, nil
	}
	if liveOK {
		return true, nil
	}
	effective := ccextractor.ResolveEffectiveMode(mode, outputPath, ccExe)
	if effective == ccextractor.ModePostOnly || effective == ccextractor.ModeLiveCCExtractor {
		ok, err := PostExtractCaptions(ffmpegPath, ffprobePath, outputPath, postProcessor, ccExe, log)
		if err != nil && log != nil {
			_, _ = fmt.Fprintf(log, "caption extract: %v\n", err)
		}
		return ok, err
	}
	return false, nil
}
