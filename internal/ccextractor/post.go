package ccextractor

import (
	"fmt"
	"io"
	"os"
	"os/exec"
	"path/filepath"
	"strings"
)

// BuildPostArgv returns CCExtractor argv for finished-file extraction.
func BuildPostArgv(ccExe, inputPath, outPath string) []string {
	return []string{
		ccExe,
		"-1",
		"--out=srt",
		"-o",
		outPath,
		inputPath,
	}
}

// TryExtractPostFromTS runs CCExtractor post-record extraction on a .ts output.
func TryExtractPostFromTS(outputPath, ccExe string, log io.Writer) (bool, error) {
	if !strings.EqualFold(filepath.Ext(outputPath), ".ts") {
		return false, nil
	}
	exe := ResolveExe(ccExe)
	if !fileExists(exe) {
		return false, fmt.Errorf("ccextractor not found at %s", exe)
	}
	outPath := SidecarSRTPath(outputPath)
	argv := BuildPostArgv(exe, outputPath, outPath)
	if log != nil {
		_, _ = fmt.Fprintf(log, "\n---\n$ %s\n", formatArgv(argv))
	}
	cmd := exec.Command(argv[0], argv[1:]...)
	configureLiveWorkerCmd(cmd)
	stdout, err := cmd.StdoutPipe()
	if err != nil {
		return false, err
	}
	cmd.Stderr = cmd.Stdout
	cmd.Stdin = nil
	if err := cmd.Start(); err != nil {
		return false, err
	}
	armLiveWorkerConsoleGuard(cmd)
	data, readErr := io.ReadAll(stdout)
	waitErr := cmd.Wait()
	if len(data) > 0 && log != nil {
		_, _ = log.Write(data)
	}
	if readErr != nil {
		_ = os.Remove(outPath)
		return false, readErr
	}
	if waitErr != nil {
		_ = os.Remove(outPath)
		return false, waitErr
	}
	return ValidateSRT(outPath), nil
}
