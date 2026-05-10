"""JSON config for M3U sources and recording jobs."""

from __future__ import annotations

import json
import uuid
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Literal

from paths import config_file


ScheduleMode = Literal["daily", "weekly"]
OutputFormat = Literal["ts", "mp4", "mkv", "mov"]
CommercialStrategy = Literal["myth_only", "legacy_only", "hybrid"]
FailSafeMode = Literal["no_cut", "low_risk_cut"]


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
class CommercialRemovalSettings:
    strategy: CommercialStrategy = "myth_only"
    enable_myth: bool = True
    enable_legacy: bool = False
    enable_ffmpeg_signals: bool = True
    weight_myth: float = 1.0
    weight_legacy: float = 1.0
    weight_ffmpeg_signals: float = 0.6
    confidence_threshold: float = 0.55
    max_commercial_ratio: float = 0.45
    min_keep_segment_seconds: float = 15.0
    episode_aware: bool = True
    episode_boundary_min_gap_seconds: float = 90.0
    episode_boundary_black_min_seconds: float = 2.0
    episode_boundary_silence_min_seconds: float = 1.5
    fail_safe_mode: FailSafeMode = "low_risk_cut"
    low_risk_max_commercial_ratio: float = 0.30


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
    remove_commercials_after_complete: bool = False
    commercial_settings: CommercialRemovalSettings = field(default_factory=CommercialRemovalSettings)
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


def _commercial_settings_from_dict(d: dict[str, Any]) -> CommercialRemovalSettings:
    strategy = str(d.get("strategy", "myth_only")).lower()
    if strategy not in ("myth_only", "legacy_only", "hybrid"):
        strategy = "myth_only"
    fail_safe_mode = str(d.get("fail_safe_mode", "low_risk_cut")).lower()
    if fail_safe_mode not in ("no_cut", "low_risk_cut"):
        fail_safe_mode = "low_risk_cut"
    return CommercialRemovalSettings(
        strategy=strategy,  # type: ignore[arg-type]
        enable_myth=bool(d.get("enable_myth", True)),
        enable_legacy=bool(d.get("enable_legacy", False)),
        enable_ffmpeg_signals=bool(d.get("enable_ffmpeg_signals", True)),
        weight_myth=float(d.get("weight_myth", 1.0)),
        weight_legacy=float(d.get("weight_legacy", 1.0)),
        weight_ffmpeg_signals=float(d.get("weight_ffmpeg_signals", 0.6)),
        confidence_threshold=float(d.get("confidence_threshold", 0.55)),
        max_commercial_ratio=float(d.get("max_commercial_ratio", 0.45)),
        min_keep_segment_seconds=float(d.get("min_keep_segment_seconds", 15.0)),
        episode_aware=bool(d.get("episode_aware", True)),
        episode_boundary_min_gap_seconds=float(d.get("episode_boundary_min_gap_seconds", 90.0)),
        episode_boundary_black_min_seconds=float(d.get("episode_boundary_black_min_seconds", 2.0)),
        episode_boundary_silence_min_seconds=float(d.get("episode_boundary_silence_min_seconds", 1.5)),
        fail_safe_mode=fail_safe_mode,  # type: ignore[arg-type]
        low_risk_max_commercial_ratio=float(d.get("low_risk_max_commercial_ratio", 0.30)),
    )


def _job_from_dict(d: dict[str, Any]) -> Job:
    sch = d.get("schedule") or {}
    output_format = str(d.get("output_format", "ts")).lower()
    if output_format not in ("ts", "mp4", "mkv", "mov"):
        output_format = "ts"
    remove_commercials = bool(d.get("remove_commercials_after_complete", False))
    settings_obj = d.get("commercial_settings")
    if isinstance(settings_obj, dict):
        commercial_settings = _commercial_settings_from_dict(settings_obj)
    else:
        # Backward-compatible defaults for older config files.
        commercial_settings = CommercialRemovalSettings()
        if remove_commercials:
            commercial_settings.strategy = "hybrid"
            commercial_settings.enable_myth = True
            commercial_settings.enable_ffmpeg_signals = True
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
        remove_commercials_after_complete=remove_commercials,
        commercial_settings=commercial_settings,
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


def save_config(cfg: AppConfig, path: Path | None = None) -> None:
    p = path or config_file()
    payload: dict[str, Any] = {
        "version": cfg.version,
        "sources": [asdict(s) for s in cfg.sources],
        "jobs": [asdict(j) for j in cfg.jobs],
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
