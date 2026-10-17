"""Articulated spider behavior in the existing structural SVG DOM harness."""

import json
from pathlib import Path
import shutil
import subprocess

import pytest


WEB = Path(__file__).resolve().parents[1] / "web"
NODE = shutil.which("node")


def spider_check(source, setup=""):
    if NODE is None:
        pytest.skip("未安装 Node.js")
    script = (
        "import assert from 'node:assert/strict';\n"
        f"import {{documentFromHTML,descendants}} from {json.dumps((Path(__file__).parent / 'frontend_dom.mjs').as_uri())};\n"
        f"import {{MechanicalSpider}} from {json.dumps((WEB / 'spider.js').as_uri())};\n"
        f"import {{SCREEN_CONTENT,SCENE_WIDTH,SCENE_TOP,SCENE_HEIGHT}} from {json.dumps((WEB / 'geometry.js').as_uri())};\n"
        "const doc=documentFromHTML('<html><body><svg id=\"scene\"></svg></body></html>');\n"
        "const parent=doc.getElementById('scene');\n"
        "const near=(actual,want)=>assert.ok(Math.abs(actual-want)<1e-8,`${actual} != ${want}`);\n"
        "const point=node=>{const t=node.getAttribute('transform');const xy=t?.match(/translate\\(([-+\\deE.]+) ([-+\\deE.]+)\\)/);return xy?{x:Number(xy[1]),y:Number(xy[2])}:{x:Number(node.getAttribute('cx')),y:Number(node.getAttribute('cy'))};};\n"
        "const distance=(a,b)=>Math.hypot(a.x-b.x,a.y-b.y);\n"
        + setup + "\n"
        "const spider=new MechanicalSpider(parent,{id:'spec-spider',x:100,y:120});\n"
        "try {\n" + source + "\n} finally {spider.destroy();}\n"
    )
    result = subprocess.run([NODE, "--input-type=module", "--eval", script],
                            text=True, capture_output=True, timeout=15)
    assert result.returncode == 0, result.stderr


def test_eight_three_segment_legs_have_real_joint_nodes_and_reference_scale():
    spider_check(r"""
      assert.equal(spider.legs.length,8);
      assert.equal(spider.root.querySelectorAll('.wq-spider-leg').length,8);
      for(const leg of spider.legs){
        assert.equal(leg.joints.length,4);
        assert.equal(leg.foot,leg.joints[3]);
        assert.equal(leg.path.getAttribute('d').match(/L/g).length,3);
        assert.ok(leg.joints.every(joint=>joint.parentNode===leg.root));
        assert.ok(leg.joints.map(point).every(p=>Number.isFinite(p.x)&&Number.isFinite(p.y)));
      }
      const feet=spider.legs.map(leg=>point(leg.foot));
      const span=Math.max(...feet.map(p=>p.x))-Math.min(...feet.map(p=>p.x));
      assert.ok(span>=100&&span<=120,'Resting span fits the factory screen');
      const abdomen=spider.root.querySelector('.wq-spider-abdomen');
      const head=spider.root.querySelector('.wq-spider-head');
      const length=Number(abdomen.getAttribute('cy'))+Number(abdomen.getAttribute('ry'))
        -Number(head.getAttribute('cy'))+Number(head.getAttribute('ry'));
      assert.ok(length>=39&&length<=48,'Body is about one quarter of the 187-unit monitor');
      assert.equal(spider.root.querySelectorAll('.wq-spider-eye').length,4);
      assert.ok(spider.root.querySelector('defs').children.some(node=>node.tagName==='linearGradient'));
    """)


