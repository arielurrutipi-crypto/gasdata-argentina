const assert=require('node:assert/strict');
const waitForArtifact=require('./wait_pages_artifact.cjs');
const name='github-pages-123-2',current={name,id:21,expired:false};
function harness(sequence){
 const calls=[],delays=[],warnings=[];let index=0;
 const endpoint=()=>{};
 const github={rest:{actions:{listWorkflowRunArtifacts:endpoint}},paginate:async(method,params)=>{
   assert.equal(method,endpoint);assert.equal(params.run_id,123);assert.equal(params.per_page,100);
   calls.push(params);const value=sequence[Math.min(index++,sequence.length-1)];
   if(value instanceof Error)throw value;return value;
 }};
 return {args:{github,context:{repo:{owner:'owner',repo:'repo'},runId:123},core:{info:()=>{},warning:x=>warnings.push(x)},name,expectedId:'21',intervalMs:1,maxAttempts:5,wait:async ms=>delays.push(ms)},calls,delays,warnings};
}
(async()=>{
 // Old attempts may remain in the run without being selected or deleted.
 const old={name:'github-pages-123-1',id:20},h=harness([[old],[old,current],[old,current]]);
 assert.equal((await waitForArtifact(h.args)).id,21);
 assert.equal(h.calls.length,3);assert.equal(h.delays.length,2);
 const transient=Object.assign(new Error('temporary'),{status:503}),r=harness([transient,[current],[current]]);
 await waitForArtifact(r.args);assert.equal(r.warnings.length,1);
 const flicker=harness([[current],[],[current],[current]]);
 await waitForArtifact(flicker.args);assert.equal(flicker.calls.length,4,'visibility must remain stable');
 const missing=harness([[old]]);
 await assert.rejects(waitForArtifact(missing.args),/No se pudo confirmar/);
 assert.equal(missing.calls.length,5);assert.equal(missing.delays.length,4,'bounded retries');
 for(const bad of [{...current,id:22},{...current,expired:true}]){
   const h=harness([[bad]]);await assert.rejects(waitForArtifact(h.args),/No se pudo confirmar/);
 }
 const duplicate=harness([[current,{...current,id:22}]]);
 await assert.rejects(waitForArtifact(duplicate.args),/varios paquetes/);
 const unconfigured=harness([[current]]);
 await assert.rejects(waitForArtifact({...unconfigured.args,expectedId:''}),/Falta/);
 assert.equal(unconfigured.calls.length,0);
 console.log('OK: isolated attempts, correct artifact ID, stable visibility, transient errors, expiry and bounded retries');
})().catch(error=>{console.error(error);process.exitCode=1;});
