"""Count actual frontend writes so cached snapshots cannot repaint every panel."""

from test_frontend import dashboard_check


# Track writes at the DOM boundary while keeping all production rendering code real.
# The shared DOM harness models structure; CSS/layout needs a separate browser check.
COUNT_WRITES = r"""
  const writes=[];
  const originalCreate=doc.createElement.bind(doc), originalNS=doc.createElementNS.bind(doc);
  const instrument=node=>{
    const set=node.setAttribute.bind(node), remove=node.removeAttribute.bind(node);
    node.setAttribute=(key,value)=>{writes.push({node,kind:'attr',key,value:String(value)});set(key,value);};
    node.removeAttribute=key=>{writes.push({node,kind:'attr',key});remove(key);};
    for(const key of ['appendChild','insertBefore','remove']){
      const original=node[key].bind(node);
      node[key]=(...args)=>{writes.push({node,kind:'structure',key});return original(...args);};
    }
    let prototype=Object.getPrototypeOf(node);
    for(const key of ['textContent','className']){
      const descriptor=Object.getOwnPropertyDescriptor(prototype,key);
      Object.defineProperty(node,key,{configurable:true,get(){return descriptor.get.call(this);},set(value){writes.push({node,kind:key,key,value:String(value)});descriptor.set.call(this,value);}});
    }
    for(const key of ['title','dateTime']){
      let value=node[key];
      Object.defineProperty(node,key,{configurable:true,get(){return value;},set(next){writes.push({node,kind:'property',key,value:next});value=next;}});
    }
    const style=node.style;
    const originalProperty=style.setProperty.bind(style);
    style.setProperty=(key,value)=>{writes.push({node,kind:'style',key,value:String(value)});originalProperty(key,value);};
    node.style=new Proxy(style,{set(target,key,value){if(key!=='setProperty')writes.push({node,kind:'style',key,value});target[key]=value;return true;}});
    node.dataset=new Proxy(node.dataset,{set(target,key,value){writes.push({node,kind:'dataset',key,value});target[key]=value;return true;}});
    return node;
  };
  doc.createElement=tag=>instrument(originalCreate(tag));
  doc.createElementNS=(ns,tag)=>instrument(originalNS(ns,tag));
  const instrumentTree=node=>{instrument(node);node.children.forEach(instrumentTree);};
  instrumentTree(doc.documentElement);
  const within=(node,roots)=>{for(let parent=node;parent;parent=parent.parentNode)if(roots.includes(parent))return true;return false;};
"""


def test_unchanged_snapshot_does_not_write_panels_or_chart_dom():
    # Removing content memoization or writing an unchanged class/style fails here.
    dashboard_check(r"""
      const snapshot={day:'2026-10-15',mode:'demo',generated_at:'2026-10-15T12:00:00+08:00',revision:1,
        totals:{alphas:3,eval_passed:2,candidates:1,sims_done:4},goal:{target:5,candidates:1},
        cards:[{key:'simulate',busy:true,value:4,progress:.4,message:'回测中'}],
        alphas:[{id:'a',expr:'rank(close)',sharpe:1.8,fitness:1,status:'candidate',turnover:.2}],
        timeline:[{t:'2026-10-15T12:00:00+08:00',eval_passed:2,candidates_cum:1,sims_done:4}],
        thresholds:{hard:[{key:'market',value:'USA',note:'market'}],soft:{standard:{sharpe:1.25,fitness:1.0},high:{sharpe:1.75,fitness:1.15}}},
        rejects:{sim_fail:1},funnel:[{key:'submit',count:4}],events:[]};
      app.render(snapshot); app.setConnection(true);
      const draws=[0,0];
      [app.output,app.scatter].forEach((chart,index)=>{const draw=chart.draw.bind(chart);chart.draw=()=>{draws[index]++;draw();};});
      const roots=['role-cards','goal-fill','goal-meter','connection','output-chart','scatter-chart','analysis-stats','scatter-ignored','fail-reasons','prod-histogram','prod-summary'].map(id=>doc.getElementById(id));
      writes.length=0;
      for(let i=0;i<4;i++)app.render(JSON.parse(JSON.stringify({...snapshot,revision:i+2,generated_at:`2026-10-15T12:00:0${i+1}+08:00`})));
      const panelWrites=writes.filter(write=>within(write.node,roots));
      assert.deepEqual(panelWrites.map(write=>[write.node.id||write.node.tagName,write.kind,write.key]),[], 'Only time labels may change for a metadata-only snapshot');
      assert.deepEqual(draws,[0,0],'Unchanged output and scatter inputs must return before drawing');
      assert.equal(app.cardNodes.get('simulate').fill.style.transform,'scaleX(0.4)');
      assert.equal(doc.getElementById('goal-fill').style.transform,'scaleX(0.2)');
    """, setup=COUNT_WRITES)


