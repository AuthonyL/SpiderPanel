/* A dependency-free, cutaway factory office. Snapshot text never becomes markup. */
import {AlphaWeb,SCREEN_CONTENT} from './silk.js';
import {SCENE_VIEWBOX,WEB_CENTER,LOWER_SHIFT,RADAR_ORIGIN,SHREDDER_ORIGIN,lowerPoint} from './geometry.js';
import {MechanicalSpider} from './spider.js';
import {FactoryNarrative} from './narrative.js';
import {SceneLayers} from './layers.js';
import {AmbientLoop,discrete,monitorMotion,avatarHands,sleepMotion,expressionMotion} from './ambient.js';
import {WorkLoop} from './work.js';
import {SecondClock} from './second-clock.js';
const NS = 'http://www.w3.org/2000/svg';
const C = {
  floor: '#0b1020', cyan: '#33d1ff', pink: '#ff5fa2', green: '#3ddc84',
  yellow: '#ffd06b', red: '#ff4d5e', purple: '#ab8aff', blue: '#4f7cff',
  ink: '#070b15', muted: '#78869e', light: '#e1eaf5',
};
function attribute(el,key,value) { const next=String(value); if(el.getAttribute(key)!==next)el.setAttribute(key,next); }
function setText(el,value) { const next=String(value); if(el.textContent!==next)el.textContent=next; }
let sceneSerial = 0;

export function iso(x, y, z = 0) {
  return { x: (x - y) * Math.sqrt(3) / 2, y: (x + y) / 2 - z };
}

function node(doc, tag, attrs = {}, content) {
  const el = doc.createElementNS(NS, tag);
  for (const [key, value] of Object.entries(attrs)) {
    if (value !== undefined && value !== null) attribute(el,key, String(value));
  }
  if (content !== undefined) setText(el,String(content));
  return el;
}

function add(parent, tag, attrs = {}, content) {
  const el = node(parent.ownerDocument, tag, attrs, content);
  parent.appendChild(el);
  return el;
}

function label(parent, x, y, content, attrs = {}) {
  return add(parent, 'text', { x, y, fill: C.muted, 'font-size': 10, ...attrs }, content);
}

