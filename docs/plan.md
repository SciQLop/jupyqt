# jupyqt Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a standalone Python package that embeds JupyterLab in PySide6 applications using an in-process IPython kernel on a background thread, jupyverse as the server, and anyio memory streams (no ZMQ).

**Architecture:** Background-thread kernel with full IPython `InteractiveShell`, wire protocol handler over anyio memory streams, jupyverse kernel plugin for serving JupyterLab, Qt proxy layer for cross-thread safety, and a QWebEngineView widget.

**Tech Stack:** IPython, jupyverse (fps), anyio, PySide6, uvicorn

**Spec:** `docs/design.md`

---

## File Map

### Source files to create

| File | Responsibility |
|------|---------------|
| `src/jupyqt/__init__.py` | Re-export `EmbeddedJupyter`, `QtProxy` |
| `src/jupyqt/api.py` | `EmbeddedJupyter` public API class |
| `src/jupyqt/kernel/__init__.py` | Package marker |
| `src/jupyqt/kernel/shell.py` | `create_shell()` — InteractiveShell setup, stdout/stderr/display capture |
| `src/jupyqt/kernel/protocol.py` | `KernelProtocol` — Jupyter wire protocol message dispatch |
| `src/jupyqt/kernel/messages.py` | `serialize_message()`, `deserialize_message()`, `create_message()` helpers |
| `src/jupyqt/kernel/thread.py` | `KernelThread` — background thread with asyncio loop, shell handoff, thread-safe push |
| `src/jupyqt/server/__init__.py` | Package marker |
| `src/jupyqt/server/plugin.py` | `JupyQtKernel(Kernel)`, `JupyQtKernelFactory`, FPS module |
| `src/jupyqt/server/launcher.py` | `ServerLauncher` — start/stop jupyverse+uvicorn in background thread |
| `src/jupyqt/qt/__init__.py` | Package marker |
| `src/jupyqt/qt/proxy.py` | `QtProxy`, `MainThreadInvoker` |
| `src/jupyqt/qt/widget.py` | `JupyterLabWidget(QWidget)` |

### Test files to create

| File | Tests |
|------|-------|
| `tests/test_messages.py` | Serialize/deserialize round-trip, HMAC signing, feed_identities |
| `tests/test_shell.py` | Shell creation, stdout capture, display hooks |
| `tests/test_protocol.py` | Protocol handler dispatch: kernel_info, execute, complete, inspect |
| `tests/test_thread.py` | KernelThread start/stop, thread-safe push, cell execution on kernel thread |
| `tests/test_proxy.py` | QtProxy cross-thread marshaling (requires Qt) |
| `tests/test_plugin.py` | JupyQtKernel stream wiring, start/stop lifecycle |
| `tests/test_integration.py` | EmbeddedJupyter start, push, wrap_qt, shutdown |
| `tests/conftest.py` | Shared fixtures (shell, protocol) with proper singleton cleanup |

### Files to modify

| File | Change |
|------|--------|
| `pyproject.toml` | Add dependencies, remove CLI entry point, update classifiers |
| `src/jupyqt/__init__.py` | Replace CLI exports with `EmbeddedJupyter`, `QtProxy` |

### Files to delete

| File | Reason |
|------|--------|
| `src/jupyqt/_internal/cli.py` | No CLI needed |
| `src/jupyqt/_internal/debug.py` | Template boilerplate |
| `src/jupyqt/_internal/__init__.py` | Template boilerplate |
| `src/jupyqt/__main__.py` | No CLI needed |
| `tests/test_cli.py` | No CLI |
| `tests/test_api.py` | Template boilerplate, replaced by our tests |

---

## Task 1: Project setup — dependencies and cleanup

**Files:**
- Modify: `pyproject.toml`
- Modify: `src/jupyqt/__init__.py`
- Delete: `src/jupyqt/_internal/cli.py`, `src/jupyqt/_internal/debug.py`, `src/jupyqt/_internal/__init__.py`, `src/jupyqt/__main__.py`, `tests/test_cli.py`, `tests/test_api.py`
- Create: `src/jupyqt/kernel/__init__.py`, `src/jupyqt/server/__init__.py`, `src/jupyqt/qt/__init__.py`
- Modify: `tests/conftest.py`

- [ ] **Step 1: Delete template boilerplate**

```bash
rm src/jupyqt/_internal/cli.py src/jupyqt/_internal/debug.py src/jupyqt/_internal/__init__.py
rmdir src/jupyqt/_internal
rm src/jupyqt/__main__.py
rm tests/test_cli.py tests/test_api.py
```

- [ ] **Step 2: Update pyproject.toml**

Replace `dependencies = []` with:

```toml
dependencies = [
    "ipython>=8.0",
    "anyio>=4.0",
    "jupyverse[jupyterlab]>=0.14",
    "fps-kernels>=0.14",
    "uvicorn>=0.30",
    "PySide6>=6.5",
]
```

Remove the `[project.scripts]` section entirely. Update classifiers:

```toml
classifiers = [
    "Development Status :: 3 - Alpha",
    "Intended Audience :: Developers",
    "Framework :: Jupyter",
    "Programming Language :: Python :: 3",
    "Programming Language :: Python :: 3 :: Only",
    "Programming Language :: Python :: 3.10",
    "Programming Language :: Python :: 3.11",
    "Programming Language :: Python :: 3.12",
    "Programming Language :: Python :: 3.13",
    "Programming Language :: Python :: 3.14",
    "Typing :: Typed",
]
```

Add `pytest-qt` to the ci dependency group:

```toml
ci = [
    # ... existing entries ...
    "pytest-qt>=4.2",
]
```

- [ ] **Step 3: Create package directories**

```bash
mkdir -p src/jupyqt/kernel src/jupyqt/server src/jupyqt/qt
touch src/jupyqt/kernel/__init__.py src/jupyqt/server/__init__.py src/jupyqt/qt/__init__.py
```

- [ ] **Step 4: Update `src/jupyqt/__init__.py`**

```python
"""jupyqt — Embed JupyterLab in PySide6 applications."""

from __future__ import annotations

__all__: list[str] = ["EmbeddedJupyter", "QtProxy"]


def __getattr__(name: str):
    if name == "EmbeddedJupyter":
        from jupyqt.api import EmbeddedJupyter
        return EmbeddedJupyter
    if name == "QtProxy":
        from jupyqt.qt.proxy import QtProxy
        return QtProxy
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
```

- [ ] **Step 5: Create shared test fixtures in `tests/conftest.py`**

```python
# tests/conftest.py
"""Shared fixtures for jupyqt tests."""

from __future__ import annotations

import pytest
from IPython.core.interactiveshell import InteractiveShell

from jupyqt.kernel.shell import create_shell


@pytest.fixture
def shell():
    """Create a fresh InteractiveShell, cleaning up the singleton after."""
    s = create_shell()
    yield s
    InteractiveShell.clear_instance()
```

- [ ] **Step 6: Verify setup**

Run: `cd /var/home/jeandet/Documents/prog/jupyqt && uv sync`
Expected: Dependencies install successfully.

