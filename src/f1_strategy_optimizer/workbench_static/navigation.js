/* Parent/child routes and a native modal navigation drawer. No data requests here. */
(() => {
 'use strict';
 const aliases={selection:'/research/select','field-forecast':'/research/select',observed:'/research/data','horizon-panel':'/research/data',assumptions:'/research/setup',comparison:'/research/results',outcomes:'/research/results','openf1-history':'/history'};
 const drawer=document.getElementById('navigation-drawer');
 const openButton=document.getElementById('navigation-open');
 const closeButton=document.getElementById('navigation-close');
 let previousRoute=null;
 function parseRoute(hash){
  const raw=String(hash||'').replace(/^#/,'');
  const path=aliases[raw]||raw||'/';
  if(path==='/history')return {page:'history',path:'/history'};
  const match=path.match(/^\/research(?:\/(select|data|setup|results))?$/);
  if(match)return {page:'research',step:match[1]||'select',path:'/research/'+(match[1]||'select')};
  return {page:'home',path:'/'};
 }
 function syncDrawer(){
  openButton?.setAttribute('aria-expanded',String(Boolean(drawer?.open)));
  if(drawer?.open)document.documentElement.dataset.navigationOpen='true';
  else delete document.documentElement.dataset.navigationOpen;
 }
 function closeDrawer(){if(drawer?.open)drawer.close();syncDrawer();}
 function render(initial=false){
  const route=parseRoute(location.hash);
  closeDrawer();
  for(const page of document.querySelectorAll('[data-page]'))page.hidden=page.dataset.page!==route.page;
  for(const panel of document.querySelectorAll('[data-step]'))panel.hidden=panel.dataset.step!==route.step;
  for(const link of document.querySelectorAll('.app-nav a')){
   const selected=parseRoute(link.hash).page===route.page;
   if(selected)link.setAttribute('aria-current','page');else link.removeAttribute('aria-current');
  }
  for(const link of document.querySelectorAll('.research-tabs a')){
   const selected=route.page==='research'&&parseRoute(link.hash).step===route.step;
   if(selected)link.setAttribute('aria-current','step');else link.removeAttribute('aria-current');
  }
  for(const link of document.querySelectorAll('[data-nav-route]')){
   if(parseRoute(link.hash).path===route.path)link.setAttribute('aria-current','page');else link.removeAttribute('aria-current');
  }
  const title={home:'F1 策略工作台',history:'历史比赛数据',research:'策略研究 · '+({'select':'选择样例',data:'检查数据',setup:'设置参数',results:'比较与导出'}[route.step]||'')}[route.page];
  document.title=title+' | Strategy Lab';
  document.documentElement.dataset.route=route.page;
  if(!initial){
   const sameResearch=route.page==='research'&&previousRoute?.page==='research';
   const stepHeading=sameResearch?document.querySelector(`[data-step="${route.step}"] h2`):null;
   const target=stepHeading||document.getElementById({home:'home-title',history:'history-page-title',research:'research-title'}[route.page]);
   target?.setAttribute('tabindex','-1');target?.focus({preventScroll:true});
   if(stepHeading)stepHeading.scrollIntoView({block:'start',behavior:'instant'});
   else window.scrollTo({top:0,behavior:'instant'});
  }
  previousRoute=route;
  window.dispatchEvent(new CustomEvent('f1:route',{detail:route}));
 }
 window.F1Navigation={parseRoute,showResults(){const r=parseRoute(location.hash);if(r.page==='research'&&r.step==='setup')this.navigate('/research/results');},navigate(path){if(location.hash==='#'+path)render();else location.hash=path;}};
 document.querySelector('.skip-link')?.addEventListener('click',event=>{event.preventDefault();document.getElementById('main-content')?.focus();});
 if(drawer&&typeof drawer.showModal==='function'&&openButton){
  openButton.hidden=false;document.documentElement.dataset.drawerReady='true';
  openButton.addEventListener('click',()=>{if(drawer.open)closeDrawer();else{drawer.showModal();syncDrawer();}});
  closeButton?.addEventListener('click',closeDrawer);
  drawer.addEventListener('close',syncDrawer);
  drawer.addEventListener('click',event=>{if(event.target===drawer)closeDrawer();});
  for(const link of drawer.querySelectorAll('a[href^="#/"]'))link.addEventListener('click',event=>{
   if(event.button!==0||event.metaKey||event.ctrlKey||event.shiftKey||event.altKey)return;
   event.preventDefault();closeDrawer();window.F1Navigation.navigate(parseRoute(link.hash).path);
  });
 }
 const header=document.querySelector('.app-header');
 if(header&&typeof ResizeObserver==='function'){
  const observer=new ResizeObserver(()=>document.documentElement.style.setProperty('--header-height',`${Math.ceil(header.getBoundingClientRect().height)}px`));
  observer.observe(header);
 }
 window.addEventListener('hashchange',()=>render());
 render(true);
})();
