"""Quiet work writes on one aligned second, including the header clock."""

from test_frontend import dashboard_check
from test_scene_r1 import scene_check
from test_work_mode import CLOCK
from test_panel_perf import COUNT_WRITES
from test_frontend import run_js, WEB
import json


def test_work_callbacks_and_typing_are_batched_once_per_second():
    scene_check(CLOCK + r"""
      const fired=[],setTimeout=scene.win.setTimeout;
      scene.win.setTimeout=(callback,delay)=>setTimeout(()=>{fired.push(now);callback();},delay);
      scene.update({...base,sessions:[session(0),session(1,{phase:'thinking'})]});
      const hand=scene.sessionNodes.get('0').workHands[0];let writes=0;
      const set=hand.setAttribute.bind(hand);hand.setAttribute=(key,value)=>{if(key==='transform')writes++;set(key,value);};
      advance(10000);
      assert.equal(fired.length,10,'One callback must batch all quiet work each second');
      assert.equal(writes,10,'Typing alternates once per second');
      const seconds=new Map();
      for(const at of fired){const second=Math.floor((at-100)/1000);seconds.set(second,(seconds.get(second)||0)+1);}
      assert.ok([...seconds.values()].every(count=>count<=1));
      assert.equal(doc.frames.size,0);
    """)


def test_header_and_work_share_the_same_aligned_callback():
    dashboard_check(r"""
      const scene=app.scene,clocks=[],hands=[],fired=[];
      const realClock=app.tickClock.bind(app);app.tickClock=()=>{clocks.push(now);realClock();};
      const setTimeout=doc.defaultView.setTimeout;
      doc.defaultView.setTimeout=(callback,delay)=>setTimeout(()=>{fired.push(now);callback();},delay);
      const epoch=Date.parse('2026-10-16T12:00:00+08:00');
      scene.work.clock=()=>epoch/1000+(now-100)/1000;
      app.render({day:'2026-10-16',mode:'live',sessions:[{pid:1,phase:'thinking'}],events:[]});
      const hand=scene.sessionNodes.get('1').workHands[0],set=hand.setAttribute.bind(hand);
      hand.setAttribute=(key,value)=>{if(key==='transform')hands.push(now);set(key,value);};
      clocks.length=0;
      for(let i=0;i<500;i++){now+=10;doc.sampleAnimations();}
      assert.equal(hands.length,5);assert.deepEqual(clocks,hands);
      assert.equal(new Set(fired).size,fired.length,'Clock and work cannot wake separate callbacks');
      assert.ok(fired.length<=5);
    """, setup="let now=100;doc.defaultView.performance.now=()=>now;\n")


def test_low_frequency_updates_skip_occluded_workstations_and_open_drawers():
    scene_check(CLOCK + r"""
      scene.work.destroy();let notify;
      doc.defaultView.IntersectionObserver=class{
        constructor(callback){notify=callback;}observe(){}unobserve(){}disconnect(){}
      };
      const {WorkLoop}=await import('./SpiderPanel/web/work.js');scene.work=new WorkLoop(scene);
      scene.work.clock=()=>epoch/1000+(now-100)/1000;
      scene.update({...base,sessions:[session(0,{phase:'thinking'}),session(1,{phase:'simulating'})],
        pending_sims:[{sim:'batch',pid:1,n:8,since:new Date(epoch-120000).toISOString()}]});
      const entry=scene.sessionNodes.get('0');
      notify([entry.surface.host,entry.overlaySurface.host,entry.station.miniSurface.host].map(target=>({target,isIntersecting:false})));
      const bubble=entry.expr.textContent,monitor=entry.station.thinkingElapsed.textContent;
      let writes=0;
      for(const root of [entry.g,entry.overlay,entry.station.panels.thinking])for(const node of [root,...root.querySelectorAll('*')]){
        const set=node.setAttribute.bind(node);node.setAttribute=(key,value)=>{writes++;set(key,value);};
      }
      advance(3000);assert.equal(writes,0);assert.equal(entry.expr.textContent,bubble);assert.equal(entry.station.thinkingElapsed.textContent,monitor);
      doc.body.classList.add('drawer-open');scene.work.sync();assert.equal(scene.work.timer,null);
      const before=scene.stations[1].workElapsed.textContent;advance(4000);assert.equal(scene.stations[1].workElapsed.textContent,before);
      doc.body.classList.remove('drawer-open');scene.work.sync();assert.notEqual(scene.work.timer,null);
    """)


