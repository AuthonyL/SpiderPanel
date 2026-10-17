from test_frontend import dashboard_check, data_check


def test_local_timestamp_format_handles_iso_null_and_invalid_values():
    data_check("""
      process.env.TZ='Asia/Shanghai';
      assert.equal(data.formatTimestamp('2026-10-15T21:08:37+08:00'),'10-15 21:08:37');
      assert.equal(data.formatTimestamp('2026-10-15T13:08:37Z'),'10-15 21:08:37');
      for(const value of [null,undefined,'','bad date'])assert.equal(data.formatTimestamp(value),'—');
    """)


def test_drawer_and_update_time_use_readable_local_timestamp():
    dashboard_check("""
      process.env.TZ='Asia/Shanghai';
      const stamp='2026-10-15T21:08:37+08:00';
      app.render({generated_at:stamp,alphas:[{id:'a',ts:stamp}]});
      app.openAlpha('a');
      assert.equal(app.drawerFields.at(-1).textContent,'10-15 21:08:37');
      assert.ok(doc.getElementById('updated-label').textContent.includes('10-15 21:08:37'));
    """)


def test_demo_clock_advances_from_snapshot_without_resetting_on_cached_updates():
    dashboard_check("""
      process.env.TZ='Asia/Shanghai';
      let mono=100;doc.defaultView.performance.now=()=>mono;
      const snapshot={mode:'demo',day:'2026-10-15',generated_at:'2026-10-15T21:08:37+08:00'};
      app.render(snapshot);
      assert.equal(doc.getElementById('clock').textContent,'21:08:37');
      mono+=2000;app.tickClock();
      assert.equal(doc.getElementById('clock').textContent,'21:08:39');
      app.render(snapshot);
      assert.equal(doc.getElementById('clock').textContent,'21:08:39');
      app.render({...snapshot,generated_at:'2026-10-15T21:09:01+08:00'});
      assert.equal(doc.getElementById('clock').textContent,'21:09:01');
      app.render({mode:'live'});
      const date=new Date(doc.getElementById('clock').dateTime);
      assert.ok(Math.abs(date.valueOf()-Date.now())<2000);
    """)


def test_only_scene_and_chart_resize_observers_remain_and_disconnect():
    dashboard_check("""
      assert.equal(doc.getElementById('recent-alphas'),null);
      assert.equal(app.listResizeObserver,undefined);
      assert.equal(observers.length,3,'One scene mapping plus two charts; no removed panel observer');
      const targets=observers.map(observer=>observer.target);
      assert.ok(targets.includes(app.scene.canvas));
      assert.ok(targets.includes(doc.getElementById('output-chart')));
      assert.ok(targets.includes(doc.getElementById('scatter-chart')));
      for(const chart of [app.output,app.scatter]){
        const observer=observers.find(item=>item.target===chart.svg);
        observer.callback([{target:chart.svg,contentRect:{width:430,height:260}}]);
        assert.equal(chart.svg.getAttribute('viewBox'),'0 0 430 260');
      }
      app.destroy();assert.ok(observers.every(observer=>observer.disconnected));
    """, setup="""
      const observers=[];
      doc.defaultView.ResizeObserver=class {
        constructor(callback){this.callback=callback;observers.push(this);}
        observe(target){this.target=target;}
        disconnect(){this.disconnected=true;}
      };
    """)
