/* Mock 客户端后端（对应 docs/接口契约.md，根地址 18039 已由真实后端实现）
 * 数据来源：../fixtures/{ready.json, paused.json, normal.sse, superseded.sse}
 * 通过本地静态服务打开时直接 fetch fixtures；file:// 打开时退回内嵌副本。
 * 仅用于首版 mock 开发，不加载模型、不启动服务。
 *
 * v0.1.1 修复（见 docs/前端检查报告.md）：
 * - 生命周期计时器使用代次守卫：启动中停止后，过期启动回调不再把状态推为 ready
 * - 翻译收尾只在 translating 状态时归还 ready，不覆盖 stopping/stopped
 * - 术语“保存失败”场景模拟存储错误，不再虚构字段错误指向“第 0 行”
 * - 无会话时也可保存术语（glossary_version 独立维护）
 * - 术语与历史在 localStorage 持久化（mock 过渡方案，正式由后端持久化）
 *
 * v0.1.2 修复（见 docs/前端复查报告.md）：
 * - 术语、术语版本与历史按 profile_id 隔离存储，与真实后端边界一致；
 *   历史条目携带 profile_id，切换游戏后互不串扰
 * - 取消与断流事件补齐四个身份字段（request_id/session_id/epoch/sequence），
 *   与 meta/delta/final 一致，可供控制器层统一校验
 */

/* 内嵌副本与 ../fixtures 内容逐字节一致（fetch 失败时的回退） */
const EMBEDDED_FIXTURES = {
  "ready.json": `{"api_version":"0.1","state":"ready","message":"模型就绪（示例数据）","model":{"id":"galtransl4-ja-zh","quantization":"Q6_K","context_tokens":2048,"gpu_layers":7},"gpu":{"free_mib":2683,"reserve_mib":2048,"sampled_at":"2026-10-10T09:00:00Z"},"active_request_id":null,"capabilities":{"streaming":true,"cancel":true,"auto_recovery":false,"text_events":false},"last_error":null}`,
  "paused.json": `{"api_version":"0.1","state":"paused","message":"可用显存不足，翻译暂停（示例数据）","model":{"id":"galtransl4-ja-zh","quantization":"Q6_K","context_tokens":2048,"gpu_layers":7},"gpu":{"free_mib":1900,"reserve_mib":2048,"sampled_at":"2026-10-10T09:00:00Z"},"active_request_id":null,"capabilities":{"streaming":true,"cancel":true,"auto_recovery":false,"text_events":false},"last_error":{"code":"VRAM_LOW","message":"可用显存低于保留阈值","retryable":true}}`,
  "normal.sse": `event: meta
data: {"request_id":"req-0001","session_id":"session-demo","epoch":1,"sequence":1,"status":"running"}

event: delta
data: {"request_id":"req-0001","session_id":"session-demo","epoch":1,"sequence":1,"text":"今天"}

event: delta
data: {"request_id":"req-0001","session_id":"session-demo","epoch":1,"sequence":1,"text":"真是个好天气呢。"}

event: final
data: {"request_id":"req-0001","session_id":"session-demo","epoch":1,"sequence":1,"translation":"今天真是个好天气呢。","elapsed_ms":869,"warnings":[],"context_committed":true}
`,
  "superseded.sse": `event: meta
data: {"request_id":"req-old","session_id":"session-demo","epoch":1,"sequence":1,"status":"running"}

event: delta
data: {"request_id":"req-old","session_id":"session-demo","epoch":1,"sequence":1,"text":"这是旧台词"}

event: cancelled
data: {"request_id":"req-old","session_id":"session-demo","epoch":1,"sequence":1,"reason":"superseded"}
`,
};

const MAX_INPUT_CHARS = 2000; // 契约：首版上限 2000 字符
const HISTORY_CAP = 128;      // 契约：会话只保留最近 128 个请求终态
const STORE_KEY = "galtransl.mock.store";

