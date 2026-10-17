"""Ongoing tool activity uses truthful data and finite, interruptible motion."""

from test_scene_r1 import scene_check


CLOCK = r"""
  let now=100;doc.defaultView.performance.now=()=>now;
  const epoch=Date.parse('2026-10-16T12:00:00+08:00');
  scene.work.clock=()=>epoch/1000+(now-100)/1000;
  scene.work.random=()=>0;
  const since=new Date(epoch-120000).toISOString();
  const base={day:'2026-10-16',mode:'live',generated_at:new Date(epoch).toISOString(),
    sessions:[session(1,{label:'矿工甲',phase:'thinking',inflight:null})],events:[],pending_sims:[]};
  const advance=ms=>{for(let done=0;done<ms;done+=20){
    now+=Math.min(20,ms-done);doc.sampleAnimations();
    for(const [id,callback]of [...doc.frames]){doc.frames.delete(id);callback(now);}
  }};
  const alphas=[{id:'a',pid:1,sim:'batch',status:'done',slot:8},{id:'b',pid:1,sim:'batch',status:'done',slot:19}];
  const inflight=(tool,extra={})=>({tool,since,...extra});
"""


def test_thinking_has_one_hz_dots_elapsed_and_typing_without_idle_frames():
    scene_check(CLOCK + r"""
      const captions=[];scene.onCaption=entry=>{if(entry)captions.push(entry);};
      scene.update({...base,sessions:[session(1,{label:'矿工甲',phase:'thinking',phase_label:'构思中',since})]});
      const entry=scene.sessionNodes.get('1');
      assert.equal(entry.station.thinkingElapsed.textContent,'构思中 2:00');
      assert.equal(entry.bubble.getAttribute('opacity'),'1');
      assert.ok(captions.some(entry=>entry.work&&entry.text.includes('矿工甲')&&entry.text.includes('构思中')));
      const hand=entry.portrait.querySelector('.wq-hand-left');let writes=0;
      const set=hand.setAttribute.bind(hand);hand.setAttribute=(key,value)=>{if(key==='transform')writes++;set(key,value);};
      advance(2000);assert.equal(writes,2);
      assert.equal(entry.station.thinkingElapsed.textContent,'构思中 2:02');
      assert.equal(entry.expr.textContent,'构思中..');
      assert.equal(doc.frames.size,0);
      scene.update({...base,sessions:[session(1,{phase:'idle',idle:true})]});
      assert.equal(entry.bubble.getAttribute('opacity'),'0');assert.equal(scene.work.timer,null);
      advance(40000);assert.equal(doc.frames.size,0);assert.equal(doc.animations.size,0);
    """)


def test_actual_sim_progress_overrides_elapsed_estimate_and_lights_eight_cells_per_batch():
    scene_check(CLOCK + r"""
      const pending=[{sim:'batch',pid:1,n:8,since,progress:.25,children_done:2,children_total:8},
        {sim:'batch2',pid:1,n:4,since,progress:null,children_done:3,children_total:4}];
      scene.update({...base,sim_typical_seconds:100,pending_sims:pending,
        sessions:[session(1,{phase:'simulating',inflight:inflight('wait_for_simulation')})]});
      const station=scene.stations[0];
      assert.equal(station.progress.getAttribute('data-progress-source'),'actual');
      assert.equal(Number(station.progress.getAttribute('width')),36);
      assert.equal(station.progress.getAttribute('data-waiting'),'false');
      const columns=scene.work.batchColumns;
      assert.equal(columns.size,2);assert.equal(columns.get('batch').cells.length,8);
      assert.equal(columns.get('batch').cells.filter(cell=>cell.getAttribute('data-lit')==='true').length,2);
      assert.equal(columns.get('batch2').cells.filter(cell=>cell.getAttribute('data-lit')==='true').length,6);
      scene.update({...base,pending_sims:[{...pending[0],progress:1}],sim_typical_seconds:null});
      assert.equal(columns.size,1);assert.equal(columns.get('batch').cells.filter(cell=>cell.getAttribute('data-lit')==='true').length,8);
      scene.update(base);assert.equal(columns.size,0);
    """)


def test_eval_walks_real_silk_to_each_cocoon_and_result_yields_at_current_position():
    scene_check(CLOCK + r"""
      const work={...base,alphas,sessions:[session(1,{phase:'evaluating',inflight:inflight('evaluate_alpha',{sim:'batch'})})],
        events:[{seq:1,kind:'eval_start',pid:1,sim:'batch',alphas:['a','b'],n:2}]};
      scene.update(work);advance(1000);
      const action=scene.narrative.workAction;assert.equal(action.kind,'inspection');
      assert.ok(action.travel.plan.frames.length>2);assert.ok(doc.frames.size>0);
      advance(500);const current=scene.spider.positionSurface.positionAt(now);
      assert.ok(Math.hypot(current.x-scene.spider.home.x,current.y-scene.spider.home.y)>0);
      scene.update({...work,events:[...work.events,{seq:2,kind:'eval_pass',pid:1,alpha:'a'}]});
      assert.equal(scene.narrative.workAction,null);
      const first=scene.narrative.active.travel.plan.frames[0];
      assert.ok(Math.hypot(first.x-current.x,first.y-current.y)<.001,'Result starts at the visible native animation position');
      advance(12000);scene.update(base);advance(500);
      assert.equal(doc.frames.size,0);assert.equal(scene.narrative.workAction,null);
    """)


