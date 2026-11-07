'use strict';
const $ = id => document.getElementById(id);
const state = {catalog:null, numericBindings:[], loadingCase:false, forecast:null, frozen:null, quality:null, assumptions:null, case:null, driver:null, epoch:0, job:null, report:null, reveal:null, busy:false, jsonDirty:false, selectionRequest:0, horizonReport:null, horizonEnvelope:null, horizonRequestId:0};
const reasonNames = {not_applicable_post_event_proxy:'赛后不适用（事后结束代理）',target_data_missing:'目标数据缺失',prefix_data_missing:'前缀数据不足',publication_boundary_rejection:'目标已开始，发布时间边界拒绝',candidate_abstention:'候选主动弃权',scored:'已评分',missing_or_stale_lap_evidence:'完成圈缺失或陈旧',segment_warmup_requires_three_completed_laps:'转换后不足三圈',unstable_segment_range_exceeds_four_seconds:'赛段波动过大',control_active_or_clearance_unconfirmed:'控制状态尚未确认解除',stale_eligible_segment:'合格样本陈旧',UNKNOWN:'未知',unknown:'未知',inferred:'推断',observed:'观测',stale_observation:'观测已陈旧',insufficient_prefix_laps:'合格历史圈不足',insufficient_or_stale_numeric_interval_prefix:'间距报告不足或已陈旧',target_missing_no_retirement_inference:'目标缺失；不据此推断退赛',target_already_started:'目标已在截止点前开始，不重选',target_duration_unknown:'目标圈时未知',stale_interval_outcome:'结果间距报告已陈旧',invalid_or_null_interval_outcome:'结果间距不是有效数值',no_new_interval_outcome:'没有新间距报告'};
const human = text => reasonNames[text] || text || '—';
const fmt = (value, digits=3) => typeof value === 'number' ? value.toFixed(digits) : value == null ? '未知' : String(value);
const node = (tag, text, cls) => {const e=document.createElement(tag);if(text!=null)e.textContent=text;if(cls)e.className=cls;return e;};
const empty = id => $(id).replaceChildren();
function error(message){$('global-error').textContent=message;$('global-error').classList.remove('hidden');}
function clearError(){$('global-error').classList.add('hidden');$('simulation-error').classList.add('hidden');}
async function api(path, document, raw=false){
 const controller=new AbortController(), timer=setTimeout(()=>controller.abort(),15000);
 try{
  const options={signal:controller.signal};
  if(document){options.method='POST';options.headers={'Content-Type':'application/json','X-Workbench-Token':state.catalog.token};options.body=JSON.stringify(document);}
  const response=await fetch(path,options);let result;
  let body;try{body=await response.text();result=JSON.parse(body);}catch{throw Error(`服务返回非 JSON（HTTP ${response.status}），请检查本地终端。`);}
  if(!response.ok)throw Error(result.error || `HTTP ${response.status}`);
  return raw?body:result;
 }catch(e){if(e.name==='AbortError')throw Error('请求超过 15 秒。请检查本地服务；模拟任务可稍后重试或取消。');throw e;}
 finally{clearTimeout(timer);}
}
function invalidate(message='假设或选择已改变，请重新运行比较。'){
 if(state.busy&&state.job)api('/api/cancel',{job_id:state.job}).catch(()=>{});
 state.epoch++;state.report=null;state.job=null;state.busy=false;
 $('comparison-content').classList.add('hidden');$('empty-comparison').classList.remove('hidden');$('empty-comparison').textContent=message;
 $('export').disabled=true;$('cancel').classList.add('hidden');$('job-status').textContent='';$('compare').setAttribute('aria-busy','false');
 $('compare').disabled=!$('ack').checked || !state.assumptions;
}
function setOptions(id, values, current){const select=$(id);select.replaceChildren();for(const [value,label] of values){const option=node('option',label);option.value=value;select.append(option);}if(current)select.value=current;}
function syncJson(){state.jsonDirty=false;$('assumption-json').value=JSON.stringify(state.assumptions,null,2);}
function updateScope(){
 const p=state.assumptions.planning,n=p.state.cars.length,total=state.frozen.state.cars.length;
 $('scope-note').textContent=`${n} / ${total} 车 · 第 ${p.state.completed_laps??'未知'} 圈后至第 ${p.state.total_laps??'未知'} 圈 · 所选车辆内排名。轮胎库存：${state.assumptions.inventory_policy.kind==='finite'?'按填写值':'未知，按不限库存模拟'}。`;
 $('scenario-overview').textContent=`${p.state.track_status} · ${p.state.weather} · ${p.state.track_temp} ℃。情景：`+p.scenarios.map(x=>`${x.name}（权重 ${x.weight}）`).join('、');
}
function checkedNumber(input,label,{min=0,max=Infinity,integer=false}={}){
 const raw=String(input.value).trim(),value=Number(raw);
 const lower=typeof min==='function'?min():min,upper=typeof max==='function'?max():max;
 let message='';
 if(!raw||!Number.isFinite(value)||input.validity?.badInput)message=`${label}：请填写有效数字。`;
 else if(integer&&!Number.isInteger(value))message=`${label}：请填写整数。`;
 else if(value<lower)message=`${label}：不能小于 ${lower}。`;
 else if(value>upper)message=`${label}：不能大于 ${upper}。`;
 input.setAttribute('aria-invalid',message?'true':'false');input.setCustomValidity?.(message);
 if(message){input.focus?.();input.reportValidity?.();throw Error(message);}
 return value;
}
function horizonRules(completed){return {min:completed+1,max:completed+30,integer:true};}
function bindNumber(input,label,rules,apply){
 input.required=true;input.setAttribute('aria-errormessage','global-error');
 state.numericBindings.push({input,label,rules,apply});
 input.oninput=()=>{input.setCustomValidity?.('');input.setAttribute('aria-invalid','false');invalidate('参数已修改，请检查后重新运行。');};
}
function validateWeatherAssumptions(planning){
 const wet=planning.state.weather==='WET'||(planning.scenarios||[]).some(s=>(s.events||[]).some(e=>e.weather==='WET'));
 if(!wet)return;
 const penalties=planning.physics.wet_penalties||{};
 const missing=Object.keys(planning.tyres).filter(c=>typeof penalties[c]!=='number'||!Number.isFinite(penalties[c])||penalties[c]<0);
 if(missing.length)throw Error(`请在 planning.physics.wet_penalties 中补充 ${missing.join('、')} 的湿地圈时损失（非负秒数），再应用 JSON。`);
}
function validatePlanningHorizon(planning){
 const start=planning.state.completed_laps,end=planning.state.total_laps,conflicts=[];
 const outside=(planning.candidates.pit_laps||[]).filter(lap=>!Number.isInteger(lap)||lap<start||lap>=end);
 if(outside.length)conflicts.push(`候选进站圈 ${outside.join('、')} 超出允许范围 ${start}–${end-1}（planning.candidates.pit_laps）`);
 for(const scenario of planning.scenarios||[]){
  const laps=(scenario.events||[]).map(event=>event.lap).filter(lap=>!Number.isInteger(lap)||lap<=start||lap>end);
  if(laps.length)conflicts.push(`情景“${scenario.name}”的事件圈 ${laps.join('、')} 超出模拟范围 ${start+1}–${end}（planning.scenarios）`);
 }
 for(const [driver,policy] of Object.entries(planning.opponents||{})){
  if(policy.kind==='fixed'){
   const laps=(policy.stops||[]).map(stop=>stop.after_lap).filter(lap=>!Number.isInteger(lap)||lap<start||lap>=end);
   if(laps.length)conflicts.push(`${driver} 的进站圈 ${laps.join('、')} 超出允许范围 ${start}–${end-1}（planning.opponents）`);
  }else if(policy.kind==='reactive'&&!(0<=policy.window_start&&policy.window_start<=policy.window_end&&policy.window_end<end))conflicts.push(`${driver} 的进站响应窗口超出模拟范围（planning.opponents）`);
 }
 if(conflicts.length)throw Error(`模拟结束圈数与现有计划不匹配：
${conflicts.join('；\n')}。
请增加结束圈数，或调整高级 JSON 中的计划后应用。`);
}
function validateAndSyncNumbers(){
 const values=state.numericBindings.filter(b=>!b.input.disabled).map(b=>[b,checkedNumber(b.input,b.label,b.rules)]);
 for(const [binding,value] of values)binding.apply(value);
 syncJson();updateScope();
}
function numeric(input){return input.value.trim()===''?null:Number(input.value);}
function syncOpponentLap(planning,driver,mode,value,change){
 const current=planning.opponents[driver];
 if(value!==(current.planned_lap??current.stops?.[0]?.after_lap)||mode!==policyMode(current))change();
}
function policyMode(policy){return policy.kind==='reactive'?policy.mode:policy.stops.length?'fixed':'stay';}
function formFromAssumptions(){
 const a=state.assumptions,p=a.planning;state.numericBindings=[];
 if(!p?.state?.cars || !p.physics)throw Error('假设 JSON 缺少 planning.state.cars 或 planning.physics。');
 $('pit-loss').value=p.physics.pit_loss;$('total-laps').value=p.state.total_laps??'';$('track-status').value=p.state.track_status;$('weather').value=p.state.weather;
 $('target-rank').value=p.risk_top_k;$('target-rank').max=p.state.cars.length;$('risk-mode').value=a.selection_preference?.mode||'mean_position';
 bindNumber($('pit-loss'),'进站损失',{min:0},v=>p.physics.pit_loss=v);
 $('total-laps').min=p.state.completed_laps+1;$('total-laps').max=p.state.completed_laps+30;
 bindNumber($('total-laps'),`模拟结束圈数（已完成 ${p.state.completed_laps} 圈，需再模拟 1–30 圈）`,horizonRules(p.state.completed_laps),v=>p.state.total_laps=v);
 bindNumber($('target-rank'),'目标名次',{min:1,max:p.state.cars.length,integer:true},v=>p.risk_top_k=v);
 empty('field-cars');const ids=new Set(p.state.cars.map(c=>c.driver));
 for(const car of state.frozen.state.cars){const label=node('label'),input=node('input');input.type='checkbox';input.value=car.id;input.checked=ids.has(car.id);input.disabled=car.id===state.driver;label.append(input,node('span',`${car.id} · ${car.team} · 间距 ${fmt(car.gap_seconds.value)} s`));$('field-cars').append(label);}
 empty('assumed-cars');
 p.state.cars.forEach((car,index)=>{const tr=node('tr');const name=node('td',car.driver+(car.driver===state.driver?' · 当前车手':''));name.append(node('small',car.team));tr.append(name);
  for(const key of ['base_lap_time','gap_seconds','tyre_age','compound']){const td=node('td');let input;
   if(key==='compound'){input=node('select');for(const value of [...new Set(['',...Object.keys(p.tyres),car.compound].filter(x=>x!==null))]){const option=node('option',value||'未知 / 须填写');option.value=value;input.append(option);}input.value=car[key]??'';}
   else{input=node('input');input.type='number';input.step=key==='tyre_age'?'1':'any';input.min=key==='base_lap_time'?'0.001':'0';input.value=car[key]??'';input.placeholder='未知 / 须填写';}
   input.setAttribute('aria-label',`${car.driver} ${key}`);input.dataset.car=String(index);input.dataset.field=key;
   if(key!=='compound')bindNumber(input,`${car.driver} ${{base_lap_time:'基础圈时',gap_seconds:'间距',tyre_age:'胎龄'}[key]}`,{min:key==='base_lap_time'?0.001:0,integer:key==='tyre_age'},v=>car[key]=v);
   input.addEventListener('change',()=>{try{if(!state.assumptions||state.loadingCase)return;if(state.jsonDirty)throw Error('请先应用完整 JSON 中的修改。');car[key]=key==='compound'?(input.value||null):numeric(input);invalidate();syncJson();}catch(e){error(e.message);}});
   td.append(input);tr.append(td);
  }
  const td=node('td');if(car.driver===state.driver){td.textContent='由候选方案决定；始终比较留场';}else{
   const policy=p.opponents[car.driver],mode=node('select'),lap=node('input');lap.type='number';lap.step='1';lap.value=policy.planned_lap??policy.stops?.[0]?.after_lap??(p.state.completed_laps+3);
   for(const [value,label] of [['stay','留场'],['fixed','固定进站'],['cover_undercut','回应 undercut'],['overcut','延后 overcut']]){const option=node('option',label);option.value=value;mode.append(option);}mode.value=policyMode(policy);mode.setAttribute('aria-label',`${car.driver} response`);lap.setAttribute('aria-label',`${car.driver} planned_lap`);
   const change=()=>{lap.disabled=mode.value==='stay';try{if(!state.assumptions||state.loadingCase)return;if(state.jsonDirty)throw Error('请先应用完整 JSON 中的修改。');const at=numeric(lap),compound=policy.compound||policy.stops?.[0]?.compound||p.candidates.compounds[0];p.opponents[car.driver]=mode.value==='stay'?{kind:'fixed',stops:[]}:mode.value==='fixed'?{kind:'fixed',stops:[{after_lap:at,compound}]}:{kind:'reactive',rival:state.driver,compound,planned_lap:at,window_start:p.state.completed_laps,window_end:p.state.total_laps-1,mode:mode.value,response_gap:12,overcut_laps:1};invalidate();syncJson();}catch(e){error(e.message);}};
   lap.disabled=mode.value==='stay';lap.min=p.state.completed_laps;
   bindNumber(lap,`${car.driver} 计划进站圈`,{min:p.state.completed_laps,max:()=>Number($('total-laps').value)-1,integer:true},v=>syncOpponentLap(p,car.driver,mode.value,v,change));
   mode.addEventListener('change',change);lap.addEventListener('change',change);td.append(mode,lap,node('small','响应阈值默认 12 s；新胎/窗口详见 JSON。'));
  }tr.append(td);$('assumed-cars').append(tr);
 });updateScope();syncJson();$('ack').disabled=false;$('compare').disabled=!$('ack').checked;
}
function renderQuality(){
 const q=state.quality;if(!q)return;const d=q.drivers[state.driver],c=d.candidate;
 const reasons={missing_or_stale_lap_evidence:'完成圈缺失或陈旧',control_active_or_clearance_unconfirmed:'SC/VSC/红旗尚未确认解除',segment_warmup_requires_three_completed_laps:'转换后不足三圈',stale_eligible_segment:'合格赛段样本已陈旧',unstable_segment_range_exceeds_four_seconds:'最近三圈极差 > 4 s',no_fixed_target_lap:'没有固定目标圈'};
 $('segment-forecast').textContent=c.value_seconds==null?'暂不预测':fmt(c.value_seconds)+' s';
 $('segment-note').textContent=c.reason?(reasons[c.reason]||c.reason):`样本圈 ${c.sample_laps.join('、')} · 极差 ${fmt(c.observed_range_seconds)} s · 目标第 ${c.target_lap} 圈`;
 $('quality-clock').textContent=`截止 ${q.cutoff} · 载入 ${new Date().toISOString()} · UTC`;
 empty('quality-table');for(const [name,v] of [['快照最新事件',q.snapshot],['所选车手完成圈',d.lap],['所选车手间距报告',d.gap],['天气报告',q.weather],['明确的全赛道状态',q.race_control]]){
  const tr=node('tr'),status={missing:'缺失',stale:'过期',event_time_only:'事件时间 · 发布未核验'}[v.reliability];tr.append(node('td',name),node('td',`${fmt(v.age_seconds_at_cutoff,1)} s / 上限 ${v.max_age_seconds} s`),node('td',status+(name.includes('间距')&&!v.numeric_usable?'；非可用数值间距':'')+(name.includes('赛道')?`；当前可用状态 ${human(v.usable_state)}`:'')),node('td',`${v.clock_source} / ${v.event_at||'未知'}`));$('quality-table').append(tr);
 }
 $('quality-limits').textContent=`事件时间 + 假设延迟 3 s。赛段边界：${c.segment_boundaries.map(x=>x.kind+' @ '+x.event_at).join('；')||'未识别'}。路面干湿未知。`+(q.context_sha256?'':'天气历史缺失。');
}
function renderFacts(){
 renderQuality();renderForecast();
 const frozen=state.frozen,car=frozen.state.cars.find(c=>c.id===state.driver),forecast=frozen.observation_forecasts.find(c=>c.driver_id===state.driver);
 empty('facts');
 for(const [key,label] of [['completed_laps','已完成圈数'],['last_started_lap','已开始圈'],['position','最后已报告名次'],['gap_seconds','间距报告 / 秒'],['compound','配方'],['estimated_completed_tyre_age','估计已完成胎龄'],['activity','活动状态'],['tyre_inventory','轮胎库存']]){
  const field=car[key] || {status:'unknown'},tr=node('tr');tr.append(node('td',label),node('td',fmt(field.value,2)));const status=node('td');status.append(node('span',human(field.status),`pill ${field.status==='unknown'?'unknown':'fact'}`));tr.append(status);
  const detail=node('td',field.event_at || '无可验证事件时间');detail.append(node('small',[field.source,human(field.reason),field.age_seconds==null?'':`事件距截止点 ${fmt(field.age_seconds,1)} 秒`].filter(x=>x&&x!=='—').join(' · ')));tr.append(detail);$('facts').append(tr);
 }
 for(const [key,label] of [['track_status','全赛道状态'],['surface_condition','路面状态']]){const f=frozen.state[key],tr=node('tr');tr.append(node('td',label),node('td',fmt(f.value)),node('td',human(f.status)),node('td',f.reason));$('facts').append(tr);}
 for(const kind of ['lap','gap']){const pred=forecast.default_prediction[kind];$(kind+'-forecast').textContent=pred.value_seconds==null?'暂不可预测':fmt(pred.value_seconds)+' s';$(kind+'-note').textContent=`${pred.method} · ${pred.reason?human(pred.reason):kind==='lap'?`目标第 ${forecast.lap.target_lap} 圈 · 样本距截止 ${fmt(forecast.lap.context?.last_eligible_age_seconds,1)} s`:`报告时域 ${forecast.gap.horizon}`}`;}
 const stale=state.quality?.drivers[state.driver].lap.reliability==='stale';$('lap-forecast').classList.toggle('stale-reference',stale);if(stale)$('lap-note').textContent+=' · 样本已过期';
 $('frozen-meta').textContent=JSON.stringify({decision_sha256:frozen.decision_sha256,cutoff:frozen.cutoff,partition:frozen.partition,code_version:frozen.code_version,config:frozen.config,data_version:frozen.data_version,fit_cutoff:frozen.fit_cutoff},null,2);
 $('snapshot-note').textContent=`${frozen.cutoff} · ${frozen.state.cars.length} 车 · ${frozen.partition==='holdout'?'原留出样本（已查看）':'开发样本'}`;
}

