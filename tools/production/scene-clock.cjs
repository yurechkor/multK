// One deterministic clock for Remotion, file rendering and short proofs.
// Adapters pass these values into the SAME scene component; no copied scene bodies.
function sceneClock(timeline, frame) {
  if (!Number.isInteger(frame) || frame < 0 || frame >= timeline.total_frames) {
    throw new Error('Frame outside timeline');
  }
  const shot = timeline.shots.find(s => frame >= s.from && frame < s.to);
  if (!shot) throw new Error('Timeline has a gap');
  return {
    shot,
    frame,
    localFrame: frame - shot.from,
    seconds: frame / timeline.fps,
    localSeconds: (frame - shot.from) / timeline.fps,
    durationSeconds: shot.frames / timeline.fps,
    event: id => {
      const event = timeline.events.find(e => e.id === id);
      if (!event) throw new Error(`Unknown event: ${id}`);
      return { ...event, ageFrames: frame - event.frame, ageSeconds: (frame - event.frame) / timeline.fps };
    },
  };
}
module.exports = { sceneClock };
