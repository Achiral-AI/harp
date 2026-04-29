"""Hijack streaming response coverage."""

from __future__ import annotations

import base64
import json
from collections.abc import AsyncIterator

import pytest

pytest.importorskip("harp.proto_loader")  # skip if protos aren't vendored

from harp.harpcache import HarpCacheContext
from harp.hijack import Eligibility, HijackHandler, _local_only_error
from harp.proto_loader import Request, ResponseEvent
from harp.settings import Settings
from harp.stats import StatsRegistry


class _StubLLM:
    def __init__(self, chunks: list[str], *, fail: bool = False) -> None:
        self._chunks = chunks
        self._fail = fail
        self.messages: list[dict[str, str]] | None = None

    async def stream_chat(self, messages: list[dict[str, str]]) -> AsyncIterator[str]:
        self.messages = messages
        if self._fail:
            raise RuntimeError("boom")
        for chunk in self._chunks:
            yield chunk


class _StubHarpCache:
    def build_context(self, req: Request, user_text: str) -> HarpCacheContext:
        return HarpCacheContext(
            text="<HarpCache>\nProject context for testing\n</HarpCache>",
            repo_root="/repo",
            cache_hit=False,
        )


def _decode_sse_frame(frame: bytes) -> ResponseEvent:
    text = frame.decode("utf-8").strip()
    assert text.startswith("data: ")
    encoded = json.loads(text.removeprefix("data: "))
    assert len(encoded) % 4 == 0
    event = ResponseEvent()
    event.ParseFromString(base64.urlsafe_b64decode(encoded))
    return event


async def _collect_events(response) -> list[ResponseEvent]:
    return [_decode_sse_frame(frame) async for frame in response.body_iterator]


@pytest.mark.asyncio
async def test_local_stream_emits_supported_stream_init_fields() -> None:
    stats = StatsRegistry()
    handler = HijackHandler(Settings(), object(), _StubLLM(["hello"]), stats)  # type: ignore[arg-type]

    events = await _collect_events(handler._serve_local(Eligibility(True, "ok", "hi")))

    assert events[0].HasField("init")
    assert events[0].init.conversation_id
    assert events[0].init.request_id
    assert [field.name for field in events[0].init.DESCRIPTOR.fields] == [
        "conversation_id",
        "request_id",
    ]
    assert events[-1].HasField("finished")
    assert events[-1].finished.HasField("done")


@pytest.mark.asyncio
async def test_local_stream_model_failure_records_error_and_finishes_cleanly() -> None:
    stats = StatsRegistry()
    handler = HijackHandler(Settings(), object(), _StubLLM([], fail=True), stats)  # type: ignore[arg-type]

    events = await _collect_events(handler._serve_local(Eligibility(True, "ok", "hi")))

    assert events[-1].HasField("finished")
    assert events[-1].finished.HasField("internal_error")
    assert stats.snapshot().errors == 1


@pytest.mark.asyncio
async def test_local_stream_injects_harpcache_context() -> None:
    stats = StatsRegistry()
    llm = _StubLLM(["hello"])
    handler = HijackHandler(
        Settings(),
        object(),  # type: ignore[arg-type]
        llm,
        stats,
        _StubHarpCache(),  # type: ignore[arg-type]
    )

    events = await _collect_events(handler._serve_local(Eligibility(True, "ok", "hi"), Request()))

    assert events[-1].HasField("finished")
    assert events[-1].finished.HasField("done")
    assert llm.messages is not None
    assert any("Project context for testing" in message["content"] for message in llm.messages)


@pytest.mark.asyncio
async def test_local_stream_injects_prior_text_history() -> None:
    stats = StatsRegistry()
    llm = _StubLLM(["hello"])
    handler = HijackHandler(Settings(), object(), llm, stats)  # type: ignore[arg-type]
    req = Request()
    task = req.task_context.tasks.add()
    task.messages.add().user_query.query = "lower the number of chat bubbles"
    task.messages.add().agent_output.text = "Please show me the file."

    events = await _collect_events(
        handler._serve_local(
            Eligibility(True, "user_query_with_history", "cleanup as asked before"),
            req,
        )
    )

    assert events[-1].HasField("finished")
    assert events[-1].finished.HasField("done")
    assert llm.messages is not None
    assert llm.messages[-3]["content"] == "lower the number of chat bubbles"
    assert llm.messages[-2]["content"] == "Please show me the file."
    assert llm.messages[-1]["content"] == "cleanup as asked before"


@pytest.mark.asyncio
async def test_local_only_error_emits_supported_stream_init_fields() -> None:
    events = await _collect_events(_local_only_error("not eligible"))

    assert events[0].HasField("init")
    assert events[0].init.conversation_id
    assert events[0].init.request_id
    assert [field.name for field in events[0].init.DESCRIPTOR.fields] == [
        "conversation_id",
        "request_id",
    ]
    assert events[-1].HasField("finished")
    assert events[-1].finished.HasField("internal_error")
