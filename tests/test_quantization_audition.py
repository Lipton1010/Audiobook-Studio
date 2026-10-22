import copy
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'app'))
import scene_direction as d
import scene_direction_cli as cli


class QuantizationAuditionTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        voice = Path(self.temp.name) / 'reference.wav'
        voice.write_bytes(b'fixed reference fixture')
        self.source = d.canonical([{'text':'Mira said, "Stay." Jo nodded. Then Jo said, "I will."'}], 'extraction')
        self.config = {'reference_wav':str(voice), 'reference_text':'Same reference words.',
            'drama3_cpu_expert_layers':12, 'generation_settings':{'max_frames':1536,
            'temperature':1., 'top_p':.9, 'top_k':30, 'context_length':4096}}
        start = self.source['text'].index('Then')
        self.selections = [
            {'id':'passage1','start':0,'end':start-1,'review_note':'Complete first sentence pair.'},
            {'id':'passage2','start':start,'end':len(self.source['text']),'review_note':'Complete second turn.'}]

    def test_plain_quantization_ready_without_any_direction_plan(self):
        manifest = cli.quantization_manifest(self.source,self.config,self.selections)
        self.assertEqual(manifest['status'],'ready_fixed_text')
        self.assertFalse(manifest['annotation_dependency'])
        self.assertNotIn('plan_sha256',manifest)
        self.assertEqual(len(manifest['cases']),6)
        self.assertEqual(manifest['matched_cpu_expert_layers'],16)
        for selection in self.selections:
            cases=[r for r in manifest['cases'] if r['id'].startswith(selection['id'])]
            self.assertEqual([r['seed'] for r in cases],[1729,2718,31415])
            self.assertEqual({r['text'] for r in cases},{self.source['text'][selection['start']:selection['end']]})
        cli.validate_quantization_manifest(self.source,self.config,manifest)

    def test_settings_text_and_reference_tampering_rejected(self):
        original=cli.quantization_manifest(self.source,self.config,self.selections)
        for key,value in [('text','[angry] changed'),('seed',7),('temperature',.5),('voice_ref','other.wav')]:
            manifest=copy.deepcopy(original)
            manifest['cases'][0][key]=value
            with self.subTest(key=key), self.assertRaisesRegex(ValueError,'contract changed'):
                cli.validate_quantization_manifest(self.source,self.config,manifest)
        for key,value in [('matched_cpu_expert_layers',12),('cue_condition','angry'),('annotation_dependency',True)]:
            manifest=copy.deepcopy(original); manifest[key]=value
            with self.subTest(key=key), self.assertRaisesRegex(ValueError,'contract changed'):
                cli.validate_quantization_manifest(self.source,self.config,manifest)
        Path(self.config['reference_wav']).write_bytes(b'changed reference')
        with self.assertRaisesRegex(ValueError,'contract changed'):
            cli.validate_quantization_manifest(self.source,self.config,original)

    def test_overlapping_or_unreviewed_selection_rejected(self):
        for field,value in [('start',0),('review_note',''),('end',9999),('id','passage1')]:
            selections=copy.deepcopy(self.selections); selections[1][field]=value
            with self.subTest(field=field), self.assertRaises(ValueError):
                cli.quantization_manifest(self.source,self.config,selections)


if __name__=='__main__':
    unittest.main()
