"""Compositor budget checks; only Chromium can verify computed CSS layers.

The browser test serves real local assets through Playwright routes. It never
starts the panel server, contacts WQ, or writes a production log directory.
"""
from datetime import datetime
import json
from pathlib import Path
from urllib.parse import unquote, urlsplit

import pytest

from SpiderPanel.demo import DemoFeeder
from SpiderPanel.state import FactoryState
from test_frontend import WEB
from test_scene_r1 import scene_check
from test_web_narrative import CLOCK


def _asset_route(route):
    """Fulfil all browser requests from local files, including module imports."""
    path = unquote(urlsplit(route.request.url).path)
    target = (WEB / ("index.html" if path == "/" else path.lstrip("/"))).resolve()
    if not target.is_relative_to(WEB.resolve()) or not target.is_file():
        route.fulfill(status=404, body="Not found")
        return
    types = {".html": "text/html", ".css": "text/css", ".js": "text/javascript"}
    body = target.read_bytes()
    if target.name == "index.html":
        body = body.replace(b'<script type="module" src="/app.js"></script>', b"")
    route.fulfill(status=200, body=body, content_type=types.get(target.suffix, "application/octet-stream"))


def _demo_snapshots(tmp_path):
    start = datetime(2026, 10, 16, 15).timestamp()
    now = [start]
    feeder = DemoFeeder(tmp_path / "layer-budget" / "log", clock=lambda: now[0])
    feeder.seed_history()
    state = FactoryState(datetime.fromtimestamp(feeder.clock()).date(), clock=feeder.clock)
    path = feeder.log_dir / f"{state.day.isoformat()}.jsonl"
    position = 0
    snapshots = []
    try:
        for second in range(31):
            now[0] = start + second
            feeder.tick()
            with path.open() as stream:
                stream.seek(position)
                for raw in stream:
                    state.feed(json.loads(raw))
                position = stream.tell()
            snapshots.append(state.snapshot("demo"))
        assert state.bad_lines == 0
        assert {event["kind"] for event in snapshots[-1]["events"]} >= {
            "sim_submit", "sim_done", "eval_pass", "eval_fail", "prod_block",
            "candidate", "precheck_fail", "sim_fail", "prod_ok", "rejected",
        }
        return snapshots
    finally:
        state.close()


def test_two_hundred_events_release_temporary_promotions_and_bound_flights():
    """The structural DOM checks ownership, not computed CSS/compositor state."""
    scene_check(CLOCK + r"""
      const alphas=Array.from({length:60},(_,i)=>({id:`budget${i}`,status:i<3?'candidate':'done'}));
      const base={day:'2026-10-16',sessions:[session(1)],alphas,review:alphas.slice(0,3),events:[]};
      scene.update(base);
      assert.ok(scene.layers.promotions instanceof Set,'Promotions must have a bounded, inspectable owner');
      const baseline=[...scene.layers.surfaces].filter(surface=>surface.ambient).length;
      const kinds=['sim_submit','sim_done','eval_pass','eval_fail','prod_ok','prod_block',
        'candidate','rejected','precheck_fail','sim_fail','error'];
      function temporaryAncestor(node){
        for(let current=node;current;current=current.parentNode)
          if(current.getAttribute?.('data-effect'))return true;
        return false;
      }
      let allocated=false;
      for(let i=0;i<200;i++){
        const kind=kinds[i%kinds.length];
        scene.update({...base,events:[{seq:i+1,kind,pid:1,n:8,
          alphas:kind==='sim_done'?alphas.slice(0,8).map(a=>a.id):[alphas[i%3].id],
          exprs:['rank(close < 2)']}]});
        advance(5500,()=>{
          assert.ok(scene.layers.promotions.size<=22,'Scene promotions reserve three slots for other panels');
          const temporary=[...scene.layers.surfaces].filter(surface=>temporaryAncestor(surface.host));
          allocated ||= temporary.length>0;
          assert.ok(temporary.length<=12,'Simultaneously flying surfaces have a hard twelve-sprite cap');
          for(const surface of temporary){
            assert.ok(Number.isFinite(surface.box.width)&&Number.isFinite(surface.box.height));
            assert.ok(surface.box.width>0&&surface.box.width<=1200);
            assert.ok(surface.box.height>0&&surface.box.height<=SCENE_TOP+SCENE_HEIGHT);
          }
        });
        until(()=>!scene.narrative.working,6000);
        // The last crawl leaves a finite 2.4-second drag-silk fade.
        // Advance its real owner, rather than artificially clearing leases.
        advance(2400);
        assert.equal(scene.effectLayer.children.length,0,`Event ${i+1} retained a temporary effect`);
        assert.ok([...scene.layers.promotions].every(node=>node.isConnected&&!temporaryAncestor(node)));
        assert.ok(scene.layers.promotions.size<=baseline,'Completed events leave only the short-lived environment active');
        assert.equal(doc.frames.size,0);
      }
      assert.ok(allocated,'The cleanup check must follow actual temporary allocations');
      scene.narrative.clear();
      assert.ok([...scene.layers.promotions].every(node=>!temporaryAncestor(node)));
    """)


