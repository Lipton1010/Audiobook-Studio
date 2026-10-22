import hashlib
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "app"))
try:
    import numpy as np
    import soundfile as sf
    import vibevoice_phases as phases
    import vibevoice_worker as w
except ModuleNotFoundError:
    phases = None


@unittest.skipUnless(phases is not None, "requires narration runtime dependencies")
class PhasedNarrationTests(unittest.TestCase):
    def test_parent_only_failure_does_not_schedule_passing_units(self):
        parent, units = self._saved_parent_with_residual_errors()
        folder = self.job / w.SEGMENTS_DIR / w.UNITS_DIR
        before = {u['index']: w.sha256_file(w._wav_path(folder, u['index'])) for u in units}
        for unit in units:
            path = w._receipt_path(folder, unit['index'])
            saved = phases._read(path)
            saved.update(attempt=1, needs_repair=False)
            w._write_json(path, saved)
        self.assertEqual(phases._schedule(self.job, self.plan, self.config), [])
        self.assertTrue(w.narration_review.detail(self.job, parent['index'])['unresolved_count'])
        self.assertEqual(before, {u['index']: w.sha256_file(w._wav_path(folder, u['index'])) for u in units})

    def test_short_semantic_failure_is_reviewed_without_repeated_generation(self):
        text = 'The keeper did not enter the room.'
        self.plan['passages'][0].update(text=text, text_sha256=hashlib.sha256(text.encode()).hexdigest())
        w._write_json(self.job / 'vibevoice_plan.json', self.plan)
        def phase(job, config, name):
            self.phase(job, config, name)
            if name == 'check':
                for row in phases._phase_rows(job, self.plan, config, 'checked'):
                    if row['unit']['index'] == 0:
                        w._write_json(Path(row['report']), {'transcript': text.replace('not ', '')})
        with mock.patch.object(phases, '_run_phase', side_effect=phase):
            with self.assertRaises(w.narration_review.ListeningRequired):
                phases.run_generate(self.job)
        self.assertEqual(self.events, [('render', [0, 10000]), ('check', [0, 10000])])
        self.assertTrue(w.narration_review.detail(self.job, 0)['unresolved_count'])

    def test_new_critical_rule_holds_cached_audio_without_rendering(self):
        self.run_worker()
        parent = self.plan['passages'][0]
        unit = w._units_for_parent(parent, self.config)[0]
        folder = self.job / w.SEGMENTS_DIR / w.UNITS_DIR
        path = w._receipt_path(folder, unit['index'])
        receipt = phases._read(path)
        report = Path(receipt['quality_report'])
        payload = phases._read(report)
        payload['transcript'] = unit['text'] + ' never'
        w._write_json(report, payload)
        receipt['report_sha256'] = w.sha256_file(report)
        w._write_json(path, receipt)
        before = w.sha256_file(w._wav_path(folder, unit['index']))
        parent_receipt = w._receipt_path(folder.parent, parent['index'])
        saved = phases._read(parent_receipt)
        saved['force_regenerate'] = True
        w._write_json(parent_receipt, saved)
        with mock.patch.object(phases, '_run_phase') as render:
            with self.assertRaises(w.narration_review.ListeningRequired):
                phases.run_generate(self.job)
            render.assert_not_called()
        self.assertEqual(before, w.sha256_file(w._wav_path(folder, unit['index'])))

    def _saved_parent_with_residual_errors(self):
        parent = self.plan['passages'][0]
        text = ' '.join(f'The keeper carried lanterns past doorway number {i} before returning safely home.' for i in range(24))
        parent.update(text=text, text_sha256=hashlib.sha256(text.encode()).hexdigest())
        w._write_json(self.job / 'vibevoice_plan.json', self.plan)
        self.run_worker()
        segments = self.job / w.SEGMENTS_DIR
        units = w._units_for_parent(parent, self.config)
        self.assertGreaterEqual(len(units), 2)
        for unit in units:
            path = w._receipt_path(segments / w.UNITS_DIR, unit['index'])
            saved = phases._read(path)
            report = Path(saved['quality_report'])
            data = phases._read(report)
            data['transcript'] = data['transcript'].replace('keeper carried lanterns', 'traveller held candles', 1)
            w._write_json(report, data)
            saved.update(report_sha256=w.sha256_file(report), needs_repair=True, attempt=3)
            w._write_json(path, saved)
            self.assertTrue(w._valid_unit(segments / w.UNITS_DIR, unit, allow_needs_repair=True))
        path = w._receipt_path(segments, parent['index'])
        saved = phases._read(path)
        saved['force_regenerate'] = True
        w._write_json(path, saved)
        return parent, units

    def test_exhausted_repair_keeps_valid_saved_takes_for_review(self):
        parent, units = self._saved_parent_with_residual_errors()
        folder = self.job / w.SEGMENTS_DIR / w.UNITS_DIR
        before = {u['index']: w.sha256_file(w._wav_path(folder, u['index'])) for u in units}
        for _ in range(2):
            with mock.patch.object(phases, '_run_phase') as render:
                with self.assertRaises(w.narration_review.ListeningRequired):
                    phases.run_generate(self.job)
            render.assert_not_called()
        self.assertEqual(before, {u['index']: w.sha256_file(w._wav_path(folder, u['index'])) for u in units})
        self.assertTrue(w.narration_review.detail(self.job, parent['index'])['unresolved_count'])
        for unit in units:
            self.assertNotIn('listening_approval', phases._read(w._receipt_path(folder, unit['index'])))

    def test_exhausted_bad_candidate_does_not_displace_valid_saved_take(self):
        parent, units = self._saved_parent_with_residual_errors()
        folder = self.job / w.SEGMENTS_DIR / w.UNITS_DIR
        unit = units[0]
        before = w.sha256_file(w._wav_path(folder, unit['index']))
        pending = self.job / w.SEGMENTS_DIR / phases.PENDING_DIR
        audio = w._wav_path(pending, unit['index'])
        sf.write(audio, np.sin(np.arange(24000) * .03) * .1, 24000)
        report = pending / 'bad_take.json'
        w._write_json(report, {'transcript':'This is unrelated speech with none of the required content.'})
        phases._save(self.job, {'unit':w._profiled_unit(unit), 'attempt':3, 'status':'checked',
                               'basis':phases._basis(folder,unit), 'audio':str(audio),
                               'audio_sha256':w.sha256_file(audio), 'report':str(report)})
        phases._resolve(self.job,parent,units,self.config)
        self.assertEqual(w.sha256_file(w._wav_path(folder,unit['index'])),before)
        self.assertNotIn(unit['index'],w.narration_review.entry(self.job,parent)['candidates'])
        self.assertTrue(w._wav_path(folder.parent / w.narration_review.CANDIDATES_DIR,unit['index']).exists())
        self.assertNotIn('listening_approval',phases._read(w._receipt_path(folder,unit['index'])))

    def test_exhausted_repair_does_not_reuse_corrupt_or_rejected_prior(self):
        parent, units = self._saved_parent_with_residual_errors()
        folder = self.job / w.SEGMENTS_DIR / w.UNITS_DIR
        for unit in units:
            path = w._receipt_path(folder, unit['index'])
            saved = phases._read(path)
            saved['force_regenerate'] = True
            w._write_json(path, saved)
            phases._save(self.job, {'unit': w._profiled_unit(unit), 'attempt': 3, 'status': 'failed',
                                   'basis': phases._basis(folder, unit), 'audio': str(w._wav_path(folder, unit['index']))})
        w._wav_path(folder, units[0]['index']).write_bytes(b'corrupt')
        with mock.patch.object(phases, '_run_phase') as render:
            with self.assertRaisesRegex(RuntimeError, 'without usable audio'):
                phases.run_generate(self.job)
        render.assert_not_called()

    def test_omitted_unit_preserves_peer_audio_and_source_reversal_invalidates_parent(self):
        spoken = 'The careful keeper watched the doorway. ' * 20
        artifact = 'Transcribe this document page as clean Markdown, preserving reading order and tables.'
        parent = self.plan['passages'][0]
        parent.update(text=spoken + artifact, text_sha256=hashlib.sha256((spoken + artifact).encode()).hexdigest())
        self.config['spoken_projection'] = {'corrections': [{
            'parent_identity': parent['identity'], 'start': len(spoken), 'end': len(parent['text']),
            'before': artifact, 'after': '', 'source_pages': [1], 'evidence': 'Synthetic blank page',
        }]}
        w._write_json(self.job / 'vibevoice_config.json', self.config)
        self.run_worker()
        self.assertEqual(self.events, [('render', [0, 10000]), ('check', [0, 10000])])
        segments = self.job / w.SEGMENTS_DIR
        self.assertFalse(w._wav_path(segments / w.UNITS_DIR, 1).exists())
        self.assertTrue(w._valid_segment(segments, parent))
        self.assertEqual(w.sha256_file(w._wav_path(segments, 0)),
                         w.sha256_file(w._wav_path(segments / w.UNITS_DIR, 0)))
        with mock.patch.object(phases, '_run_phase') as render:
            phases.run_generate(self.job)
        render.assert_not_called()
        self.config.pop('spoken_projection')
        w._write_json(self.job / 'vibevoice_config.json', self.config)
        self.assertFalse(w._valid_segment(segments, parent))

    def test_source_only_omission_needs_no_audio_and_survives_cache_only_resume(self):
        parent = self.plan['passages'][0]
        self.config['spoken_projection'] = {'corrections': [{
            'parent_identity': parent['identity'], 'start': 0, 'end': len(parent['text']),
            'before': parent['text'], 'after': '', 'source_pages': [1],
            'evidence': 'Synthetic blank-page prompt echo verified against source',
        }]}
        w._write_json(self.job / 'vibevoice_config.json', self.config)
        self.run_worker()
        self.assertEqual(self.events, [('render', [10000]), ('check', [10000])])
        self.assertTrue(w._valid_segment(self.job / w.SEGMENTS_DIR, parent))
        self.assertFalse(w._wav_path(self.job / w.SEGMENTS_DIR, 0).exists())
        progress = phases._read(self.job / w.PROGRESS_FILE)
        self.assertEqual((progress['done'], progress['total']), (2, 2))
        self.assertEqual(progress['total_words'], len(self.plan['passages'][1]['text'].split()))
        self.assertEqual(progress['generated_words'], progress['total_words'])
        with mock.patch.object(phases, '_run_phase') as render:
            phases.run_generate(self.job)
        render.assert_not_called()
        with mock.patch.object(w, 'assemble', return_value='synthetic.wav') as assemble:
            w.run_assemble(self.job)
        self.assertEqual([p['index'] for p in assemble.call_args.args[1]], [1])

    def setUp(self):
        root = Path(__file__).resolve().parents[1] / ".test-tmp"
        root.mkdir(exist_ok=True)
        self.temp = tempfile.TemporaryDirectory(dir=root)
        self.addCleanup(self.temp.cleanup)
        self.job = Path(self.temp.name)
        texts = ["The careful keeper placed the silver lantern beside the wooden door before walking home.",
                 "A quiet traveller carried the blue notebook through the forest and reached the village safely."]
        self.plan = {"passages": [{"index": i, "identity": f"parent-{i}", "text": text,
                                  "text_sha256": hashlib.sha256(text.encode()).hexdigest()}
                                 for i, text in enumerate(texts)]}
        self.config = {"workflow": phases.WORKFLOW, "quality_max_retries": 2}
        w._write_json(self.job / "vibevoice_config.json", self.config)
        w._write_json(self.job / "vibevoice_plan.json", self.plan)
        self.events = []
        self.bad = set()
        self.always_bad = False
        for target, value in [("load_plan", (self.plan, self.config))]:
            patch = mock.patch.object(w, target, return_value=value)
            patch.start()
            self.addCleanup(patch.stop)
        patch = mock.patch.object(phases, "parakeet_setup_error", return_value=None)
        patch.start()
        self.addCleanup(patch.stop)

    def phase(self, job, config, phase):
        rows = phases._phase_rows(job, self.plan, config, "render" if phase == "render" else "ready")
        self.events.append((phase, [row["unit"]["index"] for row in rows]))
        for row in rows:
            if phase == "render":
                pcm = np.sin(np.arange(24001) * 0.07).astype(np.float32) * 0.1
                sf.write(row["audio"], pcm, 24000, subtype="PCM_16")
                row.update(status="ready", audio_sha256=w.sha256_file(row["audio"]))
            else:
                unit = row["unit"]
                fail = unit["index"] in self.bad and (self.always_bad or row["attempt"] == 1)
                text = "This entirely unrelated speech contains none of the expected passage." if fail else unit["text"]
                report = job / w.SEGMENTS_DIR / phases.PENDING_DIR / f"report_{unit['index']}_{row['attempt']}.json"
                w._write_json(report, {"transcript": text})
                row.update(status="checked", report=str(report))
            phases._save(job, row)

    def run_worker(self):
        with mock.patch.object(phases, "_run_phase", side_effect=self.phase):
            phases.run_generate(self.job)

    def test_failed_primary_uses_bounded_repair_and_preserves_good_audio(self):
        self.config['repair_model'] = {'model_id': 'synthetic-7b', 'model_fingerprint': 'seven'}
        w._write_json(self.job / 'vibevoice_config.json', self.config)
        self.bad.add(0)
        good_hashes = []
        def phase(job, config, name):
            if name == 'repair':
                rows = phases._phase_rows(job, self.plan, config, 'render')
                self.assertTrue(all(row['unit']['render_model'] == config['repair_model'] for row in rows))
                self.assertTrue(all(row['unit']['render_profile'] == w.delivery.INTACT_PROFILE for row in rows))
                self.bad.clear()
            self.phase(job, config, 'render' if name == 'repair' else name)
            good = w._wav_path(job / w.SEGMENTS_DIR / w.UNITS_DIR, 10000)
            if good.exists():
                good_hashes.append(w.sha256_file(good))
        with mock.patch.object(phases, '_run_phase', side_effect=phase):
            phases.run_generate(self.job)
        self.assertEqual(self.events, [('render', [0, 10000]), ('check', [0, 10000]), ('render', [0]), ('check', [0])])
        self.assertEqual(len(set(good_hashes)), 1)
        folder = self.job / w.SEGMENTS_DIR / w.UNITS_DIR
        receipt = phases._read(w._receipt_path(folder, 0))
        self.assertEqual(receipt['render_model'], self.config['repair_model'])
        self.assertTrue(w._valid_unit(folder, w._units_for_parent(self.plan['passages'][0], self.config)[0]))
        with mock.patch.object(phases, '_run_phase') as run:
            phases.run_generate(self.job)
        run.assert_not_called()

    def test_repair_exhaustion_requires_review_and_never_loops(self):
        self.config['repair_model'] = {'model_id': 'synthetic-7b'}
        self.bad.add(0)
        self.always_bad = True
        def phase(job, config, name):
            self.phase(job, config, 'render' if name == 'repair' else name)
        with mock.patch.object(phases, '_run_phase', side_effect=phase):
            with self.assertRaises(w.narration_review.ListeningRequired):
                phases.run_generate(self.job)
        self.assertEqual(len(self.events), 8)  # one primary and three repair takes, each checked
        with mock.patch.object(phases, '_run_phase') as run:
            with self.assertRaises(w.narration_review.ListeningRequired):
                phases.run_generate(self.job)
        run.assert_not_called()

    def test_repair_worker_loads_seven_b_alone_at_batch_one(self):
        self.config['repair_model'] = {'model_id': 'synthetic-7b', 'model_dir': 'seven', 'model_fingerprint': 'seven'}
        unit = w._units_for_parent(self.plan['passages'][0], self.config)[0]
        self.config['repair_unit_ids'] = [unit['identity']]
        for folder in (self.job / w.SEGMENTS_DIR, self.job / w.SEGMENTS_DIR / w.UNITS_DIR,
                       self.job / w.SEGMENTS_DIR / phases.PENDING_DIR, self.job / w.REJECTED_DIR):
            folder.mkdir(exist_ok=True)
        phases._schedule(self.job, self.plan, self.config)
        def render(torch, processor, model, voice, items, config, folder):
            self.assertEqual(config['native_batch_size'], 1)
            self.assertEqual(config['model_id'], 'synthetic-7b')
            self.assertEqual([u['index'] for u, attempt in items], [0])
            return [(u, a, None, RuntimeError('generated audio was silent')) for u, a in items]
        with mock.patch.object(w, '_assert_no_ocr'), mock.patch.object(w, '_prepare_voice'), \
             mock.patch.object(w, '_load_model', return_value=(None,None,None)), \
             mock.patch.object(w, '_batch_size', return_value=1), mock.patch.object(w, '_render_items', side_effect=render), \
             mock.patch('vibevoice_plan.model_fingerprint', return_value='seven'):
            phases.render_phase(self.job, self.plan, self.config, repair=True)
        self.assertEqual(phases._pending(self.job, unit)['status'], 'retry')
        self.assertEqual(phases._read(self.job / 'vibevoice_progress.json')['render_workers'], 1)

    def test_enabling_repair_redirects_old_primary_retry_and_exhausted_rows(self):
        for folder in (self.job / w.SEGMENTS_DIR, self.job / w.SEGMENTS_DIR / w.UNITS_DIR,
                       self.job / w.SEGMENTS_DIR / phases.PENDING_DIR, self.job / w.REJECTED_DIR):
            folder.mkdir(exist_ok=True)
        rows = phases._schedule(self.job, self.plan, self.config)
        rows[0].update(attempt=2, status='render')
        rows[1].update(attempt=3, status='failed')
        for row in rows:
            phases._save(self.job, row)
        self.config['repair_model'] = {'model_id': 'synthetic-7b'}
        work = phases._schedule(self.job, self.plan, self.config)
        self.assertEqual(len(work), 2)
        self.assertTrue(all(r['attempt'] == 1 and r['unit']['render_model'] == self.config['repair_model'] for r in work))
        self.assertEqual(len(list((self.job / w.REJECTED_DIR).glob('*primary*.json'))), 2)

    def test_render_phase_records_local_failure_and_surfaces_systemic_error(self):
        for folder in (self.job / w.SEGMENTS_DIR, self.job / w.SEGMENTS_DIR / w.UNITS_DIR,
                       self.job / w.SEGMENTS_DIR / phases.PENDING_DIR, self.job / w.REJECTED_DIR):
            folder.mkdir(exist_ok=True)
        rows = phases._schedule(self.job, self.plan, self.config)
        def render(torch, processor, model, voice, items, config, folder):
            result = []
            for unit, attempt in items:
                path = folder / f"temporary_{unit['index']}.wav"
                path.write_bytes(b'candidate')
                error = RuntimeError('generated audio was silent') if unit['index'] == 0 else None
                result.append((unit, attempt, path, error))
            return result
        with mock.patch.object(w, '_assert_no_ocr'), mock.patch.object(w, '_prepare_voice'), \
             mock.patch.object(w, '_load_model', return_value=(None,None,None)), \
             mock.patch.object(w, '_batch_size', return_value=2), mock.patch.object(w, '_render_items', side_effect=render):
            phases.render_phase(self.job, self.plan, self.config)
            failed = phases._pending(self.job, w._units_for_parent(self.plan['passages'][0], self.config)[0])
            self.assertEqual(failed['status'], 'retry')
            self.assertEqual(failed['failures'], [{'attempt':1,'error':'generated audio was silent'}])
            self.assertEqual(phases._pending(self.job, w._units_for_parent(self.plan['passages'][1], self.config)[0])['status'], 'ready')
            failed['status'] = 'render'
            phases._save(self.job, failed)
            with mock.patch.object(w, '_render_items', side_effect=ValueError('invalid model configuration')):
                with self.assertRaisesRegex(ValueError, 'invalid model configuration'):
                    phases.render_phase(self.job, self.plan, self.config)

    def test_generates_all_parents_before_checking_and_repairs_only_failed_clip(self):
        self.bad.add(0)
        self.run_worker()
        self.assertEqual(self.events, [("render", [0, 10000]), ("check", [0, 10000]),
                                      ("render", [0]), ("check", [0])])
        for parent in self.plan["passages"]:
            self.assertTrue(w._valid_segment(self.job / w.SEGMENTS_DIR, parent))
        saved = w._receipt_path(self.job / w.SEGMENTS_DIR / w.UNITS_DIR, 10000)
        self.assertEqual(json.loads(saved.read_text())["attempt"], 1)

    def test_llm_equivalence_survives_parent_gate_resume_and_retains_raw_transcript(self):
        from test_transcript_review import receipt
        self.config["transcript_review"] = True
        source = "The keeper knew Catherine Stephen Anne Jon Geoff Sean."
        heard = "The keeper knew Katherine Steven Ann John Jeff Shaun."
        self.plan["passages"][0]["text"] = source
        self.plan["passages"][0]["text_sha256"] = hashlib.sha256(source.encode()).hexdigest()
        self.bad.add(10000)
        def phase(job, config, name):
            self.phase(job, config, name)
            if name == "check":
                for row in phases._phase_rows(job, self.plan, config, "checked"):
                    if row["unit"]["index"] == 0:
                        w._write_json(Path(row["report"]), {"transcript": heard})
        def adjudicate(expected, transcript):
            return receipt(expected, transcript, "equivalent" if transcript == heard else "error")
        with mock.patch("transcript_review.Reviewer") as reviewer, mock.patch.object(w, "_assert_no_ocr"), \
                mock.patch.object(phases, "_run_phase", side_effect=phase):
            reviewer.return_value.__enter__.return_value.review.side_effect = adjudicate
            phases.run_generate(self.job)
        self.assertEqual(self.events, [("render", [0, 10000]), ("check", [0, 10000]),
                                      ("render", [10000]), ("check", [10000])])
        folder = self.job / w.SEGMENTS_DIR / w.UNITS_DIR
        unit = w._units_for_parent(self.plan["passages"][0], self.config)[0]
        self.assertTrue(w._valid_unit(folder, unit))
        report = w._unit_report(folder, unit)
        self.assertEqual(report["transcript"], heard)
        self.assertEqual(report["comparison_transcript"], source)
        saved = json.loads(w._receipt_path(folder, unit["index"]).read_text())
        self.assertNotIn("listening_approval", saved)
        baseline = {p: w.sha256_file(p) for p in (self.job / w.SEGMENTS_DIR).rglob("*") if p.is_file()}
        self.events.clear()
        self.run_worker()
        self.assertEqual(self.events, [])
        self.assertEqual(baseline, {p: w.sha256_file(p) for p in baseline})

    def test_uncertain_review_retains_audio_for_listening_without_blind_regeneration(self):
        from test_transcript_review import receipt
        self.config["transcript_review"] = True
        self.bad.add(0)
        with mock.patch("transcript_review.Reviewer") as reviewer, mock.patch.object(w, "_assert_no_ocr"):
            reviewer.return_value.__enter__.return_value.review.side_effect = (
                lambda expected, heard: receipt(expected, heard, "uncertain"))
            with self.assertRaises(w.narration_review.ListeningRequired):
                self.run_worker()
        self.assertEqual(self.events, [("render", [0, 10000]), ("check", [0, 10000])])
        detail = w.narration_review.detail(self.job)
        self.assertEqual(detail["unresolved_count"], 1)
        self.assertEqual(detail["items"][0]["transcript_review"]["decision"], "uncertain")

    def test_failed_llm_call_keeps_checked_audio_and_resume_needs_no_render_or_asr(self):
        from test_transcript_review import receipt
        self.config["transcript_review"] = True
        self.bad.add(0)
        with mock.patch("transcript_review.Reviewer") as reviewer, mock.patch.object(w, "_assert_no_ocr"):
            reviewer.return_value.__enter__.return_value.review.side_effect = TimeoutError("review timeout")
            with self.assertRaises(TimeoutError):
                self.run_worker()
            rows = phases._phase_rows(self.job, self.plan, self.config, "checked")
            hashes = {r["audio"]: w.sha256_file(r["audio"]) for r in rows}
            self.assertEqual(len(rows), 2)
            self.events.clear()
            reviewer.return_value.__enter__.return_value.review.side_effect = (
                lambda expected, heard: receipt(expected, heard, "uncertain"))
            with self.assertRaises(w.narration_review.ListeningRequired):
                self.run_worker()
            self.assertEqual(self.events, [])
            for row in rows:
                target = w.narration_review.CANDIDATES_DIR if row["unit"]["index"] == 0 else w.UNITS_DIR
                self.assertEqual(w.sha256_file(self.job / w.SEGMENTS_DIR / target / Path(row["audio"]).name), hashes[row["audio"]])

    def test_checker_failure_resumes_saved_audio_without_generation(self):
        def interrupted(job, config, phase):
            if phase == "check":
                raise RuntimeError("checker interrupted")
            self.phase(job, config, phase)
        with mock.patch.object(phases, "_run_phase", side_effect=interrupted), self.assertRaisesRegex(RuntimeError, "interrupted"):
            phases.run_generate(self.job)
        paths = list((self.job / w.SEGMENTS_DIR / phases.PENDING_DIR).glob("*.wav"))
        hashes = {p.name: w.sha256_file(p) for p in paths}
        self.events.clear()
        self.run_worker()
        self.assertEqual(self.events, [("check", [0, 10000])])
        for name, checksum in hashes.items():
            self.assertEqual(w.sha256_file(self.job / w.SEGMENTS_DIR / w.UNITS_DIR / name), checksum)

    def test_exhausted_clip_goes_to_review_while_other_parent_finishes(self):
        self.bad.add(0)
        self.always_bad = True
        with self.assertRaises(w.narration_review.ListeningRequired):
            self.run_worker()
        self.assertEqual(len(self.events), 6)
        self.assertTrue(w._valid_segment(self.job / w.SEGMENTS_DIR, self.plan["passages"][1]))
        self.assertFalse(w._valid_segment(self.job / w.SEGMENTS_DIR, self.plan["passages"][0]))
        self.assertEqual(w.narration_review.detail(self.job)["unresolved_count"], 1)
        self.events.clear()
        with self.assertRaises(w.narration_review.ListeningRequired):
            self.run_worker()
        self.assertEqual(self.events, [])

    def test_parent_gate_does_not_regenerate_passing_units(self):
        original = w.parent_quality
        def aggregate(parent, reports, units=None):
            result = original(parent, reports, units=units)
            if parent["index"] == 0 and len(self.events) < 4:
                result["ok"] = False
            return result
        with mock.patch.object(w, "parent_quality", side_effect=aggregate), \
             mock.patch.object(w, "choose_repair_unit", side_effect=lambda units, reports, exclude: units[0]):
            with self.assertRaises(w.narration_review.ListeningRequired):
                self.run_worker()
        self.assertEqual(self.events, [("render", [0, 10000]), ("check", [0, 10000])])

    def test_render_exhaustion_is_local_and_resume_does_not_repeat_attempts(self):
        attempts = []
        def phase(job, config, name):
            if name != 'render':
                return self.phase(job, config, name)
            rows = phases._phase_rows(job, self.plan, config, 'render')
            for row in rows:
                if row['unit']['index'] == 0:
                    attempts.append(row['attempt'])
                    row.update(status='retry')
                    row.setdefault('failures', []).append({'attempt': row['attempt'], 'error': 'generated audio was silent'})
                    phases._save(job, row)
            self.phase(job, config, name)
        with mock.patch.object(phases, '_run_phase', side_effect=phase):
            for _ in range(2):
                with self.assertRaisesRegex(RuntimeError, 'without usable audio'):
                    phases.run_generate(self.job)
        self.assertEqual(attempts, [1, 2, 3])
        self.assertTrue(w._valid_segment(self.job / w.SEGMENTS_DIR, self.plan['passages'][1]))
        self.assertEqual(w.narration_review.detail(self.job)['items'], [])
        failed = phases._phase_rows(self.job, self.plan, self.config, 'failed')
        self.assertEqual(len(failed[0]['failures']), 3)

    def test_interrupted_render_consumes_attempt_and_preserves_last_checked_candidate(self):
        self.bad.add(0)
        attempts = []
        def phase(job, config, name):
            if name == 'render':
                for row in phases._phase_rows(job, self.plan, config, 'render'):
                    if row['unit']['index'] == 0:
                        attempts.append(row['attempt'])
                        if row['attempt'] > 1:
                            row['status'] = 'rendering'
                            phases._save(job, row)
                            raise SystemExit(2)
            self.phase(job, config, name)
        with mock.patch.object(phases, '_run_phase', side_effect=phase):
            for _ in range(2):
                with self.assertRaises(SystemExit):
                    phases.run_generate(self.job)
            with self.assertRaises(w.narration_review.ListeningRequired):
                phases.run_generate(self.job)
        self.assertEqual(attempts, [1, 2, 3])
        detail = w.narration_review.detail(self.job)
        self.assertEqual(len(detail['items']), 1)
        self.assertIsNone(detail['items'][0]['decision'])
        self.assertTrue(w.narration_review.audio_path(self.job, 0).exists())
        failed = phases._phase_rows(self.job, self.plan, self.config, 'failed')[0]
        self.assertEqual([f['attempt'] for f in failed['failures']], [2, 3])
        item = detail['items'][0]
        w.narration_review.decide(self.job, 0, item['fingerprint'], 'retry')
        self.bad.clear()
        self.events.clear()
        self.run_worker()
        self.assertEqual(self.events, [('render', [0]), ('check', [0])])
        self.assertTrue(list((self.job / w.REJECTED_DIR).glob('*_failed_*.json')))

    def test_cached_approved_clip_is_not_replaced_when_peer_is_regenerated(self):
        self.run_worker()
        folder = self.job / w.SEGMENTS_DIR / w.UNITS_DIR
        peer = w._units_for_parent(self.plan["passages"][1], self.config)[0]
        receipt_path = w._receipt_path(folder, peer["index"])
        receipt = phases._read(receipt_path)
        receipt["listening_approval"] = w.narration_review.fingerprint(receipt)
        w._write_json(receipt_path, receipt)
        before = (w.sha256_file(receipt_path), w.sha256_file(w._wav_path(folder, peer["index"])))
        for location in [folder, self.job / w.SEGMENTS_DIR]:
            path = w._receipt_path(location, 0)
            payload = phases._read(path)
            payload["force_regenerate"] = True
            w._write_json(path, payload)
        self.events.clear()
        self.run_worker()
        self.assertEqual(self.events, [("render", [0]), ("check", [0])])
        self.assertEqual(before, (w.sha256_file(receipt_path), w.sha256_file(w._wav_path(folder, peer["index"]))))

    def test_changed_pending_audio_stops_before_checking(self):
        def interrupt(job, config, phase):
            if phase == "render":
                self.phase(job, config, phase)
                first = next((job / w.SEGMENTS_DIR / phases.PENDING_DIR).glob("*.wav"))
                first.write_bytes(b"changed")
            else:
                self.phase(job, config, phase)
        with mock.patch.object(phases, "_run_phase", side_effect=interrupt), self.assertRaisesRegex(RuntimeError, "changed"):
            phases.run_generate(self.job)

    def test_retry_runs_while_another_clip_in_same_passage_is_undecided(self):
        parent = self.plan["passages"][0]
        parent["text"] = " ".join([parent["text"]] * 20)
        parent["text_sha256"] = hashlib.sha256(parent["text"].encode()).hexdigest()
        w._write_json(self.job / "vibevoice_plan.json", self.plan)
        units = w._units_for_parent(parent, self.config)
        self.assertGreaterEqual(len(units), 2)
        selected, peer = units[:2]
        self.bad.update([selected["index"], peer["index"]])
        self.always_bad = True
        with self.assertRaises(w.narration_review.ListeningRequired):
            self.run_worker()
        detail = w.narration_review.detail(self.job)
        selected_item = next(item for item in detail["items"] if item["index"] == selected["index"])
        peer_path = w.narration_review.audio_path(self.job, peer["index"])
        peer_hash = w.sha256_file(peer_path)
        w.narration_review.decide(self.job, selected["index"], selected_item["fingerprint"], "retry")
        self.bad.clear()
        self.events.clear()
        with self.assertRaises(w.narration_review.ListeningRequired):
            self.run_worker()
        self.assertEqual(self.events, [("render", [selected["index"]]), ("check", [selected["index"]])])
        detail = w.narration_review.detail(self.job)
        self.assertEqual([item["index"] for item in detail["items"]], [peer["index"]])
        self.assertEqual(w.sha256_file(peer_path), peer_hash)
        self.assertTrue(w._valid_unit(self.job / w.SEGMENTS_DIR / w.UNITS_DIR, selected))

    def test_cancel_terminates_and_waits_for_owned_gpu_phase(self):
        process = mock.Mock()
        process.poll.return_value = None
        with mock.patch.object(phases.subprocess, "Popen", return_value=process), \
             mock.patch.object(w, "_prepare_voice"), \
             mock.patch.object(phases, "WindowsWorkerJob"), \
             mock.patch.object(phases, "_cancel", side_effect=[None, None, SystemExit(2)]), self.assertRaises(SystemExit):
            phases._run_phase(self.job, {}, "render")
        process.terminate.assert_called_once()
        process.wait.assert_called_once()

    def test_two_worker_assignments_do_not_shift_when_a_peer_finishes(self):
        for folder in [self.job / w.SEGMENTS_DIR, self.job / w.SEGMENTS_DIR / w.UNITS_DIR,
                       self.job / w.SEGMENTS_DIR / phases.PENDING_DIR, self.job / w.REJECTED_DIR]:
            folder.mkdir(exist_ok=True)
        rows = phases._schedule(self.job, self.plan, self.config)
        first = phases._phase_rows(self.job, self.plan, self.config, "render", 0, 2)
        second = phases._phase_rows(self.job, self.plan, self.config, "render", 1, 2)
        self.assertEqual([r["unit"]["index"] for r in first], [0])
        self.assertEqual([r["unit"]["index"] for r in second], [10000])
        rows[0]["status"] = "retry"
        phases._save(self.job, rows[0])
        second_after = phases._phase_rows(self.job, self.plan, self.config, "render", 1, 2)
        self.assertEqual(second_after, second)
        self.assertEqual(phases._phase_rows(self.job, self.plan, self.config, "render", 0, 2), [])

    def test_cancel_terminates_both_render_workers(self):
        processes = [mock.Mock(), mock.Mock()]
        for process in processes:
            process.poll.return_value = None
        with mock.patch.object(phases.subprocess, "Popen", side_effect=processes) as spawn, \
             mock.patch.object(w, "_prepare_voice"), \
             mock.patch.object(phases, "WindowsWorkerJob"), \
             mock.patch.object(phases, "_cancel", side_effect=[None, None, None, SystemExit(2)]), self.assertRaises(SystemExit):
            phases._run_phase(self.job, {"render_workers": 2}, "render")
        self.assertEqual(spawn.call_args_list[0].args[0][-4:], ["--worker", "0", "--workers", "2"])
        self.assertEqual(spawn.call_args_list[1].args[0][-4:], ["--worker", "1", "--workers", "2"])
        for process in processes:
            process.terminate.assert_called_once()
            process.wait.assert_called_once()

    def test_failure_stops_peer_and_prevents_check_phase(self):
        failed, peer = mock.Mock(), mock.Mock()
        failed.poll.return_value = 1
        peer.poll.return_value = None
        with mock.patch.object(phases.subprocess, "Popen", side_effect=[failed, peer]), \
             mock.patch.object(w, "_prepare_voice"), \
             mock.patch.object(phases, "WindowsWorkerJob"), self.assertRaisesRegex(RuntimeError, "render phase failed"):
            phases._run_phase(self.job, {"render_workers": 2}, "render")
        peer.terminate.assert_called_once()
        failed.wait.assert_called_once()
        peer.wait.assert_called_once()


if __name__ == "__main__":
    unittest.main()
