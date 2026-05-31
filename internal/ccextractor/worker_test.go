package ccextractor

import "testing"

func TestBuildArgvStreamMode(t *testing.T) {
	argv := BuildArgv(`C:\tools\ccextractor.exe`, `D:\rec.ts`, `D:\rec.srt.partial`)
	if len(argv) < 7 {
		t.Fatalf("argv too short: %v", argv)
	}
	if argv[1] != "-1" || argv[2] != "--input" || argv[3] != "ts" || argv[4] != "--stream" || argv[5] != "15" {
		t.Fatalf("missing stream args: %v", argv)
	}
	if argv[6] != "--out" || argv[7] != "srt" {
		t.Fatalf("missing out format arg: %v", argv)
	}
	if argv[len(argv)-1] != `D:\rec.ts` {
		t.Fatalf("expected input last, got %v", argv)
	}
}

func TestBuildPostArgv(t *testing.T) {
	argv := BuildPostArgv(`C:\tools\ccextractor.exe`, `D:\rec.ts`, `D:\rec.srt`)
	if len(argv) < 6 {
		t.Fatalf("argv too short: %v", argv)
	}
	if argv[1] != "-1" {
		t.Fatalf("expected -1 (608-only), got %v", argv)
	}
	if argv[2] != "--out=srt" {
		t.Fatalf("missing out arg: %v", argv)
	}
	if argv[3] != "-o" || argv[4] != `D:\rec.srt` {
		t.Fatalf("missing output args: %v", argv)
	}
	if argv[len(argv)-1] != `D:\rec.ts` {
		t.Fatalf("expected input last, got %v", argv)
	}
}
