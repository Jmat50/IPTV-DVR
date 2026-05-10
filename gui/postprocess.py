"""Post-processing helpers run after recording finishes."""

from __future__ import annotations

import math
import re
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path

from cutlist_validation import validate_and_guard_cutlist
from episode_boundaries import detect_episode_blocks
from paths import ffmpeg_exe, ffprobe_exe, resolve_mythcommflag_exe
from span_fusion import FusedSpan, fuse_commercial_spans


@dataclass
class PostprocessResult:
    success: bool
    exit_code: int
    output_path: Path
    message: str = ""


@dataclass
class PostprocessRuntimeSettings:
    strategy: str = "myth_only"
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
    fail_safe_mode: str = "low_risk_cut"
    low_risk_max_commercial_ratio: float = 0.30


def _append_log_header(log_file: Path, title: str, argv: list[str]) -> None:
    log_file.parent.mkdir(parents=True, exist_ok=True)
    with open(log_file, "a", encoding="utf-8") as log_fp:
        log_fp.write(f"\n---\n[{title}]\n$ {' '.join(argv)}\n")


def _run_logged(argv: list[str], *, log_file: Path, title: str, cwd: Path | None = None) -> int:
    _append_log_header(log_file, title, argv)
    with open(log_file, "a", encoding="utf-8") as log_fp:
        p = subprocess.Popen(
            argv,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            stdin=subprocess.DEVNULL,
            cwd=str(cwd) if cwd is not None else None,
            text=True,
            bufsize=1,
        )
        assert p.stdout is not None
        for line in p.stdout:
            log_fp.write(line)
            log_fp.flush()
        return int(p.wait())


def _next_available(path: Path) -> Path:
    if not path.exists():
        return path
    idx = 1
    while True:
        candidate = path.with_name(f"{path.stem}_{idx}{path.suffix}")
        if not candidate.exists():
            return candidate
        idx += 1


def _parse_frame_rate(text: str) -> float:
    value = text.strip()
    if not value or value == "0/0":
        return 0.0
    if "/" in value:
        num_s, den_s = value.split("/", 1)
        num = float(num_s)
        den = float(den_s)
        if den == 0:
            return 0.0
        return num / den
    return float(value)


def _probe_video_fps(input_path: Path) -> float:
    argv = [
        str(ffprobe_exe()),
        "-v",
        "error",
        "-select_streams",
        "v:0",
        "-show_entries",
        "stream=avg_frame_rate,r_frame_rate",
        "-of",
        "default=noprint_wrappers=1:nokey=1",
        str(input_path),
    ]
    out = subprocess.check_output(argv, text=True, stderr=subprocess.STDOUT)
    lines = [ln.strip() for ln in out.splitlines() if ln.strip()]
    for rate in lines:
        fps = _parse_frame_rate(rate)
        if fps > 0:
            return fps
    raise RuntimeError("Could not determine input FPS for mythcommflag frame conversion.")


def _probe_duration_seconds(input_path: Path) -> float:
    argv = [
        str(ffprobe_exe()),
        "-v",
        "error",
        "-show_entries",
        "format=duration",
        "-of",
        "default=noprint_wrappers=1:nokey=1",
        str(input_path),
    ]
    out = subprocess.check_output(argv, text=True, stderr=subprocess.STDOUT).strip()
    if not out:
        raise RuntimeError("Could not determine input duration with ffprobe.")
    duration = float(out)
    if duration <= 0:
        raise RuntimeError(f"Input duration is not positive: {duration}")
    return duration


def _input_has_audio(input_path: Path) -> bool:
    argv = [
        str(ffprobe_exe()),
        "-v",
        "error",
        "-select_streams",
        "a:0",
        "-show_entries",
        "stream=index",
        "-of",
        "default=noprint_wrappers=1:nokey=1",
        str(input_path),
    ]
    out = subprocess.check_output(argv, text=True, stderr=subprocess.STDOUT)
    return bool(out.strip())


def _mythcommflag_supported_flags(mythcommflag: Path) -> set[str]:
    try:
        p = subprocess.run(
            [str(mythcommflag), "--help"],
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            stdin=subprocess.DEVNULL,
            text=True,
            check=False,
        )
        out = p.stdout or ""
    except Exception:
        return set()
    return set(re.findall(r"--[a-zA-Z0-9-]+", out))


