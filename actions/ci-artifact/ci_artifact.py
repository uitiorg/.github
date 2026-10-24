#!/usr/bin/env python3
"""Immutable CI bundles. No Cloudflare credential is accepted by this client.

HTTPStore requires a GitHub OIDC broker; FileStore is for hermetic contract tests.
Payload bytes, the manifest, and completion are separate conditional creations.
"""
import argparse
import glob
import hashlib
import io
import json
import os
from pathlib import Path, PurePosixPath
import re
import stat
import tempfile
import urllib.error
import urllib.parse
import urllib.request
import zipfile

MAX_BYTES = 90 * 1024 * 1024
MAX_EXPANDED = 1024 * 1024 * 1024
SEGMENT = re.compile(r"[A-Za-z0-9_.-]{1,180}\Z")
SHA = re.compile(r"[0-9a-f]{40}\Z")

def digest(data):
    return hashlib.sha256(data).hexdigest()

def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=True).encode()

def safe_path(value):
    p = PurePosixPath(value)
    if not value or '\\' in value or p.is_absolute() or any(x in ('', '.', '..') for x in value.split('/')):
        raise ValueError('unsafe path')
    return p

def context(repository, workflow, run_id, run_attempt, job, name, source_sha):
    parts = repository.split('/')
    if len(parts) != 2 or not all(SEGMENT.fullmatch(p) and p not in ('.','..') for p in parts + [workflow,job,name]):
        raise ValueError('invalid identity')
    if not re.fullmatch(r'[1-9][0-9]*', str(run_id)) or not re.fullmatch(r'[1-9][0-9]*', str(run_attempt)) or not SHA.fullmatch(source_sha):
        raise ValueError('invalid run/attempt/source SHA')
    return dict(repository=repository, workflow=workflow, run_id=str(run_id), run_attempt=str(run_attempt), job=job, name=name, source_sha=source_sha)

def prefix(c):
    context(**c)
    return f"v1/{c['repository']}/{c['workflow']}/{c['run_id']}/{c['run_attempt']}/{c['job']}/{c['name']}"

def select(root, patterns):
    root = Path(root).resolve()
    selected = {}
    for pattern in patterns:
        safe_path(pattern)
        matches = []
        for s in glob.glob(str(root / pattern), recursive=True):
            p = Path(s)
            matches.extend(p.rglob('*') if p.is_dir() else [p])
        files = [p for p in matches if p.is_file() or p.is_symlink()]
        if not files:
            raise ValueError(f'required pattern missing: {pattern}')
        for p in files:
            rel = p.relative_to(root)
            if p.is_symlink() or any((root / Path(*rel.parts[:n])).is_symlink() for n in range(1,len(rel.parts)+1)):
                raise ValueError('symlinks are forbidden')
            if not p.resolve().is_relative_to(root) or not p.is_file():
                raise ValueError('not a regular source file')
            selected[rel.as_posix()] = p.read_bytes()
    if not selected or sum(map(len,selected.values())) > MAX_EXPANDED:
        raise ValueError('empty or oversized bundle')
    return selected

def pack(files, c, retention_days):
    context(**c)
    if not 1 <= retention_days <= 90:
        raise ValueError('invalid retention')
    data = io.BytesIO()
    rows = []
    with zipfile.ZipFile(data,'w',zipfile.ZIP_DEFLATED) as z:
        for name, content in sorted(files.items()):
            safe_path(name)
            info=zipfile.ZipInfo(name, (1980,1,1,0,0,0))
            info.compress_type=zipfile.ZIP_DEFLATED
            info.external_attr=(stat.S_IFREG | 0o644)<<16
            z.writestr(info,content)
            rows.append(dict(path=name,size=len(content),sha256=digest(content)))
    payload=data.getvalue()
    if not rows or len(payload)>MAX_BYTES:
        raise ValueError('empty or oversized payload')
    manifest=canonical(dict(schema=1,context=c,retention_days=retention_days,
        payload=dict(size=len(payload),sha256=digest(payload)),files=rows))
    return payload,manifest

class FileStore:
    def __init__(self,root): self.root=Path(root)
    def get(self,key): return (self.root/safe_path(key)).read_bytes()
    def put(self,key,data):
        p=self.root/safe_path(key);p.parent.mkdir(parents=True,exist_ok=True)
        try:
            with p.open('xb') as f:f.write(data)
        except FileExistsError:
            if p.read_bytes()!=data:raise ValueError('immutable conflict')

class HTTPStore:
    def __init__(self,url):
        u=urllib.parse.urlparse(url)
        if u.scheme!='https' or not u.hostname or u.username or u.password or u.query or u.fragment:
            raise ValueError('broker must be an HTTPS origin')
        self.url=url.rstrip('/')
    def token(self):
        u=os.environ['ACTIONS_ID_TOKEN_REQUEST_URL']
        u += ('&' if '?' in u else '?') + urllib.parse.urlencode({'audience':'uitiorg-ci-artifacts'})
        req=urllib.request.Request(u,headers={'Authorization':'Bearer '+os.environ['ACTIONS_ID_TOKEN_REQUEST_TOKEN']})
        with urllib.request.urlopen(req,timeout=30) as r:return json.load(r)['value']
    def request(self,key,data=None):
        safe_path(key)
        headers={'Authorization':'Bearer '+self.token(),'User-Agent':'uitiorg-ci-artifact/1.0'}
        if data is not None: headers.update({'Content-Type':'application/octet-stream','X-Content-SHA256':digest(data)})
        req=urllib.request.Request(self.url+'/'+key, data=data, headers=headers,method='PUT' if data is not None else 'GET')
        try:
            with urllib.request.urlopen(req,timeout=180) as r:
                value=r.read(MAX_BYTES+1)
                if len(value)>MAX_BYTES:raise ValueError('response exceeds limit')
                return value
        except urllib.error.HTTPError as e:
            raise RuntimeError(f'artifact broker HTTP {e.code}; no fallback') from None
    def get(self,key):return self.request(key)
    def put(self,key,data):self.request(key,data)

