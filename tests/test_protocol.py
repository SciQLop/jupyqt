from __future__ import annotations

import anyio
import pytest

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


async def _collect_iopub(protocol: KernelProtocol, timeout: float = 5.0) -> list[dict]:
    """Collect all available iopub messages until the channel is empty."""
    collected = []
    with anyio.fail_after(timeout):
        while True:
            try:
                raw = protocol.iopub_receive.receive_nowait()
                _, parts = feed_identities(raw)
                collected.append(deserialize_message(parts))
            except anyio.WouldBlock:
                break
    return collected


def test_kernel_info_request(protocol):
    async def main():
        msg = create_message("kernel_info_request")
        reply = await protocol.handle_message("shell", _make_raw(msg))
        _, parts = feed_identities(reply)
        parsed = deserialize_message(parts)
        assert parsed["msg_type"] == "kernel_info_reply"
        assert parsed["content"]["language_info"]["name"] == "python"
        assert parsed["content"]["status"] == "ok"

    anyio.run(main)


def test_execute_request_simple(protocol):
    async def main():
        msg = create_message("execute_request", content={
            "code": "x = 1 + 2",
            "silent": False,
            "store_history": True,
            "allow_stdin": False,
            "stop_on_error": True,
        })
        reply = await protocol.handle_message("shell", _make_raw(msg))
        _, parts = feed_identities(reply)
        parsed = deserialize_message(parts)
        assert parsed["msg_type"] == "execute_reply"
        assert parsed["content"]["status"] == "ok"
        assert protocol._shell.user_ns["x"] == 3

    anyio.run(main)


def test_execute_request_with_stdout(protocol):
    async def main():
        msg = create_message("execute_request", content={
            "code": "print('hello from kernel')",
            "silent": False,
            "store_history": True,
            "allow_stdin": False,
            "stop_on_error": True,
        })
        reply = await protocol.handle_message("shell", _make_raw(msg))
        _, parts = feed_identities(reply)
        parsed = deserialize_message(parts)
        assert parsed["content"]["status"] == "ok"
        iopub_msgs = await _collect_iopub(protocol)
        stream_msgs = [m for m in iopub_msgs if m["msg_type"] == "stream"]
        assert any("hello from kernel" in m["content"]["text"] for m in stream_msgs)

    anyio.run(main)


def test_execute_request_with_error(protocol):
    async def main():
        msg = create_message("execute_request", content={
            "code": "1 / 0",
            "silent": False,
            "store_history": True,
            "allow_stdin": False,
            "stop_on_error": True,
        })
        reply = await protocol.handle_message("shell", _make_raw(msg))
        _, parts = feed_identities(reply)
        parsed = deserialize_message(parts)
        assert parsed["content"]["status"] == "error"
        assert parsed["content"]["ename"] == "ZeroDivisionError"

    anyio.run(main)
