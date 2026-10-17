/* One 4 Hz clock samples small visible details; no SVG animation timelines. */
const STEP_MS=250;
const write=(target,key,value)=>{value=String(value);if(target.getAttribute(key)!==value)target.setAttribute(key,value);};

function visible(target) {
  if(!target?.isConnected||target.ownerDocument?.hidden)return false;
  for(let item=target;item;item=item.parentNode){
    if(item.hidden||item.getAttribute?.('display')==='none'||item.getAttribute?.('visibility')==='hidden'
      ||item.style?.getPropertyValue('display')==='none'||item.style?.getPropertyValue('visibility')==='hidden')return false;
  }
  return true;
}

export class AmbientLoop {
  constructor(win=globalThis) {
    this.win=win;this.controls=new Set();this.paused=true;this.destroyed=false;this.timer=null;
    this.targets=new Map();
    this.observer=win.IntersectionObserver?new win.IntersectionObserver(entries=>{
      for(const entry of entries)for(const control of this.targets.get(entry.target)||[])control.inView=entry.isIntersecting;
      this._schedule();
    }):null;
  }

  now(){return this.win.performance?.now?.()??Date.now();}

  register(target,{kind,attributeName,values,seconds,type,once=false,onfinish}={}) {
    if(!target)throw new TypeError('Ambient detail requires a target');
    const loop=this,original=target.getAttribute(attributeName);
    const control={node:target,target,kind,attributeName,values:values.map(String),duration:Math.max(STEP_MS,seconds*1000),
      type,once,onfinish,active:false,inView:true,started:0,disposed:false,
      setActive(value,restart=false){
        if(control.disposed||loop.destroyed)return;
        const next=!!value;
        if(next!==control.active||restart){
          control.active=next;control.started=loop.now();
          if(!next){
            if(original===null){if(target.getAttribute(attributeName)!==null)target.removeAttribute(attributeName);}
            else write(target,attributeName,original);
          }
        }
        loop._schedule();
      },
      play(){control.setActive(true,true);},
      destroy(){
        if(control.disposed)return;control.disposed=true;control.active=false;loop.controls.delete(control);
        const items=loop.targets.get(target);items?.delete(control);
        if(!items?.size){loop.observer?.unobserve(target);loop.targets.delete(target);}
        write(target,'data-running','false');loop._schedule();
      },
    };
    write(target,'data-ambient',kind);write(target,'data-running','false');
    this.controls.add(control);
    if(!this.targets.has(target)){this.targets.set(target,new Set());this.observer?.observe(target);}
    this.targets.get(target).add(control);
    return control;
  }

  _running(control){return !this.paused&&!control.disposed&&control.active&&control.inView&&visible(control.target);}

  _schedule() {
    if(this.destroyed)return;
    let running=false;
    for(const control of this.controls){const active=this._running(control);write(control.target,'data-running',active);running=running||active;}
    if(running&&this.timer===null)this.timer=this.win.setTimeout(()=>{this.timer=null;this._tick();},STEP_MS);
    else if(!running&&this.timer!==null){this.win.clearTimeout(this.timer);this.timer=null;}
  }

  _tick() {
    if(this.destroyed||this.paused)return;
    const now=this.now();
    for(const control of [...this.controls]){
      if(!control.target.isConnected){control.destroy();continue;}
      if(!this._running(control))continue;
      const elapsed=Math.max(0,now-control.started),finished=control.once&&elapsed>=control.duration;
      const t=finished?1:(elapsed%control.duration)/control.duration;
      const value=control.values[Math.min(control.values.length-1,Math.floor(t*(control.values.length-1)))];
      write(control.target,control.attributeName,control.type?`${control.type}(${value})`:value);
      if(finished){control.active=false;write(control.target,'data-running','false');control.onfinish?.();}
    }
    this._schedule();
  }

  setPaused(value) {
    const next=!!value;if(next===this.paused)return;
    this.paused=next;
    if(!next)for(const control of this.controls)if(control.active)control.started=this.now();
    this._schedule();
  }

  destroy() {
    if(this.destroyed)return;
    this.destroyed=true;if(this.timer!==null)this.win.clearTimeout(this.timer);this.timer=null;
    this.observer?.disconnect();
    for(const control of this.controls){control.active=false;control.disposed=true;write(control.target,'data-running','false');}
    this.controls.clear();this.targets.clear();
  }
}

function frames(count,sample){return Array.from({length:count},(_,index)=>sample(index/(count-1),index));}
function group(items){return {setActive(active){for(const item of items)item.setActive(active);},destroy(){for(const item of items)item.destroy();}};}

export function discrete(target,kind,attributeName,values,seconds,{loop,type,once=false,onfinish}={}) {
  if(!loop)throw new TypeError('Ambient detail requires the shared scene loop');
  return loop.register(target,{kind,attributeName,values,seconds,type,once,onfinish});
}

export function monitorMotion(station,loop) {
  const phases=new Map();
  const progress=station.panels.simulating.querySelector('.wq-progress');
  phases.set('simulating',[discrete(progress,'progress','width',frames(15,t=>Math.min(72,2.88+t/.85*69.12).toFixed(2)),3.5,{loop})]);
  const bars=[];
  station.panels.evaluating.querySelectorAll('.wq-eval-bar').forEach((bar,index)=>{
    bar.removeAttribute('style');const height=Number(bar.getAttribute('height'));
    const heights=frames(14,t=>height*(.7-.3*Math.cos(t*Math.PI*2+index*.55)));
    bars.push(discrete(bar,'bars','height',heights.map(value=>value.toFixed(2)),3.2,{loop}));
    bars.push(discrete(bar,'bars','y',heights.map(value=>(-12-value).toFixed(2)),3.2,{loop}));
  });
  phases.set('evaluating',bars);
  phases.set('prod',[discrete(station.panels.prod.querySelector('.wq-radar-sweep'),'sweep','transform',frames(13,t=>`${t*360} 0 0`),3,{loop,type:'rotate'})]);
  return {setPhase(phase){for(const [key,items] of phases)for(const item of items)item.setActive(key===phase);}};
}

export function avatarHands(portrait,loop) {
  return group([
    discrete(portrait.querySelector('.wq-hand-left'),'hand','transform',['0 0','-1 -2','0 0'],.75,{loop,type:'translate'}),
    discrete(portrait.querySelector('.wq-hand-right'),'hand','transform',['-1 -2','0 0','-1 -2'],.75,{loop,type:'translate'}),
  ]);
}

export function sleepMotion(target,loop) {
  return group([
    discrete(target,'zzz','transform',frames(14,t=>`${(t*5).toFixed(2)} ${(3-t*13).toFixed(2)}`),3.2,{loop,type:'translate'}),
    discrete(target,'zzz','opacity',frames(14,t=>(t<.1?0:t<.45?(t-.1)/.35*.9:(1-t)/.55*.9).toFixed(2)),3.2,{loop}),
  ]);
}

export function expressionMotion(target,loop,onfinish) {
  const fade=discrete(target,'expression','opacity',frames(18,t=>(t<.1?t/.1:t<.78?1:(1-t)/.22).toFixed(2)),4.2,{loop,once:true,onfinish});
  const slide=discrete(target,'expression','transform',frames(18,t=>`0 ${(4*Math.max(0,1-t/.1)).toFixed(2)}`),4.2,{loop,type:'translate',once:true});
  return {node:target,play(){fade.play();slide.play();},stop(){fade.setActive(false);slide.setActive(false);},destroy(){fade.destroy();slide.destroy();}};
}
