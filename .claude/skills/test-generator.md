## test-generator

Canonical skill definition: `.claude/skills/test-generator/SKILL.md`

This skill transforms testcase specifications (and optional prepared test-data JSON) into runnable pytest modules plus companion data files. It mirrors framework conventions for fixtures, markers, validators, and reporting annotations, and supports controlled auto-copy into repository test paths. It is used as the final automation stage after testcase and test-data preparation.

The folder-based `SKILL.md` is the source of truth for behavior, inputs, options, and constraints.
