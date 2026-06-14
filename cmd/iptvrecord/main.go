package main

import (
	"errors"
	"flag"
	"fmt"
	"os"
	"os/exec"
	"path/filepath"
	"strings"
	"time"

	"iptv-dvr/internal/ccextractor"
	"iptv-dvr/internal/ffmpeg"
	"iptv-dvr/internal/m3u"
	"iptv-dvr/internal/winffmpeg"
	"iptv-dvr/internal/winschedule"
)

const version = "0.1.0"

func main() {
	if len(os.Args) < 2 {
		usage()
		os.Exit(2)
	}
	switch os.Args[1] {
	case "list-channels":
		cmdListChannels(os.Args[2:])
	case "record":
		if err := runRecord(os.Args[2:]); err != nil {
			die(err)
		}
	case "schedule":
		if err := runSchedule(os.Args[2:]); err != nil {
			die(err)
		}
	case "version", "-version", "--version", "-v":
		fmt.Println("iptvrecord", version)
	default:
		fmt.Fprintf(os.Stderr, "unknown command %q\n\n", os.Args[1])
		usage()
		os.Exit(2)
	}
}

func usage() {
	fmt.Fprintf(os.Stderr, `iptvrecord %s — record IPTV streams (FFmpeg stream copy).

Commands:
  list-channels  --m3u <file|url>
  record         (--m3u <file|url> --channel <name>)  OR  --url <stream-url>
                 --duration <e.g. 90m, 1h30m, 3600> --out <path.ts>
                 [--ffmpeg <path\to\ffmpeg.exe>] [--user-agent ...] [--referer ...]
                 [--captions] [--caption-mode off|post_only|live_ccextractor]
                 [--post-scan-repair]
                 [--caption-post-processor ffmpeg|ccextractor]
  schedule       --at <RFC3339>  (same flags as record)
                 [--task-name <name>]
  version

Examples:
  iptvrecord list-channels --m3u C:\iptv\playlist.m3u
  iptvrecord record --m3u C:\iptv\playlist.m3u --channel "BBC One" --duration 90m --out D:\rec.ts
  iptvrecord schedule --at 2026-05-02T20:00:00-05:00 --m3u C:\iptv\playlist.m3u --channel "BBC One" --duration 90m --out D:\rec.ts

Requires FFmpeg on PATH or --ffmpeg. Output uses -c copy (low CPU/RAM). Prefer .ts container.
`, version)
}

func cmdListChannels(args []string) {
	fs := flag.NewFlagSet("list-channels", flag.ExitOnError)
	m3uPath := fs.String("m3u", "", "path or URL to M3U playlist")
	fs.Usage = func() {
		fmt.Fprintf(os.Stderr, "usage: iptvrecord list-channels --m3u <file|url>\n")
		fs.PrintDefaults()
	}
	_ = fs.Parse(args)
	if *m3uPath == "" {
		fs.Usage()
		os.Exit(2)
	}
	channels, err := m3u.Load(*m3uPath)
	if err != nil {
		die(err)
	}
	for i, c := range channels {
		fmt.Printf("%5d  %s\n", i+1, c.Name)
	}
	fmt.Printf("\n%d channels\n", len(channels))
}

type recordOpts struct {
	m3uPath              string
	channel              string
	streamURL            string
	duration             string
	out                  string
	ffmpegPath           string
	userAgent            string
	referer              string
	scheduledStart       string
	captions             bool
	captionMode          string
	captionPostProcessor string
	postScanRepair       bool
	ccExtractor          string
}

