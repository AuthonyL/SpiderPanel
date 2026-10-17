"""Check paint boundaries; browser CPU/layout are measured separately with CDP."""
from test_frontend import dashboard_check
from test_panel_perf import COUNT_WRITES
from test_web_narrative import CLOCK


def perf_check(source):
    dashboard_check("const scene=app.scene;\n" + CLOCK + source, setup=COUNT_WRITES)


def test_background_is_static_and_ambient_art_lives_on_small_sprite_surfaces():
    perf_check(r"""
      const session={pid:1,label:'会话 1',shape:'ghost',color:'#fff',phase:'simulating',last_expr:'rank(close)'};
      app.render({day:'2026-10-16',sessions:[session],totals:{sims_pending:2},
        alphas:[{id:'a',status:'candidate'}],review:[{id:'a'}],events:[]});
      assert.equal(scene.svg.parentNode,scene.canvas);
      assert.equal(scene.layers.root.parentNode,scene.canvas);
      assert.equal(scene.svg.querySelectorAll('style').length,0,'The background must not own animation rules');
      for(const node of [scene.svg,...scene.svg.querySelectorAll('*')]){
        assert.ok(!/animation|transition/.test(node.getAttribute('style')||''));
        assert.ok(!node.classList.contains('wq-animated'),'Ambient SVG groups must leave the background');
      }
      for(const surface of scene.layers.surfaces){
        assert.ok(surface.box.width<=600&&surface.box.height<=500);
        assert.equal(surface.svg.querySelectorAll('feGaussianBlur').length,0);
        assert.equal(surface.host.style.getPropertyValue('will-change'),''); // only a motion lease may promote a sprite
      }
      assert.ok(scene.layers.surfaces.size>=16,'Miners, monitors, LEDs, cocoons and counters have separate surfaces');
      for(const entry of scene.sessionNodes.values())assert.ok(within(entry.g,[scene.layers.root]));
      assert.ok(within(scene.spider.root,[scene.layers.root]));
      assert.ok(within(scene.spider.trail,[scene.layers.root]));
      assert.equal(scene.web.wires.parentNode,scene.web.wireSurface.svg);
      assert.ok(!scene.web.wireSurface.ambient,'The large web is stationary');
      assert.ok(!scene.layers.promotions.has(scene.web.wireSurface.motion));
    """)


def test_active_narrative_never_rewrites_the_background_svg():
    perf_check(r"""
      const alpha={id:'a',status:'candidate',sharpe:1.8};
      const base={day:'2026-10-16',sessions:[{pid:1,label:'会话 1',phase:'simulating'}],alphas:[alpha],review:[],events:[]};
      app.render(base);
      app.render({...base,review:[alpha],events:[
        {seq:1,kind:'sim_submit',pid:1,n:8,exprs:['rank(close)']},
        {seq:2,kind:'sim_done',pid:1,n:1,alphas:['a']},
        {seq:3,kind:'prod_block',pid:1,alphas:['a']},
        {seq:4,kind:'candidate',pid:1,alphas:['a']},
        {seq:5,kind:'sim_fail',pid:1}]});
      writes.length=0;advance(12000);
      const staticWrites=writes.filter(write=>within(write.node,[scene.svg]));
      assert.deepEqual(staticWrites.map(write=>[write.node.tagName,write.key]),[],
        'Even landing cocoons, branch counts, notes and shredder shake must stay outside the backdrop');
      assert.equal(scene.effectLayer.children.length,0);assert.equal(doc.frames.size,0);
      assert.equal(scene.narrative.hiddenNotes.size,0);
    """)


def test_event_seq_controls_sixty_second_idle_pause_and_hidden_page_stop():
    perf_check(r"""
      const base={day:'2026-10-16',events:[{seq:10,kind:'sim_submit'}]};app.render(base);
      now=60099;scene.checkActivity();assert.equal(scene.environmentIdle,false);
      now=60100;app.tickClock();
      assert.equal(scene.environmentIdle,true);assert.equal(scene.layers.root.getAttribute('data-paused'),'true');
      assert.equal(scene.spider.paused,true);assert.ok(doc.documentElement.classList.contains('environment-idle'));
      now=62000;app.render({...base,revision:22});assert.equal(scene.environmentIdle,true,'Metadata cannot keep ambient animation alive');
      app.render({...base,events:[{seq:11,kind:'sim_submit'}]});
      assert.equal(scene.environmentIdle,false);assert.equal(scene.layers.root.getAttribute('data-paused'),'false');
      assert.equal(doc.documentElement.classList.contains('environment-idle'),false);
      doc.hidden=true;doc.dispatch('visibilitychange');
      assert.equal(scene.layers.root.getAttribute('data-paused'),'true');assert.equal(doc.frames.size,0);
      doc.hidden=false;doc.dispatch('visibilitychange');
      assert.equal(scene.layers.root.getAttribute('data-paused'),'false');
      doc.media.change(true);assert.equal(doc.frames.size,0);assert.equal(scene.spider.reducedMotion,true);
    """)


def test_metadata_only_updates_leave_background_untouched():
    perf_check(r"""
      const base={day:'2026-10-16',sessions:[{pid:0,label:'未知会话',phase:'idle'}],events:[],
        alphas:[{id:'a',status:'done'}],totals:{alphas:1,sims_pending:0}};
      app.render(base);writes.length=0;
      for(let i=0;i<4;i++)app.render({...base,revision:i,generated_at:`2026-10-16T01:00:0${i}+08:00`});
      assert.equal(writes.filter(write=>within(write.node,[scene.svg])).length,0);
      assert.equal(doc.frames.size,0);
    """)