def _run_mythcommflag_detection(
    *,
    mythcommflag: Path,
    analysis_input: Path,
    output_file: Path,
    log_file: Path,
) -> None:
    flags = _mythcommflag_supported_flags(mythcommflag)
    progress_flags: list[str | None] = []
    if "--noprogress" in flags:
        progress_flags.append("--noprogress")
    if "--nopercentage" in flags:
        progress_flags.append("--nopercentage")
    progress_flags.append(None)

    skipdb_modes = [True, False]
    last_code: int | None = None
    for use_skipdb in skipdb_modes:
        for progress_flag in progress_flags:
            if output_file.exists():
                output_file.unlink()
            argv = [str(mythcommflag)]
            if use_skipdb:
                argv.append("--skipdb")
            argv.extend(
                [
                    "--file",
                    analysis_input.name,
                    "--outputmethod",
                    "essentials",
                    "--outputfile",
                    output_file.name,
                    "--method",
                    "all",
                ],
            )
            if progress_flag:
                argv.append(progress_flag)
            code = _run_logged(
                argv,
                log_file=log_file,
                title=(
                    "postprocess: mythcommflag detection "
                    f"(skipdb={use_skipdb}, progress={progress_flag or 'none'})"
                ),
                cwd=analysis_input.parent,
            )
            last_code = code
            if code == 0 and output_file.is_file():
                return
    raise RuntimeError(f"mythcommflag failed with exit code {last_code}")


def _build_detection_proxy(input_path: Path, *, log_file: Path) -> Path:
    tmp_dir = Path(tempfile.gettempdir()) / "iptv_myth_proxy"
    tmp_dir.mkdir(parents=True, exist_ok=True)
    proxy_path = tmp_dir / f"{input_path.stem}_proxy.mp4"
    argv = [
        str(ffmpeg_exe()),
        "-y",
        "-i",
        str(input_path),
        "-map",
        "0:v:0",
        "-an",
        "-vf",
        "fps=30000/1001,scale=960:-2:flags=bicubic",
        "-c:v",
        "libx264",
        "-preset",
        "ultrafast",
        "-crf",
        "35",
        str(proxy_path),
    ]
    code = _run_logged(argv, log_file=log_file, title="postprocess: mythcommflag proxy build")
    if code != 0:
        raise RuntimeError(f"ffmpeg proxy build failed with exit code {code}")
    if not proxy_path.is_file():
        raise FileNotFoundError(f"ffmpeg proxy build completed but no output file was found at {proxy_path}")
    return proxy_path


def _load_runtime_settings(job) -> PostprocessRuntimeSettings:
    cfg = getattr(job, "commercial_settings", None)
    if cfg is None:
        return PostprocessRuntimeSettings()
    data = getattr(cfg, "__dict__", {})
    settings = PostprocessRuntimeSettings()
    for key in settings.__dict__.keys():
        if key in data:
            setattr(settings, key, data[key])
    if settings.strategy not in ("myth_only", "legacy_only", "hybrid"):
        settings.strategy = "myth_only"
    return settings


def _clip_spans_to_blocks(spans: list[tuple[float, float]], blocks: list[tuple[float, float]]) -> list[tuple[float, float]]:
    if not spans:
        return []
    clipped: list[tuple[float, float]] = []
    for start, end in spans:
        for block_start, block_end in blocks:
            s = max(start, block_start)
            e = min(end, block_end)
            if e > s:
                clipped.append((s, e))
    if not clipped:
        return []
    clipped.sort(key=lambda item: item[0])
    merged: list[tuple[float, float]] = [clipped[0]]
    for start, end in clipped[1:]:
        prev_s, prev_e = merged[-1]
        if start <= prev_e + 0.2:
            merged[-1] = (prev_s, max(prev_e, end))
        else:
            merged.append((start, end))
    return merged


def _resolve_legacy_detector_exe() -> Path | None:
    root = Path(__file__).resolve().parent.parent
    candidates = [
        root / "tools" / "comskip" / "comskip.exe",
        root / "archive" / "tools" / "comskip" / "comskip.exe",
    ]
    for candidate in candidates:
        if candidate.is_file():
            return candidate
    for name in ("comskip.exe", "comskip"):
        from shutil import which

        p = which(name)
        if p:
            return Path(p)
    return None


def _parse_edl_spans(edl_path: Path, *, duration_seconds: float) -> list[tuple[float, float]]:
    spans: list[tuple[float, float]] = []
    if not edl_path.is_file():
        return spans
    with open(edl_path, "r", encoding="utf-8", errors="replace") as fp:
        for raw in fp:
            parts = raw.strip().split()
            if len(parts) < 2:
                continue
            try:
                start = float(parts[0])
                end = float(parts[1])
            except ValueError:
                continue
            if end <= start:
                continue
            spans.append((max(0.0, start), min(duration_seconds, end)))
    return spans


