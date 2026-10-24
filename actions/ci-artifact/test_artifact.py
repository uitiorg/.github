import copy,io,json,os,tempfile,unittest,zipfile
from pathlib import Path
from ci_artifact import context,prefix,publish,restore,read_bundle,pack,select,FileStore,canonical,digest

class BundleTests(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory();self.root=Path(self.tmp.name);self.s=FileStore(self.root/'store')
  self.c=context('uitiorg/btalk2.1_backend','smoke.yml','123','1','test','evidence','a'*40)
  self.files={'test/TEST-suite.xml':b'<testsuite tests="1"/>','summary.json':b'{"passed":1}'}
 def tearDown(self):self.tmp.cleanup()
 def publish(self):return publish(self.s,self.files,self.c,3)
 def path(self,name):return self.s.root/(prefix(self.c)+'/'+name)
 def test_roundtrip_and_exact_hash(self):
  h=self.publish();self.assertEqual(restore(self.s,self.c,self.root/'out',h),h)
  for n,b in self.files.items():self.assertEqual((self.root/'out'/n).read_bytes(),b)
 def test_retry_identical(self):self.assertEqual(self.publish(),self.publish())
 def test_immutable_conflict(self):
  self.publish();self.files['summary.json']=b'changed'
  with self.assertRaises(ValueError):self.publish()
 def test_missing_completion(self):
  self.publish();self.path('complete.json').unlink()
  with self.assertRaises(FileNotFoundError):read_bundle(self.s,self.c)
 def test_missing_payload(self):
  self.publish();self.path('payload.zip').unlink()
  with self.assertRaises(FileNotFoundError):read_bundle(self.s,self.c)
 def test_payload_tamper(self):
  self.publish();self.path('payload.zip').write_bytes(b'changed')
  with self.assertRaises(ValueError):read_bundle(self.s,self.c)
 def test_manifest_tamper(self):
  self.publish();self.path('manifest.json').write_bytes(b'{}')
  with self.assertRaises(ValueError):read_bundle(self.s,self.c)
 def test_wrong_source(self):
  self.publish();c={**self.c,'source_sha':'b'*40}
  with self.assertRaises(ValueError):read_bundle(self.s,c)
 def test_attempt_isolation(self):
  self.publish();c={**self.c,'run_attempt':'2'}
  with self.assertRaises(FileNotFoundError):read_bundle(self.s,c)
  publish(self.s,self.files,c,3);self.assertEqual(read_bundle(self.s,c)[0],self.files)
 def test_wrong_expected_manifest(self):
  self.publish()
  with self.assertRaises(ValueError):read_bundle(self.s,self.c,'f'*64)
 def test_absent_required_pattern(self):
  with self.assertRaises(ValueError):select(self.root,['missing/*.xml'])
 def test_traversal(self):
  with self.assertRaises(ValueError):pack({'../escape':b'bad'},self.c,3)
 def test_source_symlink(self):
  (self.root/'link').symlink_to('/etc/hosts')
  with self.assertRaises(ValueError):select(self.root,['link'])
 def test_destination_symlink(self):
  self.publish();(self.root/'out').symlink_to(self.root/'store')
  with self.assertRaises(ValueError):restore(self.s,self.c,self.root/'out')
 def test_destination_conflict(self):
  self.publish();out=self.root/'out';out.mkdir();(out/'summary.json').write_bytes(b'other')
  with self.assertRaises(ValueError):restore(self.s,self.c,out)
  self.assertFalse((out/'test').exists())
 def test_unexpected_archive_file(self):
  self.publish();payload,m=pack({**self.files,'extra':b'injected'},self.c,3)
  manifest=json.loads(self.path('manifest.json').read_bytes());manifest['payload']={'size':len(payload),'sha256':digest(payload)}
  mb=canonical(manifest);self.path('payload.zip').write_bytes(payload);self.path('manifest.json').write_bytes(mb)
  self.path('complete.json').write_bytes(canonical({'schema':1,'manifest_sha256':digest(mb)}))
  with self.assertRaises(ValueError):read_bundle(self.s,self.c)
 def test_deterministic(self):self.assertEqual(pack(self.files,self.c,3),pack(dict(reversed(list(self.files.items()))),self.c,3))
 def test_empty(self):
  with self.assertRaises(ValueError):pack({},self.c,3)

if __name__=='__main__':unittest.main()