def test_stepped_work_effects_write_only_in_the_shared_second_batch():
    # Radar, beam and note writing cannot introduce native completion callbacks.
    setup = "let now=100;doc.defaultView.performance.now=()=>now;\n" + COUNT_WRITES.replace(
        "writes.push({node,", "writes.push({at:now,node,")
    dashboard_check(r"""
      app.render({day:'2026-10-16',mode:'live',sessions:[{pid:1,phase:'prod',inflight:{alpha:'a'}},
        {pid:2,phase:'saving'}, {pid:3,phase:'thinking'}, {pid:4,phase:'simulating'}],
        alphas:[{id:'a',status:'done'}],pending_sims:[{sim:'batch',pid:4,n:8,since:'2026-10-16T11:59:00+08:00',progress:.5}],events:[]});
      writes.length=0;
      for(let i=0;i<500;i++){now+=10;doc.sampleAnimations();}
      const times=[...new Set(writes.map(write=>write.at))];
      assert.ok(times.length>0);
      assert.ok(times.every(at=>(at-100)%1000===0),`Unexpected quiet-work DOM batches: ${times}`);
      assert.ok(!app.scene.work.prodPulse.animation);assert.equal(doc.animations.size,0);
    """, setup=setup)


def test_quiet_radar_waiting_and_writing_do_not_start_native_animations():
    scene_check(CLOCK + r"""
      scene.update({...base,alphas:[{id:'a',status:'eval_passed'}],sessions:[session(0),
        session(1,{phase:'prod',inflight:{alpha:'a'}}),session(2,{phase:'saving'}),
        session(3,{phase:'thinking'})]});
      const pulseOpacities=new Set();let turns=0;
      const dish=scene.radarDishSurface,move=dish.move;
      dish.move=(...args)=>{turns++;return move(...args);};
      // Stop before the earliest permitted patrol. Sampling between ticks
      // catches a chained native animation, not just its end-of-second state.
      for(let i=0;i<1140;i++){
        now+=1000/60;doc.sampleAnimations();
        assert.equal(doc.animations.size,0,'Quiet work must step, not restart WAAPI each second');
        assert.equal(doc.frames.size,0);
        if(scene.work.prodPulse)pulseOpacities.add(scene.work.prodPulse.motion.style.getPropertyValue('opacity'));
      }
      assert.ok(turns>0,'The dish must still aim at the real alpha');
      assert.ok(pulseOpacities.size>=3,'The beam must still show a visible three-step pulse');
      assert.equal(scene.work.savePreviews.size,1);
      assert.equal(scene.layers.promotions.size,0,'Stepped work needs no compositor leases');
    """)


def test_inspection_beam_steps_on_the_shared_clock_without_a_native_fade():
    scene_check(CLOCK + r"""
      scene.update({...base,alphas:[{id:'a',status:'done',sim:'batch'}],pending_sims:[],
        sessions:[session(0,{phase:'evaluating',inflight:{sim:'batch'}})]});
      advance(1000);
      assert.equal(scene.narrative.workAction?.kind,'inspection');
      // Arrival may finish between second ticks; the low-frequency beam itself
      // is rendered in the next shared batch and never owns a native timeline.
      for(let i=0;!scene.work.inspectionBeam&&i<500;i++)advance(20);
      assert.ok(scene.work.inspectionBeam);
      const beam=scene.work.inspectionBeam,seen=new Set();
      for(let i=0;i<180;i++){
        advance(1000/60);
        assert.ok(!beam.animation,'The inspection beam must not own a native animation');
        assert.ok(![...doc.animations].some(animation=>animation.effect.target===beam.motion));
        seen.add(beam.motion.style.getPropertyValue('opacity'));
      }
      assert.ok(seen.size>=2,'Inspection remains visible as a low-frequency pulse');
    """)


