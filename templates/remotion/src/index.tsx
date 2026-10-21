import React from 'react';
import {registerRoot,Composition,AbsoluteFill,useCurrentFrame,Audio,staticFile} from 'remotion';
import timeline from './timeline.compiled.json';
import captions from './captions.json';
import {sceneClock} from './scene-clock.cjs';
import {Scene} from './Scene';
type Props={audioSrc:string|null};
type Caption={startMs:number;endMs:number;text:string};
const Film:React.FC<Props>=({audioSrc})=>{
  const frame=useCurrentFrame(),clock=sceneClock(timeline,frame);
  const cap=(captions as Caption[]).find(c=>frame*1000/timeline.fps>=c.startMs&&frame*1000/timeline.fps<c.endMs);
  return <AbsoluteFill style={{background:'#172b38'}}>
    <Scene clock={clock}/>
    {cap&&<div style={{position:'absolute',left:80,top:1540,width:920,height:180,display:'flex',alignItems:'center',justifyContent:'center',background:'#09131c',color:'white',fontFamily:'Arial,sans-serif',fontSize:52,lineHeight:'62px',fontWeight:700,textAlign:'center',whiteSpace:'pre-line'}}>{cap.text}</div>}
    {audioSrc&&<Audio src={staticFile(audioSrc)}/>}
  </AbsoluteFill>;
};
registerRoot(()=> <Composition id="Episode" component={Film} width={1080} height={1920} fps={timeline.fps} durationInFrames={timeline.total_frames} defaultProps={{audioSrc:null}}/>);
