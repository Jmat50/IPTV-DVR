"""Detect episode boundaries in long MPEG-TS recordings."""

from __future__ import annotations

import re
import subprocess
from dataclasses import dataclass
from pathlib import Path

from duration_parse import parse_duration
from paths import ffmpeg_exe
from recorder import probe_stream_duration

from comskip_merge import EpisodeSegment

_BLACK_LINE = re.compile(
    r"black_start:([0-9.]+)\s+black_end:([0-9.]+)\s+black_duration:([0-9.]+)"
)
_SILENCE_START = re.compile(r"silence_start:\s*([0-9.]+)")
_SILENCE_END = re.compile(r"silence_end:\s*([0-9.]+)")

MIN_EPISODE_SEC = 10 * 60
MAX_EPISODE_SEC = 90 * 60
MIN_BLACK_DURATION = 2.0
CANDIDATE_LENGTHS_SEC = (22 * 60, 30 * 60, 44 * 60, 60 * 60)


@dataclass(frozen=True)
class _GapCandidate:
    time_sec: float
    score: float


def _log(log_file: Path | None, message: str) -> None:
    if log_file is None:
        return
    try:
        log_file.parent.mkdir(parents=True, exist_ok=True)
        with open(log_file, "a", encoding="utf-8") as f:
            f.write(message.rstrip() + "\n")
    except OSError:
        pass


def _run_ffmpeg_filter(
    ts_path: Path,
    *,
    vf: str | None = None,
    af: str | None = None,
    log_file: Path | None = None,
) -> str:
    ff = ffmpeg_exe()
    if not ff.is_file():
        return ""
    cmd = [str(ff), "-hide_banner", "-i", str(ts_path)]
    if vf:
        cmd += ["-map", "0:v:0", "-vf", vf, "-an"]
    elif af:
        cmd += ["-af", af]
    else:
        return ""
    cmd += ["-f", "null", "-"]
    try:
        p = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=3600,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return ""
    output = (p.stderr or "") + (p.stdout or "")
    if log_file is not None:
        _log(log_file, f"\n---\n$ {' '.join(cmd)}\n{output}")
    return output


def parse_blackdetect_output(text: str) -> list[_GapCandidate]:
    out: list[_GapCandidate] = []
    for m in _BLACK_LINE.finditer(text):
        start = float(m.group(1))
        end = float(m.group(2))
        duration = float(m.group(3))
        if duration < MIN_BLACK_DURATION:
            continue
        out.append(_GapCandidate(time_sec=(start + end) / 2.0, score=1.0))
    return out


def parse_silencedetect_output(text: str) -> list[_GapCandidate]:
    starts: list[float] = []
    ends: list[float] = []
    for m in _SILENCE_START.finditer(text):
        starts.append(float(m.group(1)))
    for m in _SILENCE_END.finditer(text):
        ends.append(float(m.group(1)))
    out: list[_GapCandidate] = []
    for start in starts:
        end = next((e for e in ends if e >= start), None)
        if end is None:
            continue
        if (end - start) < 1.0:
            continue
        out.append(_GapCandidate(time_sec=(start + end) / 2.0, score=0.6))
    return out


def _best_fit_length(total_sec: float, job_duration_sec: int) -> float:
    if job_duration_sec > 0:
        return float(job_duration_sec)
    best = CANDIDATE_LENGTHS_SEC[0]
    best_err = abs(total_sec - best)
    for length in CANDIDATE_LENGTHS_SEC:
        err = abs(total_sec - length)
        if err < best_err:
            best = length
            best_err = err
    return float(best)


def _estimate_episode_count(total_sec: float, job_duration_sec: int) -> int:
    slot = _best_fit_length(total_sec, job_duration_sec)
    if slot <= 0:
        return 1
    count = max(1, int(round(total_sec / slot)))
    return count


