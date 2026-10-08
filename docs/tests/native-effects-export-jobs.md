# Native effects and export jobs verification

2026-10-08. Implementation self-review. User deferred physical-client acceptance; no real client
was launched, installed, edited or exported during this development iteration.

Fresh checks: Ruff passed; mypy passed (88 source files); full pytest **237 passed, 1 skipped
in 51.98 seconds** (Windows PE version API on Mac). Skill checks passed separately after reference
updates. Source/wheel build passed. An isolated wheel imported from its own site-packages outside
the repository and completed schema-3 export → verify → bundled-source regeneration → planned job
→ simulated output completion → status. Export ID `71A9B850-1B4D-4D5E-A2B5-3A893A67E3EB`, job ID
`native_08f990a855e54eb99540df637f892933`. The reported input was an existing CLI synthetic preview;
this was deliberately a simulated native file, not a Jianying-rendered video. Generated evidence
remains ignored under the configured acceptance artifact root.

Tested with synthetic media and simulated GUI/driver objects:
- Schema-3 Mac/Windows identical native timelines, separate motion track and primary audio,
  native brightness/contrast/saturation settings, original MOV/spec/font payload preservation.
- Full package verification, installed Windows path rebasing and receiving-project source
  regeneration from bundled spec/font. Rehashed native parameter changes fail semantic checks.
- Gamma rejection, default strict-mode rejection and legacy schema-2 regression behavior.
- Manual planned job → full output checks → atomic published result, idempotent completion,
  corrupted evidence rejection, failed partial file recovery and read-only original video.
- Concurrent-command lock, changed original package/native timeline rejection, recovery from
  interruption after result directory publication but before convenience status update.
- Legacy version/preset/root/approval/timeout boundaries, worker dispatch without running a GUI,
  partial-output preservation, pre-submit checks rejecting outside-root/existing native targets.

Optional SDK 0.3.0 API/selectors were verified from the official release wheel without execution.
Windows CI installs the optional runtime and checks interfaces without creating a controller.
All OS CI remains separate from GUI acceptance; fixtures do not certify a native render.

Limits: native slider appearance is unmeasured; gamma mapping remains unsupported. Motion text is
regenerated from source, not editable native text. Mac/modern Windows automatic GUI export is absent;
their manual export job/completion workflow is implemented. Native provenance, font/composition,
save/reopen and sound/visual fidelity require the separately deferred acceptance process.
