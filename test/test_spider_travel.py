"""Silk travel follows the same bounded native keyframes as the leg sampler."""

import json
from pathlib import Path

from test_frontend import WEB, run_js


def travel_check(source):
    run_js("import assert from 'node:assert/strict';\n"
           f"import {{documentFromHTML}} from {json.dumps((Path(__file__).parent/'frontend_dom.mjs').as_uri())};\n"
           f"import {{SceneLayers}} from {json.dumps((WEB/'layers.js').as_uri())};\n"
           f"import {{SCREEN_CONTENT,WEB_CENTER}} from {json.dumps((WEB/'geometry.js').as_uri())};\n"
           f"const motion=await import({json.dumps((WEB/'motion.js').as_uri())}).catch(()=>({{}}));\n"
           "assert.equal(typeof motion.planSilkTravel,'function','A shared silk travel planner is required');\n"
           "const {planSilkTravel}=motion;\n"
           "const doc=documentFromHTML('<html><body><svg id=\"scene\"></svg></body></html>');\n"
           "let now=100;doc.defaultView.performance.now=()=>now;\n"
           "const bounds=SCREEN_CONTENT;\n"
           "const confine=p=>({x:Math.max(420,Math.min(770,p.x)),y:Math.max(158,Math.min(163,p.y))});\n"
           "const layers=new SceneLayers(doc.getElementById('scene'),'travel',bounds);\n"
           "const near=(a,b)=>assert.ok(Math.abs(a-b)<1e-7,`${a} != ${b}`);\n"
           "const same=(a,b)=>{near(a.x,b.x);near(a.y,b.y);};\n"
           "try {\n" + source + "\n} finally {layers.destroy();}\n")


def test_routes_use_confined_vertices_and_exact_piecewise_native_sampling():
    # Omitting the hub frame cuts across a spoke; easing the sampler separately
    # makes legs disagree with the native transform between uploaded frames.
    travel_check("""
      const plan=planSilkTravel({x:770,y:163},{x:-100,y:-50},{bounds,confine});
      same(plan.frames[0],{x:770,y:163});same(plan.frames.at(-1),{x:420,y:158});
      assert.ok(plan.frames.some(p=>Math.abs(p.x-595)<1e-8&&Math.abs(p.y-158)<1e-8),'Changing spokes visits the safe hub');
      assert.ok(plan.frames.length>=48&&plan.frames.length<=64);
      assert.equal(plan.frames[0].offset,0);assert.equal(plan.frames.at(-1).offset,1);
      for(const p of plan.frames){same(p,confine(p));}
      for(let i=1;i<plan.frames.length;i++){
        const a=plan.frames[i-1],b=plan.frames[i];assert.ok(b.offset>a.offset);
        for(const t of [.17,.5,.83]){
          const elapsed=(a.offset+(b.offset-a.offset)*t)*plan.duration;
          same(plan.sample(elapsed),{x:a.x+(b.x-a.x)*t,y:a.y+(b.y-a.y)*t});
        }
      }
      same(plan.sample(-100),{x:770,y:163});same(plan.sample(plan.duration+100),{x:420,y:158});
      const direct=planSilkTravel({x:650,y:158},{x:750,y:158},{bounds,confine});
      assert.ok(direct.frames.every(p=>p.x>=650&&p.y===158),'Same-ray travel never detours through the hub');
    """)