function points(rows) { return rows.map(p => p.join(',')).join(' '); }
function finite(value, fallback = 0) { return typeof value === 'number' && Number.isFinite(value) ? value : fallback; }
function list(value) { return Array.isArray(value) ? value : []; }
function text(value, fallback = '') { return value === null || value === undefined ? fallback : String(value); }
function short(value, limit = 26) { const s = text(value); return s.length > limit ? `${s.slice(0, limit - 1)}…` : s; }
function color(value, fallback = C.cyan) { return /^#[\da-f]{3,8}$/i.test(text(value)) ? value : fallback; }
function hash(value) { let h = 7; for (const char of text(value)) h = (h * 31 + char.charCodeAt(0)) >>> 0; return h; }
function metric(value) { return typeof value === 'number' && Number.isFinite(value) ? value.toFixed(2) : '—'; }

function sizeBubble(entry,value) {
  const source=text(value).replace(/\s+/g,' ').trim();
  if(entry.bubbleSource===source)return;
  entry.bubbleSource=source;
  const chars=Array.from(source),font=8,padding=20,maximum=168;
  const glyph=char=>font*(char.codePointAt(0)>255?1:.6);
  let content=source,measured=chars.reduce((sum,char)=>sum+glyph(char),0);
  if(measured>maximum-padding){
    const shown=[];measured=font;
    for(const char of chars){if(measured+glyph(char)>maximum-padding)break;shown.push(char);measured+=glyph(char);}
    content=shown.join('')+'…';
  }
  const width=Math.max(64,Math.min(maximum,Math.ceil(measured+padding))),half=width/2;
  entry.bubbleWidth=width;
  attribute(entry.bubble,'data-width',width);
  attribute(entry.bubbleShape,'d',`M${-half}-91H${half}V-67H7L0-61-5-67H${-half}Z`);
  setText(entry.expr,content);
}

function alphaColor(alpha) {
  return ({ done: '#6b7690', eval_failed: '#923548', eval_passed: C.blue,
    prod_ok: C.green, prod_blocked: C.red, candidate: C.pink,
    rejected: '#923548' })[alpha.status] || '#6b7690';
}

/** A small SVG portrait, also used by the cards outside the scene. */
export function createAvatar(shape = 'ghost', bodyColor = C.light, size = 24) {
  const doc = globalThis.document;
  if (!doc) throw new Error('createAvatar requires a document');
  const svg = node(doc, 'svg', {
    viewBox: '0 0 44 48', width: size, height: size, fill: 'none',
    'aria-hidden': 'true', focusable: 'false',
  });
  drawAvatar(svg, shape, bodyColor);
  return svg;
}

function drawAvatar(svg, shape, bodyColor) {
  const fill = color(bodyColor, C.light);
  add(svg, 'ellipse', { cx: 22, cy: 43, rx: 13, ry: 3, fill: '#02040a', opacity: .55 });
  const attrs = { fill, stroke: '#ffffff', 'stroke-opacity': .12, 'stroke-width': .8 };
  switch (shape) {
    case 'square': add(svg, 'rect', { x: 8, y: 9, width: 28, height: 29, rx: 8, ...attrs }); break;
    case 'circle': add(svg, 'circle', { cx: 22, cy: 24, r: 16, ...attrs }); break;
    case 'hexagon': add(svg, 'path', { d: 'M22 6 37 14 37 32 22 41 7 32 7 14Z', ...attrs }); break;
    case 'triangle': add(svg, 'path', { d: 'M18 9Q22 2 26 9L40 35Q43 40 36 40H8Q1 40 5 34Z', ...attrs }); break;
    case 'blob': add(svg, 'path', { d: 'M6 23C1 13 15 5 23 7 36 3 41 16 36 23 44 34 32 43 22 39 10 45 1 34 6 23Z', ...attrs }); break;
    default: add(svg, 'path', { d: 'M7 25C5 2 38 2 37 25V38Q34 41 31 36L27 40 22 36 17 40 12 36Q8 42 7 37Z', ...attrs });
  }
  add(svg, 'path', { d: 'M12 16Q15 10 22 11', stroke: '#fff', 'stroke-width': 2, opacity: .28, 'stroke-linecap': 'round' });
  add(svg, 'ellipse', { cx: 17, cy: 23, rx: 4, ry: 6, fill: '#fff', stroke: '#15273a', 'stroke-opacity': .14, 'stroke-width': .6 });
  add(svg, 'ellipse', { cx: 27, cy: 23, rx: 4, ry: 6, fill: '#fff', stroke: '#15273a', 'stroke-opacity': .14, 'stroke-width': .6 });
  add(svg, 'ellipse', { cx: 18, cy: 23.8, rx: 1.9, ry: 3.3, fill: '#080e1b', class: 'wq-pupil' });
  add(svg, 'ellipse', { cx: 28, cy: 23.8, rx: 1.9, ry: 3.3, fill: '#080e1b', class: 'wq-pupil' });
  add(svg, 'circle', { cx: 17.5, cy: 22.7, r: .6, fill: '#fff' });
  add(svg, 'circle', { cx: 27.5, cy: 22.7, r: .6, fill: '#fff' });
  add(svg, 'path', { d: 'M20 30Q22 32 24 30', stroke: '#102034', 'stroke-width': 1.2, 'stroke-linecap': 'round' });
  add(svg, 'ellipse', { cx: 6, cy: 32, rx: 3.2, ry: 2, fill, stroke: '#fff', 'stroke-opacity': .16, class: 'wq-hand-left wq-animated' });
  add(svg, 'ellipse', { cx: 38, cy: 32, rx: 3.2, ry: 2, fill, stroke: '#fff', 'stroke-opacity': .16, class: 'wq-hand-right wq-animated' });
  if (shape !== 'ghost') {
    add(svg, 'path', { d: 'M16 39 14 43M28 39 30 43', stroke: fill, 'stroke-width': 2, 'stroke-linecap': 'round' });
  }
}

/** A three-face cuboid, projected through the same isometric basis throughout. */
function cuboid(parent, x, y, w, d, h, shades = ['#253047', '#172032', '#101726']) {
  const g = add(parent, 'g');
  const p = (a, b, z) => { const v = iso(a, b, z); return [x + v.x, y + v.y]; };
  add(g, 'polygon', { points: points([p(0, d, 0), p(w, d, 0), p(w, d, h), p(0, d, h)]), fill: shades[1], stroke: '#43506a', 'stroke-opacity': .27 });
  add(g, 'polygon', { points: points([p(w, 0, 0), p(w, d, 0), p(w, d, h), p(w, 0, h)]), fill: shades[2], stroke: '#43506a', 'stroke-opacity': .27 });
  add(g, 'polygon', { points: points([p(0, 0, h), p(w, 0, h), p(w, d, h), p(0, d, h)]), fill: shades[0], stroke: '#66758c', 'stroke-opacity': .38 });
  return g;
}

function plant(parent, x, y, scale = 1) {
  const g = add(parent, 'g', { transform: `translate(${x} ${y}) scale(${scale})` });
  add(g, 'ellipse', { cx: 0, cy: 6, rx: 22, ry: 9, fill: '#030711', opacity: .7 });
  add(g, 'path', { d: 'M-13-7-10 16Q0 23 10 16L13-7Z', fill: '#192b38', stroke: '#425163' });
  add(g, 'ellipse', { cx: 0, cy: -7, rx: 13, ry: 5, fill: '#071218', stroke: '#415160' });
  const leaves = [[-22, -42, -4, -9], [20, -47, 3, -8], [-12, -58, -1, -7], [4, -65, 1, -7], [28, -29, 5, -7], [-28, -27, -5, -7], [15, -58, 2, -8]];
  leaves.forEach(([a, b, c, d], i) => {
    add(g, 'path', { d: `M${c} ${d}Q${a - 13} ${b + 5} ${a} ${b}Q${a + 8} ${b + 12} ${c} ${d}`, fill: i % 2 ? '#244e3d' : '#347c50', stroke: '#69a56a', 'stroke-width': .5, 'stroke-opacity': .4 });
  });
  return g;
}

export class FactoryScene {
  get effects() { return this.narrative?.effects || []; }
  get frame() { return this.narrative?.frame ?? null; }

  constructor(svgElement, { onAlpha, onSessionHover, onCaption } = {}) {
    if (!svgElement?.ownerDocument) throw new TypeError('FactoryScene requires an SVG element');
    this.svg = svgElement;
    this.doc = svgElement.ownerDocument;
    this.win = this.doc.defaultView || globalThis;
    this.id = `wq-factory-${++sceneSerial}`;
    this.layers=new SceneLayers(svgElement,this.id,SCREEN_CONTENT);
    this.canvas=this.layers.canvas;
    this.ambient=new AmbientLoop(this.win);
    this.secondClock=new SecondClock(this.win);
    this.memo=new Map();this.environmentQuiet=true;this.environmentIdle=false;this.lastEventAt=this.win.performance?.now?.()??Date.now();
    this.onAlpha = typeof onAlpha === 'function' ? onAlpha : () => {};
    this.onSessionHover = typeof onSessionHover === 'function' ? onSessionHover : () => {};
    this.onCaption = typeof onCaption === 'function' ? onCaption : () => {};
    this.networkNodes = new Map();
    this.sessionNodes = new Map();
    this.sessionLookup = new Map();
    this.noteNodes = new Map();
    this.linkAnimations = new Set();
    this.stations = [];
    this.lastSeq = null;
    this.day = null;
    this.destroyed = false;
    this.motionQuery = this.win.matchMedia?.('(prefers-reduced-motion: reduce)');
    this.reducedMotion = !!this.motionQuery?.matches;
    attribute(this.svg,'viewBox', SCENE_VIEWBOX);
    attribute(this.svg,'preserveAspectRatio', 'xMidYMid meet');
    attribute(this.svg,'role', 'group');
    attribute(this.svg,'aria-label', 'WQ Alpha Factory，实时会话、机械蜘蛛与 Alpha 蛛网、候选复核办公室');
    this.root = add(this.svg, 'g', { id: this.id, class: 'wq-office', 'font-family': '"SF Mono",Menlo,"JetBrains Mono","PingFang SC",monospace' });
    this._build();
    this._promote();
    this.narrative = new FactoryNarrative(this);
    this.work = new WorkLoop(this);
    this._onVisibility = () => { this._syncMotion(); if (this.doc.hidden) this._clearEffects(); };
    this._onMotion = event => { this.reducedMotion = event.matches; this._syncMotion(); if (event.matches) this._clearEffects(); };
    this.doc.addEventListener('visibilitychange', this._onVisibility);
    if (this.motionQuery?.addEventListener) this.motionQuery.addEventListener('change', this._onMotion);
    else this.motionQuery?.addListener?.(this._onMotion);
    this._syncMotion();
    this.update({});
    // The constructor's empty frame is not the first server snapshot.
    this.lastSeq = null;
    this.day = null;
  }

  _build() {
    const id = this.id;
    const defs = add(this.root, 'defs');
    const floor = add(defs, 'linearGradient', { id: `${id}-floor`, x1: 0, y1: 0, x2: .3, y2: 1 });
    add(floor, 'stop', { offset: '0%', 'stop-color': '#131b2d' });
    add(floor, 'stop', { offset: '100%', 'stop-color': '#080c18' });
    const wall = add(defs, 'linearGradient', { id: `${id}-wall`, x1: 0, y1: 0, x2: 0, y2: 1 });
    add(wall, 'stop', { offset: '0%', 'stop-color': '#111627' });
    add(wall, 'stop', { offset: '100%', 'stop-color': '#0b1120' });
    const glow = add(defs, 'filter', { id: `${id}-glow`, x: '-100%', y: '-100%', width: '300%', height: '300%' });
    add(glow, 'feGaussianBlur', { stdDeviation: 3, result: 'blur' });
    const merge = add(glow, 'feMerge'); add(merge, 'feMergeNode', { in: 'blur' }); add(merge, 'feMergeNode', { in: 'SourceGraphic' });
    const shadow = add(defs, 'filter', { id: `${id}-shadow`, x: '-25%', y: '-25%', width: '160%', height: '180%' });
    add(shadow, 'feDropShadow', { dx: 0, dy: 8, stdDeviation: 8, 'flood-color': '#000', 'flood-opacity': .6 });
    const screenClip = add(defs, 'clipPath', { id: `${id}-screen-clip`, clipPathUnits:'userSpaceOnUse' });
    const {left,top,right,bottom}=SCREEN_CONTENT;
    add(screenClip, 'rect', { x:left, y:top, width:right-left, height:bottom-top });
    const floorClip = add(defs, 'clipPath', { id: `${id}-floor-clip` });
    add(floorClip, 'polygon', { points: '34,456 205,275 1110,275 1180,607 155,607' });
    const style = this.doc.createElement('style');this.layers.root.appendChild(style);
    style.textContent = `
      #${id}{font-family:"SF Mono",Menlo,"JetBrains Mono","PingFang SC",monospace;isolation:isolate}
      #${id} text{pointer-events:none;user-select:none}
      #${id} .wq-hit{cursor:pointer;outline:none}
      #${id} .wq-hit:focus-visible .wq-focus{stroke:#fff;stroke-width:2;stroke-opacity:1}
      #${id} .wq-hit:hover .wq-focus{stroke:#fff;stroke-opacity:.9}
      #${id} .wq-session{cursor:help;outline:none}
      #${id} .wq-session-overlay[data-active="true"] .wq-bubble{opacity:1}
      #${id} .wq-avatar-floating{animation:${id}-float 3.4s ease-in-out infinite;animation-delay:var(--float-delay,0s)}
      #${id} .wq-session[data-idle="false"] .wq-pupil{transform:translate(-1.5px,-2px)}
      #${id} .wq-avatar-floating[data-idle="true"]{animation-duration:5.5s}
      #${id}[data-paused="true"] .wq-animated{animation-play-state:paused!important}
      @keyframes ${id}-float{0%,100%{transform:translateY(0)}50%{transform:translateY(-3px)}}
      @media(prefers-reduced-motion:reduce){#${id} *{transition:none!important;animation:none!important}}
    `;
    setText(style,style.textContent.replaceAll(`#${id}`,`.scene-sprites[data-scene="${id}"]`));
    this.architecture = add(this.root, 'g');
    this._room();
    this._wallDisplay();
    this._reviewBoard();
    this.furniture = add(this.root, 'g', { 'aria-hidden': 'true' });
    this._furniture();
    this.sessionLayer = this.layers.group('sessions');
    this._reviewDesk();
    this._machines();
    this.effectLayer = this.layers.group('effects');
    // SVG painter order keeps every label above desks, portraits and event flights.
    // Only each nameplate receives pointer input; the rest passes through to the room.
    this.sessionOverlay = this.layers.group('session-overlays');
  }

  _promote() {
    this.web.attachLayers(this.layers);
    const trail=this.layers.surface({left:WEB_CENTER.x,top:WEB_CENTER.y,width:1,height:1},{parent:this.layers.webClip,kind:'drag-silk'});
    this.spider.attachTrail(trail);
    const spider=this.layers.surface({left:-120,top:-110,width:240,height:220},{parent:this.layers.webClip,local:true,kind:'spider'});
    this.spider.attachSurface(spider);
    this.spider.attachAmbient(this.ambient);
    const infrastructure=this.layers.group('infrastructure');
    this.layers.root.insertBefore(infrastructure,this.sessionLayer);
    for(const station of this.stations){
      const graphics=node(this.doc,'g',{transform:`translate(${station.x} ${station.y}) ${station.monitor.getAttribute('transform')}`});
      graphics.append(station.chart,...Object.values(station.panels),station.phase,station.load);
      station.miniRoot=graphics;
      station.miniSurface=this.layers.mount(graphics,{left:station.x-4,top:station.y-110,width:104,height:85},{parent:infrastructure,kind:'monitor'});
      station.ambient=monitorMotion(station,this.ambient);
    }
    const leds=node(this.doc,'g',{transform:`matrix(.86 .5 0 1 248 ${279+LOWER_SHIFT})`});
    leds.append(this.cabinetPacked.pattern.parentNode,this.cabinetLampGroup,this.cabinetPacked.g);
    this.layers.mount(leds,{left:248,top:281+LOWER_SHIFT,width:43,height:42},{parent:infrastructure,kind:'cabinet-leds'});
    this.cabinetProgressGroup=add(leds,'g',{'data-batch-progress':'true'});
    this.cabinetLitGroup=add(this.cabinetLampGroup,'g');
    this.cabinetBlink=discrete(this.cabinetLitGroup,'led','opacity',['1','1','.35','.35','1'],1.2,{loop:this.ambient});
    this.packedBlink=discrete(this.cabinetPacked.g,'led','opacity',['1','1','.35','.35','1'],1.2,{loop:this.ambient});
    attribute(this.reviewAvatar,'y',247+LOWER_SHIFT);
    this.layers.mount(this.reviewAvatar,{left:934,top:243+LOWER_SHIFT,width:75,height:82},{parent:infrastructure,kind:'reviewer'});
    attribute(this.radarDish,'transform','');
    this.radarDishSurface=this.layers.mount(this.radarDish,{left:-36,top:-48,width:72,height:92},{parent:infrastructure,local:true,kind:'radar-dish'});
    this.radarDishSurface.move(RADAR_ORIGIN.x,RADAR_ORIGIN.y,-32);
    this.shredderSurface=this.layers.mount(this.shredder,{left:-70,top:-85,width:140,height:170},{parent:infrastructure,local:true,kind:'shredder'});
    attribute(this.shredder,'transform','translate(-145 -485)');this.shredderSurface.move(SHREDDER_ORIGIN.x,SHREDDER_ORIGIN.y);
    // No animation rules or animated elements remain in the cached background.
    for(const el of [this.root,...this.root.querySelectorAll('*')]){
      el.classList.remove('wq-animated','wq-silk-sway');
      const css=el.getAttribute('style');if(css&&/animation|transition/.test(css))el.removeAttribute('style');
    }
    this.layers.root.appendChild(this.sessionOverlay);
  }

  _memo(key,value,render) {
    const encoded=JSON.stringify(value);if(this.memo.has(key)&&this.memo.get(key)===encoded)return;
    this.memo.set(key,encoded);render();
  }

  checkActivity(now=this.win.performance?.now?.()??Date.now()) {
    const quiet=this.environmentQuiet||now-this.lastEventAt>=15000;
    const idle=now-this.lastEventAt>=60000;
    if(quiet!==this.environmentQuiet||idle!==this.environmentIdle){this.environmentQuiet=quiet;this.environmentIdle=idle;this._syncMotion();}
    return idle;
  }

  _room() {
    const g = this.architecture;
    add(g, 'ellipse', { cx: 608, cy: 578+LOWER_SHIFT, rx: 547, ry: 31, fill: '#02040b', opacity: .6 });
    add(g, 'polygon', { points: '34,456 205,275 1110,275 1180,607 155,607', fill: `url(#${this.id}-floor)`, stroke: '#263249' });
    add(g, 'polygon', { points: '34,165 205,52 205,275 34,456', fill: '#0c1221', stroke: '#273149' });
    add(g, 'path', { d: 'M205 52H1110V275H205Z', fill: `url(#${this.id}-wall)`, stroke: '#2d354d' });
    add(g, 'path', { d: 'M205 55H1110M207 274H1110M35 453 205 273', fill: 'none', stroke: C.purple, 'stroke-opacity': .24, 'stroke-width': 2 });
    add(g, 'path', { d: 'M36 160 205 49H1113', fill: 'none', stroke: '#7e668d', 'stroke-opacity': .5, 'stroke-width': 2 });
    const grid = add(g, 'g', { 'clip-path': `url(#${this.id}-floor-clip)`, stroke: '#2f4057', 'stroke-width': .7, opacity: .22 });
    for (let x = -200; x < 1500; x += 105) add(grid, 'path', { d: `M${x} ${270+LOWER_SHIFT}  ${x + 245} ${620+LOWER_SHIFT}`, fill: 'none' });
    for (let y = 308+LOWER_SHIFT; y < 650+LOWER_SHIFT; y += 53) add(grid, 'path', { d: `M0 ${y}H1200`, fill: 'none' });
    // Recessed lighting and a cable tray make the stage read as an actual room.
    add(g, 'path', { d: 'M206 286H1108L1165 593M51 454 208 286', fill: 'none', stroke: '#24374b', 'stroke-width': 5 });
    add(g, 'path', { d: 'M214 287H1105', fill: 'none', stroke: '#4d657a', 'stroke-width': 1, opacity: .4 });
    for (let x = 300; x < 1080; x += 160) add(g, 'rect', { x, y: 281+LOWER_SHIFT, width: 52, height: 2, fill: C.cyan, opacity: .25 });
    label(g, 205, 45, 'RESEARCH FLOOR / 01', { 'font-size': 9, 'letter-spacing': 1.8, fill: '#7f829b' });
    // Oblique left-wall monitors and neon lettering.
    const left = add(g, 'g', { transform: `matrix(1 -.59 0 1 62 ${222+LOWER_SHIFT})` });
    label(left, 0, 0, 'FACTORY', { fill: C.pink, 'font-size': 23, 'font-weight': 800, 'letter-spacing': 2, filter: `url(#${this.id}-glow)` });
    label(left, 2, 17, 'ALPHA RESEARCH LAB', { fill: '#8e7996', 'font-size': 7, 'letter-spacing': .7 });
    add(left, 'rect', { x: 0, y: 39, width: 118, height: 128, rx: 3, fill: '#050b15', stroke: '#344259', 'stroke-width': 3 });
    label(left, 9, 55, 'SIMULATION LOAD', { fill: '#7c8fa4', 'font-size': 6 });
    this.wallBars = [];
    for (let i = 0; i < 16; i++) {
      const h = 5 + ((i * 13 + 7) % 56);
      this.wallBars.push(add(left, 'rect', { x: 9 + i * 6.3, y: 121 - h, width: 3.6, height: h, fill: i % 5 === 0 ? C.pink : C.green, opacity: .65 }));
    }
    add(left, 'path', { d: 'M8 124H109M8 84H109', stroke: '#354057', 'stroke-width': .5, opacity: .5 });
    this.wallLoad = label(left, 9, 142, '00 ACTIVE JOBS', { fill: C.cyan, 'font-size': 8 });
    for (let i = 0; i < 12; i++) add(left, 'rect', { x: 9 + (i % 6) * 16, y: 151 + Math.floor(i / 6) * 7, width: 11, height: 3, fill: i % 3 ? '#335b65' : '#6a365a' });
    const banner = add(g, 'g', { transform: 'translate(231 76)' });
    add(banner, 'path', { d: 'M-4-3H76V162L36 180-4 162Z', fill: '#151e32', stroke: '#35435b', 'stroke-width': 2 });
    add(banner, 'path', { d: 'M1 1H71V156L36 172 1 156Z', fill: '#10172a', stroke: '#64718d', 'stroke-opacity': .35 });
    label(banner, 36, 61, 'WQ', { fill: '#edf2fb', 'font-size': 33, 'font-weight': 900, 'font-style': 'italic', 'text-anchor': 'middle', 'letter-spacing': -5 });
    label(banner, 36, 86, 'WORLDQUANT', { fill: '#aebcd2', 'font-size': 8, 'letter-spacing': .6, 'text-anchor': 'middle' });
    label(banner, 36, 102, 'ALPHA', { fill: '#73819b', 'font-size': 8, 'letter-spacing': 3, 'text-anchor': 'middle' });
    add(banner, 'path', { d: 'M36 119V148M29 141 36 149 43 141', fill: 'none', stroke: C.purple, 'stroke-opacity': .5 });
    add(g, 'path', { d: 'M1110 52 1180 103V339L1110 275Z', fill: '#0c1221', stroke: '#293249' });
    const rightBanner = add(g, 'g', { transform: 'matrix(.68 .23 0 .9 1120 78)' });
    add(rightBanner, 'path', { d: 'M-4-3H76V162L36 180-4 162Z', fill: '#151e32', stroke: '#35435b', 'stroke-width': 2 });
    add(rightBanner, 'path', { d: 'M1 1H71V156L36 172 1 156Z', fill: '#10172a', stroke: '#64718d', 'stroke-opacity': .35 });
    label(rightBanner, 36, 61, 'WQ', { fill: '#edf2fb', 'font-size': 33, 'font-weight': 900, 'font-style': 'italic', 'text-anchor': 'middle', 'letter-spacing': -5 });
    label(rightBanner, 36, 86, 'WORLDQUANT', { fill: '#aebcd2', 'font-size': 8, 'letter-spacing': .6, 'text-anchor': 'middle' });
    label(rightBanner, 36, 106, 'RESEARCH', { fill: '#73819b', 'font-size': 8, 'letter-spacing': 1, 'text-anchor': 'middle' });
    add(rightBanner, 'path', { d: 'M36 119V148M29 141 36 149 43 141', fill: 'none', stroke: C.purple, 'stroke-opacity': .5 });
  }

  _wallDisplay() {
    const g = this.architecture;
    add(g, 'rect', { x: 338, y: 62, width: 514, height: 210+LOWER_SHIFT, rx: 7, fill: '#040912', stroke: '#36455e', 'stroke-width': 3, filter: `url(#${this.id}-shadow)` });
    add(g, 'rect', { x: 345, y: 69, width: 500, height: 197+LOWER_SHIFT, rx: 3, fill: '#070f1b', stroke: '#536075', 'stroke-opacity': .5 });
    add(g, 'path', { d: `M354 89H835M354 ${239+LOWER_SHIFT}H835`, stroke: '#263951', 'stroke-width': .8 });
    this.networkTitle = label(g, 358, 83, 'ALPHAS · TODAY · 0 NODES', { fill: C.cyan, 'font-size': 8, 'letter-spacing': 1.1 });
    this.networkCount = label(g, 834, 83, '000 NODES', { 'text-anchor': 'end', 'font-size': 8, fill: '#7898ad' });
    this.web = new AlphaWeb(g, {id:this.id,onAlpha:id=>this.onAlpha(id),clipId:`${this.id}-screen-clip`});
    this.networkNodes = this.web.nodes;
    this.networkLayer = this.web.layer;
    this.networkLinks = this.web.wires;
    this.spider = new MechanicalSpider(this.web.content, {id:this.id,...WEB_CENTER,bounds:SCREEN_CONTENT});
    this.screenWaiting = add(g, 'g', { 'aria-hidden': 'true' });
    add(this.screenWaiting, 'rect', {x:450,y:93,width:290,height:18,rx:2,fill:'#070f1b','fill-opacity':.9});
    label(this.screenWaiting, 595, 106, 'WAITING FOR MINERS', {fill:'#8aa8bb','font-size':11,'letter-spacing':2,'text-anchor':'middle'});
    label(this.screenWaiting, 595, 213+LOWER_SHIFT, '等待会话送来第一批 Alpha', {fill:'#4e6c83','font-size':8,'text-anchor':'middle'});
    this.sparkline = add(g, 'path', { d: '', fill: 'none', stroke: C.green, 'stroke-width': 1.6, 'stroke-linecap': 'round' });
    this.sparklineArea = add(g, 'path', { d: '', fill: C.green, opacity: .055 });
    this.sparklineLabel = label(g, 356, 254+LOWER_SHIFT, '合格最佳 SHARPE —', { fill: '#89a29b', 'font-size': 7.5 });
    this.screenFooter = label(g, 834, 254+LOWER_SHIFT, 'AWAITING SIGNAL', { fill: '#627890', 'font-size': 7.5, 'text-anchor': 'end' });
    this.regionBadges = [];
    this.regionBadgeLayer = add(g, 'g');
    for (let i = 0; i < 4; i++) this._addRegionBadge();
  }

  _addRegionBadge() {
    const index = this.regionBadges.length;
    const g = add(this.regionBadgeLayer, 'g');
    const outer = add(g, 'circle', { r: 15, fill: '#101c2b', stroke: index % 2 ? '#9d7fb1' : '#4c95b8', 'stroke-width': 1.5, 'stroke-opacity': .8 });
    const inner = add(g, 'circle', { r: 12, fill: 'none', stroke: '#657a96', 'stroke-width': .5, 'stroke-opacity': .4 });
    const caption = label(g, 0, 3, '', { 'font-size': 7, fill: '#a9bfd3', 'text-anchor': 'middle' });
    this.regionBadges.push({ g, outer, inner, text: caption, title: add(g, 'title') });
  }

  _reviewBoard() {
    const g = this.architecture;
    add(g, 'rect', { x: 886, y: 78, width: 202, height: 174, rx: 3, fill: '#1b1722', stroke: '#403348', 'stroke-width': 5 });
    add(g, 'rect', { x: 892, y: 84, width: 190, height: 162, rx: 1, fill: '#292232' });
    for (let i = 0; i < 55; i++) add(g, 'circle', { cx: 897 + (i * 37 % 181), cy: 91 + (i * 23 % 147), r: .65, fill: '#8e7287', opacity: .15 });
    label(g, 987, 103, 'AWAITING REVIEW', { fill: '#d0afce', 'font-size': 9, 'font-weight': 700, 'letter-spacing': 1, 'text-anchor': 'middle' });
    add(g, 'path', { d: 'M903 111H1071', stroke: '#5b435e', 'stroke-width': .7 });
    for (let i = 0; i < 9; i++) add(g, 'rect', { x: 903 + (i % 3) * 57, y: 121 + Math.floor(i / 3) * 34, width: 47, height: 27, rx: 1, fill: '#352d3a', stroke: '#66526b', 'stroke-opacity': .25, 'stroke-dasharray': '2 3' });
    this.noteLayer = this.layers.group('review-notes');
    this.reviewMore = label(g, 1071, 238, 'NO CANDIDATES YET', { 'font-size': 7, 'text-anchor': 'end', fill: '#977a97' });
  }

  _furniture() {
    const g = this.furniture;
    // Desk coordinates are also the start points for event flights.
    const coords = [[329, 362], [531, 362], [733, 362], [348, 520], [550, 520], [752, 520]];
    coords.forEach(([x, y], index) => {
      const station = add(g, 'g', { transform: `translate(${x} ${y})`, 'data-desk': index });
      add(station, 'ellipse', { cx: 47, cy: 56, rx: 86, ry: 25, fill: '#02050d', opacity: .5 });
      // Four legs and the three-shaded desktop have a shared projection.
      [[0, 0], [121, 0], [0, 43], [121, 43]].forEach(([a, b]) => {
        const p = iso(a, b);
        add(station, 'path', { d: `M${p.x} ${p.y - 34}V${p.y + 2}`, stroke: '#35415a', 'stroke-width': 5 });
        add(station, 'path', { d: `M${p.x + 1} ${p.y - 34}V${p.y + 1}`, stroke: '#617087', 'stroke-width': 1, opacity: .4 });
      });
      cuboid(station, 0, 0, 128, 47, 42, ['#253047', '#172032', '#131b2a']);
      // The monitor face is slightly slanted with the desktop's long edge.
      const monitor = add(station, 'g', { transform: 'matrix(1 .17 0 1 4 -49)' });
      add(monitor, 'path', { d: 'M37 0V9H26M37 9H49', stroke: '#58677d', 'stroke-width': 3 });
      add(monitor, 'rect', { x: -4, y: -54, width: 94, height: 55, rx: 3, fill: '#050a14', stroke: '#52617a', 'stroke-width': 2 });
      add(monitor, 'rect', { x: 1, y: -49, width: 84, height: 44, fill: '#071525', stroke: '#132c40' });
      add(monitor, 'path', { d: 'M5-16H81M5-31H81', stroke: '#1d354b', 'stroke-width': .5 });
      const chart = add(monitor, 'path', { d: 'M7-17 17-24 28-21 39-34 50-29 61-36 73-33 80-40', fill: 'none', stroke: '#37586f', 'stroke-width': 1.3 });
      const panels = {};
      const simPanel = panels.simulating = add(monitor, 'g', { 'data-phase-graphic': 'simulating' });
      const simDecor=add(simPanel, 'path', { d: 'M7-31H80M7-25H42', stroke: '#22607c', 'stroke-width': 1.2 });
      const workElapsed=label(simPanel,7,-27,'',{fill:C.cyan,'font-size':7,display:'none'});
      add(simPanel, 'rect', { x: 7, y: -20, width: 72, height: 5, rx: 1, fill: '#102c3d' });
      const progress=add(simPanel, 'rect', { x: 7, y: -20, width: 72, height: 5, rx: 1, fill: C.cyan, opacity: .8, class: 'wq-progress wq-animated' });
      const evalPanel = panels.evaluating = add(monitor, 'g', { 'data-phase-graphic': 'evaluating' });
      for (let i = 0; i < 9; i++) {
        const height = 7 + (i * 7 + 4) % 19;
        add(evalPanel, 'rect', { x: 8 + i * 8, y: -12 - height, width: 4.5, height, fill: i % 3 ? C.blue : C.green, opacity: .8, class: 'wq-eval-bar wq-animated', style: `animation-delay:-${i * .19}s` });
      }
      const prodPanel = panels.prod = add(monitor, 'g', { 'data-phase-graphic': 'prod', transform: 'translate(43 -25)' });
      [7, 14].forEach(r => add(prodPanel, 'circle', { r, fill: 'none', stroke: '#54647e', 'stroke-width': .6 }));
      add(prodPanel, 'path', { d: 'M-16 0H16M0-16V16', stroke: '#394b68', 'stroke-width': .6 });
      const sweep = add(prodPanel, 'g', { class: 'wq-radar-sweep wq-animated' });
      add(sweep, 'path', { d: 'M0 0H14A14 14 0 0 1 7 12Z', fill: C.purple, opacity: .3 });
      add(sweep, 'path', { d: 'M0 0H14', stroke: C.purple, 'stroke-width': 1.2 });
      add(prodPanel, 'circle', { cx: 8, cy: -5, r: 1.5, fill: C.purple });
      add(prodPanel, 'circle', { cx: -6, cy: 7, r: 1, fill: C.green });
      const idlePanel = panels.idle = add(monitor, 'g', { 'data-phase-graphic': 'idle' });
      add(idlePanel, 'rect', { x: 1, y: -49, width: 84, height: 44, fill: '#02050b' });
      const savingPanel = panels.saving = add(monitor, 'g', { 'data-phase-graphic': 'saving' });
      add(savingPanel, 'path', { d: 'M34-36H47L52-31V-13H34Z', fill: C.pink, opacity: .8 });
      add(savingPanel, 'path', { d: 'M47-36V-31H52M38-26H47M38-22H47M38-18H44', fill: 'none', stroke: '#141a2a', 'stroke-width': 1 });
      const thinkingPanel=panels.thinking=add(monitor,'g',{'data-phase-graphic':'thinking'});
      const thinkingElapsed=label(thinkingPanel,7,-25,'构思中 0:00',{fill:C.blue,'font-size':7});
      label(thinkingPanel,7,-14,'...',{fill:'#637e99','font-size':9});
      const phase = label(monitor, 5, -40, 'STANDBY', { fill: '#65798e', 'font-size': 6.4 });
      const load = label(monitor, 80, -8, '—', { fill: '#4a6980', 'font-size': 5.5, 'text-anchor': 'end' });
      add(monitor, 'circle', { cx: 81, cy: -1, r: 1, fill: '#8ba2b5', opacity: .6 });
      // Keyboard, trackpad, mug, and a tucked-in chair.
      const keys = add(station, 'g', { transform: 'matrix(1 .2 -.7 .8 3 -25)' });
      add(keys, 'rect', { x: 0, y: 0, width: 52, height: 14, rx: 2, fill: '#0c1320', stroke: '#566078', 'stroke-opacity': .5 });
      for (let row = 0; row < 3; row++) for (let col = 0; col < 9; col++) add(keys, 'rect', { x: 4 + col * 5, y: 3 + row * 3.4, width: 3, height: 1.5, fill: '#7b8798', opacity: .45 });
      add(station, 'ellipse', { cx: 75, cy: -14, rx: 4, ry: 6, fill: '#667488', transform: 'rotate(24 75 -14)' });
      add(station, 'path', { d: 'M89-34V-23Q96-18 101-23V-34Z', fill: '#263b50', stroke: '#637189', 'stroke-width': .6 });
      add(station, 'ellipse', { cx: 95, cy: -34, rx: 6, ry: 2, fill: '#0b1520', stroke: '#718398', 'stroke-width': .6 });
      add(station, 'path', { d: 'M101-31Q109-31 104-24H101', fill: 'none', stroke: '#65768c' });
      const chair = add(station, 'g', { transform: 'translate(24 45)' });
      add(chair, 'path', { d: 'M0 2V17M0 17-17 23M0 17 17 23M0 17 0 27', stroke: '#3a4558', 'stroke-width': 2 });
      add(chair, 'path', { d: 'M-18-18Q0-23 18-15L15 2Q0 10-15 2Z', fill: '#172131', stroke: '#3a465d' });
      add(chair, 'path', { d: 'M-16-30Q1-36 17-27L16-11Q0-5-16-13Z', fill: '#1f2a3b', stroke: '#47536a' });
      add(chair, 'path', { d: 'M-12-26Q0-29 12-23', fill: 'none', stroke: '#65718a', opacity: .25 });
      add(station, 'path', { d: 'M83 24Q108 49 86 65', fill: 'none', stroke: '#03060c', 'stroke-width': 3 });
      label(station, -20, 3, String(index + 1).padStart(2, '0'), { fill: '#76849c', 'font-size': 6, transform: 'rotate(30 -20 3)' });
      this.stations.push({ x, y:y+LOWER_SHIFT, phase, chart, load, monitor, panels,simDecor,workElapsed,progress,thinkingElapsed });
    });
    // Floor conduit joins the desk rows to the equipment rack.
    add(g, 'path', { d: 'M378 425Q407 449 462 438H818Q849 439 851 399L855 320M398 584Q489 609 851 592L876 524', fill: 'none', stroke: '#02050c', 'stroke-width': 3, opacity: .8 });
    add(g, 'path', { d: 'M379 426Q413 446 462 440H816', fill: 'none', stroke: '#314257', 'stroke-width': .7, opacity: .55 });
    plant(g, 218, 332, .83);
    plant(g, 1130, 380, .83);
    plant(g, 844, 575, .76);
    plant(g, 286, 580, .7);
    // Small server rack at the far right, with separate bays and status LEDs.
    cuboid(g, 1117, 435, 40, 31, 111, ['#1f2a3c', '#142033', '#0b1220']);
    for (let i = 0; i < 5; i++) {
      add(g, 'path', { d: `M1094 ${346 + i * 16} 1128 ${366 + i * 16}`, stroke: '#46526a', 'stroke-width': 1 });
      add(g, 'circle', { cx: 1102, cy: 354 + i * 16, r: 1.1, fill: i === 3 ? C.purple : C.green, opacity: .75 });
    }
  }

  _reviewDesk() {
    const g = add(this.root, 'g', { 'aria-hidden': 'true' });
    add(g, 'ellipse', { cx: 986, cy: 380, rx: 106, ry: 22, fill: '#02050c', opacity: .55 });
    add(g, 'path', { d: 'M900 321V370M1065 343V387M1026 308V357', stroke: '#374259', 'stroke-width': 6 });
    cuboid(g, 933, 311, 155, 46, 17, ['#2b354b', '#172034', '#11182a']);
    const monitor = add(g, 'g', { transform: 'matrix(1 .13 0 1 1006 285)' });
    add(monitor, 'rect', { x: 0, y: -35, width: 44, height: 29, rx: 2, fill: '#050c17', stroke: '#52607b', 'stroke-width': 2 });
    add(monitor, 'path', { d: 'M21-5V4M10 4H33', stroke: '#57647c', 'stroke-width': 2 });
    [8, 14, 20].forEach((y, i) => add(monitor, 'path', { d: `M5 ${-35 + y}H${22 + i * 7}`, stroke: i === 0 ? C.purple : '#456a78', 'stroke-width': 1.6 }));
    add(g, 'path', { d: 'M1012 305 1042 309 1037 315 1007 311Z', fill: '#667085', stroke: '#9ba2b0', 'stroke-width': .5 });
    for (let i = 0; i < 3; i++) add(g, 'path', { d: `M${1060 + i} ${306 - i * 3} 1080 ${309 - i * 3} 1080 ${325 - i * 3} ${1060 + i} ${322 - i * 3}Z`, fill: i === 2 ? '#c2b9d7' : '#6a6685', stroke: '#202b3f', 'stroke-width': .7 });
    const avatar = this.reviewAvatar = add(g, 'svg', { x: 938, y: 247, width: 66, height: 73, viewBox: '0 0 44 48' });
    drawAvatar(avatar, 'ghost', '#e5e2f4');
    add(avatar, 'path', { d: 'M6 23Q3 6 21 5 42 6 38 25', fill: 'none', stroke: '#a08ed6', 'stroke-width': 4 });
    add(avatar, 'rect', { x: 4, y: 20, width: 6, height: 12, rx: 3, fill: '#6a558e', stroke: '#c5b7e9' });
    add(avatar, 'rect', { x: 34, y: 20, width: 6, height: 12, rx: 3, fill: '#6a558e', stroke: '#c5b7e9' });
    add(avatar, 'path', { d: 'M36 29Q35 37 28 35', fill: 'none', stroke: '#bba8e5', 'stroke-width': 1.5 });
    label(g, 988, 346, '你的复核台 · HEAD OF THE FLOOR', { 'font-size': 6.7, fill: '#c0b2d2', 'text-anchor': 'middle', 'letter-spacing': .3 });
    label(g, 986, 363, 'HUMAN IN THE LOOP', { 'font-size': 6, fill: '#67748d', 'text-anchor': 'middle', 'letter-spacing': 1 });
  }

  _machines() {
    // The simulator is behind the first row, beside the lower-left web corner.
    const cabinet=this.cabinet=add(this.root,'g',{'aria-hidden':'true','data-machine':'simulation'});
    add(cabinet,'ellipse',{cx:280,cy:366,rx:44,ry:12,fill:'#02050d',opacity:.65});
    cuboid(cabinet,276,329,50,36,85,['#30425a','#142337','#0b1628']);
    add(cabinet,'path',{d:'M252 269 285 288 304 277 272 258Z',fill:'#050b15',stroke:'#617c98','stroke-width':1.4});
    const face=add(cabinet,'g',{transform:'matrix(.86 .5 0 1 248 279)'});
    add(face,'rect',{x:0,y:0,width:45,height:59,rx:2,fill:'#071220',stroke:'#344d66'});
    this.cabinetLampGroup=add(face,'g');
    this.cabinetLamps=[];
    for(let i=0;i<16;i++)this.cabinetLamps.push(add(this.cabinetLampGroup,'circle',{cx:5+(i%8)*5,cy:8+Math.floor(i/8)*7,r:1.6,fill:'#263d48',class:'wq-cabinet-led','data-lit':'false'}));
    // A pattern packs larger live counts without allocating one SVG node per job.
    const defs=add(face,'defs'),pattern=add(defs,'pattern',{id:`${this.id}-sim-leds`,x:3,y:4,width:4,height:4,patternUnits:'userSpaceOnUse'});
    const dot=add(pattern,'circle',{r:1,fill:C.cyan});
    const packed=add(face,'g',{display:'none',class:'wq-cabinet-led wq-animated','data-lit':'true',fill:`url(#${this.id}-sim-leds)`});
    this.cabinetPacked={g:packed,pattern,dot,rows:add(packed,'rect',{x:3,y:4}),last:add(packed,'rect',{x:3,y:4})};
    label(face,23,29,'SIM BATCHES',{'font-size':4.7,'text-anchor':'middle',fill:'#7c94b0'});
    this.cabinetCount=label(face,23,47,'00',{'font-size':14,'font-weight':700,'text-anchor':'middle',fill:C.cyan});
    add(face,'path',{d:'M5 52H40M5 55H40',stroke:'#34516a','stroke-width':.7});
    label(cabinet,278,373,'WQ BRAIN · SIM',{'font-size':7,'text-anchor':'middle',fill:'#b0c7dc'});
    this.cabinetIntake=lowerPoint(268,280);this.cabinetOutput=lowerPoint(309,270);
    this.shredder = add(this.root, 'g', { 'aria-hidden': 'true' });
    const s = this.shredder;
    add(s, 'ellipse', { cx: 143, cy: 543, rx: 61, ry: 16, fill: '#02040a', opacity: .7 });
    cuboid(s, 136, 504, 67, 49, 83, ['#252c3e', '#151b2a', '#0c1421']);
    add(s, 'path', { d: 'M114 441 157 466 178 454 135 429Z', fill: '#04070e', stroke: '#637085', 'stroke-width': 2 });
    for (let i = 0; i < 12; i++) add(s, 'path', { d: `M${123 + (i % 4) * 9} ${434 + (i % 4) * 5 - i % 3 * 2}l${i % 2 ? 2 : -2} -${8 + i % 5 * 3}`, stroke: i % 3 ? '#adb7c9' : '#6d8198', 'stroke-width': 2 });
    add(s, 'path', { d: 'M110 468 166 500 166 527 110 495Z', fill: '#0b1120', stroke: '#35435b' });
    label(s, 138, 492, 'SHREDDER', { 'font-size': 7, fill: '#9da8bc', transform: 'rotate(30 138 492)', 'text-anchor': 'middle' });
    this.rejectCount = label(s, 135, 515, '0', { 'font-size': 12, 'font-weight': 700, fill: C.red, transform: 'rotate(30 135 515)', 'text-anchor': 'middle' });
    label(s, 142, 565, 'REJECTED · 淘汰', { 'font-size': 8, fill: '#73849c', 'text-anchor': 'middle', 'letter-spacing': .5 });
    // Satellite and receiver are grouped so event pulses can originate here.
    const radar = add(this.root, 'g', { 'aria-hidden': 'true' });
    add(radar, 'ellipse', { cx: 1079, cy: 577, rx: 69, ry: 14, fill: '#02040a', opacity: .6 });
    cuboid(radar, 1068, 555, 78, 49, 19, ['#283348', '#162034', '#0b1425']);
    add(radar, 'path', { d: 'M1072 535 1063 501M1056 537 1087 545', stroke: '#55657a', 'stroke-width': 5 });
    const dish = add(radar, 'g', { transform: 'translate(1060 492) rotate(-32)' });
    this.radarDish=dish;
    add(dish, 'ellipse', { cx: 0, cy: 0, rx: 29, ry: 37, fill: '#273142', stroke: '#a2adc0', 'stroke-width': 1.6 });
    add(dish, 'ellipse', { cx: 0, cy: 0, rx: 18, ry: 37, fill: 'none', stroke: '#5d6a7e', 'stroke-width': .8 });
    add(dish, 'ellipse', { cx: 0, cy: 0, rx: 7, ry: 37, fill: 'none', stroke: '#5d6a7e', 'stroke-width': .8 });
    [-22, -10, 3, 17, 29].forEach(y => add(dish, 'path', { d: `M-25 ${y}Q0 ${y + 12} 25 ${y}`, fill: 'none', stroke: '#5d6a7e', 'stroke-width': .8 }));
    add(dish, 'path', { d: 'M-24 21 0-5 24 21M0-5 0-42', fill: 'none', stroke: '#bdc7d3', 'stroke-width': 1.6 });
    add(dish, 'circle', { cx: 0, cy: -43, r: 3, fill: C.cyan });
    [16, 25, 34].forEach(r => add(radar, 'path', { d: `M1100 ${480 - r}Q${1111 + r / 2} 475 1105 ${485 + r / 3}`, fill: 'none', stroke: C.green, 'stroke-width': 1.4, opacity: .18 + r / 130 }));
    label(radar, 1080, 570, 'PROD RADAR', { fill: '#b3c1d3', 'font-size': 8, 'text-anchor': 'middle', 'letter-spacing': .8 });
    this.radarStatus = label(radar, 1080, 594, 'CORRELATION SCAN', { fill: '#61758a', 'font-size': 6.8, 'text-anchor': 'middle' });
    this.runner = add(this.root, 'g', { class: 'wq-hit', tabindex: -1, role: 'button' });
    this.runner.addEventListener('click', () => { if (this.bestId) this.onAlpha(this.bestId); });
    this.runner.addEventListener('keydown', event => { if (this.bestId && (event.key === 'Enter' || event.key === ' ')) { event.preventDefault(); this.onAlpha(this.bestId); } });
    add(this.runner, 'ellipse', { cx: 936, cy: 557, rx: 52, ry: 14, fill: '#02040a', opacity: .65 });
    cuboid(this.runner, 930, 531, 62, 45, 22, ['#31384f', '#1b2239', '#11192a']);
    add(this.runner, 'rect', { x: 894, y: 535, width: 90, height: 19, rx: 3, fill: '#0d1526', stroke: '#4b526c', class: 'wq-focus' });
    label(this.runner, 939, 547, '合格最佳', { fill: '#c8c9df', 'font-size': 8, 'text-anchor': 'middle', 'letter-spacing': .6 });
    const rocket = add(this.runner, 'g', { transform: 'translate(938 486)' });
    add(rocket, 'path', { d: 'M-8 9-19 25-16 37-7 28M8 9 19 25 16 37 7 28', fill: '#8275bd', stroke: '#c1b9e3', 'stroke-width': .7 });
    add(rocket, 'path', { d: 'M0-47C-12-27-13 7-8 28H8C13 7 12-27 0-47Z', fill: '#c9cddd', stroke: '#f4efff', 'stroke-width': .8 });
    add(rocket, 'path', { d: 'M0-47C1-11 3 8 1 28H8C13 7 12-27 0-47Z', fill: '#8a91b2' });
    add(rocket, 'path', { d: 'M-7-30H7L0-47Z', fill: '#665783' });
    add(rocket, 'ellipse', { cx: -1, cy: -12, rx: 5, ry: 8, fill: '#152b48', stroke: '#eeeffa', 'stroke-width': 1.6 });
    add(rocket, 'path', { d: 'M-2-16 1-20', stroke: C.cyan, 'stroke-width': 2, 'stroke-linecap': 'round' });
    add(rocket, 'path', { d: 'M-6 30-3 39 0 34 3 40 6 30', fill: C.cyan, opacity: .4 });
    this.runnerId = label(this.runner, 939, 571, '暂无合格 alpha', { fill: '#8a8da6', 'font-size': 7, 'text-anchor': 'middle' });
    this.runnerSharpe = label(this.runner, 939, 585, 'SHARPE —', { fill: C.purple, 'font-size': 8, 'text-anchor': 'middle' });
  }

  _alphaActions(entry) {
    entry.g.addEventListener('click', () => this.onAlpha(text(entry.data.id)));
    entry.g.addEventListener('keydown', event => {
      if (event.key === 'Enter' || event.key === ' ') { event.preventDefault(); this.onAlpha(text(entry.data.id)); }
    });
  }

  _network(alphas) {
    this.web.update(alphas, this.allowEnterAnimations);
    const total=list(alphas).length;
    setText(this.networkCount,total>60?`+${total-60} OUTSIDE WEB`:'LIVE WEB');
    attribute(this.screenWaiting,'display',this.networkNodes.size?'none':'inline');
  }

  _sessions(sessions) {
    const all = list(sessions).filter(s => s && typeof s === 'object');
    this.sessionLookup=new Map(all.map(session=>[String(session.pid),session]));
    const rows = all.slice(0, all.length > 6 ? 5 : 6);
    const grouped = all.length > 6 ? all.slice(5) : [];
    if (grouped.length) {
      const counts = Object.fromEntries(['exprs', 'alphas', 'eval_passed', 'candidates'].map(key => [key, grouped.reduce((sum, s) => sum + finite(s.counts?.[key]), 0)]));
      const idle = grouped.every(s => s.idle === true || s.phase === 'idle');
      rows.push({ pid: '__aggregate__', aggregate: true, grouped_sessions: grouped.length, grouped_pids: grouped.map(session=>String(session.pid??0)),
        label: `+${grouped.length} 会话`, shape: 'blob', color: C.purple,
        region: 'MULTI', universe: 'PARALLEL', phase: idle ? 'idle' : 'aggregate',
        phase_label: idle ? '空闲' : '并行矿工', idle, counts,
        running_sims: grouped.reduce((sum, s) => sum + finite(s.running_sims), 0),
        last_expr: `${grouped.length} 个会话在后台并行工作` });
    }
    const keep = new Set();
    this.sessionPositions = new Map();
    this.stations.forEach(station => {
      setText(station.phase,all.length ? '' : 'STANDBY');
      attribute(station.phase,'fill', '#61768c');
      attribute(station.monitor,'data-powered', all.length ? 'off' : 'standby');
      attribute(station.monitor,'opacity', all.length ? .48 : 1);
      attribute(station.monitor,'transform', all.length ? 'matrix(1 .17 0 .6 4 -49)' : 'matrix(1 .17 0 1 4 -49)');
      attribute(station.chart,'stroke', '#365067');
      attribute(station.chart,'opacity', .45);
      attribute(station.chart,'display', 'none');
      Object.entries(station.panels).forEach(([phase, panel]) => attribute(panel,'display', phase === 'idle' ? 'inline' : 'none'));
      setText(station.load,'');
    });
    rows.forEach((session, index) => {
      const key = text(session.pid, `session-${index}`);
      if (keep.has(key)) return;
      keep.add(key);
      const station = this.stations[index];
      const fill = color(session.color, [C.light, C.red, C.blue, C.yellow, C.pink, C.green][index]);
      let entry = this.sessionNodes.get(key);
      if (!entry) {
        const g = add(this.sessionLayer, 'g', { class: 'wq-session', role: 'group', tabindex: 0, 'data-session': key });
        const portrait = add(g, 'svg', { x: -31, y: -58, width: 62, height: 67, viewBox: '0 0 44 48', 'aria-hidden': 'true', class: 'wq-avatar-floating wq-animated', style: `animation-delay:-${index * .43}s` });
        const overlay = add(this.sessionOverlay, 'g', { class: 'wq-session-overlay', 'data-active': 'false' });
        const badge = add(overlay, 'g', { 'pointer-events': 'all', style: 'cursor:help' });
        add(badge, 'rect', { x: -50, y: 18, width: 100, height: 32, rx: 3, fill: '#0a1422', 'fill-opacity': .93, stroke: '#3a4961', 'stroke-opacity': .6 });
        const name = label(badge, 0, 31, '', { fill: '#ced8e9', 'font-size': 8.1, 'text-anchor': 'middle' });
        const sub = label(badge, 0, 43, '', { fill: '#6e8ba0', 'font-size': 6.2, 'text-anchor': 'middle' });
        const dot = add(badge, 'circle', { cx: -42, cy: 28, r: 2 });
        const sleep = label(overlay, 33, -43, 'z z z', { fill: '#b0bed4', 'font-size': 15, 'letter-spacing': 2, class: 'wq-zzz' });
        const bubble = add(overlay, 'g', { opacity:0, class: 'wq-bubble', 'aria-hidden': 'true', 'pointer-events': 'none' });
        const bubbleShape=add(bubble, 'path', { fill: '#0e1b2d', stroke: '#5a758b', 'stroke-width': .8 });
        const expr = label(bubble, 0, -76, '', { fill: '#c2d5e5', 'font-size': 8, 'text-anchor': 'middle' });
        const more = label(overlay, 0, 64, '', { fill: C.purple, 'font-size': 8, 'text-anchor': 'middle' });
        entry = { g, portrait, overlay, badge, name, sub, dot, sleep, bubble, bubbleShape, expr, more, data: session, avatarKey: null, lastExpression: null, exprCycle: false };
        entry.setBubble=value=>sizeBubble(entry,value);
        entry.surface=this.layers.mount(g,{left:-40,top:-70,width:80,height:90},{parent:this.sessionLayer,local:true,interactive:true,kind:'miner'});
        portrait.classList.remove('wq-avatar-floating','wq-animated');
        entry.surface.animate('wq-avatar-floating wq-animated');
        entry.surface.motion.style.setProperty('--float-delay',`-${index*.43}s`);
        entry.overlaySurface=this.layers.mount(overlay,{left:-110,top:-100,width:280,height:180},{parent:this.sessionOverlay,local:true,interactive:true,kind:'session-label'});
        entry.sleepMotion=sleepMotion(sleep,this.ambient);
        entry.expressionMotion=expressionMotion(bubble,this.ambient,()=>attribute(bubble,'class','wq-bubble'));
        bubble.addEventListener('animationend', () => attribute(bubble,'class', 'wq-bubble'));
        const hover = (active, event) => {
          attribute(overlay,'data-active', active ? 'true' : 'false');
          this.onSessionHover(active ? entry.data : null, event);
        };
        for (const target of [g, badge]) {
          target.addEventListener('pointerenter', event => hover(true, event));
          target.addEventListener('pointermove', event => hover(true, event));
          target.addEventListener('pointerleave', event => hover(false, event));
        }
        g.addEventListener('focus', event => hover(true, event));
        g.addEventListener('blur', event => hover(false, event));
        this.sessionNodes.set(key, entry);
      }
      entry.data = session;
      entry.station = station;
      const avatarKey = `${session.shape}:${fill}`;
      if (entry.avatarKey !== avatarKey) {
        entry.hands?.destroy();
        while (entry.portrait.firstChild) entry.portrait.firstChild.remove();
        drawAvatar(entry.portrait, session.shape, fill);
        entry.hands=avatarHands(entry.portrait,this.ambient);
        if (index % 2 === 0) {
          const headset = add(entry.portrait, 'g', { class: 'wq-headset' });
          add(headset, 'path', { d: 'M6 23Q3 5 22 5 41 5 38 23', fill: 'none', stroke: '#667c9b', 'stroke-width': 3 });
          [4, 34].forEach(x => add(headset, 'rect', { x, y: 20, width: 6, height: 12, rx: 3, fill: '#2a354b', stroke: '#a3b5ce', 'stroke-width': .9 }));
          add(headset, 'path', { d: 'M37 29Q35 36 28 34', fill: 'none', stroke: '#a3b5ce', 'stroke-width': 1.4 });
        } else {
          const aerial = add(entry.portrait, 'g', { class: 'wq-aerial' });
          add(aerial, 'path', { d: 'M24 10 27 3', stroke: '#bcc9dc', 'stroke-width': 1.6 });
          add(aerial, 'circle', { cx: 27, cy: 3, r: 2.5, fill, stroke: '#dce7f5', 'stroke-width': .8 });
        }
        entry.avatarKey = avatarKey;
      }
      const idle = session.idle === true || session.phase === 'idle';
      entry.hands.setActive(!idle);
      entry.sleepMotion.setActive(idle);
      const seat = `translate(${station.x + 24} ${station.y + 42})`;
      attribute(entry.g,'transform', 'translate(0 0)');
      attribute(entry.overlay,'transform', 'translate(0 0)');
      entry.surface.move(station.x+24,station.y+42);entry.overlaySurface.move(station.x+24,station.y+42);
      attribute(entry.surface.motion,'data-idle',String(idle));
      attribute(entry.badge,'transform', index < 3 ? 'translate(86 -10)' : 'translate(0 0)');
      attribute(entry.g,'opacity', idle ? .65 : 1);
      attribute(entry.overlay,'opacity', idle ? .85 : 1);
      attribute(entry.g,'data-idle', idle ? 'true' : 'false');
      attribute(entry.g,'aria-label', `${text(session.label, `PID ${key}`)}，${text(session.phase_label)}，${text(session.region, '未知区域')}，${text(session.universe)}`);
      setText(entry.name,short(session.label || `PID ${key}`, 15));
      setText(entry.sub,short(`${text(session.region, 'GLOBAL')} · ${text(session.universe, 'UNASSIGNED')}`, 24));
      attribute(entry.dot,'fill', idle ? '#64748b' : fill);
      attribute(entry.sleep,'display', idle ? 'inline' : 'none');
      const expression = text(session.last_expr, '等待新的 Alpha 表达式');
      if (expression !== entry.lastExpression) {
        entry.setBubble(expression);
        if (this.allowEnterAnimations && !idle) {
          entry.exprCycle = !entry.exprCycle;
          attribute(entry.bubble,'class', `wq-bubble wq-animated wq-expression-${entry.exprCycle ? 'a' : 'b'}`);
          entry.expressionMotion.play();
        }
        entry.lastExpression = expression;
      }
      setText(entry.more,session.aggregate ? 'SHARED WORKSTATION' : '');
      attribute(station.monitor,'data-powered', idle ? 'idle' : 'on');
      attribute(station.monitor,'opacity', idle ? .75 : 1);
      attribute(station.monitor,'transform', 'matrix(1 .17 0 1 4 -49)');
      const phaseFill = idle ? '#6c7c93' : ({ prod: C.purple, saving: C.yellow, evaluating: C.green, simulating: C.cyan, reading: C.blue })[session.phase] || fill;
      setText(station.phase,text(session.phase_label, idle ? 'IDLE' : 'ONLINE'));
      attribute(station.phase,'fill', phaseFill);
      attribute(station.chart,'stroke', phaseFill);
      attribute(station.chart,'opacity', idle ? .35 : .9);
      const panelPhase = idle ? 'idle' : session.phase;
      station.ambient.setPhase(panelPhase);
      Object.entries(station.panels).forEach(([phase, panel]) => attribute(panel,'display', phase === panelPhase ? 'inline' : 'none'));
      attribute(station.chart,'display', station.panels[panelPhase] ? 'none' : 'inline');
      const seed = hash(`${session.pid}:${finite(session.counts?.alphas)}:${session.phase}`);
      const segments = [];
      for (let i = 0; i < 12; i++) segments.push(`${i ? 'L' : 'M'}${7 + i * 6.5} ${-13 - ((seed >>> (i % 16)) + i * 7) % 20}`);
      attribute(station.chart,'d', segments.join(' '));
      setText(station.load,`${finite(session.running_sims)} RUN / ${finite(session.counts?.alphas)} α`);
      this.sessionPositions.set(key, { x: station.x + 47, y: station.y - 60 });
      if (session.aggregate) grouped.forEach(member => this.sessionPositions.set(text(member.pid), { x: station.x + 47, y: station.y - 60 }));
    });
    for (const [key, entry] of this.sessionNodes) if (!keep.has(key)) {
      if (entry.overlay.getAttribute('data-active') === 'true') this.onSessionHover(null);
      entry.hands.destroy();entry.sleepMotion.destroy();entry.expressionMotion.destroy();
      entry.g.remove();
      entry.overlay.remove();
      entry.surface.remove();entry.overlaySurface.remove();
      this.sessionNodes.delete(key);
    }
    const regions = [...new Set(all.map(s => text(s.region, 'GLB')))];
    const badgeCount = Math.max(4, regions.length);
    while (this.regionBadges.length < badgeCount) this._addRegionBadge();
    while (this.regionBadges.length > badgeCount) this.regionBadges.pop().g.remove();
    const spacing = Math.min(43, 850 / (badgeCount - 1));
    const radius = Math.min(15, spacing * .38);
    this.regionBadges.forEach((badge, index) => {
      const region = regions[index];
      attribute(badge.g,'transform', `translate(${1087 - (badgeCount - 1 - index) * spacing} 53)`);
      attribute(badge.outer,'r', radius); attribute(badge.inner,'r', radius * .8);
      attribute(badge.text,'font-size', Math.min(7, radius * .55));
      setText(badge.text,region ? short(region, 5) : index === 0 ? 'GLB' : '—');
      attribute(badge.g,'opacity', region ? 1 : .35);
      setText(badge.title,region ? `${region} / ${[...new Set(all.filter(s => text(s.region, 'GLB') === region).map(s => text(s.universe, 'UNASSIGNED')))].join(', ')}` : '等待区域会话');
    });
    for(const [index,station] of this.stations.entries()){
      if(index>=rows.length)station.ambient.setPhase(null);
      attribute(station.miniRoot,'transform',`translate(${station.x} ${station.y}) ${station.monitor.getAttribute('transform')}`);
      attribute(station.miniRoot,'opacity',station.monitor.getAttribute('opacity'));
    }
    this._syncMotion();
  }

  _review(review) {
    const all = list(review).filter(a => a && a.id !== undefined && a.id !== null);
    const keep = new Set();
    all.slice(0, 9).forEach((alpha, index) => {
      const key = text(alpha.id);
      if (keep.has(key)) return;
      keep.add(key);
      let entry = this.noteNodes.get(key);
      if (!entry) {
        const g = add(this.noteLayer, 'g', { class: 'wq-hit', role: 'button', tabindex: 0, 'data-alpha': key });
        const paper=add(g,'g');
        const card = add(paper, 'path', { d: 'M0 0H47V22L41 28H0Z', fill: '#e6c275', stroke: '#fce1a2', 'stroke-width': .6, class: 'wq-focus' });
        add(paper, 'path', { d: 'M41 28V22H47', fill: '#bc9854' });
        add(paper, 'circle', { cx: 24, cy: 1, r: 2, fill: C.pink, stroke: '#923e68', 'stroke-width': .7 });
        const id = label(paper, 4, 12, '', { fill: '#443820', 'font-size': 5.5 });
        const sharpe = label(paper, 4, 22, '', { fill: '#534427', 'font-size': 6.3, 'font-weight': 700 });
        const title = add(g, 'title');
        entry = { g, paper, card, id, sharpe, title, data: alpha };
        paper.addEventListener('animationend',()=>paper.removeAttribute('class'));
        this._alphaActions(entry);
        this.noteNodes.set(key, entry);
      }
      entry.data = alpha;
      attribute(entry.paper,'opacity','1');
      const x = 903 + index % 3 * 57, y = 121+LOWER_SHIFT + Math.floor(index / 3) * 34;
      entry.position={x:x+23,y:y+14};
      if(!entry.surface)entry.surface=this.layers.mount(entry.g,{left:x-5,top:y-5,width:58,height:40},{parent:this.noteLayer,interactive:true,kind:'review-note'});
      else entry.surface.setBox({left:x-5,top:y-5,width:58,height:40});
      entry.surface.setOpacity(this.narrative?.hiddenNotes.has(key)?0:1);
      if(!entry.motionListener){entry.surface.motion.addEventListener('animationend',()=>entry.surface.animate(''));entry.motionListener=true;}
      attribute(entry.g,'transform', `translate(${x} ${y}) rotate(${index % 2 ? 3 : -3} 23 14)`);
      attribute(entry.g,'aria-label', `复核候选 ${key}，Sharpe ${metric(alpha.sharpe)}`);
      setText(entry.id,short(key, 10));
      setText(entry.sharpe,`S ${metric(alpha.sharpe)}`);
      setText(entry.title,`${key}\nSharpe ${metric(alpha.sharpe)}\n${text(alpha.expr)}`);
    });
    for (const [key, entry] of this.noteNodes) if (!keep.has(key)) { entry.surface.remove(); this.noteNodes.delete(key); }
    setText(this.reviewMore,all.length > 9 ? `+${all.length - 9} MORE TO REVIEW` : all.length ? `${all.length} LOCAL CANDIDATE${all.length > 1 ? 'S' : ''}` : 'NO CANDIDATES YET');
  }

  _timeline(timeline, best) {
    const rows = list(timeline).slice(-100).map(row => row?.best_sharpe);
    const actual = rows.filter(v => typeof v === 'number' && Number.isFinite(v));
    if (!actual.length) {
      attribute(this.sparkline,'d', '');
      attribute(this.sparklineArea,'d', '');
    } else {
      const min = Math.min(...actual), max = Math.max(...actual);
      const span = max - min || 1;
      let last = actual[0];
      const coords = rows.map((v, i) => {
        if (typeof v === 'number' && Number.isFinite(v)) last = v;
        return [491 + i / Math.max(1, rows.length - 1) * 194, 255+LOWER_SHIFT - (last - min) / span * 12];
      });
      const d = coords.map(([x, y], i) => `${i ? 'L' : 'M'}${x.toFixed(2)} ${y.toFixed(2)}`).join(' ');
      attribute(this.sparkline,'d', d);
      attribute(this.sparklineArea,'d', `${d}L${coords.at(-1)[0]} ${258+LOWER_SHIFT}L${coords[0][0]} ${258+LOWER_SHIFT}Z`);
    }
    setText(this.sparklineLabel,`合格最佳 SHARPE ${metric(best?.sharpe)}`);
  }

  update(snapshot = {}) {
    if (this.destroyed) return;
    const data = snapshot && typeof snapshot === 'object' ? snapshot : {};
    this.alphaLookup=new Map(list(data.alphas).slice(0,1500).map(alpha=>[String(alpha?.id),alpha]));
    const baseline = this.lastSeq === null || (data.day !== undefined && this.day !== null && data.day !== this.day);
    this.allowEnterAnimations = !baseline && !this.doc.hidden && !this.reducedMotion;
    if(!baseline&&list(data.events).some(event=>Number.isFinite(event?.seq)&&event.seq>this.lastSeq)){
      this.work.beforeEvents();
      this.lastEventAt=this.win.performance?.now?.()??Date.now();this.environmentQuiet=false;this.environmentIdle=false;this._syncMotion();
    }
    if (baseline) {
      this.work.beforeEvents();
      this._clearEffects();
      for (const entry of this.sessionNodes.values()) {entry.expressionMotion.stop();attribute(entry.bubble,'class', 'wq-bubble');}
    }
    this._memo('network',[data.day,data.alphas],()=>{
      this._network(data.alphas);
      setText(this.networkTitle,`ALPHAS · ${text(data.day, 'TODAY')} · ${this.networkNodes.size} NODES`);
    });
    this._memo('sessions',data.sessions,()=>{this._sessions(data.sessions);this.work.displayDirty=true;});
    this._memo('review',data.review,()=>this._review(data.review));
    this._memo('timeline',[data.timeline,data.best],()=>this._timeline(data.timeline,data.best));
    this._memo('status',[data.best,data.rejects,data.totals,data.pending_sims,data.cards],()=>{
    this.bestId = data.best?.id === undefined || data.best?.id === null ? null : text(data.best.id);
    attribute(this.runner,'tabindex', this.bestId ? 0 : -1);
    attribute(this.runner,'aria-disabled', this.bestId ? 'false' : 'true');
    attribute(this.runner,'aria-label', this.bestId ? `合格最佳 Alpha ${this.bestId}，Sharpe ${metric(data.best?.sharpe)}` : '暂无合格 alpha');
    setText(this.runnerId,this.bestId ? short(this.bestId, 18) : '暂无合格 alpha');
    setText(this.runnerSharpe,`SHARPE ${metric(data.best?.sharpe)}`);
    const rejects = data.rejects && typeof data.rejects === 'object' ? Object.values(data.rejects).reduce((sum, value) => sum + Math.max(0, finite(value)), 0) : 0;
    setText(this.rejectCount,rejects.toLocaleString('en-US'));
    const pending = Array.isArray(data.pending_sims)?data.pending_sims.length:Math.max(0,Math.floor(finite(data.totals?.sims_pending)));
    setText(this.cabinetCount,String(pending).padStart(2,'0'));
    attribute(this.cabinetLampGroup,'display',pending<=16?'inline':'none');
    const packed=this.cabinetPacked;
    attribute(packed.g,'display',pending>16?'inline':'none');
    if(pending>16){
      packed.columns=Math.ceil(Math.sqrt(pending)*Math.sqrt(3));
      packed.fullRows=Math.floor(pending/packed.columns);packed.remainder=pending%packed.columns;
      const width=40/packed.columns,height=14/Math.ceil(pending/packed.columns);
      attribute(packed.pattern,'width',width);attribute(packed.pattern,'height',height);
      attribute(packed.dot,'cx',width/2);attribute(packed.dot,'cy',height/2);attribute(packed.dot,'r',Math.min(width,height)*.3);
      attribute(packed.rows,'width',40);attribute(packed.rows,'height',packed.fullRows*height);
      attribute(packed.last,'y',4+packed.fullRows*height);attribute(packed.last,'width',packed.remainder*width);attribute(packed.last,'height',height);
    }
    this.cabinetLamps.forEach((lamp,index)=>{
      attribute(lamp,'data-lit',index<pending?'true':'false');
      attribute(lamp,'fill',index<pending?C.cyan:'#263d48');
      const parent=index<pending?this.cabinetLitGroup:this.cabinetLampGroup;
      if(lamp.parentNode!==parent)parent.appendChild(lamp);
    });
    this.cabinetBlink.setActive(pending>0&&pending<=16);this.packedBlink.setActive(pending>16);
    setText(this.wallLoad,`${String(pending).padStart(2, '0')} ACTIVE JOBS`);
    this.wallBars.forEach((bar, i) => { const height = pending ? 5 + (i * 13 + pending * 7) % 57 : 3 + i % 3 * 2; attribute(bar,'height', height); attribute(bar,'y', 121 - height); attribute(bar,'opacity', pending ? .7 : .2); });
    setText(this.screenFooter,`${finite(data.totals?.alphas, list(data.alphas).length)} α / ${finite(data.totals?.eval_passed)} PASS / ${finite(data.totals?.candidates)} PICK`);
    const prod = list(data.cards).find(card => card?.key === 'prod');
    setText(this.radarStatus,short(prod?.message || 'CORRELATION SCAN', 24));
    });
    const fresh=list(data.events).some(event=>event?.seq>(this.lastSeq??Infinity));
    this.web.syncCounts(data,this.allowEnterAnimations&&(fresh||this.narrative.working));
    this._events(data.events, data.day);
    this.checkActivity();
    this.work.update(data);
  }

  _syncMotion() {
    const paused=this.doc.hidden||this.reducedMotion||this.environmentQuiet||this.environmentIdle;
    this.layers.pause(paused);
    this.spider.setPaused(paused);
    this.ambient.setPaused(paused);
    if(paused)for(const entry of this.sessionNodes.values()){
      entry.expressionMotion.stop();attribute(entry.bubble,'class','wq-bubble');
    }
    this.work?.sync();
  }

  _events(events, day) {
    const rows=list(events).filter(e=>e && typeof e.seq==='number' && Number.isFinite(e.seq));
    const max=rows.reduce((n,e)=>Math.max(n,e.seq),this.lastSeq??0);
    if(this.lastSeq===null || (day!==undefined && this.day!==null && day!==this.day)){
      this.lastEventAt=this.win.performance?.now?.()??Date.now();this.environmentQuiet=true;this.environmentIdle=false;this._syncMotion();
      this._clearEffects();this.onCaption(null);this.lastSeq=rows.reduce((n,e)=>Math.max(n,e.seq),0);this.day=day??null;return;
    }
    const unique=new Map(rows.filter(e=>e.seq>this.lastSeq).map(e=>[e.seq,e]));
    const fresh=[...unique.values()].sort((a,b)=>a.seq-b.seq);
    if(fresh.length){this.lastEventAt=this.win.performance?.now?.()??Date.now();this.environmentQuiet=false;this.environmentIdle=false;this._syncMotion();}
    this.lastSeq=max;this.day=day??this.day;
    if(this.doc.hidden || this.reducedMotion){
      this._clearEffects();
      if(fresh.length)this.narrative._caption(fresh.at(-1));
      return;
    }
    this.narrative.enqueue(fresh);
  }

  _tick(now) { this.narrative.tick(now); }
  _clearEffects() {
    this.narrative?.clear();
    this.linkAnimations.clear();
    this.web?.settle();
  }

  destroy() {
    if (this.destroyed) return;
    this.destroyed = true;
    this.work.destroy();
    this.secondClock.destroy();
    this.ambient.destroy();
    this.narrative.destroy();
    this.spider.destroy();
    this.web.destroy();
    this.doc.removeEventListener('visibilitychange', this._onVisibility);
    if (this.motionQuery?.removeEventListener) this.motionQuery.removeEventListener('change', this._onMotion);
    else this.motionQuery?.removeListener?.(this._onMotion);
    this.onSessionHover(null);
    this.root.remove();
    this.layers.destroy();
    this.networkNodes.clear();
    this.sessionNodes.clear();
    this.sessionLookup.clear();
    this.noteNodes.clear();
  }
}
