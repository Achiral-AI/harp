# Harp
A local-first inference shim for the open-source
[Warp](https://github.com/warpdotdev/warp) terminal. (Yes, the W flipped.)
Harp routes Warp's native agent (Oz) through a model running on your own
machine via [Ollama](https://ollama.com), [vLLM](https://github.com/vllm-project/vllm),
[LM Studio](https://lmstudio.ai), or anything OpenAI-compatible — and falls back
to Warp's own backend (and frontier models behind it) when the local model isn't
a good fit for the request.

```text
                      ┌──────────────────────────────────────┐
 patched Warp client  │                                      │
 ────────────────────►│  Harp  (this project, :8787)         │
 WARP_SERVER_ROOT_URL │                                      │
 = http://:8787       │  • transparent reverse proxy of all  │
                      │    auth, GraphQL, telemetry, …       │
                      │                                      │
                      │  • hijacks POST /ai/multi-agent only │──► LiteLLM (:4000)
                      │    – decode protobuf Request          │       │
                      │    – eligible? serve from local      │       ├─► Ollama
                      │      model and emit ResponseEvent SSE│       └─► frontier APIs
                      │    – not eligible? forward raw bytes │           (fallback / improver)
                      │      to app.warp.dev untouched       │──► https://app.warp.dev
                      └──────────────────────────────────────┘
```

## Why this exists

The OSS Warp repo is a *client*. All inference goes to a single endpoint on
`app.warp.dev`. There is no in-client provider SDK to swap. Re-implementing the
full multi-agent server protocol is a multi-week project. Harp sidesteps that
by transparently proxying everything to Warp's real backend by default and
only intercepting the inference endpoint when a local model can usefully serve
the request.

## What you need

- [Docker](https://docs.docker.com/get-docker/) and Docker Compose v2.
- A built copy of [Warp OSS](https://github.com/warpdotdev/warp) with one
  one-line patch applied (see [`patches/`](patches)) so it accepts
  `WARP_SERVER_ROOT_URL` overrides.
- A local model runtime. Ollama on the host is the easiest path on macOS for GPU
  access; vLLM/LM Studio also work as long as they expose an OpenAI-compatible
  HTTP API.
- Optional: API keys for Anthropic / OpenAI / Google if you want frontier
  fallback or response-improver behaviour.

## Install
```bash
git clone --recurse-submodules https://github.com/marvindanig/harp.git
cd harp
cp .env.example .env
# edit .env to set OLLAMA_BASE_URL and (optionally) ANTHROPIC_API_KEY etc.
docker compose up -d
```

Got a multi-replica vLLM/TRT-LLM cluster (e.g. behind Tailscale + NodePort)
rather than a single Ollama? Copy the example local config and point
`LITELLM_CONFIG` at it in `.env` — it's gitignored so personal endpoints
don't end up in version control:
```bash
cp litellm/config.local.yaml.example litellm/config.local.yaml
# edit litellm/config.local.yaml with your endpoint URLs and model name
sed -i '' 's|^LITELLM_CONFIG=.*|LITELLM_CONFIG=./litellm/config.local.yaml|' .env
docker compose up -d
```
Apply the Warp OSS channel patch and build:
```bash
cd /path/to/your/warp-checkout
git apply /path/to/harp/patches/0001-allow-oss-channel-server-url-override.patch
brew install protobuf  # bootstrap doesn't install this; the build needs it
./script/bootstrap     # may need `sudo xcodebuild -license` first
./script/run           # builds and launches `WarpOss.app`
```

Full walkthrough with all the gotchas we hit (Xcode license, missing
`protoc`, the `cargo` PATH stutter, `warp-channel-config` SSH warnings) is
in [`docs/building-warp.md`](docs/building-warp.md).

Point Warp at Harp:

```bash
WARP_SERVER_ROOT_URL=http://127.0.0.1:8787 ./script/run
```

That's it. Warp will sign in normally (Harp forwards the auth dance to
`app.warp.dev`), and inference requests will be served locally when eligible.

## Modes

Harp has three operating modes, controlled by `SHIM_MODE` in `.env`:

- `proxy` *(default)* — pure transparent proxy. No local inference. Useful as a
  smoke test that the patched Warp + override + Harp are wired correctly.
- `hijack` — try local model first; fall back to upstream on ineligible
  requests, errors, or low-quality responses.
- `local-only` — refuse to forward upstream. For air-gapped / fully-offline
  use. Expect failures on agentic flows that local models can't handle yet.

## Expected savings

Harp's *eligibility filter* decides which requests get served from your local
model vs. forwarded to Warp's backend. The wider the filter, the more spend
stays on your hardware — at the cost of degrading quality on agentic flows
that really need real tool calls.

| Stage                          | Eligible request types                                  | Typical spend served locally |
| ------------------------------ | ------------------------------------------------------- | ---------------------------- |
| v0.1 strict *(deprecated)*     | Plain user_query with no tools advertised               | ~0%                          |
| **v0.1.1 relaxed** *(current)* | Fresh user_query, even when the client advertises tools | **40–70%**                   |
| v0.2 read-only tools           | + `read_files`, `grep`, `file_glob`                     | 70–85%                       |
| v0.3 write tools               | + `apply_file_diffs` with guardrails                    | 95%+                          |
| v1.0 full proto                | Multi-turn agentic loops served locally                 | ~100%                         |

Caveats worth knowing:

- A weaker local model will fumble some agentic flows that frontier APIs nail.
  Failed local requests fall through to Warp's backend automatically; an
  optional frontier-improver pass can re-run iffy local outputs through a
  frontier model before returning.
- Local serving has higher token volume (no provider caching, longer replies)
  so your **electricity bill creeps up** but stays negligible vs API spend at
  typical home loads.
- Mileage varies by usage pattern. Heavy agentic coders save less under
  v0.1.1; heavy conversational users see the full 40–70%.

### Tracking your actual savings

Harp ships three views into its own counters at `GET /stats`:

```bash
make watch     # full-screen live terminal dashboard, refreshed every second
make stats     # one JSON snapshot for scripts / quick checks
```

In-window pill: the patched Warp OSS client also renders a live
`L:R 62:38` pill in the top-right of the tab bar (just left of the
avatar / settings buttons) that polls the same `/stats` endpoint once
per second. The pill is always on whenever Harp is reachable on the
configured `WARP_SERVER_ROOT_URL` and silently disappears otherwise,
so a vanilla Warp OSS launch sees nothing extra. Hover the pill for
the headline counts (total / local / upstream / uptime). The pill
ships via `patches/0002-harp-stats-pill.patch`, applied automatically
by `make patch-warp`.

The terminal dashboard additionally shows top ineligibility reasons
(so you know *why* requests bypass the local model) and top
upstream-forward reasons. Counters reset whenever the Harp container
restarts.

## Project layout

```
src/harp/            Python package source
tests/               Unit tests
Dockerfile           Builds the Harp image
docker-compose.yml   Compose stack: Harp + litellm
pyproject.toml       Python package metadata
litellm/             LiteLLM proxy config (model groups + fallbacks)
patches/             Patches to apply to a Warp OSS checkout
docs/                Architecture, installation, development, roadmap docs
vendor/              warp-proto-apis as a git submodule
.env.example         Sample environment configuration
```

## License

This project depends on protobuf bindings vendored from `warp-proto-apis`,
which is AGPL-3.0. See [`LICENSE`](LICENSE).
