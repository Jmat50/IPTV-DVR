package m3u

import (
	"fmt"
	"io"
	"net/http"
	"os"
	"strings"
	"time"
)

// Channel is one playable entry from an M3U playlist.
type Channel struct {
	Name      string
	URL       string
	UserAgent string
	Referer   string
}

// Load reads an M3U from a local path or http(s) URL.
func Load(pathOrURL string) ([]Channel, error) {
	var r io.ReadCloser
	if strings.HasPrefix(pathOrURL, "http://") || strings.HasPrefix(pathOrURL, "https://") {
		client := &http.Client{Timeout: 60 * time.Second}
		resp, err := client.Get(pathOrURL)
		if err != nil {
			return nil, err
		}
		if resp.StatusCode != http.StatusOK {
			resp.Body.Close()
			return nil, fmt.Errorf("fetch m3u: %s", resp.Status)
		}
		r = resp.Body
	} else {
		f, err := os.Open(pathOrURL)
		if err != nil {
			return nil, err
		}
		r = f
	}
	defer r.Close()
	return Parse(r)
}

// Parse reads extended M3U content.
func Parse(r io.Reader) ([]Channel, error) {
	data, err := io.ReadAll(r)
	if err != nil {
		return nil, err
	}
	lines := strings.Split(string(data), "\n")
	var out []Channel
	var cur Channel

	for _, raw := range lines {
		line := strings.TrimSpace(strings.TrimSuffix(raw, "\r"))
		if line == "" {
			continue
		}
		switch {
		case strings.HasPrefix(line, "#EXTINF"):
			cur = Channel{Name: parseExtinfTitle(line)}
		case strings.HasPrefix(line, "#EXTVLCOPT:"):
			opt := strings.TrimPrefix(line, "#EXTVLCOPT:")
			switch {
			case strings.HasPrefix(opt, "http-user-agent="):
				cur.UserAgent = strings.TrimPrefix(opt, "http-user-agent=")
			case strings.HasPrefix(opt, "http-referrer="):
				cur.Referer = strings.TrimPrefix(opt, "http-referrer=")
			}
		case strings.HasPrefix(line, "#"):
			continue
		default:
			if isStreamURL(line) {
				cur.URL = line
				if cur.Name != "" {
					out = append(out, cur)
				}
				cur = Channel{}
			}
		}
	}
	return out, nil
}

func isStreamURL(s string) bool {
	return strings.HasPrefix(s, "http://") ||
		strings.HasPrefix(s, "https://") ||
		strings.HasPrefix(s, "rtmp://") ||
		strings.HasPrefix(s, "rtsp://")
}

func parseExtinfTitle(line string) string {
	if i := strings.LastIndex(line, ","); i >= 0 && i+1 < len(line) {
		return strings.TrimSpace(line[i+1:])
	}
	return strings.TrimSpace(line)
}

// FindChannel returns the channel matching name (exact case-insensitive, else unique substring).
func FindChannel(channels []Channel, name string) (Channel, error) {
	name = strings.TrimSpace(name)
	if name == "" {
		return Channel{}, fmt.Errorf("empty channel name")
	}
	want := strings.ToLower(name)
	var exact *Channel
	var partial []Channel
	for i := range channels {
		c := &channels[i]
		n := strings.ToLower(strings.TrimSpace(c.Name))
		if n == want {
			exact = c
			break
		}
		if strings.Contains(n, want) {
			partial = append(partial, *c)
		}
	}
	if exact != nil {
		return *exact, nil
	}
	if len(partial) == 1 {
		return partial[0], nil
	}
	if len(partial) == 0 {
		return Channel{}, fmt.Errorf("no channel matching %q", name)
	}
	var names []string
	for _, c := range partial {
		if len(names) < 8 {
			names = append(names, c.Name)
		}
	}
	return Channel{}, fmt.Errorf("ambiguous channel %q matches: %s", name, strings.Join(names, "; "))
}
