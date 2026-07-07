//go:build windows

package winffmpeg

import (
	"strings"
	"syscall"
	"time"
	"unsafe"
)

// ConsoleGuard selects title/menu text for a protected child console.
type ConsoleGuard struct {
	ToolLabel string
	MenuText  string
}

var (
	// GuardFFmpeg labels FFmpeg recording consoles.
	GuardFFmpeg = ConsoleGuard{
		ToolLabel: "FFmpeg",
		MenuText:  "Close disabled while FFmpeg is recording",
	}
	// GuardCCExtractor labels live CCExtractor worker consoles.
	GuardCCExtractor = ConsoleGuard{
		ToolLabel: "CCExtractor",
		MenuText:  "Close disabled while CCExtractor is extracting captions",
	}
	// GuardComskip labels Comskip analysis consoles.
	GuardComskip = ConsoleGuard{
		ToolLabel: "Comskip",
		MenuText:  "Close disabled while Comskip is analyzing commercials",
	}
)

// ArmConsoleCloseGuard polls for the child's ConsoleWindowClass HWND and
// disables accidental system-menu close while the process runs.
func ArmConsoleCloseGuard(pid int, guard ConsoleGuard) {
	go armConsoleCloseGuard(pid, guard)
}

func armConsoleCloseGuard(pid int, guard ConsoleGuard) {
	deadline := time.Now().Add(5 * time.Second)
	for time.Now().Before(deadline) {
		hwnd := findConsoleWindowForPID(pid)
		if hwnd != 0 {
			disableConsoleClose(hwnd)
			warnConsoleIsProtected(hwnd, guard)
			return
		}
		time.Sleep(100 * time.Millisecond)
	}
}

func warnConsoleIsProtected(hwnd syscall.Handle, guard ConsoleGuard) {
	var titleBuf [512]uint16
	n, _, _ := procGetWindowTextW.Call(uintptr(hwnd), uintptr(unsafe.Pointer(&titleBuf[0])), uintptr(len(titleBuf)))
	base := guard.ToolLabel
	if n > 0 {
		if trimmed := strings.TrimSpace(syscall.UTF16ToString(titleBuf[:n])); trimmed != "" {
			base = trimmed
		}
	}
	if !strings.Contains(strings.ToLower(base), "[protected]") {
		newTitle, err := syscall.UTF16PtrFromString(base + " [" + guard.ToolLabel + " - PROTECTED - do not close]")
		if err == nil {
			procSetWindowTextW.Call(uintptr(hwnd), uintptr(unsafe.Pointer(newTitle)))
		}
	}

	menu, _, _ := procGetSystemMenu.Call(uintptr(hwnd), 0)
	if menu == 0 {
		return
	}
	procAppendMenuW.Call(menu, uintptr(mfSeparator), 0, 0)
	disabledTxt, err := syscall.UTF16PtrFromString(guard.MenuText)
	if err != nil {
		return
	}
	procAppendMenuW.Call(menu, uintptr(mfString|mfDisabled), 0, uintptr(unsafe.Pointer(disabledTxt)))
	procDrawMenuBar.Call(uintptr(hwnd))
}
