# IPTV-DVR

Super lightweight utility to record a live stream from an M3U playlist (or a direct URL) using FFmpeg stream copy. This allows for lossless capture of a live stream without re-encoding.

## May 2026 update

- Manual early stop (for example Ctrl+C in the FFmpeg console, or ending the FFmpeg process) is now treated as a supported success path when output data exists.
- Early-stopped `.ts` recordings now run a normalization/remux pass (timestamp repair + corruption-tolerant copy) before caption finalization.
- This was added to improve strict-player compatibility, especially VLC, for partial recordings.
- Caption sidecar behavior (`off`, `post_only`, `live_ccextractor`) with optional per-job post scan/repair.
- Optional per-job Comskip commercial detection (`.ts` only) with chapter sidecars.

## Build (one command)

From the repo root, this script downloads missing bundled tools (skips FFmpeg and CCExtractor when already installed), runs `go test` / `go build`, and produces **`iptvrecord.exe`** and **`gui\iptv-gui.exe`**. Close any running `gui\iptv-gui.exe` before rebuilding.

```powershell
cd "C:\Visual Studio\IPTV-DVR"
powershell -ExecutionPolicy Bypass -File .\scripts\build.ps1
```

Optional flags: `-SkipGo`, `-SkipGui`, `-SkipCCExtractor`, `-SkipComskip`, `-SkipTests`, `-ForceFfmpeg`, `-ForceCCExtractor`, `-ForceComskip`. [`scripts/build_gui_exe.ps1`](scripts/build_gui_exe.ps1) calls the same script for backward compatibility.

