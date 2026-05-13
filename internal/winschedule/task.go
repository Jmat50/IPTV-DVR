package winschedule

import (
	"fmt"
	"os"
	"os/exec"
	"strings"
	"time"
)

// CreateOnceTask registers a one-time scheduled task (local time) using PowerShell.
func CreateOnceTask(taskName, exePath, argument string, runAt time.Time) error {
	if taskName == "" {
		return fmt.Errorf("empty task name")
	}
	q := func(s string) string { return "'" + strings.ReplaceAll(s, "'", "''") + "'" }
	// Culture-invariant compact local time for ParseExact.
	tStr := runAt.Format("20060102150405")
	ps := fmt.Sprintf(
		"$ErrorActionPreference='Stop'; "+
			"$when=[datetime]::ParseExact(%s,'yyyyMMddHHmmss',$null); "+
			"$a=New-ScheduledTaskAction -Execute %s -Argument %s; "+
			"$tr=New-ScheduledTaskTrigger -Once -At $when; "+
			"$st=New-ScheduledTaskSettingsSet -WakeToRun -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -ExecutionTimeLimit (New-TimeSpan -Hours 24); "+
			"Register-ScheduledTask -TaskName %s -Action $a -Trigger $tr -Settings $st -Force | Out-Null",
		q(tStr), q(exePath), q(argument), q(taskName),
	)
	cmd := exec.Command("powershell.exe", "-NoProfile", "-NonInteractive", "-Command", ps)
	cmd.Stdout = os.Stdout
	cmd.Stderr = os.Stderr
	if err := cmd.Run(); err != nil {
		return fmt.Errorf("register scheduled task: %w", err)
	}
	return nil
}

// DefaultTaskName builds a stable task name fragment from channel and time.
func DefaultTaskName(channel string, runAt time.Time) string {
	return fmt.Sprintf("IPTVRecord_%s_%s", sanitize(channel), runAt.Format("20060102_150405"))
}

func sanitize(s string) string {
	s = strings.Map(func(r rune) rune {
		switch r {
		case '\\', '/', ':', '*', '?', '"', '<', '>', '|', ' ':
			return '_'
		default:
			return r
		}
	}, s)
	if s == "" {
		return "ch"
	}
	if len(s) > 50 {
		return s[:50]
	}
	return s
}
