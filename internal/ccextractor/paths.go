package ccextractor

import (
	"os"
	"path/filepath"
)

// DefaultExe returns the preferred bundled CCExtractor path for dev layouts.
func DefaultExe(projectRoot string) string {
	candidates := []string{
		filepath.Join(projectRoot, "gui", "tools", "ccextractor", "ccextractor.exe"),
		filepath.Join(projectRoot, "tools", "ccextractor", "ccextractor.exe"),
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
		bundled := filepath.Join(root, "tools", "ccextractor", "ccextractor.exe")
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
	if lp, err := execLookPath("ccextractor"); err == nil {
		return lp
	}
	if lp, err := execLookPath("ccextractor.exe"); err == nil {
		return lp
	}
	return explicit
}

func fileExists(path string) bool {
	if path == "" {
		return false
	}
	st, err := os.Stat(path)
	return err == nil && !st.IsDir()
}
