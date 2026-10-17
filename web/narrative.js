import {WEB_CENTER,routePoint,SCREEN_CONTENT} from './silk.js';
import {CAPTURE_CENTER,capturePoint,LOWER_SHIFT,RADAR_EMITTER,SHREDDER_ORIGIN,lowerPoint} from './geometry.js';
import {planSilkTravel} from './motion.js';
import {style} from './layers.js';

const NS='http://www.w3.org/2000/svg';
const SERIAL=new Set(['sim_done','eval_pass','eval_fail','prod_ok','prod_block','candidate','rejected']);
const PARALLEL=new Set(['sim_submit','precheck_fail','sim_fail','error']);
const STARTS=new Set(['sim_submit_start','eval_start','prod_start','save_start']);
const clamp=t=>Math.max(0,Math.min(1,Number.isFinite(t)?t:0));
const smooth=t=>{const p=clamp(t);return p*p*(3-2*p);};
const lerp=(a,b,t)=>({x:a.x+(b.x-a.x)*t,y:a.y+(b.y-a.y)*t});
const arc=(a,b,c,t)=>{const q=1-t;return{x:q*q*a.x+2*q*t*b.x+t*t*c.x,y:q*q*a.y+2*q*t*b.y+t*t*c.y};};
const idsOf=event=>(Array.isArray(event.alphas)?event.alphas:typeof event.alpha==='string'?[event.alpha]:[]).filter(id=>typeof id==='string'&&id).slice(0,8);
const count=(value,fallback=1)=>typeof value==='number'&&Number.isFinite(value)?Math.min(8,Math.max(1,Math.floor(value))):fallback;
function add(parent,tag,attrs={},content){
  const node=parent.ownerDocument.createElementNS(NS,tag);
  for(const [key,value]of Object.entries(attrs))node.setAttribute(key,String(value));
  if(content!==undefined)node.textContent=String(content);
  parent.appendChild(node);return node;
}
function place(particle,position,angle=0){
  if(particle.trajectory){particle.surface.stop();particle.trajectory=null;style(particle.surface.motion,'transform','none');}
  particle.position=position;particle.surface.move(position.x,position.y,angle);
}
function opacity(particle,value){particle.surface.setOpacity(value);}
function phaseLabel(job,value){if(job.g.getAttribute('data-phase')!==value)job.g.setAttribute('data-phase',value);}
function paintPaper(parent,kind,content){
  const g=add(parent,'g',{class:kind});
  add(g,'rect',{x:-29,y:-8,width:58,height:17,rx:1,fill:'#e5eaf1',stroke:'#8597b4','stroke-width':.65});
  add(g,'path',{d:'M-23 4H23M18-8V-2H29',fill:'none',stroke:'#96a6b9','stroke-width':.55});
  add(g,'text',{x:-24,y:0,fill:'#25364a','font-size':4.8},String(content||'ALPHA EXPRESSION').slice(0,14));
  return g;
}