def detect_commercials_with_legacy_detector(input_path: Path, *, log_file: Path) -> list[tuple[float, float]]:
    comskip = _resolve_legacy_detector_exe()
    if comskip is None:
        return []
    duration = _probe_duration_seconds(input_path)
    edl_path = input_path.with_suffix(".edl")
    argv = [
        str(comskip),
        "--ts",
        "--output",
        str(input_path.parent),
        "--output-filename",
        input_path.stem,
        str(input_path),
    ]
    code = _run_logged(argv, log_file=log_file, title="postprocess: legacy detector (comskip)")
    if code != 0:
        return []
    return _parse_edl_spans(edl_path, duration_seconds=duration)


def detect_commercials_with_ffmpeg_signals(input_path: Path, *, log_file: Path) -> list[tuple[float, float]]:
    duration = _probe_duration_seconds(input_path)
    argv = [
        str(ffmpeg_exe()),
        "-hide_banner",
        "-i",
        str(input_path),
        "-filter_complex",
        "blackdetect=d=0.40:pix_th=0.10,silencedetect=n=-35dB:d=0.50",
        "-f",
        "null",
        "-",
    ]
    _append_log_header(log_file, "postprocess: ffmpeg signal detector", argv)
    p = subprocess.run(
        argv,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        stdin=subprocess.DEVNULL,
        text=True,
        check=False,
    )
    out = p.stdout or ""
    with open(log_file, "a", encoding="utf-8") as fp:
        fp.write(out)
    if p.returncode != 0:
        return []

    transitions: list[float] = []
    black_re = re.compile(r"black_end:(?P<t>\d+(\.\d+)?)")
    silence_re = re.compile(r"silence_end:\s*(?P<t>\d+(\.\d+)?)")
    for line in out.splitlines():
        m1 = black_re.search(line)
        if m1:
            transitions.append(float(m1.group("t")))
        m2 = silence_re.search(line)
        if m2:
            transitions.append(float(m2.group("t")))
    transitions = sorted(t for t in transitions if 0.0 < t < duration)
    if len(transitions) < 2:
        return []
    spans: list[tuple[float, float]] = []
    for idx in range(len(transitions) - 1):
        start = transitions[idx]
        end = transitions[idx + 1]
        seg_len = end - start
        if 25.0 <= seg_len <= 420.0:
            spans.append((start, end))
    return spans


def _parse_mythcommflag_marks(output_file: Path) -> tuple[int | None, list[tuple[int, int]]]:
    total_frames: int | None = None
    marks: list[tuple[int, int]] = []
    total_re = re.compile(r"^totalframecount:\s*(\d+)\s*$")
    mark_re = re.compile(r"^framenum:\s*(\d+)\s+marktype:\s*(\d+)\s*$")
    with open(output_file, "r", encoding="utf-8", errors="replace") as fp:
        for raw in fp:
            line = raw.strip()
            if not line:
                continue
            total_m = total_re.match(line)
            if total_m:
                total_frames = int(total_m.group(1))
                continue
            mark_m = mark_re.match(line)
            if not mark_m:
                continue
            frame = int(mark_m.group(1))
            mark_type = int(mark_m.group(2))
            if mark_type in (4, 5):
                marks.append((frame, mark_type))
    return total_frames, marks


def _commercial_spans_from_marks(
    marks: list[tuple[int, int]],
    *,
    fallback_total_frames: int,
) -> list[tuple[int, int]]:
    spans: list[tuple[int, int]] = []
    start_frame: int | None = None
    for frame, mark_type in sorted(marks, key=lambda item: item[0]):
        if mark_type == 4:
            if start_frame is None:
                start_frame = frame
            continue
        if start_frame is None:
            continue
        end_frame = max(frame, start_frame + 1)
        spans.append((start_frame, end_frame))
        start_frame = None
    if start_frame is not None:
        spans.append((start_frame, max(fallback_total_frames, start_frame + 1)))
    return spans


def _seconds_spans_from_frames(
    frame_spans: list[tuple[int, int]],
    *,
    fps: float,
    duration_seconds: float,
) -> list[tuple[float, float]]:
    intervals: list[tuple[float, float]] = []
    for start_frame, end_frame in frame_spans:
        start_s = max(0.0, start_frame / fps)
        end_s = min(duration_seconds, end_frame / fps)
        if end_s - start_s >= 0.15:
            intervals.append((start_s, end_s))
    return intervals


