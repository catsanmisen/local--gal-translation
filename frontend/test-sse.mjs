/* SSE 解析器单元自测：node test-sse.mjs
 * 验证：逐字节 / 固定 7B / 随机切片下事件完整、UTF-8 中文不断码 */
import { readFileSync } from "node:fs";

const src = readFileSync(new URL("./js/sse.js", import.meta.url), "utf8");
const factory = new Function(`${src}; return { SseParser, chunkString };`);
const { SseParser, chunkString } = factory();

function run(file, mode) {
  const text = readFileSync(new URL(`../fixtures/${file}`, import.meta.url), "utf8");
  const events = [];
  const p = new SseParser((e, d) => events.push([e, d]));
  for (const c of chunkString(text, mode)) p.feed(c);
  p.end();
  return events;
}

for (const mode of ["byte", "fixed", "random"]) {
  const ev = run("normal.sse", mode);
  const names = ev.map(([e]) => e).join(",");
  const final = ev.find(([e]) => e === "final");
  const ok = names === "meta,delta,delta,final"
    && final && final[1].translation === "今天真是个好天气呢。"
    && ev[1][1].text === "今天";
  console.log(`normal.sse [${mode}]: ${ok ? "PASS" : "FAIL " + names}`);
  if (!ok) process.exitCode = 1;
}

const sup = run("superseded.sse", "fixed");
const okSup = sup.map(([e]) => e).join(",") === "meta,delta,cancelled"
  && sup[2][1].reason === "superseded";
console.log(`superseded.sse [fixed]: ${okSup ? "PASS" : "FAIL"}`);
if (!okSup) process.exitCode = 1;
