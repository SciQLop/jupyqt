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


async def _collect_iopub(protocol: KernelProtocol) -> list[dict]:
    """Collect all available iopub messages until the channel is empty."""
    collected = []
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


def test_complete_request(protocol):
    async def main():
        protocol._shell.run_cell("my_variable_xyz = 42")
        msg = create_message("complete_request", content={"code": "my_vari", "cursor_pos": 7})
        reply = await protocol.handle_message("shell", _make_raw(msg))
        _, parts = feed_identities(reply)
        parsed = deserialize_message(parts)
        assert parsed["msg_type"] == "complete_reply"
        assert "my_variable_xyz" in parsed["content"]["matches"]

    anyio.run(main)


def test_inspect_request(protocol):
    async def main():
        protocol._shell.run_cell("def my_func():\n    '''A docstring.'''\n    pass")
        msg = create_message("inspect_request", content={
            "code": "my_func", "cursor_pos": 7, "detail_level": 0,
        })
        reply = await protocol.handle_message("shell", _make_raw(msg))
        _, parts = feed_identities(reply)
        parsed = deserialize_message(parts)
        assert parsed["msg_type"] == "inspect_reply"
        assert parsed["content"]["found"] is True

    anyio.run(main)


def test_is_complete_request_complete(protocol):
    async def main():
        msg = create_message("is_complete_request", content={"code": "x = 1"})
        reply = await protocol.handle_message("shell", _make_raw(msg))
        _, parts = feed_identities(reply)
        parsed = deserialize_message(parts)
        assert parsed["msg_type"] == "is_complete_reply"
        assert parsed["content"]["status"] == "complete"

    anyio.run(main)


def test_is_complete_request_incomplete(protocol):
    async def main():
        msg = create_message("is_complete_request", content={"code": "def foo():"})
        reply = await protocol.handle_message("shell", _make_raw(msg))
        _, parts = feed_identities(reply)
        parsed = deserialize_message(parts)
        assert parsed["msg_type"] == "is_complete_reply"
        assert parsed["content"]["status"] == "incomplete"

    anyio.run(main)


def test_execute_display_data(protocol):
    """display() calls produce display_data iopub messages."""
    async def main():
        msg = create_message("execute_request", content={
            "code": "from IPython.display import display, HTML; display(HTML('<b>hi</b>'))",
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
        display_msgs = [m for m in iopub_msgs if m["msg_type"] == "display_data"]
        assert len(display_msgs) >= 1
        assert "text/html" in display_msgs[0]["content"]["data"]
        assert "<b>hi</b>" in display_msgs[0]["content"]["data"]["text/html"]

    anyio.run(main)


def test_execute_rich_result(protocol):
    """Objects with rich reprs include all mime types in execute_result."""
    async def main():
        msg = create_message("execute_request", content={
            "code": "from IPython.display import HTML; HTML('<em>rich</em>')",
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
        result_msgs = [m for m in iopub_msgs if m["msg_type"] == "execute_result"]
        assert len(result_msgs) == 1
        data = result_msgs[0]["content"]["data"]
        assert "text/html" in data
        assert "<em>rich</em>" in data["text/html"]
        assert "text/plain" in data

    anyio.run(main)


def test_shutdown_request(protocol):
    async def main():
        msg = create_message("shutdown_request", content={"restart": False})
        reply = await protocol.handle_message("shell", _make_raw(msg))
        _, parts = feed_identities(reply)
        parsed = deserialize_message(parts)
        assert parsed["msg_type"] == "shutdown_reply"
        assert parsed["content"]["status"] == "ok"

    anyio.run(main)


def test_complete_request_survives_busy_kernel(shell):
    """A completion request must never crash the kernel when the kernel thread
    is busy running a long synchronous cell: it degrades to an empty reply
    instead of raising an unhandled TimeoutError out of the dispatch loop."""
    import time

    from jupyqt.kernel.thread import KernelThread

    kt = KernelThread(shell)
    kt.start()
    try:
        protocol = KernelProtocol(shell, key="0", kernel_thread=kt)
        protocol._control_timeout = 0.3
        # Occupy the single kernel loop longer than the control timeout,
        # mimicking a slow synchronous cell (e.g. a blocking data fetch).
        kt.loop.call_soon_threadsafe(lambda: time.sleep(1.5))

        async def main():
            msg = create_message(
                "complete_request", content={"code": "pri", "cursor_pos": 3},
            )
            reply = await protocol.handle_message("shell", _make_raw(msg))
            _, parts = feed_identities(reply)
            parsed = deserialize_message(parts)
            assert parsed["msg_type"] == "complete_reply"
            assert parsed["content"]["status"] == "ok"
            assert parsed["content"]["matches"] == []  # graceful, not a crash

        anyio.run(main)
    finally:
        kt.stop()


def test_handle_message_returns_error_reply_on_handler_exception(protocol):
    """A handler that raises must yield an error reply, never propagate out of
    handle_message (which would tear down the jupyverse dispatch task group)."""
    async def boom(_msg):
        raise RuntimeError("kaboom")

    protocol._handlers["execute_request"] = boom

    async def main():
        msg = create_message("execute_request", content={
            "code": "x = 1", "silent": False, "allow_stdin": False,
        })
        reply = await protocol.handle_message("shell", _make_raw(msg))
        _, parts = feed_identities(reply)
        parsed = deserialize_message(parts)
        assert parsed["msg_type"] == "execute_reply"
        assert parsed["content"]["status"] == "error"
        assert "kaboom" in parsed["content"]["evalue"]

    anyio.run(main)
