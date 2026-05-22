"""Single entry point for the test-data-generator skill.

    python run.py --source file <name.xlsx>       # bare name → received_spec_sheets/
    python run.py --source file                    # no name  → newest .xlsx
    python run.py --source json <name.json>        # thin endpoint defs
    python run.py --source file --component countries
    python run.py --source file --chain            # also copy output into Skill 4
    python run.py --source file --fanout           # multiply positives by seed count

The skill does NOT call any live API. It reads a spec sheet (or thin JSON),
substitutes placeholder values from config/seeds/<component>.yaml using
config/endpoint_param_map.yaml, and writes a test_data JSON ready for the
test-generator skill to consume.
"""
from __future__ import annotations

import argparse
import json
import logging
import shutil
import sys
from pathlib import Path
from typing import Any

# Local imports
sys.path.insert(0, str(Path(__file__).resolve().parent))
from load_seeds import SeedError, load_endpoint_param_map, load_seeds  # noqa: E402
from parse_input import InputError, from_json, from_spec_sheet  # noqa: E402
from substitute import substitute_groups  # noqa: E402
from write_test_data import output_paths, write  # noqa: E402

LOG = logging.getLogger(__name__)

_SCRIPT_DIR = Path(__file__).resolve().parent
_SKILL_ROOT = _SCRIPT_DIR.parent
_INPUT_DIR = _SKILL_ROOT / "received_spec_sheets"
_OUTPUT_DIR = _SKILL_ROOT / "generated_test_data"
_TEST_GENERATOR_INBOX = (
    _SKILL_ROOT.parent / "test-generator" / "received_test_data"
)


def _die(msg: str, code: int = 2) -> None:
    print(f"[test-data-generator] {msg}", file=sys.stderr)
    sys.exit(code)


def _latest_with_suffix(suffix: str) -> Path:
    if not _INPUT_DIR.exists():
        _die(f"received_spec_sheets/ missing: {_INPUT_DIR}")
    candidates = [
        p for p in _INPUT_DIR.iterdir()
        if p.is_file() and p.suffix.lower() == suffix
        and not p.name.startswith("~$") and p.name != ".gitkeep"
    ]
    if not candidates:
        _die(f"received_spec_sheets/ has no {suffix} files: {_INPUT_DIR}")
    latest = max(candidates, key=lambda p: p.stat().st_mtime)
    LOG.info("received_spec_sheets/ has %d %s file(s); picked latest: %s",
             len(candidates), suffix, latest.name)
    return latest


def _resolve_input(name: str | None, suffix: str) -> Path:
    if not name:
        return _latest_with_suffix(suffix)
    p = Path(name)
    if p.is_absolute() or p.exists():
        return p
    candidate = _INPUT_DIR / name
    if candidate.exists():
        return candidate
    _die(f"input not found: tried {p} and {candidate}")
    return p  # unreachable


def main() -> None:
    ap = argparse.ArgumentParser(
        description="Substitute placeholder values in a spec sheet with curated seed values."
    )
    ap.add_argument("--source", required=True, choices=["file", "json"])
    ap.add_argument("locator", nargs="?",
                    help="xlsx/json filename (looked up in received_spec_sheets/)")
    ap.add_argument("--component", default=None,
                    help="Override the component used for seed lookup and output naming")
    ap.add_argument("--chain", action="store_true",
                    help="After writing, copy the JSON into ../test-generator/received_test_data/")
    ap.add_argument("--fanout", dest="fanout", action="store_true",
                    help="Multiply positive rows across all seed records (default ON)")
    ap.add_argument("--no-fanout", dest="fanout", action="store_false",
                    help="Preserve one row per spec row and distribute positive rows across seeds")
    ap.set_defaults(fanout=True)
    args = ap.parse_args()

    suffix = ".xlsx" if args.source == "file" else ".json"
    try:
        input_path = _resolve_input(args.locator, suffix)
    except SystemExit:
        raise

    # 1. Parse
    try:
        parsed = from_spec_sheet(input_path) if args.source == "file" else from_json(input_path)
    except InputError as exc:
        _die(str(exc))

    components = sorted({g["component"] for g in parsed.get("groups", [])})
    if not components:
        _die("no components detected in input")
    component_for_output = args.component or "_".join(components[:3])

    # 2. Load seeds + param map
    try:
        seeds_by_component = {c: load_seeds(c) for c in components}
        param_map_by_component = load_endpoint_param_map()
    except SeedError as exc:
        _die(str(exc))

    # 3. Substitute
    payload, warnings = substitute_groups(
        parsed, seeds_by_component, param_map_by_component, fanout=args.fanout,
    )

    # 4. Write
    json_path, report_path = output_paths(_OUTPUT_DIR, component_for_output)
    summary = write(
        payload, warnings, json_path, report_path,
        spec_sheet=str(input_path), components=components, fanout=args.fanout,
    )

    # 5. Optional chain
    if args.chain:
        _TEST_GENERATOR_INBOX.mkdir(parents=True, exist_ok=True)
        dest = _TEST_GENERATOR_INBOX / json_path.name
        shutil.copy2(json_path, dest)
        LOG.info("Chained copy: %s", dest)
        summary["chained_to"] = str(dest)

    # 6. Print summary
    print(f"\nWrote {summary['json_path']}")
    print(f"Wrote {summary['report_path']}")
    print(f"Classes:        {summary['class_count']}")
    print(f"Total rows:     {summary['total_rows']}")
    print(f"Skipped rows:   {summary['skipped_rows']}")
    print(f"By bucket:      {summary['by_bucket']}")
    print(f"Components:     {summary['components']}")
    if summary.get("chained_to"):
        print(f"Chained to:     {summary['chained_to']}")
    print()
    print("Next steps:")
    print(f"  1. Review {Path(summary['report_path']).name}.")
    if not args.chain:
        print("  2. Pass the JSON to test-generator with --test-data <path>.")
        print("     Or re-run with --chain to auto-copy.")
    else:
        print("  2. Run test-generator — it will pick up the file from received_test_data/.")


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    main()