- [ ] **Step 7: Commit**

```bash
git add pyproject.toml src/jupyqt/__init__.py src/jupyqt/kernel/__init__.py src/jupyqt/server/__init__.py src/jupyqt/qt/__init__.py tests/conftest.py
git rm src/jupyqt/_internal/cli.py src/jupyqt/_internal/debug.py src/jupyqt/_internal/__init__.py src/jupyqt/__main__.py tests/test_cli.py tests/test_api.py
git commit -m "chore: set up dependencies and package structure"
```

---

## Task 2: Message serialization layer

**Files:**
- Create: `src/jupyqt/kernel/messages.py`
- Test: `tests/test_messages.py`

- [ ] **Step 1: Write tests for message serialization**

```python
# tests/test_messages.py
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
    raw = idents + [DELIM] + parts
    got_idents, got_parts = feed_identities(raw)
    assert got_idents == idents
    assert got_parts == parts


def test_feed_identities_no_idents():
    parts = [b"hmac", b"header"]
    raw = [DELIM] + parts
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
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd /var/home/jeandet/Documents/prog/jupyqt && uv run pytest tests/test_messages.py -v`
Expected: FAIL — `ModuleNotFoundError`

- [ ] **Step 3: Implement message helpers**

```python
# src/jupyqt/kernel/messages.py
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
    return msg_list[:idx], msg_list[idx + 1 :]


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
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd /var/home/jeandet/Documents/prog/jupyqt && uv run pytest tests/test_messages.py -v`
Expected: All 6 tests PASS.

- [ ] **Step 5: Commit**

```bash
git add src/jupyqt/kernel/messages.py tests/test_messages.py
git commit -m "feat: add Jupyter wire protocol message serialization"
```

---

## Task 3: Shell setup with output capture

**Files:**
- Create: `src/jupyqt/kernel/shell.py`
- Test: `tests/test_shell.py`

- [ ] **Step 1: Write tests for shell creation and output capture**

```python
# tests/test_shell.py
from __future__ import annotations

from jupyqt.kernel.shell import create_shell, OutputCapture


def test_create_shell_returns_interactive_shell(shell):
    from IPython.core.interactiveshell import InteractiveShell
    assert isinstance(shell, InteractiveShell)


def test_shell_can_execute_code(shell):
    result = shell.run_cell("x = 42")
    assert not result.error_before_exec
    assert not result.error_in_exec
    assert shell.user_ns["x"] == 42


def test_output_capture_captures_stdout():
    collected = []
    capture = OutputCapture(on_stdout=lambda text: collected.append(text))
    with capture:
        print("hello")
    assert any("hello" in text for text in collected)


def test_output_capture_captures_stderr():
    import sys
    collected = []
    capture = OutputCapture(on_stderr=lambda text: collected.append(text))
    with capture:
        print("error msg", file=sys.stderr)
    assert any("error msg" in text for text in collected)


def test_shell_push_variables(shell):
    shell.push({"my_var": 123})
    result = shell.run_cell("out = my_var + 1")
    assert shell.user_ns["out"] == 124
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd /var/home/jeandet/Documents/prog/jupyqt && uv run pytest tests/test_shell.py -v`
Expected: FAIL — `ImportError`

- [ ] **Step 3: Implement shell setup**

```python
# src/jupyqt/kernel/shell.py
"""InteractiveShell creation and output capture for jupyqt."""

from __future__ import annotations

import io
import sys
from typing import Callable

from IPython.core.interactiveshell import InteractiveShell


def create_shell() -> InteractiveShell:
    InteractiveShell.clear_instance()
    return InteractiveShell.instance(colors="Neutral", autocall=0)


class OutputCapture:
    """Context manager that captures stdout/stderr and routes to callbacks."""

    def __init__(
        self,
        on_stdout: Callable[[str], None] | None = None,
        on_stderr: Callable[[str], None] | None = None,
    ):
        self._on_stdout = on_stdout
        self._on_stderr = on_stderr
        self._orig_stdout: io.TextIOBase | None = None
        self._orig_stderr: io.TextIOBase | None = None

    def __enter__(self):
        self._orig_stdout = sys.stdout
        self._orig_stderr = sys.stderr
        if self._on_stdout:
            sys.stdout = _CallbackWriter(self._on_stdout)
        if self._on_stderr:
            sys.stderr = _CallbackWriter(self._on_stderr)
        return self

    def __exit__(self, *exc):
        sys.stdout = self._orig_stdout
        sys.stderr = self._orig_stderr
        return False


class _CallbackWriter(io.TextIOBase):
    """A writable stream that sends each write() to a callback."""

    def __init__(self, callback: Callable[[str], None]):
        self._callback = callback

    def write(self, text: str) -> int:
        if text:
            self._callback(text)
        return len(text)

    def flush(self):
        pass
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd /var/home/jeandet/Documents/prog/jupyqt && uv run pytest tests/test_shell.py -v`
Expected: All 5 tests PASS.

- [ ] **Step 5: Commit**

```bash
git add src/jupyqt/kernel/shell.py tests/test_shell.py
git commit -m "feat: add InteractiveShell setup and output capture"
```

---

## Task 4: Kernel thread

**Files:**
- Create: `src/jupyqt/kernel/thread.py`
- Test: `tests/test_thread.py`

This is the core threading component from the spec. The kernel thread owns the InteractiveShell after `start()`, runs an asyncio event loop, and provides thread-safe `push()`.

- [ ] **Step 1: Write tests for KernelThread**

```python
# tests/test_thread.py
from __future__ import annotations

import threading

import pytest

from jupyqt.kernel.thread import KernelThread


@pytest.fixture
def kernel_thread(shell):
    kt = KernelThread(shell)
    yield kt
    if kt.is_alive():
        kt.stop()


def test_kernel_thread_starts_and_stops(kernel_thread):
    kernel_thread.start()
    assert kernel_thread.is_alive()
    kernel_thread.stop()
    assert not kernel_thread.is_alive()


def test_kernel_thread_runs_on_separate_thread(kernel_thread):
    kernel_thread.start()
    assert kernel_thread.thread_id != threading.main_thread().ident


def test_kernel_thread_has_event_loop(kernel_thread):
    kernel_thread.start()
    assert kernel_thread.loop is not None


def test_thread_safe_push(kernel_thread):
    kernel_thread.start()
    kernel_thread.push({"injected": 999})
    # Ensure push is processed by running a sync barrier on the kernel thread
    kernel_thread.run_sync(lambda: None)
    assert kernel_thread.shell.user_ns["injected"] == 999


def test_run_on_kernel_thread(kernel_thread):
    """Verify that run_sync executes code on the kernel thread."""
    kernel_thread.start()
    result = kernel_thread.run_sync(lambda: threading.current_thread().ident)
    assert result == kernel_thread.thread_id
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd /var/home/jeandet/Documents/prog/jupyqt && uv run pytest tests/test_thread.py -v`
Expected: FAIL — `ImportError`

- [ ] **Step 3: Implement KernelThread**

