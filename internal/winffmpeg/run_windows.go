//go:build windows

package winffmpeg

import (
	"fmt"
	"os"
	"os/exec"
	"strings"
	"syscall"
	"time"
	"unsafe"
)

const (
	createNewConsole = 0x00000010
	scClose          = 0xF060
	mfByCommand      = 0x0000
	mfSeparator      = 0x00000800
	mfString         = 0x0000
	mfDisabled       = 0x00000002
)

var user32 = syscall.NewLazyDLL("user32.dll")

var (
	procEnumWindows           = user32.NewProc("EnumWindows")
	procGetWindowThreadProcID = user32.NewProc("GetWindowThreadProcessId")
	procGetClassNameW         = user32.NewProc("GetClassNameW")
	procGetSystemMenu         = user32.NewProc("GetSystemMenu")
	procDeleteMenu            = user32.NewProc("DeleteMenu")
	procDrawMenuBar           = user32.NewProc("DrawMenuBar")
	procGetWindowTextW        = user32.NewProc("GetWindowTextW")
	procSetWindowTextW        = user32.NewProc("SetWindowTextW")
	procAppendMenuW           = user32.NewProc("AppendMenuW")
)

type enumData struct {
	targetPID uint32
	found     syscall.Handle
}

func enumWindowsCallback(hwnd uintptr, lparam uintptr) uintptr {
	data := (*enumData)(unsafe.Pointer(lparam))
	var pid uint32
	procGetWindowThreadProcID.Call(hwnd, uintptr(unsafe.Pointer(&pid)))
	if pid != data.targetPID {
		return 1
	}
	var classBuf [64]uint16
	n, _, _ := procGetClassNameW.Call(hwnd, uintptr(unsafe.Pointer(&classBuf[0])), uintptr(len(classBuf)))
	if n == 0 {
		return 1
	}
	name := syscall.UTF16ToString(classBuf[:n])
	if name != "ConsoleWindowClass" {
		return 1
	}
	data.found = syscall.Handle(hwnd)
	return 0
}

func findConsoleWindowForPID(pid int) syscall.Handle {
	var data enumData
	data.targetPID = uint32(pid)
	cb := syscall.NewCallback(enumWindowsCallback)
	procEnumWindows.Call(cb, uintptr(unsafe.Pointer(&data)))
	return data.found
}

func disableConsoleClose(hwnd syscall.Handle) {
	menu, _, _ := procGetSystemMenu.Call(uintptr(hwnd), 0)
	if menu == 0 {
		return
	}
	procDeleteMenu.Call(menu, uintptr(scClose), uintptr(mfByCommand))
	procDrawMenuBar.Call(uintptr(hwnd))
}

func warnConsoleIsProtected(hwnd syscall.Handle) {
	var titleBuf [512]uint16
	n, _, _ := procGetWindowTextW.Call(uintptr(hwnd), uintptr(unsafe.Pointer(&titleBuf[0])), uintptr(len(titleBuf)))
	base := "FFmpeg"
	if n > 0 {
		base = strings.TrimSpace(syscall.UTF16ToString(titleBuf[:n]))
	}
	if !strings.Contains(strings.ToLower(base), "[protected]") {
		newTitle, err := syscall.UTF16PtrFromString(base + " [FFmpeg - PROTECTED - do not close]")
		if err == nil {
			procSetWindowTextW.Call(uintptr(hwnd), uintptr(unsafe.Pointer(newTitle)))
		}
	}

	menu, _, _ := procGetSystemMenu.Call(uintptr(hwnd), 0)
	if menu == 0 {
		return
	}
	procAppendMenuW.Call(menu, uintptr(mfSeparator), 0, 0)
	disabledTxt, err := syscall.UTF16PtrFromString("Close disabled while FFmpeg is recording")
	if err != nil {
		return
	}
	procAppendMenuW.Call(menu, uintptr(mfString|mfDisabled), 0, uintptr(unsafe.Pointer(disabledTxt)))
	procDrawMenuBar.Call(uintptr(hwnd))
}

func armFFmpegConsoleCloseGuard(pid int) {
	go armConsoleClose(pid)
}

func armConsoleClose(pid int) {
	deadline := time.Now().Add(5 * time.Second)
	for time.Now().Before(deadline) {
		hwnd := findConsoleWindowForPID(pid)
		if hwnd != 0 {
			disableConsoleClose(hwnd)
			warnConsoleIsProtected(hwnd)
			return
		}
		time.Sleep(100 * time.Millisecond)
	}
}

// Run starts FFmpeg in a dedicated console window and applies the same close-button
// and title/menu protections as gui/recorder.py (Windows only). Only that FFmpeg child
// process console is touched; host apps (Tkinter, cmd shells) are unaffected.
func Run(argv []string) error {
	return RunInDir("", argv)
}

// RunInDir is like Run but sets the child process working directory (e.g. for lavfi movie=basename.ts).
func RunInDir(dir string, argv []string) error {
	if len(argv) == 0 {
		return fmt.Errorf("empty argv")
	}
	cmd := exec.Command(argv[0], argv[1:]...)
	cmd.Stdin = os.Stdin
	if dir != "" {
		cmd.Dir = dir
	}
	cmd.SysProcAttr = &syscall.SysProcAttr{
		CreationFlags: createNewConsole,
	}
	if err := cmd.Start(); err != nil {
		return err
	}
	armFFmpegConsoleCloseGuard(cmd.Process.Pid)
	err := cmd.Wait()
	return err
}
