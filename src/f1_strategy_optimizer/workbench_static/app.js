'use strict';
const $ = id => document.getElementById(id);
const state = {catalog:null, frozen:null, quality:null, assumptions:null, case:null, driver:null, epoch:0, job:null, report:null, reveal:null, busy:false, jsonDirty:false, selectionRequest:0};
const reasonNames = {unknown:'未知',inferred:'推断',observed:'观测',stale_observation:'观测已陈旧',insufficient_prefix_laps:'合格历史圈不足',insufficient_or_stale_numeric_interval_prefix:'间距报告不足或已陈旧',target_missing_no_retirement_inference:'目标缺失；不据此推断退赛',target_already_started:'目标已在截止点前开始，不重选',target_duration_unknown:'目标圈时未知',stale_interval_outcome:'结果间距报告已陈旧',invalid_or_null_interval_outcome:'结果间距不是有效数值',no_new_interval_outcome:'没有新间距报告'};
const human = text => reasonNames[text] || text || '—';
const fmt = (value, digits=3) => typeof value === 'number' ? value.toFixed(digits) : value == null ? '未知' : String(value);
const node = (tag, text, cls) => {const e=document.createElement(tag);if(text!=null)e.textContent=text;if(cls)e.className=cls;return e;};
const empty = id => $(id).replaceChildren();
function error(message){$('global-error').textContent=message;$('global-error').classList.remove('hidden');}
function clearError(){$('global-error').classList.add('hidden');}
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
 $('export').disabled=true;$('cancel').classList.add('hidden');$('job-status').textContent='';
 $('compare').disabled=!$('ack').checked || !state.assumptions;
}
function setOptions(id, values, current){const select=$(id);select.replaceChildren();for(const [value,label] of values){const option=node('option',label);option.value=value;select.append(option);}if(current)select.value=current;}
function syncJson(){state.jsonDirty=false;$('assumption-json').value=JSON.stringify(state.assumptions,null,2);}
function updateScope(){
 const p=state.assumptions.planning,n=p.state.cars.length,total=state.frozen.state.cars.length;
 $('scope-note').textContent=`人工假设范围：${n} / ${total} 车，抽象边界第 ${p.state.completed_laps??'未知'} 圈之后，终点第 ${p.state.total_laps??'未知'} 圈。所有名次仅在所选模型车阵内有效。库存：${state.assumptions.inventory_policy.kind==='finite'?'填写的有限库存':'未知，无限库存数学模型'}。历史进站次数初始假设 0；已用配方仅当前胎，不代表历史记录。`;
 $('scenario-overview').textContent=`条件假设：${p.state.track_status} / ${p.state.weather} / ${p.state.track_temp} ℃。覆盖情景：`+p.scenarios.map(x=>`${x.name}，主观权重 ${x.weight}，事件 ${JSON.stringify(x.events)}`).join('；');
}
function numeric(input){return input.value.trim()===''?null:Number(input.value);}
function policyMode(policy){return policy.kind==='reactive'?policy.mode:policy.stops.length?'fixed':'stay';}
function formFromAssumptions(){
 const a=state.assumptions,p=a.planning;
 if(!p?.state?.cars || !p.physics)throw Error('假设 JSON 缺少 planning.state.cars 或 planning.physics。');
 $('pit-loss').value=p.physics.pit_loss;$('total-laps').value=p.state.total_laps??'';$('track-status').value=p.state.track_status;$('weather').value=p.state.weather;
 $('target-rank').value=p.risk_top_k;$('target-rank').max=p.state.cars.length;$('risk-mode').value=a.selection_preference?.mode||'mean_position';
 empty('field-cars');const ids=new Set(p.state.cars.map(c=>c.driver));
 for(const car of state.frozen.state.cars){const label=node('label'),input=node('input');input.type='checkbox';input.value=car.id;input.checked=ids.has(car.id);input.disabled=car.id===state.driver;label.append(input,node('span',`${car.id} · ${car.team} · 间距 ${fmt(car.gap_seconds.value)} s`));$('field-cars').append(label);}
 empty('assumed-cars');
 p.state.cars.forEach((car,index)=>{const tr=node('tr');const name=node('td',car.driver+(car.driver===state.driver?' · 当前车手':''));name.append(node('small',car.team));tr.append(name);
  for(const key of ['base_lap_time','gap_seconds','tyre_age','compound']){const td=node('td');let input;
   if(key==='compound'){input=node('select');for(const value of [...new Set(['',...Object.keys(p.tyres),car.compound].filter(x=>x!==null))]){const option=node('option',value||'未知 / 须填写');option.value=value;input.append(option);}input.value=car[key]??'';}
   else{input=node('input');input.type='number';input.step=key==='tyre_age'?'1':'0.001';input.min='0';input.value=car[key]??'';input.placeholder='未知 / 须填写';}
   input.setAttribute('aria-label',`${car.driver} ${key}`);input.dataset.car=String(index);input.dataset.field=key;
   input.addEventListener('change',()=>{try{if(state.jsonDirty)throw Error('请先应用完整 JSON 中的修改。');car[key]=key==='compound'?(input.value||null):numeric(input);invalidate();syncJson();}catch(e){error(e.message);}});
   td.append(input);tr.append(td);
  }
  const td=node('td');if(car.driver===state.driver){td.textContent='由候选方案决定；始终比较留场';}else{
   const policy=p.opponents[car.driver],mode=node('select'),lap=node('input');lap.type='number';lap.step='1';lap.value=policy.planned_lap??policy.stops?.[0]?.after_lap??(p.state.completed_laps+3);
   for(const [value,label] of [['stay','留场'],['fixed','固定进站'],['cover_undercut','回应 undercut'],['overcut','延后 overcut']]){const option=node('option',label);option.value=value;mode.append(option);}mode.value=policyMode(policy);mode.setAttribute('aria-label',`${car.driver} response`);lap.setAttribute('aria-label',`${car.driver} planned_lap`);
   const change=()=>{try{if(state.jsonDirty)throw Error('请先应用完整 JSON 中的修改。');const at=numeric(lap),compound=policy.compound||policy.stops?.[0]?.compound||p.candidates.compounds[0];p.opponents[car.driver]=mode.value==='stay'?{kind:'fixed',stops:[]}:mode.value==='fixed'?{kind:'fixed',stops:[{after_lap:at,compound}]}:{kind:'reactive',rival:state.driver,compound,planned_lap:at,window_start:p.state.completed_laps,window_end:p.state.total_laps-1,mode:mode.value,response_gap:12,overcut_laps:1};invalidate();syncJson();}catch(e){error(e.message);}};
   mode.addEventListener('change',change);lap.addEventListener('change',change);td.append(mode,lap,node('small','响应阈值默认 12 s；新胎/窗口详见 JSON。'));
  }tr.append(td);$('assumed-cars').append(tr);
 });updateScope();syncJson();$('ack').disabled=false;$('compare').disabled=!$('ack').checked;
}
function renderQuality(){
 const q=state.quality;if(!q)return;const d=q.drivers[state.driver],c=d.candidate;
 const reasons={missing_or_stale_lap_evidence:'完成圈缺失或陈旧',control_active_or_clearance_unconfirmed:'SC/VSC/红旗尚未确认解除',segment_warmup_requires_three_completed_laps:'转换后不足三圈，等待重新积累',stale_eligible_segment:'合格赛段样本已陈旧',unstable_segment_range_exceeds_four_seconds:'最近三圈极差超过 4 秒，暂不预测',no_fixed_target_lap:'没有固定目标圈'};
 $('segment-forecast').textContent=c.value_seconds==null?'暂不预测':fmt(c.value_seconds)+' s';
 $('segment-note').textContent=c.reason?(reasons[c.reason]||c.reason):`同赛段第 ${c.sample_laps.join('、')} 圈中位数；观测极差 ${fmt(c.observed_range_seconds)} s（非置信区间）。目标第 ${c.target_lap} 圈。`;
 $('quality-clock').textContent=`冻结 UTC：${q.cutoff}；浏览器载入 UTC：${new Date().toISOString()}。年龄按事件到冻结时刻计算，不把档案距离今天的时间当作当时延迟。`;
 empty('quality-table');for(const [name,v] of [['快照内最新事件（非全车新鲜度）',q.snapshot],['所选车手完成圈',d.lap],['所选车手间距报告',d.gap],['天气报告',q.weather],['明确的全赛道状态',q.race_control]]){
  const tr=node('tr'),status={missing:'缺失：不补值',stale:'过期：降级为未知',event_time_only:'仅事件时间；发布时间未核验'}[v.reliability];tr.append(node('td',name),node('td',`${fmt(v.age_seconds_at_cutoff,1)} s / 上限 ${v.max_age_seconds} s`),node('td',status+(name.includes('间距')&&!v.numeric_usable?'；非可用数值间距':'')+(name.includes('赛道')?`；当前可用状态 ${v.usable_state}`:'')),node('td',`${v.clock_source} / ${v.event_at||'未知'}`));$('quality-table').append(tr);
 }
 $('quality-limits').textContent=`采用事件时间 + 假设 3 秒可用性延迟；不证明历史实时可得。换段边界：${c.segment_boundaries.map(x=>x.kind+' @ '+x.event_at).join('；')||'无已识别边界'}。降雨变化只是信号，真实湿干路面仍未知。`+(q.context_sha256?'':'当前缓存无天气历史，不能检测降雨转换。');
}
function renderFacts(){
 renderQuality();
 const frozen=state.frozen,car=frozen.state.cars.find(c=>c.id===state.driver),forecast=frozen.observation_forecasts.find(c=>c.driver_id===state.driver);
 empty('facts');
 for(const [key,label] of [['completed_laps','已完成圈数'],['last_started_lap','已开始圈'],['position','最后已报告名次'],['gap_seconds','间距报告 / 秒'],['compound','配方'],['estimated_completed_tyre_age','估计已完成胎龄'],['activity','活动状态'],['tyre_inventory','轮胎库存']]){
  const field=car[key] || {status:'unknown'},tr=node('tr');tr.append(node('td',label),node('td',fmt(field.value,2)));const status=node('td');status.append(node('span',human(field.status),`pill ${field.status==='unknown'?'unknown':'fact'}`));tr.append(status);
  const detail=node('td',field.event_at || '无可验证事件时间');detail.append(node('small',[field.source,human(field.reason),field.age_seconds==null?'':`事件距截止点 ${fmt(field.age_seconds,1)} 秒`].filter(x=>x&&x!=='—').join(' · ')));tr.append(detail);$('facts').append(tr);
 }
 for(const [key,label] of [['track_status','全赛道状态'],['surface_condition','路面状态']]){const f=frozen.state[key],tr=node('tr');tr.append(node('td',label),node('td',fmt(f.value)),node('td',human(f.status)),node('td',f.reason));$('facts').append(tr);}
 for(const kind of ['lap','gap']){const pred=forecast.default_prediction[kind];$(kind+'-forecast').textContent=pred.value_seconds==null?'暂不可预测':fmt(pred.value_seconds)+' s';$(kind+'-note').textContent=`${pred.method} · ${pred.reason?human(pred.reason):kind==='lap'?`固定目标第 ${forecast.lap.target_lap} 圈；最后合格圈距截止点 ${fmt(forecast.lap.context?.last_eligible_age_seconds,1)} 秒；活动状态未验证`:`报告时域 ${forecast.gap.horizon}`}`;}
 $('frozen-meta').textContent=JSON.stringify({decision_sha256:frozen.decision_sha256,cutoff:frozen.cutoff,partition:frozen.partition,code_version:frozen.code_version,config:frozen.config,data_version:frozen.data_version,fit_cutoff:frozen.fit_cutoff},null,2);
 $('snapshot-note').textContent=`${frozen.cutoff} · ${frozen.state.cars.length} 车归档前缀 · ${frozen.partition==='holdout'?'原留出记录 · 已观察，当前属开发研究':'开发示例'} · 非实时`;
}
async function loadDriver(customDrivers=null){
 const request=++state.selectionRequest,caseId=state.case,driver=$('driver').value;
 state.driver=driver;invalidate('选择已改变，正在载入匹配假设。');state.assumptions=null;$('compare').disabled=true;$('ack').checked=false;$('ack').disabled=true;empty('assumed-cars');
 state.reveal=null;$('reveal-result').textContent='结果仍未揭晓。';$('reveal').disabled=false;renderFacts();
 try{const field=Array.isArray(customDrivers)?'custom':$('field-mode').value;const selected=Array.isArray(customDrivers)?customDrivers:[driver];const a=await api(`/api/assumptions?case=${encodeURIComponent(caseId)}&driver=${encodeURIComponent(driver)}&field=${field}&drivers=${encodeURIComponent(selected.join(','))}`);if(request!==state.selectionRequest)return;state.assumptions=a;formFromAssumptions();$('empty-comparison').textContent='请检查示例假设并确认，然后运行比较。';}catch(e){error(e.message);}
}
async function loadCase(){
 clearError();const caseId=$('cutoff').value,request=++state.selectionRequest;invalidate('正在载入冻结记录。');state.case=caseId;state.assumptions=null;$('compare').disabled=true;
 try{const result=await api('/api/decision?case='+encodeURIComponent(caseId));if(request!==state.selectionRequest)return;state.frozen=result.frozen;state.quality=result.prefix_quality;$('version').textContent='代码版本 '+result.workbench_version.slice(0,12);const options=state.frozen.state.cars.map(c=>[c.id,`${c.name} · ${c.driver_number}`]);setOptions('driver',options,options.some(x=>x[0]==='leclerc')?'leclerc':options[0][0]);await loadDriver();}catch(e){error(e.message);}
}
async function loadRace(){const race=state.catalog.races.find(r=>r.id===$('race').value);const preferred=race.cases.find(c=>c.cutoff.includes('15:18:00'));setOptions('cutoff',race.cases.map(c=>[c.id,c.cutoff]),(preferred||race.cases[0]).id);await loadCase();}
function parseJson(){if(state.jsonDirty){const a=JSON.parse($('assumption-json').value);if(a.planning?.ego!==state.driver)throw Error('JSON ego 必须与当前所选车手一致。');state.assumptions=a;formFromAssumptions();}}
function detailForCandidate(candidate){
 const wrap=node('div');for(const detail of candidate.simulation_details){const box=node('div',null,'scenario');box.append(node('strong',detail.scenario));const proxy=detail.first_post_stop_lap_proxy;const outcome=candidate.outcomes.find(x=>x.scenario===detail.scenario);if(outcome){box.append(node('p','模型终点顺序：'+outcome.finish_order.join(' → '),'compact'));const actions=outcome.trace.filter(x=>Object.keys(x.pit_actions).length).map(x=>'第 '+x.lap+' 圈 '+JSON.stringify(x.pit_actions));box.append(node('p','实际模拟的进站响应：'+(actions.join('；')||'全部留场'),'compact'));}
  box.append(node('p',proxy?`进站后首圈代理：第 ${proxy.lap} 圈 / 模型 P${proxy.position}；前 ${proxy.ahead||'无'}，后 ${proxy.behind||'无'}；交通调整 ${fmt(proxy.traffic_adjustment_seconds)} s；排队 ${fmt(proxy.pit_queue_wait_seconds)} s`:'此方案无进站后首圈代理（未进站）。','compact'));
  for(const [driver,cost] of Object.entries(detail.simulated_teammate_costs)){box.append(node('p',cost?`队友 ${driver}：相对同情景留场，耗时差 ${fmt(cost.elapsed_delta_vs_same_scenario_stay_out_seconds)} s，模型名次差 ${cost.position_delta_vs_same_scenario_stay_out}，排队 ${fmt(cost.simulated_queue_wait_seconds)} s`:`队友 ${driver}：无可行留场基线，代价未知。`,'compact'));}wrap.append(box);
 }return wrap;
}
function renderReport(report){
 $('empty-comparison').classList.add('hidden');$('comparison-content').classList.remove('hidden');
 $('result-scope').textContent=`模拟范围：${report.model_scope.modeled_driver_count} / ${report.model_scope.frozen_driver_count} 车，第 ${report.model_horizon.after_lap+1}–${report.model_horizon.through_lap} 圈。仅为模型终点名次；真实行动边界未知。${report.inventory_feasibility}`;
 empty('candidates');if(!report.top3.length)$('candidates').append(node('p','没有可行候选：所有方案至少在一个声明情景下违反约束。请检查进站次数、胎龄、库存及对手计划；本次不提供策略建议。'));
 report.top3.forEach((c,i)=>{const card=node('article',null,'candidate');card.append(node('small',`可行候选 ${i+1} · 模拟`),node('h3',c.label));const rank=node('div',fmt(c.expected_finish_position,2),'rank');rank.append(node('small','模型终点均值名次'));card.append(rank,node('p',`最差模型名次 ${c.worst_finish_position} · 未达目标情景权重 ${(100*c.weighted_share_outside_top_k).toFixed(1)}%（非概率） · 仅此车阵`,'compact'));const details=node('details');details.append(node('summary','进站后交通代理与队友代价'),detailForCandidate(c));card.append(details);$('candidates').append(card);});
 $('stay-out').textContent=report.stay_out.status==='feasible'?`留场基线：可行 · 模型终点均值名次 ${fmt(report.stay_out.candidate.expected_finish_position,2)}`:`留场基线：不可行 · ${report.stay_out.rejection?.first_failure?.scenario||'未知情景'} / ${report.stay_out.rejection?.first_failure?.reason||'见拒绝详情'}`;
 $('result-conditions').textContent=`参与车辆：${report.model_scope.drivers.join('、')}；排除：${report.model_scope.excluded_drivers.join('、')||'无'}。目标模型前 ${report.selection_preference.target_top_k} 名；排序 ${report.selection_preference.mode==='conservative'?'保守：最差名次 → 未达目标的主观权重占比 → 均值名次':'平均名次优先'}。情景 ${report.covered_scenarios.map(x=>x.name+'（权重 '+x.weight+'）').join('、')}；条件 ${JSON.stringify(report.modeled_conditions)}。`;
 const t=report.initial_threats;$('threats').textContent=`前车 ${t.ahead||'无'}（${fmt(t.gap_to_ahead_seconds)} s）；后车 ${t.behind||'无'}（${fmt(t.gap_from_behind_seconds)} s）。`;
 empty('sensitivity');$('sensitivity').append(node('p',`基准胜出：${report.sensitivity.baseline_winner||'无'}`));for(const c of report.sensitivity.cases){$('sensitivity').append(node('p',`${c.name}（${c.path}: ${c.original_value} → ${c.assumed_value}）：${c.winner_changed?'方案翻转':'未翻转'} → ${c.winner||'无可行方案'}；原方案排序 ${c.baseline_plan_rank_in_variant??'不可行'}；原方案模型名次 ${fmt(c.baseline_plan_expected_position,2)}`,'compact'));}
 empty('overrides');for(const f of report.field_overrides){const tr=node('tr');tr.append(node('td',f.path),node('td',JSON.stringify(f.original)),node('td',JSON.stringify(f.assumed_value)),node('td',`${f.source} / ${f.rationale}`));$('overrides').append(tr);}
 $('rejected').textContent=JSON.stringify(report.rejected_candidates,null,2);
}
async function compare(){
 clearError();let activeEpoch=null;try{parseJson();if(!$('ack').checked)throw Error('请先确认人工假设。');
  invalidate('正在模拟当前假设。');const epoch=state.epoch;activeEpoch=epoch;state.busy=true;$('compare').disabled=true;$('cancel').classList.remove('hidden');$('job-status').textContent='已提交，正在启动后台模拟…';
  const job=await api('/api/explore',{case:state.case,driver:state.driver,assumptions:state.assumptions,acknowledged:true});if(epoch!==state.epoch){await api('/api/cancel',{job_id:job.id});return;}state.job=job.id;
  while(epoch===state.epoch){const result=await api('/api/jobs/'+encodeURIComponent(job.id));if(epoch!==state.epoch)return;$('job-status').textContent=`${result.status==='running'?'后台模拟中':'模拟已结束'} · ${fmt(result.elapsed_seconds,1)} 秒 · 超时上限 ${job.timeout_seconds} 秒`;
   if(result.status!=='running'){state.busy=false;$('compare').disabled=!$('ack').checked;$('cancel').classList.add('hidden');if(result.status!=='succeeded')throw Error(result.error||'模拟未完成');state.report=result.report;renderReport(result.report);$('export').disabled=false;$('job-status').textContent=`完成 · ${fmt(result.elapsed_seconds,2)} 秒 · ${result.report.budget.rollouts_executed} rollouts`;return;}
   await new Promise(resolve=>setTimeout(resolve,250));
  }
 }catch(e){if(activeEpoch!==null&&activeEpoch!==state.epoch)return;state.busy=false;$('compare').disabled=!$('ack').checked;$('cancel').classList.add('hidden');error(e.message);$('empty-comparison').textContent='此次比较未产生新结果，请修正错误后重试。';}
}
async function reveal(){clearError();const epoch=state.epoch;try{$('reveal').disabled=true;const result=await api('/api/reveal',{case:state.case,driver:state.driver});if(epoch!==state.epoch){$('reveal').disabled=false;return;}state.reveal=result;empty('reveal-result');$('reveal-result').append(node('p','已主动揭晓 · 事实观测结果（不验证模拟策略）'));const grid=node('div',null,'reveal-metric');for(const [kind,title] of [['lap','实际下一完整圈'],['gap','实际固定时域间距报告']]){const r=result.evaluation[kind],box=node('article');box.append(node('span',title));box.append(node('strong',r.errors?fmt(r.actual)+' s':'不可评分'));if(r.errors){const method=r.selected_method;box.append(node('p',`${method} 绝对误差：${fmt(r.errors[method])} s`,'compact'));}else box.append(node('p',human(r.reason),'compact'));grid.append(box);}$('reveal-result').append(grid);const f=result.evaluation.freshness_evaluation;if(f){$('reveal-result').append(node('p',`分段候选：${f.lap_category}；${f.candidate_abs_error==null?'无评分 / '+(f.candidate_reason||f.baseline_reason||'赛后不适用'): '绝对误差 '+fmt(f.candidate_abs_error)+' s；同目标基线 '+fmt(f.baseline_abs_error_same_target)+' s'}。赛后分类使用事后最后圈结束代理，不进入预测。`));}const details=node('details');details.append(node('summary','查看实际目标和评分证据'));details.append(node('pre',JSON.stringify(result.evaluation,null,2)));$('reveal-result').append(details);}catch(e){$('reveal').disabled=false;error(e.message);}}
async function exportRecord(){clearError();const epoch=state.epoch;try{if(state.jsonDirty)throw Error('JSON 已修改，请应用并重新运行比较后导出。');if(!state.report)throw Error('请先完成当前假设比较。');const record=await api('/api/export',{case:state.case,driver:state.driver,job_id:state.job,assumptions_sha256:state.report.assumptions_sha256,reveal_id:state.reveal?.id},true);if(epoch!==state.epoch)throw Error('选择或假设已改变，已丢弃旧导出。');const blob=new Blob([record],{type:'application/json'});const url=URL.createObjectURL(blob),a=node('a');a.href=url;a.download=`f1-decision-${state.driver}-${state.frozen.cutoff.replaceAll(':','-')}.json`;document.body.append(a);a.click();a.remove();setTimeout(()=>URL.revokeObjectURL(url),1000);$('job-status').textContent='决策记录已导出，含版本与证据哈希。';}catch(e){error(e.message);}}
$('race').addEventListener('change',loadRace);$('cutoff').addEventListener('change',loadCase);$('driver').addEventListener('change',()=>loadDriver());
$('field-mode').addEventListener('change',()=>{if($('field-mode').value!=='custom')loadDriver();});
$('apply-field').addEventListener('click',()=>{$('field-mode').value='custom';loadDriver([...$('field-cars').querySelectorAll('input:checked')].map(x=>x.value));});
for(const id of ['target-rank','risk-mode'])$(id).addEventListener('change',()=>{try{if(state.jsonDirty)throw Error('请先应用完整 JSON 中的修改。');state.assumptions.planning.risk_top_k=numeric($('target-rank'));state.assumptions.selection_preference={mode:$('risk-mode').value};invalidate();syncJson();}catch(e){error(e.message);}});
$('ack').addEventListener('change',()=>{$('compare').disabled=!$('ack').checked||state.busy||!state.assumptions;});
for(const [id,target,key] of [['pit-loss','physics','pit_loss'],['total-laps','state','total_laps'],['track-status','state','track_status'],['weather','state','weather']]){$(id).addEventListener('change',()=>{try{if(state.jsonDirty)throw Error('请先应用完整 JSON 中的修改。');state.assumptions.planning[target][key]=['track-status','weather'].includes(id)?$(id).value:numeric($(id));invalidate();updateScope();syncJson();}catch(e){error(e.message);}});}
$('assumption-json').addEventListener('input',()=>{state.jsonDirty=true;invalidate('完整假设已修改，请应用 JSON 后重新比较。');});
$('apply-json').addEventListener('click',()=>{clearError();try{parseJson();invalidate('JSON 已应用，请检查并重新比较。');}catch(e){error('假设 JSON 无法应用：'+e.message);}});
$('compare').addEventListener('click',compare);$('reveal').addEventListener('click',reveal);$('export').addEventListener('click',exportRecord);
$('cancel').addEventListener('click',async()=>{if(!state.job)return;try{await api('/api/cancel',{job_id:state.job});$('job-status').textContent='正在取消后台任务…';}catch(e){error(e.message);}});
(async()=>{try{state.catalog=await api('/api/catalog');setOptions('race',state.catalog.races.map(r=>[r.id,r.name]));await loadRace();}catch(e){error('工作台启动失败：'+e.message);}})();
