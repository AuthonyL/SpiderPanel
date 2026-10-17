/* One low-frequency work clock; the narrative owns finite spider travel. */
import {SPIDER_PATROL_SECONDS} from './animation-rules.js';
import {WEB_CENTER,SCREEN_CONTENT} from './silk.js';
import {LOWER_SHIFT,RADAR_ORIGIN} from './geometry.js';
import {style} from './layers.js';
export const WORK_DISPLAY_MS=1000;
export const WORK_TYPING_MS=1000;
export const WORK_CAPTION_MS=7000;
const rows=value=>Array.isArray(value)?value.filter(item=>item&&typeof item==='object'):[];
const busy=session=>typeof session?.phase==='string'&&session.phase!=='idle'&&session.idle!==true;
const positive=value=>typeof value==='number'&&Number.isFinite(value)&&value>0;
const fraction=value=>typeof value==='number'&&Number.isFinite(value)&&value>=0&&value<=1;
const clamp=value=>Math.max(0,Math.min(1,value));
const PHASES={submitting:'提交中',evaluating:'评估中',prod:'查相关性',saving:'存候选',reading:'读结果',precheck:'预检',simulating:'等回测',thinking:'构思中'};
const STARTS={evaluating:'eval_start',prod:'prod_start',saving:'save_start',submitting:'sim_submit_start'};
const NS='http://www.w3.org/2000/svg';
function add(parent,tag,attrs={},content){const node=parent.ownerDocument.createElementNS(NS,tag);for(const [key,value]of Object.entries(attrs))node.setAttribute(key,String(value));if(content!==undefined)node.textContent=content;parent.appendChild(node);return node;}
export function reportedProgress(sim){
  if(fraction(sim.progress))return sim.progress;
  return positive(sim.children_total)&&typeof sim.children_done==='number'&&Number.isFinite(sim.children_done)?clamp(sim.children_done/sim.children_total):null;
}
const attr=(node,key,value)=>{const next=String(value);if(node?.getAttribute(key)!==next)node?.setAttribute(key,next);};
const text=(node,value)=>{const next=String(value);if(node&&node.textContent!==next)node.textContent=next;};
export function waited(seconds){const n=Math.max(0,Math.floor(seconds));return `${Math.floor(n/60)}:${String(n%60).padStart(2,'0')}`;}

export class WorkLoop {
  constructor(scene,{random=Math.random,clock=()=>Date.now()/1000}={}){
    this.scene=scene;this.win=scene.win;this.doc=scene.doc;this.random=random;this.clock=clock;
    this.active=false;this.running=false;this.unsubscribe=null;this.destroyed=false;this.pending=[];this.sessions=[];
    this.ticker=scene.secondClock;
    this.byPid=new Map();this.targets=new Map();this.handRest=new Map();this.fidget=null;
    this.nextDisplay=0;this.nextCaption=0;this.captionIndex=0;this.hasCaption=false;
    this.nextFidget=Infinity;this.anchor=null;
    this.narrating=false;
    this.batchColumns=new Map();this.savePreviews=new Map();this.phaseSince=new Map();
    this.inspections=new Map();this.inspectedAlpha=null;this.inspectionBeam=null;this.prodPulse=null;
    this.nextProd=0;this.prodAt=null;this.inspectionAt=null;this.eventStarts=new Map();this.phaseKey='';
    this.lastStartSeq=0;
    this.observer=this.win.IntersectionObserver?new this.win.IntersectionObserver(entries=>{
      for(const entry of entries)if(this.targets.has(entry.target))this.targets.set(entry.target,entry.isIntersecting);
      this.sync();
    }):null;
  }

  now(){return this.win.performance?.now?.()??Date.now();}
  get timer(){return this.unsubscribe?this.ticker.timer:null;}
  epoch(){return this.mode==='demo'&&this.anchor?this.anchor.epoch+(this.now()-this.anchor.at)/1000:this.clock();}
  visible(target){
    if(!target?.isConnected||this.doc.hidden||this.doc.body?.classList.contains('drawer-open'))return false;
    for(let el=target;el;el=el.parentNode){
      if(this.targets.get(el)===false||el.hidden||el.getAttribute?.('display')==='none'||el.getAttribute?.('visibility')==='hidden'
        ||el.style?.getPropertyValue('display')==='none'||el.style?.getPropertyValue('visibility')==='hidden')return false;
    }
    return true;
  }

