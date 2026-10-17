/* Native SVG mechanical spider. Its owner supplies the clock through pose(). */
import {SPIDER_LEG_HZ} from './animation-rules.js';
import {WEB_CENTER} from './geometry.js';
import {legPose,cachedLegPose,clawsFor} from './spider-gait.js';
export {legPose} from './spider-gait.js';
const NS = 'http://www.w3.org/2000/svg';
const TAU = Math.PI * 2;
// Two groups alternate four planted feet over equal half cycles.
const STRIDE = 12 * 1.4 / .5;
let serial = 0;

const finite = (value, fallback = 0) => Number.isFinite(value) ? value : fallback;
const clamp = value => Math.max(0, Math.min(1, finite(value)));
const path = points => points.map((point, index) => `${index ? 'L' : 'M'}${point.x} ${point.y}`).join(' ');
const attribute = (element, key, value) => {
  value = String(value);
  if (element.getAttribute(key) !== value) element.setAttribute(key, value);
};
const style = (element, key, value) => {
  value = String(value);
  if (element.style.getPropertyValue(key) !== value) element.style.setProperty(key, value);
};

function add(parent, tag, attrs = {}, text) {
  const element = parent.ownerDocument.createElementNS(NS, tag);
  for (const [key, value] of Object.entries(attrs)) element.setAttribute(key, String(value));
  if (text !== undefined) element.textContent = text;
  parent.appendChild(element);
  return element;
}

/**
 * A 46-unit body and 108-unit resting leg span, drawn at 1.4×, facing local −Y.
 * legs[0] is the right front gripper. reach and tip use scene coordinates.
 * pose() disables CSS idle motion; rest() restores the constructor position.
 */
export class MechanicalSpider {
  constructor(parent, { id = 'mechanical-spider', x = WEB_CENTER.x, y = WEB_CENTER.y, bounds = null } = {}) {
    if (!parent?.ownerDocument) throw new TypeError('MechanicalSpider requires an SVG parent');
    this.doc = parent.ownerDocument;
    this.scale = 1.4;
    this.bounds = bounds && ['left','top','right','bottom'].every(key=>Number.isFinite(bounds[key]))
      && bounds.right>bounds.left && bounds.bottom>bounds.top ? {...bounds} : null;
    // Hip-to-foot clearance at the enlarged scale. Rotated knees and extended
    // tips are additionally contained by the stationary screen clip.
    this.clearance = 66;
    this.home = this.centerAt({ x: finite(x, WEB_CENTER.x), y: finite(y, WEB_CENTER.y) });
    this.id = `wq-spider-${String(id).replace(/[^a-zA-Z0-9_-]/g, '-')}-${++serial}`;
    this.state = { ...this.home, angle: 0, walk: 0, phase: 0, grip: 0, reach: null };
    this.paused = false;
    this.destroyed = false;
    this.tip = null;
    this.legs = [];
    this.animated = [];
    this.trailPoints = [];
    this.trailing = false;
    this.trailOpacity = 0;
    this.trailFading = false;
    this.positionSurface = null;
    this.trailSurface = null;
    this.surfacePoint = null;
    this.gaitPhase = 0;
    this.attention = false;
    // This sibling stays in scene coordinates while the spider rotates above it.
    this.trail = add(parent, 'path', { id: `${this.id}-trail`, class: 'wq-spider-trail',
      d: '', fill: 'none', stroke: '#8ae6ff', 'stroke-width': .85,
      'stroke-linecap': 'round', 'stroke-linejoin': 'round', opacity: 0,
      'aria-hidden': 'true', 'pointer-events': 'none' });
    this.trail.style.setProperty('transition', 'opacity 2.4s ease-out');
    this.root = add(parent, 'g', { id: this.id, class: 'wq-mechanical-spider',
      'aria-hidden': 'true', 'pointer-events': 'none', 'data-idle': 'true', 'data-mounted': 'false' });
    this._build();
    this.motionQuery = this.doc.defaultView?.matchMedia?.('(prefers-reduced-motion: reduce)');
    this.reducedMotion = Boolean(this.motionQuery?.matches);
    this._onMotion = event => {
      this.reducedMotion = Boolean(event.matches);
      const idle = this.root.getAttribute('data-idle') === 'true';
      this.pose(this.state);
      attribute(this.root, 'data-idle', idle);
      this._syncMotion();
    };
    if (this.motionQuery?.addEventListener) this.motionQuery.addEventListener('change', this._onMotion);
    else this.motionQuery?.addListener?.(this._onMotion);
    this.rest();
    this._syncMotion();
  }

