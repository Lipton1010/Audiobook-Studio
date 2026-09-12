# Automatic beta handoff

The owner authorized uploading each new installer and patch to the existing
Audiobook_App Google Drive folder on 2026-09-12. This authorization persists for
future beta builds. Do not request it again. Public GitHub releases still require
the complete `RELEASE_CHECKLIST.md`.

Destination: the owner's Audiobook_App folder, recorded as `folder_id` in the
gitignored `Output/drive_uploads.json`. Keep Drive IDs and links in that local
ledger, not in published source. If the ledger is unavailable, get the destination
from the active task or ask the owner; never choose another Drive folder.

## Local build contract

Build through `install/build_installer.bat` (full) and
`install/build_installer.bat patch` from clean HEAD. Bump the app version and both
Inno versions together for new application revisions. The build writes these two
fixed handoff files at the top of `Output`:

* `Setup_AudiobookStudio.exe`: new installation.
* `Setup_AudiobookStudio_Patch.exe`: existing installation.

After the manifest check passes, `record_installer.ps1` writes a `-build.json`
receipt containing the version, exact archived commit, bytes, SHA-256, manifest
hash and `distribution_name`.

For the next version onward, the owner confirmed these exact Drive naming patterns:

* `Patch_AudiobookStudio_1.0.4.exe`
* `Installer_AudiobookStudio_1.0.4.exe`

Substitute the actual app version. Put Patch or Installer first; include no build
timestamp, hash suffix, or other identifier in the filename. Keep provenance in
the receipts. Use a new version number for a different distributed build; identical
bytes do not need another upload. Before building the next version, update
`record_installer.ps1` and its naming assertion in `tests/test_installer_record.ps1`
to generate these names. The existing 1.0.3 uploads and receipts retain their old
names at the owner's request; do not rename or reupload them just for this policy.

`00_CURRENT_INSTALLERS.txt` is the human-readable local guide. Older versioned
executables are moved to `Output/Old, do not use/` instead of remaining beside the
current pair.

## Upload and retire previous copies

Use the connected Google Drive tools immediately after each successful agent-run
build, in the same task. This is a required completion step, not an optional
follow-up. The owner explicitly rejected polling on 2026-09-12: do not create a
recurring check or spend tokens when no build is happening. The batch file writes
the upload-ready receipt but does not itself authenticate to Google Drive. A
manual batch run outside an agent task therefore needs the Drive handoff performed
in the next active task; do not claim that a receipt is an upload.

1. Read the two receipts and only their exact EXE and manifest paths. Check local
   EXE size, SHA-256, product version and manifest SHA-256 against the receipt.
   Missing or mismatched records are not upload candidates. Recheck the manifest
   for prohibited book/audio/voice/job/local-config content. Keep the source and
   privacy requirements in `CLAUDE.md`. Never upload other output or source data.
2. Read the destination folder and `Output/drive_uploads.json` if it exists.
   Skip an artifact hash already uploaded when its recorded Drive file remains
   present at the destination with the expected name and size. If an exact
   distribution name already exists after an interrupted run, verify its size
   and bytes before reusing it. Do not duplicate or overwrite an ambiguous file.
3. Upload the EXE using the receipt's `distribution_name` into the destination.
   Read its metadata back and verify its title, size and destination parent.
   Record the artifact hash, distribution name, file ID and observed URL in
   `Output/drive_uploads.json`. This local ledger must contain no credentials.
4. Only after replacement verification, create or reuse the destination's
   `Old, do not use` subfolder. Move earlier **Audiobook Studio installers of the
   same kind** into it using their verified current parent IDs. Keep the newest
   full installer and newest patch directly in the destination. Never move
   `hwmonitor_1.67.exe`, the PDF or voice folders, or unrelated files. Do not
   delete files or change sharing permissions. Verify the resulting folder list.
5. Upload or update `00_CURRENT_BETA.txt`, containing both current distribution
   names, versions, commits, byte sizes and SHA-256 values. Say these are beta
   candidates and exact-build installed-machine validation remains outstanding.
   Store its observed Drive file ID in the local ledger.

For retry safety, always inspect the folder even when the hash is in the ledger:
an interrupted run may have uploaded successfully but not yet archived old copies
or updated the guide. Finish those steps without reuploading the same binary.
If a transfer or verification fails, retain the previous usable files and report
the failure. Report completed handoff or a failure within the active build task.
Do not email testers or
publish a release as part of this workflow.