  update(data){
    const displayKey=JSON.stringify([data.mode,data.day,data.sim_typical_seconds,
      rows(data.pending_sims).map(sim=>[sim.sim,sim.pid,sim.n,sim.since,sim.progress,sim.children_done,sim.children_total]),rows(data.sessions).map(session=>[session.pid,session.phase,session.idle,session.inflight])]);
    const changed=this.displayDirty||this.displayKey!==displayKey;this.displayDirty=false;this.displayKey=displayKey;
    this.mode=data.mode;
    const stamp=Date.parse(data.generated_at);
    const key=`${data.mode}:${data.day}:${data.generated_at}`;
    if(Number.isFinite(stamp)&&this.anchor?.key!==key)this.anchor={key,epoch:stamp/1000,at:this.now()};
    this.pending=rows(data.pending_sims);this.sessions=rows(data.sessions);
    this.eventStarts.clear();
    let freshStart=false;
    for(const event of rows(data.events))if(Object.values(STARTS).includes(event.kind)){
      if((event.seq??0)>this.lastStartSeq)freshStart=true;
      const key=`${event.pid}:${event.kind}`,previous=this.eventStarts.get(key);
      if(!previous||(event.seq??0)>(previous.seq??0))this.eventStarts.set(key,event);
    }
    this.lastStartSeq=Math.max(0,...rows(data.events).filter(event=>Object.values(STARTS).includes(event.kind)).map(event=>event.seq??0));
    this.typical=positive(data.sim_typical_seconds)?data.sim_typical_seconds:null;
    this.byPid.clear();
    for(const sim of this.pending){const key=String(sim.pid??0);if(!this.byPid.has(key))this.byPid.set(key,[]);this.byPid.get(key).push(sim);}
    const targets=new Set([this.scene.canvas,this.scene.cabinetProgressGroup,this.scene.cabinetLitGroup,this.scene.cabinetPacked.g,this.scene.spider.positionSurface.host,this.scene.radarDishSurface.host]);
    for(const entry of this.scene.sessionNodes.values()){
      entry.workHands=[entry.portrait.querySelector('.wq-hand-left'),entry.portrait.querySelector('.wq-hand-right')];
      targets.add(entry.surface.host);targets.add(entry.overlaySurface.host);targets.add(entry.station.miniSurface.host);
      // All ongoing work is advanced by this clock, including the first 15s.
      entry.station.ambient.setPhase(null);entry.hands.setActive(false);
      if(!this.phaseSince.has(String(entry.data.pid)))this.phaseSince.set(String(entry.data.pid),this.epoch());
    }
    for(const target of this.targets.keys())if(!targets.has(target)){this.observer?.unobserve(target);this.targets.delete(target);}
    for(const target of targets)if(!this.targets.has(target)){this.targets.set(target,true);this.observer?.observe(target);}
    for(const target of this.handRest.keys())if(!target.isConnected)this.handRest.delete(target);
    const wasActive=this.active;
    this.active=!!this.pending.length||this.sessions.some(busy);
    if(this.active&&!wasActive){this.nextFidget=this.now()+this._fidgetDelay();this.nextCaption=this.now()+WORK_CAPTION_MS;this.captionIndex=0;}
    if(!this.active){this.beforeEvents();this._clearCaption();this._resetMonitors();}
    this._reconcileBatches();this._reconcilePreviews();this._reconcileThinking();
    const phaseKey=JSON.stringify(this.sessions.map(session=>[session.pid,session.phase,session.inflight?.since,session.inflight?.alpha,session.inflight?.sim]));
    if(this.phaseKey!==phaseKey){
      this.phaseKey=phaseKey;this.nextProd=0;
      if(this.scene.narrative.workAction?.kind==='inspection')this.scene.narrative.yieldWork();
      for(const [key,value]of this.inspections){const session=this.sessions.find(row=>String(row.pid)===key);if(!session||session.phase!=='evaluating'||value.key!==this._operationKey(session))this.inspections.delete(key);}
      if(!this.sessions.some(session=>session.phase==='evaluating'))this._clearInspection();
      if(!this.sessions.some(session=>session.phase==='prod'))this._clearProd();
      if(this.active&&!freshStart)this._caption(true);
    }
    // Static text is also useful in reduced-motion, on receipt of a snapshot.
    if(!this.doc.hidden&&this.visible(this.scene.canvas)&&(changed||this.now()>=this.nextDisplay)){
      this._display(false);this.nextDisplay=this.now()+WORK_DISPLAY_MS;
    }
    this.sync();
  }

