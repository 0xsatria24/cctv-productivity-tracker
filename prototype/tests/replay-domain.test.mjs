import { test } from 'node:test';
import assert from 'node:assert/strict';
import { recentReplaySessions,replayCaptureSize,replayDisplayPacket,storedReplayCalibration,ReplayOverlayMotion,replayTrackLabel,rectangleZone,replaySessionId,replayCalibrationState,replayAreaAt } from '../src/replay-domain.js';
import {workstationIntervalMs} from '../src/workstation-engine.js';

test('both video sources honor server workstation cadence and reject invalid scheduling values',()=>{
  assert.equal(workstationIntervalMs(2),500);
  assert.equal(workstationIntervalMs(5),200);
  assert.equal(workstationIntervalMs(1),1000);
  for(const value of [undefined,null,NaN,0,-1,Infinity,1000])assert.equal(workstationIntervalMs(value),500);
});

test('area preview follows backward and forward seeks without changing saved totals or counting gaps',()=>{
  const row={occupied_us:4e6,empty_us:2e6,media_intervals:[
    [0,2e6,'UNKNOWN'],[2e6,5e6,'OCCUPIED'],[5e6,7e6,'EMPTY'],[100e6,101e6,'OCCUPIED']]};
  const original=structuredClone(row);
  assert.equal(replayAreaAt(row,5).occupied_us,3e6);
  assert.equal(replayAreaAt(row,3).occupied_us,1e6);
  assert.equal(replayAreaAt(row,4).occupied_us,2e6);
  assert.equal(replayAreaAt(row,2.5).occupied_us,.5e6);
  assert.deepEqual(replayAreaAt(row,6),{occupied_us:3e6,empty_us:1e6,state:'EMPTY',available:true});
  assert.deepEqual(replayAreaAt(row,50),{occupied_us:3e6,empty_us:2e6,state:'UNKNOWN',available:true});
  assert.equal(replayAreaAt(row,100.5).occupied_us,3.5e6);
  assert.equal(replayAreaAt(row,0).occupied_us,0);
  assert.deepEqual(row,original);
});

test('old totals never masquerade as a timer at an unanalyzed replay position',()=>{
  assert.equal(replayAreaAt({occupied_us:50e6},10),null);
  assert.equal(replayAreaAt({occupied_us:50e6,media_intervals:[]},10).available,false);
  assert.equal(replayAreaAt({media_intervals:[]},0).occupied_us,0);
  assert.equal(replayAreaAt({media_intervals:[[100e6,102e6,'OCCUPIED']]},10).occupied_us,0);
});

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
  assert.ok(Math.abs(fresh.lifetime-150)<.01);
  assert.deepEqual(replayDisplayPacket(packet,1.3,1).packet.display_detections,[measured]);
  assert.ok(Math.abs(replayDisplayPacket({media_time_seconds:1,detections:[measured]},1.1,1).lifetime-300)<.01);
  assert.deepEqual(replayDisplayPacket(packet,1.41,1).packet.display_detections,[]);
});

const measured=(id,box,extra={})=>({session_id:id,box,measured:true,accumulated_duration_us:7e6,...extra});
const motionPacket=(at,rows,generation=0)=>({media_time_seconds:at,generation,display_detections:rows});

test('server prediction lifetime bounds both packet holds and render animation',()=>{
  for(const seconds of [0,.1,.4,1]) {
    const packet={...motionPacket(1,[measured('a',[.2,.2,.4,.8])]),display_prediction_seconds:seconds};
    const motion=new ReplayOverlayMotion();motion.accept(packet);
    assert.deepEqual(replayDisplayPacket(packet,1+seconds+.001,1).packet.display_detections,[]);
    assert.deepEqual(motion.sample(1+seconds+.001),[]);
  }
});

test('temporary track labels include tracker epoch and do not masquerade as person identity',()=>{
  assert.equal(replayTrackLabel('file-uuid:0:1:3'),'T1.3');
  assert.equal(replayTrackLabel('file-uuid:0:2:3'),'T2.3');
  assert.equal(replayTrackLabel(null),'Track belum pasti');
  assert.equal(replayTrackLabel('malformed'),'Track belum pasti');
});

test('one expired hold cannot erase another person and media time bounds every box',()=>{
  const motion=new ReplayOverlayMotion();
  motion.accept(motionPacket(1,[measured('current',[.1,.1,.3,.8]),measured('lost',[.6,.1,.8,.8],{measured:false,prediction_age_seconds:.3})]));
  assert.equal(motion.sample(1.02).length,2);
  assert.deepEqual(motion.sample(1.11).map(row=>row.session_id),['current']);
  assert.deepEqual(motion.sample(1.41),[]);
});

test('render frames move smoothly without changing server identity or accumulated time',()=>{
  const motion=new ReplayOverlayMotion(),first=motionPacket(1,[measured('same',[.1,.1,.3,.8])]);
  motion.accept(first);motion.sample(1);
  const next=motionPacket(1.2,[measured('same',[.13,.1,.33,.8])]);
  const original=structuredClone(next);
  motion.accept(next);
  const positions=[1.2,1.216,1.232,1.248].map(at=>motion.sample(at)[0]);
  for(let i=1;i<positions.length;i++)assert.ok(positions[i].box[0]>positions[i-1].box[0]);
  assert.ok(positions[0].box[0]<.13);
  assert.ok(positions.every(row=>row.session_id==='same' && row.accumulated_duration_us===7e6));
  assert.ok(positions.slice(1).every(row=>row.visual_estimate));
  assert.deepEqual(next,original);
  assert.deepEqual(first.display_detections[0].box,[.1,.1,.3,.8]);
});

