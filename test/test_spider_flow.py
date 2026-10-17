"""Capped SVG gait, physical pauses and distance-based locomotion."""
import json
from test_frontend import WEB
from test_scene_r1 import scene_check
from test_spider import spider_check
from test_web_narrative import CLOCK
import pytest


def test_candidate_preview_and_its_private_test_are_removed():
    assert not (WEB / 'preview').exists()
    assert not (WEB.parent / 'test' / 'test_spider_preview.py').exists()


def test_walking_phase_follows_distance_not_the_animation_clock():
    spider_check(r"""
      let now=100;doc.defaultView.performance.now=()=>now;
      const run=times=>{
        spider.pose({x:100,y:120,phase:0});
        const phases=[];
        for(let i=0;i<times.length;i++){
          now+=times[i];spider.pose({x:100+(i+1)*3,y:120,walk:1,gait:true,smooth:true});
          phases.push(spider.state.phase);
        }
        return phases;
      };
      const fast=run([16,17,16,17,16,17]),slow=run([40,80,20,60,50,30]);
      assert.ok(fast[5]>fast[0]);fast.forEach((phase,i)=>near(phase,slow[i]));
      const before=spider.state.phase;
      now+=500;spider.pose({walk:0,gait:true,smooth:true});near(spider.state.phase,before);
    """)


def test_live_walking_leg_rate_matches_the_configured_cap():
    scene_check(f"const {{SPIDER_LEG_HZ}}=await import({json.dumps((WEB/'animation-rules.js').as_uri())});\n" + r"""
      let now=100;doc.defaultView.performance.now=()=>now;
      const base={day:'2026-10-16',alphas:[{id:'walk',status:'done'}],events:[]};scene.update(base);
      scene.update({...base,events:[{seq:1,kind:'sim_done',n:1,alphas:['walk']}]});
      let previous=scene.spider.positionSurface.positionAt(now),d=scene.spider.legs[2].path.getAttribute('d');
      let moving=0,changed=0;
      for(let i=0;i<240;i++){
        now+=1000/60;doc.sampleAnimations();
        const frames=[...doc.frames];doc.frames.clear();for(const [,fn]of frames)fn(now);
        const position=scene.spider.positionSurface.positionAt(now),next=scene.spider.legs[2].path.getAttribute('d');
        if(Math.hypot(position.x-previous.x,position.y-previous.y)>5/60){moving++;if(next!==d)changed++;}
        previous=position;d=next;
      }
      assert.ok(moving>30,'Exercise a real native crawl');
      const rate=changed/moving*60;
      assert.ok(rate>=SPIDER_LEG_HZ*.9&&rate<=SPIDER_LEG_HZ*1.1,`Moving leg updates: ${rate}/s`);
    """)


def test_stopping_blends_back_to_stance_over_three_hundred_milliseconds():
    spider_check(r"""
      let now=100;doc.defaultView.performance.now=()=>now;
      spider.pose({x:103,y:120,walk:1,gait:true,smooth:true});
      now+=100;spider.pose({x:115,y:120,walk:1,gait:true,smooth:true});
      now+=16;spider.pose({walk:0,gait:true,smooth:true});
      assert.ok(spider.state.walk>.9,'Stopping cannot snap to a zero-strength stance');
      for(let i=0;i<9;i++){now+=1000/60;spider.pose({walk:0,gait:true,smooth:true});}
      assert.ok(spider.state.walk>.2&&spider.state.walk<.8);
      for(let i=0;i<12;i++){now+=1000/60;spider.pose({walk:0,gait:true,smooth:true});}
      near(spider.state.walk,0);assert.equal(doc.frames.size,0);
    """)


