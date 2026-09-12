# Graft indexing verification

Verified on Windows on 2026-09-12 with `@nanonets/graft` 0.16.0.

## Failure and repair

The reported path is `Output/ui-review/tmp31j_4qt8` (one directory name).
The managed Codex sandbox denies Node's `spawnSync("git", ...)` with EPERM.
Graft's `dist/ingest/fs.js` then falls back from Git enumeration to a recursive
filesystem walk. That fallback does not read `.gitignore`, so it enters ignored
`Output/` and fails to enumerate this protected temporary directory. Queries
catch the error and answer from the old graph, which contained only 41 files.

Running Graft with native Windows process access restores its Git enumeration.
The same Git subprocess returned status 0 and enumerated 75 visible files before
this report was added. The root `.gitignore` now explicitly excludes runtime
environments, build/test output, source/processed books, book sample directories,
voice samples, and additional ebook/audio formats. Existing exclusions cover
`Output/`, app jobs, app voices, audiobooks, tools, and private audition material.
Sample Python scripts and `samples/Modelfile` remain visible to Git.

No existing books, audio, output, environments, or permissions were changed.
The protected directory's attributes, creation time, and last-write time matched
before and after verification. Its ACL could not be read in the sandbox; no ACL
repair or permission change was attempted.

This is an execution-context and repository-exclusion repair. The globally
installed Graft package was not patched or upgraded. Its unsafe fallback remains
an upstream limitation: `.gitignore` cannot protect a filesystem walk that does
not consult Git. Graft commands in Codex must run outside the restrictive sandbox
when Node cannot spawn Git. Ordinary native Windows execution was verified.

## Full rebuild and coverage

`graft build --no-reuse` succeeded, reparsing every eligible file with zero cache
replays. The result contains 494 nodes, 1,191 edges, and 47 file cards.

| Source location | Python files indexed |
| --- | ---: |
| `app/` | 24 |
| `install/` | 3 |
| `samples/` | 5 |
| `tests/` | 14 |
| `setup.py` | 1 |
| Total | 47 |

An independent filesystem inventory, pruning ignored directories before descent,
matched both Git's visible Python file set and Graft's file nodes exactly. It used
NUL-delimited `git check-ignore` paths to avoid Windows stdin newline translation.
There were no missing Python files, extra indexed files, traversal errors, or
indexed files over Graft's 1,000,000-byte limit. The installed parser extension
list was checked; Python is the only supported source type present in this tree.

The six files missing from the old graph were `app/managed_runtime.py`,
`app/narration_eta.py`, `tests/gpu_narration_smoke.py`,
`tests/test_managed_runtime.py`, `tests/test_narration_eta.py`, and
`tests/test_patch_dependencies.py`. Changed definitions in older files were also
reparsed. `graft check` reports that the wiring graph is in sync.

Exclusion checks passed for the protected Output path, environments, runtime,
test temporary output, source/processed books, app jobs/voices, audiobooks,
all four book/voice sample directories, and loose EPUB/M4B files. No ignored
generated Python code or third-party environment packages appear in the graph.

## Automatic refresh proof

Using native process access, a new synthetic file at
`tests/graft_refresh_probe.py` was queried with `graft skeleton ... --json`:

1. Adding a function produced its file and function nodes automatically.
2. Changing its return value changed the indexed function body hash automatically.
3. Removing only this newly created probe removed both nodes automatically.

Each query reported `refreshed the graph (1 file changed) before answering`.
No manual build occurred between these steps. A final build regenerates the
markdown cards after the probe is removed. All 66 dependency-free application
tests also passed with the base Miniconda Python and project-local test temp root.

## Remaining coverage limits

| Files | Why they are outside the structural graph |
| --- | --- |
| `app/static/index.html` | No HTML parser; its embedded JavaScript and CSS are also absent |
| `install/AudiobookStudio.iss`, `install/AudiobookStudio_Patch.iss` | No Inno Setup parser |
| `Start_Audiobook_Studio.bat`, `setup.bat`, `install/build_installer.bat` | No batch parser |
| `app/config.example.json`, `opencode.json`, `.cursor/environment.json` | No JSON parser; dot directories are also skipped |
| `install/requirements-base.txt`, `install/requirements-chatterbox.txt` | No plain-text parser |
| `samples/Modelfile`, `app/VERSION` | No matching parser for these extensionless files |
| Markdown documents, including `.claude/skills/` | No Markdown structural parser; dot directories are also skipped |
| `.gitignore`, `.ignore`, `app/icon.ico` | Policy/configuration or binary asset, not parsed source |

Inspect these files directly when relevant. `graft grep` only searches indexed
files, so it cannot prove exhaustive coverage of the UI or installer behavior.
Adding unsupported extensions with `-e` does not add a parser.

Graft also excludes dot-prefixed paths, built-in dependency/build directories,
internal symlinks, and files larger than 1,000,000 bytes. A future source file in
one of those categories needs a separate coverage review. Git ignore rules do
not exclude already tracked files; never force-add private data.

Automatic queries refresh the structural graph and fingerprint, not markdown
cards. Run `graft build` to regenerate cards after edits. The optional LLM deep
layer was not built: 494 pending summaries are expected for this deterministic
build, not stale code. No compiler/LSP enrichment was requested; call edges are
parser-derived and cannot establish every dynamic Python call.

The generated `graft/` cache stays local and Git-ignored. Other checkouts must
run `graft build`; committing this policy does not distribute the local index.
