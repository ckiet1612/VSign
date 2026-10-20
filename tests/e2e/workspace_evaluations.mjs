import assert from 'node:assert/strict';
import { spawn } from 'node:child_process';
import { mkdtemp,readFile,writeFile,realpath } from 'node:fs/promises';
import { createRequire } from 'node:module';
import os from 'node:os';
import path from 'node:path';
import net from 'node:net';
import { fileURLToPath } from 'node:url';

const require=createRequire(process.env.VSIGN_PLAYWRIGHT_FROM || import.meta.url);
const {chromium}=require('playwright'),sharp=require('sharp');
const root=fileURLToPath(new URL('../../',import.meta.url));
const output=await realpath(await mkdtemp(path.join(os.tmpdir(),'vsign-evaluations-')));
const children=[],logs=[],checks=[],layouts=[],errors=[];
let browser,page,failure;
const sleep=ms => new Promise(resolve => setTimeout(resolve,ms));
async function port() {const s=net.createServer();await new Promise(r=>s.listen(0,'127.0.0.1',r));const p=s.address().port;await new Promise(r=>s.close(r));return [8000,8002,8003,5174].includes(p) ? port() : p;}
const apiPort=await port(),webPort=await port(),api=`http://127.0.0.1:${apiPort}`,web=`http://127.0.0.1:${webPort}`;
const env={...process.env,PYTHONPATH:`${root}/services/inference:${root}`,APP_ENV:'development',AUTH_REQUIRED:'false',LOCAL_ADMIN_ENABLED:'true',
  DATABASE_URL:`sqlite:///${output}/platform.db`,DATABASE_AUTO_CREATE:'true',WORKSPACE_ID:'evaluation-e2e',
  INFERENCE_BACKEND:'mock',MODEL_MANIFEST_PATH:'',MODEL_DEPLOYMENT_WORKER:'false',COLLECTION_ENABLED:'true',COLLECTION_DIR:`${output}/media`,
  MODEL_REGISTRY_ROOTS:`${output}/registry`,MODEL_EVALUATION_ROOTS:`${output}/evidence`,ALLOWED_ORIGINS:web,
  BOOTSTRAP_ADMIN_EMAIL:'',BOOTSTRAP_ADMIN_PASSWORD:'',OPENAI_API_KEY:'',DEV_TEST_ENABLED:'false'};
function start(name,command,args,cwd,environment) {const c=spawn(command,args,{cwd,env:environment,detached:true,stdio:['ignore','pipe','pipe']});
  c.managed=['api','web','worker'].includes(name);c.on('error',e=>errors.push(e.message));c.stdout.on('data',v=>logs.push(`[${name}] ${v}`));c.stderr.on('data',v=>logs.push(`[${name}] ${v}`));children.push(c);return c;}
