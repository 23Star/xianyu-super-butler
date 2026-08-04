import { rm } from 'node:fs/promises';
import { resolve } from 'node:path';
import { fileURLToPath } from 'node:url';

const frontendDir = resolve(fileURLToPath(new URL('..', import.meta.url)));
const staticDir = resolve(frontendDir, '..', 'static');
const targets = [
  resolve(staticDir, 'assets'),
  resolve(staticDir, 'index.html'),
];

for (const target of targets) {
  const relativeTarget = target.slice(staticDir.length + 1);
  if (!relativeTarget || relativeTarget.startsWith('..')) {
    throw new Error(`Refusing to clean outside static directory: ${target}`);
  }
  await rm(target, { recursive: true, force: true });
}

console.log('Removed previous frontend build output from static/assets and static/index.html.');
