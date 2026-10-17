"""Session lifecycle and qualified-best rendering through the production dashboard."""

import json
from urllib.parse import unquote, urlsplit

import pytest

from test_frontend import WEB, dashboard_check, data_check


def test_agent_badges_and_hover_use_canonical_session_identity():
    dashboard_check("""
      const sessions=[
        {pid:4100,ppid:4100,validator_pid:91,label:'codex'},
        {pid:4200,ppid:4200,validator_pid:92,label:'kimi3 · 1'},
        {pid:4300,ppid:4300,validator_pid:93,label:'kimi3 · 2'},
        {pid:4400,ppid:4400,validator_pid:94,label:'agent_demo'},
        {pid:4500,validator_pid:4500,label:'终端 5'},
        {pid:0,label:'未知会话'}
      ];
      app.render({sessions,alphas:[{id:'live',pid:4200,session_label:'kimi3 · 1'}]});
      assert.deepEqual([...app.scene.sessionNodes.keys()],['4100','4200','4300','4400','4500','0']);
      for(const [pid,label] of [[4100,'codex'],[4200,'kimi3 · 1'],[4300,'kimi3 · 2'],
        [4400,'agent_demo'],[4500,'终端 5'],[0,'未知会话']]){
        const entry=app.scene.sessionNodes.get(String(pid));
        assert.equal(entry.name.textContent,label);
        assert.ok(entry.g.getAttribute('aria-label').startsWith(label+'，'));
        entry.badge.dispatch('pointerenter');
        assert.ok(doc.getElementById('tooltip').textContent.startsWith(label+' · '));
        entry.badge.dispatch('pointerleave');
        assert.equal(doc.getElementById('tooltip').hidden,true);
      }
      app.openAlpha('live');
      assert.equal(app.drawerFields[4].textContent,'kimi3 · 1');
    """)


def test_ended_session_releases_seat_and_overlays_but_alpha_keeps_badge():
    # Removing either lifecycle cleanup or session_label fallback breaks this flow.
    dashboard_check("""
      const codex={pid:4100,label:'codex',phase:'simulating'},
        kimi={pid:4200,label:'kimi3 · 1',phase:'evaluating'},
        wang={pid:4300,label:'agent_demo',phase:'idle'};
      const alpha={id:'from-ended',pid:4100,session_label:'codex',status:'eval_passed',passed:true};
      app.render({sessions:[codex,kimi,wang],alphas:[alpha]});
      const ended=app.scene.sessionNodes.get('4100'),survivor=app.scene.sessionNodes.get('4200');
      app.openAlpha(alpha.id);
      ended.badge.dispatch('pointerenter');
      assert.equal(doc.getElementById('tooltip').hidden,false);
      app.render({sessions:[kimi,wang],sessions_ended:1,alphas:[alpha]});
      assert.equal(app.scene.sessionNodes.has('4100'),false);
      assert.equal(ended.g.isConnected,false);
      assert.equal(ended.overlay.isConnected,false);
      assert.equal(ended.surface.host.isConnected,false);
      assert.equal(ended.overlaySurface.host.isConnected,false);
      assert.equal(doc.getElementById('tooltip').hidden,true);
      assert.equal(app.scene.sessionNodes.get('4200'),survivor);
      assert.equal(survivor.station,app.scene.stations[0]);
      assert.deepEqual(app.scene.sessionPositions.get('4200'),{x:survivor.station.x+47,y:survivor.station.y-60});
      assert.equal(app.scene.sessionOverlay.querySelectorAll('.wq-session-overlay').length,2);
      assert.equal(app.drawerFields[4].textContent,'codex');
      app.render({sessions:[],sessions_ended:3,alphas:[alpha]});
      assert.equal(app.scene.sessionNodes.size,0);
      assert.equal(app.scene.sessionOverlay.children.length,0);
      assert.equal(app.drawerFields[4].textContent,'codex');
      assert.ok(doc.getElementById('floor-status').textContent.startsWith('今日已结束 3'));
    """)


