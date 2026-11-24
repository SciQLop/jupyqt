"""jupyqt's single kernel, as the only one JupyterLab is offered.

jupyverse lists every kernelspec found in the Jupyter data dirs, but in jupyqt
any session runs the in-process kernel, whatever kernel it names (fps-kernels
needs no kernel.json for it). Listing the others only makes Lab ask which one
to start. So /api/kernelspecs serves jupyqt's spec from memory, and notebooks
naming another kernel, or none, are served as jupyqt-kernel notebooks.
"""

from __future__ import annotations

from typing import Any

from fps import Module
from jupyverse_kernels import Kernels

KERNEL_NAME = "python3"
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


class JupyQtKernelspecsModule(Module):
    """Makes fps-kernels list jupyqt's kernel only."""

    async def prepare(self) -> None:
        """Replace the kernelspec listing; its route calls ``self.get_kernelspecs`` at request time."""
        kernels = await self.get(Kernels)
        # simplify: overrides one method on the fps-kernels instance instead of
        # copying its whole Module to construct a subclass.
        kernels.get_kernelspecs = jupyqt_kernelspecs  # ty: ignore[invalid-assignment]
