import {FactoryScene, createAvatar} from './scene.js';
import {OutputChart, ScatterChart} from './charts.js';
import {CARD_META, STATUS_COLORS, STATUS_LABELS, normaliseSnapshot, list, record, numeric,
  count, clamp, text, short, formatMetric, formatNumber, formatTimestamp} from './data.js';

const CAPTION_COLORS={sim_done:'#33d1ff',eval_pass:'#3ddc84',prod_ok:'#3ddc84',
  eval_fail:'#ff4d5e',prod_block:'#ff4d5e',rejected:'#ff4d5e',candidate:'#ff5fa2',
  sim_submit:'#e8ecf4',precheck_fail:'#ffab2e',sim_fail:'#ffab2e',error:'#ffab2e',work:'#33d1ff'};
const styleValues=new WeakMap();

function element(doc, tag, className, value) {
  const node=doc.createElement(tag);
  if (className) node.className=className;
  if (value!==undefined) node.textContent=String(value);
  return node;
}
function setText(node, value) {
  const next=String(value);
  if (node.textContent!==next) node.textContent=next;
}
function setAttribute(node, key, value) {
  const next=String(value);
  if (node.getAttribute(key)!==next) node.setAttribute(key,next);
}
function setProperty(node, key, value) {
  if (node[key]!==value) node[key]=value;
}
function setStyle(node, key, value) {
  const next=String(value);
  let values=styleValues.get(node);
  if (!values) {values=new Map();styleValues.set(node,values);}
  if (values.get(key)===next) return;
  values.set(key,next);
  if (key.startsWith('--')) {
    if (node.style.getPropertyValue(key)!==next) node.style.setProperty(key,next);
  } else if (node.style[key]!==next) node.style[key]=next;
}
function setClass(node, name, active) {
  if (node.classList.contains(name)!==active) node.classList.toggle(name,active);
}
export class Dashboard {
  constructor(doc=document) {
    this.doc=doc;
    this.state=normaliseSnapshot(null);
    this.alphaIndex=new Map();
    this.cardNodes=new Map();
    this.renderKeys=new Map();
    this.connected=false; this.disposed=false; this.openId=null; this.source=null;
    this.captions=[];this.captionNodes=[];this.captionDots=[];this.captionTexts=[];this.captionCycle=false;
    this.byId=id=>doc.getElementById(id);
    this.scene=new FactoryScene(this.byId('factory-scene'),{
      onAlpha:id=>this.openAlpha(id), onSessionHover:(session,event)=>this.sessionTooltip(session,event),
      onCaption:entry=>this.renderCaption(entry),
    });
    this.output=new OutputChart(this.byId('output-chart'));
    this.scatter=new ScatterChart(this.byId('scatter-chart'),{
      onAlpha:id=>this.openAlpha(id), onHover:(alpha,event)=>this.alphaTooltip(alpha,event),
    });
    this.buildCards(); this.buildStats(); this.buildDrawer();
    for(let i=0;i<3;i++){
      const line=element(this.doc,'span','caption-line');
      const dot=element(this.doc,'i','caption-dot'),text=element(this.doc,'span','caption-text');
      dot.setAttribute('aria-hidden','true');line.append(dot,text);
      this.captionDots.push(dot);this.captionTexts.push(text);
      this.byId('event-captions').append(line);this.captionNodes.push(line);
    }
    this.visibility=()=>{
      setClass(this.doc.documentElement,'page-hidden',this.doc.hidden);
      if (this.doc.hidden) {
        this.clockUnsubscribe?.();this.clockUnsubscribe=null;
        this.hideTooltip();
        this.captionNodes.forEach((node,index)=>setProperty(node,'className',`caption-line ${index?'caption-previous':'caption-current caption-static'}`));
      }
      else if(!this.clockUnsubscribe){this.tickClock();this.clockUnsubscribe=this.scene.secondClock.subscribe(()=>this.tickClock());}
    };
    this.keydown=event=>this.handleKey(event);
    doc.addEventListener('visibilitychange',this.visibility);
    doc.addEventListener('keydown',this.keydown);
    this.visibility();
    this.render(null);
  }