/** One spider action at a time; papers and cabinet failures have their own lane. */
export class FactoryNarrative {
  constructor(scene){
    this.scene=scene;this.win=scene.win;this.queue=[];this.parallel=[];this.pending=[];this.active=null;
    this.frame=null;this.timer=null;this.lastDraw=-Infinity;this.coalesced=0;this.hiddenNotes=new Set();this.disposed=false;
    this.relaxUntil=null;this.flowVelocity=null;
    this.workAction=null;
  }
  get effects(){return this.active?[this.active,...this.parallel]:this.parallel;}
  get working(){return Boolean(this.active||this.queue.length||this.parallel.length||this.pending.length||this.relaxUntil!==null);}
  now(){return this.win.performance?.now?.()??Date.now();}
  _sprite(job,node,box={left:-15,top:-15,width:30,height:30},options={}){
    const initial=node.getAttribute('opacity');node.removeAttribute('opacity');
    for(const el of [node,...node.querySelectorAll('*')])el.removeAttribute('filter');
    const surface=this.scene.layers.mount(node,box,{parent:job.g,local:true,...options});
    if(initial!==null)surface.setOpacity(initial);
    if(options.glow)surface.glow(options.glow);
    job.surfaces.push(surface);return surface;
  }
  // Each flight uses one small bounded bitmap. Its sampled curve is uploaded
  // once; the compositor advances transform/opacity without JS style writes.
  _fly(job,particle,trajectory,duration,delay=0){
    particle.surface.stop();particle.surface.move(0,0);style(particle.surface.motion,'transform','none');
    const start=job.start+delay;
    if(!particle.positionGetter){
      let point=particle.position||{x:0,y:0};
      Object.defineProperty(particle,'position',{get:()=>particle.trajectory?particle.trajectory(clamp((this.now()-particle.flightStart)/particle.flightDuration)).point:point,set:value=>{point=value;},configurable:true});
      particle.positionGetter=true;
    }
    particle.trajectory=trajectory;particle.flightStart=start;particle.flightDuration=duration;
    const frames=Array.from({length:41},(_,i)=>{
      const t=i/40,{point,angle=0,scale=1,opacity=1}=trajectory(t);
      return {offset:t,transform:`translate(${point.x}px,${point.y}px) rotate(${angle}deg) scale(${scale})`,opacity};
    });
    particle.surface.setOpacity(frames.at(-1).opacity);
    const animation=particle.surface.play(frames,{duration,delay,fill:'both'});
    if(animation)animation.currentTime=Math.max(0,this.now()-job.start);
  }
  _need(job){
    if(job.kind==='sim_done'||job.kind==='sim_submit')return count(job.n,job.ids?.length||job.exprs?.length||1);
    if(job.kind==='prod_block')return 3;
    if(job.kind==='prod_ok'||job.kind==='candidate')return 2;
    return PARALLEL.has(job.kind)?3:1;
  }
  _room(job){return this.effects.reduce((n,item)=>n+(item.surfaces?.length||0),0)+this._need(job)<=12;}
  _defer(event){if(this.pending.length<8)this.pending.push(event);else this.coalesced++;}
  _drainParallel(now){
    while(this.pending.length&&this._room(this.pending[0]))this._startParallel(this.pending.shift(),now);
  }
  _dispose(job){for(const surface of job.surfaces||[])surface.remove();job.g?.remove();}
  _caption(event,message){
    const session=this.scene.sessionLookup?.get(String(event.pid))||this.scene.sessionNodes.get(String(event.pid))?.data;
    const name=session?.label||(event.pid===0?'未知会话':`会话 ${event.pid??'—'}`);
    const id=idsOf(event)[0]||event.alpha||'Alpha';
    const alpha=this.scene.alphaLookup?.get(String(id))||this.scene.networkNodes.get(String(id))?.data;
    const wording={
      sim_submit_start:`${name} 开始提交回测 ${event.n??'?'} 条表达式`,
      eval_start:`${name} 开始评估 ${event.n??idsOf(event).length} 个 alpha`,
      prod_start:`${name} 开始查相关性 ${id}`,
      save_start:`${name} 开始存候选 ${id}`,
      sim_submit:`${name} 提交 ${event.n??event.exprs?.length??1} 条表达式 → 送入回测`,
      sim_done:`蜘蛛捕获 ${event.n??(idsOf(event).length||1)} 个 alpha`,
      eval_pass:`${id} 评估通过 → PASS 分拣丝`,
      eval_fail:`${id} 评估未通过 → 淘汰丝`,
      prod_ok:`${id} 相关性通过 · Prod ${typeof alpha?.prod==='number'?alpha.prod.toFixed(2):'—'}`,
      prod_block:`${id} 被相关性拦截 · Prod ${typeof alpha?.prod==='number'?alpha.prod.toFixed(2):'—'}`,
      candidate:`${id} → 等你复核`,rejected:`${id} 本地检查未通过 → 淘汰丝`,
      precheck_fail:`${name} 预检未通过 → 退回 → 碎纸机`,sim_fail:`${name} 回测失败 → 纸团送入碎纸机`,
      error:`${name} 提交或工具出错 → ${String(event.text||'检查失败').slice(0,90)}`,
    };
    this.scene.onCaption({seq:event.seq,kind:event.kind,text:message||wording[event.kind]||event.text||'状态已更新'});
  }
  enqueue(events){
    if(this.disposed)return;
    if(events.length)this.yieldWork();
    for(const event of events)if(STARTS.has(event.kind))this._caption(event);
    const serial=events.filter(event=>SERIAL.has(event.kind));
    if(serial.length+this.queue.length+(this.active?1:0)>12){
      const merged=serial.length+this.queue.length+(this.active?.merged||(this.active?1:0));
      if(this.active?.travel)this._bodyPose(this.active,this.now());
      if(this.active)this._settle(this.active);
      for(const job of this.queue)this._settle(job);
      this.active=null;this.queue=[];
      for(const id of [...this.hiddenNotes])this._revealNote(id);
      for(const note of this.scene.noteNodes.values())note.surface.animate('');
      this.scene.spider.rest({atCurrent:true});this.relaxUntil=this.now()+300;this.scene.web.settle();this.coalesced+=merged;
      const last=serial.at(-1);
      this.queue.push({kind:'summary',seq:last?.seq,pid:last?.pid,ids:[],merged});
      for(const event of events)if(PARALLEL.has(event.kind))this._defer(event);
      this._drainParallel(this.now());this._next(this.now());this._schedule();return;
    }
    for(const event of events){
      if(PARALLEL.has(event.kind)){
        this._defer(event);
      }else if(SERIAL.has(event.kind)){
        const ids=idsOf(event),job={...event,ids};
        if(!ids.length&&event.kind==='sim_done'){
          const matches=[...this.scene.networkNodes.values()].filter(entry=>!event.sim||entry.data.sim===event.sim);
          job.ids=matches.slice(0,count(event.n,8)).map(entry=>String(entry.data.id));
        }
        this.scene.web.beginProcessing(job.ids);
        if(job.kind==='sim_done')this.scene.web.hold(job.ids);
        if(job.kind==='candidate')for(const id of job.ids){this.hiddenNotes.add(id);this.scene.noteNodes.get(id)?.surface.setOpacity(0);}
        this.queue.push(job);
      }
    }
    this._drainParallel(this.now());this._next(this.now());this._schedule();
  }
  _next(now){
    if(this.active||!this.queue.length||!this._room(this.queue[0]))return;
    const job=this.queue.shift();job.start=now;
    job.g=this.scene.layers.group(job.kind,this.scene.effectLayer);job.g.setAttribute('data-effect',job.kind);
    job.particles=[];job.surfaces=[];this.active=job;
    if(job.kind==='summary'){
      job.duration=650;
      this._caption(job,`${job.merged} 个积压事件合并处理 · 状态已同步`);
      const node=add(job.g,'g');for(let i=0;i<8;i++)add(node,'circle',{cx:Math.cos(i*Math.PI/4)*40,cy:Math.sin(i*Math.PI/4)*23,r:2.7,fill:'#cfe8ff'});
      const particle={node,surface:this._sprite(job,node,{left:-46,top:-30,width:92,height:60})};job.particles.push(particle);
      this._fly(job,particle,t=>({point:WEB_CENTER,scale:1-t*.8,opacity:1-t}),650);
      return;
    }
    if(job.kind==='sim_done'){
      job.n=count(job.n,job.ids.length||1);job.duration=Infinity;job.step=0;
      this.scene.web.hold(job.ids);
      for(let i=0;i<job.n;i++){
        const id=job.ids[i],edge=this.scene.spider.targetAt(capturePoint(i));
        const node=add(job.g,'g',{class:'wq-event-ball','data-alpha':id||'',opacity:0});
        add(node,'circle',{r:4.5,fill:'#a2edff'});
        add(node,'circle',{r:2,fill:'#e7fbff'});
        const particle={node,surface:this._sprite(job,node,undefined,{glow:'#33d1ff'}),id,edge,position:{...this.scene.cabinetOutput},attached:false,received:false};job.particles.push(particle);
        this._fly(job,particle,t=>({point:arc(this.scene.cabinetOutput,{x:340,y:WEB_CENTER.y+32-i*3},edge,smooth(t))}),750,i*80);
      }
    }else{
      job.duration=job.kind==='prod_ok'?1300:2000;
      const id=job.ids[0],position=this.scene.spider.targetAt(this.scene.web.position(id));
      job.origin={...position};
      if(job.kind.startsWith('prod_')){
        const fill=job.kind==='prod_block'?'#ff4d5e':'#3ddc84';
        job.beam=add(job.g,'path',{class:'wq-prod-beam',d:`M${RADAR_EMITTER.x} ${RADAR_EMITTER.y}Q920 ${250+LOWER_SHIFT} ${position.x} ${position.y}`,fill:'none',stroke:fill,'stroke-width':2.4,'stroke-dasharray':'8 5'});
        job.beamSurface=this._sprite(job,job.beam,{left:position.x-8,top:position.y-8,width:1090-position.x,height:504+LOWER_SHIFT-position.y},{local:false});
        const rings=add(job.g,'g');job.rings=[0,1,2].map(i=>add(rings,'ellipse',{cx:0,cy:0,rx:18+i*18,ry:11+i*11,fill:'none',stroke:fill,'stroke-width':1.6,opacity:1-i*.22}));
        const ringParticle={node:rings,surface:this._sprite(job,rings,{left:-65,top:-44,width:130,height:88})};job.ringSurfaces=[ringParticle.surface];
        this._fly(job,ringParticle,t=>({point:RADAR_EMITTER,scale:.2+t*.9,opacity:1-t}),1300);
        job.beamSurface.play([{opacity:.8},{offset:.85,opacity:.8},{opacity:0}],{duration:1300});
        this.scene.web.tint(id,fill);
      }
      if(job.kind!=='prod_ok'){
        this.scene.web.hold(job.ids);
        const fill=job.kind==='candidate'?'#ff5fa2':job.kind==='eval_pass'?'#4f7cff':'#ff4d5e';
        const node=add(job.g,'g',{class:'wq-sort-cocoon'});
        add(node,'ellipse',{rx:5.3,ry:3.8,fill,stroke:'#deedff','stroke-width':.8});
        add(node,'path',{d:'M-4-1 4 1M-3 2 3-2',stroke:'#fff','stroke-width':.6,opacity:.65});
        const particle={node,surface:this._sprite(job,node,undefined,{glow:fill}),id,position};place(particle,position);job.particles.push(particle);
        if(job.kind==='candidate'){
          job.branch=add(job.g,'path',{fill:'none',stroke:'#ff5fa2','stroke-width':1,'stroke-opacity':.35});
          this._sprite(job,job.branch,{left:866,top:117+LOWER_SHIFT,width:220,height:130},{local:false});
        }
      }
    }
    if(job.kind==='sim_done')this._beginBody(job,this.scene.spider.centerAt(CAPTURE_CENTER),now);
    else if(job.kind!=='prod_ok'){
      const origin=job.origin,dx=origin.x-WEB_CENTER.x,dy=origin.y-WEB_CENTER.y,length=Math.hypot(dx,dy)||1;
      job.near=this.scene.spider.centerAt({x:WEB_CENTER.x+dx*Math.max(0,length-39)/length,y:WEB_CENTER.y+dy*Math.max(0,length-39)/length});
      job.angle=Math.atan2(dx,-dy);job.duration=Infinity;this._beginBody(job,job.near,now);
    }
    if(job.kind==='prod_ok')this.scene.spider.attend(true,this._lookTarget(job));
    this._caption(job);
  }
  _startParallel(event,now){
    const g=this.scene.layers.group(event.kind,this.scene.effectLayer);g.setAttribute('data-effect',event.kind);
    const job={...event,g,start:now,particles:[],surfaces:[],duration:1900};
    const source=this.scene.sessionPositions.get(String(event.pid))||lowerPoint(600,360);job.source=source;
    if(event.kind==='sim_submit'){
      const n=count(event.n,event.exprs?.length||1);job.duration=1100+(n-1)*80;
      for(let i=0;i<n;i++){
        const node=paintPaper(g,'wq-submit-paper',event.exprs?.[i]||event.exprs?.[0]);
        const particle={node,surface:this._sprite(job,node,{left:-36,top:-18,width:72,height:36}),offset:i*80,source:{x:source.x+(i%3-1)*8,y:source.y+i%2*4}};job.particles.push(particle);
        this._fly(job,particle,t=>{const p=smooth(t);return{point:arc(particle.source,{x:(particle.source.x+this.scene.cabinetIntake.x)/2,y:Math.min(particle.source.y,this.scene.cabinetIntake.y)-100},this.scene.cabinetIntake,p),angle:Math.sin(p*Math.PI)*-18,opacity:t>=1?0:1};},1100,i*80);
      }
    }else{
      const failed=event.kind==='sim_fail',shred=lowerPoint(145,441);
      const node=failed?add(g,'g',{class:'wq-crumpled-paper'}):paintPaper(g,'wq-bounced-paper','REJECTED');
      const route=t=>{
        if(failed)return arc(this.scene.cabinetOutput,lowerPoint(230,285),shred,smooth(t/.78));
        if(t<.36)return arc(source,{x:source.x-80,y:source.y-90},this.scene.cabinetIntake,smooth(t/.36));
        if(t<.5)return lerp(this.scene.cabinetIntake,lowerPoint(210,290),smooth((t-.36)/.14));
        return arc(lowerPoint(210,290),lowerPoint(120,330),shred,smooth((t-.5)/.28));
      };
      if(failed){
        add(node,'path',{d:'M-9-4-3-10 5-7 10 0 5 8-6 6-11 0Z',fill:'#687184',stroke:'#b8bac2','stroke-width':1});
        add(node,'path',{d:'M-6-4 3 3-2 6M1-7-3 0 8 1',fill:'none',stroke:'#303a4e','stroke-width':1.2});
        const clouds=add(g,'g');for(let i=0;i<3;i++)add(clouds,'circle',{class:'wq-smoke',cx:Math.sin(i)*5,cy:-8-i*11,r:9-i,fill:'#253047',opacity:.7-i*.15});
        const smoke={node:clouds,surface:this._sprite(job,clouds,{left:-20,top:-46,width:40,height:60})};job.smoke=[smoke];
        this._fly(job,smoke,t=>{const point=route(t);return{point:{x:point.x,y:point.y-t*12},scale:.6+t*.5,opacity:(1-t)*.65};},1900);
      }
      const particle={node,surface:this._sprite(job,node,{left:-36,top:-20,width:72,height:40})};job.particles.push(particle);
      this._fly(job,particle,t=>({point:route(t*.78),angle:(failed?600:360)*t*.78,opacity:t>=1?0:1}),1482);
      // One cached spray, not eight independently promoted fragments.
      const spray=add(g,'g');for(let i=0;i<8;i++)add(spray,'path',{class:'wq-confetti',d:`M${-16+i*4} ${-Math.sin(i)*8}l3-7`,stroke:i%2?'#d2dfeb':'#ff6b87','stroke-width':1.8});
      const confetti={node:spray,surface:this._sprite(job,spray,{left:-48,top:-24,width:96,height:62})};job.confetti=[confetti];
      this._fly(job,confetti,t=>({point:{x:145,y:437+LOWER_SHIFT+t*26},scale:.35+t*.65,angle:t*16,opacity:t<.02||t>=1?0:1-t}),418,1482);
      const shake=Array.from({length:15},(_,i)=>({offset:i/14,transform:`translateX(${Math.sin(i*2.5)*(1-i/14)*2}px)`}));
      this.scene.shredderSurface.play(shake,{duration:418,delay:1482});
    }
    this.parallel.push(job);this._caption(event);
  }
  _bodyPosition(now=this.now()){
    return this.scene.spider.positionSurface.positionAt(now);
  }
  _lookTarget(job){
    const next=this.queue[0];
    if(next?.kind==='sim_done')return CAPTURE_CENTER;
    return next?.ids?.length?this.scene.web.position(next.ids[0]):job?.origin||WEB_CENTER;
  }
  _beginBody(job,target,now,travelOptions={}){
    const spider=this.scene.spider,surface=spider.positionSurface;
    spider.attend(false);surface.stopTravel();
    spider.pose({...surface.positionAt(now),angle:spider.state.angle,walk:spider.state.walk,gait:true,smooth:true});
    surface.animate('');
    const options={bounds:SCREEN_CONTENT,confine:point=>spider.centerAt(point),...travelOptions};
    let plan=planSilkTravel(surface.positionAt(now),target,options);
    if(this.flowVelocity){
      const v=this.flowVelocity,w=plan.velocityAt(1),speed=Math.hypot(v.x,v.y),other=Math.hypot(w.x,w.y);
      if(speed&&other&&(v.x*w.x+v.y*w.y)/(speed*other)>.8)plan=planSilkTravel(surface.positionAt(now),target,{...options,startSpeed:speed});
      this.flowVelocity=null;
    }
    this.relaxUntil=null;job.turn=null;
    job.travel=surface.travel(plan,{startTime:now});job.walked=0;job.stage='approach';job.stageAt=now;
  }
  // Presentation work shares the spider's serial lease, but never enters the
  // business event queue, increments a sequence, or returns through the hub.
  startWorkAction({kind,target,returnTo=null,onfinish}={}){
    if(this.disposed||this.working||this.workAction||this.scene.doc.hidden||this.scene.reducedMotion)return false;
    const now=this.now(),origin={...this._bodyPosition(now)};
    const job={kind,origin,returnTo,onfinish};
    const distance=Math.hypot(target.x-origin.x,target.y-origin.y);
    this.workAction=job;
    this._beginBody(job,target,now,kind==='patrol'?{maxSpeed:Math.max(1,distance)}:{});
    job.stage='work-walk';this._schedule();return true;
  }
  yieldWork(){
    const job=this.workAction;if(!job)return;
    // Commit the visible WAAPI sample before another owner plans its route.
    this._bodyPose(job,this.now());job.travel?.cancel();this.workAction=null;
    if(this.frame!==null)this.win.cancelAnimationFrame?.(this.frame);this.frame=null;
    // The next owner keeps the same capped contact pose; a visible result
    // handoff must not force all eight feet into an uncapped resting stance.
    this.scene.spider.attend(false);this.scene.spider.rest({atCurrent:true});
  }
  _workTick(now){
    const job=this.workAction;if(!job)return;
    this._bodyPose(job,now);
    if(!job.travel.done)return;
    if(job.returnTo&&job.stage!=='work-back'){
      const origin={...this._bodyPosition(now)},target=job.returnTo,distance=Math.hypot(target.x-origin.x,target.y-origin.y);
      job.returnTo=null;
      this._beginBody(job,target,now,{maxSpeed:Math.max(1,distance)});job.stage='work-back';return;
    }
    if(job.stage!=='work-settle'){job.stage='work-settle';job.stageAt=now;}
    if(now-job.stageAt<300||this.scene.spider.state.walk>.001||this.scene.spider.legMotionPending)return;
    this.workAction=null;this.scene.spider.rest({atCurrent:true});job.onfinish?.();
  }
  _bodyPose(job,now,extra={}){
    const spider=this.scene.spider,position=this._bodyPosition(now);
    const moving=job.travel&&!job.travel.done;
    const walked=job.travel?.distanceAt(now)??0,travelDistance=walked-(job.walked??0);
    job.walked=walked;
    let desired=job.angle??spider.state.angle;
    if(moving){
      const velocity=job.travel.plan.velocityAt(Math.min(now-job.travel.start+75,job.travel.plan.duration-.01));
      if(Math.hypot(velocity.x,velocity.y)>0)desired=Math.atan2(velocity.x,-velocity.y);
      if(job.travel.plan.duration-(now-job.travel.start)<150&&job.stage!=='return')desired=job.angle??-Math.PI/2;
    }else if(this.queue.length&&['land','retract'].includes(job.stage)){
      const target=this._lookTarget(job);desired=Math.atan2(target.x-position.x,-(target.y-position.y));
    }
    const delta=(a,b)=>Math.atan2(Math.sin(a-b),Math.cos(a-b));
    if(!job.turn||Math.abs(delta(desired,job.turn.to))>.01)job.turn={from:spider.state.angle,to:spider.state.angle+delta(desired,spider.state.angle),at:now};
    const turn=smooth((now-job.turn.at)/150),angle=job.turn.from+(job.turn.to-job.turn.from)*turn;
    spider.attend(!moving&&spider.state.walk<.01,this._lookTarget(job));
    spider.pose({...position,angle,walk:moving?1:0,gait:true,travelDistance,smooth:true,...extra});
  }
  _startReturn(job,now){
    // Work already waiting can start here; there is no mandatory hub round trip.
    if(this.queue.length){job.done=true;return;}
    this._beginBody(job,this.scene.spider.home,now);job.stage='return';
  }
  _canHandoff(job,now){
    const next=this.queue[0];
    if(!next||['prod_ok','summary'].includes(next.kind))return false;
    const position=this._bodyPosition(now),target=this._lookTarget(job);
    const v=job.travel.plan.velocityAt(now-job.travel.start);
    if((target.x-position.x)*v.x+(target.y-position.y)*v.y<=0)return false;
    const probe=planSilkTravel(position,target,{bounds:SCREEN_CONTENT,confine:point=>this.scene.spider.centerAt(point)});
    const w=probe.velocityAt(1),length=Math.hypot(v.x,v.y)*Math.hypot(w.x,w.y);
    return length>0&&(v.x*w.x+v.y*w.y)/length>.8;
  }
  _contact(point){return Math.hypot(this.scene.spider.tip.x-point.x,this.scene.spider.tip.y-point.y)<.75;}
  _capture(job,elapsed,now){
    const spider=this.scene.spider;
    for(const particle of job.particles){
      if(particle.releasedAt!==undefined&&!particle.received&&now-particle.releasedAt>=280){
        particle.received=true;particle.surface.stop();opacity(particle,0);this.scene.web.release([particle.id]);
      }
    }
    if(job.stage==='approach'){
      const edge=job.particles[0].edge,position=this._bodyPosition(now);
      // Prepare the gripper while arriving, without stretching across the web.
      this._bodyPose(job,now,Math.hypot(position.x-edge.x,position.y-edge.y)<90?{reach:edge}:{});
      if(job.travel.done){job.stage='reach';job.stageAt=now;}
    }else if(job.stage==='return'){
      this._bodyPose(job,now,{walk:job.travel.done?0:1});
      if(job.travel.done)job.done=true;
    }else if(job.step<job.n){
      const particle=job.particles[job.step];particle.attached=false;
      if(job.stage==='reach'){
        this._bodyPose(job,now,{reach:particle.edge,walk:0});
        if(this._contact(particle.edge)&&now-job.start>=job.step*80+750){
          particle.attached=true;job.stage='grip';job.stageAt=now;
        }
      }else if(job.stage==='grip'){
        this._bodyPose(job,now,{reach:particle.edge,grip:1,walk:0});particle.attached=true;
        if(now-job.stageAt>=250){job.stage='draw';job.stageAt=now;job.grabFrom={...spider.tip};}
      }else if(job.stage==='draw'){
        const p=clamp((now-job.stageAt)/120),toward=lerp(particle.edge,WEB_CENTER,.055);
        this._bodyPose(job,now,{reach:lerp(job.grabFrom,toward,smooth(p)),grip:1,walk:0});particle.attached=true;
        if(p>=1&&this._contact(toward)){
          const from={...spider.tip},target=this.scene.web.position(particle.id);
          particle.attached=false;particle.returning=true;particle.releasedAt=now;
          this._fly({start:now},particle,t=>({point:arc(from,{x:(from.x+target.x)/2,y:Math.min(from.y,target.y)-8},target,smooth(t))}),280);
          job.step++;job.stage=job.step<job.n?'reach':'land';job.stageAt=now;
        }
      }
      if(particle.attached){place(particle,{...spider.tip});opacity(particle,1);}
      const attached=String(particle.attached);if(particle.node.getAttribute('data-attached')!==attached)particle.node.setAttribute('data-attached',attached);
    }else{
      this._bodyPose(job,now,{reach:{...spider.tip},walk:0});
      if(job.particles.every(particle=>particle.received))this._startReturn(job,now);
    }
    phaseLabel(job,job.stage==='approach'?'approach':job.stage==='return'?'return':'capture');
  }
  _sort(job,elapsed,now){
    if(job.kind==='prod_ok')return;
    const origin=job.origin,route=job.kind==='candidate'?'review':job.kind==='eval_pass'?'pass':'reject';
    const particle=job.particles[0],target=route==='review'?this.scene.noteNodes.get(particle.id)?.position:null;
    if(job.stage==='approach'){
      const position=this._bodyPosition(now);
      this._bodyPose(job,now,Math.hypot(position.x-origin.x,position.y-origin.y)<90?{reach:origin}:{});
      if(job.travel.done){job.stage='touch';job.stageAt=now;}
    }else if(job.stage==='touch'){
      this._bodyPose(job,now,{reach:origin,walk:0});
      if(this._contact(origin)){job.stage='grip';job.stageAt=now;}
    }else if(job.stage==='grip'){
      this._bodyPose(job,now,{reach:origin,grip:1,walk:0});
      if(now-job.stageAt>=250){
        job.stage='flick';job.stageAt=now;job.sliding=true;job.slidingAt=now;
        if(job.branch&&target)job.branch.setAttribute('d',`M876 ${164+LOWER_SHIFT}Q875 ${127+LOWER_SHIFT} ${target.x} ${target.y}`);
        this._fly({start:now},particle,t=>({point:routePoint(route,t,origin,target)}),600);
      }
    }else if(job.stage==='flick'){
      const p=clamp((now-job.stageAt)/180),push=routePoint(route,.08,origin,target);
      this._bodyPose(job,now,{reach:lerp(origin,push,Math.sin(p*Math.PI)*.7),walk:0});
      if(p>=1){job.stage='retract';job.stageAt=now;}
    }else if(job.stage==='retract'){
      this._bodyPose(job,now,{walk:0});
      if(now-job.slidingAt>=600){
        job.arrived=true;particle.surface.stop();opacity(particle,0);this.scene.web.arrive(route);
        if(route==='review')this._revealNote(particle.id,true);
        this._startReturn(job,now);
      }
    }else if(job.stage==='return'){
      this._bodyPose(job,now,{walk:job.travel.done?0:1});if(job.travel.done)job.done=true;
    }
    phaseLabel(job,job.sliding?'sort':job.stage==='approach'?'approach':'touch');
  }
  _revealNote(id,flip=false){
    this.hiddenNotes.delete(id);const note=this.scene.noteNodes.get(id);
    if(note){note.surface.setOpacity(1);if(flip)note.surface.animate('wq-note-flip wq-animated');}
  }
  _settle(job){
    this.scene.web.release(job.ids||[]);
    this.scene.web.endProcessing(job.ids||[]);
    if(job.kind==='candidate')for(const id of job.ids||[])this._revealNote(id);
    this._dispose(job);
  }
  _schedule(){
    if(this.frame!==null||this.timer!==null||!(this.working||this.workAction)||this.disposed||this.scene.doc.hidden||this.scene.reducedMotion)return;
    if(this.workAction||this.relaxUntil!==null||this.active&&!['prod_ok','summary'].includes(this.active.kind)){
      this.frame=this.win.requestAnimationFrame(now=>{
        this.frame=null;
        this.lastDraw=now;this.tick(now);
      });
    }else{
      const deadlines=[...this.parallel.map(job=>job.start+job.duration),...(this.active?[this.active.start+this.active.duration]:[])];
      if(deadlines.length)this.timer=this.win.setTimeout(()=>{this.timer=null;this.tick(this.now());},Math.max(1,Math.min(...deadlines)-this.now()));
    }
  }
  tick(now){
    if(this.frame!==null)this.win.cancelAnimationFrame?.(this.frame);this.frame=null;
    if(this.timer!==null)this.win.clearTimeout?.(this.timer);this.timer=null;
    if(this.disposed||this.scene.doc.hidden||this.scene.reducedMotion){this.clear();return;}
    if(this.workAction)this._workTick(now);
    const keep=[];
    for(const job of this.parallel){if(now-job.start>=job.duration)this._dispose(job);else keep.push(job);}
    this.parallel=keep;this._next(now);
    while(this.active){
      const job=this.active,elapsed=Math.max(0,now-job.start);
      if(job.stage==='return'&&this._canHandoff(job,now)){
        this._bodyPose(job,now);
        this.flowVelocity=job.travel.plan.velocityAt(now-job.travel.start);job.travel.cancel();job.done=true;
      }
      if(!job.done){
        if(job.kind==='sim_done')this._capture(job,elapsed,now);
        else if(job.kind!=='summary')this._sort(job,elapsed,now);
      }
      if(!job.done&&elapsed<job.duration)break;
      this._settle(job);this.active=null;this.relaxUntil=this.scene.spider.state.walk>.001||this.scene.spider.legMotionPending?now+300:null;this._next(now);
    }
    this._drainParallel(now);this._next(now);
    if(this.relaxUntil!==null){
      if(now<this.relaxUntil||this.scene.spider.state.walk>.001||this.scene.spider.legMotionPending){
        const spider=this.scene.spider;
        spider.pose({...this._bodyPosition(now),angle:spider.state.angle,walk:0,gait:true,smooth:true});
      }else{
        this.relaxUntil=null;this.scene.spider.rest({atCurrent:true});this.scene.spider.attend(true,this._lookTarget(this.active));
      }
    }
    if(!this.working&&!this.workAction){
      if(this.scene.spider.root.getAttribute('data-idle')!=='true')this.scene.spider.rest({atCurrent:true});
      this.scene.web.settle();
    }
    this._schedule();
  }
  clear(){
    this.yieldWork();
    if(this.frame!==null)this.win.cancelAnimationFrame?.(this.frame);this.frame=null;
    if(this.timer!==null)this.win.clearTimeout?.(this.timer);this.timer=null;
    this.relaxUntil=null;this.flowVelocity=null;
    if(this.active?.travel)this._bodyPose(this.active,this.now());
    if(this.active)this._settle(this.active);
    for(const job of this.queue)this._settle(job);
    for(const job of this.parallel)this._dispose(job);
    this.active=null;this.queue=[];this.parallel=[];this.pending=[];
    for(const id of this.hiddenNotes)this._revealNote(id);this.hiddenNotes.clear();
    for(const note of this.scene.noteNodes.values())note.surface.animate('');
    this.scene.shredderSurface.stop();style(this.scene.shredderSurface.motion,'transform','none');
    this.scene.shredderSurface.move(SHREDDER_ORIGIN.x,SHREDDER_ORIGIN.y);this.scene.spider.attend(false);this.scene.spider.rest({atCurrent:true,immediate:true});this.scene.web.settle();
  }
  destroy(){this.clear();this.disposed=true;}
}
