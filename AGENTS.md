# AGENTS

## Purpose
Project-level guidance for AI/code agents working in this repo.

## Scope
- Applies to the entire repository.
- Keep changes minimal and focused on the requested behavior.

## Project Shape
- `gui/` is the Tkinter app and scheduled headless runner (`main.py run-job`).
- `cmd/iptvrecord/` is the Go CLI (`list-channels`, `record`, `schedule`).
- `internal/winffmpeg/` — Windows FFmpeg launcher with the same console close/title guard as `gui/recorder.py` (see **FFmpeg console guard (Windows)** below).
- Scheduling is Windows Task Scheduler via PowerShell (`gui/scheduler_win.py`, `internal/winschedule/task.go`).

## Guardrails
- Preserve Windows-first behavior and Task Scheduler compatibility.
- Do not reintroduce `StartWhenAvailable` for recurring GUI tasks.
- Scheduled runs must respect the original recording window:
  - late but in-window => record remaining time
  - outside window => skip cleanly
- Keep manual "run now" behavior intact (no schedule-window enforcement unless scheduled metadata is present).
- Prefer ASCII-only edits unless file already uses Unicode.
- On **Windows**, preserve parity between `gui/recorder.py` FFmpeg console protection and `internal/winffmpeg` (close menu, title suffix, disabled "Close disabled..." line, ~5s HWND poll / `CREATE_NEW_CONSOLE` for Go).

## FFmpeg console guard (Windows)
- **`gui/recorder.py` `run_ffmpeg`:** After `Popen`, spawn a short-lived poll that finds the **FFmpeg child** `ConsoleWindowClass` HWND (matched by FFmpeg's PID) and applies User32 (`GetSystemMenu`/`DeleteMenu` SC_CLOSE, `SetWindowTextW`, `AppendMenuW`).
- **`internal/winffmpeg`:** Used by `iptvrecord record` and `TryExtractCaptionsFromTS`; starts FFmpeg with `CREATE_NEW_CONSOLE` then runs the same guard on the FFmpeg child's PID.
- **Never** attach this guard to the Tkinter GUI, **Job Editor**, or unrelated top-level HWNDs. Detached **`run-job`** recordings must keep running if the user closes the GUI; Tk `WM_DELETE_WINDOW` remains an ordinary quit (aside from persist/sync confirmations).
- **Intent:** accidental-click protection targets **only** FFmpeg consoles tied to capture continuity; subtitle-extract FFmpeg runs are short-lived but still use the same guard while they run.
- Changing either path: keep behavior aligned and update [README.md](README.md) "FFmpeg console and accidental close" if user-visible behavior changes.
- Non-Windows: `winffmpeg` falls through to plain `exec` (no guard).

## Validation Before Finishing
- Python changes: `python -m compileall gui`
- Go changes: `go test ./...`
- Scheduler-related changes: verify wake settings (`WakeToRun`) and no regression in `run-job` args.

## Captions
- Recordings use FFmpeg **stream copy** (`-c copy`) for video/audio. **CEA-608 / ATSC A53 closed captions carried inside the H.264 bitstream** normally stay embedded in the output `.ts`; no sidecar is required for players (e.g. VLC) that decode CC from the video track.
- **Separate HLS subtitle renditions** (`#EXT-X-MEDIA:TYPE=SUBTITLES`, WebVTT segments) are optional: the job/CLI **download captions** path can write a `.vtt` sidecar when ffprobe sees a subtitle stream on the input URL, plus a post-record extract when the finished `.ts` exposes a muxed subtitle stream. It does **not** re-embed WebVTT into the video elementary stream by default.
- **Post-record extraction of 608-from-video** (e.g. `lavfi movie=...[out+subcc]`) is not in the primary record path unless explicitly implemented later; embedded-in-video preservation is satisfied by `-c copy` when the provider uses SEI/carried captions.
- M3U `find_channel` resolves **exact name first**, otherwise **unique substring**. Duplicate `#EXTINF` lines with the same title use the **first** URL line in playlist order.

## Notes
- Wake from sleep depends on OS power policy and hardware support.
- If wake readiness checks fail, prefer explicit user-facing warnings over silent fallback.
