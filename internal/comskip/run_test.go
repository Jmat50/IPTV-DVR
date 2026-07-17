package comskip

import "testing"

func TestRunOK(t *testing.T) {
	if !runOK(0, false, false) {
		t.Fatal("exit 0 should succeed with no sidecars")
	}
	if !runOK(1, true, false) {
		t.Fatal("exit 1 with edl should succeed")
	}
	if !runOK(1, false, true) {
		t.Fatal("exit 1 with txt should succeed")
	}
	if runOK(1, false, false) {
		t.Fatal("exit 1 without sidecars should fail")
	}
	if runOK(2, true, true) {
		t.Fatal("exit 2 should fail")
	}
}

func TestMasterEDLBesideRecording(t *testing.T) {
	got := masterEDL(`C:\Videos\show.ts`)
	want := `C:\Videos\show.edl`
	if got != want {
		t.Fatalf("masterEDL = %q, want %q", got, want)
	}
}