  buildCards() {
    const parent=this.byId('role-cards');
    for (const [key,title,en,color,shape] of CARD_META) {
      const node=element(this.doc,'article','role-card'); node.dataset.key=key;
      node.style.setProperty('--accent',color);
      const heading=element(this.doc,'div','card-heading');
      const avatar=createAvatar(shape,color,24); avatar.classList.add('card-avatar');
      const name=element(this.doc,'h2','card-title',title); name.append(element(this.doc,'small','',en));
      const tag=element(this.doc,'span','card-tag',key==='review'?'YOU':key==='generate'?'AI':'LOCAL');
      heading.append(avatar,name,tag);
      const body=element(this.doc,'div','card-body');
      const subtitle=element(this.doc,'span','card-subtitle');
      const number=element(this.doc,'strong','card-number');
      const value=element(this.doc,'span'), unit=element(this.doc,'small'); number.append(value,unit); body.append(subtitle,number);
      const progress=element(this.doc,'div','card-progress'), fill=element(this.doc,'span'); progress.append(fill);
      const bottom=element(this.doc,'div','card-bottom'), status=element(this.doc,'span','card-state');
      const statusText=element(this.doc,'span'), dots=element(this.doc,'span','typing-dots');
      dots.setAttribute('aria-hidden','true');
      status.append(statusText,dots);
      const message=element(this.doc,'span','card-message'); bottom.append(status,message);
      node.append(heading,body,progress,bottom); parent.append(node);
      this.cardNodes.set(key,{node,subtitle,value,unit,fill,statusText,message});
    }
  }

  renderCaption(entry) {
    if(!entry){
      this.workCaption=null;
      this.captions=[];
      this.captionNodes.forEach((node,index)=>{
        setText(this.captionTexts[index],'');setProperty(node,'title','');setProperty(node,'className','caption-line');setAttribute(node,'data-empty','true');
      });
      setAttribute(this.byId('event-captions').parentNode,'data-narrating','false');
      return;
    }
    if(entry.work){
      this.workCaption=entry.text?{kind:'work',text:String(entry.text).slice(0,300)}:null;
    }else{
      this.workCaption=null;
      this.captions.unshift({seq:entry.seq,kind:entry.kind,text:String(entry.text||'状态已更新').slice(0,300)});
      this.captions.length=Math.min(3,this.captions.length);this.captionCycle=!this.captionCycle;
    }
    const displayed=this.workCaption?[this.workCaption,...this.captions].slice(0,3):this.captions;
    this.captionNodes.forEach((node,index)=>{
      const caption=displayed[index];setText(this.captionTexts[index],caption?.text||'');setProperty(node,'title',caption?.text||'');
      setAttribute(node,'data-empty',String(!caption));setAttribute(node,'aria-hidden',String(index>0));
      setStyle(this.captionDots[index],'--caption-color',CAPTION_COLORS[caption?.kind]||'#a7b4ce');
      const enter=entry.work||this.doc.hidden||this.scene.reducedMotion?'caption-static':`caption-enter-${this.captionCycle?'a':'b'}`;
      setProperty(node,'className',`caption-line ${index?'caption-previous':`caption-current ${enter}`}`);
    });
    setAttribute(this.byId('event-captions').parentNode,'data-narrating',String(displayed.length>0));
  }

  buildStats() {
    this.stats=[];
    for (const label of ['ALPHAS','PASSED','合格最佳 S','AVG TURNOVER']) {
      const node=element(this.doc,'div','stat-item'), value=element(this.doc,'strong','', '—');
      node.append(element(this.doc,'span','',label),value); this.byId('analysis-stats').append(node); this.stats.push(value);
    }
    this.ignoredStat=element(this.doc,'div','stat-item scatter-ignored');
    this.ignoredStat.id='scatter-ignored';this.ignoredStat.hidden=true;
    this.byId('analysis-stats').append(this.ignoredStat);
  }

  buildDrawer() {
    this.drawerMetrics=[]; this.drawerFields=[];
    for (const label of ['SHARPE','FITNESS','TURNOVER']) {
      const node=element(this.doc,'div','drawer-metric'), value=element(this.doc,'strong','', '—');
      node.append(element(this.doc,'span','',label),value); this.byId('drawer-metrics').append(node); this.drawerMetrics.push(value);
    }
    for (const label of ['状态','评估','失败项','Prod','会话','市场','Sim ID','哈希','时间']) {
      const value=element(this.doc,'dd'); this.byId('drawer-fields').append(element(this.doc,'dt','',label),value); this.drawerFields.push(value);
    }
    this.byId('drawer-close').addEventListener('click',()=>this.closeDrawer());
    this.byId('drawer-backdrop').addEventListener('click',()=>this.closeDrawer());
    this.byId('copy-expression').addEventListener('click',()=>this.copyExpression());
  }

