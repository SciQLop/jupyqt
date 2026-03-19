"""Tests for kernel_info, rich errors, interrupt, and stdin support."""

from __future__ import annotations

import sys
import threading

import anyio
import pytest

from jupyqt.kernel.messages import (
    create_message,
    deserialize_message,
    feed_identities,
    serialize_message,
)
from jupyqt.kernel.protocol import KernelProtocol
from jupyqt.kernel.thread import KernelThread


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


async def _collect_stdin(protocol: KernelProtocol) -> list[dict]:
    collected = []
    while True:
        try:
            raw = protocol.stdin_receive.receive_nowait()
            _, parts = feed_identities(raw)
            collected.append(deserialize_message(parts))
        except anyio.WouldBlock:
            break
    return collected


# --- kernel_info ---

def test_kernel_info_has_language_info(protocol):
    async def main():
        msg = create_message("kernel_info_request")
        reply = await protocol.handle_message("shell", _make_raw(msg))
        _, parts = feed_identities(reply)
        parsed = deserialize_message(parts)
        assert parsed["msg_type"] == "kernel_info_reply"
        assert parsed["content"]["status"] == "ok"
        info = parsed["content"]["language_info"]
        assert info["name"] == "python"
        assert info["version"] == sys.version.split()[0]
        assert info["mimetype"] == "text/x-python"
        assert info["file_extension"] == ".py"

    anyio.run(main)


def test_kernel_info_has_banner(protocol):
    async def main():
        msg = create_message("kernel_info_request")
        reply = await protocol.handle_message("shell", _make_raw(msg))
        _, parts = feed_identities(reply)
        parsed = deserialize_message(parts)
        assert "jupyqt" in parsed["content"]["banner"]
        assert parsed["content"]["implementation"] == "jupyqt"

    anyio.run(main)


# --- rich errors ---

def test_error_iopub_message(protocol):
    """Errors produce an 'error' iopub message with ename/evalue/traceback."""
    async def main():
        msg = create_message("execute_request", content={
            "code": "1/0", "silent": False,
        })
        reply = await protocol.handle_message("shell", _make_raw(msg))
        _, parts = feed_identities(reply)
        parsed = deserialize_message(parts)
        assert parsed["content"]["status"] == "error"
        assert parsed["content"]["ename"] == "ZeroDivisionError"

        iopub = await _collect_iopub(protocol)
        error_msgs = [m for m in iopub if m["msg_type"] == "error"]
        assert len(error_msgs) == 1
        assert error_msgs[0]["content"]["ename"] == "ZeroDivisionError"
        assert len(error_msgs[0]["content"]["traceback"]) > 0

    anyio.run(main)


def test_error_reply_contains_traceback(protocol):
    """execute_reply with status=error includes traceback list."""
    async def main():
        msg = create_message("execute_request", content={
            "code": "raise ValueError('test error')", "silent": False,
        })
        reply = await protocol.handle_message("shell", _make_raw(msg))
        _, parts = feed_identities(reply)
        parsed = deserialize_message(parts)
        assert parsed["content"]["status"] == "error"
        assert parsed["content"]["ename"] == "ValueError"
        assert parsed["content"]["evalue"] == "test error"
        assert isinstance(parsed["content"]["traceback"], list)
        assert len(parsed["content"]["traceback"]) > 0

    anyio.run(main)


def test_keyboard_interrupt_error(protocol):
    """KeyboardInterrupt during execution produces proper error reply."""
    async def main():
        msg = create_message("execute_request", content={
            "code": "raise KeyboardInterrupt()", "silent": False,
        })
        reply = await protocol.handle_message("shell", _make_raw(msg))
        _, parts = feed_identities(reply)
        parsed = deserialize_message(parts)
        assert parsed["content"]["status"] == "error"
        assert parsed["content"]["ename"] == "KeyboardInterrupt"

    anyio.run(main)


# --- interrupt ---

def test_kernel_thread_interrupt():
    """KernelThread.interrupt() raises KeyboardInterrupt in the running code."""
    from jupyqt.kernel.shell import create_shell
    from IPython.core.interactiveshell import InteractiveShell

    shell = create_shell()
    kt = KernelThread(shell)
    kt.start()

    try:
        result = [None]

        def _run_long():
            try:
                shell.run_cell("import time\nfor i in range(1000): time.sleep(0.01)")
            except KeyboardInterrupt:
                pass
            result[0] = "interrupted"

        t = threading.Thread(target=lambda: kt.run_sync(_run_long))
        t.start()

        # Give it a moment to start, then interrupt
        import time
        time.sleep(0.2)
        kt.interrupt()
        t.join(timeout=5)
        assert result[0] == "interrupted"
    finally:
        kt.stop()
        InteractiveShell.clear_instance()


# --- stdin ---

def test_input_sends_request_on_stdin(protocol):
    """input() during execution sends input_request on the stdin channel."""
    async def main():
        # Supply the reply in a background thread after a short delay
        def _supply_reply():
            import time
            time.sleep(0.1)
            protocol.supply_stdin_reply("Alice")

        t = threading.Thread(target=_supply_reply)
        t.start()

        msg = create_message("execute_request", content={
            "code": "name = input('Name: ')",
            "silent": False,
            "allow_stdin": True,
        })
        reply = await protocol.handle_message("shell", _make_raw(msg))
        t.join(timeout=5)

        _, parts = feed_identities(reply)
        parsed = deserialize_message(parts)
        assert parsed["content"]["status"] == "ok"
        assert protocol._shell.user_ns["name"] == "Alice"

        stdin_msgs = await _collect_stdin(protocol)
        input_requests = [m for m in stdin_msgs if m["msg_type"] == "input_request"]
        assert len(input_requests) == 1
        assert input_requests[0]["content"]["prompt"] == "Name: "

    anyio.run(main)


def test_input_without_allow_stdin(protocol):
    """input() without allow_stdin raises an error."""
    async def main():
        msg = create_message("execute_request", content={
            "code": "x = input('prompt')",
            "silent": False,
            "allow_stdin": False,
        })
        reply = await protocol.handle_message("shell", _make_raw(msg))
        _, parts = feed_identities(reply)
        parsed = deserialize_message(parts)
        # Without allow_stdin, builtins.input is not patched, so it will
        # try to read from the captured stdout writer which should fail
        assert parsed["content"]["status"] == "error"

    anyio.run(main)
