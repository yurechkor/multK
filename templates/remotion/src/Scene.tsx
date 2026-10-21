import React from 'react';
// Technical fixture only. Replace with the episode's approved staging.
export const Scene: React.FC<{clock: any}> = ({clock}) => {
  const event=clock.event('contact'),u=Math.max(0,Math.min(1,(event.ageFrames+30)/30));
  const y=320+770*u*u,settle=Math.max(0,1-event.ageFrames/12);
  const squash=event.ageFrames>=0?Math.sin(settle*Math.PI)*.12:0;
  return <svg width="1080" height="1920" viewBox="0 0 1080 1920">
    <defs><radialGradient id="material" cx="30%" cy="24%"><stop stopColor="#ffe7a2"/><stop offset=".6" stopColor="#de912a"/><stop offset="1" stopColor="#7f4518"/></radialGradient></defs>
    <rect width="1080" height="1920" fill="#172b38"/>
    <ellipse cx="540" cy="1225" rx={90+80*u} ry="20" fill="#09131c" opacity={.2+.4*u}/>
    <path d="M80 1230H1000V1300H80Z" fill="#537585"/>
    <ellipse cx="540" cy={y} rx={140*(1+squash)} ry={140*(1-squash)} fill="url(#material)"/>
  </svg>;
};
