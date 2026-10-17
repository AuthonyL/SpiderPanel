import {SCREEN_CONTENT,WEB_CENTER} from './silk.js';

const RAMP_MS=200,STEPS=60,EPSILON=1e-8;
const plans=new WeakMap();
const distance=(a,b)=>Math.hypot(b.x-a.x,b.y-a.y);
const clamp=(value,low,high)=>Math.max(low,Math.min(high,value));

// Distances are pixels, speeds pixels/second, and internal times seconds.
// Short routes lower the peak while keeping both 200ms ramps. Nonzero
// boundary speeds can require shorter ramps to fit the available distance.
function speedProfile(length,maxSpeed,startSpeed,endSpeed){
  if(!length)return {duration:0,boundaries:[],distanceAt:()=>0,timeAt:()=>0};
  const targetRamp=RAMP_MS/1000;
  const peak=clamp(length/targetRamp-(startSpeed+endSpeed)/2,Math.max(startSpeed,endSpeed),maxSpeed);
  const ramp=Math.min(targetRamp,length/(peak+(startSpeed+endSpeed)/2));
  const acceleration=(peak-startSpeed)/ramp,deceleration=(peak-endSpeed)/ramp;
  const firstDistance=(startSpeed+peak)*ramp/2,lastDistance=(peak+endSpeed)*ramp/2;
  const cruise=Math.max(0,(length-firstDistance-lastDistance)/peak),duration=2*ramp+cruise;
  const rampTime=(arc,speed,acceleration)=>arc===0?0:2*arc/(speed+Math.sqrt(speed*speed+2*acceleration*arc));
  return {duration,boundaries:[ramp,ramp+cruise],distanceAt(time){
    if(time<=0)return 0;
    if(time>=duration)return length;
    if(time<ramp)return startSpeed*time+acceleration*time*time/2;
    if(time<ramp+cruise)return firstDistance+peak*(time-ramp);
    const remaining=duration-time;
    return length-endSpeed*remaining-deceleration*remaining*remaining/2;
  },timeAt(arc){
    if(arc<=0)return 0;
    if(arc>=length)return duration;
    if(arc<firstDistance)return rampTime(arc,startSpeed,acceleration);
    if(arc>length-lastDistance)return duration-rampTime(length-arc,endSpeed,deceleration);
    return ramp+(arc-firstDistance)/peak;
  }};
}

function routeProfile(vertices,lengths,speed,initial,terminal){
  const breaks=[0];
  for(let i=1;i<vertices.length-1;i++){
    const a=vertices[i-1],b=vertices[i],c=vertices[i+1];
    const cosine=((b.x-a.x)*(c.x-b.x)+(b.y-a.y)*(c.y-b.y))/(distance(a,b)*distance(b,c));
    if(cosine<.5)breaks.push(i); // Slow down before a sharp change of spoke.
  }
  breaks.push(vertices.length-1);
  if(breaks.length===2)return speedProfile(lengths.at(-1),speed,initial,terminal);
  const legs=[];let duration=0;
  for(let i=1;i<breaks.length;i++){
    const start=lengths[breaks[i-1]],end=lengths[breaks[i]];
    const profile=speedProfile(end-start,speed,i===1?initial:0,i===breaks.length-1?terminal:0);
    legs.push({start,end,at:duration,profile});duration+=profile.duration;
  }
  return {duration,boundaries:legs.flatMap((leg,i)=>[
    ...leg.profile.boundaries.map(time=>leg.at+time),...(i<legs.length-1?[leg.at+leg.profile.duration]:[])]),
    distanceAt(time){
      const leg=legs.find(leg=>time<leg.at+leg.profile.duration)||legs.at(-1);
      return leg.start+leg.profile.distanceAt(time-leg.at);
    },timeAt(arc){
      const leg=legs.find(leg=>arc<leg.end)||legs.at(-1);
      return leg.at+leg.profile.timeAt(arc-leg.start);
    }};
}