def test_walking_articulates_joints_and_has_planted_then_returning_feet():
    spider_check("""
      const leg=spider.legs[0];
      spider.pose({walk:1,phase:.2});
      const first=leg.joints.map(point), transform=spider.root.getAttribute('transform');
      spider.pose({walk:1,phase:1.2});
      const planted=leg.joints.map(point);
      near(planted[3].x,first[3].x);
      assert.ok(planted[3].y>first[3].y,'A planted foot travels back relative to the moving body');
      assert.ok(distance(first[2],planted[2])>.1,'Knees solve a new pose');
      near(distance(first[0],first[1]),distance(planted[0],planted[1]));
      near(distance(first[1],first[2]),distance(planted[1],planted[2]));
      near(distance(first[2],first[3]),distance(planted[2],planted[3]));
      spider.pose({walk:1,phase:5});
      const returning=leg.joints.map(point);
      assert.ok(returning[3].x<planted[3].x,'The return stroke lifts inward');
      assert.equal(spider.root.getAttribute('transform'),transform);
      spider.pose({walk:0,phase:0});const resting=leg.path.getAttribute('d');
      spider.pose({walk:0,phase:2.7});assert.equal(leg.path.getAttribute('d'),resting);
    """)


def test_reaching_foot_touches_absolute_scene_targets_after_world_rotation():
    spider_check(r"""
      assert.equal(spider.scale,1.4);
      assert.ok(spider.root.getAttribute('transform').includes('scale(1.4)'));
      for(const [angle,target] of [[Math.PI/2,{x:125,y:165}],[-Math.PI/3,{x:62,y:102}],[0,{x:315,y:95}],[0,{x:108,y:109}]]){
        spider.pose({x:100,y:120,angle,reach:target,grip:1});
        near(spider.tip.x,target.x);near(spider.tip.y,target.y);
        const foot=point(spider.legs[0].foot);
        near(100+1.4*(foot.x*Math.cos(angle)-foot.y*Math.sin(angle)),target.x);
        near(120+1.4*(foot.x*Math.sin(angle)+foot.y*Math.cos(angle)),target.y);
        const points=spider.legs[0].joints.map(point);
        assert.ok(points.every(p=>Number.isFinite(p.x)&&Number.isFinite(p.y)));
        for(const claw of spider.legs[0].claws){
          const numbers=claw.getAttribute('d').match(/-?\d*\.?\d+(?:e[+-]?\d+)?/gi).map(Number);
          near(numbers.at(-2),foot.x);near(numbers.at(-1),foot.y);
        }
      }
      spider.pose({reach:{x:145,y:95},grip:0});
      const open=spider.legs[0].claws.map(claw=>claw.getAttribute('d'));
      const joints=spider.legs[0].joints.map(point);
      const cross=(joints[2].x-joints[1].x)*(joints[3].y-joints[1].y)
        -(joints[2].y-joints[1].y)*(joints[3].x-joints[1].x);
      assert.ok(Math.abs(cross)>20,'Reach bends a physical elbow and knee');
      spider.pose({reach:{x:145,y:95},grip:1});
      assert.ok(spider.legs[0].claws.every((claw,i)=>claw.getAttribute('d')!==open[i]));
    """)


def test_moving_spider_leaves_one_bounded_silk_path_that_fades_without_a_timer():
    spider_check("""
      const before=descendants(parent),trail=parent.querySelector('.wq-spider-trail');
      assert.ok(trail);assert.equal(trail.getAttribute('opacity'),'0');
      assert.ok(parent.children.indexOf(trail)<parent.children.indexOf(spider.root));
      for(let i=1;i<=500;i++)spider.pose({x:100+i,y:120+Math.sin(i/20)*10,walk:1});
      assert.equal(parent.querySelectorAll('.wq-spider-trail').length,1);
      assert.equal(descendants(parent),before);
      assert.ok(Number(trail.getAttribute('opacity'))>0);
      assert.ok(trail.getAttribute('d').match(/L/g).length<=47);
      const drawn=trail.getAttribute('d');
      spider.pose({walk:0});
      assert.equal(trail.getAttribute('opacity'),'0');
      assert.equal(trail.getAttribute('d'),drawn,'Stopping fades the existing silk instead of deleting it');
      assert.equal(trail.style.getPropertyValue('transition-duration'),'2.4s');
      assert.equal(doc.frames.size,0,'Silk fading must not keep a JS animation loop alive');
      spider.pose({x:605,y:130,walk:1});
      doc.media.change(true);
      assert.equal(trail.getAttribute('opacity'),'0');
      assert.equal(trail.getAttribute('d'),'');
      spider.destroy();assert.equal(parent.children.length,0);
    """,setup="""
      const forbidden=()=>{throw new Error('Silk must use CSS fading');};
      globalThis.setTimeout=forbidden;globalThis.setInterval=forbidden;
    """)


