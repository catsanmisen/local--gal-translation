# Local GAL Translation

Windows 本地日文游戏字幕客户端。使用 OCR 读取正文，通过 GalTransl 4B Q6_K 离线翻译，再以穿透式字幕显示中文。

## 下载 v1.0

前往 [v1.0 Release](https://github.com/catsanmisen/local--gal-translation/releases/tag/v1.0.0)，下载三个 `galtransl-v1.0-offline.zip.001`～`.003` 分卷、`Join-OfflinePackage.ps1` 和 `SHA256SUMS.txt`，放到同一个新目录。

在 PowerShell 中运行：

```powershell
powershell -NoProfile -File .\Join-OfflinePackage.ps1
```

脚本校验每个分卷、合并 ZIP 并验证原包 SHA256。完整解压合并后的 ZIP，运行 `GalTransl.Desktop.exe`。无需另装 Python、.NET 或下载模型。首次运行时选择已启动的游戏，框选日文正文并保存。

原始 ZIP：4,591,605,751 字节；SHA256：`3425a89b11af95da8d3d903d93af39d84997a197b51ca27a41f5cfb00eea530d`。

## 范围与操作

v1.0 以 SeaBed 与 Aokana EXTRA2 的常规日文正文为目标。标题、厂商标识及特殊文字演出未纳入本版验收。OCR 仍可能误识生僻字、近形字及部分标点；长页延迟尚未达到原规划的统一性能目标。已有短测不代表全流程零漏捕或全部演出通过。

字幕正文穿透点击；`Backlog` 主动查看历史，`位置` 调整摆放，`全文` 查看当前句。设置窗口关闭后进入托盘，从托盘退出可回收所属后台与模型。设备选择及显存预留见 [离线使用说明](desktop/OFFLINE-README.txt)。

包内不包含游戏、存档、玩家数据库或测试日志。升级前备份原数据库，完整退出旧版，再向新解压目录恢复；不要覆盖运行中的旧安装。

## 源码与构建

- `desktop/GalTransl.Desktop`：.NET 10 WPF 桌面宿主、采集及字幕。
- `backend/src`：Python 后端、OCR、单队列推理、配置及历史。
- `frontend`、`backend/bridge`：本地页面与真实服务连接。
- `backend/vendor`：OCR/HOOK 资产、对应来源及许可。
- `docs`：接口、规划和历史验证记录；文档中的原工作区路径和 `work/` 证据索引保留历史语境，原始本机工作目录未上传。

开发需 Windows、.NET 10 SDK、Python 3.12，以及 JavaScript 检查所需 Node.js。为复用已验证资产，从完整解压的离线包复制 `backend/runtime` 和 `backend/galtransl4/models` 至源码相同路径；这些大文件不进入 Git 历史。可用的完整运行环境以 Release 为准。

```powershell
dotnet publish desktop/GalTransl.Desktop/GalTransl.Desktop.csproj -c Release -o desktop/publish-v1.0
backend/runtime/python/python.exe -B desktop/tools/build_offline.py --publish desktop/publish-v1.0 --dest dist/galtransl-v1.0-offline --release-version 1.0.0 --zip
```

常规检查入口：

```powershell
backend/runtime/python/python.exe -B -m unittest discover -s backend/tests -v
node backend/tests/test_bridge.cjs
dotnet run --project desktop/tests -c Release
cd frontend
npm test
```

真实模型、服务及窗口检查需要对应运行环境；历史 `work/` 采样和游戏图像没有随源码公开。v1.0 的本地验证记录见 [交付报告](docs/2026-10-28-v1.0-离线交付.md)：包审计 39 项、实际离线烟测 23 项、原生及服务 208 项通过，并完成 SeaBed save01 正文及可见字幕短测。

## 第三方材料

模型来自 [SakuraLLM/GalTransl-v4-4B-2601](https://huggingface.co/SakuraLLM/GalTransl-v4-4B-2601)，采用 **CC-BY-NC-SA-4.0**，使用与再分发须遵守其非商业等条款。Textractor v5.2.0 为 GPL-3.0，相关源码和 MinHook 材料已附于 `backend/vendor/textractor`。RapidOCR、PaddleOCR、Phosphor、llama.cpp、CUDA 及其他运行时的许可分别保留在资产及离线包 `licenses` 中；请按各组件条款使用，不将整包视为单一许可。
