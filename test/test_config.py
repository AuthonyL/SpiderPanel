import json
from pathlib import Path

import pytest

from SpiderPanel import config, rules, server
from SpiderPanel.wq_day import wq_day, wq_window


@pytest.fixture(autouse=True)
def isolated_config(monkeypatch, tmp_path):
    monkeypatch.setenv(rules.SPIDER_DIR_ENV, str(tmp_path / 'root'))
    monkeypatch.delenv('SPIDERPANEL_CONFIG', raising=False)


def write(path, **values):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(values), encoding='utf-8')
    return path


def test_lookup_order_flag_then_env_then_default(monkeypatch, tmp_path):
    default = write(tmp_path / 'root/config.json', daily_goal=6)
    env = write(tmp_path / 'env.json', daily_goal=7)
    flag = write(tmp_path / 'flag.json', daily_goal=9)
    assert config.load_config()['daily_goal'] == 6
    monkeypatch.setenv('SPIDERPANEL_CONFIG', str(env))
    assert config.load_config()['daily_goal'] == 7
    assert config.load_config(flag)['daily_goal'] == 9
    assert default.is_file()


def test_missing_default_is_empty_configuration(tmp_path):
    assert config.load_config() == {'progress_file': None, 'candidate_files': [],
                                    'thresholds': None, 'daily_goal': rules.DAILY_CANDIDATE_GOAL}
    assert not (tmp_path / 'root').exists()


def test_default_root_matches_log_root(monkeypatch):
    monkeypatch.delenv(rules.SPIDER_DIR_ENV)
    assert config.spider_root() == Path('~/.wq_spider').expanduser()


@pytest.mark.parametrize('selection', ['flag', 'env'])
@pytest.mark.parametrize('content', [None, '{', '[]', b'\xff'])
def test_explicit_missing_or_invalid_config_is_clean_startup_error(monkeypatch, tmp_path, capsys, selection, content):
    path = tmp_path / 'settings.json'
    if isinstance(content, bytes):
        path.write_bytes(content)
    elif content is not None:
        path.write_text(content)
    if selection == 'env':
        monkeypatch.setenv('SPIDERPANEL_CONFIG', str(path))
    argv = ['--config', str(path)] if selection == 'flag' else []
    assert server.main(argv) != 0
    captured = capsys.readouterr()
    assert '配置' in captured.err and 'Traceback' not in captured.err
    assert captured.out == ''


def test_relative_and_tilde_paths_are_resolved_from_config_directory(tmp_path):
    path = write(tmp_path / 'settings/config.json', progress_file='../progress.json',
                 candidate_files=['candidates.jsonl', '~/path/to/candidates.jsonl'], ignored='value')
    result = config.load_config(path)
    assert result['progress_file'] == tmp_path / 'progress.json'
    assert result['candidate_files'] == [path.parent / 'candidates.jsonl', Path('~/path/to/candidates.jsonl').expanduser()]
    assert 'ignored' not in result


@pytest.mark.parametrize('values', [{'daily_goal': True}, {'daily_goal': 0}, {'daily_goal': -1},
                                  {'daily_goal': 2.5}, {'progress_file': []}, {'candidate_files': 'ledger'},
                                  {'candidate_files': [1]}])
def test_invalid_config_fields_raise_configuration_error(tmp_path, values):
    with pytest.raises(config.ConfigError):
        config.load_config(write(tmp_path / 'settings.json', **values))


def test_cli_overrides_and_threshold_file(monkeypatch, tmp_path):
    from test_thresholds import value
    path = write(tmp_path / 'config.json', progress_file='old.json', candidate_files=['old.jsonl'],
                 thresholds=None, daily_goal=9)
    thresholds = write(tmp_path / 'thresholds.json', **value())
    monkeypatch.chdir(tmp_path)
    options = server.parse_args(['--config', str(path), '--progress-file', 'new.json',
                                 '--candidates-file', 'a.jsonl', '--candidates-file', '~/b.jsonl',
                                 '--thresholds', str(thresholds)])
    result = config.configure(options)
    assert result['progress_file'] == tmp_path / 'new.json'
    assert result['candidate_files'] == [tmp_path / 'a.jsonl', Path('~/b.jsonl').expanduser()]
    assert result['thresholds'] == value() and result['daily_goal'] == 9


def test_invalid_threshold_file_is_clean_startup_error(tmp_path, capsys):
    path = tmp_path / 'thresholds.json'
    path.write_text('{')
    assert server.main(['--thresholds', str(path)]) != 0
    assert '配置' in capsys.readouterr().err


@pytest.mark.parametrize("demo", [False, True])
def test_main_passes_configuration_and_daily_goal_survives_rollover(monkeypatch, tmp_path, demo):
    path = write(tmp_path / 'config.json', daily_goal=9, progress_file='progress.json', candidate_files=['ledger.jsonl'])
    monkeypatch.setattr(server.tempfile, "mkdtemp", lambda **kwargs: str(tmp_path / "demo"))
    observed = []
    real_runtime = server.PanelRuntime
    def runtime(root, **kwargs):
        observed.append(kwargs)
        instance = real_runtime(root, **kwargs)
        assert instance.snapshot()['goal']['target'] == 9
        instance.close()
        return instance
    def unavailable(*args, **kwargs):
        raise OSError('测试不启动监听')
    monkeypatch.setattr(server, 'PanelRuntime', runtime)
    monkeypatch.setattr(server, 'make_server', unavailable)
    assert server.main(['--config', str(path)] + (['--demo'] if demo else [])) == 1
    assert observed[0]['progress_path'] == tmp_path / 'progress.json'
    assert observed[0]['candidate_paths'] == [tmp_path / 'ledger.jsonl']
    now = [wq_window(wq_day()).start + 60]
    instance = real_runtime(tmp_path, clock=lambda: now[0], daily_goal=9)
    try:
        assert instance.snapshot()['goal']['target'] == 9
        now[0] = instance.window.end + 1
        instance.poll()
        assert instance.snapshot()['goal']['target'] == 9
    finally:
        instance.close()


def test_daily_goal_scales_candidate_and_review_cards(tmp_path):
    from test_candidates import pipeline
    from test_state import DAY, TS
    pipeline(tmp_path)
    runtime = server.PanelRuntime(tmp_path, day=DAY, clock=lambda: TS+10, daily_goal=9)
    try:
        runtime.poll()
        snapshot = runtime.snapshot()
        assert snapshot['goal'] == {'candidates': 1, 'target': 9}
        for card in snapshot['cards']:
            if card['key'] in ('candidate', 'review'):
                assert card['progress'] == pytest.approx(1/9)
    finally:
        runtime.close()