Manual downloads (only if you are not using `build.ps1`):

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\download_ffmpeg.ps1
powershell -ExecutionPolicy Bypass -File .\scripts\download_ccextractor.ps1
powershell -ExecutionPolicy Bypass -File .\scripts\download_comskip.ps1
```

## Bundled runtime tools (GUI)

The **Tkinter GUI** and frozen **`iptv-gui.exe`** expect:

| Tool | Path (dev) | Notes |
|------|------------|--------|
| FFmpeg | `gui\ffmpeg\ffmpeg.exe` | GPL build from [BtbN/FFmpeg-Builds](https://github.com/BtbN/FFmpeg-Builds); see [ffmpeg.org/legal.html](https://ffmpeg.org/legal.html). |
| CCExtractor (optional) | `gui\tools\ccextractor\ccextractor.exe` | Post-record `.srt` via **Captions = post_only** + **Post = ccextractor**. Runtime must include sibling DLLs (`libgpac.dll`, FFmpeg DLLs, etc.). |
| Comskip (optional) | `gui\tools\comskip\comskip.exe` | Post-record commercial detection via **Post - Detect commercials (Comskip)** (`.ts` jobs only). Requires `comskip.ini` beside the exe. |

While recording, **FFmpeg** and **live CCExtractor** subprocesses started by the app may receive the Windows console safeguards described under [Recording console and accidental close](#recording-console-and-accidental-close-windows). The Tkinter GUI itself is never modified.

Headless recording for Task Scheduler uses the same executable:

```text
iptv-gui.exe run-job --job-id <uuid>
```

(`config.json` and `logs\` live in the same folder as `iptv-gui.exe` when you run the frozen build.)

## Recording console and accidental close (Windows)

On Windows, the app tries to prevent **accidental** closure of **FFmpeg** and **live CCExtractor** recording consoles (the `ConsoleWindowClass` window owned by each child process, found by PID). It does **not** lock down unrelated windows.

### Protected vs not protected

| Window / process | Protected from accidental close? |
|------------------|----------------------------------|
| **FFmpeg recording console** (when guard attaches) | Yes — system-menu **Close** removed; title shows `[FFmpeg - PROTECTED - do not close]`; grayed menu line `Close disabled while FFmpeg is recording` |
| **Live CCExtractor console** (`live_ccextractor` mode, when guard attaches) | Yes — title shows `[CCExtractor - PROTECTED - do not close]`; grayed menu line `Close disabled while CCExtractor is extracting captions` |
| **Tkinter main window** (`iptv-gui.exe` / `python gui\main.py`) | No — close/quit works normally (aside from save/sync prompts on exit) |
| **GUI dialogs** (Job Editor, channel picker, wake settings, etc.) | No |
| **Post-record CCExtractor** (file-mode extraction) | Yes — dedicated console with the same CCExtractor guard when the HWND appears |
| **Your shell** (cmd/PowerShell where you launched `iptvrecord`) | No |
| **Other apps** (VLC, Explorer, etc.) | No |

You may close the GUI and leave a **detached** **Run selected job now** or scheduled `run-job` recording running; stopping the recording means ending the **FFmpeg** (and live **CCExtractor**, if running) processes, not closing the Tk window.

### Where the guard runs

| Path | How the process is started | Console behavior |
|------|---------------------------|------------------|
| GUI **`run-job`**, **Test 15s capture**, caption repair/extract FFmpeg | [`gui/recorder.py`](gui/recorder.py) `run_ffmpeg` — stdout/stderr piped to log files | FFmpeg may open a console HWND; guard polls up to ~5s and applies User32 tweaks **if** that HWND exists |
| GUI / **`run-job`** live and post CCExtractor | [`gui/caption_worker.py`](gui/caption_worker.py) / [`gui/recorder.py`](gui/recorder.py) `run_tool` — **`CREATE_NEW_CONSOLE`**, stdout piped to logs | Dedicated CCExtractor console; guard attaches to that window |
| **`iptvrecord record`** FFmpeg and Go post-record caption FFmpeg | [`internal/winffmpeg`](internal/winffmpeg/run_windows.go) — **`CREATE_NEW_CONSOLE`** | Dedicated visible FFmpeg console; guard attaches to that window |
| **`iptvrecord record`** live and post CCExtractor | [`internal/ccextractor`](internal/ccextractor/worker.go), [`post.go`](internal/ccextractor/post.go) — **`CREATE_NEW_CONSOLE`** | Dedicated CCExtractor console; guard attaches to that window |
| **macOS / Linux** | Plain `exec` / piped subprocess | No console guard |

Shared User32 logic in [`gui/console_guard.py`](gui/console_guard.py), [`internal/winffmpeg`](internal/winffmpeg/guard_windows.go), and live worker startup in [`internal/ccextractor`](internal/ccextractor/worker_start_windows.go). Short-lived FFmpeg used only for post-record caption extract or TS repair gets the same guard **while that FFmpeg process runs**.

**`iptvrecord` from cmd/PowerShell:** your shell prints `running: ffmpeg ...`; FFmpeg itself runs in its **own** console window (not in the shell window).

**Still allowed (not blocked by the guard):** ending FFmpeg or live CCExtractor with **Ctrl+C** in its console, Task Manager, `taskkill`, or killing the parent Python/Go host. If no child console HWND appears within ~5s, the guard never attaches (recording still works; output goes to logs).

### Early stop behavior

Ending the FFmpeg recording process early is supported (for example **Ctrl+C** in the FFmpeg console, not the disabled system-menu Close).

- If FFmpeg exits with a user-stop code (Windows `STATUS_CONTROL_C_EXIT`, etc.) **and** output bytes exist, the run is treated as a successful early stop.
- The app performs a best-effort TS normalization pass before finalizing sidecars:
  - `-fflags +genpts+discardcorrupt`
  - `-err_detect ignore_err`
  - `-avoid_negative_ts make_zero`
  - video timestamp rewrite via `setts` bitstream filter (using probed `avg_frame_rate`)
- This specifically improves strict-player compatibility (for example, VLC) for early-stopped `.ts` recordings.

## Tkinter GUI (recurring schedules + M3U sources)

- Add / edit / remove **M3U sources** (local file or `http(s)` URL).
- Define **recording jobs**: channel name, duration (`90m`, `1h30m`, …), output folder, filename pattern (`{date}`, `{time}`, `{channel}`), output format (`ts`, `mp4`, `mkv`, `mov`).
- **Daily** or **weekly** (weekday checkboxes) at a wall-clock time.
- **Save config** writes `config.json` (next to the app: repo root when using `python gui\main.py`, or the `gui\` folder when using `iptv-gui.exe`). **Sync Windows tasks** registers recurring tasks that run either  
  `pythonw.exe "…\gui\main.py" run-job --job-id <uuid>` (dev) or  
  `"…\gui\iptv-gui.exe" run-job --job-id <uuid>` (frozen build), with working directory set accordingly.
- **Run selected job now** starts the selected job immediately in background (handy for validation before waiting on a schedule).
- **Test 15s capture** uses the selected job’s source/channel.
- Optional per job: **Captions** mode (`off`, `post_only`, `live_ccextractor`) — see [Closed captions](#closed-captions). Legacy `auto` / **download closed captions** load as `post_only`.

Run (Python 3.10+ with Tk on Windows):

```powershell
cd "C:\Visual Studio\IPTV-DVR"
python .\gui\main.py
```

## Requirements (Go CLI)

- **Windows** (primary target; FFmpeg invocation is standard and works elsewhere too).
- **FFmpeg** on `PATH`, or pass `--ffmpeg` to `ffmpeg.exe` (e.g. a [Gyan.dev build](https://www.gyan.dev/ffmpeg/builds/)).
- On **Windows**, `iptvrecord record` starts FFmpeg in a **dedicated console** and applies the same User32 guard on that FFmpeg window ([Recording console and accidental close](#recording-console-and-accidental-close-windows)). Live CCExtractor uses the same guard when enabled.

## Install (from source)

Use [`scripts/build.ps1`](#build-one-command) for `iptvrecord.exe` and the GUI, or build the CLI only:

```powershell
go build -o iptvrecord.exe ./cmd/iptvrecord
```

Copy `iptvrecord.exe` anywhere you like.

## Commands

### List channels

```powershell
.\iptvrecord.exe list-channels --m3u C:\path\playlist.m3u
.\iptvrecord.exe list-channels --m3u "https://example.com/playlist.m3u"
```

### Record now

On **Windows**, FFmpeg and live CCExtractor run in **separate consoles** when applicable; accidental-close protection applies to those child windows only ([details](#recording-console-and-accidental-close-windows)).

From playlist (match channel name exactly, case-insensitive, or a **unique** substring):

```powershell
.\iptvrecord.exe record --m3u C:\path\playlist.m3u --channel "BBC One" --duration 90m --out D:\recordings\show.ts
```

Direct URL (no M3U):

```powershell
.\iptvrecord.exe record --url "http://example.com/stream" --duration 1h --out D:\rec.ts
```

Optional overrides:

```powershell
.\iptvrecord.exe record ... --ffmpeg "C:\ffmpeg\bin\ffmpeg.exe" --user-agent "VLC/3.0" --referer "https://provider/"
```

Enable captions (`--captions` is shorthand for `--caption-mode auto`):

```powershell
.\iptvrecord.exe record ... --out D:\rec.ts --captions
.\iptvrecord.exe record ... --out D:\rec.ts --caption-mode live_ccextractor --ccextractor C:\tools\ccextractor.exe
```

### Schedule once (Task Scheduler)

Registers a **one-time** Windows scheduled task that runs the same `record` command at `--at`:

```powershell
.\iptvrecord.exe schedule --at 2026-05-02T20:00:00-05:00 --m3u C:\path\playlist.m3u --channel "BBC One" --duration 90m --out D:\rec.ts
```

Local time without zone:

```powershell
.\iptvrecord.exe schedule --at 2026-05-02T20:00:00 --m3u ... --channel ... --duration 90m --out ...
```

Optional task name:

```powershell
.\iptvrecord.exe schedule --task-name "MyRecording" --at ...
```

## Output format

`.ts` (MPEG-TS) is recommended with `-c copy` for broad compatibility. To remux to MP4 without re-encoding (when the bitstream allows):

```powershell
ffmpeg -i recorded.ts -c copy recorded.mp4
```

## Closed captions

Recording uses **stream copy** (`-c copy`) for video and audio. Caption behavior depends on mode and how the broadcaster delivers captions:

| Mode | Behavior |
|------|----------|
| `off` | No sidecar work. |
| `post_only` | After record: run the selected post processor (`ffmpeg` or `ccextractor`) to produce `.srt` (`.ts` only). |
| `live_ccextractor` | During record: CCExtractor stream mode (`--stream 15 -out=srt`) writes `.srt.partial` → validated `.srt` on finish. |

Legacy configs with `caption_mode: auto` or `download_captions: true` load as **`post_only`**.

| Delivery | What you get in `.ts` | Sidecar |
|----------|------------------------|---------|
| **Embedded in video** (CEA-608 / ATSC A53) | CC stays in H.264 (VLC can show CC). | Post-extract `.srt` after recording (FFmpeg or CCExtractor). |
| **HLS subtitles** (WebVTT renditions) | Video+audio copy. | Live `.vtt` when ffprobe sees a subtitle stream; post muxed copy otherwise. |

**Post processor selector:** In Job Editor, choose **Post** = `ffmpeg` or `ccextractor`. This dropdown is editable only when **Captions** mode is `post_only`.

**Post scan/repair:** Optional per-job checkbox **Post - Scan for broken stream/repair**. When checked, the finished `.ts` is scanned after recording and repaired only if issues are detected. When unchecked, no post-record TS repair runs.

## Commercial detection (Comskip)

Optional per-job checkbox **Post - Detect commercials (Comskip)** runs after recording completes (and after optional TS repair and caption finalize). The original `.ts` is never modified. Comskip artifacts (including `.logo` files) are written under `logs/comskip_work/<recording-stem>/`, not beside the recording.

| Artifact | Purpose |
|----------|---------|
| `<stem>.edl` | Kodi/MPlayer-style commercial breaks (`edl_skip_field=3`) |
| `<stem>.txt` | Comskip frame cutlist (v2 header) |
| `<stem>.chapters.ffmeta` | FFmpeg chapter metadata (episode blocks + commercial markers) |
| `<stem>.comskip.json` | Merge manifest (mode, segments, fps) |
| `<stem>.logo.txt` | Comskip logo mask (when logo detection runs) |

**Requirements:** Output format must be **`.ts`**. Install Comskip with:

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\download_comskip.ps1
```

