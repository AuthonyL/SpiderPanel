"""Controlled-clock checks for the spider's visible event sequences."""

import json
from datetime import datetime
from pathlib import Path
import pytest

from test_frontend import WEB, run_js, dashboard_check
from test_scene_r1 import scene_check
from SpiderPanel.demo import DemoFeeder
from SpiderPanel.state import FactoryState


def silk_check(source):
    run_js("import assert from 'node:assert/strict';\n"
           f"import {{documentFromHTML,descendants}} from {json.dumps((Path(__file__).parent/'frontend_dom.mjs').as_uri())};\n"
           f"import {{AlphaWeb,webPoint,routePoint,WEB_CENTER,WEB_RADII,WEB_SPOKES,WEB_SPIRALS,COCOON_LIMIT,SCREEN_CONTENT}} from {json.dumps((WEB/'silk.js').as_uri())};\n"
           "const doc=documentFromHTML('<html><body><svg id=\"scene\"></svg></body></html>');\n"
           "const opened=[];const web=new AlphaWeb(doc.getElementById('scene'),{id:'test',onAlpha:id=>opened.push(id)});\n"
           "try {\n" + source + "\n} finally {web.destroy();}\n")


def test_web_has_bounded_clickable_cocoons_at_silk_intersections():
    silk_check("""
      const alphas=Array.from({length:150},(_,i)=>({id:`alpha${i}`,status:i%2?'candidate':'done'}));
      web.update(alphas);
      assert.equal(web.spokes.length,16);
      assert.equal(web.nodes.size,60);
      const occupied=new Set();
      for(const entry of web.nodes.values()){
        assert.ok(!occupied.has(entry.slot));occupied.add(entry.slot);
        assert.deepEqual(entry.position,webPoint(entry.slot));
        assert.equal(entry.dot.tagName,'ellipse');
      }
      const first=web.nodes.get('alpha0'),before=descendants(web.root);
      for(let i=0;i<100;i++)web.update(alphas);
      assert.equal(descendants(web.root),before);assert.equal(web.nodes.get('alpha0'),first);
      first.g.dispatch('click');assert.deepEqual(opened,['alpha0']);
      web.hold(['alpha0']);assert.equal(first.g.getAttribute('opacity'),'0');
      web.release(['alpha0']);assert.equal(first.g.getAttribute('opacity'),'0.7');
      for(let round=0;round<20;round++)web.update(alphas.map(a=>({...a,id:`${round}_${a.id}`})),true);
      assert.equal(web.nodes.size,60);assert.ok(web.retiring.size<=8);
      web.settle();assert.equal(web.retiring.size,0);
      web.update([]);assert.equal(web.nodes.size,0);
    """)


def test_restored_ellipse_keeps_six_spiral_turns_and_sixty_cocoons_inside_clip():
    silk_check(r"""
      assert.deepEqual(WEB_RADII,{x:221,y:60});
      assert.deepEqual(WEB_CENTER,{x:595,y:153});
      assert.equal(WEB_SPOKES,16);assert.equal(WEB_SPIRALS,6);assert.equal(COCOON_LIMIT,60);
      const {left,top,right,bottom}=SCREEN_CONTENT;
      assert.deepEqual(SCREEN_CONTENT,{left:354,top:92,right:836,bottom:229});
      const spokes=web.spokes.map(node=>node.getAttribute('d').match(/[-+\d.eE]+/g).map(Number));
      for(const [x,y,endX,endY]of spokes){
        assert.equal(x,WEB_CENTER.x);assert.equal(y,WEB_CENTER.y);
        const radius=Math.hypot((endX-x)/WEB_RADII.x,(endY-y)/WEB_RADII.y);
        assert.ok(Math.abs(radius-1)<1e-8);
        assert.ok(endX>=left&&endX<=right&&endY>=top&&endY<=bottom);
      }
      assert.equal((web.spiral.getAttribute('d').match(/L/g)||[]).length,WEB_SPOKES*WEB_SPIRALS);
      web.update(Array.from({length:100},(_,i)=>({id:`round${i}`,status:'done'})));
      assert.equal(web.nodes.size,60);
      const clippedHitSlots=[];
      for(const {slot,position:{x,y},g}of web.nodes.values()){
        const radius=(2+Math.floor(slot/16)+slot%16/16)/6,angle=slot%16/16*Math.PI*2-Math.PI/2;
        assert.equal(x,595+221*radius*Math.cos(angle));
        assert.equal(y,153+60*radius*Math.sin(angle));
        assert.ok(x-7>=left&&x+7<=right&&y-5>=top&&y+5<=bottom,
          'The complete visible cocoon and halo fit inside the restored screen');
        assert.equal(g.children[0].getAttribute('rx'),'9');
        assert.equal(g.children[0].getAttribute('ry'),'7');
        if(y-7<top)clippedHitSlots.push(slot);
      }
      // The original slot 63 clips 0.855px of its transparent hit ellipse.
      assert.deepEqual(clippedHitSlots,[63]);
      assert.equal(doc.frames.size,0);
    """)


