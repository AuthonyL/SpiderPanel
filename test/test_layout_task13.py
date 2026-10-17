"""Approved compact desk layout, bounded bubbles and display-only outliers."""
from test_chart_resize import chart_check
from test_frontend import dashboard_check
from test_scene_r1 import scene_check
from test_work_mode import CLOCK


def test_removed_panels_are_absent_but_scatter_thresholds_remain():
    dashboard_check("""
      app.render({thresholds:{soft:{standard:{sharpe:1.25,fitness:1.0},high:{sharpe:1.75,fitness:1.15}}}});
      for(const id of ['threshold-title','hard-rules','soft-rules','tier-label','funnel',
        'reject-total','recent-alphas','output-hero','output-count'])assert.equal(doc.getElementById(id),null);
      for(const name of ['thresholds-panel','recent-section','chart-legend','output-head'])
        assert.equal(doc.documentElement.querySelectorAll('.'+name).length,0);
      assert.equal(doc.documentElement.querySelectorAll('.panel').length,3);
      assert.equal(doc.getElementById('bottleneck-title'),null);
      assert.equal(app.scatter.tiers.size,2);
      assert.ok(!doc.documentElement.textContent.includes('LATEST DISCOVERIES'));
    """)


def test_output_is_full_height_simulation_bars_without_curves_or_end_dots():
    chart_check("""
      process.env.TZ='Asia/Shanghai';
      const output=new OutputChart(outputSvg);resize(outputSvg,400,220);output.update(snapshot);
      assert.equal(output.bars.size,2);
      assert.equal(outputSvg.querySelectorAll('path').length,0);
      assert.equal(outputSvg.querySelectorAll('circle').length,0);
      const bars=[...output.bars.values()];
      assert.equal(bars[0].getAttribute('fill'),'#ff4d5e');
      assert.equal(bars[1].getAttribute('fill'),'#3ddc84');
      assert.ok(Number(bars[0].getAttribute('height'))>100,'Use the plot, not a tiny bottom strip');
      assert.ok(Number(bars[0].getAttribute('height'))>Number(bars[1].getAttribute('height')));
      assert.ok(outputSvg.querySelectorAll('text').some(node=>node.textContent==='12:00'));
      let draws=0;const draw=output.draw.bind(output);output.draw=()=>{draws++;draw();};
      output.update({...snapshot,timeline:snapshot.timeline.map(row=>({...row,eval_passed:99,candidates_cum:100}))});
      assert.equal(draws,0,'Removed curves must not invalidate the bar chart');
      output.destroy();
    """)


def test_only_unqualified_percentile_outliers_are_hidden_and_input_is_untouched():
    chart_check("""
      const {filterScatterPoints}=await import('./SpiderPanel/web/charts.js');
      const normal=Array.from({length:200},(_,i)=>({id:`n${i}`,sharpe:-.7+i*.01,fitness:-.4+i*.01,status:'done'}));
      const bad=[{id:'outlier01',sharpe:4.8,fitness:8,status:'eval_failed'},
        {id:'low-s',sharpe:-50,fitness:.5,status:'rejected'},
        {id:'low-f',sharpe:.2,fitness:-50,status:'prod_blocked',passed:true}];
      const qualified=['eval_passed','prod_ok','candidate'].map((status,i)=>({id:`keep${i}`,status,sharpe:40+i*10,fitness:40+i*10}));
      const alphas=[...normal,...bad,...qualified,{id:'missing',sharpe:null,fitness:1}];
      const before=JSON.stringify(alphas),filtered=filterScatterPoints(alphas);
      assert.equal(filtered.ignored,3);assert.equal(filtered.points.length,203);
      assert.ok(bad.every(alpha=>!filtered.points.includes(alpha)));
      assert.ok(qualified.every(alpha=>filtered.points.includes(alpha)));
      assert.equal(JSON.stringify(alphas),before);
      const scatter=new ScatterChart(scatterSvg);scatter.update({alphas:[...normal,bad[0]]});
      assert.equal(scatter.ignoredCount,1);assert.equal(scatter.points.has('outlier01'),false);
      assert.ok(scatter.model.xMax<4.8&&scatter.model.yMax<8);
      scatter.destroy();
      for(const alphas of [null,[],[{id:'x',sharpe:0,fitness:0}],
        Array.from({length:100},(_,i)=>({id:String(i),sharpe:1,fitness:1}))]){
        assert.equal(filterScatterPoints(alphas).ignored,0,'Equal metrics and tiny sets are valid');
      }
      const huge=Array.from({length:100},(_,i)=>({id:`huge${i}`,sharpe:i%2?-1e308:1e308,fitness:1}));
      assert.equal(filterScatterPoints([...huge,{id:'extreme',sharpe:1.7e308,fitness:1}]).ignored,1,
        'Finite percentile spans must not overflow to an unbounded range');
    """)


