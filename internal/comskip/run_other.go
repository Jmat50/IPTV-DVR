//go:build !windows

package comskip

import "os/exec"

func configureCmd(cmd *exec.Cmd) {}

func armConsoleGuard(cmd *exec.Cmd) {}
