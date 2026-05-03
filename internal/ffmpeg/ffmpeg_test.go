package ffmpeg

import (
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
	if len(argv) < 8 {
		t.Fatal(argv)
	}
}