def test_eval_inspects_next_cocoon_on_shared_clock_without_inventing_events():
    scene_check(CLOCK + r"""
      scene.update({...base,alphas,sessions:[session(1,{phase:'evaluating',inflight:inflight('evaluate_alpha',{sim:'batch'})})],
        events:[{seq:1,kind:'eval_start',pid:1,sim:'batch',alphas:['a','b']}]});
      advance(3200);assert.equal(scene.work.inspectedAlpha,'a');
      assert.ok(scene.work.inspectionBeam);assert.equal(scene.lastSeq,1);
      advance(2000);assert.equal(scene.narrative.workAction.alpha,'b');
      advance(3000);assert.equal(scene.work.inspectedAlpha,'b');
      assert.equal(scene.lastSeq,1);assert.ok(scene.layers.promotions.size<=22);
    """)


def test_prod_aims_radar_at_cocoon_and_pulses_every_three_seconds():
    scene_check(CLOCK + r"""
      scene.update({...base,alphas,sessions:[session(1,{phase:'prod',inflight:inflight('check_prod_correlation',{alpha:'a'})})]});
      advance(1000);const pulse=scene.work.prodPulse;
      assert.ok(pulse);assert.equal(pulse.host.getAttribute('data-alpha'),'a');
      assert.ok(scene.radarDishSurface.point.angle<0);
      assert.ok(!scene.radarDishSurface.animation,'Quiet radar headings step without a native timeline');
      assert.equal(pulse.motion.style.getPropertyValue('opacity'),'0.75');
      advance(1000);assert.equal(pulse.motion.style.getPropertyValue('opacity'),'0.3');
      advance(1000);assert.equal(pulse.motion.style.getPropertyValue('opacity'),'0');
      advance(1000);assert.equal(pulse.motion.style.getPropertyValue('opacity'),'0.75');
      assert.equal(scene.work.prodPulse,pulse,'Pulses reuse one stationary beam');
      assert.ok(!pulse.animation);assert.ok(!scene.radarDishSurface.animation);
      scene.update(base);assert.equal(scene.work.prodPulse,null);assert.equal(scene.radarDishSurface.point.angle,-32);
    """)


def test_saving_writes_temporary_note_then_yields_to_real_candidate_flip():
    scene_check(CLOCK + r"""
      const saving={...base,alphas,sessions:[session(1,{phase:'saving',inflight:inflight('save_candidate_alpha',{alpha:'a'})})]};
      scene.update(saving);advance(500);assert.equal(scene.work.savePreviews.size,1);
      const preview=scene.work.savePreviews.get('1');const before=preview.writing.getAttribute('d');
      advance(1000);assert.notEqual(preview.writing.getAttribute('d'),before);
      assert.equal(scene.noteNodes.size,0,'Temporary writing is not a saved candidate');
      scene.update({...base,alphas:[{...alphas[0],status:'candidate'}],review:[{...alphas[0],status:'candidate'}],
        events:[{seq:1,kind:'candidate',pid:1,alpha:'a'}]});
      assert.equal(scene.work.savePreviews.size,0);assert.equal(preview.surface.host.isConnected,false);
      advance(10000);const note=scene.noteNodes.get('a');assert.ok(note);
      assert.equal(note.surface.motion.style.getPropertyValue('opacity'),'1');
    """)


def test_patrol_is_sparse_out_and_back_on_silk_and_cancels_without_position_jump():
    scene_check(CLOCK + r"""
      const {SPIDER_PATROL_SECONDS}=await import('./SpiderPanel/web/animation-rules.js');
      assert.deepEqual(SPIDER_PATROL_SECONDS,[20,30]);
      scene.update(base);advance(19500);assert.equal(scene.narrative.workAction,null);
      const origin={...scene.spider.positionSurface.positionAt(now)};
      advance(1000);assert.equal(scene.narrative.workAction.kind,'patrol');
      const action=scene.narrative.workAction;
      assert.ok(action.travel.plan.duration>=1000&&action.travel.plan.duration<=1500);
      advance(2600);assert.equal(scene.narrative.workAction,null);
      const returned=scene.spider.positionSurface.positionAt(now);
      assert.ok(Math.hypot(returned.x-origin.x,returned.y-origin.y)<.001);assert.equal(doc.frames.size,0);
      advance(18500);assert.equal(scene.narrative.workAction,null);
      advance(2000);assert.ok(scene.narrative.workAction);
      const current=scene.spider.positionSurface.positionAt(now);doc.hidden=true;doc.dispatch('visibilitychange');
      const stopped=scene.spider.positionSurface.positionAt(now);
      assert.ok(Math.hypot(current.x-stopped.x,current.y-stopped.y)<.001);
      assert.equal(doc.frames.size,0);assert.equal(scene.work.timer,null);assert.equal(doc.animations.size,0);
    """)


