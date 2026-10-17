"""Task 13 geometry and removal of the task 14 bottleneck data path."""

from SpiderPanel.state import FactoryState
from test_frontend import WEB, dashboard_check
from test_scene_r1 import scene_check
from test_state import DAY, TS, line


def test_restored_geometry_matches_the_pre_task14_coordinates():
    scene_check("""
      assert.equal(SCENE_VIEWBOX,'0 35 1200 600');
      assert.equal(scene.svg.getAttribute('viewBox'),'0 35 1200 600');
      assert.deepEqual(WEB_CENTER,{x:595,y:153});
      assert.deepEqual(WEB_RADII,{x:221,y:60});
      assert.deepEqual(SCREEN_CONTENT,{left:354,top:92,right:836,bottom:229});
      assert.equal(LOWER_SHIFT,0);
      assert.equal(scene.architecture.querySelector('polygon').getAttribute('points'),
        '34,456 205,275 1110,275 1180,607 155,607');
      assert.equal(scene.furniture.getAttribute('transform'),null);
      assert.deepEqual(CAPTURE_CENTER,{x:458,y:153});
      assert.deepEqual(capturePoint(0),{x:410,y:126});
      assert.deepEqual(capturePoint(7),{x:417,y:175});
      assert.deepEqual(RADAR_ORIGIN,{x:1060,y:492});
      assert.deepEqual(SHREDDER_ORIGIN,{x:145,y:485});
      assert.equal(scene.radarDishSurface.point.angle,-32);
      const frames=scene.architecture.querySelectorAll('rect');
      assert.ok(frames.some(node=>node.getAttribute('x')==='338'&&
        node.getAttribute('y')==='62'&&node.getAttribute('width')==='514'&&node.getAttribute('height')==='210'));
      assert.ok(frames.some(node=>node.getAttribute('x')==='345'&&
        node.getAttribute('y')==='69'&&node.getAttribute('width')==='500'&&node.getAttribute('height')==='197'));
    """)


def test_snapshot_omits_bottleneck_fields_and_keeps_prod_card_accounting():
    state = FactoryState(DAY, clock=lambda: TS + 20)
    try:
        state.feed(line("evaluate", alphas=[["same", "h", False, .2, .1, ["sharpe"]]]))
        for i, value in enumerate((0, .049, .05, .699, .699999999999, .7, .72, 1, .8)):
            state.feed(line("prod", ts=TS + i, alpha="same", prod=value))
        state.feed(line("prod", ts=TS + 10, alpha="unavailable", prod=None, ok=False, err="offline"))
        snapshot = state.snapshot("live")
        assert "fail_reasons" not in snapshot and "prod_stats" not in snapshot
        card = next(card for card in snapshot["cards"] if card["key"] == "prod")
        assert card["value"] == state.prod_checks == 10
        assert state.prod_ok_checks == 5 and state.prod_good == 0
        assert card["progress"] == .5
        assert snapshot["rejects"]["prod_blocked"] == 4
        alpha = next(alpha for alpha in snapshot["alphas"] if alpha["id"] == "same")
        assert alpha["prod"] == .8 and alpha["status"] == "prod_blocked"
        assert alpha["failed"] == ["sharpe"]
        assert not hasattr(state, "prod_valid") and not hasattr(state, "_fail_counts")
        assert not hasattr(state._archive, "record_prod")
        assert not hasattr(state._archive, "prod_median")
        assert state._archive.db is None, "Prod checks alone no longer allocate a median database"
    finally:
        state.close()


def test_dom_has_only_output_and_analysis_beside_the_floor():
    dashboard_check("""
      for(const id of ['bottleneck-title','fail-reasons','reasons-empty','prod-summary','prod-histogram'])
        assert.equal(doc.getElementById(id),null);
      assert.ok(!doc.documentElement.textContent.includes('卡在哪一关'));
      assert.equal(doc.documentElement.querySelectorAll('.panel').length,3);
      assert.ok(doc.getElementById('output-title'));
      assert.ok(doc.getElementById('analysis-title'));
      assert.equal(app.bottleneck,undefined);
      assert.equal(Object.hasOwn(app.state,'fail_reasons'),false);
      assert.equal(Object.hasOwn(app.state,'prod_stats'),false);
    """)
    assert not (WEB / "bottleneck.js").exists()