def test_ended_count_defaults_safely_and_remains_in_footer_slot():
    data_check("""
      for(const value of [undefined,null,-2,'4',NaN])
        assert.equal(data.normaliseSnapshot({sessions_ended:value}).sessions_ended,0);
      assert.equal(data.normaliseSnapshot({sessions_ended:12}).sessions_ended,12);
    """)
    dashboard_check("""
      const status=doc.getElementById('floor-status'),parent=status.parentNode;
      for(const [ended,label] of [[0,'0'],[12,'12'],[10000,'10,000']]){
        app.render({sessions_ended:ended,sessions:[{pid:1,label:'agent_demo'}],
          totals:{sessions_total:1,sessions_active:1,alphas:20,pending_review:3}});
        assert.equal(status.parentNode,parent);
        assert.ok(status.textContent.startsWith(`今日已结束 ${label} · `));
        assert.equal(status.title,status.textContent);
      }
    """)


def test_only_qualified_best_drives_numbers_and_rocket_without_filtering_alphas():
    dashboard_check("""
      const failed={id:'failed-high',sharpe:9.9,fitness:2,status:'eval_failed',passed:false};
      const blocked={id:'blocked-high',sharpe:8.8,fitness:2,status:'prod_blocked',passed:true};
      const good={id:'qualified',sharpe:1.8,fitness:.9,status:'candidate',passed:true};
      const alphas=[failed,blocked,good];
      for(const status of ['eval_passed','prod_ok','candidate']){
        app.render({alphas,best:{...good,status},totals:{alphas:3}});
        assert.equal(app.stats[2].textContent,'1.80');
        assert.equal(app.scene.bestId,'qualified');
        assert.equal(app.scene.runnerId.textContent,'qualified');
        assert.equal(app.scene.runner.getAttribute('aria-disabled'),'false');
        assert.ok(app.scene.runner.getAttribute('aria-label').startsWith('合格最佳 Alpha'));
        assert.equal(app.scene.sparklineLabel.textContent,'合格最佳 SHARPE 1.80');
        assert.equal(app.scatter.points.size,3);
        assert.equal(doc.getElementById('recent-alphas'),null);
      }
      assert.equal(doc.getElementById('analysis-stats').children[2].querySelector('span').textContent,'合格最佳 S');
      assert.ok(app.scene.runner.querySelectorAll('text').some(node=>node.textContent==='合格最佳'));
      app.scene.runner.dispatch('click');assert.equal(app.openId,'qualified');app.closeDrawer();
    """)


def test_unqualified_or_null_best_clears_all_best_displays_and_disables_rocket():
    dashboard_check("""
      const good={id:'good',sharpe:1.8,fitness:.9,status:'candidate',passed:true};
      const alphas=[good,{id:'failed',sharpe:10,fitness:2,status:'eval_failed',passed:false}];
      for(const best of [null,{...good,passed:false},{...good,passed:undefined},
        {...good,passed:1},{...good,status:'done'},{...good,status:'eval_failed'},
        {...good,status:'prod_blocked'},{...good,status:'rejected'}]){
        app.render({alphas,best:good});
        app.render({alphas,best});
        assert.equal(app.stats[2].textContent,'—');
        assert.equal(app.scene.bestId,null);
        assert.equal(app.scene.runnerId.textContent,'暂无合格 alpha');
        assert.equal(app.scene.runnerSharpe.textContent,'SHARPE —');
        assert.equal(app.scene.sparklineLabel.textContent,'合格最佳 SHARPE —');
        assert.equal(app.scene.runner.getAttribute('aria-disabled'),'true');
        assert.equal(app.scene.runner.getAttribute('tabindex'),'-1');
        app.scene.runner.dispatch('click');
        assert.equal(app.openId,null);
        assert.equal(app.scatter.points.size,2);
        assert.equal(doc.getElementById('recent-alphas'),null);
      }
    """)


