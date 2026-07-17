package comskip

import (
	"os"
	"os/exec"
	"path/filepath"
	"strings"
)

func looksLikeProjectRoot(root string) bool {
	return fileExists(filepath.Join(root, "go.mod")) ||
		fileExists(filepath.Join(root, "config.json")) ||
		fileExists(filepath.Join(root, "gui", "tools", "comskip", "comskip.exe")) ||
		fileExists(filepath.Join(root, "tools", "comskip", "comskip.exe"))
}

// workRoot picks the project/install root used for logs/comskip_work.
func workRoot() string {
	var candidates []string
	if wd, err := os.Getwd(); err == nil {
		candidates = append(candidates, wd)
	}
	if exe, err := os.Executable(); err == nil {
		dir := filepath.Dir(exe)
		candidates = append(candidates, dir)
		if filepath.Base(dir) == "gui" {
			candidates = append(candidates, filepath.Dir(dir))
		}
	}
	for _, c := range candidates {
		if looksLikeProjectRoot(c) {
			return c
		}
	}
	if len(candidates) > 0 {
		return candidates[0]
	}
	return "."
}

// ArtifactDir returns logs/comskip_work/<stem> for Comskip work logs, .logo, and other non-EDL artifacts.
func ArtifactDir(outputPath string) string {
	dir := filepath.Join(workRoot(), "logs", "comskip_work", basenameStem(outputPath))
	_ = os.MkdirAll(dir, 0o755)
	return dir
}

func execLookPath(name string) (string, error) {
	return exec.LookPath(name)
}

func fileExists(path string) bool {
	if path == "" {
		return false
	}
	st, err := os.Stat(path)
	return err == nil && !st.IsDir()
}

// DefaultExe returns the preferred bundled Comskip path for dev layouts.
func DefaultExe(projectRoot string) string {
	candidates := []string{
		filepath.Join(projectRoot, "gui", "tools", "comskip", "comskip.exe"),
		filepath.Join(projectRoot, "tools", "comskip", "comskip.exe"),
	}
	for _, p := range candidates {
		if fileExists(p) {
			return p
		}
	}
	return candidates[0]
}

// DefaultIni returns the preferred bundled comskip.ini path.
func DefaultIni(projectRoot string) string {
	candidates := []string{
		filepath.Join(projectRoot, "gui", "tools", "comskip", "comskip.ini"),
		filepath.Join(projectRoot, "tools", "comskip", "comskip.ini"),
	}
	for _, p := range candidates {
		if fileExists(p) {
			return p
		}
	}
	return candidates[0]
}

// ResolveExe picks an explicit path, bundled binary, or PATH lookup.
func ResolveExe(explicit string) string {
	if explicit != "" && fileExists(explicit) {
		return explicit
	}
	if exe, err := os.Executable(); err == nil {
		root := filepath.Dir(exe)
		bundled := filepath.Join(root, "tools", "comskip", "comskip.exe")
		if fileExists(bundled) {
			return bundled
		}
	}
	if p, err := os.Getwd(); err == nil {
		def := DefaultExe(p)
		if fileExists(def) {
			return def
		}
	}
	if lp, err := execLookPath("comskip"); err == nil {
		return lp
	}
	if lp, err := execLookPath("comskip.exe"); err == nil {
		return lp
	}
	return explicit
}

// ResolveIni picks bundled ini beside exe or explicit path.
func ResolveIni(explicit string) string {
	if explicit != "" && fileExists(explicit) {
		return explicit
	}
	exe := ResolveExe("")
	if exe != "" {
		ini := filepath.Join(filepath.Dir(exe), "comskip.ini")
		if fileExists(ini) {
			return ini
		}
	}
	if p, err := os.Getwd(); err == nil {
		def := DefaultIni(p)
		if fileExists(def) {
			return def
		}
	}
	return explicit
}

// Available reports whether Comskip runtime files are present.
func Available(explicitExe, explicitIni string) bool {
	exe := ResolveExe(explicitExe)
	ini := ResolveIni(explicitIni)
	return fileExists(exe) && fileExists(ini)
}

// SupportedOutput returns true for MPEG-TS recordings.
func SupportedOutput(path string) bool {
	return strings.EqualFold(filepath.Ext(path), ".ts")
}
