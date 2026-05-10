"""Validation and fail-safe handling for commercial cutlists."""

from __future__ import annotations

from dataclasses import dataclass

from span_fusion import FusedSpan


@dataclass
class CutlistDecision:
    allowed: bool
    spans: list[FusedSpan]
    reason: str = ""


def _sum_duration(spans: list[FusedSpan]) -> float:
    return sum(max(0.0, span.end - span.start) for span in spans)


def _ensure_min_keep_gaps(spans: list[FusedSpan], *, duration_seconds: float, min_keep_seconds: float) -> bool:
    if min_keep_seconds <= 0:
        return True
    if not spans:
        return duration_seconds >= min_keep_seconds
    cursor = 0.0
    for span in sorted(spans, key=lambda item: item.start):
        if span.start - cursor < min_keep_seconds:
            return False
        cursor = max(cursor, span.end)
    return duration_seconds - cursor >= min_keep_seconds


def validate_and_guard_cutlist(
    *,
    fused_spans: list[FusedSpan],
    duration_seconds: float,
    max_commercial_ratio: float,
    min_keep_segment_seconds: float,
    fail_safe_mode: str,
    low_risk_max_commercial_ratio: float,
) -> CutlistDecision:
    ordered = sorted(fused_spans, key=lambda item: item.start)
    if duration_seconds <= 0:
        return CutlistDecision(False, [], "Invalid duration; refusing commercial cut.")
    if not ordered:
        return CutlistDecision(True, [], "No commercials detected.")

    removed_seconds = _sum_duration(ordered)
    commercial_ratio = removed_seconds / duration_seconds
    keep_ok = _ensure_min_keep_gaps(
        ordered,
        duration_seconds=duration_seconds,
        min_keep_seconds=min_keep_segment_seconds,
    )

    if keep_ok and commercial_ratio <= max_commercial_ratio:
        return CutlistDecision(True, ordered)

    if fail_safe_mode == "no_cut":
        return CutlistDecision(
            False,
            [],
            (
                f"Quality gate rejected cutlist (ratio={commercial_ratio:.3f}, "
                f"max={max_commercial_ratio:.3f}, keep_ok={keep_ok}); fail-safe=no_cut."
            ),
        )

    if fail_safe_mode == "low_risk_cut":
        low_risk: list[FusedSpan] = [span for span in ordered if span.confidence >= 0.80]
        low_risk_removed = _sum_duration(low_risk)
        low_risk_ratio = low_risk_removed / duration_seconds
        low_risk_keep_ok = _ensure_min_keep_gaps(
            low_risk,
            duration_seconds=duration_seconds,
            min_keep_seconds=min_keep_segment_seconds,
        )
        if low_risk and low_risk_keep_ok and low_risk_ratio <= low_risk_max_commercial_ratio:
            return CutlistDecision(
                True,
                low_risk,
                (
                    "Primary cutlist rejected by quality gate; "
                    "applied low-risk subset."
                ),
            )
        return CutlistDecision(
            False,
            [],
            (
                f"Quality gate rejected cutlist and low-risk fallback failed "
                f"(ratio={commercial_ratio:.3f}, keep_ok={keep_ok}, "
                f"low_risk_ratio={low_risk_ratio:.3f}, low_risk_keep_ok={low_risk_keep_ok})."
            ),
        )

    return CutlistDecision(False, [], f"Unknown fail-safe mode: {fail_safe_mode}")