def test_cocoon_tooltip_uses_two_decimal_sharpe_and_handles_missing_metrics():
    silk_check("""
      web.update([{id:'precise',status:'done',sharpe:1.8000000000000003},
        {id:'missing',status:'done',sharpe:null}]);
      const precise=web.nodes.get('precise'),missing=web.nodes.get('missing');
      assert.equal(precise.g.getAttribute('aria-label'),'precise，done，Sharpe 1.80');
      assert.ok(precise.title.textContent.includes('Sharpe 1.80\\n'));
      assert.ok(!precise.title.textContent.includes('1.8000000000000003'));
      assert.ok(missing.title.textContent.includes('Sharpe —'));
    """)


def test_rejected_cocoons_are_quiet_after_processing_but_keep_their_click_targets():
    silk_check("""
      const statuses=['eval_failed','prod_blocked','rejected','done','eval_passed','prod_ok','candidate'];
      web.update(statuses.map(status=>({id:status,status})));
      for(const id of statuses.slice(0,3)){
        const entry=web.nodes.get(id);
        assert.equal(entry.g.getAttribute('opacity'),'0.25');
        assert.equal(entry.glyph.getAttribute('transform'),'scale(0.6)');
        assert.equal(entry.halo.getAttribute('display'),'none');
        assert.equal(entry.halo.getAttribute('filter'),null);
        assert.equal(entry.g.children[0].getAttribute('rx'),'9','The click target must not shrink');
        entry.g.dispatch('click');assert.equal(opened.at(-1),id);
        web.beginProcessing([id]);
        assert.equal(entry.g.getAttribute('opacity'),'1');
        assert.equal(entry.glyph.getAttribute('transform'),'scale(1)');
        web.hold([id]);web.update(statuses.map(status=>({id:status,status})));
        assert.equal(entry.g.getAttribute('opacity'),'0','Snapshot updates cannot reveal a held cocoon');
        web.release([id]);assert.equal(entry.g.getAttribute('opacity'),'1');
        web.endProcessing([id]);assert.equal(entry.g.getAttribute('opacity'),'0.25');
      }
      assert.equal(web.nodes.get('done').g.getAttribute('opacity'),'0.7');
      for(const id of ['eval_passed','prod_ok','candidate'])assert.equal(web.nodes.get(id).g.getAttribute('opacity'),'1');
      assert.equal(web.nodes.get('candidate').halo.getAttribute('filter'),null);
      assert.ok(web.nodes.get('candidate').halo.getAttribute('fill').startsWith('url('));
      web.beginProcessing(['rejected']);web.beginProcessing(['rejected']);
      web.endProcessing(['rejected']);assert.equal(web.nodes.get('rejected').g.getAttribute('opacity'),'1');
      web.settle();assert.equal(web.nodes.get('rejected').g.getAttribute('opacity'),'0.25');
      assert.equal(web.processing.size,0);assert.equal(doc.frames.size,0);
    """)


def test_sorting_strands_lead_to_review_board_and_counts_reconcile_to_snapshot():
    silk_check("""
      const source=webPoint(10);
      for(const route of ['reject','pass','review']){
        assert.deepEqual(routePoint(route,0,source),source);
        const point=routePoint(route,1,source);
        assert.ok(Number.isFinite(point.x)&&Number.isFinite(point.y));
        if(route==='review')assert.ok(point.x>=903&&point.y<=220);
      }
      const lastNote={x:1040,y:203};
      assert.deepEqual(routePoint('review',1,source,lastNote),lastNote,
        'The review strand must finish at the actual note, not always slot one');
      web.syncCounts({totals:{eval_passed:3,candidates:1},rejects:{eval_fail:4}});
      assert.deepEqual(web.displayCounts,{reject:4,pass:3,review:1});
      web.syncCounts({totals:{eval_passed:4,candidates:2},rejects:{eval_fail:5}},true);
      assert.deepEqual(web.displayCounts,{reject:4,pass:3,review:1});
      web.arrive('pass');assert.equal(web.displayCounts.pass,4);
      web.arrive('review');assert.equal(web.displayCounts.review,2);
      web.settle();assert.equal(web.displayCounts.reject,5);
      assert.equal(doc.frames.size,0,'Idle silk animation uses CSS, not a permanent RAF');
    """)