  render(input) {
    if (this.disposed) return;
    const state=normaliseSnapshot(input); this.state=state;
    const generated=Date.parse(state.generated_at);
    if (state.mode!=='demo' || !Number.isFinite(generated)) this.demoClock=null;
    else if (this.demoClock?.stamp!==state.generated_at) {
      this.demoClock={stamp:state.generated_at,epoch:generated,at:this.monotonicNow()};
    }
    this.tickClock();
    if (this.contentChanged('alpha-index',[state.alphas,state.review,state.best])) {
      this.alphaIndex=new Map([...state.alphas,...state.review,...(state.best?[state.best]:[])].map(a=>[a.id,a]));
    }
    for (const card of state.cards) {
      const entry=this.cardNodes.get(card.key);
      if (!this.contentChanged(`card-${card.key}`,[card.busy,card.subtitle,card.value,card.progress,card.unit,card.message])) continue;
      setClass(entry.node,'is-busy',card.busy);
      setText(entry.subtitle,card.subtitle); setText(entry.value,formatNumber(card.value)); setText(entry.unit,card.unit);
      setStyle(entry.fill,'transform',`scaleX(${card.progress})`);
      setText(entry.statusText,card.busy?'处理中':'空闲'); setText(entry.message,`“${card.message}”`);
      setProperty(entry.message,'title',card.message);
    }
    const {totals,goal}=state, percent=Math.round(clamp(goal.candidates/goal.target)*100);
    setText(this.byId('factory-subtitle'),`${formatNumber(totals.sessions_active)} SESSIONS MINING · ${formatNumber(totals.sims_done)} SIMS · ${formatNumber(totals.candidates)} PICKS`);
    setText(this.byId('goal-label'),`今日候选 ${formatNumber(goal.candidates)}/${formatNumber(goal.target)}`);
    setText(this.byId('goal-percent'),`${percent}%`); setStyle(this.byId('goal-fill'),'transform',`scaleX(${percent/100})`);
    setAttribute(this.byId('goal-meter'),'aria-valuenow',String(percent));
    setText(this.byId('day-label'),`WQ DAY · ${state.day.slice(5)}`);
    setText(this.byId('floor-summary'),`${totals.sessions_active} ONLINE · ${totals.sims_pending} IN FLIGHT`);
    const floorStatus=`今日已结束 ${formatNumber(state.sessions_ended)} · ${state.sessions.length?`${totals.sessions_total} 个会话 · ${totals.alphas} 个 alpha · ${totals.pending_review} 个待复核`:'等待挖掘会话加入'}`;
    setText(this.byId('floor-status'),floorStatus);setProperty(this.byId('floor-status'),'title',floorStatus);
    setText(this.byId('output-note'),state.timeline.length?`${totals.sims_done} BATCHES`:'等待第一批回测');
    setText(this.byId('analysis-count'),`${formatNumber(totals.alphas)} ALPHAS SCANNED`);
    setText(this.byId('updated-label'),state.generated_at?`UPDATED ${formatTimestamp(state.generated_at)} · 仅本机可见`:'等待第一条调用日志');
    this.output.update(state); this.scatter.update(state);
    if (this.contentChanged('stats',[state.totals.alphas,state.totals.eval_passed,state.best?.sharpe,state.alphas.map(alpha=>alpha.turnover),this.scatter.ignoredCount])) this.renderStats();
    // The placeholder frame must not consume the scene's first-snapshot cursor.
    if (this.receivedSnapshot || (input!==null && input!==undefined)) {
      this.scene.update(state); this.receivedSnapshot=true;
    }
    this.syncEnvironmentIdle();
    if (this.openId) {
      const alpha=this.alphaIndex.get(this.openId)||this.openAlphaValue;
      if (this.contentChanged('drawer',[this.openId,alpha,state.sessions])) this.updateDrawer(alpha);
    }
    if (this.connected) this.setConnection(true);
  }

  contentChanged(key, value) {
    const next=JSON.stringify(value);
    if (this.renderKeys.get(key)===next) return false;
    this.renderKeys.set(key,next);
    return true;
  }

  syncEnvironmentIdle() {
    setClass(this.doc.documentElement,'environment-idle',this.scene.environmentIdle===true);
    setClass(this.doc.documentElement,'environment-quiet',this.scene.environmentQuiet!==false);
  }

