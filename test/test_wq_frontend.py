"""WQ reset clock and compact two-panel layout."""

from test_frontend import dashboard_check, data_check, WEB


def test_wq_countdown_uses_demo_epoch_and_the_existing_whole_second_callback():
    dashboard_check(r"""
      const clocks=[],fired=[],tick=app.tickClock.bind(app);app.tickClock=()=>{clocks.push(now);tick();};
      const realTimeout=doc.defaultView.setTimeout;
      doc.defaultView.setTimeout=(fn,delay)=>realTimeout(()=>{fired.push(now);fn();},delay);
      doc.hidden=true;doc.dispatch('visibilitychange');doc.hidden=false;doc.dispatch('visibilitychange');
      app.render({day:'2026-11-01',mode:'demo',generated_at:'2026-11-02T12:59:55+08:00',
        wq_start:'2026-11-01T12:00:00+08:00',wq_next_reset:'2026-11-02T13:00:00+08:00',
        sessions:[{pid:1,phase:'thinking'}],events:[]});
      assert.equal(doc.getElementById('day-label').textContent,'WQ DAY · 11-01');
      assert.equal(doc.getElementById('reset-countdown').textContent,'重置 00:00:05');
      clocks.length=0;
      for(let i=0;i<400;i++){now+=10;doc.sampleAnimations();}
      assert.equal(doc.getElementById('reset-countdown').textContent,'重置 00:00:01');
      assert.equal(clocks.length,4);assert.equal(fired.length,4);
      assert.equal(new Set(fired).size,4);
      now+=1000;doc.sampleAnimations();
      assert.equal(doc.getElementById('reset-countdown').textContent,'重置 00:00:00');
      doc.hidden=true;doc.dispatch('visibilitychange');
      const callbacks=fired.length;now+=10000;doc.sampleAnimations();assert.equal(fired.length,callbacks);
    """, setup="let now=100;doc.defaultView.performance.now=()=>now;\n")


def test_autumn_timeline_keeps_all_hundred_buckets_starting_at_reset():
    data_check(r"""
      const start=Date.parse('2026-11-01T12:00:00+08:00');
      const rows=Array.from({length:100},(_,i)=>({t:new Date(start+i*900000).toISOString(),sims_done:1}));
      const series=data.timelineSeries(rows,[]);
      assert.equal(series.length,100);assert.equal(series[0].t,rows[0].t);assert.equal(series[99].t,rows[99].t);
    """)


def test_compact_floor_two_right_panels_and_reset_paint_isolation_are_declared():
    css = (WEB / "app.css").read_text()
    assert '"floor output" "floor analysis"' in css
    assert "grid-template-rows:220px minmax(0,1fr)" in css
    assert "height:calc(100dvh - 16px)" in css
    assert "aspect-ratio:2/1" in css
    assert "bottleneck" not in css
    countdown = css.split(".reset-countdown {", 1)[1].split("}", 1)[0]
    assert "contain:strict" in countdown and "width:" in countdown and "height:" in countdown
    assert "animation" not in countdown and "transition" not in countdown