function lapTime(seconds){
 if(typeof seconds!=='number'||!Number.isFinite(seconds)||seconds<0)return null;
 const milliseconds=Math.round(seconds*1000),minutes=Math.floor(milliseconds/60000);
 return `${minutes}:${(Math.floor(milliseconds/1000)%60).toString().padStart(2,'0')}.${(milliseconds%1000).toString().padStart(3,'0')}`;
}
function renderDriverSummary(driver=null,errorMessage=null){
 $('readiness-driver').textContent=driver?(driver.name||driver.driver_id):'尚未载入';
 $('readiness-team').textContent=driver?.team||'';
 $('readiness-target').textContent=driver?.target_lap==null?'圈时估计 · 目标圈未知':`第 ${driver.target_lap} 圈 · 估计圈时`;
 const time=lapTime(driver?.predicted_lap_seconds);
 $('readiness-time').textContent=driver?(time||'暂不预测'):'—';
 $('readiness-time').classList.toggle('is-unavailable',!time);
 $('readiness-time').setAttribute('aria-label',time?`估计圈时 ${driver.predicted_lap_seconds.toFixed(3)} 秒`:(driver?'暂不预测':'尚无估计值'));
 $('readiness-detail').textContent=errorMessage?'预测数据读取失败，请重新选择时间后重试。':driver?(time?'历史估计 · 分:秒':(driver.reason_zh||'数据不足，暂时无法估计圈时。')):'正在读取所选车手的数据…';
}
function renderForecast(){
 const report=state.forecast;empty('forecast-drivers');
 $('forecast-evidence').textContent='';$('forecast-limitations').textContent='';
 renderDriverSummary(null,report?.error);
 if(!report||report.error){$('forecast-count').textContent='不可用';$('forecast-status').textContent=report?.error?'预测数据读取失败：'+report.error:'正在读取历史数据…';return;}
 $('forecast-count').textContent=`${report.summary.available} 有估计值 / ${report.summary.abstained} 暂不预测`;
 $('forecast-status').textContent=`截止 ${report.cutoff} · 历史回放`;
 $('forecast-limitations').textContent=report.limitations.join('；');$('forecast-evidence').textContent=JSON.stringify(report,null,2);
 for(const d of report.drivers){
  const tr=node('tr',null,d.driver_id===state.driver?'selected-row':''),identity=node('td'),button=node('button',d.name||d.driver_id,'driver-link');button.type='button';button.setAttribute('aria-label','查看 '+(d.name||d.driver_id)+' 的数据');button.setAttribute('aria-pressed',String(d.driver_id===state.driver));button.addEventListener('click',()=>{$('driver').value=d.driver_id;loadDriver();});identity.append(button,node('small',d.team||'车队未知'));tr.append(identity,node('td',d.target_lap==null?'未知':`第 ${d.target_lap} 圈`));
  const value=node('td',d.predicted_lap_seconds==null?'暂不预测':fmt(d.predicted_lap_seconds)+' s','forecast-value');tr.append(value,node('td',d.lap_age_seconds==null?'未知':fmt(d.lap_age_seconds,1)+' s'));
  const status=node('td',d.reason_zh||(d.predicted_lap_seconds==null?'数据不足':'可估计'),'forecast-status');status.append(node('small',d.predicted_lap_seconds==null?'':`样本圈 ${d.sample_laps.join('、')} · 极差 ${fmt(d.observed_range_seconds)} s`));tr.append(status);$('forecast-drivers').append(tr);
  if(d.driver_id===state.driver)renderDriverSummary(d);
 }
}
function candidateVisual(candidate,report){
 const wrap=node('div'),plan=node('div',null,'pit-plan');
 if(!candidate.stops?.length)plan.append(node('span','本段不进站','pit-stop'));
 for(const stop of candidate.stops||[])plan.append(node('span',`L${stop.after_lap} 后 → ${stop.compound}`,'pit-stop'));
 wrap.append(plan);const ranks=node('div',null,'scenario-ranks');ranks.append(node('small','各情景模拟名次'));
 for(const outcome of candidate.outcomes||[]){const row=node('div',null,'scenario-rank'),index=outcome.finish_order.indexOf(state.driver);row.append(node('span',outcome.scenario),node('strong',index<0?'未知':`P${index+1} / ${report.model_scope.modeled_driver_count}`));ranks.append(row);}wrap.append(ranks);return wrap;
}

