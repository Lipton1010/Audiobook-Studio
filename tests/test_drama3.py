import hashlib
import json
from contextlib import ExitStack
from pathlib import Path
import sys
import tempfile
import types
import unittest
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "app"))
import drama3 as d
from generation_settings import normalize_settings, runtime_settings
from vibevoice_plan import load_plan

try:
    import numpy as np
    import soundfile as sf
    import vibevoice_worker as w
    import vibevoice_phases as phases
except ModuleNotFoundError:
    w = None


class DramaSettingsTests(unittest.TestCase):
    def test_new_job_api_defaults_to_drama_and_honors_explicit_legacy_choice(self):
        try:
            import fitz
        except ImportError:
            sys.modules.setdefault("fitz", types.ModuleType("fitz"))
        import server
        root = Path(__file__).resolve().parents[1] / ".test-tmp"
        root.mkdir(exist_ok=True)
        with tempfile.TemporaryDirectory(dir=root) as temporary, ExitStack() as stack:
            stack.enter_context(mock.patch.object(server, "JOBS_DIR", Path(temporary)))
            for name, value in {"missing_voice_error": None, "missing_drama3_error": None,
                                "missing_vibevoice_error": None, "missing_ffmpeg_error": None,
                                "missing_gpu_error": None, "page_count": 1, "save_state": True,
                                "log_line": None, "enqueue": None}.items():
                stack.enter_context(mock.patch.object(server, name, return_value=value))
            response = stack.enter_context(mock.patch.object(server, "_json_response"))
            handler = object.__new__(server.Handler)
            handler.path = "/api/jobs"
            for requested, expected in ((None, "drama3"), ("vibevoice", "vibevoice")):
                body = {"pdf_path": str(Path(temporary) / "synthetic.pdf"), "path": "A", "format": "wav"}
                if requested:
                    body["backend"] = requested
                handler._read_json = lambda: body
                handler.do_POST()
                state = response.call_args.args[1]
                self.assertEqual(state["backend"], expected)
                self.assertEqual(state["status"], "queued")
                self.assertEqual("max_frames" in state["generation_settings"], expected == "drama3")

    def test_settings_use_native_sampling_and_bound_memory(self):
        settings = runtime_settings("drama3", "A")
        self.assertEqual((settings["max_frames"], settings["context_length"]), (1536, 4096))
        self.assertNotIn("cfg_scale", settings)
        self.assertEqual(normalize_settings('drama3', 'A', {'max_frames': 1536})['max_frames'], 1536)
        for values in ({"ddpm_steps": 20}, {"max_frames": 1537}, {"context_length": 4097},
                       {"top_p": float("nan")}, {"temperature": True}, {"seed": -1}):
            with self.assertRaises(ValueError):
                normalize_settings("drama3", "A", values)

    def test_explicit_dispatch_keeps_historical_jobs_on_their_backend(self):
        try:
            import fitz
        except ImportError:
            sys.modules.setdefault("fitz", types.ModuleType("fitz"))
        import server
        self.assertEqual(server.narration_backend({}), "chatterbox")
        self.assertEqual(server.narration_backend({"backend": "vibevoice"}), "vibevoice")
        self.assertEqual(server.narration_backend({"backend": "drama3"}), "drama3")
        state = {"id": "sample", "backend": "drama3", "path": "B"}
        with mock.patch.object(server.visual_review, "project", return_value=([{"text": "Test."}], [], [], [])), \
             mock.patch.object(server.visual_review, "_write"), mock.patch.object(server, "_release_ocr") as release, \
             mock.patch.object(server, "_run_drama3_narration") as narrate:
            server.run_narration(state)
            release.assert_called_once()
            narrate.assert_called_once()