  _build() {
    const id = this.id;
    const defs = add(this.root, 'defs');
    const metal = add(defs, 'linearGradient', { id: `${id}-metal`, x1: '12%', y1: '8%', x2: '85%', y2: '95%' });
    for (const [offset, color] of [[0, '#e8ecf4'], [.19, '#b9c6da'], [.38, '#5a6785'], [.58, '#d3dce9'], [.76, '#8290ab'], [1, '#5a6785']])
      add(metal, 'stop', { offset, 'stop-color': color });
    const shell = add(defs, 'radialGradient', { id: `${id}-shell`, cx: '.28', cy: '.2', r: '.9' });
    for (const [offset, color] of [[0, '#e8ecf4'], [.24, '#bdc9dc'], [.62, '#8291ad'], [1, '#5a6785']])
      add(shell, 'stop', { offset, 'stop-color': color });
    // Small painted halos keep the illuminated metal edges without allocating
    // blur surfaces each time the articulated sprite changes.
    for (const [name, color] of [['cyan', '#33d1ff'], ['pink', '#ff5fa2']]) {
      const glow = add(defs, 'radialGradient', { id: `${id}-${name}-glow` });
      for (const [offset, opacity] of [[0, .65], [.38, .42], [.7, .17], [1, 0]])
        add(glow, 'stop', { offset, 'stop-color': color, 'stop-opacity': opacity });
    }
    add(this.root, 'style', {}, `
      #${id}{isolation:isolate}
      #${id} .wq-spider-animated{transform-box:view-box;transform-origin:0 0}
      #${id}[data-mounted="false"][data-idle="true"] .wq-spider-idle-body{animation:${id}-surface-breathe 3.6s ease-in-out infinite}
      .sprite-motion[data-spider-motion="${id}"].wq-spider-idle{animation:${id}-surface-breathe 3.6s ease-in-out infinite}
      @keyframes ${id}-surface-breathe{0%,100%{transform:translateY(0) scale(1)}50%{transform:translateY(-.49px) scale(1.015)}}
      @media(prefers-reduced-motion:reduce){#${id} .wq-spider-animated{animation:none!important}#${id}-trail{transition:none!important;opacity:0!important}}
    `);
    // Keep the observable body frame symmetric while a gripper extends. Its
    // invisible bounds prevent a changing leg bbox from looking like a jump.
    add(this.root,'rect',{x:-85,y:-75,width:170,height:150,fill:'transparent',opacity:0,'data-body-frame':'true'});
    // One cached art group breathes in standalone mode. Mounted mode uses its
    // outer HTML surface; articulated limbs only change during owner-led events.
    const assembly = add(this.root, 'g', { class: 'wq-spider-idle-body wq-spider-animated' });
    this.animated.push(assembly);
    add(assembly, 'ellipse', { cx: 0, cy: 9, rx: 17, ry: 22, fill: '#020610', opacity: .28 });
    const legLayer = add(assembly, 'g', { class: 'wq-spider-legs', fill: 'none',
      'stroke-linecap': 'round', 'stroke-linejoin': 'round' });
    for (const side of [1, -1]) for (let index = 0; index < 4; index++) {
      const root = add(legLayer, 'g', { class: 'wq-spider-leg' });
      const geometry=add(add(root,'defs'),'path',{id:`${id}-leg-${side}-${index}`});
      const href=`#${geometry.id}`;
      const outline = add(root, 'use', { href,stroke: '#092338', 'stroke-width': 5.6 });
      const limb = add(root, 'use', { href,stroke: `url(#${id}-metal)`, 'stroke-width': 3.35 });
      const light = add(root, 'use', { href,stroke: '#a5efff', 'stroke-width': .75, opacity: .8 });
      const joints = [1.9, 2.15, 1.9, 1.2].map(r => add(root, 'circle', { r,
        fill: '#e8ecf4', stroke: '#33d1ff', 'stroke-width': .7 }));
      const claws = [-1, 1].map(() => add(root, 'path', { stroke: index === 0 ? '#91d7eb' : '#648a9e', 'stroke-width': .7 }));
      this.legs.push({ root, path: geometry, outline, light, limb, joints, foot: joints[3], claws, side, index });
    }
    const body = add(assembly, 'g', { class: 'wq-spider-body' });
    this.body = body;
    const rimLight = add(body, 'g', { class: 'wq-spider-rim' });
    for (const [cy, rx, ry] of [[7.4, 12.4, 16.3], [-8, 9.3, 10.3], [-18, 7.2, 6]]) {
      add(rimLight, 'ellipse', { cx: 0, cy, rx: rx + 5, ry: ry + 5, fill: `url(#${id}-cyan-glow)` });
      add(rimLight, 'ellipse', { cx: 0, cy, rx, ry, fill: 'none', stroke: '#33d1ff', 'stroke-width': 4.4, opacity: .18 });
      add(rimLight, 'ellipse', { cx: 0, cy, rx, ry, fill: 'none', stroke: '#33d1ff', 'stroke-width': 2, opacity: .9 });
    }
    add(body, 'ellipse', { cx: 0, cy: 7.4, rx: 12.4, ry: 16.3, fill: '#050b17', stroke: '#09121f', 'stroke-width': 1.8 });
    add(body, 'ellipse', { class: 'wq-spider-abdomen', cx: 0, cy: 7.4, rx: 11.4, ry: 15.3,
      fill: `url(#${id}-shell)`, stroke: '#c8eaff', 'stroke-width': .9 });
    add(body, 'path', { d: 'M-7-3Q-12 5-8 14', fill: 'none', stroke: '#c0e3ed', 'stroke-width': .65, opacity: .5 });
    for (const [y, width] of [[-3, 7.5], [2, 10.5], [7.5, 11], [13, 10], [18, 7]]) {
      add(body, 'path', { d: `M${-width} ${y}Q0 ${y + 5} ${width} ${y}`, fill: 'none', stroke: '#020917', 'stroke-width': 1.6 });
      add(body, 'path', { d: `M${-width + .5} ${y + .65}Q0 ${y + 5.1} ${width - .5} ${y + .65}`,
        fill: 'none', stroke: '#e8ecf4', 'stroke-width': .6, opacity: .8 });
    }
    add(body, 'path', { d: 'M0-4V20', stroke: '#08111f', 'stroke-width': 2.8 });
    add(body, 'path', { d: 'M0-2V18', stroke: '#33d1ff', 'stroke-width': .6, 'stroke-dasharray': '2.4 3', opacity: .78 });
    add(body, 'ellipse', { cx: 0, cy: 5.5, rx: 5.3, ry: 6.7, fill: `url(#${id}-pink-glow)` });
    add(body, 'path', { d: 'M0 2 2.4 5.5 0 9-2.4 5.5Z', fill: '#ff5fa2' });
    add(body, 'ellipse', { class: 'wq-spider-thorax', cx: 0, cy: -8, rx: 9.3, ry: 10.3,
      fill: `url(#${id}-metal)`, stroke: '#c8eaff', 'stroke-width': .9 });
    add(body, 'path', { d: 'M-7-12-3-6 0-8 3-6 7-12M-7-2 0 0 7-2', fill: 'none', stroke: '#0a1424', 'stroke-width': 1.25 });
    add(body, 'path', { d: 'M-6-12-3-7M3-7 6-12', stroke: '#a6baca', 'stroke-width': .55, opacity: .75 });
    for (const side of [-1, 1]) for (const y of [-11, -5, 1])
      add(body, 'circle', { cx: side * 7.5, cy: y, r: 1, fill: '#15253a', stroke: '#9cb5c6', 'stroke-width': .45 });
    add(body, 'ellipse', { class: 'wq-spider-head', cx: 0, cy: -18, rx: 7.2, ry: 6,
      fill: `url(#${id}-metal)`, stroke: '#95b1c2', 'stroke-width': .7 });
    add(body, 'path', { d: 'M-6-19Q0-25 6-19L4-16H-4Z', fill: '#081222', stroke: '#516e85', 'stroke-width': .55 });
    const eyes = add(body, 'g', { class: 'wq-spider-eye-scan' });
    this.eyes = eyes;
    for (const [x, y, color] of [[-4.2, -19.9, '#ff5fa2'], [-1.45, -20.8, '#33d1ff'], [1.45, -20.8, '#33d1ff'], [4.2, -19.9, '#ff5fa2']]) {
      add(eyes, 'circle', { cx: x, cy: y, r: 3.2, fill: `url(#${id}-${color === '#ff5fa2' ? 'pink' : 'cyan'}-glow)` });
      add(eyes, 'circle', { cx: x, cy: y, r: 1.7, fill: '#030814', stroke: '#9ad4ed', 'stroke-width': .5 });
      add(eyes, 'circle', { class: 'wq-spider-eye', cx: x, cy: y, r: 1.25, fill: color });
      add(eyes, 'circle', { cx: x - .2, cy: y - .2, r: .45, fill: '#f4fdff' });
    }
    add(body, 'path', { d: 'M-3-14-4-11M3-14 4-11', stroke: '#9bb5c5', 'stroke-width': 1.2, 'stroke-linecap': 'round' });
  }