async function loadDriver(customDrivers=null){
 if(state.loadingCase||!state.frozen)return;
 const request=++state.selectionRequest,caseId=state.case,driver=$('driver').value;
 state.jsonDirty=false;$('assumption-json').value='';$('assumptions').inert=true;state.driver=driver;invalidate('选择已改变，正在读取模拟参数。');state.assumptions=null;$('compare').disabled=true;$('ack').checked=false;$('ack').disabled=true;empty('assumed-cars');
 state.horizonEnvelope=null;$('horizon-file').value='';$('horizon-import-label').textContent='历史归档 · 接收时间未知';refreshHorizon();
 state.reveal=null;$('reveal-result').textContent='尚未查看实测结果。';$('reveal').disabled=false;renderFacts();
 try{const field=Array.isArray(customDrivers)?'custom':$('field-mode').value;const selected=Array.isArray(customDrivers)?customDrivers:[driver];const a=await api(`/api/assumptions?case=${encodeURIComponent(caseId)}&driver=${encodeURIComponent(driver)}&field=${field}&drivers=${encodeURIComponent(selected.join(','))}`);if(request!==state.selectionRequest)return;state.assumptions=a;formFromAssumptions();$('assumptions').inert=false;$('empty-comparison').textContent='确认参数后即可模拟。';}catch(e){if(request!==state.selectionRequest)return;error(e.message);}
}
function resetForCaseLoad(){
 state.loadingCase=true;state.frozen=null;state.quality=null;state.driver=null;state.reveal=null;state.jsonDirty=false;state.horizonEnvelope=null;
 for(const id of ['observed','horizon-panel','assumptions','outcomes'])$(id).inert=true;
 for(const id of ['facts','quality-table','assumed-cars','field-cars'])empty(id);
 for(const id of ['lap-forecast','gap-forecast','segment-forecast','horizon-target'])$(id).textContent='等待当前快照';
 for(const id of ['lap-note','gap-note','segment-note','quality-clock','quality-limits','frozen-meta','horizon-note','horizon-clock','horizon-evidence','scope-note','scenario-overview'])$(id).textContent='';
 $('assumption-json').value='';$('ack').checked=false;$('ack').disabled=true;$('horizon-file').value='';
 $('snapshot-note').textContent='正在载入快照…';$('horizon-status').textContent='等待当前快照';$('reveal-result').textContent='尚未查看实测结果。';
}