func parseRecordFlags(fs *flag.FlagSet, args []string) recordOpts {
	var o recordOpts
	fs.StringVar(&o.m3uPath, "m3u", "", "path or URL to M3U playlist")
	fs.StringVar(&o.channel, "channel", "", "channel name (from M3U)")
	fs.StringVar(&o.streamURL, "url", "", "direct stream URL (skip M3U)")
	fs.StringVar(&o.duration, "duration", "", "recording length: 3600, 90m, 1h30m, 45s")
	fs.StringVar(&o.out, "out", "", "output file path (.ts recommended)")
	fs.StringVar(&o.ffmpegPath, "ffmpeg", "", "path to ffmpeg.exe (default: ffmpeg on PATH)")
	fs.StringVar(&o.userAgent, "user-agent", "", "override User-Agent")
	fs.StringVar(&o.referer, "referer", "", "override Referer header")
	fs.StringVar(&o.scheduledStart, "scheduled-start", "", "internal: planned schedule start time")
	fs.BoolVar(&o.captions, "captions", false, "enable closed captions (same as --caption-mode post_only)")
	fs.StringVar(&o.captionMode, "caption-mode", "", "off | post_only | live_ccextractor")
	fs.StringVar(&o.captionPostProcessor, "caption-post-processor", "ffmpeg", "ffmpeg | ccextractor (used for post-record extraction in post_only)")
	fs.BoolVar(&o.postScanRepair, "post-scan-repair", false, "after record, scan finished .ts for stream errors and repair when needed")
	fs.StringVar(&o.ccExtractor, "ccextractor", "", "path to ccextractor.exe (optional; bundled tools/ used when present)")
	_ = fs.Parse(args)
	return o
}

func captionModeForRecord(o recordOpts) ccextractor.Mode {
	return ccextractor.MigrateMode(o.captionMode, o.captions)
}

func validateRecord(o recordOpts) error {
	if o.duration == "" || o.out == "" {
		return fmt.Errorf("--duration and --out are required")
	}
	if o.streamURL != "" {
		return nil
	}
	if o.m3uPath == "" || o.channel == "" {
		return fmt.Errorf("either --url or both --m3u and --channel are required")
	}
	return nil
}

func resolveStream(o recordOpts) (inputURL, ua, ref string, err error) {
	if o.streamURL != "" {
		return o.streamURL, o.userAgent, o.referer, nil
	}
	channels, err := m3u.Load(o.m3uPath)
	if err != nil {
		return "", "", "", err
	}
	ch, err := m3u.FindChannel(channels, o.channel)
	if err != nil {
		return "", "", "", err
	}
	ua, ref = ch.UserAgent, ch.Referer
	if o.userAgent != "" {
		ua = o.userAgent
	}
	if o.referer != "" {
		ref = o.referer
	}
	return ch.URL, ua, ref, nil
}

