"""Sample composited body paths and capped local joint changes."""
import json
import pytest

from test_frontend import WEB
from test_spider import spider_check
from test_scene_r1 import scene_check


def test_smooth_joint_updates_limit_rotated_foot_offsets_without_changing_direct_pose():
    spider_check(r"""
      let now=100;doc.defaultView.performance.now=()=>now;
      const offsets=()=>spider.legs.map(leg=>{
        const p=leg.points[3],c=Math.cos(spider.state.angle),s=Math.sin(spider.state.angle);
        return {x:spider.scale*(p.x*c-p.y*s),y:spider.scale*(p.x*s+p.y*c)};
      });
      let previous=offsets(),moved=0;
      for(let i=0;i<200;i++){
        now+=1000/30;
        spider.pose({angle:i%2?2:-2,walk:1,phase:i*.7,reach:{x:145,y:95},smooth:true});
        const current=offsets();current.forEach((p,index)=>{
          const step=Math.hypot(p.x-previous[index].x,p.y-previous[index].y);
          assert.ok(step<=4.000001);if(step>.01)moved++;
        });
        previous=current;
      }
      assert.ok(moved>100,'The cap must be checked across real joint changes, not repeated poses in one clock tick');
      spider.pose({x:100,y:120,angle:.7,reach:{x:145,y:95},grip:1});
      near(spider.tip.x,145);near(spider.tip.y,95);
    """)


def test_gait_resume_after_quiet_time_cannot_accumulate_a_large_foot_step():
    spider_check(r"""
      let now=100;doc.defaultView.performance.now=()=>now;
      const offsets=()=>spider.legs.map(leg=>{
        const p=leg.points[3],c=Math.cos(spider.state.angle),s=Math.sin(spider.state.angle);
        return {x:spider.scale*(p.x*c-p.y*s),y:spider.scale*(p.x*s+p.y*c)};
      });
      spider.pose({walk:0,gait:true,smooth:true});const previous=offsets();
      now+=25000;spider.pose({angle:Math.PI,walk:1,gait:true,smooth:true});
      offsets().forEach((point,index)=>assert.ok(Math.hypot(point.x-previous[index].x,point.y-previous[index].y)<=8.000001));
      assert.ok(spider.legMotionPending,'A large turn still has a finite amount of settling work');
      assert.equal(doc.frames.size,0,'Only the existing narrative owns display frames');
    """)


@pytest.mark.parametrize("random_fraction", [0, .7, 1], ids=["shortest", "former_failure", "longest"])
def test_mixed_jobs_and_backlog_merges_never_teleport_the_composited_container(random_fraction):
    scene_check(f"scene.work.random=()=>{random_fraction};\n" + r"""
      let now=100;doc.defaultView.performance.now=()=>now;
      const rows=Array.from({length:12},(_,index)=>({id:`smooth${index}`,status:'candidate'}));
      const base={day:'2026-10-16',sessions:[session(1)],alphas:rows,review:rows.slice(0,3),events:[]};scene.update(base);
      const surface=scene.spider.positionSurface;
      assert.equal(typeof surface.positionAt,'function');
      let previous=surface.positionAt(now),peak=0,steps=0;
      const frame=()=>{
        now+=1000/60;doc.sampleAnimations();
        const callbacks=[...doc.frames];doc.frames.clear();for(const [,callback]of callbacks)callback(now);
        const current=surface.positionAt(now),distance=Math.hypot(current.x-previous.x,current.y-previous.y);
        peak=Math.max(peak,distance);if(distance>.01)steps++;
        assert.ok(distance<=12.00001,`Body jumped ${distance}px at ${now}ms`);
        previous=current;
      };
      let seq=0;
      for(let i=0;i<4200;i++){
        if(i===0||i===400||i===1800)scene.update({...base,events:[{seq:++seq,kind:'sim_done',pid:1,n:8,alphas:rows.slice(0,8).map(a=>a.id)}]});
        if(i===70||i===420||i===2100)scene.update({...base,events:[{seq:++seq,kind:'prod_block',pid:1,alphas:[rows[i%12].id]}]});
        if(i===100||i===500||i===2300)scene.update({...base,events:[{seq:++seq,kind:'candidate',pid:1,alphas:[rows[i%3].id]}]});
        if(i===130||i===600)scene.update({...base,events:Array.from({length:40},(_,index)=>({seq:++seq,kind:'eval_fail',pid:1,alphas:[rows[index%12].id]}))});
        if(i===200)scene.update({...base,events:[{seq:++seq,kind:'eval_pass',pid:1,alphas:[rows[0].id]}]});
        frame();
      }
      assert.ok(steps>60&&peak>0,'The test must contain actual continuous movement');
      assert.ok(scene.narrative.coalesced>0,'Backlog cancellation must also be exercised');
      assert.equal(scene.effectLayer.children.length,0,'Business effects must already be released');
      // The 70s sample can end inside a real 2.7s patrol. Let that same walk
      // finish while continuing to check every interpolated displacement.
      for(let i=0;scene.narrative.workAction&&i<240;i++)frame();
      assert.equal(scene.narrative.workAction,null,'Patrol must release its finite rAF without clearing it artificially');
      assert.equal(scene.effectLayer.children.length,0);assert.equal(doc.frames.size,0);
    """)


