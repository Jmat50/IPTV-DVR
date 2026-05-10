"""Utilities for fusing detector-produced commercial spans."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class FusedSpan:
    start: float
    end: float
    confidence: float
    sources: list[str]


def _clamp_interval(start: float, end: float, duration_seconds: float) -> tuple[float, float] | None:
    s = max(0.0, min(duration_seconds, start))
    e = max(0.0, min(duration_seconds, end))
    if e <= s:
        return None
    return s, e


def _merge_touching(spans: list[FusedSpan], *, tolerance_seconds: float = 0.35) -> list[FusedSpan]:
    if not spans:
        return []
    ordered = sorted(spans, key=lambda item: item.start)
    merged: list[FusedSpan] = [ordered[0]]
    for span in ordered[1:]:
        prev = merged[-1]
        if span.start <= prev.end + tolerance_seconds:
            new_start = min(prev.start, span.start)
            new_end = max(prev.end, span.end)
            weighted_conf = ((prev.confidence * (prev.end - prev.start)) + (span.confidence * (span.end - span.start))) / (
                (prev.end - prev.start) + (span.end - span.start)
            )
            new_sources = sorted(set(prev.sources + span.sources))
            merged[-1] = FusedSpan(new_start, new_end, weighted_conf, new_sources)
        else:
            merged.append(span)
    return merged


def fuse_commercial_spans(
    *,
    detector_spans: dict[str, list[tuple[float, float]]],
    detector_weights: dict[str, float],
    duration_seconds: float,
    confidence_threshold: float,
) -> list[FusedSpan]:
    """Fuse multiple detector outputs into weighted-confidence intervals."""
    points: set[float] = {0.0, duration_seconds}
    prepared: dict[str, list[tuple[float, float]]] = {}
    enabled_weight_total = 0.0
    for source, spans in detector_spans.items():
        weight = max(0.0, float(detector_weights.get(source, 0.0)))
        if weight <= 0:
            continue
        enabled_weight_total += weight
        normalized: list[tuple[float, float]] = []
        for start, end in spans:
            clamped = _clamp_interval(start, end, duration_seconds)
            if clamped is None:
                continue
            normalized.append(clamped)
            points.add(clamped[0])
            points.add(clamped[1])
        if normalized:
            prepared[source] = normalized

    if enabled_weight_total <= 0.0 or not prepared:
        return []

    ordered_points = sorted(points)
    fused: list[FusedSpan] = []
    for idx in range(len(ordered_points) - 1):
        seg_start = ordered_points[idx]
        seg_end = ordered_points[idx + 1]
        if seg_end <= seg_start:
            continue
        midpoint = (seg_start + seg_end) / 2.0
        score = 0.0
        sources: list[str] = []
        for source, spans in prepared.items():
            covered = any(start <= midpoint < end for start, end in spans)
            if covered:
                weight = max(0.0, float(detector_weights.get(source, 0.0)))
                score += weight
                sources.append(source)
        confidence = score / enabled_weight_total
        if confidence >= confidence_threshold and sources:
            fused.append(FusedSpan(seg_start, seg_end, confidence, sorted(sources)))

    return _merge_touching(fused)