/* 示例术语只预置给默认配置；其他游戏从空表开始，避免跨游戏串扰 */
const SEED_GLOSSARY = [
  { source: "葵", target: "葵", note: "人物名" },
  { source: "先輩", target: "前辈", note: "称呼" },
  { source: "桜乃学園", target: "樱乃学园", note: "地名" },
];

class MockBackend {
  constructor() {
    this.fixtures = { ...EMBEDDED_FIXTURES };
    this.state = "stopped";          // stopped/starting/loading/ready/translating/paused/error/stopping
    this.session = null;             // { session_id, epoch, glossary_version, profile_id }
    this.sequence = 0;
    this.currentProfile = "default"; // 当前游戏；术语 / 历史均按此隔离
    this._stores = {};               // profile_id -> { glossary, glossaryVersion, history }
    this.scenario = "normal";        // normal / interrupted / truncated / vram_low
    this.glossaryFailNext = false;
    this.chunkMode = "random";       // SSE 切片模式：random / fixed / byte
    this.speed = 1;                  // 计时倍率，测试可调到 0.01
    this._listeners = new Set();
    this._active = null;             // 当前请求 { request_id, cancel }
    this._gen = 0;                   // 生命周期代次：停止使过期启动回调失效
    this._loadStart = 0;
    this._restore();
  }

  /* ---- 按游戏隔离的数据区（契约：术语与历史按 profile 隔离） ---- */
  _store(profileId = this.currentProfile) {
    if (!this._stores[profileId]) {
      this._stores[profileId] = {
        glossary: profileId === "default" ? SEED_GLOSSARY.map((e) => ({ ...e })) : [],
        glossaryVersion: 1,
        history: [],
      };
    }
    return this._stores[profileId];
  }

  /* 兼容既有控制器访问方式，实际读写落在当前游戏的独立数据区 */
  get glossary() { return this._store().glossary; }
  set glossary(v) { this._store().glossary = v; }
  get history() { return this._store().history; }
  set history(v) { this._store().history = v; }
  get glossaryVersion() { return this._store().glossaryVersion; }
  set glossaryVersion(v) { this._store().glossaryVersion = v; }

  /* ---- mock 过渡持久化（正式由后端负责） ---- */
  _restore() {
    try {
      if (typeof localStorage === "undefined") return;
      const s = JSON.parse(localStorage.getItem(STORE_KEY) || "null");
      if (!s) return;
      if (s.profiles && typeof s.profiles === "object") {
        // v0.1.2 结构：按游戏分桶
        for (const [id, bucket] of Object.entries(s.profiles)) {
          this._stores[id] = {
            glossary: Array.isArray(bucket.glossary) ? bucket.glossary : [],
            glossaryVersion: Number.isInteger(bucket.glossaryVersion) ? bucket.glossaryVersion : 1,
            history: Array.isArray(bucket.history) ? bucket.history.slice(0, HISTORY_CAP) : [],
          };
        }
      } else if (Array.isArray(s.glossary) || Array.isArray(s.history)) {
        // 迁移 v0.1.1 单桶结构：归入默认配置，不丢用户数据
        const bucket = this._store("default");
        if (Array.isArray(s.glossary)) bucket.glossary = s.glossary;
        if (Array.isArray(s.history)) bucket.history = s.history.slice(0, HISTORY_CAP);
        if (Number.isInteger(s.glossaryVersion)) bucket.glossaryVersion = s.glossaryVersion;
      }
    } catch (_) { /* 存储损坏时忽略，用默认值 */ }
  }

  _persist() {
    try {
      if (typeof localStorage === "undefined") return;
      const profiles = {};
      for (const [id, bucket] of Object.entries(this._stores)) {
        profiles[id] = {
          glossary: bucket.glossary,
          glossaryVersion: bucket.glossaryVersion,
          history: bucket.history.slice(0, HISTORY_CAP),
        };
      }
      localStorage.setItem(STORE_KEY, JSON.stringify({ profiles }));
    } catch (_) { /* 存储不可用时静默降级为内存态 */ }
  }