def test_pose_uses_existing_nodes_and_owns_no_animation_loop_or_timer():
    spider_check("""
      const size=descendants(spider.root),root=spider.root;
      const paths=spider.legs.map(leg=>leg.path),feet=spider.legs.map(leg=>leg.foot);
      for(let i=0;i<200;i++)spider.pose({x:100+i/10,y:120,angle:i/20,walk:1,phase:i/7});
      assert.equal(spider.root,root);assert.equal(descendants(spider.root),size);
      assert.ok(spider.legs.every((leg,i)=>leg.path===paths[i]&&leg.foot===feet[i]));
      assert.equal(doc.frames.size,0);
    """, setup="""
      const forbidden=()=>{throw new Error('The spider must use its owner scene clock');};
      doc.defaultView.requestAnimationFrame=forbidden;
      globalThis.requestAnimationFrame=forbidden;
      globalThis.setTimeout=forbidden;globalThis.setInterval=forbidden;
    """)


def test_rest_restores_home_and_pause_controls_idle_animations():
    spider_check("""
      const home=spider.root.getAttribute('transform'),feet=spider.legs.map(leg=>leg.path.getAttribute('d'));
      assert.equal(spider.root.getAttribute('data-idle'),'true');
      spider.pose({x:240,y:200,angle:1,walk:1,phase:3,grip:1});
      assert.equal(spider.root.getAttribute('data-idle'),'false');
      spider.setPaused(true);
      assert.equal(spider.root.getAttribute('data-paused'),'true');
      assert.ok(spider.root.querySelectorAll('.wq-spider-animated').every(node=>node.style.getPropertyValue('animation-play-state')==='paused'));
      spider.rest();
      assert.equal(spider.root.getAttribute('transform'),home);
      assert.equal(spider.root.getAttribute('data-idle'),'true');
      assert.deepEqual(spider.legs.map(leg=>leg.path.getAttribute('d')),feet);
      assert.equal(spider.root.getAttribute('data-paused'),'true');
      spider.setPaused(false);
      assert.ok(spider.root.querySelectorAll('.wq-spider-animated').every(node=>node.style.getPropertyValue('animation-play-state')==='running'));
    """)


def test_reduced_motion_disables_idle_and_gait_but_keeps_exact_reach():
    spider_check("""
      spider.pose({walk:1,phase:.2});const moving=spider.legs[0].path.getAttribute('d');
      doc.media.change(true);
      assert.equal(spider.root.getAttribute('data-reduced-motion'),'true');
      assert.ok(spider.root.querySelectorAll('.wq-spider-animated').every(node=>node.style.getPropertyValue('animation')==='none'));
      spider.pose({walk:1,phase:.2});const still=spider.legs[0].path.getAttribute('d');
      spider.pose({walk:1,phase:2});assert.equal(spider.legs[0].path.getAttribute('d'),still);
      assert.notEqual(still,moving);
      spider.pose({x:100,y:120,angle:.7,reach:{x:145,y:95},grip:1});
      near(spider.tip.x,145);near(spider.tip.y,95);
      doc.media.change(false);
      assert.equal(spider.root.getAttribute('data-reduced-motion'),'false');
      assert.ok(spider.root.querySelectorAll('.wq-spider-animated').every(node=>node.style.getPropertyValue('animation')===''));
      spider.destroy();
      assert.equal(doc.media.listeners.size,0);
      assert.equal(parent.children.length,0);
    """)