```python
# src/jupyqt/kernel/thread.py
"""Background thread for the IPython kernel.

The kernel thread owns the InteractiveShell after start(). It runs an asyncio
event loop for message dispatch and provides thread-safe access methods.
"""

from __future__ import annotations

import asyncio
import concurrent.futures
import threading
from typing import Any, Callable, TypeVar

from IPython.core.interactiveshell import InteractiveShell

T = TypeVar("T")


class KernelThread:
    """Background thread with its own asyncio loop for kernel execution."""

    def __init__(self, shell: InteractiveShell) -> None:
        self._shell = shell
        self._thread: threading.Thread | None = None
        self._loop: asyncio.AbstractEventLoop | None = None
        self._started = threading.Event()
        self._thread_id: int | None = None

    @property
    def shell(self) -> InteractiveShell:
        return self._shell

    @property
    def loop(self) -> asyncio.AbstractEventLoop | None:
        return self._loop

    @property
    def thread_id(self) -> int | None:
        return self._thread_id

    def is_alive(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    def start(self) -> None:
        self._thread = threading.Thread(target=self._run, daemon=True, name="jupyqt-kernel")
        self._thread.start()
        self._started.wait(timeout=10)

    def stop(self) -> None:
        if self._loop is not None:
            self._loop.call_soon_threadsafe(self._loop.stop)
        if self._thread is not None:
            self._thread.join(timeout=10)
            self._thread = None
            self._loop = None
            self._thread_id = None

    def push(self, variables: dict[str, Any]) -> None:
        """Thread-safe variable injection into the shell namespace."""
        if self._loop is None:
            self._shell.push(variables)
        else:
            self._loop.call_soon_threadsafe(self._shell.push, variables)

    def run_sync(self, func: Callable[..., T], *args: Any) -> T:
        """Run a synchronous callable on the kernel thread, blocking until done."""
        if self._loop is None:
            raise RuntimeError("KernelThread is not running")
        future: concurrent.futures.Future[T] = concurrent.futures.Future()

        def _wrapper():
            try:
                future.set_result(func(*args))
            except Exception as e:
                future.set_exception(e)

        self._loop.call_soon_threadsafe(_wrapper)
        return future.result(timeout=30)

    def _run(self) -> None:
        self._loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self._loop)
        self._thread_id = threading.current_thread().ident
        self._started.set()
        self._loop.run_forever()
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd /var/home/jeandet/Documents/prog/jupyqt && uv run pytest tests/test_thread.py -v`
Expected: All 5 tests PASS.

- [ ] **Step 5: Commit**

```bash
git add src/jupyqt/kernel/thread.py tests/test_thread.py
git commit -m "feat: add KernelThread — background thread with asyncio loop"
```

---

## Task 5: Wire protocol handler (Phase 1 — execute + kernel_info)

**Files:**
- Create: `src/jupyqt/kernel/protocol.py`
- Test: `tests/test_protocol.py`

Key design: `KernelProtocol` takes an optional `KernelThread` reference. When set, `run_cell()` is dispatched to the kernel thread via `KernelThread.run_sync()`, ensuring all shell access happens on the dedicated kernel thread (not arbitrary anyio worker threads). When no kernel thread is set (unit tests), `run_cell()` runs directly. stdout/stderr are collected during execution and published to iopub after `run_cell()` returns (real-time streaming during execution is a future improvement).

- [ ] **Step 1: Write tests for protocol handler**

```python
# tests/test_protocol.py
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
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd /var/home/jeandet/Documents/prog/jupyqt && uv run pytest tests/test_protocol.py -v`
Expected: FAIL — `ImportError`

- [ ] **Step 3: Implement protocol handler**

```python
# src/jupyqt/kernel/protocol.py
"""Jupyter wire protocol handler for jupyqt.

Dispatches incoming Jupyter messages to handlers and publishes
results/output on the iopub channel. Cell execution is dispatched to a
worker thread via anyio.to_thread.run_sync() so it never blocks the
async event loop. stdout/stderr are captured and published to iopub
in real time during execution.
"""

from __future__ import annotations

import math
import sys
import traceback
from typing import Any

import anyio
from anyio.streams.memory import MemoryObjectReceiveStream, MemoryObjectSendStream

from IPython.core.interactiveshell import InteractiveShell

from jupyqt.kernel.messages import (
    create_message,
    deserialize_message,
    feed_identities,
    serialize_message,
)
from jupyqt.kernel.shell import OutputCapture
from jupyqt.kernel.thread import KernelThread


class KernelProtocol:
    """Handles Jupyter wire protocol messages using an InteractiveShell."""

    def __init__(
        self,
        shell: InteractiveShell,
        key: str = "0",
        kernel_thread: KernelThread | None = None,
    ) -> None:
        self._shell = shell
        self._key = key
        self._kernel_thread = kernel_thread
        self._execution_count = 0
        self._iopub_send: MemoryObjectSendStream[list[bytes]]
        self._iopub_recv: MemoryObjectReceiveStream[list[bytes]]
        self._iopub_send, self._iopub_recv = anyio.create_memory_object_stream[list[bytes]](
            max_buffer_size=math.inf
        )
        self._handlers = {
            "kernel_info_request": self._handle_kernel_info,
            "execute_request": self._handle_execute,
        }

    @property
    def iopub_receive(self) -> MemoryObjectReceiveStream[list[bytes]]:
        return self._iopub_recv

    async def handle_message(self, channel: str, raw_msg: list[bytes]) -> list[bytes]:
        _, parts = feed_identities(raw_msg)
        msg = deserialize_message(parts)
        msg_type = msg["msg_type"]
        handler = self._handlers.get(msg_type)
        if handler is None:
            reply = create_message(
                msg_type.replace("_request", "_reply"),
                parent=msg,
                content={"status": "error", "ename": "NotImplementedError",
                         "evalue": f"Unknown: {msg_type}", "traceback": []},
            )
            return serialize_message(reply, self._key)
        await self._publish_status("busy", msg)
        reply = await handler(msg)
        serialized = serialize_message(reply, self._key)
        await self._publish_status("idle", msg)
        return serialized

    async def _publish_status(self, status: str, parent: dict[str, Any]) -> None:
        msg = create_message("status", parent=parent, content={"execution_state": status})
        await self._iopub_send.send(serialize_message(msg, self._key))

    async def _publish_stream(self, name: str, text: str, parent: dict[str, Any]) -> None:
        msg = create_message("stream", parent=parent, content={"name": name, "text": text})
        await self._iopub_send.send(serialize_message(msg, self._key))

    async def _handle_kernel_info(self, msg: dict[str, Any]) -> dict[str, Any]:
        return create_message(
            "kernel_info_reply",
            parent=msg,
            content={
                "status": "ok",
                "protocol_version": "5.4",
                "implementation": "jupyqt",
                "implementation_version": "0.1.0",
                "language_info": {
                    "name": "python",
                    "version": sys.version.split()[0],
                    "mimetype": "text/x-python",
                    "file_extension": ".py",
                    "pygments_lexer": "ipython3",
                    "codemirror_mode": {"name": "ipython", "version": 3},
                    "nbconvert_exporter": "python",
                },
                "banner": f"jupyqt kernel (Python {sys.version})",
                "help_links": [],
            },
        )

    async def _handle_execute(self, msg: dict[str, Any]) -> dict[str, Any]:
        content = msg["content"]
        code = content["code"]
        silent = content.get("silent", False)

        if not silent:
            self._execution_count += 1

        # Collect stdout/stderr chunks; published after run_cell returns.
        # Real-time streaming during execution is a future improvement.
        stdout_chunks: list[str] = []
        stderr_chunks: list[str] = []

        def _execute() -> Any:
            """Runs on the kernel thread (or current thread in unit tests)."""
            capture = OutputCapture(
                on_stdout=lambda text: stdout_chunks.append(text),
                on_stderr=lambda text: stderr_chunks.append(text),
            )
            with capture:
                return self._shell.run_cell(code, store_history=not silent, silent=silent)

        # Dispatch to the dedicated kernel thread if available,
        # otherwise run directly (for unit tests without a thread).
        if self._kernel_thread is not None:
            result = self._kernel_thread.run_sync(_execute)
        else:
            result = _execute()

        # Publish captured output
        if stdout_chunks:
            await self._publish_stream("stdout", "".join(stdout_chunks), msg)
        if stderr_chunks:
            await self._publish_stream("stderr", "".join(stderr_chunks), msg)

        # Handle display data / execute_result
        if result.result is not None and not silent:
            exec_result_msg = create_message(
                "execute_result",
                parent=msg,
                content={
                    "execution_count": self._execution_count,
                    "data": {"text/plain": repr(result.result)},
                    "metadata": {},
                },
            )
            await self._iopub_send.send(serialize_message(exec_result_msg, self._key))

        if result.error_in_exec is not None:
            tb = traceback.format_exception(
                type(result.error_in_exec), result.error_in_exec,
                result.error_in_exec.__traceback__,
            )
            error_content = {
                "status": "error",
                "ename": type(result.error_in_exec).__name__,
                "evalue": str(result.error_in_exec),
                "traceback": tb,
                "execution_count": self._execution_count,
            }
            error_msg = create_message("error", parent=msg, content=error_content)
            await self._iopub_send.send(serialize_message(error_msg, self._key))
            return create_message("execute_reply", parent=msg, content=error_content)

        return create_message(
            "execute_reply",
            parent=msg,
            content={
                "status": "ok",
                "execution_count": self._execution_count,
                "user_expressions": {},
            },
        )
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd /var/home/jeandet/Documents/prog/jupyqt && uv run pytest tests/test_protocol.py -v`
Expected: All 4 tests PASS.

