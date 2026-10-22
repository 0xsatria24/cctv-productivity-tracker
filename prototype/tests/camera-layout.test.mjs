import test from 'node:test';
import assert from 'node:assert/strict';
import { cameraView } from '../src/camera-layout.mjs';

const cameras = Array.from({ length: 17 }, (_, i) => ({ id: `camera-${i}` }));

test('grid and video wall use the same source order and selected density', () => {
  for (const layout of [1, 4, 9, 16]) {
    const options = { layout, selected: 'camera-8', page: 1 };
    const grid = cameraView(cameras, { ...options, mode: 'grid' });
    const wall = cameraView(cameras, { ...options, mode: 'wall' });
    assert.deepEqual(wall, grid);
    assert.deepEqual(grid.displayed, cameras.slice(layout, layout * 2));
    assert.equal(grid.capacity, layout);
  }
});

test('focus pins the selected camera across pages and reaches every companion once', () => {
  const companionIds = [];
  for (let page = 0; page < 4; page++) {
    const view = cameraView(cameras, { mode: 'focus', layout: 4, selected: 'camera-8', page });
    assert.equal(view.primaryId, 'camera-8');
    assert.equal(view.displayed[0].id, 'camera-8');
    assert.equal(view.capacity, 6);
    assert.equal(view.pages, 4);
    const ids = view.displayed.map(camera => camera.id);
    assert.equal(new Set(ids).size, ids.length);
    companionIds.push(...ids.slice(1));
  }
  assert.deepEqual(companionIds, cameras.filter(camera => camera.id !== 'camera-8').map(camera => camera.id));
});

test('removed or hidden primary falls back safely and short pages are clamped', () => {
  const view = cameraView(cameras.slice(0, 3), { mode: 'focus', selected: 'removed-camera', layout: 16, page: 10 });
  assert.equal(view.primaryId, 'camera-0');
  assert.equal(view.currentPage, 0);
  assert.deepEqual(view.displayed, cameras.slice(0, 3));
  const grid = cameraView(cameras.slice(0, 3), { mode: 'grid', layout: 4, page: 10 });
  assert.equal(grid.currentPage, 0);
  assert.deepEqual(grid.displayed, cameras.slice(0, 3));
});

test('focus with no enabled cameras has no duplicate or phantom sources', () => {
  const view = cameraView([], { mode: 'focus', layout: 4, page: 2 });
  assert.deepEqual(view.displayed, []);
  assert.equal(view.primaryId, undefined);
  assert.equal(view.pages, 1);
  assert.equal(view.currentPage, 0);
});
