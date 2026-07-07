package comskip

import (
	"encoding/json"
	"fmt"
	"io"
	"os"
	"path/filepath"

	"iptv-dvr/internal/ffmpeg"
)

type manifestSegment struct {
	Index    int     `json:"index"`
	StartSec float64 `json:"start_sec"`
	EndSec   float64 `json:"end_sec"`
}

type manifest struct {
	Version         int               `json:"version"`
	Mode            string            `json:"mode"`
	FPS             float64           `json:"fps"`
	TotalSec        float64           `json:"total_sec"`
	CommercialCount int               `json:"commercial_count"`
	Segments        []manifestSegment `json:"segments"`
}

// MaybeRun executes Comskip post-processing when enabled.
func MaybeRun(
	outputPath string,
	enabled bool,
	jobDuration string,
	ffmpegPath string,
	explicitExe string,
	explicitIni string,
	log io.Writer,
) bool {
	if !enabled {
		return false
	}
	if !SupportedOutput(outputPath) {
		if log != nil {
			_, _ = fmt.Fprintln(log, "comskip: skipped (output is not .ts)")
		}
		return false
	}
	if !Available(explicitExe, explicitIni) {
		if log != nil {
			_, _ = fmt.Fprintln(log, "comskip: skipped (comskip.exe or comskip.ini not found)")
		}
		return false
	}
	if sidecarsExist(outputPath) {
		if log != nil {
			_, _ = fmt.Fprintln(log, "comskip: skipped (sidecars already exist)")
		}
		return false
	}

	workRoot := ""
	defer func() {
		if workRoot != "" {
			_ = os.RemoveAll(workRoot)
		}
	}()

	totalSec, ok := probeStreamDuration(ffmpegPath, outputPath, "v:0")
	if !ok || totalSec <= 0 {
		if log != nil {
			_, _ = fmt.Fprintln(log, "comskip: skipped (could not probe duration)")
		}
		return false
	}

	jobSec := 0
	if d, err := ffmpeg.ParseDuration(jobDuration); err == nil {
		jobSec = int(d.Seconds())
	}

	fps := probeVideoFPS(ffmpegPath, outputPath)
	segments := DetectEpisodeBoundaries(ffmpegPath, outputPath, jobSec, log)
	if len(segments) > 0 && segments[len(segments)-1].EndSec > 0 {
		if segments[len(segments)-1].EndSec > totalSec {
			totalSec = segments[len(segments)-1].EndSec
		}
	}
	if probed, ok := probeStreamDuration(ffmpegPath, outputPath, "v:0"); ok && probed > totalSec {
		totalSec = probed
	}

	ini := ResolveIni(explicitIni)
	mode := "whole_file"
	var breaks []CommercialBreak

	if len(segments) <= 1 {
		result, err := TryRun(outputPath, explicitExe, ini, log)
		if err != nil || !result.OK {
			if log != nil {
				_, _ = fmt.Fprintf(log, "comskip: run failed (exit %d)\n", result.ExitCode)
			}
			return false
		}
		breaks, _ = breaksFromSidecars(result.EDLPath, result.TXTPath, fps)
	} else {
		mode = "multi_episode"
		var err error
		workRoot, err = os.MkdirTemp("", "iptv_comskip_")
		if err != nil {
			if log != nil {
				_, _ = fmt.Fprintf(log, "comskip: temp work dir: %v\n", err)
			}
			return false
		}
		var mergeInputs []segmentSidecars
		stem := basenameStem(outputPath)
		for _, seg := range segments {
			segPath := filepath.Join(workRoot, fmt.Sprintf("%s_ep%d.ts", stem, seg.Index))
			if !extractSegment(ffmpegPath, outputPath, seg.StartSec, seg.EndSec, segPath, log) {
				if log != nil {
					_, _ = fmt.Fprintf(log, "comskip: segment extract failed for episode %d\n", seg.Index)
				}
				continue
			}
			result, err := TryRun(segPath, explicitExe, ini, log)
			if err != nil || !result.OK {
				if log != nil {
					_, _ = fmt.Fprintf(log, "comskip: segment %d failed (exit %d)\n", seg.Index, result.ExitCode)
				}
				continue
			}
			mergeInputs = append(mergeInputs, segmentSidecars{
				Segment: seg,
				EDL:     result.EDLPath,
				TXT:     result.TXTPath,
			})
		}
		if len(mergeInputs) == 0 {
			if log != nil {
				_, _ = fmt.Fprintln(log, "comskip: no segment produced commercial markers")
			}
			return false
		}
		breaks = MergeCommercialBreaks(mergeInputs, totalSec)
		_ = WriteMergedEDL(masterEDL(outputPath), breaks)
		_ = WriteMergedTXT(masterTXT(outputPath), breaks, fps, totalSec)
	}

	chaptersPath := masterChapters(outputPath)
	_ = WriteChaptersFFMeta(chaptersPath, basenameStem(outputPath), segments, breaks, totalSec)

	manifestPath := masterManifest(outputPath)
	segPayload := make([]manifestSegment, 0, len(segments))
	for _, seg := range segments {
		segPayload = append(segPayload, manifestSegment{
			Index:    seg.Index,
			StartSec: seg.StartSec,
			EndSec:   seg.EndSec,
		})
	}
	payload := manifest{
		Version:         1,
		Mode:            mode,
		FPS:             fps,
		TotalSec:        totalSec,
		CommercialCount: len(breaks),
		Segments:        segPayload,
	}
	if data, err := json.MarshalIndent(payload, "", "  "); err == nil {
		_ = os.WriteFile(manifestPath, data, 0o644)
	}

	if log != nil {
		_, _ = fmt.Fprintf(log, "comskip: wrote %d commercial markers (%s)\n", len(breaks), mode)
	}
	return true
}
