/* GalTranslClient 主窗口逻辑 v0.1.2（Mock 模式）
 * 行为约束来自 docs/前端需求.md 与 docs/接口契约.md：
 * - 先登记 request_id，仅接受当前会话 / 当前台词 / 当前 epoch 的流事件
 * - 只有 final 标为完成；截断、取消、中断不冒充完整译文
 * - 原文全链路保留，任何终态都不丢弃原文
 * - 状态轮询 1s，不阻塞界面；不生成假进度
 *
 * v0.1.1 修复（见 docs/前端检查报告.md）：
 * - 每个请求持有独立记录，所有回调校验身份；旧请求终态只写自身历史，不动新字幕
 * - handle 保存前核对当前记录仍是此次提交，消除连续台词的 null.handle 异常
 * - 字幕按状态流实时推送（携带身份与终态），失败片段显式标注，不再伪装成译文
 * - 游戏配置真正切换输入源与字幕偏好，并按 profile 分别保存
 * - 页面卸载时模拟停止本客户端后台（真实回收由桌面壳与后端实现）
 *
 * v0.1.2 修复（见 docs/前端复查报告.md）：
 * - 字幕预览拖动改为按下时记录舞台 / 字幕矩形与指针起点，移动时按增量一次性计算并夹取
 * - “清空上下文（读档）”只重置会话上下文，不再删除历史；删除历史为独立显式操作
 * - 术语与历史随 MockBackend 按 profile_id 隔离，切换游戏时重新渲染
 * - 取消 / 错误回调与 meta/delta/final 一样校验四个身份字段，且所有终态回调防重入；
 *   onRejected 发生在请求被接受前、无流事件身份，按提交时的记录核对
 */
