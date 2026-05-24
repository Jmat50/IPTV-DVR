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

func TestBuildExtractEmbedded608Argv(t *testing.T) {
	argv, dir, err := BuildExtractEmbedded608Argv(`C:\bin\ffmpeg.exe`, `Y:\Family Feud\2026-05-19_Game Show Network.ts`)
	if err != nil {
		t.Fatal(err)
	}
	if dir != `Y:\Family Feud` {
		t.Fatalf("dir: got %q", dir)
	}
	if argv[len(argv)-1] != `2026-05-19_Game Show Network.srt` {
		t.Fatalf("output: got %v", argv)
	}
	wantLavfi := "movie='2026-05-19_Game Show Network.ts'[out+subcc]"
	gotLavfi := ""
	for i := 0; i < len(argv)-1; i++ {
		if argv[i] == "-i" {
			gotLavfi = argv[i+1]
			break
		}
	}
	if gotLavfi != wantLavfi {
		t.Fatalf("lavfi: got %q want %q", gotLavfi, wantLavfi)
	}
}

func TestMovieBasenameForLavfi(t *testing.T) {
	if got := movieBasenameForLavfi("it's.ts"); got != `it\'s.ts` {
		t.Fatalf("got %q", got)
	}
}
