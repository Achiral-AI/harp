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
2. When the client sends `POST /ai/multi-agent`, the shim:
   - reads the protobuf body
   - decodes it into a `Request` message
   - runs the eligibility filter (`hijack.evaluate`)
   - if eligible: streams a synthesized `ResponseEvent` sequence back, sourced
     from a local model via LiteLLM
   - if not eligible: forwards the original raw bytes to upstream and pipes the
     SSE stream back unchanged
3. In `local-only` mode, ineligible requests get a clean error event instead of
   a forward.

## Eligibility (v1)

Conservative on purpose. A request is local-eligible iff:

- `Request.input` is `user_inputs` containing exactly one `user_query`
- `Request.task_context.tasks` is empty (no prior tool-call history)
- `Request.settings.supported_tools` is empty (not an agentic flow)

Everything else (tool-call results, multi-turn agentic loops, ambient/cloud
runs, code-review pipelines, …) falls through to upstream.

## Local response shape

For an eligible request, the shim emits this `ResponseEvent` sequence:

1. `StreamInit { conversation_id, request_id, run_id }`
2. `ClientActions { BeginTransaction }`
3. `ClientActions { CreateTask, AddMessagesToTask{assistant_message_scaffold} }`
4. Repeated `ClientActions { AppendToMessageContent { mask: ["content"] } }` —
   one per LiteLLM streaming token-delta
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
| `hijack`     | Serve locally      | Forward upstream    |
| `local-only` | Serve locally      | Return error event  |
