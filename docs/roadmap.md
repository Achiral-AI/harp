# Roadmap

## Shipped (v0.1)

- Patch for `Channel::Oss` to honour `WARP_SERVER_ROOT_URL`.
- Transparent reverse proxy of all Warp client traffic.
- `/ai/multi-agent` hijack with conservative eligibility filter.
- Minimal local `ResponseEvent` stream for plain user-query chats.
- LiteLLM proxy with `local-primary` and `frontier-fallback` model groups,
  plus error- and context-window-fallback chains.

## Next (v0.2)

- **Read-only tool support.** Allow eligibility for requests that advertise a
  small read-only toolset (`read_files`, `grep`, `file_glob`). Translate these
  to OpenAI tool-calls and back to `ResponseEvent` actions.
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
- **Local embeddings.** Index codebase via Ollama embeddings instead of Warp's
  cloud index.
- **Configurable hijack rules.** YAML-driven matchers (regex on user text, MCP
  server presence, etc.) instead of hard-coded eligibility logic.

## Out of scope

- Re-implementing telemetry, billing, or the Warp Drive cloud sync surface.
- Distributing modified Warp binaries (AGPL would obligate publishing changes
  for any networked redistribution).
- Multi-user / team deployments. The shim is a single-user localhost tool.
