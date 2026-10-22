import unittest
import tempfile
from pathlib import Path
from unittest import mock
from app.vibevoice_delivery import delivery_parts, spoken_text, spoken_units


class DeliveryTests(unittest.TestCase):
    def test_versioned_projection_preserves_source_and_exact_correction_spans(self):
        from app.vibevoice_delivery import project_units, PROJECTION_VERSION
        source = 'On November 2, we read the lan- guage results.8 At 11:00 p.m. we left.'
        parent = {'identity': 'synthetic'}
        units = [{'text': source, 'identity': 'unit', 'index': 0}]
        fixes = []
        for before, after in [('lan- guage', 'language'), ('.8', '.')]:
            start = source.index(before)
            fixes.append({'parent_identity': 'synthetic', 'start': start, 'end': start + len(before),
                          'before': before, 'after': after, 'source_pages': [1, 2],
                          'evidence': 'synthetic source geometry fixture'})
        config = {'spoken_projection': {'version': PROJECTION_VERSION, 'corrections': fixes}}
        projected = project_units(units, parent, config)
        self.assertEqual(projected[0]['text'], source)
        self.assertEqual(projected[0]['spoken_text'],
                         "On November second, we read the language results. At eleven o'clock P M. we left.")
        self.assertEqual(projected[0]['identity'], 'unit')
        fixes[0]['before'] = 'stale text'
        with self.assertRaises(ValueError):
            project_units(units, parent, config)

    def test_dates_protect_names_identifiers_compounds_and_ambiguous_numbers(self):
        from app.vibevoice_delivery import calendar_clock_edits
        for text in ('May 6 apples please.', '6/66', 'November 32', 'February 30',
                     'November 2nd', 'November 2/3', 'November 2-3',
                     'short- and long-term', 'well- known', 'abc- def', 'May came home.'):
            self.assertEqual(calendar_clock_edits(text), [], text)
        self.assertEqual(calendar_clock_edits('November 2 and 3')[0]['after'], 'November second and third')
        self.assertEqual(calendar_clock_edits('May 6, 1960')[0]['after'], 'May sixth')

    def test_correction_crosses_old_unit_boundary_and_leaves_ambiguous_hyphens(self):
        from app.vibevoice_delivery import project_units
        units = [{'text': 'The lan-', 'identity': 'a'}, {'text': 'guage is well- known.', 'identity': 'b'}]
        config = {'spoken_projection': {'corrections': [
            {'parent_identity': 'p', 'start': 4, 'end': 14, 'before': 'lan- guage', 'after': 'language',
             'source_pages': [1, 2], 'evidence': 'verified line/page break'}]}}
        # Offsets are exact: no fuzzy repair is allowed.
        result = project_units(units, {'identity': 'p'}, config)
        self.assertEqual(' '.join(u.get('spoken_text', u['text']) for u in result),
                         'The language is well- known.')

    def test_intact_policy_preserves_quote_and_aside_context(self):
        from app.vibevoice_delivery import INTACT_PROFILE, policy_hash, PROFILE
        text = '“Wait!” Mara said (quietly).'
        self.assertEqual(delivery_parts(text, INTACT_PROFILE), [{'text': text, 'aside': False}])
        self.assertNotEqual(policy_hash(PROFILE), policy_hash(INTACT_PROFILE))

    def test_reference_split_across_existing_units_keeps_indices_and_source(self):
        units = [{'index': 10, 'text': 'The lantern fell. (p.'},
                 {'index': 11, 'text': '76; punctuation is original) Another sentence.'}]
        projected = spoken_units(units)
        self.assertEqual(projected[0]['spoken_text'], 'The lantern fell.')
        self.assertEqual(projected[1]['spoken_text'], 'punctuation is original Another sentence.')
        self.assertEqual([u['text'] for u in projected], [u['text'] for u in units])
        self.assertEqual([u['index'] for u in projected], [10, 11])
    def test_omit_only_parenthetical_page_references(self):
        self.assertEqual(spoken_text('(pp. 111-12) The lantern (still warm) fell.'),
                         'The lantern (still warm) fell.')
        self.assertEqual(spoken_text('(p. 12; an editorial note)'), '(an editorial note)')
        for text in ['See p. 12 for details.', '(12 people)', 'Pages 11-12 are missing.']:
            self.assertEqual(spoken_text(text), text)

    def test_dialogue_has_quote_boundaries_without_splitting_apostrophes(self):
        text = "‘Halt!’ a guard called. ‘We’re ready,’ said Mara. The guards’ horses waited."
        parts = delivery_parts(text)
        self.assertEqual([p['text'] for p in parts], [
            '‘Halt!’', 'a guard called. ‘We’re ready,’', 'said Mara. The guards’ horses waited.'])
        self.assertEqual(' '.join(p['text'] for p in parts), text)

    def test_quoted_terms_stay_in_the_sentence(self):
        text = "The ‘meaning of life’ and ‘honour’ mattered to him."
        self.assertEqual(delivery_parts(text), [{'text': text, 'aside': False}])

    def test_aside_is_separate_and_preserves_words(self):
        parts = delivery_parts('A messenger (quietly): ‘Follow me.’')
        self.assertEqual(parts, [{'text': 'A messenger', 'aside': False},
                                {'text': 'quietly', 'aside': True},
                                {'text': '‘Follow me.’', 'aside': False}])

    def test_nested_quotation_keeps_one_turn(self):
        self.assertEqual(len(delivery_parts('‘He said “wait” before leaving!’ she replied.')), 2)

    def test_narration_gate_uses_spoken_text_and_still_detects_omissions(self):
        from app.vibevoice_quality import assess_narration
        self.assertTrue(assess_narration('(pp. 11-12) Five bright lanterns lit the room.',
                                        'Five bright lanterns lit the room.')['ok'])
        self.assertFalse(assess_narration('(pp. 11-12) Five bright lanterns lit the room.', 'Room.')['ok'])

    def test_render_adds_real_silence_and_quieter_aside_without_time_stretch(self):
        import sys
        sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'app'))
        try:
            import numpy as np
            import soundfile as sf
            import vibevoice_worker as worker
        except ModuleNotFoundError:
            self.skipTest('requires isolated narration runtime')
        unit = worker._profiled_unit({'index': 0, 'text': 'Mara (quietly) returned.'})
        def render(torch, processor, model, voice, fragment, config, path):
            sf.write(path, np.full(4800, 0.5, dtype='float32'), 24000, subtype='PCM_16')
        with tempfile.TemporaryDirectory() as directory, mock.patch.object(worker, '_render_one', side_effect=render):
            result = worker._render_items(None, None, None, None, [(unit, 1)], {}, Path(directory))
            self.assertIsNone(result[0][3])
            audio, sr = sf.read(result[0][2])
            self.assertEqual(sr, 24000)
            self.assertEqual(len(audio), 4800 * 5)
            self.assertTrue(np.all(audio[4800:9600] == 0))
            self.assertAlmostEqual(audio[11000], 0.42, places=4)
            self.assertEqual(audio[4799], 0)
