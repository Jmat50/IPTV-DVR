//go:build windows

package comskip

import (
	"os/exec"
	"syscall"

	"iptv-dvr/internal/winffmpeg"
)

const createNewConsole = 0x00000010

func configureCmd(cmd *exec.Cmd) {
	cmd.SysProcAttr = &syscall.SysProcAttr{
		CreationFlags: createNewConsole,
	}
}

func armConsoleGuard(cmd *exec.Cmd) {
	if cmd != nil && cmd.Process != nil {
		winffmpeg.ArmConsoleCloseGuard(cmd.Process.Pid, winffmpeg.GuardComskip)
	}
}