- [ ] **Step 5: Commit**

```bash
git add src/jupyqt/kernel/protocol.py tests/test_protocol.py
git commit -m "feat: add wire protocol handler with execute and kernel_info"
```

---

## Task 6: Wire protocol Phase 2 — complete, inspect, is_complete, shutdown

**Files:**
- Modify: `src/jupyqt/kernel/protocol.py`
- Modify: `tests/test_protocol.py`

- [ ] **Step 1: Write tests for Phase 2 message types**

Add to `tests/test_protocol.py`:

```python
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


def test_shutdown_request(protocol):
    async def main():
        msg = create_message("shutdown_request", content={"restart": False})
        reply = await protocol.handle_message("shell", _make_raw(msg))
        _, parts = feed_identities(reply)
        parsed = deserialize_message(parts)
        assert parsed["msg_type"] == "shutdown_reply"
        assert parsed["content"]["status"] == "ok"

    anyio.run(main)
```

- [ ] **Step 2: Run tests to verify new ones fail**

Run: `cd /var/home/jeandet/Documents/prog/jupyqt && uv run pytest tests/test_protocol.py -v -k "complete or inspect or is_complete or shutdown"`
Expected: FAIL — handlers not registered.

- [ ] **Step 3: Add Phase 2 handlers to protocol.py**

Add to `KernelProtocol.__init__` `_handlers` dict:

```python
"complete_request": self._handle_complete,
"inspect_request": self._handle_inspect,
"is_complete_request": self._handle_is_complete,
"shutdown_request": self._handle_shutdown,
"history_request": self._handle_history,
```

Add these methods to `KernelProtocol`:

```python
async def _handle_complete(self, msg: dict[str, Any]) -> dict[str, Any]:
    content = msg["content"]
    code = content["code"]
    cursor_pos = content["cursor_pos"]
    # IPython's Completer.completions() returns Completion objects
    completions = list(self._shell.Completer.completions(code, cursor_pos))
    matches = [c.text for c in completions]
    cursor_start = completions[0].start if completions else cursor_pos
    return create_message(
        "complete_reply",
        parent=msg,
        content={
            "status": "ok",
            "matches": matches,
            "cursor_start": cursor_start,
            "cursor_end": cursor_pos,
            "metadata": {},
        },
    )

async def _handle_inspect(self, msg: dict[str, Any]) -> dict[str, Any]:
    content = msg["content"]
    code = content["code"]
    cursor_pos = content["cursor_pos"]
    detail_level = content.get("detail_level", 0)
    name = code[:cursor_pos].split()[-1] if code[:cursor_pos].strip() else ""
    try:
        info = self._shell.object_inspect(name, detail_level=detail_level)
        found = info.get("found", False)
        data = {}
        if found:
            text_parts = []
            if info.get("type_name"):
                text_parts.append(f"Type: {info['type_name']}")
            if info.get("string_form"):
                text_parts.append(f"String form: {info['string_form']}")
            if info.get("docstring"):
                text_parts.append(info["docstring"])
            data["text/plain"] = "\n".join(text_parts) if text_parts else str(info)
    except Exception:
        found = False
        data = {}
    return create_message(
        "inspect_reply",
        parent=msg,
        content={"status": "ok", "found": found, "data": data, "metadata": {}},
    )

async def _handle_is_complete(self, msg: dict[str, Any]) -> dict[str, Any]:
    code = msg["content"]["code"]
    result = self._shell.input_transformer_manager.check_complete(code)
    status = result[0]
    indent = result[1] if len(result) > 1 else ""
    reply_content = {"status": status}
    if status == "incomplete":
        reply_content["indent"] = indent or ""
    return create_message("is_complete_reply", parent=msg, content=reply_content)

async def _handle_shutdown(self, msg: dict[str, Any]) -> dict[str, Any]:
    restart = msg["content"].get("restart", False)
    return create_message(
        "shutdown_reply",
        parent=msg,
        content={"status": "ok", "restart": restart},
    )

async def _handle_history(self, msg: dict[str, Any]) -> dict[str, Any]:
    return create_message(
        "history_reply",
        parent=msg,
        content={"status": "ok", "history": []},
    )
```

- [ ] **Step 4: Run all protocol tests**

Run: `cd /var/home/jeandet/Documents/prog/jupyqt && uv run pytest tests/test_protocol.py -v`
Expected: All 9 tests PASS.

