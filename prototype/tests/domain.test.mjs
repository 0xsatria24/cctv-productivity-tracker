import test from 'node:test';
import assert from 'node:assert/strict';
import { summarize, clipIntervals, validPolygon, csvCell, duration } from '../src/domain.js';

test('occupied duration is counted once when the count changes, with a single session', () => {
  const records = [{ workspaceId: 'a', start: 0, end: 60_000, state: 'OCCUPIED', count: 1, revision: 1 }, { workspaceId: 'a', start: 60_000, end: 120_000, state: 'OCCUPIED', count: 2, revision: 1 }];
  const result = summarize(records);
  assert.equal(result.occupied, 120_000); assert.equal(result.countIntegral, 180_000); assert.equal(result.sessions, 1);
});
test('unknown is retained separately and ratios use weighted denominators', () => {
  const rows = ['OCCUPIED', 'EMPTY', 'UNKNOWN'].map((state, i) => ({ workspaceId: 'a', start: i * 60_000, end: (i + 1) * 60_000, state, count: state === 'UNKNOWN' ? null : 1, revision: 1 }));
  const result = summarize(rows);
  assert.equal(result.occupied + result.empty + result.unknown, result.eligible);
  assert.equal(result.utilization, 50); assert.equal(result.coverage, 100 * 2 / 3);
});
test('zero denominator is N/A and elapsed duration does not wrap at 24 hours', () => {
  assert.equal(summarize([]).coverage, null); assert.equal(summarize([]).utilization, null); assert.equal(duration(27 * 3600_000), '27:00:00');
});
test('custom ranges clip both ends of a session and keep the workspace scope', () => {
  const rows = [{ workspaceId: 'a', start: 0, end: 100, state: 'OCCUPIED' }, { workspaceId: 'b', start: 0, end: 100, state: 'EMPTY' }];
  assert.deepEqual(clipIntervals(rows, 20, 70, ['a']), [{ ...rows[0], start: 20, end: 70 }]);
});
test('polygon rejects self-intersection, duplicate nonadjacent geometry and invalid coordinates', () => {
  assert.equal(validPolygon([[.1,.1],[.9,.1],[.9,.9],[.1,.9]]), true);
  assert.equal(validPolygon([[.1,.1],[.9,.9],[.9,.1],[.1,.9]]), false);
  assert.equal(validPolygon([[.1,.1],[1.2,.1],[.4,.9]]), false);
});
test('CSV quotes user input and neutralizes spreadsheet formulas', () => {
  assert.equal(csvCell('=SUM(A1)'), '"\'=SUM(A1)"'); assert.equal(csvCell('Desk "A"'), '"Desk ""A"""');
});
