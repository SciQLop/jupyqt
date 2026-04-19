"""Comm protocol support for jupyqt — enables ipywidgets.

Provides a standalone Comm/CommManager that publishes messages via the
protocol's iopub channel. When the ``comm`` package is installed (required
by ipywidgets >= 8), monkey-patches it to use our implementation.
"""

from __future__ import annotations

import uuid
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from collections.abc import Callable

# Module-level state, set by KernelProtocol during init/execution
_publish_fn: Callable[..., None] | None = None
_current_parent: dict[str, Any] = {}


def set_publish_fn(fn: Callable[..., None] | None) -> None:
    """Set the callback used to publish comm iopub messages."""
    global _publish_fn  # noqa: PLW0603
    _publish_fn = fn


def set_current_parent(parent: dict[str, Any]) -> None:
    """Set the current parent message (for iopub message threading)."""
    global _current_parent  # noqa: PLW0603
    _current_parent = parent


class Comm:
    """Minimal Comm implementation compatible with ipywidgets."""

    def __init__(
        self,
        target_name: str = "",
        data: dict[str, Any] | None = None,  # noqa: ARG002
        metadata: dict[str, Any] | None = None,  # noqa: ARG002
        buffers: list[bytes] | None = None,  # noqa: ARG002
        comm_id: str | None = None,
        target_module: str | None = None,
        **_kwargs: Any,
    ) -> None:
        """Initialise a Comm with target name, optional ID and module."""
        self.comm_id = comm_id or str(uuid.uuid4())
        self.target_name = target_name
        self.target_module = target_module
        self._msg_callbacks: list[Callable] = []
        self._close_callbacks: list[Callable] = []
        self._open = False

    def open(
        self,
        data: dict[str, Any] | None = None,
        metadata: dict[str, Any] | None = None,
        buffers: list[bytes] | None = None,
    ) -> None:
        """Open the comm, publishing comm_open on iopub."""
        get_comm_manager().register_comm(self)
        self._open = True
        self._publish_msg(
            "comm_open",
            data=data,
            metadata=metadata,
            buffers=buffers,
            target_name=self.target_name,
            target_module=self.target_module,
        )

    def send(
        self,
        data: dict[str, Any] | None = None,
        metadata: dict[str, Any] | None = None,
        buffers: list[bytes] | None = None,
    ) -> None:
        """Send a message on this comm."""
        self._publish_msg("comm_msg", data=data, metadata=metadata, buffers=buffers)

    def close(
        self,
        data: dict[str, Any] | None = None,
        metadata: dict[str, Any] | None = None,
        buffers: list[bytes] | None = None,
    ) -> None:
        """Close the comm."""
        self._publish_msg("comm_close", data=data, metadata=metadata, buffers=buffers)
        self._open = False
        get_comm_manager().unregister_comm(self.comm_id)

    def on_msg(self, callback: Callable) -> None:
        """Register a handler for incoming messages."""
        self._msg_callbacks.append(callback)

    def on_close(self, callback: Callable) -> None:
        """Register a handler for comm close."""
        self._close_callbacks.append(callback)

    def handle_msg(self, msg: dict[str, Any]) -> None:
        """Dispatch an incoming message to registered callbacks."""
        for cb in self._msg_callbacks:
            cb(msg)

    def handle_close(self, msg: dict[str, Any]) -> None:
        """Dispatch a close event to registered callbacks."""
        for cb in self._close_callbacks:
            cb(msg)

    def _publish_msg(
        self,
        msg_type: str,
        data: Any = None,
        metadata: dict[str, Any] | None = None,
        buffers: list[bytes] | None = None,
        **keys: Any,
    ) -> None:
        if _publish_fn is None:
            return
        content: dict[str, Any] = {
            "comm_id": self.comm_id,
            "data": data or {},
            **{k: v for k, v in keys.items() if v is not None},
        }
        _publish_fn(msg_type, content, _current_parent, metadata=metadata, buffers=buffers)


class CommManager:
    """Tracks open comms and dispatches incoming messages."""

    def __init__(self) -> None:
        """Initialise empty comm and target registries."""
        self._comms: dict[str, Comm] = {}
        self._targets: dict[str, Callable] = {}

    def register_target(self, target_name: str, handler: Callable) -> None:
        """Register a handler for the given target name."""
        self._targets[target_name] = handler

    def unregister_target(self, target_name: str) -> None:
        """Remove the handler for the given target name."""
        self._targets.pop(target_name, None)

    def register_comm(self, comm: Comm) -> None:
        """Track an open comm by its ID."""
        self._comms[comm.comm_id] = comm

    def unregister_comm(self, comm_id: str) -> None:
        """Remove a comm from the registry."""
        self._comms.pop(comm_id, None)

    def get_comm(self, comm_id: str) -> Comm | None:
        """Return the comm for the given ID, or None."""
        return self._comms.get(comm_id)

    def new_comm(
        self,
        target_name: str = "",
        data: dict[str, Any] | None = None,
        metadata: dict[str, Any] | None = None,
        comm_id: str | None = None,
        buffers: list[bytes] | None = None,
        **kwargs: Any,
    ) -> Comm:
        """Create, register, and open a new Comm."""
        comm = Comm(target_name=target_name, comm_id=comm_id, **kwargs)
        self.register_comm(comm)
        comm.open(data=data, metadata=metadata, buffers=buffers)
        return comm

    def comm_info(self, target_name: str | None = None) -> dict[str, dict[str, str]]:
        """Return info dict for open comms, optionally filtered by target."""
        return {
            cid: {"target_name": c.target_name}
            for cid, c in self._comms.items()
            if target_name is None or c.target_name == target_name
        }

    def handle_comm_open(self, msg: dict[str, Any]) -> None:
        """Handle a comm_open from the frontend."""
        content = msg["content"]
        target_name = content["target_name"]
        comm_id = content["comm_id"]
        handler = self._targets.get(target_name)
        if handler is not None:
            comm = Comm(target_name=target_name, comm_id=comm_id)
            comm._open = True
            self.register_comm(comm)
            handler(comm, msg)

    def handle_comm_msg(self, msg: dict[str, Any]) -> None:
        """Route an incoming comm_msg to the target Comm."""
        comm = self.get_comm(msg["content"]["comm_id"])
        if comm is not None:
            comm.handle_msg(msg)

    def handle_comm_close(self, msg: dict[str, Any]) -> None:
        """Route a comm_close and remove the Comm."""
        comm_id = msg["content"]["comm_id"]
        comm = self.get_comm(comm_id)
        if comm is not None:
            comm.handle_close(msg)
            self.unregister_comm(comm_id)


_comm_manager: CommManager | None = None


def get_comm_manager() -> CommManager:
    """Return the global CommManager singleton."""
    global _comm_manager  # noqa: PLW0603
    if _comm_manager is None:
        _comm_manager = CommManager()
    return _comm_manager


def create_comm(**kwargs: Any) -> Comm:
    """Create and open a new Comm via the global CommManager."""
    return get_comm_manager().new_comm(**kwargs)


def install() -> None:
    """Monkey-patch the ``comm`` package to use jupyqt's implementation."""
    try:
        import comm  # noqa: PLC0415  # ty: ignore[unresolved-import]

        comm.create_comm = create_comm
        comm.get_comm_manager = get_comm_manager
    except ImportError:
        pass
