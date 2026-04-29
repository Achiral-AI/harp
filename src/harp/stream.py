"""Encode ``ResponseEvent`` messages as base64-protobuf SSE frames.

The Warp client decodes each SSE ``data:`` line by stripping outer quotes and
``base64url``-decoding to a protobuf wire-format ``ResponseEvent``. See
``app/src/server/server_api.rs:1130-1154`` in the Warp OSS source.
"""

from __future__ import annotations

import base64
import json
from typing import AsyncIterator

from .proto_loader import ResponseEvent


def encode_event(event: ResponseEvent) -> bytes:
    """Encode one ResponseEvent into a single SSE frame, terminator included."""

    wire = event.SerializeToString()
    encoded = base64.urlsafe_b64encode(wire).decode("ascii").rstrip("=")
    # The client decodes ``message_event.data.trim_matches('"')``, so wrapping in
    # JSON-style quotes is harmless and matches Warp's own output.
    payload = json.dumps(encoded)
    return f"data: {payload}\n\n".encode("utf-8")


async def to_sse_stream(events: AsyncIterator[ResponseEvent]) -> AsyncIterator[bytes]:
    """Pipe a stream of ResponseEvents into an SSE byte stream."""

    async for event in events:
        yield encode_event(event)
