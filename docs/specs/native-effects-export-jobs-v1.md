# Experimental native effects and export jobs v1

Native acceptance is paused by the user. These are serialization/job contracts, not client
compatibility certification. Default editable export remains strict. Opt in explicitly:

```bash
interview-edit export jianying --project PROJECT --cutlist CUT --name UNIQUE_NAME \
  --platform both --native-effects --json
```

This requires bundled resources and produces manifest schema 3. Schema 2 remains readable; schema
1 requires re-export. Brightness maps directly to `KFTypeBrightness`, contrast minus one to
`KFTypeContrast`, saturation minus one to `KFTypeSaturation`, each a constant pair at segment
offsets zero/end. Actual cameras/B-roll receive their settings; audio, titles/subtitles do not.
These sliders are experimental and not guaranteed pixel-equivalent to FFmpeg eq. Non-neutral gamma
fails with `jianying_gamma_unsupported`. Known-HDR correction retains its rejection gate.

Verified motion movies become a separate video track with original alpha, duration, dimensions and
source identity. The package retains source spec, manifest, poster and matching font with the MOV.
Motion pixels are not native text: native trim/position and source-text regeneration are distinct.
Ordinary titles/subtitles remain native editable text. Receiver-side regeneration:

```bash
interview-edit motion from-spec --project PROJECT --spec PACKAGE/Resources/SPEC.json \
  --font PACKAGE/Resources/FONT.ttf --json
interview-edit motion edit --project PROJECT --asset NEW_ASSET --text "Revised text" --json
```

Schema 3 adds `native_effects` and typed `motion_assets` containing input overlay bindings,
spec/manifest and resource mapping. Generated motion is declared media, distinct from indexed
camera/audio sources. Verification checks inventory, fonts/hashes, retained spec, frame timing,
dimensions, segment mapping and exact color settings. Rehashing a changed native entry does not
make missing/different effect values valid.

## Native export jobs

Manual jobs work without driving a client GUI:

```bash
interview-edit jianying export-video --project PROJECT --draft ORIGINAL_PACKAGE --json
# Export in Jianying to the returned incomingPath, then:
interview-edit jianying finish-export --project PROJECT --job JOB_ID --video COMPLETED.mp4 --json
interview-edit jianying export-status --project PROJECT --job JOB_ID --json
```

The default backend creates a **planned job**, not an MP4, and never launches the client. It binds
project/package identity and the original manifest hash. Use `--expected-duration-us` at creation
when native trimming changes length. Selected incoming files are read-only inputs. Generated files
stay under `artifact_root/native-exports/`.

Optional legacy Windows execution:

```bash
uv tool install '.[native-windows]'  # separately authorized dependency installation
interview-edit jianying export-video --project PROJECT --draft ORIGINAL_PACKAGE \
  --backend windows-legacy --installed-draft INSTALLED_FOLDER --json
# Configure native export inside this job folder, start at home, then:
interview-edit jianying run-export --project PROJECT --job JOB_ID --approve --json
```

Only detected Windows Jianying 5.x/6.x is eligible; modern Windows, Mac and unknown versions fail
explicitly. SDK pyJianYingDraft 0.3.0 is optional and Windows-only. Commands never download it.
`doctor` reports backend eligibility/dependency availability separately from compatibility and
nativeValidation. SDK import/API CI does not operate a native client.

The installed folder must belong to the detected library and retain the bound project ID and
timeline/material/canvas fingerprint. Legacy name-based selection rejects duplicate/unreadable
names. `--approve` binds automatic rendering to those inputs. The worker refuses an active editor
to preserve other work. Immediately before submit, its path guard requires a new export file inside
the job folder. SDK export-to-default-then-move cannot write outside it. No location change, VIP
purchase, security bypass or draft decryption is automated.

Driver timeout is 30–3600 seconds plus a 15-second outer allowance. It stops the worker; the native
app may still render independently. Partial files are retained, never overwritten or marked complete.
Resume with `finish-export` after completion, or create a new job.

Jobs use `planned/running/succeeded/failed`. Completion checks full decode, dimensions, expected
duration, audio, the package's frame rate (0.01% tolerance) and stable hashes, then publishes
video/check/receipt together by directory rename. General `check-output` remains frame-rate-agnostic
unless its service caller requests a rate; its additive report fields record observed/requested rates.
Locks prevent overlapping commands. A committed receipt recovers an interrupted status update;
missing/changed output or evidence fails status inspection. Sources/previous outputs are preserved.
`succeeded` means local checks/publication passed, not native provenance or human review. It does not
satisfy CLI master/release-QC/freeze gates. Dry-run writes nothing or invokes a GUI.