def test_real_demo_computed_compositing_budget_and_motion_bounds(tmp_path):
    """Sample real computed styles plus active transform/opacity animations.

    This intentionally skips when Chromium cannot start in the macOS sandbox;
    passing structural tests alone does not count as browser verification.
    """
    playwright = pytest.importorskip("playwright.sync_api")
    snapshots = _demo_snapshots(tmp_path)
    errors = []
    with playwright.sync_playwright() as runtime:
        try:
            browser = runtime.chromium.launch(headless=True, timeout=7000)
        except playwright.Error as exc:
            message = str(exc)
            if "MachPortRendezvousServer" in message and "Permission denied" in message:
                reason = "macOS MachPortRendezvousServer: Permission denied (1100)"
            else:
                reason = next((line.strip() for line in message.splitlines() if line.strip()), message)[:300]
            pytest.skip(f"Chromium cannot start in this environment: {reason}")
        try:
            page = browser.new_page(viewport={"width": 1920, "height": 1080}, reduced_motion="no-preference")
            page.on("pageerror", lambda error: errors.append(str(error)))

            # Every resource is fulfilled locally; no DNS or network requests
            # escape this route, including imports and a possible favicon.
            page.route("**/*", _asset_route)
            page.goto("http://panel.test/", wait_until="load")
            page.evaluate("""async () => {
              const root=document.getElementById('factory-app');root.id='factory-test-root';
              const {Dashboard}=await import('/app.js');root.id='factory-app';
              window.budgetApp=new Dashboard(document);
              window.budgetSamples={peak:0,willChangePeak:0,flightPeak:0,maxArea:0,violations:[]};
              window.budgetMeasure=()=>{
                const all=[...document.querySelectorAll('*')], promoted=new Set();
                const smil=document.querySelectorAll('animate,animateTransform,animateMotion,set').length;
                if(smil&&window.budgetSamples.violations.length<12)
                  window.budgetSamples.violations.push({type:'smil-timeline',count:smil});
                for(const el of all)if(getComputedStyle(el).willChange!=='auto')promoted.add(el);
                const willChangeCount=promoted.size;
                for(const animation of document.getAnimations()){
                  if(animation.playState!=='running'||!animation.effect?.target)continue;
                  const frames=animation.effect.getKeyframes();
                  if(frames.some(frame=>'transform'in frame||'opacity'in frame))promoted.add(animation.effect.target);
                }
                const sample=window.budgetSamples;
                const moving=new Set([...promoted,...document.querySelectorAll('[data-running="true"]')]);
                for(const target of moving)for(let el=target;el;el=el.parentElement){
                  const filter=getComputedStyle(el).filter;
                  if(filter!=='none'&&sample.violations.length<12)
                    sample.violations.push({type:'moving-filter',tag:el.tagName,classes:el.getAttribute('class'),filter});
                }
                sample.peak=Math.max(sample.peak,promoted.size);
                sample.willChangePeak=Math.max(sample.willChangePeak,willChangeCount);
                const flights=[...document.querySelectorAll('[data-effect] .scene-sprite')];
                sample.flightPeak=Math.max(sample.flightPeak,flights.length);
                for(const host of flights){
                  const containment=getComputedStyle(host).contain;
                  if(/paint|strict|content/.test(containment)&&sample.violations.length<12)
                    sample.violations.push({type:'flight-clipped-at-origin',containment});
                }
                const areaLimit=innerWidth*innerHeight*4;
                for(const el of document.querySelectorAll('.sprite-motion')){
                  const rect=el.getBoundingClientRect(),area=rect.width*rect.height;
                  sample.maxArea=Math.max(sample.maxArea,area);
                  if(!Number.isFinite(area)||area>areaLimit){
                    if(sample.violations.length<12)sample.violations.push({type:'bounds',sprite:el.parentElement?.dataset.sprite,width:rect.width,height:rect.height});
                  }
                }
                if(promoted.size>25&&sample.violations.length<12)
                  sample.violations.push({type:'promotion-budget',count:promoted.size,willChangeCount,
                    targets:[...promoted].map(el=>({tag:el.tagName,classes:el.getAttribute('class'),sprite:el.dataset.sprite}))});
                if(flights.length>12&&sample.violations.length<12)
                  sample.violations.push({type:'flight-budget',count:flights.length});
              };
              window.budgetTimer=setInterval(window.budgetMeasure,100);
            }""")
            for snapshot in snapshots:
                page.evaluate("snapshot => {window.budgetApp.render(snapshot);window.budgetMeasure();}", snapshot)
                page.wait_for_timeout(1000)
            quiet = page.evaluate("""() => {
              const app=window.budgetApp;
              app.scene.lastEventAt=performance.now()-15001;app.tickClock();window.budgetMeasure();
              const loops=document.getAnimations().filter(animation=>animation.playState==='running'&&animation.effect?.getComputedTiming().iterations===Infinity);
              return {quiet:app.scene.environmentQuiet,idle:app.scene.environmentIdle,
                timer:app.scene.ambient.timer,loops:loops.length,
                details:document.querySelectorAll('[data-running="true"]').length};
            }""")
            assert quiet == {"quiet": True, "idle": False, "timer": None, "loops": 0, "details": 0}, quiet
            # Real CSS media handling must also cancel native finite flights.
            page.emulate_media(reduced_motion="reduce")
            stopped = page.evaluate("""() => ({timer:window.budgetApp.scene.ambient.timer,
              effects:window.budgetApp.scene.effectLayer.children.length,
              frames:window.budgetApp.scene.narrative.frame,
              promotions:window.budgetApp.scene.layers.promotions.size})""")
            assert stopped == {"timer": None, "effects": 0, "frames": None, "promotions": 0}, stopped
            measured = page.evaluate("""() => {
              clearInterval(window.budgetTimer);window.budgetMeasure();
              window.budgetApp.destroy();return window.budgetSamples;
            }""")
            assert not errors, errors
            assert measured["willChangePeak"] <= 25, measured
            assert measured["peak"] <= 25, measured
            assert measured["flightPeak"] <= 12, measured
            assert not measured["violations"], measured
        finally:
            browser.close()


