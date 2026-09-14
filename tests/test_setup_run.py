import subprocess
import sys
import unittest
from pathlib import Path

import setup


class SetupRunTests(unittest.TestCase):
    def test_run_accepts_path_command_parts(self):
        result = setup.run([Path(sys.executable), '-c', 'print("setup run works")'],
                           capture_output=True, text=True, check=True)
        self.assertEqual(result.stdout.strip(), 'setup run works')


if __name__ == '__main__':
    unittest.main()