def test_arc_length_timing_caps_actual_velocity_and_60fps_displacement():
    # A fixed duration or uncorrected ease-in-out peak exceeds the speed cap.
    travel_check("""
      for(const maxSpeed of [undefined,80,240]){
        const cap=maxSpeed??(836-354)/3;
        const plan=planSilkTravel({x:420,y:158},{x:770,y:163},{bounds,confine,maxSpeed});
        for(let i=1;i<plan.frames.length;i++){
          const a=plan.frames[i-1],b=plan.frames[i],dt=(b.offset-a.offset)*plan.duration/1000;
          assert.ok(Math.hypot(b.x-a.x,b.y-a.y)/dt<=cap+1e-6,'Native linear segments obey maxSpeed');
        }
        let previous=plan.sample(0);
        for(let t=1000/60;t<=plan.duration+1000/60;t+=1000/60){
          const current=plan.sample(t),step=Math.hypot(current.x-previous.x,current.y-previous.y);
          assert.ok(step<=12&&step<=cap/60+1e-6);same(current,confine(current));previous=current;
        }
        const first=plan.frames[1],last=plan.frames.at(-2),middle=plan.frames[Math.floor(plan.frames.length/2)];
        const speed=(a,b)=>Math.hypot(b.x-a.x,b.y-a.y)/((b.offset-a.offset)*plan.duration/1000);
        assert.ok(speed(plan.frames[0],first)<cap*.2);assert.ok(speed(last,plan.frames.at(-1))<cap*.2);
        assert.ok(speed(middle,plan.frames[plan.frames.indexOf(middle)+1])>cap*.95);
      }
    """)


def test_restored_screen_boundary_routes_keep_exact_native_samples_and_velocity_caps():
    travel_check("""
      const safe=p=>({x:Math.max(bounds.left+66,Math.min(bounds.right-66,p.x)),
        y:Math.max(bounds.top+66,Math.min(bounds.bottom-66,p.y))});
      const corners=[{x:bounds.left,y:bounds.top},{x:bounds.right,y:bounds.top},
        {x:bounds.right,y:bounds.bottom},{x:bounds.left,y:bounds.bottom}];
      for(const from of corners)for(const to of corners){
        const plan=planSilkTravel(from,to,{bounds,confine:safe});
        same(plan.frames[0],safe(from));same(plan.frames.at(-1),safe(to));
        assert.ok(plan.frames.length<=64);
        let previous=plan.sample(0);
        for(let elapsed=1000/60;elapsed<=plan.duration+1000/60;elapsed+=1000/60){
          const current=plan.sample(elapsed);
          same(current,safe(current));
          assert.ok(Math.hypot(current.x-previous.x,current.y-previous.y)<=12,
            'A boundary route cannot jump between display frames');
          previous=current;
        }
        for(let i=1;i<plan.frames.length;i++){
          const a=plan.frames[i-1],b=plan.frames[i],dt=(b.offset-a.offset)*plan.duration/1000;
          assert.ok(Math.hypot(b.x-a.x,b.y-a.y)/dt<=(bounds.right-bounds.left)/3+1e-6);
        }
      }
    """)


def test_acceleration_uses_200ms_ramps_and_reduces_the_peak_for_short_travel():
    # Fractional-duration ramps make short approaches look like instant starts.
    travel_check("""
      const long=planSilkTravel({x:650,y:158},{x:750,y:158},{bounds,confine,maxSpeed:100});
      near(long.duration,1200);
      for(const elapsed of [200,long.duration-200]){
        assert.ok(long.frames.some(frame=>Math.abs(frame.offset*long.duration-elapsed)<1e-7),
          'Native keyframes include the exact acceleration/deceleration boundary');
      }
      same(long.sample(100),{x:652.5,y:158});same(long.sample(200),{x:660,y:158});
      same(long.sample(1000),{x:740,y:158});same(long.sample(1100),{x:747.5,y:158});
      const short=planSilkTravel({x:650,y:158},{x:660,y:158},{bounds,confine,maxSpeed:100});
      near(short.duration,400);
      assert.ok(short.frames.some(frame=>Math.abs(frame.offset*short.duration-200)<1e-7));
      same(short.sample(100),{x:651.25,y:158});same(short.sample(200),{x:655,y:158});
      same(short.sample(300),{x:658.75,y:158});
      const speeds=short.frames.slice(1).map((b,i)=>{
        const a=short.frames[i];return Math.hypot(b.x-a.x,b.y-a.y)/((b.offset-a.offset)*short.duration/1000);
      });
      const peak=Math.max(...speeds),first100=Math.hypot(short.sample(100).x-650,short.sample(100).y-158)/.1;
      assert.ok(peak>45&&peak<=50,'A short route lowers its peak below maxSpeed');
      assert.ok(first100<peak*.6,'The first 100ms remains visibly slower than the short-route peak');
    """)


