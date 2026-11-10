import unittest
from unittest.mock import patch
from app.model_hardware import parse_gpus, inventory, describe, MODEL_CHOICES, require_generation_capacity


class HardwareTests(unittest.TestCase):
    def test_rows_keep_separate_devices(self):
        rows = parse_gpus('0, GPU A, 8192, 4096, 580.88\n1, GPU B, 24576, 22000, 580.88')
        self.assertEqual([g['total_gib'] for g in rows], [8, 24])

    def test_invalid_memory_is_not_presence(self):
        self.assertEqual(parse_gpus('0, GPU, N/A, N/A, 580.88\n0, GPU, nan, 1, 580.88\n0, GPU, 8, 9, 580.88'), [])

    @patch('app.model_hardware.subprocess.run', side_effect=OSError('missing'))
    def test_query_failure_unknown(self, run):
        result = inventory('.')
        self.assertEqual(result['gpus'], [])
        self.assertIsNone(result['selected_gpu'])
        self.assertIn('unknown', describe(result))

    @patch.dict('os.environ', {'CUDA_VISIBLE_DEVICES': '1'})
    @patch('app.model_hardware.subprocess.run')
    def test_remapped_device_not_guessed(self, run):
        run.return_value.returncode = 0
        run.return_value.stdout = '0, GPU, 8192, 4096, 580.88'
        self.assertIsNone(inventory('.')['selected_gpu'])

    def test_generation_admission_is_read_only_and_model_specific(self):
        machine = {"selected_gpu": {"free_gib": 10, "compute_capability": "8.9"}, "free_ram_gib": 16, "free_disk_gib": 5}
        self.assertIs(require_generation_capacity("vibevoice", ".", machine), machine)
        with self.assertRaisesRegex(RuntimeError, "paused before model loading"):
            require_generation_capacity("drama3", ".", machine)
        self.assertEqual(machine["selected_gpu"]["free_gib"], 10)

    def test_generation_unknown_device_refuses_fallback(self):
        with self.assertRaisesRegex(RuntimeError, "no CPU fallback"):
            require_generation_capacity("vibevoice", ".", {"selected_gpu": None})

    def test_drama_evidence_does_not_claim_twelve_layer_success(self):
        evidence = MODEL_CHOICES["drama3"]["evidence"]
        self.assertIn("four-layer default", evidence)
        self.assertIn("remain unvalidated", evidence)
        self.assertNotIn("passed with 22.75", evidence)

    def test_core_installer_explicitly_selects_no_narrator(self):
        from pathlib import Path
        source = (Path(__file__).resolve().parents[1] / "install" / "AudiobookStudio.iss").read_text()
        self.assertIn("--narrator none --auto-install-ffmpeg", source)
        self.assertNotIn("--prefetch-weights", source)

    def test_model_evidence_disclosed(self):
        self.assertEqual(set(MODEL_CHOICES), {'none', 'vibevoice', 'chatterbox', 'drama3'})
        for model in MODEL_CHOICES.values():
            self.assertTrue(model['vram'])
            self.assertTrue(model['evidence'])


if __name__ == '__main__':
    unittest.main()
