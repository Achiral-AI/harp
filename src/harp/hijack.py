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
from .stream import encode_event

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class Eligibility:
    """Outcome of the eligibility check."""

    eligible: bool
    reason: str
    user_text: str = ""


def evaluate(req: Request) -> Eligibility:
    """v1 eligibility filter. Conservative on purpose.

    Serve locally only when the request is a fresh, single-turn user query
    with no tools to be invoked and no prior tool-call history. Anything more
    complex is forwarded upstream.
    """

    input_obj = req.input
    if not input_obj.WhichOneof("type"):
        return Eligibility(False, "no input.type set")

    kind = input_obj.WhichOneof("type")
    if kind != "user_inputs":
        return Eligibility(False, f"input.type={kind} not yet handled locally")

    user_inputs = input_obj.user_inputs.inputs
    if len(user_inputs) != 1:
        return Eligibility(False, f"expected 1 user input, got {len(user_inputs)}")

    item = user_inputs[0]
    sub_kind = item.WhichOneof("input")
    if sub_kind != "user_query":
        return Eligibility(False, f"sub-input={sub_kind} not yet handled locally")

    if req.task_context.tasks:
        # Existing tasks imply prior tool-call state we don't yet replay locally.
        return Eligibility(False, "request has prior task history")

    settings = req.settings
    if settings.supported_tools:
        # Local handling for tool-calling agents lands in v2.
        return Eligibility(False, "request advertises supported_tools (agentic flow)")

    return Eligibility(True, "ok", user_text=item.user_query.query)


class HijackHandler:
    """Dispatches `/ai/multi-agent` requests."""

    def __init__(
        self,
        settings: Settings,
        proxy: UpstreamProxy,
        llm: LiteLLMClient,
    ) -> None:
        self._settings = settings
        self._proxy = proxy
        self._llm = llm

    async def handle(self, request: StarletteRequest) -> Response:
        body = await request.body()

        if self._settings.mode == ShimMode.PROXY:
            return await self._proxy.forward(request, body=body)

        if len(body) > self._settings.max_local_request_bytes:
            logger.info(
                "Forwarding upstream: body too large for local handling (%d > %d)",
                len(body),
                self._settings.max_local_request_bytes,
            )
            return await self._proxy.forward(request, body=body)

        try:
            decoded = Request()
            decoded.ParseFromString(body)
        except Exception:
            logger.exception("Failed to decode multi-agent Request; forwarding upstream")
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
                return _local_only_error(verdict.reason)
            return await self._proxy.forward(request, body=body)

        return self._serve_local(verdict)

    # ------------------------------------------------------------------ local

    def _serve_local(self, verdict: Eligibility) -> Response:
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
                        run_id=conversation_id,
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
                },
                {"role": "user", "content": verdict.user_text},
            ]

            try:
                async for delta in self._llm.stream_chat(messages):
                    yield encode_event(_append_message_content(task_id, message_id, delta))
            except Exception as exc:  # pragma: no cover - surfaced as a finished/error event
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
                    finished=ResponseEvent.StreamFinished(
                        done=ResponseEvent.StreamFinished.Done()
                    )
                )
            )

        return StreamingResponse(_events(), media_type="text/event-stream")


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


def _local_only_error(reason: str) -> Response:
    """LOCAL_ONLY mode: refuse to forward and emit a clear finished/error event."""

    async def _events() -> AsyncIterator[bytes]:
        yield encode_event(
            ResponseEvent(
                init=ResponseEvent.StreamInit(
                    conversation_id=str(uuid.uuid4()),
                    request_id=str(uuid.uuid4()),
                    run_id=str(uuid.uuid4()),
                )
            )
        )
        yield encode_event(
            ResponseEvent(
                finished=ResponseEvent.StreamFinished(
                    internal_error=ResponseEvent.StreamFinished.InternalError(
                        message=f"local-only mode rejected request: {reason}"
                    )
                )
            )
        )

    return StreamingResponse(_events(), media_type="text/event-stream")
