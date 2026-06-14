//go:build !windows

package ccextractor

import "os/exec"

func configureLiveWorkerCmd(_ *exec.Cmd) {}

func armLiveWorkerConsoleGuard(_ *exec.Cmd) {}