Bundled layout: `gui\tools\comskip\comskip.exe` + `comskip.ini` + DLLs from the official Windows zip.

**Multi-episode recordings:** Long back-to-back blocks are pre-segmented using broadcast-style black/silence gaps plus duration heuristics. Comskip runs per segment when multiple episodes are detected; commercial markers are merged onto the full timeline.

**CLI equivalent:** `iptvrecord record ... --comskip` (`.ts` output only).

**Failure contract:** Comskip errors are logged to the job log and do not fail the recording job.

**Practical takeaway:** Set job **Captions** to **post_only**, select your preferred **Post** processor (`ccextractor` recommended for broadcast `.ts`), and use `.ts` output for automated `.srt` sidecar generation after each recording.

**Caption/post CLI flags:** `--caption-post-processor ffmpeg|ccextractor` (applies to post-record extraction in `post_only`). `--post-scan-repair` enables the optional TS scan/repair step.

## Caption troubleshooting

If you can see embedded CC in playback but no `.srt` sidecar appears:

1. Check the job log: `gui\logs\job_<job-id>.log`.
2. Look for these signatures:
   - `captions: live worker produced no valid SRT`  
     (live worker ran, but no valid timed-caption output was produced)
   - `a value is required for '--stream <STREAM>'`  
     (CCExtractor invocation mismatch; worker args must use `--stream 15`)
   - `libgpac.dll was not found`  
     (CCExtractor runtime install incomplete; rerun `scripts\download_ccextractor.ps1`)
   - `Error reading HTTP response: End of file` / HLS parse errors  
     (provider/network instability; FFmpeg reconnect logic retries but long failures can still abort)
3. Confirm output format is `.ts` for live embedded-caption extraction.
4. If needed, switch mode to `post_only`, then set **Post** to either `ffmpeg` or `ccextractor` to force that post extractor after recording.

If a run was stopped manually and you see a `.failed.txt` marker:

1. Check `gui\logs\job_<job-id>.log` for FFmpeg exit code `3221225786` (Windows control-close / Ctrl+C path).
2. Verify whether a non-empty `.ts` was produced.
3. If a non-empty `.ts` exists, current behavior should keep that file and treat the stop as a successful early stop after TS normalization.

**Playlist tip:** If an M3U lists the same channel name more than once, the app matches **the first** matching entry (`#EXTINF` then URL).

## Legal

Record only streams you are allowed to record. DRM-protected sources are not supported.