  renderStats() {
    let turnover=0, n=0;
    for (const alpha of this.state.alphas) if (numeric(alpha.turnover)!==null) {turnover+=alpha.turnover; n++;}
    const values=[formatNumber(this.state.totals.alphas),formatNumber(this.state.totals.eval_passed),
      formatMetric(this.state.best?.sharpe),n?`${(turnover/n*100).toFixed(1)}%`:'—'];
    this.stats.forEach((node,index)=>setText(node,values[index]));
    setText(this.ignoredStat,`已忽略 ${formatNumber(this.scatter.ignoredCount)} 个异常点`);
    setProperty(this.ignoredStat,'hidden',!this.scatter.ignoredCount);
  }

  setConnection(connected) {
    this.connected=connected;
    const node=this.byId('connection'), mode=this.state.mode;
    setProperty(node,'className',`connection ${connected?mode:'reconnecting'}`);
    setText(node.querySelector('span'),connected?(mode==='demo'?'DEMO':mode==='replay'?'REPLAY':'LIVE'):'RECONNECTING');
  }

  monotonicNow() {return this.doc.defaultView?.performance?.now?.() ?? Date.now();}
  tickClock() {
    this.scene.checkActivity?.();
    this.syncEnvironmentIdle();
    const epoch=this.demoClock?this.demoClock.epoch+Math.max(0,this.monotonicNow()-this.demoClock.at):Date.now();
    const now=new Date(epoch), clock=this.byId('clock');
    setText(clock,now.toLocaleTimeString('en-GB',{hour12:false})); setProperty(clock,'dateTime',now.toISOString());
    const reset=Date.parse(this.state.wq_next_reset);
    const seconds=Number.isFinite(reset)?Math.max(0,Math.ceil((reset-epoch)/1000)):null;
    const countdown=seconds===null?'—':[Math.floor(seconds/3600),Math.floor(seconds%3600/60),seconds%60]
      .map(value=>String(value).padStart(2,'0')).join(':');
    setText(this.byId('reset-countdown'),`重置 ${countdown}`);
  }

  showTooltip(value,event) {
    const node=this.byId('tooltip'); setText(node,value); node.hidden=false;
    const rect=event?.currentTarget?.getBoundingClientRect?.();
    const x=event?.clientX || rect?.left || 20, y=event?.clientY || rect?.top || 20;
    const width=globalThis.innerWidth||this.doc.documentElement.clientWidth||1000;
    const height=globalThis.innerHeight||this.doc.documentElement.clientHeight||800;
    const bounds=node.getBoundingClientRect();
    node.style.left=`${Math.max(8,Math.min(x+14,width-bounds.width-8))}px`;
    node.style.top=`${Math.max(8,Math.min(y+14,height-bounds.height-8))}px`;
  }
  hideTooltip() {this.byId('tooltip').hidden=true;}
  alphaTooltip(alpha,event) {
    if (!alpha) {this.hideTooltip(); return;}
    this.showTooltip(`${alpha.id}\n${short(alpha.expr||alpha.id,45)}\nSharpe ${formatMetric(alpha.sharpe)} · Fitness ${formatMetric(alpha.fitness)}\n${STATUS_LABELS[alpha.status]||'回测完成'}`,event);
  }
  sessionTooltip(session,event) {
    if (!session) {this.hideTooltip(); return;}
    const counts=record(session.counts);
    this.showTooltip(`${text(session.label)} · ${text(session.region,'—')} ${text(session.universe,'')}\n${text(session.phase_label)} · ${count(session.running_sims)} 批回测中\n表达式 ${count(counts.exprs)} · alpha ${count(counts.alphas)}\n评估通过 ${count(counts.eval_passed)} · 候选 ${count(counts.candidates)}`,event);
  }

