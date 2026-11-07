/* OpenF1 historical observations. Independent of frozen research state and jobs. */
(() => {
 'use strict';
 const el=id=>document.getElementById(id);
 const hs={generation:0,controller:null,started:false,busy:false,stage:'sessions',sessions:[],drivers:[],record:null};
 const make=(tag,text)=>{const node=document.createElement(tag);if(text!=null)node.textContent=String(text);return node;};
 const text=value=>value==null?'未知':String(value);
 function duration(value){if(typeof value!=='number'||!Number.isFinite(value)||value<0)return '缺失';const ms=Math.round(value*1000);return `${Math.floor(ms/60000)}:${(Math.floor(ms/1000)%60).toString().padStart(2,'0')}.${(ms%1000).toString().padStart(3,'0')}`;}
 function utc(value){if(!value)return '未知';const date=new Date(value);return Number.isNaN(date.valueOf())?'时间格式未知':date.toISOString().replace('T',' ').replace('.000Z',' UTC').replace('Z',' UTC');}
 function options(id,placeholder,rows){const target=el(id);target.replaceChildren();const first=make('option',placeholder);first.value='';target.append(first);for(const row of rows){const option=make('option',row.label);option.value=String(row.value);option.disabled=Boolean(row.disabled);target.append(option);}target.value='';}
 function clearRecord(){hs.record=null;el('history-warning').textContent='';el('history-warning').classList.add('hidden');el('history-export').disabled=true;el('history-results').classList.add('hidden');for(const id of ['history-laps','history-stints'])el(id).replaceChildren();for(const id of ['history-source','history-limits','history-provenance','history-selection'])el(id).textContent='';}
 function sourceWarnings(source={}){
  const warnings=Array.isArray(source.warnings)?source.warnings:[];
  const stale=source.cache_status==='stale_fallback';
  if(!stale&&!warnings.length){el('history-warning').textContent='';el('history-warning').classList.add('hidden');return;}
  const parts=[];
  if(stale){parts.push('刷新失败，含旧缓存。');el('history-status').textContent='刷新失败，显示旧缓存。';}
  parts.push(`最早缓存时间：${utc(source.retrieved_at_utc)}。`);
  parts.push(...new Set(warnings.map(String)));
  el('history-warning').textContent=parts.join(' ');el('history-warning').classList.remove('hidden');
 }
 function resetPendingSelect(stage,message){if(stage==='sessions')options('history-session',message,[]);if(stage==='drivers')options('history-driver',message,[]);}
 function showError(message){el('history-error').textContent=message;el('history-error').classList.remove('hidden');}
 async function run(stage,path,onSuccess){
  hs.controller?.abort();const generation=++hs.generation,controller=new AbortController();hs.controller=controller;hs.stage=stage;hs.busy=true;hs.started=true;
  el('history-error').classList.add('hidden');el('history-load').disabled=true;el('history-load').setAttribute('aria-busy','true');el('history-cancel').classList.remove('hidden');
  const label={sessions:'比赛列表',drivers:'车手列表',history:'历史圈时与轮胎记录'}[stage];el('history-status').textContent=`正在加载${label}…`;
  const timeout=setTimeout(()=>controller.abort(),45000);
  try{
   const response=await fetch(path,{signal:controller.signal});let result;try{result=await response.json();}catch{throw Error(`服务返回了无法解析的数据（HTTP ${response.status}）。`);}
   if(generation!==hs.generation)return;
   if(!response.ok)throw Error(result.error||`加载失败（HTTP ${response.status}）。`);
   onSuccess(result);sourceWarnings(result.source);
  }catch(error){if(generation!==hs.generation)return;clearRecord();resetPendingSelect(stage,'加载失败，请重试');showError(error.name==='AbortError'?'请求超时或中断，请重试。':error.message);el('history-status').textContent='加载失败，请重试。';}
  finally{clearTimeout(timeout);if(generation===hs.generation){hs.busy=false;hs.controller=null;el('history-load').disabled=false;el('history-load').setAttribute('aria-busy','false');el('history-load').textContent='重新加载';el('history-cancel').classList.add('hidden');}}
 }
 function cancel(){const wasBusy=hs.busy;hs.controller?.abort();++hs.generation;hs.controller=null;hs.busy=false;clearRecord();if(wasBusy)resetPendingSelect(hs.stage,'已取消，请重新加载');el('history-load').disabled=false;el('history-load').setAttribute('aria-busy','false');el('history-cancel').classList.add('hidden');el('history-status').textContent='已取消，可重新加载。';}
 function loadSessions(){
  clearRecord();hs.sessions=[];hs.drivers=[];options('history-session','正在加载比赛…',[]);options('history-driver','请先选择比赛',[]);el('history-session').disabled=true;el('history-driver').disabled=true;
  return run('sessions',`/api/openf1/sessions?year=${encodeURIComponent(el('history-year').value)}`,result=>{
   if(!Array.isArray(result.races))throw Error('比赛列表格式不正确。');hs.sessions=result.races;
   options('history-session',result.races.length?'请选择比赛':'没有可用比赛',result.races.map(r=>({value:r.session_key,label:`${r.meeting_name||r.location||r.country_name} · ${utc(r.date_start).slice(0,10)}${r.available===false?' · '+(r.blocked_reason||'不可加载'):''}`,disabled:r.available===false})));
   el('history-session').disabled=!result.races.some(r=>r.available!==false);el('history-status').textContent=result.races.length?'请选择比赛。':'该年份暂无可用正赛。';
  });
 }
 function loadDrivers(){
  clearRecord();hs.drivers=[];options('history-driver','正在加载车手…',[]);el('history-driver').disabled=true;
  const session=hs.sessions.find(r=>String(r.session_key)===el('history-session').value);
  if(!session||session.available===false){cancel();el('history-status').textContent=session?.blocked_reason||'请先选择可用的比赛。';return;}
  return run('drivers',`/api/openf1/drivers?session_key=${encodeURIComponent(session.session_key)}`,result=>{
   if(!Array.isArray(result.drivers))throw Error('车手列表格式不正确。');if(String(result.session?.session_key)!==String(session.session_key))throw Error('车手列表所属比赛与当前选择不匹配。');hs.drivers=result.drivers;
   options('history-driver',result.drivers.length?'请选择车手':'没有车手记录',result.drivers.map(d=>({value:d.driver_number,label:`${d.full_name||d.name_acronym||d.driver_number} · ${d.team_name||'车队未知'}`})));
   el('history-driver').disabled=!result.drivers.length;el('history-status').textContent=result.drivers.length?'选择车手后自动加载。':'暂无车手记录。';
  });
 }
 function renderHistory(result){
  if(!Array.isArray(result.laps)||!Array.isArray(result.stints)||!result.source)throw Error('历史记录格式不完整。');
  if(String(result.session?.session_key)!==el('history-session').value||String(result.driver?.driver_number)!==el('history-driver').value)throw Error('返回的比赛或车手与当前选择不匹配。');
  if(result.source.live!==false||result.source.availability_basis!=='post_event_download')throw Error('来源未确认为赛后历史下载。');
  hs.record=result;const source=result.source;
  el('history-selection').textContent=`${result.session.meeting_name||result.session.location||result.session.country_name} · ${result.driver.full_name||result.driver.name_acronym||result.driver.driver_number}`;
  el('history-lap-count').textContent=String(result.laps.length);el('history-timed-count').textContent=String(result.laps.filter(l=>typeof l.lap_duration==='number'&&Number.isFinite(l.lap_duration)&&l.lap_duration>=0).length);el('history-stint-count').textContent=String(result.stints.length);
  el('history-cache').textContent=`历史记录 · ${({hit:'使用缓存',miss:'新下载',cached:'使用缓存',fresh:'新下载',stale_fallback:'刷新失败 · 旧缓存'})[source.cache_status]||source.cache_status||'缓存状态未知'}`;
  el('history-source').textContent=`${source.provider||'OpenF1'} · 赛后下载：${utc(source.retrieved_at_utc)}（非比赛接收时间）`;
  el('history-limits').textContent='记录可能含赛后修订。';
  el('history-provenance').textContent=JSON.stringify({source,limitations:result.limitations},null,2);
  el('history-laps').replaceChildren();for(const lap of result.laps){const row=make('tr');row.append(make('td',text(lap.lap_number)),make('td',duration(lap.lap_duration)),make('td',utc(lap.date_start)),make('td',lap.is_pit_out_lap===true?'是':lap.is_pit_out_lap===false?'否':'未知'));el('history-laps').append(row);}
  el('history-stints').replaceChildren();for(const stint of result.stints){const row=make('tr');for(const value of [stint.stint_number,stint.compound,stint.lap_start,stint.lap_end,stint.tyre_age_at_start])row.append(make('td',text(value)));el('history-stints').append(row);}
  el('history-results').classList.remove('hidden');el('history-export').disabled=false;el('history-status').textContent=result.laps.length?'历史记录已加载。':'没有圈时数据。';sourceWarnings(source);
 }
 function loadHistory(){
  clearRecord();const session=el('history-session').value,driver=el('history-driver').value;
  if(!session||!driver){cancel();el('history-status').textContent='请选择比赛和车手。';return;}
  return run('history',`/api/openf1/history?session_key=${encodeURIComponent(session)}&driver_number=${encodeURIComponent(driver)}`,renderHistory);
 }
 el('history-load').addEventListener('click',()=>{if(hs.stage==='history'&&el('history-driver').value)loadHistory();else if(hs.stage==='drivers'&&el('history-session').value)loadDrivers();else loadSessions();});
 el('history-cancel').addEventListener('click',cancel);
 el('history-year').addEventListener('change',()=>{if(hs.started)loadSessions();});
 el('history-session').addEventListener('change',loadDrivers);el('history-driver').addEventListener('change',loadHistory);
 el('history-export').addEventListener('click',()=>{if(!hs.record||hs.busy)return;const blob=new Blob([JSON.stringify(hs.record,null,2)],{type:'application/json'}),url=URL.createObjectURL(blob),a=make('a');a.href=url;a.download=`openf1-history-${hs.record.session.session_key}-${hs.record.driver.driver_number}.json`;document.body.append(a);a.click();a.remove();setTimeout(()=>URL.revokeObjectURL(url),1000);});
 // Entering the history child page is the user's explicit browsing action.
 // Fetch once only; returning/back navigation never retries a rejected request.
 if(typeof window!=='undefined')window.addEventListener('f1:route',event=>{
  if(event.detail.page==='history'&&!hs.started){
   if(window.F1Preview){el('history-status').textContent='界面预览未连接 OpenF1，请在本地工作台查询。';return;}
   loadSessions();
  }else if(event.detail.page!=='history'&&hs.busy)cancel();
 });
 const year=new Date().getUTCFullYear();for(let value=year;value>=2023;value--){const option=make('option',value);option.value=String(value);el('history-year').append(option);}el('history-year').value=String(year);
})();
