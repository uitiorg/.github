// Private R2 broker. No list, delete, public-read, or cross-run access route.
// ALLOWLIST is empty by default. Deployment and authorization are separate approvals.
const issuer = 'https://token.actions.githubusercontent.com';
const audience = 'uitiorg-ci-artifacts';
const limit = 90 * 1024 * 1024;
let jwksCache;
const bytes = value => Uint8Array.from(atob(value.replace(/-/g, '+').replace(/_/g, '/')), c => c.charCodeAt(0));
const jsonPart = value => JSON.parse(new TextDecoder().decode(bytes(value)));
const hex = value => [...new Uint8Array(value)].map(x => x.toString(16).padStart(2, '0')).join('');
const sha = async value => hex(await crypto.subtle.digest('SHA-256', value));

export async function verifyJWT(token, fetcher = fetch, now = Date.now()/1000) {
  if (typeof token !== 'string' || token.length > 16000) throw new Error('bad token');
  const parts = token.split('.');
  if (parts.length !== 3) throw new Error('bad token');
  const header = jsonPart(parts[0]), claims = jsonPart(parts[1]);
  if (header.alg !== 'RS256' || typeof header.kid !== 'string') throw new Error('bad algorithm');
  if (!jwksCache || jwksCache.until < now) {
    const result = await fetcher(issuer+'/.well-known/jwks');
    if (!result.ok) throw new Error('JWKS unavailable');
    jwksCache = {until: now+300, keys: (await result.json()).keys};
  }
  const jwk = jwksCache.keys.find(k => k.kid === header.kid && k.kty === 'RSA' && k.alg === 'RS256' && k.use === 'sig');
  if (!jwk) throw new Error('unknown signing key');
  const key = await crypto.subtle.importKey('jwk', jwk, {name:'RSASSA-PKCS1-v1_5',hash:'SHA-256'},false,['verify']);
  if (!await crypto.subtle.verify('RSASSA-PKCS1-v1_5',key,bytes(parts[2]),new TextEncoder().encode(parts.slice(0,2).join('.')))) throw new Error('signature');
  if (claims.iss !== issuer || claims.aud !== audience || !Number.isFinite(claims.exp) || !Number.isFinite(claims.iat) || !Number.isFinite(claims.nbf) || claims.exp <= now || claims.nbf > now+30 || claims.iat > now+30 || claims.exp-claims.iat > 600) throw new Error('token claims');
  return claims;
}

export function authorize(claims, key, policy, method) {
  const p = key.split('/');
  if (p.length !== 9 || p[0] !== 'v1' || p.some(x => !/^[A-Za-z0-9_.-]{1,180}$/.test(x) || x === '.' || x === '..')) throw new Error('path');
  const [,owner,repo,workflow,run,attempt,job,name,file] = p;
  const repository = owner+'/'+repo;
  const approved = policy[repository];
  const workflowPolicy = approved?.workflows?.[workflow];
  if (!approved || claims.repository !== repository || String(claims.repository_id) !== String(approved.id) || String(claims.repository_owner_id) !== '117706611') throw new Error('repository');
  if (!workflowPolicy || claims.workflow_ref?.split('@')[0] !== repository+'/.github/workflows/'+workflow || !workflowPolicy.events.includes(claims.event_name)) throw new Error('workflow');
  if (claims.event_name !== 'pull_request' && !workflowPolicy.refs.includes(claims.ref)) throw new Error('ref');
  if (claims.event_name === 'pull_request' && workflowPolicy.pull_request_base_refs &&
      (!/^refs\/pull\/[1-9][0-9]*\/merge$/.test(claims.ref || '') ||
       !workflowPolicy.pull_request_base_refs.includes(claims.base_ref))) throw new Error('PR base ref');
  if (workflowPolicy.reusable_refs && !workflowPolicy.reusable_refs.includes(claims.job_workflow_ref)) throw new Error('reusable workflow');
  // A signed run identity scopes *all* callers, including modified PR code, to
  // this run and attempt. It never grants access to older or other repo data.
  if (String(claims.run_id) !== run || String(claims.run_attempt) !== attempt || !/^[1-9][0-9]*$/.test(run) || !/^[1-9][0-9]*$/.test(attempt)) throw new Error('run');
  const names = workflowPolicy.slots[job];
  if (!names?.map(x=>x.replaceAll('{run}',run).replaceAll('{attempt}',attempt)).includes(name)) throw new Error('slot');
  if (!['GET','PUT'].includes(method) || !['payload.zip','manifest.json','complete.json'].includes(file)) throw new Error('operation');
  return {repository,workflow,run_id:run,run_attempt:attempt,job,name,file};
}