async function until(name,fn,timeout=90000) {const end=Date.now()+timeout;while(Date.now()<end) {assert.deepEqual(errors,[]);for(const child of children) if(child.managed) assert.equal(child.exitCode,null,`${name}: service exited; see ${output}/runtime.log`);if(await fn())return;await sleep(200);}throw new Error(`Timeout: ${name}`);}
async function json(route) {const r=await fetch(api+route);assert.equal(r.status,200,await r.clone().text());return r.json();}
const base='/api/v1/workspace/evaluations';
try {
  start('api',`${root}/.venv/bin/python`,['tests/e2e/workspace_evaluation_fixture.py','--output',output,'--port',String(apiPort),'--origin',web],root,env);
  await until('api',async()=>{try{return (await fetch(api+'/health')).ok;}catch{return false;}});
  const fixture=JSON.parse(await readFile(`${output}/fixture.json`,'utf8'));
  start('web',process.execPath,['node_modules/vite/bin/vite.js','--host','127.0.0.1','--port',String(webPort),'--strictPort'],`${root}/apps/web`,
    {...process.env,VITE_PLATFORM_HTTP_URL:api,VITE_INFERENCE_HTTP_URL:api,VITE_INFERENCE_WS_URL:api.replace('http:','ws:')+'/ws/inference',VITE_PUBLIC_DEMO:'false',VITE_PLATFORM_AUTH_REQUIRED:'false'});
  await until('web',async()=>{try{return (await fetch(web)).ok;}catch{return false;}});
  browser=await chromium.launch({channel:'chrome',headless:true});
  page=await browser.newPage({viewport:{width:1365,height:1000}});
  page.on('pageerror',e=>errors.push(e.message));
  await page.goto(web+'/?view=evaluation');
  await page.getByRole('heading',{name:'Đánh giá',exact:true}).waitFor();
  await page.getByText('Chưa có lượt đánh giá.',{exact:true}).waitFor();
  assert.equal(await page.locator('input[type=password]').count(),0);
  const before=await json('/metadata');
  await page.getByLabel('Model cần đánh giá',{exact:true}).selectOption(fixture.candidate_id);
  await page.getByLabel('Bản dữ liệu đã chốt',{exact:true}).selectOption(fixture.snapshot_id);
  await page.getByRole('button',{name:'Tạo lượt đánh giá',exact:true}).click();
  await page.getByRole('button',{name:'Hủy lượt đánh giá',exact:true}).waitFor();
  await page.getByRole('button',{name:'Hủy lượt đánh giá',exact:true}).click();
  await until('cancelled',async()=> (await json(base)).runs[0]?.status==='cancelled');
  checks.push('Enterprise admin creates and cancels a persisted queued run; no login or internal controls');
  await page.getByRole('button',{name:'Tạo lượt đánh giá',exact:true}).click();
  start('worker',`${root}/.venv/bin/python`,['-m','app.evaluation_worker','--backend','onnx'],root,env);
  await until('computed report',async()=> (await json(base)).runs[0]?.status==='completed');
  let run=(await json(base)).runs[0];
  assert.equal(run.report.candidate.accuracy,1);assert.equal(run.report.candidate.macro_f1,1);assert.equal(run.report.candidate.false_accept_rate,0);
  assert.equal(run.gate.passed,false);assert.equal(run.report.held_out,false);
  await page.getByRole('heading',{name:'Chưa đạt chốt chất lượng',exact:true}).waitFor();
  assert.equal(await page.getByRole('table').count(),2);
  checks.push('Separate native ONNX worker evaluates actual immutable MP4s; measured comparison available; missing provenance fails closed');
  const proof=start('proof',`${root}/.venv/bin/python`,['tests/e2e/workspace_evaluation_fixture.py','--output',output,'--proof'],root,env);
  await new Promise((resolve,reject)=>proof.once('exit',code=>code===0 ? resolve() : reject(new Error('Proof fixture failed'))));
  await page.getByRole('button',{name:'Tạo lượt đánh giá',exact:true}).click();
  await until('trusted computed report',async()=>{const runs=(await json(base)).runs;return runs.length===3 && runs[0].status==='completed';});
  run=(await json(base)).runs[0];
  assert.equal(run.gate.passed,true,JSON.stringify(run.gate));
  await page.getByRole('heading',{name:'Đạt chốt chất lượng',exact:true}).waitFor();
  const models=await json('/api/v1/workspace/models');
  const candidate=models.models.find(m=>m.id===fixture.candidate_id);
  assert.equal(candidate.approved_validation_id,null);assert.equal(models.target.revision,0);assert.equal(models.target.active_model_id,fixture.baseline_id);
  assert.equal((await fetch(api+`/api/v1/workspace/models/${candidate.id}/approve`,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({validation_id:candidate.validation.id})})).status,403);
  assert.deepEqual(await json('/metadata'),before);
  checks.push('Trusted synthetic lineage plus computed passing metrics still leaves approval empty and production unchanged; enterprise approval denied');
  for (const width of [1440,1024,768,390]) {
    await page.setViewportSize({width,height:1000});
    const file=`${output}/evaluation-${width}.png`;
    await page.screenshot({path:file,fullPage:true});
    const layout=await page.evaluate(()=>({overflow:document.documentElement.scrollWidth>innerWidth,
      text:document.querySelector('.evaluations-detail')?.textContent,main:document.querySelector('.evaluations-page')?.getBoundingClientRect().width}));
    assert.equal(layout.overflow,false,JSON.stringify({width,...layout}));assert.ok(layout.main>100 && layout.text.includes('Hello'));
    const stats=await sharp(file).stats();assert.ok(stats.channels.some(c=>c.stdev>15));layouts.push({width,screenshot:file,overflow:false});
  }
  checks.push('Completed run comparison and quality checks render across four widths, with nonblank screenshots and no page overflow');
} catch(e) {failure=e;if(page) {await page.screenshot({path:`${output}/failure.png`,fullPage:true}).catch(()=>{});await writeFile(`${output}/failure.txt`,await page.locator('body').innerText().catch(()=>''));}}
finally {
  if(browser) await browser.close();
  for(const c of children.reverse()) {if(c.exitCode===null) {try{process.kill(-c.pid,'SIGTERM');}catch{}}}
  for(const c of children) {if(c.exitCode===null) await Promise.race([new Promise(r=>c.once('exit',r)),sleep(7000)]);
    if(c.exitCode===null) {try{process.kill(-c.pid,'SIGKILL');}catch{}}}
  await writeFile(`${output}/runtime.log`,logs.join(''));
  await writeFile(`${output}/report.json`,JSON.stringify({checks,layouts,errors,failure:failure?.stack ?? null,limits:'Generated videos and tiny synthetic ONNX only; not real sign quality.'},null,2));
}
console.log(JSON.stringify({output,checks,layouts,failure:failure?.message ?? null},null,2));
if(failure) throw failure;
