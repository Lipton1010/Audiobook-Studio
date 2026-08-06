# Audiobook Studio release checklist

The project remains a private beta until every required gate below passes on
the exact commit and installer artifact being published.

## Source and privacy

- [x] `git status --short --branch` is clean and synchronized with the intended remote.
- [x] Dependency-free regression tests pass: `python -m unittest discover -s tests -v`.
- [x] Python and embedded JavaScript syntax checks pass.
- [x] The two former `ab_samples` excerpt files are absent from every rewritten Git ref.
- [x] A recoverable pre-rewrite Git bundle exists outside the published history.
- [x] No PDF, generated audio, voice sample, job data, local config, or private audition text is tracked.
- [x] GitHub Support has dereferenced affected PRs 1 through 4, run server garbage collection, and removed cached views of the former excerpt blobs.

## Installer artifact

- [x] Build only with `install\build_installer.bat`; never compile the Inno file directly.
- [x] The build comes from clean `HEAD` and records its commit, byte size, and SHA-256.
- [x] The Inno output manifest passes the prohibited-content checks.
- [x] The built executable is not committed to Git.

## Exact-build clean-machine validation

- [ ] Install on a clean Windows account or VM with no existing app runtime.
- [ ] Observe the full wizard, disk-space copy, warnings, and Finished page.
- [ ] Confirm the private Miniconda and all caches stay below the single app runtime folder.
- [ ] Confirm the installed shortcut opens the native app without a console window.
- [ ] Confirm `install_log.txt` exists and the diagnostic logs are usable.
- [ ] Import a real PDF through the UI and confirm the recommended start page.
- [ ] Generate a short CUDA narration with the installed build and verify the final audio.
- [ ] Confirm M4B chapter navigation and the completed-job segment-cache cleanup action.
- [ ] Uninstall and verify user books, voices, jobs, and audiobooks are preserved as documented.

## Publish

- [ ] Tag the exact validated commit.
- [ ] Publish the exact validated installer and its SHA-256 as a GitHub Release asset.
- [ ] Verify the README latest-release link and badge resolve to that release.
- [ ] Keep release notes candid about Windows, NVIDIA/CUDA, disk usage, unsigned SmartScreen warnings, and the personal-use scope.
