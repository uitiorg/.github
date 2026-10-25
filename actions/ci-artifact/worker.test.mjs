import test from 'node:test';
import assert from 'node:assert/strict';
import {authorize,serve,verifyJWT,readPolicy} from './worker.mjs';

const claims={repository:'uitiorg/btalk2.1_backend',repository_id:'975204945',repository_owner_id:'117706611',workflow_ref:'uitiorg/btalk2.1_backend/.github/workflows/smoke.yml@refs/heads/develop',event_name:'workflow_dispatch',ref:'refs/heads/develop',run_id:'123',run_attempt:'1'};
const policy={'uitiorg/btalk2.1_backend':{id:'975204945',workflows:{'smoke.yml':{events:['workflow_dispatch'],refs:['refs/heads/develop'],slots:{test:['evidence']}}}}};
const prefix='v1/uitiorg/btalk2.1_backend/smoke.yml/123/1/test/evidence/';
const hash=async b=>Buffer.from(await crypto.subtle.digest('SHA-256',b)).toString('hex');
const makeEnv=()=>({ALLOWLIST:JSON.stringify(policy),ARTIFACTS:new Store()});
test('split repository bindings preserve exact policy without overrides',()=>{
 const combined=readPolicy({ALLOWLIST:JSON.stringify(policy),ALLOWLIST_2:JSON.stringify({'uitiorg/second':{id:'2',workflows:{}}})});
 assert.deepEqual(combined['uitiorg/btalk2.1_backend'],policy['uitiorg/btalk2.1_backend']);
 assert.deepEqual(combined['uitiorg/second'],{id:'2',workflows:{}});
 assert.throws(()=>readPolicy({ALLOWLIST:JSON.stringify(policy),ALLOWLIST_2:JSON.stringify(policy)}));
 for(const value of ['[]','null','broken'])assert.throws(()=>readPolicy({ALLOWLIST:value}));
});
test('invalid split policy fails closed before reading storage',async()=>{
 const env={ALLOWLIST:JSON.stringify(policy),ALLOWLIST_2:JSON.stringify(policy),ARTIFACTS:{get(){assert.fail('must not access storage');}}};
 assert.equal((await serve(new Request('https://broker.invalid/'+prefix+'payload.zip'),env,claims)).status,403);
});
class Store {
 map=new Map();
 async head(k){const v=this.map.get(k);return v?{size:v.data.byteLength,customMetadata:v.customMetadata}:null;}
 async get(k){const v=this.map.get(k);return v?{body:v.data}:null;}
 async put(k,b,options){
  assert.equal(options.onlyIf.get('If-None-Match'),'*');
  if(this.map.has(k))return null;
  const data=b instanceof ArrayBuffer?b:await new Response(b).arrayBuffer();
  assert.equal(await hash(data),options.sha256);
  this.map.set(k,{data,customMetadata:options.customMetadata});return {};
 }
}
async function put(env,file,data){
 const body=Buffer.from(data);
 const req=new Request('https://broker.invalid/'+prefix+file,{method:'PUT',headers:{'Content-Length':String(body.length),'X-Content-SHA256':await hash(body)},body});
 return serve(req,env,claims);
}
test('authorized exact namespace',()=>assert.equal(authorize(claims,prefix+'payload.zip',policy,'PUT').run_id,'123'));
for(const [name,key,change] of [
 ['cross repository',prefix.replace('btalk2.1_backend','zerro'),{}],
 ['cross run',prefix.replace('/123/','/124/'),{}],
 ['cross attempt',prefix.replace('/1/test/','/2/test/'),{}],
 ['unapproved job',prefix.replace('/test/','/other/'),{}],
 ['unknown slot',prefix.replace('/evidence/','/other/'),{}],
 ['wrong repository ID',prefix,{repository_id:'1'}],
 ['wrong owner ID',prefix,{repository_owner_id:'1'}],
 ['wrong workflow',prefix,{workflow_ref:'uitiorg/btalk2.1_backend/.github/workflows/other.yml@refs/heads/develop'}],
 ['unapproved event',prefix,{event_name:'pull_request_target'}],
 ['unapproved ref',prefix,{ref:'refs/heads/other'}]
])test('denies '+name,()=>assert.throws(()=>authorize({...claims,...change},key+'payload.zip',policy,'PUT')));
test('denies deletion/listing',()=>{assert.throws(()=>authorize(claims,prefix+'payload.zip',policy,'DELETE'));assert.throws(()=>authorize(claims,prefix,policy,'GET'));});
test('default empty policy denies',()=>assert.throws(()=>authorize(claims,prefix+'payload.zip',{},'PUT')));
test('optional PR base restrictions reject wrong and missing signed base refs',()=>{
 const p=structuredClone(policy),w=p[claims.repository].workflows['smoke.yml'];
 w.events=['pull_request'];w.pull_request_base_refs=['develop','main'];
 const c={...claims,event_name:'pull_request',ref:'refs/pull/42/merge',base_ref:'develop'};
 assert.equal(authorize(c,prefix+'payload.zip',p,'PUT').run_id,'123');
 for(const change of [{base_ref:'release/other'},{base_ref:undefined},{ref:'refs/heads/develop'}])
  assert.throws(()=>authorize({...c,...change},prefix+'payload.zip',p,'PUT'));
});
test('optional reusable identity must match the exact approved workflow commit',()=>{
 const p=structuredClone(policy),w=p[claims.repository].workflows['smoke.yml'];
 const ref='uitiorg/.github/.github/workflows/jacoco-rule.yml@'+'a'.repeat(40);w.reusable_refs=[ref];
 assert.equal(authorize({...claims,job_workflow_ref:ref},prefix+'payload.zip',p,'PUT').run_id,'123');
 for(const value of [undefined,ref.replace('a'.repeat(40),'b'.repeat(40)),ref.replace('jacoco-rule','other')])
  assert.throws(()=>authorize({...claims,job_workflow_ref:value},prefix+'payload.zip',p,'PUT'));
});
test('conditional writes are idempotent and immutable',async()=>{
 const e=makeEnv();assert.equal((await put(e,'payload.zip','abc')).status,200);
 assert.equal((await put(e,'payload.zip','abc')).status,200);
 assert.equal((await put(e,'payload.zip','def')).status,409);
});
test('incomplete publication cannot complete',async()=>{
 const e=makeEnv();assert.equal((await put(e,'complete.json',JSON.stringify({schema:1,manifest_sha256:'a'.repeat(64)}))).status,409);
});
test('publication requires matching original payload then manifest',async()=>{
 const e=makeEnv();const identity=authorize(claims,prefix+'payload.zip',policy,'PUT');delete identity.file;
 const m={schema:1,context:{...identity,source_sha:'a'.repeat(40)},retention_days:3,files:[{path:'test.txt',size:3,sha256:await hash(Buffer.from('abc'))}],payload:{size:3,sha256:await hash(Buffer.from('abc'))}};
 const mb=JSON.stringify(m);
 assert.equal((await put(e,'manifest.json',mb)).status,409);
 assert.equal((await put(e,'payload.zip','abc')).status,200);
 assert.equal((await put(e,'manifest.json',mb)).status,200);
 assert.equal((await put(e,'complete.json',JSON.stringify({schema:1,manifest_sha256:await hash(Buffer.from(mb))}))).status,200);
 const response=await serve(new Request('https://broker.invalid/'+prefix+'payload.zip'),e,claims);
 assert.equal(await response.text(),'abc');assert.equal(response.headers.get('Cache-Control'),'private, no-store');
});
test('signed JWT validation rejects spoofing, expiry and wrong audience',async()=>{
 const pair=await crypto.subtle.generateKey({name:'RSASSA-PKCS1-v1_5',modulusLength:2048,publicExponent:new Uint8Array([1,0,1]),hash:'SHA-256'},true,['sign','verify']);
 const jwk=await crypto.subtle.exportKey('jwk',pair.publicKey);Object.assign(jwk,{kid:'test',alg:'RS256',use:'sig'});
 const now=Math.floor(Date.now()/1000);const base={...claims,iss:'https://token.actions.githubusercontent.com',aud:'uitiorg-ci-artifacts',iat:now,nbf:now,exp:now+300};
 const encode=v=>Buffer.from(JSON.stringify(v)).toString('base64url');
 async function sign(c){const body=encode({kid:'test',alg:'RS256'})+'.'+encode(c);return body+'.'+Buffer.from(await crypto.subtle.sign('RSASSA-PKCS1-v1_5',pair.privateKey,Buffer.from(body))).toString('base64url');}
 const fetcher=async()=>Response.json({keys:[jwk]});const token=await sign(base);
 assert.equal((await verifyJWT(token,fetcher,now)).run_id,'123');
 await assert.rejects(verifyJWT(await sign({...base,aud:'other'}),fetcher,now));
 await assert.rejects(verifyJWT(await sign({...base,exp:now-1}),fetcher,now));
 await assert.rejects(verifyJWT(await sign({...base,iss:'https://attacker.invalid'}),fetcher,now));
 const p=token.split('.');p[1]=encode({...base,run_id:'999'});await assert.rejects(verifyJWT(p.join('.'),fetcher,now));
});
