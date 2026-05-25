# IPTV-DVR

Super lightweight utility to record a live stream from an M3U playlist (or a direct URL) using FFmpeg stream copy. This allows for lossless capture of a live stream without re-encoding.

## May 2026 update

- Manual early stop by closing the FFmpeg console is now treated as a supported success path when output data exists.
- Early-stopped `.ts` recordings now run a normalization/remux pass (timestamp repair + corruption-tolerant copy) before caption finalization.
- This was added to improve strict-player compatibility, especially VLC, for partial recordings.
- Caption sidecar behavior remains unchanged at a high level (`off`, `post_only`, `live_ccextractor`, `auto`) but docs now include updated troubleshooting for manual-stop and runtime dependency scenarios.

## Build (one command)

From the repo root, this script downloads missing bundled tools (skips FFmpeg and CCExtractor when already installed), runs `go test` / `go build`, and produces **`iptvrecord.exe`** and **`gui\iptv-gui.exe`**. Close any running `gui\iptv-gui.exe` before rebuilding.

```powershell
cd "C:\Visual Studio\IPTV-DVR"
powershell -ExecutionPolicy Bypass -File .\scripts\build.ps1
```

Optional flags: `-SkipGo`, `-SkipGui`, `-SkipCCExtractor`, `-SkipTests`, `-ForceFfmpeg`, `-ForceCCExtractor`. [`scripts/build_gui_exe.ps1`](scripts/build_gui_exe.ps1) calls the same script for backward compatibility.