def test_velocity_at_reports_the_actual_native_segment_and_stops_at_the_end():
    # Reading an analytic ramp derivative disagrees with linear native frames.
    travel_check("""
      const plan=planSilkTravel({x:420,y:158},{x:770,y:163},{bounds,confine,maxSpeed:100});
      assert.equal(typeof plan.velocityAt,'function');
      const before=JSON.stringify(plan.frames);
      for(let i=1;i<plan.frames.length;i++){
        const a=plan.frames[i-1],b=plan.frames[i],dt=(b.offset-a.offset)*plan.duration/1000;
        const velocity={x:(b.x-a.x)/dt,y:(b.y-a.y)/dt};
        for(const fraction of [.17,.5,.83]){
          const elapsed=(a.offset+(b.offset-a.offset)*fraction)*plan.duration;
          same(plan.velocityAt(elapsed),velocity);
          const delta=.001,left=plan.sample(elapsed-delta),right=plan.sample(elapsed+delta);
          near((right.x-left.x)/(2*delta/1000),velocity.x);
          near((right.y-left.y)/(2*delta/1000),velocity.y);
        }
      }
      same(plan.velocityAt(0),plan.velocityAt(plan.frames[1].offset*plan.duration/2));
      same(plan.velocityAt(-1),{x:0,y:0});same(plan.velocityAt(plan.duration),{x:0,y:0});
      same(plan.velocityAt(plan.duration+100),{x:0,y:0});
      same(plan.sample(0),{x:420,y:158});assert.equal(JSON.stringify(plan.frames),before,'Sampling stays pure');
    """)


def test_boundary_speeds_are_clamped_and_survive_rebasing():
    travel_check("""
      const options={bounds,confine,maxSpeed:100,startSpeed:40,endSpeed:20};
      const plan=planSilkTravel({x:650,y:158},{x:750,y:158},options);
      near(plan.duration,1140);same(plan.sample(200),{x:664,y:158});
      same(plan.velocityAt(plan.duration),{x:20,y:0});same(plan.velocityAt(plan.duration+10),{x:20,y:0});
      const rebased=motion.rebaseSilkTravel(plan,{x:700,y:158});
      near(rebased.duration,640);same(rebased.sample(200),{x:714,y:158});
      same(rebased.velocityAt(rebased.duration),{x:20,y:0});
      const clamped=planSilkTravel({x:650,y:158},{x:750,y:158},{...options,startSpeed:500,endSpeed:-50});
      near(clamped.duration,1100);same(clamped.sample(100),{x:660,y:158});
      same(clamped.velocityAt(0),{x:100,y:0});same(clamped.velocityAt(clamped.duration),{x:0,y:0});
      const fastEnd=planSilkTravel({x:650,y:158},{x:750,y:158},{...options,startSpeed:0,endSpeed:500});
      near(fastEnd.duration,1100);same(fastEnd.velocityAt(fastEnd.duration),{x:100,y:0});
      const bent=planSilkTravel({x:420,y:158},{x:770,y:163},options),finalLength=Math.hypot(175,5);
      same(bent.velocityAt(bent.duration),{x:175/finalLength*20,y:5/finalLength*20});
      const tiny=motion.rebaseSilkTravel(plan,{x:749,y:158});
      assert.ok(tiny.duration>0&&Number.isFinite(tiny.duration));
      for(let i=1;i<tiny.frames.length;i++){
        const a=tiny.frames[i-1],b=tiny.frames[i],dt=(b.offset-a.offset)*tiny.duration/1000;
        assert.ok(Math.hypot(b.x-a.x,b.y-a.y)/dt<=100+1e-6);
      }
      same(tiny.sample(tiny.duration),{x:750,y:158});same(tiny.velocityAt(tiny.duration),{x:20,y:0});
      const still=planSilkTravel({x:650,y:158},{x:650,y:158},options);
      assert.equal(still.duration,0);assert.equal(still.frames.length,1);
      same(still.velocityAt(0),{x:0,y:0});same(still.velocityAt(100),{x:0,y:0});
    """)


