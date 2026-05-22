## test-data-generator

Canonical skill definition: `.claude/skills/test-data-generator/SKILL.md`

This skill converts testcase spec rows into practical JSON test data using curated seed sources and endpoint-aware substitution rules. It is designed to keep generated test data realistic while preserving row intent and supporting chaining into test generation. The workflow is offline-friendly and avoids circular validation patterns.

The folder-based `SKILL.md` is the source of truth for behavior, inputs, options, and constraints.
