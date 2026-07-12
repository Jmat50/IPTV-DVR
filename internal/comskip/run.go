package comskip

import (
	"fmt"
	"io"
	"os"
	"os/exec"
	"path/filepath"
)

// RunResult captures Comskip output sidecars.
type RunResult struct {
	OK       bool
	ExitCode int
	EDLPath  string
	TXTPath  string
}

// BuildArgv returns argv for finished-file Comskip analysis.
func BuildArgv(exe, ini, inputTS, outputDir string) []string {
	return []string{
		exe,
		fmt.Sprintf("--ini=%s", ini),
		fmt.Sprintf("--output=%s", outputDir),
		"-t",
		inputTS,
	}
}

func sidecarEDL(outputDir, stem string) string {
	return filepath.Join(outputDir, stem+".edl")
}

func sidecarTXT(outputDir, stem string) string {
	return filepath.Join(outputDir, stem+".txt")
}

func stringsTrimSuffixExt(path string) string {
	ext := filepath.Ext(path)
	if ext == "" {
		return path
	}
	return path[:len(path)-len(ext)]
}

// TryRun executes Comskip on a finished TS; sidecars are written under outputDir.
func TryRun(inputTS, explicitExe, explicitIni, outputDir string, log io.Writer) (RunResult, error) {
	exe := ResolveExe(explicitExe)
	ini := ResolveIni(explicitIni)
	if !fileExists(exe) || !fileExists(ini) {
		return RunResult{OK: false, ExitCode: 127}, fmt.Errorf("comskip not found")
	}
	if outputDir == "" {
		outputDir = ArtifactDir(inputTS)
	}
	if err := os.MkdirAll(outputDir, 0o755); err != nil {
		return RunResult{}, err
	}
	argv := BuildArgv(exe, ini, inputTS, outputDir)
	if log != nil {
		_, _ = fmt.Fprintf(log, "\n---\n$ %s\n", formatArgv(argv))
	}
	cmd := exec.Command(argv[0], argv[1:]...)
	configureCmd(cmd)
	cmd.Dir = outputDir
	stdout, err := cmd.StdoutPipe()
	if err != nil {
		return RunResult{}, err
	}
	cmd.Stderr = cmd.Stdout
	cmd.Stdin = nil
	if err := cmd.Start(); err != nil {
		return RunResult{}, err
	}
	armConsoleGuard(cmd)
	data, readErr := io.ReadAll(stdout)
	waitErr := cmd.Wait()
	if len(data) > 0 && log != nil {
		_, _ = log.Write(data)
	}
	if readErr != nil {
		return RunResult{}, readErr
	}
	code := 0
	if waitErr != nil {
		if ee, ok := waitErr.(*exec.ExitError); ok {
			code = ee.ExitCode()
		} else {
			return RunResult{}, waitErr
		}
	}
	stem := basenameStem(inputTS)
	edl := sidecarEDL(outputDir, stem)
	txt := sidecarTXT(outputDir, stem)
	edlOK := fileSize(edl) > 0
	txtOK := fileSize(txt) > 0
	return RunResult{
		OK:       code == 0 && (edlOK || txtOK),
		ExitCode: code,
		EDLPath:  edl,
		TXTPath:  txt,
	}, nil
}

func formatArgv(argv []string) string {
	out := ""
	for i, a := range argv {
		if i > 0 {
			out += " "
		}
		if containsSpace(a) {
			out += `"` + a + `"`
		} else {
			out += a
		}
	}
	return out
}

func containsSpace(s string) bool {
	for _, r := range s {
		if r == ' ' || r == '\t' {
			return true
		}
	}
	return false
}

func fileSize(path string) int64 {
	st, err := os.Stat(path)
	if err != nil {
		return 0
	}
	return st.Size()
}
