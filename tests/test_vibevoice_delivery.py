import unittest
import tempfile
from pathlib import Path
from unittest import mock
from app.vibevoice_delivery import delivery_parts, spoken_text, spoken_units


class DeliveryTests(unittest.TestCase):
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
