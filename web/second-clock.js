/* Clock and quiet work share one wall-second callback, without catch-up ticks. */
export class SecondClock {
  constructor(win=globalThis){
    this.win=win;this.callbacks=new Set();this.timer=null;this.destroyed=false;
  }
  now(){
    const performance=this.win.performance;
    return performance? (performance.timeOrigin||0)+performance.now():Date.now();
  }
  subscribe(callback){
    if(this.destroyed)return ()=>{};
    this.callbacks.add(callback);this._schedule();
    return ()=>{this.callbacks.delete(callback);if(!this.callbacks.size)this._cancel();};
  }
  _cancel(){if(this.timer!==null)this.win.clearTimeout(this.timer);this.timer=null;}
  _schedule(){
    if(this.destroyed||this.timer!==null||!this.callbacks.size)return;
    const remainder=((this.now()%1000)+1000)%1000;
    this.timer=this.win.setTimeout(()=>{
      this.timer=null;
      try{for(const callback of [...this.callbacks])if(this.callbacks.has(callback))callback();}
      finally{this._schedule();}
    // setTimeout converts its delay to integer milliseconds. Round up so a
    // fractional timeOrigin cannot cause a pre-boundary tick plus a 1ms retry.
    },Math.max(1,Math.ceil(1000-remainder)));
  }
  destroy(){this.destroyed=true;this._cancel();this.callbacks.clear();}
}
