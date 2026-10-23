"use strict";
const { test } = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");
const KEY = "huawei-marketing-prototype-v1";

// Exercise the real event handlers without network/model access. Browser QA covers layout.
function browser(saved, date = "2026-10-21T12:00:00", fetchImpl) {
  const nodes = new Map(), handlers = {}, copies = [];
  let stored = saved ? JSON.stringify(saved) : null;
  function node(selector) {
    if (!nodes.has(selector)) nodes.set(selector, {
      value: "", textContent: "", innerHTML: "", hidden: false, disabled: false,
      classList: { add() {}, remove() {}, toggle() {} },
      setAttribute() {}, removeAttribute() {}, focus() {}, addEventListener(type, fn) { this[type] = fn; }
    });
    return nodes.get(selector);
  }
  const location = { hash: "" };
  const windowHandlers = {};
  const window = { scrollTo() {}, addEventListener(type, fn) { windowHandlers[type] = fn; }, confirm: () => true };
  const entries = [], nativeHistory = { index: -1,
    replaceState(state, _, hash) { if (this.index < 0) this.index = 0; entries[this.index] = { state: structuredClone(state), hash }; location.hash = hash; },
    pushState(state, _, hash) { entries.splice(++this.index); entries.push({ state: structuredClone(state), hash }); location.hash = hash; },
    back() { if (this.index > 0) { const entry = entries[--this.index]; location.hash = entry.hash; windowHandlers.popstate?.({ state: structuredClone(entry.state) }); } },
    forward() { if (this.index + 1 < entries.length) { const entry = entries[++this.index]; location.hash = entry.hash; windowHandlers.popstate?.({ state: structuredClone(entry.state) }); } }
  };
  const context = vm.createContext({
    Date: class extends Date { constructor(...args) { super(...(args.length ? args : [date])); } static now() { return new Date(date).getTime(); } },
    window, location, document: { querySelector: node, querySelectorAll: () => [], addEventListener(type, fn) { handlers[type] = fn; } },
    fetch: fetchImpl,
    localStorage: { getItem: () => stored, setItem(key, value) { assert.equal(key, KEY); stored = value; } },
    history: nativeHistory,
    FormData: class { constructor(target) { this.values = target.values; } get(k) { return this.values[k]; } getAll(k) { const v = this.values[k]; return Array.isArray(v) ? v : v === undefined ? [] : [v]; } },
    navigator: { clipboard: { async writeText(text) { copies.push(text); } } },
    setTimeout(fn, ms) { if (ms <= 550) return setImmediate(fn); return 1; }, clearTimeout() {}, console
  });
  for (const file of ["prototype-data.js", "guidance.js", "prototype.js"]) vm.runInContext(fs.readFileSync(path.join(__dirname, "../ui", file), "utf8"), context);
  return {
    window, node, copies, nativeHistory,
    state: () => JSON.parse(stored),
    async click(action, id) { await handlers.click({ target: { closest(selector) { return selector === "[data-action]" ? { dataset: { action, id } } : null; } } }); },
    async clickPage(page) { await handlers.click({ target: { closest(selector) { return selector === "[data-page]" ? { dataset: { page } } : null; } } }); },
    async start() { await node("#mc-continue").click(); },
    input(id, value, field) { const el = node("#" + id); el.id = id; el.value = value; el.dataset = field ? { field } : {}; handlers.input({ target: el }); },
    async submit(id, values = {}) { await handlers.submit({ target: { id, values }, preventDefault() {} }); },
    async say(text) { this.input("guide-input", text); await this.submit("guide-compose"); },
    async complete(task = "seeding") {
      const goals = { seeding: "建立产品认知", launch: "介绍新品", store: "吸引到店", season: "开学节点" };
      this.input("mc-prompt", `面向经常出差的顾客，介绍MateBook 14，${goals[task]}，用朋友圈，简短，不提价格`);
      await this.start();
      assert.equal(this.state().page, "guide");
      assert.equal(this.state().draft.task, task);
      await this.click("guide-strategies");
      await this.click("decide"); await this.click("generate");
      assert.equal(this.state().page, "results");
    }
  };
}

test("opportunity helpers filter finite sample schedules and derive honest statuses", () => {
  const b = browser();
  const model = b.window.MarketingPrototypeModel;
  const sample = [
    { id: "before", displayStart: "2026-10-01", windowStart: "2026-10-25", validUntil: "2026-11-01", preparationDays: 7, verification: "ready", relevance: "high", storeFit: true, actionable: true },
    { id: "current", displayStart: "2026-10-01", windowStart: "2026-10-20", validUntil: "2026-11-01", preparationDays: 3, verification: "ready", relevance: "high", storeFit: true, actionable: true },
    { id: "pending", displayStart: "2026-10-01", windowStart: "2026-10-20", validUntil: "2026-11-01", preparationDays: 3, verification: "pending", relevance: "high", storeFit: true, actionable: true },
    { id: "expired", displayStart: "2026-09-01", windowStart: "2026-09-10", validUntil: "2026-10-01", preparationDays: 3, verification: "ready", relevance: "high", storeFit: true, actionable: true }
  ];
  const items = model.eligibleOpportunities(sample, new Date("2026-10-21T12:00:00"));
  assert.deepEqual(items.map(item => item.id), ["current", "before", "pending"]);
  assert.equal(items[0].status, "近期值得关注");
  assert.equal(items[1].status, "建议提前准备");
  assert.equal(items[2].status, "部分信息待确认");
  assert.equal(model.opportunityState(sample[3], new Date("2026-10-21T12:00:00")), null);
});

test("display start, preparation window, validity end and invalid dates have explicit boundaries", () => {
  const model = browser().window.MarketingPrototypeModel;
  const sample = { id: "schedule", displayStart: "2026-10-10", windowStart: "2026-10-25", validUntil: "2026-10-31", preparationDays: 7, verification: "ready", actionable: true };
  assert.equal(model.opportunityState(sample, "2026-10-09"), null);
  assert.equal(model.opportunityState(sample, "2026-10-10").phase, "ahead");
  assert.equal(model.opportunityState(sample, "2026-10-18").phase, "preparing");
  assert.equal(model.opportunityState(sample, "2026-10-25").status, "近期值得关注");
  assert.ok(model.opportunityState(sample, "2026-10-31"));
  assert.equal(model.opportunityState(sample, "2026-11-01"), null);
  assert.equal(model.opportunityState({ ...sample, validUntil: "2026-02-30" }, "2026-10-21"), null);
  assert.equal(model.opportunityState({ ...sample, actionable: false }, "2026-10-21"), null);
});

test("recommendations do not repeat until every eligible direction has been seen and survive reload", async () => {
  const b = browser(), seen = [b.state().recommendation.id];
  for (let i = 0; i < 3; i++) { await b.click("next-opportunity"); seen.push(b.state().recommendation.id); }
  assert.equal(new Set(seen).size, 4);
  const restored = browser(b.state());
  assert.equal(restored.state().recommendation.id, seen[3]);
  await restored.click("next-opportunity");
  assert.notEqual(restored.state().recommendation.id, seen[3]);
  const tomorrow = browser(restored.state(), "2026-10-22T12:00:00");
  assert.notEqual(tomorrow.state().recommendation.day, restored.state().recommendation.day);
  assert.equal(tomorrow.state().recommendation.seen.length, 1);
});

test("homepage recommendation prioritizes a near date node and keeps the same candidate stable by day", () => {
  const model = browser().window.MarketingPrototypeModel;
  const sample = [
    { id: "product", type: "产品探索", displayStart: "2026-10-01", windowStart: "2026-10-20", validUntil: "2026-11-20", preparationDays: 3, verification: "ready", relevance: "high", storeFit: true, actionable: true },
    { id: "date", type: "时间节点", displayStart: "2026-10-01", windowStart: "2026-11-05", validUntil: "2026-11-25", preparationDays: 7, verification: "ready", relevance: "high", storeFit: true, actionable: true },
    { id: "scene", type: "门店场景", displayStart: "2026-10-01", windowStart: "2026-10-20", validUntil: "2026-11-20", preparationDays: 3, verification: "pending", relevance: "low", storeFit: false, actionable: true }
  ];
  const first = model.eligibleOpportunities(sample, new Date("2026-10-21T12:00:00"));
  assert.equal(first[0].id, "date");
  assert.equal(model.dailyOpportunity(first, new Date("2026-10-21T12:00:00")).id, "date");
  assert.equal(model.dailyOpportunity(first, new Date("2026-10-22T12:00:00")).id, "date");
});

test("one or no eligible opportunity stays honest at the model level", async () => {
  // 首页推荐区已移除（推荐内容保留在「推广机会」页），此处改为模型层校验。
  const only = browser(null, "2026-11-22T12:00:00");
  const model = only.window.MarketingPrototypeModel;
  const sample = [
    { id: "date", type: "时间节点", displayStart: "2026-10-01", windowStart: "2026-11-05", validUntil: "2026-11-25", preparationDays: 7, verification: "ready", relevance: "high", storeFit: true, actionable: true }
  ];
  assert.equal(model.eligibleOpportunities(sample, new Date("2026-11-22T12:00:00")).length, 1);
  assert.equal(model.eligibleOpportunities(sample, new Date("2026-12-01T12:00:00")).length, 0);
});


for (const [task, heading] of Object.entries({ seeding: "场景体验分享", launch: "新品信息介绍", store: "到店咨询邀请", season: "节点主题内容" })) {
  test(`${task}: guided flow retains context, creates a task-specific draft and record`, async () => {
    const b = browser(); await b.complete(task);
    assert.match(b.node("#mc-work-page").innerHTML, /图片预览/);
    const d = b.state().draft;
    assert.equal(d.task, task);
    assert.equal(d.outputContext.task.goal, d.goal);
    assert.ok(d.outputs["微信朋友圈"].strategy.coreIdea);
    assert.match(d.outputs["微信朋友圈"].body, /差旅/);
    assert.doesNotMatch(d.outputs["微信朋友圈"].body, /价格/);
    assert.equal(b.state().history.length, 1);
    await b.click("analysis"); await b.click("guide");
    assert.equal(b.state().draft.strategyId, d.strategyId);
    assert.equal(b.state().draft.prompt, d.prompt);
    assert.equal(b.state().guide.events[0].text, d.prompt);
  });
}