CLOCK = """
      let now=100;doc.defaultView.performance.now=()=>now;
      function advance(ms,inspect=()=>{}){
        const end=now+ms;
        while(now<end){now=Math.min(end,now+20);
          doc.sampleAnimations();
          const callbacks=[...doc.frames];doc.frames.clear();
          for(const [,callback]of callbacks)callback(now);
          inspect();
        }
      }
      function until(predicate,maxMs=10000,inspect=()=>{}){
        const deadline=now+maxMs;
        while(!predicate()&&now<deadline)advance(20,inspect);
        assert.ok(predicate(),'The action must finish within its bounded travel window');
      }
"""


def test_empty_office_keeps_the_spider_waiting_on_the_web_without_a_js_loop():
    scene_check("""
      scene.update({alphas:[],sessions:[],review:[],events:[]});
      assert.equal(scene.networkNodes.size,0);
      assert.equal(scene.spider.root.getAttribute('data-idle'),'true');
      assert.notEqual(scene.spider.root.getAttribute('display'),'none');
      assert.equal(scene.screenWaiting.getAttribute('display'),'inline');
      assert.ok(scene.screenWaiting.textContent.includes('WAITING FOR MINERS'));
      assert.equal(scene.sessionNodes.size,0);assert.equal(doc.frames.size,0);
    """)


def test_screen_content_clips_the_web_cocoons_spider_and_drag_silk_only():
    scene_check("""
      const clipOf=node=>{for(let el=node;el;el=el.parentNode){const clip=el.getAttribute('clip-path');if(clip)return clip;}return null;};
      const reference=`url(#${scene.id}-screen-clip)`;
      for(const node of [scene.web.layer])
        assert.equal(clipOf(node),reference,'All web artwork must share a stationary content clip');
      scene.update({alphas:[{id:'clipped',status:'done'}],events:[]});
      for(const surface of [scene.web.wireSurface,scene.spider.positionSurface,scene.spider.trailSurface,scene.web.nodes.get('clipped').surface])
        assert.equal(surface.host.parentNode,scene.layers.webClip,'Sprite artwork uses the same content bounds via the HTML overflow clip');
      const clip=scene.root.querySelector(`#${scene.id}-screen-clip`),rect=clip.querySelector('rect');
      assert.equal(clip.getAttribute('clipPathUnits'),'userSpaceOnUse');
      const top=Number(rect.getAttribute('y')),bottom=top+Number(rect.getAttribute('height'));
      const clipStyle=scene.layers.webClip.style;
      assert.equal(clipStyle.getPropertyValue('left'),`${rect.getAttribute('x')}px`);
      assert.equal(clipStyle.getPropertyValue('top'),`${top}px`);
      assert.equal(clipStyle.getPropertyValue('width'),`${rect.getAttribute('width')}px`);
      assert.equal(clipStyle.getPropertyValue('height'),`${rect.getAttribute('height')}px`);
      assert.ok(top>=91,'The clip starts below the ALPHAS title rule');
      assert.equal(bottom,SCREEN_CONTENT.bottom);
      assert.ok(bottom<Number(scene.web.countNodes.pass.getAttribute('y')),'The clip ends before sorting labels');
      assert.equal(clipOf(scene.networkTitle),null);
      assert.equal(clipOf(scene.web.strands),null,'The REVIEW strand must still reach the note board');
      assert.equal(scene.spider.scale,1.4);
    """)