def test_real_quiet_work_has_no_running_unpromoted_or_periodic_native_animation():
    """Inspect real CSS/WAAPI at every browser frame, including finite patrols.

    The audit's rAF is test instrumentation, not a CPU benchmark. Production
    quiet work must not create that loop or a recurring opacity timeline.
    """
    playwright = pytest.importorskip("playwright.sync_api")
    with playwright.sync_playwright() as runtime:
        try:
            browser = runtime.chromium.launch(headless=True, timeout=7000)
        except playwright.Error as exc:
            message = str(exc)
            reason = "macOS MachPortRendezvousServer: Permission denied (1100)" if (
                "MachPortRendezvousServer" in message and "Permission denied" in message
            ) else message.splitlines()[0][:300]
            pytest.skip(f"Chromium cannot start in this environment: {reason}")
        try:
            page = browser.new_page(viewport={"width": 1920, "height": 1080}, reduced_motion="no-preference")
            errors = []
            page.on("pageerror", lambda error: errors.append(str(error)))
            page.route("**/*", _asset_route)
            page.goto("http://panel.test/", wait_until="load")
            measured = page.evaluate("""async () => {
              const root=document.getElementById('factory-app');root.id='factory-test-root';
              const {Dashboard}=await import('/app.js');root.id='factory-app';
              const app=new Dashboard(document),scene=app.scene;
              scene.work.random=()=>0;
              const at=Date.now(),stamp=new Date(at-120000).toISOString();
              const base={mode:'live',day:'2026-10-16',generated_at:new Date(at).toISOString(),
                events:[],alphas:[{id:'a',status:'eval_passed',sim:'batch'},{id:'b',status:'done',sim:'batch'}],
                sessions:[{pid:1,label:'agent_demo',phase:'prod',inflight:{alpha:'a',since:stamp}},
                  {pid:2,label:'kimi3',phase:'simulating'}, {pid:3,phase:'saving'}, {pid:4,phase:'thinking'}],
                pending_sims:[{sim:'pending',pid:2,n:8,since:stamp,progress:.5}],sim_typical_seconds:300};
              const audit={samples:0,peak:0,violations:[],observed:[],ticks:[],inspection:false,beam:false};
              const allowed=new Set(['spider','spider-silk']);let frame,done=false;
              const tick=scene.work._tick.bind(scene.work);
              scene.work._tick=()=>{audit.ticks.push(performance.timeOrigin+performance.now());tick();};
              const measure=()=>{
                audit.samples++;
                const promoted=[...document.querySelectorAll('*')].filter(el=>getComputedStyle(el).willChange!=='auto');
                audit.peak=Math.max(audit.peak,promoted.length);
                for(const animation of document.getAnimations()){
                  if(animation.playState!=='running')continue;
                  const target=animation.effect?.target,style=target&&getComputedStyle(target);
                  const kind=target?.closest('.scene-sprite')?.dataset.sprite;
                  if(!audit.observed.includes(kind))audit.observed.push(kind);
                  if((!style||!/(transform|opacity)/.test(style.willChange))&&audit.violations.length<10)
                    audit.violations.push({reason:'unpromoted',kind,classes:target?.className});
                  if(!allowed.has(kind)&&audit.violations.length<10)
                    audit.violations.push({reason:'periodic-work-timeline',kind});
                }
                if(scene.work.inspectedAlpha)audit.inspection=true;
                if(scene.work.prodPulse&&Number(getComputedStyle(scene.work.prodPulse.motion).opacity)>0)audit.beam=true;
                if(!done)frame=requestAnimationFrame(measure);
              };
              try {
                app.render(base);measure();
                await new Promise(resolve=>setTimeout(resolve,24000));
                // A day change establishes another quiet baseline, so these
                // are ongoing calls rather than freshly replayed events.
                app.render({...base,day:'2026-10-17',sessions:[{pid:1,phase:'evaluating',inflight:{sim:'batch',since:stamp}}],pending_sims:[]});
                await new Promise(resolve=>setTimeout(resolve,9000));
                return audit;
              } finally {done=true;cancelAnimationFrame(frame);app.destroy();}
            }""")
            assert not errors, errors
            assert measured["samples"] > 100, measured
            assert measured["peak"] <= 25, measured
            assert not measured["violations"], measured
            assert "spider" in measured["observed"], measured
            assert measured["inspection"] and measured["beam"], measured
            # A delayed batch can be followed by the next wall-second boundary;
            # each second still contains at most one callback, with no catch-up.
            seconds = [int(at // 1000) for at in measured["ticks"]]
            assert len(set(seconds)) == len(seconds), measured
        finally:
            browser.close()
