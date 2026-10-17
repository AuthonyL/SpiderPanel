import {timelineSeries, scatterModel, formatMetric, formatTimestamp, timeLabel, STATUS_COLORS} from './data.js';

const NS = 'http://www.w3.org/2000/svg';
const GREEN = '#3ddc84', RED = '#ff4d5e';
const MAX_POINTS = 1500;
const QUALIFIED_STATUSES=new Set(['eval_passed','prod_ok','candidate']);

function attributes(node, values) {
  for (const [key, value] of Object.entries(values)) {
    const next = String(value);
    if (node.getAttribute(key) !== next) node.setAttribute(key, next);
  }
}

function setText(node, value) {
  const next = String(value);
  if (node.textContent !== next) node.textContent = next;
}

function add(parent, tag, values = {}, content) {
  const node = parent.ownerDocument.createElementNS(NS, tag);
  attributes(node, values);
  // Inline size wins over chart classes and stays in CSS pixels as the host resizes.
  if (tag === 'text') node.style.setProperty('font-size', '10px');
  if (content !== undefined) node.textContent = String(content);
  parent.appendChild(node);
  return node;
}

function show(node, visible) {
  if (visible) { if (node.getAttribute('display') !== null) node.removeAttribute('display'); }
  else attributes(node, {display:'none'});
}

function reconcile(entries, rows, key, create, update) {
  const current = new Set();
  for (const row of rows) {
    const id = key(row);
    current.add(id);
    if (!entries.has(id)) entries.set(id, create(row));
    update(entries.get(id), row);
  }
  for (const [id, entry] of entries) {
    if (!current.has(id)) {
      (entry.node || entry).remove();
      entries.delete(id);
    }
  }
}

// Dividing the bounds first also supports finite metrics near Number.MAX_VALUE.
function project(value, low, high, from, to) {
  const size = Math.max(1, Math.abs(low), Math.abs(high));
  const span = high / size - low / size;
  const ratio = span > 0 ? (value / size - low / size) / span : .5;
  return from + Math.max(0, Math.min(1, ratio)) * (to - from);
}

function boundedCount(value) {
  return value === Infinity ? Number.MAX_VALUE : Number.isFinite(value) ? Math.max(0, value) : 0;
}

function countLabel(value) {
  if (value < 1000) return String(Math.round(value));
  if (value >= 1e15) return tickLabel(value);
  return new Intl.NumberFormat('en', {notation:'compact', maximumFractionDigits:1}).format(value);
}

function tickLabel(value) {
  if (!Number.isFinite(value)) return '—';
  if (value === 0) return '0';
  if (Math.abs(value) >= 1e4 || Math.abs(value) < .001)
    return value.toExponential(1).replace('.0e', 'e').replace('e+', 'e');
  return String(Number(value.toPrecision(10)));
}

function metricLabel(value) {
  return Math.abs(value) >= 1e4 ? tickLabel(value) : formatMetric(value);
}

// The normalized span avoids overflow for domains spanning ±Number.MAX_VALUE.
function niceScale(low, high, intervals, minimumStep = 0) {
  low = Number.isFinite(low) ? low : 0;
  high = Number.isFinite(high) && high > low ? high : Math.max(1, low);
  const magnitude = Math.max(1, Math.abs(low), Math.abs(high));
  const raw = (high / magnitude - low / magnitude) / Math.max(2, intervals) * magnitude;
  const power = 10 ** Math.floor(Math.log10(raw || 1));
  const fraction = raw / power;
  const factor = fraction <= 1 ? 1 : fraction <= 2 ? 2 : fraction <= 5 ? 5 : 10;
  const step = Math.max(minimumStep,
    Number.isFinite(power * factor) && power * factor > 0 ? power * factor : raw || 1);
  const roundedLow = Math.floor(low / step) * step, roundedHigh = Math.ceil(high / step) * step;
  const min = Number.isFinite(roundedLow) ? roundedLow : low;
  const max = Number.isFinite(roundedHigh) ? roundedHigh : high;
  const ticks = [];
  const first = Math.ceil(min / step - 1e-9), last = Math.floor(max / step + 1e-9);
  for (let index = first; index <= last && ticks.length < 32; index++) {
    const value = index * step;
    if (Number.isFinite(value)) ticks.push(value === 0 ? 0 : value);
  }
  return {min, max, ticks};
}