def test_sorting_and_capture_keep_the_body_and_contact_targets_inside_the_screen():
    scene_check(CLOCK + """
      const alphas=Array.from({length:60},(_,i)=>({id:`edge${i}`,status:'eval_failed'}));
      const base={day:'2026-10-16',sessions:[session(1)],alphas,events:[]};scene.update(base);
      const rect=scene.root.querySelector(`#${scene.id}-screen-clip`).querySelector('rect');
      const left=Number(rect.getAttribute('x')),top=Number(rect.getAttribute('y'));
      const right=left+Number(rect.getAttribute('width')),bottom=top+Number(rect.getAttribute('height'));
      let contact=0,walking=0;
      const inspect=()=>{
        const spider=scene.spider,{x,y,reach,walk}=spider.state;
        assert.ok(x>=left+66&&x<=right-66,'Center keeps a hip-to-foot clearance at both sides');
        assert.ok(y>=top+66&&y<=bottom-66,'Center cannot follow an upper cocoon into the title bar');
        if(walk>0)walking++;
        if(reach){
          contact++;
          assert.ok(reach.x>=left+10&&reach.x<=right-10);
          assert.ok(reach.y>=top+10&&reach.y<=bottom-10);
          assert.ok(Math.hypot(spider.tip.x-reach.x,spider.tip.y-reach.y)<.01);
        }
      };
      for(let i=0;i<60;i++){
        scene.update({...base,events:[{seq:i+1,kind:i%2?'eval_fail':'candidate',pid:1,alphas:[alphas[i].id]}]});
        advance(2100,inspect);
      }
      scene.update({...base,events:[{seq:61,kind:'sim_done',pid:1,n:8,alphas:alphas.slice(0,8).map(a=>a.id)}]});
      advance(5500,inspect);
      until(()=>!scene.narrative.working,40000,inspect);
      assert.ok(contact>100&&walking>100);
      const far=scene.spider.targetAt({x:-1000,y:-1000});
      assert.deepEqual(far,{x:left+10,y:top+10});
      scene.spider.pose({x:-1000,y:-1000,reach:{x:-1000,y:-1000}});inspect();
      assert.deepEqual(scene.spider.tip,far);scene.spider.rest();
      assert.equal(doc.frames.size,0);
    """)


def test_two_hundred_mixed_events_return_transient_nodes_to_the_idle_baseline():
    scene_check(CLOCK + """
      const alphas=Array.from({length:60},(_,i)=>({id:`stable${i}`,status:i<3?'candidate':'done'}));
      const base={day:'2026-10-16',sessions:[session(1)],alphas,review:alphas.slice(0,3),events:[]};
      scene.update(base);
      const baseline=descendants(scene.canvas),surfaces=scene.layers.surfaces.size,trail=scene.spider.trail;
      const transientClasses=['wq-submit-paper','wq-event-ball','wq-sort-cocoon','wq-prod-beam',
        'wq-crumpled-paper','wq-smoke','wq-bounced-paper'];
      const kinds=['sim_submit','sim_done','eval_pass','eval_fail','prod_ok','prod_block',
        'candidate','rejected','precheck_fail','sim_fail','error'];
      const seen=new Set();let peak=baseline;
      for(let i=0;i<200;i++){
        // Replace old non-candidates too, so retiring cocoons are checked along
        // with the job-owned balls, papers, beams, smoke and confetti.
        const rows=alphas.map((a,index)=>index<3?a:{...a,id:`round${Math.floor(i/11)}_${a.id}`});
        const kind=kinds[i%kinds.length],ids=kind==='sim_done'?rows.slice(0,8).map(a=>a.id):[rows[i%3].id];
        scene.update({...base,alphas:rows,events:[{seq:i+1,kind,pid:1,n:8,alphas:ids,exprs:['rank(close < 2)']}]});
        advance(5500,()=>{
          peak=Math.max(peak,descendants(scene.canvas));
          for(const job of scene.narrative.effects)seen.add(job.kind);
        });
        until(()=>!scene.narrative.working,6000);
        advance(2400); // The reused drag silk fades after the final physical step.
        assert.equal(scene.effectLayer.children.length,0,`Event ${i+1} left an effect group behind`);
        assert.equal(scene.layers.surfaces.size,surfaces,'Temporary HTML surfaces must be removed from their registry too');
        assert.equal(descendants(scene.canvas),baseline,`Event ${i+1} did not return to the exact DOM baseline`);
        for(const name of transientClasses)assert.equal(scene.canvas.querySelectorAll('.'+name).length,0);
        assert.equal(scene.narrative.active,null);assert.equal(scene.narrative.queue.length,0);
        assert.equal(scene.narrative.parallel.length,0);assert.equal(scene.web.held.size,0);
        assert.equal(scene.web.retiring.size,0);
        assert.equal(scene.web.processing.size,0);assert.equal(doc.frames.size,0);
        assert.equal(scene.spider.trail,trail);assert.equal(scene.canvas.querySelectorAll('.wq-spider-trail').length,1);
        assert.equal(scene.spider.trailSurface.motion.style.getPropertyValue('opacity'),'0');assert.ok(scene.spider.trailPoints.length<=48);
      }
      for(const kind of kinds)assert.ok(seen.has(kind),`The test must animate ${kind}, not just merge it away`);
      assert.ok(peak>baseline,'The baseline check must follow real temporary node allocations');
      scene.destroy();assert.equal(descendants(doc.getElementById('scene')),1);assert.equal(doc.frames.size,0);
    """)


