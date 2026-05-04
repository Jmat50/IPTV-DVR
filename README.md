# iptv-recorder

Super lightweight utility to record a live stream from an M3U playlist (or a direct URL) using FFmpeg stream copy. This allows for lossless capture of a live stream without re-encoding.

## Embedded FFmpeg (GUI)

The **Tkinter GUI** uses FFmpeg from `gui\ffmpeg\` (not committed to git). From the repo root:

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\download_ffmpeg.ps1
```

This downloads a Windows x64 **GPL** build from [BtbN/FFmpeg-Builds](https://github.com/BtbN/FFmpeg-Builds) (see [ffmpeg.org/legal.html](https://ffmpeg.org/legal.html)).

## Optional Post-Processing Tools

Two recurring job options are available in the GUI:

- `Output format` (choose native FFmpeg container: `ts`, `mp4`, `mkv`, `mov`)
- `Remove Commercials after Complete`

When commercial removal is enabled, the pipeline is:

1. Record stream directly to the selected output format
2. Generate `.edl` using Comskip
3. Run CommercialCleaner to produce `*_clean.mkv`

The original recording is never overwritten.

Set up dependencies:

```powershell
# CommercialCleaner binary
powershell -ExecutionPolicy Bypass -File .\scripts\download_commercial_cleaner.ps1

# Comskip from a local zip
powershell -ExecutionPolicy Bypass -File .\scripts\setup_comskip.ps1 -ZipPath "C:\Downloads\comskip.zip"
```

Expected paths:

- `tools\commercialcleaner\CommercialCleaner.exe`
- `tools\comskip\comskip.exe`
- optional: `tools\comskip\comskip.ini`

If installed elsewhere, `comskip` and `CommercialCleaner` are also resolved from `PATH`.

## Build standalone GUI (`gui\iptv-gui.exe`)

From the repo root (installs/updates PyInstaller via pip, then builds a **one-file, windowed** executable into **`gui\iptv-gui.exe`**). Close any running `gui\iptv-gui.exe` before rebuilding.

```powershell
cd "C:\Visual Studio\iptv-recorder"
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

## Tkinter GUI (recurring schedules + M3U sources)

- Add / edit / remove **M3U sources** (local file or `http(s)` URL).
- Define **recording jobs**: channel name, duration (`90m`, `1h30m`, …), output folder, filename pattern (`{date}`, `{time}`, `{channel}`), output format (`ts`, `mp4`, `mkv`, `mov`).
- Optional post-processing on each job:
  - **Remove Commercials after Complete** (uses Comskip + CommercialCleaner and creates a new cleaned file)
- **Daily** or **weekly** (weekday checkboxes) at a wall-clock time.
- **Save config** writes `config.json` (next to the app: repo root when using `python gui\main.py`, or the `gui\` folder when using `iptv-gui.exe`). **Sync Windows tasks** registers recurring tasks that run either  
  `pythonw.exe "…\gui\main.py" run-job --job-id <uuid>` (dev) or  
  `"…\gui\iptv-gui.exe" run-job --job-id <uuid>` (frozen build), with working directory set accordingly.
- **Run selected job now** starts the selected job immediately in background (handy for validation before waiting on a schedule).
- **Test 15s capture** uses the selected job’s source/channel.

Run (Python 3.10+ with Tk on Windows):

```powershell
cd "C:\Visual Studio\iptv-recorder"
python .\gui\main.py
```

## Requirements (Go CLI)

- **Windows** (primary target; FFmpeg invocation is standard and works elsewhere too).
- **FFmpeg** on `PATH`, or pass `--ffmpeg` to `ffmpeg.exe` (e.g. a [Gyan.dev build](https://www.gyan.dev/ffmpeg/builds/)).

## Install (from source)

```powershell
cd "C:\Visual Studio\iptv-recorder"
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

## Legal

Record only streams you are allowed to record. DRM-protected sources are not supported.
