/* Mock 后端行为回归测试：node test-mock.mjs
 * 覆盖 docs/前端检查报告.md 复现的缺陷：
 * 1. 启动中立即停止后，旧启动计时器不得再把状态推为 ready
 * 2. 连续两条台词：旧请求被取消且不产生异常，新请求正常完成
 * 3. 翻译中途停止引擎：收尾回调不得把 stopping/stopped 改回 ready
 * 4. 术语“保存失败”场景报存储错误，不虚构“第 0 行”字段错误
 * 5. 无会话时术语可保存且版本递增；空词条校验定位真实行
 * 覆盖 docs/前端复查报告.md 复现的缺陷：
 * 6. 取消与断流事件携带完整身份字段（request_id/session_id/epoch/sequence）
 * 7. 术语、术语版本与历史按 profile_id 隔离，切换游戏互不串扰
 * 8. 重置上下文保留历史；只有显式删除才清空
 */
const readFileSync = require("node:fs").readFileSync;
const path = require("node:path");

const sseSrc = readFileSync(path.join(__dirname, "js", "sse.js"), "utf8");
const mockSrc = readFileSync(path.join(__dirname, "js", "mock-api.js"), "utf8");
const factory = new Function(`${sseSrc}\n${mockSrc}\nreturn MockBackend;`);
const MockBackend = factory();

const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
let failures = 0;

function check(name, cond, detail) {
  if (cond) console.log(`PASS  ${name}`);
  else { console.log(`FAIL  ${name}${detail ? " :: " + detail : ""}`); failures++; }
}

