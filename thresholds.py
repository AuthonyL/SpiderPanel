"""校验独立配置中的展示阈值。"""

import math


def _number(value):
    try:
        return type(value) in (int, float) and math.isfinite(value)
    except OverflowError:
        return False


def _text(value):
    if not isinstance(value, str):
        return False
    try:
        value.encode("utf-8")
        return True
    except UnicodeError:
        return False


def load_thresholds(value=None):
    if not isinstance(value, dict):
        return None
    hard, soft = value.get("hard"), value.get("soft")
    if not isinstance(hard, list) or not isinstance(soft, dict) or not _number(soft.get("tier_sharpe")):
        return None
    cleaned = []
    for row in hard:
        if not isinstance(row, dict) or not all(_text(row.get(key)) for key in ("key", "note")) or not _number(row.get("value")):
            return None
        cleaned.append({key: row[key] for key in ("key", "value", "note")})
    tiers = {}
    for key in ("standard", "high"):
        tier = soft.get(key)
        if not isinstance(tier, dict) or not all(metric in tier for metric in ("sharpe", "fitness")) or not all(_text(k) and _number(v) for k, v in tier.items()):
            return None
        tiers[key] = dict(tier)
    result = {"hard": cleaned, "soft": {"tier_sharpe": soft["tier_sharpe"], **tiers}}
    source = value.get("source")
    if source is not None:
        if _text(source):
            result["source"] = source
        elif isinstance(source, list) and all(_text(item) for item in source):
            result["source"] = list(source)
        else:
            return None
    return result
