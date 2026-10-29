import copy,io,json,os,tempfile,unittest,zipfile
import urllib.error
import signal,ssl,time
import subprocess,sys
from contextlib import redirect_stderr
from unittest.mock import patch
from pathlib import Path
from ci_artifact import context,prefix,publish,restore,restore_set,read_bundle,pack,select,FileStore,HTTPStore,canonical,digest,request_deadline,_RequestDeadline

class HTTPRetryTests(unittest.TestCase):
 def setUp(self):
  self.store=HTTPStore('https://example.invalid');self.key='v1/owner/repo/wf/1/1/job/name/payload.zip'
  self.real_sleep=time.sleep
  self.token=patch.object(self.store,'token',return_value='synthetic');self.token.start();self.addCleanup(self.token.stop)
  self.sleep=patch('ci_artifact.time.sleep');self.sleep.start();self.addCleanup(self.sleep.stop)
 def error(self,code):return urllib.error.HTTPError('https://example.invalid',code,'',{},None)
 def response(self,value=b'ok'):
  class Response:
   def __enter__(self):return self
   def __exit__(self,*args):pass
   def read(self,n):return value
  return Response()
 def test_get_success_and_502_retry(self):
  with patch('ci_artifact.urllib.request.urlopen',side_effect=[self.error(502),self.response()]) as send:
   self.assertEqual(self.store.get(self.key),b'ok')
  self.assertEqual(send.call_count,2);self.assertEqual([c.args[0].full_url for c in send.call_args_list],[f'https://example.invalid/{self.key}']*2)
 def test_exhausted_and_authorization_no_retry(self):
  for code in (400,401,403,404,409,500,502,503,504):
   with self.subTest(code=code),patch('ci_artifact.urllib.request.urlopen',side_effect=self.error(code)) as send:
    with self.assertRaisesRegex(RuntimeError,f'HTTP {code}'):self.store.get(self.key)
    self.assertEqual(send.call_count,3 if code in (500,502,503,504) else 1)
 def test_put_lost_response_reuses_exact_bytes_and_conflict_fails(self):
  data=b'original immutable bytes'
  with patch('ci_artifact.urllib.request.urlopen',side_effect=[ConnectionResetError(),self.response()]) as send:self.store.put(self.key,data)
  self.assertEqual([c.args[0].data for c in send.call_args_list],[data,data])
  self.assertEqual([c.args[0].get_header('X-content-sha256') for c in send.call_args_list],[digest(data)]*2)
  with patch('ci_artifact.urllib.request.urlopen',side_effect=[ConnectionResetError(),self.error(409)]) as send:
   with self.assertRaisesRegex(RuntimeError,'HTTP 409'):self.store.put(self.key,data)
   self.assertEqual(send.call_count,2)
 def test_put_lost_response_after_store_preserves_original(self):
  stored={};calls=[]
  def conditional_put(req,timeout):
   data=req.data;calls.append(data)
   if not stored:
    stored['bytes']=data;stored['sha']=req.get_header('X-content-sha256')
    raise ConnectionResetError()
   if stored['bytes']!=data or stored['sha']!=req.get_header('X-content-sha256'):raise self.error(409)
   return self.response(b'stored')
  with patch('ci_artifact.urllib.request.urlopen',side_effect=conditional_put):
   self.store.put(self.key,b'first')
   with self.assertRaisesRegex(RuntimeError,'HTTP 409'):self.store.put(self.key,b'different')
  self.assertEqual(calls,[b'first',b'first',b'different']);self.assertEqual(stored['bytes'],b'first')
 def test_other_network_errors_not_retried(self):
  with patch('ci_artifact.urllib.request.urlopen',side_effect=urllib.error.URLError('unexpected')) as send:
   with self.assertRaises(urllib.error.URLError):self.store.get(self.key)
   self.assertEqual(send.call_count,1)
  with patch('ci_artifact.urllib.request.urlopen',side_effect=urllib.error.URLError(ssl.SSLError('synthetic'))) as send:
   with self.assertRaises(urllib.error.URLError):self.store.get(self.key)
   self.assertEqual(send.call_count,1)
 def test_deadline_no_more_retries(self):
  with patch('ci_artifact.time.monotonic',side_effect=[0,0,0,0,0,0,179.5]),patch('ci_artifact.urllib.request.urlopen',side_effect=self.error(502)) as send:
   with self.assertRaisesRegex(RuntimeError,'HTTP 502'):self.store.get(self.key)
   self.assertEqual(send.call_count,1)
 def test_http_log_allowlist_and_no_sensitive_values(self):
  err=urllib.error.HTTPError('https://secret.invalid/path?token=private',401,'private-body',{
   'CF-Ray':'1234567890abcdef-ICN','X-Request-ID':'12345678-1234-4234-8234-123456789abc',
   'Authorization':'Bearer synthetic-secret'},None)
  out=io.StringIO()
  with patch('ci_artifact.urllib.request.urlopen',side_effect=err),redirect_stderr(out):
   with self.assertRaisesRegex(RuntimeError,'HTTP 401'):self.store.get(self.key)
  record=json.loads(out.getvalue());self.assertEqual(record['operation'],'GET');self.assertEqual(record['object_kind'],'payload')
  self.assertEqual(record['status'],401);self.assertEqual(record['cf_ray'],'1234567890abcdef-ICN')
  self.assertEqual(record['request_id'],'12345678-1234-4234-8234-123456789abc')
  self.assertNotIn('private',out.getvalue());self.assertNotIn('synthetic-secret',out.getvalue());self.assertNotIn(self.key,out.getvalue())
 def test_malformed_ids_omitted_and_logging_error_does_not_change_exit(self):
  err=urllib.error.HTTPError('https://example.invalid',403,'',{'CF-Ray':'1234567890abcdef-ICN\ninjected','X-Request-ID':'A'*200},None)
  out=io.StringIO()
  with patch('ci_artifact.urllib.request.urlopen',side_effect=err),redirect_stderr(out):
   with self.assertRaisesRegex(RuntimeError,'HTTP 403'):self.store.get(self.key)
  record=json.loads(out.getvalue());self.assertNotIn('cf_ray',record);self.assertNotIn('request_id',record)
  with patch('ci_artifact.urllib.request.urlopen',side_effect=self.error(409)) as send,patch('ci_artifact.print',side_effect=OSError('private diagnostic error')):
   with self.assertRaisesRegex(RuntimeError,'HTTP 409'):self.store.put(self.key,b'bytes')
   self.assertEqual(send.call_count,1)
 def test_oidc_http_error_is_logged_and_reraised_without_retry(self):
  error=self.error(401);out=io.StringIO()
  with patch.object(self.store,'token',side_effect=error) as token,redirect_stderr(out):
   with self.assertRaises(urllib.error.HTTPError) as caught:self.store.get(self.key)
  self.assertEqual(caught.exception.code,401);self.assertEqual(caught.exception.reason,'OIDC request failed');self.assertEqual(token.call_count,1)
  record=json.loads(out.getvalue());self.assertEqual((record['operation'],record['object_kind'],record['status']),('TOKEN','payload',401))
 def test_deadline_during_diagnostics_preserves_primary_http_failure(self):
  err=self.error(401)
  with patch.object(err,'close',wraps=err.close) as closed,patch('ci_artifact.urllib.request.urlopen',side_effect=err) as send,patch('ci_artifact.print',side_effect=_RequestDeadline()):
   with self.assertRaisesRegex(RuntimeError,'HTTP 401'):self.store.get(self.key)
   self.assertEqual(send.call_count,1);closed.assert_called_once()
 def test_oidc_traceback_does_not_echo_untrusted_reason_or_url(self):
  script="""import urllib.error\nfrom unittest.mock import patch\nfrom ci_artifact import HTTPStore\ns=HTTPStore('https://example.invalid')\ne=urllib.error.HTTPError('https://synthetic-secret.invalid/path?key=synthetic-secret',401,'synthetic-secret',{},None)\nwith patch.object(s,'token',side_effect=e):s.get('v1/o/r/w/1/1/j/n/payload.zip')\n"""
  result=subprocess.run([sys.executable,'-c',script],capture_output=True,text=True,timeout=5)
  self.assertNotEqual(result.returncode,0);self.assertIn('HTTP Error 401: OIDC request failed',result.stderr)
  self.assertNotIn('synthetic-secret',result.stderr);self.assertNotIn('https://',result.stderr)
 def test_slow_read_stops_at_deadline_and_restores_alarm(self):
  real_sleep=self.real_sleep
  class SlowResponse:
   def __enter__(self):return self
   def __exit__(self,*args):pass
   def read(self,n):
    for _ in range(10):real_sleep(0.02)
    return b'ok'
  before=signal.getsignal(signal.SIGALRM)
  with patch('ci_artifact.request_deadline',side_effect=lambda seconds:request_deadline(0.06)),patch('ci_artifact.urllib.request.urlopen',return_value=SlowResponse()) as send:
   with self.assertRaisesRegex(RuntimeError,'deadline exceeded'):self.store.get(self.key)
  self.assertEqual(send.call_count,1);self.assertEqual(signal.getsignal(signal.SIGALRM),before)
  self.assertEqual(signal.getitimer(signal.ITIMER_REAL),(0.0,0.0))
 def test_existing_alarm_is_not_changed(self):
  before=signal.getsignal(signal.SIGALRM)
  signal.setitimer(signal.ITIMER_REAL,10)
  try:
   with self.assertRaisesRegex(RuntimeError,'timer unavailable'):self.store.get(self.key)
   self.assertGreater(signal.getitimer(signal.ITIMER_REAL)[0],0)
   self.assertEqual(signal.getsignal(signal.SIGALRM),before)
  finally:signal.setitimer(signal.ITIMER_REAL,0)
 def test_unsupported_signal_context_fails_closed(self):
  with patch('ci_artifact.signal.signal',side_effect=ValueError('not main thread')):
   with self.assertRaisesRegex(RuntimeError,'timer unavailable'):self.store.get(self.key)
 def test_existing_alarm_handler_is_not_changed(self):
  before=signal.getsignal(signal.SIGALRM)
  def owned_handler(signum,frame):pass
  signal.signal(signal.SIGALRM,owned_handler)
  try:
   with self.assertRaisesRegex(RuntimeError,'timer unavailable'):self.store.get(self.key)
   self.assertIs(signal.getsignal(signal.SIGALRM),owned_handler)
  finally:signal.signal(signal.SIGALRM,before)

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
 def test_complete_expected_set(self):
  self.publish();c={**self.c,'job':'test2','name':'evidence2'};publish(self.s,self.files,c,3)
  rows=[dict(job='test',name='evidence',destination='first'),dict(job='test2',name='evidence2',destination='second')]
  self.assertEqual(len(restore_set(self.s,self.c,rows,self.root/'out')),2)
 def test_expected_set_missing(self):
  self.publish();rows=[dict(job='test',name='evidence',destination=''),dict(job='missing',name='missing',destination='')]
  with self.assertRaises(FileNotFoundError):restore_set(self.s,self.c,rows,self.root/'out')
 def test_expected_set_duplicate(self):
  self.publish();row=dict(job='test',name='evidence',destination='')
  with self.assertRaises(ValueError):restore_set(self.s,self.c,[row,row],self.root/'out')
 def test_expected_set_empty(self):
  with self.assertRaises(ValueError):restore_set(self.s,self.c,[],self.root/'out')

if __name__=='__main__':unittest.main()
