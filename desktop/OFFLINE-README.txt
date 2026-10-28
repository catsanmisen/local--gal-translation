GalTransl v1.0 正文离线版（Windows x64，桌面协议2）

首次使用
1. 将ZIP完整解压到一个新目录，运行 GalTransl.Desktop.exe。
2. 启动日文游戏，在“游戏设置”选择该游戏，框选日文正文取词区域并保存。
   SeaBed建议覆盖中央正文区域；Aokana EXTRA2建议覆盖下方对话正文。
3. 回到游戏，等待正文稳定，字幕会自动显示。以后启动会恢复保存的配置。
本包内置Python、OCR、GalTransl 4B Q6_K和推理运行时，无需另装开发工具，运行无需联网。
包内不含游戏、游戏存档或任何玩家配置；路径移动后使用解压目录中的程序。

字幕与设置
正文窗口支持点击穿透；字幕旁“Backlog”仅主动打开历史，“全文”查看当前句，
“位置”调整摆放。关闭设置窗口后客户端留在托盘；托盘菜单可以暂停、隐藏字幕、
打开设置和退出。单键隐藏设置不会吞掉传给游戏的输入。
设备可选自动、CPU或GPU；GPU显存不足会提示等待，不会暗中改为CPU。
显存预留默认2048 MiB，可选1536/1024 MiB；降低预留会减少留给游戏的显存。
设置界面显示实际使用的CPU/GPU层数；更改设备保存后会安全重载。
高占用Wallpaper Engine可由客户端临时stop/play，停止翻译或退出后尝试恢复；
部分壁纸停止后仍占显存，可在设置中关闭自动壁纸释放，再自行管理占用。

v1.0支持范围
本版以SeaBed、Aokana EXTRA2的常规日文正文OCR与离线翻译为重点。
标题、厂商标识及特殊文字演出不作为本版验收目标，可能被误识或翻译。
建议进入正文后再启用采集，并将取词区域限制在正文范围。
生僻字、省略号与部分闭引号仍可能误识，原文可对照；本版不猜字补标点。
长页完整翻译需要更久，具体速度受CPU、GPU、显存及壁纸占用影响。
本版没有宣称达到旧计划的统一延迟目标、50句统计或CPU/GPU各30分钟长测门槛。
HOOK、跨屏/缩放兼容与特殊演出未作本版完整验收。

升级、备份与回退
默认数据位于本目录 data/client.sqlite3。不要覆盖正在运行的旧包或玩家数据库。
升级前，在旧包目录将数据库备份到一个新的文件名：
backend\runtime\python\python.exe -B backend/src/data_tools.py backup data/client.sqlite3 ../client-before-upgrade.sqlite3
正常退出旧客户端后，在新包目录恢复：
backend\runtime\python\python.exe -B backend/src/data_tools.py restore ../client-before-upgrade.sqlite3 data/client.sqlite3
恢复工具会拒绝覆盖活动数据库；回退时使用旧程序与升级前备份。
请通过托盘“退出客户端”正常退出，以便回收所属后台、模型及恢复壁纸。
异常退出后下次启动会尝试补偿恢复。

完整性与许可
ZIP的SHA256见随附 .zip.sha256；包内 package-manifest.json 列出文件大小和SHA256。
许可、组件版本及上游源码材料见 licenses/ 与 backend/vendor/。
本包用于用户本地离线使用，未对外发布或上传。
