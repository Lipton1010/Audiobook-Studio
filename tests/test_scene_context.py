"""Synthetic source-context regressions; no book text, models or GPU calls."""
import copy
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest import mock
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'app'))
import scene_analysis as a
import scene_direction as d


def make(text):
    return d.canonical([{'text': text}], 'synthetic')


def turn(source, quote, delivery='whisper'):
    start = source['text'].index(quote)
    return {'id': 'turn', 'start': start, 'end': start+len(quote), 'quote': quote,
            'scene': 'unspecified', 'kind': 'dialogue', 'speaker': 'Mira',
            'intention': 'unknown', 'emotion': 'unknown', 'intensity': 0,
            'delivery': delivery, 'confidence': .99, 'ambiguity': '',
            'evidence': [{'start': 0, 'end': len(source['text']), 'quote': source['text']}]}


class SourceContextTests(unittest.TestCase):
    def test_written_introduction_survives_window_boundary_and_blocks_cue(self):
        source = make('Mira sent a written response. ' + 'Background. '*100 + '"Stay."')
        span = turn(source, '"Stay."')
        window = {'start': span['start'], 'end': span['end'], 'text': span['quote']}
        catalog = a.source_catalog(source, window)
        self.assertTrue(any('written response' in r['quote'] for r in catalog if r['candidate_kind'] == 'evidence'))
        self.assertIn('possible_written_medium', [f['code'] for f in d.source_flags(source, span)])
        plan = d.new_plan(source, 'local', 'pin'); plan['spans'] = [span]
        compiled = d.compile_range(source, plan, span['start'], span['end'])
        self.assertEqual(compiled['render_text'], span['quote'])
        self.assertIn('possible_written_medium', compiled['review'][0]['reason'])

    def test_later_email_does_not_reclassify_earlier_spoken_quote(self):
        source = make('I spoke to Mira. "Hello!" she said. Later I received an email from Jo.')
        self.assertNotIn('possible_written_medium', [f['code'] for f in d.source_flags(source, turn(source, '"Hello!"'))])

    def test_explicit_spoken_transition_resets_written_review_signal(self):
        source = make('Mira sent an email. Then I spoke to Mira on the phone. "Hello!"')
        self.assertEqual(d.source_flags(source, turn(source, '"Hello!"')), [])

    def test_medium_is_not_carried_into_unrelated_paragraph(self):
        source = make('Mira sent an email. "Later."\n\nJo said, "Hello!"')
        self.assertEqual(d.source_flags(source, turn(source, '"Hello!"')), [])

    def test_lowercase_embedded_phrase_is_review_not_automatic_turn(self):
        source = make('I asked why she called it her "so-called home."')
        span = turn(source, '"so-called home."')
        flags = d.source_flags(source, span)
        self.assertIn('possible_quoted_fragment', [f['code'] for f in flags])
        self.assertEqual(flags[0]['evidence']['quote'], span['quote'])

    def test_reported_cry_is_not_assigned_current_speaker(self):
        source = make('There was a report of someone yelling, "Help!"')
        self.assertIn('reported_cry_not_current_turn', [f['code'] for f in d.source_flags(source, turn(source, '"Help!"'))])

    def test_paraphrase_wrong_evidence_and_partial_word_rejected(self):
        text = 'Mira said the date might be wrong. Jo left.'
        evidence = {'start': 0, 'end': len(text), 'quote': text}
        for fact in ('The date was wrong.', 'Mira is a doctor.', 'Mira said the dat', 'Mira said the date'):
            with self.subTest(fact=fact), self.assertRaises(ValueError):
                d.validate_context_fact(text, {'character': 'Mira', 'fact': fact, 'evidence': evidence})
        good = {'character': 'Mira', 'fact': 'Mira said the date might be wrong.', 'evidence': evidence}
        d.validate_context_fact(text, good)

    def test_paragraph_evidence_keeps_following_caveat(self):
        source = make('Mira wrote, "It happened." It was unclear which incident she meant.')
        span = turn(source, '"It happened."')
        catalog = a.source_catalog(source, {'start': span['start'], 'end': span['end'], 'text': span['quote']})
        self.assertTrue(any('It was unclear which incident she meant.' in r['quote'] for r in catalog if r['candidate_kind'] == 'evidence'))

    def test_model_proposals_never_propagate_as_memory(self):
        source = make('Mira said, "Stay."\n\nMira said, "Go."')
        chunks = list(a.windows(source, 23)); calls = []
        class Director:
            def analyze(self, payload):
                calls.append(copy.deepcopy(payload))
                return {'done': True, 'done_reason': 'stop', 'message': {'content': '{"spans":[],"facts":[]}'}}
        with tempfile.TemporaryDirectory() as temp, mock.patch.object(a, 'windows', return_value=iter(chunks)):
            a.analyze_source(source, temp, Director())
        self.assertGreaterEqual(len(calls), 2)
        self.assertTrue(all(p['context'] == [] and p['previous_direction'] == [] for p in calls))

    def test_fresh_saved_plan_quarantines_without_changing_original(self):
        source = make('Mira said the date might be wrong.')
        original = d.new_plan(source, 'local', 'pin'); original['policy'] = 'scene_direction_v1'
        evidence = {'start': 0, 'end': len(source['text']), 'quote': source['text']}
        original['context'] = [{'character': 'Mira', 'fact': 'The date was wrong.', 'evidence': evidence},
                               {'character': 'Mira', 'fact': source['text'], 'evidence': evidence}]
        before = copy.deepcopy(original)
        candidate, report = a.revalidate_saved_plan(source, original)
        self.assertEqual(original, before)
        self.assertEqual(len(report['quarantined_context']), 1)
        self.assertEqual(len(candidate['context']), 1)
        self.assertFalse(report['semantic_approval'])
        d.validate_plan(source, candidate)
        with self.assertRaises(ValueError):
            d.validate_plan(source, original)

    def test_bounded_context_is_explicit_and_deduplicated(self):
        source = make('Mira wrote. ' + 'background '*700 + '"Stay." "Go."')
        window = {'start': 0, 'end': len(source['text']), 'text': source['text']}
        catalog = a.source_catalog(source, window)
        frames = [r for r in catalog if r['candidate_kind'] == 'evidence']
        self.assertEqual(len(frames), 1)
        self.assertLessEqual(sum(len(r['quote']) for r in frames), 6000)
        self.assertFalse(frames[0]['complete'])
        self.assertIn('paragraph_context_exceeds_bound', [f['code'] for f in d.source_flags(source, turn(source, '"Go."'))])

    def test_cli_revalidation_preserves_original_and_blocks_render(self):
        import scene_direction_cli as cli
        source = make('Mira said the date might be wrong.')
        old = d.new_plan(source, 'local', 'pin'); old['policy'] = 'scene_direction_v1'
        with tempfile.TemporaryDirectory() as temp:
            original = Path(temp)/'original'; original.mkdir()
            output = Path(temp)/'new'
            cli.write(original/'canonical.json', source)
            cli.write(original/'directions.json', old)
            cli.write(original/'baseline_config.json', {})
            before = (original/'directions.json').read_bytes()
            result = cli.revalidate(original, output)
            self.assertFalse(result['semantic_approval'])
            self.assertEqual((original/'directions.json').read_bytes(), before)
            self.assertEqual((output/'original_directions.json').read_bytes(), before)
            with self.assertRaisesRegex(ValueError, 'Incomplete diagnostic'):
                cli.audition(output)
            with self.assertRaises(FileExistsError):
                cli.revalidate(original, output)

    def test_omitted_context_budget_remains_a_review_block_in_saved_plan(self):
        source = make('Background. '*300 + '"Stay."\n\n' + 'Background. '*300 + '"Go."')
        window = {'start': 0, 'end': len(source['text']), 'text': source['text']}
        catalog = a.source_catalog(source, window)
        target = next(row for row in catalog if row['quote'] == '"Go."')
        self.assertTrue(target['context_frame_omitted_by_budget'])
        span = turn(source, '"Go."')
        fields = {key: value for key, value in span.items() if key not in ('id', 'start', 'end', 'quote', 'evidence')}
        fields.update(quote_id=target['id'], evidence_id=target['id'])
        plan = a.incorporate(source, d.new_plan(source, 'local', 'pin'), window, {'spans': [fields], 'facts': []}, catalog)
        self.assertIn('omitted by budget', plan['spans'][0]['ambiguity'])
        self.assertEqual(d.compile_range(source, plan, span['start'], span['end'])['insertions'], [])


if __name__ == '__main__':
    unittest.main()