def test_hub_frames_remain_exact_when_a_bend_falls_inside_either_ramp():
    travel_check("""
      for(const [from,to] of [
        [{x:590,y:158},{x:770,y:163}],
        [{x:420,y:158},{x:596,y:158.1}],
      ]){
        const plan=planSilkTravel(from,to,{bounds,confine,maxSpeed:100});
        const hub=plan.frames.find(frame=>Math.abs(frame.x-595)<1e-8&&Math.abs(frame.y-158)<1e-8);
        assert.ok(hub,'A ramp never cuts the corner between two silk spokes');
        const at=hub.offset*plan.duration;
        assert.ok(at<200||at>plan.duration-200);
        same(plan.sample(at),{x:595,y:158});
        for(const elapsed of [200,plan.duration-200]){
          assert.ok(plan.frames.some(frame=>Math.abs(frame.offset*plan.duration-elapsed)<1e-7));
        }
        for(let i=1;i<plan.frames.length;i++){
          const a=plan.frames[i-1],b=plan.frames[i],elapsed=(a.offset+b.offset)/2*plan.duration;
          const dt=(b.offset-a.offset)*plan.duration/1000;
          same(plan.sample(elapsed),{x:(a.x+b.x)/2,y:(a.y+b.y)/2});
          same(plan.velocityAt(elapsed),{x:(b.x-a.x)/dt,y:(b.y-a.y)/dt});
          assert.ok(Math.hypot(b.x-a.x,b.y-a.y)/dt<=100+1e-6);
        }
      }
    """)


def test_native_arc_length_is_independent_of_display_sampling_at_a_hub():
    travel_check("""
      const plan=planSilkTravel({x:770,y:163},{x:770,y:158},{bounds,confine});
      assert.equal(typeof plan.distanceAt,'function');
      const length=plan.frames.slice(1).reduce((n,b,i)=>n+Math.hypot(b.x-plan.frames[i].x,b.y-plan.frames[i].y),0);
      near(plan.distanceAt(-1),0);near(plan.distanceAt(plan.duration+10),length);
      for(const hz of [50,60,144]){
        let walked=0,previous=0;
        for(let t=1000/hz;t<plan.duration+1000/hz;t+=1000/hz){
          const current=plan.distanceAt(t);walked+=current-previous;previous=current;
        }
        near(walked,length);
      }
      for(let i=1;i<plan.frames.length;i++){
        const a=plan.frames[i-1],b=plan.frames[i],half=(a.offset+b.offset)/2*plan.duration;
        near(plan.distanceAt(half),(plan.distanceAt(a.offset*plan.duration)+plan.distanceAt(b.offset*plan.duration))/2);
      }
    """)


def test_sharp_hub_turns_decelerate_before_reversing_direction():
    travel_check("""
      const plan=planSilkTravel({x:770,y:163},{x:770,y:158},{bounds,confine,maxSpeed:100});
      const hub=plan.frames.find(frame=>Math.abs(frame.x-595)<1e-8&&Math.abs(frame.y-158)<1e-8);
      assert.ok(hub);const at=hub.offset*plan.duration;
      const speed=t=>{const v=plan.velocityAt(t);return Math.hypot(v.x,v.y);};
      assert.ok(speed(at-1)<10&&speed(at+1)<10,'A reversing body must slow down at the hub');
      assert.ok(speed(at-100)<60&&speed(at+100)<60);
      assert.ok(speed(at-250)>95&&speed(at+250)>95);
      assert.ok(plan.frames.length<=64);
    """)