  /** Mount in a centered local SVG; move() positions its HTML surface in scene coordinates. */
  attachSurface(surface) {
    if (this.destroyed) return this;
    if (!surface?.svg?.ownerDocument || typeof surface.move !== 'function')
      throw new TypeError('Spider surface requires an SVG and move(x, y)');
    this.positionSurface = surface;
    this.surfacePoint = null;
    surface.svg.appendChild(this.root);
    attribute(this.root, 'data-mounted', true);
    if (surface.motion) attribute(surface.motion, 'data-spider-motion', this.id);
    // Whole-surface CSS breathing owns the only ambient animation. No SVG
    // timeline is created: even dormant SMIL timelines keep Chrome requesting frames.
    this._position(this.state);
    this._syncMotion();
    return this;
  }

  /** Span surfaces transform a retained unit line; older surfaces keep world paths. */
  attachTrail(surface) {
    if (this.destroyed) return this;
    if (!surface?.svg?.ownerDocument || typeof surface.setBox !== 'function')
      throw new TypeError('Spider trail surface requires an SVG and setBox(box)');
    this.trailSurface = surface;
    surface.svg.appendChild(this.trail);
    attribute(this.trail, 'd', typeof surface.span === 'function' ? 'M0 0H1' : path(this.trailPoints));
    this._trailOpacity(this.trailOpacity, '0s');
    this._positionTrail();
    return this;
  }