def test_real_browser_session_footer_and_best_labels_at_four_viewports(tmp_path):
    """Local assets only; structural DOM checks do not establish CSS layout."""
    playwright = pytest.importorskip("playwright.sync_api")
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
            page = browser.new_page(viewport={"width": 1920, "height": 1080})
            errors = []
            page.on("pageerror", lambda error: errors.append(str(error)))

            def asset_route(route):
                path = unquote(urlsplit(route.request.url).path)
                target = (WEB / ("index.html" if path == "/" else path.lstrip("/"))).resolve()
                if not target.is_relative_to(WEB.resolve()) or not target.is_file():
                    route.fulfill(status=404, body="Not found")
                    return
                body = target.read_bytes()
                if target.name == "index.html":
                    body = body.replace(b'<script type="module" src="/app.js"></script>', b"")
                types = {".html": "text/html", ".css": "text/css", ".js": "text/javascript"}
                route.fulfill(status=200, body=body, content_type=types.get(target.suffix, "application/octet-stream"))

            page.route("**/*", asset_route)
            page.goto("http://panel.test/", wait_until="load")
            page.evaluate("""async () => {
              const root=document.getElementById('factory-app');root.id='factory-test-root';
              const {Dashboard}=await import('/app.js');root.id='factory-app';
              window.sessionApp=new Dashboard(document);
              sessionApp.render({sessions:[],sessions_ended:12345,
                alphas:[{id:'ended',pid:41,session_label:'kimi3 · 1',sharpe:9.9,fitness:2,status:'eval_failed',passed:false}],best:null});
            }""")
            for width, height in [(1920, 1080), (1600, 900), (1280, 1600), (768, 1024), (390, 844)]:
                page.set_viewport_size({"width": width, "height": height})
                result = page.evaluate("""() => {
                  const status=document.getElementById('floor-status'),footer=status.parentElement;
                  const bounds=status.getBoundingClientRect(),box=footer.getBoundingClientRect();
                  return {ended:status.textContent,bounds:{left:bounds.left,right:bounds.right},
                    footer:{left:box.left,right:box.right},
                    pageWidth:document.documentElement.scrollWidth,viewport:innerWidth,
                    best:sessionApp.stats[2].textContent,
                    removed:document.querySelector('.thresholds-panel,.recent-section,.output-head,.bottleneck-panel'),
                    pageHeight:document.documentElement.scrollHeight,
                    floor:document.querySelector('.floor-panel').getBoundingClientRect().toJSON(),
                    output:document.querySelector('.output-panel').getBoundingClientRect().toJSON(),
                    analysis:document.querySelector('.analysis-panel').getBoundingClientRect().toJSON(),
                    grid:document.querySelector('.work-grid').getBoundingClientRect().toJSON(),
                    sceneWidth:document.querySelector('.scene-stage').scrollWidth,
                    rocket:sessionApp.scene.runnerId.textContent};
                }""")
                assert result["ended"].startswith("今日已结束 12,345")
                assert result["bounds"]["left"] >= result["footer"]["left"]
                assert result["bounds"]["right"] <= result["footer"]["right"] + 1
                assert result["pageWidth"] <= result["viewport"]
                assert result["best"] == "—"
                assert result["removed"] is None
                floor, output, analysis, grid = (result[key] for key in ("floor", "output", "analysis", "grid"))
                if width >= 1440:
                    assert result["pageHeight"] <= height  # The desktop fits in one screen again.
                    assert abs(floor["height"] - grid["height"]) <= 1
                    assert abs(floor["width"] / grid["width"] - .72) < .02
                    assert abs(output["height"] - 220) <= 1
                    assert analysis["top"] >= output["bottom"] and analysis["height"] >= 300
                    assert abs(analysis["bottom"] - grid["bottom"]) <= 1
                    assert abs(output["x"] - analysis["x"]) <= 1
                elif width >= 900:
                    assert abs(output["top"] - analysis["top"]) <= 1
                    assert analysis["left"] >= output["right"]
                    assert output["top"] >= floor["bottom"]
                else:
                    assert output["top"] >= floor["bottom"]
                    assert analysis["top"] >= output["bottom"]
                    assert result["sceneWidth"] >= 820
                assert result["rocket"] == "暂无合格 alpha"
                (tmp_path / f"layout_{width}x{height}.json").write_text(json.dumps(result, ensure_ascii=False))
                page.screenshot(path=str(tmp_path / f"layout_{width}x{height}.png"))
            page.evaluate("sessionApp.openAlpha('ended')")
            assert page.locator("#drawer-fields dd").nth(4).inner_text() == "kimi3 · 1"
            assert errors == []
            page.evaluate("sessionApp.destroy()")
        finally:
            browser.close()