def _invert_intervals(duration_seconds: float, commercials: list[tuple[float, float]]) -> list[tuple[float, float]]:
    if not commercials:
        return [(0.0, duration_seconds)]
    cleaned: list[tuple[float, float]] = []
    for start, end in sorted(commercials, key=lambda item: item[0]):
        s = max(0.0, min(start, duration_seconds))
        e = max(0.0, min(end, duration_seconds))
        if e <= s:
            continue
        if cleaned and s <= cleaned[-1][1] + 0.05:
            cleaned[-1] = (cleaned[-1][0], max(cleaned[-1][1], e))
        else:
            cleaned.append((s, e))
    keep: list[tuple[float, float]] = []
    cursor = 0.0
    for start, end in cleaned:
        if start - cursor >= 0.25:
            keep.append((cursor, start))
        cursor = max(cursor, end)
    if duration_seconds - cursor >= 0.25:
        keep.append((cursor, duration_seconds))
    return keep


def detect_commercials_with_mythcommflag(input_path: Path, *, log_file: Path) -> list[tuple[float, float]]:
    mythcommflag = resolve_mythcommflag_exe()
    if mythcommflag is None:
        raise FileNotFoundError(
            "mythcommflag not found (expected tools/mythtv/mythcommflag.exe or PATH).",
        )
    analysis_input = input_path
    output_file = analysis_input.with_suffix(".mythcommflag.txt")
    try:
        _run_mythcommflag_detection(
            mythcommflag=mythcommflag,
            analysis_input=analysis_input,
            output_file=output_file,
            log_file=log_file,
        )
    except Exception:
        # Some Windows x86 mythcommflag builds fail on >2GB files. Build a small proxy for detection only.
        if input_path.stat().st_size <= 2_000_000_000:
            raise
        analysis_input = _build_detection_proxy(input_path, log_file=log_file)
        output_file = analysis_input.with_suffix(".mythcommflag.txt")
        _run_mythcommflag_detection(
            mythcommflag=mythcommflag,
            analysis_input=analysis_input,
            output_file=output_file,
            log_file=log_file,
        )

    total_frames, marks = _parse_mythcommflag_marks(output_file)
    if not marks:
        return []

    fps = _probe_video_fps(analysis_input)
    duration_s = _probe_duration_seconds(analysis_input)
    fallback_total_frames = total_frames if total_frames and total_frames > 0 else int(math.ceil(duration_s * fps))
    frame_spans = _commercial_spans_from_marks(marks, fallback_total_frames=fallback_total_frames)
    intervals = _seconds_spans_from_frames(frame_spans, fps=fps, duration_seconds=duration_s)
    if analysis_input == input_path:
        return intervals

    input_duration_s = _probe_duration_seconds(input_path)
    if duration_s <= 0:
        return intervals
    scale = input_duration_s / duration_s
    adjusted: list[tuple[float, float]] = []
    for start, end in intervals:
        s = max(0.0, min(input_duration_s, start * scale))
        e = max(0.0, min(input_duration_s, end * scale))
        if e > s:
            adjusted.append((s, e))
    return adjusted


def _build_clean_output_path(input_path: Path) -> Path:
    output_suffix = input_path.suffix.lower() if input_path.suffix.lower() in (".mp4", ".mkv") else ".mkv"
    return input_path.with_name(f"{input_path.stem}_clean{output_suffix}")


def _build_concat_filter(keep_ranges: list[tuple[float, float]], *, with_audio: bool) -> str:
    parts: list[str] = []
    for idx, (start, end) in enumerate(keep_ranges):
        parts.append(f"[0:v:0]trim=start={start:.6f}:end={end:.6f},setpts=PTS-STARTPTS[v{idx}]")
        if with_audio:
            parts.append(f"[0:a:0]atrim=start={start:.6f}:end={end:.6f},asetpts=PTS-STARTPTS[a{idx}]")
    video_inputs = "".join(f"[v{idx}]" for idx in range(len(keep_ranges)))
    if with_audio:
        interleaved_inputs = "".join(f"[v{idx}][a{idx}]" for idx in range(len(keep_ranges)))
        parts.append(f"{interleaved_inputs}concat=n={len(keep_ranges)}:v=1:a=1[vout][aout]")
    else:
        parts.append(f"{video_inputs}concat=n={len(keep_ranges)}:v=1:a=0[vout]")
    return ";".join(parts)


