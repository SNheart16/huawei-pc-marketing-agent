"use strict";

// Offline browser contract checks. All responses below are synthetic fixtures.
const { test } = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");

const script = fs.readFileSync(path.join(__dirname, "..", "ui", "app.js"), "utf8");
const model = "HUAWEI MateBook X Pro 酷睿 Ultra 微绒典藏版";

function fixture(status = "success") {
  return {
    schema_version: "1.0", status, status_message: "离线测试状态说明",
    knowledge_source: { mode: "local", name: "测试知识库", live: false, status: "ok", message: "离线测试来源" },
    scenario: { product_query: model, product_model: model, audience: "大学新生", scene: "开学季", platform: "小红书", goal: "测试目标", purchase_stage: null, user_problems: ["测试问题"], strategy: "测试策略" },
    evidence: [{ evidence_id: "E1", product_model: model, fact: "用于测试的事实", source_title: "测试资料", source_ref: "产品/测试.md", media_ids: [] }],
    content: ["success", "partial"].includes(status) ? { title: "测试标题", subtitle: null, lead: null, body: "展示正文", selling_points: [], cta: "测试行动", tags: ["测试标签"], activity_note: null, images: [], plain_text: "后端原始 plain_text\n保留格式与内容。" } : null,
    checks: { facts: [{ claim: "用于测试的事实", status: "pass", evidence_ids: ["E1"], note: "测试核验" }], images: [], compliance: [{ type: "真实性", status: "pass", note: "测试通过" }], risks: status === "conflict" ? ["测试型号存在冲突"] : [], missing_information: status === "partial" ? ["图片不足，请补充确认"] : [], questions: status === "needs_input" ? ["请补充完整产品型号？"] : [] }
  };
}

function browser(response, options = {}) {
  const nodes = new Map();
  const calls = [];
  const copies = [];
  let serial = 0;
  function element(id) {
    if (nodes.has(id)) return nodes.get(id);
    const classes = new Set();
    const events = new Map();
    const node = {
      id, value: "", textContent: "", innerHTML: "", hidden: false, disabled: false, dataset: {},
      className: "", title: "", tabIndex: 0,
      classList: {
        add(...items) { items.forEach((v) => classes.add(v)); },
        remove(...items) { items.forEach((v) => classes.delete(v)); },
        contains(v) { return classes.has(v); },
        toggle(v, force) { const on = force === undefined ? !classes.has(v) : force; if (on) classes.add(v); else classes.delete(v); return on; }
      },
      addEventListener(name, fn) { events.set(name, fn); },
      async dispatch(name) { const fn = events.get(name); if (fn) await fn({ preventDefault() {}, target: node }); },
      querySelector(selector) { return element(id + ":" + selector); },
      querySelectorAll() { return []; }, closest() { return element(id + ":field"); },
      setAttribute() {}, scrollIntoView() {}, focus() {}, select() {}, remove() {}, appendChild() {}
    };
    nodes.set(id, node);
    return node;
  }
  const document = {
    getElementById: element, addEventListener() {},
    createElement() { return element("created:" + (++serial)); }, body: { appendChild() {} }, execCommand() {}
  };
  const context = vm.createContext({
    document, window: { MOCK: new Proxy({}, { get() { throw new Error("Mock generation must never be used"); } }) },
    navigator: { clipboard: { async writeText(text) { copies.push(text); } } },
    AbortController, URL, console,
    fetch: async (url, init) => {
      calls.push({ url, init });
      if (url === "/api/health") return { ok: true, json: async () => ({ backend: options.backendReady !== false }) };
      if (url !== "/api/run") throw new Error("Unexpected request");
      if (options.networkFailure) throw new Error("Network fixture failure");
      return { ok: true, status: 200, json: async () => structuredClone(response) };
    },
    setTimeout(fn, ms) { if (ms <= 120) queueMicrotask(fn); return ++serial; },
    clearTimeout() {}, setInterval() { return ++serial; }, clearInterval() {}
  });
  vm.runInContext(script, context, { filename: "ui/app.js" });
  element("product").value = model;
  element("audience").value = "大学新生";
  element("goal").value = "测试目标";
  element("extra").value = "表达克制";
  return {
    element, calls, copies,
    rendered() { return [...nodes.values()].map((n) => n.innerHTML + n.textContent).join("\n"); },
    async submit() {
      await element("taskForm").dispatch("submit");
      for (let i = 0; i < 40 && element("runBtn").disabled; i++) await new Promise(setImmediate);
      assert.equal(element("runBtn").disabled, false, "The form must finish rendering");
    }
  };
}

