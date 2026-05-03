"""Headless job execution (used by Windows Task Scheduler)."""

from __future__ import annotations

import re
import sys
from datetime import datetime
from pathlib import Path

from config_store import job_by_id, load_config, source_by_id
from m3u_load import find_channel, load_m3u
from paths import log_dir
from postprocess import run_postprocessing
from recorder import build_ffmpeg_argv, run_ffmpeg


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


def run_job(job_id: str) -> int:
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
    out = build_output_path(job)
    log_path = log_dir() / f"job_{job.id}.log"
    try:
        argv = build_ffmpeg_argv(
            stream_url=ch.url,
            output_path=out,
            duration_text=job.duration,
            user_agent=ua,
            referer=ref,
        )
    except Exception as e:
        print(f"build: {e}", file=sys.stderr)
        return 2
    code = run_ffmpeg(argv, log_file=log_path)
    if code != 0:
        print(f"ffmpeg exited {code}; see {log_path}", file=sys.stderr)
        return code

    post = run_postprocessing(job, recorded_path=out, log_file=log_path)
    if not post.success:
        print(f"post-processing failed: {post.message}; see {log_path}", file=sys.stderr)
        return post.exit_code
    return 0
