"""Benchmark Myth-only, Legacy-only, and Hybrid post-processing strategies."""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path


def _repo_root() -> Path:
    return Path(__file__).resolve().parent.parent


def _build_job(strategy: str):
    sys.path.insert(0, str(_repo_root() / "gui"))
    from config_store import CommercialRemovalSettings

    class Job:
        remove_commercials_after_complete = True
        commercial_settings = CommercialRemovalSettings(strategy=strategy)  # type: ignore[arg-type]

    return Job()


def _probe(path: Path) -> dict[str, float]:
    import subprocess

    ffprobe = _repo_root() / "gui" / "ffmpeg" / "ffprobe.exe"
    out = subprocess.check_output(
        [
            str(ffprobe),
            "-v",
            "error",
            "-show_entries",
            "format=duration,size,bit_rate",
            "-of",
            "default=noprint_wrappers=1:nokey=1",
            str(path),
        ],
        text=True,
        stderr=subprocess.STDOUT,
    )
    vals = [x.strip() for x in out.splitlines() if x.strip()]
    return {
        "duration_seconds": float(vals[0]),
        "size_bytes": float(vals[1]),
        "bit_rate": float(vals[2]),
    }


def run_benchmark(inputs: list[Path], output_path: Path | None) -> dict:
    sys.path.insert(0, str(_repo_root() / "gui"))
    import postprocess

    results: list[dict] = []
    strategies = ["myth_only", "legacy_only", "hybrid"]
    for input_path in inputs:
        item: dict = {
            "input": str(input_path),
            "input_probe": _probe(input_path),
            "strategies": {},
        }
        for strategy in strategies:
            log_file = input_path.with_name(f"{input_path.stem}_{strategy}.benchmark.log")
            job = _build_job(strategy)
            t0 = time.time()
            result = postprocess.run_postprocessing(job, recorded_path=input_path, log_file=log_file)
            elapsed = time.time() - t0
            strategy_result = {
                "success": result.success,
                "exit_code": result.exit_code,
                "output_path": str(result.output_path),
                "message": result.message,
                "elapsed_seconds": elapsed,
                "log_file": str(log_file),
            }
            out_path = Path(strategy_result["output_path"])
            if out_path.is_file():
                strategy_result["output_probe"] = _probe(out_path)
            item["strategies"][strategy] = strategy_result
        results.append(item)
    payload = {"benchmarked_at_epoch": time.time(), "results": results}
    if output_path:
        output_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return payload


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--inputs", nargs="+", required=True, help="Input recording files to benchmark.")
    p.add_argument("--out", default="", help="Optional output JSON file.")
    args = p.parse_args()
    inputs = [Path(x).expanduser() for x in args.inputs]
    missing = [str(x) for x in inputs if not x.is_file()]
    if missing:
        print(json.dumps({"error": "missing_input_files", "files": missing}, indent=2))
        return 2
    out = Path(args.out).expanduser() if args.out else None
    payload = run_benchmark(inputs, out)
    print(json.dumps(payload, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
