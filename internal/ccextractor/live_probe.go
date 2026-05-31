package ccextractor

import (
	"bytes"
	"os"
	"os/exec"
	"path/filepath"
	"strings"
	"time"
)

// LiveSupported reports whether the installed CCExtractor accepts tail-follow (--stream)
// on a single growing .ts file. CCExtractor 0.96.x Rust CLI has an inverted validation check
// that rejects --stream <secs> whenever an input file is present.
func LiveSupported(ccExe string) (bool, string) {
	exe := ResolveExe(ccExe)
	if !fileExists(exe) {
		return false, "CCExtractor not found at " + exe
	}
	dir, err := os.MkdirTemp("", "iptv-ccx-probe-*")
	if err != nil {
		return false, "live probe temp dir: " + err.Error()
	}
	defer os.RemoveAll(dir)

	probe := filepath.Join(dir, "probe.ts")
	partial := filepath.Join(dir, "probe.srt.partial")
	if err := os.WriteFile(probe, []byte{0x47}, 0o600); err != nil {
		return false, "live probe file: " + err.Error()
	}

	argv := BuildArgv(exe, probe, partial)
	cmd := exec.Command(argv[0], argv[1:]...)
	cmd.Dir = filepath.Dir(exe)
	var out bytes.Buffer
	cmd.Stdout = &out
	cmd.Stderr = &out
	if err := cmd.Start(); err != nil {
		return false, "live probe start: " + err.Error()
	}
	done := make(chan error, 1)
	go func() { done <- cmd.Wait() }()
	select {
	case <-time.After(5 * time.Second):
		_ = cmd.Process.Kill()
		<-done
		return true, "live probe timed out while waiting for stream data"
	case err := <-done:
		text := strings.ToLower(out.String())
		if err == nil {
			return true, "live probe exited cleanly"
		}
		if strings.Contains(text, "only supports one input file") {
			return false, "CCExtractor 0.96.x CLI regression: --stream <secs> rejects any input file " +
				"(inverted validation in rust parser; live tail mode never starts)"
		}
		if strings.Contains(text, "a value is required for '--stream") {
			return false, "live stream mode parsing failed (--stream value)"
		}
		trim := strings.Join(strings.Fields(text), " ")
		if len(trim) > 220 {
			trim = trim[:220]
		}
		if trim == "" {
			trim = err.Error()
		}
		return false, trim
	}
}
