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
