"""Single entry point for the validator-generator skill.

    python run.py                                  # process every YAML in received_schemas/
    python run.py --schema countries               # one specific schema
    python run.py --schema countries --write-to-validators
                                                   # also append into src/validators.py
                                                   # inside a marked auto-gen block
"""
from __future__ import annotations

import argparse
import logging
import re
import sys
from pathlib import Path

# Local imports
sys.path.insert(0, str(Path(__file__).resolve().parent))
from emit_validator import emit, write_file  # noqa: E402
from parse_schema import SchemaError, load  # noqa: E402

LOG = logging.getLogger(__name__)

_SCRIPT_DIR = Path(__file__).resolve().parent
_SKILL_ROOT = _SCRIPT_DIR.parent
_SCHEMAS_DIR = _SKILL_ROOT / "received_schemas"
_OUTPUT_DIR = _SKILL_ROOT / "generated_validators"
_REPO_VALIDATORS = (
    _SKILL_ROOT.parent.parent.parent / "src" / "validators.py"
)

_AUTOGEN_START = "# === auto-generated validators (DO NOT EDIT) ==="
_AUTOGEN_END = "# === end auto-generated ==="


def _die(msg: str, code: int = 2) -> None:
    print(f"[validator-generator] {msg}", file=sys.stderr)
    sys.exit(code)


def _find_schemas(name: str | None) -> list[Path]:
    if name:
        path = _SCHEMAS_DIR / f"{name}.yaml"
        if not path.exists():
            _die(f"schema not found: {path}")
        return [path]
    schemas = sorted(
        p for p in _SCHEMAS_DIR.glob("*.yaml")
        if p.name != ".gitkeep"
    )
    if not schemas:
        _die(f"no schemas in {_SCHEMAS_DIR}")
    return schemas


def _autogen_block(content: str) -> str:
    return f"\n\n{_AUTOGEN_START}\n{content.rstrip()}\n{_AUTOGEN_END}\n"


def _append_into_validators(schema_file: Path, force: bool) -> str:
    """Insert/replace the generated function inside the marked auto-gen block."""
    schema = load(schema_file)
    generated_py = emit(schema)
    fn_name = schema["validator_name"]

    # Strip the module docstring + imports — keep just the function definition.
    fn_match = re.search(
        r"(?ms)^def\s+" + re.escape(fn_name) + r".*?(?=\n(?:def\s|\Z))", generated_py
    )
    if not fn_match:
        _die(f"could not locate function '{fn_name}' in generated source")
    function_block = fn_match.group(0).rstrip() + "\n"

    if not _REPO_VALIDATORS.exists():
        _die(f"src/validators.py not found at {_REPO_VALIDATORS}")
    existing = _REPO_VALIDATORS.read_text(encoding="utf-8")

    # Locate auto-gen block (if any).
    block_re = re.compile(
        re.escape(_AUTOGEN_START) + r".*?" + re.escape(_AUTOGEN_END),
        re.DOTALL,
    )
    block_match = block_re.search(existing)
    if block_match is None:
        # No existing block — append fresh.
        new_block = _autogen_block(function_block)
        # Refuse if a same-named function already exists OUTSIDE the block.
        if re.search(r"(?m)^def\s+" + re.escape(fn_name) + r"\(", existing) and not force:
            _die(
                f"src/validators.py already defines '{fn_name}' outside the auto-gen block. "
                f"Pass --force to overwrite (you would lose the hand-written version)."
            )
        updated = existing.rstrip() + new_block
    else:
        # Existing block — splice in or replace the function inside it.
        block_content = block_match.group(0)
        inner = block_content[len(_AUTOGEN_START): -len(_AUTOGEN_END)].strip()
        fn_in_block = re.search(
            r"(?ms)^def\s+" + re.escape(fn_name) + r"\(.*?(?=\n(?:def\s|\Z))",
            inner,
        )
        if fn_in_block and not force:
            _die(
                f"'{fn_name}' already exists inside the auto-gen block. "
                f"Pass --force to overwrite."
            )
        if fn_in_block:
            new_inner = inner[:fn_in_block.start()] + function_block + inner[fn_in_block.end():]
        else:
            new_inner = inner + ("\n\n" if inner else "") + function_block
        new_block = _autogen_block(new_inner)
        updated = existing[:block_match.start()] + new_block.lstrip("\n") + existing[block_match.end():]

    _REPO_VALIDATORS.write_text(updated, encoding="utf-8")
    LOG.info("Patched %s with %s (inside auto-gen block)", _REPO_VALIDATORS, fn_name)
    return fn_name


def main() -> None:
    ap = argparse.ArgumentParser(
        description="Emit Python validators from curated schema YAML files."
    )
    ap.add_argument("--schema", default=None,
                    help="Name (without .yaml) of a single schema to process")
    ap.add_argument("--write-to-validators", action="store_true",
                    help="Also append the function into src/validators.py auto-gen block")
    ap.add_argument("--force", action="store_true",
                    help="Required to overwrite an existing function inside the block")
    ap.add_argument("--verbose", action="store_true")
    args = ap.parse_args()

    if args.verbose:
        logging.getLogger().setLevel(logging.DEBUG)

    schemas = _find_schemas(args.schema)
    wrote_validators: list[str] = []
    wrote_repo_fns: list[str] = []

    for schema_file in schemas:
        try:
            schema = load(schema_file)
        except SchemaError as exc:
            _die(str(exc))
        out = write_file(_OUTPUT_DIR, schema)
        wrote_validators.append(str(out))

        if args.write_to_validators:
            fn_name = _append_into_validators(schema_file, args.force)
            wrote_repo_fns.append(fn_name)

    print()
    for p in wrote_validators:
        print(f"Wrote {p}")
    if wrote_repo_fns:
        print()
        print(f"Updated src/validators.py with function(s): {wrote_repo_fns}")
        print("Re-run pytest to confirm imports still resolve.")
    else:
        print()
        print("Review the file(s) above, then either:")
        print("  - paste the function into src/validators.py manually, or")
        print("  - re-run with --write-to-validators to do it automatically.")


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    main()
