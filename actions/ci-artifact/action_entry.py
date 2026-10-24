import os,sys,json
from pathlib import Path
from ci_artifact import main,context,HTTPStore,restore_set
e=os.environ
workflow=e['GITHUB_WORKFLOW_REF'].split('@')[0].rsplit('/',1)[-1]
if e['TRANSPORT_OPERATION']=='download-set':
 c=context(e['GITHUB_REPOSITORY'],workflow,e['GITHUB_RUN_ID'],e['GITHUB_RUN_ATTEMPT'],e['TRANSPORT_JOB'],e['TRANSPORT_NAME'],e['TRANSPORT_SOURCE_SHA'])
 results=restore_set(HTTPStore(e['TRANSPORT_BROKER']),c,json.loads(Path(e['TRANSPORT_BUNDLE_LIST']).read_text()),e['TRANSPORT_DESTINATION'])
 print(f'Verified all {len(results)} explicitly expected R2 bundles')
 sys.exit(0)
sys.argv=['ci_artifact.py',e['TRANSPORT_OPERATION'],'--broker',e['TRANSPORT_BROKER'],
 '--workflow',workflow,'--job',e['TRANSPORT_JOB'],'--name',e['TRANSPORT_NAME'],
 '--source-sha',e['TRANSPORT_SOURCE_SHA'],'--root',e['TRANSPORT_ROOT'],
 '--retention-days',e['TRANSPORT_RETENTION']]
for path in e.get('TRANSPORT_PATHS','').splitlines():
 if path.strip():sys.argv.extend(['--path',path.strip()])
if e.get('TRANSPORT_DESTINATION'):sys.argv.extend(['--destination',e['TRANSPORT_DESTINATION']])
if e.get('TRANSPORT_MANIFEST_SHA'):sys.argv.extend(['--manifest-sha',e['TRANSPORT_MANIFEST_SHA']])
main()
