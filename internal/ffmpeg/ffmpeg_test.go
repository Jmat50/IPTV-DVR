package ffmpeg

import (
	"strings"
	"testing"
	"time"
)

func TestParseDuration(t *testing.T) {
	cases := []struct {
		in   string
		want time.Duration
	}{
		{"3600", 3600 * time.Second},
		{"90m", 90 * time.Minute},
		{"1h30m", time.Hour + 30*time.Minute},
		{"45s", 45 * time.Second},
	}
	for _, c := range cases {
		d, err := ParseDuration(c.in)
		if err != nil {
			t.Fatalf("%q: %v", c.in, err)
		}
		if d != c.want {
			t.Fatalf("%q: got %v want %v", c.in, d, c.want)
		}
	}
}

func TestBuildArgv(t *testing.T) {
	argv, err := BuildArgv(Args{
		FFmpegPath: `C:\bin\ffmpeg.exe`,
		InputURL:   "http://x/stream",
		OutputPath: `D:\out.ts`,
		Duration:   2 * time.Minute,
		UserAgent:  "UA",
		Referer:    "https://ref/",
	})
	if err != nil {
		t.Fatal(err)
	}
	if argv[0] != `C:\bin\ffmpeg.exe` {
		t.Fatal(argv)
	}
	if !containsAll(argv, "-map", "0:v:0", "-map", "0:a:0?", "-c", "copy", "-t", "120", "-y", `D:\out.ts`) {
		t.Fatalf("missing expected args: %v", argv)
	}
}

func TestBuildArgvCaptions(t *testing.T) {
	argv, err := BuildArgv(Args{
		FFmpegPath:   `C:\bin\ffmpeg.exe`,
		InputURL:     "http://x/stream.m3u8",
		OutputPath:   `D:\out.ts`,
		CaptionsPath: `D:\out.vtt`,
		Duration:     30 * time.Second,
	})
	if err != nil {
		t.Fatal(err)
	}
	if !containsAll(argv, "-map", "0:s:0?", "-y", `D:\out.vtt`) {
		t.Fatalf("missing caption output: %v", argv)
	}
}

func TestCaptionsSidecarPath(t *testing.T) {
	if got := CaptionsSidecarPath(`D:\rec.ts`); got != `D:\rec.vtt` {
		t.Fatalf("got %q", got)
	}
}

func containsAll(argv []string, parts ...string) bool {
	joined := strings.Join(argv, "\x00")
	for _, p := range parts {
		if !strings.Contains(joined, p) {
			return false
		}
	}
	return true
}