- [ ] **Step 5: Commit**

```bash
git add src/jupyqt/kernel/protocol.py tests/test_protocol.py
git commit -m "feat: add complete, inspect, is_complete, shutdown, history handlers"
```

---

## Task 7: Jupyverse kernel plugin

**Files:**
- Create: `src/jupyqt/server/plugin.py`
- Test: `tests/test_plugin.py`

- [ ] **Step 1: Write tests for the kernel plugin**

```python
# tests/test_plugin.py
from __future__ import annotations

import anyio

from jupyqt.kernel.messages import (
    create_message,
    deserialize_message,
    feed_identities,
    serialize_message,
)
from jupyqt.server.plugin import JupyQtKernel


def test_kernel_start_and_kernel_info(shell):
    async def main():
        kernel = JupyQtKernel(shell)
        async with anyio.create_task_group() as tg:
            await tg.start(kernel.start)
            msg = create_message("kernel_info_request")
            await kernel.shell_stream.send(serialize_message(msg, kernel.key))
            reply_raw = await kernel.shell_stream.receive()
            _, parts = feed_identities(reply_raw)
            reply = deserialize_message(parts)
            assert reply["msg_type"] == "kernel_info_reply"
            await kernel.stop()
            tg.cancel_scope.cancel()

    anyio.run(main)


def test_kernel_execute_cell(shell):
    async def main():
        kernel = JupyQtKernel(shell)
        async with anyio.create_task_group() as tg:
            await tg.start(kernel.start)
            msg = create_message("execute_request", content={
                "code": "result = 6 * 7",
                "silent": False,
                "store_history": True,
                "allow_stdin": False,
                "stop_on_error": True,
            })
            await kernel.shell_stream.send(serialize_message(msg, kernel.key))
            reply_raw = await kernel.shell_stream.receive()
            _, parts = feed_identities(reply_raw)
            reply = deserialize_message(parts)
            assert reply["content"]["status"] == "ok"
            assert shell.user_ns["result"] == 42
            await kernel.stop()
            tg.cancel_scope.cancel()

    anyio.run(main)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd /var/home/jeandet/Documents/prog/jupyqt && uv run pytest tests/test_plugin.py -v`
Expected: FAIL — `ImportError`

- [ ] **Step 3: Implement the kernel plugin**

```python
# src/jupyqt/server/plugin.py
"""Jupyverse kernel plugin for jupyqt.

Provides a Kernel implementation that wires jupyverse's memory streams
to our KernelProtocol. When jupyverse is not installed, JupyQtKernel
creates its own streams for testing.
"""

from __future__ import annotations

import math
from typing import Any

import anyio
from anyio.abc import TaskStatus
from anyio.streams.memory import MemoryObjectReceiveStream
from anyio.streams.stapled import StapledObjectStream

from IPython.core.interactiveshell import InteractiveShell

from jupyqt.kernel.protocol import KernelProtocol
from jupyqt.kernel.thread import KernelThread

try:
    from jupyverse_kernel import DefaultKernelFactory, Kernel, KernelFactory

    HAS_JUPYVERSE = True
except ImportError:
    HAS_JUPYVERSE = False


# Sentinel for default task_status parameter
_IGNORED = object()


class JupyQtKernel:
    """Kernel that processes Jupyter messages using an InteractiveShell.

    Creates its own anyio memory streams (same layout as jupyverse_kernel.Kernel).
    Used directly in tests; the jupyverse-compatible subclass is created by
    create_jupyqt_kernel_class().
    """

    def __init__(self, shell: InteractiveShell, kernel_thread: KernelThread | None = None, **kwargs: Any) -> None:
        self._shell = shell
        self.key = "0"
        self._protocol = KernelProtocol(shell, key=self.key, kernel_thread=kernel_thread)
        self._task_group: anyio.abc.TaskGroup | None = None

        self._to_shell_send, self._to_shell_recv = anyio.create_memory_object_stream[list[bytes]]()
        self._from_shell_send, self._from_shell_recv = anyio.create_memory_object_stream[list[bytes]]()
        self._to_control_send, self._to_control_recv = anyio.create_memory_object_stream[list[bytes]]()
        self._from_control_send, self._from_control_recv = anyio.create_memory_object_stream[list[bytes]]()
        self._to_stdin_send, self._to_stdin_recv = anyio.create_memory_object_stream[list[bytes]]()
        self._from_stdin_send, self._from_stdin_recv = anyio.create_memory_object_stream[list[bytes]]()
        self._from_iopub_send, self._from_iopub_recv = anyio.create_memory_object_stream[list[bytes]](
            max_buffer_size=math.inf
        )

        self._shell_stream = StapledObjectStream(self._to_shell_send, self._from_shell_recv)
        self._control_stream = StapledObjectStream(self._to_control_send, self._from_control_recv)
        self._stdin_stream = StapledObjectStream(self._to_stdin_send, self._from_stdin_recv)

    @property
    def shell_stream(self) -> StapledObjectStream:
        return self._shell_stream

    @property
    def control_stream(self) -> StapledObjectStream:
        return self._control_stream

    @property
    def stdin_stream(self) -> StapledObjectStream:
        return self._stdin_stream

    @property
    def iopub_stream(self) -> MemoryObjectReceiveStream:
        return self._from_iopub_recv

    async def start(self, *, task_status=_IGNORED) -> None:
        async with anyio.create_task_group() as tg:
            self._task_group = tg
            tg.start_soon(self._dispatch_channel, self._to_shell_recv, self._from_shell_send)
            tg.start_soon(self._dispatch_channel, self._to_control_recv, self._from_control_send)
            tg.start_soon(self._forward_iopub)
            if task_status is not _IGNORED:
                task_status.started()
            await anyio.sleep_forever()

    async def stop(self) -> None:
        if self._task_group:
            self._task_group.cancel_scope.cancel()

    async def interrupt(self) -> None:
        pass

    async def _dispatch_channel(self, recv_stream, send_stream) -> None:
        async for raw_msg in recv_stream:
            reply = await self._protocol.handle_message("shell", raw_msg)
            await send_stream.send(reply)

    async def _forward_iopub(self) -> None:
        async for raw_msg in self._protocol.iopub_receive:
            await self._from_iopub_send.send(raw_msg)


def create_jupyqt_kernel_class(shell: InteractiveShell, kernel_thread: KernelThread | None = None) -> type:
    """Create a Kernel subclass that inherits from jupyverse_kernel.Kernel.

    The class captures the shell and kernel_thread references via closure.
    """
    if not HAS_JUPYVERSE:
        raise ImportError("jupyverse is required")

    class _JupyQtJupyverseKernel(Kernel):
        def __init__(self, **kwargs: Any) -> None:
            super().__init__()
            self._protocol = KernelProtocol(shell, key=self.key, kernel_thread=kernel_thread)
            self._tg: anyio.abc.TaskGroup | None = None

        async def start(self, *, task_status: TaskStatus[None] = anyio.TASK_STATUS_IGNORED) -> None:
            async with anyio.create_task_group() as tg:
                self._tg = tg
                tg.start_soon(self._dispatch, self._to_shell_receive_stream, self._from_shell_send_stream)
                tg.start_soon(self._dispatch, self._to_control_receive_stream, self._from_control_send_stream)
                tg.start_soon(self._forward_iopub)
                self.started.set()
                task_status.started()
                await anyio.sleep_forever()

        async def stop(self) -> None:
            if self._tg:
                self._tg.cancel_scope.cancel()

        async def interrupt(self) -> None:
            pass

        async def _dispatch(self, recv_stream, send_stream) -> None:
            async for raw_msg in recv_stream:
                reply = await self._protocol.handle_message("shell", raw_msg)
                await send_stream.send(reply)

        async def _forward_iopub(self) -> None:
            async for raw_msg in self._protocol.iopub_receive:
                await self._from_iopub_send_stream.send(raw_msg)

    return _JupyQtJupyverseKernel


def create_kernel_factory(shell: InteractiveShell, kernel_thread: KernelThread | None = None) -> Any:
    """Create a KernelFactory for registering with jupyverse."""
    kernel_class = create_jupyqt_kernel_class(shell, kernel_thread)
    return KernelFactory(kernel_class)


class JupyQtKernelModule:
    """FPS module that registers the jupyqt kernel factory with jupyverse.

    The shell and kernel_thread must be set via set_shell() before
    jupyverse starts (called by ServerLauncher._run()).
    """

    _shell: InteractiveShell | None = None
    _kernel_thread: KernelThread | None = None

    @classmethod
    def set_shell(cls, shell: InteractiveShell, kernel_thread: KernelThread | None = None) -> None:
        cls._shell = shell
        cls._kernel_thread = kernel_thread

    async def prepare(self) -> None:
        if not HAS_JUPYVERSE or self._shell is None:
            return
        # Import here to avoid circular deps at module level
        from fps import Module
        from jupyverse_api.kernels import Kernels
        kernels = await Module.get(Kernels)
        factory = create_kernel_factory(self._shell, self._kernel_thread)
        kernels.register_kernel_factory("python3", factory)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd /var/home/jeandet/Documents/prog/jupyqt && uv run pytest tests/test_plugin.py -v`
