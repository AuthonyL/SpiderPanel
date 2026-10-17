"""Scene layering and seat geometry regressions; rendering is checked in Chromium."""

import json
from pathlib import Path
import shutil
import subprocess

import pytest


WEB = Path(__file__).resolve().parents[1] / "web"
NODE = shutil.which("node")


def scene_check(source):
    if NODE is None:
        pytest.skip("未安装 Node.js")
    setup = (
        "import assert from 'node:assert/strict';\n"
        f"import {{documentFromHTML,descendants}} from {json.dumps((Path(__file__).parent / 'frontend_dom.mjs').as_uri())};\n"
        f"import {{FactoryScene}} from {json.dumps((WEB / 'scene.js').as_uri())};\n"
        f"import {{SCENE_WIDTH,SCENE_HEIGHT,SCENE_TOP,SCENE_VIEWBOX,LOWER_SHIFT,SCREEN_CONTENT,WEB_CENTER,WEB_RADII,CAPTURE_CENTER,capturePoint,RADAR_ORIGIN,SHREDDER_ORIGIN}} from {json.dumps((WEB / 'geometry.js').as_uri())};\n"
        "const doc=documentFromHTML('<html><body><svg id=\"scene\"></svg></body></html>');\n"
        "const hovered=[]; const opened=[];\n"
        "const scene=new FactoryScene(doc.getElementById('scene'), {onSessionHover:(data)=>hovered.push(data?.pid??null),onAlpha:id=>opened.push(id)});\n"
        "const session=(pid,extra={})=>({pid,label:`会话 ${pid}`,shape:'ghost',color:'#e1eaf5',phase:'simulating',last_expr:'rank(close)',...extra});\n"
        "try {\n"
    )
    result = subprocess.run(
        [NODE, "--input-type=module", "--eval", setup + source + "\n} finally {scene.destroy();}\n"],
        text=True, capture_output=True, timeout=15,
    )
    assert result.returncode == 0, result.stderr


def test_populated_office_unused_monitors_are_short_dark_and_silent():
    scene_check(r"""
      assert.ok(scene.stations.every(s=>s.phase.textContent==='STANDBY'));
      const fullTransform=scene.stations[0].monitor.getAttribute('transform');
      scene.update({sessions:[session(1)]});
      assert.equal(scene.stations[0].monitor.getAttribute('transform'),fullTransform);
      for(const station of scene.stations.slice(1)){
        assert.equal(station.phase.textContent,'');
        assert.equal(station.load.textContent,'');
        assert.equal(station.monitor.getAttribute('data-powered'),'off');
        assert.ok(Number(station.monitor.getAttribute('opacity'))<.6);
        const matrix=station.monitor.getAttribute('transform').match(/-?\d*\.?\d+/g).map(Number);
        assert.ok(matrix[3]<.7,'Unused screens have a shorter silhouette');
        assert.ok(!station.monitor.textContent.includes('OFFLINE'));
        assert.ok(!station.monitor.textContent.includes('STANDBY'));
      }
      scene.update({sessions:Array.from({length:6},(_,i)=>session(i))});
      assert.ok(scene.stations.every(s=>s.monitor.getAttribute('transform')===fullTransform));
      scene.update(null);
      assert.ok(scene.stations.every(s=>s.phase.textContent==='STANDBY'));
      assert.ok(scene.stations.every(s=>s.monitor.getAttribute('transform')===fullTransform));
    """)


def test_seated_portraits_clear_the_next_row_and_room_art_fits_crop():
    scene_check(r"""
      assert.equal(scene.svg.getAttribute('viewBox'),SCENE_VIEWBOX);
      assert.equal(scene.svg.getAttribute('preserveAspectRatio'),'xMidYMid meet');
      scene.update({sessions:Array.from({length:6},(_,i)=>session(i,{idle:i===0,phase:i===0?'idle':'simulating'}))});
      assert.ok(scene.stations[3].y-scene.stations[0].y>=155);
      for(const [index,entry] of [...scene.sessionNodes.values()].entries()){
        const station=scene.stations[index];
        assert.equal(entry.g.getAttribute('transform'),'translate(0 0)');
        assert.equal(entry.overlay.getAttribute('transform'),'translate(0 0)');
        for(const surface of [entry.surface,entry.overlaySurface]){
          assert.deepEqual(surface.point,{x:station.x+24,y:station.y+42,angle:0,scale:1});
          assert.equal(surface.host.isConnected,true);
        }
        assert.equal(entry.g.parentNode,entry.surface.svg);
        assert.equal(entry.surface.host.parentNode,scene.sessionLayer);
        assert.equal(Number(entry.portrait.getAttribute('width')),62);
        assert.equal(Number(entry.portrait.getAttribute('height')),67);
        const bottom=entry.surface.point.y+Number(entry.portrait.getAttribute('y'))+67;
        if(index<3)assert.ok(bottom<scene.stations[index+3].y-103,'A full second-row monitor clears the first-row portrait');
        else assert.ok(bottom<SCENE_TOP+SCENE_HEIGHT);
        assert.ok(entry.portrait.querySelector('.wq-headset')||entry.portrait.querySelector('.wq-aerial'));
      }
      assert.equal(scene.sessionNodes.get('0').sleep.textContent,'z z z');
      assert.ok(Number(scene.sessionNodes.get('0').sleep.getAttribute('font-size'))>=15);
      assert.ok(scene.canvas.textContent.includes('REJECTED · 淘汰'));
      assert.ok(!scene.canvas.textContent.includes('PAPER HANDS'));
      const floor=scene.architecture.querySelector('polygon').getAttribute('points').match(/-?\d+(?:\.\d+)?/g).map(Number);
      assert.ok(floor.filter((_,i)=>i%2).every(y=>y>=SCENE_TOP&&y<=SCENE_TOP+SCENE_HEIGHT));
      assert.ok(Number(scene.radarStatus.getAttribute('y'))+LOWER_SHIFT<SCENE_TOP+SCENE_HEIGHT);
    """)