def test_initial_reduced_motion_and_unique_scoped_svg_definitions():
    spider_check(r"""
      assert.equal(spider.root.getAttribute('data-reduced-motion'),'true');
      const other=new MechanicalSpider(parent,{id:'spec-spider',x:1,y:2});
      try {
        const collect=node=>[node,...node.children.flatMap(collect)];
        const ids=collect(parent).map(node=>node.id).filter(Boolean);
        assert.equal(new Set(ids).size,ids.length);
        for(const item of [spider,other]){
          const style=item.root.querySelector('style').textContent;
          assert.ok(style.includes(`#${item.root.id}`));
          assert.ok(style.includes('prefers-reduced-motion'));
          for(const node of collect(item.root)){
            for(const value of Object.values(node.attributes)){
              for(const match of value.matchAll(/url\(#([^)]+)\)/g))
                assert.ok(item.root.querySelector('#'+match[1]),'Paint references stay inside the owning spider');
            }
          }
        }
      } finally {other.destroy();}
      assert.equal(doc.frames.size,0);
    """, setup="doc.media.matches=true;")


def test_invalid_numbers_never_generate_invalid_svg_geometry():
    spider_check("""
      spider.pose({x:NaN,y:Infinity,angle:NaN,phase:Infinity,walk:NaN,grip:Infinity,reach:{x:NaN,y:0}});
      assert.ok(!/NaN|Infinity/.test(spider.root.getAttribute('transform')));
      assert.ok(spider.legs.every(leg=>!(/NaN|Infinity/.test(leg.path.getAttribute('d')))));
      spider.destroy();spider.destroy();spider.rest();spider.pose({x:2,y:3});
      assert.equal(parent.children.length,0);
    """)


def test_surface_translation_preserves_world_contacts_and_avoids_svg_position_writes():
    spider_check("""
      const svg=doc.createElementNS('http://www.w3.org/2000/svg','svg');
      svg.setAttribute('viewBox','-120 -110 240 220');doc.body.appendChild(svg);
      const moves=[];
      spider.attachSurface({svg,move(x,y){moves.push({x,y});}});
      assert.equal(spider.root.parentNode,svg);
      assert.equal(spider.trail.parentNode,parent,'The world-space trail has its own surface');
      assert.deepEqual(moves,[{x:100,y:120}]);
      const writes=[],set=spider.root.setAttribute.bind(spider.root);
      spider.root.setAttribute=(key,value)=>{writes.push({key,value});set(key,value);};
      spider.pose({x:145,y:132,angle:Math.PI/2,reach:{x:166,y:179},grip:1});
      near(spider.tip.x,166);near(spider.tip.y,179);
      assert.deepEqual(moves.at(-1),{x:145,y:132});
      assert.equal(spider.root.getAttribute('transform'),'rotate(90) scale(1.4)');
      const transformWrites=writes.filter(write=>write.key==='transform').length;
      spider.pose({x:151,y:138,angle:Math.PI/2,reach:{x:166,y:179},grip:1});
      near(spider.tip.x,166);near(spider.tip.y,179);
      assert.equal(writes.filter(write=>write.key==='transform').length,transformWrites,
        'World movement must use the outer HTML surface, without invalidating the SVG transform');
      const moveCount=moves.length;
      for(let i=0;i<100;i++)spider.pose({x:151,y:138,angle:Math.PI/2,reach:{x:166,y:179},grip:1});
      assert.equal(moves.length,moveCount);
      assert.equal(doc.frames.size,0);
      spider.rest();assert.deepEqual(moves.at(-1),{x:100,y:120});
      spider.destroy();assert.equal(svg.children.length,0);
    """)