function createTick(parent) {
  const node = add(parent, 'g');
  return {node, line:add(node, 'line', {class:'chart-grid'}),
    label:add(node, 'text', {class:'chart-label'})};
}

class PixelChart {
  constructor(svg) {
    this.svg = svg;
    this.width = 320;
    this.height = 220;
    this.destroyed = false;
    attributes(svg, {viewBox:`0 0 ${this.width} ${this.height}`});
  }

  observe() {
    this.resize();
    const ResizeObserverClass = this.svg.ownerDocument.defaultView?.ResizeObserver ?? globalThis.ResizeObserver;
    if (typeof ResizeObserverClass !== 'function') return;
    this.observer = new ResizeObserverClass(entries => {
      const entry = entries.find(item => item.target === this.svg);
      if (entry) this.resize(entry);
    });
    // Observing the SVG avoids mistaking the entire output panel for the plot.
    this.observer.observe(this.svg);
  }

  resize(entry) {
    if (this.destroyed) return;
    const boxes = entry?.contentBoxSize;
    const box = Array.isArray(boxes) ? boxes[0] : boxes;
    const rect = entry?.contentRect ?? this.svg.getBoundingClientRect();
    const measuredWidth = box?.inlineSize ?? rect?.width ?? this.svg.clientWidth;
    const measuredHeight = box?.blockSize ?? rect?.height ?? this.svg.clientHeight;
    const width = Number.isFinite(measuredWidth) && measuredWidth > 0 ? measuredWidth : this.width;
    const height = Number.isFinite(measuredHeight) && measuredHeight > 0 ? measuredHeight : this.height;
    if (this.width === width && this.height === height) return;
    this.width = width;
    this.height = height;
    attributes(this.svg, {viewBox:`0 0 ${width} ${height}`});
    this.draw();
  }

  destroy() {
    this.destroyed = true;
    this.observer?.disconnect();
  }
}

export class OutputChart extends PixelChart {
  constructor(svg) {
    super(svg);
    this.failedBuckets = new Set();
    this.day = undefined;
    this.grid = add(svg, 'g', {'aria-hidden':'true', class:'chart-y-axis'});
    this.gridTicks = new Map();
    this.barLayer = add(svg, 'g', {'aria-label':'每 15 分钟完成的回测批次'});
    this.bars = new Map();
    this.barTitle = add(svg, 'text', {class:'chart-label'}, 'SIM / 15 MIN');
    this.timeLabels = Array.from({length:5}, () => add(svg, 'text', {class:'chart-label'}));
    this.empty = add(svg, 'text', {'text-anchor':'middle', class:'chart-empty'}, '等待第一批回测');
    this.update({});
    this.observe();
  }

  update(snapshot = {}) {
    const inputKey = JSON.stringify([snapshot?.day,
      (Array.isArray(snapshot?.timeline) ? snapshot.timeline : []).map(row => row && [row.t,row.sims_done]),
      (Array.isArray(snapshot?.events) ? snapshot.events : []).filter(event => event?.kind === 'sim_fail').map(event => event.ts)]);
    if (inputKey === this.inputKey) return;
    this.inputKey = inputKey;
    if (this.day !== snapshot?.day) { this.failedBuckets.clear(); this.day = snapshot?.day; }
    const rows = timelineSeries(snapshot?.timeline, snapshot?.events).map(row => ({
      t:row.t, sims:boundedCount(row.sims), failed:row.failed,
    }));
    const visibleBuckets = new Set(rows.map(row => row.t));
    for (const key of this.failedBuckets) if (!visibleBuckets.has(key)) this.failedBuckets.delete(key);
    for (const row of rows) {
      if (row.failed) this.failedBuckets.add(row.t);
      row.failed = this.failedBuckets.has(row.t);
    }
    this.rows = rows;
    const renderKey = JSON.stringify(rows);
    if (renderKey === this.renderKey) return;
    this.renderKey = renderKey;
    this.draw();
  }

