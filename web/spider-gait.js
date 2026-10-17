/* Bounded, shared gait samples; exact IK is reserved for reaching and turns. */
import {SPIDER_GAIT_KEYFRAMES} from './animation-rules.js';
const TAU=Math.PI*2;
const finite=(v,f=0)=>Number.isFinite(v)?v:f;
const clamp=v=>Math.max(0,Math.min(1,finite(v)));
const unit=(x,y)=>{const length=Math.hypot(x,y)||1;return{x:x/length,y:y/length};};

// Stance travels backward relative to the body; only the return stroke lifts.
function stepAt(phase,stance=.64) {
  const cycle = ((phase / TAU) % 1 + 1) % 1;
  if (cycle < stance) return { along: cycle / stance - .5, lift: 0 };
  const swing = (cycle - stance) / (1-stance);
  return { along: .5 - swing * swing * (3 - 2 * swing), lift: Math.sin(swing * Math.PI) };
}

/** Local coordinates: four legs per side; index 0 is front, +Y is rearward. */
export function legPose({ side = 1, index = 0, walk = 0, phase = 0, target = null, stance = .64 } = {}) {
  const row = Math.max(0, Math.min(3, Math.floor(finite(index))));
  side = side < 0 ? -1 : 1;
  const root = { x: side * [7.5, 9, 9, 8][row], y: [-11, -5, 3, 10][row] };
  const step = stepAt(finite(phase) + (row % 2) * Math.PI + (side < 0 ? Math.PI : 0),stance);
  const strength = clamp(walk);
  const foot = target && Number.isFinite(target.x) && Number.isFinite(target.y)
    ? { x: target.x, y: target.y }
    : { x: side * ([42, 54, 53, 41][row] - step.lift * (stance===.5?3:5) * strength),
      y: [-36, -17, 15, 37][row] + step.along * 12 * strength - (stance===.5?0:step.lift*2.5*strength) };
  const aim = unit(foot.x - root.x, foot.y - root.y);
  const coxa = unit(side * .82 + aim.x * .35, (row < 2 ? -.28 : .28) + aim.y * .35);
  const elbow = { x: root.x + coxa.x * 11, y: root.y + coxa.y * 11 };
  const dx = foot.x - elbow.x, dy = foot.y - elbow.y;
  const distance = Math.hypot(dx, dy);
  const direction = distance > 1e-10 ? { x: dx / distance, y: dy / distance } : { x: side, y: 0 };
  // Two equal links fold all the way back. Far narrative targets extend the
  // telescopic links instead of silently clamping the requested contact point.
  const link = Math.max(24, distance / 2 + .001);
  const height = Math.sqrt(Math.max(0, link * link - distance * distance / 4));
  const bend = side * (row < 2 ? 1 : -1);
  const knee = { x: (elbow.x + foot.x) / 2 - direction.y * height * bend,
    y: (elbow.y + foot.y) / 2 + direction.x * height * bend };
  return { root, elbow, knee, foot, lift: step.lift * strength };
}


export function clawsFor(pose,opening){
  const {foot,knee}=pose,aim=unit(foot.x-knee.x,foot.y-knee.y),normal={x:-aim.y,y:aim.x};
  return [-1,1].map(side=>[
    {x:foot.x-aim.x*3,y:foot.y-aim.y*3},
    {x:foot.x-aim.x*1.1+normal.x*side*(opening+.65),y:foot.y-aim.y*1.1+normal.y*side*(opening+.65)},
    {x:foot.x+normal.x*side*opening,y:foot.y+normal.y*side*opening},
  ]);
}
const complete=(pose,front)=>({...pose,claws:clawsFor(pose,front?2.1:.85)});
const CACHE=Array.from({length:8},(_,number)=>{
  const side=number<4?1:-1,index=number%4,front=number===0;
  return {rest:complete(legPose({side,index}),front),frames:Array.from({length:SPIDER_GAIT_KEYFRAMES},(_,frame)=>
    complete(legPose({side,index,walk:1,phase:frame/SPIDER_GAIT_KEYFRAMES*TAU,stance:.5}),front))};
});

export function cachedLegPose(number,phase,walk){
  const {frames,rest}=CACHE[number],at=((phase/TAU)%1+1)%1*frames.length;
  const index=Math.floor(at),t=at-index,a=frames[index],b=frames[(index+1)%frames.length],strength=clamp(walk);
  const blend=(p,q,r)=>({x:r.x+strength*(p.x+(q.x-p.x)*t-r.x),y:r.y+strength*(p.y+(q.y-p.y)*t-r.y)});
  return {root:blend(a.root,b.root,rest.root),elbow:blend(a.elbow,b.elbow,rest.elbow),
    knee:blend(a.knee,b.knee,rest.knee),foot:blend(a.foot,b.foot,rest.foot),lift:(a.lift+(b.lift-a.lift)*t)*strength,
    claws:a.claws.map((claw,i)=>claw.map((p,j)=>blend(p,b.claws[i][j],rest.claws[i][j])))};
}
