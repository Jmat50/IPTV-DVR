package ccextractor

import (
	"os"
	"path/filepath"
	"testing"
)

func TestValidateAndFinalizeSRT(t *testing.T) {
	dir := t.TempDir()
	partial := filepath.Join(dir, "show.srt.partial")
	final := filepath.Join(dir, "show.srt")
	content := "1\n00:00:01,000 --> 00:00:02,000\nHello\n"
	if err := os.WriteFile(partial, []byte(content), 0644); err != nil {
		t.Fatal(err)
	}
	if !ValidateSRT(partial) {
		t.Fatal("expected valid partial")
	}
	if !FinalizePartial(partial, final) {
		t.Fatal("finalize failed")
	}
	if _, err := os.Stat(partial); err == nil {
		t.Fatal("partial should be renamed away")
	}
	if !ValidateSRT(final) {
		t.Fatal("expected valid final")
	}
}

func TestSidecarPaths(t *testing.T) {
	if got := SidecarSRTPath(`Y:\rec.ts`); got != `Y:\rec.srt` {
		t.Fatalf("srt: %q", got)
	}
	if got := PartialSRTPath(`Y:\rec.ts`); got != `Y:\rec.srt.partial` {
		t.Fatalf("partial: %q", got)
	}
}
