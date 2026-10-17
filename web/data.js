// Pure snapshot transforms shared by the view and its offline tests.
export const CARD_META = [
  ['generate', '生成', 'GEN', '#e8ecf4', 'ghost', 'AI 送去回测的表达式', '条'],
  ['precheck', '预检', 'CHECK', '#ffd23f', 'hexagon', '表达式入场检查', '次'],
  ['simulate', '回测', 'SIM', '#3ddc84', 'square', '已完成的回测批次', '批'],
  ['evaluate', '评估', 'EVAL', '#4f7cff', 'circle', '寻找通过评估的 alpha', '个'],
  ['prod', '相关性', 'PROD', '#ff4d5e', 'circle', 'Prod Correlation', '次'],
  ['candidate', '候选', 'PICK', '#ff5fa2', 'triangle', '保存有价值的发现', '个'],
  ['error', '错误', 'RISK', '#ffab2e', 'hexagon', '提交与工具异常', '次'],
  ['review', '复核', 'YOU', '#a78bfa', 'blob', '最后一关，由你决定', '个'],
];
export const STATUS_COLORS = {done:'#6b7690', eval_failed:'#8a354b', eval_passed:'#4f7cff',
  prod_ok:'#3ddc84', prod_blocked:'#ff4d5e', candidate:'#ff5fa2', rejected:'#ffab2e'};
export const STATUS_LABELS = {done:'回测完成', eval_failed:'评估未过', eval_passed:'评估通过',
  prod_ok:'相关性通过', prod_blocked:'相关性拦截', candidate:'待复核', rejected:'本地检查未过'};
export const list = value => Array.isArray(value) ? value : [];
export const record = value => value && typeof value === 'object' && !Array.isArray(value) ? value : {};
export const numeric = value => typeof value === 'number' && Number.isFinite(value) ? value : null;
export const count = value => Math.max(0, numeric(value) ?? 0);
export const clamp = value => Math.max(0, Math.min(1, numeric(value) ?? 0));
export const text = (value, fallback='—') => typeof value === 'string' && value.length ? value : fallback;
export const short = (value, length=40) => {
  const chars = Array.from(text(value, '').replace(/\s+/g,' ').trim());
  return chars.length > length ? chars.slice(0, Math.max(0,length-1)).join('')+'…' : chars.join('');
};
export const formatMetric = value => numeric(value) === null ? '—' : value.toFixed(2);
export const formatNumber = value => numeric(value) === null ? '—' : value.toLocaleString('en-US', {maximumFractionDigits:0});
export const timeLabel = value => {
  const date = new Date(value);
  return Number.isNaN(date.valueOf()) ? '—' : date.toLocaleTimeString('zh-CN',{hour:'2-digit',minute:'2-digit',hour12:false});
};
export const formatTimestamp = value => {
  if (value===null || value===undefined || value==='') return '—';
  const date=new Date(value), pad=n=>String(n).padStart(2,'0');
  if (Number.isNaN(date.valueOf())) return '—';
  return `${pad(date.getMonth()+1)}-${pad(date.getDate())} ${pad(date.getHours())}:${pad(date.getMinutes())}:${pad(date.getSeconds())}`;
};

export function normaliseSnapshot(input) {
  const raw = record(input), totals = record(raw.totals), goal = record(raw.goal);
  const cards = new Map(list(raw.cards).filter(c=>c && typeof c.key==='string').map(c=>[c.key,c]));
  return {...raw,
    mode: ['live','demo','replay'].includes(raw.mode) ? raw.mode : 'live',
    day: text(raw.day, new Date().toLocaleDateString('en-CA')),
    totals: Object.fromEntries(['sessions_active','sessions_total','exprs','sims_done','sims_pending',
      'alphas','eval_passed','candidates','pending_review'].map(k=>[k,count(totals[k])])),
    goal: {candidates:count(goal.candidates), target:numeric(goal.target)>0 ? goal.target : 5},
    cards: CARD_META.map(([key,title,en,color,shape,subtitle,unit])=>{
      const card = cards.get(key) || {};
      return {...card,key,title,en,color,shape,subtitle:text(card.subtitle,subtitle),unit,
        value:count(card.value),progress:clamp(card.progress),busy:card.busy===true,
        message:text(card.message,'等待数据')};
    }),
    sessions: list(raw.sessions).filter(s=>s && typeof s==='object' && numeric(s.pid)!==null),
    sessions_ended: count(raw.sessions_ended),
    alphas: list(raw.alphas).filter(a=>a && typeof a.id==='string'),
    pending_sims: list(raw.pending_sims).filter(Boolean),
    timeline: list(raw.timeline).filter(Boolean),
    funnel: list(raw.funnel).filter(Boolean), events:list(raw.events).filter(Boolean),
    review:list(raw.review).filter(a=>a && typeof a.id==='string'),
    best: raw.best?.passed===true && ['eval_passed','prod_ok','candidate'].includes(raw.best.status) ? raw.best : null,
    rejects:record(raw.rejects), thresholds:raw.thresholds && typeof raw.thresholds==='object' ? raw.thresholds : null,
  };
}

export function timelineSeries(timeline, events) {
  let evaluated = 0;
  const failedTimes = list(events).filter(e=>e?.kind==='sim_fail').map(e=>Date.parse(e.ts));
  return list(timeline).filter(row=>row && Number.isFinite(Date.parse(row.t))).slice(0,100).map(row=>{
    const start = Date.parse(row.t);
    evaluated += count(row.eval_passed);
    return {...row, evaluated, candidates:count(row.candidates_cum), sims:count(row.sims_done),
      failed:failedTimes.some(ts=>ts>=start && ts<start+900000)};
  });
}

export function scatterModel(alphas, thresholds) {
  const points = list(alphas).filter(a=>a && numeric(a.sharpe)!==null && numeric(a.fitness)!==null);
  const soft = record(record(thresholds).soft);
  const tiers = ['standard','high'].flatMap(key=>{
    const tier = record(soft[key]);
    return numeric(tier.sharpe)!==null && numeric(tier.fitness)!==null ? [{key,sharpe:tier.sharpe,fitness:tier.fitness}] : [];
  });
  let xMin=-1, xMax=2.2, yMin=-.4, yMax=1.5;
  for (const p of points) {
    xMin=Math.min(xMin,p.sharpe-.15); xMax=Math.max(xMax,p.sharpe+.15);
    yMin=Math.min(yMin,p.fitness-.1); yMax=Math.max(yMax,p.fitness+.1);
  }
  for (const p of tiers) { xMax=Math.max(xMax,p.sharpe+.3); yMax=Math.max(yMax,p.fitness+.2); }
  return {points,tiers,xMin,xMax,yMin,yMax};
}