  _running(){return !this.destroyed&&!this.scene.destroyed&&this.active&&!this.doc.hidden&&!this.scene.reducedMotion&&this.visible(this.scene.canvas);}
  sync(){
    const running=this._running();
    attr(this.scene.layers.root,'data-work-active',this.active);
    if(!running){
      this.running=false;
      this.unsubscribe?.();this.unsubscribe=null;
      this.beforeEvents();return;
    }
    if(!this.running){this.running=true;this._display(false);}
    if(!this.unsubscribe)this.unsubscribe=this.ticker.subscribe(()=>this._tick());
  }
  _pendingFor(entry){return (entry.data.grouped_pids||[String(entry.data.pid)]).flatMap(pid=>this.byPid.get(String(pid))||[]);}
  _tick(){
    if(!this._running()){this.sync();return;}
    const now=this.now();
    this._display(true);this.nextDisplay=now+WORK_DISPLAY_MS;this._type();
    if(now>=this.nextCaption){this.nextCaption=now+WORK_CAPTION_MS;this._caption();}
    this._work(now);this._stepBeams(now);this._spider(now);this.sync();
  }

  _display(animate){
    const scene=this.scene,epoch=this.epoch(),step=Math.floor(this.now()/WORK_DISPLAY_MS);
    const blinking=animate&&!scene.reducedMotion;
    this._batchDisplay(epoch,blinking,step);this._thinkingDisplay(epoch,step);
    if(this.pending.length&&blinking){
      for(const group of [scene.cabinetLitGroup,scene.cabinetPacked.g])if(this.visible(group))attr(group,'opacity',step%2?'.4':'1');
    }
    for(const entry of scene.sessionNodes.values()){
      const station=entry.station;if(!this.visible(station.miniSurface.host))continue;
      const pending=this._pendingFor(entry);
      const times=pending.map(sim=>Date.parse(sim.since)/1000).filter(Number.isFinite);
      const since=times.length?Math.min(...times):null;
      if(pending.length&&(!busy(entry.data)||entry.data.phase==='simulating'||entry.data.aggregate)){
        for(const [phase,panel]of Object.entries(station.panels))attr(panel,'display',phase==='simulating'?'inline':'none');
        attr(station.chart,'display','none');attr(station.simDecor,'display','none');attr(station.workElapsed,'display','inline');
        const elapsed=since===null?null:Math.max(0,epoch-since),actual=pending.map(reportedProgress).filter(value=>value!==null);
        const progress=actual.length?actual.reduce((n,value)=>n+value,0)/actual.length:null;
        const overdue=progress===null&&this.typical!==null&&elapsed!==null&&elapsed>=this.typical;
        text(station.workElapsed,elapsed===null?'等待回测结果':`已等 ${waited(elapsed)}`);
        text(station.phase,overdue?'回测 · 等待中':'等回测');
        attr(station.progress,'data-waiting',overdue);
        attr(station.progress,'data-progress-source',progress!==null?'actual':this.typical!==null?'estimate':'unknown');
        attr(station.progress,'display',progress!==null||this.typical!==null&&elapsed!==null?'inline':'none');
        const position=blinking?Math.abs((step%12)-6)/6:0;
        attr(station.progress,'x',overdue?(7+position*54).toFixed(2):7);
        attr(station.progress,'width',overdue?18:(72*(progress??Math.min(.95,Math.max(0,(elapsed??0)/(this.typical||1))))).toFixed(2));
      }else{
        this._resetMonitor(station,entry);
        if(!blinking||!busy(entry.data))continue;
        if(entry.data.phase==='prod')attr(station.panels.prod.querySelector('.wq-radar-sweep'),'transform',`rotate(${step%4*90} 0 0)`);
        if(entry.data.phase==='evaluating'){
          station.panels.evaluating.querySelectorAll('.wq-eval-bar').forEach((bar,index)=>attr(bar,'opacity',(index+step)%3===0?'1':'.35'));
        }
      }
    }
    if(blinking)this._writePreviews(step);
  }