def test_capture_requires_front_leg_contact_then_reveals_each_cocoon():
    scene_check(CLOCK + """
      const base={day:'2026-10-16',sessions:[session(1)],alphas:[],events:[]};
      scene.update(base);
      const alphas=['a','b'].map(id=>({id,pid:1,sim:'s',status:'done'}));
      scene.update({...base,alphas,events:[{seq:1,kind:'sim_done',pid:1,sim:'s',n:2,alphas:['a','b']}]});
      assert.ok(scene.narrative,'The scene needs one serial narrative controller');
      assert.equal(scene.narrative.active.kind,'sim_done');
      assert.equal(scene.networkNodes.get('a').g.getAttribute('opacity'),'0');
      let touched=false,moved=false;
      advance(4200,()=>{
        const active=scene.narrative.active;
        if(!active)return;
        moved ||= Math.abs(scene.spider.state.x-595)>20;
        for(const particle of active.particles||[])if(particle.attached){
          touched=true;
          assert.ok(Math.hypot(particle.position.x-scene.spider.tip.x,particle.position.y-scene.spider.tip.y)<.01,
            'An attached ball must follow the actual articulated foot');
        }
      });
      assert.ok(touched,'A ball must spend visible time attached to the leg');
      assert.ok(moved,'The spider must crawl out along a radial thread');
      assert.equal(scene.networkNodes.get('a').g.getAttribute('opacity'),'0.7');
      assert.equal(scene.networkNodes.get('b').g.getAttribute('opacity'),'0.7');
      assert.equal(scene.narrative.active,null);
      assert.equal(doc.frames.size,0,'No RAF stays alive after the work ends');
    """)


def test_rejected_cocoon_stays_visible_during_sort_then_becomes_dim():
    scene_check(CLOCK + """
      const base={day:'2026-10-16',sessions:[session(1)],events:[],alphas:[{id:'fail',status:'done'}]};
      scene.update(base);
      scene.update({...base,alphas:[{id:'fail',status:'eval_failed'}],
        events:[{seq:1,kind:'eval_fail',pid:1,alpha:'fail',alphas:['fail']}]});
      const entry=scene.networkNodes.get('fail');
      assert.equal(entry.g.getAttribute('opacity'),'0');
      advance(1000);
      assert.equal(scene.narrative.active.kind,'eval_fail');
      assert.equal(entry.glyph.getAttribute('transform'),'scale(1)');
      const moving=scene.effectLayer.querySelector('.wq-sort-cocoon');
      assert.ok(moving);assert.notEqual(moving.getAttribute('opacity'),'0');
      until(()=>!scene.narrative.working);
      assert.equal(entry.g.getAttribute('opacity'),'0.25');
      assert.equal(entry.glyph.getAttribute('transform'),'scale(0.6)');
      assert.equal(entry.halo.getAttribute('filter'),null);
      assert.equal(scene.narrative.active,null);assert.equal(doc.frames.size,0);
    """)


def test_serial_sort_radar_and_review_flip_have_visible_intermediate_states():
    scene_check(CLOCK + """
      const alpha={id:'pick',pid:1,status:'candidate',sharpe:1.8,prod:.42};
      const base={day:'2026-10-16',sessions:[session(1)],alphas:[alpha],review:[],events:[]};
      scene.update(base);
      scene.update({...base,review:[alpha],events:[
        {seq:1,kind:'eval_pass',pid:1,alpha:'pick',alphas:['pick']},
        {seq:2,kind:'prod_ok',pid:1,alpha:'pick',alphas:['pick']},
        {seq:3,kind:'candidate',pid:1,alpha:'pick',alphas:['pick']}]});
      assert.equal(scene.narrative.active.kind,'eval_pass');
      assert.equal(scene.narrative.queue.length,2);
      assert.equal(scene.noteNodes.get('pick').surface.motion.style.getPropertyValue('opacity'),'0');
      until(()=>scene.narrative.active?.kind==='prod_ok');
      assert.equal(scene.narrative.active.kind,'prod_ok');
      assert.equal(scene.noteNodes.get('pick').surface.motion.style.getPropertyValue('opacity'),'0',
        'Finishing an earlier evaluation cannot reveal a queued candidate note');
      assert.ok(scene.effectLayer.querySelector('.wq-prod-beam'));
      until(()=>scene.narrative.active?.kind==='candidate');
      const surface=scene.noteNodes.get('pick').surface;
      until(()=>surface.motion.classList.contains('wq-note-flip'));
      assert.equal(surface.motion.style.getPropertyValue('opacity'),'1');
      assert.ok(surface.motion.classList.contains('wq-note-flip'));
      until(()=>!scene.narrative.working);assert.equal(scene.narrative.active,null);
    """)


