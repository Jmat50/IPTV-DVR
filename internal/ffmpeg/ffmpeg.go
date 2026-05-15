package ffmpeg

import (
	"fmt"
	"strconv"
	"strings"
	"time"
)

// Args holds inputs for building an ffmpeg stream-copy record command.
type Args struct {
	FFmpegPath   string
	InputURL     string
	OutputPath   string
	CaptionsPath string // optional sidecar .vtt (empty = no caption output)
	Duration     time.Duration
	UserAgent    string
	Referer      string
}

// BuildArgv returns a full argv slice: [ffmpegExe, flags...] for exec.Command(argv[0], argv[1:]...).
func BuildArgv(a Args) ([]string, error) {
	if a.InputURL == "" {
		return nil, fmt.Errorf("missing input URL")
	}
	if a.OutputPath == "" {
		return nil, fmt.Errorf("missing output path")
	}
	if a.Duration <= 0 {
		return nil, fmt.Errorf("duration must be positive")
	}
	exe := a.FFmpegPath
	if exe == "" {
		exe = "ffmpeg"
	}
	sec := int(a.Duration.Round(time.Second) / time.Second)
	if sec < 1 {
		sec = 1
	}

	out := []string{
		exe,
		"-hide_banner",
		"-loglevel", "warning",
		"-reconnect", "1",
		"-reconnect_streamed", "1",
		"-reconnect_at_eof", "1",
		"-reconnect_delay_max", "5",
	}
	if a.UserAgent != "" {
		out = append(out, "-user_agent", a.UserAgent)
	}
	if a.Referer != "" {
		out = append(out, "-headers", fmt.Sprintf("Referer: %s\r\n", a.Referer))
	}
	out = append(out, "-i", a.InputURL)
	out = append(out,
		"-map", "0:v:0",
		"-map", "0:a:0?",
		"-c", "copy",
		"-t", strconv.Itoa(sec),
		"-y",
		a.OutputPath,
	)
	if a.CaptionsPath != "" {
		out = append(out,
			"-map", "0:s:0?",
			"-c", "copy",
			"-t", strconv.Itoa(sec),
			"-y",
			a.CaptionsPath,
		)
	}
	return out, nil
}

// ParseDuration accepts forms like 90m, 1h30m, 3600, 2h, 45s.
func ParseDuration(s string) (time.Duration, error) {
	s = strings.TrimSpace(strings.ToLower(s))
	if s == "" {
		return 0, fmt.Errorf("empty duration")
	}
	if n, err := strconv.Atoi(s); err == nil && n > 0 {
		return time.Duration(n) * time.Second, nil
	}
	var d time.Duration
	rem := s
	for rem != "" {
		i := 0
		for i < len(rem) && rem[i] >= '0' && rem[i] <= '9' {
			i++
		}
		if i == 0 {
			return 0, fmt.Errorf("invalid duration %q", s)
		}
		n, err := strconv.Atoi(rem[:i])
		if err != nil {
			return 0, err
		}
		if i >= len(rem) {
			return 0, fmt.Errorf("missing unit in %q", s)
		}
		unit := rem[i]
		rem = strings.TrimSpace(rem[i+1:])
		switch unit {
		case 'h':
			d += time.Duration(n) * time.Hour
		case 'm':
			d += time.Duration(n) * time.Minute
		case 's':
			d += time.Duration(n) * time.Second
		default:
			return 0, fmt.Errorf("unknown unit %q in duration", string(unit))
		}
	}
	if d <= 0 {
		return 0, fmt.Errorf("duration must be positive")
	}
	return d, nil
}