  pushHistory(entry) {
    const profileId = entry.profile_id || this.currentProfile;
    const bucket = this._store(profileId);
    bucket.history.unshift({ ...entry, profile_id: profileId });
    if (bucket.history.length > HISTORY_CAP) bucket.history.length = HISTORY_CAP;
    this._persist();
  }

  /* 仅清空当前游戏的历史；上下文重置（resetSession）不调用此方法 */
  clearHistory() {
    this._store().history = [];
    this._persist();
  }

  /* ---- fixtures 加载（优先真实文件） ---- */
  async loadFixtures() {
    if (typeof fetch === "undefined") return;
    const names = Object.keys(EMBEDDED_FIXTURES);
    await Promise.all(names.map(async (name) => {
      try {
        const res = await fetch(`../fixtures/${name}`);
        if (res.ok) this.fixtures[name] = await res.text();
      } catch (_) { /* file:// 等情况：保留内嵌副本 */ }
    }));
  }

  /* ---- 状态订阅（对应 GET /status 轮询） ---- */
  onStatus(fn) { this._listeners.add(fn); return () => this._listeners.delete(fn); }

  getStatus() {
    const base = JSON.parse(this.fixtures[
      this.state === "paused" ? "paused.json" : "ready.json"
    ]);
    base.state = this.state;
    base.active_request_id = this._active ? this._active.request_id : null;
    if (this.state === "loading") {
      base.message = "模型加载中（mock 不生成假进度，只报告已持续时间）";
      base.loading_elapsed_ms = Date.now() - this._loadStart;
    }
    if (this.state === "stopped") base.message = "服务未启动";
    if (this.state === "starting") base.message = "启动请求已接受，正在拉起引擎";
    if (this.state === "stopping") base.message = "停止请求已接受，正在释放模型";
    if (this.state === "translating") base.message = "翻译中";
    if (this.state === "error") {
      base.last_error = { code: "INTERNAL_ERROR", message: "模拟的内部错误（mock 场景）", retryable: true };
      base.message = "服务错误";
    }
    return base;
  }

  _emit() { const s = this.getStatus(); this._listeners.forEach((fn) => fn(s)); }

  /* ---- 引擎生命周期（POST /engine/start|stop，202 接受后轮询） ---- */
  startEngine() {
    if (this.state !== "stopped" && this.state !== "error") return;
    const gen = ++this._gen;         // 本次启动的代次
    this.state = "starting"; this._emit();
    setTimeout(() => {
      if (this._gen !== gen || this.state !== "starting") return; // 已被停止取代
      this.state = "loading"; this._loadStart = Date.now(); this._emit();
      setTimeout(() => {
        if (this._gen !== gen || this.state !== "loading") return;
        this.state = this.scenario === "vram_low" ? "paused" : "ready";
        this._emit();
      }, 2200 * this.speed);
    }, 700 * this.speed);
  }

  stopEngine() {
    if (this.state === "stopped") return;
    this._gen += 1;                  // 使所有未完成的启动回调失效
    this.state = "stopping"; this._emit();
    if (this._active) this._active.cancel("engine_stopped");
    setTimeout(() => {
      this.state = "stopped";
      this.session = null;
      this.sequence = 0;
      this._emit();
    }, 800 * this.speed);
  }

  /* ---- 会话（POST /sessions、POST /sessions/{id}/reset） ---- */
  createSession(profileId = "default") {
    this.currentProfile = profileId;
    const bucket = this._store(profileId);
    this.session = {
      session_id: "session-" + Math.random().toString(36).slice(2, 8),
      epoch: 1,
      glossary_version: bucket.glossaryVersion,
      profile_id: profileId,
    };
    this.sequence = 0;
    return { ...this.session };
  }

  /* 契约：重置上下文保留历史；只取消活动请求、推进 epoch、清空推理上下文 */
  resetSession(reason = "scene_change") {
    if (!this.session) return null;
    if (this._active) this._active.cancel("session_reset");
    this.session.epoch += 1;         // 重置后使用新 epoch 提交
    this.sequence = 0;
    return { ...this.session, reason };
  }