def publish(store,files,c,retention_days):
    payload,manifest=pack(files,c,retention_days)
    base=prefix(c)
    store.put(base+'/payload.zip',payload)
    store.put(base+'/manifest.json',manifest)
    completion=canonical(dict(schema=1,manifest_sha256=digest(manifest)))
    store.put(base+'/complete.json',completion)
    return digest(manifest)

def read_bundle(store,c,expected_manifest_sha=None):
    base=prefix(c)
    done=json.loads(store.get(base+'/complete.json'))
    manifest_bytes=store.get(base+'/manifest.json')
    mh=digest(manifest_bytes)
    if done != dict(schema=1,manifest_sha256=mh) or (expected_manifest_sha and mh!=expected_manifest_sha):
        raise ValueError('completion/manifest mismatch')
    m=json.loads(manifest_bytes)
    if m.get('schema')!=1 or m.get('context')!=c or not m.get('files'):
        raise ValueError('manifest context or file list mismatch')
    payload=store.get(base+'/payload.zip')
    if m['payload']!=dict(size=len(payload),sha256=digest(payload)):
        raise ValueError('payload checksum mismatch')
    expected={}
    for row in m['files']:
        safe_path(row['path'])
        if row['path'] in expected:raise ValueError('duplicate expected file')
        expected[row['path']]=row
    files={}
    with zipfile.ZipFile(io.BytesIO(payload)) as z:
        infos=z.infolist()
        if len(infos)!=len(expected) or {x.filename for x in infos}!=set(expected):
            raise ValueError('missing, extra or duplicate archive file')
        if sum(x.file_size for x in infos)>MAX_EXPANDED:raise ValueError('expanded bundle too large')
        for info in infos:
            safe_path(info.filename)
            if stat.S_IFMT(info.external_attr>>16) not in (0,stat.S_IFREG):raise ValueError('special file forbidden')
            data=z.read(info)
            if expected[info.filename]!=dict(path=info.filename,size=len(data),sha256=digest(data)):
                raise ValueError('file checksum mismatch')
            files[info.filename]=data
    return files,mh

def restore(store,c,destination,expected_manifest_sha=None):
    files,mh=read_bundle(store,c,expected_manifest_sha)
    dest=Path(destination)
    if dest.is_symlink():raise ValueError('destination symlink')
    dest=dest.resolve()
    # Validate the entire bundle and all destination collisions before writing.
    for name,data in files.items():
        p=dest/safe_path(name)
        if p.is_symlink() or any(x.is_symlink() for x in p.parents):raise ValueError('destination symlink')
        if p.exists() and (not p.is_file() or p.read_bytes()!=data):raise ValueError('destination conflict')
    for name,data in files.items():
        p=dest/name;p.parent.mkdir(parents=True,exist_ok=True)
        if not p.exists():
            with p.open('xb') as f:f.write(data)
    return mh

def restore_set(store,base_context,bundles,destination):
    if not isinstance(bundles,list) or not bundles:raise ValueError('expected bundle list is empty')
    seen=set();results=[]
    for item in bundles:
        if set(item)!= {'job','name','destination'}:raise ValueError('invalid expected bundle row')
        identity=(item['job'],item['name'])
        if identity in seen:raise ValueError('duplicate expected bundle')
        seen.add(identity)
        target=Path(destination)
        if item['destination']:target=target/safe_path(item['destination'])
        c={**base_context,'job':item['job'],'name':item['name']}
        results.append(restore(store,c,target))
    return results

def main():
    p=argparse.ArgumentParser();p.add_argument('operation',choices=['upload','download'])
    p.add_argument('--broker',default=os.getenv('CI_ARTIFACT_BROKER_URL'))
    p.add_argument('--repository',default=os.getenv('GITHUB_REPOSITORY'))
    p.add_argument('--workflow',required=True);p.add_argument('--job',required=True);p.add_argument('--name',required=True)
    p.add_argument('--run-id',default=os.getenv('GITHUB_RUN_ID'));p.add_argument('--run-attempt',default=os.getenv('GITHUB_RUN_ATTEMPT'))
    p.add_argument('--source-sha',required=True);p.add_argument('--root',default='.')
    p.add_argument('--path',action='append');p.add_argument('--retention-days',type=int,default=7)
    p.add_argument('--destination');p.add_argument('--manifest-sha')
    a=p.parse_args();c=context(a.repository,a.workflow,a.run_id,a.run_attempt,a.job,a.name,a.source_sha)
    store=HTTPStore(a.broker or '')
    if a.operation=='upload':
        if not a.path:raise ValueError('explicit required paths required')
        mh=publish(store,select(a.root,a.path),c,a.retention_days)
    else:
        if not a.destination:raise ValueError('destination required')
        mh=restore(store,c,a.destination,a.manifest_sha)
    if os.getenv('GITHUB_OUTPUT'):
        with open(os.environ['GITHUB_OUTPUT'],'a') as f:f.write(f'manifest_sha256={mh}\n')
    if os.getenv('GITHUB_STEP_SUMMARY'):
        with open(os.environ['GITHUB_STEP_SUMMARY'],'a') as f:f.write(f'Private R2 {a.operation}: `{prefix(c)}`; manifest `{mh}`\n')
    print(f'{a.operation} verified; manifest SHA256 {mh}')

if __name__=='__main__': main()