def test_body_travel_animates_the_host_and_never_writes_transform_per_frame():
    travel_check(r"""
      const body=layers.surface({left:-66,top:-66,width:132,height:132},{parent:layers.webClip,local:true});
      body.move(420,158);
      const writes=[],set=body.host.style.setProperty.bind(body.host.style);
      body.host.style.setProperty=(key,value)=>{if(key==='transform')writes.push(value);set(key,value);};
      const plan=planSilkTravel(body.point,{x:770,y:163},{bounds,confine});
      const handle=body.travel(plan,{startTime:now});
      assert.equal(handle.start,100);assert.equal(handle.plan,plan);assert.equal(body.traveling,true);assert.equal(handle.done,false);
      const animation=[...doc.animations][0];assert.equal(animation.effect.target,body.host);
      const keys=animation.effect.getKeyframes();assert.equal(keys.length,plan.frames.length);
      keys.forEach((key,i)=>{
        const match=key.transform.match(/^translate\(([-+\deE.]+)px,([-+\deE.]+)px\)/);
        same({x:Number(match[1])+420,y:Number(match[2])+158},plan.frames[i]);
        assert.equal(key.offset,plan.frames[i].offset);
      });
      assert.equal(keys[0].transform,'translate(0px,0px) rotate(0deg) scale(1)');
      assert.equal(keys.at(-1).transform,'translate(350px,5px) rotate(0deg) scale(1)');
      assert.equal(keys.at(-1).offset,1);
      assert.ok(layers.promotions.has(body.host));assert.ok(!layers.promotions.has(body.motion));
      assert.equal(body.motion.style.getPropertyValue('will-change'),'auto');
      for(let t=0;t<plan.duration;t+=1000/60){
        now=100+t;same(handle.positionAt(now),plan.sample(t));same(body.positionAt(now),plan.sample(t));
        if(Math.floor(t/(1000/60))%2===0){const p=handle.positionAt(now);body.move(p.x,p.y);body.animate('');}
      }
      assert.equal(writes.length,0,'IK updates must not replace the compositor-owned host transform');
      now=100+plan.duration;doc.sampleAnimations();
      assert.equal(handle.done,true);assert.equal(body.traveling,false);same(body.point,{x:770,y:163});
      assert.equal(writes.length,1);assert.equal(doc.animations.size,0);assert.equal(layers.promotions.size,0);
      assert.equal(body.host.style.getPropertyValue('will-change'),'auto');
      assert.equal(body.positionAt(),body.point);
    """)


def test_explicit_start_clock_and_external_native_cancel_keep_position_continuous():
    travel_check("""
      const body=layers.surface({left:-66,top:-66,width:132,height:132},{parent:layers.webClip,local:true});
      body.move(420,158);
      const plan=planSilkTravel(body.point,{x:770,y:163},{bounds,confine});
      const handle=body.travel(plan,{startTime:50});assert.equal(handle.start,50);
      same(handle.positionAt(),plan.sample(50));
      const animation=[...doc.animations][0];near(animation.currentTime,50);
      now=100+plan.duration*.25;const current=handle.positionAt();
      animation.cancel();assert.equal(handle.done,true);assert.equal(body.traveling,false);same(body.point,current);
      assert.equal(body.host.style.getPropertyValue('transform'),`translate(${current.x-420}px,${current.y-158}px) rotate(0deg) scale(1)`);
      assert.equal(doc.animations.size,0);assert.equal(layers.promotions.size,0);
      const next=body.travel(planSilkTravel(current,{x:600,y:159},{bounds,confine}));
      now=next.start+next.plan.duration;assert.equal(next.done,true,'The completion getter uses the injected clock before a finish event');
      same(next.positionAt(),{x:600,y:159});
      body.stopTravel();same(body.point,{x:600,y:159});
      body.host.animate=undefined;
      const unavailable=body.travel(planSilkTravel(body.point,{x:770,y:163},{bounds,confine}));
      assert.equal(unavailable.done,true);same(body.point,{x:600,y:159});assert.equal(layers.promotions.size,0);
    """)