def test_start_captions_are_immediate_and_keep_agent_count_and_alpha():
    scene_check(CLOCK + r"""
      const captions=[];scene.onCaption=entry=>{if(entry)captions.push(entry);};
      scene.update(base);
      const phases=[['sim_submit_start','submitting',{n:8},'开始提交回测 8 条表达式'],
        ['eval_start','evaluating',{sim:'batch',n:8,alphas:['a','b']},'开始评估 8 个 alpha'],
        ['prod_start','prod',{alpha:'a',alphas:['a']},'开始查相关性 a'],
        ['save_start','saving',{alpha:'a',alphas:['a']},'开始存候选 a']];
      for(let i=0;i<phases.length;i++){
        const [kind,phase,fields,wording]=phases[i];
        scene.update({...base,alphas,sessions:[session(1,{label:'kimi3 · 1',phase,inflight:inflight(kind,fields)})],
          events:[{seq:i+1,kind,pid:1,...fields}]});
        assert.equal(captions.at(-1).seq,i+1);
        assert.ok(captions.at(-1).text.includes('kimi3 · 1'));
        assert.ok(captions.at(-1).text.includes(wording));
      }
    """)


def test_real_progress_lamps_blink_at_one_hz_and_captions_use_reported_fraction():
    scene_check(CLOCK + r"""
      const captions=[];scene.onCaption=entry=>{if(entry)captions.push(entry);};
      scene.update({...base,sessions:[session(1)],sim_typical_seconds:100,
        pending_sims:[{sim:'batch',pid:1,n:8,since,progress:.375,children_done:3,children_total:8}]});
      const cell=scene.work.batchColumns.get('batch').cells[0];
      const opacity=cell.getAttribute('opacity');advance(1000);assert.notEqual(cell.getAttribute('opacity'),opacity);
      const next=cell.getAttribute('opacity');advance(500);assert.equal(cell.getAttribute('opacity'),next);
      assert.ok(captions.some(entry=>entry.text.includes('38%')));
      assert.ok(!captions.some(entry=>entry.text.includes('超过典型用时')),'Real progress takes precedence over elapsed estimates');
    """)


def test_radar_and_writing_continue_while_spider_handles_another_real_event():
    scene_check(CLOCK + r"""
      scene.update({...base,alphas});
      scene.update({...base,alphas,sessions:[session(1,{phase:'saving',inflight:inflight('save',{alpha:'a'})}),
        session(2,{phase:'prod',inflight:inflight('prod',{alpha:'b'})})],
        events:[{seq:1,kind:'sim_done',pid:1,n:8,alphas:['a','b']}]});
      assert.ok(scene.narrative.working);
      assert.equal(scene.work.savePreviews.size,1);
      const preview=scene.work.savePreviews.get('1'),before=preview.writing.getAttribute('d');
      advance(1000);assert.notEqual(preview.writing.getAttribute('d'),before);
      assert.equal(scene.work.prodPulse.host.getAttribute('data-alpha'),'b');
      assert.ok(scene.layers.promotions.size<=22);assert.ok(doc.frames.size<=1);
    """)


def test_shortest_patrol_delay_does_not_restart_frames_as_event_queue_drains(monkeypatch):
    import test_animation_cost
    original = test_animation_cost.scene_check
    monkeypatch.setattr(test_animation_cost, "scene_check",
                        lambda source: original("scene.work.random=()=>0;\n" + source))
    # Keep every assertion in the reported regression, including the final
    # absence of rAF. A random 20–30s delay used to mask the unwanted patrol.
    test_animation_cost.test_queued_event_flights_continue_when_only_the_environment_turns_quiet()


def test_start_caption_uses_real_agent_even_when_its_workstation_is_grouped():
    scene_check(CLOCK + r"""
      const captions=[];scene.onCaption=entry=>{if(entry)captions.push(entry);};
      const sessions=Array.from({length:8},(_,index)=>session(index+1,{label:`agent${index+1}`,phase:'thinking'}));
      scene.update({...base,sessions});
      scene.update({...base,sessions,events:[{seq:1,kind:'prod_start',pid:8,alpha:'a'}]});
      assert.ok(captions.at(-1).text.startsWith('agent8 开始查相关性 a'));
      assert.equal(scene.sessionNodes.size,6);
    """)


def test_resumed_older_call_does_not_aim_at_a_newer_finished_calls_alpha():
    scene_check(CLOCK + r"""
      scene.update({...base,alphas,sessions:[session(1,{phase:'prod',inflight:inflight('prod',{alpha:'b'})})],
        events:[{seq:1,kind:'prod_start',pid:1,alpha:'a',alphas:['a']}]});
      advance(1000);assert.equal(scene.work.prodPulse.host.getAttribute('data-alpha'),'b');
    """)