Expected: All 2 tests PASS.

- [ ] **Step 5: Commit**

```bash
git add src/jupyqt/server/plugin.py tests/test_plugin.py
git commit -m "feat: add jupyverse kernel plugin with stream dispatch"
```

---

## Task 8: Server launcher

**Files:**
- Create: `src/jupyqt/server/launcher.py`
- Test: `tests/test_launcher.py`

**Note:** This is the riskiest task — the fps/jupyverse configuration API is not fully documented. The implementation below is a best-effort based on akernel's integration pattern. It will likely need iterative refinement during development. The test verifies the server starts and responds to HTTP; if the fps API differs, adjust the `_run()` method.

- [ ] **Step 1: Write test for server launcher**

```python
# tests/test_launcher.py
from __future__ import annotations

import time
import urllib.request

import pytest

from jupyqt.server.launcher import ServerLauncher


def test_server_starts_and_provides_url(shell):
    launcher = ServerLauncher(shell, port=0)  # No kernel_thread for basic test
    launcher.start()
    try:
        assert launcher.port > 0
        assert launcher.url.startswith("http://localhost:")
        assert launcher.token in launcher.url
    finally:
        launcher.stop()


def test_server_responds_to_http(shell):
    launcher = ServerLauncher(shell, port=0)
    launcher.start()
    try:
        time.sleep(3)  # Give uvicorn time to start
        req = urllib.request.Request(f"http://localhost:{launcher.port}/api/status")
        try:
            with urllib.request.urlopen(req, timeout=5) as resp:
                assert resp.status == 200
        except urllib.error.HTTPError as e:
            # 403 is OK — means server is running but auth is required
            assert e.code in (200, 403)
    finally:
        launcher.stop()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /var/home/jeandet/Documents/prog/jupyqt && uv run pytest tests/test_launcher.py -v`
Expected: FAIL — `ImportError`

- [ ] **Step 3: Implement server launcher**

```python
# src/jupyqt/server/launcher.py
"""Manages jupyverse server lifecycle in a background thread."""

from __future__ import annotations

import secrets
import socket
import threading
from typing import Any

from IPython.core.interactiveshell import InteractiveShell

from jupyqt.kernel.thread import KernelThread


def _find_free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("", 0))
        return s.getsockname()[1]


class ServerLauncher:
    """Starts and stops a jupyverse server in a background thread."""

    def __init__(
        self,
        shell: InteractiveShell,
        kernel_thread: KernelThread | None = None,
        port: int = 0,
        token: str | None = None,
    ) -> None:
        self._shell = shell
        self._kernel_thread = kernel_thread
        self._port = port if port != 0 else _find_free_port()
        self._token = token or secrets.token_hex(16)
        self._thread: threading.Thread | None = None
        self._server: Any = None
        self._started = threading.Event()

    @property
    def port(self) -> int:
        return self._port

    @property
    def token(self) -> str:
        return self._token

    @property
    def url(self) -> str:
        return f"http://localhost:{self._port}/lab?token={self._token}"

    def start(self) -> None:
        self._thread = threading.Thread(target=self._run, daemon=True, name="jupyqt-server")
        self._thread.start()
        self._started.wait(timeout=30)

    def stop(self) -> None:
        if self._server is not None:
            self._server.should_exit = True
        if self._thread is not None:
            self._thread.join(timeout=10)
            self._thread = None

    def _run(self) -> None:
        """Start jupyverse+uvicorn. This runs in the server thread.

        NOTE: The fps configuration API may need adjustment based on the
        actual jupyverse version. This is based on akernel's integration
        pattern. If it doesn't work, consult:
        - https://github.com/davidbrochart/akernel (fps_akernel_task)
        - https://github.com/jupyter-server/jupyverse (plugins/kernels)
        """
        import asyncio

        import uvicorn

        from jupyqt.server.plugin import JupyQtKernelModule, create_kernel_factory

        # Configure our kernel module with the shell and thread
        # so the FPS plugin can create kernel instances
        JupyQtKernelModule.set_shell(self._shell, self._kernel_thread)

        # Build jupyverse ASGI app via fps
        # fps discovers plugins via entry points (registered in pyproject.toml)
        try:
            from fps.app import create_app

            app = create_app()
        except ImportError:
            raise ImportError(
                "fps is required to run the jupyverse server. "
                "Install jupyverse[jupyterlab]."
            )

        config = uvicorn.Config(
            app,
            host="127.0.0.1",
            port=self._port,
            log_level="warning",
        )
        self._server = uvicorn.Server(config)
        self._started.set()

        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        loop.run_until_complete(self._server.serve())
```

- [ ] **Step 4: Run test**

Run: `cd /var/home/jeandet/Documents/prog/jupyqt && uv run pytest tests/test_launcher.py -v`
Expected: At minimum `test_server_starts_and_provides_url` passes. `test_server_responds_to_http` may need fps API adjustments.

