// A structural DOM double, not a rendering engine. Browser layout needs Chromium.
export class Element {
  constructor(tagName, ownerDocument) {
    Object.assign(this,{tagName,ownerDocument,children:[],attributes:{},listeners:new Map(),parentNode:null,
      dataset:{},hidden:false,disabled:false,_text:''});
    this.style={setProperty(key,value){this[key]=String(value);},getPropertyValue(key){return this[key]||'';}};
    this.classList={
      add:(...names)=>{const all=new Set(this.className.split(/\s+/).filter(Boolean));names.forEach(n=>all.add(n));this.className=[...all].join(' ');},
      remove:(...names)=>{this.className=this.className.split(/\s+/).filter(n=>!names.includes(n)).join(' ');},
      contains:name=>this.className.split(/\s+/).includes(name),
      toggle:(name,force)=>{const add=force??!this.classList.contains(name);add?this.classList.add(name):this.classList.remove(name);return add;},
    };
  }
  set className(value){this.attributes.class=String(value);} get className(){return this.attributes.class||'';}
  set id(value){this.attributes.id=String(value);} get id(){return this.attributes.id||'';}
  set textContent(value){this._text=String(value);for(const child of this.children)child.parentNode=null;this.children=[];}
  get textContent(){return this._text+this.children.map(c=>c.textContent).join('');}
  set innerHTML(value){throw new Error('Markup injection is forbidden: '+String(value).slice(0,30));}
  setAttribute(key,value){this.attributes[key]=String(value);if(key==='hidden')this.hidden=true;}
  getAttribute(key){return this.attributes[key]??null;}
  removeAttribute(key){delete this.attributes[key];if(key==='hidden')this.hidden=false;}
  appendChild(child){child.remove();this.children.push(child);child.parentNode=this;return child;}
  append(...children){for(const child of children)this.appendChild(child);}
  insertBefore(child,reference){if(child===reference)return child;child.remove();const i=reference?this.children.indexOf(reference):-1;if(i<0)this.children.push(child);else this.children.splice(i,0,child);child.parentNode=this;return child;}
  remove(){if(this.parentNode)this.parentNode.children=this.parentNode.children.filter(c=>c!==this);this.parentNode=null;}
  get firstChild(){return this.children[0]??null;} get childNodes(){return this.children;}
  get isConnected(){let node=this;while(node.parentNode)node=node.parentNode;return node===this.ownerDocument.documentElement;}
  addEventListener(type,handler){if(!this.listeners.has(type))this.listeners.set(type,new Set());this.listeners.get(type).add(handler);}
  removeEventListener(type,handler){this.listeners.get(type)?.delete(handler);}
  dispatch(type,values={}){const event={type,target:this,currentTarget:this,preventDefault(){this.defaultPrevented=true;},...values};for(const handler of this.listeners.get(type)||[])handler(event);return event;}
  dispatchEvent(event){this.dispatch(event.type,event);return true;}
  animate(frames,options){
    const doc=this.ownerDocument,started=doc.defaultView.performance.now();let offset=0;
    const animation={playState:'running',onfinish:null,oncancel:null,sampled:{},effect:{target:this,getKeyframes:()=>frames},
      cancel(){this.playState='idle';doc.animations.delete(this);this.oncancel?.();},
      get currentTime(){return doc.defaultView.performance.now()-started+offset;},
      set currentTime(value){offset=value-(doc.defaultView.performance.now()-started);},
      sample(){
        const time=this.currentTime,delay=options.delay||0,duration=options.duration||0;
        const progress=Math.max(0,Math.min(1,(time-delay)/(duration||1)));
        const keys=frames.map((frame,i)=>({...frame,offset:frame.offset??i/(frames.length-1)}));
        let b=keys.findIndex(frame=>frame.offset>=progress);if(b<1)b=1;
        const from=keys[b-1],to=keys[b],t=(progress-from.offset)/(to.offset-from.offset||1);
        for(const property of ['opacity'])if(from[property]!==undefined&&to[property]!==undefined)
          this.sampled[property]=Number(from[property])+(Number(to[property])-Number(from[property]))*t;
        if(time>=delay+duration&&this.playState==='running'){this.playState='finished';this.onfinish?.();}
      },
    };
    doc.animations.add(animation);animation.sample();return animation;
  }
  matches(selector){if(selector==='*')return true;if(selector[0]==='#')return this.id===selector.slice(1);if(selector[0]==='.')return this.classList.contains(selector.slice(1));return this.tagName.toLowerCase()===selector.toLowerCase();}
  querySelectorAll(selector){return this.children.flatMap(child=>[...(child.matches(selector)?[child]:[]),...child.querySelectorAll(selector)]);}
  querySelector(selector){return this.querySelectorAll(selector)[0]||null;}
  focus(){this.ownerDocument.activeElement=this;this.dispatch('focus');}
  getBoundingClientRect(){return {left:10,top:10,width:100,height:25};}
}
export function documentFromHTML(html){
  const doc={hidden:false,listeners:new Map(),activeElement:null,
    createElement(tag){return new Element(tag,this);},createElementNS(ns,tag){return new Element(tag,this);},
    getElementById(id){return this.documentElement.id===id?this.documentElement:this.documentElement.querySelector('#'+id);},
    addEventListener(type,handler){if(!this.listeners.has(type))this.listeners.set(type,new Set());this.listeners.get(type).add(handler);},
    removeEventListener(type,handler){this.listeners.get(type)?.delete(handler);},
    dispatch(type,event={}){for(const handler of this.listeners.get(type)||[])handler(event);},
  };
  const callbacks=new Map(),timers=new Map();let seq=0;
  const media={matches:false,listeners:new Set(),addEventListener(type,handler){this.listeners.add(handler);},removeEventListener(type,handler){this.listeners.delete(handler);},change(value){this.matches=value;for(const handler of this.listeners)handler({matches:value});}};
  doc.animations=new Set();
  doc.defaultView={Event:class{constructor(type){this.type=type;}},performance:{timeOrigin:900,now:()=>100},requestAnimationFrame:fn=>{callbacks.set(++seq,fn);return seq;},cancelAnimationFrame:id=>callbacks.delete(id),matchMedia:()=>media,
    setTimeout:(fn,delay)=>{timers.set(++seq,{fn,at:doc.defaultView.performance.now()+delay});return seq;},clearTimeout:id=>timers.delete(id)};
  doc.sampleAnimations=()=>{
    for(const animation of [...doc.animations])animation.sample();
    for(const [id,timer]of [...timers])if(timer.at<=doc.defaultView.performance.now()){timers.delete(id);timer.fn();}
  };
  doc.frames=callbacks;doc.media=media;
  const stack=[];
  for(const match of html.matchAll(/<\/?[a-zA-Z][^>]*>/g)){
    const token=match[0];if(token.startsWith('</')){stack.pop();continue;}
    const tag=token.match(/^<([^\s/>]+)/)[1].toLowerCase(),node=doc.createElement(tag);
    for(const attr of token.matchAll(/\s([^\s=/>]+)(?:="([^"]*)")?/g))node.setAttribute(attr[1],attr[2]??'');
    if(stack.length)stack.at(-1).appendChild(node);
    if(tag==='html')doc.documentElement=node;if(tag==='body')doc.body=node;
    if(!['meta','link','br','input','img','hr'].includes(tag)&&!token.endsWith('/>'))stack.push(node);
  }
  doc.documentElement.clientWidth=1600;doc.documentElement.clientHeight=900;
  return doc;
}
export function descendants(node){return 1+node.children.reduce((n,child)=>n+descendants(child),0);}
