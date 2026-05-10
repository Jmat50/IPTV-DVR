"""Episode-aware boundary estimation for long recordings."""

from __future__ import annotations

import re
import subprocess
from pathlib import Path

from paths import ffmpeg_exe, ffprobe_exe


def _probe_duration_seconds(input_path: Path) -> float:
    out = subprocess.check_output(
        [
            str(ffprobe_exe()),
            "-v",
            "error",
            "-show_entries",
            "format=duration",
            "-of",
            "default=noprint_wrappers=1:nokey=1",
            str(input_path),
        ],
        text=True,
        stderr=subprocess.STDOUT,
    ).strip()
    return float(out) if out else 0.0


def _run_signal_scan(input_path: Path) -> str:
    argv = [
        str(ffmpeg_exe()),
        "-hide_banner",
        "-i",
        str(input_path),
        "-filter_complex",
        "blackdetect=d=0.50:pix_th=0.10,metadata=mode=print:s=black|"
        "silencedetect=n=-35dB:d=0.50",
        "-an",
        "-f",
        "null",
        "-",
    ]
    p = subprocess.run(
        argv,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        stdin=subprocess.DEVNULL,
        text=True,
        check=False,
    )
    return p.stdout or ""


def detect_episode_blocks(
    input_path: Path,
    *,
    min_gap_seconds: float,
    min_black_seconds: float,
    min_silence_seconds: float,
) -> list[tuple[float, float]]:
    """Infer coarse episode blocks from black/silence transitions."""
    duration = _probe_duration_seconds(input_path)
    if duration <= 0:
        return [(0.0, 0.0)]
    if duration < max(2.0 * min_gap_seconds, 1500.0):
        return [(0.0, duration)]

    out = _run_signal_scan(input_path)
    black_re = re.compile(r"black_start:(?P<start>\d+(\.\d+)?)\s+black_end:(?P<end>\d+(\.\d+)?)")
    silence_start_re = re.compile(r"silence_start:\s*(?P<start>\d+(\.\d+)?)")
    silence_end_re = re.compile(r"silence_end:\s*(?P<end>\d+(\.\d+)?)\s*\|\s*silence_duration:\s*(?P<dur>\d+(\.\d+)?)")

    black_midpoints: list[float] = []
    for m in black_re.finditer(out):
        start = float(m.group("start"))
        end = float(m.group("end"))
        if end - start >= min_black_seconds:
            black_midpoints.append((start + end) / 2.0)

    pending_silence_start: float | None = None
    silence_midpoints: list[float] = []
    for line in out.splitlines():
        m_start = silence_start_re.search(line)
        if m_start:
            pending_silence_start = float(m_start.group("start"))
            continue
        m_end = silence_end_re.search(line)
        if m_end and pending_silence_start is not None:
            end = float(m_end.group("end"))
            dur = float(m_end.group("dur"))
            if dur >= min_silence_seconds:
                silence_midpoints.append((pending_silence_start + end) / 2.0)
            pending_silence_start = None

    candidates: list[float] = []
    for b in black_midpoints:
        near_silence = any(abs(b - s) <= 8.0 for s in silence_midpoints)
        if near_silence:
            candidates.append(b)

    candidates = sorted(x for x in candidates if min_gap_seconds <= x <= duration - min_gap_seconds)
    filtered: list[float] = []
    for c in candidates:
        if not filtered or c - filtered[-1] >= min_gap_seconds:
            filtered.append(c)

    blocks: list[tuple[float, float]] = []
    cursor = 0.0
    for boundary in filtered:
        if boundary - cursor >= min_gap_seconds:
            blocks.append((cursor, boundary))
            cursor = boundary
    if duration - cursor >= min_gap_seconds:
        blocks.append((cursor, duration))
    if not blocks:
        return [(0.0, duration)]
    return blocks
