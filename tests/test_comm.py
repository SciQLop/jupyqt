"""Tests for comm protocol support."""

from __future__ import annotations

import anyio
import pytest

from jupyqt.kernel.comm import Comm, CommManager, get_comm_manager, set_current_parent
from jupyqt.kernel.messages import (
    create_message,
    deserialize_message,
    feed_identities,
    serialize_message,
)
from jupyqt.kernel.protocol import KernelProtocol


@pytest.fixture
def protocol(shell):
    return KernelProtocol(shell, key="0")


def _make_raw(msg: dict, key: str = "0") -> list[bytes]:
    return serialize_message(msg, key)


async def _collect_iopub(protocol: KernelProtocol) -> list[dict]:
    collected = []
    while True:
        try:
            raw = protocol.iopub_receive.receive_nowait()
            _, parts = feed_identities(raw)
            collected.append(deserialize_message(parts))
        except anyio.WouldBlock:
            break
    return collected


def test_comm_manager_register_and_info():
    mgr = CommManager()
    comm = Comm(target_name="test.target", comm_id="abc123")
    mgr.register_comm(comm)
    info = mgr.comm_info()
    assert "abc123" in info
    assert info["abc123"]["target_name"] == "test.target"

    info_filtered = mgr.comm_info(target_name="other")
    assert "abc123" not in info_filtered

    mgr.unregister_comm("abc123")
    assert mgr.comm_info() == {}


def test_comm_manager_handle_comm_open():
    mgr = CommManager()
    received = []

    def handler(comm, msg):
        received.append((comm, msg))

    mgr.register_target("test.target", handler)

    msg = {
        "content": {
            "comm_id": "xyz",
            "target_name": "test.target",
            "data": {"key": "value"},
        },
    }
    mgr.handle_comm_open(msg)
    assert len(received) == 1
    assert received[0][0].comm_id == "xyz"
    assert mgr.get_comm("xyz") is not None


def test_comm_manager_handle_comm_msg():
    mgr = CommManager()
    comm = Comm(target_name="test", comm_id="c1")
    mgr.register_comm(comm)

    received_msgs = []
    comm.on_msg(received_msgs.append)

    mgr.handle_comm_msg({"content": {"comm_id": "c1", "data": {"val": 42}}})
    assert len(received_msgs) == 1
    assert received_msgs[0]["content"]["data"]["val"] == 42


def test_comm_manager_handle_comm_close():
    mgr = CommManager()
    comm = Comm(target_name="test", comm_id="c2")
    mgr.register_comm(comm)

    closed = []
    comm.on_close(closed.append)

    mgr.handle_comm_close({"content": {"comm_id": "c2", "data": {}}})
    assert len(closed) == 1
    assert mgr.get_comm("c2") is None


def test_comm_publish(protocol):
    """Comm.open() publishes a comm_open message on iopub."""
    async def main():
        parent = create_message("execute_request", content={"code": ""})
        set_current_parent(parent)

        comm = Comm(target_name="test.widget", comm_id="pub1")
        comm.open(data={"state": "initial"})

        iopub = await _collect_iopub(protocol)
        comm_opens = [m for m in iopub if m["msg_type"] == "comm_open"]
        assert len(comm_opens) == 1
        assert comm_opens[0]["content"]["comm_id"] == "pub1"
        assert comm_opens[0]["content"]["target_name"] == "test.widget"
        assert comm_opens[0]["content"]["data"]["state"] == "initial"

    anyio.run(main)


def test_comm_info_request_with_comms(protocol):
    """comm_info_request returns info about open comms."""
    async def main():
        comm = Comm(target_name="jupyter.widget.comm", comm_id="w1")
        get_comm_manager().register_comm(comm)
        comm._open = True

        msg = create_message("comm_info_request", content={"target_name": ""})
        reply = await protocol.handle_message("shell", _make_raw(msg))
        _, parts = feed_identities(reply)
        parsed = deserialize_message(parts)
        assert parsed["msg_type"] == "comm_info_reply"
        assert "w1" in parsed["content"]["comms"]

        get_comm_manager().unregister_comm("w1")

    anyio.run(main)


def test_comm_open_from_frontend(protocol):
    """comm_open from frontend dispatches to registered target handler."""
    async def main():
        received = []
        get_comm_manager().register_target("test.frontend", lambda comm, msg: received.append(comm))

        msg = create_message("comm_open", content={
            "comm_id": "fe1",
            "target_name": "test.frontend",
            "data": {},
        })
        reply = await protocol.handle_message("shell", _make_raw(msg))
        assert reply is None  # comm_open has no reply

        assert len(received) == 1
        assert received[0].comm_id == "fe1"

        get_comm_manager().unregister_target("test.frontend")
        get_comm_manager().unregister_comm("fe1")

    anyio.run(main)
