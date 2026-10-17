import {rebaseSilkTravel} from './motion.js';
import {SCENE_WIDTH,SCENE_HEIGHT,SCENE_TOP} from './geometry.js';

// One cached background and small independently rasterized sprite surfaces.
const NS='http://www.w3.org/2000/svg';
let haloSerial=0;
// Reserve three compositor slots for LIVE, the current subtitle and the drawer.
const PROMOTION_LIMIT=22;
const FINITE={
  'wq-note-flip':{duration:650,frames:[{transform:'scaleY(.05) skewX(-12deg)',opacity:0},{offset:.55,transform:'scaleY(1.12) skewX(4deg)',opacity:1},{transform:'none',opacity:1}]},
  'wq-sort-count':{duration:400,frames:[{transform:'scale(.94)',opacity:.3},{offset:.5,transform:'scale(1.08)',opacity:1},{transform:'none',opacity:1}]},
  'wq-cocoon-retire':{duration:650,frames:[{opacity:1},{opacity:0}]},
};
const attr=(node,key,value)=>{const next=String(value);if(node.getAttribute(key)!==next)node.setAttribute(key,next);};
export const style=(node,key,value)=>{const next=String(value);if(node.style.getPropertyValue(key)!==next)node.style.setProperty(key,next);};

export class SceneLayers {
  constructor(svg,id,bounds){
    this.doc=svg.ownerDocument;this.svg=svg;this.id=id;this.surfaces=new Set();this.promotions=new Set();this.destroyed=false;this.paused=false;
    this.reduceQuery=this.doc.defaultView?.matchMedia?.('(prefers-reduced-motion: reduce)');
    this.canvas=this.doc.createElement('div');this.canvas.className='scene-canvas';
    svg.parentNode.insertBefore(this.canvas,svg);this.canvas.appendChild(svg);
    svg.classList.add('scene-background');svg.setAttribute('data-scene',id);
    this.root=this.doc.createElement('div');this.root.className='scene-sprites';this.root.setAttribute('data-scene',id);
    style(this.root,'width',`${SCENE_WIDTH}px`);style(this.root,'height',`${SCENE_TOP+SCENE_HEIGHT}px`);
    this.canvas.appendChild(this.root);
    this.webClip=this.group('web-sprites');this.webClip.setAttribute('data-screen-clip','true');
    this.webClip.spriteOrigin={x:bounds.left,y:bounds.top};
    for(const [key,value]of Object.entries({left:`${bounds.left}px`,top:`${bounds.top}px`,width:`${bounds.right-bounds.left}px`,height:`${bounds.bottom-bounds.top}px`}))style(this.webClip,key,value);
    this.webClip.className='scene-web-clip';
    this.resize();
    const Observer=this.doc.defaultView?.ResizeObserver;
    if(Observer){this.observer=new Observer(()=>this.resize());this.observer.observe(this.canvas);}
  }
  group(kind,parent=this.root){
    const group=this.doc.createElement('div');group.className='scene-sprite-group';group.setAttribute('data-layer',kind);parent.appendChild(group);return group;
  }
  resize(){
    if(this.destroyed)return;
    const rect=this.canvas.getBoundingClientRect();
    const width=rect.width||SCENE_WIDTH,height=rect.height||SCENE_HEIGHT,scale=Math.min(width/SCENE_WIDTH,height/SCENE_HEIGHT);
    this.mapping={scale,x:(width-SCENE_WIDTH*scale)/2,y:(height-SCENE_HEIGHT*scale)/2-SCENE_TOP*scale};
    style(this.root,'transform',`translate(${this.mapping.x}px,${this.mapping.y}px) scale(${scale})`);
  }
  _release(surface,target=surface.motion){
    this.promotions.delete(target);style(target,'will-change','auto');
    if(surface.leaseTarget===target)surface.leaseTarget=null;
  }
  _claim(surface,ambient=false,target=surface.motion){
    if(surface.traveling&&target===surface.motion)return false;
    if(this.promotions.has(target))return true;
    // Quiet pauses the environment, not an already queued event narrative.
    if(this.doc.hidden||this.reduceQuery?.matches||ambient&&this.paused)return false;
    if(this.promotions.size>=PROMOTION_LIMIT&&!ambient){
      const victim=[...this.surfaces].find(item=>item.ambient&&this.promotions.has(item.motion));
      if(victim){style(victim.motion,'animation','none');this._release(victim);}
    }
    if(this.promotions.size>=PROMOTION_LIMIT)return false;
    if(surface.leaseTarget&&surface.leaseTarget!==target)this._release(surface,surface.leaseTarget);
    this.promotions.add(target);surface.leaseTarget=target;style(target,'will-change','transform,opacity');return true;
  }
  _resumeAmbient(){
    if(this.paused||this.destroyed)return;
    for(const surface of this.surfaces)if(surface.ambient&&!surface.traveling&&this._claim(surface,true))style(surface.motion,'animation','');
  }
  surface(box,{parent=this.root,local=false,interactive=false,kind=''}={}){
    const host=this.doc.createElement('div');host.className='scene-sprite';host.setAttribute('data-sprite',kind);
    host.setAttribute('data-interactive',String(interactive));
    const motion=this.doc.createElement('div');motion.className='sprite-motion';host.appendChild(motion);
    const svg=this.doc.createElementNS(NS,'svg');svg.setAttribute('aria-hidden',interactive?'false':'true');
    svg.setAttribute('font-family','"SF Mono",Menlo,"JetBrains Mono","PingFang SC",monospace');motion.appendChild(svg);parent.appendChild(host);
    const origin=parent.spriteOrigin||{x:0,y:0};
    const now=()=>this.doc.defaultView?.performance?.now?.()??globalThis.performance.now();
    const transform=(x,y,angle=0,scale=1)=>{
      const b=surface.box;
      return `translate(${b.left+(local?x:0)-origin.x}px,${b.top+(local?y:0)-origin.y}px) rotate(${angle}deg) scale(${scale})`;
    };
    const surface={host,motion,svg,box:null,point:{x:0,y:0,angle:0,scale:1},removed:false,
      get traveling(){return Boolean(surface.travelHandle);},
      positionAt:(time=now())=>surface.travelHandle?{...surface.point,...surface.travelHandle.positionAt(time)}:surface.point,
      stopTravel:(commitCurrent=true)=>surface.travelHandle?.cancel(commitCurrent),
      travel:(requested,{startTime}={})=>{
        const time=now(),current=surface.positionAt(time);
        surface.stopTravel();
        const plan=rebaseSilkTravel(requested,current),start=Number.isFinite(startTime)?startTime:time;
        surface.ambient=false;surface.stop();motion.className='sprite-motion';style(motion,'animation','');
        let closed=false,animation=null,settled={x:current.x,y:current.y},settledDistance=0;
        const finish=(point,commit,elapsed=now()-start)=>{
          if(closed)return settled;
          closed=true;settled={x:point.x,y:point.y};settledDistance=plan.distanceAt(elapsed);
          if(surface.travelHandle===handle)surface.travelHandle=null;
          if(commit)surface.move(point.x,point.y,surface.point.angle,surface.point.scale);
          if(animation){animation.onfinish=null;animation.oncancel=null;animation.cancel();}
          surface.travelAnimation=null;this._release(surface,host);this._resumeAmbient();
          return settled;
        };
        const handle={plan,start,
          positionAt:(time=now())=>closed?{...settled}:plan.sample(time-start),
          distanceAt:(time=now())=>closed?settledDistance:plan.distanceAt(time-start),
          get done(){return closed||now()>=start+plan.duration;},
          cancel:(commitCurrent=true)=>finish(handle.positionAt(now()),commitCurrent),
        };
        if(!plan.duration||surface.removed||!this._claim(surface,false,host)||typeof host.animate!=='function'){
          finish(current,false,0);return handle;
        }
        surface.travelHandle=handle;
        const frames=plan.frames.map(point=>({offset:point.offset,transform:transform(point.x,point.y,surface.point.angle,surface.point.scale)}));
        animation=host.animate(frames,{duration:plan.duration,fill:'both',easing:'linear'});
        surface.travelAnimation=animation;
        animation.startTime=start;animation.currentTime=time-start;
        animation.onfinish=()=>finish(plan.sample(plan.duration),true,plan.duration);
        animation.oncancel=()=>handle.cancel();
        return handle;
      },
      setBox:next=>{
        if(![next.left,next.top,next.width,next.height].every(Number.isFinite)||next.width<=0||next.height<=0)throw new RangeError('Invalid sprite bounds');
        surface.box={...next};
        for(const element of [host,motion,svg]){style(element,'width',`${next.width}px`);style(element,'height',`${next.height}px`);}
        // World-coordinate viewBoxes must not put a CSS pivot hundreds of
        // pixels outside the small sprite. Local sprites rotate around (0,0).
        const pivot=local?`${-next.left}px ${-next.top}px`:'50% 50%';
        style(host,'transform-origin',pivot);style(motion,'transform-origin',pivot);
        attr(svg,'viewBox',`${next.left} ${next.top} ${next.width} ${next.height}`);
        surface.move(surface.point.x,surface.point.y,surface.point.angle,surface.point.scale);
      },
      move:(x=0,y=0,angle=0,scale=1)=>{
        // The host's native transform owns position until it is committed.
        // Articulated legs never replace the compositor-owned host transform.
        if(surface.traveling)return;
        surface.point={x,y,angle,scale};const b=surface.box;if(!b)return;
        style(host,'transform',transform(x,y,angle,scale));
      },
      setOpacity:value=>style(motion,'opacity',value),
      // Radial crawls leave straight silk. Stretch a cached one-unit stroke;
      // neither its SVG path nor its raster bounds change on animation frames.
      span:(from,to)=>{
        if(!surface.unitSpan){surface.setBox({left:0,top:-1,width:1,height:2});surface.unitSpan=true;}
        const dx=to.x-from.x,dy=to.y-from.y;
        style(host,'transform-origin','0px 1px');
        style(host,'transform',`translate(${from.x-origin.x}px,${from.y-1-origin.y}px) rotate(${Math.atan2(dy,dx)*180/Math.PI}deg) scaleX(${Math.hypot(dx,dy)})`);
      },
      stop:()=>{
        const animation=surface.animation;surface.animation=null;
        if(animation){animation.onfinish=null;animation.oncancel=null;animation.cancel();}
        this._release(surface);this._resumeAmbient();
      },
      play:(frames,options={})=>{
        surface.stop();surface.ambient=false;
        const last=frames.at(-1),finish=()=>{
          for(const property of ['transform','opacity'])if(last[property]!==undefined)style(motion,property,last[property]);
          surface.animation=null;this._release(surface);this._resumeAmbient();
          if(options.onfinish)options.onfinish();
        };
        if(!this._claim(surface)||typeof motion.animate!=='function'){finish();return null;}
        const {onfinish,deferFinish,...timing}=options;
        const animation=motion.animate(frames,{fill:'both',easing:'linear',...timing});surface.animation=animation;
        animation.onfinish=()=>{
          animation.onfinish=null;
          const settle=()=>{
            // Quiet-work effects commit in the shared second batch. A replaced
            // or removed sprite must never be touched by a delayed completion.
            if(surface.animation!==animation)return;
            animation.oncancel=null;finish();animation.cancel();
          };
          if(deferFinish)deferFinish(settle);else settle();
        };
        animation.oncancel=()=>{if(surface.animation===animation){surface.animation=null;this._release(surface);this._resumeAmbient();}};
        return animation;
      },
      animate:classes=>{
        const next=`sprite-motion ${classes||''}`;
        if(motion.className===next)return;
        surface.ambient=false;surface.stop();motion.className=next;
        const name=Object.keys(FINITE).find(name=>(classes||'').split(/\s+/).includes(name));
        if(name){
          const recipe=FINITE[name];if(name==='wq-note-flip')style(motion,'transform-origin','50% 0');
          surface.play(recipe.frames,{duration:recipe.duration,easing:'ease-out',onfinish:()=>{motion.className='sprite-motion';motion.dispatchEvent?.(new this.doc.defaultView.Event('animationend'));}});
        }
        else if(classes){surface.ambient=true;if(this._claim(surface,true))style(motion,'animation','');else style(motion,'animation','none');}
        else {style(motion,'animation','');this._resumeAmbient();}
      },
      glow:(fill,opacity=1)=>{
        if(!surface.halo&&fill){
          // Paint the halo into this small cached bitmap. CSS filters on a
          // moving composited ancestor would recalculate it on every GPU frame.
          const create=(tag,attributes,parent)=>{const el=this.doc.createElementNS(NS,tag);for(const [key,value]of Object.entries(attributes))attr(el,key,value);parent.appendChild(el);return el;};
          const defs=create('defs',{},svg),id=`${this.id}-sprite-halo-${++haloSerial}`;
          const gradient=create('radialGradient',{id},defs);
          const stops=[[0,.5],[.35,.32],[.7,.1],[1,0]].map(([offset,opacity])=>create('stop',{offset,'stop-color':fill,'stop-opacity':opacity},gradient));
          const b=surface.box,halo=create('ellipse',{cx:b.left+b.width/2,cy:b.top+b.height/2,rx:Math.min(13,b.width/2),ry:Math.min(11,b.height/2),fill:`url(#${id})`,'pointer-events':'none','data-painted-glow':'true'},svg);
          svg.insertBefore(halo,svg.firstChild);surface.halo=halo;surface.haloStops=stops;
        }
        if(surface.halo){attr(surface.halo,'display',fill?'inline':'none');attr(surface.halo,'opacity',opacity);if(fill)for(const stop of surface.haloStops)attr(stop,'stop-color',fill);}
      },
      remove:()=>{if(surface.removed)return;surface.removed=true;surface.ambient=false;surface.stopTravel(false);surface.stop();host.remove();this.surfaces.delete(surface);},
    };
    surface.setBox(box);this.surfaces.add(surface);return surface;
  }
  mount(node,box,options={}){
    const surface=this.surface(box,options);surface.svg.appendChild(node);node.spriteSurface=surface;return surface;
  }
  pause(value){
    this.paused=Boolean(value);attr(this.root,'data-paused',this.paused);
    for(const surface of this.surfaces)if(this.paused&&surface.ambient){style(surface.motion,'animation','none');this._release(surface);}
    this._resumeAmbient();
  }
  destroy(){
    if(this.destroyed)return;this.destroyed=true;this.observer?.disconnect();
    for(const surface of [...this.surfaces])surface.remove();
    this.canvas.parentNode?.insertBefore(this.svg,this.canvas);this.canvas.remove();
  }
}