def test_quiet_work_native_travel_keeps_its_promotion_until_it_finishes():
    scene_check(CLOCK + r"""
      scene.update({...base,alphas:[{id:'a',status:'done',sim:'batch'}],sessions:[session(0),
        session(1,{phase:'prod',inflight:{alpha:'a'}}),session(2,{phase:'saving'})]});
      let nativeFrames=0,quietFrames=0;
      for(let i=0;i<4200;i++){
        now+=1000/60;doc.sampleAnimations();
        for(const [id,callback]of [...doc.frames]){doc.frames.delete(id);callback(now);}
        const running=[...doc.animations].filter(animation=>animation.playState==='running');
        if(running.length)nativeFrames++;else quietFrames++;
        for(const animation of running){
          const target=animation.effect.target;
          assert.ok(scene.layers.promotions.has(target),'A quiet-work animation cannot lose its compositor lease');
          assert.ok(/transform|opacity/.test(target.style.getPropertyValue('will-change')));
          const host=target.classList.contains('scene-sprite')?target:target.parentNode;
          assert.ok(['spider','spider-silk'].includes(host.getAttribute('data-sprite')),
            `Unexpected quiet-work timeline: ${host.getAttribute('data-sprite')}`);
        }
        assert.ok(scene.layers.promotions.size<=22);
      }
      assert.ok(nativeFrames>60,'Exercise actual finite patrols');
      assert.ok(quietFrames>3000,'Finite patrols must leave long, genuinely quiet gaps');
    """)


def test_subscribers_join_one_wall_second_clock_without_a_phase_shift_or_catchup():
    run_js("import assert from 'node:assert/strict';\n"
           f"import {{SecondClock}} from {json.dumps((WEB/'second-clock.js').as_uri())};\n" + r"""
      let now=237,id=0;const timers=new Map(),fired=[],a=[],b=[];
      const win={performance:{timeOrigin:0,now:()=>now},
        setTimeout(fn,delay){timers.set(++id,{at:now+delay,fn});return id;},clearTimeout(id){timers.delete(id);}};
      const clock=new SecondClock(win),offA=clock.subscribe(()=>a.push(now));
      now=631;const offB=clock.subscribe(()=>b.push(now));
      assert.equal(timers.size,1);
      const advance=until=>{while(true){const due=[...timers].sort((a,b)=>a[1].at-b[1].at)[0];
        if(!due||due[1].at>until)break;now=due[1].at;timers.delete(due[0]);fired.push(now);due[1].fn();}now=until;};
      advance(5100);assert.deepEqual(a,[1000,2000,3000,4000,5000]);assert.deepEqual(b,a);
      offA();offB();assert.equal(timers.size,0);advance(10000);assert.equal(fired.length,5);
      clock.destroy();
    """)


def test_fractional_browser_time_origin_cannot_produce_two_adjacent_timer_callbacks():
    run_js("import assert from 'node:assert/strict';\n"
           f"import {{SecondClock}} from {json.dumps((WEB/'second-clock.js').as_uri())};\n" + r"""
      let now=237.2,id=0;const timers=new Map(),fired=[];
      const win={performance:{timeOrigin:.3,now:()=>now},
        // Browser timers accept integer milliseconds. Truncating a fractional
        // remainder used to wake just before, then again after, each second.
        setTimeout(fn,delay){timers.set(++id,{at:now+Math.floor(delay),fn});return id;},clearTimeout(id){timers.delete(id);}};
      const clock=new SecondClock(win);clock.subscribe(()=>fired.push(now+.3));
      while(true){const next=[...timers].sort((a,b)=>a[1].at-b[1].at)[0];
        if(next[1].at>2001)break;now=next[1].at;timers.delete(next[0]);next[1].fn();}
      assert.equal(fired.length,2);assert.ok(fired[0]>=1000&&fired[0]<1002);
      assert.ok(fired[1]-fired[0]>=999);clock.destroy();
    """)