Manual downloads (only if you are not using `build.ps1`):

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\download_ffmpeg.ps1
powershell -ExecutionPolicy Bypass -File .\scripts\download_ccextractor.ps1
```

## Bundled runtime tools (GUI)

The **Tkinter GUI** and frozen **`iptv-gui.exe`** expect:

| Tool | Path (dev) | Notes |
|------|------------|--------|
| FFmpeg | `gui\ffmpeg\ffmpeg.exe` | GPL build from [BtbN/FFmpeg-Builds](https://github.com/BtbN/FFmpeg-Builds); see [ffmpeg.org/legal.html](https://ffmpeg.org/legal.html). |
| CCExtractor (optional) | `gui\tools\ccextractor\ccextractor.exe` | Live `.srt` during `.ts` record; **Captions = auto** falls back to post-record FFmpeg if missing. Runtime must include sibling DLLs (`libgpac.dll`, FFmpeg DLLs, etc.). |

While recording, the GUI uses the Windows console safeguards described under [FFmpeg console and accidental close](#ffmpeg-console-and-accidental-close-windows).

Headless recording for Task Scheduler uses the same executable:

```text
iptv-gui.exe run-job --job-id <uuid>
```

(`config.json` and `logs\` live in the same folder as `iptv-gui.exe` when you run the frozen build.)

## FFmpeg console and accidental close (Windows)

**Scope:** safeguards apply **only** to the **Windows console window owned by each FFmpeg subprocess** that the app starts (located by FFmpeg's process ID + `ConsoleWindowClass`). Anything that **does not** terminate that FFmpeg process is **not** locked down—including the **Tkinter main window**, dialogs (`Job Editor`, channel picker, wake settings), and other apps (`VLC`, etc.). You may close the GUI and leave a **detached** `run-job`/`Run selected job now` recording running; FFmpeg still gets these protections inside its own console.

While that FFmpeg runs, User32 tweaks on **that console only**:

- Remove the Close item from its **system menu** and append a grayed/disabled entry: `Close disabled while FFmpeg is recording`.
- Append to the console **title**: ` [FFmpeg - PROTECTED - do not close]` unless a `[protected]` marker is already in the title (same logic in [`gui/recorder.py`](gui/recorder.py) and [`internal/winffmpeg`](internal/winffmpeg/run_windows.go)).

**Where this applies**

| Path | Mechanism |
|------|-----------|
| GUI **Test 15s capture**, **Run job** (`run-job`) | [`gui/recorder.py`](gui/recorder.py) `run_ffmpeg` starts FFmpeg with piped output and arms the guard on the FFmpeg child **PID** (polls up to ~5s for a `ConsoleWindowClass` window). |
| **`iptvrecord record`** and post-record caption extract | [`internal/winffmpeg`](internal/winffmpeg/run_windows.go) starts FFmpeg with **`CREATE_NEW_CONSOLE`** so the subprocess owns its console, applies the same User32 steps, then waits. |
| **macOS / Linux** (`iptvrecord` on non-Windows) | No console guard; plain `exec` with inherited stdio. |

**`iptvrecord` from `cmd` or PowerShell:** FFmpeg opens in a **separate** console window (so the guard can attach reliably). Your shell still prints the `running: ffmpeg ...` line; FFmpeg progress and messages appear in the FFmpeg window.

**Not prevented:** Task Manager, `taskkill`, killing the parent Python/go host, closing the Tk UI, or contexts where no FFmpeg console HWND appears (piped/streaming services).

### Early stop behavior (manual close)

Closing the FFmpeg console window to stop a recording early is a supported stop path.

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
- Optional per job: **Captions** mode (`off`, `auto`, `post_only`, `live_ccextractor`) — see [Closed captions](#closed-captions). Legacy configs with **download closed captions** enabled map to `auto`.

Run (Python 3.10+ with Tk on Windows):

```powershell
cd "C:\Visual Studio\IPTV-DVR"
python .\gui\main.py
```

## Requirements (Go CLI)

- **Windows** (primary target; FFmpeg invocation is standard and works elsewhere too).
- **FFmpeg** on `PATH`, or pass `--ffmpeg` to `ffmpeg.exe` (e.g. a [Gyan.dev build](https://www.gyan.dev/ffmpeg/builds/)).
- On **Windows**, `iptvrecord record` uses a **dedicated FFmpeg console** and the same close/title protection as the GUI ([FFmpeg console and accidental close](#ffmpeg-console-and-accidental-close-windows)).

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

On **Windows**, FFmpeg output appears in a **separate console** with the same accidental-close protection as the GUI ([details](#ffmpeg-console-and-accidental-close-windows)).

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
| `post_only` | After record: muxed subtitle copy, then FFmpeg embedded-608 extract to `.srt` (`.ts` only). |
| `live_ccextractor` | During record: CCExtractor stream mode (`--stream 15 -out=srt`) writes `.srt.partial` → validated `.srt` on finish; post-extract fallback if live output is empty. |
| `auto` | `live_ccextractor` when CCExtractor is installed and output is `.ts`; otherwise `post_only`. |

| Delivery | What you get in `.ts` | Sidecar |
|----------|------------------------|---------|
| **Embedded in video** (CEA-608 / ATSC A53) | CC stays in H.264 (VLC can show CC). | Live `.srt` while recording (CCExtractor) or post-extract `.srt` (FFmpeg). |
| **HLS subtitles** (WebVTT renditions) | Video+audio copy. | Live `.vtt` when ffprobe sees a subtitle stream; post muxed copy otherwise. |

**Practical takeaway:** Set job **Captions** to **auto**, run `download_ccextractor.ps1` once, and use `.ts` output for broadcast IPTV — you get a Jellyfin-ready `.srt` beside each recording without a manual FFmpeg step.

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
4. If needed, switch mode to `post_only` to force FFmpeg fallback sidecar generation after recording.

If a run was stopped manually and you see a `.failed.txt` marker:

1. Check `gui\logs\job_<job-id>.log` for FFmpeg exit code `3221225786` (Windows control-close / Ctrl+C path).
2. Verify whether a non-empty `.ts` was produced.
3. If a non-empty `.ts` exists, current behavior should keep that file and treat the stop as a successful early stop after TS normalization.

**Playlist tip:** If an M3U lists the same channel name more than once, the app matches **the first** matching entry (`#EXTINF` then URL).

## Legal

Record only streams you are allowed to record. DRM-protected sources are not supported.
