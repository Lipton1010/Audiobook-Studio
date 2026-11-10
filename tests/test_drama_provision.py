import importlib.util,json,sys,tempfile,unittest
from pathlib import Path
from unittest.mock import patch, Mock
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'install'))
import provision_drama3 as provision
class ProvisionTests(unittest.TestCase):
    def setUp(self):
        disk=patch.object(provision.shutil, "disk_usage", return_value=Mock(free=100*1024**3))
        disk.start();self.addCleanup(disk.stop)
    def test_setup_can_install_while_generation_headroom_is_unavailable(self):
        machine={'selected_gpu':{'compute_capability':'8.9','total_gib':24,'free_gib':6},'ram_gib':31.7,'free_ram_gib':18}
        provision.check_setup_capacity(machine)
        machine['selected_gpu']['compute_capability']='7.5'
        with self.assertRaisesRegex(RuntimeError,'Ada'):provision.check_setup_capacity(machine)
    def test_setup_refuses_insufficient_capacity(self):
        machine={'selected_gpu':{'compute_capability':'8.9','total_gib':12,'free_gib':10},'ram_gib':31.7,'free_ram_gib':18}
        with self.assertRaisesRegex(RuntimeError,'20 GiB'):provision.check_setup_capacity(machine)

    def test_unpublished_runtime_fails_before_any_download(self):
        with tempfile.TemporaryDirectory() as folder, patch.object(provision,'inventory',return_value={}),patch.object(provision,'describe',return_value='test inventory'),patch.object(provision,'check_setup_capacity'),patch.object(provision,'download') as download:
            repo=Path(folder)/'repo';(repo/'install').mkdir(parents=True)
            manifest=json.loads((ROOT/'install/drama3-pack.json').read_text());manifest['runtime']['download_url']=None
            (repo/'install/drama3-pack.json').write_text(json.dumps(manifest))
            with patch.object(provision,'ROOT',repo),self.assertRaisesRegex(ValueError,'not published'):
                provision.provision(Path(folder)/'runtime')
            download.assert_not_called()
    def test_hardware_failure_prevents_download_and_runtime_install(self):
        with tempfile.TemporaryDirectory() as folder,patch.object(provision,'inventory',return_value={}),patch.object(provision,'describe',return_value='test inventory'),patch.object(provision,'check_setup_capacity',side_effect=RuntimeError('unsupported GPU')),patch.object(provision,'download') as download,patch.object(provision,'install_pack') as install:
            with self.assertRaisesRegex(RuntimeError,'unsupported GPU'):provision.provision(Path(folder),'archive.zip')
            download.assert_not_called();install.assert_not_called()
    def test_changed_existing_runtime_is_not_overwritten(self):
        with tempfile.TemporaryDirectory() as folder,patch.object(provision,'inventory',return_value={}),patch.object(provision,'describe',return_value='test inventory'),patch.object(provision,'check_setup_capacity'),patch.object(provision,'download') as download:
            root=Path(folder);target=root/'drama3-native';target.mkdir();sentinel=target/'audiocpp_cli.exe';sentinel.write_bytes(b'existing')
            with self.assertRaisesRegex(ValueError,'differs'):provision.provision(root,'archive.zip')
            self.assertEqual(sentinel.read_bytes(),b'existing');download.assert_not_called()
