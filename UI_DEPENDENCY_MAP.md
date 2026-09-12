# Audiobook Studio UI dependency map

| Workflow | Screen/state | UI handler | API route | Backend operation | Verification evidence |
| --- | --- | --- | --- | --- | --- |
| Add and select PDF | Library, empty or populated | `uploadPdf`, `loadLibrary`, `openDlg` | `GET /api/library`, `POST /api/library/import` | `scan_library`, `import_pdf`, suggested path/start page | Observed source; isolated browser harness exercised empty/loading/error/import and modal entry. |
| Configure and queue audiobook | Creation dialog, queued | form submit, `createJob` | `POST /api/jobs` | voice, ffmpeg and GPU preflight; persist then `enqueue` | Observed source; isolated browser harness exercised range validation, keyboard submit, cancellation, and job failure feedback. |
| Extract then narrate | queued, extracting, tagging, narrating | `refreshJobs`, `renderJob` | `GET /api/jobs`, `GET /api/jobs/:id` | serial `worker_loop`, OCR then narration; GPU stages never overlap | Observed source plus fixture states; active narration rendered 73/160, 46%, ETA and named generation state. |
| Cancel and resume safely | running, canceled, failed, interrupted | `jobAction` | `POST /api/jobs/:id/cancel`, `/resume` | owned process cancellation; cached segments and blocks support resume | Observed source; unit coverage and isolated browser action calls. No real job was touched. |
| Inspect and recover job | all terminal and running states | log toggle, open output, cache cleanup, delete | job detail, `open-output`, `cleanup-cache`, `delete` | log tails, safe output-folder validation, cache-only deletion, job deletion | Observed source; isolated harness exercised log state and job actions. Completed cache cleanup/explorer remains an installed-runtime check. |
| Play and download | completed | audio element, `monitorDownload` | `GET/HEAD /api/jobs/:id/audio/:file` | range audio response and native-window Save dialog handoff | Observed source and download unit tests; pywebview 5.4 fixture opened the WAV Save As dialog, canceled without writes. |
| Download beta report | any job | `monitorDownload` | `GET/HEAD /api/jobs/:id/beta-log` | create ZIP with summary/log data only | Observed source and download unit tests; pywebview 5.4 fixture opened the report Save As dialog, canceled without writes. |
| Manage voices | Narrator voices, empty/populated/upload error | `loadVoices`, `uploadVoice`, delete action | `GET/POST /api/voices`, `POST /api/voices/:name/delete` | isolated chatterbox conversion; local WAV removal | Observed source; isolated browser harness exercised empty, upload error, refresh, and deletion feedback. |
| Missing ffmpeg recovery | creation dialog | `loadFfmpeg`, `installFfmpeg`, `renderFfmpeg` | `GET /api/ffmpeg`, `POST /api/ffmpeg/install` | report/install helper; server rejects M4B/MP3 if unavailable | Observed source; isolated harness exercised unavailable fallback and restored encoder options without downloading. |
| Theme and navigation | all screens, light/dark | `showScreen`, `setTheme` | none | browser-local preference only | Observed at browser and native 144 DPI, default and 900×600; persistence, focus, 200% text and narrow reflow passed. |

## Important transitions and uncertainties

`worker_loop` is the observed serialization boundary. It runs extraction before narration and accepts only one queued job at a time, preserving the OCR/TTS GPU separation. A resumed job keeps `blocks.json`, so normal resume does not re-extract. The browser has no engine selector; the API omits `engine`, letting the backend default control it. The exposed blocks route has no current UI consumer.

This map covers observed routes and symbols. Rendered browser/native evidence and remaining installed-runtime limits are recorded in `UI_VERIFICATION.md`.
