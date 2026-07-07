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
- On **Windows**, preserve parity between `gui/console_guard.py`, `gui/recorder.py`, `gui/caption_worker.py` (live CCExtractor), `gui/comskip_worker.py` (post-record Comskip), and `internal/winffmpeg` / `internal/ccextractor` / `internal/comskip` (close menu, title suffix, disabled menu line, ~5s HWND poll / `CREATE_NEW_CONSOLE` for Go).

## FFmpeg console guard (Windows)
- **`gui/recorder.py` `run_ffmpeg`:** After `Popen`, spawn a short-lived poll that finds the **FFmpeg child** `ConsoleWindowClass` HWND (matched by FFmpeg's PID) and applies User32 (`GetSystemMenu`/`DeleteMenu` SC_CLOSE, `SetWindowTextW`, `AppendMenuW`). Shared helpers live in `gui/console_guard.py`.
- **`gui/caption_worker.py` `LiveCaptionWorker`:** Live CCExtractor starts with **`CREATE_NEW_CONSOLE`** on Windows and uses the same guard helpers with **`GUARD_CCEXTRACTOR`** (title/menu text for caption extraction).
- **`internal/winffmpeg`:** Used by `iptvrecord record` and `TryExtractCaptionsFromTS`; starts FFmpeg with `CREATE_NEW_CONSOLE` then runs `ArmConsoleCloseGuard(..., GuardFFmpeg)`.
- **`internal/ccextractor` live worker:** On Windows, starts CCExtractor with `CREATE_NEW_CONSOLE` and `ArmConsoleCloseGuard(..., GuardCCExtractor)`.
- **`gui/comskip_worker.py` / `internal/comskip`:** Post-record Comskip starts with `CREATE_NEW_CONSOLE` on Windows and uses `GUARD_COMSKIP` / `GuardComskip`.
- **Never** attach this guard to the Tkinter GUI, **Job Editor**, or unrelated top-level HWNDs. Detached **`run-job`** recordings must keep running if the user closes the GUI; Tk `WM_DELETE_WINDOW` remains an ordinary quit (aside from persist/sync confirmations).
- **Intent:** accidental-click protection targets **FFmpeg, CCExtractor, and Comskip consoles** tied to capture continuity; post-record CCExtractor file-mode extraction uses the same guarded console on Windows.
- Changing either path: keep behavior aligned and update [README.md](README.md) "Recording console and accidental close" if user-visible behavior changes.
- Non-Windows: `winffmpeg` falls through to plain `exec` (no guard).
- Manual user stop contract: when FFmpeg exits with a user-stop code (for example `STATUS_CONTROL_C_EXIT`) but output has data, treat run as successful early stop after repair/finalize; do not leave a false failure marker.

## Validation Before Finishing
- Python changes: `python -m compileall gui`
- Go changes: `go test ./...`
- Scheduler-related changes: verify wake settings (`WakeToRun`) and no regression in `run-job` args.

## Captions
- Recordings use FFmpeg **stream copy** (`-c copy`) for video/audio. **CEA-608 / ATSC A53** in H.264 stay in the `.ts` unless a sidecar is requested.
- **Caption modes** (`off`, `post_only`, `live_ccextractor`): jobs store `caption_mode`; legacy `download_captions: true` and legacy `auto` migrate to `post_only`. Use **`live_ccextractor`** explicitly for tail-follow extraction during recording.
- Jobs also store `caption_post_processor` (`ffmpeg` or `ccextractor`) for post-record extraction. In GUI, this selector is editable only for `post_only`.
- Jobs may set `post_scan_repair: true` to scan/repair finished `.ts` files after recording; when false, skip post-record TS repair entirely.
- **Live path (optional):** `gui/caption_worker.py` and `internal/ccextractor` run `ccextractor --input ts --stream 15 --out srt -o <partial> <growing.ts>` only when mode is **`live_ccextractor`**. **CCExtractor 0.96.x** rejects that invocation (inverted `--stream` validation); `live_ccextractor` falls back to post-only until a fixed runtime is bundled.
- **HLS subtitle renditions:** when ffprobe sees `0:s:0?`, dual-output still writes `.vtt` during record (`-c copy`).
- **Post-record extraction:** when a sidecar is still needed, use the selected post processor:
  - `ffmpeg`: muxed `-map 0:s:0?` copy, then `movie='basename.ts'[out+subcc]` → `.srt`
  - `ccextractor`: file-mode `ccextractor --out=srt -o <basename.srt> <basename.ts>`
- Install CCExtractor: `scripts/download_ccextractor.ps1` (optional; required for live mode). Runtime must include `ccextractor.exe` and sibling DLLs (notably `libgpac.dll`).
- Build/install scripts should treat CCExtractor as present only when runtime DLLs are present; avoid skipping a partial install.
- For `.ts` outputs that end non-zero with bytes present, run repair/remux before caption finalize:
  - `-fflags +genpts+discardcorrupt`
  - `-err_detect ignore_err`
  - `-avoid_negative_ts make_zero`
  - `-bsf:v setts=pts=N/(avg_frame_rate*TB):dts=N/(avg_frame_rate*TB)`
- **Skip TS repair** when the recording is already complete (decode probe passes) or when A/V durations diverge by >5s (e.g. after a prior setts remux). Use `reprocess_captions()` / post-only finalize for caption-only reruns — never repair on that path.
- Keep Python/Go parity for manual-stop detection (`3221225786`, `-1073741510`, `130`) and "keep partial recording" behavior.
- If embedded CC is visible in VLC but `.srt` is missing, inspect `gui/logs/job_<id>.log` for:
  - `captions: live worker produced no valid SRT`
  - `a value is required for '--stream <STREAM>'` (wrong worker args)
  - `libgpac.dll was not found` (broken runtime install)
  - HLS input failures (`Error reading HTTP response: End of file`, parse playlist errors)
- M3U `find_channel` resolves **exact name first**, otherwise **unique substring**. Duplicate `#EXTINF` lines with the same title use the **first** URL line in playlist order.

## Comskip (commercial detection)
- Jobs store `comskip_enabled: bool` (default false). GUI checkbox: **Post - Detect commercials (Comskip)**.
- Post-record order: `maybe_post_scan_repair` -> `finalize_captions` -> `maybe_run_comskip` (`gui/comskip_finalize.py`, `internal/comskip/finalize.go`).
- Comskip applies only to `.ts` output. Non-fatal on failure (log and continue).
- Install: `scripts/download_comskip.ps1` (Windows zip from kaashoek.com). Runtime: `comskip.exe` + `comskip.ini` + sibling DLLs under `gui/tools/comskip/`.
- Multi-episode: `gui/episode_boundaries.py` segments long recordings; per-segment Comskip + merge in `gui/comskip_merge.py`.
- Sidecars: `.edl`, `.txt`, `.chapters.ffmeta`, `.comskip.json` beside the recording.
- Go CLI parity: `iptvrecord record --comskip`.

## Notes
- Wake from sleep depends on OS power policy and hardware support.
- If wake readiness checks fail, prefer explicit user-facing warnings over silent fallback.
