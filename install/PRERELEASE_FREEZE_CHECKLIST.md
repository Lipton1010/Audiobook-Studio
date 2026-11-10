# Storybird 1.1.0 beta freeze

Owner selected Apache-2.0 for original application code on 2026-11-10.
Third-party code, runtime and model licenses remain separate; see NOTICE.
The separate no-weights Drama runtime prerelease is already published:
https://github.com/Lipton1010/Audiobook-Studio/releases/tag/drama-runtime-4e6018f-win64-ada-beta.1
Its exact asset URL, hash and size are bound in drama3-pack.json.

Candidate installer version is 1.1.0; intended prerelease tag v1.1.0-beta.1.
Build only from clean committed HEAD using install/build_installer.bat.
Verify exact artifact manifests, hashes, preservation and native installed UI.
No weights, user settings, books, voices, jobs or generated audio may be bundled.

Repository RELEASE_CHECKLIST.md still requires clean-account/VM validation,
physical 16 GB GPU testing and confirmation the old webhook is revoked.
These have not been established for this candidate. Isolated Alpha tests and
RTX 4090 smokes must not be described as satisfying those requirements.
Public app publication remains held pending satisfaction or an explicit
owner-approved change to the beta release scope. No gate is silently waived.

Hardware estimates and observed tests remain labeled. Drama runtime is Ada
compute capability 8.9 only; other architectures are not certified. Existing
jobs and narrator defaults are retained, and optional packs require consent.
README app download links must only be added after a verified app release.
