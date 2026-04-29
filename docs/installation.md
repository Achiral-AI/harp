# Installation

## 1. Prerequisites

- macOS 13+, Linux, or WSL2
- Docker Desktop / Docker Engine with Compose v2
- A Warp OSS checkout you can build from source
- A local model runtime exposing an OpenAI-compatible API. Easiest:
  [Ollama](https://ollama.com) running on the host

## 2. Clone with submodules

```bash
git clone --recurse-submodules https://github.com/marvindanig/harp.git
cd harp
```

If you already cloned without `--recurse-submodules`:

```bash
git submodule update --init --recursive
```

## 3. Configure

```bash
cp .env.example .env
```

Edit `.env`. The minimum you need to change:

- `OLLAMA_BASE_URL` — usually `http://host.docker.internal:11434` on macOS/Windows
- `LOCAL_PRIMARY_MODEL` — must be a model you've already pulled, e.g.
  `ollama pull qwen2.5-coder:32b-instruct`

Optional:

- `ANTHROPIC_API_KEY` / `OPENAI_API_KEY` / `GOOGLE_API_KEY` for frontier
  fallbacks and the response-improver feature

## 4. Start the stack

```bash
make up
make smoke    # should print {"ok":true,...}
make logs     # tail combined logs
```

This brings up two containers: `harp` on `:8787` and `harp-litellm` on
`:4000`.

## 5. Patch and build Warp OSS

The OSS Warp client gates `WARP_SERVER_ROOT_URL` overrides on internal channels
only. Apply the included patch to opt the OSS channel in:

```bash
make patch-warp WARP_DIR=/path/to/your/warp-checkout
cd /path/to/your/warp-checkout
brew install protobuf      # bootstrap doesn't install this; the build needs it
./script/bootstrap         # first time only; platform deps
./script/run               # builds and runs `WarpOss.app` from source
```

If bootstrap exits with `Please install Xcode from the App Store...`, install
full Xcode (~12 GB), then run `sudo xcodebuild -license` and accept it before
re-running bootstrap. See [`development.md`](development.md) and
[`building-warp.md`](building-warp.md) for the full set of footguns we hit.

## 6. Point Warp at Harp

```bash
WARP_SERVER_ROOT_URL=http://127.0.0.1:8787 ./script/run
```

You should see in `make logs` that requests are flowing through Harp. If
`SHIM_MODE=hijack`, eligible inference requests are served from your local model
and ineligible ones are forwarded to `app.warp.dev` automatically.

## 7. (Optional) switch modes

Edit `.env`:

```
SHIM_MODE=hijack       # local-first, fall back to upstream
# SHIM_MODE=local-only # never forward upstream
# SHIM_MODE=proxy      # smoke-test mode, all traffic to upstream
```

```bash
make down && make up
```