  draw() {
    const rows = this.rows;
    const {width, height} = this;
    const left = Math.min(42, width * .18), right = Math.max(left + 1, width - Math.min(14, width * .06));
    const top = Math.min(22, height * .15), bottom = Math.max(top + 1, height - 28);
    const maximum = Math.max(1, ...rows.map(row => row.sims));
    const scale = niceScale(0, maximum, Math.max(2, Math.min(3, Math.floor((bottom - top) / 60))), 1);
    const slot = (right - left) / Math.max(1, rows.length);
    const x = index => left + (index + .5) * slot;
    const y = value => project(value, scale.min, scale.max, bottom, top);
    reconcile(this.gridTicks, scale.ticks, value => value, () => createTick(this.grid), (entry, value) => {
      attributes(entry.line, {x1:left, x2:right, y1:y(value), y2:y(value)});
      attributes(entry.label, {x:left - 7, y:y(value) + 3, 'text-anchor':'end'});
      setText(entry.label, countLabel(value));
    });
    const hasActivity = rows.some(row => row.sims || row.failed);
    attributes(this.barTitle, {x:left, y:Math.min(12, top)});
    attributes(this.empty, {x:(left + right) / 2, y:(top + bottom) / 2});
    show(this.empty, !hasActivity);show(this.barTitle, hasActivity);
    const indices = new Map(rows.map((row, index) => [row.t, index]));
    reconcile(this.bars, rows, row => row.t, () => {
      const bar = add(this.barLayer, 'rect', {rx:1});add(bar, 'title');return bar;
    }, (bar, row) => {
      const width = Math.min(24, slot * .68);
      const height = row.sims ? bottom-y(row.sims) : row.failed ? Math.min(2,bottom-top) : 0;
      attributes(bar, {x:x(indices.get(row.t))-width/2, y:bottom-height, width, height, fill:row.failed ? RED : GREEN});
      setText(bar.firstChild, `${formatTimestamp(row.t)} · 完成 ${countLabel(row.sims)} 批${row.failed ? ' · 有回测失败' : ''}`);
    });
    const labelCount = Math.min(5, rows.length, Math.max(2, Math.floor((right - left) / 80) + 1));
    const labelIndices = [...new Set(Array.from({length:labelCount}, (_, index) =>
      labelCount > 1 ? Math.round(index / (labelCount - 1) * (rows.length - 1)) : 0))];
    this.timeLabels.forEach((label, index) => {
      const position = labelIndices[index];show(label, position !== undefined);
      if (position === undefined) return;
      attributes(label, {x:x(position), y:Math.max(10, height - 8),
        'text-anchor':index === 0 ? 'start' : index === labelIndices.length-1 ? 'end' : 'middle'});
      setText(label, timeLabel(rows[position].t));
    });
  }
}

// Exclusion is display-only: the dashboard's full alpha index and totals survive.
export function filterScatterPoints(alphas) {
  const points=(Array.isArray(alphas)?alphas:[]).filter(alpha=>alpha&&
    typeof alpha.sharpe==='number'&&Number.isFinite(alpha.sharpe)&&
    typeof alpha.fitness==='number'&&Number.isFinite(alpha.fitness));
  const range=key=>{
    const sorted=points.map(point=>point[key]).sort((a,b)=>a-b);
    const percentile=p=>{
      const position=(sorted.length-1)*p,low=Math.floor(position),high=Math.ceil(position),weight=position-low;
      return low===high?sorted[low]:sorted[low]*(1-weight)+sorted[high]*weight;
    };
    if(!sorted.length)return [-Infinity,Infinity];
    const low=percentile(.02),high=percentile(.98),padding=high*.25-low*.25;
    return [low-padding,high+padding];
  };
  const [xMin,xMax]=range('sharpe'),[yMin,yMax]=range('fitness');
  const visible=points.filter(alpha=>QUALIFIED_STATUSES.has(alpha.status)||
    alpha.sharpe>=xMin&&alpha.sharpe<=xMax&&alpha.fitness>=yMin&&alpha.fitness<=yMax);
  return {points:visible,ignored:points.length-visible.length};
}

function pointerEvent(event, node) {
  if (Number.isFinite(event?.clientX) && Number.isFinite(event?.clientY)) return event;
  const bounds = node.getBoundingClientRect();
  return {clientX:bounds.left+bounds.width/2, clientY:bounds.top, target:node, originalEvent:event};
}

