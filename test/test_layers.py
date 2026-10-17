"""Coordinate conversion and compositor-surface lifecycle without a browser."""
import json
from pathlib import Path

from test_frontend import WEB, run_js


def layers_check(source):
    run_js("import assert from 'node:assert/strict';\n"
           f"import {{documentFromHTML}} from {json.dumps((Path(__file__).parent/'frontend_dom.mjs').as_uri())};\n"
           f"import {{SceneLayers}} from {json.dumps((WEB/'layers.js').as_uri())};\n"
           f"import {{SCENE_WIDTH,SCENE_HEIGHT,SCENE_TOP,SCREEN_CONTENT}} from {json.dumps((WEB/'geometry.js').as_uri())};\n"
           "const doc=documentFromHTML('<html><body><div id=\"stage\"><svg id=\"scene\"></svg></div></body></html>');\n"
           "let observer;doc.defaultView.ResizeObserver=class{constructor(fn){this.fn=fn;observer=this;}observe(target){this.target=target;}disconnect(){this.disconnected=true;}};\n"
           "const svg=doc.getElementById('scene'),stage=doc.getElementById('stage');\n"
           "const bounds=SCREEN_CONTENT;\n"
           "const layers=new SceneLayers(svg,'coordinates',bounds);\n"
           "const near=(a,b)=>assert.ok(Math.abs(a-b)<1e-8,`${a} != ${b}`);\n"
           "try {\n" + source + "\n} finally {layers.destroy();}\n")


def test_resize_preserves_viewbox_letterboxing_and_native_mobile_scroll():
    layers_check("""
      const surface=layers.surface({left:-14,top:-12,width:28,height:24},{local:true,parent:layers.webClip});
      surface.move(595,153);const transform=surface.host.style.getPropertyValue('transform');
      assert.equal(observer.target,layers.canvas);
      for(const [width,height]of [[1264,530],[1050,525],[820,410]]){
        layers.canvas.getBoundingClientRect=()=>({width,height});observer.fn();
        const s=Math.min(width/SCENE_WIDTH,height/SCENE_HEIGHT),m=layers.mapping;
        near(m.scale,s);near(m.x,(width-SCENE_WIDTH*s)/2);near(m.y,(height-SCENE_HEIGHT*s)/2-SCENE_TOP*s);
        near(595*s+m.x,(width-SCENE_WIDTH*s)/2+595*s);
        near(153*s+m.y,(height-SCENE_HEIGHT*s)/2+(153-SCENE_TOP)*s);
        assert.equal(surface.host.style.getPropertyValue('transform'),transform,'Resize updates one parent transform, not every sprite');
      }
      stage.scrollLeft=220;
      assert.equal(layers.canvas.parentNode,stage);
      assert.equal(layers.root.parentNode,svg.parentNode,'Native horizontal scrolling carries both layers together');
      assert.equal(doc.frames.size,0);
      layers.destroy();assert.equal(observer.disconnected,true);assert.equal(svg.parentNode,stage);
      assert.equal(stage.children.length,1);assert.equal(layers.surfaces.size,0);
    """)


def test_local_world_and_clipped_surfaces_share_the_same_world_coordinates():
    layers_check("""
      const local=layers.surface({left:-14,top:-12,width:28,height:24},{local:true,parent:layers.webClip});
      local.move(595,153);
      assert.equal(local.host.style.getPropertyValue('transform'),'translate(227px,49px) rotate(0deg) scale(1)');
      assert.equal(local.host.style.getPropertyValue('transform-origin'),'14px 12px');
      const world=layers.surface({left:581,top:141,width:28,height:24},{parent:layers.webClip});
      assert.equal(world.host.style.getPropertyValue('transform'),local.host.style.getPropertyValue('transform'));
      assert.equal(world.svg.getAttribute('viewBox'),'581 141 28 24');
      assert.equal(world.host.style.getPropertyValue('transform-origin'),'50% 50%','A world viewBox must never become an off-surface CSS pivot');
      for(const element of [world.host,world.motion,world.svg]){
        assert.equal(element.style.getPropertyValue('width'),'28px');assert.equal(element.style.getPropertyValue('height'),'24px');
      }
      const line=layers.surface({left:0,top:0,width:1,height:1},{parent:layers.webClip});
      line.span({x:500,y:150},{x:560,y:150});
      assert.equal(line.host.style.getPropertyValue('transform'),'translate(146px,57px) rotate(0deg) scaleX(60)');
      assert.equal(line.host.style.getPropertyValue('transform-origin'),'0px 1px');
      const box=line.svg.getAttribute('viewBox');line.span({x:500,y:150},{x:500,y:210});
      assert.equal(line.svg.getAttribute('viewBox'),box);assert.ok(line.host.style.getPropertyValue('transform').includes('rotate(90deg)'));
      local.remove();local.remove();world.remove();line.remove();assert.equal(layers.surfaces.size,0);
    """)


def test_promotions_have_a_hard_budget_and_finite_motion_preempts_ambient():
    layers_check(r"""
      let now=100;doc.defaultView.performance.now=()=>now;
      const actors=Array.from({length:30},()=>layers.surface({left:-20,top:-20,width:40,height:40},{local:true}));
      actors.forEach(surface=>surface.animate('wq-avatar-floating wq-animated'));
      assert.equal(layers.promotions.size,22);
      assert.equal(actors.filter(surface=>surface.motion.style.getPropertyValue('animation')==='none').length,8);
      const flights=Array.from({length:22},()=>layers.surface({left:-5,top:-5,width:10,height:10},{local:true}));
      for(const surface of flights){
        surface.play([{transform:'translate(0px,0px)',opacity:1},{transform:'translate(50px,40px)',opacity:0}],{duration:200});
        assert.equal(layers.promotions.size,22);
      }
      assert.ok(actors.every(surface=>surface.motion.style.getPropertyValue('animation')==='none'));
      assert.ok(flights.every(surface=>layers.promotions.has(surface.motion)));
      const overflow=layers.surface({left:0,top:0,width:10,height:10});
      let finished=0;assert.equal(overflow.play([{opacity:1},{opacity:0}],{duration:200,onfinish:()=>finished++}),null);
      assert.equal(finished,1);assert.equal(overflow.motion.style.getPropertyValue('opacity'),'0');
      now=300;doc.sampleAnimations();
      assert.equal(doc.animations.size,0);assert.equal(layers.promotions.size,22);
      assert.ok(flights.every(surface=>surface.motion.style.getPropertyValue('will-change')==='auto'));
      layers.pause(true);assert.equal(layers.promotions.size,0);
      layers.pause(false);assert.equal(layers.promotions.size,22);
      for(const surface of [...layers.surfaces])surface.remove();assert.equal(layers.promotions.size,0);
    """)
