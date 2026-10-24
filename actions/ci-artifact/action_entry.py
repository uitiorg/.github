import os,sys
from pathlib import Path
from ci_artifact import main
e=os.environ
workflow=e['GITHUB_WORKFLOW_REF'].split('@')[0].rsplit('/',1)[-1]
sys.argv=['ci_artifact.py',e['TRANSPORT_OPERATION'],'--broker',e['TRANSPORT_BROKER'],
 '--workflow',workflow,'--job',e['TRANSPORT_JOB'],'--name',e['TRANSPORT_NAME'],
 '--source-sha',e['TRANSPORT_SOURCE_SHA'],'--root',e['TRANSPORT_ROOT'],
 '--retention-days',e['TRANSPORT_RETENTION']]
for path in e.get('TRANSPORT_PATHS','').splitlines():
 if path.strip():sys.argv.extend(['--path',path.strip()])
if e.get('TRANSPORT_DESTINATION'):sys.argv.extend(['--destination',e['TRANSPORT_DESTINATION']])
if e.get('TRANSPORT_MANIFEST_SHA'):sys.argv.extend(['--manifest-sha',e['TRANSPORT_MANIFEST_SHA']])
main()
