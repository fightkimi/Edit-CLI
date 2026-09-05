# Output-quality Skills integration

User request: research suitable Skills on GitHub and X, integrate them into this project, and
submit the current project to `fightkimi/Edit-CLI`.

Scope: add project-local editorial, speech-pacing, caption/audio and render-review guidance;
connect the existing orchestration Skill; preserve license/source provenance. Publish the current
project including existing uncommitted operation-observability and status improvements after
verification. Preserve the original Git remote and avoid forced updates.

Non-goals: changing render contracts, adding another media engine, uploading footage, downloading
models, or claiming a real-video quality improvement without a before/after viewing comparison.

Acceptance:

1. Skills have valid discoverable metadata, working references and narrow responsibilities.
2. Only compatible workflow guidance is installed; no upstream shell/cloud/bootstrap code runs.
3. Adaptations preserve MIT notices and fixed commit/source checksums.
4. Cut-list validation, privacy, artifact boundaries, master/freeze gates remain intact.
5. Ruff, mypy, pytest and Skill structural validation pass on final files.
6. Commit and push to the requested repository; verify its branch head matches local evidence.

Baseline: original `origin` points to `guang-tech/edit-CLI`; local branch `main` at `36e7d6c`.
Target repository was empty when checked. Existing modifications were inspected and are preserved.
Before integration: Ruff passed, mypy passed (56 source files), pytest 108 passed in 27.31 seconds.

Validation separates metadata/link checks, existing synthetic render regression coverage, and
unperformed real-media editorial A/B evaluation. Keep temporary research downloads outside Git.
