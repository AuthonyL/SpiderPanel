"""Dependency-free frontend data checks; DOM tests use a small local harness."""

import json
from pathlib import Path
import shutil
import subprocess

import pytest


WEB = Path(__file__).resolve().parents[1] / "web"
NODE = shutil.which("node")


def run_js(source):
    if NODE is None:
        pytest.skip("未安装 Node.js")
    result = subprocess.run([NODE, "--input-type=module", "--eval", source],
                            text=True, capture_output=True, timeout=15)
    assert result.returncode == 0, result.stderr
    return result.stdout


def data_check(source):
    run_js("import assert from 'node:assert/strict';\n"
           f"import * as data from {json.dumps((WEB/'data.js').as_uri())};\n" + source)


def test_empty_and_nullable_snapshot_has_eight_safe_cards():
    data_check("""
      for (const input of [null, {}, {cards:null, alphas:null, sessions:[null]}]) {
        const state=data.normaliseSnapshot(input);
        assert.equal(state.cards.length,8);
        assert.deepEqual(state.cards.map(c=>c.key),['generate','precheck','simulate','evaluate','prod','candidate','error','review']);
        assert.ok(state.cards.every(c=>c.value===0 && !c.busy));
        assert.equal(state.sessions.length,0);
        assert.equal(state.thresholds,null);
      }
      const state=data.normaliseSnapshot({cards:[{key:'simulate',progress:9}],sessions:[{pid:0,label:'未知会话'}],alphas:[{id:'a',expr:'rank(close < 3)'}]});
      assert.equal(state.cards[2].progress,1);
      assert.equal(state.sessions[0].label,'未知会话');
      assert.equal(state.alphas[0].expr,'rank(close < 3)');
    """)


def test_scatter_threshold_labels_have_two_decimals_and_preserve_other_config():
    dashboard_check("""
      app.render({thresholds:{hard:[{key:'prod_corr_max',value:.7000000000000001}],
        soft:{tier_sharpe:1.8000000000000003,
          standard:{sharpe:1.8000000000000003,fitness:.4000000000000001,turnover_min:.01,margin:.0002},
          high:{sharpe:2,fitness:.6,turnover_min:.02,margin:.0003}}}});
      assert.equal(app.scatter.tiers.get('standard').label.textContent,'STANDARD · S≥1.80 F≥0.40');
      assert.equal(app.scatter.tiers.get('high').label.textContent,'HIGH · S≥2.00 F≥0.60');
      assert.equal(app.state.thresholds.soft.standard.margin,.0002);
      assert.equal(app.state.thresholds.soft.standard.turnover_min,.01);
      assert.equal(doc.getElementById('hard-rules'),null);
    """)


def test_timeline_uses_cumulative_evaluations_and_failure_buckets():
    data_check("""
      const rows=[{t:'2026-10-15T12:00:00+08:00',eval_passed:2,candidates_cum:1,sims_done:2},
        {t:'2026-10-15T12:15:00+08:00',eval_passed:3,candidates_cum:2,sims_done:1}];
      const points=data.timelineSeries(rows,[{kind:'sim_fail',ts:'2026-10-15T12:02:00+08:00'}]);
      assert.deepEqual(points.map(p=>p.evaluated),[2,5]);
      assert.deepEqual(points.map(p=>p.candidates),[1,2]);
      assert.deepEqual(points.map(p=>p.failed),[true,false]);
      assert.equal(data.timelineSeries(null,null).length,0);
    """)


def test_output_retains_observed_failure_when_recent_event_window_rolls():
    run_js("import assert from 'node:assert/strict';\nimport fs from 'node:fs';\n"
           f"import {{documentFromHTML}} from {json.dumps((Path(__file__).parent/'frontend_dom.mjs').as_uri())};\n"
           f"import {{OutputChart}} from {json.dumps((WEB/'charts.js').as_uri())};\n"
           f"const doc=documentFromHTML(fs.readFileSync({json.dumps(str(WEB/'index.html'))},'utf8'));\n"+"""
      const chart=new OutputChart(doc.getElementById('output-chart'));
      const timeline=[{t:'2026-10-15T12:00:00+08:00',sims_done:1}];
      chart.update({day:'2026-10-15',timeline,events:[{kind:'sim_fail',ts:'2026-10-15T12:01:00+08:00'}]});
      assert.equal([...chart.bars.values()][0].getAttribute('fill'),'#ff4d5e');
      chart.update({day:'2026-10-15',timeline,events:[]});
      assert.equal([...chart.bars.values()][0].getAttribute('fill'),'#ff4d5e');
      chart.update({day:'2026-10-16',timeline,events:[]});
      assert.notEqual([...chart.bars.values()][0].getAttribute('fill'),'#ff4d5e');
    """)