def test_papers_failures_queue_overflow_and_visibility_cleanup_are_bounded():
    scene_check(CLOCK + """
      const base={day:'2026-10-16',sessions:[session(1)],alphas:[],events:[]};scene.update(base);
      const events=[
        {seq:1,kind:'sim_submit',pid:1,n:8,exprs:['rank(close < 2)']},
        {seq:2,kind:'precheck_fail',pid:1},
        {seq:3,kind:'sim_fail',pid:1,sim:'failed'}];
      scene.update({...base,events});
      assert.equal(scene.effectLayer.querySelectorAll('.wq-submit-paper').length,8);
      assert.ok(scene.effectLayer.querySelector('.wq-bounced-paper'));
      assert.equal(scene.narrative.pending[0].kind,'sim_fail','A full flight lane waits instead of allocating beyond twelve sprites');
      advance(1900);
      assert.ok(scene.effectLayer.querySelector('.wq-smoke'));
      const burst=Array.from({length:80},(_,i)=>({seq:i+4,kind:'eval_fail',pid:1,alpha:`x${i}`,alphas:[`x${i}`]}));
      scene.update({...base,events:burst});
      assert.ok(scene.narrative.queue.length+(scene.narrative.active?1:0)<=12);
      assert.ok(scene.narrative.coalesced>0);
      assert.ok(scene.narrative.active?.kind==='summary'||scene.narrative.queue.some(job=>job.kind==='summary'));
      assert.ok(scene.effectLayer.children.length<=10);
      doc.hidden=true;doc.dispatch('visibilitychange');
      assert.equal(doc.frames.size,0);assert.equal(scene.effectLayer.children.length,0);
      assert.equal(scene.narrative.queue.length,0);assert.equal(scene.narrative.active,null);
      doc.hidden=false;doc.dispatch('visibilitychange');assert.equal(doc.frames.size,0);
      doc.media.change(true);scene.update({...base,events:[{seq:100,kind:'sim_done',n:8}]});
      assert.equal(doc.frames.size,0);assert.equal(scene.effectLayer.children.length,0);
    """)


def test_footer_retains_three_safe_captions_and_reuses_nodes():
    dashboard_check("""
      const footer=doc.getElementById('event-captions');
      assert.ok(footer,'The narrative needs a visible subtitle line');
      const nodes=[...footer.children],before=descendants(doc.documentElement);
      for(let seq=1;seq<=100;seq++)app.renderCaption({seq,kind:'candidate',text:`<alpha ${seq}> → 等你复核`});
      assert.equal(app.captions.length,3);assert.equal(footer.children.length,3);
      assert.equal(footer.children[0].textContent,'<alpha 100> → 等你复核');
      assert.equal(footer.children[1].textContent,'<alpha 99> → 等你复核');
      assert.ok(footer.children.every((node,index)=>node===nodes[index]));
      assert.equal(descendants(doc.documentElement),before);
      assert.equal(doc.documentElement.querySelectorAll('alpha').length,0);
      for(const [kind,color] of Object.entries({sim_done:'#33d1ff',eval_pass:'#3ddc84',prod_ok:'#3ddc84',
        eval_fail:'#ff4d5e',prod_block:'#ff4d5e',rejected:'#ff4d5e',candidate:'#ff5fa2',
        sim_submit:'#e8ecf4',precheck_fail:'#ffab2e',sim_fail:'#ffab2e',error:'#ffab2e'})){
        app.renderCaption({kind,text:'new caption'});
        const dot=footer.children[0].querySelector('.caption-dot');
        assert.equal(dot.style.getPropertyValue('--caption-color'),color);
        assert.ok(footer.children[0].classList.contains('caption-current'));
        assert.ok(footer.children[1].classList.contains('caption-previous'));
        assert.ok(footer.children[2].classList.contains('caption-previous'));
      }
      const status=doc.getElementById('floor-status');
      assert.equal(status.parentNode,footer.parentNode,'Session statistics keep their dedicated footer slot');
      assert.ok(status.textContent);
      assert.equal(descendants(doc.documentElement),before,'Colored caption dots must reuse nodes too');
      app.renderCaption(null);assert.equal(app.captions.length,0);
    """)


