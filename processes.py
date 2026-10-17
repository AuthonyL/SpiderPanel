"""Small, best-effort process queries used by tracker and panel state."""

import errno
import os
import shlex
import subprocess


def parse_agent(command: str) -> str | None:
    """Identify a CCS settings name before falling back to the agent type."""
    if not isinstance(command, str):
        return None
    try:
        arguments = shlex.split(command)
    except ValueError:
        arguments = command.split()
    suffix = ".settings.json"
    for index, argument in enumerate(arguments):
        if argument == "--settings" and index + 1 < len(arguments):
            path = arguments[index + 1]
        elif argument.startswith("--settings="):
            path = argument.partition("=")[2]
        else:
            continue
        name = path.rsplit("/", 1)[-1]
        if name.endswith(suffix) and len(name) > len(suffix):
            return name[:-len(suffix)][:120]
    if "codex" in command or "app-server-daemon" in command:
        return "codex"
    if "claude" in command.lower():
        return "claude"
    return None


def _valid_pid(pid):
    return isinstance(pid, int) and not isinstance(pid, bool) and 0 < pid <= 2 ** 31 - 1


def process_alive(pid: int) -> bool:
    """Treat permission errors and unknown OS errors as possibly alive."""
    if not _valid_pid(pid):
        return False
    try:
        os.kill(pid, 0)
    except PermissionError:
        return True
    except OSError as error:
        return error.errno != errno.ESRCH
    except (OverflowError, TypeError, ValueError):
        return False
    return True


def _ps_value(pid, field):
    if not _valid_pid(pid):
        return None
    try:
        result = subprocess.run(
            ["ps", "-o", field, "-p", str(pid)],
            capture_output=True, text=True, timeout=1, check=False,
        )
        if result.returncode != 0:
            return None
        return result.stdout.strip() or None
    except Exception:
        return None


def parent_pid(pid: int) -> int | None:
    """Return a positive parent PID, or None when ps cannot resolve it."""
    value = _ps_value(pid, "ppid=")
    try:
        ppid = int(value)
        return ppid if _valid_pid(ppid) else None
    except (TypeError, ValueError):
        return None


def parent_agent(ppid: int) -> str | None:
    """Return the agent inferred from the parent command, without output."""
    return parse_agent(_ps_value(ppid, "command="))