def test_scatter_excludes_missing_metrics_and_preserves_thresholds():
    data_check("""
      const model=data.scatterModel([{id:'a',sharpe:-2,fitness:-1},{id:'b',sharpe:2.4,fitness:1.8},{id:'bad',sharpe:null,fitness:4}],
        {soft:{standard:{sharpe:1.25,fitness:1.0},high:{sharpe:1.75,fitness:1.15}}});
      assert.equal(model.points.length,2);
      assert.ok(model.xMin < -2 && model.xMax > 2.4 && model.yMin < -1 && model.yMax > 1.8);
      assert.equal(model.tiers.length,2);
      assert.equal(model.tiers[1].sharpe,1.75);
      assert.equal(data.scatterModel([],null).tiers.length,0);
      assert.equal(data.formatMetric(null),'—');
      assert.equal(data.short(' rank(  close ) ',12),'rank( close…');
    """)


def dashboard_check(source, setup=""):
    run_js("import assert from 'node:assert/strict';\nimport fs from 'node:fs';\n"
           f"import {{documentFromHTML,descendants}} from {json.dumps((Path(__file__).parent/'frontend_dom.mjs').as_uri())};\n"
           f"const doc=documentFromHTML(fs.readFileSync({json.dumps(str(WEB/'index.html'))},'utf8'));\n"
           "globalThis.document=doc;\n"+setup+"\n"
           f"const {{Dashboard}}=await import({json.dumps((WEB/'app.js').as_uri())});\n"
           "const app=new Dashboard(doc);\ntry {\n"+source+"\n} finally {app.destroy();}\n")


def test_dashboard_diffs_nodes_bounds_scene_and_keeps_expression_as_text():
    dashboard_check("""
      const expr='<img src=x onerror=alert(1)> + rank(close < 3)';
      const alphas=Array.from({length:180},(_,i)=>({id:`a${i}`,expr,status:i%2?'candidate':'done',sharpe:1,fitness:.6,turnover:.2,pid:0}));
      const snapshot={day:'2026-10-15',alphas,review:alphas.slice(0,12),sessions:[{pid:0,label:'未知会话',shape:'ghost',color:'#e8ecf4'}],events:[{seq:50,kind:'candidate',pid:0}]};
      app.render(snapshot);
      assert.equal(app.scene.effects.length,0,'Initial events are history, not animation');
      const before=descendants(doc.documentElement),card=doc.getElementById('role-cards').firstChild;
      const point=app.scatter.points.get('a0').node;
      const network=app.scene.networkNodes.get('a0').g;
      const canvas=app.scene.canvas,background=app.scene.svg;
      const sceneSize=descendants(canvas),surfaceCount=app.scene.layers.surfaces.size;
      const networkSurface=app.scene.networkNodes.get('a0').surface;
      assert.equal(canvas.children[0],background);
      assert.equal(canvas.children.at(-1),app.scene.layers.root);
      assert.equal(network.parentNode,networkSurface.svg);
      for(let i=0;i<30;i++)app.render(snapshot);
      assert.equal(descendants(doc.documentElement),before);
      assert.equal(descendants(canvas),sceneSize);
      assert.equal(app.scene.layers.surfaces.size,surfaceCount);
      assert.equal(app.scene.canvas,canvas);
      assert.equal(app.scene.svg,background);
      assert.equal(app.scene.networkNodes.get('a0').surface,networkSurface);
      assert.equal(doc.getElementById('role-cards').firstChild,card);
      assert.equal(app.scatter.points.get('a0').node,point);
      assert.equal(app.scene.networkNodes.get('a0').g,network);
      assert.equal(app.scatter.points.size,180);
      assert.equal(doc.getElementById('recent-alphas'),null);
      assert.equal(app.scene.networkNodes.size,60);
      assert.equal(app.scene.noteNodes.size,9);
      point.dispatch('click');
      assert.equal(doc.getElementById('drawer-expression').textContent,expr);
      assert.ok(doc.getElementById('drawer-fields').textContent.includes('未知会话'));
      assert.equal(doc.getElementById('drawer-overlay').hidden,false);
      doc.dispatch('keydown',{key:'Escape',preventDefault(){}});
      assert.equal(doc.getElementById('drawer-overlay').hidden,true);
      assert.equal(doc.documentElement.querySelectorAll('img').length,0);
      app.render({...snapshot,events:[{seq:51,kind:'sim_done',pid:0}]});
      assert.equal(app.scene.effects.length,1);
      doc.hidden=true;doc.dispatch('visibilitychange');
      app.render({...snapshot,events:[{seq:52,kind:'candidate',pid:0}]});
      assert.equal(app.scene.effects.length,0);
      assert.equal(doc.frames.size,0);
      app.render(null);
      assert.equal(app.alphaIndex.size,0);
      assert.equal(app.scene.networkNodes.size,0);
      assert.equal(networkSurface.removed,true);
      assert.equal(networkSurface.host.isConnected,false);
      assert.ok([...app.cardNodes.values()].every(entry=>entry.value.textContent==='0'));
    """)


