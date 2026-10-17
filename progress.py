"""Read the simulator's registry as data; never import or lock its writer."""

import json
import math
from pathlib import Path
from urllib.parse import urlsplit


EMPTY_PROGRESS = {"progress": None, "children_done": None, "children_total": None}


def load_progress(path):
    try:
        registry = json.loads(Path(path).read_text(encoding="utf-8"))
        if not isinstance(registry, dict) or registry.get("version") != 1 or not isinstance(registry.get("runs"), list):
            return None
        result = {}
        for run in registry["runs"]:
            if not isinstance(run, dict) or not isinstance(run.get("multisimulation_location"), str):
                continue
            sim = urlsplit(run["multisimulation_location"]).path.rstrip("/").rsplit("/", 1)[-1]
            if not sim:
                continue
            progress = run.get("progress")
            if isinstance(progress, bool) or not isinstance(progress, (int, float)) or not math.isfinite(progress) or not 0 <= progress <= 1:
                progress = None
            children = run.get("children")
            total = len(children) if isinstance(children, list) and all(isinstance(child, str) for child in children) else None
            # The actual writer stores URLs, not child completion flags. These
            # completed slots are derived from its reported fraction, never time.
            done = min(total, int(progress*total+1e-9)) if progress is not None and total is not None else None
            result[sim] = {"progress": progress, "children_done": done, "children_total": total}
        return result
    except (OSError, ValueError, TypeError, OverflowError, RecursionError):
        return None
