# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](http://keepachangelog.com/en/1.0.0/)
and this project adheres to [Semantic Versioning](http://semver.org/spec/v2.0.0.html).

<!-- insertion marker -->
## [0.1.0](https://github.com/SciQLop/jupyqt/releases/tag/0.1.0) - 2026-03-18

### Added

- Embed JupyterLab in PySide6 applications — no ipykernel, no ZMQ, no qasync
- Background-thread kernel with IPython InteractiveShell and asyncio event loop
- Jupyter wire protocol handler over anyio memory streams (execute, complete, inspect, is_complete, history, shutdown)
- jupyverse kernel plugin with FPS module integration
- Server launcher managing jupyverse lifecycle in a background thread
- QtProxy for safe cross-thread access to Qt objects from notebook cells
- JupyterLabWidget (QWebEngineView) with loading placeholder and ready signal
- EmbeddedJupyter public API: `push()`, `wrap_qt()`, `widget()`, `start()`, `shutdown()`
- Top-level `await` support in notebook cells via `run_cell_async()`
- Minimal smoke test example (`examples/minimal_app.py`)
- Demo app with exposed UI widgets and pre-loaded notebook (`examples/demo_app.py`)

### Fixed

- All shell access (complete, inspect, is_complete) dispatched to kernel thread
- IPython completions wrapped in `provisionalcompleter()` context manager
