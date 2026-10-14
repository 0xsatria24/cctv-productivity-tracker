import { mkdirSync, existsSync, writeFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';

// Deterministic moving YUV test frames. This source is used only by Chromium's fake-camera flag.
export function cameraTestVideo() {
  const directory = new URL('../../../runtime/test-media/', import.meta.url);
  mkdirSync(directory, { recursive: true });
  const destination = new URL('webcam-v1.y4m', directory);
  if (!existsSync(destination)) {
    const width = 320, height = 240;
    const parts = [Buffer.from(`YUV4MPEG2 W${width} H${height} F20:1 Ip A1:1 C420jpeg\n`)];
    for (let frame = 0; frame < 120; frame++) {
      const pixels = Buffer.alloc(width * height * 3 / 2, 128);
      pixels.fill(35, 0, width * height);
      const left = 20 + frame * 2 % 240;
      for (let y = 80; y < 160; y++) pixels.fill(210, y * width + left, y * width + left + 40);
      parts.push(Buffer.from('FRAME\n'), pixels);
    }
    writeFileSync(destination, Buffer.concat(parts), { flag: 'wx' });
  }
  return fileURLToPath(destination);
}