def test_mounted_idle_uses_one_outer_css_animation_without_svg_timelines():
    spider_check("""
      const svg=doc.createElementNS('http://www.w3.org/2000/svg','svg');doc.body.appendChild(svg);
      const motion=doc.createElement('div');
      const forbidden=()=>{throw new Error('The spider must not create an SVG animation timeline');};
      svg.pauseAnimations=forbidden;svg.unpauseAnimations=forbidden;
      spider.attachSurface({svg,motion,move(){}});
      const assertNoSMIL=()=>{
        const tags=new Set(['animate','animatetransform','animatemotion','set']);
        const collect=node=>[node,...node.children.flatMap(collect)];
        assert.equal(collect(svg).filter(node=>tags.has(node.tagName.toLowerCase())).length,0);
      };
      assertNoSMIL();
      assert.equal(spider.root.getAttribute('data-mounted'),'true');
      assert.ok(motion.style.getPropertyValue('animation').includes('-surface-breathe'));
      assert.equal(spider.animated.length,1,'Standalone breathing has one art group, not per-leg animation');
      assert.ok(spider.animated.every(node=>node.style.getPropertyValue('animation')==='none'),
        'Mounted SVG art stays static inside its single moving HTML surface');
      spider.pose({walk:1,reach:{x:145,y:95},grip:1});
      assert.equal(motion.style.getPropertyValue('animation'),'none');
      near(spider.tip.x,145);near(spider.tip.y,95);
      spider.rest();
      assert.ok(motion.style.getPropertyValue('animation').includes('-surface-breathe'));
      spider.setPaused(true);
      assert.equal(motion.style.getPropertyValue('animation-play-state'),'paused');
      spider.setPaused(false);
      assert.equal(motion.style.getPropertyValue('animation-play-state'),'running');
      doc.media.change(true);
      assert.equal(motion.style.getPropertyValue('animation'),'none');
      assertNoSMIL();
      assert.equal(doc.frames.size,0);
    """)


def test_standalone_idle_has_one_filter_free_breathing_group_and_zero_smil():
    spider_check("""
      const collect=node=>[node,...node.children.flatMap(collect)];
      const nodes=collect(spider.root);
      const banned=new Set(['animate','animatetransform','animatemotion','set']);
      assert.ok(nodes.every(node=>!banned.has(node.tagName.toLowerCase())));
      assert.equal(spider.root.querySelectorAll('.wq-spider-animated').length,1);
      const assembly=spider.root.querySelector('.wq-spider-idle-body');
      assert.ok(assembly);
      assert.equal(assembly.querySelectorAll('.wq-spider-leg').length,8);
      assert.equal(assembly.querySelectorAll('.wq-spider-eye').length,4);
      const css=spider.root.querySelector('style').textContent;
      assert.ok(!css.includes('-twitch'));
      assert.ok(!css.includes('-scan'));
      assert.ok(!css.includes('filter:'));
      assert.ok(nodes.every(node=>!node.getAttribute('filter')&&!node.style.getPropertyValue('filter')));
      spider.setPaused(true);
      assert.equal(assembly.style.getPropertyValue('animation-play-state'),'paused');
      spider.setPaused(false);
      assert.equal(assembly.style.getPropertyValue('animation-play-state'),'running');
    """)


def test_unchanged_poses_do_not_rewrite_any_inline_style():
    spider_check("""
      const svg=doc.createElementNS('http://www.w3.org/2000/svg','svg');doc.body.appendChild(svg);
      const motion=doc.createElement('div');spider.attachSurface({svg,motion,move(){}});
      spider.pose({x:120,y:130,angle:.4,reach:{x:145,y:95},grip:1});
      let writes=0;
      for(const node of [motion,spider.root,...spider.animated,spider.trail]){
        const set=node.style.setProperty.bind(node.style);
        node.style.setProperty=(...args)=>{writes++;set(...args);};
      }
      for(let i=0;i<200;i++)spider.pose({x:120,y:130,angle:.4,reach:{x:145,y:95},grip:1});
      spider.setPaused(false);spider.setPaused(false);
      assert.equal(writes,0,'Identical poses and pause state must not trigger Layerize via inline style writes');
    """)


