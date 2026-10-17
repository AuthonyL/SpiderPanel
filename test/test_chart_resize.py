"""Pixel-space chart behavior with controlled SVG layout and resize delivery."""

import json
from pathlib import Path

from test_frontend import WEB, run_js


def chart_check(source):
    run_js("import assert from 'node:assert/strict';\nimport fs from 'node:fs';\n"
           f"import {{documentFromHTML}} from {json.dumps((Path(__file__).parent/'frontend_dom.mjs').as_uri())};\n"
           f"import {{OutputChart,ScatterChart}} from {json.dumps((WEB/'charts.js').as_uri())};\n"
           f"const doc=documentFromHTML(fs.readFileSync({json.dumps(str(WEB/'index.html'))},'utf8'));\n"+"""
      const observers=[];
      doc.defaultView.ResizeObserver=class {
        constructor(callback){this.callback=callback;this.targets=new Set();this.disconnected=false;observers.push(this);}
        observe(target){this.targets.add(target);}
        disconnect(){this.targets.clear();this.disconnected=true;}
      };
      function geometry(node,width,height){
        node.clientWidth=width;node.clientHeight=height;
        node.getBoundingClientRect=()=>({x:0,y:0,left:0,top:0,width,height,right:width,bottom:height});
      }
      function resize(node,width,height){
        geometry(node,width,height);
        for(const observer of observers)if(observer.targets.has(node))
          observer.callback([{target:node,contentRect:{width,height},contentBoxSize:[{inlineSize:width,blockSize:height}]}]);
      }
      const outputSvg=doc.getElementById('output-chart'),scatterSvg=doc.getElementById('scatter-chart');
      geometry(outputSvg,0,0);geometry(scatterSvg,0,0);
      geometry(outputSvg.parentNode,1600,900);geometry(scatterSvg.parentNode,1600,900);
      const snapshot={day:'2026-10-15',
        timeline:[{t:'2026-10-15T12:00:00+08:00',eval_passed:2,candidates_cum:1,sims_done:3},
          {t:'2026-10-15T12:15:00+08:00',eval_passed:1,candidates_cum:2,sims_done:1}],
        alphas:[{id:'low',sharpe:-1,fitness:-.4,status:'done'},
          {id:'pick',sharpe:2.2,fitness:1.5,status:'candidate'}],
        thresholds:{soft:{standard:{sharpe:1.25,fitness:1.0},high:{sharpe:1.75,fitness:1.15}}},
        events:[{kind:'sim_fail',ts:'2026-10-15T12:01:00+08:00'}]};
      function finiteGeometry(svg,width,height){
        const visit=node=>{
          for(const key of ['x','y','x1','x2','y1','y2','cx','cy','width','height']){
            const raw=node.getAttribute(key);if(raw===null)continue;
            const number=Number(raw);assert.ok(Number.isFinite(number),`${node.tagName}.${key}: ${raw}`);
            assert.ok(number>=0,`${node.tagName}.${key} is negative`);
            if(['x','x1','x2','cx','width'].includes(key))assert.ok(number<=width,`${key} exceeds width`);
            if(['y','y1','y2','cy','height'].includes(key))assert.ok(number<=height,`${key} exceeds height`);
          }
          const path=node.getAttribute('d');if(path)assert.ok(!/NaN|Infinity/.test(path),path);
          for(const child of node.children)visit(child);
        };visit(svg);
      }
    """+source)


def test_charts_resize_in_pixel_space_without_replacing_data_nodes():
    # Fixed viewBoxes fail this test even when the SVG element fills its CSS box.
    chart_check(r"""
      const output=new OutputChart(outputSvg),scatter=new ScatterChart(scatterSvg);
      assert.equal(outputSvg.getAttribute('viewBox'),'0 0 320 220');
      assert.equal(scatterSvg.getAttribute('viewBox'),'0 0 320 220');
      output.update(snapshot);scatter.update(snapshot);
      const bar=output.bars.values().next().value,point=scatter.points.get('pick').node;
      const initialX=bar.getAttribute('x');
      for(const [width,height] of [[1200,300],[620,220],[370,260]]){
        resize(outputSvg,width,height);resize(scatterSvg,width,height);
        assert.equal(outputSvg.getAttribute('viewBox'),`0 0 ${width} ${height}`);
        assert.equal(scatterSvg.getAttribute('viewBox'),`0 0 ${width} ${height}`);
        finiteGeometry(outputSvg,width,height);finiteGeometry(scatterSvg,width,height);
        for(const svg of [outputSvg,scatterSvg])for(const text of svg.querySelectorAll('text'))
          assert.equal(text.style.getPropertyValue('font-size'),'10px');
        assert.equal(output.bars.values().next().value,bar);
        assert.equal(scatter.points.get('pick').node,point);
        assert.equal(outputSvg.querySelectorAll('path').length,0);
        assert.notEqual(bar.getAttribute('x'),initialX);
        assert.equal(bar.getAttribute('fill'),'#ff4d5e');
        assert.match(bar.firstChild.textContent,/\d\d-\d\d \d\d:\d\d:\d\d/);
      }
      const beforeY=Number(scatter.points.get('low').node.getAttribute('cy'));
      resize(scatterSvg,370,480);
      assert.ok(Number(scatter.points.get('low').node.getAttribute('cy'))>beforeY+150,
        'Scatter should use the available vertical space');
      for(let i=0;i<20;i++){output.update(snapshot);scatter.update(snapshot);}
      assert.equal(observers.length,2,'One observer per chart, not per update');
      output.destroy();scatter.destroy();
    """)