(function () {
  "use strict";

  const $ = (sel) => document.querySelector(sel);
  const $$ = (sel) => Array.from(document.querySelectorAll(sel));

  const backend = new MockBackend();
  // Device control belongs to the connected service, never to the demo model.
  document.querySelectorAll('#model-mode button, #model-reserve, #wallpaper-relief, #btn-model-save').forEach(control=>control.disabled=true);
  $('#wallpaper-runtime').textContent='Mock 预览不操作壁纸；本机客户端可自动临时停止高占用壁纸，并在翻译结束后恢复。';
  $('#model-runtime').textContent='Mock 预览 · 未连接真实运行设备';
  $('#model-policy-hint').textContent='从本机客户端或桌面托盘打开设置，可选择 CPU / GPU 并调整显存预留。';
  const backlogAccess = new BacklogAccess();

  /* ---------------- 按游戏的配置状态 ---------------- */
  const PROFILE_DEFS = {
    default: { name: "默认配置", sourceKind: "manual",
      subtitle: { font: 22, opacity: 62, mode: "both", clickthrough: false } },
    sakura: { name: "樱乃学园物语（示例）", sourceKind: "clipboard",
      subtitle: { font: 22, opacity: 62, mode: "both", clickthrough: false } },
    yoru: { name: "夜巡（示例）", sourceKind: "manual",
      subtitle: { font: 26, opacity: 62, mode: "both", clickthrough: false } },
  };
  const PROFILE_KEY = "galtransl.profiles";
  const ACTIVE_PROFILE_KEY = "galtransl.activeProfile";
  const SUB_PREFS_KEY = "galtransl.subtitlePrefs"; // 当前生效的字幕偏好，字幕窗读取
  const SUB_KEY = "galtransl.subtitle";            // 当前字幕内容与状态流

  function loadProfiles() {
    let saved = {};
    try { saved = JSON.parse(localStorage.getItem(PROFILE_KEY) || "{}"); } catch (_) { /* 损坏则用默认 */ }
    const out = {};
    for (const id of Object.keys(PROFILE_DEFS)) {
      out[id] = {
        ...PROFILE_DEFS[id],
        ...(saved[id] || {}),
        subtitle: { ...PROFILE_DEFS[id].subtitle, ...((saved[id] || {}).subtitle || {}) },
      };
    }
    return out;
  }

  const profiles = loadProfiles();
  let activeProfile = localStorage.getItem(ACTIVE_PROFILE_KEY) || "default";
  if (!profiles[activeProfile]) activeProfile = "default";

  const ui = {
    session: null,          // { session_id, epoch, glossary_version, profile_id }
    status: null,
    activeReq: null,        // 当前请求记录（详见 submitTranslate）
    lastInput: null,        // 供重试（不自动重复提交）
    sourceKind: profiles[activeProfile].sourceKind,
    clipboardOn: false,
    clipboardIdx: 0,
    historyPage: 1,
    HISTORY_PAGE_SIZE: 5,
  };

  const CLIPBOARD_SAMPLES = [
    { text: "「葵、待って！」", speaker: "桜乃" },
    { text: "彼女は振り返って、\n少し驚いた顔をした。", speaker: null },
    { text: "それでも、俺は前に進むしかなかった。", speaker: null },
  ];

  const STATE_TEXT = {
    stopped: "未启动", starting: "启动中", loading: "加载中",
    ready: "就绪", translating: "翻译中", paused: "已暂停（显存不足）",
    recovering: "恢复中", error: "错误", stopping: "停止中",
  };

  const STATE_TONE = {
    stopped: "", starting: "busy", loading: "busy", ready: "ok",
    translating: "busy", paused: "busy", recovering: "busy",
    error: "err", stopping: "busy",
  };

  /* ---------------- 主题 ---------------- */
  function initTheme() {
    const saved = localStorage.getItem("galtransl.theme");
    if (saved) document.documentElement.dataset.theme = saved;
    syncThemeIcon();
  }
  function syncThemeIcon() {
    const dark = document.documentElement.dataset.theme !== "light";
    $("#theme-toggle").innerHTML = dark ? '<i class="ph ph-moon"></i>' : '<i class="ph ph-sun"></i>';
    $("#theme-toggle").setAttribute("aria-label", dark ? "切换到浅色主题" : "切换到深色主题");
  }
  $("#theme-toggle").addEventListener("click", () => {
    const dark = document.documentElement.dataset.theme !== "light";
    document.documentElement.dataset.theme = dark ? "light" : "dark";
    localStorage.setItem("galtransl.theme", dark ? "light" : "dark");
    syncThemeIcon();
  });

  /* ---------------- 导航 ---------------- */
  $$(".rail-item").forEach((btn) => {
    btn.addEventListener("click", () => {
      $$(".rail-item").forEach((b) => {
        b.classList.remove("active");
        b.removeAttribute("aria-current");
      });
      btn.classList.add("active");
      btn.setAttribute("aria-current", "page");
      $$(".page").forEach((p) => p.classList.remove("active"));
      $("#page-" + btn.dataset.page).classList.add("active");
      if(btn.dataset.page === "history") {backlogAccess.open(activeProfile);ui.historyPage=1;renderHistory();}
      else backlogAccess.close();
    });
  });
  $("#btn-backlog").addEventListener("click",()=>$('.rail-item[data-page="history"]').click());
  $("#btn-backlog-close").addEventListener("click",()=>$('.rail-item[data-page="translate"]').click());
  $("#btn-history-refresh").addEventListener("click",renderHistory);

  /* ---------------- 状态轮询（1s，不阻塞界面） ---------------- */
  function renderStatus(s) {
    ui.status = s;
    const pill = $("#state-pill");
    pill.dataset.tone = STATE_TONE[s.state] || "";
    let text = STATE_TEXT[s.state] || s.state;
    if (s.state === "loading" && s.loading_elapsed_ms != null) {
      text = `加载中 · ${Math.round(s.loading_elapsed_ms / 1000)}s`; // 只显示持续时间，不编进度
    }
    $("#state-text").textContent = text;

    if (s.gpu) {
      const warn = s.gpu.free_mib < s.gpu.reserve_mib;
      $("#vram-value").textContent = `${s.gpu.free_mib} / ${s.gpu.reserve_mib} MiB`;
      $("#metric-vram").classList.toggle("warn", warn);
    } else {
      $("#vram-value").textContent = "采样不可用";
    }

    syncSessionUi();

    const running = !["stopped", "error"].includes(s.state);
    $("#btn-start").disabled = running;
    $("#btn-stop").disabled = !running;
    $("#btn-translate").disabled = !(s.state === "ready") || !!ui.activeReq || inputOverLimit();

    const paused = s.state === "paused";
    $("#banner-vram").hidden = !paused;
    if (paused && s.gpu) {
      $("#banner-vram-desc").textContent =
        `当前可用 ${s.gpu.free_mib} MiB，低于后端保留阈值 ${s.gpu.reserve_mib} MiB。` +
        "显存恢复前不会调度新请求，前端不会绕过保留阈值。";
    }
    if (s.last_error && s.state !== "paused") showError(s.last_error.code, s.last_error.message);
  }

  backend.onStatus(renderStatus);
  setInterval(() => { /* GET /status 轮询 */ renderStatus(backend.getStatus()); }, 1000);

  /* ---------------- 引擎控制 ---------------- */
  $("#btn-start").addEventListener("click", () => {
    backend.startEngine();
    renderStatus(backend.getStatus());
  });

  $("#btn-stop").addEventListener("click", () => {
    backend.stopEngine();       // 幂等；只管理本客户端启动的进程
    pushSubtitleIdle();
    renderStatus(backend.getStatus());
  });

  /* 页面卸载时模拟“退出时请求停止自己管理的后台”；
     真实的进程回收由桌面壳与后端实现（见接口契约） */
  window.addEventListener("beforeunload", () => {
    try { backend.stopEngine(); } catch (_) { /* 卸载中忽略 */ }
  });

  /* 状态进入 ready 时自动建会话 */
  let sessionReady = false;
  backend.onStatus((s) => {
    if (s.state === "ready" && !sessionReady) {
      sessionReady = true;
      ui.session = backend.createSession(activeProfile);
      syncSessionUi();
    }
    if (s.state === "stopped") { sessionReady = false; ui.session = null; }
  });

  function syncSessionUi() {
    const chip = $("#session-value");
    if (ui.session) {
      chip.textContent = profiles[activeProfile] ? profiles[activeProfile].name : ui.session.profile_id;
      chip.title = `${ui.session.session_id} · epoch ${ui.session.epoch} · glossary v${ui.session.glossary_version}`;
    } else {
      chip.textContent = "无会话";
      chip.title = "";
    }
    $("#glossary-version").textContent = "glossary v" + backend.glossaryVersion;
  }

  /* ---------------- 输入 ---------------- */
  const inputJa = $("#input-ja");

  function inputOverLimit() {
    return inputJa.value.length > 2000;
  }

  inputJa.addEventListener("input", () => {
    const n = inputJa.value.length;
    const cc = $("#char-count");
    cc.textContent = `${n} / 2000`;
    cc.classList.toggle("over", n > 2000);
    $("#field-manual").classList.toggle("invalid", n > 2000);
    $("#input-error").textContent = n > 2000
      ? "超过首版上限 2000 字符，请拆分后重试（后端不会静默截断）" : "";
    renderStatus(backend.getStatus());
  });

  /* 输入来源切换（可被游戏配置恢复调用） */
  function setSourceKind(kind) {
    ui.sourceKind = kind;
    $$("#source-kind button").forEach((b) => b.classList.toggle("on", b.dataset.kind === kind));
    $("#field-clipboard").hidden = kind !== "clipboard";
    $("#field-manual").hidden = kind !== "manual";
  }

  $$("#source-kind button").forEach((btn) => {
    btn.addEventListener("click", () => setSourceKind(btn.dataset.kind));
  });

  /* 剪贴板监听开关：默认关闭，由用户打开 */
  const clipSwitch = $("#clipboard-switch");
  clipSwitch.addEventListener("click", () => {
    ui.clipboardOn = !ui.clipboardOn;
    clipSwitch.classList.toggle("on", ui.clipboardOn);
    clipSwitch.setAttribute("aria-checked", String(ui.clipboardOn));
    ensureClipboardMockButton();
  });

  /* mock：模拟一条剪贴板事件（真实监听由桌面壳实现；监听期间不回写剪贴板） */
  function ensureClipboardMockButton() {
    let btn = $("#btn-clipboard-mock");
    if (ui.clipboardOn && !btn) {
      btn = document.createElement("button");
      btn.id = "btn-clipboard-mock";
      btn.className = "btn ghost small";
      btn.innerHTML = '<i class="ph ph-clipboard-text"></i>模拟一条剪贴板文本';
      btn.addEventListener("click", () => {
        const sample = CLIPBOARD_SAMPLES[ui.clipboardIdx++ % CLIPBOARD_SAMPLES.length];
        submitTranslate(sample.text, "clipboard", sample.speaker);
      });
      $(".input-toolbar").prepend(btn);
    } else if (!ui.clipboardOn && btn) {
      btn.remove();
    }
  }

  /* ---------------- 翻译流 ---------------- */
  $("#btn-translate").addEventListener("click", () => {
    submitTranslate(inputJa.value, "manual", $("#input-speaker").value.trim() || null);
  });

  $("#btn-cancel").addEventListener("click", () => {
    if (ui.activeReq && ui.activeReq.handle) ui.activeReq.handle.cancel("user_cancelled");
  });

  $("#btn-retry").addEventListener("click", () => {
    if (ui.lastInput) submitTranslate(ui.lastInput.text, ui.lastInput.kind, ui.lastInput.speaker);
  });

  /* 字幕内容已通过状态流实时同步，按钮只负责打开窗口 */
  $("#btn-to-subtitle").addEventListener("click", openSubtitleWindow);
  $("#btn-open-subtitle").addEventListener("click", openSubtitleWindow);

  function openSubtitleWindow() {
    window.open("subtitle.html", "galtransl-subtitle", "width=720,height=160");
  }

  function uuid() {
    return crypto.randomUUID ? crypto.randomUUID()
      : "req-" + Date.now() + "-" + Math.random().toString(36).slice(2, 10);
  }

  function submitTranslate(text, kind, speaker) {
    if (!text || !text.trim()) return;
    if (!ui.session) { showError("ENGINE_NOT_READY", "会话未建立，请先启动翻译服务"); return; }

    ui.lastInput = { text, kind, speaker };
    const req = {
      request_id: uuid(),                    // 前端生成，先登记
      session_id: ui.session.session_id,
      epoch: ui.session.epoch,
      sequence: ++backend.sequence,          // 会话内单调递增
      source_text: text,
      source_kind: kind,
      speaker,
      captured_at: new Date().toISOString(),
      complete: true,
      stream: true,
    };

    // 每个请求持有独立记录；回调一律以记录校验身份
    const record = {
      id: req.request_id,
      profile_id: backend.currentProfile,
      session_id: req.session_id,
      epoch: req.epoch,
      sequence: req.sequence,
      source_text: text,
      kind,
      speaker: speaker || null,
      buffer: "",
      terminal: null,
      handle: null,
    };

    ui.activeReq = record;
    setStreamTag("streaming", "翻译中");
    showStreamSkeleton(true);
    $("#stream-empty").hidden = true;
    $("#stream-content").hidden = false;
    $("#stream-original").textContent = text;   // 原文立即原样展示，且永不丢失
    $("#stream-translation").innerHTML = "";
    setStreamMeta(`台词 ${req.sequence} · 排队中`, reqDetail(record));
    $("#stream-actions").hidden = true;
    $("#btn-cancel").disabled = false;
    renderStatus(backend.getStatus());
    pushSubtitle("streaming", record, text, "");

    const handle = backend.translate(req, {
      onRejected: (err) => {
        if (record.terminal) return;            // 防重入：已终结记录不再处理
        const current = ui.activeReq === record;  // 先取“当前性”，再落终态
        record.terminal = "rejected";
        writeHistory(record, "rejected", err);
        if (current) {
          ui.activeReq = null;
          showStreamSkeleton(false);
          displayTerminal(record, "rejected", err);
          pushSubtitle("error", record, record.source_text, "",
            { reason: `${err.code}：${err.message}` });
          $("#btn-cancel").disabled = true;
          renderStatus(backend.getStatus());
        }
        showError(err.code, err.message);
      },
      onMeta: (d) => {
        if (!isLive(record, d)) return;
        if(d.replace_buffer){record.buffer="";renderStreamText("",true);pushSubtitle("streaming",record,record.source_text,"");}
        showStreamSkeleton(false);
        setStreamMeta(`台词 ${record.sequence} · 翻译中`, reqDetail(record));
      },
      onDelta: (d) => {
        if (!isLive(record, d)) return;
        showStreamSkeleton(false);
        record.buffer += d.text;                // 增量显示，标注“翻译中”
        renderStreamText(record.buffer, true);
        pushSubtitle("streaming", record, record.source_text, record.buffer);
      },
      onFinal: (d) => {
        if (record.terminal) return;            // 防重入：终态唯一
        if (!matchIdentity(record, d)) return;  // 身份不符的终态不采信
        const current = ui.activeReq === record;
        record.terminal = "final";
        writeHistory(record, "final", d);       // 被取代请求的迟到 final 也存历史
        if (current) {
          ui.activeReq = null;
          renderStreamText(d.translation, false); // final 整体替换增量缓冲
          displayTerminal(record, "final", d);
          pushSubtitle("final", record, record.source_text, d.translation);
          $("#btn-cancel").disabled = true;
          renderStatus(backend.getStatus());
        }
        // 非当前记录的 final：只落历史，不覆盖新字幕
      },
      onCancelled: (d) => {
        if (record.terminal) return;            // 防重入：终态唯一
        if (!matchIdentity(record, d)) return;  // 与 meta/delta/final 同一道身份校验
        // 可能因被新请求取代而同步触发：只更新自身记录与历史
        const current = ui.activeReq === record;
        record.terminal = "cancelled";
        writeHistory(record, "cancelled", d);
        if (current) {
          ui.activeReq = null;
          displayTerminal(record, "cancelled", d);
          pushSubtitle("cancelled", record, record.source_text, record.buffer,
            { reason: reasonText(d.reason) });
          $("#btn-cancel").disabled = true;
          renderStatus(backend.getStatus());
        }
      },
      onError: (d) => {
        if (record.terminal) return;            // 防重入：终态唯一
        if (!matchIdentity(record, d)) return;  // 与 meta/delta/final 同一道身份校验
        const current = ui.activeReq === record;
        record.terminal = d.interrupted ? "interrupted" : "error";
        writeHistory(record, record.terminal, d);
        if (current) {
          ui.activeReq = null;
          displayTerminal(record, record.terminal, d);
          pushSubtitle(record.terminal, record, record.source_text, record.buffer,
            { reason: `${d.code}：${d.message}` });
          $("#btn-cancel").disabled = true;
          renderStatus(backend.getStatus());
        }
      },
    });

    if (handle) {
      // 保存句柄前核对当前记录仍是此次提交（旧请求的同步取消可能已替换 activeReq）
      if (ui.activeReq === record && !record.terminal) {
        record.handle = handle;
      } else {
        handle.cancel("superseded");
      }
    } else if (ui.activeReq === record && !record.terminal) {
      ui.activeReq = null;
      $("#btn-cancel").disabled = true;
    }
  }

  /* 身份校验：事件四要素与记录一致 */
  function matchIdentity(record, d) {
    return !!record && !!d
      && d.request_id === record.id
      && d.session_id === record.session_id
      && d.epoch === record.epoch
      && d.sequence === record.sequence;
  }

  /* 增量事件门禁：身份一致、仍是当前台词、尚未到达终态 */
  function isLive(record, d) {
    return matchIdentity(record, d) && ui.activeReq === record && !record.terminal;
  }

  /* 外部注入（mock 调试：旧请求晚到）也走同一道门禁 */
  window.__injectStreamEvent = function (eventName, data) {
    if (ui.activeReq && isLive(ui.activeReq, data)) {
      if (eventName === "delta") {
        ui.activeReq.buffer += data.text;
        renderStreamText(ui.activeReq.buffer, true);
      }
      return true;
    }
    noteStaleEvent(eventName, data);
    return false;
  };

  function noteStaleEvent(eventName, data) {
    setStreamMeta(
      `已忽略过期事件 ${eventName}`,
      `request ${data.request_id} · seq ${data.sequence} · epoch ${data.epoch}`
    );
  }

  function reqDetail(record) {
    return `request ${record.id} · session ${record.session_id} · seq ${record.sequence} · epoch ${record.epoch}`;
  }

  /* 玩家可读的元信息；协议细节放进悬停提示 */
  function setStreamMeta(text, title) {
    const meta = $("#stream-meta");
    meta.textContent = text;
    meta.title = title || "";
  }

  function renderStreamText(text, streaming) {
    const el = $("#stream-translation");
    el.textContent = text;
    if (streaming) {
      const caret = document.createElement("span");
      caret.className = "caret";
      el.appendChild(caret);
    }
  }

  function setStreamTag(kind, label) {
    const tag = $("#stream-tag");
    tag.className = "tag" + (kind === "streaming" ? " streaming"
      : kind === "final" ? " final"
      : kind === "broken" ? " broken" : "");
    tag.textContent = label;
  }

  function showStreamSkeleton(on) {
    $("#stream-skeleton").hidden = !on;
    $("#stream-content").hidden = on;
  }

  /* 终态写历史：原文原样保留，任何终态都不丢原文 */
  function writeHistory(record, terminal, data) {
    backend.pushHistory({
      request_id: record.id,
      profile_id: record.profile_id,
      at: new Date().toISOString(),
      source_text: record.source_text,
      source_kind: record.kind,
      speaker: record.speaker,
      terminal,
      translation: terminal === "final" ? data.translation : null,
      reason: terminal === "cancelled" ? reasonText(data.reason)
        : terminal === "interrupted" ? "流中断，未收到终态"
        : terminal === "error" ? `${data.code}：${data.message}`
        : terminal === "rejected" ? `${data.code}：${data.message}` : null,
      elapsed_ms: terminal === "final" ? data.elapsed_ms : null,
      warnings: terminal === "final" ? (data.warnings || []) : [],
    });
  }

  /* 终态上屏：仅当前记录可调用 */
  function displayTerminal(record, terminal, data) {
    if (terminal === "final") {
      setStreamTag("final", "已完成");
      setStreamMeta(`台词 ${record.sequence} · 耗时 ${data.elapsed_ms} ms`, reqDetail(record));
      renderWarnings(data.warnings || []);
    } else if (terminal === "cancelled") {
      setStreamTag("broken", "已取消");
      setStreamMeta(`台词 ${record.sequence} · ${reasonText(data.reason)}，原文已保留`, reqDetail(record));
    } else if (terminal === "interrupted") {
      setStreamTag("broken", "已中断");
      setStreamMeta("流断开且未收到终态，可重试（不会自动重复提交）", reqDetail(record));
    } else if (terminal === "rejected") {
      setStreamTag("broken", "未提交");
      setStreamMeta(`${data.code}：${data.message} · 原文已保留`, reqDetail(record));
    } else {
      setStreamTag("broken", "未完成");
      setStreamMeta(`${data.code}：${data.message} · 原文已保留`, reqDetail(record));
    }
    $("#stream-actions").hidden = false;
  }

  function reasonText(r) {
    return { user_cancelled: "用户取消", superseded: "被新台词取代",
      session_reset: "会话重置", engine_stopped: "引擎停止" }[r] || r;
  }

  /* 风险提示：轻量“需复核”，不显示成置信度 */
  function renderWarnings(warnings) {
    const meta = $("#stream-meta");
    warnings.forEach((w) => {
      const chip = document.createElement("span");
      chip.className = "tag warn-review";
      chip.style.marginLeft = "8px";
      chip.title = w.message;
      chip.innerHTML = '<i class="ph ph-warning"></i>需复核';
      meta.appendChild(chip);
    });
  }

  /* ---------------- 字幕状态流 ----------------
   * 有效台词自动进入字幕；payload 携带身份与终态，
   * 失败 / 取消 / 断流片段显式标注，不冒充普通译文。 */
  function pushSubtitle(state, record, ja, zh, extra) {
    const payload = {
      request_id: record ? record.id : null,
      session_id: record ? record.session_id : null,
      epoch: record ? record.epoch : null,
      sequence: record ? record.sequence : null,
      state,                    // idle / streaming / final / cancelled / interrupted / error
      ja: ja || "",
      zh: zh || "",
      reason: extra && extra.reason ? extra.reason : null,
      at: new Date().toISOString(),
    };
    try { localStorage.setItem(SUB_KEY, JSON.stringify(payload)); } catch (_) { /* 忽略 */ }
    syncSubtitlePreview(payload);
  }

  function pushSubtitleIdle() {
    pushSubtitle("idle", null, "", "");
  }

  function syncSubtitlePreview(p) {
    $("#sub-prev-ja").textContent = p.ja || "（等待台词）";
    $("#sub-prev-zh").textContent = p.zh || "";
    const badge = $("#sub-state-badge");
    if (p.state === "final" || p.state === "idle") {
      badge.hidden = true;
    } else {
      badge.hidden = false;
      badge.className = "tag " + (p.state === "streaming" ? "streaming" : "broken");
      badge.textContent = { streaming: "翻译中", cancelled: "已取消",
        interrupted: "已中断", error: "未完成" }[p.state] || p.state;
      badge.title = p.reason || "";
    }
  }

  /* ---------------- 会话重置 / 读档 ---------------- */
  $("#btn-reset-session").addEventListener("click", () => {
    const next = backend.resetSession("scene_change");
    if (next) {
      ui.session = next;
      syncSessionUi();
      pushSubtitleIdle();
      setStreamTag("", "待输入");
      setStreamMeta("会话已重置，可以提交新台词", "");
    }
  });

  /* ---------------- 错误横幅 ---------------- */
  function showError(code, message) {
    $("#banner-error").hidden = false;
    $("#banner-error-title").textContent = code;
    $("#banner-error-desc").textContent = message;
  }
  $("#banner-error-close").addEventListener("click", () => { $("#banner-error").hidden = true; });
  $("#btn-vram-recheck").addEventListener("click", () => renderStatus(backend.getStatus()));

  /* ---------------- 术语表 ---------------- */
  function renderGlossary() {
    const body = $("#glossary-body");
    body.innerHTML = "";
    backend.glossary.forEach((e, i) => {
      const tr = document.createElement("tr");
      tr.innerHTML =
        `<td><input type="text" class="ja" data-field="source" aria-label="第 ${i + 1} 行日文词" value="${escapeHtml(e.source)}"></td>` +
        `<td><input type="text" data-field="target" aria-label="第 ${i + 1} 行中文译名" value="${escapeHtml(e.target)}"></td>` +
        `<td><input type="text" data-field="note" aria-label="第 ${i + 1} 行备注" value="${escapeHtml(e.note || "")}"></td>` +
        `<td><button class="icon-btn" title="删除" aria-label="删除第 ${i + 1} 行"><i class="ph ph-trash"></i></button></td>`;
      tr.querySelectorAll("input").forEach((inp) => {
        inp.addEventListener("input", () => { e[inp.dataset.field] = inp.value; });
      });
      tr.querySelector(".icon-btn").addEventListener("click", () => {
        backend.glossary.splice(i, 1);
        renderGlossary();
      });
      body.appendChild(tr);
    });
  }

  function escapeHtml(s) {
    return String(s).replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/"/g, "&quot;");
  }

  $("#btn-glossary-add").addEventListener("click", () => {
    backend.glossary.push({ source: "", target: "", note: "" });
    renderGlossary();
    const inputs = $$("#glossary-body tr:last-child input");
    if (inputs[0]) inputs[0].focus();
  });

  $("#btn-glossary-save").addEventListener("click", () => {
    const btn = $("#btn-glossary-save");
    try {
      const res = backend.saveGlossary(backend.glossary);
      if (res && res.session_id) ui.session = res;   // 无会话时返回仅含版本号
      syncSessionUi();
      $("#banner-glossary").hidden = true;
      $$("#glossary-body tr").forEach((tr) => tr.classList.remove("row-error"));
      btn.innerHTML = '<i class="ph ph-check"></i>已保存';
      setTimeout(() => { btn.innerHTML = '<i class="ph ph-floppy-disk"></i>保存到后端'; }, 1500);
    } catch (err) {
      $("#banner-glossary").hidden = false;
      $("#banner-glossary-desc").textContent = `${err.code}：${err.message}`;
      $$("#glossary-body tr").forEach((tr, i) =>
        tr.classList.toggle("row-error", typeof err.row === "number" && i === err.row));
    }
  });
  $("#banner-glossary-close").addEventListener("click", () => { $("#banner-glossary").hidden = true; });

  /* UTF-8 导入导出 */
  $("#btn-glossary-export").addEventListener("click", () => {
    const blob = new Blob([JSON.stringify(backend.glossary, null, 2)],
      { type: "application/json;charset=utf-8" });
    download(blob, "glossary-utf8.json");
  });

  $("#btn-glossary-import").addEventListener("click", () => {
    const input = document.createElement("input");
    input.type = "file";
    input.accept = ".json,application/json";
    input.addEventListener("change", async () => {
      if (!input.files[0]) return;
      try {
        const text = await input.files[0].text();   // 按 UTF-8 读取
        const entries = JSON.parse(text);
        if (!Array.isArray(entries)) throw new Error("格式应为词条数组");
        backend.glossary = entries.map((e) => ({
          source: String(e.source || ""), target: String(e.target || ""), note: String(e.note || ""),
        }));
        renderGlossary();
      } catch (e2) {
        $("#banner-glossary").hidden = false;
        $("#banner-glossary-desc").textContent = "导入失败：" + e2.message;
      }
    });
    input.click();
  });

  /* ---------------- 历史 ---------------- */
  function renderHistory() {
    if(!backlogAccess.requestToken(activeProfile))return;
    const list = $("#history-list");
    const all = backend.history;
    $("#history-empty").hidden = all.length > 0;
    $$(".history-item").forEach((n) => n.remove());

    const pages = Math.max(1, Math.ceil(all.length / ui.HISTORY_PAGE_SIZE));
    ui.historyPage = Math.min(ui.historyPage, pages);
    const start = (ui.historyPage - 1) * ui.HISTORY_PAGE_SIZE;
    const items = all.slice(start, start + ui.HISTORY_PAGE_SIZE);

    items.forEach((h) => {
      const div = document.createElement("div");
      div.className = "history-item";
      const meta = document.createElement("div");
      meta.className = "history-meta";
      const kindText = h.source_kind === "manual" ? "手动" : h.source_kind === "clipboard" ? "剪贴板" : h.source_kind;
      meta.innerHTML =
        `<span class="tag">${kindText}</span>` +
        (h.speaker ? `<span class="tag ja">${escapeHtml(h.speaker)}</span>` : "") +
        (h.terminal === "final"
          ? `<span class="tag final">完成</span><span class="mono">${h.elapsed_ms} ms</span>`
          : `<span class="tag broken">${h.terminal === "cancelled" ? "已取消" : h.terminal === "interrupted" ? "已中断" : "未完成"}</span>`) +
        h.warnings.map(() => '<span class="tag warn-review" title="规则提示，非置信度"><i class="ph ph-warning"></i>需复核</span>').join("") +
        `<span class="mono">${new Date(h.at).toLocaleTimeString("zh-CN")}</span>`;
      const ja = document.createElement("div");
      ja.className = "history-ja";
      ja.textContent = h.source_text;
      const zh = document.createElement("div");
      zh.className = "history-zh" + (h.terminal === "final" ? "" : " failed");
      zh.textContent = h.terminal === "final" ? h.translation : "未产生译文：" + h.reason;
      div.append(meta, ja, zh);
      list.appendChild(div);
    });

    $("#history-pager").hidden = pages <= 1;
    $("#pager-info").textContent = `${ui.historyPage} / ${pages}`;
  }

  $("#pager-prev").addEventListener("click", () => {
    if (ui.historyPage > 1) { ui.historyPage--; renderHistory(); }
  });
  $("#pager-next").addEventListener("click", () => {
    const pages = Math.ceil(backend.history.length / ui.HISTORY_PAGE_SIZE);
    if (ui.historyPage < pages) { ui.historyPage++; renderHistory(); }
  });

  /* 清空上下文（读档）：只重置会话上下文，契约要求保留原文对照历史 */
  $("#btn-history-clear").addEventListener("click", () => {
    const next = backend.resetSession("save_load");   // 读档：先会话重置，返回后用新 epoch
    if (next) { ui.session = next; syncSessionUi(); }
    ui.historyPage = 1;
    pushSubtitleIdle();
    renderHistory();                                  // 历史保留，仅回到第一页
  });

  /* 删除历史是独立的显式操作：永久删除当前游戏的历史（含原文对照） */
  $("#btn-history-delete").addEventListener("click", () => {
    const name = profiles[activeProfile] ? profiles[activeProfile].name : activeProfile;
    if (!window.confirm(`永久删除「${name}」的全部历史记录（含原文对照）？此操作不可撤销。`)) return;
    backend.clearHistory();
    ui.historyPage = 1;
    renderHistory();
  });

  $("#btn-history-export").addEventListener("click", () => {
    const blob = new Blob([JSON.stringify(backend.history, null, 2)],
      { type: "application/json;charset=utf-8" });
    download(blob, "history-utf8.json");
  });

  function download(blob, name) {
    const a = document.createElement("a");
    a.href = URL.createObjectURL(blob);
    a.download = name;
    a.click();
    setTimeout(() => URL.revokeObjectURL(a.href), 5000);
  }

  /* ---------------- 字幕预览控制 ---------------- */
  const subPreview = $("#subtitle-preview");
  const clickthrough = $("#sub-clickthrough");

  $("#sub-font").addEventListener("input", (e) => {
    const s = profiles[activeProfile].subtitle;
    s.font = Number(e.target.value);
    $("#sub-font-value").textContent = s.font + "px";
    subPreview.style.fontSize = s.font + "px";
    persistProfiles();
  });

  $("#sub-opacity").addEventListener("input", (e) => {
    const s = profiles[activeProfile].subtitle;
    s.opacity = Number(e.target.value);
    $("#sub-opacity-value").textContent = s.opacity + "%";
    // 只调底衬透明度，文字保持全不透明
    subPreview.style.setProperty("--sub-alpha", (s.opacity / 100).toFixed(2));
    persistProfiles();
  });

  $$("#sub-mode button").forEach((btn) => {
    btn.addEventListener("click", () => {
      profiles[activeProfile].subtitle.mode = btn.dataset.mode;
      applySubtitleMode(btn.dataset.mode);
      persistProfiles();
    });
  });

  function applySubtitleMode(mode) {
    $$("#sub-mode button").forEach((b) => b.classList.toggle("on", b.dataset.mode === mode));
    $("#sub-prev-ja").style.display = mode === "zh" ? "none" : "";
    $("#sub-prev-zh").style.display = mode === "ja" ? "none" : "";
  }

  clickthrough.addEventListener("click", () => {
    const on = !clickthrough.classList.contains("on");
    profiles[activeProfile].subtitle.clickthrough = on;
    clickthrough.classList.toggle("on", on);
    clickthrough.setAttribute("aria-checked", String(on));
    subPreview.style.pointerEvents = on ? "none" : "";
    persistProfiles();
  });

  /* 字幕偏好写入当前 profile，并发布到字幕窗读取的生效键 */
  function persistProfiles() {
    try {
      localStorage.setItem(PROFILE_KEY, JSON.stringify(profiles));
      localStorage.setItem(ACTIVE_PROFILE_KEY, activeProfile);
      localStorage.setItem(SUB_PREFS_KEY, JSON.stringify(profiles[activeProfile].subtitle));
    } catch (_) { /* 忽略 */ }
  }

  function applySubtitleControls(s) {
    $("#sub-font").value = s.font;
    $("#sub-font-value").textContent = s.font + "px";
    subPreview.style.fontSize = s.font + "px";
    $("#sub-opacity").value = s.opacity;
    $("#sub-opacity-value").textContent = s.opacity + "%";
    subPreview.style.setProperty("--sub-alpha", (s.opacity / 100).toFixed(2));
    applySubtitleMode(s.mode);
    clickthrough.classList.toggle("on", s.clickthrough);
    clickthrough.setAttribute("aria-checked", String(s.clickthrough));
    subPreview.style.pointerEvents = s.clickthrough ? "none" : "";
  }

  function collectCurrentControls() {
    profiles[activeProfile].sourceKind = ui.sourceKind;
    // 字幕控件在各自的 input/click 处理中已实时写回 profile
  }

  function applyProfile(id) {
    setSourceKind(profiles[id].sourceKind);
    applySubtitleControls(profiles[id].subtitle);
    $$(".profile-card").forEach((c) => c.classList.toggle("on", c.dataset.profile === id));
  }

  /* 字幕条拖动（预览区内）：按下时记录舞台 / 字幕矩形与指针起点，
     移动时只按“起点 + 指针位移”一次性计算并夹取，不叠加变化的 offsetLeft */
  (function enableDrag() {
    const stage = $("#subtitle-stage");
    let drag = null; // { pointerId, startX, startY, baseLeft, baseTop, maxLeft, maxTop }
    subPreview.addEventListener("pointerdown", (e) => {
      const stageRect = stage.getBoundingClientRect();
      const barRect = subPreview.getBoundingClientRect();
      // CSS left/top 相对舞台 padding box：clientLeft 为边框宽度
      const originX = stageRect.left + stage.clientLeft;
      const originY = stageRect.top + stage.clientTop;
      drag = {
        pointerId: e.pointerId,
        startX: e.clientX,
        startY: e.clientY,
        baseLeft: barRect.left - originX,
        baseTop: barRect.top - originY,
        maxLeft: Math.max(0, stage.clientWidth - subPreview.offsetWidth),
        maxTop: Math.max(0, stage.clientHeight - subPreview.offsetHeight),
      };
      subPreview.style.position = "absolute";
      subPreview.style.left = drag.baseLeft + "px";
      subPreview.style.top = drag.baseTop + "px";
      subPreview.setPointerCapture(e.pointerId);
      e.preventDefault();
    });
    subPreview.addEventListener("pointermove", (e) => {
      if (!drag || e.pointerId !== drag.pointerId) return;
      const left = drag.baseLeft + (e.clientX - drag.startX);
      const top = drag.baseTop + (e.clientY - drag.startY);
      subPreview.style.left = Math.max(0, Math.min(left, drag.maxLeft)) + "px";
      subPreview.style.top = Math.max(0, Math.min(top, drag.maxTop)) + "px";
    });
    const endDrag = (e) => {
      if (drag && e.pointerId === drag.pointerId) drag = null; // pointerup / pointercancel 都收尾
    };
    subPreview.addEventListener("pointerup", endDrag);
    subPreview.addEventListener("pointercancel", endDrag);
  })();

  /* ---------------- 游戏配置 ---------------- */
  $$(".profile-card").forEach((card) => {
    card.addEventListener("click", () => {
      const id = card.dataset.profile;
      if (!profiles[id] || id === activeProfile) return;
      collectCurrentControls();             // 旧配置的控件状态先落盘
      activeProfile = id;
      backlogAccess.close();
      if($('#page-history').classList.contains('active'))$('.rail-item[data-page="translate"]').click();
      applyProfile(id);                     // 真正应用新配置的输入源与字幕样式
      persistProfiles();
      backend.setProfile(id);
      if (ui.session) {
        const next = backend.resetSession("profile_switch"); // 切换游戏：重置会话并清空上下文
        if (next) ui.session = next;
      }
      pushSubtitleIdle();
      syncSessionUi();
      renderGlossary();                 // 术语按游戏隔离，切换后重新渲染
      ui.historyPage = 1;
      renderHistory();                  // 历史按游戏隔离，切换后重新渲染
    });
  });

  /* ---------------- Mock 场景条 ---------------- */
  $$("#mock-bar [data-scenario]").forEach((btn) => {
    btn.addEventListener("click", () => {
      const sc = btn.dataset.scenario;
      $$("#mock-bar [data-scenario]").forEach((b) => b.classList.remove("primary"));
      btn.classList.add("primary");

      if (sc === "superseded") {
        // 旧请求晚到验证：直接以 fixtures 原始身份注入流，必须被门禁丢弃
        const parser = new SseParser((event, data) => window.__injectStreamEvent(event, data));
        chunkString(backend.fixtures["superseded.sse"], backend.chunkMode)
          .forEach((c, i) => setTimeout(() => parser.feed(c), i * 60));
        setTimeout(() => parser.end(), backend.fixtures["superseded.sse"].length);
        return;
      }
      if (sc === "engine_not_ready") {
        backend.scenario = "normal";
        backend.state = "loading";            // 未就绪时提交应收到 ENGINE_NOT_READY
        backend._loadStart = Date.now();
        backend._emit();
        return;
      }
      backend.scenario = sc;
      if (sc === "vram_low" && (backend.state === "ready" || backend.state === "translating")) {
        backend.state = "paused";
        backend._emit();
      }
      if (sc === "normal" && (backend.state === "paused" || backend.state === "loading")) {
        backend.state = "ready";              // 模拟显存恢复 / 加载完成
        backend._emit();
      }
    });
  });

  $("#btn-glossary-fail").addEventListener("click", () => {
    backend.glossaryFailNext = true;
    $("#btn-glossary-fail").textContent = "已标记：下一次保存将失败";
    setTimeout(() => { $("#btn-glossary-fail").textContent = "术语保存失败（下一次）"; }, 2500);
  });

  /* ---------------- 启动 ---------------- */
  (async function init() {
    initTheme();
    applyProfile(activeProfile);        // 读回保存的游戏配置与字幕偏好
    persistProfiles();
    await backend.loadFixtures();
    renderGlossary();
    renderHistory();
    renderStatus(backend.getStatus());
  })();
})();