export async function serve(request, env, claims) {
  const url = new URL(request.url);
  if (url.search || url.pathname.includes('%')) return new Response('invalid path',{status:400});
  const key=url.pathname.slice(1);
  let identity;
  try {identity=authorize(claims,key,JSON.parse(env.ALLOWLIST || '{}'),request.method);}
  catch {return new Response('forbidden',{status:403});}
  if (request.method === 'GET') {
    const value=await env.ARTIFACTS.get(key);
    if (!value) return new Response('missing artifact',{status:404});
    return new Response(value.body,{headers:{'Content-Type':'application/octet-stream','Cache-Control':'private, no-store','X-Content-Type-Options':'nosniff'}});
  }
  const size=Number(request.headers.get('Content-Length'));
  const checksum=request.headers.get('X-Content-SHA256');
  if (!Number.isSafeInteger(size) || size<1 || size>limit || !/^[0-9a-f]{64}$/.test(checksum || '')) return new Response('invalid size or checksum',{status:400});
  const base=key.slice(0,key.lastIndexOf('/'));
  let value=request.body;
  if (identity.file !== 'payload.zip') {
    if(size>1024*1024) return new Response('metadata too large',{status:413});
    value=await request.arrayBuffer();
    if(value.byteLength!==size || await sha(value)!==checksum) return new Response('checksum mismatch',{status:400});
    let metadata;
    try{metadata=JSON.parse(new TextDecoder().decode(value));}catch{return new Response('bad JSON',{status:400});}
    if(identity.file==='manifest.json') {
      const expected={...identity};delete expected.file;
      if(metadata.schema!==1 || !/^[0-9a-f]{40}$/.test(metadata.context?.source_sha || '') || !metadata.files?.length || !Number.isInteger(metadata.retention_days) || metadata.retention_days<1 || metadata.retention_days>90 || Object.entries(expected).some(([k,v])=>metadata.context[k]!==v)) return new Response('manifest context',{status:400});
      const payload=await env.ARTIFACTS.head(base+'/payload.zip');
      if(!payload || payload.size!==metadata.payload?.size || payload.customMetadata?.sha256!==metadata.payload?.sha256) return new Response('payload missing or mismatched',{status:409});
    } else {
      const manifest=await env.ARTIFACTS.head(base+'/manifest.json');
      if(metadata.schema!==1 || !manifest || manifest.customMetadata?.sha256!==metadata.manifest_sha256) return new Response('manifest missing or mismatched',{status:409});
    }
  }
  const result=await env.ARTIFACTS.put(key,value,{sha256:checksum,onlyIf:new Headers({'If-None-Match':'*'}),customMetadata:{sha256:checksum}});
  if(!result) {
    const old=await env.ARTIFACTS.head(key);
    if(old?.size!==size || old?.customMetadata?.sha256!==checksum) return new Response('immutable conflict',{status:409});
  }
  return new Response('stored',{status:200});
}

export default {async fetch(request,env) {
  let claims;
  try {
    const auth=request.headers.get('Authorization') || '';
    if(!auth.startsWith('Bearer '))throw new Error('missing token');
    claims=await verifyJWT(auth.slice(7));
  }catch{return new Response('unauthorized',{status:401});}
  try{return await serve(request,env,claims);}
  catch{return new Response('storage unavailable',{status:503});}
}};
