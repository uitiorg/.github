"""Only run after explicit broker/identity-policy approval; no deletion."""
import os
from pathlib import Path
from ci_artifact import context,publish,restore,HTTPStore
e=os.environ
c=context(e['GITHUB_REPOSITORY'],'ci-artifact-contract.yml',e['GITHUB_RUN_ID'],e['GITHUB_RUN_ATTEMPT'],'smoke','smoke',e['GITHUB_SHA'])
s=HTTPStore(e['CI_ARTIFACT_BROKER_URL'])
files={'test/TEST-smoke.xml':b'<testsuite tests="1" failures="0"/>','source.txt':c['source_sha'].encode()}
h=publish(s,files,c,3)
assert publish(s,files,c,3)==h
dest=Path(e['RUNNER_TEMP'])/f'artifact-smoke-{c["run_id"]}-{c["run_attempt"]}'
restore(s,c,dest,h)
for name,expected in files.items():assert (dest/name).read_bytes()==expected
try:publish(s,{'different.txt':b'different'},c,3)
except RuntimeError as ex:assert 'HTTP 409' in str(ex)
else:raise AssertionError('overwrite accepted')
denied=[({**c,'name':'missing'},404),({**c,'run_id':str(int(c['run_id'])+1)},403),({**c,'run_attempt':str(int(c['run_attempt'])+1)},403),({**c,'repository':'uitiorg/legacy-service'},403)]
if int(c['run_attempt'])>1:denied.append(({**c,'run_attempt':str(int(c['run_attempt'])-1)},403))
for bad,status in denied:
 try:restore(s,bad,dest/'must-not-exist')
 except RuntimeError as ex:assert f'HTTP {status}' in str(ex),str(ex)
 else:raise AssertionError('missing/unauthorized bundle accepted')
try:restore(s,{**c,'source_sha':'f'*40},dest/'wrong-source')
except ValueError:pass
else:raise AssertionError('wrong expected source accepted')
with open(e['GITHUB_STEP_SUMMARY'],'a') as f:
 f.write(f'R2 smoke verified upload/restore, immutable retry/conflict, missing and cross-run/attempt denial. Source `{c["source_sha"]}`, run `{c["run_id"]}`, attempt `{c["run_attempt"]}`, manifest `{h}`.\n')
print('Live R2 smoke PASS; run/attempt and manifest recorded in step summary')