def test_review_data_refresh_during_a_flight_cannot_leave_the_note_invisible():
    perf_check(r"""
      const alpha={id:'pick',status:'candidate',sharpe:1.8};
      const base={day:'2026-10-16',alphas:[alpha],review:[],events:[]};app.render(base);
      const events=[{seq:1,kind:'candidate',alpha:'pick',alphas:['pick']}];
      app.render({...base,review:[alpha],events});advance(800);
      const note=scene.noteNodes.get('pick');assert.equal(note.surface.motion.style.getPropertyValue('opacity'),'0');
      app.render({...base,review:[{...alpha,sharpe:1.9}],events});
      until(()=>note.surface.motion.classList.contains('wq-note-flip'));
      assert.equal(note.paper.getAttribute('opacity'),'1','Only the HTML surface may hide a flying note');
      assert.equal(note.surface.motion.style.getPropertyValue('opacity'),'1');
      assert.ok(note.surface.motion.classList.contains('wq-note-flip'));
    """)


def test_status_only_alpha_change_does_not_repaint_the_background():
    perf_check(r"""
      const base={day:'2026-10-16',alphas:[{id:'a',status:'done'}],events:[]};
      app.render(base);writes.length=0;
      app.render({...base,alphas:[{id:'a',status:'eval_failed'}]});
      assert.deepEqual(writes.filter(write=>within(write.node,[scene.svg])).map(write=>[write.node.tagName,write.key]),[],
        'A cocoon status change cannot rewrite unchanged ALPHAS title or counts in the cached backdrop');
    """)


def test_promoted_monitor_graphics_keep_the_original_parent_opacity():
    perf_check(r"""
      const session={pid:1,label:'会话 1',phase:'idle',idle:true};app.render({sessions:[session],events:[]});
      for(const station of scene.stations)assert.equal(station.miniRoot.getAttribute('opacity'),station.monitor.getAttribute('opacity'));
      app.render({sessions:[{...session,phase:'simulating',idle:false}],events:[]});
      for(const station of scene.stations)assert.equal(station.miniRoot.getAttribute('opacity'),station.monitor.getAttribute('opacity'));
    """)


def test_compositor_flights_need_no_js_frames_or_per_frame_style_writes():
    perf_check(r"""
      const base={day:'2026-10-16',sessions:[{pid:1,label:'会话 1',phase:'simulating'}],events:[]};
      app.render(base);app.render({...base,events:[{seq:1,kind:'sim_submit',pid:1,n:8,exprs:['rank(close)']}]});
      const job=scene.narrative.parallel[0];
      assert.equal(doc.frames.size,0,'Paper trajectories run on the compositor, not in a JS frame loop');
      assert.equal(job.particles.length,8);
      for(const particle of job.particles){
        assert.equal(particle.surface.animation.playState,'running');
        assert.ok(particle.surface.animation.effect.getKeyframes().length>30,'Upload a sampled curved trajectory once');
      }
      const flights=job.particles.map(particle=>particle.surface.host);
      writes.length=0;advance(1000);
      assert.equal(writes.filter(write=>within(write.node,flights)).length,0,'Flight frames must not rewrite SVG, style, or position; environment details may step at 4 Hz');
      advance(800);assert.equal(scene.effectLayer.children.length,0);assert.equal(doc.frames.size,0);
    """)


def test_hidden_and_reduced_motion_cancel_the_delayed_shredder_animation():
    perf_check(r"""
      const base={day:'2026-10-16',events:[]};app.render(base);
      app.render({...base,events:[{seq:1,kind:'sim_fail'}]});
      const shredder=scene.shredderSurface;
      assert.ok(shredder.animation,'The shaker has a delayed native animation');
      doc.hidden=true;doc.dispatch('visibilitychange');
      assert.equal(shredder.animation,null);assert.equal(shredder.motion.style.getPropertyValue('transform'),'none');
      assert.equal(scene.layers.promotions.size,0);assert.equal(doc.animations.size,0);
      advance(3000);assert.equal(shredder.animation,null);assert.equal(doc.frames.size,0);
      doc.hidden=false;doc.dispatch('visibilitychange');
      app.render({...base,events:[{seq:2,kind:'precheck_fail'}]});assert.ok(shredder.animation);
      doc.media.change(true);assert.equal(shredder.animation,null);assert.equal(doc.animations.size,0);
      assert.equal(scene.layers.promotions.size,0);assert.equal(scene.effectLayer.children.length,0);
    """)


def test_relaxed_gripper_queries_do_not_pose_or_repaint_the_spider():
    perf_check(r"""
      const spider=scene.spider;
      for(const angle of [0,Math.PI/2,-Math.PI/2,2.4]){
        const point={x:540,y:160,angle};spider.pose(point);
        const actual={...spider.tip};writes.length=0;
        const relaxed=spider.restTipAt(point);
        assert.ok(Math.hypot(relaxed.x-actual.x,relaxed.y-actual.y)<1e-8);
        assert.equal(writes.length,0,'IK must compute one final pose per frame, without an intermediate rest repaint');
      }
    """)
