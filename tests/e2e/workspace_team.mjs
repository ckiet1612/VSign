import assert from 'node:assert/strict';
import {spawn} from 'node:child_process';
import {mkdtemp,realpath,writeFile} from 'node:fs/promises';
import {createRequire} from 'node:module';
import os from 'node:os';
import path from 'node:path';
import net from 'node:net';
import {fileURLToPath} from 'node:url';

const require=createRequire(process.env.VSIGN_PLAYWRIGHT_FROM || import.meta.url);
const {chromium}=require('playwright'),sharp=require('sharp');
const root=fileURLToPath(new URL('../../',import.meta.url));
const output=await realpath(await mkdtemp(path.join(os.tmpdir(),'vsign-team-')));
const children=[],runtime=[],checks=[],layouts=[],errors=[];
const sleep=ms=>new Promise(r=>setTimeout(r,ms));
let browser,page,failure;
async function port(){const server=net.createServer();await new Promise(r=>server.listen(0,'127.0.0.1',r));const value=server.address().port;await new Promise(r=>server.close(r));return value;}
const apiPort=await port(),webPort=await port(),api=`http://127.0.0.1:${apiPort}`,web=`http://127.0.0.1:${webPort}`;
const password='fixture-password-12345',email='invited@example.com';
const name='Thành viên kiểm thử với tên dài · '.repeat(3).trim();
const base='/api/v1/workspace/team';
const env={...process.env,PYTHONPATH:`${root}/services/inference:${root}`,APP_ENV:'development',AUTH_REQUIRED:'true',LOCAL_ADMIN_ENABLED:'false',
  DATABASE_URL:`sqlite:///${output}/platform.db`,DATABASE_AUTO_CREATE:'true',WORKSPACE_ID:'team-e2e',INFERENCE_BACKEND:'mock',
  MODEL_MANIFEST_PATH:'',MODEL_DEPLOYMENT_WORKER:'false',COLLECTION_ENABLED:'false',ALLOWED_ORIGINS:web,
  BOOTSTRAP_ADMIN_EMAIL:'owner@example.com',BOOTSTRAP_ADMIN_PASSWORD:password,OPENAI_API_KEY:'',DEV_TEST_ENABLED:'false',
  INTEGRATION_ENCRYPTION_KEY:'',INTEGRATION_ENCRYPTION_KEY_FILE:''};
function start(label,command,args,cwd,environment){const child=spawn(command,args,{cwd,env:environment,detached:true,stdio:['ignore','pipe','pipe']});
  child.on('error',e=>errors.push(e.message));child.stdout.on('data',v=>runtime.push(`[${label}] ${v}`));child.stderr.on('data',v=>runtime.push(`[${label}] ${v}`));children.push(child);}
