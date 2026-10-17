"""True ongoing work has one bounded clock, independent of event animations."""

from test_scene_r1 import scene_check


CLOCK = r"""
  let now=100;doc.defaultView.performance.now=()=>now;
  const epoch=Date.parse('2026-10-16T12:00:00+08:00');
  scene.work.clock=()=>epoch/1000+(now-100)/1000;
  scene.work.random=()=>0;
  const base={day:'2026-10-16',mode:'live',generated_at:new Date(epoch).toISOString(),
    sessions:[session(0,{label:'未知会话'})],events:[],sim_typical_seconds:300,
    pending_sims:[{sim:'batch',pid:0,n:8,since:new Date(epoch-120000).toISOString()}]};
  const advance=(ms,frameMs=100)=>{for(let done=0;done<ms;done+=frameMs){now+=Math.min(frameMs,ms-done);doc.sampleAnimations();
    for(const [id,callback]of [...doc.frames]){doc.frames.delete(id);callback(now);}}};
"""


def test_work_mode_enters_for_pending_or_active_session_and_fully_stops_when_idle():
    scene_check(CLOCK + r"""
      assert.equal(scene.work.active,false);assert.equal(scene.work.timer,null);
      scene.update(base);assert.equal(scene.work.active,true);assert.notEqual(scene.work.timer,null);
      assert.equal(scene.ambient.paused,true,'Work does not resume event-window ambient animations');
      assert.equal(doc.frames.size,0,'Waiting work has no rAF loop');
      scene.update({...base,pending_sims:[],sessions:[session(0,{phase:'evaluating'})]});
      assert.equal(scene.work.active,true);
      scene.update({...base,pending_sims:[],sessions:[session(0,{phase:'idle',idle:true})]});
      assert.equal(scene.work.active,false);assert.equal(scene.work.timer,null);
      scene.update({...base,sessions:[]});assert.equal(scene.work.active,true,'Pending alone is sufficient');
      scene.update({});assert.equal(scene.work.active,false);assert.equal(scene.work.timer,null);
    """)


def test_waiting_uses_real_since_and_typical_duration_without_false_completion():
    scene_check(CLOCK + r"""
      scene.update(base);const station=scene.stations[0];
      assert.equal(station.workElapsed.textContent,'已等 2:00');
      assert.equal(Number(station.progress.getAttribute('width')),72*.4);
      advance(2000);assert.equal(station.workElapsed.textContent,'已等 2:02');
      scene.update(base);advance(1000);
      assert.equal(station.workElapsed.textContent,'已等 2:03','Repeated cached snapshots do not reset the clock');
      scene.update({...base,sim_typical_seconds:null});
      assert.equal(station.progress.getAttribute('display'),'none');
      assert.equal(station.workElapsed.textContent,'已等 2:03');
      scene.update({...base,sim_typical_seconds:100});
      assert.equal(station.progress.getAttribute('data-waiting'),'true');
      assert.ok(station.phase.textContent.includes('等待中'));
      const x=station.progress.getAttribute('x');advance(2000);
      assert.notEqual(station.progress.getAttribute('x'),x);
      assert.ok(Number(station.progress.getAttribute('width'))<=72*.95);
      assert.equal(scene.sessionNodes.get('0').name.textContent,'未知会话');
    """)


def test_one_work_clock_caps_display_and_typing_at_one_hz():
    scene_check(CLOCK + r"""
      scene.update({...base,sessions:[session(0),session(1,{phase:'evaluating'}),session(2,{phase:'prod'})]});
      const hand=scene.sessionNodes.get('0').portrait.querySelector('.wq-hand-left');
      let handWrites=0,displayWrites=0,lampWrites=0;
      const count=(el,key,onwrite)=>{const set=el.setAttribute.bind(el);el.setAttribute=(k,v)=>{if(k===key)onwrite();set(k,v);};};
      count(hand,'transform',()=>handWrites++);count(scene.cabinetLitGroup,'opacity',()=>lampWrites++);
      count(scene.stations[2].panels.prod.querySelector('.wq-radar-sweep'),'transform',()=>displayWrites++);
      advance(10000);
      assert.equal(handWrites,10);assert.equal(lampWrites,0,'Hidden legacy lamps do not blink');assert.equal(displayWrites,10);
      assert.equal(scene.cabinetLamps.filter(el=>el.getAttribute('data-lit')==='true').length,1);
      assert.equal(scene.ambient.timer,null);assert.equal(doc.frames.size,0);
      scene.destroy();assert.equal(scene.work.timer,null);
    """)


