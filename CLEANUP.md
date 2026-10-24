# Completed-job storage cleanup

After a new job finishes and its audiobook is published, Storybird validates the
finished audio with a complete CPU decode and verifies the library copy. It then
saves `cleanup_preview.json` and displays the estimated reclaimable space. This
step is automatic; it removes nothing. Existing historical jobs are not swept.

Use **Review cleanup** on a completed job to refresh its preview. The explicit
confirmation permanently removes only the exact previewed working WAVs and
`drama3_runs/*/native.log` files. The server rechecks completion, review state,
finished audio, file identities and hashes before removing its first file. A
changed or stale preview must be reviewed again. This action needs no GPU.

Original PDFs/text, model weights, selected voices/references, final job and
library audio, cover/chapter metadata, extraction, JSON plans/receipts and the
main job log are retained. Reference aliases/hardlinks are protected by file
identity. Symbolic links and junctions in a cleanup scope are refused. Failed,
unfinished or unresolved-review jobs cannot be cleaned.

There is no scheduled purge or automatic permanent deletion. Working audio and
resume material remain indefinitely until the user chooses cleanup. After that
choice, clip-level repair/resume will require rendering new audio. The approved
scope and actual removals are retained in `cleanup_history/`; this is an audit
record, not a backup or an undo mechanism. Partial failures retain their removal
record and leave unremoved files available for a new preview.

The preview reports logical bytes and estimated allocated space separately.
Hardlinked files with other links are not counted as reclaimable physical space.
Historical experiment folders and unused model variants require a separate
explicit file manifest; job cleanup never traverses model stores or `Output/`.

API: `POST /api/jobs/{id}/cleanup-working-files` with `{"preview": true}` returns the plan.
The distinct endpoint prevents a new page from accidentally invoking an old server's
immediate deletion handler before restart. An old server returns404 and the page
asks for restart without sending a request to the legacy deletion endpoint.
Only `{"confirmed": true, "preview_token": "..."}` can apply that current plan.
On the updated server, legacy `cleanup-cache` requests with no confirmation cannot remove files. Normal application
restart is required to load source changes; no installer or release is implied.
