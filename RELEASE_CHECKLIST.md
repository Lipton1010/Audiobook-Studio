# Audiobook Studio release checklist

The project remains a private beta until every required gate below passes on
the exact commit and installer artifact being published.

## Source and privacy

- [ ] The exact 1.0.3 candidate `git status --short --branch` is clean and synchronized with the intended remote.
- [x] Dependency-free regression tests pass: `python -m unittest discover -s tests -v`.
- [x] Python and embedded JavaScript syntax checks pass.
- [x] Current source and installer designs contain no live crash-report credential; reporting is local opt-in and disabled by default.
- [ ] The formerly embedded Discord webhook has been revoked at the provider. Revocation is separate from source removal.
- [x] The two former `ab_samples` excerpt files are absent from every rewritten Git ref.
- [x] A recoverable pre-rewrite Git bundle exists outside the published history.
- [x] No PDF, generated audio, voice sample, job data, local config, or private audition text is tracked.
- [x] GitHub Support has dereferenced affected PRs 1 through 4, run server garbage collection, and removed cached views of the former excerpt blobs.

## Installer artifact

- [ ] Build 1.0.3 only with `install\build_installer.bat` and `install\build_installer.bat patch`; never compile the Inno file directly.
- [ ] The 1.0.3 builds come from clean `HEAD` and record their commit, byte sizes, and SHA-256 at handoff.
- [ ] Both 1.0.3 Inno output manifests pass the prohibited-content check, and source/artifact credential scans pass.
- [ ] The built 1.0.3 executables are not committed to Git.

## Exact-build clean-machine validation

- [ ] Install on a clean Windows account or VM with no existing app runtime.
- [ ] Observe the full wizard, disk-space copy, warnings, and Finished page.
- [ ] Confirm the private Miniconda and all caches stay below the single app runtime folder.
- [ ] Confirm the installed shortcut opens the native app without a console window.
- [ ] Confirm `install_log.txt` exists and the diagnostic logs are usable.
- [ ] Import a real PDF through the UI and confirm the recommended start page.
- [ ] Generate a short CUDA narration with the installed build and verify the final audio.
- [ ] In the installed pywebview window, save and inspect both a beta-report ZIP and finished audio.
- [ ] On a 16 GB NVIDIA GPU, force or naturally reach a recoverable batched OOM and confirm ordered bisection/resume succeeds.
- [ ] Apply the patch to an actual 1.0.1 install and verify narration imports, audio downloads, and retained user data.
- [ ] Observe dedicated and shared GPU memory through a complete installed-build narration; a developer-machine allocator cap test is not a physical small-card test.
- [ ] Close the app during a synthetic narration and confirm no owned GPU worker survives and no unrelated process is terminated.
- [ ] Confirm M4B chapter navigation and the completed-job segment-cache cleanup action.
- [ ] Uninstall and verify user books, voices, jobs, and audiobooks are preserved as documented.

## Publish

- [ ] Tag the exact validated commit.
- [ ] Publish the exact validated installer and its SHA-256 as a GitHub Release asset.
- [ ] Verify the README latest-release link and badge resolve to that release.
- [ ] Keep release notes candid about Windows, NVIDIA/CUDA, disk usage, unsigned SmartScreen warnings, and the personal-use scope.
