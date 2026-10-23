import { test } from 'node:test';
import assert from 'node:assert/strict';
import { recentReplaySessions,replayCaptureSize,replayDisplayPacket } from '../src/replay-domain.js';

test('current timers precede lost fragments without rewriting their durations',()=>{
  const rows=[{session_id:'old',status:'LOST',last_seen_media_seconds:3,accumulated_duration_us:2e6},
    {session_id:'current',status:'ACTIVE',last_seen_media_seconds:8,accumulated_duration_us:4e6},
    {session_id:'recent-lost',status:'LOST',last_seen_media_seconds:7,accumulated_duration_us:1e6}];
  assert.deepEqual(recentReplaySessions(rows).map(s=>s.session_id),['current','recent-lost','old']);
  assert.equal(rows[0].session_id,'old');
});

test('frame capture preserves aspect ratio and stays within JPEG limits',()=>{
  for(const [width,height] of [[1920,1080],[1080,1920],[640,480],[3840,2160]]){
    const size=replayCaptureSize(width,height);
    assert.ok(size.width*size.height<=1280*720);
    assert.ok(Math.abs(size.width/size.height-width/height)<.005);
    assert.ok(size.width<=960&&size.height<=960);
  }
});

test('held positions expire by media time including response latency and playback speed',()=>{
  const measured={measured:true}, held={measured:false,prediction_age_seconds:.2};
  const packet={media_time_seconds:1,display_detections:[measured,held]};
  const fresh=replayDisplayPacket(packet,1.1,2);
  assert.equal(fresh.packet.display_detections.length,2);
  assert.ok(Math.abs(fresh.lifetime-50)<.01);
  assert.deepEqual(replayDisplayPacket(packet,1.3,1).packet.display_detections,[measured]);
  assert.equal(replayDisplayPacket({media_time_seconds:1,detections:[measured]},1.1,1).lifetime,750);
});
