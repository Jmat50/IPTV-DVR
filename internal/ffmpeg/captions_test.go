package ffmpeg

import "testing"

func TestCaptionExtForCodec(t *testing.T) {
	cases := map[string]string{
		"webvtt": ".vtt",
		"subrip": ".srt",
		"ass":    ".ass",
		"eia_608": ".srt",
	}
	for codec, want := range cases {
		got := captionExtForCodec(codec)
		if got != want {
			t.Fatalf("%s: got %q want %q", codec, got, want)
		}
	}
}

func TestBuildExtractArgv(t *testing.T) {
	argv, err := BuildExtractArgv(`C:\bin\ffmpeg.exe`, `D:\rec.ts`, "webvtt")
	if err != nil {
		t.Fatal(err)
	}
	if argv[len(argv)-1] != `D:\rec.vtt` {
		t.Fatalf("got %v", argv)
	}
}
