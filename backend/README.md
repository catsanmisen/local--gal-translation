# 私人客户端后端

2026-10-24当前离线候选：`dist/galtransl-offline-20261024-candidate.zip`，新宿主 `desktop/publish-offline-20261024/`。实际解压包已验证便携Python、OCR、CPU模型、迁移回退和重启；完整GUI/游戏验收仍待完成。见 [本轮验证与限制](../docs/2026-10-24-离线验证与交付候选.md)。下方旧构建与数量仅作历史记录。

2026-10-10：GalTransl 4B 与现有页面的真实翻译链路已接通。Python 标准库实现，不需要安装 Python Web 框架，也没有重新下载模型或推理运行时。

## 启动

在项目根目录双击 [启动私人翻译客户端.cmd](E:/GalTranslClient/启动私人翻译客户端.cmd)。页面打开后点击“启动翻译”，等待模型就绪。原始 `frontend/` 的独立静态服务仍是 Mock；实际客户端入口是 `http://127.0.0.1:18039/app/`。

也可以运行：

```powershell
cd E:\GalTranslClient
python -B backend/src/server.py
# 打开 http://127.0.0.1:18039/app/
```

完整退出用 [停止私人翻译客户端.cmd](E:/GalTranslClient/停止私人翻译客户端.cmd)，或在服务控制台按 Ctrl+C。关闭最后一个主页面会停止模型，API 保留；异常失联最长等待 90 秒。模型子进程已在恢复执行前绑定 Windows kill-on-close Job Object，后端进程退出会释放该子进程。

服务和控制脚本均支持 `GALTRANSL_CLIENT_PORT`，未设置时使用 18039；显式 `--port` 优先。端口需为 1–65535，客户端端口不能与内部模型端口相同。控制脚本同样可用 `--port` 指定目标；启动失败或端口被占用时，不会先改写数据库的崩溃恢复状态。

桌面设置与浏览器“配置”提供全局模型设备选择：自动沿用原策略，CPU明确使用处理器，GPU预算不足时保持选择并提示，不自动退回CPU。GPU显存预留默认2048MiB，可选1536或1024MiB；启动最低可用量为预留加512MiB，实际还需容纳权重与运行缓冲。CPU不依赖NVIDIA监测，也不因显存不足停止。实际CPU / GPU+CPU及GPU层数由v0.3 `/status`上报；CPU就绪后不自动升级GPU。

玩家已授权可临时停止高占用壁纸。自动壁纸释放默认开启，可以关闭；检测到Wallpaper Engine显存占用≥1024MiB，且GPU预算不足以完整加载模型时，在启动前执行官方stop、等待显存释放并重新计算层数。明确CPU也允许停止高占用动态壁纸，设备仍保持CPU；CPU推理不因壁纸监测失败受阻。停止翻译、游戏退出或客户端退出后play恢复，仅恢复本客户端持有的租约；壁纸应用主动退出/重启后不重新启动它。运行中换设备保持已有壁纸租约，避免反复stop/play。恢复失败有提示和有界重试，异常退出后下一次客户端启动读取共享恢复记录补偿。细节及412项回归见 [壁纸显存释放与先行版目标](../docs/2026-10-13-壁纸显存释放与先行版目标.md)。

GET `/settings`补齐旧数据默认值；PUT / PATCH只更新给定字段，主题保存不会覆盖设备选择。运行中切换先保存，再回收所属模型后应用新设置；保留已完成字幕，只有仍有效的最新未完成自动台词可以恢复。失败明确上报，不启动其他进程或改用CPU。新增接口字段和本轮381项回归、包内检查、真实性能记录见 [模型设备选择与显存预留](../docs/2026-10-13-模型设备选择与显存预留.md)。

## 输入与保存

- 手动：输入日文，点击翻译；新台词取代未完成旧台词，单推理并发。
- 剪贴板：手动兼容入口，只读取开启后的新 Unicode 文本，不回写，默认关闭。原生自动会话优先使用 WGC/OCR 或已保存的 Textractor 线程，具体配置见 `desktop/README.md`。
- 术语：按游戏保存；保存成功会递增术语版本和 epoch，并清空翻译上下文。
- 历史：原文先保存，最终结果后提交；失败、取消和断流保留原文。读档重置不删除历史。
- 字幕：浏览器提供预览；WPF 原生正文置顶、穿透、不抢焦点，独立小按钮区允许主动打开 Backlog 或位置设置。字幕布局保护整块原文，安全空间不足时收起正文，历史不自动显示。

主窗与独立预览共用 `bridge/presentation.js`，统一失败状态、字号、显示模式和底衬透明度；Ctrl+Shift+H 仅在独立字幕窗口内隐藏。剪贴板占用采用最多 2 秒间隔的退避重试，在输入状态行显示；同一错误关闭后不会因轮询重弹。

取消/断流后若约 8 秒仍不能确认计算槽空闲，会停止自己的模型，并在日志、状态和请求诊断中保留 CANCEL_TIMEOUT。请重新启动模型。当前继续使用关闭连接后确认槽位释放的路径，不将缓存擦除当作推理取消。

SQLite 数据位于 `data/client.sqlite3`；推理上下文仅在内存中。测试创建的“联调验证”配置含可复现样例，正常使用可选择“默认配置”。创建自己的配置可使用 PUT `/api/v1/profiles`，当前字段见 [v0.3 契约](E:/GalTranslClient/docs/接口契约-v0.3.md)，手动接口见 v0.2 归档。省略 prefs 或 game 均保留其原值，避免单独保存原生摆放时覆盖浏览器字号设置。