for (const [status, label] of Object.entries({ success: "生成完成", partial: "部分完成", needs_input: "需要补充信息", conflict: "资料冲突", error: "执行失败" })) {
  test(`JSON v1.0 ${status} renders through the form without a crash`, async () => {
    const page = browser(fixture(status));
    await page.submit();
    assert.equal(page.element("statusBadge").textContent, label);
    assert.equal(page.element("results").hidden, false);
    assert.equal(page.element("copyBtn").disabled, !["success", "partial"].includes(status));
    if (status === "needs_input") assert.match(page.element("alertBox").innerHTML, /请补充完整产品型号/);
    if (status === "conflict") assert.match(page.element("alertBox").innerHTML, /冲突/);
    if (["success", "partial"].includes(status)) assert.match(page.rendered(), /测试知识库/);
  });
}

test("partial copies the exact backend plain_text without an unlock step", async () => {
  const result = fixture("partial");
  const page = browser(result);
  await page.submit();
  assert.equal(page.element("copyBtn").disabled, false);
  assert.equal(page.element("plainView").textContent, result.content.plain_text);
  await page.element("copyBtn").dispatch("click");
  assert.deepEqual(page.copies, [result.content.plain_text]);
  assert.doesNotMatch(page.element("alertBox").innerHTML, /默认锁定|unlockCopy/);
});

test("content=null displays no final content and disables copying", async () => {
  const result = fixture("partial"); result.content = null;
  const page = browser(result);
  await page.submit();
  assert.equal(page.element("copyBtn").disabled, true);
  assert.equal(page.element("plainView").textContent, "");
  assert.match(page.element("previewStage").innerHTML, /文案暂未生成/);
});

test("unknown image with url=null is pending and renders no img or invented URL", async () => {
  const result = fixture("partial");
  result.content.images = [{ image_id: "M1", name: "待核实图片", url: null, source_title: "测试图片来源", source_ref: "图片/待核实.png", product_model: null, caption: "等待确认", suggested_position: "正文后", status: "unknown", evidence_ids: [] }];
  const page = browser(result);
  await page.submit();
  assert.match(page.element("mediaStrip").innerHTML, /待确认/);
  assert.match(page.element("mediaStrip").innerHTML, /待核实图片/);
  assert.doesNotMatch(page.element("mediaStrip").innerHTML, /<img\b|src=|https?:/);
  assert.match(page.element("evCount").textContent, /1/);
});

test("fact and compliance failures remain failures", async () => {
  const result = fixture("partial");
  result.checks.facts[0].status = "fail";
  result.checks.compliance[0].status = "fail";
  const page = browser(result);
  await page.submit();
  assert.match(page.element("checkSummary").innerHTML, /失败 2/);
  assert.match(page.element("checkList").innerHTML, /r-fail/);
  assert.doesNotMatch(page.element("checkList").innerHTML, /r-pass/);
});

test("backend unavailable does not invoke mock generation", async () => {
  const page = browser(fixture("error"), { backendReady: false, networkFailure: true });
  await page.submit();
  assert.equal(page.element("statusBadge").textContent, "执行失败");
  assert.equal(page.calls.filter((v) => v.url === "/api/run").length, 1);
  assert.equal(page.element("copyBtn").disabled, true);
  assert.doesNotMatch(page.rendered(), /开发用模拟数据|MOCK.run|Network fixture failure/);
});

test("submit sends exactly the six input contract fields", async () => {
  const page = browser(fixture());
  await page.submit();
  const call = page.calls.find((v) => v.url === "/api/run");
  assert.equal(call.init.method, "POST");
  assert.deepEqual(JSON.parse(call.init.body), { product_query: model, audience: "大学新生", scene: "开学季", platform: "小红书", goal: "测试目标", extra_requirements: "表达克制" });
});

test("empty product reaches the real backend needs_input handler", async () => {
  const page = browser(fixture("needs_input"));
  page.element("product").value = "";
  await page.submit();
  const call = page.calls.find((v) => v.url === "/api/run");
  assert.equal(JSON.parse(call.init.body).product_query, "");
  assert.equal(page.element("statusBadge").textContent, "需要补充信息");
});
