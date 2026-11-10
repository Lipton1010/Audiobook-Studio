import sys
import types
import unittest
from pathlib import Path
from unittest.mock import patch, Mock
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'install'))
import bootstrap_webview2 as bootstrap

class BootstrapWebViewTests(unittest.TestCase):
    def setUp(self):
        self.module_patch = patch.dict(sys.modules, {'webview': types.ModuleType('webview')})
        self.module_patch.start()
        self.addCleanup(self.module_patch.stop)

    def test_existing_runtime_never_downloads_or_installs(self):
        with patch.object(bootstrap.sys, 'platform', 'win32'), patch.object(bootstrap, 'runtime_version', return_value='157.0'), patch.object(bootstrap, 'download') as download, patch.object(bootstrap.subprocess, 'run') as run:
            self.assertEqual(bootstrap.ensure_runtime(), '157.0')
        download.assert_not_called(); run.assert_not_called()

    def test_missing_runtime_without_consent_never_downloads(self):
        with patch.object(bootstrap.sys, 'platform', 'win32'), patch.object(bootstrap, 'runtime_version', return_value=None), patch.object(bootstrap, 'download') as download:
            with self.assertRaisesRegex(RuntimeError, '--yes is not consent'):
                bootstrap.ensure_runtime()
        download.assert_not_called()

    def test_elevated_install_refused(self):
        with patch.object(bootstrap.sys, 'platform', 'win32'), patch.object(bootstrap, 'runtime_version', return_value=None), patch.object(bootstrap.platform, 'machine', return_value='AMD64'), patch.object(bootstrap.ctypes, 'windll', create=True) as dll, patch.object(bootstrap, 'download') as download:
            dll.shell32.IsUserAnAdmin.return_value = 1
            with self.assertRaisesRegex(RuntimeError, 'without administrator'):
                bootstrap.ensure_runtime(accept_terms=True)
        download.assert_not_called()

    def test_pinned_install_is_rechecked(self):
        with patch.object(bootstrap.sys, 'platform', 'win32'), patch.object(bootstrap, 'runtime_version', side_effect=[None, '157.0']), patch.object(bootstrap.platform, 'machine', return_value='AMD64'), patch.object(bootstrap.ctypes, 'windll', create=True) as dll, patch.object(bootstrap, 'download', return_value=Path('reviewed.exe')) as download, patch.object(bootstrap.subprocess, 'run', return_value=Mock(returncode=0)) as run:
            dll.shell32.IsUserAnAdmin.return_value = 0
            self.assertEqual(bootstrap.ensure_runtime(accept_terms=True), '157.0')
            self.assertEqual(download.call_args.args[2:], (bootstrap.SHA256, bootstrap.SIZE))
            run.assert_called_once_with(['reviewed.exe', '/silent', '/install'], timeout=600)

    def test_failed_install_never_reports_success(self):
        with patch.object(bootstrap.sys, 'platform', 'win32'), patch.object(bootstrap, 'runtime_version', return_value=None), patch.object(bootstrap.platform, 'machine', return_value='AMD64'), patch.object(bootstrap.ctypes, 'windll', create=True) as dll, patch.object(bootstrap, 'download', return_value=Path('reviewed.exe')), patch.object(bootstrap.subprocess, 'run', return_value=Mock(returncode=1)):
            dll.shell32.IsUserAnAdmin.return_value = 0
            with self.assertRaisesRegex(RuntimeError, 'returned 1'):
                bootstrap.ensure_runtime(accept_terms=True)

    def test_other_platform_is_noop(self):
        with patch.object(bootstrap.sys, 'platform', 'linux'), patch.object(bootstrap, 'runtime_version') as probe:
            self.assertIsNone(bootstrap.ensure_runtime(accept_terms=True))
        probe.assert_not_called()
