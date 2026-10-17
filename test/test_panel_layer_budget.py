"""Panel status indicators must not allocate a layer for each dot or meter."""

import re

from test_frontend import WEB, dashboard_check


def declaration(css, selector):
    match = re.search(re.escape(selector) + r"\s*\{([^}]*)\}", css)
    assert match, selector
    return match.group(1)


def test_busy_cards_have_one_leaf_indicator_and_keep_idle_state():
    dashboard_check(r"""
      const cards=[...app.cardNodes.keys()].map(key=>({key,busy:true,value:1,progress:.5}));
      app.render({mode:'demo',cards});
      const dots=doc.getElementById('role-cards').querySelectorAll('.typing-dots');
      assert.equal(dots.length,8);
      assert.ok(dots.every(node=>node.children.length===0),'Each card needs one animated element, not three dot layers');
      assert.ok([...app.cardNodes.values()].every(entry=>entry.node.classList.contains('is-busy')));
      app.render({cards:cards.map(card=>({...card,busy:false}))});
      assert.ok([...app.cardNodes.values()].every(entry=>!entry.node.classList.contains('is-busy')));
      assert.equal(doc.getElementById('connection').querySelectorAll('i').length,1);
    """)


def test_status_indicator_steps_repaint_only_its_tiny_background():
    css = (WEB / "app.css").read_text()
    dots = declaration(css, ".typing-dots")
    busy = declaration(css, ".is-busy .typing-dots")
    typing = re.search(r"@keyframes typing\s*\{(.*?)\}\s*@keyframes", css, re.S).group(1)
    assert "animation:" not in dots
    assert "steps(" in busy
    assert "background-position:" in typing
    assert "transform:" not in typing and "opacity:" not in typing
    assert "html.environment-idle .typing-dots {animation-play-state:paused!important}" in css
    assert "html.page-hidden *" in css
    assert "@media(prefers-reduced-motion:reduce)" in css
    assert "will-change:" not in css
    for selector in (".goal-meter>span", ".card-progress span", ".scatter-point"):
        assert "transition:" not in declaration(css, selector)


def test_clock_has_fixed_size_and_paint_containment_at_every_breakpoint():
    css = (WEB / "app.css").read_text()
    desktop = declaration(css, ".header-right time")
    assert "contain:strict" in desktop
    assert "display:block" in desktop and "flex:none" in desktop
    assert re.search(r"\bwidth:calc\([^;]+\)", desktop)
    assert re.search(r"\bheight:\d+px", desktop)
    mobile = css[css.index("@media(max-width:899px)"):]
    mobile_clock = declaration(mobile, ".header-right time")
    assert re.search(r"\bwidth:calc\([^;]+\)", mobile_clock)
    assert re.search(r"\bheight:\d+px", mobile_clock)


def test_environment_quiet_class_starts_paused_and_tracks_event_window():
    dashboard_check(r"""
      assert.equal(doc.documentElement.classList.contains('environment-quiet'),true,
        'Before the first new event, ambient status indicators must remain quiet');
      app.scene.environmentQuiet=false;app.scene.environmentIdle=false;
      app.syncEnvironmentIdle();
      assert.equal(doc.documentElement.classList.contains('environment-quiet'),false);
      app.scene.checkActivity=()=>{app.scene.environmentQuiet=true;return true;};
      app.tickClock();
      assert.equal(doc.documentElement.classList.contains('environment-quiet'),true);
      assert.equal(doc.documentElement.classList.contains('environment-idle'),false,
        'The 15-second quiet window must not replace the 60-second idle state');
      app.scene.update=()=>{app.scene.environmentQuiet=false;};
      app.render({events:[]});
      assert.equal(doc.documentElement.classList.contains('environment-quiet'),false,
        'An update must synchronize a newly active scene after its clock check');
    """)


def test_quiet_environment_pauses_status_indicators_and_has_no_css_filters():
    css = (WEB / "app.css").read_text()
    for selector in (".connection i", ".live-square", ".typing-dots"):
        assert "html.environment-quiet " + selector in css
    assert "filter:" not in css
