import hashlib,importlib.util,io,tempfile,unittest
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
spec=importlib.util.spec_from_file_location('pinned_download',ROOT/'install/pinned_download.py');module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
class Response(io.BytesIO):
    def __init__(self,data,status=200,headers=None):super().__init__(data);self.status=status;self.headers=headers or {}
    def geturl(self):return 'https://example.test/file'
class DownloadTests(unittest.TestCase):
    def test_valid_and_existing_pin(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)/'x';h=hashlib.sha256(b'hello').hexdigest()
            module.download('https://example.test/file',p,h,5,lambda *a,**k:Response(b'hello'))
            self.assertEqual(p.read_bytes(),b'hello')
            module.download('https://example.test/file',p,h,5,lambda *a,**k:self.fail('No redownload'))
    def test_resume_exact_range(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)/'x';p.with_name('x.part').write_bytes(b'he')
            def open(req,**kw):
                self.assertEqual(req.headers['Range'],'bytes=2-');return Response(b'llo',206,{'Content-Range':'bytes 2-4/5'})
            module.download('https://example.test/file',p,hashlib.sha256(b'hello').hexdigest(),5,open)
            self.assertEqual(p.read_bytes(),b'hello')
    def test_mismatch_never_published(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)/'x'
            with self.assertRaisesRegex(ValueError,'checksum'):module.download('https://example.test/file',p,'0'*64,3,lambda *a,**k:Response(b'bad'))
            self.assertFalse(p.exists())
    def test_bad_resume_never_appended(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)/'x';part=p.with_name('x.part');part.write_bytes(b'he')
            with self.assertRaisesRegex(ValueError,'range'):module.download('https://example.test/file',p,'0'*64,5,lambda *a,**k:Response(b'bad',206,{'Content-Range':'bytes 0-2/5'}))
            self.assertEqual(part.read_bytes(),b'he')
    def test_existing_file_never_replaced(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)/'x';p.write_bytes(b'keep')
            with self.assertRaisesRegex(ValueError,'not replaced'):module.download('https://example.test/file',p,'0'*64,4)
            self.assertEqual(p.read_bytes(),b'keep')
