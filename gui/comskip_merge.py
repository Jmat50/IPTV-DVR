"""Parse and merge Comskip commercial marker sidecars."""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from recorder import probe_video_frame_rate


@dataclass(frozen=True)
class CommercialBreak:
    start_sec: float
    end_sec: float
    episode_index: int | None = None


@dataclass(frozen=True)
class EpisodeSegment:
    index: int
    start_sec: float
    end_sec: float


_EDL_LINE = re.compile(
    r"^\s*([0-9]+(?:\.[0-9]+)?)\s+([0-9]+(?:\.[0-9]+)?)\s+([0-9]+)\s*$"
)
_FRAME_PAIR = re.compile(r"^\s*(\d+)\s+(\d+)\s*$")
_TXT_V2 = re.compile(
    r"FILE PROCESSING COMPLETE\s+(\d+)\s+FRAMES AT\s+(\d+)",
    re.IGNORECASE,
)


def probe_video_fps(media_path: Path) -> float:
    rate = probe_video_frame_rate(media_path)
    if not rate:
        return 29.97
    if "/" in rate:
        num, den = rate.split("/", 1)
        try:
            den_f = float(den)
            if den_f != 0:
                return float(num) / den_f
        except ValueError:
            pass
    try:
        val = float(rate)
        if val > 0:
            return val
    except ValueError:
        pass
    return 29.97


def parse_comskip_edl(path: Path) -> list[CommercialBreak]:
    if not path.is_file():
        return []
    breaks: list[CommercialBreak] = []
    for raw in path.read_text(encoding="utf-8", errors="replace").splitlines():
        m = _EDL_LINE.match(raw)
        if not m:
            continue
        start = float(m.group(1))
        end = float(m.group(2))
        if end <= start:
            continue
        breaks.append(CommercialBreak(start_sec=start, end_sec=end))
    return breaks


def parse_comskip_txt(path: Path) -> tuple[float, list[tuple[int, int]]]:
    """Return (fps, list of (start_frame, end_frame))."""
    if not path.is_file():
        return 0.0, []
    lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    fps = 0.0
    pairs: list[tuple[int, int]] = []
    past_header = False
    for line in lines:
        if not past_header:
            m = _TXT_V2.search(line)
            if m:
                frames_at = int(m.group(2))
                if frames_at > 0:
                    fps = frames_at / 100.0
            if line.strip().startswith("---"):
                past_header = True
            continue
        m = _FRAME_PAIR.match(line)
        if not m:
            continue
        start_f = int(m.group(1))
        end_f = int(m.group(2))
        if end_f <= start_f:
            continue
        pairs.append((start_f, end_f))
    return fps, pairs


def commercial_breaks_from_txt(
    path: Path,
    *,
    fps: float | None = None,
) -> list[CommercialBreak]:
    parsed_fps, pairs = parse_comskip_txt(path)
    use_fps = fps or parsed_fps or 29.97
    if use_fps <= 0:
        use_fps = 29.97
    out: list[CommercialBreak] = []
    for start_f, end_f in pairs:
        out.append(
            CommercialBreak(
                start_sec=start_f / use_fps,
                end_sec=end_f / use_fps,
            )
        )
    return out


def merge_commercial_breaks(
    segments: list[tuple[EpisodeSegment, Path | None, Path | None]],
    *,
    total_sec: float,
) -> list[CommercialBreak]:
    """Merge per-segment .edl/.txt sidecars onto the master timeline."""
    merged: list[CommercialBreak] = []
    for seg, edl_path, txt_path in segments:
        local: list[CommercialBreak] = []
        if edl_path is not None and edl_path.is_file():
            local = parse_comskip_edl(edl_path)
        elif txt_path is not None and txt_path.is_file():
            local = commercial_breaks_from_txt(txt_path)
        for br in local:
            merged.append(
                CommercialBreak(
                    start_sec=br.start_sec + seg.start_sec,
                    end_sec=br.end_sec + seg.start_sec,
                    episode_index=seg.index,
                )
            )
    return normalize_breaks(merged, total_sec=total_sec)


def normalize_breaks(
    breaks: list[CommercialBreak],
    *,
    total_sec: float,
) -> list[CommercialBreak]:
    if not breaks:
        return []
    clipped: list[CommercialBreak] = []
    for br in breaks:
        start = max(0.0, min(br.start_sec, total_sec))
        end = max(0.0, min(br.end_sec, total_sec))
        if end <= start:
            continue
        clipped.append(
            CommercialBreak(
                start_sec=start,
                end_sec=end,
                episode_index=br.episode_index,
            )
        )
    clipped.sort(key=lambda b: (b.start_sec, b.end_sec))
    out: list[CommercialBreak] = []
    for br in clipped:
        if out and br.start_sec < out[-1].end_sec:
            prev = out[-1]
            out[-1] = CommercialBreak(
                start_sec=prev.start_sec,
                end_sec=max(prev.end_sec, br.end_sec),
                episode_index=prev.episode_index or br.episode_index,
            )
            continue
        out.append(br)
    return out


def write_merged_edl(path: Path, breaks: list[CommercialBreak]) -> None:
    lines = [f"{br.start_sec:.2f}\t{br.end_sec:.2f}\t3" for br in breaks]
    path.write_text("\n".join(lines) + ("\n" if lines else ""), encoding="utf-8")


def write_merged_txt(
    path: Path,
    breaks: list[CommercialBreak],
    *,
    fps: float,
    total_sec: float,
) -> None:
    total_frames = max(1, int(round(total_sec * fps)))
    fps_x100 = int(round(fps * 100))
    header = [
        f"FILE PROCESSING COMPLETE {total_frames} FRAMES AT {fps_x100}",
        "-------------",
    ]
    body: list[str] = []
    for br in breaks:
        start_f = int(round(br.start_sec * fps))
        end_f = int(round(br.end_sec * fps))
        if end_f <= start_f:
            continue
        body.append(f"{start_f} {end_f}")
    path.write_text("\n".join(header + body) + ("\n" if body else ""), encoding="utf-8")