  _position({ x, y, angle }) {
    if (this.positionSurface && (!this.surfacePoint || this.surfacePoint.x !== x || this.surfacePoint.y !== y)) {
      if(!this.positionSurface.traveling)this.positionSurface.move(x, y);
      this.surfacePoint = { x, y };
    }
    const translation = this.positionSurface ? '' : `translate(${x} ${y}) `;
    attribute(this.root, 'transform', `${translation}rotate(${angle * 180 / Math.PI}) scale(${this.scale})`);
  }

  _positionTrail() {
    if (!this.trailSurface) return;
    const points = this.trailPoints.length ? this.trailPoints : [this.state];
    if (typeof this.trailSurface.span === 'function') {
      this.trailSurface.span(points[0], points.at(-1));
      return;
    }
    const left = Math.min(...points.map(point => point.x)) - 3;
    const top = Math.min(...points.map(point => point.y)) - 3;
    const width = Math.max(...points.map(point => point.x)) - left + 3;
    const height = Math.max(...points.map(point => point.y)) - top + 3;
    this.trailSurface.setBox({ left, top, width, height });
    attribute(this.trailSurface.svg, 'viewBox', `${left} ${top} ${width} ${height}`);
  }

  pose({ x, y, angle = 0, walk = 0, reach = null, grip = 0, phase, gait = false, travelDistance, smooth = false } = {}) {
    if (this.destroyed) return this;
    ({x,y} = this.centerAt({ x: finite(x, this.state.x), y: finite(y, this.state.y) }));
    angle = finite(angle); walk = clamp(walk); grip = clamp(grip);
    const now=this.doc.defaultView?.performance?.now?.()??Date.now();
    if(gait){
      const previous=this.gaitPoint||this.state;
      const walked=Number.isFinite(travelDistance)?Math.max(0,travelDistance):Math.hypot(x-previous.x,y-previous.y);
      if(walk>0||this.state.walk>0||travelDistance>0)this.gaitPhase+=walked/STRIDE*TAU;
      phase=this.gaitPhase;
    }else{phase=finite(phase,this.gaitPhase);this.gaitPhase=phase;}
    this.gaitPoint={x,y};this.state.phase=phase;
    // Consume every native distance sample, but paint only on this one clock.
    // Fixed deadlines avoid quantization/drift turning 30Hz into 15–20Hz.
    if(smooth){
      if(walk>0)this.walkSettle=null;
      else if(this.walkRequest>0)this.walkSettle={at:now,from:this.state.walk};
      this.walkRequest=walk;
      if(this.nextLegAt!==undefined&&now+.01<this.nextLegAt&&now>=this.lastLegAt)return this;
      const interval=1000/SPIDER_LEG_HZ;
      this.nextLegAt=this.nextLegAt===undefined||now<this.lastLegAt?now+interval:
        this.nextLegAt+Math.max(1,Math.floor((now-this.nextLegAt+.01)/interval)+1)*interval;
      this.lastLegAt=now;
    }else this.nextLegAt=undefined;
    if(smooth){
      const elapsed=Math.max(0,Math.min(100,now-(this.lastSmoothAt??now-1000/SPIDER_LEG_HZ)));
      // A quiet interval cannot accumulate a larger first visible foot step.
      this.lastSmoothAt=now;this.footStep=Math.min(gait?8:4,elapsed*.24);
      if(this.walkSettle){const t=clamp((now-this.walkSettle.at)/300);walk=this.walkSettle.from*(1-t*t*(3-2*t));}
      this.smoothFrame={feet:this.legs.map(leg=>{
        const p=leg.points?.[3]||{x:0,y:0},c=Math.cos(this.state.angle),s=Math.sin(this.state.angle);
        return{x:this.scale*(p.x*c-p.y*s),y:this.scale*(p.x*s+p.y*c)};
      })};
    }else{this.smoothFrame=null;this.lastSmoothAt=null;this.walkSettle=null;this.walkRequest=walk;}
    const target = reach && Number.isFinite(reach.x) && Number.isFinite(reach.y) ? this.targetAt(reach) : null;
    this._trailTo({ x, y }, walk);
    this.state = { x, y, angle, walk, reach: target, grip, phase };
    const c = Math.cos(angle), s = Math.sin(angle);
    const localTarget = target ? { x: ((target.x - x) * c + (target.y - y) * s) / this.scale,
      y: (-(target.x - x) * s + (target.y - y) * c) / this.scale } : null;
    this._position(this.state);
    attribute(this.root, 'data-idle', 'false');
    this.legMotionPending=false;
    for (const [number, leg] of this.legs.entries()) {
      const cached=smooth&&gait&&!(number===0&&localTarget);
      let solved = cached?cachedLegPose(number,phase,this.reducedMotion?0:walk):legPose({ side: leg.side, index: leg.index, phase,
        walk: this.reducedMotion ? 0 : walk, target: number === 0 ? localTarget : null,stance:gait?.5:.64 });
      if(smooth&&leg.points){
        const previous=this.smoothFrame.feet[number];
        const next={x:this.scale*(solved.foot.x*c-solved.foot.y*s),y:this.scale*(solved.foot.x*s+solved.foot.y*c)};
        const distance=Math.hypot(next.x-previous.x,next.y-previous.y);
        if(distance>this.footStep+1e-8){
          this.legMotionPending=true;
          const ratio=this.footStep/distance,limited={x:previous.x+(next.x-previous.x)*ratio,y:previous.y+(next.y-previous.y)*ratio};
          solved=legPose({side:leg.side,index:leg.index,target:{x:(limited.x*c+limited.y*s)/this.scale,y:(-limited.x*s+limited.y*c)/this.scale}});
        }
      }
      const points = [solved.root, solved.elbow, solved.knee, solved.foot];
      const moved=!leg.points||points.some((p,i)=>Math.abs(p.x-leg.points[i].x)>1e-8||Math.abs(p.y-leg.points[i].y)>1e-8);
      if(moved){
        leg.points = points;attribute(leg.path,'d',path(points));
        for (const [index, joint] of leg.joints.entries())attribute(joint,'transform',`translate(${points[index].x} ${points[index].y})`);
      }
      attribute(leg.foot, 'opacity', 1 - solved.lift * .32);
      const shapes=solved.claws&&!(number===0&&grip>0)?solved.claws:clawsFor(solved,number===0?(1-grip)*2.1:.85);
      for (const [index, claw] of leg.claws.entries()) {
        const shape=shapes[index];
        if(!leg.clawPoints||shape.some((p,i)=>Math.abs(p.x-leg.clawPoints[index][i].x)>1e-8||Math.abs(p.y-leg.clawPoints[index][i].y)>1e-8))attribute(claw,'d',path(shape));
      }
      leg.clawPoints=shapes;
    }
    const front = this.legs[0].points[3];
    this.tip = { x: x + this.scale * (front.x * c - front.y * s), y: y + this.scale * (front.x * s + front.y * c) };
    if(smooth&&target){
      const bounded=this.targetAt(this.tip);
      this.state.reach=Math.hypot(bounded.x-this.tip.x,bounded.y-this.tip.y)<.001?bounded:null;
    }
    // Bounce the torso, not the contact geometry or the compositor-owned host.
    if(!this.attention||walk>0)attribute(this.body,'transform',`translate(0 ${(-(Math.sin(phase)**2)*walk*1.1).toFixed(3)})`);
    this._syncMotion();
    return this;
  }