export function planSilkTravel(from,to,{bounds=SCREEN_CONTENT,confine,maxSpeed,startSpeed=0,endSpeed=0}={}){
  const project=point=>{
    if(!Number.isFinite(point?.x)||!Number.isFinite(point?.y))throw new RangeError('Invalid travel point');
    const safe=typeof confine==='function'?confine({x:point.x,y:point.y}):point;
    return {x:clamp(safe.x,bounds.left,bounds.right),y:clamp(safe.y,bounds.top,bounds.bottom)};
  };
  const first=project(from),last=project(to),hub=project(WEB_CENTER);
  const speed=maxSpeed??(bounds.right-bounds.left)/3;
  if(!Number.isFinite(speed)||speed<=0)throw new RangeError('Invalid travel speed');
  const initial=clamp(startSpeed,0,speed),terminal=clamp(endSpeed,0,speed);
  if(!Number.isFinite(initial)||!Number.isFinite(terminal))throw new RangeError('Invalid travel boundary speed');
  const a={x:first.x-hub.x,y:first.y-hub.y},b={x:last.x-hub.x,y:last.y-hub.y};
  const sameRay=Math.abs(a.x*b.y-a.y*b.x)<=EPSILON*Math.max(1,Math.hypot(a.x,a.y)*Math.hypot(b.x,b.y))&&a.x*b.x+a.y*b.y>=0;
  const vertices=(sameRay?[first,last]:[first,hub,last]).filter((point,index,all)=>!index||distance(point,all[index-1])>EPSILON);
  const lengths=[0];
  for(let i=1;i<vertices.length;i++)lengths.push(lengths.at(-1)+distance(vertices[i-1],vertices[i]));
  const length=lengths.at(-1),profile=routeProfile(vertices,lengths,speed,initial,terminal),duration=profile.duration*1000;
  const at=arc=>{
    if(arc<=0)return {...first};
    if(arc>=length)return {...last};
    let i=1;while(i<lengths.length-1&&lengths[i]<arc)i++;
    const t=(arc-lengths[i-1])/(lengths[i]-lengths[i-1]),a=vertices[i-1],b=vertices[i];
    return {x:a.x+(b.x-a.x)*t,y:a.y+(b.y-a.y)*t};
  };
  const steps=profile.boundaries.length>2?56:STEPS;
  const turnFrames=profile.boundaries.length>2?lengths.slice(1,-1).flatMap(arc=>{
    const time=profile.timeAt(arc);return [time-.015,time+.015].map(time=>clamp(time/profile.duration,0,1));
  }):[];
  const offsets=length?[...Array.from({length:steps+1},(_,i)=>i/steps),
    ...profile.boundaries.map(time=>time/profile.duration),
    ...turnFrames,
    ...lengths.slice(1,-1).map(arc=>profile.timeAt(arc)/profile.duration)].sort((a,b)=>a-b):[0];
  const frames=offsets.filter((offset,index)=>!index||offset-offsets[index-1]>Number.EPSILON)
    .map(offset=>({offset,...at(profile.distanceAt(offset*profile.duration))}));
  // Keep bends exact even when inversion rounds the corresponding arc length.
  for(let i=1;i<lengths.length-1;i++){
    const offset=profile.timeAt(lengths[i])/profile.duration,frame=frames.find(frame=>Math.abs(frame.offset-offset)<Number.EPSILON*2);
    if(frame)Object.assign(frame,vertices[i]);
  }
  const frameDistances=[0];
  for(let i=1;i<frames.length;i++)frameDistances.push(frameDistances.at(-1)+distance(frames[i-1],frames[i]));
  const segmentAt=offset=>{
    let low=0,high=frames.length-1;
    while(high-low>1){const middle=(low+high)>>1;if(frames[middle].offset<=offset)low=middle;else high=middle;}
    return [frames[low],frames[high],low];
  };
  const plan={frames,duration,sample(elapsedMs){
    if(!duration||elapsedMs<=0)return {x:frames[0].x,y:frames[0].y};
    const offset=clamp(elapsedMs/duration,0,1);
    if(offset>=1)return {x:frames.at(-1).x,y:frames.at(-1).y};
    const [a,b]=segmentAt(offset),t=(offset-a.offset)/(b.offset-a.offset);
    return {x:a.x+(b.x-a.x)*t,y:a.y+(b.y-a.y)*t};
  },distanceAt(elapsedMs){
    if(!duration||elapsedMs<=0)return 0;
    if(elapsedMs>=duration)return frameDistances.at(-1);
    const offset=elapsedMs/duration,[a,b,i]=segmentAt(offset),t=(offset-a.offset)/(b.offset-a.offset);
    return frameDistances[i]+(frameDistances[i+1]-frameDistances[i])*t;
  },velocityAt(elapsedMs){
    if(!duration||elapsedMs<0)return {x:0,y:0};
    if(elapsedMs>=duration){
      if(!terminal)return {x:0,y:0};
      const a=vertices.at(-2),b=vertices.at(-1),scale=terminal/distance(a,b);
      return {x:(b.x-a.x)*scale,y:(b.y-a.y)*scale};
    }
    // WAAPI interpolates linearly between uploaded frames. Its segment slope,
    // rather than the analytic ramp derivative, is the body's actual velocity.
    const [a,b]=segmentAt(elapsedMs/duration),seconds=(b.offset-a.offset)*duration/1000;
    return {x:(b.x-a.x)/seconds,y:(b.y-a.y)/seconds};
  }};
  plans.set(plan,{to:last,bounds,confine,maxSpeed:speed,startSpeed:initial,endSpeed:terminal});
  return plan;
}

// A replacement may have been planned before the old native animation was
// sampled. Rebuild its route and timing from the committed current position.
export function rebaseSilkTravel(plan,from){
  if(distance(plan.frames[0],from)<=EPSILON)return plan;
  const options=plans.get(plan);
  if(!options)throw new TypeError('Travel requires a planSilkTravel plan');
  return planSilkTravel(from,options.to,options);
}
