import { readFileSync } from 'node:fs';
import { calculateLogisticsQuote } from './logistics-quote.mjs';

// A single invocation reads one JSON document and writes one JSON result.
const args = process.argv.slice(2);
let result;
let exitCode = 0;
try {
  if (args.length === 1 && args[0] === '--schema') {
    result = JSON.parse(readFileSync(new URL('./logistics-quote.tool.json', import.meta.url), 'utf8'));
  } else {
    if (args.length > 1 || (args[0]?.startsWith('-') && args[0] !== '-')) {
      throw Object.assign(new Error('用法：node workflows/logistics-quote.cli.mjs [input.json|-|--schema]'), { reason: 'invalid_arguments' });
    }
    let source;
    try {
      source = readFileSync(!args.length || args[0] === '-' ? 0 : args[0], 'utf8');
    } catch {
      throw Object.assign(new Error('无法读取输入 JSON'), { reason: 'input_read_failed' });
    }
    let input;
    try {
      input = JSON.parse(source.replace(/^\uFEFF/, ''));
    } catch {
      throw Object.assign(new Error('输入必须为一个有效的 JSON 对象'), { reason: 'invalid_json' });
    }
    result = calculateLogisticsQuote(input);
    exitCode = result.success ? 0 : 1;
  }
} catch (error) {
  result = { success: false, partial: false, reason: error.reason ?? 'invalid_arguments', message: error.message, quotes: [], errors: [] };
  exitCode = 2;
}
process.stdout.write(`${JSON.stringify(result)}\n`);
process.exitCode = exitCode;
