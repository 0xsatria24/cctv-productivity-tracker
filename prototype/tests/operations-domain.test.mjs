import test from 'node:test';
import assert from 'node:assert/strict';
import { currentObservation, localInput, localToUtc, periodRange } from '../src/operations-domain.mjs';

test('report wall times use the location timezone instead of the OS timezone', () => {
  const utc = Date.parse('2026-10-12T02:30:00Z') * 1000;
  assert.equal(localInput(utc, 'Asia/Jakarta'), '2026-10-12T09:30:00');
  assert.equal(localToUtc('2026-10-12T09:30', 'Asia/Jakarta'), utc);
  assert.equal(localToUtc('2026-02-30T09:30', 'Asia/Jakarta'), null);
  assert.equal(localToUtc('2026-10-12T25:30', 'Asia/Jakarta'), null);
});
test('overnight shifts cross midnight and weekly ranges include seven local days', () => {
  const range = periodRange('shift', '2026-10-12', 'Asia/Jakarta', '23:00', '07:00');
  assert.equal(range.start, Date.parse('2026-10-12T16:00:00Z') * 1000);
  assert.equal(range.end, Date.parse('2026-10-13T00:00:00Z') * 1000);
  const week = periodRange('week', '2026-10-12', 'Asia/Jakarta');
  assert.equal((week.end - week.start) / 1e6, 7 * 86400);
  assert.throws(() => periodRange('shift', '2026-10-12', 'Asia/Jakarta', '07:00', '07:00'));
});
test('day boundaries respect DST and ambiguous/nonexistent custom times are rejected', () => {
  const spring = periodRange('day', '2026-03-08', 'America/New_York');
  const fall = periodRange('day', '2026-11-01', 'America/New_York');
  assert.equal((spring.end - spring.start) / 1e6, 23 * 3600);
  assert.equal((fall.end - fall.start) / 1e6, 25 * 3600);
  assert.equal(localToUtc('2026-03-08T02:30', 'America/New_York'), null);
  assert.equal(localToUtc('2026-11-01T01:30', 'America/New_York'), null);
});
test('live counts require fresh evidence; stopped or failed polls do not retain observed counts', () => {
  const state = { status: 'RUNNING', camera_health: 'ONLINE', preview_only: false,
    latest: { count: 1, zones: [{ state: 'OCCUPIED' }, { state: 'UNKNOWN' }] } };
  assert.equal(currentObservation(state, 1000, 2000).count, 1);
  assert.equal(currentObservation(state, 1000, 2000).occupied, 1);
  assert.equal(currentObservation(state, 1000, 2000).unknown, 1);
  assert.equal(currentObservation(state, 1000, 6000).count, null);
  assert.equal(currentObservation(state, 1000, 2000, 'offline').count, null);
  assert.equal(currentObservation({ ...state, status: 'STOPPED' }, 1000, 2000).count, null);
  assert.deepEqual(currentObservation({ ...state, preview_only: true }, 1000, 2000).zones, []);
});
