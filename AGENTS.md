# AGENTS

## Purpose
Project-level guidance for AI/code agents working in this repo.

## Scope
- Applies to the entire repository.
- Keep changes minimal and focused on the requested behavior.

## Project Shape
- `gui/` is the Tkinter app and scheduled headless runner (`main.py run-job`).
- `cmd/iptvrecord/` is the Go CLI (`list-channels`, `record`, `schedule`).
- Scheduling is Windows Task Scheduler via PowerShell (`gui/scheduler_win.py`, `internal/winschedule/task.go`).

## Guardrails
- Preserve Windows-first behavior and Task Scheduler compatibility.
- Do not reintroduce `StartWhenAvailable` for recurring GUI tasks.
- Scheduled runs must respect the original recording window:
  - late but in-window => record remaining time
  - outside window => skip cleanly
- Keep manual "run now" behavior intact (no schedule-window enforcement unless scheduled metadata is present).
- Prefer ASCII-only edits unless file already uses Unicode.

## Validation Before Finishing
- Python changes: `python -m compileall gui`
- Go changes: `go test ./...`
- Scheduler-related changes: verify wake settings (`WakeToRun`) and no regression in `run-job` args.

## Notes
- Wake from sleep depends on OS power policy and hardware support.
- If wake readiness checks fail, prefer explicit user-facing warnings over silent fallback.
