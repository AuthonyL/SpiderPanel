// Stable web geometry shared by the artwork and the event paths.
import {formatMetric} from './data.js';
import {WEB_CENTER,WEB_RADII,WEB_SPOKES,WEB_SPIRALS,COCOON_LIMIT,SCREEN_CONTENT,LOWER_SHIFT} from './geometry.js';
export {WEB_CENTER,WEB_RADII,WEB_SPOKES,WEB_SPIRALS,COCOON_LIMIT,SCREEN_CONTENT} from './geometry.js';
const TAU=Math.PI*2, NS='http://www.w3.org/2000/svg';
const bounded=t=>Math.max(0,Math.min(1,Number.isFinite(t)?t:0));
const number=value=>typeof value==='number'&&Number.isFinite(value)?Math.max(0,value):0;
const COLORS={done:'#c7d4e3',eval_failed:'#8a354b',eval_passed:'#4f7cff',prod_ok:'#3ddc84',prod_blocked:'#ff4d5e',candidate:'#ff5fa2',rejected:'#8a354b'};
const REJECTED=new Set(['eval_failed','prod_blocked','rejected']);
const attribute=(node,key,value)=>{const next=String(value);if(node.getAttribute(key)!==next)node.setAttribute(key,next);};
const removeAttribute=(node,key)=>{if(node.getAttribute(key)!==null)node.removeAttribute(key);};
const text=(node,value)=>{const next=String(value);if(node.textContent!==next)node.textContent=next;};
const point=(spoke,radius)=>({x:WEB_CENTER.x+WEB_RADII.x*radius*Math.cos(spoke/WEB_SPOKES*TAU-Math.PI/2),y:WEB_CENTER.y+WEB_RADII.y*radius*Math.sin(spoke/WEB_SPOKES*TAU-Math.PI/2)});
export function webPoint(slot) {
  const index=((Math.floor(Number.isFinite(slot)?slot:0)%64)+64)%64;
  return point(index%WEB_SPOKES,(2+Math.floor(index/WEB_SPOKES)+index%WEB_SPOKES/WEB_SPOKES)/WEB_SPIRALS);
}
function add(parent,tag,attrs={},value) {
  const el=parent.ownerDocument.createElementNS(NS,tag);
  for(const [key,val] of Object.entries(attrs))el.setAttribute(key,String(val));
  if(value!==undefined)el.textContent=String(value);
  parent.appendChild(el);return el;
}
function quadratic(a,b,c,t) {const q=1-t;return{x:q*q*a.x+2*q*t*b.x+t*t*c.x,y:q*q*a.y+2*q*t*b.y+t*t*c.y};}
const ROUTES=Object.fromEntries(Object.entries({
  reject:[{x:463,y:194},{x:449,y:217},{x:419,y:228}],
  pass:[{x:650,y:201},{x:635,y:219},{x:595,y:228}],
  review:[{x:754,y:186},{x:809,y:232},{x:842,y:226},{x:873,y:244},{x:876,y:164},{x:875,y:127},{x:925,y:135}],
}).map(([key,path])=>[key,path.map(({x,y})=>({x,y:y+LOWER_SHIFT}))]));
export function routePoint(key,t,source,destination) {
  const base=ROUTES[key]||ROUTES.reject;
  const path=key==='review'&&Number.isFinite(destination?.x)&&Number.isFinite(destination?.y)
    ? [...base.slice(0,-1),destination]:base;
  const p=bounded(t),start=source||path[0];
  if(p<=.25)return quadratic(start,{x:(start.x+path[0].x)/2,y:Math.min(start.y,path[0].y)-8},path[0],p*4);
  const segments=(path.length-1)/2,at=(p-.25)/.75*segments,index=Math.min(segments-1,Math.floor(at));
  return quadratic(path[index*2],path[index*2+1],path[index*2+2],Math.min(1,at-index));
}