def test_budgeted_surface_owns_the_only_idle_css_animation_and_trail_fade():
    spider_check("""
      const svg=doc.createElementNS('http://www.w3.org/2000/svg','svg');doc.body.appendChild(svg);
      const motion=doc.createElement('div'),idle=[];
      spider.attachSurface({svg,motion,move(){},animate(classes){idle.push(classes);}});
      assert.deepEqual(idle,['wq-spider-idle wq-animated']);
      const trailSVG=doc.createElementNS('http://www.w3.org/2000/svg','svg');doc.body.appendChild(trailSVG);
      const trailMotion=doc.createElement('div'),plays=[];let stops=0;
      spider.attachTrail({svg:trailSVG,motion:trailMotion,setBox(){},span(){},stop(){stops++;},
        setOpacity(value){trailMotion.style.setProperty('opacity',value);},
        play(frames,options){plays.push({frames,options});}});
      spider.pose({x:110,y:120,walk:1});
      const firstStops=stops;
      for(let i=1;i<=100;i++)spider.pose({x:110+i,y:120,walk:1,phase:i/7});
      assert.equal(stops,firstStops,'Motion must not cancel and recreate a fade on every leg frame');
      assert.deepEqual(idle,['wq-spider-idle wq-animated','']);
      spider.pose({walk:0});
      assert.deepEqual(plays,[{frames:[{opacity:.42},{opacity:0}],options:{duration:2400,easing:'ease-out'}}]);
      assert.equal(trailMotion.style.getPropertyValue('transition'),'none');
      assert.equal(spider.trail.style.getPropertyValue('transition'),'none');
      assert.equal(doc.frames.size,0);
      spider.setPaused(true);assert.equal(trailMotion.style.getPropertyValue('opacity'),'0');
      assert.equal(plays.length,1);assert.ok(stops>firstStops);
    """)


def test_surface_mount_keeps_screen_insets_and_exact_enlarged_gripper_contact():
    spider_check("""
      spider.bounds=SCREEN_CONTENT;
      const svg=doc.createElementNS('http://www.w3.org/2000/svg','svg');doc.body.appendChild(svg);
      const moves=[];spider.attachSurface({svg,move(x,y){moves.push({x,y});}});
      spider.pose({x:0,y:0,angle:.7,reach:{x:0,y:0},grip:1});
      assert.deepEqual(moves.at(-1),{x:420,y:158});
      near(spider.tip.x,364);near(spider.tip.y,102);
      spider.pose({x:1000,y:1000,angle:-.9,reach:{x:1000,y:1000},grip:1});
      assert.deepEqual(moves.at(-1),{x:770,y:163});
      near(spider.tip.x,826);near(spider.tip.y,219);
      assert.ok(spider.root.getAttribute('transform').endsWith('scale(1.4)'));
    """)


def test_retained_trail_surface_tracks_its_world_bounds_and_reuses_one_path():
    spider_check("""
      const svg=doc.createElementNS('http://www.w3.org/2000/svg','svg');doc.body.appendChild(svg);
      const motion=doc.createElement('div');
      const boxes=[];spider.attachTrail({svg,motion,setBox(box){boxes.push(box);},
        setOpacity(value){motion.style.setProperty('opacity',value);}});
      const trail=spider.trail,size=descendants(svg);
      spider.pose({x:110,y:120,walk:1});spider.pose({x:120,y:130,walk:1});
      assert.equal(trail.parentNode,svg);assert.equal(descendants(svg),size);
      const box=boxes.at(-1);
      assert.ok(box.left<100&&box.top<120&&box.left+box.width>120&&box.top+box.height>130);
      assert.equal(svg.getAttribute('viewBox'),`${box.left} ${box.top} ${box.width} ${box.height}`);
      assert.equal(motion.style.getPropertyValue('opacity'),'0.42');
      assert.equal(trail.getAttribute('opacity'),'1','Only the HTML surface fades while mounted');
      const drawn=trail.getAttribute('d'),updates=boxes.length;
      spider.pose({walk:0});
      assert.equal(boxes.length,updates);assert.equal(trail.getAttribute('d'),drawn);
      assert.equal(motion.style.getPropertyValue('opacity'),'0');
      assert.equal(motion.style.getPropertyValue('transition-duration'),'2.4s');
      assert.equal(doc.frames.size,0);
      spider.destroy();assert.equal(svg.children.length,0);
    """)


