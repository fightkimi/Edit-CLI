# SDR color quality verification

Date: 2026-10-08. Implementation self-review; extends the editorial-quality feature branch.

- Ruff passed; mypy passed for 78 source files.
- Full suite: **207 passed, 1 skipped in 40.84 seconds**. The skip is Windows PE API on this Mac.
- Nine real-media integration cases plus three focused unit cases cover this phase.
- Built wheel/source distribution; isolated installed CLI passed both new command registrations,
  actual source-index validation and dry-run planned/no-artifact JSON behavior.
- Runtime filter interface checked with local FFmpeg 9.0.2 `-h filter=eq` and
  https://ffmpeg.org/ffmpeg-filters.html#eq. No upstream code or new dependency was copied/installed.

## Evidence

A synthetic dark SDR gradient generated through FFmpeg was used for diagnosis, correction and
real preview renders. The CLI contact sheet was inspected: originals/after images are clearly
separated, actual sample times are readable, aspect ratio is preserved and proposed status is shown.

For the synthetic contact sheet, sampled mean luma changed from 0.20304466 to 0.23522840 using a
proposed brightness 0.036739. Near-dark fraction changed from 0.08002315 to 0; near-white fraction
remained 0. This is evidence of the implemented transformation, not a subjective quality score or a
claim that every dark scene should be brightened. Media and images remain local temporary evidence.

Render tests independently confirm a configured correction increases sampled image luma while
preserving audio PCM exactly and output duration. A subtitle pixel test confirms source grading
leaves white text readable/ungraded. Actual switched-camera and B-roll sources receive their own
settings. Neutral correction reuses the existing cache; changing relevant source settings changes
cache identity. Partial parameter revisions preserve other source values; reset restores native
export eligibility.

Reference-camera tests use verified same-take manual sync evidence and inspect the synchronized
source/reference statistics. Reports record reference ranges, corrections, sample times/hashes and
source fingerprints. A nonzero-container-start fixture verifies normalized source sampling and
stream-duration bounds. AAC priming can make container start earlier than nominal video start; the
test checks the actual video start and normalized evidence, not a fixed assumed format start.

Rejected before publication: nonfinite/out-of-range settings, active known-HDR correction, stale
source changed during contact generation and unsupported native color export. Source mutation
preserves prior reviews and removes new staging only. HDR diagnosis is not treated as an SDR result.

## Limits

RGB-derived thumbnail statistics are uncalibrated heuristics. Scene intent, faces/skin tone, white
balance and exposure taste still require viewing real footage. Unknown transfer metadata is flagged.
There is no verified HDR tonemapping, per-frame automatic grade, LUT or native Jianying color mapping.
The existing native-client acceptance pause and QC/master/freeze gates remain in force.
New cases are included in the existing Mac/Windows CI jobs alongside Linux full-suite checks.