def test_simulator_lights_track_batch_count_without_one_dom_node_per_batch():
    scene_check("""
      const size=descendants(scene.canvas);
      scene.update({totals:{sims_pending:3}});
      assert.equal(scene.cabinetLamps.filter(lamp=>lamp.getAttribute('data-lit')==='true').length,3);
      scene.update({totals:{sims_pending:37}});
      assert.equal(scene.cabinetCount.textContent,'37');
      assert.equal(scene.cabinetPacked.g.getAttribute('display'),'inline');
      assert.equal(scene.cabinetLampGroup.getAttribute('display'),'none');
      const packed=scene.cabinetPacked;
      assert.equal(packed.columns*packed.fullRows+packed.remainder,37);
      scene.update({totals:{sims_pending:10000}});
      assert.equal(descendants(scene.canvas),size,'Packed SVG lights cannot allocate nodes for every batch');
      scene.update({totals:{sims_pending:0}});
      assert.ok(scene.cabinetLamps.every(lamp=>lamp.getAttribute('data-lit')==='false'));
    """)


def test_overflow_immediately_reconciles_all_cocoons_notes_and_counters():
    scene_check(CLOCK + """
      const alphas=Array.from({length:20},(_,i)=>({id:`a${i}`,pid:1,status:'done'}));
      const base={day:'2026-10-16',sessions:[session(1)],alphas,review:[],events:[]};scene.update(base);
      const review=alphas.map(a=>({...a,status:'candidate'}));
      scene.update({...base,alphas:review,review,totals:{candidates:20,eval_passed:20},events:
        review.map((a,index)=>({seq:index+1,kind:'candidate',pid:1,alpha:a.id,alphas:[a.id]}))});
      assert.equal(scene.narrative.active.kind,'summary');
      assert.equal(scene.narrative.queue.length,0);
      assert.equal(scene.narrative.hiddenNotes.size,0);
      assert.ok([...scene.noteNodes.values()].every(note=>note.surface.motion.style.getPropertyValue('opacity')==='1'));
      assert.ok([...scene.networkNodes.values()].every(entry=>entry.g.getAttribute('opacity')==='1'));
      assert.equal(scene.web.displayCounts.review,20);
      advance(800);assert.equal(scene.narrative.active,null);assert.equal(doc.frames.size,0);
    """)


def test_shredded_confetti_starts_after_the_rejected_paper_reaches_the_hopper():
    scene_check(CLOCK + """
      const base={day:'2026-10-16',sessions:[session(1)],events:[]};scene.update(base);
      scene.update({...base,events:[{seq:1,kind:'precheck_fail',pid:1},{seq:2,kind:'sim_fail',pid:1}]});
      let shredded=0;
      advance(2000,()=>{
        for(const job of scene.narrative.parallel){
          if(job.confetti.some(piece=>Number(piece.surface.animation?.sampled.opacity??piece.surface.motion.style.getPropertyValue('opacity'))>0)){
            shredded++;
            assert.equal(job.particles[0].surface.motion.style.getPropertyValue('opacity'),'0');
            assert.ok(Math.hypot(job.particles[0].position.x-145,job.particles[0].position.y-(441+LOWER_SHIFT))<.01,
              'Confetti cannot appear while the rejected paper is still falling');
          }
        }
      });
      assert.ok(shredded>0);
    """)


def test_sorting_leg_pushes_then_retracts_instead_of_freezing_at_the_cocoon():
    scene_check(CLOCK + """
      const alpha={id:'flick',status:'eval_passed'};
      const base={day:'2026-10-16',alphas:[alpha],events:[]};scene.update(base);
      scene.update({...base,events:[{seq:1,kind:'eval_pass',alphas:['flick']}]});
      until(()=>scene.narrative.active?.stage==='grip');const contact={...scene.spider.tip};
      assert.ok(Math.hypot(contact.x-scene.web.position('flick').x,contact.y-scene.web.position('flick').y)<.01);
      until(()=>scene.narrative.active?.stage==='flick');advance(100);
      assert.ok(Math.hypot(scene.spider.tip.x-contact.x,scene.spider.tip.y-contact.y)>1,
        'The front leg must visibly flick the cocoon onto its sorting strand');
      advance(450);
      assert.ok(Math.hypot(scene.spider.tip.x-contact.x,scene.spider.tip.y-contact.y)>5,
        'The front leg must retract after releasing the cocoon');
    """)


