from __future__ import annotations

import hashlib
import hmac as hmac_mod

from jupyqt.kernel.messages import (
    DELIM,
    create_message,
    deserialize_message,
    feed_identities,
    serialize_message,
)


def test_feed_identities_splits_on_delimiter():
    idents = [b"id1", b"id2"]
    parts = [b"hmac", b"header", b"parent", b"meta", b"content"]
    raw = [*idents, DELIM, *parts]
    got_idents, got_parts = feed_identities(raw)
    assert got_idents == idents
    assert got_parts == parts


def test_feed_identities_no_idents():
    parts = [b"hmac", b"header"]
    raw = [DELIM, *parts]
    got_idents, got_parts = feed_identities(raw)
    assert got_idents == []
    assert got_parts == parts


def test_serialize_deserialize_round_trip():
    msg = create_message("kernel_info_request")
    key = "test-key"
    serialized = serialize_message(msg, key)
    assert isinstance(serialized, list)
    assert all(isinstance(b, bytes) for b in serialized)
    assert serialized[0] == DELIM
    _, parts = feed_identities(serialized)
    restored = deserialize_message(parts)
    assert restored["header"]["msg_type"] == "kernel_info_request"
    assert restored["parent_header"] == {}
    assert restored["metadata"] == {}


def test_hmac_signature_is_valid():
    msg = create_message("execute_request", content={"code": "1+1"})
    key = "my-secret"
    serialized = serialize_message(msg, key)
    _, parts = feed_identities(serialized)
    h = hmac_mod.new(key.encode("ascii"), digestmod=hashlib.sha256)
    for p in parts[1:5]:
        h.update(p)
    assert parts[0] == h.hexdigest().encode()


def test_create_message_with_parent():
    parent = create_message("execute_request")
    reply = create_message("execute_reply", parent=parent, content={"status": "ok"})
    assert reply["parent_header"] == parent["header"]
    assert reply["content"] == {"status": "ok"}


def test_buffers_preserved():
    msg = create_message("display_data", buffers=[b"binary1", b"binary2"])
    serialized = serialize_message(msg, "0")
    _, parts = feed_identities(serialized)
    restored = deserialize_message(parts)
    assert len(restored["buffers"]) == 2