def test_cancel_commits_the_sample_and_stale_replacements_start_at_that_sample():
    travel_check("""
      const body=layers.surface({left:-66,top:-66,width:132,height:132},{parent:layers.webClip,local:true});
      body.move(420,158);
      const first=body.travel(planSilkTravel(body.point,{x:770,y:163},{bounds,confine}));
      now=100+first.plan.duration*.37;const current=first.positionAt(now);
      first.cancel();assert.equal(first.done,true);same(body.point,current);same(body.positionAt(now+1000),current);
      const transform=body.host.style.getPropertyValue('transform');
      const stale=planSilkTravel({x:420,y:158},{x:700,y:160},{bounds,confine,maxSpeed:90});
      const next=body.travel(stale);same(next.plan.frames[0],current);same(next.positionAt(now),current);
      assert.equal(body.host.style.getPropertyValue('transform'),transform,'Replacement has no first-frame teleport');
      now+=next.plan.duration*.2;const interrupted=next.positionAt(now);
      const replacement=body.travel(planSilkTravel({x:420,y:158},{x:450,y:160},{bounds,confine}));
      same(replacement.plan.frames[0],interrupted);assert.equal(next.done,true);assert.equal(doc.animations.size,1);
      now+=20;const stopped=replacement.positionAt(now);body.stopTravel();same(body.point,stopped);
      assert.equal(body.traveling,false);assert.equal(doc.animations.size,0);assert.equal(layers.promotions.size,0);
      const still=body.travel(planSilkTravel(body.point,body.point,{bounds,confine}));
      assert.equal(still.done,true);assert.equal(doc.animations.size,0,'A zero-distance plan starts no native animation');
    """)


def test_travel_uses_one_budget_slot_and_removal_releases_the_native_animation():
    travel_check("""
      const ambient=Array.from({length:25},()=>layers.surface({left:-2,top:-2,width:4,height:4},{local:true}));
      ambient.forEach(s=>s.animate('wq-avatar-floating wq-animated'));assert.equal(layers.promotions.size,22);
      const body=layers.surface({left:-66,top:-66,width:132,height:132},{parent:layers.webClip,local:true});
      body.move(420,158);body.animate('wq-spider-breathe wq-animated');
      body.travel(planSilkTravel(body.point,{x:770,y:163},{bounds,confine}));
      assert.equal(layers.promotions.size,22);assert.ok(layers.promotions.has(body.host));assert.ok(!layers.promotions.has(body.motion));
      body.animate('');body.stop();assert.equal(body.traveling,true);assert.ok(layers.promotions.has(body.host));
      body.remove();assert.equal(body.traveling,false);assert.equal(doc.animations.size,0);
      assert.ok(!layers.promotions.has(body.host));assert.ok(!layers.promotions.has(body.motion));
      assert.equal(layers.promotions.size,22,'Freed travel promotion resumes one ambient surface');
      const finite=Array.from({length:22},()=>layers.surface({left:-2,top:-2,width:4,height:4},{local:true}));
      finite.forEach(s=>s.play([{opacity:1},{opacity:0}],{duration:5000}));
      const blocked=layers.surface({left:-66,top:-66,width:132,height:132},{local:true});blocked.move(420,158);
      const noSlot=blocked.travel(planSilkTravel(blocked.point,{x:770,y:163},{bounds,confine}));
      assert.equal(noSlot.done,true);same(blocked.point,{x:420,y:158});assert.equal(layers.promotions.size,22);
      layers.destroy();assert.equal(layers.promotions.size,0);assert.equal(doc.animations.size,0);
    """)