- [ ] **Step 5: Commit**

```bash
git add src/jupyqt/server/launcher.py tests/test_launcher.py
git commit -m "feat: add jupyverse server launcher"
```

---

## Task 9: Qt proxy layer

**Files:**
- Create: `src/jupyqt/qt/proxy.py`
- Test: `tests/test_proxy.py`

- [ ] **Step 1: Write tests for QtProxy**

```python
# tests/test_proxy.py
from __future__ import annotations

import threading

import pytest
from PySide6.QtCore import QObject

from jupyqt.qt.proxy import MainThreadInvoker, QtProxy


class FakeWidget(QObject):
    def __init__(self):
        super().__init__()
        self._title = "initial"

    def title(self) -> str:
        return self._title

    def set_title(self, value: str) -> None:
        self._title = value

    def get_thread_name(self) -> str:
        return threading.current_thread().name


def test_proxy_calls_execute_on_main_thread(qtbot):
    widget = FakeWidget()
    invoker = MainThreadInvoker()
    proxy = QtProxy(widget, invoker)

    result = [None]
    error = [None]

    def worker():
        try:
            result[0] = proxy.get_thread_name()
        except Exception as e:
            error[0] = e

    t = threading.Thread(target=worker, name="test-worker")
    t.start()
    qtbot.waitUntil(lambda: not t.is_alive(), timeout=5000)
    t.join()

    assert error[0] is None
    assert result[0] == threading.main_thread().name


def test_proxy_method_returns_value(qtbot):
    widget = FakeWidget()
    invoker = MainThreadInvoker()
    proxy = QtProxy(widget, invoker)

    result = [None]

    def worker():
        result[0] = proxy.title()

    t = threading.Thread(target=worker)
    t.start()
    qtbot.waitUntil(lambda: not t.is_alive(), timeout=5000)
    t.join()

    assert result[0] == "initial"


def test_proxy_wraps_qobject_returns(qtbot):
    parent = FakeWidget()
    child = FakeWidget()
    child.setParent(parent)

    invoker = MainThreadInvoker()
    proxy = QtProxy(parent, invoker)

    result = [None]

    def worker():
        children = proxy.children()
        result[0] = children

    t = threading.Thread(target=worker)
    t.start()
    qtbot.waitUntil(lambda: not t.is_alive(), timeout=5000)
    t.join()

    assert isinstance(result[0], list)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd /var/home/jeandet/Documents/prog/jupyqt && uv run pytest tests/test_proxy.py -v`
Expected: FAIL — `ImportError`

- [ ] **Step 3: Implement QtProxy and MainThreadInvoker**

```python
# src/jupyqt/qt/proxy.py
"""Qt proxy layer for cross-thread access from kernel to Qt main thread."""

from __future__ import annotations

import threading
from typing import Any, Callable

from PySide6.QtCore import QCoreApplication, QEvent, QObject


class _InvokeEvent(QEvent):
    """Custom QEvent carrying a callable to execute on the main thread."""

    EVENT_TYPE = QEvent.Type(QEvent.registerEventType())

    def __init__(
        self,
        func: Callable,
        args: tuple,
        kwargs: dict,
        result_event: threading.Event,
        result_box: list,
    ):
        super().__init__(self.EVENT_TYPE)
        self.func = func
        self.args = args
        self.kwargs = kwargs
        self.result_event = result_event
        self.result_box = result_box  # [value, exception]


class _Receiver(QObject):
    """Receives _InvokeEvents and executes them on the main thread."""

    def event(self, event: QEvent) -> bool:
        if isinstance(event, _InvokeEvent):
            try:
                event.result_box[0] = event.func(*event.args, **event.kwargs)
            except Exception as e:
                event.result_box[1] = e
            finally:
                event.result_event.set()
            return True
        return super().event(event)


class MainThreadInvoker:
    """Invokes callables on the Qt main thread from any thread."""

    def __init__(self) -> None:
        self._receiver = _Receiver()

    def __call__(self, func: Callable, *args: Any, **kwargs: Any) -> Any:
        if threading.current_thread() is threading.main_thread():
            return func(*args, **kwargs)

        result_event = threading.Event()
        result_box: list = [None, None]
        event = _InvokeEvent(func, args, kwargs, result_event, result_box)
        QCoreApplication.postEvent(self._receiver, event)
        result_event.wait()

        if result_box[1] is not None:
            raise result_box[1]
        return result_box[0]


class QtProxy:
    """Wraps a QObject, dispatching all access to the Qt main thread."""

    def __init__(self, target: Any, invoker: MainThreadInvoker) -> None:
        object.__setattr__(self, "_target", target)
        object.__setattr__(self, "_invoke", invoker)

    def __getattr__(self, name: str) -> Any:
        invoke = object.__getattribute__(self, "_invoke")
        target = object.__getattribute__(self, "_target")

        # Marshal the getattr itself to the main thread
        attr = invoke(getattr, target, name)
        if callable(attr):

            def caller(*args: Any, **kwargs: Any) -> Any:
                result = invoke(attr, *args, **kwargs)
                if isinstance(result, QObject):
                    return QtProxy(result, invoke)
                return result

            return caller
        return attr

    def __repr__(self) -> str:
        target = object.__getattribute__(self, "_target")
        return f"QtProxy({target!r})"
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd /var/home/jeandet/Documents/prog/jupyqt && uv run pytest tests/test_proxy.py -v`
Expected: All 3 tests PASS.

- [ ] **Step 5: Commit**

```bash
git add src/jupyqt/qt/proxy.py tests/test_proxy.py
git commit -m "feat: add QtProxy for cross-thread Qt access"
```

---

## Task 10: JupyterLab widget

**Files:**
- Create: `src/jupyqt/qt/widget.py`

- [ ] **Step 1: Implement the widget**

```python
# src/jupyqt/qt/widget.py
"""JupyterLab widget embedding via QWebEngineView."""

from __future__ import annotations

from PySide6.QtCore import Qt, QUrl, Signal
from PySide6.QtGui import QDesktopServices
from PySide6.QtWebEngineCore import QWebEnginePage, QWebEngineProfile
from PySide6.QtWebEngineWidgets import QWebEngineView
from PySide6.QtWidgets import QLabel, QStackedWidget, QWidget


class JupyterLabWidget(QStackedWidget):
    """QWidget that embeds JupyterLab via QWebEngineView."""

    ready = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._url: str | None = None

        self._placeholder = QLabel("Loading JupyterLab...")
        self._placeholder.setAlignment(Qt.AlignCenter)
        self.addWidget(self._placeholder)

        self._profile = QWebEngineProfile("jupyqt", self)
        page = QWebEnginePage(self._profile, self)
        self._web_view = QWebEngineView(self)
        self._web_view.setPage(page)
        self._web_view.loadFinished.connect(self._on_load_finished)
        self.addWidget(self._web_view)

        self.setCurrentWidget(self._placeholder)

    def load(self, url: str) -> None:
        self._url = url
        self._web_view.load(QUrl(url))

    def open_in_browser(self) -> None:
        if self._url:
            QDesktopServices.openUrl(QUrl(self._url))

    def _on_load_finished(self, ok: bool) -> None:
        if ok:
            self.setCurrentWidget(self._web_view)
            self.ready.emit()
```

