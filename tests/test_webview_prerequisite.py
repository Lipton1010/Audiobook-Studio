import sys
import types
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'app'))
import launcher


class WebViewPrerequisiteTests(unittest.TestCase):
    def test_missing_runtime_stops_before_server_or_window(self):
        fake = types.ModuleType('webview')
        with patch.dict(sys.modules, {'webview': fake}), \
             patch.object(launcher, '_require_webview2', side_effect=RuntimeError('Missing runtime')), \
             patch.object(launcher, '_show_error') as error, \
             patch.object(launcher, '_start_server_thread') as server, \
             patch.object(launcher, '_open_native_window') as window:
            launcher.main()
        server.assert_not_called()
        window.assert_not_called()
        self.assertIn('https://developer.microsoft.com/microsoft-edge/webview2/', error.call_args.args[1])

    def test_windows_loader_missing_version_fails(self):
        with patch.object(launcher.sys, 'platform', 'win32'), \
             patch.object(launcher, '_webview2_version', return_value=None):
            with self.assertRaisesRegex(RuntimeError, 'not installed or usable'):
                launcher._require_webview2(object())

    def test_windows_loader_failure_fails_clearly(self):
        with patch.object(launcher.sys, 'platform', 'win32'), \
             patch.object(launcher, '_webview2_version', side_effect=OSError('loader missing')):
            with self.assertRaisesRegex(RuntimeError, 'could not be checked'):
                launcher._require_webview2(object())

    def test_available_runtime_passes(self):
        with patch.object(launcher.sys, 'platform', 'win32'), \
             patch.object(launcher, '_webview2_version', return_value='143.0.0.1'):
            launcher._require_webview2(object())

    def test_other_platform_does_not_load_windows_dll(self):
        with patch.object(launcher.sys, 'platform', 'linux'), \
             patch.object(launcher, '_webview2_version') as query:
            launcher._require_webview2(object())
        query.assert_not_called()
