# Harp local-serve ratio pill in patched Warp OSS

## Problem
Add a UI element in the top-right corner of the patched Warp OSS window that shows the live "local-serve ratio" (the same headline metric `make watch` displays) by default, while Warp is being routed through Harp.

## Current state
- `make watch` already shows this data in a terminal by polling `http://127.0.0.1:${SHIM_PORT:-8787}/stats` once per second (`scripts/harp-watch`, `Makefile:24-25`). Snapshot JSON keys: `total`, `served_local`, `forwarded_upstream`, `errors`, `local_serve_ratio`, `uptime_s`.
- Patched Warp OSS already routes through Harp via `WARP_SERVER_ROOT_URL`. Inside Warp the configured origin is reachable as `ChannelState::server_root_url()` (`crates/warp_core/src/channel/state.rs:263`), so the same origin that serves `/ai/multi-agent` also serves `/stats`.
- Right-side tab-bar chrome is composed in `add_configurable_right_side_tab_bar_controls` in `app/src/workspace/view.rs (17291-17402)`. Existing precedent for a small pill widget lives in `render_tab_overflow_menu` (`app/src/workspace/view.rs:18044`) — the "update ready" pill — using `Container` + `Border::all` + `CornerRadius::Percentage(50)` and `TAB_BAR_PILL_WIDTH`.
- Harp ships exactly one patch today, `patches/0001-allow-oss-channel-server-url-override.patch`, applied via `make patch-warp WARP_DIR=...` (`Makefile:27-30`, documented in `README.md (67-78)`).

## Proposed change
Two coordinated pieces, both shipped from the Harp repo so a clean Warp OSS checkout remains untouched.

### 1. New shipped patch: `patches/0002-harp-stats-pill.patch`
Adds a small status pill to Warp's right-side tab bar that polls `<server_root_url>/stats` once per second and renders the live local-serve ratio.

- New module `app/src/workspace/harp_stats.rs`:
  - `HarpStatsSnapshot { total, served_local, forwarded_upstream, errors, local_serve_ratio, uptime_s }` deserialized via `serde_json` from the same fields produced by `src/harp/stats.py`. No new fields invented — schema is taken verbatim from what `harp-watch` already consumes.
  - `HarpStatsModel`: a GPUI model owning the latest `Option<HarpStatsSnapshot>` plus a `reachable: bool` flag. A background task is spawned at workspace init using the executor pattern already used elsewhere in `app/src/workspace/view.rs`, calling `<ChannelState::server_root_url()>/stats` via the `http_client` crate already in the workspace.
  - On any failure (connection refused, 404, JSON parse error, non-2xx) the model flips `reachable = false` so the pill disappears; otherwise it stores the snapshot and notifies observers.
- Modification to `app/src/workspace/view.rs`:
  - In `add_configurable_right_side_tab_bar_controls`, prepend a pill (when `HarpStatsModel::reachable()`) styled like the existing update pill: rounded `Container`, accent border, `PILL_FONT_SIZE` text. Label is `H · {local_serve_ratio:.0%}` (e.g. `H · 62%`).
  - Tooltip mirrors `harp-watch`'s headline numbers: total / served-local / forwarded-upstream / uptime.
  - The pill is positioned at the right edge of the tab bar, to the left of the avatar/settings buttons (effectively the visual top-right corner of the window).
  - Default behavior: pill shows automatically when `/stats` responds with valid JSON, silently absent otherwise. No feature flag required for v1; `make watch` continues to work for users who prefer the terminal view.
- `Makefile`'s `patch-warp` target updated to `git apply` both patch files in order.
- `README.md` "Tracking your actual savings" section updated to mention the in-window pill alongside `make watch` / `make stats`.

### 2. Harp-side verification (no code change expected)
`/stats` is already an unauthenticated GET on the same origin Warp talks to. The plan includes a verification step (curl `/stats` from a fresh container in `proxy`, `hijack`, and `local-only` modes) to confirm the pill won't silently break in any `SHIM_MODE` before shipping.

## Out of scope
- Rewriting `scripts/harp-watch` — it stays as the headless / scriptable view.
- Persisting stats across container restarts (counters still reset on restart, same as today).
- A settings-page toggle to hide the pill — can be added later if requested; v1 hides itself automatically when `/stats` is unreachable.

## Validation
- `cargo check` on a Warp OSS checkout with both patches applied (the same checkout `make patch-warp` already targets).
- Manual: launch `WarpOss.app` with `WARP_SERVER_ROOT_URL=http://127.0.0.1:8787 ./script/run`, fire a few prompts, confirm the pill appears in the top-right and the percentage moves as `make stats` updates.
- Manual: launch `WarpOss.app` without Harp running and confirm the pill is absent with no error toast or log spam.
- `make stats` continues to return JSON with the exact fields the pill consumes (regression check that the schema in `harp_stats.rs` stays in sync with `src/harp/stats.py`).