def test_distance_gait_keeps_four_support_feet_planted_in_alternating_groups():
    spider_check(r"""
      const planted=[2,0,5,7],swing=[1,3,4,6];
      const run=phase=>{
        spider.pose({x:100,y:120,angle:Math.PI/2,phase,walk:1});
        const first=spider.legs.map(leg=>100-spider.scale*leg.points[3].y);
        for(let step=1;step<=5;step++){
          spider.pose({x:100+step*3,y:120,angle:Math.PI/2,walk:1,gait:true});
          const support=phase===0?planted:swing;
          for(const i of support)near(100+step*3-spider.scale*spider.legs[i].points[3].y,first[i]);
        }
      };
      run(0);run(Math.PI);
    """)


def test_explicit_route_distance_drives_gait_even_when_a_frame_crosses_a_turn():
    spider_check(r"""
      spider.pose({x:100,y:120,phase:0,walk:1});
      spider.pose({x:100,y:120,walk:1,gait:true,travelDistance:12});const p=spider.state.phase;
      assert.ok(p>0,'Returning to the same pixel can still traverse two silk segments');
      spider.pose({x:100,y:120,walk:1,gait:true,travelDistance:12});near(spider.state.phase,p*2);
      spider.pose({x:110,y:120,walk:1,gait:true,travelDistance:0});near(spider.state.phase,p*2);
    """)


def test_cancelling_native_travel_cannot_keep_advancing_the_walk_phase():
    scene_check(CLOCK + r"""
      const base={day:'2026-10-16',alphas:[{id:'cancel',status:'done'}],events:[]};scene.update(base);
      scene.update({...base,events:[{seq:1,kind:'sim_done',n:1,alphas:['cancel']}]});
      advance(200);scene.spider.positionSurface.travelAnimation.cancel();
      advance(20);const phase=scene.spider.state.phase,position={x:scene.spider.state.x,y:scene.spider.state.y};
      advance(100);
      assert.ok(Math.abs(scene.spider.state.phase-phase)<1e-8);
      assert.equal(scene.spider.state.x,position.x);assert.equal(scene.spider.state.y,position.y);
    """)


@pytest.mark.parametrize('merge', [False, True])
def test_stopping_between_frames_consumes_the_last_native_arc_at_a_hub(merge):
    scene_check(CLOCK + f"const merge={str(merge).lower()};\n" + r"""
      scene.update({day:'2026-10-16',alphas:[],events:[]});
      scene.spider.pose({x:770,y:163,walk:0,phase:0});
      const director=scene.narrative,job={kind:'sim_done',ids:[],surfaces:[]};director.active=job;
      director._beginBody(job,{x:770,y:158},now);
      const travel=job.travel,hub=travel.plan.frames.find(frame=>Math.abs(frame.x-595)<1e-8&&Math.abs(frame.y-158)<1e-8);
      now=travel.start+hub.offset*travel.plan.duration-10;director._bodyPose(job,now);
      const phase=scene.spider.state.phase,old=travel.distanceAt(now);
      now+=20;const expected=(travel.distanceAt(now)-old)/(12*1.4/.5)*2*Math.PI;
      if(merge)director.enqueue(Array.from({length:20},(_,i)=>({seq:i+1,kind:'eval_fail'})));
      else director.clear();
      assert.ok(Math.abs(scene.spider.state.phase-phase-expected)<1e-7,'A stop must consume the exact arc since the last display frame');
    """)


