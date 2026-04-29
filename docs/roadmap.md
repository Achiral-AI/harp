# Roadmap

## Shipped (v0.1)

- Patch for `Channel::Oss` to honour `WARP_SERVER_ROOT_URL`.
- Transparent reverse proxy of all Warp client traffic.
- `/ai/multi-agent` hijack with conservative eligibility filter.
- Minimal local `ResponseEvent` stream for plain user-query chats.
- LiteLLM proxy with `local-primary` and `frontier-fallback` model groups,
  plus error- and context-window-fallback chains.

## Shipped (v0.1.1)

- **Relaxed eligibility filter.** Fresh user queries are served locally even
  when the client advertises a toolset, as long as no prior tool-call history
  exists. Lifts typical local-serve ratio from ~0% to 40–70%.
- **Reasoning-mode handling.** `enable_thinking=false` is sent through to
  Qwen-class models via `chat_template_kwargs`, with a defensive
  `<think>...</think>` stripper on the streaming output for any leakage.
- **`LITELLM_CONFIG` env var** to point Compose at a personal LiteLLM config
  (e.g. `litellm/config.local.yaml`) without modifying the bundled defaults.
- **Multi-replica example config** (`litellm/config.local.yaml.example`)
  showing simple-shuffle round-robin across a self-hosted vLLM/TRT-LLM cluster
  reachable via NodePort + Tailscale.
- **`/stats` endpoint and `make watch` dashboard** for tracking the
  served-local ratio, error rate, and per-reason breakdowns of why requests
  bypass the local model.

## Shipped (v0.1.2)

- **Auth-redirect handler.** Browser-launched URLs (sign-up, login, upgrade,
  account, billing, team, referral) are 302'd to the real upstream so OAuth
  flows complete correctly. Without this, the patched Warp client opened
  `http://127.0.0.1:8787/signup/remote?...` in the browser and got nothing.
- **`docs/building-warp.md`.** Front-to-back walkthrough of building Warp OSS
  on macOS, including footguns Warp's own bootstrap doesn't surface
  (`protoc` missing, Xcode license at admin level, `cargo` PATH after fresh
  rustup, the `warp-channel-config` SSH warning).
- **HarpCache.** Bounded local project-context cache injected into local model
  prompts. It uses Warp's request metadata, active project rules, important
  project files, an ignore-aware manifest, and path-relevant snippets.
- **Protocol hardening.** Local streams preserve padded base64 URL-safe SSE
  frames, omit unsupported `StreamInit.run_id` for the vendored client proto,
  and return valid local SSE errors for unsupported hijack-mode requests.
- **Second-turn text support.** Follow-up user queries with prior task history
  are served locally with recent text-only history included in the model
  prompt.

## Next (v0.2)

- **Read-only tool execution locally.** Translate the client's `read_files`,
  `grep`, `file_glob` tool calls to OpenAI tool-call schema, run them locally,
  and feed the results back as `ResponseEvent` actions.
- **Frontier-improver pass.** Behind `ENABLE_FRONTIER_IMPROVER`, pipe local
  responses through a frontier model when a quality heuristic fails (very
  short, JSON-parse failure, repeated tokens).
- **Per-model routing.** Pick `local-primary` vs `frontier-fallback` based on
  request shape (e.g. coding query length, presence of code blocks).
- **Streaming-friendly tool-call mapping.** Ensure tool-call argument streaming
  doesn't get fragmented across multiple `AppendToMessageContent` events.

## Later (v0.3+)

- **Write tools.** Support `apply_file_diffs` round-trips locally with strong
  guardrails.
- **Conversation continuity.** Persist `conversation_id` ↔ assistant-message
  history so multi-turn chats work without falling back upstream.
- **Local embeddings.** Extend HarpCache with embeddings instead of relying
  only on bounded manifests and path-scored snippets.
- **Configurable hijack rules.** YAML-driven matchers (regex on user text, MCP
  server presence, etc.) instead of hard-coded eligibility logic.

## Out of scope

- Re-implementing telemetry, billing, or the Warp Drive cloud sync surface.
- Distributing modified Warp binaries (AGPL would obligate publishing changes
  for any networked redistribution).
- Multi-user / team deployments. The shim is a single-user localhost tool.
