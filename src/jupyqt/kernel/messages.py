"""Jupyter wire protocol message serialization.

Messages are list[bytes]: [DELIM, HMAC, header, parent_header, metadata, content, *buffers].
"""

from __future__ import annotations

import hashlib
import hmac
import json
import uuid
from typing import Any

DELIM = b"<IDS|MSG>"
PROTOCOL_VERSION = "5.4"


def _pack(obj: Any) -> bytes:
    return json.dumps(obj, default=str).encode("utf-8")


def _unpack(data: bytes) -> Any:
    return json.loads(data)


def feed_identities(msg_list: list[bytes]) -> tuple[list[bytes], list[bytes]]:
    idx = msg_list.index(DELIM)
    return msg_list[:idx], msg_list[idx + 1:]


def sign(parts: list[bytes], key: str) -> bytes:
    h = hmac.new(key.encode("ascii"), digestmod=hashlib.sha256)
    for p in parts:
        h.update(p)
    return h.hexdigest().encode()


def serialize_message(msg: dict[str, Any], key: str) -> list[bytes]:
    parts = [
        _pack(msg["header"]),
        _pack(msg.get("parent_header", {})),
        _pack(msg.get("metadata", {})),
        _pack(msg.get("content", {})),
    ]
    return [DELIM, sign(parts, key)] + parts + msg.get("buffers", [])


def deserialize_message(parts: list[bytes]) -> dict[str, Any]:
    header = _unpack(parts[1])
    return {
        "header": header,
        "msg_id": header["msg_id"],
        "msg_type": header["msg_type"],
        "parent_header": _unpack(parts[2]),
        "metadata": _unpack(parts[3]),
        "content": _unpack(parts[4]),
        "buffers": list(parts[5:]),
    }


def create_message(
    msg_type: str,
    content: dict[str, Any] | None = None,
    parent: dict[str, Any] | None = None,
    metadata: dict[str, Any] | None = None,
    buffers: list[bytes] | None = None,
) -> dict[str, Any]:
    return {
        "header": {
            "msg_id": uuid.uuid4().hex,
            "msg_type": msg_type,
            "username": "jupyqt",
            "session": uuid.uuid4().hex,
            "version": PROTOCOL_VERSION,
        },
        "parent_header": parent["header"] if parent else {},
        "metadata": metadata or {},
        "content": content or {},
        "buffers": buffers or [],
    }
