# IPTV-DVR

Super lightweight utility to record a live stream from an M3U playlist (or a direct URL) using FFmpeg stream copy. This allows for lossless capture of a live stream without re-encoding.

## Embedded FFmpeg (GUI)

The **Tkinter GUI** uses FFmpeg from `gui\ffmpeg\` (not committed to git). From the repo root:

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\download_ffmpeg.ps1
```

This downloads a Windows x64 **GPL** build from [BtbN/FFmpeg-Builds](https://github.com/BtbN/FFmpeg-Builds) (see [ffmpeg.org/legal.html](https://ffmpeg.org/legal.html)). While recording, the GUI uses the Windows console safeguards described under [FFmpeg console and accidental close](#ffmpeg-console-and-accidental-close-windows).

## Build standalone GUI (`gui\iptv-gui.exe`)

From the repo root (installs/updates PyInstaller via pip, then builds a **one-file, windowed** executable into **`gui\iptv-gui.exe`**). Close any running `gui\iptv-gui.exe` before rebuilding.

```powershell
cd "C:\Visual Studio\IPTV-DVR"
powershell -ExecutionPolicy Bypass -File .\scripts\build_gui_exe.ps1
```

Manual PyInstaller: use the same flags as [`scripts/build_gui_exe.ps1`](scripts/build_gui_exe.ps1) (notably `--paths .\gui` and `--hidden-import` for each module in `gui\` that `main.py` imports).

After building, place **`ffmpeg.exe`** where the app can find it:

- `gui\ffmpeg\ffmpeg.exe`

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

## Tkinter GUI (recurring schedules + M3U sources)

- Add / edit / remove **M3U sources** (local file or `http(s)` URL).
- Define **recording jobs**: channel name, duration (`90m`, `1h30m`, …), output folder, filename pattern (`{date}`, `{time}`, `{channel}`), output format (`ts`, `mp4`, `mkv`, `mov`).
- **Daily** or **weekly** (weekday checkboxes) at a wall-clock time.
- **Save config** writes `config.json` (next to the app: repo root when using `python gui\main.py`, or the `gui\` folder when using `iptv-gui.exe`). **Sync Windows tasks** registers recurring tasks that run either  
  `pythonw.exe "…\gui\main.py" run-job --job-id <uuid>` (dev) or  
  `"…\gui\iptv-gui.exe" run-job --job-id <uuid>` (frozen build), with working directory set accordingly.
- **Run selected job now** starts the selected job immediately in background (handy for validation before waiting on a schedule).
- **Test 15s capture** uses the selected job’s source/channel.
- Optional per job: **download closed captions when available** mirrors the CLI `--captions` flag (see [Closed captions](#closed-captions) below).

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

```powershell
cd "C:\Visual Studio\IPTV-DVR"
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

Add a sidecar when the manifest exposes subtitle streams (`--captions`):

```powershell
.\iptvrecord.exe record ... --out D:\rec.ts --captions
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

Recording uses **stream copy** (`-c copy`) for video and audio. Caption behavior depends on how the broadcaster delivers them:

| Delivery | What you get in `.ts` | Sidecar `.vtt` / `--captions` |
|----------|------------------------|------------------------------|
| **Embedded in video** (CEA-608 / ATSC A53 in H.264) | Caption data stays **in the video elementary stream**. Players such as VLC can show CC (**often CC1**; CC2-CC4 services may appear empty.) | Not required for embedded captions. Optional feature does little unless a separate subtitle track exists on the manifest or later in the file. |
| **HLS subtitles** (distinct WebVTT / subtitle playlists) | Main output is still video+audio copy; text is only in the `.ts` if you map that subtitle stream into the same multiplex (the app prefers a `.vtt` sidecar when enabled). | Enable **download closed captions** on the job, or `--captions` with the Go CLI; recording still succeeds when no subtitle stream is present (optional maps). |

**Practical takeaway:** Many IPTV feeds use **broadcast-style embedded CC**. You normally **do not need** a `.srt` or `.vtt` file unless you want subtitles as a separate file or the provider exposes them only as **HLS subtitle renditions**.

**Playlist tip:** If an M3U lists the same channel name more than once, the app matches **the first** matching entry (`#EXTINF` then URL).

## Legal

Record only streams you are allowed to record. DRM-protected sources are not supported.
