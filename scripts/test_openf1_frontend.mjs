/** Node-only historical-data UI contract tests; no external network or browser. */
import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import vm from 'node:vm';
import {fileURLToPath} from 'node:url';
const root=path.resolve(path.dirname(fileURLToPath(import.meta.url)),'..');
const dir=path.join(root,'src/f1_strategy_optimizer/workbench_static');
const html=fs.readFileSync(path.join(dir,'index.html'),'utf8');
class Element{
 constructor(){this.children=[];this.textContent='';this.value='';this.disabled=false;this.events={};this.classes=new Set();this.classList={add:c=>this.classes.add(c),remove:c=>this.classes.delete(c)};}
 append(...children){this.children.push(...children);}replaceChildren(...children){this.children=children;this.textContent='';}addEventListener(name,fn){this.events[name]=fn;}
}
const ids=new Map([...html.matchAll(/id="([^"]+)"/g)].map(m=>[m[1],new Element()]));
const pending=[],requests=[];
const fakeFetch=(url,{signal})=>{requests.push(url);return new Promise((resolve,reject)=>{const request={url,resolve:body=>resolve({ok:true,status:200,json:async()=>body}),fail:message=>resolve({ok:false,status:429,json:async()=>({error:message})})};pending.push(request);signal.addEventListener('abort',()=>reject(Object.assign(Error('aborted'),{name:'AbortError'})));});};
const context=vm.createContext({document:{getElementById:id=>ids.get(id),createElement:()=>new Element()},fetch:fakeFetch,AbortController,setTimeout,clearTimeout,Date,Blob,URL});
const source=fs.readFileSync(path.join(dir,'history.js'),'utf8');
for(const match of source.matchAll(/el\('([^']+)'\)/g))assert.ok(ids.has(match[1]),match[1]);
vm.runInContext(source.replace(/\}\)\(\);\s*$/,'globalThis.historyTest={hs,loadSessions,loadDrivers,loadHistory,cancel,duration,utc,renderHistory};})();'),context);
const t=context.historyTest;
assert.equal(requests.length,0,'Opening the workbench must remain offline');
assert.equal(t.duration(98.614),'1:38.614');assert.equal(t.duration(null),'缺失');assert.equal(t.duration(NaN),'缺失');
const session={session_key:100,meeting_name:'Historical test',date_start:'2024-01-01T12:00:00Z',available:true};
let task=t.loadSessions();pending.at(-1).resolve({races:[session,{...session,session_key:101,available:false,blocked_reason:'封存赛事'}],source:{cache_status:'stale_fallback',retrieved_at_utc:'2025-01-01T00:00:00Z',warnings:['比赛列表刷新失败']}});await task;
assert.match(ids.get('history-warning').textContent,/比赛列表刷新失败/);assert.match(ids.get('history-status').textContent,/旧缓存/);
assert.equal(ids.get('history-session').children[2].disabled,true);
ids.get('history-session').value='101';await t.loadDrivers();assert.equal(requests.length,1,'Blocked races must not be requested');
ids.get('history-session').value='100';task=t.loadDrivers();pending.at(-1).resolve({session,drivers:[{driver_number:44,full_name:'Driver A',team_name:'Team A'},{driver_number:1,full_name:'Driver B',team_name:'Team B'}]});await task;
assert.equal(requests.length,2,'Selecting a race only loads its driver list');
const record=driver=>({session,driver:{driver_number:driver,full_name:driver===44?'Driver A':'Driver B'},laps:[{lap_number:1,lap_duration:98.614,date_start:'2024-01-01T12:00:00Z',is_pit_out_lap:false},{lap_number:2,lap_duration:null,is_pit_out_lap:null}],stints:[],source:{provider:'OpenF1',live:false,availability_basis:'post_event_download',retrieved_at_utc:'2026-11-04T05:00:00Z',cache_status:'miss'},limitations:['Not a validated live forecast']});
ids.get('history-driver').value='44';task=t.loadHistory();pending.at(-1).resolve(record(44));await task;
assert.equal(ids.get('history-lap-count').textContent,'2');assert.equal(ids.get('history-timed-count').textContent,'1');assert.equal(ids.get('history-laps').children[1].children[1].textContent,'缺失');assert.match(ids.get('history-source').textContent,/不是比赛当时的接收时间/);assert.equal(ids.get('history-export').disabled,false);
// A newer choice wins over a delayed/aborted older response.
let old=t.loadHistory(),oldRequest=pending.at(-1);ids.get('history-driver').value='1';let latest=t.loadHistory();pending.at(-1).resolve(record(1));await latest;oldRequest.resolve(record(44));await old;
assert.equal(t.hs.record.driver.driver_number,1);assert.match(ids.get('history-selection').textContent,/Driver B/);
task=t.loadHistory();pending.at(-1).fail('请求过于频繁');await task;assert.equal(t.hs.record,null);assert.equal(ids.get('history-export').disabled,true);assert.equal(ids.get('history-laps').children.length,0);assert.match(ids.get('history-error').textContent,/请求过于频繁/);
task=t.loadHistory();t.cancel();await task;assert.equal(t.hs.record,null);assert.equal(t.hs.busy,false);
task=t.loadHistory();pending.at(-1).resolve(record(44));await task;assert.equal(t.hs.record,null);assert.match(ids.get('history-error').textContent,/不匹配/);
task=t.loadHistory();const live=record(1);live.source.live=true;pending.at(-1).resolve(live);await task;assert.equal(t.hs.record,null);assert.match(ids.get('history-error').textContent,/赛后历史下载/);
task=t.loadHistory();const empty=record(1);empty.laps=[];pending.at(-1).resolve(empty);await task;assert.equal(ids.get('history-lap-count').textContent,'0');assert.match(ids.get('history-status').textContent,/没有圈时数据/);
task=t.loadHistory();const stale=record(1);stale.source.cache_status='stale_fallback';stale.source.warnings=['服务刷新失败，显示原缓存'];stale.source.retrieved_at_utc='2025-01-01T00:00:00Z';pending.at(-1).resolve(stale);await task;
assert.match(ids.get('history-status').textContent,/旧缓存/);assert.match(ids.get('history-cache').textContent,/刷新失败/);assert.match(ids.get('history-warning').textContent,/2025-01-01/);assert.match(ids.get('history-warning').textContent,/服务刷新失败/);assert.equal(ids.get('history-warning').classes.has('hidden'),false);
task=t.loadHistory();pending.at(-1).resolve(record(1));await task;assert.equal(ids.get('history-warning').classes.has('hidden'),true);assert.equal(ids.get('history-warning').textContent,'');
assert.ok(requests.every(url=>url.startsWith('/api/openf1/')),'Historical browsing must not call frozen/reveal/explore APIs');
console.log('PASS: offline startup, blocked sessions, automatic selection loading, source/identity checks, null/empty data, stale request suppression, retryable error clearing, cancellation, frozen-flow isolation.');

if(process.argv[2]){
 const real=JSON.parse(fs.readFileSync(process.argv[2],'utf8'));
 ids.get('history-session').value=String(real.session.session_key);ids.get('history-driver').value=String(real.driver.driver_number);
 t.renderHistory(real);
 assert.equal(ids.get('history-laps').children.length,real.laps.length);
 assert.equal(ids.get('history-stints').children.length,real.stints.length);
 assert.equal(ids.get('history-export').disabled,false);
 assert.match(ids.get('history-source').textContent,/不是比赛当时的接收时间/);
 console.log(`PASS: captured real API response rendered: session ${real.session.session_key}, driver ${real.driver.driver_number}, ${real.laps.length} laps, ${real.stints.length} stints; no new external requests.`);
}
