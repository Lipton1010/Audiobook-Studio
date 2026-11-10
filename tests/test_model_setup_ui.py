import sys,tempfile,unittest
from pathlib import Path
from unittest.mock import patch,Mock
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/'app'))
import model_setup_ui as ui
class ModelSetupUITests(unittest.TestCase):
    def test_local_same_origin_action_allowed(self):
        self.assertTrue(ui.authorized({'Host':'localhost:8765','Origin':'http://localhost:8765','X-Storybird-Action':'model-setup'},'127.0.0.1',8765))
    def test_external_origins_hosts_and_missing_action_denied(self):
        base={'Host':'localhost:8765','X-Storybird-Action':'model-setup'}
        for change in [{'Origin':'https://evil.test'},{'Host':'evil.test:8765'},{'X-Storybird-Action':''}]:
            self.assertFalse(ui.authorized(base|change,'127.0.0.1',8765))
        self.assertFalse(ui.authorized(base,'192.168.1.2',8765))
    @unittest.skipUnless(sys.platform=='win32','Windows optional runtime GUI')
    def test_singleton_gui_launch_does_not_start_downloads(self):
        with tempfile.TemporaryDirectory() as folder:
            repo=Path(folder);(repo/'install').mkdir();(repo/'install/model_setup.py').touch()
            proc=Mock();proc.poll.return_value=None
            with patch.object(ui,'_PROCESS',None),patch.object(ui.subprocess,'Popen',return_value=proc) as start:
                self.assertTrue(ui.launch(repo));self.assertFalse(ui.launch(repo))
                start.assert_called_once();self.assertEqual(start.call_args.args[0],[sys.executable,str(repo/'install/model_setup.py')])

class ModelSetupRouteTests(unittest.TestCase):
    def test_cross_origin_route_cannot_launch_setup(self):
        import types,server
        request=types.SimpleNamespace(path='/api/models/setup',headers={'Host':'localhost:8765','Origin':'https://evil.test','X-Storybird-Action':'model-setup'},client_address=('127.0.0.1',1),server=types.SimpleNamespace(server_address=('127.0.0.1',8765)))
        with patch.object(ui,'launch') as launch,patch.object(server,'_json_response') as response:
            server.Handler.do_POST(request)
            launch.assert_not_called();self.assertEqual(response.call_args.args[2],403)
    def test_local_route_opens_picker_without_installing_model(self):
        import types,server
        request=types.SimpleNamespace(path='/api/models/setup',headers={'Host':'localhost:8765','Origin':'http://localhost:8765','X-Storybird-Action':'model-setup'},client_address=('127.0.0.1',1),server=types.SimpleNamespace(server_address=('127.0.0.1',8765)))
        with patch.object(ui,'launch',return_value=True) as launch,patch.object(server,'_json_response') as response:
            server.Handler.do_POST(request)
            launch.assert_called_once_with(server.APP_DIR.parent);self.assertTrue(response.call_args.args[1]['started'])