async function loadCase(){
 clearError();const caseId=$('cutoff').value,request=++state.selectionRequest;invalidate('正在载入冻结记录。');state.case=caseId;resetForCaseLoad();$('driver').disabled=true;$('reveal').disabled=true;state.assumptions=null;state.horizonReport=null;state.forecast=null;renderForecast();++state.horizonRequestId;$('export-horizon').disabled=true;$('compare').disabled=true;
 try{const [result,forecast]=await Promise.all([api('/api/decision?case='+encodeURIComponent(caseId)),api('/api/forecast?case='+encodeURIComponent(caseId)).catch(e=>({error:e.message}))]);if(request!==state.selectionRequest)return;state.forecast=forecast;state.loadingCase=false;for(const id of ['observed','horizon-panel','outcomes'])$(id).inert=false;$('driver').disabled=false;state.frozen=result.frozen;state.quality=result.prefix_quality;$('version').textContent='代码版本 '+result.workbench_version.slice(0,12);const options=state.frozen.state.cars.map(c=>[c.id,`${c.name} · ${c.driver_number}`]);setOptions('driver',options,options.some(x=>x[0]==='leclerc')?'leclerc':options[0][0]);await loadDriver();}catch(e){if(request!==state.selectionRequest)return;error(e.message);}
}
async function loadRace(){const race=state.catalog.races.find(r=>r.id===$('race').value);const preferred=race.cases.find(c=>c.cutoff.includes('15:18:00'));setOptions('cutoff',race.cases.map(c=>[c.id,c.cutoff.replace('T',' ').replace('+00:00',' UTC').replace('Z',' UTC')]),(preferred||race.cases[0]).id);await loadCase();}
function parseJson(){if(state.jsonDirty){const a=JSON.parse($('assumption-json').value);if(a.planning?.ego!==state.driver)throw Error('JSON ego 必须与当前所选车手一致。');state.assumptions=a;formFromAssumptions();}}
function detailForCandidate(candidate){
 const wrap=node('div');for(const detail of candidate.simulation_details){const box=node('div',null,'scenario');box.append(node('strong',detail.scenario));const proxy=detail.first_post_stop_lap_proxy;const outcome=candidate.outcomes.find(x=>x.scenario===detail.scenario);if(outcome){box.append(node('p','模拟顺序：'+outcome.finish_order.join(' → '),'compact'));const actions=outcome.trace.filter(x=>Object.keys(x.pit_actions).length).map(x=>'第 '+x.lap+' 圈 '+JSON.stringify(x.pit_actions));box.append(node('p','模拟进站：'+(actions.join('；')||'全部留场'),'compact'));}
  box.append(node('p',proxy?`进站后首圈估计：第 ${proxy.lap} 圈 / 模型 P${proxy.position}；前 ${proxy.ahead||'无'}，后 ${proxy.behind||'无'}；交通调整 ${fmt(proxy.traffic_adjustment_seconds)} s；排队 ${fmt(proxy.pit_queue_wait_seconds)} s`:'本方案不进站。','compact'));
  for(const [driver,cost] of Object.entries(detail.simulated_teammate_costs)){box.append(node('p',cost?`队友 ${driver}：相对同情景留场，耗时差 ${fmt(cost.elapsed_delta_vs_same_scenario_stay_out_seconds)} s，模型名次差 ${cost.position_delta_vs_same_scenario_stay_out}，排队 ${fmt(cost.simulated_queue_wait_seconds)} s`:`队友 ${driver}：无可行的不进站方案，代价未知。`,'compact'));}wrap.append(box);
 }return wrap;
}
function renderReport(report){
 $('empty-comparison').classList.add('hidden');$('comparison-content').classList.remove('hidden');
 $('result-scope').textContent=`模拟：${report.model_scope.modeled_driver_count} / ${report.model_scope.frozen_driver_count} 车 · 第 ${report.model_horizon.after_lap+1}–${report.model_horizon.through_lap} 圈 · 所选车辆内排名。${report.inventory_feasibility==='configured finite spare stocks only'?'库存按填写值。':'库存未知，按不限库存模拟。'}`;
 empty('candidates');if(!report.top3.length)$('candidates').append(node('p','暂无可行方案，请检查进站次数、胎龄、库存和对手计划。'));
 report.top3.forEach((c,i)=>{const card=node('article',null,'candidate');card.append(node('small',`方案 ${i+1} · 模拟结果`),node('h3',c.label));const rank=node('div',fmt(c.expected_finish_position,2),'rank');rank.append(node('small','模拟平均名次'));card.append(rank,node('p',`最差 P${c.worst_finish_position} · 未达目标权重 ${(100*c.weighted_share_outside_top_k).toFixed(1)}%（非概率）`,'compact'));card.append(candidateVisual(c,report));const details=node('details');details.append(node('summary','进站车流与队友影响'),detailForCandidate(c));card.append(details);$('candidates').append(card);});
 $('stay-out').textContent=report.stay_out.status==='feasible'?`不进站方案：可行 · 模拟平均名次 ${fmt(report.stay_out.candidate.expected_finish_position,2)}`:`不进站方案：不可行 · ${report.stay_out.rejection?.first_failure?.scenario||'未知情景'} / ${report.stay_out.rejection?.first_failure?.reason||'见拒绝详情'}`;
 $('result-conditions').textContent=`目标前 ${report.selection_preference.target_top_k} 名 · ${report.selection_preference.mode==='conservative'?'保守排序':'平均名次优先'}。情景：${report.covered_scenarios.map(x=>x.name+'（权重 '+x.weight+'）').join('、')}。`;
 const t=report.initial_threats;$('threats').textContent=`前车 ${t.ahead||'无'}（${fmt(t.gap_to_ahead_seconds)} s）；后车 ${t.behind||'无'}（${fmt(t.gap_from_behind_seconds)} s）。`;
 empty('sensitivity');$('sensitivity').append(node('p',`首选方案：${report.sensitivity.baseline_winner||'无'}`));for(const c of report.sensitivity.cases){$('sensitivity').append(node('p',`${c.name}（${c.path}: ${c.original_value} → ${c.assumed_value}）：${c.winner_changed?'最优方案改变':'最优方案未变'} → ${c.winner||'无可行方案'}；原方案排序 ${c.baseline_plan_rank_in_variant??'不可行'}；原方案模型名次 ${fmt(c.baseline_plan_expected_position,2)}`,'compact'));}
 empty('overrides');for(const f of report.field_overrides){const tr=node('tr');tr.append(node('td',f.path),node('td',JSON.stringify(f.original)),node('td',JSON.stringify(f.assumed_value)),node('td',`${f.source} / ${f.rationale}`));$('overrides').append(tr);}
 $('rejected').textContent=JSON.stringify(report.rejected_candidates,null,2);
}
async function compare(){
 if(state.loadingCase||!state.frozen||!state.assumptions||state.busy)return;
 clearError();let activeEpoch=null;try{parseJson();validateAndSyncNumbers();validatePlanningHorizon(state.assumptions.planning);validateWeatherAssumptions(state.assumptions.planning);if(!$('ack').checked)throw Error('请先确认人工假设。');
  invalidate('正在模拟当前假设。');const epoch=state.epoch;activeEpoch=epoch;state.busy=true;$('compare').disabled=true;$('compare').setAttribute('aria-busy','true');$('cancel').classList.remove('hidden');$('job-status').textContent='已提交，正在启动后台模拟…';
  const job=await api('/api/explore',{case:state.case,driver:state.driver,assumptions:state.assumptions,acknowledged:true});if(epoch!==state.epoch){await api('/api/cancel',{job_id:job.id});return;}state.job=job.id;
  while(epoch===state.epoch){const result=await api('/api/jobs/'+encodeURIComponent(job.id));if(epoch!==state.epoch)return;$('job-status').textContent=`${result.status==='running'?'后台模拟中':'模拟已结束'} · ${fmt(result.elapsed_seconds,1)} 秒 · 超时上限 ${job.timeout_seconds} 秒`;
   if(result.status!=='running'){state.busy=false;$('compare').disabled=!$('ack').checked;$('compare').setAttribute('aria-busy','false');$('cancel').classList.add('hidden');if(result.status!=='succeeded')throw Error(result.error||'模拟未完成');state.report=result.report;renderReport(result.report);globalThis.F1Navigation?.showResults();$('export').disabled=!state.horizonReport;$('job-status').textContent=`完成 · ${fmt(result.elapsed_seconds,2)} 秒 · ${result.report.budget.rollouts_executed} rollouts`;return;}
   await new Promise(resolve=>setTimeout(resolve,250));
  }
 }catch(e){if(activeEpoch!==null&&activeEpoch!==state.epoch)return;if(activeEpoch===null)invalidate('参数有误，请修正后重新运行。');state.busy=false;$('compare').disabled=!$('ack').checked;$('compare').setAttribute('aria-busy','false');$('cancel').classList.add('hidden');error(e.message);$('simulation-error').textContent=e.message;$('simulation-error').classList.remove('hidden');$('empty-comparison').textContent='此次比较未产生新结果，请修正错误后重试。';}
}
async function reveal(){if(state.loadingCase||!state.frozen||!state.driver)return;clearError();const selection=state.selectionRequest;try{$('reveal').disabled=true;const result=await api('/api/reveal',{case:state.case,driver:state.driver});if(selection!==state.selectionRequest)return;state.reveal=result;empty('reveal-result');$('reveal-result').append(node('p','实测结果'));const grid=node('div',null,'reveal-metric');for(const [kind,title] of [['lap','实际下一完整圈'],['gap','实际固定时域间距报告']]){const r=result.evaluation[kind],box=node('article');box.append(node('span',title));box.append(node('strong',r.errors?fmt(r.actual)+' s':'不可评分'));if(r.errors){const method=r.selected_method;box.append(node('p',`原冻结基线 ${method} 绝对误差：${fmt(r.errors[method])} s`,'compact'));}else box.append(node('p',human(r.reason),'compact'));grid.append(box);}$('reveal-result').append(grid);const f=result.evaluation.freshness_evaluation;if(f){$('reveal-result').append(node('p',`分段圈时估计：${human(f.lap_category)}；${f.candidate_abs_error==null?'无评分 / '+human(f.candidate_reason||f.baseline_reason||'赛后不适用'): '绝对误差 '+fmt(f.candidate_abs_error)+' s；同目标基线 '+fmt(f.baseline_abs_error_same_target)+' s'}。含赛后分类。`));}const details=node('details');details.append(node('summary','查看实际目标和评分证据'));details.append(node('pre',JSON.stringify(result.evaluation,null,2)));$('reveal-result').append(details);}catch(e){if(selection!==state.selectionRequest)return;$('reveal').disabled=false;error(e.message);}}
async function exportRecord(){clearError();const epoch=state.epoch;try{if(!state.assumptions||state.loadingCase)return;if(state.jsonDirty)throw Error('JSON 已修改，请应用并重新运行比较后导出。');if(!state.report)throw Error('请先完成当前假设比较。');if(!state.horizonReport)throw Error('预测条件检查尚未完成，或输入无效。');const record=await api('/api/export',{case:state.case,driver:state.driver,job_id:state.job,assumptions_sha256:state.report.assumptions_sha256,reveal_id:state.reveal?.id,horizon_request:horizonRequest()},true);if(epoch!==state.epoch)throw Error('选择或假设已改变，已丢弃旧导出。');const blob=new Blob([record],{type:'application/json'});const url=URL.createObjectURL(blob),a=node('a');a.href=url;a.download=`f1-decision-${state.driver}-${state.frozen.cutoff.replaceAll(':','-')}.json`;document.body.append(a);a.click();a.remove();setTimeout(()=>URL.revokeObjectURL(url),1000);$('job-status').textContent='决策记录已导出，含版本与证据哈希。';}catch(e){error(e.message);}}
$('race').addEventListener('change',loadRace);$('cutoff').addEventListener('change',loadCase);$('driver').addEventListener('change',()=>loadDriver());
$('field-mode').addEventListener('change',()=>{if($('field-mode').value!=='custom')loadDriver();});
$('apply-field').addEventListener('click',()=>{$('field-mode').value='custom';loadDriver([...$('field-cars').querySelectorAll('input:checked')].map(x=>x.value));});
for(const id of ['target-rank','risk-mode'])$(id).addEventListener('change',()=>{try{if(!state.assumptions||state.loadingCase)return;if(state.jsonDirty)throw Error('请先应用完整 JSON 中的修改。');state.assumptions.planning.risk_top_k=numeric($('target-rank'));state.assumptions.selection_preference={mode:$('risk-mode').value};invalidate();syncJson();}catch(e){error(e.message);}});
$('ack').addEventListener('change',()=>{$('compare').disabled=!$('ack').checked||state.busy||!state.assumptions;});
for(const [id,target,key] of [['pit-loss','physics','pit_loss'],['total-laps','state','total_laps'],['track-status','state','track_status'],['weather','state','weather']]){$(id).addEventListener('change',()=>{try{if(!state.assumptions||state.loadingCase)return;if(state.jsonDirty)throw Error('请先应用完整 JSON 中的修改。');state.assumptions.planning[target][key]=['track-status','weather'].includes(id)?$(id).value:numeric($(id));invalidate();updateScope();syncJson();}catch(e){error(e.message);}});}
$('assumption-json').addEventListener('input',()=>{if(!state.assumptions||state.loadingCase)return;state.jsonDirty=true;invalidate('完整假设已修改，请应用 JSON 后重新比较。');});
$('apply-json').addEventListener('click',()=>{clearError();try{parseJson();invalidate('JSON 已应用，请检查并重新比较。');}catch(e){error('假设 JSON 无法应用：'+e.message);}});
const horizonReasons={immediate_next_lap_remains_blocked:'缺少出站或消息时间记录',no_prefix_confirmed_completed_outlap:'尚无已确认的出站圈',missing_current_lap_state:'当前圈状态缺失',unstarted_boundary_unverified:'目标圈起点未确认',unstarted_boundary_stale:'目标圈状态已过期',snapshot_checks_failed:'记录不同步、缺失或过期',candidate_not_after_original_immediate_target:'候选圈不晚于原目标',distinct_horizon_structurally_selected_external_validation_required:'目标圈通过检查 · 来源未核验，暂无预测'};
function horizonRequest(){return {horizon:$('horizon-choice').value,mode:$('availability-mode').value,assumed_delay_seconds:$('availability-mode').value==='historical_approximation'?checkedNumber($('availability-delay'),'假设延迟',{min:0}):null,envelope:state.horizonEnvelope};}
function renderHorizon(report){
 const s=report.selection;
 $('horizon-status').textContent=horizonReasons[s.reason]||s.reason;
 $('horizon-target').textContent=`原即时：${s.original_immediate_target_lap==null?'未知': '第 '+s.original_immediate_target_lap+' 圈'} / 所选：${s.selected_target_lap==null?'不可用':'第 '+s.selected_target_lap+' 圈'}`;
 $('horizon-note').textContent=`${s.requested_horizon==='immediate_post_pit'?'即时目标':'后续完整圈'} · 候选 ${s.candidate_target_lap??'未知'} · 暂无数值预测`;
 $('horizon-clock').textContent=`${({'retrospective assumed availability':'事件时间 + 假设延迟','imported received_at; provenance unverified':'导入接收时间 · 未核验'})[s.availability_label]||s.availability_label||'时间依据未知'} · 延迟 ${report.assumptions.publication_delay_seconds??'不采用'} s`;
 $('horizon-import-label').textContent=report.data_label==='cached_archive'?'历史归档 · 接收时间未知':report.data_label==='synthetic_fixture_unverified'?'合成测试数据':'用户导入 · 时间与来源未核验';
 $('horizon-evidence').textContent=JSON.stringify(report,null,2);
}
async function refreshHorizon(){
 if(!state.frozen||!state.driver)return;
 const requestId=++state.horizonRequestId,caseId=state.case,driver=state.driver;
 state.horizonReport=null;$('export-horizon').disabled=true;$('export').disabled=true;$('horizon-status').textContent='正在检查预测圈和消息时间…';$('availability-delay').disabled=$('availability-mode').value!=='historical_approximation';
 try{const report=await api('/api/horizon',{case:caseId,driver,horizon_request:horizonRequest()});if(requestId!==state.horizonRequestId||caseId!==state.case||driver!==state.driver)return;state.horizonReport=report;renderHorizon(report);$('export-horizon').disabled=false;$('export').disabled=!state.report;}catch(e){if(requestId!==state.horizonRequestId)return;$('horizon-status').textContent='不可用：'+e.message;$('horizon-target').textContent='不可用';$('horizon-evidence').textContent='';}
}
function downloadJson(raw,name){const blob=new Blob([raw],{type:'application/json'}),url=URL.createObjectURL(blob),a=node('a');a.href=url;a.download=name;document.body.append(a);a.click();a.remove();setTimeout(()=>URL.revokeObjectURL(url),1000);}
$('availability-delay').oninput=()=>{++state.horizonRequestId;state.horizonReport=null;$('export-horizon').disabled=true;$('export').disabled=true;$('horizon-status').textContent='延迟已修改，请完成输入后重新检查。';};
$('horizon-choice').addEventListener('change',refreshHorizon);$('availability-mode').addEventListener('change',refreshHorizon);$('availability-delay').addEventListener('change',refreshHorizon);
$('horizon-file').addEventListener('change',async()=>{const file=$('horizon-file').files[0];if(!file)return;const requestId=++state.horizonRequestId;state.horizonReport=null;$('export-horizon').disabled=true;$('export').disabled=true;try{if(file.size>1000000)throw Error('消息 JSON 超过 1 MB');const envelope=JSON.parse(await file.text());if(requestId!==state.horizonRequestId)return;state.horizonEnvelope=envelope;await refreshHorizon();}catch(e){if(requestId!==state.horizonRequestId)return;$('horizon-status').textContent='不可用：无法导入消息 JSON：'+e.message;}});
$('clear-horizon-file').addEventListener('click',()=>{state.horizonEnvelope=null;$('horizon-file').value='';refreshHorizon();});
$('export-horizon').addEventListener('click',async()=>{clearError();if(!state.horizonReport)return;const requestId=state.horizonRequestId;try{const raw=await api('/api/horizon/export',{case:state.case,driver:state.driver,horizon_request:horizonRequest()},true);if(requestId!==state.horizonRequestId)throw Error('目标已改变，请重新导出');downloadJson(raw,`f1-horizon-${state.driver}-${$('horizon-choice').value}.json`);}catch(e){error(e.message);}});
$('compare').addEventListener('click',compare);$('reveal').addEventListener('click',reveal);$('export').addEventListener('click',exportRecord);
$('cancel').addEventListener('click',async()=>{if(!state.job)return;try{await api('/api/cancel',{job_id:state.job});$('job-status').textContent='正在取消后台任务…';}catch(e){error(e.message);}});
(async()=>{try{state.catalog=await api('/api/catalog');$('dataset-summary').textContent=`${state.catalog.races.length} 场比赛 · ${state.catalog.races.reduce((n,r)=>n+r.cases.length,0)} 个历史快照`;setOptions('race',state.catalog.races.map(r=>[r.id,r.name]));await loadRace();}catch(e){error('工作台启动失败：'+e.message);}})();