## 目录边界

`src/` 管理模型、OCR、队列、数据和 HTTP API；`bridge/` 包含浏览器连接控制器；`desktop/` 包含原生宿主。后端读取前端 HTML/CSS 与共享 SSE/Backlog 模块，在响应中替换交互脚本入口。前端修改权限已由玩家开放，本轮仍按组件职责组织代码。

连接视图的 Phosphor 2.1.1 图标 CSS 和字体已随 `backend/vendor/phosphor/` 提供，保留 MIT 许可；运行时不再请求原页面的 unpkg CDN，翻译与界面资源均可离线使用。

构建期间检测到前端并行更新，见 `work/frontend-before.json` 与 `work/frontend-preservation.json`。这些快照反映并行文件变化，不是本次后端写入前端文件的记录。

API 仅绑定 127.0.0.1，凭据只驻内存且不放入 URL、日志或设置。静态资源使用明确白名单，不提供数据库、权重、源代码目录或日志下载。内部模型凭据只通过子进程环境注入。日志有大小限制；模型日志超过 8MiB 会停止模型并报错，避免无限增长。

安全边界为本机单用户：bootstrap 可以被本机非浏览器进程读取，因此不防御本机恶意进程。控制脚本也依赖此入口；未来收紧入口需同步迁移三端。

实际连接视图以 `backend/bridge/` 的交互、字幕脚本为准；`frontend/` 的 Mock 控制器供原型开发。必需布局 ID 与脚本入口由 `src/ui_contract.py` 校验，避免前端并行修改后静默失配。详见 [前后端连接约定](E:/GalTranslClient/docs/前后端连接约定.md)。

## 验证

```powershell
python -B -m unittest discover -s backend/tests -v
node backend/tests/test_bridge.cjs
# 显式加载真实模型的联调，需先运行 API：
python -B backend/tests/real_smoke.py
# 独立端口的调试实例可指定：
python -B backend/tests/real_smoke.py --port 18059 --output work/backend-improvements-smoke.json
```

单元/API 测试采用模拟引擎，默认发现测试不会加载真实模型。真实联调结果写入 `work/backend-real-smoke.json`，涵盖短句、术语、控制符、断流取消、计算槽空闲、后续推理和内部鉴权。加 `--keep-model` 可保留模型用于浏览器测试；默认结束后停止模型。

原始 80 项回归保留；10月14日431项检查与候选见 [当前优化与接续](../docs/2026-10-14-真实漏捕与GPU实验.md)，上轮短 SeaBed UI 证据见 [字幕入口与演出布局记录](E:/GalTranslClient/docs/2026-10-11-字幕入口与演出布局.md)。早期手动/剪贴板与浏览器验收见 [原验收报告](E:/GalTranslClient/docs/前端提交与全流程验收报告.md)，其中预设短句约 0.53–1.02 秒不是游戏内端到端性能或准确率结论。

仅在用户明确允许覆盖系统剪贴板后，使用独立测试服务运行 `python -B backend/tests/windows_clipboard_smoke.py --port 18059 --allow-system-clipboard-write`。脚本验证启用跳过旧内容、自动翻译、序列去重、超长拒绝与停用；结束恢复原有 Unicode 纯文本，不能保证恢复其他格式。生产监听不会写剪贴板。`lifecycle_smoke.py` 供上述验收顺序中的 snapshot、restart、closed-window、shutdown 检查使用；snapshot 依赖报告中的测试配置，不应指向正式实例。

实现依据：现有本地部署与提示词，[llama.cpp b11429 服务接口](https://github.com/ggml-org/llama.cpp/blob/b11429/tools/server/README.md)、[Windows Job Objects](https://learn.microsoft.com/en-us/windows/win32/procthread/job-objects)、[模型发布说明](https://huggingface.co/SakuraLLM/GalTransl-v4-4B-2601)。

## 后台身份与数据备份

当前桌面协议为2。`/bootstrap`含backend_root、database_path及每次启动重新生成的instance_id；桌面核对项目根和数据库路径后才连接。同协议的其他安装或数据库不会被接管。桌面创建的后台连续至少三次连接失败且持续60秒，才允许回收其所属进程树；10分钟最多两次，不回收共享服务。后台恢复后先获取当前状态、恢复游戏绑定，旧场景快照不进入字幕。

每个数据库只允许一个Storage拥有者，使用同目录`.lock`文件上的操作系统锁；文件存在本身不代表仍被占用，不应手动删除锁文件来绕过保护。备份使用SQLite只读连接和backup接口，包含已提交WAL数据，不覆写已有备份。恢复要求正常退出客户端，拒绝活动日志或仍被打开的目标数据库，先校验副本再原子替换。

```powershell
# 在项目根执行；输出路径应使用新的文件名。
.\backend\runtime\python\python.exe -B backend/src/data_tools.py backup data/client.sqlite3 work/client-before-upgrade.sqlite3
# 正常关闭客户端后，才可将已验证备份恢复到目标数据库。
.\backend\runtime\python\python.exe -B backend/src/data_tools.py restore work/client-before-upgrade.sqlite3 data/client.sqlite3
```

离线包同样带有便携Python和data_tools.py，可先从旧目录备份，再恢复到新解压目录的data/client.sqlite3。回退前保留升级前备份，不在运行中的数据库上复制或覆盖文件。本轮升级/回退仅使用隔离样本，未改玩家正式数据库。