@unittest.skipUnless(w is not None, "requires narration audio dependencies")
class DramaRuntimeTests(unittest.TestCase):
    def test_exact_source_corrections_preserve_plan_and_unaffected_unit_identities(self):
        parent = self.plan['passages'][1]
        before = w._units_for_parent(parent, self.config)
        correction = {'parent_identity':parent['identity'], 'start':0, 'end':18,
                      'before':'The careful keeper', 'after':'The keeper',
                      'source_pages':[1], 'evidence':'Synthetic source correction'}
        changed = {**self.config, 'spoken_projection':{**self.config['spoken_projection'], 'corrections':[correction]}}
        d.validate_plan(self.plan, changed)
        self.assertEqual(d.write_plan(self.job, self.blocks, changed), self.plan)
        self.assertEqual(load_plan(self.job)[0], self.plan)
        after = w._units_for_parent(parent, changed)
        self.assertEqual([u['identity'] for u in before], [u['identity'] for u in after])
        self.assertEqual(sum(a.get('spoken_text',a['text']) != b.get('spoken_text',b['text']) for a,b in zip(before,after)), 1)
        for field, value in [('parent_identity','unknown'), ('before','stale'), ('evidence','')]:
            invalid = {**changed, 'spoken_projection':{**changed['spoken_projection'], 'corrections':[{**correction,field:value}]}}
            with self.assertRaises(ValueError):
                d.validate_plan(self.plan, invalid)
        invalid = {**changed, 'spoken_projection':{**changed['spoken_projection'], 'version':'unknown'}}
        with self.assertRaises(ValueError):
            d.validate_plan(self.plan, invalid)

    def setUp(self):
        root = Path(__file__).resolve().parents[1] / ".test-tmp"
        root.mkdir(exist_ok=True)
        temp = tempfile.TemporaryDirectory(dir=root)
        self.addCleanup(temp.cleanup)
        self.job = Path(temp.name)
        exe, model, dll = [self.job / name for name in ("native.exe", "model.gguf", "cuda.dll")]
        for path in (exe, model, dll):
            path.write_bytes(path.name.encode())
        for key, value in (("EXE_SHA256", d.sha256_file(exe)), ("MODEL_SHA256", d.sha256_file(model))):
            patch = mock.patch.object(d, key, value)
            patch.start()
            self.addCleanup(patch.stop)
        voice = self.job / "voice.wav"
        sf.write(str(voice), np.sin(np.arange(44100) * .07) * .1, 44100)
        self.config = dict(backend="drama3", drama3_executable=str(exe), drama3_model=str(model),
                           drama3_cuda_bin=str(self.job), reference_wav=str(voice), reference_text="A voice reference.",
                           source_voice_sha256=d.sha256_file(voice), path="A", title="Synthetic", format="wav")
        text = "The careful keeper put the silver lantern beside the wooden door and walked home. "
        self.blocks = [{"type": "heading", "text": "CHAPTER ONE", "source_pages": [1]},
                       {"type": "body", "text": text * 9, "source_pages": [1]}]
        self.plan = d.write_plan(self.job, self.blocks, self.config)
        self.plan, self.config = load_plan(self.job)
        for folder in (self.job / w.SEGMENTS_DIR, self.job / w.REJECTED_DIR,
                       self.job / w.SEGMENTS_DIR / w.UNITS_DIR, self.job / w.SEGMENTS_DIR / phases.PENDING_DIR,
                       self.job / w.SEGMENTS_DIR / w.narration_review.CANDIDATES_DIR):
            folder.mkdir(exist_ok=True)

    def row(self, parent_index=1):
        unit = w._profiled_unit(w._units_for_parent(self.plan["passages"][parent_index], self.config)[0])
        folder = self.job / "native_output"
        folder.mkdir(exist_ok=True)
        row = dict(unit=unit, attempt=1, status="rendering", basis=None,
                   audio=str(w._wav_path(self.job / w.SEGMENTS_DIR / phases.PENDING_DIR, unit["index"])))
        row["native_run"] = {"folder": str(folder), "request": d._request(row, self.config, folder)}
        phases._save(self.job, row)
        return row

    def output(self, row, frames=10, rate=44100, text=None):
        run = row["native_run"]
        folder = Path(run["folder"]) / "audio"
        request = run["request"]
        codes = folder / request["id"] / "drama3_take.json"
        codes.parent.mkdir(parents=True, exist_ok=True)
        take = {"text": request["text"] if text is None else text, "vq_codes": [[17] * frames for _ in range(10)]}
        payload = json.dumps(take).encode()
        d.write(codes, {"kind": "acoustic_tokens", "bytes": len(payload), "meta": {"family": "fish_drama3", "schema": "drama3_take_v1"}, "payload_hex": payload.hex()})
        sf.write(str(folder / (request["id"] + ".wav")), np.sin(np.arange(frames * 2048) * .07) * .1, rate)
        return codes

    def test_plan_binds_native_assets_voice_text_and_sampling(self):
        self.assertEqual(self.plan["runtime"]["sample_rate"], 44100)
        self.assertNotIn("cfg_scale", self.plan["runtime"])
        d.write_plan(self.job, self.blocks, self.config)
        for key, value in (("reference_text", "Changed."), ("source_voice_sha256", "changed")):
            changed = {**self.config, key: value}
            with self.assertRaises(ValueError):
                d.validate_plan(self.plan, changed)
        changed = {**self.config, "generation_settings": {**self.config["generation_settings"], "seed": 44}}
        with self.assertRaises(ValueError):
            d.write_plan(self.job, self.blocks, changed)
        Path(self.config["drama3_model"]).write_bytes(b"different weights")
        with self.assertRaisesRegex(ValueError, "assets changed"):
            load_plan(self.job)

    def test_new_plans_leave_memory_and_duration_headroom(self):
        self.assertEqual(self.plan['runtime']['cpu_expert_layers'], 12)
        self.assertEqual(self.plan['runtime']['unit_policy'], 'intact_75_100_sentences_v4')
        self.assertIn('fish_drama3.cpu_expert_layers=12',
                      d.command(self.config, self.job/'requests.json', self.job))
        units = w._units_for_parent(self.plan['passages'][1], self.config)
        self.assertTrue(all(unit['text'].endswith('.') for unit in units))
        self.assertTrue(any(len(unit['text'].split()) > 55 for unit in units))
        self.assertEqual(' '.join(unit['text'] for unit in units), self.plan['passages'][1]['text'])
        changed = {**self.config, 'drama3_cpu_expert_layers': 0}
        with self.assertRaises(ValueError):
            d.validate_plan(self.plan, changed)

    def test_numbered_heading_uses_strict_bounded_retry_before_listening(self):
        parent = {**self.plan['passages'][0], 'text': '01: ARRIVAL', 'heading': '01: ARRIVAL'}
        self.plan['passages'][0] = parent
        units = w._units_for_parent(parent, self.config)
        row = self.row(parent_index=0)
        self.output(row)
        self.assertTrue(d._harvest(self.job, row, self.config))
        report = self.job / 'heading_check.json'
        d.write(report, {'transcript': 'On one.', 'generation': row['generation']})
        row['unit'].pop('numbered_heading', None)  # Pending take saved before the checker fix.
        row.update(status='checked', report=str(report))
        phases._save(self.job, row)

        phases._resolve(self.job, parent, units, self.config)

        pending = phases._pending(self.job, units[0])
        self.assertIsNotNone(pending)
        self.assertEqual(pending['status'], 'retry')
        self.assertEqual(w.narration_review.entries(self.job), [])
        self.assertTrue(Path(pending['last_candidate']['audio']).exists())
        self.assertTrue(w.unit_assessment(units[0], {'transcript': 'One. Arrival.'})['ok'])
        self.assertFalse(w.unit_assessment(units[0], {'transcript': 'Arrival.'})['ok'])

        pending['attempt'] = 3
        pending['status'] = 'checked'
        pending['audio'] = pending['last_candidate']['audio']
        phases._save(self.job, pending)
        phases._resolve(self.job, parent, units, self.config)
        self.assertIsNone(phases._pending(self.job, units[0]))
        self.assertEqual(len(w.narration_review.entries(self.job)), 1)

    def test_critical_wording_uses_bounded_retry_before_listening(self):
        text = 'She followed the narrow trail through the forest and waited beside the old wooden bridge until morning.'
        parent = {**self.plan['passages'][0], 'text': text, 'heading': None}
        self.plan['passages'][0] = parent
        units = w._units_for_parent(parent, self.config)
        row = self.row(parent_index=0)
        self.output(row)
        self.assertTrue(d._harvest(self.job, row, self.config))
        report = self.job / 'wording_check.json'
        d.write(report, {'transcript': text.replace('She', 'He'), 'generation': row['generation']})
        self.assertTrue(w.unit_assessment(units[0], d.read(report))['review_required'])
        row.update(status='checked', report=str(report))
        phases._save(self.job, row)

        phases._resolve(self.job, parent, units, self.config)

        pending = phases._pending(self.job, units[0])
        self.assertIsNotNone(pending)
        self.assertEqual(pending['status'], 'retry')
        self.assertEqual(w.narration_review.entries(self.job), [])
        self.assertTrue(Path(pending['last_candidate']['audio']).exists())
        pending.update(attempt=3, status='checked', audio=pending['last_candidate']['audio'])
        phases._save(self.job, pending)
        phases._resolve(self.job, parent, units, self.config)
        self.assertIsNone(phases._pending(self.job, units[0]))
        self.assertEqual(len(w.narration_review.entries(self.job)), 1)
        self.assertFalse(w._valid_unit(self.job / w.SEGMENTS_DIR / w.UNITS_DIR, units[0]))

    def test_dense_lists_end_at_existing_punctuation_without_losing_names(self):
        parent = {**self.plan['passages'][1], 'text': 'Alice Example; Robert F. Smith; ' * 40}
        units = w._units_for_parent(parent, self.config)
        self.assertTrue(all(unit['text'].endswith(';') for unit in units))
        self.assertTrue(all(len(unit['text']) <= d.MAX_TEXT_CHARS for unit in units))
        self.assertEqual(' '.join(unit['text'] for unit in units), parent['text'].strip())

    def test_indivisible_sentence_exceeding_native_limit_requires_review(self):
        parent = {**self.plan['passages'][1], 'text': ' '.join(['unbroken'] * 200) + '.'}
        with self.assertRaisesRegex(ValueError, 'sentence exceeding.*kept intact'):
            w._units_for_parent(parent, self.config)

    def test_existing_plans_keep_original_render_limits(self):
        legacy = dict(self.config)
        legacy.pop('drama3_cpu_expert_layers', None)
        legacy.pop('drama3_unit_limits', None)
        legacy.pop('drama3_list_max_words', None)
        legacy['unit_boundary_policy'] = 'initials_v2'
        self.assertEqual(d.runtime_profile(legacy)['cpu_expert_layers'], 0)
        self.assertEqual(d.runtime_profile(legacy)['unit_policy'], 'intact_55_75_initials_v2')
        self.assertIn('fish_drama3.cpu_expert_layers=0',
                      d.command(legacy, self.job/'requests.json', self.job))

    def test_resuming_legacy_plan_does_not_switch_sentence_policy(self):
        legacy_job = self.job / 'legacy'
        legacy_job.mkdir()
        legacy_config = {**self.config, 'unit_boundary_policy': 'initials_v2',
                         'drama3_unit_limits': {'target_words': 40, 'max_words': 55},
                         'drama3_list_max_words': 35, 'drama3_cpu_expert_layers': 4,
                         'generation_settings': {**self.config['generation_settings'], 'max_frames': 768, 'context_length': 2048}}
        old = d.write_plan(legacy_job, self.blocks, legacy_config)
        before = (legacy_job / 'vibevoice_plan.json').read_bytes()
        resumed = dict(d.read(legacy_job / 'vibevoice_config.json'))
        resumed.pop('unit_boundary_policy')
        d.write_plan(legacy_job, self.blocks, resumed)
        self.assertEqual((legacy_job / 'vibevoice_plan.json').read_bytes(), before)
        self.assertEqual(old['runtime']['unit_policy'], 'intact_40_55_initials_v2_lists35')
        self.assertEqual(d.read(legacy_job / 'vibevoice_config.json')['generation_settings']['max_frames'], 768)
        self.assertEqual(d.read(legacy_job / 'vibevoice_config.json')['generation_settings']['context_length'], 2048)
        self.assertEqual(d.read(legacy_job / 'vibevoice_config.json')['drama3_cpu_expert_layers'], 4)

    def test_explicit_resource_migration_preserves_frozen_plan_and_rejects_other_changes(self):
        import copy
        import hashlib
        legacy_job = self.job / 'capacity_migration'
        legacy_job.mkdir()
        old = {**self.config, 'unit_boundary_policy': 'initials_v2', 'drama3_cpu_expert_layers': 4,
               'generation_settings': {**self.config['generation_settings'], 'max_frames': 768, 'context_length': 2048}}
        plan = d.write_plan(legacy_job, self.blocks, old)
        config = d.read(legacy_job / 'vibevoice_config.json')
        config['generation_settings'].update(max_frames=1536, context_length=4096)
        config['drama3_cpu_expert_layers'] = 12
        with self.assertRaisesRegex(ValueError, 'generation settings changed'):
            d.validate_plan(plan, config)
        keys = ('max_frames', 'context_length', 'cpu_expert_layers')
        current = d.runtime_profile(config)
        config['drama3_resource_migration'] = {
            'source_runtime_identity': hashlib.sha256(json.dumps(plan['runtime'], sort_keys=True).encode()).hexdigest(),
            'previous_limits': {key: plan['runtime'][key] for key in keys},
            'limits': {key: current[key] for key in keys}}
        before = (legacy_job / 'vibevoice_plan.json').read_bytes()
        d.validate_plan(plan, config)
        d.write_plan(legacy_job, self.blocks, config)
        self.assertEqual((legacy_job / 'vibevoice_plan.json').read_bytes(), before)
        changed = copy.deepcopy(config)
        changed['generation_settings']['temperature'] = 0.5
        with self.assertRaisesRegex(ValueError, 'generation settings changed'):
            d.validate_plan(plan, changed)
        changed = copy.deepcopy(config)
        changed['drama3_resource_migration']['previous_limits']['max_frames'] = 1024
        with self.assertRaisesRegex(ValueError, 'resource migration'):
            d.validate_plan(plan, changed)

    def test_complete_request_survives_interruption_without_rendering_again(self):
        row = self.row()
        self.output(row)
        d.recover(self.job, self.plan, self.config)
        saved = phases._pending(self.job, row["unit"])
        self.assertEqual((saved["status"], saved["attempt"]), ("ready", 1))
        info = sf.info(saved["audio"])
        self.assertEqual((info.samplerate, info.channels, info.frames), (44100, 1, 20480))
        audio_hash = d.sha256_file(saved["audio"])
        d.recover(self.job, self.plan, self.config)
        self.assertEqual(d.sha256_file(saved["audio"]), audio_hash)
        Path(saved["generation"]["codes"]).write_text("broken", encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "changed"):
            phases._pending(self.job, row["unit"])

    def test_empty_native_request_retries_without_stopping_later_audio(self):
        rows = phases._schedule(self.job, self.plan, self.config)[:2]
        calls = []

        def native_process(command, **kwargs):
            calls.append(command)
            if len(calls) == 1:
                kwargs["stdout"].write("audiocpp_cli failed: Drama 3 ended before producing an audio frame\n")
                kwargs["stdout"].flush()
                code = 1
            else:
                self.output(rows[1])
                code = 0
            return mock.Mock(returncode=code, poll=mock.Mock(return_value=code),
                             wait=mock.Mock(return_value=code))

        with mock.patch.object(phases, "_phase_rows", return_value=rows), \
             mock.patch.object(w, "_assert_no_ocr"), \
             mock.patch.object(d, "BATCH_SIZE", 1), \
             mock.patch.object(d, "WindowsWorkerJob"), \
             mock.patch.object(d.subprocess, "Popen", side_effect=native_process):
            d.render_phase(self.job, self.plan, self.config)

        failed = phases._pending(self.job, rows[0]["unit"])
        following = phases._pending(self.job, rows[1]["unit"])
        self.assertEqual((failed["status"], failed["attempt"]), ("retry", 1))
        self.assertEqual((following["status"], following["attempt"]), ("ready", 1))
        self.assertEqual(len(calls), 2)
        self.assertFalse(Path(failed["audio"]).exists())
        self.assertTrue(Path(following["audio"]).is_file())

    def native_process(self, fail_until, seen):
        def launch(command, **kwargs):
            requests = d.read(command[command.index("--request-sequence") + 1])
            code = 0
            for request in requests:
                index, attempt = map(int, request["id"].split("_")[1:])
                seen.append((index, attempt, request["seed"]))
                if attempt <= fail_until.get(index, 0):
                    kwargs["stdout"].write("audiocpp_cli failed: Drama 3 ended before producing an audio frame\n")
                    kwargs["stdout"].flush()
                    code = 1
                    break
                row = d.read(w._receipt_path(self.job / w.SEGMENTS_DIR / phases.PENDING_DIR, index))
                self.output(row)
            return mock.Mock(returncode=code, poll=mock.Mock(return_value=code),
                             wait=mock.Mock(return_value=code))
        return launch

    def test_empty_request_keeps_completed_prefix_and_unstarted_attempts(self):
        rows = phases._schedule(self.job, self.plan, self.config)
        self.assertGreaterEqual(len(rows), 3)
        failed_index = rows[1]["unit"]["index"]
        seen = []
        with mock.patch.object(w, "_assert_no_ocr"), \
             mock.patch.object(d, "WindowsWorkerJob") as owner, \
             mock.patch.object(d.subprocess, "Popen", side_effect=self.native_process({failed_index: 1}, seen)):
            d.render_phase(self.job, self.plan, self.config)
        self.assertEqual([(index, attempt) for index, attempt, _ in seen],
                         [(r["unit"]["index"], 1) for r in rows])
        self.assertEqual(owner.return_value.close.call_count, 2)
        for row in rows:
            saved = phases._pending(self.job, row["unit"])
            self.assertEqual(saved["status"], "retry" if row["unit"]["index"] == failed_index else "ready")
            self.assertEqual(len(saved.get("failures", [])), int(row["unit"]["index"] == failed_index))
        retry = next(r for r in phases._schedule(self.job, self.plan, self.config)
                     if r["unit"]["index"] == failed_index)
        self.assertEqual(retry["attempt"], 2)
        self.assertEqual(d._request(retry, self.config, self.job)["seed"], seen[1][2] + 1)

    def test_native_runtime_errors_and_incomplete_artifacts_still_stop(self):
        empty_error = "audiocpp_cli failed: Drama 3 ended before producing an audio frame\n"
        for code, message, partial in ((1, "CUDA out of memory\n", False),
                                       (1, empty_error + "unexpected runtime failure\n", False),
                                       (2, empty_error, False), (0, "", False),
                                       (1, empty_error, True)):
            with self.subTest(code=code, message=message, partial=partial):
                rows = phases._schedule(self.job, self.plan, self.config)[:1]
                row = rows[0]
                row["status"] = "render"
                row["attempt"] = 1
                phases._save(self.job, row)

                def launch(command, **kwargs):
                    kwargs["stdout"].write(message)
                    kwargs["stdout"].flush()
                    if partial:
                        self.output(row).write_text("incomplete", encoding="utf-8")
                    return mock.Mock(returncode=code, poll=mock.Mock(return_value=code),
                                     wait=mock.Mock(return_value=code))

                with mock.patch.object(phases, "_phase_rows", return_value=[row]), \
                     mock.patch.object(w, "_assert_no_ocr"), \
                     mock.patch.object(d, "WindowsWorkerJob"), \
                     mock.patch.object(d.subprocess, "Popen", side_effect=launch):
                    with self.assertRaisesRegex(RuntimeError, "native process failed"):
                        d.render_phase(self.job, self.plan, self.config)

    def test_empty_native_retry_budget_finishes_peers_but_blocks_missing_audio(self):
        rows = phases._schedule(self.job, self.plan, self.config)
        failed_index = rows[1]["unit"]["index"]
        seen = []

        def phase(job, config, name):
            if name == "render":
                phases.render_phase(job, self.plan, config)
            else:
                phases.check_phase(job, self.plan, config)

        def transcribe(batch):
            return [r["unit"].get("spoken_text", r["unit"]["text"]) for r in batch]

        with mock.patch.object(phases, "parakeet_setup_error", return_value=None), \
             mock.patch.object(phases, "_run_phase", side_effect=phase), \
             mock.patch.object(phases, "load_transcriber", return_value=transcribe), \
             mock.patch.object(w, "_assert_no_ocr"), \
             mock.patch.object(d, "WindowsWorkerJob"), \
             mock.patch.object(d.subprocess, "Popen", side_effect=self.native_process({failed_index: 99}, seen)):
            with self.assertRaisesRegex(RuntimeError, "1 clip.*exhausted rendering attempts"):
                phases.run_generate(self.job)

        self.assertEqual([attempt for index, attempt, _ in seen if index == failed_index], [1, 2, 3])
        for row in rows:
            if row["unit"]["index"] != failed_index:
                self.assertEqual(sum(index == row["unit"]["index"] for index, _, _ in seen), 1)
                self.assertTrue(w._valid_unit(self.job / w.SEGMENTS_DIR / w.UNITS_DIR, row["unit"]))
        missing = phases._pending(self.job, rows[1]["unit"])
        self.assertEqual(missing["status"], "failed")
        self.assertFalse(Path(missing["audio"]).exists())

    def test_cancel_during_empty_take_stops_before_starting_another_batch(self):
        rows = phases._schedule(self.job, self.plan, self.config)
        launch = self.native_process({rows[0]["unit"]["index"]: 1}, [])

        def canceled_process(command, **kwargs):
            process = launch(command, **kwargs)
            (self.job / "cancel_flag.txt").touch()
            return process

        with mock.patch.object(w, "_assert_no_ocr"), \
             mock.patch.object(d, "WindowsWorkerJob") as owner, \
             mock.patch.object(d.subprocess, "Popen", side_effect=canceled_process) as native:
            with self.assertRaises(SystemExit) as raised:
                d.render_phase(self.job, self.plan, self.config)
        self.assertEqual(raised.exception.code, 2)
        native.assert_called_once()
        owner.return_value.close.assert_called_once()

    def test_partial_output_keeps_attempt_and_capped_output_never_becomes_ready(self):
        row = self.row()
        codes = self.output(row)
        codes.write_text('{"payload_hex":', encoding="utf-8")
        d.recover(self.job, self.plan, self.config)
        saved = phases._pending(self.job, row["unit"])
        self.assertEqual((saved["status"], saved["attempt"]), ("render", 1))
        self.output(row, frames=row['native_run']['request']['max_tokens'])
        self.assertTrue(d._harvest(self.job, row, self.config))
        self.assertEqual(row["status"], "retry")
        self.assertFalse(Path(row["audio"]).exists())

    def test_wrong_rate_and_mismatched_code_text_cannot_be_reused(self):
        row = self.row()
        self.output(row, rate=24000)
        self.assertFalse(d._harvest(self.job, row, self.config))
        self.output(row, text="A different passage.")
        self.assertFalse(d._harvest(self.job, row, self.config))

    def test_history_is_unwrapped_and_binds_both_audio_and_codes(self):
        row = self.row()
        self.output(row)
        d._harvest(self.job, row, self.config)
        config = {**self.config, "drama3_history": {str(row["unit"]["index"]): row["generation"]}}
        request = d._request(row, config, self.job)
        history = d.read(request["previous_takes_file"])
        self.assertEqual(len(history[0]["vq_codes"]), 10)
        self.assertNotIn("payload_hex", history[0])
        Path(row["generation"]["raw_wav"]).write_bytes(b"changed")
        with self.assertRaisesRegex(ValueError, "changed"):
            d._request(row, config, self.job)

    def test_manual_retry_uses_new_seed_and_resume_keeps_it(self):
        row = self.row()
        self.output(row)
        d._harvest(self.job, row, self.config)
        unit = row["unit"]
        old_seed = row["native_run"]["request"]["seed"]
        report = self.job / "check.json"
        d.write(report, {"transcript": unit["text"], "generation": row["generation"]})
        folder = self.job / w.SEGMENTS_DIR / w.UNITS_DIR
        w._publish_unit(folder, unit, Path(row["audio"]), report, 1)
        path = w._receipt_path(folder, unit["index"])
        receipt = d.read(path)
        receipt["force_regenerate"] = True
        d.write(path, receipt)
        w._receipt_path(folder.parent / phases.PENDING_DIR, unit["index"]).unlink()
        scheduled = phases._schedule(self.job, self.plan, self.config)
        replacement = next(r for r in scheduled if r["unit"]["index"] == unit["index"])
        seed = d._request(replacement, self.config, self.job)["seed"]
        self.assertNotEqual(seed, old_seed)
        resumed = next(r for r in phases._schedule(self.job, self.plan, self.config)
                       if r["unit"]["index"] == unit["index"])
        self.assertEqual(d._request(resumed, self.config, self.job)["seed"], seed)

    def test_new_projection_is_bound_without_rewriting_original_text(self):
        self.assertEqual(self.config["spoken_projection"]["version"], w.delivery.PROJECTION_VERSION)
        self.assertEqual(self.plan["runtime"]["spoken_projection"], self.config["spoken_projection"])
        self.assertEqual(self.plan["passages"][1]["text"], self.blocks[1]["text"].strip())
        changed = {**self.config, "spoken_projection": {}}
        with self.assertRaisesRegex(ValueError, "conditioning"):
            d.validate_plan(self.plan, changed)

    def test_replacement_waits_for_listening_and_preserves_original(self):
        row = self.row()
        self.output(row)
        d._harvest(self.job, row, self.config)
        unit = row["unit"]
        report = self.job / "check.json"
        d.write(report, {"transcript": unit["text"], "generation": row["generation"]})
        folder = self.job / w.SEGMENTS_DIR / w.UNITS_DIR
        w._publish_unit(folder, unit, Path(row["audio"]), report, 1)
        accepted = w._wav_path(folder, unit["index"])
        original = accepted.read_bytes()
        path = w._receipt_path(folder, unit["index"])
        receipt = d.read(path)
        receipt["listening_approval"] = w.narration_review.fingerprint(receipt)
        receipt["force_regenerate"] = True
        d.write(path, receipt)
        row["basis"] = phases._basis(folder, unit)
        self.output(row, frames=12)
        d._harvest(self.job, row, self.config)
        replacement_report = self.job / "replacement.json"
        d.write(replacement_report, {"transcript": unit["text"], "generation": row["generation"]})
        row.update(status="checked", report=str(replacement_report))
        phases._save(self.job, row)
        parent = self.plan["passages"][1]
        phases._resolve(self.job, parent, w._units_for_parent(parent, self.config), self.config)
        self.assertEqual(accepted.read_bytes(), original)
        detail = w.narration_review.detail(self.job)
        self.assertEqual(detail["unresolved_count"], 1)
        self.assertIsNone(detail["items"][0]["decision"])

    def test_parent_assembly_preserves_rate_duration_and_interior_pcm(self):
        parent = self.plan["passages"][1]
        units = w._units_for_parent(parent, self.config)
        folder = self.job / w.SEGMENTS_DIR / w.UNITS_DIR
        pcm = (np.sin(np.arange(44100) * .07) * .1).astype(np.float32)
        for unit in units:
            sf.write(str(w._wav_path(folder, unit["index"])), pcm, 44100, subtype="PCM_16")
        with mock.patch.object(w, "_unit_report", return_value={"transcript": parent["text"]}):
            w._assemble_parent_from_units(parent, units, folder, folder.parent, {"ok": True})
        audio, rate = sf.read(str(w._wav_path(folder.parent, parent["index"])), dtype="float32")
        self.assertEqual((rate, len(audio)), (44100, 44100 * len(units)))
        first, _ = sf.read(str(w._wav_path(folder, units[0]["index"])), dtype="float32")
        np.testing.assert_array_equal(audio[300:43800], first[300:43800])
        sf.write(str(w._wav_path(folder, units[-1]["index"])), pcm, 24000)
        with self.assertRaisesRegex(RuntimeError, "44100"):
            w._assemble_parent_from_units(parent, units, folder, folder.parent, {"ok": True})


if __name__ == "__main__":
    unittest.main()
