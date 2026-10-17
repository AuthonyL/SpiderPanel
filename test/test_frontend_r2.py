import json

from SpiderPanel.thresholds import load_thresholds
from test_thresholds import value
from test_frontend import dashboard_check


def test_configured_thresholds_feed_reused_scatter_boxes_without_a_rules_panel():
    thresholds = load_thresholds(value())
    dashboard_check("const thresholds=" + json.dumps(thresholds) + ";\n" + """
      app.render({thresholds});
      assert.equal(Object.keys(thresholds.soft.standard).length,2);
      assert.deepEqual(app.state.thresholds,thresholds);
      const standard=app.scatter.tiers.get('standard'),high=app.scatter.tiers.get('high');
      assert.equal(standard.label.textContent,'STANDARD · S≥1.75 F≥1.15');
      assert.equal(high.label.textContent,'HIGH · S≥2.75 F≥1.65');
      assert.equal(doc.getElementById('hard-rules'),null);
      assert.equal(doc.getElementById('soft-rules'),null);
      app.render({thresholds});
      assert.equal(app.scatter.tiers.get('standard'),standard);
      assert.equal(app.scatter.tiers.get('high'),high);
      app.render({thresholds:{soft:{standard:{sharpe:1,fitness:.5}}}});
      assert.equal(app.scatter.tiers.size,1);
      assert.equal(app.scatter.tiers.get('standard'),standard);
      assert.equal(standard.label.textContent,'STANDARD · S≥1.00 F≥0.50');
      assert.equal(high.node.isConnected,false);
      app.render({thresholds:null});assert.equal(app.scatter.tiers.size,0);
    """)