func runRecord(args []string) error {
	fs := flag.NewFlagSet("record", flag.ExitOnError)
	fs.Usage = func() {
		fmt.Fprintf(os.Stderr, "usage: iptvrecord record --m3u ... --channel ... --duration ... --out ...\n")
		fs.PrintDefaults()
	}
	o := parseRecordFlags(fs, args)
	if err := validateRecord(o); err != nil {
		fs.Usage()
		return err
	}
	dur, err := ffmpeg.ParseDuration(o.duration)
	if err != nil {
		return fmt.Errorf("duration: %w", err)
	}
	if o.scheduledStart != "" {
		scheduledStart, err := time.Parse(time.RFC3339, o.scheduledStart)
		if err != nil {
			return fmt.Errorf("--scheduled-start: %w", err)
		}
		windowEnd := scheduledStart.Add(dur)
		jitter := 8 * time.Second
		now := time.Now()
		if now.Before(scheduledStart.Add(-jitter)) {
			wait := time.Until(scheduledStart)
			if wait > 0 {
				fmt.Fprintf(os.Stderr, "scheduled run arrived early; waiting %.1fs until start\n", wait.Seconds())
				time.Sleep(wait)
			}
			now = time.Now()
		}
		if now.After(windowEnd.Add(jitter)) {
			fmt.Fprintf(
				os.Stderr,
				"skipping run: recording window already ended (start=%s end=%s now=%s)\n",
				scheduledStart.Format(time.RFC3339),
				windowEnd.Format(time.RFC3339),
				now.Format(time.RFC3339),
			)
			return nil
		}
		if now.After(scheduledStart.Add(jitter)) {
			remaining := windowEnd.Sub(now)
			if remaining <= 0 {
				fmt.Fprintln(os.Stderr, "skipping run: no remaining duration in scheduled window")
				return nil
			}
			dur = remaining
			fmt.Fprintf(
				os.Stderr,
				"late start detected; recording remaining %.0fs (window end %s)\n",
				dur.Seconds(),
				windowEnd.Format(time.RFC3339),
			)
		} else {
			fmt.Fprintf(os.Stderr, "on-time scheduled start; recording full configured duration (%s)\n", o.duration)
		}
	}
	inputURL, ua, ref, err := resolveStream(o)
	if err != nil {
		return err
	}
	ff := o.ffmpegPath
	if ff == "" {
		ff = "ffmpeg"
	}
	mode := captionModeForRecord(o)
	postProcessor := ccextractor.ResolvePostProcessorForMode(mode, o.captionPostProcessor)
	ccExe := ccextractor.ResolveExe(o.ccExtractor)
	ffprobe := ffprobeFromFFmpeg(ff)
	captionsPath := ""
	if ccextractor.CaptionsEnabled(mode) && ffmpeg.ProbeURLHasSubtitles(ffprobe, inputURL, ua, ref) {
		captionsPath = ffmpeg.CaptionsSidecarPath(o.out)
	}
	argv, err := ffmpeg.BuildArgv(ffmpeg.Args{
		FFmpegPath:   ff,
		InputURL:     inputURL,
		OutputPath:   o.out,
		CaptionsPath: captionsPath,
		Duration:     dur,
		UserAgent:    ua,
		Referer:      ref,
	})
	if err != nil {
		return err
	}
	fmt.Fprintf(os.Stderr, "running: %s %s\n", argv[0], strings.Join(argv[1:], " "))

	var worker *ccextractor.Worker
	if ccextractor.UseLiveCCExtractor(mode, o.out, ccExe) {
		// Ensure live extractor follows this run's file, not stale content.
		if mkErr := os.MkdirAll(filepath.Dir(o.out), 0o755); mkErr == nil {
			_ = os.WriteFile(o.out, []byte{}, 0o644)
		}
		worker = ccextractor.NewWorker(o.out, ccExe, os.Stderr)
		if startErr := worker.Start(); startErr != nil {
			fmt.Fprintf(os.Stderr, "captions: live worker start failed: %v\n", startErr)
			worker = nil
		}
	}

	if err := winffmpeg.Run(argv); err != nil {
		// If ffmpeg failed before writing payload, remove empty placeholder output.
		outSize := int64(0)
		if st, statErr := os.Stat(o.out); statErr == nil {
			outSize = st.Size()
			if outSize == 0 {
				_ = os.Remove(o.out)
			}
		}
		// If ffmpeg wrote bytes but exited non-zero (manual close / stream break),
		// normalize the partial TS so strict players can still open it.
		if outSize > 0 {
			if !ffmpeg.MaybePostScanRepair(ff, o.out, os.Stderr, o.postScanRepair, true) && o.postScanRepair {
				fmt.Fprintln(os.Stderr, "captions: post scan repair was attempted but not applied")
			}
		}
		// If partial recording exists and captions were enabled, still try caption finalize.
		mode := captionModeForRecord(o)
		if outSize > 0 && ccextractor.CaptionsEnabled(mode) {
			ffprobe := ffprobeFromFFmpeg(ff)
			_, _ = ffmpeg.FinalizeCaptions(ff, ffprobe, o.out, mode, postProcessor, ccExe, false, os.Stderr)
		}
		if outSize > 0 && isManualStopErr(err) {
			fmt.Fprintln(os.Stderr, "ffmpeg stopped by user; keeping partial recording")
			return nil
		}
		return err
	}

	liveOK := false
	if worker != nil {
		var stopErr error
		liveOK, stopErr = worker.Stop()
		if !liveOK && stopErr != nil {
			fmt.Fprintf(os.Stderr, "captions: live worker stop: %v\n", stopErr)
		}
	}

	if st, err := os.Stat(o.out); err == nil && st.Size() > 0 {
		ffmpeg.MaybePostScanRepair(ff, o.out, os.Stderr, o.postScanRepair, false)
	}

	if !ccextractor.CaptionsEnabled(mode) {
		return nil
	}
	if ffmpeg.SidecarHasContent(captionsPath) || ffmpeg.AnyCaptionSidecar(o.out) {
		return nil
	}
	ok, extractErr := ffmpeg.FinalizeCaptions(ff, ffprobe, o.out, mode, postProcessor, ccExe, liveOK, os.Stderr)
	if extractErr != nil {
		fmt.Fprintf(os.Stderr, "caption extract: %v\n", extractErr)
	} else if !ok {
		fmt.Fprintln(os.Stderr, "captions: none found in stream or recording")
	}
	return nil
}

