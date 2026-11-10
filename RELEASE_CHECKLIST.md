# Audiobook Studio release checklist

Release only when the applicable gates below pass, with the owner-approved exceptions explicitly disclosed. Installer source is frozen at 49c9006e0e5aeb438f375c3c2a0cd2bf010dcfef; later checklist/homepage-only commits do not change those artifacts. The audio-runtime suite ran 605 tests: 581 passes, 24 dependency-specific skips.

## Source and privacy

- [ ] The exact 1.1.2 candidate `git status --short --branch` is clean and synchronized with the intended remote.
- [x] Dependency-free regression tests pass: `python -m unittest discover -s tests -v`.
- [x] Python and embedded JavaScript syntax checks pass.
- [x] Current source and installer designs contain no live crash-report credential; reporting is local opt-in and disabled by default.
- [x] Owner confirmed deleting the formerly embedded Discord webhook on 2026-11-10. Owner attestation; no independent credential request or test message was sent. Revocation is separate from source removal.
- [x] The two former `ab_samples` excerpt files are absent from every rewritten Git ref.
- [x] A recoverable pre-rewrite Git bundle exists outside the published history.
- [x] No PDF, generated audio, voice sample, job data, local config, or private audition text is tracked.
- [x] GitHub Support has dereferenced affected PRs 1 through 4, run server garbage collection, and removed cached views of the former excerpt blobs.

## Installer artifact

- [x] Build 1.1.2 only with `install\build_installer.bat` and `install\build_installer.bat patch`; never compile the Inno file directly.
- [x] The 1.1.2 builds come from clean `HEAD` and record their commit, byte sizes, and SHA-256 at handoff.
- [x] Both 1.1.2 Inno output manifests pass the prohibited-content check, and source/artifact credential scans pass.
- [x] The built 1.1.2 executables are not committed to Git.

## Exact-build validation and owner-approved scope

- [x] Owner-approved clean-PC exception (2026-11-10): fresh Windows/WebView2 provisioning and the full fresh-PC wizard path remain UNVERIFIED. Sandbox blocked Microsoft's runtime installer. Do not describe developer-machine testing as a clean-PC pass.
- [x] Exact 1.1.2 full installer and patch ran on an isolated Alpha installation with existing prerequisites. Core setup logs were retained; no model was automatically selected/downloaded.
- [x] Installed native WebView2 app imported a synthetic PDF and rendered its page preview (816 x 1056); recommended range was 1-1.
- [x] Exact installed Chatterbox worker produced short synthetic CUDA narration offline. This does not certify whole-book voice quality.
- [x] Native Save dialogs exported exact audio and a CRC-valid diagnostic ZIP. Both files remained intact after app exit. The first test closed too soon; retained failure evidence is not counted as a pass.
- [x] Owner-approved hardware scope (2026-11-10): experimental RTX 4090/Ada only. Physical 16 GB OOM/bisection and shared-memory behavior on smaller cards remain NOT RUN.
- [x] Owner-approved upgrade scope (2026-11-10): 1.1.0 only. Exact patch upgraded the retained 1.1.0 test-installation copy, preserving 13 protected files. Missing/older/newer/malformed version markers were rejected before target files changed.
- [x] Older-version full-installer upgrades and their data preservation remain UNVERIFIED. Recommend backup; do not represent the full installer as a proven older-version migration.
- [x] Native app closed during actual synthetic CUDA sampling: owned worker exited; unrelated sentinel survived. Whole-board peak was 5,198 MiB. This is not per-process peak or a minimum requirement.
- [x] M4B chapter navigation and completed-job cache cleanup passed separate synthetic tests; their unchanged installed implementations are manifest-verified. These checks are not claimed to be a whole-book test.
- [x] Exact-build uninstall preserved all 20 protected synthetic user-data files. Equivalent recovery copies of all 21,910 installation files were verified before uninstall. Production data was not used.
- [x] Fresh optional Chatterbox provisioning downloaded pinned official files, verified hashes, installed its isolated runtime and generated offline without manual repair. No default narrator was selected. Model/dependency licenses and retirement/watermark limitations are disclosed.
- [x] Drama portability is separate and unvalidated for the app's twelve-CPU-layer configuration. No arbitrary memory requirement is represented as measured.

## Publish

- [ ] Tag the exact validated commit.
- [ ] Publish the exact validated installer and its SHA-256 as a GitHub Release asset.
- [ ] Verify the README latest-release link and badge resolve to that release.
- [ ] Keep release notes candid about Windows, NVIDIA/CUDA, disk usage, unsigned SmartScreen warnings, and separate application, component and model licensing. Drama portability remains experimental; do not claim the app twelve-layer configuration passed.