def test_restored_screen_and_room_sprites_share_one_world_geometry():
    scene_check(r"""
      assert.equal(SCENE_WIDTH,1200);assert.equal(SCENE_HEIGHT,600);assert.equal(SCENE_TOP,35);
      assert.equal(scene.svg.getAttribute('viewBox'),SCENE_VIEWBOX);
      assert.deepEqual(WEB_RADII,{x:221,y:60});
      assert.deepEqual(WEB_CENTER,{x:595,y:153});
      assert.equal(LOWER_SHIFT,0);
      assert.deepEqual(scene.spider.home,scene.spider.centerAt(WEB_CENTER));
      assert.deepEqual(scene.spider.home,{x:595,y:158});
      assert.equal(scene.furniture.getAttribute('transform'),null);
      assert.equal(scene.cabinet.getAttribute('transform'),null);
      assert.equal(scene.runner.getAttribute('transform'),null);
      assert.deepEqual(scene.cabinetIntake,{x:268,y:280});
      assert.deepEqual(scene.cabinetOutput,{x:309,y:270});
      assert.equal(scene.radarDishSurface.point.y,RADAR_ORIGIN.y);
      assert.equal(scene.shredderSurface.point.y,SHREDDER_ORIGIN.y);
      assert.equal(scene.stations[0].y,362+LOWER_SHIFT);
      assert.equal(scene.stations[3].y,520+LOWER_SHIFT);
      assert.equal(Number(scene.reviewAvatar.getAttribute('y')),247+LOWER_SHIFT);
      scene.update({sessions:[session(1)],alphas:[{id:'shifted',status:'candidate'}],review:[{id:'shifted'}],events:[]});
      const note=scene.noteNodes.get('shifted');
      assert.deepEqual(note.position,{x:926,y:135});
      assert.equal(note.surface.box.top,121+LOWER_SHIFT-5);
      assert.equal(scene.sessionPositions.get('1').y,scene.stations[0].y-60);
      scene.update({alphas:[{id:'shifted',status:'candidate'}],events:[{seq:1,kind:'sim_done',n:1,alphas:['shifted']}]});
      const job=scene.narrative.active;
      assert.deepEqual(job.particles[0].edge,capturePoint(0));
      assert.deepEqual(job.travel.plan.frames.at(-1),{...scene.spider.centerAt(CAPTURE_CENTER),offset:1});
      assert.equal(doc.frames.size,1,'Only the active narrative owns a display-frame callback');
    """)


def test_screen_sparkline_keeps_a_hundred_buckets_inside_the_lower_footer():
    scene_check(r"""
      scene._timeline(Array.from({length:100},(_,index)=>({best_sharpe:index/10})),{sharpe:9.9});
      const path=scene.sparkline.getAttribute('d');
      assert.equal((path.match(/L/g)||[]).length,99);
      const coords=path.match(/-?\d+(?:\.\d+)?/g).map(Number);
      assert.equal(coords[0],491);assert.equal(coords.at(-2),685);
      assert.equal(coords[1],255+LOWER_SHIFT);assert.equal(coords.at(-1),243+LOWER_SHIFT);
      assert.ok(coords.filter((_,index)=>index%2).every(y=>y>SCREEN_CONTENT.bottom&&y<SCENE_TOP+SCENE_HEIGHT));
      assert.equal(doc.frames.size,0);
    """)


