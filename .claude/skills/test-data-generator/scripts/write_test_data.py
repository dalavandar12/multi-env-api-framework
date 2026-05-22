"""Emit the test_data JSON + a generation report."""
from __future__ import annotations

import datetime as dt
import json
import logging
from collections import Counter
from pathlib import Path
from typing import Any

LOG = logging.getLogger(__name__)


def output_paths(output_dir: Path, component: str) -> tuple[Path, Path]:
    ts = dt.datetime.now(dt.timezone.utc).strftime("%Y%m%d_%H%M%SZ")
    safe = (component or "mixed").replace("+", "_")
    return (
        output_dir / f"test_data_{safe}_generated_{ts}.json",
        output_dir / f"report_{safe}_{ts}.txt",
    )


def write(
    payload: dict[str, dict[str, list[dict[str, Any]]]],
    warnings: list[str],
    json_path: Path,
    report_path: Path,
    *,
    spec_sheet: str,
    components: list[str],
    fanout: bool,
) -> dict[str, Any]:
    """Persist the JSON + report; return a summary dict."""
    json_path.parent.mkdir(parents=True, exist_ok=True)
    json_path.write_text(
        json.dumps(payload, indent=2, ensure_ascii=False, default=str),
        encoding="utf-8",
    )
    LOG.info("Wrote test_data JSON %s", json_path)

    cls_count = len(payload)
    total = 0
    skipped = 0
    by_bucket: Counter[str] = Counter()
    for buckets in payload.values():
        for bucket, rows in buckets.items():
            total += len(rows)
            by_bucket[bucket] += len(rows)
            skipped += sum(1 for r in rows if r.get("skip"))

    lines = [
        "test-data-generator — generation report",
        "=" * 60,
        f"Spec sheet:    {spec_sheet}",
        f"Components:    {', '.join(components) or '(none)'}",
        f"Fan-out mode:  {'YES' if fanout else 'NO (one seed per row)'}",
        f"Classes:       {cls_count}",
        f"Total rows:    {total}",
        f"Skipped rows:  {skipped}  (unrunnable categories — see skip_reason in JSON)",
        "",
        "Per-bucket counts:",
    ]
    for bucket, n in sorted(by_bucket.items()):
        lines.append(f"  {bucket:<20} {n}")
    if warnings:
        lines += ["", "Warnings:"]
        lines += [f"  - {w}" for w in warnings]
    else:
        lines += ["", "Warnings: none"]
    report_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    LOG.info("Wrote report %s", report_path)

    return {
        "json_path": str(json_path),
        "report_path": str(report_path),
        "class_count": cls_count,
        "total_rows": total,
        "skipped_rows": skipped,
        "by_bucket": dict(by_bucket),
        "components": components,
    }