- [ ] **Step 2: Commit**

```bash
git add src/jupyqt/qt/widget.py
git commit -m "feat: add JupyterLabWidget with QWebEngineView"
```

---

## Task 11: Public API — EmbeddedJupyter

**Files:**
- Create: `src/jupyqt/api.py`
- Test: `tests/test_integration.py`

- [ ] **Step 1: Write integration tests**

```python
# tests/test_integration.py
from __future__ import annotations

import pytest

from jupyqt.api import EmbeddedJupyter


@pytest.fixture
def jupyter():
    j = EmbeddedJupyter()
    yield j
    j.shutdown()
    from IPython.core.interactiveshell import InteractiveShell
    InteractiveShell.clear_instance()


def test_shell_accessible_before_start(jupyter):
    assert jupyter.shell is not None
    jupyter.shell.push({"test_var": 42})
    assert jupyter.shell.user_ns["test_var"] == 42


def test_wrap_qt(jupyter, qtbot):
    from PySide6.QtCore import QObject
    from jupyqt.qt.proxy import QtProxy

    obj = QObject()
    proxy = jupyter.wrap_qt(obj)
    assert isinstance(proxy, QtProxy)


def test_push_before_start(jupyter):
    jupyter.push({"x": 10})
    assert jupyter.shell.user_ns["x"] == 10
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd /var/home/jeandet/Documents/prog/jupyqt && uv run pytest tests/test_integration.py -v`
Expected: FAIL — `ImportError`

- [ ] **Step 3: Implement EmbeddedJupyter**

```python
# src/jupyqt/api.py
"""Public API for jupyqt — embed JupyterLab in PySide6 applications."""

from __future__ import annotations

from typing import Any

from IPython.core.interactiveshell import InteractiveShell

from jupyqt.kernel.shell import create_shell
from jupyqt.kernel.thread import KernelThread
from jupyqt.qt.proxy import MainThreadInvoker, QtProxy


class EmbeddedJupyter:
    """Batteries-included JupyterLab embedding for PySide6 apps.

    Usage::

        jupyter = EmbeddedJupyter()
        jupyter.shell.push({"my_data": data})
        jupyter.start()
        layout.addWidget(jupyter.widget())
    """

    def __init__(self) -> None:
        self._shell = create_shell()
        self._kernel_thread = KernelThread(self._shell)
        self._invoker = MainThreadInvoker()
        self._launcher = None
        self._widget = None
        self._started = False

    @property
    def shell(self) -> InteractiveShell:
        return self._shell

    def push(self, variables: dict[str, Any]) -> None:
        """Thread-safe variable injection into the kernel namespace."""
        self._kernel_thread.push(variables)

    def wrap_qt(self, obj: Any) -> QtProxy:
        return QtProxy(obj, self._invoker)

    def widget(self):
        if self._widget is None:
            from jupyqt.qt.widget import JupyterLabWidget
            self._widget = JupyterLabWidget()
        if self._launcher is not None:
            self._widget.load(self._launcher.url)
        return self._widget

    def open_in_browser(self) -> None:
        if self._launcher is not None:
            from PySide6.QtCore import QUrl
            from PySide6.QtGui import QDesktopServices
            QDesktopServices.openUrl(QUrl(self._launcher.url))

    def start(self, port: int = 0) -> None:
        self._kernel_thread.start()
        from jupyqt.server.launcher import ServerLauncher
        self._launcher = ServerLauncher(self._shell, self._kernel_thread, port=port)
        self._launcher.start()
        self._started = True
        if self._widget is not None:
            self._widget.load(self._launcher.url)

    def shutdown(self) -> None:
        if self._launcher is not None:
            self._launcher.stop()
            self._launcher = None
        self._kernel_thread.stop()
        self._started = False
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd /var/home/jeandet/Documents/prog/jupyqt && uv run pytest tests/test_integration.py -v`
Expected: All 3 tests PASS.

- [ ] **Step 5: Commit**

```bash
git add src/jupyqt/api.py tests/test_integration.py
git commit -m "feat: add EmbeddedJupyter public API"
```

---

## Task 12: FPS module entry point

**Files:**
- Modify: `pyproject.toml`

- [ ] **Step 1: Add entry points to pyproject.toml**

```toml
[project.entry-points."fps.modules"]
jupyqt_kernel = "jupyqt.server.plugin:JupyQtKernelModule"

[project.entry-points."jupyverse.modules"]
jupyqt_kernel = "jupyqt.server.plugin:JupyQtKernelModule"
```

- [ ] **Step 2: Commit**

```bash
git add pyproject.toml
git commit -m "chore: add FPS module entry points for jupyverse discovery"
```

---

## Task 13: End-to-end smoke test

**Files:**
- Create: `examples/minimal_app.py`

- [ ] **Step 1: Write minimal example app**

```python
# examples/minimal_app.py
"""Minimal PySide6 app with embedded JupyterLab — smoke test."""

import sys

from PySide6.QtWidgets import QApplication, QMainWindow, QVBoxLayout, QWidget

from jupyqt import EmbeddedJupyter


def main():
    app = QApplication(sys.argv)
    window = QMainWindow()
    window.setWindowTitle("jupyqt smoke test")
    window.resize(1200, 800)

    jupyter = EmbeddedJupyter()
    jupyter.shell.push({"greeting": "Hello from jupyqt!"})
    jupyter.start()

    central = QWidget()
    layout = QVBoxLayout(central)
    layout.addWidget(jupyter.widget())
    window.setCentralWidget(central)

    window.show()

    ret = app.exec()
    jupyter.shutdown()
    sys.exit(ret)


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: Run manually**

Run: `cd /var/home/jeandet/Documents/prog/jupyqt && uv run python examples/minimal_app.py`
Expected: A window opens with JupyterLab. Type `greeting` in a cell → `'Hello from jupyqt!'`.

- [ ] **Step 3: Commit**

```bash
git add examples/minimal_app.py
git commit -m "feat: add minimal smoke test example app"
```

---

## Implementation Notes

### Task ordering and dependencies
- Tasks 1-6: Pure Python, no Qt — can be tested headless.
- Task 7: jupyverse integration — may need iterative refinement of fps API.
- Tasks 8: Server launcher — riskiest task, fps config may differ.
- Tasks 9-11: Qt required.
- Task 12: Just pyproject.toml.
- Task 13: Manual smoke test.

### Known risks
1. **fps configuration API:** `create_app()` and module registration may differ from docs. akernel's `fps_akernel_task` is the reference.
2. **Thread handoff of InteractiveShell:** Created on main thread, used on kernel thread. Should be fine since InteractiveShell doesn't use thread-local storage, but verify.
3. **`InteractiveShell.Completer.completions()`:** The API may vary across IPython versions. Test with IPython 8.x+.
4. **jupyverse version compatibility:** Pin to `>=0.14` and test against latest.
