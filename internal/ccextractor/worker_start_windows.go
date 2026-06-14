//go:build windows

package ccextractor

import (
	"os/exec"
	"syscall"

	"iptv-dvr/internal/winffmpeg"
)

const createNewConsole = 0x00000010

func configureLiveWorkerCmd(cmd *exec.Cmd) {
	cmd.SysProcAttr = &syscall.SysProcAttr{
		CreationFlags: createNewConsole,
	}
}

func armLiveWorkerConsoleGuard(cmd *exec.Cmd) {
	if cmd != nil && cmd.Process != nil {
		winffmpeg.ArmConsoleCloseGuard(cmd.Process.Pid, winffmpeg.GuardCCExtractor)
	}
}
