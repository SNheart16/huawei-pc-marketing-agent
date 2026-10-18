/* 华为 PC 营销内容智能体 · 前端逻辑（成员 B）
 * 优先调用后端 POST /api/run（即 run_agent）；后端不可用时回退到 mock.js。
 */
(function () {
  "use strict";
  const $ = (id) => document.getElementById(id);
  const esc = (s) => String(s == null ? "" : s).replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));

  const SCENES = ["开学季", "职场办公", "内容创作", "家庭换新", "企业采购", "门店到访", "新品首发", "节日营销"];
  const PLATFORMS = [
    { key: "公众号", ico: "WECHAT", color: "#07c160", hint: "2–4 图 · 长文" },
    { key: "小红书", ico: "RED", color: "#ff2442", hint: "3–6 图 · 标签" },
    { key: "门店朋友圈", ico: "MOMENTS", color: "#576b95", hint: "1–3 图 · 短文" },
    { key: "门店海报", ico: "POSTER", color: "#e5a23a", hint: "1 主视觉" }
  ];
  const STEPS = [
    ["scene", "场景解析", "◎"], ["strategy", "平台策略", "◇"], ["retrieve", "ima 检索", "⌕"],
    ["facts", "事实提取", "≡"], ["layout", "图文编排", "▦"], ["generate", "软文生成", "✎"],
    ["verify", "事实核验", "✓"], ["compliance", "合规检查", "⚖"], ["export", "导出", "↗"]
  ];
  const CASES = [
    { tag: "用例1", label: "大学新生 · 开学季 · 小红书", v: { product_query: "MateBook 14", audience: "大学新生", scene: "开学季", platform: "小红书", goal: "突出学习、便携和多设备协同", extra_requirements: "" } },
    { tag: "用例2", label: "商务人士 · 职场办公 · 公众号", v: { product_query: "MateBook 14", audience: "经常出差的商务人士", scene: "职场办公", platform: "公众号", goal: "突出会议、差旅、文档处理和安全", extra_requirements: "" } },
    { tag: "用例3a", label: "缺价格 · 只做产品介绍 · 朋友圈", v: { product_query: "MateBook 14", audience: "附近潜在顾客", scene: "门店到访", platform: "门店朋友圈", goal: "产品介绍", extra_requirements: "" } },
    { tag: "用例3b", label: "要求写价格优惠 → 追问", v: { product_query: "MateBook 14", audience: "普通消费者", scene: "节日营销", platform: "门店朋友圈", goal: "价格优惠推广", extra_requirements: "加上国补后的价格" } },
    { tag: "用例3c", label: "型号模糊“想买轻薄本” → 追问", v: { product_query: "想买轻薄本", audience: "普通消费者", scene: "新品首发", platform: "门店朋友圈", goal: "", extra_requirements: "" } },
    { tag: "用例4", label: "家庭用户 · 家庭换新 · 门店海报", v: { product_query: "MateBook 14", audience: "家庭用户", scene: "家庭换新", platform: "门店海报", goal: "", extra_requirements: "" } }
  ];
  const STATUS_TEXT = { success: "生成完成", partial: "部分完成", needs_input: "需要补充信息", conflict: "资料冲突", error: "执行失败" };
  const RESULT_ICO = { pass: "✓", warning: "!", fail: "✕", unknown: "?" };
  const RESULT_TEXT = { pass: "通过", warning: "警告", fail: "失败", unknown: "待确认" };
  const MEDIA_TEXT = { usable: "可用", unreachable: "无法访问", model_mismatch: "型号不符", pending_confirmation: "待确认" };
  const GRADS = ["#ff6b6b,#c7000b", "#6366f1,#312e81", "#0ea5e9,#075985", "#10b981,#065f46", "#f59e0b,#92400e", "#ec4899,#831843"];

  const state = { scene: "开学季", platform: "小红书", force: "auto", live: false, result: null, plain: false, busy: false };

  /* ---------- 初始化控件 ---------- */
  function radio(container, items, current, render, onPick) {
    container.innerHTML = items.map(render).join("");
    container.querySelectorAll("[role=radio]").forEach((el) => {
      el.addEventListener("click", () => { onPick(el.dataset.v); sync(); });
      el.addEventListener("keydown", (e) => {
        if (!["ArrowRight", "ArrowLeft", "ArrowDown", "ArrowUp"].includes(e.key)) return;
        e.preventDefault();
        const all = [...container.querySelectorAll("[role=radio]")];
        const i = all.indexOf(el) + (e.key === "ArrowRight" || e.key === "ArrowDown" ? 1 : -1);
        const next = all[(i + all.length) % all.length];
        next.focus(); next.click();
      });
    });
    function sync() {
      container.querySelectorAll("[role=radio]").forEach((el) => {
        const on = el.dataset.v === current();
        el.setAttribute("aria-checked", on); el.tabIndex = on ? 0 : -1;
      });
    }
    sync();
    return sync;
  }

  const syncScene = radio($("sceneChips"), SCENES, () => state.scene,
    (s) => `<button type="button" role="radio" class="chip" data-v="${s}">${s}</button>`,
    (v) => (state.scene = v));
  const syncPlatform = radio($("platformCards"), PLATFORMS, () => state.platform,
    (p) => `<button type="button" role="radio" class="pf" data-v="${p.key}"><span class="pf-ico" style="--c:${p.color}">${p.ico}</span><b>${p.key}</b><small>${p.hint}</small></button>`,
    (v) => (state.platform = v));

  $("productPresets").innerHTML = ["MateBook 14", "MateBook X Pro", "想买轻薄本"]
    .map((p) => `<button type="button" data-p="${p}">${p}</button>`).join("");
  $("productPresets").addEventListener("click", (e) => {
    const b = e.target.closest("button"); if (!b) return;
    $("product").value = b.dataset.p; $("product").closest(".field").classList.remove("invalid");
  });

  $("caseBtns").innerHTML = CASES.map((c, i) => `<button type="button" data-i="${i}"><b>${c.tag}</b>${c.label}</button>`).join("");
  $("caseBtns").addEventListener("click", (e) => {
    const b = e.target.closest("button"); if (!b) return;
    const v = CASES[+b.dataset.i].v;
    $("product").value = v.product_query; $("audience").value = v.audience;
    $("goal").value = v.goal; $("extra").value = v.extra_requirements;
    state.scene = v.scene; state.platform = v.platform; syncScene(); syncPlatform();
    setForce("auto");
    submit();
  });

  function setForce(v) {
    state.force = v;
    $("forceSeg").querySelectorAll("button").forEach((b) => b.classList.toggle("on", b.dataset.v === v));
  }
  $("forceSeg").addEventListener("click", (e) => { const b = e.target.closest("button"); if (b) setForce(b.dataset.v); });

  renderPipeline(null);

  /* ---------- 后端探测 ---------- */
  fetch("/api/health").then((r) => (r.ok ? r.json() : Promise.reject()))
    .then((h) => {
      state.live = !!h.backend;
      $("kbChip").className = "kb-chip " + (state.live ? "ok" : "mock");
      $("kbText").textContent = state.live ? (h.kb_name || "知识库已连接") : "后端未就绪 · 使用模拟数据";
    })
    .catch(() => {
      $("kbChip").className = "kb-chip mock";
      $("kbText").textContent = "离线 · 使用模拟数据";
    })
    .finally(updateMode);

  function updateMode() {
    $("modeChip").textContent = state.live ? "LIVE" : "MOCK";
    $("modeChip").classList.toggle("live", state.live);
    $("demoBox").hidden = state.live;
    $("footNote").textContent = state.live
      ? "已连接真实后端 run_agent()，结果来自 ima 知识库检索与模型生成。"
      : "当前为模拟数据，仅用于展示页面结构，不代表真实检索结果。";
  }

  /* ---------- 提交 ---------- */
  $("taskForm").addEventListener("submit", (e) => { e.preventDefault(); submit(); });
  document.addEventListener("keydown", (e) => { if ((e.ctrlKey || e.metaKey) && e.key === "Enter") submit(); });

  function collect() {
    return {
      product_query: $("product").value.trim(),
      audience: $("audience").value.trim(),
      scene: state.scene,
      platform: state.platform,
      goal: $("goal").value.trim(),
      extra_requirements: $("extra").value.trim()
    };
  }

  async function submit() {
    if (state.busy) return;
    const input = collect();
    const field = $("product").closest(".field");
    if (!input.product_query) {
      field.classList.add("invalid"); $("product").focus();
      toast("请先填写产品型号或需求"); return;
    }
    field.classList.remove("invalid");

    state.busy = true;
    $("runBtn").classList.add("loading"); $("runBtn").disabled = true;
    $("runBtn").querySelector(".btn-text").textContent = "Agent 执行中…";
    $("emptyState").hidden = true; $("alertBox").hidden = true; $("results").hidden = true;
    $("statusBadge").hidden = true;

    const animation = animatePipeline();
    let result;
    try {
      result = state.live ? await callBackend(input) : await fakeDelay(window.MOCK.run(input, state.force));
    } catch (err) {
      result = { status: "error", scenario: {}, evidence: { facts: [], media: [] }, content: {}, checks: [], questions: [], conflicts: [],
        error: { code: "NETWORK", message: err.message || "请求失败", retry: "检查后端服务是否启动后重试。" }, trace: null };
    }
    await animation.stop();

    state.result = normalize(result);
    render(state.result);
    state.busy = false;
    $("runBtn").classList.remove("loading"); $("runBtn").disabled = false;
    $("runBtn").querySelector(".btn-text").textContent = "重新生成";
  }

  async function callBackend(input) {
    const ctrl = new AbortController();
    const t = setTimeout(() => ctrl.abort(), 180000);
    try {
      const r = await fetch("/api/run", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(input), signal: ctrl.signal });
      const data = await r.json().catch(() => null);
      if (!data) throw new Error(`后端返回 ${r.status}`);
      return data;
    } catch (e) {
      if (e.name === "AbortError") throw new Error("请求超时（180 秒）");
      throw e;
    } finally { clearTimeout(t); }
  }

  const fakeDelay = (v) => new Promise((res) => setTimeout(() => res(v), 1900));

  /* ---------- 兼容旧接口（team-plan 2.2 格式） ---------- */
  function normalize(r) {
    r = r || {};
    const out = { ...r };
    out.status = r.status || (r.checks && r.checks.missing_information && r.checks.missing_information.length ? "needs_input" : "success");
    out.scenario = r.scenario || {};
    if (Array.isArray(r.evidence)) {
      out.evidence = {
        facts: r.evidence.map((e) => ({ claim: e.fact, source: e.source, topic: "事实" })),
        media: r.evidence.filter((e) => e.media).map((e) => ({ name: e.media, url: /^https?:/.test(e.media) ? e.media : "", source: e.source, status: "pending_confirmation", position: "" }))
      };
    } else out.evidence = { facts: (r.evidence && r.evidence.facts) || [], media: (r.evidence && r.evidence.media) || [] };
    out.content = r.content || {};
    if (r.checks && !Array.isArray(r.checks)) {
      const c = r.checks;
      out.checks = [
        ...(c.facts || []).map((t) => ({ label: "事实核验", result: "pass", reason: t })),
        ...(c.risks || []).map((t) => ({ label: "合规风险", result: "warning", reason: t })),
        ...(c.missing_information || []).map((t) => ({ label: "待补充", result: "unknown", reason: t }))
      ];
      out.questions = r.questions || c.missing_information || [];
    } else out.checks = r.checks || [];
    out.questions = out.questions || r.questions || [];
    out.conflicts = r.conflicts || [];
    return out;
  }

  /* ---------- 流程动画 ---------- */
  function renderPipeline(trace) {
    const map = {};
    (trace || []).forEach((t) => (map[t.step] = t));
    $("pipeline").innerHTML = STEPS.map(([k, name, ico]) => {
      const t = map[k]; const st = t ? t.status : "";
      const icon = st === "done" ? "✓" : st === "failed" ? "✕" : st === "paused" ? "‖" : ico;
      return `<li class="${st}" title="${esc(t && t.detail ? t.detail : name)}"><div class="node">${icon}</div>${name}</li>`;
    }).join("");
  }

  function animatePipeline() {
    let i = 0, stopped = false;
    const tick = () => {
      if (stopped) return;
      renderPipeline(STEPS.map(([k], j) => ({ step: k, status: j < i ? "done" : j === i ? "active" : "" })));
      if (i < STEPS.length - 1) i++;
    };
    tick();
    const h = setInterval(tick, state.live ? 1400 : 210);
    return { stop: () => new Promise((res) => { stopped = true; clearInterval(h); setTimeout(res, 120); }) };
  }

  /* ---------- 渲染 ---------- */
  function render(r) {
    const trace = r.trace || STEPS.map(([k]) => ({ step: k, status: r.status === "error" ? "skipped" : "done" }));
    renderPipeline(trace);
    const badge = $("statusBadge");
    badge.hidden = false; badge.className = "status-badge st-" + r.status;
    badge.textContent = STATUS_TEXT[r.status] || r.status;

    renderAlert(r);
    $("results").hidden = r.status === "error" && !r.evidence.facts.length;
    renderScene(r.scenario);
    renderEvidence(r.evidence);
    renderContent(r);
    renderChecks(r.checks);
    $("cardContent").scrollIntoView({ behavior: "smooth", block: "nearest" });
  }

  function renderAlert(r) {
    const box = $("alertBox");
    let html = "";
    if (r.status === "needs_input") {
      html = `<h3>◐ 信息不足，Agent 已暂停生成</h3><p>为避免编造型号、价格或参数，请先补充以下信息，补充后可直接重新生成。</p>
        <ol>${r.questions.map((q) => `<li>${esc(q)}</li>`).join("")}</ol>
        <button class="q-btn" type="button" id="focusExtra">去补充信息 →</button>`;
    } else if (r.status === "partial") {
      html = `<h3>◑ 已生成草稿，但仍有缺口</h3><p>以下问题解决前，复制按钮默认锁定；确认内容可发布后可手动解锁。</p>
        <ul>${r.questions.map((q) => `<li>${esc(q)}</li>`).join("")}</ul>
        <button class="q-btn" type="button" id="unlockCopy">我已确认，解锁复制</button>`;
    } else if (r.status === "conflict") {
      html = `<h3>⚠ 资料冲突，已停止输出</h3><p>知识库中存在相互矛盾的资料，需要人工确认以哪份为准。</p>
        ${r.conflicts.map((c) => `<div class="conflict-grid">
          <div class="conflict-side"><small>${esc(c.field)}</small><b>${esc(c.a && c.a.value)}</b><small>${esc(c.a && c.a.source)}</small></div>
          <span class="vs">VS</span>
          <div class="conflict-side"><small>${esc(c.field)}</small><b>${esc(c.b && c.b.value)}</b><small>${esc(c.b && c.b.source)}</small></div></div>`).join("")}
        ${r.questions.length ? `<ul style="margin-top:10px">${r.questions.map((q) => `<li>${esc(q)}</li>`).join("")}</ul>` : ""}`;
    } else if (r.status === "error") {
      const e = r.error || {};
      html = `<h3>✕ 执行失败</h3><p>${esc(e.message || "未知错误")} <code>${esc(e.code || "UNKNOWN")}</code></p>
        ${e.retry ? `<p>${esc(e.retry)}</p>` : ""}<button class="q-btn" type="button" id="retryBtn">重试</button>`;
    }
    box.className = "alert " + r.status;
    box.innerHTML = html; box.hidden = !html;
    const fe = $("focusExtra"); if (fe) fe.onclick = () => { ($("product").value.match(/\d/) ? $("extra") : $("product")).focus(); };
    const uc = $("unlockCopy"); if (uc) uc.onclick = () => { $("copyBtn").disabled = false; uc.disabled = true; uc.textContent = "已解锁"; toast("复制已解锁，请确认后再发布"); };
    const rb = $("retryBtn"); if (rb) rb.onclick = submit;
  }

  function renderScene(s) {
    const items = [
      ["目标人群", s.audience], ["业务场景", s.scene || s.name], ["发布平台", s.platform], ["购买阶段", s.stage],
      ["用户问题", s.problem, true], ["内容目标", s.goal, true], ["内容策略", s.strategy, true], ["平台结构", s.structure, true]
    ].filter((x) => x[1]);
    $("sceneGrid").innerHTML = items.map(([k, v, full]) => `<div class="scene-item${full ? " full" : ""}"><span>${k}</span><b>${esc(v)}</b></div>`).join("")
      || `<div class="empty-mini">暂无场景信息</div>`;
  }

  function renderEvidence(ev) {
    const facts = ev.facts || [], media = ev.media || [];
    $("evCount").textContent = `${facts.length} 条事实 · ${media.length} 张图片`;
    $("factList").innerHTML = facts.length
      ? facts.map((f) => `<li class="fact"><span class="fact-tag">${esc(f.topic || "事实")}</span><div><p>${esc(f.claim)}</p><small>来源：${esc(f.source || "未标注")}${f.model ? " · 型号：" + esc(f.model) : ""}</small></div></li>`).join("")
      : `<li class="empty-mini">尚未检索到可用事实</li>`;
    $("mediaStrip").innerHTML = media.map((m, i) => `
      <div class="media ${esc(m.status || "pending_confirmation")}" title="${esc(m.caption || m.name)}">
        <span class="pill">${MEDIA_TEXT[m.status] || "待确认"}</span>
        <div class="thumb" style="background:${grad(i)}">${m.url ? `<img src="${esc(m.url)}" alt="${esc(m.name)}" style="width:100%;height:100%;object-fit:cover">` : laptop()}</div>
        <div class="meta"><b>${esc(m.name)}</b><small>${esc(m.position || m.role || "")}${m.model ? " · " + esc(m.model) : ""}</small></div>
      </div>`).join("");
  }

  const grad = (i) => `linear-gradient(135deg, ${GRADS[i % GRADS.length].split(",")[0]}, ${GRADS[i % GRADS.length].split(",")[1]})`;
  const laptop = () => `<svg viewBox="0 0 64 44" fill="none" stroke="rgba(255,255,255,.95)" stroke-width="2.2" stroke-linejoin="round"><rect x="10" y="4" width="44" height="28" rx="3"/><path d="M4 38h56l-4 4H8z"/></svg>`;
  function slot(m, i, cls) {
    if (!m) return "";
    const inner = m.url ? `<img src="${esc(m.url)}" alt="${esc(m.name)}" style="position:absolute;inset:0;width:100%;height:100%;object-fit:cover">` : laptop();
    return `<div class="img-slot ${cls || ""}" style="background:${grad(i)}" title="${esc(m.caption || "")}">${inner}
      <span class="pos">${esc(m.position || "")}</span><span class="cap">${esc(m.name)}</span></div>`;
  }

  function renderContent(r) {
    const c = r.content || {};
    const usable = (r.evidence.media || []).filter((m) => m.status === "usable");
    const hasContent = !!(c.title || c.body || (c.sections && c.sections.length));
    const stage = $("previewStage");
    const p = r.scenario.platform || state.platform;

    if (!hasContent) {
      stage.innerHTML = `<div class="blank-content"><b>文案暂未生成</b>${r.status === "error" ? "请处理错误后重试" : "请先处理上方提示，避免输出无依据内容"}</div>`;
    } else if (p === "公众号") stage.innerHTML = wx(c, usable);
    else if (p === "小红书") stage.innerHTML = xhs(c, usable);
    else if (p === "门店朋友圈") stage.innerHTML = pyq(c, usable);
    else if (p === "门店海报") stage.innerHTML = poster(c, usable);
    else stage.innerHTML = wx(c, usable);

    $("plainView").textContent = hasContent ? toPlain(c, p, usable) : "";
    const copyOk = hasContent && r.status === "success";
    $("copyBtn").disabled = !copyOk;
    $("copyBtn").classList.remove("copied");
    $("copyBtn").title = copyOk ? "复制纯文本文案" : "当前状态不允许直接复制";
    setView(state.plain && hasContent);
    $("toggleView").disabled = !hasContent;
  }

  function wx(c, m) {
    const secs = c.sections && c.sections.length ? c.sections : (c.body ? c.body.split(/\n{2,}/).map((t) => ({ text: t })) : []);
    let html = `<div class="wx-article"><h1>${esc(c.title)}</h1><div class="wx-meta"><a>华为终端门店</a>演示预览</div>`;
    if (c.lead) html += `<div class="wx-lead">${esc(c.lead)}</div>`;
    html += slot(m[0], 0);
    secs.forEach((s, i) => {
      if (s.heading) html += `<h3>${esc(s.heading)}</h3>`;
      html += `<p>${esc(s.text)}</p>`;
      if (m[i + 1] && i < 2) html += slot(m[i + 1], i + 1);
    });
    if (c.cta) html += `<div class="wx-cta">${esc(c.cta)}</div>`;
    return html + `</div>`;
  }

  const phone = (inner) => `<div class="phone"><div class="phone-screen"><div class="phone-bar"><span>9:41</span><span>●●● 5G</span></div><div class="phone-body">${inner}</div></div></div>`;

  function xhs(c, m) {
    const paras = (c.body || "").split(/\n{2,}/).map((t) => `<p>${esc(t)}</p>`).join("");
    return phone(`
      <div class="xhs-cover">${slot(m[0], 0)}<div class="xhs-dots">${m.map(() => "<i></i>").join("")}</div></div>
      <div class="xhs-thumbs">${m.slice(1).map((x, i) => slot(x, i + 1)).join("")}</div>
      <div class="xhs-content"><h2>${esc(c.title)}</h2>${paras}
        <div class="xhs-tags">${(c.tags || []).map((t) => `<span>${esc(t)}</span>`).join("")}</div>
        ${c.cta ? `<div class="xhs-cta">${esc(c.cta)}</div>` : ""}</div>`);
  }

  function pyq(c, m) {
    return phone(`<div class="pyq"><div class="pyq-avatar">门店</div><div>
      <div class="pyq-name">华为门店 · 导购</div>
      <p class="pyq-text">${esc([c.title, c.body, c.cta].filter(Boolean).join("\n"))}</p>
      <div class="pyq-imgs">${m.map((x, i) => slot(x, i)).join("")}</div>
      ${(c.selling_points || []).map((s) => `<span class="pyq-point">核心卖点 · ${esc(s)}</span>`).join("")}
      <div class="pyq-foot"><span>刚刚</span><span>••</span></div></div></div>`);
  }

  function poster(c, m) {
    return `<div class="poster-wrap"><div class="poster">
      <div class="poster-brand">HUAWEI · MateBook</div>
      <h1>${esc(c.title)}</h1>${c.subtitle ? `<h2>${esc(c.subtitle)}</h2>` : ""}
      ${slot(m[0], 0)}
      <ul>${(c.selling_points || []).slice(0, 3).map((s) => `<li>${esc(s)}</li>`).join("")}</ul>
      <div class="poster-act">${c.activity ? esc(c.activity) : "活动说明：知识库暂无活动依据，留空待补充"}</div>
    </div><div class="poster-note">文案与主视觉建议预览，非最终排版成品</div></div>`;
  }

  function toPlain(c, p, m) {
    const L = [];
    if (c.title) L.push(c.title);
    if (c.subtitle) L.push(c.subtitle);
    if (c.lead) L.push("", c.lead);
    if (c.sections && c.sections.length) c.sections.forEach((s) => L.push("", s.heading || "", s.text));
    else if (c.body) L.push("", c.body);
    if (c.selling_points && c.selling_points.length && p === "门店海报") L.push("", ...c.selling_points.map((s) => "· " + s));
    if (c.activity) L.push("", "活动：" + c.activity);
    if (c.cta) L.push("", c.cta);
    if (c.tags && c.tags.length) L.push("", c.tags.join(" "));
    if (m.length) {
      L.push("", "—— 配图方案 ——");
      m.forEach((x, i) => L.push(`${i + 1}. [${x.position || "未指定"}] ${x.name}｜来源：${x.source || "未标注"}${x.caption ? "｜" + x.caption : ""}`));
    }
    return L.join("\n").replace(/\n{3,}/g, "\n\n").trim();
  }

  function setView(plain) {
    state.plain = plain;
    $("plainView").hidden = !plain; $("previewStage").hidden = plain;
    $("toggleView").textContent = plain ? "平台预览" : "纯文本";
  }
  $("toggleView").addEventListener("click", () => setView(!state.plain));

  $("copyBtn").addEventListener("click", async () => {
    const text = $("plainView").textContent;
    try {
      await navigator.clipboard.writeText(text);
    } catch (_) {
      const ta = document.createElement("textarea"); ta.value = text; document.body.appendChild(ta);
      ta.select(); document.execCommand("copy"); ta.remove();
    }
    const b = $("copyBtn"); b.classList.add("copied"); b.querySelector("span").textContent = "已复制";
    toast(`已复制 ${text.length} 字（含配图方案）`);
    setTimeout(() => { b.classList.remove("copied"); b.querySelector("span").textContent = "复制文案"; }, 1800);
  });

  function renderChecks(list) {
    const count = { pass: 0, warning: 0, fail: 0, unknown: 0 };
    list.forEach((c) => (count[c.result] = (count[c.result] || 0) + 1));
    $("checkSummary").innerHTML = Object.entries(count).filter(([, n]) => n)
      .map(([k, n]) => `<span class="st-${k === "pass" ? "success" : k === "warning" ? "partial" : k === "fail" ? "error" : "needs_input"}">${RESULT_TEXT[k]} ${n}</span>`).join("");
    $("checkList").innerHTML = list.length
      ? list.map((c) => `<div class="check r-${esc(c.result)}"><span class="ico" aria-label="${RESULT_TEXT[c.result] || ""}">${RESULT_ICO[c.result] || "?"}</span>
          <div><b>${esc(c.label || c.item)}</b><p>${esc(c.reason)}</p>${c.blocking ? `<span class="block-tag">阻断输出</span>` : ""}</div></div>`).join("")
      : `<div class="empty-mini">暂无核验结果</div>`;
  }

  let toastTimer;
  function toast(msg) {
    const t = $("toast"); t.textContent = msg; t.classList.add("show");
    clearTimeout(toastTimer); toastTimer = setTimeout(() => t.classList.remove("show"), 2200);
  }
})();
