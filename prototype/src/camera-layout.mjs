export const CAMERA_MODES = [
  { value: 'grid', label: 'Grid' },
  { value: 'focus', label: 'Fokus' },
  { value: 'wall', label: 'Video wall' },
];

// Source order stays stable; the primary camera never also occupies a companion slot.
export function cameraView(cameras, { mode, layout, page = 0, selected }) {
  const primary = mode === 'focus' ? cameras.find(camera => camera.id === selected) || cameras[0] : null;
  const candidates = primary ? cameras.filter(camera => camera.id !== primary.id) : cameras;
  const pageSize = mode === 'focus' ? 5 : layout;
  const pages = Math.max(1, Math.ceil(candidates.length / pageSize));
  const currentPage = Math.max(0, Math.min(page, pages - 1));
  const companions = candidates.slice(currentPage * pageSize, (currentPage + 1) * pageSize);
  return {
    displayed: primary ? [primary, ...companions] : companions,
    primaryId: primary?.id,
    capacity: mode === 'focus' ? 6 : layout,
    pages,
    currentPage,
  };
}
