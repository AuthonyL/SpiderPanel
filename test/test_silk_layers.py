"""Cocoons and sorting counters use bounded surfaces outside the cached SVG."""

import json
from pathlib import Path
import shutil
import subprocess

import pytest


WEB = Path(__file__).resolve().parents[1] / "web"
NODE = shutil.which("node")


def silk_layers_check(source):
    if NODE is None:
        pytest.skip("未安装 Node.js")
    script = (
        "import assert from 'node:assert/strict';\n"
        f"import {{documentFromHTML}} from {json.dumps((Path(__file__).parent / 'frontend_dom.mjs').as_uri())};\n"
        f"import {{AlphaWeb,SCREEN_CONTENT}} from {json.dumps((WEB / 'silk.js').as_uri())};\n"
        f"import {{SceneLayers}} from {json.dumps((WEB / 'layers.js').as_uri())};\n"
        "const doc=documentFromHTML('<html><body><svg id=\"scene\"></svg></body></html>');\n"
        "const svg=doc.getElementById('scene'),opened=[];\n"
        "const layers=new SceneLayers(svg,'test',SCREEN_CONTENT);\n"
        "const web=new AlphaWeb(svg,{id:'test',onAlpha:id=>opened.push(id)});\n"
        "const collect=node=>[node,...node.children.flatMap(collect)];\n"
        "const inside=(node,ancestor)=>{while(node){if(node===ancestor)return true;node=node.parentNode;}return false;};\n"
        "try {\n" + source + "\n} finally {web.destroy();layers.destroy();}\n"
    )
    result = subprocess.run([NODE, "--input-type=module", "--eval", script],
                            text=True, capture_output=True, timeout=15)
    assert result.returncode == 0, result.stderr


def test_layer_attachment_moves_existing_and_new_cocoons_out_of_the_background():
    silk_layers_check("""
      web.update([{id:'existing',status:'candidate'}]);
      const first=web.nodes.get('existing'),wires=web.wires;
      web.attachLayers(layers);
      web.update([{id:'existing',status:'candidate'},...Array.from({length:59},(_,i)=>({id:`alpha${i}`,status:'done'}))]);
      assert.equal(web.nodes.get('existing'),first);
      assert.equal(web.wires,wires);assert.equal(wires.parentNode,web.wireSurface.svg);assert.ok(inside(wires,layers.webClip));
      assert.ok(!wires.classList.contains('wq-animated'));
      assert.ok(!wires.classList.contains('wq-silk-sway'));
      assert.equal(svg.querySelectorAll('.wq-cocoon').length,0);
      assert.equal(layers.surfaces.size,64);
      for(const entry of web.nodes.values()){
        assert.ok(inside(entry.surface.host,layers.webClip));
        assert.equal(entry.g.parentNode,entry.surface.svg);
        assert.equal(entry.g.getAttribute('transform'),'translate(0 0)');
        assert.equal(entry.surface.point.x,entry.position.x);assert.equal(entry.surface.point.y,entry.position.y);
        assert.ok(entry.surface.box.width<=32&&entry.surface.box.height<=28);
      }
      for(const node of Object.values(web.countNodes))assert.ok(!inside(node,svg));
      first.g.dispatch('click');first.g.dispatch('keydown',{key:'Enter'});
      first.g.dispatch('keydown',{key:' '});assert.deepEqual(opened,['existing','existing','existing']);
      web.attachLayers(layers);assert.equal(layers.surfaces.size,64);
      assert.equal(doc.frames.size,0);
    """)


def test_mounted_statuses_keep_clickable_processing_and_held_appearance_without_svg_filters():
    silk_layers_check("""
      web.attachLayers(layers);
      web.update([{id:'candidate',status:'candidate'},{id:'failed',status:'eval_failed'}]);
      const candidate=web.nodes.get('candidate'),failed=web.nodes.get('failed');
      assert.equal(candidate.halo.getAttribute('filter'),null);
      assert.equal(candidate.surface.motion.style.getPropertyValue('filter'),'');
      assert.equal(candidate.surface.halo.getAttribute('display'),'inline');
      assert.ok(candidate.surface.svg.querySelectorAll('radialGradient').length>0);
      assert.equal(failed.g.getAttribute('opacity'),'0.25');
      assert.equal(failed.glyph.getAttribute('transform'),'scale(0.6)');
      failed.g.dispatch('click');assert.deepEqual(opened,['failed']);
      web.beginProcessing(['failed']);assert.equal(failed.g.getAttribute('opacity'),'1');
      assert.equal(failed.glyph.getAttribute('transform'),'scale(1)');
      web.hold(['failed']);web.update([{id:'candidate',status:'candidate'},{id:'failed',status:'eval_failed'}]);
      assert.equal(failed.g.getAttribute('opacity'),'0');
      web.release(['failed']);assert.equal(failed.g.getAttribute('opacity'),'1');
      web.endProcessing(['failed']);assert.equal(failed.g.getAttribute('opacity'),'0.25');
      web.hold(['candidate']);assert.equal(candidate.surface.halo.getAttribute('opacity'),'0','A held cocoon must not leave its glow behind on the web');
      web.release(['candidate']);assert.equal(candidate.surface.halo.getAttribute('opacity'),'1');
      web.update([{id:'candidate',status:'done'},{id:'failed',status:'eval_failed'}]);
      assert.equal(candidate.surface.motion.style.getPropertyValue('filter'),'');
      assert.equal(candidate.surface.halo.getAttribute('display'),'none');
      for(const entry of web.nodes.values())assert.ok(collect(entry.g).every(node=>!node.getAttribute('filter')));
    """)


