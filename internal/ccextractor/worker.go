package ccextractor

import (
	"bufio"
	"fmt"
	"io"
	"os"
	"os/exec"
	"strings"
	"time"
)

// BuildArgv returns CCExtractor argv for stream-mode SRT extraction.
func BuildArgv(ccExe, inputPath, partialOut string) []string {
	return []string{
		ccExe,
		"-s",
		"-out=srt",
		inputPath,
		"-o",
		partialOut,
	}
}

// Worker runs CCExtractor against a growing recording file.
type Worker struct {
	recordingPath string
	partialPath   string
	finalPath     string
	ccExe         string
	cmd           *exec.Cmd
	log           io.Writer
}

// NewWorker constructs a worker for outputPath (recording file).
func NewWorker(outputPath, ccExe string, log io.Writer) *Worker {
	if ccExe == "" {
		ccExe = ResolveExe("")
	}
	return &Worker{
		recordingPath: outputPath,
		partialPath:   PartialSRTPath(outputPath),
		finalPath:     SidecarSRTPath(outputPath),
		ccExe:         ccExe,
		log:           log,
	}
}

func (w *Worker) appendLog(msg string) {
	if w.log == nil {
		return
	}
	_, _ = fmt.Fprint(w.log, msg)
}

// Start waits for the recording file then launches CCExtractor in stream mode.
func (w *Worker) Start() error {
	if !fileExists(w.ccExe) {
		return fmt.Errorf("ccextractor not found at %s", w.ccExe)
	}
	deadline := time.Now().Add(120 * time.Second)
	for time.Now().Before(deadline) {
		st, err := os.Stat(w.recordingPath)
		if err == nil && st.Size() > 0 {
			break
		}
		time.Sleep(500 * time.Millisecond)
	}
	st, err := os.Stat(w.recordingPath)
	if err != nil || st.Size() == 0 {
		return fmt.Errorf("timed out waiting for recording file %s", w.recordingPath)
	}
	_ = os.Remove(w.partialPath)
	argv := BuildArgv(w.ccExe, w.recordingPath, w.partialPath)
	w.appendLog(fmt.Sprintf("\n---\n$ %s\n", formatArgv(argv)))
	cmd := exec.Command(argv[0], argv[1:]...)
	stdout, err := cmd.StdoutPipe()
	if err != nil {
		return err
	}
	cmd.Stderr = cmd.Stdout
	cmd.Stdin = nil
	if err := cmd.Start(); err != nil {
		return err
	}
	w.cmd = cmd
	go w.drain(stdout)
	return nil
}

func (w *Worker) drain(r io.Reader) {
	sc := bufio.NewScanner(r)
	for sc.Scan() {
		w.appendLog(sc.Text() + "\n")
	}
}

// Stop terminates CCExtractor and promotes partial output to the final .srt.
func (w *Worker) Stop() (bool, error) {
	if w.cmd != nil && w.cmd.Process != nil {
		_ = w.cmd.Process.Signal(os.Interrupt)
		done := make(chan error, 1)
		go func() { done <- w.cmd.Wait() }()
		select {
		case <-done:
		case <-time.After(15 * time.Second):
			_ = w.cmd.Process.Kill()
			<-done
		}
	}
	w.cmd = nil
	if FinalizePartial(w.partialPath, w.finalPath) {
		return true, nil
	}
	_ = os.Remove(w.partialPath)
	return false, nil
}

func formatArgv(argv []string) string {
	var b strings.Builder
	for i, a := range argv {
		if i > 0 {
			b.WriteByte(' ')
		}
		if strings.ContainsAny(a, " \t\"") {
			b.WriteByte('"')
			b.WriteString(a)
			b.WriteByte('"')
		} else {
			b.WriteString(a)
		}
	}
	return b.String()
}
