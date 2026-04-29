# Architecture

## What the shim is

A localhost HTTP server that the patched Warp client talks to instead of
`https://app.warp.dev`. The shim either serves a request locally with an
on-device model, or forwards it to Warp's real backend untouched.

## Why a proxy, not a full backend

The Warp OSS repo is a *client*. All inference traffic — chat, code suggestions,
agent tool-calling, the entire multi-agent orchestration — funnels through one
endpoint:

```
POST {server_root_url}/ai/multi-agent
Content-Type: application/x-protobuf
Body: warp_multi_agent_api.v1.Request (proto wire format)

Response: text/event-stream
data: "<base64url(warp_multi_agent_api.v1.ResponseEvent)>"
```

Implementing the full server (auth, GraphQL, telemetry, conversation storage,
the entire `Request` / `ResponseEvent` matrix) is a multi-week effort. Instead,
we proxy everything to `app.warp.dev` by default and only intercept the one
inference endpoint when a local model can usefully serve the request.

## Flow

1. The patched Warp client signs in normally. Auth, GraphQL, telemetry, version
   pings — all transparent through the shim's catch-all proxy.
2. **Browser-launched URLs** (sign-up, login, upgrade, billing, account, team,
   referral) are detected before the proxy step and 302'd to the same path on
   `app.warp.dev`. The Warp client constructs these from `WARP_SERVER_ROOT_URL`
   and shells out via `ctx.open_url(...)`; without the redirect they'd land
   on the proxy with no HTML to render. See `src/harp/auth_redirect.py`.
3. When the client sends `POST /ai/multi-agent`, the shim:
   - reads the protobuf body
   - decodes it into a `Request` message
   - runs the eligibility filter (`hijack.evaluate`)
   - if eligible: streams a synthesized `ResponseEvent` sequence back, sourced
     from a local model via LiteLLM
   - if unsupported in `hijack` or `local-only`: emits a valid local SSE error
     stream
   - if running in pure `proxy` mode: forwards the original raw bytes to
     upstream and pipes the SSE stream back unchanged

## Eligibility (v1)

Conservative on purpose, but multi-turn text follow-ups are supported. A
request is local-eligible iff:

- `Request.input` is `user_inputs` containing exactly one `user_query`
- `Request.input` is `resume_conversation` and prior task history contains a
  user query to resume

Warp advertises supported tools on normal user-query requests and includes
prior `task_context.tasks` on follow-up turns. Harp does not reject those by
itself anymore; it injects recent text history into the local model so phrases
such as "as asked before" can resolve. Non-text flows such as tool-call
results, ambient/cloud runs, code-review pipelines, and passive suggestions
remain unsupported locally.

In `hijack` mode, unsupported `/ai/multi-agent` requests return a valid local
SSE stream ending in `StreamFinished{InternalError}` instead of being forwarded
to Warp upstream. This avoids leaking upstream 403 HTML responses into the
patched OSS client.

## HarpCache

Before calling LiteLLM, eligible local requests can receive a HarpCache system
message. HarpCache builds a bounded, read-only snapshot from Warp's request
context: current working directory, codebase roots, git branch/head, and active
project rules.

The snapshot includes a bounded manifest, important config/docs files, active
project rules, and a few path-relevant snippets. It respects root-level
`.gitignore`, `.warpignore`, `.warpindexingignore`, `.cursorignore`,
`.cursorindexingignore`, and `.codeiumignore` files, de-duplicates manifest
entries, and stops directory walking after `HARP_CACHE_WALK_TIME_BUDGET_S`.
See `docs/harpcache.md` for details.

## Local response shape

For an eligible request, the shim emits this `ResponseEvent` sequence:

1. `StreamInit { conversation_id, request_id }`
2. `ClientActions { BeginTransaction }`
3. `ClientActions { CreateTask, AddMessagesToTask{assistant_message_scaffold} }`
4. Repeated `ClientActions { AppendToMessageContent { mask: ["agent_output.text"] } }` — one per LiteLLM streaming token-delta
5. `ClientActions { CommitTransaction }`
6. `StreamFinished { Done }`

This is the minimum that lights up Warp's chat UI. Tool calling, planning, and
the rest of the agentic surface are deliberately out of scope for v1.

## Why LiteLLM in the middle

- One config file to switch between Ollama, vLLM, LM Studio, and frontier APIs.
- Built-in fallback chains: `local-primary` → `frontier-fallback` on errors or
  context-window overflow.
- Drop-unsupported-params handling for local models that don't accept the same
  knob set as OpenAI.
- A clean separation: the shim worries about Warp's protocol; LiteLLM worries
  about model providers.

## Modes

| Mode         | Eligible request   | Ineligible request  |
| ------------ | ------------------ | ------------------- |
| `proxy`      | Forward upstream   | Forward upstream    |
| `hijack`     | Serve locally      | Return error event  |
| `local-only` | Serve locally      | Return error event  |