export class ScatterChart extends PixelChart {
  constructor(svg, {onAlpha = () => {}, onHover = () => {}} = {}) {
    super(svg);
    this.onAlpha = onAlpha;
    this.onHover = onHover;
    attributes(svg, {role:'group'});
    this.xAxis = add(svg, 'g', {'aria-hidden':'true', class:'chart-x-axis'});
    this.yAxis = add(svg, 'g', {'aria-hidden':'true', class:'chart-y-axis'});
    this.xTicks = new Map();
    this.yTicks = new Map();
    this.xTitle = add(svg, 'text', {'text-anchor':'end', class:'chart-label'}, 'SHARPE →');
    this.yTitle = add(svg, 'text', {x:8, y:12, class:'chart-label'}, 'FITNESS');
    this.tierLayer = add(svg, 'g');
    this.tiers = new Map();
    this.pointLayer = add(svg, 'g', {'aria-label':'alpha 指标'});
    this.points = new Map();
    this.empty = add(svg, 'text', {'text-anchor':'middle', class:'chart-empty'}, '等待有 Sharpe / Fitness 的 alpha');
    this.update({});
    this.observe();
  }

  createPoint(alpha) {
    const entry = {node:add(this.pointLayer, 'circle', {class:'scatter-point', tabindex:0, role:'button'}),
      alpha, hovered:false, focused:false};
    entry.title = add(entry.node, 'title');
    const interaction = event => {
      const active = entry.hovered || entry.focused;
      attributes(entry.node, {r:active ? 6 : entry.radius, opacity:active ? 1 : entry.opacity,
        stroke:active ? '#e8ecf4' : 'none', 'stroke-width':active ? 1.5 : 0});
      this.onHover(active ? entry.alpha : null, active ? pointerEvent(event, entry.node) : event);
    };
    entry.node.addEventListener('mouseenter', event => { entry.hovered = true; interaction(event); });
    entry.node.addEventListener('mousemove', event => { if (entry.hovered) interaction(event); });
    entry.node.addEventListener('mouseleave', event => { entry.hovered = false; interaction(event); });
    entry.node.addEventListener('focus', event => { entry.focused = true; interaction(event); });
    entry.node.addEventListener('blur', event => { entry.focused = false; interaction(event); });
    entry.node.addEventListener('click', () => this.onAlpha(entry.alpha.id));
    entry.node.addEventListener('keydown', event => {
      if ((event.key === 'Enter' || event.key === ' ') && !event.repeat) {
        event.preventDefault();
        this.onAlpha(entry.alpha.id);
      }
    });
    return entry;
  }

  update(snapshot = {}) {
    const filtered=filterScatterPoints(snapshot?.alphas);
    this.ignoredCount=filtered.ignored;
    const points = filtered.points.filter(point => typeof point.id === 'string');
    this.displayed = points.length > MAX_POINTS ? [
      ...points.filter(point => point.status === 'candidate'),
      ...points.filter(point => point.status !== 'candidate'&&QUALIFIED_STATUSES.has(point.status)),
      ...points.filter(point => !QUALIFIED_STATUSES.has(point.status)),
    ].slice(0, MAX_POINTS) : points;
    const model=this.model=scatterModel(this.displayed,snapshot?.thresholds);
    // Interaction handlers always see the latest alpha, including nonvisual metadata.
    for (const alpha of this.displayed) {
      const entry = this.points.get(alpha.id);
      if (entry) entry.alpha = alpha;
    }
    const renderKey = JSON.stringify([model.xMin,model.xMax,model.yMin,model.yMax,model.tiers,points.length,
      this.displayed.map(alpha => [alpha.id,alpha.sharpe,alpha.fitness,alpha.status])]);
    attributes(this.svg, {'aria-label':`Sharpe 与 Fitness 散点图，显示 ${this.displayed.length} / ${points.length} 个 alpha${this.ignoredCount?`，已忽略 ${this.ignoredCount} 个异常点`:''}，可点击查看详情`});
    if (renderKey === this.renderKey) return;
    this.renderKey = renderKey;
    const ids = new Set(this.displayed.map(point => point.id));
    for (const [id, entry] of this.points) {
      if ((entry.hovered || entry.focused) && !ids.has(id)) this.onHover(null, null);
    }
    this.draw();
  }

