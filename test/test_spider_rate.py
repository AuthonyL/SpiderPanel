"""SVG pose rate and native body travel are independent clocks."""
import json
import pytest
from test_frontend import WEB
from test_spider import spider_check
from test_scene_r1 import scene_check
from test_web_narrative import CLOCK


@pytest.mark.parametrize('refresh', [50, 60, 90, 120, 144])
def test_leg_updates_follow_the_configured_cap_without_halving_it(refresh):
    spider_check(f"const refresh={refresh};\n" + r"""
      const {SPIDER_LEG_HZ}=await import(__RULES__);
      let now=100;doc.defaultView.performance.now=()=>now;
      let changed=0,last=-1;
      for(const leg of spider.legs){
        const set=leg.path.setAttribute.bind(leg.path);
        leg.path.setAttribute=(key,value)=>{if(key==='d'&&last!==now){changed++;last=now;}set(key,value);};
      }
      for(let i=0;i<=refresh*4;i++){
        now=100+i*1000/refresh;
        spider.pose({x:100+i/refresh*150,y:120,angle:Math.PI/2,walk:1,gait:true,smooth:true});
      }
      const rate=(changed-1)/4;
      assert.ok(rate>=SPIDER_LEG_HZ*.9&&rate<=SPIDER_LEG_HZ*1.1,`${refresh}Hz display produced ${rate} poses/second`);
    """.replace('__RULES__', json.dumps((WEB/'animation-rules.js').as_uri())))


def test_skipped_frames_still_accumulate_distance_and_sample_the_current_position():
    spider_check(r"""
      let now=100;doc.defaultView.performance.now=()=>now;
      spider.pose({x:100,y:120,angle:Math.PI/2,walk:1,phase:0,smooth:true});
      const before=spider.legs[2].path.getAttribute('d');
      now+=10;spider.pose({x:101.5,y:120,angle:Math.PI/2,walk:1,gait:true,travelDistance:1.5,smooth:true});
      assert.equal(spider.legs[2].path.getAttribute('d'),before,'An early display frame must not repaint legs');
      assert.ok(spider.state.phase>0,'A skipped paint must still consume native arc length');
      now+=10;spider.pose({x:103,y:120,angle:Math.PI/2,walk:1,gait:true,travelDistance:1.5,smooth:true});
      now+=14;spider.pose({x:105.1,y:120,angle:Math.PI/2,walk:1,gait:true,travelDistance:2.1,smooth:true});
      near(spider.state.x,105.1);near(spider.state.phase,5.1/33.6*2*Math.PI);
      assert.notEqual(spider.legs[2].path.getAttribute('d'),before);
    """)


def test_resting_legs_do_not_repaint_and_reaching_only_repaints_the_gripper():
    spider_check(r"""
      let now=100;doc.defaultView.performance.now=()=>now;
      spider.pose({walk:0,gait:true,smooth:true});
      const changed=new Set();
      for(const [index,leg]of spider.legs.entries())for(const node of [leg.path,...leg.joints,...leg.claws]){
        const set=node.setAttribute.bind(node);node.setAttribute=(key,value)=>{changed.add(index);set(key,value);};
      }
      for(let i=0;i<120;i++){now+=1000/60;spider.pose({walk:0,gait:true,smooth:true});}
      assert.equal(changed.size,0);
      for(let i=0;i<60;i++){now+=1000/60;spider.pose({reach:{x:145,y:95},grip:1,gait:true,smooth:true});}
      assert.deepEqual([...changed],[0]);near(spider.tip.x,145);near(spider.tip.y,95);
    """)


def test_live_scene_has_svg_legs_and_no_canvas_dependency():
    scene_check(CLOCK + r"""
      assert.equal(scene.canvas.querySelectorAll('canvas').length,0);
      assert.equal(scene.spider.root.querySelectorAll('.wq-spider-leg').length,8);
      const base={day:'2026-10-16',alphas:[{id:'svg',status:'done'}],events:[]};scene.update(base);
      scene.update({...base,events:[{seq:1,kind:'sim_done',n:1,alphas:['svg']}]});
      advance(100);assert.ok(scene.spider.positionSurface.traveling);
      assert.ok(scene.spider.positionSurface.travelAnimation);
      assert.equal(scene.spider.positionSurface.travelAnimation.effect.target,scene.spider.positionSurface.host);
    """)
    assert not (WEB/'spider-legs.js').exists()


def test_regular_walk_uses_cached_joint_and_claw_poses_instead_of_eight_ik_solves():
    spider_check(r"""
      let now=100;doc.defaultView.performance.now=()=>now;
      spider.pose({x:100,y:120,angle:0,walk:1,phase:0});
      let solves=0;const sqrt=Math.sqrt;Math.sqrt=value=>{solves++;return sqrt(value);};
      try{
        for(let i=1;i<=180;i++){
          now=100+i*1000/30;
          spider.pose({x:100,y:120-i*5,angle:0,walk:1,gait:true,smooth:true});
        }
      }finally{Math.sqrt=sqrt;}
      assert.ok(solves<180*2,`A straight cached walk still solved IK ${solves} times`);
    """)


@pytest.mark.parametrize('refresh', [50, 60, 90, 120, 144])
def test_final_relaxation_finishes_standing_before_the_owner_stops_its_clock(refresh):
    scene_check(f"const refresh={refresh};\n" + r"""
      let now=100;doc.defaultView.performance.now=()=>now;
      const base={day:'2026-10-16',alphas:[{id:'settle',status:'done'}],events:[]};scene.update(base);
      scene.update({...base,events:[{seq:1,kind:'sim_done',n:1,alphas:['settle']}]});
      for(let i=0;i<refresh*20&&scene.narrative.working;i++){
        now+=1000/refresh;doc.sampleAnimations();
        const frames=[...doc.frames];doc.frames.clear();for(const [,fn]of frames)fn(now);
      }
      assert.equal(scene.narrative.working,false);assert.equal(doc.frames.size,0);
      assert.equal(scene.spider.state.walk,0,'The final standing pose cannot be left behind the paint gate');
    """)
