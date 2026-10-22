import copy
import hashlib
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'app'))
try:
    import vibevoice_worker as w
    import vibevoice_delivery as d
    from vibevoice_migration import plan_migration
except ModuleNotFoundError:
    w = None


@unittest.skipUnless(w, 'narration runtime dependencies required')
class MigrationTests(unittest.TestCase):
    def test_sentence_policy_requires_explicit_review_boundary_migration(self):
        from vibevoice_units import repair_units
        parent = {'index': 0, 'identity': 'parent', 'text': ' '.join(['quiet'] * 70) + ' New York.'}
        old = repair_units(parent, target_words=40, max_words=55)
        with tempfile.TemporaryDirectory() as temp:
            job = Path(temp)
            w._write_json(job / 'vibevoice_config.json', {'unit_boundary_policy': 'sentences_v4',
                'backend': 'drama3', 'drama3_unit_limits': {'target_words': 40, 'max_words': 55}})
            with self.assertRaisesRegex(ValueError, 'unit boundaries changed'):
                w.narration_review._passage_items(job, {'parent': parent, 'units': old}, {'passages': [parent]})

    def test_review_rejects_old_boundaries_after_explicit_migration(self):
        from vibevoice_units import repair_units
        with tempfile.TemporaryDirectory() as temp:
            job = Path(temp)
            parent = {'index':0, 'identity':'parent', 'text':' '.join(['quiet']*119)+' Evan I. Mercer arrived. Then we left.'}
            old = repair_units(parent, boundary_policy='legacy_v1')
            new = repair_units(parent, boundary_policy='initials_v2')
            self.assertNotEqual([u['identity'] for u in old], [u['identity'] for u in new])
            w._write_json(job / 'vibevoice_config.json', {'unit_boundary_policy':'initials_v2'})
            with self.assertRaisesRegex(ValueError, 'unit boundaries changed'):
                w.narration_review._passage_items(job, {'parent':parent,'units':old}, {'passages':[parent]})

    def test_parent_and_approval_reuse_reject_changed_projection_without_identity_change(self):
        with tempfile.TemporaryDirectory() as temp:
            job = Path(temp)
            segments = job / w.SEGMENTS_DIR
            folder = segments / w.UNITS_DIR
            folder.mkdir(parents=True)
            parent = {'index':0, 'identity':'parent', 'text':'We met on June 3.'}
            parent['text_sha256'] = d.text_hash(parent['text'])
            unit = w._profiled_unit(w._units_for_parent(parent, {})[0])
            w._write_json(job / 'vibevoice_config.json', {})
            report = job / 'report.json'
            w._write_json(report, {'transcript':parent['text']})
            wave = folder / 'tmp.wav'
            w.sf.write(str(wave), w.np.sin(w.np.arange(24001)*0.07)*0.1, 24000)
            w._publish_unit(folder, unit, wave, report, 1)
            receipt_path = w._receipt_path(folder, unit['index'])
            receipt = json.loads(receipt_path.read_text())
            receipt['listening_approval'] = w.narration_review.fingerprint(receipt)
            w._write_json(receipt_path, receipt)
            w._assemble_parent_from_units(parent, [unit], folder, segments, {'ok':True})
            self.assertTrue(w._valid_segment(segments, parent))
            self.assertTrue(w.narration_review.approved(receipt, unit))
            config = {'spoken_projection':{'version':d.PROJECTION_VERSION}}
            w._write_json(job / 'vibevoice_config.json', config)
            updated = w._units_for_parent(parent, config)[0]
            self.assertEqual(unit['identity'], updated['identity'])
            self.assertFalse(w._valid_segment(segments, parent))
            self.assertFalse(w._valid_unit(folder, updated))
            self.assertFalse(w.narration_review.approved(receipt, updated))
            w._write_json(job / 'vibevoice_config.json', {})
            self.assertTrue(w._valid_segment(segments, parent))
            w._wav_path(folder, unit['index']).write_bytes(b'corrupt child')
            self.assertFalse(w._valid_segment(segments, parent))

    def test_selective_manifest_does_not_write_or_transfer_approval(self):
        with tempfile.TemporaryDirectory() as temp:
            job = Path(temp)
            parents = [{'index': i, 'identity': f'p{i}', 'text': text}
                       for i, text in enumerate(['We arrived on June 3.', 'The quiet room was empty.'])]
            plan = {'passages': parents}
            old = {}
            w._write_json(job / 'vibevoice_plan.json', plan)
            w._write_json(job / 'vibevoice_config.json', old)
            folder = job / w.SEGMENTS_DIR / w.UNITS_DIR
            folder.mkdir(parents=True)
            for parent in parents:
                unit = w._units_for_parent(parent, old)[0]
                w._wav_path(folder, unit['index']).write_bytes(b'original audio')
                w._write_json(w._receipt_path(folder, unit['index']), {'listening_approval': 'original-only'})
            before = {str(p): w.sha256_file(p) for p in job.rglob('*') if p.is_file()}
            new = {'spoken_projection': {'version': d.PROJECTION_VERSION}}
            with patch.object(w, 'load_plan', return_value=(plan, old)):
                manifest = plan_migration(job, new)
            self.assertEqual([p['parent_index'] for p in manifest['changed_parents']], [0])
            self.assertEqual(manifest['unchanged_units'], 1)
            self.assertEqual(manifest['affected_approvals'], 1)
            row = manifest['changed_parents'][0]['units'][0]
            self.assertEqual(row['old']['identity'], row['new']['identity'])
            self.assertNotEqual(row['old']['spoken_text_sha256'], row['new']['spoken_text_sha256'])
            self.assertFalse(row['transfer_approval'])
            self.assertEqual(before, {str(p): w.sha256_file(p) for p in job.rglob('*') if p.is_file()})

    def test_legacy_receipts_bind_projection_and_frozen_policy(self):
        unit = {'text': 'A quiet evening.'}
        self.assertTrue(d.receipt_matches_projection({}, unit))
        self.assertFalse(d.receipt_matches_projection({'render_text_sha256':'wrong'}, unit))
        self.assertFalse(d.receipt_matches_projection({}, {**unit, 'spoken_text': 'A loud evening.'}))
        receipt = {'render_profile': d.PROFILE, 'render_text_sha256': d.text_hash(unit['text'])}
        self.assertTrue(d.receipt_matches_projection(receipt, unit))
        self.assertFalse(d.receipt_matches_projection({**receipt, 'spoken_text_sha256':d.text_hash(unit['text']), 'render_text_sha256':'wrong'}, unit))
        self.assertFalse(d.receipt_matches_projection({**receipt, 'render_policy_sha256': 'wrong'}, unit))
        self.assertFalse(d.receipt_matches_projection(receipt, {**unit, 'render_profile': d.INTACT_PROFILE}))

    def test_exact_source_edits_preserve_compounds_and_suspended_hyphens(self):
        parent = {'index': 0, 'identity': 'source', 'text': 'Four- and five-year plans use lan- guage and wing-over turns.'}
        text = parent['text']
        start = text.index('lan- guage')
        config = {'spoken_projection': {'corrections': [{'parent_identity':'source', 'start':start, 'end':start+10,
            'before':'lan- guage', 'after':'language', 'source_pages':[2], 'evidence':'within-page line geometry'}]}}
        unit = w._units_for_parent(parent, config)[0]
        self.assertEqual(unit['text'], text)
        self.assertEqual(unit['spoken_text'], 'Four- and five-year plans use language and wing-over turns.')
        restored = d.project_units([unit], parent, {})[0]
        self.assertNotIn('spoken_text', restored)
        config['spoken_projection']['corrections'][0]['before'] = 'wrong'
        with self.assertRaises(ValueError):
            w._units_for_parent(parent, config)

    def test_oversize_sentence_keeps_initials_and_exact_words(self):
        from vibevoice_units import repair_units
        text = ' '.join(['quiet'] * 8) + ' John I. Miller walked through the long hallway without stopping.'
        parent = {'index':0, 'identity':'name', 'text':text}
        units = repair_units(parent, target_words=10, max_words=10)
        self.assertEqual(' '.join(u['text'] for u in units), text)
        self.assertTrue(any('John I. Miller' in u['text'] for u in units))
        self.assertTrue(all(len(u['text'].split()) <= 10 for u in units))

    def test_date_validation_and_names(self):
        text = 'May 3 children attend. February 29, 2023 was invalid. On May 3, 2024 we met.'
        edits = d.calendar_clock_edits(text)
        self.assertEqual([(e['before'],e['after']) for e in edits], [('May 3','May third')])

    def test_shadow_content_diagnostics_keep_acceptance_and_orthography_separate(self):
        from vibevoice_quality import assess_narration
        for source, heard, reason in [('We did not leave.', 'We did leave.', 'negation differs'),
                                      ('There were 18 boxes.', 'There were 80 boxes.', 'numeric wording differs'),
                                      ('She walked home.', 'She quickly walked home.', 'addition candidate')]:
            report = assess_narration(source, heard)
            self.assertTrue(report['ok'])
            self.assertTrue(any(reason in d['reasons'] for d in report['content_diagnostics']))
        self.assertEqual(assess_narration('Her favourite colour.', 'Her favorite color.')['content_diagnostics'], [])


if __name__ == '__main__':
    unittest.main()
