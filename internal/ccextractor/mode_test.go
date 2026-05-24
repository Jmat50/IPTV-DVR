package ccextractor

import "testing"

func TestMigrateMode(t *testing.T) {
	if got := MigrateMode("", true); got != ModeAuto {
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
