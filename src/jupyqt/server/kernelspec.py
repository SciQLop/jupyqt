"""jupyqt's single kernel, as the only one JupyterLab is offered.

jupyverse lists every kernelspec found in the Jupyter data dirs, but in jupyqt
any session runs the in-process kernel, whatever kernel it names (fps-kernels
needs no kernel.json for it). Listing the others only makes Lab ask which one
to start. So /api/kernelspecs serves jupyqt's spec from memory, and notebooks
naming another kernel, or none, are served as jupyqt-kernel notebooks.
"""

from __future__ import annotations

import json
import logging
import sys
from pathlib import Path
from typing import Any

from fps import Module
from jupyverse_kernels import Kernels

log = logging.getLogger(__name__)

KERNEL_NAME = "python3"
_OLD_JUPYQT_ARGV_TAIL = ["-m", "jupyqt", "-f", "{connection_file}"]
KERNELSPEC: dict[str, Any] = {
    "argv": [],
    "display_name": "Python 3 (jupyqt)",
    "language": "python",
    "metadata": {},
}


async def jupyqt_kernelspecs(*_args: Any) -> dict[str, Any]:
    """The /api/kernelspecs reply: jupyqt's kernel only, as the default."""
    entry = {"name": KERNEL_NAME, "spec": KERNELSPEC, "resources": {}}
    return {"default": KERNEL_NAME, "kernelspecs": {KERNEL_NAME: entry}}


def with_jupyqt_kernel(notebook: dict) -> dict:
    """Return *notebook* naming jupyqt's kernel, unchanged if it already does.

    Lab only starts a kernel without asking when the notebook names one it is
    offered. Lab writes the running kernel's spec back on save anyway.
    """
    metadata = notebook.get("metadata", {})
    if metadata.get("kernelspec", {}).get("name") == KERNEL_NAME:
        return notebook
    kernelspec = {"name": KERNEL_NAME, **{k: KERNELSPEC[k] for k in ("display_name", "language")}}
    return {**notebook, "metadata": {**metadata, "kernelspec": kernelspec}}


def is_old_jupyqt_kernelspec(text: str) -> bool:
    """Whether *text* is exactly the python3 kernel.json an older jupyqt wrote.

    jupyqt 0.4.0 to 0.6.6 wrote ``json.dumps(spec, indent=1)`` plus a newline, with these
    three keys and ``argv[0]`` set to ``sys.executable`` (an unreleased branch
    used ``"python3"``). Anything else, even reformatted, is someone else's.
    It wrote in text mode, so *text* must be read in text mode too: on Windows
    the file has CRLF line endings.
    """
    try:
        spec = json.loads(text)
    except ValueError:
        return False
    return (
        isinstance(spec, dict)
        and list(spec) == ["argv", "display_name", "language"]
        and spec["display_name"] == "Python 3 (jupyqt)"
        and spec["language"] == "python"
        and isinstance(spec["argv"], list)
        and len(spec["argv"]) == 1 + len(_OLD_JUPYQT_ARGV_TAIL)
        and isinstance(spec["argv"][0], str)
        and spec["argv"][1:] == _OLD_JUPYQT_ARGV_TAIL
        and text == json.dumps(spec, indent=1) + "\n"
    )


def remove_old_jupyqt_kernelspec(kernel_dir: Path) -> None:
    """Delete *kernel_dir*/kernel.json if an older jupyqt wrote it, then the folder if empty.

    Symlinks, for the folder or the file, are never followed or removed.
    """
    kernel_json = kernel_dir / "kernel.json"
    if kernel_dir.is_symlink() or kernel_json.is_symlink() or not kernel_json.is_file():
        return
    try:
        if not is_old_jupyqt_kernelspec(kernel_json.read_text(encoding="utf-8")):
            return
        kernel_json.unlink()
        log.info("Removed the broken kernelspec an older jupyqt wrote: %s", kernel_json)
        if not any(kernel_dir.iterdir()):
            kernel_dir.rmdir()
    except (OSError, UnicodeDecodeError):
        log.debug("Could not clean up %s", kernel_json, exc_info=True)


def _old_jupyqt_kernel_dirs() -> list[Path]:
    """The two folders older jupyqt wrote its python3 kernelspec to."""
    dirs = [Path(sys.prefix) / "share" / "jupyter" / "kernels" / KERNEL_NAME]
    try:
        from jupyter_core.paths import jupyter_data_dir  # noqa: PLC0415
    except ImportError:
        return dirs
    return [*dirs, Path(jupyter_data_dir()) / "kernels" / KERNEL_NAME]


def remove_old_jupyqt_kernelspecs() -> None:
    """Remove the broken kernelspecs older jupyqt left behind, where it wrote them."""
    for kernel_dir in _old_jupyqt_kernel_dirs():
        remove_old_jupyqt_kernelspec(kernel_dir)


class JupyQtKernelspecsModule(Module):
    """Makes fps-kernels list jupyqt's kernel only."""

    async def prepare(self) -> None:
        """Replace the kernelspec listing; its route calls ``self.get_kernelspecs`` at request time."""
        kernels = await self.get(Kernels)
        # simplify: overrides one method on the fps-kernels instance instead of
        # copying its whole Module to construct a subclass.
        kernels.get_kernelspecs = jupyqt_kernelspecs  # ty: ignore[invalid-assignment]
