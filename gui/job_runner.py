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
from caption_finalize import finalize_captions, should_dual_output_vtt
from caption_mode import migrate_caption_mode, resolve_caption_mode_with_reason
from caption_worker import LiveCaptionWorker
from recorder import build_ffmpeg_argv, is_manual_stop_exit, run_ffmpeg, try_repair_ts_file

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
    caption_mode = migrate_caption_mode(
        caption_mode=getattr(job, "caption_mode", None),
        download_captions=job.download_captions,
    )
    resolved_caption_mode, caption_mode_reason = resolve_caption_mode_with_reason(caption_mode, out)
    if caption_mode != "off" and resolved_caption_mode != caption_mode:
        log_path.parent.mkdir(parents=True, exist_ok=True)
        with open(log_path, "a", encoding="utf-8") as f:
            f.write(f"captions: mode fallback {caption_mode} -> {resolved_caption_mode}: {caption_mode_reason}\n")
    try:
        argv = build_ffmpeg_argv(
            stream_url=ch.url,
            output_path=out,
            duration_text=duration_text,
            user_agent=ua,
            referer=ref,
            download_captions=caption_mode != "off",
            dual_output_vtt=should_dual_output_vtt(
                caption_mode,
                stream_url=ch.url,
                user_agent=ua,
                referer=ref,
            ),
        )
    except Exception as e:
        print(f"build: {e}", file=sys.stderr)
        return 2

    live_worker: LiveCaptionWorker | None = None
    if resolved_caption_mode == "live_ccextractor":
        # Ensure CCExtractor follows this run's file, not stale content from prior runs.
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_bytes(b"")
        live_worker = LiveCaptionWorker(out, log_file=log_path)
        if not live_worker.start():
            live_worker = None

    code = run_ffmpeg(argv, log_file=log_path)
    live_ok = False
    if live_worker is not None:
        live_ok = live_worker.stop_and_finalize()

    if code != 0:
        # Avoid leaving empty/corrupt placeholder files when ffmpeg fails before writing data.
        out_size = 0
        try:
            if out.is_file():
                out_size = out.stat().st_size
            if out.is_file() and out_size == 0:
                out.unlink()
        except OSError:
            pass
        # If ffmpeg wrote bytes but ended non-zero (manual stop, network break, etc.),
        # normalize the partial TS so strict players can decode it.
        if out_size > 0:
            _ = try_repair_ts_file(out, log_file=log_path)
        # If ffmpeg produced a partial recording, still try caption finalize for that file.
        if out_size > 0 and caption_mode != "off":
            try:
                finalize_captions(
                    out,
                    resolved_caption_mode,
                    log_file=log_path,
                    live_ok=live_ok,
                )
            except Exception as e:
                print(f"captions finalize after ffmpeg error: {e}", file=sys.stderr)
        # User-driven console close can report a non-zero exit on Windows
        # even when ffmpeg already wrote a valid partial recording.
        if out_size > 0 and is_manual_stop_exit(code):
            print("ffmpeg stopped by user; keeping partial recording", file=sys.stderr)
            return 0
        # Write a small marker beside the expected output so failures are obvious in the target folder.
        fail_marker = Path(str(out) + ".failed.txt")
        tail = ""
        try:
            if log_path.is_file():
                lines = log_path.read_text(encoding="utf-8", errors="replace").splitlines()
                tail = "\n".join(lines[-30:])
        except OSError:
            tail = ""
        try:
            fail_marker.write_text(
                (
                    f"Recording failed (ffmpeg exit code {code}).\n"
                    f"Expected output: {out}\n"
                    f"Log file: {log_path}\n\n"
                    "Last log lines:\n"
                    f"{tail}\n"
                ),
                encoding="utf-8",
            )
        except OSError:
            pass
        print(f"ffmpeg exited {code}; see {log_path}", file=sys.stderr)
        return code

    finalize_captions(
        out,
        resolved_caption_mode,
        log_file=log_path,
        live_ok=live_ok,
    )

    return 0
