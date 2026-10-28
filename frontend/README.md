# GalTranslClient 前端（首版设计稿 · Mock）

对应《docs/前端需求.md》的初版界面设计，当前连接契约为《docs/接口契约-v0.3.md》。
**当前为纯 Mock 模式**：不加载模型、不启动服务，数据来自 `../fixtures/` 与内置 mock 引擎。界面顶部以 `MOCK` 徽章明确标识。
真实后端 v0.3 已实现：实际客户端由后端托管于 `http://127.0.0.1:18039/app/`（复用本目录的 HTML/CSS 骨架，交互层为 `backend/bridge/` 的独立副本）。当前契约为 `docs/接口契约-v0.3.md`，v0.2 手动接口保持兼容。**本目录 Mock 的修复不会自动进入实际连接层**，两处行为需分别验收。

## 运行

使用项目的白名单开发服务器（页面会 fetch `../fixtures/`）：

```powershell
cd E:\GalTranslClient\frontend
npm run dev              # 零依赖静态服务器，默认 127.0.0.1:8080
npm run dev -- --port 8899
# 打开 http://localhost:8080/frontend/
```

开发服务器只提供 frontend 静态资产与指定 fixtures。直接双击 `index.html`（file://）同样能运行，fixtures 自动退回 `js/mock-api.js` 内的逐字节内嵌副本。

## 测试

```powershell
cd E:\GalTranslClient\frontend
npm test    # SSE 4 项 + Mock 22 项 + 主动 Backlog 5 项
```

`test-sse.mjs` 验证逐字节 / 固定 / 随机切片下的解析与 UTF-8 完整性；`test-mock.cjs` 回归历史记录中复现的缺陷：启动中停止、连续台词取代、翻译中停止、术语失败语义、无会话保存。

## 依赖

- 运行时零构建、零 npm 依赖；Phosphor 图标已随包提供于 `vendor/phosphor/`（regular 字重，woff2 + woff），离线可用。
- 设计令牌与组件样式为原生 CSS（`css/tokens.css`、`css/app.css`），无框架锁定。

## 文件结构

```
frontend/
  index.html        主窗口：翻译 / 字幕 / 术语表 / 历史 / 配置 五页
  subtitle.html     悬浮字幕独立窗 mock（样式预览，实时接收字幕状态流）
  css/tokens.css    设计令牌：色彩 / 字体 / 圆角 / 动效，深浅双主题，字幕成对令牌
  css/app.css       组件样式
  js/sse.js         SSE 增量解析器（跨块 UTF-8 安全）+ 任意切片工具
  js/mock-api.js    mock 客户端后端：状态机、会话、术语、翻译流、场景注入
  js/app.js         主窗口逻辑：请求身份门禁、终态分流、字幕状态流、按游戏配置
  vendor/phosphor/  离线图标资源
  server.mjs        零依赖静态服务器（npm run dev）
  test-sse.mjs      SSE 解析器测试
  test-mock.cjs     Mock 行为回归测试
  DESIGN.md         设计说明（taste-skill 设计解读与自查）
  README.md         本文件
```

## Mock 场景（页面底部调试条）

| 场景 | 验证点 |
|---|---|
| 正常流式 | meta / delta / final 顺序，final 整体替换增量 |
| 旧请求被取消 | 以 fixtures 原始身份（req-old · seq 1 · epoch 1）注入 `superseded.sse`，新字幕不被覆盖，界面提示已忽略过期事件 |
| 流中断 | 只收 delta 无终态，标“已中断”，可手动重试，不自动重复提交 |
| 生成截断 | `GENERATION_TRUNCATED` 以错误收尾，片段不标完成 |
| 低显存暂停 | 状态进入 paused，显示原因与阈值，禁止绕过 |
| 引擎未就绪 | 未 ready 提交收到 `ENGINE_NOT_READY`，原文保留可重试 |
| 术语保存失败 | “术语保存失败”按钮（模拟存储错误，如实报 INTERNAL_ERROR）；字段校验 `INVALID_GLOSSARY` 定位真实行并高亮 |

SSE 流统一按随机 1-23 字节切片投喂解析器（含中文多字节中间切开），对应 fixtures/README 的健壮性要求。

## v0.1.1 修复记录（对应 已归档的历史记录）

| 报告项 | 修复 |
|---|---|
| 连续台词 null.handle 异常 | 每请求独立记录，所有回调先取“当前性”再落终态；handle 保存前复核记录仍有效 |
| 小窗口字幕设置被裁切 | Grid/Flex 容器补 `min-height:0`，页面独立滚动；900px 以下保留显存与当前游戏的紧凑呈现 |
| 失败片段无标记进入字幕 | 字幕改为状态流推送（携带身份与终态），截断 / 取消 / 断流在字幕窗与预览显式标注“未完成”，原文保留 |
| 浅色主题字幕对比度失效 | 字幕前景 / 底衬成对令牌，深浅主题各自定义；底衬透明度与文字透明度分离；独立字幕窗跟随主窗主题 |
| 启动中停止仍变就绪 | 生命周期计时器代次守卫；翻译收尾只在 translating 时归还 ready |
| 游戏配置不生效 | 输入源与字幕样式按 profile 保存、切换即恢复，会话 profile_id 同步更新 |
| 功能说明超过实现 | 置顶 / 穿透 / 全局热键 / 退出回收如实标注为桌面壳能力；字幕窗内 Ctrl+Shift+H 已可用 |
| 术语失败指向“第 0 行” | 存储失败与字段校验分离；空词条定位真实行；无会话也可保存术语 |
| 原文换行被折叠 | 原文 / 译文 / 历史 / 字幕统一 `white-space: pre-wrap` |