  openAlpha(id) {
    const alpha=this.alphaIndex.get(id);
    if (!alpha) return;
    this.openId=id; this.openAlphaValue=alpha; this.previousFocus=this.doc.activeElement;
    this.hideTooltip(); this.updateDrawer(alpha); this.byId('drawer-overlay').hidden=false;
    this.doc.body.classList.add('drawer-open'); this.byId('factory-app').inert=true; this.byId('drawer-close').focus();
    this.scene.work.sync();
  }
  updateDrawer(alpha) {
    if (!alpha) return;
    this.openAlphaValue=alpha;
    setText(this.byId('drawer-title'),alpha.id);
    const status=this.byId('drawer-status'); setText(status,STATUS_LABELS[alpha.status]||'回测完成');
    setStyle(status,'color',STATUS_COLORS[alpha.status]||STATUS_COLORS.done);
    setText(this.byId('drawer-expression'),text(alpha.expr,'暂无表达式，等待哈希关联'));
    setProperty(this.byId('copy-expression'),'disabled',!alpha.expr);
    const values=[formatMetric(alpha.sharpe),formatMetric(alpha.fitness),numeric(alpha.turnover)===null?'—':`${(alpha.turnover*100).toFixed(1)}%`];
    this.drawerMetrics.forEach((node,index)=>setText(node,values[index]));
    const session=this.state.sessions.find(s=>s.pid===alpha.pid);
    const fields=[STATUS_LABELS[alpha.status]||alpha.status||'—',alpha.passed===true?'通过':alpha.passed===false?'未通过':'尚未评估',
      list(alpha.failed).join(' · ')||'无',formatMetric(alpha.prod),session?.label||text(alpha.session_label,alpha.pid===0?'未知会话':`PID ${alpha.pid??'—'}`),
      session?[text(session.region,'—'),text(session.universe,'—'),`D${session.delay??'—'}`].join(' · '):'—',
      text(alpha.sim),text(alpha.h),formatTimestamp(alpha.ts)];
    this.drawerFields.forEach((node,index)=>setText(node,fields[index]));
  }
  closeDrawer() {
    this.byId('drawer-overlay').hidden=true; this.doc.body.classList.remove('drawer-open'); this.byId('factory-app').inert=false;
    this.openId=null; this.openAlphaValue=null;
    this.scene.work.sync();
    if (this.previousFocus?.isConnected) this.previousFocus.focus();
  }
  handleKey(event) {
    if (!this.openId) return;
    if (event.key==='Escape') {event.preventDefault(); this.closeDrawer();}
    if (event.key==='Tab') {
      const first=this.byId('drawer-close'), last=this.byId('drawer-expression');
      if (event.shiftKey && this.doc.activeElement===first) {event.preventDefault(); last.focus();}
      else if (!event.shiftKey && this.doc.activeElement===last) {event.preventDefault(); first.focus();}
    }
  }
  async copyExpression() {
    if (!this.openAlphaValue?.expr) return;
    const button=this.byId('copy-expression');
    try {
      await globalThis.navigator.clipboard.writeText(this.openAlphaValue.expr);
      setText(button,'已复制');
    } catch {
      const range=this.doc.createRange(); range.selectNodeContents(this.byId('drawer-expression'));
      const selection=this.doc.getSelection(); selection.removeAllRanges(); selection.addRange(range);
      setText(button,'已选中，可复制');
    }
    clearTimeout(this.copyTimer); this.copyTimer=setTimeout(()=>setText(button,'复制表达式'),1800);
  }

  async connect({fetcher=globalThis.fetch, EventSourceClass=globalThis.EventSource}={}) {
    this.abort=new AbortController();
    const timeout=setTimeout(()=>this.abort.abort(),8000);
    try {
      const response=await fetcher('/api/state',{cache:'no-store',signal:this.abort.signal});
      if (!response.ok) throw new Error(`HTTP ${response.status}`);
      const input=await response.json();
      if (!this.disposed) this.render(input);
    } catch {if (!this.disposed) this.setConnection(false);}
    finally {clearTimeout(timeout);}
    if (this.disposed) return;
    try {
      this.source=new EventSourceClass('/api/stream');
      this.source.addEventListener('state',event=>{
        if (this.disposed) return;
        try {this.render(JSON.parse(event.data)); this.setConnection(true);} catch { /* Keep last valid snapshot. */ }
      });
      this.source.addEventListener('open',()=>{if (!this.disposed) this.setConnection(true);});
      this.source.addEventListener('error',()=>{if (!this.disposed) this.setConnection(false);});
    } catch {this.setConnection(false);}
  }

  destroy() {
    this.disposed=true; this.source?.close(); this.abort?.abort();
    this.clockUnsubscribe?.();this.clockUnsubscribe=null;clearTimeout(this.copyTimer);this.scene.destroy();
    this.output.destroy?.(); this.scatter.destroy?.();
    this.doc.removeEventListener('visibilitychange',this.visibility); this.doc.removeEventListener('keydown',this.keydown);
    this.hideTooltip(); this.doc.body.classList.remove('drawer-open');
  }
}

if (typeof window!=='undefined' && document.getElementById('factory-app')) {
  const dashboard=new Dashboard();
  dashboard.connect();
  window.addEventListener('pagehide',event=>{if (!event.persisted) dashboard.destroy();});
}
