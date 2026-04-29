# harp
A local-first inference shim for the open-source
[Warp](https://github.com/warpdotdev/warp) terminal. (Yes, the W flipped.)
harp routes Warp's native agent (Oz) through a model running on your own
machine via [Ollama](https://ollama.com), [vLLM](https://github.com/vllm-project/vllm),
[LM Studio](https://lmstudio.ai), or anything OpenAI-compatible — and falls back
to Warp's own backend (and frontier models behind it) when the local model isn't
a good fit for the request.

```text
                      ┌──────────────────────────────────────┐
 patched Warp client  │                                      │
 ────────────────────►│  harp  (this project, :8787)         │
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
full multi-agent server protocol is a multi-week project. harp sidesteps that
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
git clone --recurse-submodules https://github.com/your-org/harp.git
cd harp
cp .env.example .env
# edit .env to set OLLAMA_BASE_URL and (optionally) ANTHROPIC_API_KEY etc.
docker compose up -d
```
Apply the Warp OSS channel patch:
```bash
cd /path/to/your/warp-checkout
git apply /path/to/harp/patches/0001-allow-oss-channel-server-url-override.patch
./script/run    # builds and launches the patched Warp
```

Point Warp at harp:

```bash
WARP_SERVER_ROOT_URL=http://127.0.0.1:8787 ./script/run
```

That's it. Warp will sign in normally (harp forwards the auth dance to
`app.warp.dev`), and inference requests will be served locally when eligible.

## Modes

harp has three operating modes, controlled by `SHIM_MODE` in `.env`:

- `proxy` *(default)* — pure transparent proxy. No local inference. Useful as a
  smoke test that the patched Warp + override + harp are wired correctly.
- `hijack` — try local model first; fall back to upstream on ineligible
  requests, errors, or low-quality responses.
- `local-only` — refuse to forward upstream. For air-gapped / fully-offline
  use. Expect failures on agentic flows that local models can't handle yet.

## Project layout

```
src/harp/            Python package source
tests/               Unit tests
Dockerfile           Builds the harp image
docker-compose.yml   Compose stack: harp + litellm
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
