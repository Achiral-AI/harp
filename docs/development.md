# Development
Notes for hacking on harp without Docker.
## Local development (without Docker)
```bash
# From the repo root.
python3 -m venv .venv
source .venv/bin/activate
pip install -e '.[dev]'
# Vendor the protobuf bindings into the package directory.
# (Docker builds do this automatically; this step is only for native runs.)
ln -s ../../vendor/warp-proto-apis/apis/multi_agent/v1/gen/python \
      src/harp/proto
touch src/harp/proto/__init__.py
# Run
SHIM_PORT=8787 python -m harp
```
## Configuration
All settings come from environment variables (see `../.env.example`). Inside
the package they're loaded by `harp.settings.Settings`.
## Source layout
- `src/harp/server.py` — FastAPI app. Mounts the catch-all proxy and the hijack handler.
- `src/harp/proxy.py` — transparent reverse proxy logic.
- `src/harp/hijack.py` — `/ai/multi-agent` decode + eligibility + dispatch.
- `src/harp/litellm_client.py` — OpenAI-compatible client targeting the LiteLLM proxy.
- `src/harp/proto_loader.py` — imports the vendored `*_pb2` modules.
- `src/harp/stream.py` — encodes `ResponseEvent` messages as base64-protobuf SSE frames.
- `src/harp/settings.py` — env-driven configuration via pydantic-settings.
## Tests
```bash
make test
# or:
python -m pytest -q
```
