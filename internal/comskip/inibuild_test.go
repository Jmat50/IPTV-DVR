package comskip

import (
	"os"
	"path/filepath"
	"strconv"
	"strings"
	"testing"
)

func TestDefaultDetectMethod(t *testing.T) {
	s := DefaultSettings()
	if s.DetectMethod() != DefaultDetectMethod || s.DetectMethod() != 43 {
		t.Fatalf("got %d want 43", s.DetectMethod())
	}
}

func TestIniOverrides(t *testing.T) {
	s := DefaultSettings()
	s.Subtitles = true
	s.MinCommercialBreak = 15
	s.ConnectBlocksWithLogo = false
	o := s.IniOverrides()
	if o["subtitles"] != "1" || o["min_commercialbreak"] != "15" || o["connect_blocks_with_logo"] != "0" {
		t.Fatalf("unexpected overrides: %#v", o)
	}
}

func TestApplyIniOverridesReplaceAndAppend(t *testing.T) {
	tpl := "detect_method=43\t\t;comment\nsubtitles=0\n"
	out := ApplyIniOverrides(tpl, map[string]string{
		"detect_method": "111",
		"subtitles":     "1",
		"extra_key":     "9",
	})
	if !strings.Contains(out, "detect_method=111") {
		t.Fatalf("missing replaced detect_method: %s", out)
	}
	if strings.Contains(out, "detect_method=43") {
		t.Fatalf("old detect_method still present: %s", out)
	}
	if !strings.Contains(out, "subtitles=1") {
		t.Fatalf("missing subtitles: %s", out)
	}
	if !strings.Contains(out, "extra_key=9") {
		t.Fatalf("missing appended key: %s", out)
	}
}

func TestMaterializeIni(t *testing.T) {
	dir := t.TempDir()
	tpl := filepath.Join(dir, "template.ini")
	if err := os.WriteFile(tpl, []byte("detect_method=43\nsubtitles=0\n"), 0o644); err != nil {
		t.Fatal(err)
	}
	dest := filepath.Join(dir, "work", "comskip.ini")
	s := DefaultSettings()
	s.Subtitles = true
	s.DetectSilence = true
	path, err := MaterializeIni(s, dest, tpl)
	if err != nil {
		t.Fatal(err)
	}
	data, err := os.ReadFile(path)
	if err != nil {
		t.Fatal(err)
	}
	text := string(data)
	want := "detect_method=" + strconv.Itoa(s.DetectMethod())
	if !strings.Contains(text, want) {
		t.Fatalf("detect_method missing (%s): %s", want, text)
	}
	if !strings.Contains(text, "subtitles=1") {
		t.Fatalf("subtitles missing: %s", text)
	}
}
