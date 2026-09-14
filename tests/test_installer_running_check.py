import subprocess
import sys
import time
import unittest
from pathlib import Path


@unittest.skipUnless(sys.platform == 'win32', 'Windows installer helper')
class InstallerRunningCheckTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.root = Path(__file__).resolve().parents[1]
        cls.script = cls.root / 'install/check_running_app.ps1'
        cls.power_shell = Path(r'C:\Windows\System32\WindowsPowerShell\v1.0\powershell.exe')

    def check(self):
        return subprocess.run([
            self.power_shell, '-NoProfile', '-NonInteractive', '-ExecutionPolicy', 'Bypass',
            '-File', self.script, '-AppRoot', self.root,
        ], timeout=20).returncode

    def test_detects_exact_app_process_without_matching_unrelated_python(self):
        self.assertEqual(self.check(), 0)
        process = subprocess.Popen([
            sys.executable, '-c', 'import time; time.sleep(20)',
            str(self.root / 'app/server.py'),
        ])
        try:
            time.sleep(0.25)
            self.assertEqual(self.check(), 9)
        finally:
            process.terminate()
            process.wait(timeout=10)


if __name__ == '__main__':
    unittest.main()