def test_a_queued_action_prepares_its_target_without_frozen_waits():
    scene_check(r"""
      let now=100;doc.defaultView.performance.now=()=>now;
      const rows=Array.from({length:5},(_,i)=>({id:`flow${i}`,status:'candidate'}));
      const base={day:'2026-10-16',alphas:rows,review:rows,events:[]};scene.update(base);
      scene.update({...base,events:[
        {seq:1,kind:'eval_pass',alphas:['flow0']},{seq:2,kind:'prod_ok',alphas:['flow1']},
        {seq:3,kind:'candidate',alphas:['flow2']},{seq:4,kind:'eval_fail',alphas:['flow3']}]});
      let frozen=0,longest=0,previous='',bypasses=0,last=null;
      for(let i=0;i<1500;i++){
        now+=1000/60;doc.sampleAnimations();
        const callbacks=[...doc.frames];doc.frames.clear();for(const [,fn]of callbacks)fn(now);
        const job=scene.narrative.active;
        const signature=scene.spider.root.getAttribute('transform')+'|'+scene.spider.body.getAttribute('transform')+'|'+scene.spider.legs.map(leg=>leg.path.getAttribute('d')).join('|');
        if(job&&scene.narrative.queue.length){frozen=signature===previous?frozen+1000/60:0;longest=Math.max(longest,frozen);}
        else frozen=0;
        if(last&&job&&last!==job&&last.kind!=='prod_ok'){
          if(Math.hypot(scene.spider.state.x-595,scene.spider.state.y-158)>10)bypasses++;
        }
        previous=signature;last=job;
      }
      assert.ok(bypasses>0,'Queued work must continue from the working site rather than always returning home');
      assert.ok(longest<1000,`The queue froze for ${longest}ms`);
      assert.equal(scene.narrative.working,false);assert.equal(doc.frames.size,0);
    """)


def test_waiting_micro_actions_share_the_low_frequency_clock_and_pause_when_quiet():
    scene_check(CLOCK + r"""
      const base={day:'2026-10-16',alphas:[{id:'watch',status:'prod_ok'}],events:[]};scene.update(base);
      scene.update({...base,events:[{seq:1,kind:'prod_ok',alphas:['watch']}]});
      const controls=scene.spider.attentionControls;
      assert.equal(controls.length,3);assert.ok(controls.every(control=>control.active));
      assert.equal(doc.frames.size,0,'Waiting details use the existing shared 4Hz timer');
      const seen=new Set();advance(2500,()=>seen.add(scene.spider.eyes.getAttribute('transform')));
      assert.ok(seen.size>1,'Eyes must keep looking while the body waits');
      now=scene.lastEventAt+15001;scene.checkActivity(now);
      assert.ok(controls.every(control=>!control.active));assert.equal(scene.ambient.timer,null);
      const signature=()=>controls.map(control=>control.node.getAttribute('transform')).join('|');
      const still=signature();advance(1000);assert.equal(signature(),still);assert.equal(doc.frames.size,0);
      doc.hidden=true;doc.dispatch('visibilitychange');assert.equal(scene.ambient.timer,null);
      doc.media.change(true);assert.equal(scene.ambient.timer,null);
    """)


@pytest.mark.parametrize('continuing', [False, True])
def test_return_handoffs_preserve_speed_or_finish_decelerating(continuing):
    scene_check(CLOCK + f"const continuing={str(continuing).lower()};\n" + r"""
      const rows=Array.from({length:60},(_,i)=>({id:`handoff${i}`,status:'done'}));
      const base={day:'2026-10-16',alphas:rows,events:[]};scene.update(base);
      scene.update({...base,events:[{seq:1,kind:'sim_done',n:1,alphas:[rows[0].id]}]});
      until(()=>scene.narrative.active?.stage==='return');advance(250);
      const job=scene.narrative.active,body=scene.spider.positionSurface;
      const velocity=job.travel.plan.velocityAt(now-job.travel.start),speed=Math.hypot(velocity.x,velocity.y);
      assert.ok(speed>40);
      const candidates=rows.slice().sort((a,b)=>scene.web.position(a.id).x-scene.web.position(b.id).x);
      const target=continuing?candidates.at(-1):candidates[0];
      scene.update({...base,events:[{seq:2,kind:'eval_fail',alphas:[target.id]}]});
      const before=body.positionAt(now);advance(20);
      if(continuing){
        const next=scene.narrative.active;assert.notEqual(next,job);
        const v=next.travel.plan.velocityAt(0);
        assert.ok(Math.hypot(v.x,v.y)>speed*.7,'A forward handoff cannot restart from zero');
        assert.ok(Math.hypot(body.positionAt(now).x-before.x,body.positionAt(now).y-before.y)<=12);
      }else assert.ok(scene.narrative.active===job,'An opposite target must let the current crawl decelerate');
    """)