def test_hidden_reduced_motion_and_offscreen_work_do_not_keep_a_timer():
    scene_check(CLOCK + r"""
      scene.update(base);const station=scene.stations[0];
      doc.hidden=true;doc.dispatch('visibilitychange');assert.equal(scene.work.timer,null);
      const before=station.workElapsed.textContent;advance(5000);assert.equal(station.workElapsed.textContent,before);
      doc.hidden=false;doc.dispatch('visibilitychange');assert.notEqual(scene.work.timer,null);
      assert.equal(station.workElapsed.textContent,'已等 2:05');
      doc.media.change(true);assert.equal(scene.work.timer,null);advance(5000);
      assert.equal(station.workElapsed.textContent,'已等 2:05');
      scene.update({...base,generated_at:new Date(epoch+10000).toISOString()});
      assert.equal(station.workElapsed.textContent,'已等 2:10','Reduced motion still gets static truthful text');
      assert.equal(scene.work.timer,null);doc.media.change(false);assert.notEqual(scene.work.timer,null);
      scene.canvas.style.setProperty('visibility','hidden');scene.work.sync();assert.equal(scene.work.timer,null);
      scene.canvas.style.setProperty('visibility','visible');scene.work.sync();assert.notEqual(scene.work.timer,null);
    """)


def test_work_caption_rotates_without_business_events_or_replaying_history():
    scene_check(CLOCK + r"""
      const captions=[];scene.onCaption=entry=>{if(entry)captions.push(entry);};
      scene.update(base);advance(7500);
      assert.ok(captions.some(entry=>entry.work&&entry.text.includes('未知会话 回测中')&&entry.text.includes('已等')));
      advance(7500);assert.ok(captions.some(entry=>entry.work&&entry.text.includes('1 批回测进行中')));
      assert.ok(captions.filter(entry=>entry.work).every(entry=>entry.seq===undefined));
      const count=captions.length;scene.narrative.active={};advance(7500);assert.equal(captions.length,count);
      scene.narrative.active=null;
      scene.update({...base,pending_sims:[],sessions:[]});
      assert.equal(captions.at(-1).text,'');assert.equal(scene.lastSeq,0);
    """)


def test_work_spider_patrol_is_sparse_and_has_no_frames_between_short_walks():
    scene_check(CLOCK + r"""
      scene.update(base);const origin={...scene.spider.positionSurface.positionAt(now)};
      advance(19500);assert.equal(doc.frames.size,0);assert.equal(scene.narrative.workAction,null);
      // Quiet time can advance coarsely; finite motion samples real display frames.
      advance(1000,20);assert.equal(scene.narrative.workAction.kind,'patrol');assert.ok(doc.frames.size>0);
      advance(2600,20);assert.equal(scene.narrative.workAction,null);assert.equal(doc.frames.size,0);
      assert.ok(Math.hypot(scene.spider.state.x-origin.x,scene.spider.state.y-origin.y)<.001);
      scene.update({...base,sessions:[],pending_sims:[]});advance(20000);assert.equal(doc.frames.size,0);
    """)


def test_old_live_snapshot_does_not_set_the_waiting_clock_back():
    scene_check(CLOCK + r"""
      scene.update({...base,generated_at:new Date(epoch-60000).toISOString()});
      assert.equal(scene.stations[0].workElapsed.textContent,'已等 2:00');
      scene.update({...base,mode:'demo'});advance(3000);
      assert.equal(scene.stations[0].workElapsed.textContent,'已等 2:03');
    """)