def test_scatter_uses_nice_ticks_and_keeps_negative_thresholds_in_domain():
    # Interpolating the padded metric bounds produces labels such as -1.15 and .59.
    chart_check("""
      const scatter=new ScatterChart(scatterSvg);
      scatter.update({...snapshot,alphas:[]});resize(scatterSvg,370,260);
      const labels=scatterSvg.querySelector('.chart-x-axis').querySelectorAll('text')
        .sort((a,b)=>Number(a.getAttribute('x'))-Number(b.getAttribute('x'))).map(node=>node.textContent);
      assert.deepEqual(labels,['-1','0','1','2','3']);
      scatter.update({alphas:[],thresholds:{soft:{standard:{sharpe:-4,fitness:-3}}}});
      const tickValues=axis=>scatterSvg.querySelector(axis).querySelectorAll('text').map(node=>Number(node.textContent));
      assert.ok(Math.min(...tickValues('.chart-x-axis'))<=-4,'Threshold Sharpe must be inside the domain');
      assert.ok(Math.min(...tickValues('.chart-y-axis'))<=-3,'Threshold Fitness must be inside the domain');
      const low={id:'negative',sharpe:-4,fitness:-3,status:'candidate'};
      scatter.update({alphas:[low],thresholds:{soft:{standard:{sharpe:-4,fitness:-3}}}});
      const point=scatter.points.get('negative').node,box=scatter.tiers.get('standard').box;
      assert.ok(Number(point.getAttribute('cx'))>0);
      assert.ok(Number(point.getAttribute('cy'))<260);
      assert.ok(Math.abs(Number(point.getAttribute('cx'))-Number(box.getAttribute('x')))<.001);
      assert.ok(Math.abs(Number(point.getAttribute('cy'))-Number(box.getAttribute('y'))-Number(box.getAttribute('height')))<.001);
      finiteGeometry(scatterSvg,370,260);
      scatter.destroy();
    """)


def test_extreme_metrics_and_counts_do_not_create_invalid_svg_geometry():
    chart_check("""
      const output=new OutputChart(outputSvg),scatter=new ScatterChart(scatterSvg);
      resize(outputSvg,370,220);resize(scatterSvg,370,220);
      output.update({timeline:Array.from({length:96},(_,i)=>({t:new Date(1700000000000+i*900000).toISOString(),
        eval_passed:Number.MAX_VALUE,sims_done:Number.MAX_VALUE,candidates_cum:Number.MAX_VALUE}))});
      scatter.update({alphas:[{id:'min',sharpe:-Number.MAX_VALUE,fitness:-Number.MAX_VALUE},
        {id:'max',sharpe:Number.MAX_VALUE,fitness:Number.MAX_VALUE},
        {id:'invalid',sharpe:Infinity,fitness:NaN}],
        thresholds:{soft:{standard:{sharpe:-Number.MAX_VALUE,fitness:-Number.MAX_VALUE}}}});
      finiteGeometry(outputSvg,370,220);finiteGeometry(scatterSvg,370,220);
      assert.equal(scatter.points.size,2);
      assert.ok(output.bars.size<=96);assert.ok(output.failedBuckets.size<=96);
      output.destroy();scatter.destroy();
    """)


def test_output_count_ticks_are_distinct_for_a_single_completed_batch():
    chart_check("""
      const output=new OutputChart(outputSvg);resize(outputSvg,370,220);
      output.update({timeline:[{t:'2026-10-15T12:00:00+08:00',eval_passed:1,sims_done:1}]});
      const labels=outputSvg.querySelector('.chart-y-axis').querySelectorAll('text').map(node=>node.textContent);
      assert.equal(new Set(labels).size,labels.length,'Count ticks must not round different values to the same label');
      assert.ok(labels.every(label=>/^\\d+$/.test(label)));
      output.destroy();
    """)


def test_resized_scatter_retains_interaction_and_destroy_stops_resize_delivery():
    chart_check("""
      const opened=[],hovered=[];
      const output=new OutputChart(outputSvg),scatter=new ScatterChart(scatterSvg,
        {onAlpha:id=>opened.push(id),onHover:alpha=>hovered.push(alpha?.id??null)});
      output.update(snapshot);scatter.update(snapshot);
      resize(outputSvg,370,220);resize(scatterSvg,370,220);
      const point=scatter.points.get('pick').node;
      point.dispatch('focus');resize(scatterSvg,620,320);
      assert.equal(point.getAttribute('r'),'6');
      point.dispatch('keydown',{key:'Enter'});point.dispatch('click');point.dispatch('blur');
      assert.deepEqual(opened,['pick','pick']);assert.deepEqual(hovered,['pick',null]);
      const outView=outputSvg.getAttribute('viewBox'),scatterView=scatterSvg.getAttribute('viewBox');
      output.destroy();scatter.destroy();
      assert.ok(observers.every(observer=>observer.disconnected));
      for(const observer of observers)observer.callback([{target:outputSvg,contentRect:{width:999,height:999}},
        {target:scatterSvg,contentRect:{width:999,height:999}}]);
      assert.equal(outputSvg.getAttribute('viewBox'),outView);
      assert.equal(scatterSvg.getAttribute('viewBox'),scatterView);
    """)
