"""Eligibility filter coverage."""

from __future__ import annotations

import pytest

pytest.importorskip("harp.proto_loader")  # skip if protos aren't vendored

from harp.hijack import evaluate
from harp.proto_loader import Request, ToolType, task_pb2


def test_eligible_simple_user_query() -> None:
    req = Request()
    req.input.user_inputs.inputs.add().user_query.query = "what's the date command?"
    verdict = evaluate(req)
    assert verdict.eligible
    assert verdict.user_text == "what's the date command?"


def test_ineligible_when_supported_tools_present() -> None:
    req = Request()
    req.input.user_inputs.inputs.add().user_query.query = "list files in this dir"
    # Any tool advertised flips it agentic.
    req.settings.supported_tools.append(ToolType.RUN_SHELL_COMMAND)
    verdict = evaluate(req)
    assert not verdict.eligible
    assert "supported_tools" in verdict.reason


def test_ineligible_with_prior_task_history() -> None:
    req = Request()
    req.input.user_inputs.inputs.add().user_query.query = "continue"
    req.task_context.tasks.append(task_pb2.Task(id="prior-task"))
    verdict = evaluate(req)
    assert not verdict.eligible
    assert "task history" in verdict.reason


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