  setProfile(profileId) {
    this.currentProfile = profileId;
    this._store(profileId);          // 确保该游戏有独立数据区
    if (this.session) this.session.profile_id = profileId;
  }

  /* ---- 术语表（PUT /sessions/{id}/glossary） ---- */
  saveGlossary(entries) {
    // 模拟“存储失败”场景：如实报存储错误，不虚构字段错误
    if (this.glossaryFailNext) {
      this.glossaryFailNext = false;
      throw {
        code: "INTERNAL_ERROR",
        message: "模拟存储写入失败（mock 场景），请重试",
        retryable: true,
        row: null,
      };
    }
    // 真实字段校验：定位到实际空行（1 起始）
    const bad = entries.findIndex((e) => !e.source.trim() || !e.target.trim());
    if (bad !== -1) {
      throw {
        code: "INVALID_GLOSSARY",
        message: `第 ${bad + 1} 行：日文词与中文译名不能为空`,
        retryable: false,
        row: bad,
      };
    }
    const bucket = this._store();
    bucket.glossary = entries.map((e) => ({ ...e }));
    bucket.glossaryVersion += 1;
    if (this.session) {
      // 契约：更新后返回新 glossary_version 与 epoch，取消旧请求并清空旧上下文
      if (this._active) this._active.cancel("session_reset");
      this.session.glossary_version = bucket.glossaryVersion;
      this.session.epoch += 1;
      this.sequence = 0;
    }
    this._persist();
    return this.session ? { ...this.session } : { glossary_version: bucket.glossaryVersion };
  }

  /* ---- 翻译（POST /translate → SSE 流） ----
   * handlers: { onMeta, onDelta, onFinal, onCancelled, onError, onRejected }
   * 严格按契约：只有 final 才算完成；断流且未收到终态视为中断。 */
  translate(req, handlers) {
    if (!this.session) { handlers.onRejected(this._err("ENGINE_NOT_READY", "会话未建立", true)); return null; }
    if (this.state !== "ready" && this.state !== "translating") {
      const code = this.state === "paused" ? "VRAM_LOW" : "ENGINE_NOT_READY";
      handlers.onRejected(this._err(code,
        this.state === "paused" ? "可用显存低于保留阈值，翻译已暂停" : "模型未就绪", true));
      return null;
    }
    if (req.epoch !== this.session.epoch) {
      handlers.onRejected(this._err("STALE_EPOCH", "epoch 已过期，请使用最新会话信息", false));
      return null;
    }
    if (!req.source_text || !req.source_text.trim()) {
      handlers.onRejected(this._err("INVALID_INPUT", "原文不能为空", false));
      return null;
    }
    if (req.source_text.length > MAX_INPUT_CHARS) {
      handlers.onRejected(this._err("INPUT_TOO_LONG",
        `原文 ${req.source_text.length} 字符，超过首版上限 ${MAX_INPUT_CHARS}，请拆分后重试`, false));
      return null;
    }

    // 新请求使此前未完成请求失效（单推理队列）
    if (this._active) this._active.cancel("superseded");

    const requestId = req.request_id;
    // 取消 / 中断等绕过解析器的事件也补齐四个身份字段（v0.1.2）
    const identity = () => ({
      request_id: requestId, session_id: req.session_id, epoch: req.epoch, sequence: req.sequence,
    });
    this.state = "translating"; this._emit();

    let cancelled = null;
    const timers = [];
    // 收尾只在仍处于 translating 时归还 ready，不覆盖 stopping/stopped
    const finish = () => {
      this._active = null;
      if (this.state === "translating") {
        this.state = "ready";
        this._emit();
      }
    };
    this._active = {
      request_id: requestId,
      cancel: (reason) => {
        cancelled = reason || "user_cancelled";
        timers.forEach(clearTimeout);
        handlers.onCancelled({ ...identity(), reason: cancelled });
        finish();
      },
    };

    // 按场景生成事件流；统一走 SseParser + 任意切片，验证解析健壮性
    const sseText = this._buildStream(req);
    const chunks = chunkString(sseText, this.chunkMode);
    let t = 60 * this.speed;
    const parser = new SseParser((event, data) => {
      // 事件身份字段改写为本次请求身份（fixtures 里是示例身份）
      const payload = { ...identity(), ...this._payloadOf(event, data, req) };
      if (event === "meta") handlers.onMeta(payload);
      else if (event === "delta") handlers.onDelta(payload);
      else if (event === "final") { handlers.onFinal(payload); finish(); }
      else if (event === "cancelled") { handlers.onCancelled(payload); finish(); }
      else if (event === "error") { handlers.onError(payload); finish(); }
    });

    chunks.forEach((c) => {
      timers.push(setTimeout(() => {
        if (cancelled) return;
        parser.feed(c);
      }, t));
      t += (40 + Math.random() * 120) * this.speed;
    });
    // 全部网络块送达后冲刷解析器：流末尾可能没有空行边界，
    // 最后一个事件必须在 end() 时才落地（对应真实连接关闭语义）
    timers.push(setTimeout(() => {
      if (cancelled) return;
      parser.end();
    }, t + 30 * this.speed));
    // 流中断场景：不发送终态事件，直接结束（前端应显示“中断”并可重试）
    if (this.scenario === "interrupted") {
      timers.push(setTimeout(() => {
        if (cancelled) return;
        handlers.onError({ ...identity(), interrupted: true,
          code: "STREAM_INTERRUPTED", message: "流断开且未收到终态事件", retryable: true });
        finish();
      }, t + 250 * this.speed));
    }
    return this._active;
  }