def cut_commercials_with_ffmpeg(
    input_path: Path,
    commercials: list[tuple[float, float]],
    *,
    log_file: Path,
) -> Path:
    duration_s = _probe_duration_seconds(input_path)
    keep_ranges = _invert_intervals(duration_s, commercials)
    if not keep_ranges:
        raise RuntimeError("All content was flagged as commercials; refusing to generate an empty cleaned file.")

    output_path = _build_clean_output_path(input_path)
    reserved_prior_clean: Path | None = None
    if output_path.exists():
        moved = _next_available(output_path)
        output_path.replace(moved)
        reserved_prior_clean = moved

    has_audio = _input_has_audio(input_path)
    filter_complex = _build_concat_filter(keep_ranges, with_audio=has_audio)
    argv = [
        str(ffmpeg_exe()),
        "-y",
        "-i",
        str(input_path),
        "-filter_complex",
        filter_complex,
        "-map",
        "[vout]",
    ]
    if has_audio:
        argv.extend(["-map", "[aout]", "-c:a", "aac", "-b:a", "160k"])
    argv.extend(
        [
            "-c:v",
            "libx264",
            "-preset",
            "veryfast",
            "-crf",
            "18",
            str(output_path),
        ],
    )
    code = _run_logged(argv, log_file=log_file, title="postprocess: ffmpeg cut")
    if code != 0:
        if reserved_prior_clean is not None and reserved_prior_clean.is_file():
            reserved_prior_clean.replace(output_path)
        raise RuntimeError(f"ffmpeg commercial cutting failed with exit code {code}")
    if not output_path.is_file():
        if reserved_prior_clean is not None and reserved_prior_clean.is_file():
            reserved_prior_clean.replace(output_path)
        raise FileNotFoundError(f"ffmpeg completed but cleaned output was not found at {output_path}")
    return output_path


def run_postprocessing(job, *, recorded_path: Path, log_file: Path) -> PostprocessResult:
    if not job.remove_commercials_after_complete:
        return PostprocessResult(True, 0, recorded_path)

    current = recorded_path
    try:
        settings = _load_runtime_settings(job)
        duration_s = _probe_duration_seconds(current)
        if settings.episode_aware:
            blocks = detect_episode_blocks(
                current,
                min_gap_seconds=settings.episode_boundary_min_gap_seconds,
                min_black_seconds=settings.episode_boundary_black_min_seconds,
                min_silence_seconds=settings.episode_boundary_silence_min_seconds,
            )
        else:
            blocks = [(0.0, duration_s)]

        detector_spans: dict[str, list[tuple[float, float]]] = {}
        if settings.strategy in ("myth_only", "hybrid") and settings.enable_myth:
            myth_spans = detect_commercials_with_mythcommflag(current, log_file=log_file)
            detector_spans["myth"] = _clip_spans_to_blocks(myth_spans, blocks)
        if settings.strategy in ("legacy_only", "hybrid") and settings.enable_legacy:
            legacy_spans = detect_commercials_with_legacy_detector(current, log_file=log_file)
            detector_spans["legacy"] = _clip_spans_to_blocks(legacy_spans, blocks)
        if settings.strategy == "hybrid" and settings.enable_ffmpeg_signals:
            ffmpeg_spans = detect_commercials_with_ffmpeg_signals(current, log_file=log_file)
            detector_spans["ffmpeg_signals"] = _clip_spans_to_blocks(ffmpeg_spans, blocks)

        weights = {
            "myth": settings.weight_myth,
            "legacy": settings.weight_legacy,
            "ffmpeg_signals": settings.weight_ffmpeg_signals,
        }
        fused_spans: list[FusedSpan] = fuse_commercial_spans(
            detector_spans=detector_spans,
            detector_weights=weights,
            duration_seconds=duration_s,
            confidence_threshold=settings.confidence_threshold,
        )
        decision = validate_and_guard_cutlist(
            fused_spans=fused_spans,
            duration_seconds=duration_s,
            max_commercial_ratio=settings.max_commercial_ratio,
            min_keep_segment_seconds=settings.min_keep_segment_seconds,
            fail_safe_mode=settings.fail_safe_mode,
            low_risk_max_commercial_ratio=settings.low_risk_max_commercial_ratio,
        )
        if not decision.allowed:
            return PostprocessResult(True, 0, current, decision.reason)
        commercials = [(span.start, span.end) for span in decision.spans]
        if commercials:
            current = cut_commercials_with_ffmpeg(current, commercials, log_file=log_file)
    except Exception as exc:
        return PostprocessResult(False, 3, current, str(exc))

    return PostprocessResult(True, 0, current)
