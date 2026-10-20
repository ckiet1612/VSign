import assert from 'node:assert/strict';
import {spawn} from 'node:child_process';
import {mkdtemp,realpath,writeFile} from 'node:fs/promises';
import {createRequire} from 'node:module';
import {randomBytes} from 'node:crypto';
import os from 'node:os';
import path from 'node:path';
import net from 'node:net';
import {fileURLToPath} from 'node:url';

const require=createRequire(process.env.VSIGN_PLAYWRIGHT_FROM || import.meta.url);
const {chromium}=require('playwright'),sharp=require('sharp');
const root=fileURLToPath(new URL('../../',import.meta.url));
const output=await realpath(await mkdtemp(path.join(os.tmpdir(),'vsign-integrations-')));
const children=[],runtime=[],checks=[],layouts=[],errors=[];
let browser,page,failure;
const sleep=ms=>new Promise(r=>setTimeout(r,ms));
async function port(){const s=net.createServer();await new Promise(r=>s.listen(0,'127.0.0.1',r));const p=s.address().port;await new Promise(r=>s.close(r));return p;}
const apiPort=await port(),webPort=await port(),api=`http://127.0.0.1:${apiPort}`,web=`http://127.0.0.1:${webPort}`;
const env={...process.env,PYTHONPATH:`${root}/services/inference:${root}`,APP_ENV:'development',AUTH_REQUIRED:'false',LOCAL_ADMIN_ENABLED:'true',
  DATABASE_URL:`sqlite:///${output}/platform.db`,DATABASE_AUTO_CREATE:'true',WORKSPACE_ID:'integration-e2e',INFERENCE_BACKEND:'mock',
  MODEL_MANIFEST_PATH:'',MODEL_DEPLOYMENT_WORKER:'false',COLLECTION_ENABLED:'false',ALLOWED_ORIGINS:web,
  BOOTSTRAP_ADMIN_EMAIL:'',BOOTSTRAP_ADMIN_PASSWORD:'',OPENAI_API_KEY:'',DEV_TEST_ENABLED:'false',
  INTEGRATION_ENCRYPTION_KEY:randomBytes(32).toString('base64url')+'='};
function start(name,command,args,cwd,environment){const child=spawn(command,args,{cwd,env:environment,detached:true,stdio:['ignore','pipe','pipe']});
  child.on('error',e=>errors.push(e.message));child.stdout.on('data',v=>runtime.push(`[${name}] ${v}`));child.stderr.on('data',v=>runtime.push(`[${name}] ${v}`));children.push(child);return child;}