@pytest.mark.parametrize("opened_at", [0, 4])
def test_real_demo_story_reaches_every_visible_stage_within_thirty_seconds(tmp_path, opened_at):
    clock = [datetime(2026, 10, 15, 15).timestamp()]
    feeder = DemoFeeder(tmp_path / "log", clock=lambda: clock[0])
    feeder.seed_history()
    state = FactoryState(datetime.fromtimestamp(clock[0]).date(), clock=feeder.clock)
    snapshots, offset = [], 0
    path = tmp_path / "log" / "2026-10-15.jsonl"
    try:
        for second in range(opened_at + 31):
            clock[0] = feeder._start + second
            feeder.tick()
            with path.open("rb") as file:
                file.seek(offset)
                for row in file:
                    state.feed(json.loads(row))
                offset = file.tell()
            snap = state.snapshot("demo")
            if second >= opened_at:
                snapshots.append({key: snap[key] for key in (
                    "day", "alphas", "sessions", "review", "events", "timeline", "best", "totals", "rejects", "cards")})
        data = tmp_path / "demo-snapshots.json"
        data.write_text(json.dumps(snapshots), encoding="utf-8")
    finally:
        state.close()
    scene_check(CLOCK + f"const snapshots=JSON.parse((await import('node:fs')).readFileSync({json.dumps(str(data))},'utf8'));\n" + """
      const seen=new Set(),phases=new Set();let caught=0,flipped=false;
      function inspect(){
        const director=scene.narrative,job=director.active;
        if(job){seen.add(job.kind);phases.add(`${job.kind}:${job.g.getAttribute('data-phase')}`);
          if(job.kind==='sim_done')caught=Math.max(caught,job.particles.filter(p=>p.attached||p.received).length);
        }
        for(const parallel of director.parallel)seen.add(parallel.kind);
        flipped ||= scene.noteNodes.get('DEMO_ONBOARD_0')?.surface.motion.classList.contains('wq-note-flip')===true;
        assert.ok(doc.frames.size<=1);assert.ok(director.queue.length+(job?1:0)<=12);
      }
      snapshots.forEach((snapshot,index)=>{if(index)advance(1000,inspect);scene.update(snapshot);inspect();});
      for(const kind of ['sim_submit','sim_done','eval_pass','eval_fail','prod_block','prod_ok','candidate','rejected','precheck_fail','sim_fail'])
        assert.ok(seen.has(kind),`Missing visible demo event ${kind}`);
      assert.ok(caught>=8,'All eight demo alphas must be grabbed, not just one representative');
      for(const kind of ['eval_pass','eval_fail','prod_block','candidate','rejected'])assert.ok(phases.has(`${kind}:sort`));
      assert.ok(flipped,'The review note must unfold before the 30-second demo ends');
      assert.equal(scene.narrative.coalesced,0,'The onboarding story should be slow enough to narrate in full');
    """)


def test_sixty_seconds_of_churn_keeps_scene_queues_nodes_and_frames_bounded():
    scene_check(CLOCK + """
      let seq=0;
      const base={day:'2026-10-16',sessions:[session(1)],events:[]};
      scene.update({...base,alphas:Array.from({length:60},(_,i)=>({id:`seed${i}`,status:'done'}))});
      const warm=descendants(scene.canvas);
      for(let second=1;second<=60;second++){
        const alphas=Array.from({length:70},(_,i)=>({id:`batch${Math.floor(second/3)}_${i}`,status:i<3?'candidate':'done'}));
        const kinds=['sim_submit','sim_done','eval_pass','eval_fail','prod_block','candidate','rejected','sim_fail'];
        const kind=kinds[second%kinds.length],ids=alphas.slice(0,kind==='sim_done'?8:1).map(a=>a.id);
        scene.update({...base,alphas,review:alphas.slice(0,3),events:[{seq:++seq,kind,pid:1,alphas:ids,n:8,exprs:['rank(close < 3)']}]});
        advance(1000,()=>{
          assert.ok(doc.frames.size<=1);
          assert.ok(scene.narrative.queue.length+(scene.narrative.active?1:0)<=12);
          assert.ok(scene.narrative.parallel.length<=8);
          assert.ok(scene.web.processing.size<=12*8,'Processing appearance tracks only bounded queued work');
          assert.ok(scene.spider.trailPoints.length<=48,'The drag silk cannot retain the walking history');
        });
        assert.equal(scene.networkNodes.size,60);assert.ok(scene.web.retiring.size<=8);
        assert.ok(scene.effectLayer.children.length<=9);assert.ok(scene.noteNodes.size<=9);
        assert.ok(descendants(scene.canvas)<warm+450,'Transient DOM cannot grow with event history');
      }
      doc.hidden=true;doc.dispatch('visibilitychange');
      assert.equal(scene.effectLayer.children.length,0);assert.equal(doc.frames.size,0);
      assert.equal(scene.web.held.size,0);assert.equal(scene.narrative.hiddenNotes.size,0);
      assert.equal(scene.web.processing.size,0);
      assert.equal(scene.spider.trailPoints.length,0);
      assert.equal(scene.web.retiring.size,0);
    """)