(async () => {
  /* 1. 启动中停止：过期启动回调失效 */
  {
    const b = new MockBackend();
    b.speed = 0.01;
    b.startEngine();
    await sleep(5);
    b.stopEngine();
    await sleep(200); // 远超 (700+2200+800)*0.01
    check("启动中停止后保持 stopped", b.state === "stopped", `state=${b.state}`);
  }

  /* 2. 连续台词：旧取消、新完成、无异常 */
  {
    const b = new MockBackend();
    b.speed = 0.01;
    b.chunkMode = "fixed";
    b.state = "ready";
    const s = b.createSession("default");
    const mk = (text, seq) => ({
      request_id: "req-" + seq, session_id: s.session_id, epoch: 1, sequence: seq,
      source_text: text, source_kind: "clipboard", speaker: null,
      captured_at: new Date().toISOString(), complete: true, stream: true,
    });
    const eventsA = [];
    let crashed = null;
    let bFinal = null;
    try {
      b.translate(mk("第一句", 1), {
        onRejected: (e) => eventsA.push(["rejected", e.code]),
        onMeta: () => eventsA.push(["meta"]), onDelta: () => eventsA.push(["delta"]),
        onFinal: () => eventsA.push(["final"]),
        onCancelled: (d) => eventsA.push(["cancelled", d.reason]),
        onError: (d) => eventsA.push(["error", d.code]),
      });
      // 立刻提交第二条（同步取代旧请求）
      const h2 = b.translate(mk("第二句", 2), {
        onRejected: (e) => eventsA.push(["B-rejected", e.code]),
        onMeta: () => {}, onDelta: () => {},
        onFinal: (d) => { bFinal = d; },
        onCancelled: () => eventsA.push(["B-cancelled"]),
        onError: (d) => eventsA.push(["B-error", d.code]),
      });
      if (!h2) crashed = "second translate returned no handle";
      const deadline = Date.now() + 5000;
      while (!bFinal && !crashed && Date.now() < deadline) await sleep(10);
    } catch (e) { crashed = e.message; }
    check("连续台词无异常", !crashed, crashed);
    check("旧请求收到 superseded 取消",
      eventsA.some(([e, r]) => e === "cancelled" && r === "superseded"),
      JSON.stringify(eventsA));
    check("新请求拿到 final", !!bFinal && typeof bFinal.translation === "string");
    check("新请求完成后回到 ready", b.state === "ready", `state=${b.state}`);
  }

  /* 3. 翻译中途停止引擎：收尾不得改回 ready */
  {
    const b = new MockBackend();
    b.speed = 0.01;
    b.state = "ready";
    const s = b.createSession("default");
    let cancelReason = null;
    b.translate({
      request_id: "req-x", session_id: s.session_id, epoch: 1, sequence: 1,
      source_text: "テスト", source_kind: "manual", speaker: null,
      captured_at: new Date().toISOString(), complete: true, stream: true,
    }, {
      onRejected: () => {}, onMeta: () => {}, onDelta: () => {},
      onFinal: () => {}, onCancelled: (d) => { cancelReason = d.reason; }, onError: () => {},
    });
    // 确定性时序：translate 同步登记 _active，同一宏任务内停止必定命中取消；
    // 原先 sleep(20) 会与随机切片流（最短约 10ms 播完）赛跑，约 1/4 概率漏取消
    b.stopEngine();
    await sleep(200);
    check("翻译中停止后保持 stopped", b.state === "stopped", `state=${b.state}`);
    check("活动请求以 engine_stopped 取消", cancelReason === "engine_stopped", cancelReason);
  }

  /* 4. 术语保存失败场景：存储错误，不虚构行号 */
  {
    const b = new MockBackend();
    b.glossaryFailNext = true;
    let err = null;
    try { b.saveGlossary(b.glossary); } catch (e) { err = e; }
    check("保存失败报 INTERNAL_ERROR", !!err && err.code === "INTERNAL_ERROR", err && err.code);
    check("不虚构字段错误行", !!err && err.row === null, err && String(err.row));
  }

  /* 5. 无会话保存术语 + 真实空行定位 */
  {
    const b = new MockBackend();
    const before = b.glossaryVersion;
    const res = b.saveGlossary([{ source: "葵", target: "葵", note: "" }]);
    check("无会话保存成功且版本递增", res.glossary_version === before + 1,
      JSON.stringify(res));
    let err = null;
    try {
      b.saveGlossary([{ source: "葵", target: "葵", note: "" }, { source: "  ", target: "x", note: "" }]);
    } catch (e) { err = e; }
    check("空词条定位真实行（第 2 行）", !!err && err.row === 1 && err.code === "INVALID_GLOSSARY",
      err && `${err.code} row=${err.row}`);
  }

  /* 6. 取消与断流事件携带完整身份字段（v0.1.2，复查报告） */
  {
    const b = new MockBackend();
    b.speed = 0.01;
    b.state = "ready";
    const s = b.createSession("default");
    const req = {
      request_id: "req-id1", session_id: s.session_id, epoch: 1, sequence: 1,
      source_text: "テスト", source_kind: "manual", speaker: null,
      captured_at: new Date().toISOString(), complete: true, stream: true,
    };
    let cancelledPayload = null;
    const h = b.translate(req, {
      onRejected: () => {}, onMeta: () => {}, onDelta: () => {},
      onFinal: () => {}, onCancelled: (d) => { cancelledPayload = d; }, onError: () => {},
    });
    h.cancel("user_cancelled");
    check("取消事件携带完整身份字段",
      !!cancelledPayload && ["request_id", "session_id", "epoch", "sequence"]
        .every((k) => cancelledPayload[k] === req[k]),
      JSON.stringify(cancelledPayload));

    const b2 = new MockBackend();
    b2.speed = 0.01;
    b2.chunkMode = "fixed";
    b2.scenario = "interrupted";
    b2.state = "ready";
    const s2 = b2.createSession("default");
    const req2 = { ...req, request_id: "req-id2", session_id: s2.session_id };
    let errPayload = null;
    b2.translate(req2, {
      onRejected: () => {}, onMeta: () => {}, onDelta: () => {},
      onFinal: () => {}, onCancelled: () => {}, onError: (d) => { errPayload = d; },
    });
    const deadline = Date.now() + 5000;
    while (!errPayload && Date.now() < deadline) await sleep(10);
    check("断流事件携带完整身份字段",
      !!errPayload && errPayload.interrupted === true && ["request_id", "session_id", "epoch", "sequence"]
        .every((k) => errPayload[k] === req2[k]),
      JSON.stringify(errPayload));
  }

  /* 7. 术语、术语版本与历史按游戏隔离（v0.1.2，复查报告） */
  {
    const b = new MockBackend();
    b.createSession("default");
    b.saveGlossary([{ source: "葵", target: "小葵", note: "" }]);
    b.pushHistory({ request_id: "r-default", source_text: "デフォルトの台詞", terminal: "final" });
    const versionInDefault = b.glossaryVersion;

    b.setProfile("yoru");
    check("切换游戏后术语为空表", b.glossary.length === 0, JSON.stringify(b.glossary));
    check("切换游戏后历史为空", b.history.length === 0, JSON.stringify(b.history));
    check("切换游戏后术语版本独立", b.glossaryVersion === 1, String(b.glossaryVersion));

    b.setProfile("default");
    check("切回默认配置术语保留",
      b.glossary.some((e) => e.target === "小葵") && b.glossaryVersion === versionInDefault,
      JSON.stringify(b.glossary));
    check("切回默认配置历史保留且带游戏身份",
      b.history.length === 1 && b.history[0].profile_id === "default",
      JSON.stringify(b.history));
  }

  /* 8. 重置上下文保留历史；只有显式删除才清空（v0.1.2，复查报告） */
  {
    const b = new MockBackend();
    b.createSession("default");
    b.pushHistory({ request_id: "r-keep", source_text: "残す台詞", terminal: "final" });
    b.resetSession("save_load");
    check("重置上下文保留历史", b.history.length === 1, JSON.stringify(b.history));
    b.clearHistory();
    check("显式删除才清空历史", b.history.length === 0, JSON.stringify(b.history));
  }

  /* 请求发起游戏固定：切换之后的取消回调不能落入新游戏。 */
  {
    const b = new MockBackend();
    b.state = "ready";
    const s = b.createSession("default");
    const profileId = b.currentProfile;
    const req = {request_id:"switch-running",session_id:s.session_id,epoch:s.epoch,sequence:1,
      source_text:"切换中的旧台词",source_kind:"manual",speaker:null,
      captured_at:new Date().toISOString(),complete:true,stream:true};
    b.translate(req, {onRejected:()=>{},onMeta:()=>{},onDelta:()=>{},onFinal:()=>{},onError:()=>{},
      onCancelled:d=>b.pushHistory({profile_id:profileId,request_id:d.request_id,source_text:req.source_text,terminal:"cancelled"})});
    b.setProfile("sakura");
    b.resetSession("profile_switch");
    check("切换中的旧取消记录不进入新游戏", b.history.length === 0, JSON.stringify(b.history));
    b.setProfile("default");
    check("旧取消记录保留在发起游戏", b.history.some(h=>h.request_id===req.request_id && h.profile_id===profileId), JSON.stringify(b.history));
  }

  console.log(failures === 0 ? "\n全部通过" : `\n${failures} 项失败`);
  process.exitCode = failures === 0 ? 0 : 1;
})();
