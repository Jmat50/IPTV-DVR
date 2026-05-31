"""JSON config for M3U sources and recording jobs."""

from __future__ import annotations

import json
import uuid
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Literal

from caption_mode import (
    migrate_caption_mode,
    normalize_caption_mode,
    normalize_caption_post_processor,
)
from paths import config_file


ScheduleMode = Literal["daily", "weekly"]
OutputFormat = Literal["ts", "mp4", "mkv", "mov"]
CaptionMode = Literal["off", "post_only", "live_ccextractor", "auto"]
CaptionPostProcessor = Literal["ffmpeg", "ccextractor"]
@dataclass
class Source:
    id: str
    name: str
    path_or_url: str

    @staticmethod
    def new(name: str, path_or_url: str) -> "Source":
        return Source(id=str(uuid.uuid4()), name=name.strip(), path_or_url=path_or_url.strip())


@dataclass
class Schedule:
    mode: ScheduleMode = "daily"
    days: list[str] = field(default_factory=list)  # mon..sun for weekly
    hour: int = 20
    minute: int = 0


@dataclass
class Job:
    id: str
    name: str
    source_id: str
    channel: str
    duration: str  # e.g. 90m
    output_dir: str
    filename_pattern: str = "{date}_{channel}.ts"
    output_format: OutputFormat = "ts"
    user_agent: str = ""
    referer: str = ""
    enabled: bool = True
    download_captions: bool = False  # legacy; mirrored when caption_mode != off
    caption_mode: CaptionMode = "off"
    caption_post_processor: CaptionPostProcessor = "ffmpeg"
    schedule: Schedule = field(default_factory=Schedule)

    @staticmethod
    def new(
        name: str,
        source_id: str,
        channel: str,
        duration: str,
        output_dir: str,
    ) -> "Job":
        return Job(
            id=str(uuid.uuid4()),
            name=name.strip(),
            source_id=source_id,
            channel=channel.strip(),
            duration=duration.strip(),
            output_dir=output_dir.strip(),
        )


@dataclass
class AppConfig:
    version: int = 1
    sources: list[Source] = field(default_factory=list)
    jobs: list[Job] = field(default_factory=list)


def _schedule_from_dict(d: dict[str, Any]) -> Schedule:
    mode = d.get("mode", "daily")
    if mode not in ("daily", "weekly"):
        mode = "daily"
    return Schedule(
        mode=mode,
        days=[str(x).lower() for x in d.get("days", [])],
        hour=int(d.get("hour", 20)),
        minute=int(d.get("minute", 0)),
    )


def _job_from_dict(d: dict[str, Any]) -> Job:
    sch = d.get("schedule") or {}
    output_format = str(d.get("output_format", "ts")).lower()
    if output_format not in ("ts", "mp4", "mkv", "mov"):
        output_format = "ts"
    download_captions = bool(d.get("download_captions", False))
    caption_mode = migrate_caption_mode(
        caption_mode=d.get("caption_mode"),
        download_captions=download_captions,
    )
    return Job(
        id=d["id"],
        name=d.get("name", "Job"),
        source_id=d["source_id"],
        channel=d["channel"],
        duration=d["duration"],
        output_dir=d["output_dir"],
        filename_pattern=d.get("filename_pattern", "{date}_{channel}.ts"),
        output_format=output_format,
        user_agent=d.get("user_agent", ""),
        referer=d.get("referer", ""),
        enabled=bool(d.get("enabled", True)),
        download_captions=caption_mode != "off",
        caption_mode=caption_mode,
        caption_post_processor=normalize_caption_post_processor(d.get("caption_post_processor")),
        schedule=_schedule_from_dict(sch) if isinstance(sch, dict) else Schedule(),
    )


def _source_from_dict(d: dict[str, Any]) -> Source:
    return Source(id=d["id"], name=d["name"], path_or_url=d["path_or_url"])


def load_config(path: Path | None = None) -> AppConfig:
    p = path or config_file()
    if not p.is_file():
        return AppConfig()
    data = json.loads(p.read_text(encoding="utf-8"))
    sources = [_source_from_dict(x) for x in data.get("sources", [])]
    jobs = [_job_from_dict(x) for x in data.get("jobs", [])]
    return AppConfig(version=int(data.get("version", 1)), sources=sources, jobs=jobs)


def _job_to_dict(job: Job) -> dict[str, Any]:
    d = asdict(job)
    mode = normalize_caption_mode(job.caption_mode)
    d["caption_mode"] = mode
    d["download_captions"] = mode != "off"
    d["caption_post_processor"] = normalize_caption_post_processor(
        getattr(job, "caption_post_processor", "ffmpeg")
    )
    return d


def save_config(cfg: AppConfig, path: Path | None = None) -> None:
    p = path or config_file()
    payload: dict[str, Any] = {
        "version": cfg.version,
        "sources": [asdict(s) for s in cfg.sources],
        "jobs": [_job_to_dict(j) for j in cfg.jobs],
    }
    p.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def source_by_id(cfg: AppConfig, sid: str) -> Source | None:
    for s in cfg.sources:
        if s.id == sid:
            return s
    return None


def job_by_id(cfg: AppConfig, jid: str) -> Job | None:
    for j in cfg.jobs:
        if j.id == jid:
            return j
    return None
