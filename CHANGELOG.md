# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](http://keepachangelog.com/en/1.0.0/)
and this project adheres to [Semantic Versioning](http://semver.org/spec/v2.0.0.html).

<!-- insertion marker -->
## [0.5.2](https://github.com/jeandet/jupyqt/releases/tag/0.5.2) - 2026-04-13

<small>[Compare with 0.5.1](https://github.com/jeandet/jupyqt/compare/0.5.1...0.5.2)</small>

### Bug Fixes

- use default-value Depends in /files/{path} route ([bfbbd9e](https://github.com/jeandet/jupyqt/commit/bfbbd9ecf921ce28f1b3092ecd8e2166b2df8ba8) by Alexis Jeandet). Co-Authored-By: Claude Opus 4.6 <noreply@anthropic.com>

## [0.5.1](https://github.com/jeandet/jupyqt/releases/tag/0.5.1) - 2026-04-13

<small>[Compare with 0.5.0](https://github.com/jeandet/jupyqt/compare/0.5.0...0.5.1)</small>

### Bug Fixes

- patch fps-contents gaps for uploads, copy-paste, and downloads ([6a0e2ef](https://github.com/jeandet/jupyqt/commit/6a0e2ef1b39eae77512dd4c40e56ff804cfcbf77) by Alexis Jeandet). Co-Authored-By: Claude Opus 4.6 <noreply@anthropic.com>

## [0.5.0](https://github.com/SciQLop/jupyqt/releases/tag/0.5.0) - 2026-04-08

### Added

- File download support in the embedded JupyterLab webview (notebook export, etc.) via QWebEngineProfile download hook with a save-file dialog

### Fixed

- Server startup crash when `fps_nbconvert` is installed — exclude `nbconvert` module to avoid pulling in tornado/SSL

## [0.4.1](https://github.com/SciQLop/jupyqt/releases/tag/0.4.1) - 2026-04-05

### Fixed

- Crash on macOS when creating a QWebEngineProfile — use the default profile instead of constructing a new one, which triggers a fatal assertion in Chromium's ProfileAdapter on Qt 6.10

## [0.4.0](https://github.com/SciQLop/jupyqt/releases/tag/0.4.0) - 2026-03-25

### Added

- Kernel interrupt support (`interrupt_request` handler)
- `input()` / stdin support for interactive prompts
- Non-blocking kernel dispatch (execute requests no longer block the Qt event loop)
- Auto-create python3 kernel spec so JupyterLab finds a kernel on all OSes, with fallback to user Jupyter data dir when `sys.prefix` isn't writable

### Fixed

- Server startup timeout now raises `TimeoutError` instead of silently proceeding
- Server thread restores working directory after shutdown (`os.chdir` is process-wide)
- Bumped `PySide6>=6.8` (6.5 segfaults on Python 3.12+)
- Bumped `ipython>=8.14` / `>=9.2` (Python 3.14 compatibility)
- CI: install `libegl1` on Linux, use `QT_QPA_PLATFORM=offscreen`, drop Python 3.15-dev
- Resolved pre-existing ruff lint and ty type checker errors

## [0.3.1](https://github.com/SciQLop/jupyqt/releases/tag/0.3.1) - 2026-03-19

### Fixed

- `NotImplementedError: Implement enable_gui in a subclass` when switching matplotlib backends
- All repository URLs now point to the SciQLop org instead of personal fork

## [0.3.0](https://github.com/SciQLop/jupyqt/releases/tag/0.3.0) - 2026-03-19

### Added

- Rich display support: `display()` calls produce `display_data` iopub messages with base64-encoded binary MIME types
- Matplotlib inline backend auto-activation with backend-aware flush hook (switching to Qt backend stops inline rendering from closing figures)
- Matplotlib Qt backend (`module://jupyqt.matplotlib.backend`): native Qt figure windows with zoom/pan toolbar, created on the main thread via `MainThreadInvoker`
- ipywidgets/comm protocol support: `comm_open`, `comm_msg`, `comm_close`, `comm_info_request` handlers enabling interactive widgets
- Example apps and notebooks for matplotlib and ipywidgets

### Fixed

- QtProxy now recursively wraps non-callable QObject attributes
- Matplotlib Qt backend lifecycle: proper Gcf cleanup on window close, guarded destroy() against deleted C++ objects

## [0.2.0](https://github.com/SciQLop/jupyqt/releases/tag/0.2.0) - 2026-03-19

### Added

- `cwd` parameter on `EmbeddedJupyter` to set the JupyterLab file browser root directory
- Lazy server start — `start()` only starts the kernel thread; the jupyverse server launches on first `widget()` or `open_in_browser()` call

### Fixed

- All ruff lint errors resolved across source and test files
- Release workflow only triggers on tag pushes (no more spurious failures)
- Documentation deployment added to release workflow

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