def test_scatter_only_mutates_changed_points_when_domains_stay_fixed():
    # Rewriting axes or every circle for one changed metric fails this test.
    dashboard_check(r"""
      const alphas=[{id:'left',sharpe:-3,fitness:-2,status:'done'},
        {id:'middle',sharpe:1,fitness:.5,status:'eval_passed',expr:'old'},
        {id:'right',sharpe:6,fitness:4,status:'candidate'}];
      app.scatter.update({alphas});
      let draws=0;const draw=app.scatter.draw.bind(app.scatter);app.scatter.draw=()=>{draws++;draw();};
      writes.length=0;
      app.scatter.update({alphas:structuredClone(alphas),revision:3,generated_at:'other'});
      assert.equal(draws,0,'A repeated scatter snapshot must skip drawing');
      assert.equal(writes.length,0);
      const changed=structuredClone(alphas);changed[1].sharpe=1.25;changed[1].expr='new';
      app.scatter.update({alphas:changed});
      const entry=app.scatter.points.get('middle');
      assert.ok(writes.length>0,'The changed point must actually move');
      assert.ok(writes.every(write=>write.node===entry.node||write.node===entry.title),'Stable domains must not rewrite axes, tiers, or other points');
      assert.ok(writes.some(write=>write.key==='cx'));
      writes.length=0;changed[1].expr='newer';app.scatter.update({alphas:changed});
      assert.equal(writes.length,0,'Nonvisual alpha data must not repaint a point');
      let hovered=null;app.scatter.onHover=alpha=>hovered=alpha;
      entry.node.dispatch('focus');assert.equal(hovered.expr,'newer','Hover data must refresh even when point attributes do not');
    """, setup=COUNT_WRITES)


def test_chart_resize_redraws_cached_content_and_failure_buckets_survive_event_rolloff():
    # A cache that ignores dimensions or drops remembered failures fails here.
    dashboard_check(r"""
      const snapshot={day:'2026-10-15',timeline:[{t:'2026-10-15T12:00:00+08:00',sims_done:1}],
        alphas:[{id:'a',sharpe:1,fitness:.5,status:'done'}],events:[{kind:'sim_fail',ts:'2026-10-15T12:01:00+08:00'}]};
      app.output.update(snapshot);app.scatter.update(snapshot);
      const bar=[...app.output.bars.values()][0], point=app.scatter.points.get('a').node;
      const originalX=point.getAttribute('cx');
      writes.length=0;app.output.update({...snapshot,events:[]});
      assert.equal(writes.length,0,'A rolled-off failure event must retain the same red bucket without repainting');
      assert.equal(bar.getAttribute('fill'),'#ff4d5e');
      for(const chart of [app.output,app.scatter])chart.resize({contentRect:{width:700,height:260}});
      assert.notEqual(point.getAttribute('cx'),originalX);
      assert.equal(app.scatter.svg.getAttribute('viewBox'),'0 0 700 260');
      assert.ok(Number.isFinite(Number(point.getAttribute('cx'))));
      assert.equal(bar.getAttribute('fill'),'#ff4d5e');
      app.output.update({...snapshot,day:'2026-10-16',events:[]});
      assert.notEqual(bar.getAttribute('fill'),'#ff4d5e');
    """, setup=COUNT_WRITES)


def test_clock_checks_inactivity_and_tracks_wake_after_update():
    # Without the one-second activity check, a quiet page never pauses ambient CSS.
    dashboard_check(r"""
      let checks=0;app.scene.environmentIdle=false;
      app.scene.checkActivity=()=>{checks++;app.scene.environmentIdle=true;return true;};
      app.tickClock();
      assert.equal(checks,1);
      assert.equal(doc.documentElement.classList.contains('environment-idle'),true);
      app.scene.update=()=>{app.scene.environmentIdle=false;};
      app.render({day:'2026-10-15',events:[]});
      assert.equal(doc.documentElement.classList.contains('environment-idle'),false,'A scene update must synchronize wake state after the clock check');
    """, setup=COUNT_WRITES)
