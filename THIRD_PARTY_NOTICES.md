# Third-party binaries

## FFmpeg

When you run `scripts/download_ffmpeg.ps1`, a Windows x64 **FFmpeg** binary is placed under `ffmpeg/ffmpeg.exe`.

- Project: https://ffmpeg.org/
- Typical upstream Windows builds: https://github.com/BtbN/FFmpeg-Builds (GPL variant used by the download script)
- License: LGPL / GPL (see upstream `LICENSE.txt` inside the downloaded archive and https://ffmpeg.org/legal.html)

How IPTV-DVR starts FFmpeg (e.g. dedicated Windows console, accidental-close mitigation) is described in [README.md](README.md) under **FFmpeg console and accidental close (Windows)**.
