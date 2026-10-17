"""Keep animated sprites free of SVG timelines and compositor filters."""
from test_scene_r1 import scene_check
from test_web_narrative import CLOCK
from test_panel_perf import COUNT_WRITES
from test_frontend import dashboard_check


def test_animated_sprites_use_painted_glows_without_css_or_svg_filters():
    scene_check(CLOCK + r"""
      const alpha={id:'pick',status:'candidate',sharpe:1.8};
      const base={day:'2026-10-16',sessions:[session(1)],alphas:[alpha],review:[],events:[]};
      scene.update(base);
      const forbidden=new Set(['animate','animatetransform','animatemotion','set']);
      const inspect=()=>{
        for(const node of scene.canvas.querySelectorAll('*'))assert.ok(!forbidden.has(node.tagName.toLowerCase()));
        for(const surface of scene.layers.surfaces){
          for(let node=surface.motion;node;node=node.parentNode){
            assert.ok(['','none'].includes(node.style.getPropertyValue('filter')),'An animated sprite and every ancestor must be filter-free');
            assert.equal(node.getAttribute('filter'),null);
          }
          for(const node of surface.svg.querySelectorAll('*'))assert.equal(node.getAttribute('filter'),null,'Sprite glows are painted gradients');
        }
      };
      inspect();
      const cocoon=scene.networkNodes.get('pick');
      assert.ok(cocoon.surface.svg.querySelectorAll('radialGradient').length>0,'Candidate glow must remain visible as cached artwork');
      scene.update({...base,review:[alpha],events:[
        {seq:1,kind:'sim_submit',pid:1,n:8,exprs:['rank(close)']},
        {seq:2,kind:'sim_done',pid:1,n:1,alphas:['pick']},
        {seq:3,kind:'prod_block',pid:1,alphas:['pick']},
        {seq:4,kind:'candidate',pid:1,alphas:['pick']}]});
      advance(12000,inspect);
      assert.equal(scene.effectLayer.children.length,0);
    """)


def test_quiet_clock_ticks_touch_only_the_fixed_clock_box():
    dashboard_check(CLOCK + r"""
      app.render({day:'2026-10-16',mode:'demo',generated_at:'2026-10-16T12:00:00+08:00',events:[]});
      now=70100;app.tickClock();writes.length=0;
      const clock=doc.getElementById('clock');
      for(let i=0;i<5;i++){now+=1000;app.tickClock();}
      assert.ok(writes.length>0);
      assert.ok(writes.every(write=>within(write.node,[clock])),'Quiet clock ticks cannot rewrite panels or the scene');
    """, setup=COUNT_WRITES)


def test_queued_event_flights_continue_when_only_the_environment_turns_quiet():
    scene_check(CLOCK + r"""
      const alpha={id:'keep-sorting',status:'eval_passed',sharpe:1.7};
      const base={day:'2026-10-16',sessions:[session(1)],alphas:[alpha],events:[]};scene.update(base);
      scene.update({...base,events:Array.from({length:10},(_,index)=>({seq:index+1,kind:'eval_pass',pid:1,alphas:[alpha.id]}))});
      let quietFlight=false,forced=false;
      advance(21000,()=>{
        const job=scene.narrative.active;
        const flight=job?.particles[0]?.surface.animation;
        if(!forced&&flight?.playState==='running'){
          scene.lastEventAt=now-15001;forced=true;
          scene.checkActivity(now);
          assert.equal(scene.environmentQuiet,true);assert.equal(flight.playState,'running');
        }
        scene.checkActivity(now);
        if(forced&&scene.environmentQuiet&&flight?.playState==='running')quietFlight=true;
      });
      assert.ok(quietFlight,'A 15-second environment pause must not cancel queued sorting flights');
      assert.equal(scene.ambient.timer,null);assert.equal(scene.effectLayer.children.length,0);assert.equal(doc.frames.size,0);
    """)
