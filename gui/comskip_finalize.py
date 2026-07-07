"""Post-record Comskip orchestration."""

from __future__ import annotations

import json
import shutil
import traceback
from pathlib import Path

from comskip_chapters import write_chapters_ffmeta
from comskip_merge import (
    CommercialBreak,
    commercial_breaks_from_txt,
    merge_commercial_breaks,
    parse_comskip_edl,
    probe_video_fps,
    write_merged_edl,
    write_merged_txt,
)
from comskip_mode import comskip_available, comskip_supported_output
from comskip_worker import comskip_sidecar_edl, comskip_sidecar_txt, try_run_comskip
from episode_boundaries import detect_episode_boundaries, job_duration_seconds
from paths import comskip_ini, comskip_work_dir, ffmpeg_exe
from recorder import probe_stream_duration, run_ffmpeg


def _log(log_file: Path | None, message: str) -> None:
    if log_file is None:
        return
    try:
        log_file.parent.mkdir(parents=True, exist_ok=True)
        with open(log_file, "a", encoding="utf-8") as f:
            f.write(message.rstrip() + "\n")
    except OSError:
        pass


def _sidecars_exist(output_path: Path) -> bool:
    manifest = Path(str(output_path) + ".comskip.json")
    if manifest.is_file() and manifest.stat().st_size > 0:
        return True
    edl = comskip_sidecar_edl(output_path)
    return edl.is_file() and edl.stat().st_size > 0


def _build_segment_extract_argv(
    ts_path: Path,
    start_sec: float,
    end_sec: float,
    out_seg: Path,
) -> list[str]:
    return [
        str(ffmpeg_exe()),
        "-y",
        "-ss",
        f"{start_sec:.3f}",
        "-to",
        f"{end_sec:.3f}",
        "-i",
        str(ts_path),
        "-map",
        "0",
        "-c",
        "copy",
        str(out_seg),
    ]


def _extract_segment(
    ts_path: Path,
    start_sec: float,
    end_sec: float,
    out_seg: Path,
    *,
    log_file: Path | None,
) -> bool:
    argv = _build_segment_extract_argv(ts_path, start_sec, end_sec, out_seg)
    code = run_ffmpeg(argv, log_file=log_file)
    try:
        return code == 0 and out_seg.is_file() and out_seg.stat().st_size > 0
    except OSError:
        return False


def _breaks_from_sidecars(
    edl_path: Path | None,
    txt_path: Path | None,
    *,
    fps: float,
) -> list[CommercialBreak]:
    if edl_path is not None and edl_path.is_file():
        return parse_comskip_edl(edl_path)
    if txt_path is not None and txt_path.is_file():
        return commercial_breaks_from_txt(txt_path, fps=fps)
    return []


def _write_manifest(
    output_path: Path,
    *,
    mode: str,
    segments: list,
    fps: float,
    total_sec: float,
    commercial_count: int,
) -> None:
    manifest = Path(str(output_path) + ".comskip.json")
    payload = {
        "version": 1,
        "mode": mode,
        "fps": fps,
        "total_sec": total_sec,
        "commercial_count": commercial_count,
        "segments": [
            {
                "index": seg.index,
                "start_sec": seg.start_sec,
                "end_sec": seg.end_sec,
            }
            for seg in segments
        ],
    }
    manifest.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def maybe_run_comskip(
    output_path: Path,
    *,
    enabled: bool,
    job_duration: str,
    log_file: Path | None = None,
) -> bool:
    """Run Comskip when enabled; return True when sidecars were written."""
    if not enabled:
        return False
    if not comskip_supported_output(output_path):
        _log(log_file, "comskip: skipped (output is not .ts)")
        return False
    if not comskip_available():
        _log(log_file, "comskip: skipped (comskip.exe or comskip.ini not found)")
        return False
    if _sidecars_exist(output_path):
        _log(log_file, "comskip: skipped (sidecars already exist)")
        return False

    work_root: Path | None = None
    try:
        total_sec = probe_stream_duration(output_path, "v:0") or 0.0
        if total_sec <= 0:
            _log(log_file, "comskip: skipped (could not probe duration)")
            return False

        fps = probe_video_fps(output_path)
        job_sec = job_duration_seconds(job_duration)
        segments = detect_episode_boundaries(
            output_path,
            job_duration_sec=job_sec,
            log_file=log_file,
        )
        if segments and segments[0].end_sec > 0:
            total_sec = max(total_sec, segments[-1].end_sec)

        ini = comskip_ini()
        breaks: list[CommercialBreak] = []
        mode = "whole_file"

        if len(segments) <= 1:
            result = try_run_comskip(output_path, ini_path=ini, log_file=log_file)
            if not result.ok:
                _log(log_file, f"comskip: run failed (exit {result.exit_code})")
                return False
            breaks = _breaks_from_sidecars(result.edl_path, result.txt_path, fps=fps)
        else:
            mode = "multi_episode"
            work_root = comskip_work_dir() / output_path.stem
            work_root.mkdir(parents=True, exist_ok=True)
            merge_inputs: list = []
            for seg in segments:
                seg_path = work_root / f"{output_path.stem}_ep{seg.index}.ts"
                if not _extract_segment(
                    output_path,
                    seg.start_sec,
                    seg.end_sec,
                    seg_path,
                    log_file=log_file,
                ):
                    _log(log_file, f"comskip: segment extract failed for episode {seg.index}")
                    continue
                result = try_run_comskip(seg_path, ini_path=ini, log_file=log_file)
                if not result.ok:
                    _log(log_file, f"comskip: segment {seg.index} failed (exit {result.exit_code})")
                    continue
                merge_inputs.append((seg, result.edl_path, result.txt_path))
            if not merge_inputs:
                _log(log_file, "comskip: no segment produced commercial markers")
                return False
            breaks = merge_commercial_breaks(merge_inputs, total_sec=total_sec)
            master_edl = comskip_sidecar_edl(output_path)
            master_txt = comskip_sidecar_txt(output_path)
            write_merged_edl(master_edl, breaks)
            write_merged_txt(master_txt, breaks, fps=fps, total_sec=total_sec)

        chapters_path = Path(str(output_path) + ".chapters.ffmeta")
        write_chapters_ffmeta(
            chapters_path,
            title=output_path.stem,
            episodes=segments if segments else [],
            commercials=breaks,
            total_sec=total_sec,
        )
        _write_manifest(
            output_path,
            mode=mode,
            segments=segments,
            fps=fps,
            total_sec=total_sec,
            commercial_count=len(breaks),
        )
        _log(log_file, f"comskip: wrote {len(breaks)} commercial markers ({mode})")
        return True
    except Exception:
        _log(log_file, "comskip: error during processing")
        _log(log_file, traceback.format_exc())
        try:
            Path(str(output_path) + ".comskip.failed.txt").write_text(
                traceback.format_exc(),
                encoding="utf-8",
            )
        except OSError:
            pass
        return False
    finally:
        if work_root is not None and work_root.is_dir():
            shutil.rmtree(work_root, ignore_errors=True)