  _resetMonitor(station,entry){
    if(station.workElapsed.getAttribute('display')==='none')return;
    attr(station.workElapsed,'display','none');attr(station.simDecor,'display','inline');
    attr(station.progress,'display','inline');attr(station.progress,'data-waiting','false');attr(station.progress,'x',7);
    text(station.phase,entry?.data?.phase_label||'');
    for(const [phase,panel]of Object.entries(station.panels))attr(panel,'display',phase===(entry?.data?.phase||'idle')?'inline':'none');
    attr(station.chart,'display',entry&&!station.panels[entry.data.phase]?'inline':'none');
  }
  _resetMonitors(){
    for(const entry of this.scene.sessionNodes.values())this._resetMonitor(entry.station,entry);
    for(const station of this.scene.stations)if(![...this.scene.sessionNodes.values()].some(entry=>entry.station===station))this._resetMonitor(station);
  }

  _type(){
    const frame=Math.floor(this.now()/WORK_TYPING_MS)%2;
    for(const entry of this.scene.sessionNodes.values()){
      if(!busy(entry.data)||!this.visible(entry.surface.host))continue;
      entry.workHands.forEach((hand,index)=>{
        if(!this.handRest.has(hand))this.handRest.set(hand,hand.getAttribute('transform'));
        attr(hand,'transform',(frame+index)%2?'translate(-1 -2)':'translate(0 0)');
      });
    }
  }

  _caption(immediate=false){
    if(this.scene.narrative.working||!immediate&&this.now()-this.scene.lastEventAt<WORK_CAPTION_MS)return;
    const messages=[];
    for(const session of this.sessions){
      const batches=this.byPid.get(String(session.pid))||[],label=String(session.label||`会话 ${session.pid??0}`);
      if(batches.length&&(!busy(session)||session.phase==='simulating')){
        const times=batches.map(sim=>Date.parse(sim.since)/1000).filter(Number.isFinite);
        const elapsed=times.length?Math.max(0,this.epoch()-Math.min(...times)):null;
        let message=`${label} 回测中${elapsed===null?'':` · 已等 ${waited(elapsed)}`}`;
        const actual=batches.map(reportedProgress).filter(value=>value!==null);
        if(actual.length)message+=` · 真实进度 ${Math.round(100*actual.reduce((n,value)=>n+value,0)/actual.length)}%`;
        else if(this.typical!==null&&elapsed!==null)message+=elapsed>=this.typical?' · 超过典型用时，继续等待':` · 预计还需约 ${Math.max(1,Math.ceil((this.typical-elapsed)/60))} 分钟`;
        messages.push(message);
      }else if(busy(session))messages.push(`${label} · ${session.phase_label||PHASES[session.phase]||'工作中'}`);
    }
    if(this.pending.length)messages.push(`${this.pending.length} 批回测进行中 · ${this.pending.reduce((n,sim)=>n+(Number.isFinite(sim.n)?Math.max(0,sim.n):0),0)} 条表达式`);
    if(messages.length){this.scene.onCaption({work:true,kind:'work',text:messages[this.captionIndex++%messages.length]});this.hasCaption=true;}
  }
  _clearCaption(){if(this.hasCaption){this.scene.onCaption({work:true,text:''});this.hasCaption=false;}}

