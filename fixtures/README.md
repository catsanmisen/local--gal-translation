# 前端 mock 素材

这些是静态示例，不会加载模型或启动服务。ready.json 和 paused.json 模拟状态；normal.sse 模拟成功流；superseded.sse 模拟旧台词被取消。前端应拆成任意大小网络块（包括中文 UTF-8 字符中间）喂给解析器，并在新 sequence 已显示后输入旧流，验证不会覆盖字幕。

示例 epoch=1、session_id=session-demo，不可当作真实会话提交。暂停/取消行为是新后端契约，旧部署脚本不提供此套 API。
