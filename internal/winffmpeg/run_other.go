//go:build !windows

package winffmpeg

import (
	"fmt"
	"os"
	"os/exec"
)

// Run starts FFmpeg with inherited standard I/O (non-Windows).
func Run(argv []string) error {
	return RunInDir("", argv)
}

// RunInDir is like Run but sets the child process working directory.
func RunInDir(dir string, argv []string) error {
	if len(argv) == 0 {
		return fmt.Errorf("empty argv")
	}
	cmd := exec.Command(argv[0], argv[1:]...)
	cmd.Stdin = os.Stdin
	cmd.Stdout = os.Stdout
	cmd.Stderr = os.Stderr
	if dir != "" {
		cmd.Dir = dir
	}
	return cmd.Run()
}
