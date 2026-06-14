package ccextractor

import "testing"

func TestMigrateMode(t *testing.T) {
	if got := MigrateMode("", true); got != ModePostOnly {
		t.Fatalf("legacy captions: got %q", got)
	}
	if got := MigrateMode("live_ccextractor", false); got != ModeLiveCCExtractor {
		t.Fatalf("explicit: got %q", got)
	}
	if got := MigrateMode("", false); got != ModeOff {
		t.Fatalf("off: got %q", got)
	}
}

func TestResolveEffectiveModeNonTS(t *testing.T) {
	got := ResolveEffectiveMode(ModeLiveCCExtractor, `D:\rec.mp4`, "")
	if got != ModePostOnly {
		t.Fatalf("mp4 live -> post_only, got %q", got)
	}
}

func TestNormalizeModeLegacyAuto(t *testing.T) {
	if got := NormalizeMode("auto"); got != ModePostOnly {
		t.Fatalf("legacy auto: got %q", got)
	}
}

func TestResolvePostProcessorForMode(t *testing.T) {
	if got := ResolvePostProcessorForMode(ModePostOnly, "ccextractor"); got != PostProcessorCCExtractor {
		t.Fatalf("post_only should allow ccextractor, got %q", got)
	}
	if got := ResolvePostProcessorForMode(ModeOff, "ccextractor"); got != PostProcessorFFmpeg {
		t.Fatalf("off should force ffmpeg, got %q", got)
	}
}
