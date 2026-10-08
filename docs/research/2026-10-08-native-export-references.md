# Native export references and dependency decision

Read-only reference: [GuanYixuan/pyJianYingDraft](https://github.com/GuanYixuan/pyJianYingDraft/tree/6bb2d06a713f7b58e1375269daec835a03882086),
commit `6bb2d06a713f7b58e1375269daec835a03882086`.
[Keyframe definitions](https://github.com/GuanYixuan/pyJianYingDraft/blob/6bb2d06a713f7b58e1375269daec835a03882086/pyJianYingDraft/keyframe.py)
provide the brightness/contrast/saturation property names and neutral-zero ranges. No corresponding
gamma property is declared. Slider mapping is an experimental parameter conversion, not measured
equivalence to FFmpeg.

[Controller source](https://github.com/GuanYixuan/pyJianYingDraft/blob/6bb2d06a713f7b58e1375269daec835a03882086/pyJianYingDraft/jianying_controller.py)
and maintained README bound automation to legacy Windows controls. Modern Mac/Windows automation
is not established by that reference. The SDK exports to the native dialog path and moves the file
afterwards; our adapter instead checks the path before submit and keeps all writes inside the job.

Optional dependency decision: [official PyPI release 0.3.0](https://pypi.org/project/pyJianYingDraft/0.3.0/),
Windows-only extra. Wheel SHA-256:
`09863de4b0cfbb23fff54b4122ef49eff3527685f7978c6230f0651942954bdc`.
The release wheel's LICENSE is **Apache License 2.0**. This is an installed external dependency,
not vendored source. The base CLI does not install it, and this Mac development run did not execute
it. API signatures/selectors were checked by read-only AST inspection of that exact release wheel;
Windows CI checks imports/enums without constructing the controller. No upstream implementation,
source text, executable client DLL, media or machine-specific configuration is copied into the repo.

Reimplemented locally: typed manifests, constant native color serialization, portable motion source
inventory, input-bound export jobs, output validation/publication and a submit-path guard around the
optional SDK. GUI acceptance remains deferred by the user. Eligibility is separate from certification.
