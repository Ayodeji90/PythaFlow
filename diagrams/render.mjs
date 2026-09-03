import fs from 'fs';
import path from 'path';
import { fileURLToPath } from 'url';
import { render } from '@mermaid-js/mermaid-cli';

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const input = path.join(__dirname, 'balance-architecture.mmd');
const outputSvg = path.join(__dirname, 'balance-architecture.svg');
const outputPng = path.join(__dirname, 'balance-architecture.png');

const mmd = fs.readFileSync(input, 'utf-8');

try {
  // Render SVG
  await render(mmd, { output: outputSvg, format: 'svg' });
  console.log('SVG rendered to:', outputSvg);
  
  // Render PNG
  await render(mmd, { output: outputPng, format: 'png', width: 1920 });
  console.log('PNG rendered to:', outputPng);
} catch (e) {
  console.error('Render failed:', e.message);
  process.exit(1);
}