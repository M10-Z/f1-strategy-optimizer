/** Dependency-free DOM contract tests; not a replacement for browser visual QA.
 * Run: node scripts/test_workbench_frontend.mjs
 */
import assert from 'node:assert/strict';
import fs from 'node:fs';
import vm from 'node:vm';
import path from 'node:path';
import {fileURLToPath} from 'node:url';
const root=path.resolve(path.dirname(fileURLToPath(import.meta.url)),'..');
const assets=path.join(root,'src/f1_strategy_optimizer/workbench_static');
const html=fs.readFileSync(path.join(assets,'index.html'),'utf8');
class Element {
 constructor(tag='div'){this.tagName=tag;this.children=[];this.textContent='';this.value='';this.disabled=false;this.dataset={};this.events={};this.classes=new Set();this.classList={add:x=>this.classes.add(x),remove:x=>this.classes.delete(x),toggle:(x,v)=>v?this.classes.add(x):this.classes.delete(x)};}
 append(...children){this.children.push(...children);}
 replaceChildren(...children){this.children=children;this.textContent='';}
 setAttribute(k,v){this[k]=v;}
 addEventListener(k,fn){this.events[k]=fn;}
 querySelectorAll(){return [];}
}
const ids=new Map([...html.matchAll(/id="([^"]+)"/g)].map(x=>[x[1],new Element()]));
assert.equal(ids.size,[...html.matchAll(/id="([^"]+)"/g)].length,'Duplicate HTML IDs');
const source=fs.readFileSync(path.join(assets,'app.js'),'utf8');
for(const match of source.matchAll(/\$\('([^']+)'\)/g))assert.ok(ids.has(match[1]),`Missing DOM ID ${match[1]}`);
const context=vm.createContext({document:{getElementById:id=>ids.get(id),createElement:tag=>new Element(tag)},console,setTimeout,clearTimeout,AbortController,Blob,URL,fetch:()=>{throw Error('Unexpected network request');}});
vm.runInContext(source.slice(0,source.lastIndexOf('(async()=>'))+'\nglobalThis.test={state,renderForecast,candidateVisual,invalidate,loadCase,loadDriver,reveal,lapTime,checkedNumber,bindNumber,validateAndSyncNumbers,compare,horizonRules,validatePlanningHorizon,validateWeatherAssumptions,syncOpponentLap};',context);
const {state,renderForecast,candidateVisual,invalidate}=context.test;
// Controls must not accept edits before initial data or a replacement case is ready.
for(const id of ['horizon-panel','observed','assumptions','outcomes'])assert.ok(html.includes(`id="${id}" class="panel" inert`));
state.assumptions=null;state.loadingCase=false;ids.get('global-error').textContent='';
for(const id of ['weather','track-status','pit-loss','total-laps','target-rank','risk-mode'])ids.get(id).events.change();
assert.equal(ids.get('global-error').textContent,'');assert.equal(state.assumptions,null);
const row=(id,value)=>({driver_id:id,name:id,team:'Team',target_lap:12,predicted_lap_seconds:value,lap_age_seconds:15,reason_zh:value===null?'证据过期':null,sample_laps:[8,9,10],observed_range_seconds:0.5});
state.driver='a';state.forecast={summary:{available:1,abstained:1},cutoff:'2023-03-05T15:18:00Z',limitations:['历史回放'],drivers:[row('a',95.3),row('b',null)]};
renderForecast();
assert.equal(ids.get('forecast-drivers').children.length,2);
assert.equal(ids.get('forecast-drivers').children[1].children[2].textContent,'暂不预测');
assert.equal(ids.get('readiness-driver').textContent,'a');
assert.equal(ids.get('readiness-time').textContent,'1:35.300');
assert.equal(ids.get('readiness-target').textContent,'第 12 圈 · 估计圈时');
assert.equal(ids.get('readiness-team').textContent,'Team');
assert.match(ids.get('readiness-detail').textContent,/精度尚未达标/);
assert.match(ids.get('forecast-count').textContent,/1 有估计值 \/ 1 暂不预测/);
state.driver='b';renderForecast();assert.equal(ids.get('readiness-driver').textContent,'b');assert.equal(ids.get('readiness-time').textContent,'暂不预测');assert.equal(ids.get('readiness-detail').textContent,'证据过期');
state.forecast={error:'service unavailable'};renderForecast();assert.equal(ids.get('forecast-drivers').children.length,0);assert.match(ids.get('forecast-status').textContent,/service unavailable/);assert.equal(ids.get('forecast-evidence').textContent,'');
assert.equal(ids.get('readiness-time').textContent,'—');assert.equal(ids.get('readiness-team').textContent,'');
state.forecast=null;renderForecast();assert.match(ids.get('forecast-status').textContent,/读取/);
state.driver='a';const visual=candidateVisual({stops:[{after_lap:12,compound:'HARD'}],outcomes:[{scenario:'dry',finish_order:['b','a']}]},{model_scope:{modeled_driver_count:2}});
assert.match(visual.children[0].children[0].textContent,/L12 后 → HARD/);
assert.equal(visual.children[1].children[1].children[1].textContent,'P2 / 2');
state.report={};state.job='old';state.busy=false;invalidate();assert.equal(state.report,null);assert.equal(state.job,null);assert.equal(ids.get('export').disabled,true);
assert.ok(!source.slice(source.lastIndexOf('(async()=>')).includes('/api/reveal'),'Startup must not reveal outcomes');
assert.equal(context.test.lapTime(98.614),'1:38.614');
assert.equal(context.test.lapTime(59.9999),'1:00.000');
assert.equal(context.test.lapTime(60),'1:00.000');
assert.equal(context.test.lapTime(null),null);
assert.equal(context.test.lapTime(NaN),null);
assert.equal(context.test.lapTime(-1),null);
// Numeric fields reject missing/nonfinite values and enforce their model bounds.
const {checkedNumber,bindNumber,validateAndSyncNumbers}=context.test;
const numericInput=value=>{const e=new Element('input');e.value=String(value);return e;};
for(const bad of ['', 'abc', Infinity, -1])assert.throws(()=>checkedNumber(numericInput(bad),'进站损失',{min:0}));
assert.equal(checkedNumber(numericInput(18.5),'进站损失',{min:0}),18.5);
assert.equal(checkedNumber(numericInput(0),'进站损失',{min:0}),0);
assert.throws(()=>checkedNumber(numericInput(0),'基础圈时',{min:0.001}));
assert.equal(checkedNumber(numericInput(0.001),'基础圈时',{min:0.001}),0.001);
for(const [label,rules,bad] of [['胎龄',{min:0,integer:true},0.5],['目标名次',{min:1,max:5,integer:true},6],['目标名次',{min:1,max:5,integer:true},0],['模拟结束圈数',{min:8,integer:true},7],['进站圈',{min:8,max:13,integer:true},14],['假设延迟',{min:0},-1]])assert.throws(()=>checkedNumber(numericInput(bad),label,rules));
assert.equal(checkedNumber(numericInput(13),'进站圈',{min:8,max:()=>13,integer:true}),13);
// The exploration API accepts exactly 1..30 future laps, not a finished horizon.
const bounds=context.test.horizonRules(8);
for(const end of [0,7,8,39,8.5])assert.throws(()=>checkedNumber(numericInput(end),'模拟结束圈数（已完成 8 圈，需再模拟 1–30 圈）',bounds));
for(const end of [9,38])assert.equal(checkedNumber(numericInput(end),'模拟结束圈数',bounds),end);
assert.equal(context.test.horizonRules(12).min,13);
assert.equal(context.test.horizonRules(12).max,42);
const horizonPlan={state:{completed_laps:8,total_laps:9},candidates:{pit_laps:[8,10,12]},scenarios:[{name:'VSC',events:[{lap:11},{lap:13}]}],opponents:{rival:{kind:'fixed',stops:[{after_lap:10}]}}};
const beforeValidation=JSON.stringify(horizonPlan);
assert.throws(()=>context.test.validatePlanningHorizon(horizonPlan),/候选进站圈 10、12.*[\s\S]*事件圈 11、13.*[\s\S]*rival/);
assert.equal(JSON.stringify(horizonPlan),beforeValidation,'Validation must not discard plans');
horizonPlan.state.total_laps=14;context.test.validatePlanningHorizon(horizonPlan);
horizonPlan.state.total_laps=9;horizonPlan.candidates.pit_laps=[8];horizonPlan.scenarios=[];horizonPlan.opponents={};context.test.validatePlanningHorizon(horizonPlan);
horizonPlan.opponents={rival:{kind:'reactive',window_start:8,window_end:13}};assert.throws(()=>context.test.validatePlanningHorizon(horizonPlan),/响应窗口/);
const wetPlan={state:{weather:'WET'},physics:{wet_penalties:{}},tyres:{SOFT:{},HARD:{}},scenarios:[]};
assert.throws(()=>context.test.validateWeatherAssumptions(wetPlan),/湿地圈时损失/);
assert.deepEqual(wetPlan.physics.wet_penalties,{});
wetPlan.physics.wet_penalties={SOFT:0,HARD:5};context.test.validateWeatherAssumptions(wetPlan);
wetPlan.physics.wet_penalties.HARD=-1;assert.throws(()=>context.test.validateWeatherAssumptions(wetPlan),/HARD/);
wetPlan.state.weather='DRY';context.test.validateWeatherAssumptions(wetPlan);
wetPlan.scenarios=[{events:[{weather:'WET'}]}];assert.throws(()=>context.test.validateWeatherAssumptions(wetPlan),/HARD/);
// A routine submit must preserve advanced opponent plans and custom thresholds.
const multiStop={opponents:{rival:{kind:'fixed',stops:[{after_lap:8,compound:'HARD'},{after_lap:10,compound:'SOFT'}]}}};
let policyEdits=0;context.test.syncOpponentLap(multiStop,'rival','fixed',8,()=>policyEdits++);assert.equal(policyEdits,0);assert.equal(multiStop.opponents.rival.stops.length,2);
context.test.syncOpponentLap(multiStop,'rival','fixed',9,()=>policyEdits++);assert.equal(policyEdits,1);
const reactive={opponents:{rival:{kind:'reactive',mode:'overcut',planned_lap:9,response_gap:7,overcut_laps:2}}};
context.test.syncOpponentLap(reactive,'rival','overcut',9,()=>policyEdits++);assert.equal(policyEdits,1);assert.equal(reactive.opponents.rival.response_gap,7);
const malformed=numericInput('1');malformed.validity={badInput:true};assert.throws(()=>checkedNumber(malformed,'数字'));
// Validate the whole form before mutating any model values; sync current DOM even
// when a programmatic fill did not fire change. Disabled stay-out laps are ignored.
vm.runInContext('updateScope=()=>{};',context);
state.numericBindings=[];state.assumptions={pitLoss:22};const pit=numericInput(-1),inactive=numericInput(-50);inactive.disabled=true;
bindNumber(pit,'进站损失',{min:0},v=>state.assumptions.pitLoss=v);bindNumber(inactive,'不进站圈',{min:0},()=>{throw Error('disabled field applied');});
assert.throws(()=>validateAndSyncNumbers());assert.equal(state.assumptions.pitLoss,22);
pit.value='18.5';validateAndSyncNumbers();assert.equal(state.assumptions.pitLoss,18.5);assert.equal(pit['aria-invalid'],'false');
state.loadingCase=false;state.frozen={};state.busy=false;state.report={old:true};state.job='old';pit.value='-1';ids.get('ack').checked=true;
await context.test.compare();assert.equal(state.report,null);assert.equal(ids.get('export').disabled,true);assert.match(ids.get('global-error').textContent,/进站损失.*不能小于 0/);
state.numericBindings=[];
// Reproduce an interrupted case load with deferred network responses. Only the
// display-only helpers are stubbed; loadCase/loadDriver/reveal are production code.
vm.runInContext('renderFacts=()=>{}; formFromAssumptions=()=>{}; refreshHorizon=()=>{};',context);
const deferred=()=>{let resolve,reject;const promise=new Promise((a,b)=>{resolve=a;reject=b;});return {promise,resolve,reject};};
let pending={},requests=[];
context.stubApi=(url)=>{requests.push(url);if(url.startsWith('/api/assumptions'))return Promise.resolve({case:state.case});pending[url]=deferred();return pending[url].promise;};
vm.runInContext('api=(url)=>stubApi(url);',context);
state.frozen={old:true};state.driver='a';state.reveal={old:true};state.assumptions={old:true};state.report=null;state.job=null;
ids.get('cutoff').value='new';const loading=context.test.loadCase();
assert.equal(state.frozen,null);assert.equal(state.reveal,null);assert.equal(ids.get('assumptions').inert,true);assert.equal(ids.get('ack').checked,false);
ids.get('driver').value='b';await context.test.loadDriver();
assert.equal(requests.filter(x=>x.startsWith('/api/assumptions')).length,0,'No assumptions request may race the case load');
const decision=id=>({frozen:{id,state:{cars:[{id:'a',name:'A',driver_number:1}]}},prefix_quality:{},workbench_version:'test'});
pending['/api/decision?case=new'].resolve(decision('new'));pending['/api/forecast?case=new'].resolve({id:'new'});await loading;
assert.equal(state.frozen.id,'new');assert.equal(state.assumptions.case,'new');assert.equal(state.loadingCase,false);
// A late response from an older snapshot must never replace the newer one.
ids.get('cutoff').value='older';const older=context.test.loadCase();ids.get('cutoff').value='latest';const latest=context.test.loadCase();
pending['/api/decision?case=latest'].resolve(decision('latest'));pending['/api/forecast?case=latest'].resolve({id:'latest'});await latest;
pending['/api/decision?case=older'].resolve(decision('older'));pending['/api/forecast?case=older'].resolve({id:'older'});await older;
assert.equal(state.frozen.id,'latest');assert.equal(state.assumptions.case,'latest');
// An old reveal response must not re-enable reveal during a new case load.
const revealing=context.test.reveal();ids.get('cutoff').value='failed';const failing=context.test.loadCase();
pending['/api/reveal'].resolve({});await revealing;assert.equal(ids.get('reveal').disabled,true);
pending['/api/decision?case=failed'].reject(Error('offline'));pending['/api/forecast?case=failed'].resolve({});await failing;
assert.equal(state.loadingCase,true);assert.equal(state.frozen,null);assert.equal(ids.get('driver').disabled,true);await context.test.loadDriver();assert.equal(state.assumptions,null);
// Editing hypotheses does not change the selected historical observation.
state.loadingCase=false;state.frozen={};state.driver='a';const sameSelectionReveal=context.test.reveal();invalidate();
pending['/api/reveal'].resolve({evaluation:{lap:{errors:null,reason:'target_missing'},gap:{errors:null,reason:'target_missing'}}});await sameSelectionReveal;
assert.ok(state.reveal,'A same-selection reveal must survive assumption edits');
console.log('PASS: deferred case/driver interleaving, out-of-order snapshots, stale reveal, failed-load lockout.');
console.log('PASS: DOM IDs, forecast/null rendering, driver switch, error/loading reset, model rank/stop rendering, stale-result invalidation, no startup reveal. Browser layout not tested.');