def test_spider_glow_keeps_rim_and_eyes_without_filter_surfaces():
    spider_check("""
      const collect=node=>[node,...node.children.flatMap(collect)];
      const nodes=collect(spider.root);
      assert.equal(nodes.filter(node=>node.tagName==='filter'||node.tagName==='feGaussianBlur').length,0);
      assert.ok(nodes.every(node=>!node.getAttribute('filter')));
      assert.ok(spider.root.querySelector('.wq-spider-rim'));
      assert.equal(spider.root.querySelectorAll('.wq-spider-eye').length,4);
      assert.ok(nodes.filter(node=>node.tagName==='radialGradient').length>=3,
        'Gradient halos preserve cyan and pink glow without realtime blurring');
      assert.equal(spider.root.querySelectorAll('animate').length,0);
      assert.equal(doc.frames.size,0);
    """)


def test_span_trail_moves_only_html_transform_and_opacity_after_unit_path_mount():
    spider_check("""
      const {SceneLayers}=await import(__LAYERS__);
      const layers=new SceneLayers(parent,'trail-spec',{left:0,top:0,right:SCENE_WIDTH,bottom:SCENE_TOP+SCENE_HEIGHT});
      try {
        const surface=layers.surface({left:0,top:-1,width:1,height:2},{local:true,kind:'drag-silk'});
        const spans=[],span=surface.span;
        surface.span=(from,to)=>{spans.push({from:{...from},to:{...to}});span(from,to);};
        spider.attachTrail(surface);
        const initial=surface.host.style.getPropertyValue('transform');
        const viewBox=surface.svg.getAttribute('viewBox'),writes=[];
        for(const node of [spider.trail,surface.svg]){
          const set=node.setAttribute.bind(node);
          node.setAttribute=(key,value)=>{writes.push({node,key,value});set(key,value);};
        }
        for(let i=1;i<=100;i++){
          spider.pose({x:100+i,y:120+Math.sin(i/8)*10,walk:1,phase:i/7,angle:.3,
            reach:{x:250,y:140},grip:1});
          near(spider.tip.x,250);near(spider.tip.y,140);
        }
        assert.equal(spider.trail.getAttribute('d'),'M0 0H1');
        assert.equal(surface.svg.getAttribute('viewBox'),viewBox);
        assert.equal(writes.length,0,'Trail SVG stays unchanged while the retained unit line moves');
        assert.notEqual(surface.host.style.getPropertyValue('transform'),initial);
        assert.ok(surface.host.style.getPropertyValue('transform').includes('scaleX('));
        assert.equal(spider.trail.getAttribute('opacity'),'1');
        assert.equal(surface.motion.style.getPropertyValue('opacity'),'0.42');
        assert.equal(spider.trailPoints.length,48);
        assert.deepEqual(spans.at(-1),{from:spider.trailPoints[0],to:spider.trailPoints.at(-1)});
        spider.pose({walk:0});
        if(typeof surface.play==='function') {
          assert.equal(spider.trailOpacity,0);
          assert.deepEqual(surface.animation.effect.getKeyframes(),[{opacity:.42},{opacity:0}]);
          assert.equal(surface.motion.style.getPropertyValue('transition'),'none',
            'A mounted trail fades through the shared finite-animation budget');
        } else {
          assert.equal(surface.motion.style.getPropertyValue('opacity'),'0');
          assert.equal(surface.motion.style.getPropertyValue('transition-duration'),'2.4s');
        }
        doc.media.change(true);
        assert.equal(surface.motion.style.getPropertyValue('opacity'),'0');
        assert.equal(surface.animation??null,null,'Reduced motion cancels and releases an unfinished fade');
        assert.equal(spider.trail.getAttribute('d'),'M0 0H1');
        assert.equal(surface.svg.getAttribute('viewBox'),viewBox);assert.equal(writes.length,0);
        assert.deepEqual(spans.at(-1).from,spans.at(-1).to);
        assert.equal(doc.frames.size,0);
      } finally {spider.destroy();layers.destroy();}
    """.replace("__LAYERS__", json.dumps((WEB / "layers.js").as_uri())), setup="""
      const forbidden=()=>{throw new Error('The retained trail must not own a frame loop or timer');};
      doc.defaultView.requestAnimationFrame=forbidden;
      globalThis.requestAnimationFrame=forbidden;
      globalThis.setTimeout=forbidden;globalThis.setInterval=forbidden;
    """)