def test_session_overlays_stay_above_room_and_keep_hover_expression_and_cleanup():
    scene_check("""
      scene.update({day:'2026-10-16',sessions:[session(1)],events:[{seq:1,kind:'candidate',pid:1}]});
      const entry=scene.sessionNodes.get('1');
      const overlay=entry.overlay;
      assert.ok(overlay,'Session annotations have a separate overlay');
      const overlayLayer=scene.sessionOverlay;
      assert.equal(scene.canvas.children[0],scene.svg);
      assert.equal(scene.canvas.children.at(-1),scene.layers.root);
      const layers=[...scene.layers.root.children];
      for(const layer of [scene.sessionLayer,scene.effectLayer,scene.noteLayer]){
        assert.ok(layers.indexOf(overlayLayer)>layers.indexOf(layer),'Annotations paint above miners, review papers and event flights');
      }
      const infrastructure=layers.find(layer=>layer.getAttribute('data-layer')==='infrastructure');
      assert.ok(infrastructure&&layers.indexOf(infrastructure)<layers.indexOf(overlayLayer));
      assert.equal(overlayLayer.tagName,'div');
      assert.equal(overlay.parentNode,entry.overlaySurface.svg);
      assert.equal(entry.overlaySurface.host.parentNode,overlayLayer);
      assert.equal(entry.overlaySurface.host.getAttribute('data-interactive'),'true');
      assert.equal(entry.overlaySurface.host.style.getPropertyValue('pointer-events'),'','Only the badge and portrait can receive pointer input; blank sprite bounds pass through');
      assert.equal(entry.overlaySurface.svg.getAttribute('aria-hidden'),'false');
      assert.equal(entry.badge.parentNode,overlay);
      assert.equal(entry.bubble.parentNode,overlay);
      assert.equal(entry.bubble.getAttribute('pointer-events'),'none');
      assert.equal(entry.badge.getAttribute('pointer-events'),'all');
      assert.equal(scene.effects.length,0,'Initial event history never plays');
      entry.g.dispatch('pointerenter');
      assert.equal(hovered.at(-1),1);
      assert.equal(overlay.getAttribute('data-active'),'true');
      entry.g.dispatch('pointerleave');
      assert.equal(hovered.at(-1),null);
      assert.equal(overlay.getAttribute('data-active'),'false');
      entry.badge.dispatch('pointerenter');assert.equal(hovered.at(-1),1);
      entry.badge.dispatch('pointermove');assert.equal(hovered.at(-1),1);
      entry.badge.dispatch('pointerleave');assert.equal(hovered.at(-1),null);
      entry.g.dispatch('focus');assert.equal(overlay.getAttribute('data-active'),'true');
      entry.g.dispatch('blur');assert.equal(overlay.getAttribute('data-active'),'false');
      scene.update({day:'2026-10-16',sessions:[session(1,{last_expr:'rank(open < close)'})],events:[{seq:2}]});
      assert.equal(scene.sessionNodes.get('1'),entry);
      assert.equal(entry.expr.textContent,'rank(open < close)');
      assert.ok(entry.bubble.className.includes('wq-expression-'));
      entry.bubble.dispatch('animationend');assert.equal(entry.bubble.className,'wq-bubble');
      doc.media.change(true);
      scene.update({day:'2026-10-16',sessions:[session(1,{last_expr:'rank(high)'})],events:[{seq:3,kind:'candidate',pid:1}]});
      assert.equal(scene.effects.length,0);
      assert.equal(doc.frames.size,0);
      assert.equal(entry.bubble.className,'wq-bubble');
      const size=descendants(scene.canvas),surfaces=scene.layers.surfaces.size;
      const listenerCount=[...doc.listeners.values()].reduce((n,s)=>n+s.size,0);
      entry.g.dispatch('focus');
      for(let i=0;i<40;i++){
        scene.update({sessions:[session(i+10)],events:[]});
        assert.equal(hovered.at(-1),null,'Removing a hovered session clears its tooltip');
        assert.equal(descendants(scene.canvas),size);
        assert.equal(scene.layers.surfaces.size,surfaces,'Replacing a miner releases both old surfaces');
        assert.equal(overlayLayer.children.length,1);
      }
      assert.equal(overlay.isConnected,false);
      assert.equal(entry.surface.removed,true);
      assert.equal(entry.overlaySurface.removed,true);
      assert.equal([...doc.listeners.values()].reduce((n,s)=>n+s.size,0),listenerCount);
      scene.update({sessions:[],events:[]});
      assert.equal(overlayLayer.children.length,0);
      assert.equal(scene.sessionLayer.children.length,0);
      assert.equal(scene.sessionNodes.size,0);
      scene.destroy();
      assert.equal(scene.layers.surfaces.size,0);
      assert.equal(scene.canvas.isConnected,false);
      assert.equal(scene.svg.parentNode===doc.body,true,'Destroy removes the layer wrapper and returns the original SVG');
      assert.equal(doc.frames.size,0);
      assert.equal(doc.media.listeners.size,0);
      assert.equal([...doc.listeners.values()].reduce((n,s)=>n+s.size,0),0);
    """)
