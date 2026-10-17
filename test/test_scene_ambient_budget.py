"""Ambient detail sampling uses one bounded timer and never SVG timelines."""

import json
import subprocess
from pathlib import Path

import pytest

from test_scene_r1 import NODE, WEB, scene_check


def ambient_check(source):
    if NODE is None:
        pytest.skip("未安装 Node.js")
    result = subprocess.run(
        [NODE, "--input-type=module", "--eval", (
            "import assert from 'node:assert/strict';\n"
            f"import {{documentFromHTML}} from {json.dumps((Path(__file__).parent / 'frontend_dom.mjs').as_uri())};\n"
            f"import {{AmbientLoop,discrete}} from {json.dumps((WEB / 'ambient.js').as_uri())};\n"
            "const doc=documentFromHTML('<html><body><svg id=\"ambient\"></svg></body></html>');\n"
            "const win=doc.defaultView, timers=new Map();let now=0,seq=0;\n"
            "win.performance.now=()=>now;win.setTimeout=(fn,delay)=>{timers.set(++seq,{fn,at:now+delay});return seq;};win.clearTimeout=id=>timers.delete(id);\n"
            "const advance=ms=>{const end=now+ms;while(true){const due=[...timers].filter(([,t])=>t.at<=end).sort((a,b)=>a[1].at-b[1].at)[0];if(!due)break;now=due[1].at;timers.delete(due[0]);due[1].fn();}now=end;};\n"
            "const loop=new AmbientLoop(win),svg=doc.getElementById('ambient');\n"
            + source + "\nloop.destroy();\n"
        )], text=True, capture_output=True, timeout=15,
    )
    assert result.returncode == 0, result.stderr


def test_one_timer_samples_at_most_four_times_a_second_and_releases_everything():
    ambient_check(r"""
      loop.setPaused(false);
      const items=Array.from({length:40},(_,i)=>{const target=doc.createElementNS('svg','rect');svg.appendChild(target);target.setAttribute('width','10');return {target,control:discrete(target,'progress','width',['10','20','30','40','50'],1,{loop})};});
      let writes=0;for(const item of items){const original=item.target.setAttribute.bind(item.target);item.target.setAttribute=(key,value)=>{if(key==='width')writes++;original(key,value);};item.control.setActive(true);}
      assert.equal(timers.size,1,'All detail animations share one timer');
      writes=0;advance(999);assert.ok(writes<=40*3,'No more than four sampling ticks/second');
      advance(1);assert.equal(timers.size,1);assert.ok(writes<=40*4);
      loop.setPaused(true);assert.equal(timers.size,0);const before=writes;advance(4000);assert.equal(writes,before);
      loop.setPaused(false);assert.equal(timers.size,1);
      loop.destroy();assert.equal(timers.size,0);assert.equal(loop.controls.size,0);
      assert.equal(svg.querySelectorAll('animate').length+svg.querySelectorAll('animateTransform').length,0);
    """)


def test_inactive_hidden_and_detached_details_do_not_change_attributes():
    ambient_check(r"""
      loop.setPaused(false);
      const targets=Array.from({length:4},()=>{const item=doc.createElementNS('svg','rect');svg.appendChild(item);item.setAttribute('width','10');return item;});
      const controls=targets.map(target=>discrete(target,'detail','width',['10','20','30','40','50'],1,{loop}));
      controls[0].setActive(true);controls[1].setActive(false);controls[2].setActive(true);targets[2].setAttribute('display','none');controls[3].setActive(true);targets[3].remove();
      advance(500);assert.equal(targets[0].getAttribute('width'),'30');
      for(const target of targets.slice(1))assert.equal(target.getAttribute('width'),'10');
      assert.equal(loop.controls.size,3,'Detached detail controls are pruned');
      controls[0].setActive(false);assert.equal(timers.size,0,'No timer for inactive or hidden details');
      targets[2].removeAttribute('display');controls[2].setActive(true);assert.equal(timers.size,1);
      const finite=discrete(targets[1],'expression','opacity',['0','1','0'],.5,{loop,once:true});
      finite.play();advance(501);assert.equal(targets[1].getAttribute('data-running'),'false');
      finite.destroy();controls[2].destroy();assert.equal(timers.size,0);
    """)


def test_offscreen_observer_stops_the_shared_timer_and_unregisters_targets():
    ambient_check(r"""
      loop.destroy();let notify,disconnects=0;const watched=new Set();
      win.IntersectionObserver=class{
        constructor(callback){notify=callback;}
        observe(target){watched.add(target);}unobserve(target){watched.delete(target);}
        disconnect(){watched.clear();disconnects++;}
      };
      const offscreenLoop=new AmbientLoop(win),target=doc.createElementNS('svg','rect');
      svg.appendChild(target);target.setAttribute('width','10');
      const control=discrete(target,'progress','width',['10','20','30','40','50'],1,{loop:offscreenLoop});
      offscreenLoop.setPaused(false);control.setActive(true);assert.equal(timers.size,1);
      notify([{target,isIntersecting:false}]);assert.equal(timers.size,0);
      advance(1500);assert.equal(target.getAttribute('width'),'10');
      notify([{target,isIntersecting:true}]);assert.equal(timers.size,1);
      advance(250);assert.notEqual(target.getAttribute('width'),'10');
      control.destroy();assert.equal(timers.size,0);assert.equal(watched.size,0);
      offscreenLoop.destroy();assert.equal(disconnects,1);
    """)