test('generation, seek, new identities and geometry jumps do not inherit old motion',()=>{
  const motion=new ReplayOverlayMotion();
  motion.accept(motionPacket(1,[measured('a',[.1,.1,.3,.8])]));motion.sample(1);
  motion.accept(motionPacket(1.2,[measured('b',[.7,.1,.9,.8])]));
  assert.equal(motion.sample(1.2)[0].box[0],.7);
  motion.accept(motionPacket(1.4,[measured('b',[.1,.1,.3,.8])]));
  assert.equal(motion.sample(1.4)[0].box[0],.1);
  motion.accept(motionPacket(0,[measured('b',[.6,.1,.8,.8])],1));
  assert.equal(motion.sample(0)[0].box[0],.6);
  assert.deepEqual(motion.sample(-.01),[]);
  assert.deepEqual(motion.sample(.1),[]);
});

test('the same raw track with a different timer session never inherits displayed time or motion',()=>{
  const motion=new ReplayOverlayMotion(),track_id='file:0:1:3';
  motion.accept(motionPacket(1,[measured('old',[.1,.1,.3,.8],{track_id})]));motion.sample(1);
  motion.accept(motionPacket(1.2,[measured('new',[.13,.1,.33,.8],{track_id,accumulated_duration_us:0})]));
  const row=motion.sample(1.2)[0];
  assert.equal(row.box[0],.13);
  assert.equal(row.accumulated_duration_us,0);
  assert.equal(row.session_id,'new');
  assert.equal(replayTrackLabel(row.track_id),'T1.3');
});

test('prediction is bounded at frame edges and disabled for overlapping people',()=>{
  const motion=new ReplayOverlayMotion();
  motion.accept(motionPacket(1,[measured('a',[.6,.1,.8,.8])]));motion.sample(1);
  motion.accept(motionPacket(1.2,[measured('a',[.75,.1,.95,.8])]));
  for(let at=1.2;at<1.59;at+=.016) {
    const row=motion.sample(at)[0];assert.ok(row.box[2]<=1);assert.ok(row.box[0]>=0);
  }
  motion.clear();
  motion.accept(motionPacket(1,[measured('a',[.1,.1,.3,.8])]));motion.sample(1);
  motion.accept(motionPacket(1.2,[measured('a',[.13,.1,.33,.8]),measured('b',[.2,.1,.4,.8])]));
  for(let at=1.2;at<1.59;at+=.016)assert.ok(motion.sample(at)[0].box[0]<=.13);
});

test('corrupt browser calibration cannot become a rendered or active workstation',()=>{
  const zone={id:'a',name:'Meja',polygon:[[.1,.1],[.9,.1],[.9,.9],[.1,.9]]};
  const value={association:'bbox_overlap',zones:[zone]};
  assert.deepEqual(storedReplayCalibration(value),value);
  for(const invalid of [null,{}, {...value,zones:[zone,zone]}, {...value,zones:[{...zone,polygon:[null]}]},
    {...value,zones:[{...zone,polygon:[[0,0],[1,1],[0,1],[1,0]]}]}, {...value,association:'unknown'}]) {
    assert.equal(storedReplayCalibration(invalid),null);
  }
});

test('saved marker registry retains explicit IDs and rejects duplicate or malformed identities',()=>{
  const base={association:'bbox_overlap',zones:[],markers:[{marker_id:7,label:'Pekerja A'}]};
  assert.deepEqual(storedReplayCalibration(base),base);
  for(const markers of [[{marker_id:7,label:' '}],[{marker_id:50,label:'A'}],[{marker_id:true,label:'A'}],
    [...base.markers,...base.markers],null])assert.equal(storedReplayCalibration({...base,markers}),null);
});

test('drawing an area backwards or outside the picture keeps normalized corner order',()=>{
  assert.deepEqual(rectangleZone([.8,.9],[.2,.1]),[[.2,.1],[.8,.1],[.8,.9],[.2,.9]]);
  assert.deepEqual(rectangleZone([-.2,1.3],[.5,.4]),[[0,.4],[.5,.4],[.5,1],[0,1]]);
});

test('reopening the same source retains its replay identity without mixing distinct files',()=>{
  const values=new Map(),storage={getItem:key=>values.get(key),setItem:(key,value)=>values.set(key,value)};
  const first=replaySessionId('one.mp4:123:456',storage);
  assert.equal(replaySessionId('one.mp4:123:456',storage),first);
  assert.notEqual(replaySessionId('two.mp4:123:456',storage),first);
  values.set('replay-session-v2:broken','../../other');
  assert.match(replaySessionId('broken',storage),/^[a-f0-9-]{36}$/);
});

test('restore waits out a checkpoint lock rather than replacing saved totals with zero',async()=>{
  let calls=0;
  const packet={workstations:[{occupied_us:34_000_000}]};
  const fetcher=async()=>++calls<3?{status:429,ok:false,json:async()=>({detail:'Frame masih diproses'})}:{status:200,ok:true,json:async()=>packet};
  assert.deepEqual(await replayCalibrationState('/state',{fetcher,pause:async()=>{}}),packet);
  assert.equal(calls,3);
  await assert.rejects(replayCalibrationState('/state',{fetcher:async()=>({status:422,ok:false,json:async()=>({detail:'Data rusak'})})}),/Data rusak/);
});