def test_retiring_cocoons_remove_whole_surfaces_on_completion_eviction_and_settle():
    silk_layers_check("""
      web.attachLayers(layers);
      web.update(Array.from({length:60},(_,i)=>({id:`first${i}`,status:'done'})));
      const old=web.nodes.get('first59'),oldSurface=old.surface;
      web.update(Array.from({length:60},(_,i)=>({id:`next${i}`,status:'done'})),true);
      assert.equal(web.retiring.size,8);assert.equal(layers.surfaces.size,72);
      assert.ok(web.retiring.has(old.g));
      assert.ok(oldSurface.motion.classList.contains('wq-cocoon-retire'));
      assert.ok(!old.g.classList.contains('wq-animated'));
      assert.ok(!old.g.classList.contains('wq-hit'),'Retiring artwork cannot override pointer-events=none through the global hit rule');
      oldSurface.motion.dispatch('animationend');
      assert.equal(oldSurface.host.parentNode,null);assert.ok(!layers.surfaces.has(oldSurface));
      assert.ok(!web.retiring.has(old.g));
      for(let round=0;round<20;round++){
        web.update(Array.from({length:60},(_,i)=>({id:`round${round}_${i}`,status:'candidate'})),true);
        assert.ok(layers.surfaces.size<=72);assert.ok(web.retiring.size<=8);
      }
      web.hold(['round19_0']);web.beginProcessing(['round19_1']);
      web.settle();assert.equal(web.retiring.size,0);assert.equal(layers.surfaces.size,64);
      assert.equal(web.held.size,0);assert.equal(web.processing.size,0);
      web.update([]);assert.equal(layers.surfaces.size,4);
      web.destroy();assert.equal(layers.surfaces.size,0);assert.equal(web.nodes.size,0);
    """)


def test_counter_arrivals_animate_html_and_unchanged_snapshots_do_not_repaint_svg():
    silk_layers_check("""
      web.attachLayers(layers);
      const rows=Array.from({length:60},(_,i)=>({id:`alpha${i}`,status:i%2?'candidate':'eval_failed'}));
      web.update(rows);
      web.syncCounts({totals:{eval_passed:2,candidates:3},rejects:{eval_fail:4}},true);
      const writes=[];
      for(const node of collect(svg)){
        const set=node.setAttribute.bind(node);node.setAttribute=(key,value)=>{writes.push({node,key,value});set(key,value);};
      }
      web.arrive('pass');assert.equal(web.countNodes.pass.textContent,'1');
      const surface=web.countNodes.pass.spriteSurface;
      assert.ok(surface.motion.classList.contains('wq-sort-count'));
      assert.equal(web.countNodes.pass.getAttribute('class'),null);
      surface.motion.dispatch('animationend');assert.ok(!surface.motion.classList.contains('wq-sort-count'));
      assert.equal(writes.length,0,'Arrival must not modify the cached background');
      web.settle();
      const repeated=[];
      for(const node of [...collect(svg),...[...layers.surfaces].flatMap(surface=>collect(surface.svg))]){
        const set=node.setAttribute.bind(node);node.setAttribute=(key,value)=>{repeated.push({node,key,value});set(key,value);};
        const descriptor=Object.getOwnPropertyDescriptor(Object.getPrototypeOf(node),'textContent');
        Object.defineProperty(node,'textContent',{get(){return descriptor.get.call(this);},
          set(value){repeated.push({node,key:'textContent',value});descriptor.set.call(this,value);}});
      }
      for(let i=0;i<20;i++){web.update(rows);web.settle();}
      assert.equal(repeated.length,0,'Stable snapshots and settlement leave all existing artwork unchanged');
      assert.equal(doc.frames.size,0);
    """)