def test_scene_has_zero_smil_and_one_shared_loop_for_all_environment_details():
    scene_check(r"""
      scene.update({sessions:[session(1),session(2,{phase:'evaluating'}),session(3,{phase:'prod'}),session(4,{phase:'idle',idle:true})],totals:{sims_pending:2},events:[]});
      assert.ok(scene.ambient.controls.size>20,'One shared loop owns charts, hands, zzz and LEDs');
      for(const tag of ['animate','animateTransform','animateMotion','set'])assert.equal(scene.canvas.querySelectorAll(tag).length,0,tag+' is forbidden');
      const css=[...scene.layers.root.querySelectorAll('style')].find(style=>style.textContent.includes('wq-session-overlay')).textContent;
      assert.ok(!css.includes('wq-silk-sway'),'The web does not sway');
      for(const name of ['wq-hand-left','wq-hand-right','wq-zzz','wq-progress','wq-eval-bar','wq-radar-sweep','wq-cabinet-led','wq-expression-a','wq-expression-b'])assert.ok(!new RegExp(`\\.${name}[^{}]*\\{[^{}]*animation:`).test(css));
      assert.equal(doc.frames.size,0,'Ambient details do not request animation frames');
      const initial=scene.ambient.controls.size;
      for(let i=0;i<30;i++)scene.update({sessions:[session(i*4+10),session(i*4+11,{phase:'evaluating'}),session(i*4+12,{phase:'prod'}),session(i*4+13,{phase:'idle',idle:true})],events:[]});
      assert.equal(scene.ambient.controls.size,initial,'Replacing sessions releases obsolete detail controllers');
      assert.equal(scene.ambient.timer,null,'Quiet scenes do not retain a timer');
    """)


def test_environment_is_quiet_initially_then_pauses_fifteen_seconds_after_an_event():
    scene_check(r"""
      let now=100;doc.defaultView.performance.now=()=>now;
      const base={day:'2026-10-16',sessions:[session(1)],totals:{sims_pending:1},events:[]};
      scene.update(base);assert.equal(scene.environmentQuiet,true);assert.equal(scene.ambient.paused,true);
      assert.equal(scene.layers.root.getAttribute('data-paused'),'true');
      scene.update({...base,events:[{seq:1,kind:'sim_submit',pid:1,n:1,exprs:['rank(close)']}]});
      assert.equal(scene.environmentQuiet,false);assert.equal(scene.ambient.paused,false);
      assert.equal(scene.layers.root.getAttribute('data-paused'),'false');
      now=15099;scene.checkActivity();assert.equal(scene.environmentQuiet,false);
      now=15100;scene.checkActivity();assert.equal(scene.environmentQuiet,true);assert.equal(scene.environmentIdle,false);
      assert.equal(scene.ambient.paused,true);assert.equal(scene.ambient.timer,null);assert.equal(scene.layers.root.getAttribute('data-paused'),'true');
      now=60100;scene.checkActivity();assert.equal(scene.environmentIdle,true);
      scene.update({...base,events:[{seq:2,kind:'precheck_fail',pid:1}]});assert.equal(scene.environmentQuiet,false);assert.equal(scene.environmentIdle,false);
      doc.hidden=true;doc.dispatch('visibilitychange');assert.equal(scene.ambient.paused,true);
      doc.hidden=false;doc.dispatch('visibilitychange');assert.equal(scene.ambient.paused,false);
      doc.media.change(true);assert.equal(scene.ambient.paused,true);
    """)


def test_expression_bubble_presentation_opacity_is_visible_during_sampled_fade():
    scene_check(r"""
      let now=100;doc.defaultView.performance.now=()=>now;
      const advance=ms=>{for(let elapsed=0;elapsed<ms;elapsed+=250){now+=Math.min(250,ms-elapsed);doc.sampleAnimations();}};
      const base={day:'2026-10-16',sessions:[session(1)],events:[]};
      scene.update(base);const entry=scene.sessionNodes.get('1');
      assert.equal(entry.bubble.getAttribute('opacity'),'0','Default presentation is transparent before any event');
      const css=[...scene.layers.root.querySelectorAll('style')].find(style=>style.textContent.includes('wq-session-overlay')).textContent;
      assert.ok(!css.includes('.wq-bubble{opacity:0}'),'CSS must not override JS presentation opacity');
      assert.ok(css.includes('.wq-session-overlay[data-active="true"] .wq-bubble{opacity:1}'),'Hover can still expose the expression');
      const update=(seq,expression)=>scene.update({...base,sessions:[session(1,{last_expr:expression})],events:[{seq}]});
      update(1,'rank(volume)');assert.equal(entry.bubble.getAttribute('opacity'),'0');
      advance(250);assert.ok(Number(entry.bubble.getAttribute('opacity'))>0,'The first sampled fade becomes visible');
      advance(750);assert.ok(Number(entry.bubble.getAttribute('opacity'))>.9);
      advance(3250);assert.equal(Number(entry.bubble.getAttribute('opacity')),0,'The finite fade ends transparently');
      assert.equal(entry.bubble.className,'wq-bubble');
      update(2,'rank(returns)');advance(250);assert.ok(Number(entry.bubble.getAttribute('opacity'))>0);
      entry.expressionMotion.stop();assert.equal(entry.bubble.getAttribute('opacity'),'0','Stopping restores the transparent presentation value');
    """)
