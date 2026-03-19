# jupyqt

[![ci](https://github.com/SciQLop/jupyqt/workflows/ci/badge.svg)](https://github.com/SciQLop/jupyqt/actions?query=workflow%3Aci)
[![documentation](https://img.shields.io/badge/docs-zensical-FF9100.svg?style=flat)](https://SciQLop.github.io/jupyqt/)
[![pypi version](https://img.shields.io/pypi/v/jupyqt.svg)](https://pypi.org/project/jupyqt/)

Embed JupyterLab in PySide6 applications — no ipykernel, no ZMQ, no qasync.

## Features

- **Background-thread kernel** — cell execution never blocks the Qt event loop
- **Top-level `await`** — async/await works in notebook cells out of the box
- **Qt proxy** — safely manipulate Qt widgets from notebook code
- **jupyverse server** — full JupyterLab UI via QWebEngineView or external browser

## Installation

```bash
pip install jupyqt
```

With [`uv`](https://docs.astral.sh/uv/):

```bash
uv add jupyqt
```

## Quick start

```python
from PySide6.QtWidgets import QApplication, QMainWindow, QVBoxLayout, QWidget
from jupyqt import EmbeddedJupyter

app = QApplication([])
window = QMainWindow()

jupyter = EmbeddedJupyter()
jupyter.shell.push({"greeting": "Hello from jupyqt!"})
jupyter.start()

central = QWidget()
QVBoxLayout(central).addWidget(jupyter.widget())
window.setCentralWidget(central)
window.show()

app.exec()
jupyter.shutdown()
```

## Exposing Qt objects to the notebook

Wrap Qt objects with `wrap_qt()` so notebook cells can safely call methods on the main thread:

```python
jupyter.push({
    "window": jupyter.wrap_qt(main_window),
    "label": jupyter.wrap_qt(some_label),
    "do_stuff": my_function,
})
```

Then in a notebook cell:

```python
window.setWindowTitle("Controlled from Jupyter!")
label.setText("Updated from a cell")

import asyncio
for i in range(5):
    await asyncio.sleep(0.5)
    do_stuff()
```

## Examples

```bash
# Minimal smoke test
uv run python examples/minimal_app.py

# Full demo with exposed UI, counter widget, and demo notebook
uv run python examples/demo_app.py
```

## Architecture

```
┌─────────────────────────────────────┐
│  JupyterLabWidget (QWebEngineView)  │  ← Qt main thread
└───────────────┬─────────────────────┘
                │ HTTP / WebSocket
┌───────────────┴─────────────────────┐
│  jupyverse (fps + anyio)            │  ← server thread
└───────────────┬─────────────────────┘
                │ anyio MemoryObjectStreams
┌───────────────┴─────────────────────┐
│  Wire Protocol + InteractiveShell   │  ← kernel thread (asyncio)
└───────────────┬─────────────────────┘
                │ QtProxy (blocking invoke)
┌───────────────┴─────────────────────┐
│  Host Qt Application                │  ← Qt main thread
└─────────────────────────────────────┘
```

Three threads, no shared event loop, no reentrancy.
