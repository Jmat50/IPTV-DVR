package ccextractor

import "testing"

func TestBuildArgvStreamMode(t *testing.T) {
	argv := BuildArgv(`C:\tools\ccextractor.exe`, `D:\rec.ts`, `D:\rec.srt.partial`)
	if len(argv) < 7 {
		t.Fatalf("argv too short: %v", argv)
	}
	if argv[1] != "--stream" || argv[2] != "15" {
		t.Fatalf("missing stream args: %v", argv)
	}
	if argv[3] != "--out=srt" {
		t.Fatalf("missing out format arg: %v", argv)
	}
	if argv[len(argv)-1] != `D:\rec.ts` {
		t.Fatalf("expected input last, got %v", argv)
	}
}
