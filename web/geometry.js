// World coordinates shared by the cached room, sprites, and native travel.
export const SCENE_WIDTH=1200;
export const SCENE_TOP=35;
export const SCENE_HEIGHT=600;
export const SCENE_VIEWBOX=`0 ${SCENE_TOP} ${SCENE_WIDTH} ${SCENE_HEIGHT}`;
export const LOWER_SHIFT=0;
export const SCREEN_CONTENT=Object.freeze({left:354,top:92,right:836,bottom:229});
export const WEB_CENTER=Object.freeze({x:595,y:153});
export const WEB_RADII=Object.freeze({x:221,y:60});
export const WEB_SPOKES=16;
export const WEB_SPIRALS=6;
export const COCOON_LIMIT=60;
export const CAPTURE_CENTER=Object.freeze({x:WEB_CENTER.x-137,y:WEB_CENTER.y});
export const capturePoint=index=>({x:410+(index%2)*7,y:WEB_CENTER.y-27+index*7});
export const lowerPoint=(x,y)=>({x,y:y+LOWER_SHIFT});
export const RADAR_ORIGIN=Object.freeze(lowerPoint(1060,492));
export const RADAR_EMITTER=Object.freeze(lowerPoint(1078,488));
export const SHREDDER_ORIGIN=Object.freeze(lowerPoint(145,485));