  _payloadOf(event, data, req) {
    if (event === "delta") return { text: data.text };
    if (event === "meta") return { status: "running" };
    if (event === "final") {
      return {
        translation: data.translation,
        elapsed_ms: 600 + Math.floor(Math.random() * 900),
        warnings: req.source_text.includes("彼女") || req.source_text.includes("彼")
          ? [{ code: "inferred_gender", message: "人称性别为规则推断，建议复核" }]
          : [],
        context_committed: true,
      };
    }
    if (event === "cancelled") return { reason: data.reason };
    if (event === "error") return { code: data.code, message: data.message, retryable: true };
    return {};
  }

  _buildStream(req) {
    // 用 fixtures 的流结构，正文替换为用户输入对应的 mock 译文
    const mockTranslation = "（mock 译文）" + req.source_text;
    if (this.scenario === "interrupted") {
      return [
        'event: meta\ndata: {"status":"running"}\n',
        'event: delta\ndata: {"text":"（mock 译文片段，流即将中断）"}\n',
      ].join("\n");
    }
    if (this.scenario === "truncated") {
      return [
        'event: meta\ndata: {"status":"running"}\n',
        'event: delta\ndata: {"text":"（mock 译文片段，生成被截断）"}\n',
        'event: error\ndata: {"code":"GENERATION_TRUNCATED","message":"输出达到长度上限，译文不完整"}\n',
      ].join("\n");
    }
    // normal：基于 normal.sse 的结构，替换 delta/final 文本
    const half = Math.ceil(mockTranslation.length / 2);
    return [
      'event: meta\ndata: {"status":"running"}\n',
      `event: delta\ndata: {"text":${JSON.stringify(mockTranslation.slice(0, half))}}\n`,
      `event: delta\ndata: {"text":${JSON.stringify(mockTranslation.slice(half))}}\n`,
      `event: final\ndata: {"translation":${JSON.stringify(mockTranslation)},"elapsed_ms":869,"warnings":[],"context_committed":true}\n`,
    ].join("\n");
  }

  /* 断流后确认（GET /requests/{id} 的 mock，按当前游戏历史查找） */
  getRequest(requestId) {
    const h = this.history.find((x) => x.request_id === requestId);
    return h || null;
  }

  _err(code, message, retryable) {
    return { code, message, retryable };
  }
}

/* 浏览器与 Node 测试都可用 */
if (typeof globalThis !== "undefined") globalThis.MockBackend = MockBackend;
