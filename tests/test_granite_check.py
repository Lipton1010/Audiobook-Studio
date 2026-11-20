import sys
import unittest
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'app'))
import granite_check

class GraniteCheckTests(unittest.TestCase):
    def test_chunking_preserves_every_sample_and_respects_limit(self):
        source = bytes(16000 * 2 * 59)
        parts = list(granite_check.chunks(source))
        self.assertEqual(len(parts), 3)
        self.assertEqual(b''.join(parts), source)
        self.assertTrue(all(0 < len(part) <= 16000*2*27 for part in parts))

    @patch.object(granite_check, 'setup_error', return_value=None)
    @patch.object(granite_check, 'request')
    def test_other_ollama_workload_blocks_check(self, mock_request, _):
        mock_request.return_value = {'models': [{'name': 'unrelated:model'}]}
        with self.assertRaisesRegex(RuntimeError, 'free GPU'):
            granite_check.load()

    @patch.object(granite_check, 'ffmpeg_path', return_value='ffmpeg')
    @patch.object(granite_check, 'request', return_value={'models': []})
    def test_missing_model_names_install_step(self, _, __):
        self.assertIn('ollama pull ibm/granite5-speech:2b', granite_check.setup_error())
