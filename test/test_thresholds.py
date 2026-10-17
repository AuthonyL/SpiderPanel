import copy

import pytest

from SpiderPanel.server import PanelRuntime
from SpiderPanel.thresholds import load_thresholds


def value():
    return {'hard': [{'key': 'sample_limit', 'value': 17, 'note': '虚构限制'}],
            'soft': {'tier_sharpe': 2.75, 'standard': {'sharpe': 1.75, 'fitness': 1.15},
                     'high': {'sharpe': 2.75, 'fitness': 1.65}}, 'source': ['虚构配置']}


def test_valid_thresholds_are_an_independent_clean_copy():
    original = value()
    original['ignored'] = 'extra'
    original['hard'][0]['ignored'] = 'extra'
    result = load_thresholds(original)
    assert result == value()
    result['soft']['standard']['sharpe'] = 9
    result['hard'][0]['value'] = 99
    result['source'].append('changed')
    assert original['soft']['standard']['sharpe'] == 1.75
    assert original['hard'][0]['value'] == 17
    assert original['source'] == ['虚构配置']


@pytest.mark.parametrize('bad', [None, [], {}, {'hard': [], 'soft': {}}, 'settings'])
def test_missing_or_invalid_thresholds_return_null(bad):
    assert load_thresholds(bad) is None


@pytest.mark.parametrize('part', ['hard', 'key', 'note', 'number', 'tier', 'standard', 'high', 'missing_metric'])
def test_invalid_threshold_fields_return_null(part):
    sample = copy.deepcopy(value())
    if part == 'hard':
        sample['hard'] = {}
    elif part in ('key', 'note'):
        sample['hard'][0][part] = 7
    elif part == 'number':
        sample['hard'][0]['value'] = True
    elif part == 'tier':
        sample['soft']['tier_sharpe'] = float('nan')
    elif part == 'missing_metric':
        del sample['soft']['standard']['fitness']
    else:
        sample['soft'][part]['sharpe'] = float('inf')
    assert load_thresholds(sample) is None


@pytest.mark.parametrize('thresholds', [value(), None, {'hard': []}])
def test_configured_thresholds_reach_runtime_snapshot_and_rollover(tmp_path, thresholds):
    now = [1780000000]
    runtime = PanelRuntime(tmp_path, clock=lambda: now[0], thresholds=thresholds)
    try:
        assert runtime.snapshot()['thresholds'] == load_thresholds(thresholds)
        now[0] = runtime.window.end + 1
        runtime.poll()
        assert runtime.snapshot()['thresholds'] == load_thresholds(thresholds)
    finally:
        runtime.close()


@pytest.mark.parametrize('field', ['hard_key', 'hard_note', 'tier_key', 'source', 'source_list'])
def test_unencodable_threshold_strings_yield_null_snapshot(tmp_path, field):
    sample = value()
    if field.startswith('hard_'):
        sample['hard'][0][field[5:]] = '\ud800'
    elif field == 'tier_key':
        sample['soft']['standard']['\ud800'] = 1
    else:
        sample['source'] = '\ud800' if field == 'source' else ['\ud800']
    assert load_thresholds(sample) is None
    runtime = PanelRuntime(tmp_path, thresholds=sample)
    try:
        assert runtime.snapshot()['thresholds'] is None
    finally:
        runtime.close()
