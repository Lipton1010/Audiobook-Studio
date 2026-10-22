import copy
import hashlib
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'app'))
import drama3
import scene_direction as d
import scene_analysis as a
import vibevoice_delivery as delivery
from vibevoice_plan import pack_passages
try:
    import vibevoice_worker as worker
except ModuleNotFoundError:
    worker = None


@unittest.skipUnless(worker, 'needs existing narration dependencies; no GPU inference')
class DirectionIntegrationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        root = Path(self.temp.name)
        assets = [root / name for name in ('native.exe', 'model.gguf', 'cuda.dll', 'voice.wav')]
        for path in assets:
            path.write_bytes(path.name.encode())
        for key, path in (('EXE_SHA256', assets[0]), ('MODEL_SHA256', assets[1])):
            patch = mock.patch.object(drama3, key, drama3.sha256_file(path))
            patch.start(); self.addCleanup(patch.stop)
        self.config = {'backend': 'drama3', 'drama3_executable': str(assets[0]), 'drama3_model': str(assets[1]),
                       'drama3_cuda_bin': str(root), 'reference_wav': str(assets[3]), 'reference_text': 'Reference.',
                       'source_voice_sha256': drama3.sha256_file(assets[3]), 'path': 'A'}
        self.blocks = [{'type': 'body', 'text': 'She whispered. "Stay here."'}]
        self.source = d.canonical(pack_passages(self.blocks, preserve_sentences=True), 'extraction')
        self.direction = d.new_plan(self.source, a.MODEL, a.MODEL_DIGEST)
        self.direction['spans'] = [{'id': 'turn', 'start': 15, 'end': 27, 'quote': '"Stay here."',
            'scene': 'door', 'kind': 'dialogue', 'speaker': 'woman', 'intention': 'protect', 'emotion': 'fear',
            'intensity': 1, 'delivery': 'whisper', 'confidence': .9, 'ambiguity': '',
            'evidence': [{'start': 0, 'end': 14, 'quote': 'She whispered.'}]}]
        self.bound = {'source': self.source, 'plan': self.direction}
        self.job = root / 'job'; self.job.mkdir()

    def make_plan(self, directed=True):
        if directed:
            drama3.write(self.job / 'scene_direction.json', self.bound)
        plan = drama3.write_plan(self.job, self.blocks, self.config)
        return plan, drama3.read(self.job / 'vibevoice_config.json')

    def test_optional_new_job_request_and_receipt_use_cues_but_checker_uses_plain_words(self):
        plan, config = self.make_plan()
        unit = worker._units_for_parent(plan['passages'][0], config)[0]
        rendered = worker._profiled_unit(unit)
        self.assertEqual(rendered['text'], 'She whispered. "Stay here."')
        self.assertEqual(rendered['render_text'], 'She whispered. [whisper]"Stay here."')
        request = drama3._request({'unit': rendered, 'attempt': 1}, config, self.job)
        self.assertEqual(request['text'], rendered['render_text'])
        receipt = {'render_profile': delivery.INTACT_PROFILE,
                   'spoken_text_sha256': d.digest(unit['text']),
                   'render_policy_sha256': delivery.policy_hash(delivery.INTACT_PROFILE),
                   'render_text_sha256': worker._render_text_sha256(unit, delivery.INTACT_PROFILE)}
        self.assertTrue(delivery.receipt_matches_projection(receipt, unit))
        receipt['render_text_sha256'] = d.digest(unit['text'])
        self.assertFalse(delivery.receipt_matches_projection(receipt, unit))
        self.assertEqual(drama3.write_plan(self.job, self.blocks, config), plan)

    def test_edited_direction_cannot_reuse_saved_plan(self):
        plan, config = self.make_plan()
        changed = copy.deepcopy(config)
        changed['scene_direction']['plan']['spans'][0]['delivery'] = 'calm'
        with self.assertRaises(ValueError):
            drama3.validate_plan(plan, changed)
        with self.assertRaises(ValueError):
            drama3.write_plan(self.job, self.blocks, changed)

    def test_legacy_runtime_unchanged_and_cannot_add_directions_to_saved_audio(self):
        plan, config = self.make_plan(False)
        self.assertNotIn('scene_direction_sha256', plan['runtime'])
        self.assertNotIn('scene_direction_compiled', worker._units_for_parent(plan['passages'][0], config)[0])
        drama3.write(self.job / 'scene_direction.json', self.bound)
        before = (self.job / 'vibevoice_plan.json').read_bytes()
        with self.assertRaises(ValueError):
            drama3.write_plan(self.job, self.blocks, config)
        self.assertEqual(before, (self.job / 'vibevoice_plan.json').read_bytes())

    def test_mismatched_chapter_refuses_before_saving_plan(self):
        self.blocks[0]['text'] += ' Invented continuation.'
        with self.assertRaises(ValueError):
            self.make_plan()
        self.assertFalse((self.job / 'vibevoice_plan.json').exists())

    def test_new_direction_has_new_parent_and_unit_identity(self):
        plan, config = self.make_plan()
        first = worker._units_for_parent(plan['passages'][0], config)[0]
        self.job = self.job.parent / 'second'; self.job.mkdir()
        self.direction['overrides']['turn'] = {'decision': 'plain', 'delivery': 'plain', 'speaker': 'woman', 'note': 'Keep calm'}
        second_plan, second_config = self.make_plan()
        second = worker._units_for_parent(second_plan['passages'][0], second_config)[0]
        self.assertNotEqual(first['identity'], second['identity'])
        self.assertEqual(first['text'], second['text'])


if __name__ == '__main__':
    unittest.main()
