import test from 'node:test';
import assert from 'node:assert/strict';
import { readRoute, routeHash } from '../src/navigation.mjs';
import { monitoringState } from '../src/camera-status.mjs';
import { currentObservation } from '../src/operations-domain.mjs';

test('old report links open the unified export tab; camera links retain live access',()=>{
  assert.deepEqual(readRoute('#/reports'),{page:'analytics',tab:'export'});
  assert.deepEqual(readRoute('#/cameras'),{page:'live',tab:'summary'});
  for(const tab of ['summary','daily','timeline','export']) assert.equal(readRoute(routeHash('analytics',tab)).tab,tab);
});

test('only the matching camera with committed evidence is labelled monitoring',()=>{
  const camera={id:'a',camera_key:'key-a'};
  const live={active:true,receivedAt:1000,state:{source:'RTSP_LIVE',camera_key:'key-a',camera_health:'ONLINE',latest:{recorded:true}}};
  assert.equal(monitoringState(camera,live,1100).label,'Monitoring aktif');
  assert.equal(monitoringState({id:'b',camera_key:'key-b'},live,1100).label,'Preview saja');
  assert.equal(monitoringState(camera,{...live,state:{...live.state,preview_only:true}},1100).label,'Perlu zona');
  assert.equal(monitoringState(camera,{...live,state:{...live.state,preview_only:true,camera_health:'OFFLINE'}},1100).label,'Preview belum tersambung');
  assert.equal(monitoringState(camera,live,6000).label,'Bukti terhenti');
  assert.equal(monitoringState(camera,{...live,state:{...live.state,latest:{recorded:false}}},1100).label,'Menunggu bukti');
  assert.equal(monitoringState(camera,{...live,state:{...live.state,camera_health:'OFFLINE'}},1100).label,'Bukti terhenti');
  assert.equal(monitoringState(camera,{...live,state:{...live.state,processed:10,latest:null}},1100).label,'Bukti terhenti');
  assert.equal(currentObservation({...live.state,status:'RUNNING',preview_only:true,latest:{count:0}},1000,1100).count,null);
});