def test_drawer_copies_available_expression_and_traps_keyboard_focus():
    dashboard_check("""
      const value='rank(close < ts_mean(close, 5))';let copied=null;
      Object.defineProperty(globalThis,'navigator',{configurable:true,value:{clipboard:{writeText:async text=>{copied=text;}}}});
      app.render({alphas:[{id:'a',expr:value,status:'candidate',pid:0}],sessions:[{pid:0,label:'未知会话'}]});
      app.openAlpha('a');
      assert.equal(doc.activeElement,doc.getElementById('drawer-close'));
      const reverse=doc.getElementById('drawer-close');
      doc.dispatch('keydown',{key:'Tab',shiftKey:true,preventDefault(){}});
      assert.equal(doc.activeElement,doc.getElementById('drawer-expression'));
      doc.dispatch('keydown',{key:'Tab',shiftKey:false,preventDefault(){}});
      assert.equal(doc.activeElement,reverse);
      await app.copyExpression();assert.equal(copied,value);
      doc.getElementById('drawer-backdrop').dispatch('click');
      assert.equal(app.openId,null);assert.equal(doc.getElementById('factory-app').inert,false);
    """)


def test_fetch_precedes_sse_and_connection_recovers_without_duplicate_streams():
    dashboard_check("""
      const calls=[];
      class Stream {
        constructor(url){calls.push(url);this.events={};this.closed=false;}
        addEventListener(key,handler){this.events[key]=handler;}
        close(){this.closed=true;}
      }
      await app.connect({fetcher:async url=>{calls.push(url);return {ok:true,json:async()=>({mode:'demo',events:[{seq:10,kind:'candidate'}]})};},EventSourceClass:Stream});
      assert.deepEqual(calls,['/api/state','/api/stream']);
      assert.equal(app.scene.effects.length,0);
      app.source.events.open();
      assert.equal(doc.getElementById('connection').querySelector('span').textContent,'DEMO');
      app.source.events.error();
      assert.equal(doc.getElementById('connection').querySelector('span').textContent,'RECONNECTING');
      app.source.events.state({data:JSON.stringify({mode:'live',alphas:[],events:[]})});
      assert.equal(doc.getElementById('connection').querySelector('span').textContent,'LIVE');
      const source=app.source;app.destroy();
      assert.equal(source.closed,true);
      assert.equal(app.scene.layers.surfaces.size,0);
      assert.equal(app.scene.canvas.isConnected,false);
      assert.equal(doc.frames.size,0);
    """)


def test_svg_charts_update_existing_points_thresholds_and_failure_bars():
    dashboard_check("""
      const timeline=[{t:'2026-10-15T12:00:00+08:00',eval_passed:2,candidates_cum:1,sims_done:3},
        {t:'2026-10-15T12:15:00+08:00',eval_passed:1,candidates_cum:2,sims_done:1}];
      const alphas=[{id:'a',sharpe:1.8,fitness:1,status:'candidate'}];
      const thresholds={soft:{standard:{sharpe:1.25,fitness:1.0},high:{sharpe:1.75,fitness:1.15}}};
      app.render({timeline,alphas,thresholds,events:[{seq:1,kind:'sim_fail',ts:'2026-10-15T12:01:00+08:00'}]});
      assert.equal(app.output.bars.size,2);assert.equal(app.scatter.tiers.size,2);
      assert.equal([...app.output.bars.values()][0].getAttribute('fill'),'#ff4d5e');
      const point=app.scatter.points.get('a').node;
      assert.equal(point.getAttribute('fill'),'#ff5fa2');
      point.dispatch('focus');assert.equal(point.getAttribute('r'),'6');
      assert.equal(doc.getElementById('tooltip').hidden,false);
      point.dispatch('keydown',{key:'Enter'});
      assert.equal(app.openId,'a');app.closeDrawer();
      app.render({timeline,alphas,thresholds});
      assert.equal(app.scatter.points.get('a').node,point);
      assert.equal(doc.getElementById('scatter-chart').getAttribute('role'),'group');
      app.render({timeline:[],alphas:[],thresholds:null});
      assert.equal(app.output.bars.size,0);assert.equal(app.scatter.points.size,0);assert.equal(app.scatter.tiers.size,0);
    """)


