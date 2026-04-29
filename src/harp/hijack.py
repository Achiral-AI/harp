"""Multi-agent endpoint hijack.

Receives the protobuf-encoded ``warp_multi_agent_api.v1.Request`` body. Decides
whether the request can be served locally; if so, builds a streaming response
out of ``ResponseEvent`` messages. Otherwise, forwards the original bytes to
upstream and proxies the SSE stream back unchanged.
"""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass
from typing import AsyncIterator

from openai.types.chat import ChatCompletionMessageParam
from starlette.requests import Request as StarletteRequest
from starlette.responses import Response, StreamingResponse
from .harpcache import HarpCache

from .litellm_client import LiteLLMClient
from .proto_loader import (
    AgentOutput,
    ClientAction,
    Message,
    Request,
    ResponseEvent,
    Task,
)
from .proxy import UpstreamProxy
from .settings import Settings, ShimMode
from .stats import StatsRegistry
from .stream import encode_event

logger = logging.getLogger(__name__)

_MAX_HISTORY_MESSAGES = 12
_MAX_HISTORY_CHARS = 8_000


@dataclass(slots=True)
class Eligibility:
    """Outcome of the eligibility check."""

    eligible: bool
    reason: str
    user_text: str = ""


def evaluate(req: Request) -> Eligibility:
    """v1 eligibility filter. Conservative on purpose.
    Serve locally when the request is a user query. Warp includes prior task
    history on follow-up turns; Harp can pass recent text history through to
    the local model even though full client-tool execution is still a later
    milestone.
    """

    input_obj = req.input
    if not input_obj.WhichOneof("type"):
        return Eligibility(False, "no input.type set")

    kind = input_obj.WhichOneof("type")
    if kind == "resume_conversation":
        user_text = _latest_user_query(req)
        if not user_text:
            return Eligibility(False, "resume_conversation has no user query history")
        return Eligibility(True, "resume_conversation", user_text=user_text)
    if kind != "user_inputs":
        return Eligibility(False, f"input.type={kind} not yet handled locally")

    user_inputs = input_obj.user_inputs.inputs
    if len(user_inputs) != 1:
        return Eligibility(False, f"expected 1 user input, got {len(user_inputs)}")

    item = user_inputs[0]
    sub_kind = item.WhichOneof("input")
    if sub_kind != "user_query":
        return Eligibility(False, f"sub-input={sub_kind} not yet handled locally")

    # NOTE: as of v0.1.1 we deliberately do *not* reject requests that advertise
    # `supported_tools`. Warp's client lists its toolset on every fresh
    # user_query, but with no prior task history we're at the start of the
    # conversation and a text-only reply from the local model is acceptable.
    # Read-only tool support (read_files, grep, file_glob) is the v0.2 milestone.

    if req.task_context.tasks:
        return Eligibility(True, "user_query_with_history", user_text=item.user_query.query)
    return Eligibility(True, "ok", user_text=item.user_query.query)


def _latest_user_query(req: Request) -> str:
    """Return the most recent user query from task history, if present."""

    for task in reversed(req.task_context.tasks):
        for message in reversed(task.messages):
            if message.WhichOneof("message") == "user_query" and message.user_query.query:
                return message.user_query.query
    return ""