def test_work_observer_pauses_offscreen_and_skips_hidden_stations():
    scene_check(CLOCK + r"""
      scene.work.destroy();let notify;const watched=new Set();
      doc.defaultView.IntersectionObserver=class{
        constructor(callback){notify=callback;}
        observe(target){watched.add(target);}unobserve(target){watched.delete(target);}
        disconnect(){watched.clear();}
      };
      const {WorkLoop}=await import('./SpiderPanel/web/work.js');scene.work=new WorkLoop(scene);
      scene.work.clock=()=>epoch/1000+(now-100)/1000;
      scene.update(base);const station=scene.stations[0];
      notify([{target:station.miniSurface.host,isIntersecting:false}]);
      const before=station.workElapsed.textContent;advance(2000);assert.equal(station.workElapsed.textContent,before);
      notify([{target:scene.canvas,isIntersecting:false}]);assert.equal(scene.work.timer,null);
      notify([{target:scene.canvas,isIntersecting:true},{target:station.miniSurface.host,isIntersecting:true}]);
      assert.notEqual(scene.work.timer,null);assert.equal(station.workElapsed.textContent,'已等 2:02');
      scene.destroy();assert.equal(watched.size,0);
    """)


def test_shared_overflow_workstation_includes_pending_from_its_real_sessions():
    scene_check(CLOCK + r"""
      scene.update({...base,sessions:Array.from({length:8},(_,i)=>session(i)),
        pending_sims:[{sim:'overflow',pid:7,n:8,since:new Date(epoch-60000).toISOString()}]});
      const station=scene.sessionNodes.get('__aggregate__').station;
      assert.equal(station.workElapsed.textContent,'已等 1:00');
      assert.equal(station.panels.simulating.getAttribute('display'),'inline');
      assert.equal(Number(station.progress.getAttribute('width')),14.4);
      scene.update({...base,pending_sims:[],sessions:Array.from({length:8},(_,i)=>session(i,{phase:'reading'}))});
      assert.equal(station.workElapsed.getAttribute('display'),'none');
      assert.equal(station.chart.getAttribute('display'),'inline');
    """)


def test_quiet_work_keeps_static_background_and_layer_budget_unchanged():
    scene_check(CLOCK + r"""
      scene.update(base);let writes=0;
      for(const el of [scene.svg,...scene.svg.querySelectorAll('*')]){
        const set=el.setAttribute.bind(el);el.setAttribute=(key,value)=>{writes++;set(key,value);};
      }
      const count=descendants(scene.canvas),targets=scene.work.targets.size;
      advance(75000);scene.checkActivity();
      assert.equal(scene.environmentIdle,true);assert.equal(scene.work.active,true);
      assert.notEqual(scene.work.timer,null);assert.equal(scene.ambient.timer,null);
      assert.equal(scene.stations[0].workElapsed.textContent,'已等 3:15');
      assert.equal(writes,0,'Low-frequency work never writes the large static SVG');
      assert.equal(descendants(scene.canvas),count);assert.equal(scene.work.targets.size,targets);
      assert.equal(scene.layers.promotions.size,0);assert.equal(doc.frames.size,0);
    """)


def test_work_caption_is_transient_and_real_event_captions_keep_their_history():
    from test_frontend import dashboard_check

    dashboard_check(r"""
      app.renderCaption({seq:1,kind:'sim_done',text:'回测完成'});
      app.renderCaption({work:true,kind:'work',text:'会话 1 回测中 · 已等 4:12'});
      assert.equal(app.captions.length,1);assert.equal(app.captions[0].seq,1);
      assert.equal(app.captionTexts[0].textContent,'会话 1 回测中 · 已等 4:12');
      assert.ok(app.captionNodes[0].className.includes('caption-static'));
      app.renderCaption({seq:2,kind:'candidate',text:'候选到达'});
      assert.equal(app.captionTexts[0].textContent,'候选到达');assert.equal(app.captions.length,2);
      app.renderCaption({work:true,kind:'work',text:'2 批回测进行中'});
      app.renderCaption({work:true,text:''});
      assert.equal(app.captionTexts[0].textContent,'候选到达');
      assert.deepEqual(app.captions.map(entry=>entry.seq),[2,1]);
    """)
