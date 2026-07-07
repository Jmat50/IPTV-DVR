package comskip

import (
	"os"
	"path/filepath"
	"testing"
)

func TestMergeCommercialBreaks(t *testing.T) {
	dir := t.TempDir()
	edl := filepath.Join(dir, "seg.edl")
	if err := os.WriteFile(edl, []byte("10.00\t40.00\t3\n"), 0o644); err != nil {
		t.Fatal(err)
	}
	seg := EpisodeSegment{Index: 2, StartSec: 3600, EndSec: 7200}
	merged := MergeCommercialBreaks([]segmentSidecars{{Segment: seg, EDL: edl}}, 8000)
	if len(merged) != 1 {
		t.Fatalf("expected 1 break, got %d", len(merged))
	}
	if merged[0].StartSec != 3610 {
		t.Fatalf("expected offset start 3610, got %v", merged[0].StartSec)
	}
	if merged[0].EpisodeIndex != 2 {
		t.Fatalf("expected episode index 2, got %d", merged[0].EpisodeIndex)
	}
}

func TestNormalizeBreaksOverlap(t *testing.T) {
	in := []CommercialBreak{
		{StartSec: 10, EndSec: 50},
		{StartSec: 40, EndSec: 70},
	}
	out := NormalizeBreaks(in, 100)
	if len(out) != 1 {
		t.Fatalf("expected 1 merged break, got %d", len(out))
	}
	if out[0].EndSec != 70 {
		t.Fatalf("expected end 70, got %v", out[0].EndSec)
	}
}

func TestParseEDL(t *testing.T) {
	dir := t.TempDir()
	path := filepath.Join(dir, "x.edl")
	if err := os.WriteFile(path, []byte("1.00\t2.00\t3\n"), 0o644); err != nil {
		t.Fatal(err)
	}
	breaks, err := ParseEDL(path)
	if err != nil {
		t.Fatal(err)
	}
	if len(breaks) != 1 || breaks[0].EndSec != 2 {
		t.Fatalf("unexpected breaks: %+v", breaks)
	}
}