  _confine(point, margin) {
    if (!this.bounds) return {x:point.x,y:point.y};
    const {left,top,right,bottom}=this.bounds;
    const inset=(value,low,high)=>high-low<margin*2 ? (low+high)/2 : Math.max(low+margin,Math.min(high-margin,value));
    return {x:inset(point.x,left,right),y:inset(point.y,top,bottom)};
  }

  centerAt(point) { return this._confine(point,this.clearance); }
  targetAt(point) { return this._confine(point,10); }

  attachAmbient(loop) {
    this.attentionControls?.forEach(control=>control.destroy());
    this.attentionControls=[
      loop.register(this.body,{kind:'spider-weight',attributeName:'transform',values:['translate(0 0)','translate(.35 -.6)','translate(-.3 -.25)','translate(0 0)'],seconds:1.6}),
      loop.register(this.eyes,{kind:'spider-gaze',attributeName:'transform',values:['translate(0 0)','translate(.5 -.15)','translate(-.4 .1)','translate(0 0)'],seconds:2}),
      loop.register(this.legs[7].root,{kind:'spider-foot',attributeName:'transform',values:['translate(0 0)','translate(0 0)','translate(0 -.6)','translate(0 0)'],seconds:2.5}),
    ];
    this.motionKey=null;this._syncMotion();return this;
  }