export class AlphaWeb {
  constructor(parent,{id='wq-web',onAlpha=()=>{},clipId=null}={}) {
    this.id=id;this.onAlpha=onAlpha;this.nodes=new Map();this.retiring=new Set();this.held=new Set();this.processing=new Map();
    this.layers=null;this.retiringEntries=new Map();this.countSurfaces={};
    this.displayCounts={reject:0,pass:0,review:0};this.targetCounts={...this.displayCounts};
    this.root=add(parent,'g',{'data-layer':'alpha-web'});
    const defs=add(this.root,'defs');
    for(const [key,fill]of [['reject','#ae566d'],['pass','#3ddc84'],['review','#ff5fa2']]){
      const gradient=add(defs,'radialGradient',{id:`${id}-strand-${key}`});
      for(const [offset,opacity]of [[0,.55],[.4,.25],[1,0]])add(gradient,'stop',{offset,'stop-color':fill,'stop-opacity':opacity});
    }
    this.content=add(this.root,'g',{'data-layer':'web-content'});
    if(clipId)this.content.setAttribute('clip-path',`url(#${clipId})`);
    this.wires=add(this.content,'g',{fill:'none',stroke:'#cfe8ff','stroke-width':.65,'stroke-opacity':.18});
    this.spokes=[];
    for(let index=0;index<WEB_SPOKES;index++){
      const end=point(index,1);
      this.spokes.push(add(this.wires,'path',{d:`M${WEB_CENTER.x} ${WEB_CENTER.y}L${end.x} ${end.y}`}));
    }
    const coords=Array.from({length:WEB_SPOKES*WEB_SPIRALS+1},(_,i)=>point(i%WEB_SPOKES,i/(WEB_SPOKES*WEB_SPIRALS)));
    this.spiral=add(this.wires,'path',{d:coords.map((p,i)=>`${i?'L':'M'}${p.x} ${p.y}`).join(' '),'stroke-opacity':.22});
    this.layer=add(this.content,'g',{'data-layer':'cocoons'});
    this.strands=add(this.root,'g',{'data-layer':'sorting-strands',fill:'none'});
    this.countNodes={};
    for(const [key,title,fill,x] of [['reject','淘汰 REJECT','#ae566d',419],['pass','通过 PASS','#3ddc84',595],['review','复核 REVIEW','#ff5fa2',777]]){
      const path=ROUTES[key];
      add(this.strands,'path',{d:`M${path[0].x} ${path[0].y}`+Array.from({length:(path.length-1)/2},(_,i)=>`Q${path[2*i+1].x} ${path[2*i+1].y} ${path[2*i+2].x} ${path[2*i+2].y}`).join(' '),stroke:fill,'stroke-width':1.65,'stroke-opacity':.6});
      const end={cx:key==='review'?842:path.at(-1).x,cy:(key==='review'?226:228)+LOWER_SHIFT};
      add(this.strands,'circle',{...end,r:7,fill:`url(#${id}-strand-${key})`});
      add(this.strands,'circle',{...end,r:2.5,fill});
      add(this.strands,'text',{x:x-36,y:237+LOWER_SHIFT,fill,'font-size':6.4},title);
      this.countNodes[key]=add(this.strands,'text',{x:x+37,y:237+LOWER_SHIFT,fill,'font-size':7.5,'text-anchor':'end','font-weight':700},'0');
      this.countNodes[key].addEventListener('animationend',()=>this.countNodes[key].removeAttribute('class'));
    }
  }

  attachLayers(layers) {
    if(this.layers===layers)return this;
    if(!layers||typeof layers.mount!=='function')throw new TypeError('AlphaWeb layers require mount(node, box, options)');
    this.layers=layers;
    const {left,top,right,bottom}=SCREEN_CONTENT;
    removeAttribute(this.spiral,'filter');
    this.wireSurface=layers.mount(this.wires,{left,top,width:right-left,height:bottom-top},{parent:layers.webClip,kind:'web-silk'});
    // The full web is stationary; only the small captured sprites move.
    for(const entry of this.nodes.values())this._mount(entry);
    for(const [key,node] of Object.entries(this.countNodes)){
      this.countSurfaces[key]?.remove();
      removeAttribute(node,'class');
      const x=Number(node.getAttribute('x'));
      const surface=layers.mount(node,{left:x-60,top:225+LOWER_SHIFT,width:64,height:20},{kind:'sort-count'});
      this.countSurfaces[key]=surface;
      surface.motion.addEventListener('animationend',()=>surface.animate(''));
    }
    return this;
  }