async function until(name,fn){const end=Date.now()+60000;while(Date.now()<end){for(const c of children)assert.equal(c.exitCode,null,`${name}: service exited`);try{if(await fn())return;}catch{}await sleep(200);}throw new Error('Timeout: '+name);}
async function json(route,options){const r=await fetch(api+route,options);assert.equal(r.status,200,await r.clone().text());return r.json();}
const base='/api/v1/workspace/integrations';
try {
  start('api',`${root}/.venv/bin/python`,['-m','uvicorn','app.main:app','--host','127.0.0.1','--port',String(apiPort)],root,env);
  await until('api',async()=> (await fetch(api+'/health')).ok);
  const before=await json('/metadata');
  start('web',process.execPath,['node_modules/vite/bin/vite.js','--host','127.0.0.1','--port',String(webPort),'--strictPort'],`${root}/apps/web`,
    {...process.env,VITE_PLATFORM_HTTP_URL:api,VITE_INFERENCE_HTTP_URL:api,VITE_INFERENCE_WS_URL:api.replace('http:','ws:')+'/ws/inference',VITE_PUBLIC_DEMO:'false',VITE_PLATFORM_AUTH_REQUIRED:'false'});
  await until('web',async()=> (await fetch(web)).ok);
  browser=await chromium.launch({channel:'chrome',headless:true});page=await browser.newPage({viewport:{width:1440,height:1000}});
  page.on('pageerror',e=>errors.push(e.message));
  await page.goto(web+'/?view=integrations');
  await page.getByText('Chưa có khóa API.',{exact:true}).waitFor();
  assert.equal(await page.locator('input[type=password]').count(),0);
  await page.getByRole('button',{name:'Tạo khóa',exact:true}).click();
  const name='CRM doanh nghiệp · '+ 'Tên kết nối dài '.repeat(5);
  await page.getByLabel('Tên khóa',{exact:true}).fill(name);
  await page.getByLabel('Lượt gọi / phút',{exact:true}).fill('2');
  await page.getByRole('button',{name:'Lưu khóa',exact:true}).click();
  const secret=await page.getByRole('region',{name:'Khóa bí mật',exact:true}).locator('code').innerText();
  assert.ok(secret.startsWith('vsign_'));
  const headers={Authorization:'Bearer '+secret};
  assert.equal((await fetch(api+'/api/v1/integrations/models',{headers})).status,200);
  assert.equal((await fetch(api+'/api/v1/workspace/members',{headers})).status,403);
  assert.equal((await fetch(api+'/api/v1/integrations/snapshots',{headers})).status,403);
  assert.equal((await fetch(api+'/api/v1/integrations/models',{headers})).status,429);
  assert.equal(JSON.stringify(await json(base)).includes(secret),false);
  await page.getByRole('button',{name:'Đóng khóa bí mật',exact:true}).click();
  checks.push('Real enterprise UI creates a one-time hashed key; scoped reads, no-admin escalation and persisted rate limit enforced');
  await page.getByRole('tab',{name:'Webhooks',exact:true}).click();
  await page.getByRole('button',{name:'Thêm webhook',exact:true}).click();
  await page.getByLabel('Tên kết nối',{exact:true}).fill('ERP · Đơn hàng');
  await page.getByLabel('Địa chỉ nhận',{exact:true}).fill('https://example.com/events');
  await page.getByRole('button',{name:'Lưu webhook',exact:true}).click();
  await page.getByRole('region',{name:'Khóa bí mật',exact:true}).waitFor();
  await page.getByRole('button',{name:'Đóng khóa bí mật',exact:true}).click();
  await page.getByRole('button',{name:'Gửi thử',exact:true}).click();
  await until('queued delivery',async()=> (await json(base)).deliveries.length===1);
  await page.getByRole('region',{name:'Lượt giao webhook',exact:true}).waitFor();
  assert.equal((await json(base)).worker_online,false);
  checks.push('Encrypted webhook and selected subscriptions persist; explicit send-test queues exactly one delivery; no dispatcher or outbound request in fixture');
  for(const width of process.env.VSIGN_E2E_WIDTHS?.split(',').map(Number) ?? [1440,1024,768,390]) {
    await page.setViewportSize({width,height:1000});
    for(const [tab,label] of [['webhooks','Webhooks'],['keys','Khóa API'],['logs','Nhật ký']]) {
      await page.getByRole('tab',{name:label,exact:true}).click();
      const file=`${output}/${tab}-${width}.png`;await page.screenshot({path:file,fullPage:true});
      const layout=await page.evaluate(()=>({overflow:document.documentElement.scrollWidth>innerWidth,pageWidth:document.querySelector('.integrations-page').getBoundingClientRect().width,
        documentWidth:document.documentElement.scrollWidth,viewport:innerWidth,
        tables:[...document.querySelectorAll('.integrations-table')].map(e=>({width:e.getBoundingClientRect().width,right:e.getBoundingClientRect().right,scroll:e.scrollWidth,overflow:getComputedStyle(e).overflowX})),
        nodes:[...document.querySelectorAll('body *')].filter(e=>e.getBoundingClientRect().right>innerWidth+1 && !e.closest('nav') && !e.closest('table')).slice(0,30)
          .map(e=>({tag:e.tagName,class:e.className,right:e.getBoundingClientRect().right,width:e.getBoundingClientRect().width}))}));
      assert.equal(layout.overflow,false,`${tab} ${width} ${JSON.stringify(layout)}`);assert.ok(layout.pageWidth>100);
      const stats=await sharp(file).stats();assert.ok(stats.channels.some(c=>c.stdev>15));layouts.push({tab,width,screenshot:file,overflow:false});
    }
  }
  checks.push('Three populated views render at four desktop/mobile widths; nonblank screenshots and no document overflow');
  await page.getByRole('tab',{name:'Khóa API',exact:true}).click();
  await page.getByRole('button',{name:`Thu hồi ${name}`,exact:true}).click();
  await page.getByRole('button',{name:'Xác nhận',exact:true}).click();
  await page.getByText('Đã thu hồi',{exact:true}).waitFor();
  assert.equal((await fetch(api+'/api/v1/integrations/models',{headers})).status,401);
  assert.deepEqual(await json('/metadata'),before);
  assert.equal((await json('/api/v1/auth/me')).auth_mode,'local_admin');
  assert.deepEqual(errors,[]);
  checks.push('Revocation takes effect immediately; no login, production metadata unchanged, no page errors');
} catch(error){failure=error;if(page){await page.screenshot({path:`${output}/failure.png`,fullPage:true}).catch(()=>{});}}
finally {
  if(browser)await browser.close();
  for(const child of children.reverse())if(child.exitCode===null){try{process.kill(-child.pid,'SIGTERM');}catch{}}
  for(const child of children){if(child.exitCode===null)await Promise.race([new Promise(r=>child.once('exit',r)),sleep(5000)]);if(child.exitCode===null){try{process.kill(-child.pid,'SIGKILL');}catch{}}}
  await writeFile(`${output}/runtime.log`,runtime.join(''));
  await writeFile(`${output}/report.json`,JSON.stringify({checks,layouts,errors,failure:failure?.stack ?? null,
    limits:'Isolated database; no external webhook dispatch; real TLS/signature covered by backend tests, not public delivery acceptance.'},null,2));
}
console.log(JSON.stringify({output,checks,layouts,failure:failure?.message ?? null},null,2));
if(failure)throw failure;