  attend(value,target=null) {
    const next=Boolean(value);
    if(next&&target&&this.attentionControls){
      const dx=target.x-this.state.x,dy=target.y-this.state.y,c=Math.cos(this.state.angle),s=Math.sin(this.state.angle);
      const aim=Math.max(-.65,Math.min(.65,(dx*c+dy*s)/120));
      this.attentionControls[1].values=[`translate(${aim} -.1)`,`translate(${aim+.25} -.2)`,`translate(${aim-.2} 0)`,`translate(${aim} -.1)`];
    }
    if(this.attention!==next){this.attention=next;this.motionKey=null;this._syncMotion();}
    return this;
  }

  // Query the relaxed gripper without posing and repainting all eight legs.
  restTipAt({x,y,angle=0}) {
    const center=this.centerAt({x,y}),foot=legPose().foot,c=Math.cos(angle),s=Math.sin(angle);
    return {x:center.x+this.scale*(foot.x*c-foot.y*s),y:center.y+this.scale*(foot.x*s+foot.y*c)};
  }

  _trailOpacity(value, duration) {
    const previous = this.trailOpacity;
    this.trailOpacity = value;
    const surface = this.trailSurface;
    if (surface?.motion?.style) {
      if (typeof surface.play === 'function') {
        if (previous !== value || duration === '0s' && this.trailFading
          || surface.motion.style.getPropertyValue('opacity') === '') {
          surface.stop?.();
          this.trailFading = false;
          if (typeof surface.setOpacity === 'function') surface.setOpacity(value);
          else style(surface.motion, 'opacity', value);
          if (duration !== '0s' && previous > value) {
            surface.play([{ opacity: previous }, { opacity: value }], { duration: 2400, easing: 'ease-out' });
            this.trailFading = true;
          }
        }
        style(surface.motion, 'transition', 'none');
      } else {
        style(surface.motion, 'transition', 'opacity 2.4s ease-out');
        style(surface.motion, 'transition-duration', duration);
        if (typeof surface.setOpacity === 'function') surface.setOpacity(value);
        else style(surface.motion, 'opacity', value);
      }
      style(this.trail, 'transition', 'none');
      attribute(this.trail, 'opacity', 1);
    } else {
      style(this.trail, 'transition-duration', duration);
      attribute(this.trail, 'opacity', value);
    }
  }

