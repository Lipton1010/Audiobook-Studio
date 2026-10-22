import copy
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "app"))
import scene_direction as d
import scene_analysis as a


class DirectionTests(unittest.TestCase):
    def setUp(self):
        self.text = 'Mira kept her fear hidden. "Stay here," she whispered. "I will return."'
        self.source = d.canonical([{"text": self.text}], "extraction-hash")
        self.plan = d.new_plan(self.source, a.MODEL, a.MODEL_DIGEST)
        quote = '"I will return."'
        start = self.text.index(quote)
        evidence = 'she whispered'
        offset = self.text.index(evidence)
        self.plan["spans"] = [{"id": "line", "start": start, "end": start + len(quote), "quote": quote,
                              "scene": "doorway", "kind": "dialogue", "speaker": "Mira",
                              "intention": "reassure", "emotion": "fear", "intensity": 2,
                              "delivery": "whisper", "confidence": .95,
                              "evidence": [{"start": offset, "end": offset + len(evidence), "quote": evidence}],
                              "ambiguity": ""}]

    def compile(self):
        return d.compile_range(self.source, self.plan, 0, len(self.text))

    def test_source_is_separate_and_exact_including_unicode_whitespace(self):
        text = '  A\r\n\U0001f600 [angry] B\t'
        source = d.canonical([{"text": text}], 'hash')
        self.assertEqual(d.validate_source(source), text)
        plan = d.new_plan(source, a.MODEL, a.MODEL_DIGEST)
        self.assertEqual(d.compile_range(source, plan, 0, len(text))["render_text"], text)

    def test_cue_insertion_preserves_source_and_only_tags_dialogue(self):
        before = copy.deepcopy(self.source)
        result = self.compile()
        self.assertEqual(result['render_text'], self.text.replace('"I will', '[whisper]"I will'))
        self.assertEqual(self.source, before)
        self.assertEqual(len(result['insertions']), 1)
        self.assertEqual(d.render_unit({'scene_direction_compiled': result}, self.text), result['render_text'])

    def test_concealed_fear_with_calm_delivery_is_not_fear_tag(self):
        self.plan['spans'][0].update(emotion='terror', intensity=3, delivery='calm')
        self.assertEqual(self.compile()['render_text'], self.text)

    def test_unknown_cue_falls_back_and_is_visible(self):
        self.plan['spans'][0]['delivery'] = 'furious secretly but smiling'
        result = self.compile()
        self.assertEqual(result['render_text'], self.text)
        self.assertIn('unsupported', result['review'][0]['reason'])

    def test_ambiguity_is_not_silently_guessed(self):
        for change in ({'confidence': .3}, {'speaker': 'unknown'}, {'ambiguity': 'possibly the other speaker'}):
            with self.subTest(change=change):
                plan = copy.deepcopy(self.plan)
                self.plan['spans'][0].update(change)
                self.assertEqual(self.compile()['render_text'], self.text)
                self.assertTrue(self.compile()['review'])
                self.plan = plan

    def test_plain_ambiguity_still_surfaces(self):
        self.plan['spans'][0].update(delivery='plain', speaker='unknown')
        self.assertTrue(self.compile()['review'])

    def test_user_override_is_source_bound_and_does_not_rewrite_model_note(self):
        self.plan['spans'][0]['confidence'] = .1
        original = copy.deepcopy(self.plan['spans'])
        self.plan['overrides']['line'] = {'decision': 'use', 'delivery': 'whisper', 'speaker': 'Mira', 'note': 'Checked the source attribution'}
        self.assertTrue(self.compile()['insertions'])
        self.assertEqual(original, self.plan['spans'])
        self.plan['overrides']['line']['decision'] = 'plain'
        self.assertEqual(self.compile()['render_text'], self.text)

    def test_no_nonverbal_event_without_user_choice(self):
        self.plan['spans'][0]['delivery'] = 'sighs'
        self.assertEqual(self.compile()['render_text'], self.text)
        self.assertIn('explicit user', self.compile()['review'][0]['reason'])

    def test_narrator_is_not_directed_by_character_emotion(self):
        self.plan['spans'][0].update(kind='narrator', speaker='narrator', delivery='angry')
        self.assertEqual(self.compile()['render_text'], self.text)

    def test_no_cue_leaks_into_following_narration(self):
        span = self.plan['spans'][0]
        quote = '"Stay here,"'
        span.update(start=self.text.index(quote), end=self.text.index(quote) + len(quote), quote=quote)
        self.assertEqual(self.compile()['render_text'], self.text)
        self.assertIn('reset', self.compile()['review'][0]['reason'])

    def test_split_turn_is_held_without_changing_boundaries(self):
        start = self.plan['spans'][0]['start'] + 2
        result = d.compile_range(self.source, self.plan, start, len(self.text))
        self.assertEqual(result['render_text'], self.text[start:])
        self.assertIn('boundary', result['review'][0]['reason'])

    def test_projection_difference_requires_alignment_review(self):
        result = d.compile_range(self.source, self.plan, 0, len(self.text), self.text.replace('Mira', 'M.'))
        self.assertFalse(result['insertions'])
        self.assertIn('projection', result['review'][0]['reason'])

    def test_native_character_limit_includes_cues_without_truncation(self):
        result = d.compile_range(self.source, self.plan, 0, len(self.text), max_chars=len(self.text))
        self.assertEqual(result['render_text'], self.text)
        self.assertTrue(result['review'])
        with self.assertRaises(ValueError):
            d.compile_range(self.source, self.plan, 0, len(self.text), max_chars=5)

    def test_invalid_schema_and_stale_source_are_rejected(self):
        for key, value in [('start', True), ('quote', 'invented'), ('confidence', float('nan')),
                           ('intensity', True), ('evidence', []), ('end', 999999)]:
            plan = copy.deepcopy(self.plan)
            plan['spans'][0][key] = value
            with self.subTest(key=key), self.assertRaises(ValueError):
                d.validate_plan(self.source, plan)
        changed = copy.deepcopy(self.source)
        changed['text'] += '!'
        with self.assertRaises(ValueError):
            d.validate_plan(changed, self.plan)

    def test_duplicate_or_overlapping_span_rejected(self):
        self.plan['spans'].append(copy.deepcopy(self.plan['spans'][0]))
        with self.assertRaises(ValueError):
            self.compile()

    def test_plan_identity_changes_with_override_or_context(self):
        old = d.digest(self.plan)
        self.plan['overrides']['line'] = {'decision': 'plain', 'delivery': 'plain', 'speaker': 'Mira', 'note': 'Keep understated'}
        self.assertNotEqual(old, d.digest(self.plan))

    def test_compiler_rejects_altered_output_even_if_hash_updated(self):
        result = self.compile()
        result['render_text'] += ' invented'
        result['render_sha256'] = d.digest(result['render_text'])
        with self.assertRaises(ValueError):
            d.render_unit({'scene_direction_compiled': result}, self.text)

    def test_existing_undirected_config_is_noop(self):
        units = [{'text': self.text}]
        self.assertIs(d.attach_units(units, {'text': self.text}, {}), units)
        self.assertEqual(d.render_unit({}, self.text), self.text)

    def test_units_map_to_exact_canonical_spans(self):
        unit = {'text': self.text, 'spoken_text': self.text}
        output = d.attach_units([unit], {'text': self.text, 'index': 0}, {'scene_direction': {'source': self.source, 'plan': self.plan}})
        self.assertEqual(output[0]['text'], unit['text'])
        self.assertTrue(output[0]['scene_direction_compiled']['insertions'])

    def test_analyzer_rejects_invented_and_repeated_anchors(self):
        window = {'text': 'No. No. She whispered.', 'start': 20}
        for quote in ('No.', 'invented'):
            with self.assertRaises(ValueError):
                a.anchor(quote, window)
        self.assertEqual(a.anchor('She whispered.', window)['start'], 28)

    def test_analysis_windows_cover_every_character_and_keep_context(self):
        source = d.canonical([{'text': ('A sentence. Another sentence. ' * 100)}], 'hash')
        windows = list(a.windows(source, 300))
        self.assertEqual(''.join(w['text'] for w in windows), source['text'])
        self.assertTrue(windows[1]['preceding_text'])
        self.assertTrue(windows[0]['following_text'])

    def test_catalog_keeps_repeated_unicode_turns_distinct(self):
        source = d.canonical([{'text': 'Mira said \u201cNo.\u201d Jo said \u201cNo.\u201d'}], 'hash')
        window = next(a.windows(source))
        catalog = a.source_catalog(source, window)
        turns = [r for r in catalog if r['candidate_kind'] == 'dialogue']
        self.assertEqual(len(turns), 2)
        self.assertNotEqual(turns[0]['id'], turns[1]['id'])
        row = {k:v for k,v in self.plan['spans'][0].items() if k not in ('id','start','end','quote','evidence')}
        row.update(quote_id=turns[1]['id'], evidence_id=catalog[-1]['id'])
        plan = a.incorporate(source, d.new_plan(source,a.MODEL,a.MODEL_DIGEST),window,{'spans':[row],'facts':[]},catalog)
        self.assertEqual(plan['spans'][0]['start'],turns[1]['start'])
        self.assertEqual(plan['spans'][0]['quote'],'\u201cNo.\u201d')
        row['quote_id']='invented'
        with self.assertRaisesRegex(ValueError,'catalog ID'):
            a.incorporate(source, d.new_plan(source,a.MODEL,a.MODEL_DIGEST),window,{'spans':[row],'facts':[]},catalog)

    def test_catalog_does_not_truncate_a_turn_at_window_boundary(self):
        source = d.canonical([{'text':'Before. "A long complete turn." After.'}], 'hash')
        window={'start':0,'end':20,'text':source['text'][:20]}
        self.assertEqual(a.source_catalog(source,window),[])

    def test_window_without_complete_quotes_does_not_call_model(self):
        source=d.canonical([{'text':'Ordinary narration. Nothing is spoken here.'}],'hash')
        director=mock.Mock(spec=['analyze'])
        with tempfile.TemporaryDirectory() as temp:
            plan=a.analyze_source(source,temp,director)
        director.analyze.assert_not_called()
        self.assertEqual(plan['spans'],[])

    def test_incomplete_diagnostic_cannot_bind_or_audition(self):
        import scene_direction_cli as cli
        with tempfile.TemporaryDirectory() as temp:
            Path(temp,'analysis_review_status.json').write_text('{"complete":false}')
            with self.assertRaisesRegex(ValueError,'Incomplete diagnostic'):
                cli.audition(temp)
            with self.assertRaisesRegex(ValueError,'Incomplete diagnostic'):
                cli.bind(temp,Path(temp,'unused'))

    def test_review_embedded_text_roundtrips_html_characters(self):
        import scene_direction_cli as cli
        source=d.canonical([{'text':'Literal </script><b> & text.'}],'hash')
        with tempfile.TemporaryDirectory() as temp:
            folder=Path(temp)
            cli.write(folder/'canonical.json',source)
            cli.write(folder/'directions.json',d.new_plan(source,a.MODEL,a.MODEL_DIGEST))
            cli.write(folder/'baseline_config.json',{})
            units=mock.Mock(repair_units=lambda parent,**kwargs:[{'text':parent['text']}])
            with mock.patch.dict(sys.modules,{'vibevoice_units':units}):
                cli.review(folder)
            html=(folder/'review.html').read_text(encoding='utf-8')
        embedded=html.split('const data=',1)[1].split(';const plan=',1)[0]
        self.assertNotIn('<',embedded)
        self.assertEqual(json.loads(embedded)['source'],source)

    def test_gpu_gate_does_not_make_any_request(self):
        calls = []
        with self.assertRaisesRegex(RuntimeError, 'GPU GATE'):
            with a.LocalDirector(request=lambda *args: calls.append(args)):
                pass
        self.assertEqual(calls, [])

    def test_local_director_unloads_on_analysis_exception(self):
        calls, resident = [], []
        def request(endpoint, payload=None):
            calls.append((endpoint, payload))
            if endpoint == 'tags':
                return {'models': [{'name': a.MODEL, 'digest': a.MODEL_DIGEST}]}
            if endpoint == 'ps':
                return {'models': resident.copy()}
            if endpoint == 'generate':
                resident[:] = [] if payload['keep_alive'] == 0 else [{'name': a.MODEL, 'digest': a.MODEL_DIGEST, 'size': 10, 'size_vram': 10}]
                return {}
        with self.assertRaisesRegex(ValueError, 'fixture'):
            with a.LocalDirector(True, request):
                raise ValueError('fixture')
        self.assertEqual(resident, [])
        self.assertEqual(calls[-2][1]['keep_alive'], 0)

    def test_explicit_pinned_candidate_keeps_its_identity_and_unloads(self):
        resident, calls = [], []
        def request(endpoint, payload=None):
            calls.append((endpoint,payload))
            if endpoint=='tags': return {'models':[{'name':'candidate:local','digest':'candidate-pin'}]}
            if endpoint=='ps': return {'models':resident.copy()}
            if endpoint=='generate':
                resident[:]=[] if payload['keep_alive']==0 else [{'name':'candidate:local','digest':'candidate-pin','size':20,'size_vram':20}]
            return {}
        with a.LocalDirector(True,request,model='candidate:local',model_digest='candidate-pin',options={'num_ctx':4096},think=False) as director:
            director.analyze({'anchors':a.source_catalog(self.source,next(a.windows(self.source)))})
        chat=next(p for e,p in calls if e=='chat')
        self.assertEqual(chat['model'],'candidate:local')
        self.assertFalse(chat['think'])
        self.assertEqual(chat['options'],{'num_ctx':4096})
        self.assertEqual(resident,[])
        self.assertEqual(calls[-2][1]['model'],'candidate:local')

    def test_cloud_alias_and_partial_gpu_are_rejected(self):
        for remote in (True, False):
            resident = []
            def request(endpoint, payload=None):
                if endpoint == 'tags':
                    return {'models': [{'name': a.MODEL, 'digest': a.MODEL_DIGEST, **({'remote_host': 'cloud'} if remote else {})}]}
                if endpoint == 'ps':
                    return {'models': resident.copy()}
                if endpoint == 'generate':
                    resident[:] = [] if payload['keep_alive'] == 0 else [{'name': a.MODEL, 'digest': a.MODEL_DIGEST, 'size': 10, 'size_vram': 5}]
                    return {}
            with self.assertRaises(RuntimeError):
                with a.LocalDirector(True, request):
                    pass
            self.assertFalse(resident)

    def test_cache_carries_source_without_model_memory_and_replays_without_inference(self):
        source = d.canonical([{'text': 'Mira whispered. "Stay."\n\nMira returned. "Safe."'}], 'hash')
        chunks = list(a.windows(source, 25))
        self.assertEqual(len(chunks), 2)
        calls = []
        class FakeDirector:
            def analyze(self, payload):
                calls.append(payload)
                quote = 'Mira whispered.' if payload['start'] == 0 else 'Mira returned.'
                result = {'spans': [], 'facts': [{'character': 'Mira', 'fact': quote, 'evidence': quote}]}
                return {'done': True, 'done_reason': 'stop', 'message': {'content': json.dumps(result)}}
        with tempfile.TemporaryDirectory() as temp, mock.patch.object(a, 'windows', return_value=iter(chunks)):
            plan = a.analyze_source(source, temp, FakeDirector())
            self.assertEqual(len(calls), 2)
            self.assertEqual(calls[1]['context'], [])
            self.assertEqual(calls[1]['previous_direction'], [])
            self.assertIn('Mira whispered.', calls[1]['preceding_text'])
            self.assertEqual(calls[1]['context_policy'], a.CONTEXT_POLICY)
            self.assertEqual(len(plan['context']), 2)
            with mock.patch.object(a, 'windows', return_value=iter(chunks)):
                self.assertEqual(a.analyze_source(source, temp, FakeDirector()), plan)
            self.assertEqual(len(calls), 2)
            with mock.patch.object(a, 'windows', return_value=iter(chunks)), mock.patch.object(a, 'OPTIONS', {**a.OPTIONS, 'seed': 7}):
                a.analyze_source(source, temp, FakeDirector())
            self.assertEqual(len(calls), 4)

    def test_incomplete_analysis_is_retained_but_cannot_compile(self):
        class FakeDirector:
            def analyze(self, payload):
                return {'done': True, 'done_reason': 'length', 'message': {'content': '{'}}
        with tempfile.TemporaryDirectory() as temp:
            with self.assertRaisesRegex(ValueError, 'Incomplete'):
                a.analyze_source(self.source, temp, FakeDirector())
            raw = list(Path(temp).glob('*.json'))
            self.assertEqual(len(raw), 1)
            self.assertEqual(json.loads(raw[0].read_text())['raw']['done_reason'], 'length')


if __name__ == '__main__':
    unittest.main()