def test_existing_point_budget_prioritizes_all_qualified_statuses():
    chart_check("""
      const ordinary=Array.from({length:1500},(_,i)=>({id:`n${i}`,sharpe:1,fitness:1,status:'done'}));
      const qualified=['eval_passed','prod_ok','candidate'].map(status=>({id:status,status,sharpe:50,fitness:50}));
      const scatter=new ScatterChart(scatterSvg);scatter.update({alphas:[...ordinary,...qualified]});
      assert.equal(scatter.points.size,1500,'Keep the accepted DOM/memory limit');
      for(const point of qualified)assert.ok(scatter.points.has(point.id));
      assert.equal(scatter.ignoredCount,0,'Capacity is not a percentile rejection');
      scatter.destroy();
    """)


def test_ignored_count_is_visible_only_when_nonzero_and_does_not_remove_details():
    dashboard_check("""
      const normal=Array.from({length:200},(_,i)=>({id:`n${i}`,sharpe:-.7+i*.01,fitness:-.4+i*.01,status:'done'}));
      const outlier={id:'outlier01',sharpe:4.8,fitness:8,status:'eval_failed',expr:'rank(close < volume)'};
      app.render({alphas:[...normal,outlier],totals:{alphas:201}});
      const note=doc.getElementById('scatter-ignored');
      assert.equal(note.hidden,false);assert.equal(note.textContent,'已忽略 1 个异常点');
      assert.equal(app.stats[0].textContent,'201');assert.equal(app.alphaIndex.size,201);
      assert.equal(app.scatter.points.size,200);
      app.openAlpha(outlier.id);assert.equal(app.openId,outlier.id);
      assert.equal(doc.getElementById('drawer-expression').textContent,outlier.expr);app.closeDrawer();
      const point=app.scatter.points.get('n10').node;
      app.render({alphas:normal});assert.equal(note.hidden,true);
      assert.equal(app.scatter.points.get('n10').node,point);
    """)


def test_speech_bubbles_fit_short_and_long_text_and_leave_neighbor_gaps():
    scene_check("""
      scene.update({sessions:[session(1),session(2),session(3)]});
      const entries=[...scene.sessionNodes.values()];
      entries[0].setBubble('构思中...');const small=entries[0].bubbleWidth;
      assert.ok(small>=64&&small<90);
      entries[0].setBubble('rank(ts_delta(close, 5)) + '.repeat(20));
      assert.ok(entries[0].bubbleWidth>small&&entries[0].bubbleWidth<=168);
      assert.ok(entries[0].expr.textContent.endsWith('…'));
      assert.ok(entries[0].bubbleShape.getAttribute('d').includes('L0-61'));
      for(let i=1;i<entries.length;i++){
        entries[i].setBubble('很长的表达式'.repeat(20));
        const left=entries[i-1],right=entries[i];
        const gap=right.overlaySurface.point.x-right.bubbleWidth/2-left.overlaySurface.point.x-left.bubbleWidth/2;
        assert.ok(gap>=30,'Adjacent maximum-width bubbles must not join');
      }
      const entry=entries[0];let writes=0;const set=entry.bubbleShape.setAttribute.bind(entry.bubbleShape);
      entry.bubbleShape.setAttribute=(...args)=>{writes++;set(...args);};
      entry.setBubble('构思中');entry.setBubble('构思中');assert.equal(writes,1);
    """)


def test_thinking_and_expression_restore_use_the_same_bubble_sizer():
    scene_check(CLOCK + """
      const expr='rank(ts_delta(close, 5)) + rank(volume)';
      scene.update({...base,sessions:[session(0,{phase:'thinking',last_expr:expr})]});
      const entry=scene.sessionNodes.get('0'),width=entry.bubbleWidth;
      advance(1000);assert.ok(entry.expr.textContent.startsWith('构思中'));
      assert.ok(entry.bubbleWidth<=90);assert.equal(doc.frames.size,0);
      scene.update({...base,sessions:[session(0,{phase:'prod',last_expr:expr})]});
      assert.ok(entry.expr.textContent.startsWith('rank('));assert.ok(entry.bubbleWidth>width);
      assert.ok(entry.bubbleWidth<=168);
    """)