test("three different inputs take ready, candidate and exploratory paths; input stays exact", async () => {
  const cases = [
    ["  面向大学生介绍MateBook 14，吸引到店体验。\n先不写参数  ", "ready"],
    ["想吸引附近的大学生来店体验华为笔记本，但不知道该主推哪款。", "product"],
    ["最近门店宣传效果不好，不知道怎么做。", "direction"]
  ];
  for (const [text, stage] of cases) {
    const b = browser(); b.input("mc-prompt", text); await b.start();
    assert.equal(b.state().page, "guide");
    assert.equal(b.state().draft.prompt, text);
    assert.equal(b.state().guide.events[0].text, text);
    const G = b.window.MarketingGuidance, st = b.state();
    assert.equal(G.stage(G.resolve(st.guide, st.draft.opportunity)), stage);
  }
});

test("product recommendation, reranking and multiround conversation preserve known information", async () => {
  const b = browser(); b.input("mc-prompt", "吸引附近大学生到店，但不知道推广哪款"); await b.start();
  assert.match(b.node("#mc-work-page").innerHTML, /演示数据|模拟选题/);
  const G = b.window.MarketingGuidance;
  const first = G.candidates(G.resolve(b.state().guide), b.window.MarketingPrototypeData.products, 0)[0].id;
  await b.click("guide-candidates");
  const next = G.candidates(G.resolve(b.state().guide), b.window.MarketingPrototypeData.products, b.state().guide.candidateRound)[0].id;
  assert.notEqual(first, next);
  await b.click("guide-product", "matebook-14"); await b.say("用小红书发布");
  assert.equal(b.state().draft.product, "matebook-14"); assert.equal(b.state().draft.goal, "store");
  assert.equal(b.state().draft.audience, "附近大学生"); assert.deepEqual(b.state().draft.platforms, ["小红书"]);
  assert.equal(b.state().guide.events.length, 4);
  const restored = browser(b.state()); assert.equal(restored.state().guide.events.length, 4);
  assert.match(restored.node("#mc-work-page").innerHTML, /用小红书发布/);
});

test("different directions change subsequent prompts, summaries and actual strategies", async () => {
  const a = browser(), b = browser(); await a.start(); await b.start();
  await a.click("guide-direction", "store"); await b.click("guide-direction", "awareness");
  assert.notEqual(a.state().draft.task, b.state().draft.task);
  assert.match(a.node("#mc-work-page").innerHTML, /吸引顾客到店体验/);
  await a.click("guide-skip-product"); await b.click("guide-skip-product");
  await a.click("guide-strategies"); await b.click("guide-strategies");
  assert.notEqual(a.window.MarketingPrototypeModel.strategyOptions(a.state().draft)[0].claim, b.window.MarketingPrototypeModel.strategyOptions(b.state().draft)[0].claim);
});

test("multiple goals ask a priority; explicit or rule-based selection resolves it", async () => {
  const b = browser(); b.input("mc-prompt", "推广MateBook 14，建立产品认知并吸引到店"); await b.start();
  assert.match(b.node("#mc-work-page").innerHTML, /本次更优先的目标|这次先做哪一个目标/);
  await b.click("guide-goal", "awareness");
  assert.equal(b.state().draft.goal, "awareness");
  assert.equal(b.window.MarketingGuidance.stage(b.window.MarketingGuidance.resolve(b.state().guide)), "ready");
});

test("opportunity title, evidence and task pass through guide, strategies and saved results", async () => {
  const b = browser(); await b.click("opportunity", "date-refresh");
  assert.equal(b.state().page, "guide"); assert.equal(b.state().draft.task, "season");
  assert.match(b.node("#mc-work-page").innerHTML, /双 11 前后 · 预售与优惠/);
  await b.click("guide-goal", "needs"); await b.click("guide-focus", "checklist"); await b.click("guide-strategies"); await b.click("decide"); await b.click("generate");
  assert.equal(b.state().draft.outputContext.task.opportunity.title, "双 11 前后 · 预售与优惠");
  assert.equal(b.state().draft.product, ""); assert.doesNotMatch(b.state().draft.outputs["通用草稿"].body, /X Pro|MateBook 14/);
  assert.equal(b.state().history[0].draft.opportunity.id, "date-refresh");
});

test("opportunity explorer keeps calendar selection and date details in sync", async () => {
  const b = browser();
  await b.click("preview-opportunity", "date-refresh");
  assert.equal(b.state().page, "opportunities");
  assert.equal(b.state().opportunityExplorer.month, "2026-11");
  assert.equal(b.state().opportunityExplorer.selectedDate, "2026-11-05");
  assert.match(b.node("#mc-work-page").innerHTML, /双 11 前后 · 预售与优惠/);
  await b.click("opportunity-month", "prev");
  assert.equal(b.state().opportunityExplorer.month, "2026-10");
  assert.match(b.node("#mc-work-page").innerHTML, /这一天没有配置机会/);
  await b.click("opportunity-month", "next");
  await b.click("opportunity-date", "2026-11-05");
  assert.match(b.node("#mc-work-page").innerHTML, /data-action="opportunity"/);
  assert.match(b.node("#mc-work-page").innerHTML, /推荐主题/);
});

test("real-scenario explorer offers four scenario cards that seed a targeted guide draft", async () => {
  const b = browser();
  await b.click("preview-opportunity", "software-questions");
  assert.equal(b.state().page, "opportunities");
  const html = b.node("#mc-work-page").innerHTML;
  assert.equal((html.match(/mc-scenario-card/g) || []).length, 4);
  for (const s of ["dorm", "office", "travel", "home"]) assert.match(html, new RegExp(`data-action="opportunity-scenario" data-id="${s}"`));
  await b.click("opportunity-scenario", "travel");
  assert.equal(b.state().page, "guide");
  assert.equal(b.state().draft.opportunity.scenario.id, "travel");
  assert.match(b.node("#mc-work-page").innerHTML, /差旅/);
});