  _operationKey(session){const flight=session.inflight||{};return `${session.phase}:${flight.since||''}:${flight.sim||''}:${flight.alpha||''}`;}
  _ids(session){
    const flight=session.inflight||{},recent=this.eventStarts.get(`${session.pid}:${STARTS[session.phase]}`);
    // An older concurrent call can become current after a newer call ends.
    // Its explicit subject takes precedence over the latest start event.
    const start=recent&&!['sim','alpha'].some(key=>flight[key]&&recent[key]&&flight[key]!==recent[key])?recent:null;
    const ids=[];
    if(typeof flight.alpha==='string')ids.push(flight.alpha);
    for(const value of [flight.alphas,start?.alphas])if(Array.isArray(value))for(const id of value)if(typeof id==='string'&&id&&!ids.includes(id))ids.push(id);
    const sim=flight.sim||start?.sim;
    if(!ids.length&&sim)for(const [id,alpha]of this.scene.alphaLookup)if(alpha.sim===sim)ids.push(id);
    if(!ids.length&&typeof flight.alpha==='string')ids.push(flight.alpha);
    if(!ids.length&&typeof start?.alpha==='string')ids.push(start.alpha);
    return ids.filter(id=>this.scene.networkNodes.has(id)).slice(0,8);
  }
  _reconcileBatches(){
    const keep=new Set(),width=40/Math.max(1,this.pending.length);
    this.pending.forEach((sim,index)=>{
      const key=String(sim.sim??`${sim.pid}:${index}`);keep.add(key);let column=this.batchColumns.get(key);
      if(!column){const g=add(this.scene.cabinetProgressGroup,'g',{'data-sim':key});
        column={g,cells:Array.from({length:8},()=>add(g,'rect',{'data-lit':'false',fill:'#263d48'}))};this.batchColumns.set(key,column);}
      column.sim=sim;
      column.cells.forEach((cell,row)=>{attr(cell,'x',3+index*width);attr(cell,'y',4+(7-row)*4);attr(cell,'width',Math.max(.05,width*.72));attr(cell,'height',2.8);});
    });
    for(const [key,column]of this.batchColumns)if(!keep.has(key)){column.g.remove();this.batchColumns.delete(key);}
    attr(this.scene.cabinetProgressGroup,'display',this.pending.length?'inline':'none');
    if(this.pending.length){attr(this.scene.cabinetLampGroup,'display','none');attr(this.scene.cabinetPacked.g,'display','none');}
  }
  _batchDisplay(epoch,blinking=false,step=0){
    if(!this.visible(this.scene.cabinetProgressGroup))return;
    for(const column of this.batchColumns.values()){
      const actual=reportedProgress(column.sim),since=Date.parse(column.sim.since)/1000;
      const estimate=actual===null&&this.typical!==null&&Number.isFinite(since)?Math.min(.95,Math.max(0,(epoch-since)/this.typical)):0;
      const lit=Math.floor(8*(actual??estimate)+1e-8);
      attr(column.g,'data-progress-source',actual!==null?'actual':this.typical!==null?'estimate':'unknown');
      column.cells.forEach((cell,index)=>{attr(cell,'data-lit',index<lit);attr(cell,'fill',index<lit?'#33d1ff':'#263d48');attr(cell,'opacity',blinking&&index<lit&&step%2?'.45':'1');});
    }
  }
  _reconcileThinking(){
    for(const entry of this.scene.sessionNodes.values()){
      const thinking=busy(entry.data)&&entry.data.phase==='thinking';
      if(thinking){entry.expressionMotion.stop();attr(entry.bubble,'class','wq-bubble');attr(entry.bubble,'opacity',1);entry.workThinking=true;}
      else if(entry.workThinking){attr(entry.bubble,'opacity',0);entry.setBubble(entry.lastExpression||'');entry.workThinking=false;}
    }
    const pids=new Set(this.sessions.map(session=>String(session.pid)));
    for(const key of this.phaseSince.keys())if(!pids.has(key))this.phaseSince.delete(key);
  }
  _thinkingDisplay(epoch,step){
    for(const entry of this.scene.sessionNodes.values()){
      if(!entry.workThinking||!this.visible(entry.station.miniSurface.host))continue;
      const stamp=Date.parse(entry.data.since||entry.data.phase_since||entry.data.last_seen||entry.data.inflight?.since)/1000;
      const since=Number.isFinite(stamp)?stamp:this.phaseSince.get(String(entry.data.pid))??epoch;
      text(entry.station.thinkingElapsed,`构思中 ${waited(epoch-since)}`);
      if(this.visible(entry.overlaySurface.host))entry.setBubble(`构思中${'.'.repeat(step%4)}`);
    }
  }
  _reconcilePreviews(){
    const keep=new Set();
    for(const session of this.sessions){
      if(!busy(session)||session.phase!=='saving')continue;
      const key=String(session.pid);keep.add(key);let preview=this.savePreviews.get(key);
      if(!preview){
        const g=this.doc.createElementNS(NS,'g');attr(g,'data-work-preview','saving');
        add(g,'path',{d:'M0 0H53L62 9V34H0Z',fill:'#e6d599',stroke:'#ad965d','stroke-width':1});
        add(g,'text',{x:4,y:10,'font-size':5,fill:'#574921'},String(session.label||`会话 ${session.pid}`).slice(0,10));
        const writing=add(g,'path',{d:'M5 17H15',stroke:'#705d32','stroke-width':1.2,fill:'none'});
        const pencil=add(g,'path',{d:'M31 28 42 17 45 20 34 31Z',fill:'#ffb66c'});
        const surface=this.scene.layers.mount(g,{left:-4,top:-4,width:74,height:43},{parent:this.scene.noteLayer,local:true,kind:'saving-preview'});
        preview={g,writing,pencil,surface};this.savePreviews.set(key,preview);
      }
      preview.surface.move(916+(keep.size-1)%2*74,167+LOWER_SHIFT+Math.floor((keep.size-1)/2)*38);
    }
    for(const [key,preview]of this.savePreviews)if(!keep.has(key)){preview.surface.remove();this.savePreviews.delete(key);}
  }
  _writePreviews(step){
    for(const preview of this.savePreviews.values()){
      if(!this.visible(preview.surface.host))continue;
      const frame=step%4;attr(preview.writing,'d',`M5 17H${15+frame*11}${frame>1?'M5 23H'+(12+(frame-2)*16):''}`);
      attr(preview.pencil,'transform',`translate(${frame*3} ${frame%2?-3:0})`);
    }
  }
  _clearInspection(){this.inspectionBeam?.remove();this.inspectionBeam=null;this.inspectedAlpha=null;this.inspectionAt=null;}
  _inspect(id){
    if(!this._running()||!this.visible(this.scene.spider.positionSurface.host)||this.scene.narrative.working||!this.scene.networkNodes.has(id))return;
    this._clearInspection();this.inspectedAlpha=id;
    const spider=this.scene.spider,target=this.scene.web.position(id),position=spider.positionSurface.positionAt();
    spider.attend(true,target);
    const g=this.doc.createElementNS(NS,'g');add(g,'path',{d:`M${position.x} ${position.y-5}L${target.x} ${target.y}`,stroke:'#b4f5ff','stroke-width':1,opacity:.8});
    add(g,'ellipse',{cx:target.x,cy:target.y,rx:9,ry:5,fill:'none',stroke:'#a4eefe','stroke-width':.9});
    this.inspectionBeam=this.scene.layers.mount(g,{left:SCREEN_CONTENT.left,top:SCREEN_CONTENT.top,width:SCREEN_CONTENT.right-SCREEN_CONTENT.left,height:SCREEN_CONTENT.bottom-SCREEN_CONTENT.top},{parent:this.scene.layers.webClip,kind:'inspection-beam'});
    attr(this.inspectionBeam.host,'data-alpha',id);
    this.inspectionAt=this.now();this.inspectionBeam.setOpacity(.85);
  }
  _clearProd(){
    this.prodPulse?.remove();this.prodPulse=null;this.prodAt=null;
    const dish=this.scene.radarDishSurface;
    dish.stop();style(dish.motion,'transform','none');dish.move(RADAR_ORIGIN.x,RADAR_ORIGIN.y,-32);
  }
  _prod(id){
    if(!id||!this.visible(this.scene.radarDishSurface.host))return;
    const target=this.scene.web.position(id),origin=RADAR_ORIGIN;
    const dish=this.scene.radarDishSurface;
    const angle=Math.atan2(target.x-origin.x,-(target.y-origin.y))*180/Math.PI;
    // A work tick paints one settled heading. Restarting a finite turn on
    // successive ticks would keep Chrome presenting frames between batches.
    dish.move(origin.x,origin.y,angle);
    if(this.prodPulse?.host.getAttribute('data-alpha')!==id){
      this.prodPulse?.remove();const g=this.doc.createElementNS(NS,'g');
      add(g,'path',{d:`M${origin.x} ${origin.y}L${target.x} ${target.y}`,stroke:'#ae91ff','stroke-width':1.1,'stroke-dasharray':'5 8',fill:'none'});
      add(g,'ellipse',{cx:target.x,cy:target.y,rx:15,ry:8,stroke:'#ae91ff','stroke-width':1.2,fill:'none'});
      this.prodPulse=this.scene.layers.mount(g,{left:Math.min(target.x,origin.x)-17,top:target.y-10,width:Math.abs(origin.x-target.x)+34,height:origin.y-target.y+22},{parent:this.scene.effectLayer,kind:'work-prod-pulse'});
      attr(this.prodPulse.host,'data-alpha',id);
    }
    this.prodAt=this.now();
  }
  _stepBeams(now){
    // These are samples, not opacity animations: no WAAPI/CSS timeline, no
    // compositor lease and no completion callback between shared seconds.
    for(const [surface,at,levels]of [[this.prodPulse,this.prodAt,[.75,.3,0]],
      [this.inspectionBeam,this.inspectionAt,[.85,.5,0]]]){
      if(surface&&at!==null&&this.visible(surface.host))
        surface.setOpacity(levels[Math.min(levels.length-1,Math.floor(Math.max(0,now-at)/WORK_DISPLAY_MS))]);
    }
  }
  _work(now){
    const scene=this.scene;
    this._reconcilePreviews();
    const prod=this.sessions.find(session=>busy(session)&&session.phase==='prod');
    if(prod&&now>=this.nextProd){this.nextProd=now+3000;this._prod(this._ids(prod)[0]);}
    // Radar and writing belong to other desks, so they can run alongside a
    // capture or sorting job. Only spider travel needs the serial lease.
    if(scene.narrative.working)return;
    if(scene.narrative.workAction||!this.visible(scene.spider.positionSurface.host))return;
    for(const session of this.sessions){
      if(!busy(session)||session.phase!=='evaluating')continue;
      const ids=this._ids(session);if(!ids.length)continue;
      const key=String(session.pid),operation=this._operationKey(session);
      let inspection=this.inspections.get(key);
      if(!inspection||inspection.key!==operation){inspection={key:operation,index:0,next:0};this.inspections.set(key,inspection);}
      if(now<inspection.next)continue;
      const id=ids[inspection.index%ids.length],origin=scene.spider.positionSurface.positionAt(now),cocoon=scene.web.position(id);
      const dx=cocoon.x-WEB_CENTER.x,dy=cocoon.y-WEB_CENTER.y,length=Math.hypot(dx,dy)||1;
      const target=scene.spider.centerAt({x:WEB_CENTER.x+dx*Math.max(0,length-30)/length,y:WEB_CENTER.y+dy*Math.max(0,length-30)/length});
      if(Math.hypot(origin.x-target.x,origin.y-target.y)<1){this._inspect(id);}
      else {
        if(!scene.narrative.startWorkAction({kind:'inspection',target,onfinish:()=>this._inspect(id)}))return;
        scene.narrative.workAction.alpha=id;
      }
      inspection.next=now+3500;inspection.index++;return;
    }
  }