  draw() {
    const {model, displayed, width, height} = this;
    const left = Math.min(48, width * .2), right = Math.max(left + 1, width - Math.min(14, width * .06));
    const top = Math.min(height * .26, model.tiers.length ? 48 : 24);
    const bottom = Math.max(top + 1, height - 36);
    const xScale = niceScale(Math.min(model.xMin, ...model.tiers.map(tier => tier.sharpe)), model.xMax,
      Math.max(2, Math.min(8, Math.floor((right - left) / 70))));
    const yScale = niceScale(Math.min(model.yMin, ...model.tiers.map(tier => tier.fitness)), model.yMax,
      Math.max(2, Math.min(6, Math.floor((bottom - top) / 45))));
    const x = value => project(value, xScale.min, xScale.max, left, right);
    const y = value => project(value, yScale.min, yScale.max, bottom, top);
    const layoutKey = JSON.stringify([width,height,xScale,yScale,model.tiers]);
    if (layoutKey !== this.layoutKey) {
      this.layoutKey = layoutKey;
      reconcile(this.xTicks, xScale.ticks, value => value, () => createTick(this.xAxis), (entry, value) => {
        attributes(entry.line, {x1:x(value), x2:x(value), y1:top, y2:bottom});
        attributes(entry.label, {x:x(value), y:Math.min(height - 6, bottom + 16), 'text-anchor':'middle'});
        setText(entry.label, tickLabel(value));
      });
      reconcile(this.yTicks, yScale.ticks, value => value, () => createTick(this.yAxis), (entry, value) => {
        attributes(entry.line, {x1:left, x2:right, y1:y(value), y2:y(value)});
        attributes(entry.label, {x:left - 7, y:y(value) + 3, 'text-anchor':'end'});
        setText(entry.label, tickLabel(value));
      });
      attributes(this.xTitle, {x:right, y:Math.max(10, height - 5)});
      attributes(this.empty, {x:(left + right) / 2, y:(top + bottom) / 2});
      reconcile(this.tiers, model.tiers, tier => tier.key,
        () => {
          const node = add(this.tierLayer, 'g');
          return {node, box:add(node, 'rect', {class:'threshold-box'}),
            label:add(node, 'text', {class:'chart-label', 'text-anchor':'end'})};
        },
        (entry, tier) => {
          const color = tier.key === 'high' ? GREEN : '#4f7cff';
          attributes(entry.box, {x:x(tier.sharpe), y:top, width:right-x(tier.sharpe), height:y(tier.fitness)-top, stroke:color});
          attributes(entry.label, {x:right, y:Math.min(height - 4, tier.key === 'high' ? 30 : 15), fill:color});
          setText(entry.label, `${tier.key.toUpperCase()} · S≥${metricLabel(tier.sharpe)} F≥${metricLabel(tier.fitness)}`);
        });
    }
    show(this.empty, displayed.length === 0);
    reconcile(this.points, displayed, point => point.id, point => this.createPoint(point),
      (entry, alpha) => {
        entry.alpha = alpha;
        const pointKey = JSON.stringify([alpha.sharpe,alpha.fitness,alpha.status]);
        if (entry.renderKey === pointKey && entry.layoutKey === layoutKey) return;
        entry.renderKey = pointKey;
        entry.layoutKey = layoutKey;
        entry.radius = alpha.status === 'candidate' ? 4.2 : 3.4;
        entry.opacity = ['eval_failed', 'rejected', 'done'].includes(alpha.status) ? .55 : .88;
        const color = Object.hasOwn(STATUS_COLORS, alpha.status) ? STATUS_COLORS[alpha.status] : STATUS_COLORS.done;
        const label = `${alpha.id} · Sharpe ${formatMetric(alpha.sharpe)} · Fitness ${formatMetric(alpha.fitness)}`;
        attributes(entry.node, {cx:x(alpha.sharpe), cy:y(alpha.fitness), fill:color,
          r:entry.hovered || entry.focused ? 6 : entry.radius,
          opacity:entry.hovered || entry.focused ? 1 : entry.opacity, 'aria-label':label});
        setText(entry.title, label);
      });
  }
}