  _trailTo(next, walk) {
    if (this.paused || this.reducedMotion) { this._clearTrail(); return; }
    const moved = walk > 0 && Math.hypot(next.x - this.state.x, next.y - this.state.y) > .02;
    if (moved) {
      if (!this.trailing) this.trailPoints = [{ x: this.state.x, y: this.state.y }];
      const last = this.trailPoints.at(-1);
      if (Math.hypot(next.x - last.x, next.y - last.y) >= .7) {
        this.trailPoints.push(next);
        if (this.trailPoints.length > 48) this.trailPoints.shift();
        if (typeof this.trailSurface?.span !== 'function') attribute(this.trail, 'd', path(this.trailPoints));
        this._positionTrail();
      }
      this._trailOpacity(.42, '0s');
    } else if (this.trailing) {
      this._trailOpacity(0, '2.4s');
    }
    this.trailing = moved;
  }

  _clearTrail() {
    this.trailPoints = []; this.trailing = false;
    this._trailOpacity(0, '0s');
    if (typeof this.trailSurface?.span !== 'function') attribute(this.trail, 'd', '');
    this._positionTrail();
  }

  rest({atCurrent=false,immediate=false}={}) {
    if (this.destroyed) return this;
    if(atCurrent){
      const position=this.positionSurface?.positionAt?.()||this.state;
      this.positionSurface?.stopTravel?.();
      const now=this.doc.defaultView?.performance?.now?.()??Date.now();
      const settled=this.walkSettle&&now+.01>=this.walkSettle.at+300&&!this.legMotionPending;
      // A completed strength blend may still have feet catching up with a turn.
      this.pose({...position,angle:this.state.angle,gait:true,smooth:!immediate&&!settled});
    }else this.pose(this.home);
    attribute(this.root, 'data-idle', true);
    this._syncMotion();
    return this;
  }

  _syncMotion() {
    const mounted = Boolean(this.positionSurface);
    const idle = this.root.getAttribute('data-idle') === 'true' && !this.reducedMotion;
    const key = `${mounted}:${idle}:${this.paused}:${this.reducedMotion}:${this.attention}`;
    if (this.motionKey === key && this.motionSurface === this.positionSurface) return;
    this.motionKey = key;
    this.motionSurface = this.positionSurface;
    if (this.paused || this.reducedMotion) this._clearTrail();
    for(const control of this.attentionControls||[])control.setActive(this.attention&&!this.paused&&!this.reducedMotion);
    attribute(this.root, 'data-paused', this.paused);
    attribute(this.root, 'data-reduced-motion', this.reducedMotion);
    for (const element of this.animated) {
      style(element, 'animation', mounted || this.reducedMotion ? 'none' : '');
      style(element, 'animation-play-state', this.paused ? 'paused' : 'running');
    }
    if (mounted) {
      const surface = this.positionSurface;
      if (typeof surface.animate === 'function') surface.animate(idle ? 'wq-spider-idle wq-animated' : '');
      else if (surface.motion) style(surface.motion, 'animation', idle ? `${this.id}-surface-breathe 3.6s ease-in-out infinite` : 'none');
      if (surface.motion) style(surface.motion, 'animation-play-state', this.paused ? 'paused' : 'running');

    }
  }

  setPaused(paused) {
    if (this.destroyed) return this;
    this.paused = Boolean(paused);
    this._syncMotion();
    return this;
  }

  destroy() {
    if (this.destroyed) return;
    this.destroyed = true;
    this.positionSurface?.stopTravel?.();
    this.attentionControls?.forEach(control=>control.destroy());
    this.trailSurface?.stop?.();
    if (typeof this.positionSurface?.animate === 'function') this.positionSurface.animate('');
    if (this.motionQuery?.removeEventListener) this.motionQuery.removeEventListener('change', this._onMotion);
    else this.motionQuery?.removeListener?.(this._onMotion);
    this.root.remove();
    this.trail.remove(); this.trailPoints = [];
    this.positionSurface = null; this.trailSurface = null; this.surfacePoint = null;
    this.tip = null;
  }
}
