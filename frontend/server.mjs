/* 零依赖静态服务器：仅提供 frontend/ 与 fixtures/ 白名单内的静态资产。
 * 用法：npm run dev [-- --port 7100 --host 127.0.0.1]
 * 或：node server.mjs --port 8080
 *
 * v0.1.2 修复（见 docs/前端复查报告.md）：
 * - 不再提供整个项目根目录（仓库现已包含真实数据库、日志与模型权重）；
 *   只开放 frontend/ 与 fixtures/ 两个目录
 * - 路径边界用 path.relative 判断，避免 startsWith 的相邻目录前缀问题
 */
import { createServer } from "node:http";
import { readFile } from "node:fs/promises";
import { extname, isAbsolute, join, normalize, relative, sep } from "node:path";
import { fileURLToPath } from "node:url";

const frontendDir = fileURLToPath(new URL(".", import.meta.url));
const rootDir = normalize(join(frontendDir, "..")); // 仓库根，仅用于定位 fixtures
const ALLOW_ROOTS = [normalize(frontendDir), normalize(join(rootDir, "fixtures"))];

function arg(name, fallback) {
  const i = process.argv.indexOf("--" + name);
  return i !== -1 && process.argv[i + 1] ? process.argv[i + 1] : fallback;
}
const port = Number(arg("port", 8080));
const host = arg("host", "127.0.0.1");

const MIME = {
  ".html": "text/html; charset=utf-8",
  ".css": "text/css; charset=utf-8",
  ".js": "text/javascript; charset=utf-8",
  ".mjs": "text/javascript; charset=utf-8",
  ".json": "application/json; charset=utf-8",
  ".sse": "text/event-stream; charset=utf-8",
  ".md": "text/markdown; charset=utf-8",
  ".png": "image/png",
  ".svg": "image/svg+xml",
  ".woff": "font/woff",
  ".woff2": "font/woff2",
};

/* 白名单判定：目标必须位于某个允许目录之内（relative 不以 ".." 开头） */
function isAllowed(file) {
  return ALLOW_ROOTS.some((root) => {
    const rel = relative(root, file);
    return rel !== "" && !rel.startsWith(".." + sep) && rel !== ".." && !isAbsolute(rel);
  });
}

createServer(async (req, res) => {
  try {
    let path = decodeURIComponent(new URL(req.url, "http://x").pathname);
    if (path === "/") {
      res.writeHead(302, { Location: "/frontend/" });
      return res.end();
    }
    if (path.endsWith("/")) path += "index.html";
    const file = normalize(join(rootDir, path));
    if (!isAllowed(file)) { res.writeHead(403); return res.end("forbidden"); }
    const data = await readFile(file);
    res.writeHead(200, { "Content-Type": MIME[extname(file)] || "application/octet-stream" });
    res.end(data);
  } catch {
    res.writeHead(404);
    res.end("not found");
  }
}).listen(port, host, () => {
  console.log(`GalTranslClient mock: http://${host}:${port}/frontend/`);
});
