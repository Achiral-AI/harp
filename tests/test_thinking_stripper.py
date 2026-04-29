"""Coverage for the streaming ``<think>`` block stripper."""

from __future__ import annotations

import pytest

pytest.importorskip("harp.proto_loader")

from harp.hijack import ThinkingStripper


def _drain(chunks: list[str]) -> str:
    s = ThinkingStripper()
    out = []
    for c in chunks:
        out.append(s.feed(c))
    out.append(s.flush())
    return "".join(out)


def test_passes_through_when_no_think_block() -> None:
    assert _drain(["hello ", "world"]) == "hello world"


def test_strips_self_contained_think_block() -> None:
    assert _drain(["before ", "<think>reasoning here</think>", " after"]) == "before  after"


def test_strips_block_split_across_chunks() -> None:
    chunks = ["pre", "<thi", "nk>secret thoughts</thi", "nk>tail"]
    assert _drain(chunks) == "pretail"


def test_strips_block_with_internal_split() -> None:
    chunks = ["<think>", "step 1", " step 2", "</think>", "answer"]
    assert _drain(chunks) == "answer"


def test_drops_unterminated_think_at_end_of_stream() -> None:
    chunks = ["visible ", "<think>oops cut off"]
    assert _drain(chunks) == "visible "


def test_emits_partial_safely_holding_back_potential_open_tag() -> None:
    """If the stream ends with characters that could be a partial ``<th``, hold them."""
    s = ThinkingStripper()
    # First chunk ends with potential prefix of ``<think>``.
    assert s.feed("hello <") == "hello "
    # Once we know it's not a tag, it gets emitted with the next chunk.
    assert s.feed("3") == "<3"
    assert s.flush() == ""


def test_multiple_think_blocks() -> None:
    chunks = ["a", "<think>x</think>", "b", "<think>y</think>", "c"]
    assert _drain(chunks) == "abc"
