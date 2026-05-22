"""Seed dataset + endpoint parameter-map loaders.

Reads two YAMLs:
  - config/seeds/<component>.yaml — list of record dicts (curated values)
  - config/endpoint_param_map.yaml — per-component map from endpoint pattern
    to the seed-field templates that fill its path/query params
"""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

import yaml

LOG = logging.getLogger(__name__)

_SCRIPT_DIR = Path(__file__).resolve().parent
_SKILL_ROOT = _SCRIPT_DIR.parent
_SEEDS_DIR = _SKILL_ROOT / "config" / "seeds"
_PARAM_MAP = _SKILL_ROOT / "config" / "endpoint_param_map.yaml"


class SeedError(Exception):
    """Raised when a seed file or param map is missing or malformed."""


def load_seeds(component: str) -> list[dict[str, Any]]:
    """Return the list of seed records from config/seeds/<component>.yaml."""
    path = _SEEDS_DIR / f"{component}.yaml"
    if not path.exists():
        raise SeedError(
            f"seed file not found for component '{component}': {path}. "
            f"Available: {[p.stem for p in _SEEDS_DIR.glob('*.yaml')]}"
        )
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except yaml.YAMLError as exc:
        raise SeedError(f"could not parse {path}: {exc}") from exc
    records = data.get("records")
    if not isinstance(records, list) or not records:
        raise SeedError(f"{path} has no 'records' list (or it is empty)")
    LOG.info("Loaded %d seed record(s) from %s", len(records), path.name)
    return [dict(r) for r in records]


def load_endpoint_param_map() -> dict[str, dict[str, dict[str, dict[str, str]]]]:
    """Return {component: {endpoint_pattern: {path_params|query_params: {name: tmpl}}}}."""
    if not _PARAM_MAP.exists():
        raise SeedError(f"endpoint_param_map.yaml not found: {_PARAM_MAP}")
    try:
        data = yaml.safe_load(_PARAM_MAP.read_text(encoding="utf-8")) or {}
    except yaml.YAMLError as exc:
        raise SeedError(f"could not parse {_PARAM_MAP}: {exc}") from exc
    if not isinstance(data, dict) or not data:
        raise SeedError(f"{_PARAM_MAP} is empty or not a mapping")
    LOG.info("Loaded endpoint param map for components: %s", sorted(data.keys()))
    return {str(k): dict(v) for k, v in data.items()}