class HijackHandler:
    """Dispatches `/ai/multi-agent` requests."""

    def __init__(
        self,
        settings: Settings,
        proxy: UpstreamProxy,
        llm: LiteLLMClient,
        stats: StatsRegistry,
        harpcache: HarpCache | None = None,
    ) -> None:
        self._settings = settings
        self._proxy = proxy
        self._llm = llm
        self._stats = stats
        self._harpcache = harpcache

    async def handle(self, request: StarletteRequest) -> Response:
        body = await request.body()

        if self._settings.mode == ShimMode.PROXY:
            self._stats.record_forwarded_upstream(reason="mode=proxy")
            return await self._proxy.forward(request, body=body)

        if len(body) > self._settings.max_local_request_bytes:
            logger.info(
                "Forwarding upstream: body too large for local handling (%d > %d)",
                len(body),
                self._settings.max_local_request_bytes,
            )
            self._stats.record_forwarded_upstream(reason="body too large")
            return await self._proxy.forward(request, body=body)

        try:
            decoded = Request()
            decoded.ParseFromString(body)
        except Exception:
            logger.exception("Failed to decode multi-agent Request; forwarding upstream")
            self._stats.record_forwarded_upstream(reason="proto decode failed")
            return await self._proxy.forward(request, body=body)

        verdict = evaluate(decoded)
        logger.info(
            "multi-agent eligibility: eligible=%s reason=%r mode=%s",
            verdict.eligible,
            verdict.reason,
            self._settings.mode,
        )

        if not verdict.eligible:
            if self._settings.mode == ShimMode.LOCAL_ONLY:
                self._stats.record_rejected_local_only(reason=verdict.reason)
                return _local_only_error(verdict.reason)
            if self._settings.mode == ShimMode.HIJACK:
                self._stats.record_local_error(reason=verdict.reason)
                return _local_error(f"local request unsupported: {verdict.reason}")
            self._stats.record_ineligibility(reason=verdict.reason)
            self._stats.record_forwarded_upstream(reason=verdict.reason)
            return await self._proxy.forward(request, body=body)

        self._stats.record_served_local()
        return self._serve_local(verdict, decoded)

    # ------------------------------------------------------------------ local

    def _serve_local(self, verdict: Eligibility, req: Request | None = None) -> Response:
        async def _events() -> AsyncIterator[bytes]:
            conversation_id = str(uuid.uuid4())
            request_id = str(uuid.uuid4())
            task_id = str(uuid.uuid4())
            message_id = str(uuid.uuid4())

            # 1. StreamInit
            yield encode_event(
                ResponseEvent(
                    init=ResponseEvent.StreamInit(
                        conversation_id=conversation_id,
                        request_id=request_id,
                    )
                )
            )

            # 2. BeginTransaction
            yield encode_event(
                ResponseEvent(
                    client_actions=ResponseEvent.ClientActions(
                        actions=[ClientAction(begin_transaction=ClientAction.BeginTransaction())]
                    )
                )
            )

            # 3. CreateTask scaffold + assistant message scaffold.
            #    NOTE: this is a v1 minimum scaffold. The Task / Message proto has many
            #    fields we leave empty here; flesh out as we observe how the client
            #    renders these events. The assistant turn is an `agent_output` Message
            #    whose `text` field is appended to as the local model streams.
            task = Task(id=task_id)
            assistant = Message(id=message_id, agent_output=AgentOutput(text=""))
            yield encode_event(
                ResponseEvent(
                    client_actions=ResponseEvent.ClientActions(
                        actions=[
                            ClientAction(create_task=ClientAction.CreateTask(task=task)),
                            ClientAction(
                                add_messages_to_task=ClientAction.AddMessagesToTask(
                                    task_id=task_id, messages=[assistant]
                                )
                            ),
                        ]
                    )
                )
            )

            # 4. Stream the local model's text deltas as AppendToMessageContent.
            messages: list[ChatCompletionMessageParam] = [
                {
                    "role": "system",
                    "content": (
                        "You are a helpful assistant embedded inside the Warp terminal. "
                        "Answer concisely. If the user asks for a shell command, prefer "
                        "POSIX-compatible syntax."
                    ),
                }
            ]
            harpcache_context = self._harpcache_context(req, verdict.user_text)
            if harpcache_context:
                messages.append({"role": "system", "content": harpcache_context})
            messages.extend(_conversation_history_messages(req, verdict.user_text))
            messages.append({"role": "user", "content": verdict.user_text})

            stripper = ThinkingStripper()
            try:
                async for delta in self._llm.stream_chat(messages):
                    visible = stripper.feed(delta)
                    if visible:
                        yield encode_event(_append_message_content(task_id, message_id, visible))
                tail = stripper.flush()
                if tail:
                    yield encode_event(_append_message_content(task_id, message_id, tail))
            except Exception as exc:  # pragma: no cover - surfaced as a finished/error event
                self._stats.record_error()
                logger.exception("Local stream failed; emitting StreamFinished{InternalError}")
                yield encode_event(
                    ResponseEvent(
                        finished=ResponseEvent.StreamFinished(
                            internal_error=ResponseEvent.StreamFinished.InternalError(
                                message=f"local model error: {type(exc).__name__}"
                            )
                        )
                    )
                )
                return

            # 5. CommitTransaction
            yield encode_event(
                ResponseEvent(
                    client_actions=ResponseEvent.ClientActions(
                        actions=[ClientAction(commit_transaction=ClientAction.CommitTransaction())]
                    )
                )
            )

            # 6. StreamFinished{Done}
            yield encode_event(
                ResponseEvent(
                    finished=ResponseEvent.StreamFinished(done=ResponseEvent.StreamFinished.Done())
                )
            )

        return StreamingResponse(_events(), media_type="text/event-stream")

    def _harpcache_context(self, req: Request | None, user_text: str) -> str:
        if self._harpcache is None or req is None:
            return ""
        try:
            context = self._harpcache.build_context(req, user_text)
        except Exception:  # pragma: no cover - cache failures should never break chat
            logger.exception("HarpCache failed; continuing without project context")
            return ""
        if context is None:
            return ""
        logger.info(
            "HarpCache context attached: repo=%s cache_hit=%s",
            context.repo_root,
            context.cache_hit,
        )
        return context.text


def _conversation_history_messages(
    req: Request | None,
    current_user_text: str,
) -> list[ChatCompletionMessageParam]:
    if req is None:
        return []

    history: list[ChatCompletionMessageParam] = []
    for task in req.task_context.tasks:
        for message in task.messages:
            kind = message.WhichOneof("message")
            if kind == "user_query" and message.user_query.query:
                history.append({"role": "user", "content": message.user_query.query})
            elif kind == "agent_output" and message.agent_output.text:
                history.append({"role": "assistant", "content": message.agent_output.text})
            elif kind == "summarization":
                summary = _summarization_text(message)
                if summary:
                    history.append(
                        {"role": "assistant", "content": f"Conversation summary: {summary}"}
                    )

    if (
        history
        and history[-1].get("role") == "user"
        and history[-1].get("content") == current_user_text
    ):
        history.pop()

    return _trim_history(history)