test("guide conversation renders as chat bubbles with a single agent identity tag", async () => {
  const b = browser(); b.input("mc-prompt", "给到店顾客介绍 MateBook 14"); await b.start();
  let html = b.node("#mc-work-page").innerHTML;
  assert.match(html, /class="mc-msg mc-msg-agent is-first"/);
  assert.match(html, /mc-msg-user/);
  assert.equal((html.match(/Agent · 规则模拟/g) || []).length, 1);
  assert.doesNotMatch(html, /class="mc-message/);
  await b.say("主要面向到店咨询的顾客");
  html = b.node("#mc-work-page").innerHTML;
  assert.equal((html.match(/Agent · 规则模拟/g) || []).length, 1);
  assert.ok((html.match(/mc-msg-user/g) || []).length >= 2);
  assert.match(html, /placeholder="说说你这次想怎么推广……"/);
});

test("summary panel layers confirmed, pending and optional needs; ready stage shows a summary card with a primary action", async () => {
  const b = browser(); await b.click("opportunity", "date-refresh");
  await b.click("guide-goal", "store"); await b.click("guide-focus", "experience");
  let html = b.node("#mc-work-page").innerHTML;
  assert.match(html, /mc-sum-group is-confirmed/);
  assert.match(html, /mc-sum-group is-pending/);
  await b.say("用小红书发布，内容简短一点，不提价格");
  html = b.node("#mc-work-page").innerHTML;
  assert.match(html, /mc-sum-group is-optional/);
  await b.click("guide-candidates"); await b.click("guide-skip-product");
  assert.equal(b.window.MarketingGuidance.stage(b.window.MarketingGuidance.resolve(b.state().guide, b.state().draft.opportunity)), "ready");
  html = b.node("#mc-work-page").innerHTML;
  assert.match(html, /这次内容想要什么语气/);
  assert.doesNotMatch(html, /mc-ready-card/);
  await b.click("guide-tone-default");
  html = b.node("#mc-work-page").innerHTML;
  assert.match(html, /mc-ready-card/);
  assert.match(html, /mc-ready-summary/);
  assert.match(html, /进入推广策略/);
  assert.match(html, /mc-sum-ready/);
  await b.click("guide-strategies"); assert.equal(b.state().page, "analysis");
});

test("content tone can be guided in conversation by free text or ready-card chips and travels to the draft", async () => {
  const b = browser(); b.input("mc-prompt", "给到店顾客介绍 MateBook 14"); await b.start();
  await b.say("语气简洁专业一点");
  assert.equal(b.state().draft.tone, "简洁专业");
  assert.equal(b.state().draft.fieldStatus.tone, "confirmed");
  let html = b.node("#mc-work-page").innerHTML;
  assert.match(html, /<small>内容语气<\/small><span>简洁专业<\/span>/);
  assert.match(html, /语气收到/);
  await b.click("guide-tone", "轻松亲切");
  assert.equal(b.state().draft.tone, "轻松亲切");
  html = b.node("#mc-work-page").innerHTML;
  assert.ok((html.match(/mc-tone-chip is-on/g) || []).length, 1);
  await b.say("恢复默认语气");
  assert.equal(b.state().draft.tone, "自然真诚");
});

test("opportunity explorer opens only the selected opportunity view", async () => {
  const b = browser();
  await b.click("opportunities");
  const initial = b.node("#mc-work-page").innerHTML;
  assert.equal((initial.match(/class="mc-opportunity-list-item mc-opportunity-card/g) || []).length, 3);
  assert.doesNotMatch(b.node("#mc-work-page").innerHTML, /id="mc-opportunity-(?:date-explorer|place-explorer)"/);
  assert.doesNotMatch(initial, /id="mc-opportunity-product-detail"/);
  await b.click("opportunity-focus-date", "date-refresh");
  assert.match(b.node("#mc-work-page").innerHTML, /id="mc-opportunity-date-explorer"/);
  assert.doesNotMatch(b.node("#mc-work-page").innerHTML, /id="mc-opportunity-place-explorer"/);
  await b.click("opportunity-collapse");
  assert.doesNotMatch(b.node("#mc-work-page").innerHTML, /id="mc-opportunity-(?:date-explorer|place-explorer|product-detail)"/);
  await b.click("opportunity-focus-place", "local");
  assert.match(b.node("#mc-work-page").innerHTML, /id="mc-opportunity-place-explorer"/);
  assert.doesNotMatch(b.node("#mc-work-page").innerHTML, /id="mc-opportunity-date-explorer"/);
  await b.click("opportunity-focus-opportunity", "software-questions");
  assert.match(b.node("#mc-work-page").innerHTML, /id="mc-opportunity-product-detail"/);
  assert.doesNotMatch(b.node("#mc-work-page").innerHTML, /id="mc-opportunity-(?:place-explorer|date-explorer)"/);
  await b.clickPage("opportunities");
  assert.doesNotMatch(b.node("#mc-work-page").innerHTML, /id="mc-opportunity-(?:product-detail|place-explorer|date-explorer)"/);
});

test("concept place filters select the visible marker and carry its demo context", async () => {
  const b = browser();
  await b.click("opportunity", "local");
  assert.equal(b.state().page, "guide");
  const explorer = browser();
  await explorer.click("preview-opportunity", "local");
  assert.equal(explorer.state().opportunityExplorer.mapFilter, "all");
  assert.equal(explorer.state().opportunityExplorer.selectedPlace, "place-shopping");
  await explorer.click("opportunity-map-filter", "school");
  assert.equal(explorer.state().opportunityExplorer.selectedPlace, "");
  assert.match(explorer.node("#mc-work-page").innerHTML, /浙江大学紫金港校区（西区）/);
  await explorer.click("opportunity-place", "place-school");
  assert.equal(explorer.state().opportunityExplorer.selectedPlace, "place-school");
  await explorer.click("opportunity", "local");
  assert.equal(explorer.state().draft.opportunity.place.id, "place-school");
  assert.match(explorer.state().draft.opportunity.scene, /概念地点/);
});

test("homepage recommendation rotates to an eligible shared opportunity and routes to its detail", async () => {
  const b = browser();
  const initial = b.state().recommendation.id;
  await b.click("next-opportunity");
  const next = b.state().recommendation.id;
  assert.notEqual(next, initial);
  await b.click("preview-opportunity", next);
  assert.equal(b.state().page, "opportunities");
  assert.equal(b.state().opportunityExplorer.selectedOpportunity, next === "software-questions" ? next : "");
  assert.match(b.node("#mc-work-page").innerHTML, new RegExp(next));
});

test("skip unknown fields and empty task still reach strategies without silent product selection", async () => {
  const b = browser(); await b.start(); await b.click("guide-strategies");
  assert.equal(b.state().page, "analysis"); assert.equal(b.state().draft.product, "");
  await b.click("decide"); await b.click("generate");
  assert.equal(b.state().page, "results"); assert.doesNotMatch(b.node("#mc-work-page").innerHTML, /undefined|NaN/);
  assert.match(b.node("#mc-work-page").innerHTML, /暂不指定型号/);
});

test("unknown input is preserved with honest fallback; blank send does not create fake messages", async () => {
  const b = browser(); await b.start(); const count = b.state().guide.events.length;
  await b.say("   "); assert.equal(b.state().guide.events.length, count);
  await b.say("abcdef？先帮我想想"); assert.match(b.node("#mc-work-page").innerHTML, /不能可靠提取/);
  assert.match(b.node("#mc-work-page").innerHTML, /abcdef/);
  await b.click("guide-directions"); assert.equal(b.state().guide.directionRound, 1);
  await b.click("guide-auto"); assert.equal(b.state().draft.goal, "awareness");
});

test("summary edit overrides earlier answers, invalidates stale output and keeps original input", async () => {
  const b = browser(); await b.complete("store"); const original = b.state().draft.prompt;
  await b.click("guide"); await b.click("guide-edit");
  await b.submit("guide-summary-form", { goal: "awareness", audience: "已沟通过的办公人群", product: "matebook-d" });
  assert.equal(b.state().draft.audience, "已沟通过的办公人群"); assert.equal(b.state().draft.product, "matebook-d");
  assert.equal(b.state().draft.prompt, original); assert.deepEqual(b.state().draft.outputs, {});
  assert.equal(b.state().history.length, 1);
  await b.click("guide-strategies"); assert.match(b.node("#mc-work-page").innerHTML, /已沟通过的办公人群/);
});

test("channel changes are optional, retained and cannot remove every channel", async () => {
  const b = browser(); await b.start(); await b.click("guide-channels"); await b.click("guide-platform", "小红书");
  await b.click("guide-platform", "微信朋友圈"); await b.click("guide-platform", "小红书");
  assert.deepEqual(b.state().draft.platforms, ["小红书"]);
  await b.click("guide-close-panel"); await b.click("guide-strategies"); await b.click("decide"); await b.click("generate");
  assert.deepEqual(Object.keys(b.state().draft.outputs), ["小红书"]);
});

test("editing, copy, partial update, regeneration and return preserve selected strategy and saved draft", async () => {
  const b = browser(); await b.complete("store");
  b.input("output-title", "手动修改标题"); b.input("output-body", "手动修改正文");
  await b.click("copy"); assert.equal(b.copies[0], "手动修改标题\n\n手动修改正文");
  const restored = browser(b.state()); assert.match(restored.node("#mc-work-page").innerHTML, /手动修改标题/);
  const id = b.state().draft.strategyId; await b.click("improve-title"); await b.click("shorten");
  b.node("#result-requirement").value = "更短，需要人工设计海报"; b.node("#result-tone").value = "简洁专业";
  await b.click("update-output"); assert.match(b.state().draft.outputs["微信朋友圈"].body, /^选购建议/);
  assert.match(b.state().draft.outputs["微信朋友圈"].requirementNote, /人工设计海报/);
  await b.click("regenerate"); assert.equal(b.state().draft.strategyId, id);
  await b.click("analysis"); assert.equal(b.state().draft.strategyId, id);
  await b.click("guide"); await b.click("guide-restart"); assert.equal(b.state().guide.events.length, 0);
  assert.equal(b.state().history.length, 1); await b.click("history");
  await b.click("open-record", b.state().history[0].id); assert.equal(b.state().page, "results");
});

test("creation records can be cancelled or deleted individually without clearing the active work", async () => {
  const b = browser();
  await b.complete("seeding");
  const firstId = b.state().history[0].id;
  await b.click("new");
  await b.complete("launch");
  const activeId = b.state().draft.recordId;
  const activeOutputs = structuredClone(b.state().draft.outputs);
  assert.equal(b.state().history.length, 2);

  await b.click("history");
  assert.match(b.node("#mc-work-page").innerHTML, new RegExp(`data-action="delete-record" data-id="${firstId}"`));
  assert.match(b.node("#mc-work-page").innerHTML, /class="mc-history-actions"/);

  b.window.confirm = () => false;
  await b.click("delete-record", firstId);
  assert.equal(b.state().history.length, 2);

  b.window.confirm = () => true;
  await b.click("delete-record", firstId);
  assert.deepEqual(b.state().history.map(r => r.id), [activeId]);
  assert.deepEqual(b.state().draft.outputs, activeOutputs);
  assert.equal(b.state().draft.recordId, activeId);

  await b.click("delete-record", activeId);
  assert.equal(b.state().history.length, 0);
  assert.equal(b.state().draft.recordId, null);
  assert.deepEqual(b.state().draft.outputs, activeOutputs);
  assert.match(b.node("#mc-work-page").innerHTML, /还没有创作草稿/);

  const restored = browser(b.state());
  assert.equal(restored.state().history.length, 0);
  assert.deepEqual(restored.state().draft.outputs, activeOutputs);
});

test("a missing creation record id is ignored and a deleted active work saves under a new id", async () => {
  const b = browser(); await b.complete("store");
  const deletedId = b.state().draft.recordId;
  await b.click("history");
  await b.click("delete-record", "missing-id");
  assert.equal(b.state().history.length, 1);
  await b.click("delete-record", deletedId);
  assert.equal(b.state().history.length, 0);

  await b.click("results");
  b.input("output-title", "删除记录后继续编辑");
  assert.equal(b.state().history.length, 1);
  assert.notEqual(b.state().history[0].id, deletedId);
  assert.equal(b.state().history[0].draft.outputs["微信朋友圈"].title, "删除记录后继续编辑");
});

test("optional legacy product page retains search and selection flow without becoming mandatory", async () => {
  const b = browser(); await b.start(); await b.click("guide-strategies"); await b.click("config");
  await b.click("product", "matebook-x-pro"); await b.click("platform", "门店海报"); await b.click("analyze");
  assert.equal(b.state().page, "analysis"); assert.equal(b.state().draft.product, "matebook-x-pro");
  await b.click("guide"); assert.equal(b.state().draft.product, "matebook-x-pro");
});

test("local opportunity evidence stays a hypothesis and unrelated drafts are cleared", async () => {
  const b = browser(); await b.complete("launch"); await b.click("home");
  // Explicit homepage input now travels with an opportunity; clear it to test isolation.
  b.input("mc-prompt", "");
  await b.click("opportunity", "consultation-list"); assert.equal(b.state().draft.product, ""); assert.deepEqual(b.state().draft.outputs, {});
  const saved = b.state(); saved.store.location = "门店填写商圈"; saved.store.landmarks = "附近大学";
  const local = browser(saved); await local.click("opportunity", "local");
  assert.match(local.state().draft.opportunity.evidence, /门店填写.*推断.*待验证/);
  assert.equal(local.state().draft.audience, "");
  await local.click("settings"); assert.match(local.node("#mc-work-page").innerHTML, /门店基础信息/);
});

test("catalog search covers names, model aliases and series without inventing missing products", () => {
  const D = browser().window.MarketingPrototypeData;
  assert.ok(D.products.length > 3);
  for (const [query, id] of [["d16", "matebook-d-16"], ["华为 D 14", "matebook-d-14"], ["matebook 16s", "matebook-16s"], ["X Pro", "matebook-x-pro"], ["华为14", "matebook-14"]]) {
    assert.ok(D.searchProducts(query).some(p => p.id === id), query);
  }
  assert.ok(D.searchProducts("D 系列").length >= 3);
  assert.equal(D.searchProducts("不存在的MateBook 9999").length, 0);
  assert.ok(D.searchProducts("", "型号示例").every(p => p.category === "型号示例"));
});

test("homepage single selection can switch, remove and survive reload without becoming a task answer", async () => {
  const b = browser(); b.input("mc-home-product-search", "d16");
  assert.match(b.node("#mc-home-product-results").innerHTML, /data-id="matebook-d-16"/);
  assert.doesNotMatch(b.node("#mc-home-product-results").innerHTML, /data-id="matebook-14"/);
  await b.click("home-product-select", "matebook-d-16");
  assert.equal(b.state().homeProduct, "matebook-d-16"); assert.equal(b.state().draft.product, "");
  assert.match(b.node("#mc-home-product-selection").innerHTML, /MateBook D 16/);
  const restored = browser(b.state()); assert.equal(restored.state().homeProduct, "matebook-d-16");
  await restored.click("home-product-select", "matebook-16s"); assert.equal(restored.state().homeProduct, "matebook-16s");
  await restored.click("home-product-remove"); assert.equal(restored.state().homeProduct, "");
  restored.input("mc-home-product-search", "unknown-9999"); assert.match(restored.node("#mc-home-product-count").textContent, /暂未找到匹配产品/);
  assert.doesNotMatch(restored.node("#mc-home-product-results").innerHTML, /data-action="home-product-select"/);
});

test("selected catalog product and exact original input reach guide and generated output", async () => {
  const b = browser(), prompt = "  介绍产品，让更多顾客了解实际使用价值。\n不提价格  ";
  await b.click("home-product-select", "matebook-d-16"); b.input("mc-prompt", prompt); await b.start();
  assert.equal(b.state().draft.product, "matebook-d-16"); assert.equal(b.state().draft.prompt, prompt);
  assert.equal(b.state().guide.events[0].text, prompt); assert.equal(b.state().draft.opportunity, null);
  assert.equal(b.window.MarketingGuidance.stage(b.window.MarketingGuidance.resolve(b.state().guide)), "ready");
  await b.click("guide-strategies"); await b.click("decide"); await b.click("generate");
  assert.match(b.state().draft.outputs["通用草稿"].body, /MateBook D 16/);
});

test("unselected or deferred product never blocks strategy and new task clears homepage config", async () => {
  const b = browser(); b.input("mc-prompt", "还没想好从什么角度切入"); await b.start();
  assert.equal(b.state().draft.product, ""); await b.click("guide-strategies"); assert.equal(b.state().page, "analysis");
  await b.click("home"); await b.click("home-product-select", "matebook-16s"); await b.click("home-product-defer");
  b.input("mc-prompt", "建立产品认知"); await b.start();
  assert.equal(b.state().draft.product, ""); assert.equal(b.window.MarketingGuidance.stage(b.window.MarketingGuidance.resolve(b.state().guide)), "ready");
  await b.click("home"); await b.click("home-product-select", "matebook-14"); await b.click("new");
  assert.equal(b.state().homeProduct, ""); assert.equal(b.state().homeProductDeferred, false); assert.equal(b.state().homePrompt, "");
});

test("opportunity carries explicit homepage context but never inherits answers from another guide", async () => {
  const b = browser(), prompt = "  希望帮助附近大学生明确选购需求\n  ";
  b.input("mc-prompt", prompt); await b.click("home-product-select", "matebook-16s"); await b.click("opportunity", "date-refresh");
  assert.equal(b.state().draft.prompt, prompt); assert.equal(b.state().draft.opportunity.id, "date-refresh");
  assert.equal(b.state().draft.product, "matebook-16s"); assert.equal(b.state().draft.goal, "needs");
  assert.match(b.node("#mc-work-page").innerHTML, /已沿用你补充的目标/);
  assert.doesNotMatch(b.node("#mc-work-page").innerHTML, /推广目标还没有确定/);
  await b.say("用小红书发布，促进产品咨询"); await b.click("guide-product", "matebook-14");
  await b.click("home"); await b.click("opportunity", "consultation-list");
  assert.equal(b.state().draft.opportunity.id, "consultation-list"); assert.equal(b.state().draft.product, "matebook-16s");
  assert.equal(b.state().draft.goal, "needs"); assert.deepEqual(b.state().draft.platforms, ["微信朋友圈"]);
  await b.click("home"); await b.start(); assert.equal(b.state().draft.opportunity, null); assert.equal(b.state().draft.product, "matebook-16s");
});

test("free-text recognition uses the extended catalog and distinguishes similar model names", () => {
  const G = browser().window.MarketingGuidance;
  for (const [name, id] of [["MateBook D 16", "matebook-d-16"], ["MateBook D14", "matebook-d-14"], ["MateBook 16s", "matebook-16s"], ["MateBook X Pro", "matebook-x-pro"]]) {
    assert.deepEqual(Array.from(G.recognize(`推广${name}，介绍产品`).products), [id]);
  }
  assert.equal(G.recognize("推广MateBook 9999").products.length, 0);
});

test("rewriting homepage idea drops the previous opportunity instead of leaking its goal", async () => {
  const b = browser(); await b.click("opportunity", "consultation-list"); await b.click("home");
  b.input("mc-prompt", "想了解顾客常用的软件，还没决定推广方向"); await b.start();
  assert.equal(b.state().draft.opportunity, null); assert.equal(b.state().draft.goal, "");
  assert.equal(b.window.MarketingGuidance.stage(b.window.MarketingGuidance.resolve(b.state().guide)), "direction");
});

test("store channels become editable suggestions and consultation changes strategy substance", async () => {
  const initial = browser().state(); initial.store.platforms = ["公众号"];
  const b = browser(initial); b.input("mc-prompt", "给MateBook 14建立产品认知"); await b.start();
  assert.deepEqual(b.state().draft.platforms, ["公众号"]);
  const before = b.window.MarketingPrototypeModel.strategyOptions(b.state().draft)[0].claim;
  await b.say("这次推动购买咨询更重要");
  const after = b.window.MarketingPrototypeModel.strategyOptions(b.state().draft)[0].claim;
  assert.notEqual(before, after);
});

test("regeneration varies body while retaining the chosen strategy; old guide data migrates safely", async () => {
  const b = browser(); await b.complete("store"); const original = b.state().draft.outputs["微信朋友圈"].body, id = b.state().draft.strategyId;
  await b.click("regenerate"); assert.notEqual(b.state().draft.outputs["微信朋友圈"].body, original);
  assert.equal(b.state().draft.strategyId, id);
  const legacy = b.state(); delete legacy.guide; legacy.page = "config";
  const restored = browser(legacy); assert.equal(restored.state().page, "guide");
  assert.equal(restored.state().draft.product, "matebook-14");
});


test("opportunity starts with complete provenance and no inferred goal, audience or product", async () => {
  const b = browser(); await b.click("opportunity", "date-refresh");
  const st = b.state(), o = st.draft.opportunity, html = b.node("#mc-work-page").innerHTML;
  for (const key of ["title", "description", "reason", "type", "status", "direction", "evidence", "unknown"]) assert.ok(html.includes(o[key]), key);
  assert.equal(st.draft.goal, ""); assert.equal(st.draft.product, ""); assert.equal(st.draft.audience, "");
  assert.equal(b.window.MarketingGuidance.stage(b.window.MarketingGuidance.resolve(st.guide, o)), "opportunity-goal");
  assert.match(html, /推广目标还没有确定/); assert.match(html, /介绍华为 PC 的切入点/);
  assert.doesNotMatch(html, /已有信息足以整理第一版策略/);
  await b.click("guide-strategies"); assert.equal(b.state().page, "guide");
});

test("three opportunity goals drive different questions, summaries, strategies and outputs", async () => {
  const outputs = [], claims = [], questions = [];
  for (const [goal, focus] of [["store", "experience"], ["needs", "checklist"], ["consultation", "faq"]]) {
    const b = browser(); await b.click("opportunity", "date-refresh"); await b.click("guide-goal", goal);
    assert.equal(b.state().draft.goal, goal); questions.push(b.node("#mc-work-page").innerHTML);
    assert.doesNotMatch(b.node("#mc-work-page").innerHTML, /class="mc-guide-products"/);
    await b.click("guide-focus", focus); assert.equal(b.state().draft.focus, focus);
    await b.say("用小红书发布"); assert.deepEqual(b.state().draft.platforms, ["小红书"]);
    const restored = browser(b.state()); assert.equal(restored.state().draft.focus, focus);
    await restored.click("guide-strategies");
    const strategies = restored.window.MarketingPrototypeModel.strategyOptions(restored.state().draft);
    assert.equal(new Set(strategies.map(s => s.claim)).size, 3);
    for (const s of strategies) for (const field of ["claim", "audience", "format", "reason", "cta", "plan", "relation", "evidence", "unknown"]) assert.ok(s[field], field);
    claims.push(strategies[0].claim);
    await restored.click("decide"); await restored.click("generate");
    outputs.push(restored.state().draft.outputs["小红书"].body);
    assert.equal(restored.state().draft.product, "");
    assert.match(outputs.at(-1), /待选择|尚未指定/);
    assert.doesNotMatch(outputs.at(-1), /MateBook 14|X Pro|有货|限时优惠|提升.*%/);
  }
  assert.equal(new Set(claims).size, 3); assert.equal(new Set(outputs).size, 3); assert.equal(new Set(questions).size, 3);
});

test("product comparison appears only when relevant and can still be skipped", async () => {
  const b = browser(); await b.click("opportunity", "date-refresh"); await b.click("guide-goal", "needs");
  await b.click("guide-focus", "match"); assert.match(b.node("#mc-work-page").innerHTML, /class="mc-guide-products"/);
  await b.click("guide-candidates"); await b.click("guide-skip-product");
  assert.equal(b.window.MarketingGuidance.stage(b.window.MarketingGuidance.resolve(b.state().guide, b.state().draft.opportunity)), "ready");
  await b.click("guide-strategies"); assert.equal(b.state().page, "analysis"); assert.equal(b.state().draft.product, "");
  assert.match(b.window.MarketingPrototypeModel.strategyOptions(b.state().draft)[0].name, /资料/);
});

test("automatic goal recommendation depends on the opportunity and explains its reason", async () => {
  const selected = [], reasons = [], options = [];
  for (const id of ["date-refresh", "consultation-list", "local", "software-questions"]) {
    const b = browser(); await b.click("opportunity", id);
    options.push(b.window.MarketingGuidance.opportunityGoals(b.state().draft.opportunity).map(x => x.id).join(","));
    await b.click("guide-auto"); selected.push(b.state().draft.goal);
    const reason = b.state().guide.events.at(-1).patch.recommendationReason; reasons.push(reason);
    assert.ok(reason.length > 30); assert.ok(b.node("#mc-work-page").innerHTML.includes(reason));
  }
  assert.equal(new Set(selected).size, 3); assert.equal(new Set(reasons).size, 4); assert.ok(new Set(options).size > 1);
});

test("home start is isolated even with unchanged input or an empty input after opportunity", async () => {
  const b = browser(); const original = "  帮我给MateBook 14建立产品认知\n  ";
  b.input("mc-prompt", original); await b.start(); await b.say("用小红书发布");
  await b.click("home"); await b.click("opportunity", "date-refresh"); await b.click("guide-goal", "store");
  await b.click("home"); assert.equal(b.node("#mc-prompt").value, original);
  await b.start(); assert.equal(b.state().draft.prompt, original); assert.equal(b.state().draft.opportunity, null);
  assert.equal(b.state().draft.goal, "awareness"); assert.equal(b.state().guide.events.length, 1);
  assert.deepEqual(b.state().draft.platforms, ["微信朋友圈"]);
  const empty = browser(); await empty.click("opportunity", "date-refresh"); await empty.click("home"); await empty.start();
  assert.equal(empty.state().draft.opportunity, null); assert.equal(empty.state().draft.goal, ""); assert.equal(empty.state().guide.events.length, 0);
});

test("switching opportunities replaces task snapshot and clears prior answers and results", async () => {
  const b = browser(); await b.click("opportunity", "date-refresh"); await b.click("guide-auto"); await b.click("guide-strategies");
  await b.click("decide"); await b.click("generate"); await b.click("home"); await b.click("preview-opportunity", "consultation-list");
  await b.click("opportunity", "consultation-list");
  assert.equal(b.state().draft.opportunity.id, "consultation-list"); assert.equal(b.state().draft.goal, "");
  assert.equal(b.state().draft.focus, ""); assert.deepEqual(b.state().draft.outputs, {}); assert.equal(b.state().guide.events.length, 0);
  assert.match(b.node("#mc-work-page").innerHTML, /到店前沟通连起来/);
  const restored = browser(b.state()); assert.equal(restored.state().draft.opportunity.status, b.state().draft.opportunity.status);
});

test("changing opportunity goal clears obsolete focus and output while keeping original context", async () => {
  const b = browser(); await b.click("opportunity", "date-refresh"); await b.click("guide-goal", "store");
  await b.click("guide-focus", "experience"); await b.click("guide-strategies"); await b.click("decide"); await b.click("generate");
  await b.click("analysis"); await b.click("guide"); await b.click("guide-edit");
  await b.submit("guide-summary-form", { goal: "consultation", audience: "", product: "" });
  assert.equal(b.state().draft.focus, ""); assert.deepEqual(b.state().draft.outputs, {});
  assert.equal(b.state().draft.opportunity.id, "date-refresh");
  assert.match(b.node("#mc-work-page").innerHTML, /如何开启沟通/);
  await b.click("guide-focus", "private"); await b.click("guide-strategies");
  assert.match(b.window.MarketingPrototypeModel.strategyOptions(b.state().draft)[0].claim, /咨询|软件|选购/);
});

// Regression: transcript is provenance; only the current resolved fields drive generation.
async function finishCurrent(b) {
  await b.click("guide-strategies"); assert.equal(b.state().page, "analysis");
  await b.click("decide"); await b.click("generate"); assert.equal(b.state().page, "results");
  return b.state().draft;
}
const generatedText = d => Object.values(d.outputs).map(o => `${o.title}\n${o.body}`).join("\n");

test("explicit replacement removes the old product, audience and platform from generated strategies and copy", async () => {
  const b = browser(); b.input("mc-prompt", "给 MateBook 14 建立产品认知，面向附近大学生，用小红书发布"); await b.start();
  await b.say("不要面向大学生了，改为退休老人；不推广 MateBook 14，改为 MateBook X Pro；不要小红书，改发朋友圈");
  const d = b.state().draft;
  assert.equal(d.product, "matebook-x-pro"); assert.equal(d.audience, "退休老人"); assert.deepEqual(d.platforms, ["微信朋友圈"]);
  assert.match(d.prompt, /MateBook 14/); assert.match(b.state().guide.events[0].text, /大学生/);
  const strategies = JSON.stringify(b.window.MarketingPrototypeModel.strategyOptions(d));
  assert.doesNotMatch(strategies, /MateBook 14|大学生|小红书/);
  const output = generatedText(await finishCurrent(b));
  assert.match(output, /MateBook X Pro/); assert.match(output, /退休老人/); assert.doesNotMatch(output, /MateBook 14|大学生|小红书/);
});

test("single-sentence model replacement takes precedence over all prior mentions", async () => {
  const b = browser(); b.input("mc-prompt", "介绍 MateBook 14，建立产品认知"); await b.start();
  await b.say("把 MateBook 14 改成 MateBook X Pro");
  assert.equal(b.state().draft.product, "matebook-x-pro");
  assert.doesNotMatch(generatedText(await finishCurrent(b)), /MateBook 14/);
});

test("cleared audience, product and channel stay cleared across rerender, reload and generation", async () => {
  const b = browser(); b.input("mc-prompt", "面向大学生介绍MateBook 14，建立产品认知，用小红书"); await b.start();
  await b.say("不要指定任何产品，先不选型号；清空受众；清空平台");
  const c = b.state().draft;
  assert.equal(c.product, ""); assert.equal(c.audience, ""); assert.deepEqual(c.platforms, []);
  for (const key of ["product", "audience", "platforms"]) assert.equal(c.fieldStatus[key], "cleared");
  const restored = browser(b.state()); const d = await finishCurrent(restored);
  assert.equal(d.audience, ""); assert.deepEqual(d.platforms, []);
  assert.deepEqual(Object.keys(d.outputs), ["通用草稿"]);
  assert.doesNotMatch(generatedText(d), /MateBook 14|大学生|小红书/);
});

test("summary clearing audience never re-infers it from the initial prompt", async () => {
  const b = browser(); b.input("mc-prompt", "给大学生介绍 MateBook 14，建立产品认知"); await b.start();
  await b.click("guide-edit"); await b.submit("guide-summary-form", { goal: "awareness", audience: "", product: "matebook-14" });
  assert.equal(b.state().draft.fieldStatus.audience, "cleared");
  assert.doesNotMatch(JSON.stringify(b.window.MarketingPrototypeModel.strategyOptions(b.state().draft)), /大学生/);
  assert.doesNotMatch(generatedText(await finishCurrent(b)), /大学生/);
});

test("negating travel preserves the replacement learning scene and removes travel from all strategies and copy", async () => {
  const b = browser(); b.input("mc-prompt", "推广 MateBook X Pro，建立产品认知，面向经常出差的顾客，用小红书"); await b.start();
  await b.say("改为面向大学生的学习用途，不要差旅内容");
  assert.equal(b.state().draft.audience, "附近大学生"); assert.equal(b.state().draft.scene, "学习用途");
  assert.ok(b.state().draft.excludedScenes.includes("travel"));
  for (let round = 0; round < 3; round++) {
    assert.doesNotMatch(JSON.stringify(b.window.MarketingPrototypeModel.strategyOptions(b.state().draft)), /差旅|出差/);
    await b.click("shuffle");
  }
  assert.doesNotMatch(generatedText(await finishCurrent(b)), /差旅|出差/);
});

test("homepage product/text conflict requires explicit confirmation and cannot generate prematurely", async () => {
  const b = browser(); await b.click("home-product-select", "matebook-14");
  b.input("mc-prompt", "推广 MateBook X Pro，建立产品认知"); await b.start();
  assert.match(b.node("#mc-work-page").innerHTML, /首页所选产品与输入型号不一致/);
  assert.equal(b.state().draft.product, "");
  await b.click("guide-strategies"); assert.equal(b.state().page, "guide");
  await b.click("guide-product", "matebook-x-pro");
  assert.doesNotMatch(generatedText(await finishCurrent(b)), /MateBook 14/);
});

test("four distinct goals retain distinct strategy substance after shuffling", async () => {
  const claims = [], bodies = [];
  for (const goal of ["awareness", "needs", "consultation", "store"]) {
    const b = browser(); await b.start(); await b.click("guide-goal", goal); await b.click("guide-skip-product");
    for (let round = 0; round < 3; round++) {
      const options = b.window.MarketingPrototypeModel.strategyOptions(b.state().draft);
      assert.equal(options.length, 3); assert.equal(new Set(options.map(s => s.claim)).size, 3);
      if (round === 1) claims.push(options.map(s => s.claim).sort().join("|"));
      await b.click("shuffle");
    }
    bodies.push(generatedText(await finishCurrent(b)));
  }
  assert.equal(new Set(claims).size, 4); assert.equal(new Set(bodies).size, 4);
  assert.match(claims[2], /用途|软件|选购/); assert.match(claims[1], /需求|标准|比较/);
});

test("changing goal invalidates old results, and strategy adjustments update effective fields", async () => {
  const b = browser(); await b.complete("store"); await b.click("analysis");
  b.node("#strategy-adjustment").value = "改为建立产品认知；产品改为 MateBook X Pro；不要差旅内容";
  await b.click("adjust-strategy");
  assert.equal(b.state().draft.goal, "awareness"); assert.equal(b.state().draft.product, "matebook-x-pro");
  assert.deepEqual(b.state().draft.outputs, {}); assert.equal(b.state().draft.strategyId, "");
  await b.click("shuffle");
  assert.doesNotMatch(JSON.stringify(b.window.MarketingPrototypeModel.strategyOptions(b.state().draft)), /MateBook 14|差旅/);
});

test("unsupported ambiguous changes request confirmation rather than silently applying a guess", async () => {
  const b = browser(); b.input("mc-prompt", "推广MateBook 14，建立产品认知"); await b.start();
  await b.say("改成那个更适合的");
  assert.match(b.node("#mc-work-page").innerHTML, /请确认本次修改/);
  assert.equal(b.state().draft.product, "matebook-14");
  await b.click("guide-strategies"); assert.equal(b.state().page, "guide");
  await b.click("guide-confirm-current"); await b.click("guide-strategies"); assert.equal(b.state().page, "analysis");
});

test("unknown input acknowledges mock limitations without claiming readiness or changing state", async () => {
  const b = browser(); await b.complete(); await b.click("guide");
  await b.say("蓝鲸在火星上跳舞");
  const last = b.state().guide.events.at(-1).response;
  assert.match(last, /不能可靠提取/); assert.doesNotMatch(last, /已有信息足以/);
  assert.equal(b.state().draft.product, "matebook-14");
});

test("local content updates operate on manual text and unsupported edits preserve it exactly", async () => {
  const b = browser(); await b.complete(); const original = "我的手写开场，不应被模板替换。\n\n我亲自写的第二段。\n\n保留的结尾。";
  b.input("output-body", original); b.node("#result-tone").value = "自然真诚";
  b.node("#result-requirement").value = "把第二段写成一首七言诗"; await b.click("update-output");
  assert.equal(b.state().draft.outputs["微信朋友圈"].body, original);
  assert.match(b.node("#mc-toast").textContent, /未支持/);
  b.node("#result-requirement").value = "更短"; await b.click("update-output");
  assert.match(b.state().draft.outputs["微信朋友圈"].body, /我的手写开场/);
  assert.match(b.state().draft.outputs["微信朋友圈"].body, /我亲自写的第二段/);
  assert.doesNotMatch(b.state().draft.outputs["微信朋友圈"].body, /MateBook/);
  await b.click("restore-body"); assert.equal(b.state().draft.outputs["微信朋友圈"].body, original);
  await b.click("copy"); assert.ok(b.copies.at(-1).endsWith(original));
});

test("full replacement actions can be cancelled without losing manual content", async () => {
  const b = browser(); await b.complete(); b.input("output-body", "需要保护的正文");
  b.window.confirm = () => false;
  await b.click("regenerate"); await b.click("change-angle");
  assert.equal(b.state().draft.outputs["微信朋友圈"].body, "需要保护的正文");
});

test("AI transcript and initial opportunity reply are immutable across subsequent choices and reload", async () => {
  const b = browser(); await b.click("opportunity", "date-refresh");
  const intro = b.state().guide.intro;
  await b.click("guide-goal", "needs"); const first = b.state().guide.events[0].response;
  await b.click("guide-focus", "checklist"); await b.say("改为促进产品咨询");
  assert.equal(b.state().guide.intro, intro); assert.equal(b.state().guide.events[0].response, first);
  const restored = browser(b.state()); assert.equal(restored.state().guide.intro, intro); assert.equal(restored.state().guide.events[0].response, first);
  assert.equal(restored.state().draft.goal, "consultation");
});

test("native history traverses app pages, preserves latest edits and restores different task snapshots", async () => {
  const b = browser(); await b.complete(); b.input("output-body", "返回时不能丢失的手写正文");
  b.nativeHistory.back(); assert.equal(b.state().page, "analysis");
  b.nativeHistory.back(); assert.equal(b.state().page, "guide");
  b.nativeHistory.forward(); assert.equal(b.state().page, "analysis");
  b.nativeHistory.forward(); assert.equal(b.state().page, "results");
  assert.equal(b.state().draft.outputs["微信朋友圈"].body, "返回时不能丢失的手写正文");
  const oldTask = b.state().draft.taskId;
  await b.click("new"); b.input("mc-prompt", "推广MateBook X Pro，促进产品咨询"); await b.start();
  assert.notEqual(b.state().draft.taskId, oldTask);
  b.nativeHistory.back(); assert.equal(b.state().page, "home");
  b.nativeHistory.back(); assert.equal(b.state().page, "results"); assert.equal(b.state().draft.taskId, oldTask);
  assert.equal(b.state().draft.product, "matebook-14");
});

test("forward navigation after requirement edits never renders invalidated results", async () => {
  const b = browser(); await b.complete(); b.nativeHistory.back(); b.nativeHistory.back();
  await b.say("产品改为MateBook X Pro");
  b.nativeHistory.forward(); b.nativeHistory.forward();
  assert.equal(b.state().page, "analysis"); assert.deepEqual(b.state().draft.outputs, {});
});

test("legacy config edits and clearing opportunity retain cleared fields and frozen messages", async () => {
  const b = browser(); b.input("mc-prompt", "推广MateBook 14，建立产品认知，面向大学生，用小红书"); await b.start();
  const first = b.state().guide.events[0].response;
  await b.say("清空产品；清空受众；清空平台");
  await b.click("config");
  b.input("legacy-prompt", "更短", "prompt");
  await b.click("guide");
  assert.equal(b.state().draft.product, ""); assert.equal(b.state().draft.audience, "");
  assert.deepEqual(b.state().draft.platforms, []); assert.equal(b.state().draft.short, true);
  assert.equal(b.state().guide.events[0].response, first);
  assert.doesNotMatch(generatedText(await finishCurrent(b)), /MateBook 14|大学生|小红书/);
  const o = browser(); await o.click("opportunity", "date-refresh"); await o.click("guide-goal", "needs");
  await o.say("清空受众；清空平台"); await o.click("config"); await o.click("clear-opportunity"); await o.click("guide");
  assert.equal(o.state().draft.opportunity, null); assert.equal(o.state().draft.goal, "needs");
  assert.deepEqual(o.state().draft.platforms, []); assert.equal(o.state().draft.audience, "");
});

test("every legacy strategy branch honors excluded scenes before and after shuffle", async () => {
  for (const task of ["launch", "season", "store"]) {
    const b = browser(); await b.complete(task); await b.click("guide"); await b.say("不要学习内容；不要差旅内容");
    for (let round = 0; round < 3; round++) {
      assert.doesNotMatch(JSON.stringify(b.window.MarketingPrototypeModel.strategyOptions(b.state().draft)), /学习|差旅|出差/);
      await b.click("shuffle");
    }
    assert.doesNotMatch(generatedText(await finishCurrent(b)), /学习|差旅|出差/);
  }
});

test("compact channel replacement is recognized and unknown channel changes need confirmation", async () => {
  const b = browser(); b.input("mc-prompt", "推广MateBook 14，建立产品认知，用小红书"); await b.start();
  await b.say("不要小红书改发朋友圈"); assert.deepEqual(b.state().draft.platforms, ["微信朋友圈"]);
  await b.say("把平台换成抖音");
  assert.match(b.node("#mc-work-page").innerHTML, /请确认本次修改/);
  assert.deepEqual(b.state().draft.platforms, ["微信朋友圈"]);
});

test("creative previews vary by direction and expected outputs follow the platform", async () => {
  const b = browser(); b.input("mc-prompt", "面向大学生推广 MateBook 14，建立产品认知，用小红书"); await b.start();
  await b.click("guide-strategies");
  const options = b.window.MarketingPrototypeModel.strategyOptions(b.state().draft);
  assert.equal(new Set(options.map(s => s.visualSrc)).size, 3);
  assert.equal(new Set(options.map(s => s.coreIdea)).size, 3);
  for (const s of options) {
    assert.match(s.visualNote, /概念示意/); assert.match(s.visualAlt, /概念示意/);
    assert.ok(fs.existsSync(path.join(__dirname, "../ui", s.visualSrc)));
    assert.ok(s.expectedOutputs.length >= 2);
    assert.match(s.factBasis, /示例|未核实|无已核实/);
  }
  await b.say("不要小红书，改发门店海报");
  for (const s of b.window.MarketingPrototypeModel.strategyOptions(b.state().draft)) assert.match(s.expectedOutputs.join(" "), /海报/);
});

test("each selected creative transfers its complete brief and distinct copy into results", async () => {
  const bodies = [];
  for (let i = 0; i < 3; i++) {
    const b = browser(); b.input("mc-prompt", "面向大学生推广 MateBook 14，建立产品认知，用小红书"); await b.start(); await b.click("guide-strategies");
    const s = JSON.parse(JSON.stringify(b.window.MarketingPrototypeModel.strategyOptions(b.state().draft)[i]));
    await b.click("strategy", s.id);
    const selected = b.state().draft.strategyContext.strategy;
    assert.equal(selected.id, s.id); assert.equal(selected.coreIdea, s.coreIdea); assert.equal(selected.cta, s.cta);
    assert.equal(selected.visualStyle, s.visualStyle); assert.match(selected.recommendationReason, /MateBook 14/);
    await b.click("generate");
    const d = b.state().draft, output = d.outputs["小红书"];
    assert.deepEqual(d.strategyContext.strategy, selected); assert.deepEqual(d.outputContext.strategy, selected); assert.deepEqual(output.strategy, selected);
    assert.equal(d.outputContext.task.product, d.product); assert.equal(d.outputContext.task.goal, d.goal);
    assert.match(output.body, new RegExp(s.opening));
    assert.ok(output.body.includes(s.cta));
    assert.ok(b.node("#mc-work-page").innerHTML.includes(s.visualStyle));
    assert.equal(output.strategy.coreIdea, s.coreIdea);
    assert.doesNotMatch(b.node("#mc-work-page").innerHTML, /策略与生成依据| · 配套内容/);
    bodies.push(output.body);
  }
  assert.equal(new Set(bodies).size, 3);
});

test("shuffling clears selection but preserves edited results and their original creative snapshot", async () => {
  const b = browser(); await b.complete(); b.input("output-body", "保留我的手工正文");
  const before = b.state().draft.outputContext; await b.click("analysis"); await b.click("shuffle");
  assert.equal(b.state().draft.strategyId, ""); assert.equal(b.state().draft.strategyContext, null);
  assert.deepEqual(b.state().draft.outputContext, before);
  assert.match(b.node("#mc-work-page").innerHTML, /确认方向，生成推广图文/);
  assert.equal((b.node("#mc-work-page").innerHTML.match(/class="mc-lead-strategy"/g) || []).length, 1);
  await b.click("results");
  assert.equal(b.state().draft.outputs["微信朋友圈"].body, "保留我的手工正文");
  assert.ok(b.node("#mc-work-page").innerHTML.includes(before.strategy.visualStyle));
  await b.click("analysis"); b.node("#strategy-adjustment").value = "改为建立产品认知"; b.window.confirm = () => false;
  await b.click("adjust-strategy");
  assert.equal(b.state().draft.outputs["微信朋友圈"].body, "保留我的手工正文");
});

test("strategy summary leaves unconfirmed product, audience and platform pending", async () => {
  const b = browser(); await b.start(); await b.click("guide-goal", "needs"); await b.click("guide-skip-product"); await b.click("guide-strategies");
  const html = b.node("#mc-work-page").innerHTML;
  assert.match(html, /当前产品<\/dt><dd>待确认/);
  assert.match(html, /目标受众<\/dt><dd>待确认/);
  assert.match(html, /发布平台<\/dt><dd>待确认/);
  assert.match(html, /查看任务详情/); assert.match(html, /查看推荐依据/);
  assert.doesNotMatch(html, /营销/);
});

test("one lead recommendation can generate directly without a separate selection", async () => {
  const b = browser(); b.input("mc-prompt", "推广 MateBook 14，建立产品认知，用小红书"); await b.start(); await b.click("guide-strategies");
  const html = b.node("#mc-work-page").innerHTML;
  assert.equal((html.match(/class="mc-lead-strategy"/g) || []).length, 1);
  assert.doesNotMatch(html, /class="mc-strategy-grid"|选择这个方向/);
  assert.doesNotMatch(html, /mc-alternatives|查看其他方向/);
  assert.match(html, /规则模拟/); assert.match(html, /确认方向，生成推广图文/);
  assert.equal(b.state().draft.strategyId, "");
  await Promise.all([b.click("generate"), b.click("generate")]);
  assert.equal(b.state().page, "results");
  const d = b.state().draft, c = d.outputContext;
  assert.equal(c.task.product, "matebook-14"); assert.equal(c.task.goal, "awareness");
  assert.match(c.task.productFacts.source, /示例目录/);
  assert.ok(c.strategy.recommendationReason); assert.ok(c.strategy.visualStyle); assert.ok(c.strategy.expectedOutputs.length);
  assert.deepEqual(d.outputs["小红书"].strategy, c.strategy);
  assert.equal(b.state().history.length, 1);
});

test("lead recommendations differ by goal and current scenario rather than initial history", async () => {
  const briefs = [];
  for (const goal of ["awareness", "needs", "store", "consultation"]) {
    const b = browser(); await b.click("opportunity", "date-refresh"); await b.click("guide-goal", goal); await b.click("guide-strategies"); await b.click("generate");
    const s = b.state().draft.outputContext.strategy; assert.equal(s.goal, goal);
    briefs.push([s.claim, s.copy, s.cta].join("|"));
  }
  assert.equal(new Set(briefs).size, 4);
  const b = browser(); b.input("mc-prompt", "面向大学生推广 MateBook 14，建立产品认知，用小红书"); await b.start(); await b.click("guide-strategies"); await b.click("generate");
  assert.equal(b.state().draft.outputContext.strategy.angle, 2);
  await b.click("guide"); await b.say("清空场景；清空受众"); await b.click("guide-strategies"); await b.click("generate");
  assert.equal(b.state().draft.outputContext.strategy.angle, 1);
  assert.equal(b.state().draft.outputContext.strategy.confirmedAudience, "");
});

test("lead strategy copy names the promotion theme and varies deliverables by goal", async () => {
  const briefs = {};
  for (const goal of ["consultation", "awareness", "needs"]) {
    const b = browser();
    b.input("mc-prompt", `推广 MateBook 16，${goal === "consultation" ? "促进产品咨询" : goal === "awareness" ? "建立产品认知" : "帮助顾客明确选购需求"}`);
    await b.start(); await b.click("guide-strategies");
    const s = b.window.MarketingPrototypeModel.strategyOptions(b.state().draft)[0];
    briefs[goal] = s;
    assert.doesNotMatch(`${s.name}${s.coreIdea}`, /收集咨询线索|首次行动|一对一提问/);
    assert.ok(s.expectedOutputs.length >= 2);
  }
  assert.notEqual(briefs.consultation.name, briefs.awareness.name);
  assert.notEqual(briefs.awareness.coreIdea, briefs.needs.coreIdea);
  assert.match(briefs.consultation.expectedOutputs.join(" "), /咨询/);
  assert.match(briefs.needs.expectedOutputs.join(" "), /选购/);
});

test("explicit creative themes update the current strategy and result without becoming product facts", async () => {
  const b = browser(); b.input("mc-prompt", "推广 MateBook 16，促进产品咨询"); await b.start(); await b.click("guide-strategies");
  b.node("#strategy-adjustment").value = "主题改为常用软件与选购关注点"; await b.click("adjust-strategy");
  assert.match(b.node("#mc-work-page").innerHTML, /常用软件与选购关注点/);
  await b.click("generate");
  const updated = b.state().draft.outputContext.strategy;
  assert.equal(updated.name, "常用软件与选购关注点");
  assert.match(updated.coreIdea, /常用软件与选购关注点/);
  assert.match(updated.copy, /常用软件与选购关注点/);
  assert.equal(b.state().draft.outputContext.strategy.name, "常用软件与选购关注点");
  assert.match(b.state().draft.outputs["通用草稿"].title, /常用软件与选购关注点/);
  assert.match(b.state().draft.outputs["通用草稿"].body, /常用软件与选购关注点/);
  assert.doesNotMatch(JSON.stringify(b.state().draft.outputContext.task.productFacts), /常用软件与选购关注点/);
});

test("MateBook 16 acceptance tasks select distinct primary themes, content and deliverables without inventing a platform", async () => {
  const briefs = [];
  for (const [goal, text] of [["consultation", "促进产品咨询"], ["awareness", "建立产品认知"], ["needs", "帮助顾客判断产品是否适合自己"]]) {
    const b = browser(); b.input("mc-prompt", `推广 MateBook 16，${text}`); await b.start();
    assert.equal(b.state().draft.goal, goal);
    await b.click("guide-strategies"); await b.click("generate");
    const { task, strategy: s } = b.state().draft.outputContext;
    assert.equal(task.product, "matebook-16"); assert.equal(s.goal, goal); assert.deepEqual(task.platforms, []);
    assert.equal(b.state().draft.activePlatform, "通用草稿");
    assert.doesNotMatch(`${s.name}${s.coreIdea}${s.copy}`, /首次行动|咨询线索|一对一提问|店员如何|由店员/);
    assert.match(s.productIntegration, /MateBook 16/); assert.ok(s.cta); assert.ok(s.contentFormat);
    assert.match(s.expectedOutputs.join(" "), /通用推广文案/);
    assert.match(b.state().draft.outputs["通用草稿"].body, new RegExp(s.copy));
    briefs.push(s);
  }
  for (const field of ["name", "coreIdea", "copy", "cta"]) assert.equal(new Set(briefs.map(s => s[field])).size, 3, field);
  assert.equal(new Set(briefs.map(s => s.expectedOutputs.join("|"))).size, 3);
});

test("clearing or proposing an unsupported creative theme cannot revive or assert old information", async () => {
  const b = browser(); b.input("mc-prompt", "推广 MateBook 16，促进产品咨询"); await b.start(); await b.click("guide-strategies");
  b.node("#strategy-adjustment").value = "主题改为真实使用任务的选购参考"; await b.click("adjust-strategy");
  b.node("#strategy-adjustment").value = "清空主题"; await b.click("adjust-strategy");
  assert.equal(b.state().draft.creative, ""); assert.equal(b.state().draft.fieldStatus.creative, "cleared");
  assert.doesNotMatch(b.node("#mc-work-page").innerHTML, /真实使用任务的选购参考/);
  const before = b.state().draft;
  b.node("#strategy-adjustment").value = "主题改为 MateBook 16 续航 20 小时"; await b.click("adjust-strategy");
  assert.deepEqual(b.state().draft, before);
  assert.match(b.node("#mc-toast").textContent, /需要核实/);
});

test("one sentence adjusts the lead and the actual generated copy without restarting guidance", async () => {
  const b = browser(); b.input("mc-prompt", "面向大学生推广 MateBook 14，建立产品认知，用小红书"); await b.start(); await b.click("guide-strategies");
  const before = b.state().draft; const events = b.state().guide.events.length;
  b.node("#strategy-adjustment").value = "更突出真实使用场景、减少参数介绍、表达得更自然";
  await b.click("adjust-strategy"); assert.equal(b.state().page, "analysis");
  assert.equal(b.state().guide.events.length, events);
  assert.equal(b.state().draft.product, before.product); assert.equal(b.state().draft.goal, before.goal);
  assert.match(b.node("#mc-work-page").innerHTML, /减少参数罗列/);
  await b.click("generate"); const d = b.state().draft, s = d.outputContext.strategy;
  assert.equal(s.visualKind, "scene"); assert.match(s.narrative, /日常提问/);
  assert.match(s.adjustmentNote, /减少参数介绍/);
  assert.match(d.outputs["小红书"].body, /最近用电脑|减少参数罗列/);
  assert.deepEqual(d.outputs["小红书"].strategy, s);
});

test("empty and unsupported strategy adjustments leave the recommendation and edited copy intact", async () => {
  const b = browser(); await b.complete(); b.input("output-body", "原稿手工编辑"); await b.click("analysis");
  const before = b.state().draft;
  for (const text of ["", "改写为七言诗", "表达得更自然；加入没有依据的独家优惠"]) {
    b.node("#strategy-adjustment").value = text; await b.click("adjust-strategy"); assert.deepEqual(b.state().draft, before);
  }
  assert.match(b.node("#mc-toast").textContent, /规则|范围/);
  b.node("#strategy-adjustment").value = "更自然"; b.window.confirm = () => false; await b.click("adjust-strategy");
  assert.deepEqual(b.state().draft, before);
});

test("strategy field adjustments replace or clear context and never include old fields in the output brief", async () => {
  const b = browser(); b.input("mc-prompt", "面向大学生推广 MateBook 14，建立产品认知，用小红书"); await b.start(); await b.click("guide-strategies");
  b.node("#strategy-adjustment").value = "产品改为 MateBook X Pro；清空受众；清空平台；不要学习内容"; await b.click("adjust-strategy");
  await b.click("generate"); const d = b.state().draft;
  assert.equal(d.product, "matebook-x-pro"); assert.deepEqual(d.platforms, []); assert.equal(d.audience, "");
  assert.doesNotMatch(JSON.stringify(d.outputContext), /MateBook 14|大学生|小红书|学习用途/);
  assert.equal(d.activePlatform, "通用草稿");
});

test("single canvas and independent image or copy generation preserve unrelated manual edits", async () => {
  const b = browser(); await b.complete();
  const html = b.node("#mc-work-page").innerHTML;
  assert.equal((html.match(/class="mc-publication-preview"/g) || []).length, 1);
  assert.equal((html.match(/class="mc-result-poster"[\s\S]*?<img /g) || []).length, 1);
  assert.doesNotMatch(html, /策略与生成依据| · 配套内容/);
  assert.match(html, /<details class="mc-result-fact-details">/);
  b.input("output-title", "手写发布标题"); b.input("output-body", "我的手写正文");
  b.input("output-visual-headline", "我的图片主标题"); b.input("output-cta", "留言了解资料");
  const read = () => b.state().draft.outputs["微信朋友圈"];
  await b.click("choose-image", "altDialogue");
  const before = read();
  b.window.confirm = () => false; await b.click("regenerate-copy"); assert.deepEqual(read(), before);
  b.window.confirm = () => true; await b.click("regenerate-copy");
  const after = read();
  assert.notEqual(after.body, before.body);
  for (const key of ["visualSrc", "visualHeadline", "visualSubline", "strategy"]) assert.deepEqual(after[key], before[key]);
  await b.click("undo-copy");
  for (const key of ["title", "body", "cta"]) assert.equal(read()[key], before[key]);
  await b.click("change-image"); assert.notEqual(read().visualSrc, before.visualSrc);
  assert.equal(read().body, before.body); assert.equal(read().visualHeadline, before.visualHeadline);
  const restored = browser(b.state()); assert.equal(restored.state().draft.outputs["微信朋友圈"].body, before.body);
});

test("multi-image work stays one workbench and image operations leave copy untouched", async () => {
  const b = browser(); await b.complete();
  const originalBody = b.state().draft.outputs["微信朋友圈"].body;
  let output = b.state().draft.outputs["微信朋友圈"];
  assert.equal(output.imageMode, "multi"); assert.equal(output.images.length, 3);
  assert.equal(new Set(output.images.map(image => image.visualSrc)).size, 3);
  await b.click("select-result-image", "image-2");
  output = b.state().draft.outputs["微信朋友圈"];
  assert.equal(output.activeImageId, "image-2"); assert.equal(output.visualKind, output.images[1].visualKind);
  assert.equal(output.body, originalBody);
  await b.click("choose-image", "altScene");
  output = b.state().draft.outputs["微信朋友圈"];
  assert.equal(output.images[1].visualKind, "altScene"); assert.equal(output.images[0].visualKind, "scene");
  assert.equal(output.body, originalBody);
  await b.click("move-image-up"); assert.equal(b.state().draft.outputs["微信朋友圈"].images[0].id, "image-2");
  await b.click("remove-result-image"); assert.equal(b.state().draft.outputs["微信朋友圈"].images.length, 2);
  const reload = browser(b.state()).state().draft.outputs["微信朋友圈"];
  assert.equal(reload.images.length, 2); assert.equal(reload.body, originalBody);
});

test("changing the lead never rewrites manual results and regeneration uses the published output snapshot", async () => {
  const b = browser(); await b.complete(); b.input("output-body", "我的已编辑草稿");
  const original = b.state().draft.outputContext.strategy;
  await b.click("analysis");
  const other = b.window.MarketingPrototypeModel.strategyOptions(b.state().draft).find(s => s.id !== original.id);
  await b.click("strategy", other.id); b.window.confirm = () => false; await b.click("generate");
  assert.equal(b.state().draft.outputs["微信朋友圈"].body, "我的已编辑草稿");
  await b.click("results"); b.window.confirm = () => true; await b.click("regenerate");
  assert.deepEqual(b.state().draft.outputs["微信朋友圈"].strategy, original);
  const previousOutputs = b.state().draft.outputs;
  const previousRecordId = b.state().draft.recordId;
  await b.click("analysis"); await b.click("generate");
  assert.equal(b.state().draft.outputContext.strategy.id, other.id);
  assert.deepEqual(b.state().history.find(r => r.id === previousRecordId).draft.outputs, previousOutputs);
  assert.notEqual(b.state().draft.recordId, previousRecordId);
  assert.equal(b.state().history.some(r => Object.values(r.draft.outputs).some(o => o.strategy.id === other.id)), true);
});

test("placePosition maps bearing and distance proportionally around the store", () => {
  const model = browser().window.MarketingPrototypeModel;
  const store = { lat: 30.0, lng: 120.0 };
  const pos = style => Object.fromEntries(style.replace(/;$/, "").split(";").map(pair => pair.split(":")));
  const north = pos(model.placePosition({ lat: 30.01, lng: 120.0 }, store));
  const east = pos(model.placePosition({ lat: 30.0, lng: 120.01 }, store));
  const far = pos(model.placePosition({ lat: 30.1, lng: 120.0 }, store));
  assert.ok(Number(north.left.replace("%", "")) > 49 && Number(north.left.replace("%", "")) < 51);
  assert.ok(Number(north.top.replace("%", "")) < 50, "北侧地点应在门店上方");
  assert.ok(Number(east.left.replace("%", "")) > 50, "东侧地点应在门店右方");
  assert.ok(Number(east.top.replace("%", "")) > 49 && Number(east.top.replace("%", "")) < 51);
  assert.equal(far.top, "10.0%", "超过 2.5 公里应被钳制在外圈");
  assert.equal(far.left, "50.0%");
});

// ===== 地理信息契约 v0.1（docs/geo-api-contract-v0.1.json）：搜索 → 周边 → 地理上下文进聊天 =====
function contractPoi(id, name, category, lng, lat, distance_m) {
  return {
    poi_id: id, name, address: "合成地址（测试数据）",
    location: { lng, lat, coordinate_system: "GCJ-02" },
    type_code: "TEST", category, distance_m,
    source: { provider: "amap", queried_at: "2026-10-23T06:00:00Z", verification_scope: "provider_record_only", live: true }
  };
}
const flush = async (rounds = 6) => { for (let i = 0; i < rounds; i++) await new Promise(r => setImmediate(r)); };
async function openPlaceExplorer(b) {
  await b.clickPage("opportunities");
  await b.click("opportunity-focus-place", "local");
}

test("settings form persists store basics (location, landmarks, audience, platforms) across restore", async () => {
  const b = browser();
  await b.submit("store-form", { location: "杭州市西湖区示例商圈", landmarks: "示例大学旁", audience: "门店观察填写（待验证）", platforms: ["微信朋友圈", "小红书"] });
  assert.equal(b.state().store.location, "杭州市西湖区示例商圈");
  assert.equal(b.state().store.landmarks, "示例大学旁");
  assert.deepEqual(b.state().store.platforms, ["微信朋友圈", "小红书"]);
  const restored = browser(b.state());
  assert.equal(restored.state().store.location, "杭州市西湖区示例商圈");
  assert.equal(restored.state().store.platforms.length, 2);
});

test("place explorer starts with concept fallback before any geo search", async () => {
  const b = browser();
  await openPlaceExplorer(b);
  const html = b.node("#mc-work-page").innerHTML;
  assert.ok(html.includes("mc-geo-search"), "应出现契约搜索面板");
  assert.ok(html.includes("data:image/jpeg;base64,"), "初始态应直接展示城西银泰地图截图");
  assert.ok(html.includes("演示素材"));
  assert.ok(!html.includes("围绕这里策划"), "未选门店不应出现策划按钮");
});

test("demo geo flow: search demo data → select store → nearby categories → pick place → context enters chat", async () => {
  const b = browser();
  await openPlaceExplorer(b);
  await b.click("opportunity-demo-geo");
  let html = b.node("#mc-work-page").innerHTML;
  assert.ok(html.includes("SYNTHETIC_STORE_001"), "演示搜索应返回合成候选门店");
  assert.ok(html.includes("华为授权服务中心（城西银泰）"), "演示门店应为城西银泰华为店");
  await b.click("geo-select-store", "SYNTHETIC_STORE_001");
  await flush();
  html = b.node("#mc-work-page").innerHTML;
  for (const name of ["杭州绿城育华学校", "杭州电子商务产业园", "印象城"]) assert.ok(html.includes(name), `周边应包含 ${name}`);
  assert.ok(html.includes("data:image/jpeg;base64,"), "已选门店应展示地图截图（演示素材）");
  assert.ok(/left:\d+\.\d%/.test(html), "地图标记应按距离等比定位");
  assert.ok(html.includes("围绕这里策划"));
  await b.click("geo-toggle-nearby", "SYNTHETIC_SCHOOL_001");
  await b.click("geo-plan");
  await flush();
  assert.equal(b.state().page, "guide", "生成地理上下文后应进入聊天任务");
  const geo = b.state().draft.geo;
  assert.equal(geo.geo_context_id, "geo-context-demo-001");
  assert.equal(geo.scenarioInputs.store.geo_context_id, "geo-context-demo-001");
  assert.equal(geo.verification_scope, "provider_record_only");
  assert.equal(geo.demo, true);
  html = b.node("#mc-work-page").innerHTML;
  assert.ok(html.includes("scenario_inputs.store.geo_context_id"), "聊天页应展示将提交的载荷");
  assert.ok(html.includes("geo-context-demo-001"));
  assert.ok(html.includes("data:image/jpeg;base64,"), "聊天页上下文卡片应带门店地图截图");
});

test("geo search surfaces envelope error GEO_NOT_CONFIGURED in the panel", async () => {
  const fetchImpl = async () => ({ ok: false, status: 503, json: async () => ({ success: false, data: null, error: { code: "GEO_NOT_CONFIGURED", message: "地图服务未配置", retryable: false } }) });
  const b = browser(null, "2026-10-21T12:00:00", fetchImpl);
  await openPlaceExplorer(b);
  b.node("#mc-geo-city").value = "杭州";
  b.node("#mc-geo-keyword").value = "华为授权体验店";
  await b.click("geo-search");
  await flush();
  const html = b.node("#mc-work-page").innerHTML;
  assert.ok(html.includes("地图服务未配置或凭证无效"), "503 envelope 应转成可读提示");
  assert.ok(html.includes("geo-search-retry"), "应提供重试入口");
});

test("geo context GEO_CONTEXT_EXPIRED keeps the user on the explorer with a re-select hint", async () => {
  const store = contractPoi("TEST_STORE_001", "测试门店", "other", 120.1, 30.2, null);
  const nearbyByCat = {
    school: [contractPoi("TEST_SCHOOL_001", "测试学校", "school", 120.101, 30.201, 150)],
    office: [contractPoi("TEST_OFFICE_001", "测试写字楼", "office", 120.112, 30.205, 1100)],
    mall: [contractPoi("TEST_MALL_001", "测试商场", "mall", 120.098, 30.19, 1200)]
  };
  const ok = data => ({ ok: true, status: 200, json: async () => ({ success: true, data, error: null }) });
  const fetchImpl = async (url) => {
    if (url.startsWith("/api/geo/search")) return ok({ query_id: "q-search-1", expires_at: "2026-10-23T10:00:00Z", keyword: "华为", city: "杭州", page: 1, page_size: 10, has_more: false, items: [store], limitations: ["合成限制说明"] });
    if (url.startsWith("/api/geo/nearby")) { const cat = /category=([a-z]+)/.exec(url)[1]; return ok({ query_id: `q-nearby-${cat}`, expires_at: "2026-10-23T10:00:00Z", center: { ...store.location }, radius_m: 1500, category: cat, page: 1, page_size: 20, has_more: false, items: nearbyByCat[cat] || [], limitations: ["合成限制说明"] }); }
    if (url.startsWith("/api/geo/context")) return { ok: false, status: 410, json: async () => ({ success: false, data: null, error: { code: "GEO_CONTEXT_EXPIRED", message: "地点选择已过期", retryable: false } }) };
    throw new Error("unexpected url " + url);
  };
  const b = browser(null, "2026-10-21T12:00:00", fetchImpl);
  await openPlaceExplorer(b);
  b.node("#mc-geo-city").value = "杭州";
  b.node("#mc-geo-keyword").value = "华为授权体验店";
  await b.click("geo-search");
  await flush();
  assert.ok(b.node("#mc-work-page").innerHTML.includes("TEST_STORE_001"));
  await b.click("geo-select-store", "TEST_STORE_001");
  await flush();
  const html = b.node("#mc-work-page").innerHTML;
  assert.ok(html.includes("测试学校") && html.includes("GCJ-02"));
  await b.click("geo-toggle-nearby", "TEST_SCHOOL_001");
  await b.click("geo-plan");
  await flush();
  assert.equal(b.state().page, "opportunities", "410 时不应进入聊天");
  assert.ok(!b.state().draft.geo, "410 时不应写入地理上下文");
  assert.ok(b.node("#mc-work-page").innerHTML.includes("地点选择已过期，请重新查询并选择。"));
});