def _merge_candidates(
    black: list[_GapCandidate],
    silence: list[_GapCandidate],
) -> list[_GapCandidate]:
    merged: dict[float, float] = {}
    for cand in black + silence:
        key = round(cand.time_sec, 1)
        merged[key] = merged.get(key, 0.0) + cand.score
    for b in black:
        for s in silence:
            if abs(b.time_sec - s.time_sec) <= 1.0:
                key = round((b.time_sec + s.time_sec) / 2.0, 1)
                merged[key] = merged.get(key, 0.0) + 0.5
    return [_GapCandidate(time_sec=k, score=v) for k, v in merged.items()]


def _score_boundary(
    time_sec: float,
    *,
    total_sec: float,
    expected_count: int,
    base_score: float,
) -> float:
    if expected_count <= 1:
        return base_score
    score = base_score
    for k in range(1, expected_count):
        ideal = (total_sec * k) / expected_count
        dist = abs(time_sec - ideal)
        tolerance = total_sec / (expected_count * 2)
        if tolerance > 0:
            score += max(0.0, 1.0 - (dist / tolerance))
    return score


def _pick_boundaries(
    candidates: list[_GapCandidate],
    *,
    total_sec: float,
    expected_count: int,
) -> list[float]:
    if expected_count <= 1:
        return []
    scored = [
        (
            c.time_sec,
            _score_boundary(
                c.time_sec,
                total_sec=total_sec,
                expected_count=expected_count,
                base_score=c.score,
            ),
        )
        for c in candidates
        if MIN_EPISODE_SEC < c.time_sec < (total_sec - MIN_EPISODE_SEC)
    ]
    scored.sort(key=lambda x: (-x[1], x[0]))
    chosen: list[float] = []
    min_gap = MIN_EPISODE_SEC
    for time_sec, score in scored:
        if score < 1.0:
            continue
        if any(abs(time_sec - existing) < min_gap for existing in chosen):
            continue
        chosen.append(time_sec)
        if len(chosen) >= expected_count - 1:
            break
    chosen.sort()
    return chosen


def _segments_from_boundaries(
    boundaries: list[float],
    *,
    total_sec: float,
) -> list[EpisodeSegment]:
    if not boundaries:
        return [EpisodeSegment(index=1, start_sec=0.0, end_sec=total_sec)]
    points = [0.0] + boundaries + [total_sec]
    segments: list[EpisodeSegment] = []
    for i in range(len(points) - 1):
        start = points[i]
        end = points[i + 1]
        if end - start < MIN_EPISODE_SEC / 2:
            continue
        if end - start > MAX_EPISODE_SEC:
            continue
        segments.append(EpisodeSegment(index=len(segments) + 1, start_sec=start, end_sec=end))
    if not segments:
        return [EpisodeSegment(index=1, start_sec=0.0, end_sec=total_sec)]
    return segments


def detect_episode_boundaries(
    ts_path: Path,
    *,
    job_duration_sec: int,
    log_file: Path | None = None,
) -> list[EpisodeSegment]:
    total = probe_stream_duration(ts_path, "v:0")
    if total is None or total <= 0:
        return [EpisodeSegment(index=1, start_sec=0.0, end_sec=0.0)]

    black_text = _run_ffmpeg_filter(
        ts_path,
        vf="blackdetect=d=2.5:pic_th=0.98:pix_th=0.10",
        log_file=log_file,
    )
    silence_text = _run_ffmpeg_filter(
        ts_path,
        af="silencedetect=noise=-35dB:d=1.2",
        log_file=log_file,
    )
    black = parse_blackdetect_output(black_text)
    silence = parse_silencedetect_output(silence_text)
    candidates = _merge_candidates(black, silence)
    expected = _estimate_episode_count(total, job_duration_sec)
    boundaries = _pick_boundaries(
        candidates,
        total_sec=total,
        expected_count=expected,
    )
    segments = _segments_from_boundaries(boundaries, total_sec=total)
    if len(segments) == 1:
        _log(log_file, "comskip: episode detection found single segment (whole file)")
    else:
        _log(
            log_file,
            f"comskip: episode detection found {len(segments)} segments "
            f"(expected_count={expected}, boundaries={len(boundaries)})",
        )
    return segments


def job_duration_seconds(job_duration: str) -> int:
    try:
        return parse_duration(job_duration)
    except ValueError:
        return 0