def test_destroying_a_moving_spider_cancels_its_native_body_animation():
    scene_check(f"const {{planSilkTravel}}=await import({json.dumps((WEB/'motion.js').as_uri())});\n" + r"""
      const body=scene.spider.positionSurface;
      const plan=planSilkTravel(body.positionAt(),{x:450,y:158},{confine:p=>scene.spider.centerAt(p)});
      body.travel(plan);
      assert.equal(body.traveling,true);assert.ok(scene.layers.promotions.has(body.host));
      scene.spider.destroy();
      assert.equal(body.traveling,false);assert.equal(body.travelAnimation,null);
      assert.ok(!scene.layers.promotions.has(body.host));
      assert.ok([...doc.animations].every(animation=>animation.effect.target!==body.host));
    """)


def test_full_height_inspection_routes_keep_body_and_world_feet_continuous():
    scene_check(r"""
      let now=100;doc.defaultView.performance.now=()=>now;
      const body=scene.spider.positionSurface,spider=scene.spider;
      const feet=()=>spider.legs.map(leg=>{
        const p=leg.points[3],c=Math.cos(spider.state.angle),s=Math.sin(spider.state.angle);
        const center=body.positionAt(now);
        return {x:center.x+spider.scale*(p.x*c-p.y*s),y:center.y+spider.scale*(p.x*s+p.y*c)};
      });
      let previous=body.positionAt(now),previousFeet=feet(),walking=0;
      for(const target of [{x:420,y:158},{x:770,y:163},{x:420,y:163},{x:770,y:158}]){
        assert.equal(scene.narrative.startWorkAction({kind:'inspection',target}),true);
        for(let frames=0;scene.narrative.workAction&&frames<600;frames++){
          now+=1000/60;doc.sampleAnimations();
          const callbacks=[...doc.frames];doc.frames.clear();for(const [,callback]of callbacks)callback(now);
          const current=body.positionAt(now),currentFeet=feet();
          assert.ok(current.x>=SCREEN_CONTENT.left+66&&current.x<=SCREEN_CONTENT.right-66);
          assert.ok(current.y>=SCREEN_CONTENT.top+66&&current.y<=SCREEN_CONTENT.bottom-66);
          assert.ok(Math.hypot(current.x-previous.x,current.y-previous.y)<=12.00001);
          currentFeet.forEach((point,i)=>assert.ok(Math.hypot(point.x-previousFeet[i].x,point.y-previousFeet[i].y)<=12.00001,
            'A world-space contact cannot jump while traversing the taller screen'));
          if(spider.state.walk>0)walking++;
          previous=current;previousFeet=currentFeet;
        }
        assert.equal(scene.narrative.workAction,null);
      }
      assert.ok(walking>100);assert.equal(doc.frames.size,0);
    """)


def test_visible_inspection_result_handoff_preserves_the_capped_contact_pose():
    scene_check(r"""
      let now=100;doc.defaultView.performance.now=()=>now;
      const base={day:'2026-10-16',alphas:[{id:'handoff-feet',status:'done'}],events:[]};scene.update(base);
      const spider=scene.spider,body=spider.positionSurface;
      const feet=()=>spider.legs.map(leg=>{
        const p=leg.points[3],c=Math.cos(spider.state.angle),s=Math.sin(spider.state.angle),center=body.positionAt(now);
        return {x:center.x+spider.scale*(p.x*c-p.y*s),y:center.y+spider.scale*(p.x*s+p.y*c)};
      });
      let previous=feet();
      const inspect=()=>{
        const current=feet();
        current.forEach((point,i)=>assert.ok(Math.hypot(point.x-previous[i].x,point.y-previous[i].y)<=12.00001));
        previous=current;
      };
      const advance=()=>{
        now+=1000/60;doc.sampleAnimations();
        const callbacks=[...doc.frames];doc.frames.clear();for(const [,callback]of callbacks)callback(now);
        inspect();
      };
      assert.equal(scene.narrative.startWorkAction({kind:'inspection',target:{x:420,y:158}}),true);
      for(let i=0;i<45;i++)advance();
      scene.update({...base,events:[{seq:1,kind:'eval_pass',alpha:'handoff-feet'}]});
      assert.equal(scene.narrative.workAction,null);assert.equal(scene.narrative.active.kind,'eval_pass');inspect();
      for(let i=0;scene.narrative.working&&i<900;i++)advance();
      assert.equal(scene.narrative.working,false);assert.equal(doc.frames.size,0);
    """)