  _fidgetDelay(){const [low,high]=SPIDER_PATROL_SECONDS;return 1000*(low+Math.min(1,Math.max(0,this.random()))*(high-low));}
  _spider(now){
    const scene=this.scene;
    if(scene.narrative.working){this.narrating=true;return;}
    if(this.narrating){this.narrating=false;this.nextFidget=now+this._fidgetDelay();}
    if(scene.narrative.workAction||!this.visible(scene.spider.positionSurface.host)||this.sessions.some(session=>session.phase==='evaluating'))return;
    if(now<this.nextFidget)return;
    const origin={...scene.spider.positionSurface.positionAt(now)},hub=scene.spider.centerAt(WEB_CENTER),dx=origin.x-hub.x,dy=origin.y-hub.y,length=Math.hypot(dx,dy);
    // Stay on the current silk; the hub uses its horizontal spoke.
    const target=scene.spider.centerAt(length>1?{x:origin.x-dx/length*Math.min(22,length*.4),y:origin.y-dy/length*Math.min(22,length*.4)}:{x:origin.x+22,y:origin.y});
    // Measure the quiet interval from arrival, not departure. Otherwise the
    // return journey consumes part of the promised 20–30 seconds of rest.
    if(scene.narrative.startWorkAction({kind:'patrol',target,returnTo:origin,
      onfinish:()=>{this.nextFidget=this.now()+this._fidgetDelay();}}))this.nextFidget=Infinity;
  }
  _resetFidget(){
    if(!this.fidget)return;
    for(const {target,original}of this.fidget.items){if(original===null)target.removeAttribute('transform');else attr(target,'transform',original);}
    this.fidget=null;
  }
  beforeEvents(){
    this.nextFidget=this.now()+this._fidgetDelay();
    this.scene.narrative?.yieldWork();this._clearInspection();this._clearProd();
    this._resetFidget();
    for(const [target,value]of this.handRest){if(!target.isConnected)continue;if(value===null)target.removeAttribute('transform');else attr(target,'transform',value);}
    this.handRest.clear();
  }
  destroy(){
    if(this.destroyed)return;this.destroyed=true;this.unsubscribe?.();this.unsubscribe=null;
    this.beforeEvents();this.observer?.disconnect();this.targets.clear();this.byPid.clear();this.pending=[];this.sessions=[];
    for(const column of this.batchColumns.values())column.g.remove();this.batchColumns.clear();
    for(const preview of this.savePreviews.values())preview.surface.remove();this.savePreviews.clear();
  }
}