async function until(label,fn){const end=Date.now()+60000;while(Date.now()<end){for(const child of children)assert.equal(child.exitCode,null,label+': process exited');try{if(await fn())return;}catch{}await sleep(150);}throw new Error('Timeout: '+label);}
async function json(context,route){const response=await context.request.get(api+route);assert.equal(response.status(),200,await response.text());return response.json();}
async function login(target,account){await target.goto(web+'/?view=team');await target.getByLabel('Email',{exact:true}).fill(account);await target.getByLabel('Mật khẩu',{exact:true}).fill(password);await target.getByRole('button',{name:'Đăng nhập',exact:true}).click();}
async function invite(account,role='operator'){
  await page.getByRole('tab',{name:'Lời mời',exact:true}).click();await page.getByRole('button',{name:'Mời thành viên',exact:true}).click();
  await page.getByLabel('Email người nhận',{exact:true}).fill(account);await page.getByRole('combobox',{name:'Vai trò',exact:true}).selectOption(role);
  await page.getByRole('button',{name:'Tạo lời mời',exact:true}).click();
  const link=await page.getByRole('region',{name:'Liên kết mời một lần'}).locator('code').innerText();
  await page.getByRole('button',{name:'Ẩn liên kết'}).click();return link;
}
async function changeMember(label){await page.getByRole('button',{name:`${label} ${name}`,exact:true}).click();await page.getByRole('button',{name:'Xác nhận',exact:true}).click();await until('member updated',async()=>await page.getByRole('button',{name:'Xác nhận',exact:true}).count()===0);}
try {
  start('api',`${root}/.venv/bin/python`,['-m','uvicorn','app.main:app','--host','127.0.0.1','--port',String(apiPort)],root,env);
  await until('api',async()=> (await fetch(api+'/health')).ok);const metadata=await (await fetch(api+'/metadata')).json();
  start('web',process.execPath,['node_modules/vite/bin/vite.js','--host','127.0.0.1','--port',String(webPort),'--strictPort'],`${root}/apps/web`,
    {...process.env,VITE_PLATFORM_HTTP_URL:api,VITE_INFERENCE_HTTP_URL:api,VITE_INFERENCE_WS_URL:api.replace('http:','ws:')+'/ws/inference',VITE_PUBLIC_DEMO:'false'});
  await until('web',async()=> (await fetch(web)).ok);
  browser=await chromium.launch({channel:'chrome',headless:true});const owner=await browser.newContext({viewport:{width:1440,height:1000}});page=await owner.newPage();page.on('pageerror',e=>errors.push(e.message));
  await login(page,'owner@example.com');await page.getByRole('region',{name:'Danh sách thành viên'}).waitFor();
  assert.equal(await page.getByRole('tab').count(),4);assert.equal(await page.getByRole('button',{name:/^Gỡ /}).count(),0);
  const link=await invite(email);const token=new URL(link).hash.slice(7);
  assert.equal(JSON.stringify(await json(owner,base+'/invitations')).includes(token),false);
  checks.push('Owner signs in and creates a manual one-time invitation through enterprise UI; protected owner has no destructive controls; reads never echo token');
  const guest=await browser.newContext({viewport:{width:390,height:844}}),accept=await guest.newPage();accept.on('pageerror',e=>errors.push(e.message));
  let accepts=0;accept.on('request',request=>{if(request.url().endsWith('/invitations/accept'))accepts++;});
  await accept.goto(link);await accept.getByText(email,{exact:true}).waitFor();assert.equal(new URL(accept.url()).hash,'');assert.equal(accepts,0);assert.deepEqual(await guest.cookies(),[]);
  assert.equal(await accept.evaluate(()=>document.documentElement.scrollWidth>innerWidth),false);await accept.screenshot({path:`${output}/accept-form-390.png`,fullPage:true});
  await accept.getByLabel('Tên hiển thị',{exact:true}).fill(name);await accept.getByLabel('Mật khẩu',{exact:true}).fill(password);
  await accept.getByRole('button',{name:'Chấp nhận lời mời',exact:true}).click();await accept.getByRole('heading',{name:'Đã tham gia workspace.',exact:true}).waitFor();
  assert.equal(accepts,1);assert.deepEqual(await guest.cookies(),[]);assert.equal((await json(owner,'/api/v1/auth/me')).user.email,'owner@example.com');
  assert.equal((await guest.request.get(api+'/api/v1/auth/me')).status(),401);
  const invited=await guest.newPage();await login(invited,email);await until('invited session',async()=> (await guest.request.get(api+'/api/v1/auth/me')).status()===200);
  assert.equal((await json(guest,'/api/v1/auth/me')).user.role,'operator');assert.equal((await guest.request.get(api+base)).status(),403);
  checks.push('Anonymous acceptance clears hash before inspect, never submits on load or creates a session; invited account signs in explicitly with operator-only access');
  await page.getByRole('tab',{name:'Thành viên',exact:true}).click();await page.getByRole('button',{name:'Làm mới thành viên'}).click();
  await page.getByRole('combobox',{name:`Vai trò của ${name}`,exact:true}).selectOption('reviewer');await page.getByRole('button',{name:'Xác nhận',exact:true}).click();
  await until('role changes immediately',async()=> (await json(guest,'/api/v1/auth/me')).user.role==='reviewer');
  await changeMember('Tạm khóa');assert.equal((await guest.request.get(api+'/api/v1/auth/me')).status(),401);
  await changeMember('Khôi phục');assert.equal((await guest.request.get(api+'/api/v1/auth/me')).status(),401);
  const relogin=await guest.request.post(api+'/api/v1/auth/login',{data:{email,password}});assert.equal(relogin.status(),200);
  await changeMember('Gỡ');assert.equal((await guest.request.get(api+'/api/v1/auth/me')).status(),401);
  checks.push('Role change applies to existing session; suspend revokes it; restore never revives it; explicit re-login works; removal denies access');
  const secondLink=await invite(email,'viewer');const existingContext=await browser.newContext(),existing=await existingContext.newPage();
  await existing.goto(secondLink);await existing.getByLabel('Mật khẩu hiện tại',{exact:true}).fill('wrong-password');
  assert.equal(await existing.getByLabel('Tên hiển thị',{exact:true}).count(),0);
  await existing.getByRole('button',{name:'Chấp nhận lời mời',exact:true}).click();await existing.getByRole('alert').waitFor();
  await existing.getByLabel('Mật khẩu hiện tại',{exact:true}).fill(password);await existing.getByRole('button',{name:'Chấp nhận lời mời',exact:true}).click();
  await existing.getByRole('heading',{name:'Đã tham gia workspace.',exact:true}).waitFor();assert.deepEqual(await existingContext.cookies(),[]);
  const existingLogin=await existingContext.request.post(api+'/api/v1/auth/login',{data:{email,password}});assert.equal(existingLogin.status(),200);assert.equal((await existingLogin.json()).user.role,'viewer');
  const denied=await existingContext.request.post(api+base+'/invitations',{data:{}});assert.equal(denied.status(),403);
  const legacy=await json(existingContext,'/api/v1/workspace/audit/events?group=permission');assert.deepEqual(legacy.events,[]);
  const revokedLink=await invite('revoke@example.com');await page.getByRole('button',{name:'Thu hồi lời mời revoke@example.com',exact:true}).click();await page.getByRole('button',{name:'Xác nhận',exact:true}).click();
  await page.getByText('Đã thu hồi',{exact:true}).waitFor();assert.equal((await fetch(api+'/api/v1/invitations/inspect',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({token:new URL(revokedLink).hash.slice(7)})})).status,410);
  checks.push('Existing-account reinvite requires its existing password without reset; viewer cannot manage team or read private successful/denied audit; revoked links fail closed');
  for(const width of [1440,1024,768,390,320]) {
    await page.setViewportSize({width,height:1000});
    for(const [tab,label] of [['members','Thành viên'],['roles','Vai trò'],['invitations','Lời mời'],['audit','Nhật ký quyền']]) {
      await page.getByRole('tab',{name:label,exact:true}).click();await page.locator('#team-panel[aria-busy=false]').waitFor();
      if(tab==='audit'){await page.locator('.team-member-filter summary').click();await page.getByLabel('Tìm thành viên trong nhật ký').waitFor();}
      const file=`${output}/${tab}-${width}.png`;await page.screenshot({path:file,fullPage:true});
      const layout=await page.evaluate(()=>({overflow:document.documentElement.scrollWidth>innerWidth,width:document.querySelector('.team-page').getBoundingClientRect().width}));
      assert.equal(layout.overflow,false,`${tab} ${width}`);assert.ok(layout.width>100);assert.ok((await sharp(file).stats()).channels.some(channel=>channel.stdev>15));layouts.push({tab,width,screenshot:file});
      if(tab==='audit')await page.locator('.team-member-filter summary').click();
    }
  }
  await accept.setViewportSize({width:320,height:800});await accept.screenshot({path:`${output}/accepted-320.png`,fullPage:true});
  assert.equal(await accept.evaluate(()=>document.documentElement.scrollWidth>innerWidth),false);
  assert.deepEqual(await (await fetch(api+'/metadata')).json(),metadata);assert.deepEqual(errors,[]);
  checks.push('Four populated views render at five widths with nonblank pixel statistics and no page overflow; acceptance mobile layout passes; inference metadata unchanged and no page errors');
} catch(error){failure=error;if(page)await page.screenshot({path:`${output}/failure.png`,fullPage:true}).catch(()=>{});}
finally {
  if(browser)await browser.close();
  for(const child of children.reverse())if(child.exitCode===null){try{process.kill(-child.pid,'SIGTERM');}catch{}}
  for(const child of children){if(child.exitCode===null)await Promise.race([new Promise(r=>child.once('exit',r)),sleep(5000)]);if(child.exitCode===null){try{process.kill(-child.pid,'SIGKILL');}catch{}}}
  await writeFile(`${output}/runtime.log`,runtime.join(''));
  await writeFile(`${output}/report.json`,JSON.stringify({checks,layouts,errors,failure:failure?.stack??null,limits:'Isolated SQLite/mock fixture. No shared DB writes, real email, public delivery, PostgreSQL or production acceptance.'},null,2));
}
console.log(JSON.stringify({output,checks,layouts,failure:failure?.message??null},null,2));if(failure)throw failure;