def _summarization_text(message: Message) -> str:
    if message.summarization.WhichOneof("summary_type") != "conversation_summary":
        return ""
    return message.summarization.conversation_summary.summary


def _trim_history(
    history: list[ChatCompletionMessageParam],
) -> list[ChatCompletionMessageParam]:
    trimmed: list[ChatCompletionMessageParam] = []
    remaining = _MAX_HISTORY_CHARS
    for message in reversed(history[-_MAX_HISTORY_MESSAGES:]):
        content = str(message.get("content", ""))
        if not content:
            continue
        if len(content) > remaining:
            content = content[:remaining]
        if not content:
            break
        trimmed.append({"role": message["role"], "content": content})
        remaining -= len(content)
        if remaining <= 0:
            break
    return list(reversed(trimmed))


def _append_message_content(task_id: str, message_id: str, content_delta: str) -> ResponseEvent:
    """Build an AppendToMessageContent event for a streamed text delta.

    The ``mask`` field names the string field on the Message that the client
    should append to. For a normal assistant turn that is
    ``agent_output.text``.
    """

    from google.protobuf import field_mask_pb2

    msg = Message(id=message_id, agent_output=AgentOutput(text=content_delta))
    mask = field_mask_pb2.FieldMask(paths=["agent_output.text"])
    return ResponseEvent(
        client_actions=ResponseEvent.ClientActions(
            actions=[
                ClientAction(
                    append_to_message_content=ClientAction.AppendToMessageContent(
                        task_id=task_id, message=msg, mask=mask
                    )
                )
            ]
        )
    )


class ThinkingStripper:
    """Strip ``<think>...</think>`` blocks from a streaming token stream.

    Qwen3 (and similar reasoning models) interleave a ``<think>...</think>``
    block before the user-visible answer. We disable thinking at request build
    time via the ``chat_template_kwargs`` extra body, but some servers still
    leak partial reasoning tokens. This filter buffers across chunks so a tag
    split mid-stream (e.g. ``<thi`` then ``nk>``) is still detected.
    """

    _OPEN = "<think>"
    _CLOSE = "</think>"

    def __init__(self) -> None:
        self._mode: str = "outside"  # or "inside"
        self._buf: str = ""

    def feed(self, chunk: str) -> str:
        """Append ``chunk`` and return the content safe to emit so far."""

        self._buf += chunk
        out: list[str] = []
        while True:
            if self._mode == "outside":
                idx = self._buf.find(self._OPEN)
                if idx != -1:
                    out.append(self._buf[:idx])
                    self._buf = self._buf[idx + len(self._OPEN) :]
                    self._mode = "inside"
                    continue
                # No full open tag. Hold back any trailing prefix that could be
                # the *start* of a future ``<think>`` so we don't emit ``<th``
                # only to retract it next chunk.
                hold = self._max_partial_open()
                if hold:
                    out.append(self._buf[: -len(hold)])
                    self._buf = hold
                else:
                    out.append(self._buf)
                    self._buf = ""
                break
            # inside
            idx = self._buf.find(self._CLOSE)
            if idx != -1:
                # Drop the reasoning block entirely.
                self._buf = self._buf[idx + len(self._CLOSE) :]
                self._mode = "outside"
                continue
            # Hold back any trailing prefix that could be the start of
            # ``</think>`` so we don't accidentally exit early.
            hold = self._max_partial_close()
            self._buf = hold
            break
        return "".join(out)

    def flush(self) -> str:
        """Final flush after the stream ends."""

        if self._mode == "outside":
            out, self._buf = self._buf, ""
            return out
        # Stream ended mid-thinking; drop the rest.
        self._buf = ""
        return ""

    def _max_partial_open(self) -> str:
        return self._max_partial_suffix(self._OPEN)

    def _max_partial_close(self) -> str:
        return self._max_partial_suffix(self._CLOSE)

    def _max_partial_suffix(self, tag: str) -> str:
        """Return the longest suffix of ``self._buf`` that is also a prefix of ``tag``."""

        max_len = min(len(self._buf), len(tag) - 1)
        for n in range(max_len, 0, -1):
            if tag.startswith(self._buf[-n:]):
                return self._buf[-n:]
        return ""


def _local_only_error(reason: str) -> Response:
    """LOCAL_ONLY mode: refuse to forward and emit a clear finished/error event."""

    return _local_error(f"local-only mode rejected request: {reason}")


def _local_error(message: str) -> Response:
    """Emit a valid local SSE stream that finishes with an internal error."""

    async def _events() -> AsyncIterator[bytes]:
        yield encode_event(
            ResponseEvent(
                init=ResponseEvent.StreamInit(
                    conversation_id=str(uuid.uuid4()),
                    request_id=str(uuid.uuid4()),
                )
            )
        )
        yield encode_event(
            ResponseEvent(
                finished=ResponseEvent.StreamFinished(
                    internal_error=ResponseEvent.StreamFinished.InternalError(message=message)
                )
            )
        )

    return StreamingResponse(_events(), media_type="text/event-stream")