func ffprobeFromFFmpeg(ffmpegPath string) string {
	if ffmpegPath == "" {
		return "ffprobe"
	}
	return filepath.Join(filepath.Dir(ffmpegPath), "ffprobe"+filepath.Ext(ffmpegPath))
}

func isManualStopErr(err error) bool {
	var exitErr *exec.ExitError
	if !errors.As(err, &exitErr) {
		return false
	}
	code := exitErr.ExitCode()
	return code == 130 || code == -1073741510 || code == 3221225786
}

func runSchedule(args []string) error {
	atStr, taskName, recArgs, err := splitScheduleArgs(args)
	if err != nil {
		return err
	}
	if atStr == "" {
		fmt.Fprintf(os.Stderr, "usage: iptvrecord schedule --at <RFC3339> [same flags as record]\n")
		return fmt.Errorf("--at is required")
	}
	runAt, err := time.Parse(time.RFC3339, atStr)
	if err != nil {
		runAt, err = time.ParseInLocation("2006-01-02T15:04:05", atStr, time.Local)
		if err != nil {
			return fmt.Errorf("--at: parse RFC3339 or 2006-01-02T15:04:05 (local): %w", err)
		}
	}
	if runAt.Before(time.Now().Add(-5 * time.Second)) {
		return fmt.Errorf("--at must be in the future (got %s)", runAt.Format(time.RFC3339))
	}

	rfs := flag.NewFlagSet("record", flag.ExitOnError)
	o := parseRecordFlags(rfs, recArgs)
	if err := validateRecord(o); err != nil {
		fmt.Fprintf(os.Stderr, "usage: iptvrecord schedule --at <time> --m3u ... --channel ... --duration ... --out ...\n")
		return err
	}

	exe, err := os.Executable()
	if err != nil {
		return err
	}
	exe, err = filepath.Abs(exe)
	if err != nil {
		return err
	}

	argLine := buildScheduledRecordArgLine(recArgs, runAt)
	tname := taskName
	if tname == "" {
		tname = winschedule.DefaultTaskName(o.channel, runAt)
	}
	fmt.Fprintf(os.Stderr, "registering task %q at %s (local)\n", tname, runAt.Format(time.RFC3339))
	return winschedule.CreateOnceTask(tname, exe, argLine, runAt)
}

// splitScheduleArgs pulls --at / --task-name then returns the rest for record flag parsing.
func splitScheduleArgs(args []string) (at, taskName string, recArgs []string, err error) {
	for i := 0; i < len(args); i++ {
		a := args[i]
		switch {
		case a == "--at":
			if i+1 >= len(args) {
				return "", "", nil, fmt.Errorf("--at needs a value")
			}
			i++
			at = args[i]
		case a == "--task-name":
			if i+1 >= len(args) {
				return "", "", nil, fmt.Errorf("--task-name needs a value")
			}
			i++
			taskName = args[i]
		case strings.HasPrefix(a, "--at="):
			at = strings.TrimPrefix(a, "--at=")
		case strings.HasPrefix(a, "--task-name="):
			taskName = strings.TrimPrefix(a, "--task-name=")
		default:
			recArgs = append(recArgs, a)
		}
	}
	return at, taskName, recArgs, nil
}

// buildScheduledRecordArgLine builds the argument string for the scheduled task.
func buildScheduledRecordArgLine(recArgs []string, runAt time.Time) string {
	parts := append([]string{"record"}, recArgs...)
	parts = append(parts, "--scheduled-start", runAt.Format(time.RFC3339))
	return strings.Join(quoteArgsForTask(parts), " ")
}

func quoteArgsForTask(args []string) []string {
	out := make([]string, len(args))
	for i, a := range args {
		if strings.ContainsAny(a, " \t\"") {
			s := strings.ReplaceAll(a, `\`, `\\`)
			s = strings.ReplaceAll(s, `"`, `\"`)
			out[i] = `"` + s + `"`
		} else {
			out[i] = a
		}
	}
	return out
}

func die(err error) {
	fmt.Fprintf(os.Stderr, "error: %v\n", err)
	os.Exit(1)
}
