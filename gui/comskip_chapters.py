"""Generate FFmpeg chapter metadata from Comskip results."""

from __future__ import annotations

from pathlib import Path

from comskip_merge import CommercialBreak, EpisodeSegment


def _escape_ffmeta(value: str) -> str:
    return (
        value.replace("\\", "\\\\")
        .replace("=", "\\=")
        .replace(";", "\\;")
        .replace("#", "\\#")
        .replace("\n", "\\\n")
    )


def _ms(sec: float) -> int:
    return max(0, int(round(sec * 1000.0)))


def write_chapters_ffmeta(
    path: Path,
    *,
    title: str,
    episodes: list[EpisodeSegment],
    commercials: list[CommercialBreak],
    total_sec: float,
) -> None:
    lines = [";FFMETADATA1", f"title={_escape_ffmeta(title)}"]
    for ep in episodes:
        end = ep.end_sec if ep.end_sec > 0 else total_sec
        lines += [
            "",
            "[CHAPTER]",
            "TIMEBASE=1/1000",
            f"START={_ms(ep.start_sec)}",
            f"END={_ms(end)}",
            f"title=Episode {ep.index}",
        ]
    for br in commercials:
        label = "Commercial"
        if br.episode_index is not None:
            label = f"Commercial (Ep {br.episode_index})"
        lines += [
            "",
            "[CHAPTER]",
            "TIMEBASE=1/1000",
            f"START={_ms(br.start_sec)}",
            f"END={_ms(br.end_sec)}",
            f"title={_escape_ffmeta(label)}",
        ]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
