"""Eligibility filter coverage."""

from __future__ import annotations

import pytest

pytest.importorskip("harp.proto_loader")  # skip if protos aren't vendored

from harp.hijack import evaluate
from harp.proto_loader import Request, ToolType


def test_eligible_simple_user_query() -> None:
    req = Request()
    req.input.user_inputs.inputs.add().user_query.query = "what's the date command?"
    verdict = evaluate(req)
    assert verdict.eligible
    assert verdict.user_text == "what's the date command?"


def test_eligible_when_supported_tools_present_but_no_history() -> None:
    """v0.1.1: tools may be advertised; we still serve fresh user queries locally."""
    req = Request()
    req.input.user_inputs.inputs.add().user_query.query = "list files in this dir"
    # Warp's client advertises tools on every request, but with no prior task
    # history we're at the start of the conversation and a text-only reply is OK.
    req.settings.supported_tools.append(ToolType.RUN_SHELL_COMMAND)
    verdict = evaluate(req)
    assert verdict.eligible
    assert verdict.user_text == "list files in this dir"


def test_eligible_resume_conversation_uses_latest_task_user_query() -> None:
    req = Request()
    req.input.resume_conversation.SetInParent()
    first = req.task_context.tasks.add()
    first.messages.add().user_query.query = "old query"
    second = req.task_context.tasks.add()
    second.messages.add().agent_output.text = "old response"
    second.messages.add().user_query.query = "resume this query"

    verdict = evaluate(req)

    assert verdict.eligible
    assert verdict.reason == "resume_conversation"
    assert verdict.user_text == "resume this query"


def test_ineligible_resume_conversation_without_user_query_history() -> None:
    req = Request()
    req.input.resume_conversation.SetInParent()
    task = req.task_context.tasks.add()
    task.messages.add().agent_output.text = "assistant-only history"

    verdict = evaluate(req)

    assert not verdict.eligible
    assert "no user query history" in verdict.reason


def test_eligible_user_query_with_prior_task_history() -> None:
    req = Request()
    req.input.user_inputs.inputs.add().user_query.query = "continue with the edit"
    task = req.task_context.tasks.add()
    task.messages.add().user_query.query = "edit src/app.js"
    task.messages.add().agent_output.text = "I need to inspect the file."
    verdict = evaluate(req)

    assert verdict.eligible
    assert verdict.reason == "user_query_with_history"
    assert verdict.user_text == "continue with the edit"


def test_ineligible_when_no_input_type() -> None:
    req = Request()
    verdict = evaluate(req)
    assert not verdict.eligible


def test_ineligible_for_tool_call_result_input() -> None:
    req = Request()
    sub = req.input.user_inputs.inputs.add()
    sub.tool_call_result.tool_call_id = "abc"
    verdict = evaluate(req)
    assert not verdict.eligible
    assert "sub-input=tool_call_result" in verdict.reason
