import errno
import subprocess
from types import SimpleNamespace

import pytest

from SpiderPanel import processes


@pytest.mark.parametrize("command,expected", [
    ('claude --settings /home/demo/.ccs/Kimi2.settings.json', 'Kimi2'),
    ('claude --settings="/home/Demo User/.ccs/My Agent.settings.json"', 'My Agent'),
    ('claude --settings "/home/Demo User/.ccs/Case.settings.json"', 'Case'),
    ('node @openai/codex/codex/app-server-daemon --settings=/tmp/CCS.settings.json claude', 'CCS'),
    ('node @openai/codex/codex/app-server-daemon claude', 'codex'),
    ('node /usr/local/lib/node_modules/@openai/codex/bin/codex.js --resume', 'codex'),
    ('node @openai/codex --resume', 'codex'),
    ('node /opt/codex-cli.js --resume', 'codex'),
    ('codex --resume', 'codex'),
    ('/usr/local/bin/codex --resume', 'codex'),
    ('app-server-daemon --port 1234', 'codex'),
    ('/Applications/Codex.app/Contents/Resources/app-server-daemon', 'codex'),
    ('/usr/local/bin/claude --resume', 'claude'),
    ('python tool_server.py', None),
    ('', None),
    (None, None),
])
def test_parse_agent_priority_and_quoted_settings(command, expected):
    assert processes.parse_agent(command) == expected


def test_parse_agent_bounds_ccs_name_without_changing_case():
    assert processes.parse_agent('claude --settings /tmp/' + 'Ab' * 100 + '.settings.json') == 'Ab' * 60


@pytest.mark.parametrize("command,expected", [
    ('claude /tmp/Other.settings.json', 'claude'),
    ('codex /tmp/Other.settings.json', 'codex'),
    ('python /tmp/Other.settings.json', None),
    ('claude --settings /tmp/Right.settings.json /tmp/Other.settings.json', 'Right'),
    ('claude /tmp/Other.settings.json --settings="/tmp/Right Agent.settings.json"', 'Right Agent'),
    ('claude --settings=/tmp/config.json /tmp/Other.settings.json', 'claude'),
    ('claude --settings', 'claude'),
])
def test_only_settings_flags_supply_profile_name(command, expected):
    assert processes.parse_agent(command) == expected


@pytest.mark.parametrize("pid", [None, '', '12', 0, -1, 1.5, True, 2 ** 100])
def test_process_alive_rejects_invalid_pid_without_signalling(monkeypatch, pid):
    def kill(*args):
        pytest.fail('invalid PIDs must not be signalled')
    monkeypatch.setattr(processes.os, 'kill', kill)
    assert processes.process_alive(pid) is False


@pytest.mark.parametrize("error,expected", [
    (None, True),
    (PermissionError(errno.EPERM, 'denied'), True),
    (ProcessLookupError(errno.ESRCH, 'gone'), False),
    (OSError(errno.ESRCH, 'gone'), False),
    (OSError(errno.EIO, 'unknown'), True),
])
def test_process_alive_checks_signal_zero_conservatively(monkeypatch, error, expected):
    def kill(pid, signal):
        assert (pid, signal) == (123, 0)
        if error:
            raise error
    monkeypatch.setattr(processes.os, 'kill', kill)
    assert processes.process_alive(123) is expected


@pytest.mark.parametrize("helper,field,output,expected", [
    (processes.parent_pid, 'ppid=', '  42\n', 42),
    (processes.parent_agent, 'command=', 'claude --settings=/tmp/Zed.settings.json\n', 'Zed'),
])
def test_ps_queries_use_argument_list_timeout_and_captured_output(monkeypatch, helper, field, output, expected):
    def run(args, **kwargs):
        assert args == ['ps', '-o', field, '-p', '123']
        assert kwargs == {'capture_output': True, 'text': True, 'timeout': 1, 'check': False}
        return subprocess.CompletedProcess(args, 0, output, '')
    monkeypatch.setattr(processes.subprocess, 'run', run)
    assert helper(123) == expected


@pytest.mark.parametrize("helper", [processes.parent_pid, processes.parent_agent])
@pytest.mark.parametrize("response", [
    SimpleNamespace(returncode=1, stdout='42', stderr='private command'),
    SimpleNamespace(returncode=0, stdout='', stderr=''),
    subprocess.TimeoutExpired(['ps'], 1, output='secret', stderr='secret'),
    FileNotFoundError('ps unavailable'),
    PermissionError('denied'),
])
def test_ps_failures_return_none_without_output(monkeypatch, capsys, helper, response):
    def run(*args, **kwargs):
        if isinstance(response, Exception):
            raise response
        return response
    monkeypatch.setattr(processes.subprocess, 'run', run)
    assert helper(123) is None
    captured = capsys.readouterr()
    assert captured.out == captured.err == ''


@pytest.mark.parametrize("output", ['abc', '0', '-2', '42\n99'])
def test_parent_pid_rejects_invalid_ps_output(monkeypatch, output):
    monkeypatch.setattr(processes.subprocess, 'run', lambda *a, **kw: subprocess.CompletedProcess(a, 0, output, ''))
    assert processes.parent_pid(123) is None


@pytest.mark.parametrize("helper", [processes.parent_pid, processes.parent_agent])
@pytest.mark.parametrize("pid", [None, '', '12', 0, -1, 1.5, True])
def test_parent_queries_skip_invalid_pid(monkeypatch, helper, pid):
    def run(*args, **kwargs):
        pytest.fail('invalid PIDs must not invoke ps')
    monkeypatch.setattr(processes.subprocess, 'run', run)
    assert helper(pid) is None
