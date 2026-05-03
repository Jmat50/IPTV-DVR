package m3u

import (
	"strings"
	"testing"
)

func TestParse_extvlc(t *testing.T) {
	const raw = `#EXTM3U
#EXTINF:-1 tvg-id="1",Alpha News
#EXTVLCOPT:http-user-agent=TestAgent/1.0
#EXTVLCOPT:http-referrer=https://example.com/ref
http://example.com/alpha
#EXTINF:-1,Beta TV
http://example.com/beta
`
	ch, err := Parse(strings.NewReader(raw))
	if err != nil {
		t.Fatal(err)
	}
	if len(ch) != 2 {
		t.Fatalf("channels: got %d want 2", len(ch))
	}
	if ch[0].Name != "Alpha News" || ch[0].URL != "http://example.com/alpha" {
		t.Fatalf("ch0: %+v", ch[0])
	}
	if ch[0].UserAgent != "TestAgent/1.0" || ch[0].Referer != "https://example.com/ref" {
		t.Fatalf("ch0 headers: %+v", ch[0])
	}
	if ch[1].Name != "Beta TV" || ch[1].URL != "http://example.com/beta" {
		t.Fatalf("ch1: %+v", ch[1])
	}
}

func TestFindChannel(t *testing.T) {
	ch := []Channel{
		{Name: "BBC One HD", URL: "http://x/1"},
		{Name: "BBC Two", URL: "http://x/2"},
	}
	c, err := FindChannel(ch, "bbc one hd")
	if err != nil {
		t.Fatal(err)
	}
	if c.URL != "http://x/1" {
		t.Fatal(c)
	}
	_, err = FindChannel(ch, "bbc")
	if err == nil {
		t.Fatal("expected ambiguous")
	}
}
