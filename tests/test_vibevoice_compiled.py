import json
import tempfile
import unittest
import sys
import types
from pathlib import Path
from unittest import mock

from app import vibevoice_plan as plan
from app import vibevoice_hf as hf


class CompiledPlanTests(unittest.TestCase):
    def test_legacy_identity_is_unchanged_and_compiled_is_distinct(self):
        self.assertEqual(plan.runtime_profile({}), plan.RUNTIME)
        self.assertEqual(plan.runtime_profile({'inference_backend': 'legacy'}), plan.RUNTIME)
        compiled = plan.runtime_profile({'inference_backend': 'compiled'})
        self.assertEqual(compiled['transformers_version'], '5.19.0')
        self.assertNotEqual(plan.passage_identity('Words.', 'voice'),
                            plan.passage_identity('Words.', 'voice', compiled))
        with self.assertRaisesRegex(ValueError, 'Unknown'):
            plan.runtime_profile({'inference_backend': 'typo'})

    def test_compiled_plan_roundtrip_and_runtime_tampering(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            voice = root / 'voice.wav'
            voice.write_bytes(b'synthetic reference')
            config = {'reference_wav': str(voice), 'model_dir': 'model', 'inference_backend': 'compiled'}
            with mock.patch.object(plan, 'model_fingerprint', return_value='model fingerprint'):
                expected = plan.write_plan(root, [{'type': 'body', 'text': 'Synthetic sentence.'}], config)
                actual, saved = plan.load_plan(root)
                self.assertEqual(actual, expected)
                self.assertEqual(saved['inference_backend'], 'compiled')
                saved['transformers_version'] = '5.18.0'
                (root / plan.CONFIG_FILENAME).write_text(json.dumps(saved))
                with self.assertRaisesRegex(ValueError, 'transformers_version'):
                    plan.load_plan(root)


class CompiledGenerationTests(unittest.TestCase):
    def test_cap_detection_ignores_prompt_padding_and_keeps_batch_rows(self):
        try:
            import torch
        except ImportError:
            self.skipTest('torch is not installed in this test environment')
        class Inputs(dict):
            def to(self, *args):
                return self
        inputs = Inputs(input_ids=torch.tensor([[0, 5], [0, 6]]),
                        attention_mask=torch.tensor([[0, 1], [0, 1]]))
        processor = mock.Mock()
        processor.apply_chat_template.return_value = inputs
        outputs = [torch.ones(3), torch.ones(8)]
        model = mock.Mock(device='cpu', dtype=torch.float32)
        model.generation_config.eos_token_id = 0
        model.generate.return_value = types.SimpleNamespace(
            audio=outputs, sequences=torch.tensor([[0, 5, 9, 0], [0, 6, 9, 9]]))
        with mock.patch.dict(sys.modules, {'transformers': types.SimpleNamespace(CompileConfig=mock.Mock())}), \
             mock.patch.object(torch.compiler, 'cudagraph_mark_step_begin'):
            audio, capped = hf.generate(torch, processor, model, [], [{'text': 'Short.'}, {'text': 'Longer.'}], plan.RUNTIME)
            self.assertIs(audio, outputs)
            self.assertEqual(capped.tolist(), [False, True])
            self.assertEqual(model.generate.call_args.kwargs['cache_implementation'], 'static')
            with self.assertRaisesRegex(RuntimeError, 'input-token ceiling'):
                hf.generate(torch, processor, model, [], [{'text': 'Words.'}], {**plan.RUNTIME, 'max_input_tokens': 0})
