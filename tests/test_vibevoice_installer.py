"""Static closure checks for the installer paths; Inno compilation is release-only."""
import unittest
from pathlib import Path


class VibeVoiceInstallerTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        root = Path(__file__).resolve().parents[1]
        cls.setup = (root / 'setup.py').read_text(encoding='utf-8')
        cls.full = (root / 'install/AudiobookStudio.iss').read_text(encoding='utf-8')
        cls.patch = (root / 'install/AudiobookStudio_Patch.iss').read_text(encoding='utf-8')

    def test_setup_defaults_to_vibevoice_bootstrap(self):
        self.assertIn('choices=("vibevoice", "chatterbox")', self.setup)
        self.assertIn('default="vibevoice"', self.setup)
        self.assertIn('bootstrap_vibevoice.py", "--install"', self.setup)

    def test_full_installer_runs_setup_with_private_runtime(self):
        self.assertIn('--runtime-root', self.full)
        self.assertIn("function SetupPySucceeded", self.full)
        self.assertIn("Check: SetupPySucceeded", self.full)
        self.assertIn('Source: "..\\install\\check_running_app.ps1"; Flags: dontcopy', self.full)
        self.assertIn("ExtractTemporaryFile('check_running_app.ps1')", self.full)
        self.assertIn('function GetCustomSetupExitCode', self.full)
        self.assertIn('up to 20 GB of disk space', self.full)

    def test_installers_refuse_to_patch_a_running_new_app(self):
        self.assertIn('AppMutex=AudiobookStudio_1E05_4C9D_9B5D_204F12CD7183', self.full)
        self.assertIn('AppMutex=AudiobookStudio_1E05_4C9D_9B5D_204F12CD7183', self.patch)
        self.assertIn('function InstalledAppIsRunning', self.patch)
        self.assertIn('check_running_app.ps1', self.patch)
        self.assertIn('Source: "..\\install\\check_running_app.ps1"; Flags: dontcopy', self.patch)
        self.assertIn("ExtractTemporaryFile('check_running_app.ps1')", self.patch)
        self.assertIn("ExpandConstant('{tmp}\\check_running_app.ps1')", self.patch)
        self.assertIn('GetCustomSetupExitCode', self.patch)
        helper = (Path(__file__).resolve().parents[1] / 'install/check_running_app.ps1').read_text(encoding='utf-8')
        self.assertIn('app\\narrate_worker.py', helper)
        self.assertIn('app\\vibevoice_worker.py', helper)

    def test_patch_provisions_vibevoice_and_suppresses_launch_on_failure(self):
        self.assertIn('bootstrap_vibevoice.py', self.patch)
        self.assertIn('--install --conda', self.patch)
        self.assertIn('PrivateBasePython', self.patch)
        self.assertIn('PrivateConda', self.patch)
        self.assertIn('LogPath := ExpandConstant', self.patch)
        self.assertIn('2>&1', self.patch)
        self.assertIn('PatchSetupSucceeded', self.patch)
        self.assertIn('Check: PatchSetupSucceeded', self.patch)


if __name__ == '__main__':
    unittest.main()