另补齐：图标离线随包（vendor/phosphor）、术语与历史 localStorage 持久化（mock 过渡）、有效台词自动进入字幕、滑杆 / 开关 / 表格输入补齐 aria 标签、流式状态与引擎状态接入 live region、协议细节移入悬停提示。

## v0.1.2 修复记录（对应 已归档的历史记录）

| 报告项 | 修复 |
|---|---|
| 字幕预览拖动跳位 | 按下时记录舞台 / 字幕矩形与指针起点，移动时只按“起点 + 指针位移”一次性计算并按舞台边界夹取；补 pointercancel 收尾 |
| “清空上下文（读档）”误删历史 | 该按钮只重置会话上下文（契约：重置保留历史）；永久删除拆分为独立的“删除历史”按钮，带确认提示且仅影响当前游戏 |
| Mock 术语 / 历史跨游戏共用 | MockBackend 数据按 profile_id 分桶（术语、术语版本、历史各自独立），历史条目携带 profile_id；切换游戏后术语表与历史重新渲染；旧版单桶 localStorage 数据自动迁移到默认配置 |
| 取消 / 错误回调缺身份校验 | mock 的取消与断流事件补齐四个身份字段；app.js 所有终态回调统一 matchIdentity 校验并加防重入 guard |
| `--text-3` 对比度不足 | 深色 `#6f6f78→#92929e`、浅色 `#8a8a93→#656570`，对 bg/surface/surface-2 实测 ≥ 5.0:1（与 bridge connection.css 取值对齐） |
| dev server 暴露整个仓库 | server.mjs 改为白名单（仅 frontend/ 与 fixtures/），路径边界用 path.relative 判断，杜绝相邻目录前缀与穿越 |
| README 连接说明过期 | 更新真实后端 v0.2 的连接方式与 bridge 副本说明（本节） |

## 验收映射（docs/前端需求.md §前端交付与验收）

| 验收项 | 覆盖方式 |
|---|---|
| 中文 / 日文多行与名字 | 多行输入 + 说话人字段，ja 字体栈渲染 |
| 流式正常完成 | “正常流式”场景 |
| 模型加载失败 | “引擎未就绪”场景 + 错误横幅 |
| 低显存暂停 | “低显存暂停”场景 + 显存横幅 |
| 取消 | 翻译中“取消”按钮，终态“已取消”并留原文 |
| 切换会话 | 游戏配置切换 / 重置会话，epoch 递增 |
| 快速翻页后旧请求晚到 | “旧请求被取消”场景，事件身份门禁丢弃 |
| 流中断 | “流中断”场景 |
| 术语更新失败 | “术语保存失败”按钮 |
| DPI / 窗口缩放 | 响应式断点 900px，流式布局 |
| 退出回收 | 停止按钮幂等；配置页说明只管理本客户端进程 |

模拟错误后界面不冻结（全部异步 + 骨架屏）、不丢原文（原文独立于译文渲染并入历史）、不显示错误台词（截断 / 取消 / 中断均不标完成）。

## 真实后端连接（v0.3）

真实后端已落地（`backend/`，`docs/接口契约-v0.3.md`；手动接口细节参见 v0.2 归档）：

1. 打开 `http://127.0.0.1:18039/app/` 即为实际客户端：后端复用本目录的 `index.html` / `css/` / `js/sse.js` 骨架，但交互层替换为 `backend/bridge/api.js`（fetch + token + SSE 断流恢复）与 `backend/bridge/client.js`，字幕页使用 `backend/bridge/subtitle.html`。
2. 连接凭据：页面从同源 `/bootstrap` 取得仅驻内存的随机 token，请求头统一 `Authorization: Bearer <token>`；界面不出现 token、内部端口等实现细节。
3. **维护注意**：`bridge/` 与本目录是两份独立副本。本目录的事件身份门禁、终态分流、原文保留逻辑在 bridge 中有对应实现；修改任一一侧的行为语义时，需核对另一侧并分别验收。
4. Mock 侧的替换点（若未来重新对齐传输层）：`js/mock-api.js` 整体替换为 fetch 客户端（`GET /status` 轮询、`POST /translate` 复用 `js/sse.js` 读取 POST SSE 等）。

## 桌面与浏览器的边界

- WPF 候选已实现 WGC/OCR、Textractor 管理、托盘、全局快捷键、原生穿透字幕和游戏内 Backlog / 位置按钮。OCR 在 Python 后端执行；HOOK 与跨屏/Magpie 的实机覆盖仍未完成。
- Backlog 默认关闭，仅由按钮、导航或桌面快捷键主动打开。新译文不会打开、自动刷新或滚动历史；历史不回写实时字幕。`js/backlog.js` 统一访问门禁，关闭/切游戏后的迟到读取被丢弃。
- `/profiles`、`/settings`、分页 `/history` 在真实后端实现；Mock 侧以 localStorage 模拟。浏览器独立字幕页只提供样式预览；游戏旁摆放使用原生宿主。

本轮样式统一为深灰/中灰/灰白三种基础色，按钮使用圆矩形细边框，默认字幕底衬不透明度62%。已保存的显示偏好继续有效。游戏单键隐藏、固定内置对话框与稳定摆放在原生“位置”窗口配置；浏览器独立预览不模拟全局游戏输入。当前Aokana/SeaBed实验及后台验证见 [最新记录](../docs/2026-10-14-真实漏捕与GPU实验.md)。