  _mount(entry) {
    if(!this.layers)return;
    entry.surface?.remove();
    entry.surface=this.layers.mount(entry.g,{left:-14,top:-12,width:28,height:24},
      {parent:this.layers.webClip,local:true,interactive:true,kind:'cocoon'});
    attribute(entry.g,'transform','translate(0 0)');
    entry.surface.move(entry.position.x,entry.position.y);
    this._appearance(String(entry.data.id),entry);
  }

  _removeRetiring(g) {
    const entry=this.retiringEntries.get(g);
    if(entry?.surface)entry.surface.remove();else g.remove();
    this.retiringEntries.delete(g);this.retiring.delete(g);
  }

  update(alphas,animate=false) {
    const rows=(Array.isArray(alphas)?alphas:[]).filter(a=>a&&a.id!==null&&a.id!==undefined).slice(0,COCOON_LIMIT);
    const keep=new Set(rows.map(a=>String(a.id)));
    for(const [key,entry] of this.nodes)if(!keep.has(key)){
      this.nodes.delete(key);this.held.delete(key);
      if(animate){
        const motion=entry.surface?.motion||entry.g;
        attribute(entry.g,'pointer-events','none');removeAttribute(entry.g,'tabindex');
        entry.g.classList.remove('wq-hit');
        this.retiring.add(entry.g);this.retiringEntries.set(entry.g,entry);
        motion.addEventListener('animationend',()=>this._removeRetiring(entry.g));
        // A full compositor budget settles the fade synchronously.
        if(entry.surface)entry.surface.animate('wq-cocoon-retire wq-animated');
        else attribute(entry.g,'class','wq-cocoon-retire wq-animated');
        while(this.retiring.size>8)this._removeRetiring(this.retiring.values().next().value);
      }else if(entry.surface)entry.surface.remove();else entry.g.remove();
    }
    const occupied=new Set([...this.nodes.values()].map(entry=>entry.slot));
    for(const alpha of rows){
      const key=String(alpha.id);let entry=this.nodes.get(key);
      if(!entry){
        let seed=7;for(const char of key)seed=(seed*31+char.charCodeAt(0))>>>0;
        let slot=seed%64;while(occupied.has(slot))slot=(slot+1)%64;occupied.add(slot);
        const position=webPoint(slot),g=add(this.layer,'g',{class:'wq-hit wq-cocoon',role:'button',tabindex:0,'data-alpha':key,transform:`translate(${position.x} ${position.y})`});
        add(g,'ellipse',{rx:9,ry:7,fill:'transparent'});
        // Scale only the artwork. The transparent hit area remains easy to click.
        const glyph=add(g,'g');
        const halo=add(glyph,'ellipse',{rx:7,ry:5,fill:'none','stroke-opacity':.45,class:'wq-focus'});
        const dot=add(glyph,'ellipse',{rx:4.7,ry:3.4,stroke:'#e6f4ff','stroke-width':.5,'stroke-opacity':.65});
        add(glyph,'path',{d:'M-3-2Q0 1 3-2M-3 0Q0 3 3 0M-2 2 2-2',fill:'none',stroke:'#f3f7ff','stroke-width':.45,opacity:.5});
        entry={g,glyph,halo,dot,title:add(g,'title'),slot,position,data:alpha};
        g.addEventListener('click',()=>this.onAlpha(key));
        g.addEventListener('keydown',event=>{if(event.key==='Enter'||event.key===' '){event.preventDefault();this.onAlpha(key);}});
        this.nodes.set(key,entry);
        this._mount(entry);
      }
      entry.data=alpha;this._appearance(key,entry);
      attribute(entry.g,'aria-label',`${key}，${alpha.status||'done'}，Sharpe ${formatMetric(alpha.sharpe)}`);
      text(entry.title,`${key}\n${alpha.status||'done'} · Sharpe ${formatMetric(alpha.sharpe)}\n${alpha.expr||''}`);
    }
  }

