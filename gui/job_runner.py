"""Headless job execution (used by Windows Task Scheduler)."""

from __future__ import annotations

import math
import re
import sys
import time
from datetime import datetime, timedelta
from pathlib import Path

from config_store import job_by_id, load_config, source_by_id
from duration_parse import parse_duration
from m3u_load import find_channel, load_m3u
from paths import log_dir
from recorder import build_ffmpeg_argv, maybe_post_extract_captions, run_ffmpeg

_JITTER_SECONDS = 8


def _safe_channel(name: str) -> str:
    s = re.sub(r'[\\/:*?"<>|]', "_", name.strip())
    return s[:80] if s else "channel"


def build_output_path(job) -> Path:
    now = datetime.now()
    sub = (
        job.filename_pattern.replace("{date}", now.strftime("%Y-%m-%d"))
        .replace("{time}", now.strftime("%H%M%S"))
        .replace("{channel}", _safe_channel(job.channel))
    )
    out_dir = Path(job.output_dir).expanduser()
    out_dir.mkdir(parents=True, exist_ok=True)
    out = out_dir / sub
    fmt = str(getattr(job, "output_format", "ts")).lower()
    if fmt not in ("ts", "mp4", "mkv", "mov"):
        fmt = "ts"
    if out.suffix.lower() != f".{fmt}":
        out = out.with_suffix(f".{fmt}")
    return out


def _parse_local_datetime(text: str) -> datetime:
    s = text.strip()
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    dt = datetime.fromisoformat(s)
    if dt.tzinfo is not None:
        return dt.astimezone().replace(tzinfo=None)
    return dt


def _parse_days_csv(csv: str | None) -> set[int]:
    raw = (csv or "").strip()
    if not raw:
        return set()
    map_days = {"mon": 0, "tue": 1, "wed": 2, "thu": 3, "fri": 4, "sat": 5, "sun": 6}
    out: set[int] = set()
    for part in raw.split(","):
        d = part.strip().lower()
        if d in map_days:
            out.add(map_days[d])
    return out


def _derive_scheduled_start(
    *,
    scheduled_start_text: str | None,
    scheduled_mode: str | None,
    scheduled_hour: int | None,
    scheduled_minute: int | None,
    scheduled_days_csv: str | None,
) -> datetime | None:
    if scheduled_start_text:
        try:
            return _parse_local_datetime(scheduled_start_text)
        except Exception:
            return None
    if scheduled_mode not in ("daily", "weekly"):
        return None
    if scheduled_hour is None or scheduled_minute is None:
        return None
    if not (0 <= scheduled_hour <= 23 and 0 <= scheduled_minute <= 59):
        return None

    now = datetime.now()
    if scheduled_mode == "daily":
        cand = now.replace(hour=scheduled_hour, minute=scheduled_minute, second=0, microsecond=0)
        if cand > now + timedelta(seconds=_JITTER_SECONDS):
            cand -= timedelta(days=1)
        return cand

    valid_days = _parse_days_csv(scheduled_days_csv)
    if not valid_days:
        return None
    for delta in range(0, 8):
        d = now - timedelta(days=delta)
        if d.weekday() not in valid_days:
            continue
        cand = d.replace(hour=scheduled_hour, minute=scheduled_minute, second=0, microsecond=0)
        if cand <= now + timedelta(seconds=_JITTER_SECONDS):
            return cand
    return None


def _windowed_duration_text(job_duration: str, scheduled_start: datetime) -> str | None:
    duration_seconds = parse_duration(job_duration)
    window_end = scheduled_start + timedelta(seconds=duration_seconds)
    now = datetime.now()

    if now < scheduled_start - timedelta(seconds=_JITTER_SECONDS):
        wait_s = (scheduled_start - now).total_seconds()
        if wait_s > 0:
            print(f"scheduled run arrived early; waiting {wait_s:.1f}s until start", file=sys.stderr)
            time.sleep(wait_s)
        now = datetime.now()

    if now > window_end + timedelta(seconds=_JITTER_SECONDS):
        print(
            (
                "skipping run: recording window already ended "
                f"(start={scheduled_start.isoformat(sep=' ', timespec='seconds')}, "
                f"end={window_end.isoformat(sep=' ', timespec='seconds')}, "
                f"now={now.isoformat(sep=' ', timespec='seconds')})"
            ),
            file=sys.stderr,
        )
        return None

    if now > scheduled_start + timedelta(seconds=_JITTER_SECONDS):
        rem = window_end - now
        remaining_seconds = max(0, math.ceil(rem.total_seconds()))
        if remaining_seconds <= 0:
            print("skipping run: no remaining duration in scheduled window", file=sys.stderr)
            return None
        print(
            (
                f"late start detected; recording remaining {remaining_seconds}s "
                f"(window end {window_end.isoformat(sep=' ', timespec='seconds')})"
            ),
            file=sys.stderr,
        )
        return str(remaining_seconds)

    print(
        f"on-time scheduled start; recording full configured duration ({job_duration})",
        file=sys.stderr,
    )
    return job_duration


def run_job(
    job_id: str,
    *,
    scheduled_start_text: str | None = None,
    scheduled_mode: str | None = None,
    scheduled_hour: int | None = None,
    scheduled_minute: int | None = None,
    scheduled_days_csv: str | None = None,
) -> int:
    cfg = load_config()
    job = job_by_id(cfg, job_id)
    if job is None:
        print(f"unknown job id {job_id}", file=sys.stderr)
        return 2
    if not job.enabled:
        print(f"job {job_id} is disabled", file=sys.stderr)
        return 0
    src = source_by_id(cfg, job.source_id)
    if src is None:
        print(f"missing source for job {job_id}", file=sys.stderr)
        return 2
    try:
        channels = load_m3u(src.path_or_url)
        ch = find_channel(channels, job.channel)
    except Exception as e:
        print(f"m3u/channel: {e}", file=sys.stderr)
        return 2
    ua = job.user_agent or ch.user_agent
    ref = job.referer or ch.referer
    duration_text = job.duration
    scheduled_start = _derive_scheduled_start(
        scheduled_start_text=scheduled_start_text,
        scheduled_mode=scheduled_mode,
        scheduled_hour=scheduled_hour,
        scheduled_minute=scheduled_minute,
        scheduled_days_csv=scheduled_days_csv,
    )
    if scheduled_start is not None:
        try:
            resolved = _windowed_duration_text(job.duration, scheduled_start)
        except Exception as e:
            print(f"duration/window: {e}", file=sys.stderr)
            return 2
        if resolved is None:
            return 0
        duration_text = resolved
    out = build_output_path(job)
    log_path = log_dir() / f"job_{job.id}.log"
    try:
        argv = build_ffmpeg_argv(
            stream_url=ch.url,
            output_path=out,
            duration_text=duration_text,
            user_agent=ua,
            referer=ref,
            download_captions=job.download_captions,
        )
    except Exception as e:
        print(f"build: {e}", file=sys.stderr)
        return 2
    code = run_ffmpeg(argv, log_file=log_path)
    if code != 0:
        print(f"ffmpeg exited {code}; see {log_path}", file=sys.stderr)
        return code
    maybe_post_extract_captions(
        out,
        download_captions=job.download_captions,
        log_file=log_path,
    )

    return 0