def test_scene_event_budget_hidden_motion_and_replacement_memory_bounds():
    dashboard_check("""
      const base={day:'2026-10-15',sessions:[{pid:0,label:'未知会话',shape:'ghost',color:'#e8ecf4',phase:'simulating'}],
        alphas:[{id:'a',status:'candidate',sharpe:1.8}],events:[{seq:1,kind:'candidate',pid:0}]};
      app.render(base);assert.equal(app.scene.effects.length,0);
      app.render({...base,events:Array.from({length:40},(_,i)=>({seq:i+2,kind:i%2?'candidate':'prod_block',pid:0}))});
      assert.equal(app.scene.effects.length,1,'The spider works on one action at a time');
      assert.ok(app.scene.narrative.queue.length+1<=12);
      assert.equal(app.scene.narrative.active.kind,'summary','An overflow jumps to final state with one quick action');
      app.scene._tick(50000);assert.equal(app.scene.effects.length,0);
      doc.media.change(true);
      app.render({...base,events:[{seq:42,kind:'candidate',pid:0}]});
      assert.equal(app.scene.effects.length,0);
      doc.media.change(false);
      app.render({...base,day:'2026-10-16',events:[{seq:1,kind:'candidate'}]});
      assert.equal(app.scene.effects.length,0);
      for(let batch=0;batch<10;batch++){
        const alphas=Array.from({length:1600},(_,i)=>({id:`${batch}_${i}`,sharpe:i%4-1,fitness:.5,status:i===1599?'candidate':'done'}));
        app.render({...base,alphas,review:[alphas[1599]],events:[]});
        assert.equal(app.scene.networkNodes.size,60);
        assert.equal(doc.getElementById('recent-alphas'),null);
        assert.equal(app.scatter.points.size,1500);
        assert.ok(app.scatter.points.has(alphas[1599].id));
        assert.equal(app.scene.layers.webClip.querySelectorAll('.wq-cocoon').length<=68,true,
          'At most 60 current and eight retiring cocoons remain in the full scene');
      }
      app.render({alphas:[],review:[],sessions:[],events:[]});
      assert.equal(app.scene.networkNodes.size,0);assert.equal(app.scene.sessionNodes.size,0);assert.equal(app.scene.noteNodes.size,0);
      assert.equal(app.scene.sessionLayer.children.length,0);
      assert.equal(app.scene.sessionOverlay.children.length,0);
      assert.equal(app.scene.noteLayer.children.length,0);
      assert.equal(app.scene.layers.webClip.querySelectorAll('.wq-cocoon').length,0);
      assert.equal(app.scatter.points.size,0);
    """)


def test_new_cocoons_and_batch_events_keep_serial_queue_bounded():
    dashboard_check("""
      app.render({day:'2026-10-15',alphas:[{id:'baseline'}],events:[{seq:1,kind:'sim_done'}]});
      app.render({day:'2026-10-15',alphas:Array.from({length:24},(_,i)=>({id:`new${i}`,status:'done'})),
        events:Array.from({length:12},(_,i)=>({seq:i+2,kind:'sim_done'}))});
      assert.equal(app.scene.networkNodes.size,24);
      assert.equal(app.scene.narrative.active.kind,'sim_done');
      assert.equal(app.scene.narrative.queue.length,11);
      assert.equal(app.scene.effectLayer.children.length,1,'Only the active batch owns effect nodes');
      const active=app.scene.narrative.active;
      assert.equal(active.g.parentNode,app.scene.effectLayer);
      assert.equal(active.g.getAttribute('data-effect'),'sim_done');
      assert.ok(active.surfaces.length>0);
      assert.ok(active.surfaces.every(surface=>surface.host.parentNode===active.g&&surface.host.isConnected));
    """)


def test_scene_region_badges_include_every_region_in_the_snapshot():
    dashboard_check("""
      const regions=['USA','ASI','EUR','CHN','JPN','IND'];
      app.render({sessions:regions.map((region,pid)=>({pid,region,label:`会话 ${pid+1}`}))});
      const displayed=new Set(app.scene.regionBadges.map(badge=>badge.text.textContent));
      assert.ok(regions.every(region=>displayed.has(region)));
      app.render({sessions:[]});assert.equal(app.scene.regionBadges.length,4);
    """)
