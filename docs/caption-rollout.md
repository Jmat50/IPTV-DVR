# Caption overhaul rollout

## Staged enablement

1. **Default for new jobs:** `caption_mode: off` (unchanged until user opts in).
2. **Migration:** existing `download_captions: true` loads as `auto` on next config read/save.
3. **Promote to default:** after validation, switch Job Editor default from `off` to `auto` in code.

## Acceptance checks

| Scenario | Expected |
|----------|----------|
| Mode `off` | No sidecar processes; record unchanged. |
| Mode `post_only`, `.ts`, embedded 608 | `.srt` after record via FFmpeg fallback. |
| Mode `live_ccextractor`, CCExtractor present | `.srt` exists at end; may grow during record. |
| Mode `auto`, no CCExtractor | Same as `post_only`. |
| HLS subs on manifest | `.vtt` during record when probe succeeds. |
| Live worker failure | Post-extract still runs; log notes live failure. |
| Scheduled late start | Caption duration matches trimmed `-t`. |
| Manual run-now | Full duration; no window skip. |

## Regression gates

- `go test ./...`
- `python -m compileall gui`
- `cd gui && python -m unittest caption_mode_test caption_worker_test`
- Windows: one 15s test capture with captions `auto` + CCExtractor installed.
