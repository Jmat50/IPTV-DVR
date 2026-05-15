package main

import (
	"flag"
	"fmt"
	"os"
	"os/exec"
	"path/filepath"
	"strings"
	"time"

	"iptv-dvr/internal/ffmpeg"
	"iptv-dvr/internal/m3u"
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
                 [--captions]
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
	m3uPath        string
	channel        string
	streamURL      string
	duration       string
	out            string
	ffmpegPath     string
	userAgent      string
	referer        string
	scheduledStart string
	captions       bool
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
	fs.BoolVar(&o.captions, "captions", false, "download closed captions to a .vtt sidecar when available")
	_ = fs.Parse(args)
	return o
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
	captionsPath := ""
	if o.captions {
		ffprobe := ffprobeFromFFmpeg(ff)
		if ffmpeg.ProbeURLHasSubtitles(ffprobe, inputURL, ua, ref) {
			captionsPath = ffmpeg.CaptionsSidecarPath(o.out)
		}
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
	cmd := exec.Command(argv[0], argv[1:]...)
	cmd.Stdin = os.Stdin
	cmd.Stdout = os.Stdout
	cmd.Stderr = os.Stderr
	fmt.Fprintf(os.Stderr, "running: %s %s\n", argv[0], strings.Join(argv[1:], " "))
	if err := cmd.Run(); err != nil {
		return err
	}
	if o.captions {
		ffprobe := ffprobeFromFFmpeg(ff)
		if ffmpeg.SidecarHasContent(captionsPath) || ffmpeg.AnyCaptionSidecar(o.out) {
			return nil
		}
		if strings.EqualFold(filepath.Ext(o.out), ".ts") {
			ok, extractErr := ffmpeg.TryExtractCaptionsFromTS(ff, ffprobe, o.out)
			if extractErr != nil {
				fmt.Fprintf(os.Stderr, "caption extract: %v\n", extractErr)
			} else if !ok {
				fmt.Fprintln(os.Stderr, "captions: none found in stream or recording")
			}
		} else if captionsPath != "" {
			fmt.Fprintln(os.Stderr, "captions: none found in stream or recording")
		}
	}
	return nil
}

func ffprobeFromFFmpeg(ffmpegPath string) string {
	if ffmpegPath == "" {
		return "ffprobe"
	}
	return filepath.Join(filepath.Dir(ffmpegPath), "ffprobe"+filepath.Ext(ffmpegPath))
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