  _appearance(key,entry=this.nodes.get(key)) {
    if(!entry)return;
    const status=entry.data.status,active=this.processing.has(key),quiet=REJECTED.has(status)&&!active;
    const fill=COLORS[status]||COLORS.done;
    attribute(entry.g,'opacity',this.held.has(key)?'0':quiet?'0.25':status==='done'&&!active?'0.7':'1');
    attribute(entry.glyph,'transform',quiet?'scale(0.6)':'scale(1)');
    attribute(entry.dot,'fill',fill);attribute(entry.halo,'stroke',fill);
    attribute(entry.halo,'display',REJECTED.has(status)?'none':'inline');
    if(entry.surface){
      removeAttribute(entry.halo,'filter');
      entry.surface.glow(status==='candidate'?fill:null,this.held.has(key)?0:1);
    }else attribute(entry.halo,'fill',status==='candidate'?`url(#${this.id}-strand-review)`:'none');
  }

  // Counts cover overlapping queued actions for one alpha. It becomes quiet only
  // after the last action finishes, including when the snapshot already advanced.
  beginProcessing(ids) {for(const id of ids){const key=String(id);this.processing.set(key,(this.processing.get(key)||0)+1);this._appearance(key);}}
  endProcessing(ids) {for(const id of ids){const key=String(id),left=(this.processing.get(key)||0)-1;if(left>0)this.processing.set(key,left);else this.processing.delete(key);this._appearance(key);}}
  position(id) {return this.nodes.get(String(id))?.position||webPoint(0);}
  hold(ids) {for(const id of ids){const key=String(id);this.held.add(key);this._appearance(key);}}
  release(ids) {for(const id of ids){const key=String(id);this.held.delete(key);this._appearance(key);}}
  tint(id,fill) {const entry=this.nodes.get(String(id));if(entry)attribute(entry.dot,'fill',fill);}
  syncCounts(snapshot={},defer=false) {
    const rejects=snapshot.rejects||{},totals=snapshot.totals||{};
    this.targetCounts={reject:number(rejects.eval_fail)+number(rejects.prod_blocked)+number(rejects.save_rejected),pass:number(totals.eval_passed),review:number(totals.candidates)};
    if(!defer){this.displayCounts={...this.targetCounts};this._counts();}
  }
  arrive(key,n=1) {
    if(key in this.displayCounts){this.displayCounts[key]=Math.min(this.targetCounts[key],this.displayCounts[key]+number(n));this._counts();}
    const el=this.countNodes[key];
    if(this.countSurfaces[key])this.countSurfaces[key].animate('wq-sort-count wq-animated');
    else if(el)attribute(el,'class','wq-sort-count wq-animated');
  }
  _counts() {for(const key of Object.keys(this.displayCounts))text(this.countNodes[key],this.displayCounts[key]);}
  settle() {
    for(const el of this.retiring)this._removeRetiring(el);
    this.held.clear();this.processing.clear();
    for(const [key,entry]of this.nodes)this._appearance(key,entry);
    this.displayCounts={...this.targetCounts};this._counts();
    for(const [key,node] of Object.entries(this.countNodes)){
      removeAttribute(node,'class');this.countSurfaces[key]?.animate('');
    }
  }
  destroy() {
    this.wireSurface?.remove();
    this.settle();
    for(const entry of this.nodes.values())entry.surface?.remove();
    for(const surface of Object.values(this.countSurfaces))surface.remove();
    this.countSurfaces={};this.root.remove();this.nodes.clear();this.layers=null;
  }
}
