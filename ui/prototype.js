(() => {
  "use strict";
  const D = window.MarketingPrototypeData;
  const KEY = "huawei-marketing-prototype-v1";
  const routes = ["home", "guide", "config", "analysis", "results", "settings", "history", "opportunities"];
  const platforms = ["微信朋友圈", "小红书", "公众号", "门店海报", "其他平台"];
  // 赛题平台形态规则：标题/篇幅/结构/语气/图片数量/行动引导随平台实质变化。
  const platformSpecs = {
    "微信朋友圈": { imageRange: [1, 3], imageLabel: "1-3 张", structure: "短文案、一个核心卖点、咨询或到店引导", poster: false },
    "小红书": { imageRange: [3, 6], imageLabel: "3-6 张", structure: "口语化标题、短段落、使用场景、话题标签", poster: false },
    "公众号": { imageRange: [2, 4], imageLabel: "2-4 张", structure: "标题、导语、分段正文、结尾行动引导", poster: false },
    "视频号": { imageRange: [1, 1], imageLabel: "封面 1 张", structure: "口播脚本与镜头顺序", poster: false },
    "门店海报": { imageRange: [1, 1], imageLabel: "主视觉 1 张", structure: "主标题、副标题、3 个以内卖点、活动说明", poster: true },
    "其他平台": { imageRange: [1, 3], imageLabel: "1-3 张", structure: "通用图文草稿", poster: false }
  };
  const platformSpec = name => platformSpecs[name] || platformSpecs["其他平台"];
  const fresh = () => ({ taskId: `task-${Date.now()}-${Math.random().toString(36).slice(2)}`, scene: "", creative: "", excludedScenes: [], fieldStatus: {}, short: false, noPrice: false, task: "seeding", prompt: "", product: "", platforms: ["微信朋友圈"], audience: "", goal: "", focus: "", tone: "自然真诚", extra: "", opportunity: null, strategyId: "", strategyContext: null, outputContext: null, strategyAdjustment: "", round: 0, adjustment: "", outputs: {}, complianceNotes: [], activePlatform: "微信朋友圈", facts: {}, revision: 0, generationRound: 0, recordId: null });
  let state = { version: 1, page: "home", draft: fresh(), guide: null, store: { location: "", landmarks: "", audience: "", city: "", address: "", lat: "", lng: "", geoSource: "", platforms: ["微信朋友圈"] }, history: [], opportunityExplorer: { month: "", selectedDate: "", mapFilter: "all", selectedPlace: "", selectedOpportunity: "", activeView: "", geo: null } };
  let lastGuideEvents = null;
  let homePlatformMenuOpen = false;
  let storageWarning = false;
  try {
    const saved = JSON.parse(localStorage.getItem(KEY));
    if (saved?.version === 1) {
      state = { ...state, ...saved, draft: { ...fresh(), ...saved.draft }, store: { ...state.store, ...saved.store }, opportunityExplorer: { ...state.opportunityExplorer, ...saved.opportunityExplorer } };
      if (state.page === "config" && saved.page === "config") state.page = "guide";
      if (!Array.isArray(state.history)) state.history = [];
      if (!D.tasks.some(t => t.id === state.draft.task)) state.draft.task = "seeding";
      if (!Array.isArray(state.draft.platforms)) state.draft.platforms = ["微信朋友圈"];
      state.draft.platforms = state.draft.platforms.filter(p => platforms.includes(p));
      if (!Array.isArray(state.store.platforms)) state.store.platforms = ["微信朋友圈"];
      if (state.guide) { delete state.guide.thinking; state.guide.events?.forEach(event => { if (event && typeof event.response !== "string") delete event.response; }); }
    }
  } catch { storageWarning = true; }
  state.homePrompt ??= state.draft.opportunity ? "" : state.draft.prompt;
  // Homepage configuration is independent of answers in an existing task.
  state.homeProduct = D.products.some(p => p.id === state.homeProduct) ? state.homeProduct : "";
  state.homeProductDeferred = Boolean(state.homeProductDeferred);
  let homeProductQuery = "";
  const $ = (s) => document.querySelector(s);
  const esc = (s = "") => String(s).replace(/[&<>"']/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
  const paths = { "panels-top-left": '<rect x="3" y="3" width="18" height="18" rx="2"/><path d="M3 9h18M9 9v12"/>', "pen-line": '<path d="m16 3 5 5-12 12-6 1 1-6ZM14 5l5 5M12 21h9"/>', "folder-open": '<path d="M3 7V5h6l2 2h9v4M3 11h19l-3 9H3Z"/>', "compass": '<circle cx="12" cy="12" r="9"/><path d="m16 8-2 6-6 2 2-6Z"/>', "settings": '<path d="m9 3-1 3-3 1v4l-2 1 2 2v3l3 1 1 3h6l1-3 3-1v-3l2-2-2-1V7l-3-1-1-3Z"/><circle cx="12" cy="12" r="3"/>', "laptop": '<rect x="4" y="3" width="16" height="13" rx="2"/><path d="m4 16-3 5h22l-3-5"/>', "arrow-up-right": '<path d="M7 17 17 7M7 7h10v10"/>', "arrow-left": '<path d="m10 5-7 7 7 7M3 12h18"/>', "shield-check": '<path d="m12 2 9 4v6c0 5-9 10-9 10S3 17 3 12V6Z"/><path d="m8 12 3 3 5-6"/>', "sparkles": '<path d="m12 3 2.5 6.5L21 12l-6.5 2.5L12 21l-2.5-6.5L3 12l6.5-2.5ZM20 2v4M18 4h4"/>', "badge-plus": '<rect x="4" y="4" width="16" height="16" rx="4"/><path d="M12 8v8M8 12h8"/>', "map-pin": '<path d="M20 10c0 6-8 12-8 12S4 16 4 10a8 8 0 0 1 16 0Z"/><circle cx="12" cy="10" r="3"/>', "calendar-days": '<rect x="3" y="5" width="18" height="16" rx="2"/><path d="M7 3v4M17 3v4M3 11h18M7 15h3M14 15h3"/>', "check": '<path d="m5 12 4 4L19 6"/>', "chevron-down": '<path d="m6 9 6 6 6-6"/>', "copy": '<rect x="8" y="8" width="13" height="13" rx="2"/><path d="M16 8V3H3v13h5"/>', "download": '<path d="M12 3v12m-5-5 5 5 5-5M4 17v4h16v-4"/>', "refresh-cw": '<path d="M21 4v6h-6M3 20v-6h6M4 9a8 8 0 0 1 13-5l4 6M3 14l4 6a8 8 0 0 0 13-5"/>' };
  const icon = name => `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">${paths[name] || paths["sparkles"]}</svg>`;
  const button = (label, action, cls = "mc-secondary", attrs = "") => `<button type="button" class="${cls}" data-action="${action}" ${attrs}>${label}</button>`;
  const task = () => D.tasks.find(t => t.id === state.draft.task);
  const product = () => D.products.find(p => p.id === state.draft.product);
  function inferredAudience(d = state.draft) {
    if (d.audience?.trim()) return d.audience.trim();
    if (d.opportunity) return "受众尚未确认，需通过实际用途收集线索";
    return "受众尚未确认，需通过实际用途收集线索";
  }
  function audienceLabel(d = state.draft) {
    const value = inferredAudience(d);
    return /待验证/.test(value) ? value : `${value}（待验证）`;
  }
  let navigationReady = false;
  const routeSnapshot = () => ({ marketingPrototype: true, page: state.page, draft: JSON.parse(JSON.stringify(state.draft)), guide: state.guide ? JSON.parse(JSON.stringify(state.guide)) : null, opportunityExplorer: JSON.parse(JSON.stringify(state.opportunityExplorer)) });
  const save = () => { try { localStorage.setItem(KEY, JSON.stringify(state)); if (navigationReady && location.hash === `#${state.page}`) history.replaceState(routeSnapshot(), "", location.hash); } catch { if (!storageWarning) toast("浏览器无法保存本地状态，请导出重要成果。"); storageWarning = true; } };
  let toastTimer;
  function toast(message) { const el = $("#mc-toast"); el.textContent = message; el.classList.add("visible"); clearTimeout(toastTimer); toastTimer = setTimeout(() => el.classList.remove("visible"), 3500); }
  function invalidate() { state.draft.strategyId = ""; state.draft.strategyContext = null; state.draft.outputContext = null; state.draft.outputs = {}; delete state.draft.previousOutputs; state.draft.recordId = null; state.draft.facts = {}; }
  // Calendar days, rather than elapsed milliseconds, keep date boundaries stable across DST.
  function calendarDay(value = new Date()) {
    const key = typeof value === "string" ? value : `${value.getFullYear()}-${String(value.getMonth() + 1).padStart(2, "0")}-${String(value.getDate()).padStart(2, "0")}`;
    if (!/^\d{4}-\d{2}-\d{2}$/.test(key)) return NaN;
    const [y, m, d] = key.split("-").map(Number), date = new Date(Date.UTC(y, m - 1, d));
    return date.toISOString().slice(0, 10) === key ? date.getTime() / 86400000 : NaN;
  }
  function opportunityState(o, now = new Date()) {
    const today = calendarDay(now), start = calendarDay(o.displayStart), windowStart = calendarDay(o.windowStart), end = calendarDay(o.validUntil);
    if (![today, start, windowStart, end].every(Number.isFinite) || start > windowStart || windowStart > end || !Number.isInteger(o.preparationDays) || o.preparationDays < 0) return null;
    if (today < start || today > end || !o.actionable) return null;
    const phase = today >= windowStart ? "current" : today >= windowStart - o.preparationDays ? "preparing" : "ahead";
    const status = o.verification !== "ready" ? "部分信息待确认" : phase === "current" ? "近期值得关注" : "建议提前准备";
    return { ...o, phase, status, daysUntil: Math.max(0, windowStart - today) };
  }
  function eligibleOpportunities(items, now = new Date()) {
    // Prefer a concrete, near-term opportunity over a generic conversion prompt.
    // Missing store configuration deliberately lowers local-scene candidates.
    const priority = o => {
      if (!o.type) return [o.verification === "ready" ? 0 : 1, o.phase === "current" ? 0 : 1, o.relevance === "high" ? 0 : 1, o.storeFit ? 0 : 1];
      const nearDate = o.type === "时间节点" && o.verification === "ready" && (o.phase !== "ahead" || o.daysUntil <= 21);
      const configuredScene = o.type === "门店场景" && o.storeFit && o.verification === "ready";
      const productBasis = o.type === "产品探索" && o.verification === "ready";
      return [nearDate ? 0 : configuredScene ? 1 : productBasis ? 2 : 3, o.verification === "ready" ? 0 : 1, o.daysUntil, o.id];
    };
    return items.map(o => opportunityState(o, now)).filter(Boolean).sort((a, b) => {
      const ap = priority(a), bp = priority(b);
      for (let i = 0; i < ap.length; i++) if (ap[i] !== bp[i]) return typeof ap[i] === "number" ? ap[i] - bp[i] : String(ap[i]).localeCompare(String(bp[i]));
      return 0;
    });
  }
  function opportunityList(now = new Date()) {
    const candidates = D.opportunities.map(o => {
      if (o.id !== "local" || !state.store.location.trim()) return o;
      const place = state.store.landmarks.trim(), campus = /高校|大学|学院|学校/.test(place), office = /写字楼|园区|办公/.test(place);
      return { ...o, title: campus ? "探索周边学习人群的设备需求" : office ? "探索周边办公人群的设备需求" : o.title, evidence: `已知（门店填写）：${state.store.location}${place ? `；附近地标：${place}` : "；尚未填写地标"}。推断：可能存在相关使用场景。待验证：实际客群、购买需求及效果。`, direction: campus ? "探索课程学习场景（待门店验证），先收集用途再核实产品适配性。" : office ? "探索移动办公场景（待门店验证），先收集用途再核实产品适配性。" : o.direction };
    });
    return eligibleOpportunities(candidates.map(o => o.id === "local" && !state.store.location.trim() ? { ...o, storeFit: false, relevance: "low", evidence: "尚未填写门店位置或地标；当前只保留为通用场景示意，不对周边客群作判断。" } : o), now);
  }
  function dailyOpportunity(items, now = new Date()) {
    if (!items.length) return null;
    // Keep the recommendation stable while the same opportunity remains valid.
    // Rotation is explicit through "换一条推荐", never caused by the calendar day.
    return items[0];
  }
  function monthKey(value = new Date()) {
    const date = value instanceof Date ? value : new Date(value);
    return `${date.getFullYear()}-${String(date.getMonth() + 1).padStart(2, "0")}`;
  }
  function monthDate(key) {
    const [year, month] = String(key || monthKey()).split("-").map(Number);
    return new Date(year, month - 1, 1);
  }
  function opportunityExplorerItems() {
    // Keep the explorer and homepage recommendation on the same eligible source.
    return opportunityList();
  }
  function opportunityDate(o) { return o?.windowStart || o?.displayStart || ""; }
  function placeTypeLabel(type) { return ({ school: "学校", business: "办公区", shopping: "商圈" })[type] || "其他"; }
  const opportunityTypeLabel = t => ({ "产品探索": "真实场景", "门店场景": "门店周边" })[t] || t;
  // ===== 地图接口 provider：三个接口与字段名严格对齐 docs/geo-api-contract-v0.1.json（后端 A v0.1 草案）=====
  // 对齐约定：坐标统一 GCJ-02；经纬度字段叫 lng/lat；距离单位米；响应 envelope 为 {success, data, error}。
  const GEO_CATEGORY_LABELS = { school: "学校", office: "办公楼", mall: "商场", residential: "住宅", transit: "交通站点", other: "其他" };
  const GEO_RADIUS_OPTIONS = [500, 1000, 1500, 2000, 3000, 5000];
  const GEO_NEARBY_MAX = 10;
  const GEO_LIMITATIONS_FALLBACK = ["地图地点记录不代表实时营业或官方认证。", "周边距离为直线距离，非步行距离；不代表客流或购买意愿。"];
  function geoDemoMode() { return typeof location !== "undefined" && /demo-geo/.test(location.search || ""); }
  function geoQueryString(params) {
    return Object.entries(params).filter(([, v]) => v !== undefined && v !== null && v !== "").map(([k, v]) => `${k}=${encodeURIComponent(v)}`).join("&");
  }
  class GeoApiError extends Error {
    constructor(status, code, message, retryable) { super(message); this.name = "GeoApiError"; this.status = status; this.code = code; this.retryable = Boolean(retryable); }
  }
  function geoErrorMessage(e) {
    if (e instanceof GeoApiError) {
      if (e.code === "GEO_CONTEXT_EXPIRED") return "地点选择已过期，请重新查询并选择。";
      if (e.code === "GEO_NOT_CONFIGURED" || e.code === "GEO_PROVIDER_AUTH_FAILED") return "地图服务未配置或凭证无效（后端环境变量），可先用演示数据体验。";
      if (e.code === "GEO_RATE_LIMITED") return "地图查询过于频繁，请稍后重试。";
      if (e.code === "GEO_TIMEOUT") return "地图服务请求超时，请重试。";
      return e.message || "地图服务暂时不可用。";
    }
    return "网络异常，地图服务暂时不可用。";
  }
  async function geoRequest(path, params, { method = "GET", body } = {}) {
    if (typeof fetch !== "function") throw new GeoApiError(0, "GEO_FETCH_UNAVAILABLE", "当前环境不支持网络请求", true);
    const qs = method === "GET" ? geoQueryString(params || {}) : "";
    const res = await fetch(qs ? `${path}?${qs}` : path, method === "GET" ? {} : { method, headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
    let payload = null;
    try { payload = await res.json(); } catch { /* 非 JSON 响应按上游错误处理 */ }
    if (!res.ok || !payload || payload.success !== true || !payload.data) {
      const e = payload?.error || {};
      throw new GeoApiError(res.status, e.code || `HTTP_${res.status}`, e.message || "地图服务暂时不可用", e.retryable);
    }
    return payload.data;
  }
  function demoExpiry() { return new Date(Date.now() + 2 * 60 * 60 * 1000).toISOString(); }
  function demoGeoSearch(keyword, city) {
    const D0 = D.demoGeo;
    return { query_id: "geo-query-demo-store", expires_at: demoExpiry(), keyword: keyword || "华为授权服务中心（城西银泰）", city: city || "杭州", page: 1, page_size: 10, has_more: false, items: [JSON.parse(JSON.stringify(D0.store))], limitations: [...D0.limitations] };
  }
  function demoGeoNearby(category, radius) {
    const D0 = D.demoGeo;
    return { query_id: `geo-query-demo-${category}`, expires_at: demoExpiry(), center: { ...D0.store.location }, radius_m: radius || 1500, category, page: 1, page_size: 20, has_more: false, items: (D0.nearby[category] || []).map(p => JSON.parse(JSON.stringify(p))), limitations: [...D0.limitations] };
  }
  function demoGeoContext(storeRef, nearbyRefs) {
    const D0 = D.demoGeo;
    const find = (ref) => ref.query_id === "geo-query-demo-store" ? D0.store : (D0.nearby[ref.query_id.replace("geo-query-demo-", "")] || []).find(p => p.poi_id === ref.poi_id);
    return {
      geo_context_id: "geo-context-demo-001", expires_at: demoExpiry(),
      store: JSON.parse(JSON.stringify(find(storeRef) || D0.store)),
      nearby_places: (nearbyRefs || []).map(r => find(r)).filter(Boolean).map(p => JSON.parse(JSON.stringify(p))),
      selection_source: "user_selection", selected_at: new Date().toISOString(), limitations: [...D0.limitations]
    };
  }
  // 演示数据来源：URL 带 ?demo-geo，或用户在周边场景页点了「使用演示数据」（g.demo）
  function geoApiDemo() { return geoDemoMode() || Boolean(geoState().demo); }
  async function searchStoresApi({ keyword, city, page = 1 }) {
    if (geoApiDemo()) return demoGeoSearch(keyword, city);
    return geoRequest("/api/geo/search", { keyword, city, page, page_size: 10 });
  }
  async function fetchNearbyApi({ lng, lat, radius, category, page = 1 }) {
    if (geoApiDemo()) return demoGeoNearby(category, radius);
    return geoRequest("/api/geo/nearby", { lng, lat, radius, category, page, page_size: 20 });
  }
  async function createGeoContextApi({ storeRef, nearbyRefs }) {
    if (geoApiDemo()) return demoGeoContext(storeRef, nearbyRefs);
    return geoRequest("/api/geo/context", {}, { method: "POST", body: { store_ref: storeRef, nearby_refs: nearbyRefs } });
  }
  async function geoFetchNearbyCategory(category) {
    const g = geoState();
    const store = g.store;
    if (!store) return;
    g.nearbyByCat[category] = { status: "loading", error: "", data: null };
    try {
      const data = await fetchNearbyApi({ lng: store.location.lng, lat: store.location.lat, radius: g.radius, category });
      const g1 = geoState();
      g1.nearbyByCat[category] = { status: "done", error: "", data: { ...data, items: (data.items || []).map(p => ({ ...p, query_id: data.query_id })) } };
    } catch (e) {
      const g1 = geoState();
      g1.nearbyByCat[category] = { status: "error", error: geoErrorMessage(e), data: null };
    }
    save(); if (state.page === "opportunities") render();
  }
  // 地理上下文进入聊天：写入 draft.geo，随后由 understand/continue 以 scenario_inputs 提交（见契约 x-existing-chat-integration）。
  function geoEnterChat(ctx, demo) {
    state.draft.geo = {
      geo_context_id: ctx.geo_context_id,
      store: { name: ctx.store?.name || "", address: ctx.store?.address || "" },
      nearby: (ctx.nearby_places || []).map(p => ({ name: p.name, category: p.category, distance_m: p.distance_m })),
      limitations: ctx.limitations || [],
      provider: ctx.store?.source?.provider || "amap",
      queried_at: ctx.store?.source?.queried_at || "",
      verification_scope: ctx.store?.source?.verification_scope || "provider_record_only",
      scenarioInputs: { store: { geo_context_id: ctx.geo_context_id } },
      mapShot: demo ? D.demoGeo.mapShot : "",
      mapShotCaption: demo ? D.demoGeo.mapShotCaption : "",
      demo: Boolean(demo)
    };
    const o = opportunityList().find(x => x.id === "local");
    const nearbyNames = state.draft.geo.nearby.map(p => p.name).join("、");
    const source = o ? { ...o, evidence: `地点来自地图检索快照（${state.draft.geo.provider}，${state.draft.geo.queried_at}，${state.draft.geo.verification_scope}）：门店「${state.draft.geo.store.name}」${nearbyNames ? `；周边 ${nearbyNames}` : ""}。仅为地点记录，不代表客流、购买意愿或官方认证。`, direction: `${nearbyNames ? `可围绕 ${nearbyNames} 等周边地点探索推广主题` : "可围绕门店所在位置探索推广主题"}（地点为检索快照，实际客群需门店观察确认）。`, unknown: "门店实际客群、客流、购买意愿与门店可提供服务均需核实。" } : null;
    state.draft.opportunity = source;
    state.draft.task = source?.task || "seeding";
    state.draft.prompt = state.homePrompt || source?.direction || "";
    state.guide = G.create(state.homePrompt, homeProductSeed());
    state.guide.defaultPlatforms = [...(state.store.platforms.length ? state.store.platforms : ["微信朋友圈"])];
    navigate("guide");
    toast(demo ? "已生成演示地理上下文并进入聊天（模拟提交）。" : "地理上下文已生成，已进入聊天任务。");
  }
  // 聊天页展示的地理上下文卡片
  function geoContextCard(draft = state.draft) {
    const geo = draft?.geo;
    if (!geo) return "";
    const nearby = geo.nearby?.length ? geo.nearby.map(p => `${esc(p.name)}（${esc(GEO_CATEGORY_LABELS[p.category] || "其他")}${Number.isFinite(Number(p.distance_m)) ? ` · ${esc(geoDistanceText(p.distance_m))}` : ""}）`).join("、") : "未选周边地点";
    const shot = geo.mapShot ? `<figure class="mc-geo-shot mc-geo-context-shot"><img src="${esc(geo.mapShot)}" alt="${esc(geo.mapShotCaption || "门店地图截图")}" loading="lazy"><figcaption>${esc(geo.mapShotCaption || "门店地图截图（演示素材）")}</figcaption></figure>` : "";
    return `<div class="mc-geo-context" data-demo="${geo.demo ? "1" : ""}"><div class="mc-geo-context-head">${icon("map-pin")}<strong>门店地理上下文</strong><span class="mc-tag">${esc(geo.geo_context_id)}${geo.demo ? " · 演示" : ""}</span></div>${shot}<dl class="mc-definition"><dt>门店</dt><dd>${esc(geo.store.name)}${geo.store.address ? ` · ${esc(geo.store.address)}` : ""}</dd><dt>周边地点</dt><dd>${nearby}</dd><dt>来源与时效</dt><dd>${esc(geo.provider)} · ${esc(geo.queried_at)} · ${esc(geo.verification_scope)}；过期后任务内已保存的地点不消失</dd><dt>提交载荷</dt><dd><code>scenario_inputs.store.geo_context_id = "${esc(geo.geo_context_id)}"</code></dd></dl><p class="mc-muted">${(geo.limitations || []).map(x => `· ${esc(x)}`).join(" ")}</p></div>`;
  }
  // ===== 周边场景交互状态 =====
  function freshGeoState() {
    return { keyword: "", city: "", searchStatus: "idle", searchError: "", searchResult: null, selectedStorePoiId: "", store: null, radius: 1500, activeCategories: ["school", "office", "mall"], nearbyByCat: {}, selectedNearby: [], contextStatus: "idle", contextError: "", geoContext: null, demo: false };
  }
  function geoState() { const d = state.opportunityExplorer; if (!d.geo || typeof d.geo !== "object") d.geo = freshGeoState(); return d.geo; }
  function geoAllNearby(g) { return Object.values(g.nearbyByCat || {}).flatMap(x => (x.data?.items) || []); }
  function geoContextExpired(g) { return Boolean(g.geoContext?.expires_at && new Date(g.geoContext.expires_at).getTime() < Date.now()); }
  // 距离格式化：米 → 约 xxx 米 / 约 x.x 公里
  function geoDistanceText(distance_m) {
    const d = Number(distance_m);
    if (!Number.isFinite(d)) return "距离未知";
    return d < 1000 ? `约 ${Math.round(d / 10) * 10} 米` : `约 ${Math.round(d / 100) / 10} 公里`;
  }
  // 地图等比定位（沿用：方位角 + 距离，2.5 公里映射外圈；GCJ-02 相对偏移不受坐标系常量偏移影响）
  function placePosition(place, store) {
    const lat1 = +store.lat || 0, lng1 = +store.lng || 0, lat2 = +place.lat || lat1, lng2 = +place.lng || lng1;
    const dy = (lat2 - lat1) * 111000, dx = (lng2 - lng1) * 111000 * Math.cos(lat1 * Math.PI / 180);
    const dist = Math.hypot(dx, dy), angle = Math.atan2(dx, dy);
    const r = Math.min(dist / 2500, 1) * 45;
    const x = Math.min(Math.max(50 + r * Math.sin(angle), 6), 94), y = Math.min(Math.max(50 - r * Math.cos(angle), 10), 90);
    return `left:${x.toFixed(1)}%;top:${y.toFixed(1)}%`;
  }
  const mockPlaces = D.opportunityPlaces || [];
  function opportunityExplorerPage() {
    const d = state.opportunityExplorer || (state.opportunityExplorer = { month: "", selectedDate: "", mapFilter: "all", selectedPlace: "", selectedOpportunity: "", activeView: "" });
    d.activeView = d.activeView || "";
    const today = new Date(), todayKey = `${monthKey(today)}-${String(today.getDate()).padStart(2, "0")}`;
    // Time nodes are windows, not single days; the calendar shows the whole annual sample calendar.
    const allDateItems = D.opportunities.filter(o => o.type === "时间节点").map(o => ({ ...o, ...(opportunityState(o) || {}) }));
    const inWindow = (o, key) => o.windowStart <= key && key <= (o.windowEnd || o.windowStart);
    // First visit lands on the nearest upcoming window instead of an empty "today".
    if (!d.activeView && !d.selectedDate) {
      const upcoming = allDateItems.filter(o => o.windowStart >= todayKey).sort((a, b) => a.windowStart < b.windowStart ? -1 : 1)[0];
      if (upcoming) d.month = upcoming.windowStart.slice(0, 7);
    }
    const currentMonth = d.month || monthKey(today), date = monthDate(currentMonth);
    d.month = currentMonth;
    const items = opportunityExplorerItems(), dateItems = allDateItems.filter(o => o.windowStart.slice(0, 7) === currentMonth);
    const selectedDate = d.selectedDate || (dateItems.find(o => o.windowStart >= todayKey) || dateItems[0] || { windowStart: todayKey }).windowStart;
    d.selectedDate = selectedDate;
    const selectedDateItem = dateItems.find(o => inWindow(o, selectedDate)) || null;
    const firstDay = new Date(date.getFullYear(), date.getMonth(), 1).getDay();
    const days = new Date(date.getFullYear(), date.getMonth() + 1, 0).getDate();
    const cells = Array.from({ length: firstDay + days }, (_, i) => {
      if (i < firstDay) return "<span class=\"mc-calendar-empty\" aria-hidden=\"true\"></span>";
      const day = i - firstDay + 1, key = `${currentMonth}-${String(day).padStart(2, "0")}`, match = dateItems.find(o => o.windowStart === key), rangeOnly = !match && dateItems.some(o => o.windowStart < key && key <= (o.windowEnd || o.windowStart));
      return `<button type=\"button\" class=\"mc-calendar-day ${key === selectedDate ? "is-selected" : ""} ${match ? "has-opportunity" : ""} ${rangeOnly ? "is-range" : ""}\" data-action=\"opportunity-date\" data-id=\"${key}\"><span>${day}</span>${match ? `<i>${esc(opportunityTypeLabel(match.type))}</i>` : ""}</button>`;
    }).join("");
    // ===== 概念示意（未走搜索流程时的降级展示）=====
    const filter = d.mapFilter || "all";
    const visiblePlaces = mockPlaces.filter(p => filter === "all" || p.type === filter), selectedPlace = visiblePlaces.find(p => p.id === d.selectedPlace) || visiblePlaces[0] || null;
    const conceptBadge = p => p.type === "school" ? "学" : p.type === "business" ? "办" : "商";
    const placeChips = visiblePlaces.length ? `<div class="mc-place-chips" role="list">${visiblePlaces.map(p => `<button type="button" role="listitem" class="mc-place-chip ${p.id === selectedPlace?.id ? "is-active" : ""}" data-action="opportunity-place" data-id="${p.id}\"><span class="mc-place-chip-badge ${esc(p.type)}">${conceptBadge(p)}</span><strong>${esc(p.name)}</strong><small>${esc(p.direction || "概念地点")}</small></button>`).join("")}</div>` : "";
    // ===== 真实流程（契约 v0.1）：搜索门店 → 周边分类/半径 → 选择地点 → 地理上下文进聊天 =====
    const g = geoState();
    const geoBadge = p => ({ school: "学", office: "办", mall: "商", residential: "住", transit: "交" })[p.category] || "地";
    const geoSelectedSet = new Set(g.selectedNearby);
    const searchPanel = `<div class="mc-geo-search"><div class="mc-geo-search-row"><label class="mc-field"><span>城市</span><input id="mc-geo-city" value="${esc(g.city)}" placeholder="例如：杭州" maxlength="100" autocomplete="off"></label><label class="mc-field mc-geo-search-keyword"><span>门店或地点名称</span><input id="mc-geo-keyword" value="${esc(g.keyword)}" placeholder="例如：华为授权体验店" maxlength="100" autocomplete="off"></label>${button(g.searchStatus === "loading" ? "搜索中…" : "搜索门店", "geo-search", "mc-primary", g.searchStatus === "loading" ? "disabled" : "")}</div><div class="mc-geo-search-tools">${button("使用演示数据", "opportunity-demo-geo", "mc-link")}<span class="mc-muted">只查询、不修改任务；坐标统一 GCJ-02，距离单位米；不获取浏览器实时定位。</span></div>${g.searchStatus === "error" ? `<div class="mc-geo-error" role="alert">${esc(g.searchError)} ${button("重试", "geo-search-retry", "mc-link")}</div>` : ""}</div>`;
    const candidates = g.searchResult?.items?.length ? `<div class="mc-geo-candidates" role="radiogroup" aria-label="候选门店">${g.searchResult.items.map(p => `<button type="button" role="radio" aria-checked="${p.poi_id === g.selectedStorePoiId}" class="mc-geo-candidate ${p.poi_id === g.selectedStorePoiId ? "is-active" : ""}" data-action="geo-select-store" data-id="${esc(p.poi_id)}"><strong>${esc(p.name)}</strong><span>${esc(p.address || "地址未提供")}</span><small>${esc(p.location.lng)}, ${esc(p.location.lat)}（GCJ-02） · 来源 ${esc(p.source?.provider || "未知")} · 快照 ${esc(g.searchResult.query_id)} · 过期 ${esc(g.searchResult.expires_at || "未知")}</small></button>`).join("")}</div>` : g.searchStatus === "done" ? `<div class="mc-geo-empty">没有找到匹配的门店，请换个关键字或城市。</div>` : "";
    const storeShot = g.store && g.demo && D.demoGeo.mapShot ? `<figure class="mc-geo-shot"><img src="${esc(D.demoGeo.mapShot)}" alt="${esc(D.demoGeo.mapShotCaption || "门店地图截图")}" loading="lazy"><figcaption>${esc(D.demoGeo.mapShotCaption || "门店地图截图（演示素材）")} · 定位与周边距离以下方演示数据为准</figcaption></figure>` : "";
    const storeBlock = g.store ? `<div class="mc-geo-store"><span class="mc-tag">已选门店 · ${esc(g.demo ? "演示模拟数据" : "地图检索")}</span><strong>${esc(g.store.name)}</strong><span class="mc-muted">${esc(g.store.address || "")} · ${esc(g.store.location.lng)}, ${esc(g.store.location.lat)}（GCJ-02）</span>${storeShot}</div>` : "";
    const radiusChips = g.store ? `<div class="mc-map-filters mc-geo-radius" role="group" aria-label="半径">${GEO_RADIUS_OPTIONS.map(r => button(r < 1000 ? `${r} 米` : `${r / 1000} 公里`, "geo-radius", `mc-link ${r === g.radius ? "is-active" : ""}`, `data-id="${r}"`)).join("")}</div>` : "";
    const categoryChips = g.store ? `<div class="mc-map-filters" role="group" aria-label="周边分类">${Object.entries(GEO_CATEGORY_LABELS).filter(([k]) => k !== "other").map(([value, label]) => { const st = g.nearbyByCat[value]?.status; return button(`${label}${st === "loading" ? "…" : st === "error" ? "（失败）" : ""}`, "geo-category", `mc-link ${g.activeCategories.includes(value) ? "is-active" : ""}`, `data-id="${value}"`); }).join("")}</div>` : "";
    const nearbyErrors = g.store ? Object.entries(g.nearbyByCat).filter(([, x]) => x.status === "error").map(([cat, x]) => `<div class="mc-geo-error" role="alert">${esc(GEO_CATEGORY_LABELS[cat] || cat)}：${esc(x.error)} ${button("重试", "geo-category-retry", "mc-link", `data-id="${esc(cat)}"`)}</div>`).join("") : "";
    const allNearby = geoAllNearby(g);
    const visibleNearby = g.store ? allNearby.filter(p => g.activeCategories.includes(p.category)) : [];
    const storeGeoForMap = g.store ? { lat: g.store.location.lat, lng: g.store.location.lng } : null;
    const realMarkers = g.store ? visibleNearby.map(p => `<button type=\"button\" class=\"mc-map-marker ${geoSelectedSet.has(p.poi_id) ? "is-selected" : ""}\" data-action=\"geo-toggle-nearby\" data-id=\"${esc(p.poi_id)}\" style=\"${placePosition({ lat: p.location.lat, lng: p.location.lng }, storeGeoForMap)}\" aria-label=\"${esc(p.name)}\" aria-pressed=\"${geoSelectedSet.has(p.poi_id)}\"><span class=\"mc-cat-${esc(p.category)}\">${geoBadge(p)}</span><small>${esc(p.name)}</small></button>`).join("") : "";
    const nearbyList = g.store ? `<div class="mc-geo-nearby-head"><strong>周边地点</strong><span class="mc-muted">点选加入策划（最多 ${GEO_NEARBY_MAX} 个）· 距离为直线距离</span></div><div class="mc-place-chips" role="list">${visibleNearby.map(p => `<button type="button" role="listitem" class="mc-place-chip ${geoSelectedSet.has(p.poi_id) ? "is-active" : ""}" data-action="geo-toggle-nearby" data-id="${esc(p.poi_id)}" aria-pressed=\"${geoSelectedSet.has(p.poi_id)}\"><span class="mc-place-chip-badge ${esc(p.category)}">${geoBadge(p)}</span><strong>${esc(p.name)}</strong><small>${geoDistanceText(p.distance_m)} · ${esc(GEO_CATEGORY_LABELS[p.category] || "其他")}</small></button>`).join("") || `<p class="mc-muted">该范围内暂无地点，可调整半径或分类。</p>`}</div>` : "";
    const contextExpired = g.store && g.geoContext && geoContextExpired(g);
    const planDisabled = !g.store || g.contextStatus === "loading" || Boolean(g.geoContext && !contextExpired);
    const planBlock = g.store ? `<div class="mc-geo-plan"><div class="mc-geo-plan-head"><strong>已选 ${g.selectedNearby.length}/${GEO_NEARBY_MAX} 个周边地点</strong><span class="mc-muted">门店与选中地点将作为服务端地理上下文（geo_context_id）进入聊天任务；不会自动推断客流或购买意愿。</span></div>${g.contextStatus === "error" ? `<div class="mc-geo-error" role="alert">${esc(g.contextError)}</div>` : ""}${contextExpired ? `<div class="mc-geo-error" role="alert">地点选择已过期，请重新查询并选择。</div>` : ""}<div class="mc-geo-plan-actions">${button(g.contextStatus === "loading" ? "正在生成地理上下文…" : "围绕这里策划", "geo-plan", "mc-primary", planDisabled ? "disabled" : "")}${g.geoContext ? `<span class="mc-muted">已生成 ${esc(g.geoContext.geo_context_id)}${g.demo ? "（演示）" : ""} · 过期时间 ${esc(g.geoContext.expires_at || "未知")}</span>` : ""}</div></div>` : "";
    const limitationsNote = g.store ? `<p class="mc-muted mc-geo-limitations">${(Object.values(g.nearbyByCat).map(x => x.data?.limitations).find(l => l?.length) || D.demoGeo.limitations).map(x => `· ${esc(x)}`).join(" ")}</p>` : "";
    const mapStatus = g.store ? `已选门店：${g.store.name} · 半径 ${g.radius} 米 · ${g.demo ? "演示模拟数据" : "地图检索数据 provider_record_only"}` : "搜索门店后展示真实周边分布；当前为城西银泰门店地图截图（演示素材）";
    const mapScale = g.store ? `<span class="mc-map-scale">按实际距离等比示意 · 外圈约 2.5 公里</span>` : "";
    const dateDetail = selectedDateItem ? `<div class=\"mc-opportunity-detail\"><div><span class=\"mc-tag\">时间节点 · ${esc(selectedDateItem.status || "样例排期")}</span><h3>${esc(selectedDateItem.title)}</h3><p class=\"mc-detail-date\">${esc(selectedDateItem.windowStart)}${selectedDateItem.windowEnd && selectedDateItem.windowEnd !== selectedDateItem.windowStart ? ` 至 ${esc(selectedDateItem.windowEnd.slice(5))}` : ""}</p><p>${esc(selectedDateItem.scene)}</p><p><strong>推荐主题：</strong>${esc(selectedDateItem.direction)}</p><p><strong>准备方向：</strong>提前 ${selectedDateItem.preparationDays} 天整理用途、软件与待核实资料。</p><p class=\"mc-muted\">待确认：${esc(selectedDateItem.unknown)}</p></div>${button("围绕这个机会制定推广方案", "opportunity", "mc-primary", `data-id="${esc(selectedDateItem.id)}"`)}</div>` : `<div class=\"mc-opportunity-detail mc-empty-detail\"><h3>这一天没有配置机会</h3><p>可以选择其他日期，或回到机会列表查看当前有效的演示机会。</p></div>`;
    const placeDetail = selectedPlace ? `<div class=\"mc-opportunity-detail\"><div><span class=\"mc-tag\">${placeTypeLabel(selectedPlace.type)} · 概念地点</span><h3>${esc(selectedPlace.name)}</h3><p class=\"mc-detail-date\">位于门店${esc(selectedPlace.direction)}</p><p><strong>适合聊的话题：</strong>${esc(selectedPlace.theme)}</p><p><strong>相关产品特点：</strong>${esc(selectedPlace.facts)}</p><p class=\"mc-muted\">${esc(selectedPlace.detail)}</p></div>${button("围绕这个场景制定推广方案", "opportunity", "mc-primary", `data-id="local"`)}</div>` : `<div class=\"mc-opportunity-detail mc-empty-detail\"><h3>没有符合条件的地点</h3><p>请选择其他地点类型。</p></div>`;
    const selectedGeneric = !d.activeView && items.find(o => o.id === d.selectedOpportunity && o.type === "产品探索");
    const scenarioCards = selectedGeneric ? (selectedGeneric.scenarios || []).map(s => `<button type="button" class="mc-scenario-card" data-action="opportunity-scenario" data-id="${esc(s.id)}"><strong>${esc(s.name)}</strong><span>${esc(s.hook)}</span><em>围绕这个场景生成方案 ${icon("arrow-up-right")}</em></button>`).join("") : "";
    const genericDetail = selectedGeneric ? `<section class="mc-opportunity-explore-block mc-opportunity-generic-detail" id="mc-opportunity-product-detail"><div class="mc-section-head"><div><h2>${esc(selectedGeneric.title)}</h2><p class="mc-muted">选一个场景，生成更有针对性的推广方案</p></div>${button("收起详情", "opportunity-collapse", "mc-link")}</div><div class="mc-scenario-grid">${scenarioCards}</div><p class="mc-muted">样例场景用于演示选题方向；具体软件适配、配置与价格均需核实。</p></section>` : "";
    // One entrance per opportunity type; keep all eligible records for deep links and date details.
    const cardItems = items.filter((o, index) => items.findIndex(item => item.type === o.type) === index);
    const cards = cardItems.map(o => {
      const isSelected = o.type === "时间节点" ? d.activeView === "date" && opportunityDate(o) === d.selectedDate : o.type === "产品探索" ? selectedGeneric?.id === o.id : d.activeView === "place";
      const action = o.type === "时间节点" ? "opportunity-focus-date" : o.type === "产品探索" ? "opportunity-focus-opportunity" : "opportunity-focus-place";
      const target = o.type === "时间节点" ? "mc-opportunity-date-explorer" : o.type === "产品探索" ? "mc-opportunity-product-detail" : "mc-opportunity-place-explorer";
      return `<article class=\"mc-opportunity-list-item mc-opportunity-card ${o.type === "时间节点" ? "is-date" : ""} ${isSelected ? "is-selected" : ""}\"><div class=\"mc-opportunity-card-copy\"><span class=\"mc-tag\">${esc(opportunityTypeLabel(o.type))} · ${esc(o.status)}</span><h3>${esc(o.title)}</h3><p>${esc(o.description)}</p></div>${button(`查看详情 ${icon("chevron-down")}`, action, "mc-opportunity-card-action", `data-id="${esc(o.id)}" aria-expanded="${isSelected}" aria-controls="${target}"`)}</article>`;
    }).join("");
    const dateView = d.activeView === "date" ? `<section class="mc-opportunity-explore-block" id="mc-opportunity-date-explorer"><div class="mc-section-head"><div><h2>时间节点</h2><p class="mc-muted">每个标记是一段建议窗口（年度样例排期），不代表真实活动；浅色为窗口内的其他日期。</p></div><div class="mc-opportunity-detail-tools"><div class="mc-calendar-nav">${button("上个月", "opportunity-month", "mc-link", 'data-id="prev"')}${button(`${date.getFullYear()} 年 ${date.getMonth() + 1} 月`, "noop", "mc-tag")}${button("下个月", "opportunity-month", "mc-link", 'data-id="next"')}</div>${button("收起详情", "opportunity-collapse", "mc-link")}</div></div><div class="mc-calendar" aria-label="推广机会月历"><div class="mc-calendar-week">${["日", "一", "二", "三", "四", "五", "六"].map(x => `<span>${x}</span>`).join("")}</div><div class="mc-calendar-grid">${cells}</div></div>${dateDetail}</section>` : "";
    const placeView = d.activeView === "place" ? `<section class="mc-opportunity-explore-block" id="mc-opportunity-place-explorer"><div class="mc-section-head"><div><h2>周边场景</h2><p class="mc-muted">${mapStatus}</p></div><div class="mc-opportunity-detail-tools"><div class="mc-map-filters">${[["all", "全部"], ["shopping", "商圈"], ["school", "学校"], ["business", "办公区"]].map(([value, label]) => button(label, "opportunity-map-filter", `mc-link ${filter === value ? "is-active" : ""}`, `data-id="${value}"`)).join("")}</div>${button("收起详情", "opportunity-collapse", "mc-link")}</div></div>${searchPanel}${candidates}${storeBlock}${g.store ? `${radiusChips}${categoryChips}${nearbyErrors}<div class="mc-concept-map is-real" aria-label="周边分布图"><div class="mc-map-road road-a"></div><div class="mc-map-road road-b"></div><div class="mc-map-road road-c"></div><div class="mc-map-ring ring-a"></div><div class="mc-map-ring ring-b"></div><div class="mc-map-store"><span>店</span><small>${esc(g.store.name)}</small></div>${mapScale}${realMarkers}</div>${nearbyList}${limitationsNote}${planBlock}` : `<p class="mc-muted">当前展示演示门店的地图截图；搜索并选择门店后，这里按真实距离展示周边的学校、办公楼、商场等分布。</p><figure class="mc-geo-shot mc-geo-shot-hero"><img src="${esc(D.demoGeo.mapShot)}" alt="${esc(D.demoGeo.mapShotCaption || "门店地图截图")}" loading="lazy"><figcaption>${esc(D.demoGeo.mapShotCaption || "门店地图截图（演示素材）")} · 点「使用演示数据」体验完整选址流程</figcaption></figure>${placeChips}${placeDetail}`}</section>` : "";
    return `${pageHead("推广机会", "发现值得关注的时间节点、周边场景与产品表达方向。", button("返回首页", "home", "mc-secondary"))}<section class="mc-opportunity-explorer"><div class="mc-opportunity-list"><div class="mc-section-head"><div><h2>探索一个方向</h2><p class="mc-muted">${cardItems.length} 个机会方向 · 选择后查看详情</p></div></div><div class="mc-opportunity-card-grid">${cards}</div></div>${dateView}${placeView}${genericDetail}</section>`;
  }
  function nextOpportunity(items, current, seen = []) {
    return items.find(o => o.id !== current && !seen.includes(o.id)) || items.find(o => o.id !== current) || null;
  }
  function featuredOpportunity(items = opportunityExplorerItems()) {
    const day = calendarDay();
    let selected = items.find(o => o.id === state.recommendation?.id);
    if (state.recommendation?.day !== day || !selected) {
      selected = dailyOpportunity(items);
      state.recommendation = { day, id: selected?.id || null, seen: selected ? [selected.id] : [] };
      save();
    }
    if (!Array.isArray(state.recommendation.seen)) state.recommendation.seen = selected ? [selected.id] : [];
    return selected;
  }
  function opportunityStrategies(d) {
    const o = d.opportunity, c = { goal: d.goal, opportunity: o }, audience = d.audience ? `${d.audience}（任务设定，实际需求待验证）` : "受众待确认，先围绕实际用途收集问题";
    const sets = {
      store: [
        ["从一个真实任务开始体验", "把要完成的任务变成到店观察清单", "场景体验邀请", "先联系门店，确认展示型号与体验安排后，再决定是否到店。", "体验价值取决于顾客任务和门店可提供条件，先核实再邀请。", "列出任务、软件与拟观察项目 → 门店确认条件 → 发送有条件的体验邀请。", "体验前，你最想拿电脑完成哪一件事？", "可以先带来一个真实任务或软件问题。门店确认具体型号、展示与服务后，再一起规划观察内容，不预先承诺体验结果。"],
        ["先在线聊，再安排到访", "用一次线上问题收集衔接到店沟通", "到店前沟通卡", "先私信你的一个问题，由门店回复展示和到访信息。", "降低首次沟通成本，让顾客知道到访前能确认什么，而非默认愿意来店。", "征集一个用途问题 → 店员按资料回复 → 核对地址与营业时间 → 顾客自主决定。", "到店之前，你希望先问清哪件事？", "先说说主要用途或常用软件。门店核对能提供的信息、地址与时间后，再由你判断是否值得到访。"],
        ["把到店路径讲清楚", "核实安排后发布一份到访准备说明", "到访准备清单", "出发前联系门店核对地址、时间、实机和服务范围。", "把行动条件单列出来，避免模糊体验承诺造成无效到访。", "核对服务范围 → 整理所需问题 → 告知到访安排 → 不承诺咨询或推广效果。", "一次到访，先准备好问题和安排。", "把用途、软件版本与最关心的问题记下来。是否有对应实机、是否提供体验或预约服务，请先联系门店核实。"]
      ],
      needs: [
        ["把用途变成选购标准", "先做任务清单，再判断是否需要比较华为 PC", "需求自查清单", "列出最常用的三项任务，先检查现有设备是否满足。", "有明确任务才有比较标准；设备需求探索不等于换新或购买意愿。", "收集任务与软件 → 记录现有设备问题 → 区分必要与可延后需求 → 再找产品资料。", "先写下任务，不急着决定换电脑。", "接下来要完成哪些学习或工作任务？常用软件和预算范围是什么？先检查现有设备是否够用；确有比较需要时，再查证华为 PC 对应型号的资料。"],
        ["让产品匹配有资料可查", "建立任务、产品资料与待确认项的对应表", "有来源的比较表", "带着软件版本与具体任务，向门店核实候选型号资料。", "演示目录只能提供讨论对象，不能代替兼容性、配置与性能核验。", "记录任务 → 找到具体型号与官方来源 → 标记未知 → 形成有依据的比较问题。", "这台电脑适合什么任务？先找依据。", "把用途和软件版本放在比较表左侧，把经核实的华为 PC 型号资料放在右侧。没有来源或测试依据的适配性先留空，不用参数多少替你做决定。"],
        ["给需求排优先级", "用必要性、频率与预算做取舍", "选购取舍问答", "选出两项最重要的需求，再决定是否继续了解产品。", "帮助顾客形成判断标准，允许暂缓或不购买，避免用排期制造换新压力。", "区分必须与可选 → 确认频率与预算 → 检查现有设备 → 按标准继续咨询。", "不是每项新计划，都需要一台新电脑。", "先挑出必须完成的任务，再讨论携带方式、使用频率和预算。现有设备能满足时，可以继续使用；需要比较产品时，再核实与关键任务相关的华为 PC 信息。"]
      ],
      consultation: [
        ["用一个软件问题打开沟通", "以具体任务问答引导产品咨询", "软件任务问答", "留下常用软件与版本，向门店询问具体型号的核实资料。", "具体问题让店员知道要查什么，避免泛泛催促购买。", "整理常见问题假设 → 邀请自愿提问 → 查询可靠资料 → 标注未确认结论。", "选电脑时，你最想先问哪一个软件问题？", "告诉我们软件版本、使用任务和最关心的地方。咨询华为 PC 时，兼容性、配置与使用结论需要对应资料支持，暂时无法确认的部分会如实说明。"],
        ["从顾客的实际用途开始咨询", "用一条具体使用任务，邀请顾客先说清需求，再根据资料回答", "用途咨询邀请", "邀请顾客说出最常用电脑完成的一件事，再由店员按资料回复。", "顾客先说清一个使用任务，店员就能围绕用途、软件与资料来源继续沟通，适合尚未确定型号的咨询。", "提出使用任务 → 记录软件与版本 → 核验型号资料 → 回复可确认的信息。", "你最常用电脑完成哪一件事？", "如果你正在了解华为 PC，可以先说说一个具体使用任务。店员会按可核实的型号资料回应，暂时无法确认的配置、适配与服务会单独说明。"],
        ["带着比较问题继续咨询", "把选购取舍转为可回答的咨询提纲", "产品比较咨询卡", "带着两项优先需求，咨询具体型号和资料来源。", "让咨询围绕顾客标准推进，不用未经核实的性能对比代替答案。", "确认优先需求 → 生成比较问题 → 核对型号与来源 → 留下待确认项。", "比较电脑之前，先比较问题。", "你最看重哪些用途？哪些软件必须满足？带着自己的标准咨询华为 PC，逐项核实具体型号资料；资料不足时，不急着得出适配结论。"]
      ],
      awareness: [
        ["先收集使用问题", "用问题征集寻找值得介绍的产品主题", "用途问题征集", "说说常用电脑完成的一件事，不必提供购买计划。", "场景线索只适合提出问题，真实反馈仍需门店收集。", "发布用途问题 → 记录自愿反馈 → 找对应资料 → 决定后续介绍主题。", "聊聊用途，让产品介绍更具体。", "你经常用电脑完成什么任务？先从一个具体问题聊起，再查证哪些华为 PC 产品信息值得介绍。回复只用于了解问题，不代表购买意愿。"],
        ["让资料来源看得见", "做一份已知与待核实信息导读", "产品资料导读", "查看有来源的信息，再提出你关心的问题。", "信息不足时公开边界，让产品介绍有资料基础。", "确认型号 → 整理官方来源 → 标注未知 → 介绍与用途相关的信息。", "认识产品，也要知道信息从哪里来。", "了解华为 PC，可以先核对具体型号和资料来源，再看功能与自己的用途有何关系。尚未核实的配置、软件适配和体验条件会单独注明。"],
        ["把真实任务讲清楚", "用使用问题组织场景内容", "场景问题图文", "留下最想了解的使用问题，供后续内容选择参考。", "先找到内容问题，再核实产品联系，不用环境标签推断客群。", "选一个待验证场景 → 提出任务问题 → 查资料 → 收集反馈。", "从任务理解产品，从依据判断是否相关。", "学习和办公有哪些具体任务值得讨论？可以先写下问题，再核实华为 PC 的产品资料是否足以回应，不预先把场景写成适配结论。"]
      ]
    };
    const alternatives = {
      store: [
        ["把到访拍成一条任务路线", "用任务起点、拟观察内容和离店问题串起短片", "到访路线短片", "先确认展示条件，再带着任务到访。", "以观察与提问说明到店价值，不承诺未确认的体验服务。", "确定任务 → 核实展示条件 → 拟定路线 → 顾客决定是否到访。", "如果只带一个问题到店，你会带什么？", "先把任务记下来，再向门店核实具体型号、展示条件和地址时间，准备自己的观察路线，不预设现场一定能完成测试。"],
        ["用问题投票规划到店邀请", "让顾客先选关心的问题，再规划邀请主题", "互动投票邀请", "选一个想了解的问题，再确认到访条件。", "自愿反馈可帮助规划内容，不能视为到店承诺。", "列待验证问题 → 邀请选择 → 核对可答内容 → 有条件地邀请。", "到店之前，先选一个想问清的问题。", "用途、资料来源、展示安排，你希望先了解哪项？回复只帮助整理问题；是否到访由你决定，门店条件另行确认。"],
        ["出发前，把安排确认清楚", "用一页到访确认单说明行动条件", "到访确认单", "核对位置、时间和展示后，再决定出发。", "公开未知条件，减少无效到访；不虚构预约服务。", "整理待确认安排 → 联系门店 → 记录结果 → 自主安排。", "先把安排问清，再决定是否出发。", "请联系门店核对地址、营业时间和具体型号展示。把任务与软件问题带上，服务范围以门店回复为准。"]
      ],
      needs: [
        ["用任务日记明确选购需求", "记录使用频率和问题，再形成选购标准", "任务日记图文", "记录几次真实任务，再判断是否比较产品。", "用可观察任务代替换新假设，允许现有设备已经够用。", "记录任务 → 标记困扰 → 检查设备 → 查产品资料。", "先记录几次使用，再谈要不要换。", "记录常用软件、频率和困扰。现有设备能满足时不必换；确有不足，再带着记录核实候选华为 PC 的资料。"],
        ["把选购标准做成取舍地图", "用必要与可选两栏梳理用途和预算", "需求取舍地图", "选出必须满足的两项需求，再比较。", "优先级决定比较标准，参数数量不等于适配结论。", "列任务 → 分必要与可选 → 确认预算 → 核对资料。", "只能先满足两件事，你会选什么？", "把必要任务和可延后需求分开，确认预算与软件版本，再带着标准比较华为 PC；无依据的性能结论留空。"],
        ["从现有设备的问题开始问", "通过自查问答判断比较产品是否必要", "设备自查问答", "说出一个困扰，也可以暂缓选购。", "保留不购买的可能，不预设换新意愿。", "自查 → 记录困扰 → 排查原因 → 必要时比较。", "先看看，问题是否真的来自设备。", "困扰发生在哪个软件与任务中？先排查原因，再判断是否比较华为 PC；兼容性和解决办法需可靠资料支持。"]
      ],
      consultation: [
        ["把待回答问题做成咨询专栏", "用已知、未知和来源组织持续问答", "咨询问答专栏", "留下具体问题，等待有来源的回复。", "以可查证问题开启咨询，不用推测代替答案。", "征集问题 → 查来源 → 分已知未知 → 继续咨询。", "关于这台电脑，哪些问题需要查证？", "留下软件、配置或使用问题。咨询华为 PC 时应附对应资料，无法确认的如实标注，不承诺适配结果。"],
        ["从一个用途问题开始沟通", "先说清一项使用任务，再按需补充软件与频率", "分步咨询卡", "邀请顾客先说一个任务，再补充必要信息并继续核对资料。", "逐步补齐用途和软件信息，店员更容易给出有来源的回应，也不会要求顾客一次填写完整。", "确认任务 → 补充软件版本 → 核对型号与来源 → 回复已确认内容。", "不用一次说全，先告诉我们一件事。", "最常用电脑完成什么任务？先说这一件，再按需补充软件版本与频率；华为 PC 的具体资料和服务条件核实后再回复。"],
        ["带着任务做咨询前准备", "用任务桌面清单连接产品咨询", "任务咨询准备图文", "整理任务、软件和问题，再咨询门店。", "准备可查证信息，避免泛泛讨论哪台更好。", "选任务 → 记软件版本 → 列问题 → 核实资料。", "把问题摆上桌面，咨询更有方向。", "选择常见任务，记录软件版本与疑问。带着清单咨询华为 PC 的具体型号和来源，不预先断言使用表现。"]
      ],
      awareness: [
        ["用开放问题开启产品话题", "用问答互动收集值得介绍的主题", "开放问题互动", "留言一个问题，帮助选择后续主题。", "收集自愿反馈再定内容，互动不代表市场热度。", "提问 → 自愿反馈 → 核实资料 → 后续主题。", "日常用电脑，你想先了解什么？", "从使用问题出发选择华为 PC 介绍主题，配置与使用表现查证后再讲，留言不代表购买计划。"],
        ["把一条产品信息追到来源", "通过资料溯源讲清一条产品信息", "来源导读图文", "查看资料来源，再提出关心的问题。", "以可靠资料建立产品认知，不把演示标签写成卖点。", "确认型号 → 找来源 → 解释边界 → 开放提问。", "一句产品介绍，先问依据在哪里。", "了解华为 PC 的一项信息时，先看型号和来源。未核实配置与适配性单列，再讨论与个人用途是否相关。"],
        ["让一个任务成为内容主角", "用任务过程组织图文，避免罗列参数", "任务过程图文", "分享想了解的任务环节，作为内容参考。", "从过程提出产品问题，实际表现仍需验证。", "任务假设 → 拆过程 → 提产品问题 → 核实介绍。", "打开电脑之后，真正要完成什么？", "选具体任务，拆成准备、处理与交付几个环节。由此提出华为 PC 问题并核实资料，不把概念场景当实测表现。"]
      ]
    };
    const items = (d.round % 2 ? alternatives : sets)[d.goal] || (d.round % 2 ? alternatives.needs : sets.needs);
    const preferred = { experience: 0, visit: 2, checklist: 0, match: 1, faq: 0, private: 1, listen: 0, sources: 1 }[d.focus] || 0;
    const offset = (preferred + d.round) % items.length;
    const focus = G.focusOptions(c).find(f => f.id === d.focus);
    const bridge = { "date-refresh": "可以先问接下来的学习或工作任务，而不是将排期当成换新理由。", "software-questions": "沟通时记录软件名称、版本与具体任务，兼容性需对照可靠资料核实。", local: "周边环境只是观察线索，实际客群和问题要通过门店收集。", "consultation-list": "先收集选购问题，再联系门店确认能提供的信息与到访条件。" }[o.id] || "从当前机会的问题出发，先核对依据。";
    const link = o.id === "date-refresh" ? "以新学习或工作任务为线索，不把排期等同换新需求" : o.id === "software-questions" ? "以软件版本与具体任务为线索，兼容性和性能仍待核实" : o.id === "local" ? "以周边线索提出问题，真实客群需门店观察" : "从选购问题衔接到店前沟通，展示与服务需确认";
    return items.map((_, i) => {
      const n = (i + offset) % items.length, s = items[n];
      return { id: `op-${o.id}-${d.goal}-${n}-r${d.round}`, name: s[0], claim: s[1], audience, format: `${s[2]} · ${d.platforms.join(" / ")}（可调整建议）`, reason: `${s[4]} ${focus ? `当前重点：${focus.title}。` : ""}`, cta: s[3], plan: s[5], opening: s[6], copy: `${s[7]} ${bridge}`, relation: `「${o.title}」：${link}。`, evidence: `已知任务：所选机会与目标「${G.names[d.goal] || "待确认"}」。原型建议依据：${o.evidence} 产品名称仅来自示例目录，无适配事实；平台为可调整建议或用户输入。`, unknown: `${o.unknown} 真实客群、软件适配、库存价格、推广效果均未核实。`, adjustment: d.adjustment, angle: n };
    });
  }
  function strategyVisual(s, d) {
    const kinds = { store: ["scene", "dialogue", "editorial"], needs: ["scene", "editorial", "dialogue"], consultation: ["editorial", "dialogue", "scene"], awareness: ["dialogue", "editorial", "scene"], launch: ["editorial", "scene", "dialogue"], season: ["editorial", "scene", "dialogue"] };
    const kind = /场景|真实使用|使用任务/.test(d.strategyAdjustment || "") ? "scene" : (kinds[d.goal || d.task] || ["scene", "editorial", "dialogue"])[s.angle % 3];
    const visuals = {
      scene: { alt: "通用学习或办公桌面，电脑屏幕展示任务资料，旁有手写清单；不是指定型号产品照片", label: "使用场景", style: "桌面任务、屏幕资料与手写清单构图", outputs: ["场景化标题与正文", "封面构图与场景配图建议"], narrative: "用一个任务的过程串起内容" },
      editorial: { alt: "选购参考版式概念图，问题、资料来源与待确认信息分层呈现", label: "选购参考", style: "问题标题、资料摘要与待核实提示分层", outputs: ["选购问题导读与推广正文", "信息层级与封面构图建议"], narrative: "用清单或资料对照组织内容" },
      dialogue: { alt: "通用电脑与一张具体问题说明卡的内容构图，非真实产品或最终图文", label: "问题解答", style: "一个具体问题、简短回应与资料核对提示", outputs: ["顾客问题导读与咨询正文", "问答内容构图与行动引导建议"], narrative: "以一个具体问题衔接自愿沟通" }
    };
    const channels = d.fieldStatus.platforms === "confirmed" ? d.platforms : [];
    const v = visuals[kind], video = channels.includes("视频号");
    const previewTitle = s.previewTitle || ({ store: "到店前，先把安排问清楚", needs: "先看任务，再判断产品是否合适", consultation: "有具体问题，咨询更有方向", awareness: "产品信息，从真实用途讲起", launch: "先核对资料，再介绍产品", season: "新阶段开始前，先整理实际需求" }[d.goal] || "从实际用途开始了解");
    const previewDetail = ({ scene: "使用场景参考", editorial: "信息结构参考", dialogue: "咨询内容参考" })[kind];
    const goalOutput = ({ store: "到店了解清单", needs: "选购自查图文", consultation: "选购问题导读", awareness: "产品特点主题图文", launch: "新品信息导读", season: "设备需求自查图文" })[d.goal || d.task] || "推广主题图文";
    const actionOutput = d.goal === "store" ? "核实门店安排后的联系引导" : d.goal === "consultation" ? "邀请顾客带着具体问题咨询" : d.goal === "needs" ? "帮助顾客整理选购关注点" : d.goal === "awareness" ? "引导顾客继续了解已核实信息" : d.goal === "launch" ? "产品资料来源与待确认项提示" : "按实际需求决定是否进一步了解";
    const outputs = video
      ? ["视频号标题与口播脚本", `${goalOutput}的镜头顺序建议`, actionOutput]
      : channels.includes("门店海报")
        ? ["门店海报主标题、副标题与卖点文案（3 个以内）", "主视觉构图与活动说明建议（不虚构优惠）", actionOutput]
        : channels.includes("公众号")
          ? ["公众号标题、导语与分段正文", `${goalOutput}的配图来源与插入位置建议（2-4 张）`, actionOutput]
          : channels.includes("小红书")
            ? ["小红书标题与正文", `${goalOutput}的封面构图建议（建议 3-6 张配图）`, actionOutput]
            : channels.includes("微信朋友圈")
              ? ["朋友圈推广文案", `${goalOutput}的配图构想（1-3 张）`, actionOutput]
              : ["通用推广文案", `${goalOutput}的内容结构建议`, actionOutput];
    return { visualKind: kind, visualSrc: `assets/strategy-${kind}.svg`, visualAlt: `概念示意：${v.alt}`, visualLabel: v.label, visualStyle: v.style, expectedOutputs: outputs, expression: s.contentFormat || s.format.split(" · ")[0], narrative: v.narrative, previewTitle, previewNote: ({ scene: "从具体任务呈现场景", editorial: "重点信息与核验来源分层呈现", dialogue: "先提出问题，再给出有依据的回应" })[kind], visualNote: "本地 SVG 概念示意 · 非产品实拍、最终配图或已生成成品" };
  }
  const visualAssets = {
    scene: { src: "assets/result-scene.svg", label: "使用场景", alt: "通用学习或办公桌面概念示意，非指定型号实拍" },
    editorial: { src: "assets/result-editorial.svg", label: "选购参考", alt: "问题、资料与待确认信息的版式概念示意" },
    dialogue: { src: "assets/result-dialogue.svg", label: "问题解答", alt: "具体选购问题与资料回应的内容概念示意" }
  };
  const mediaKinds = Object.keys(visualAssets);
  // AI 生成时一并产出的备选图（前端模拟：接入真实生成后由生成结果替换）。
  const candidateAssets = {
    altScene: { src: "assets/strategy-scene.svg", label: "备选 · 场景视角", alt: "AI 生成备选：使用场景概念示意，非指定型号实拍" },
    altEditorial: { src: "assets/strategy-editorial.svg", label: "备选 · 图文版式", alt: "AI 生成备选：图文版式概念示意，非指定型号实拍" },
    altDialogue: { src: "assets/strategy-dialogue.svg", label: "备选 · 问答视角", alt: "AI 生成备选：问答内容概念示意，非指定型号实拍" }
  };
  const assetOf = kind => visualAssets[kind] || candidateAssets[kind];
  // 图片来源为演示占位：接入 ima 知识库后由真实检索结果替换（来源链接、命中资料与授权状态）。
  const demoImageSource = "演示知识库 · 产品资料图（占位；接入 ima 后替换为真实来源与链接）";
  const defaultImagePosition = { "封面": "封面（首图）", "场景": "正文第 1 段后", "补充": "正文第 2 段后" };
  const imageCaption = (platform, label, role) => `${label}概念示意 · ${role}；${platformSpec(platform).structure}`;
  function fillImageMeta(image, platform) {
    if (!image) return image;
    if (!image.source) image.source = demoImageSource;
    if (!image.caption) image.caption = imageCaption(platform || "其他平台", image.visualLabel || "配图", image.role || "插图");
    if (!image.position) image.position = defaultImagePosition[image.role] || "随文插图";
    return image;
  }
  function ensureOutputMedia(output, platform = "其他平台") {
    if (!output) return [];
    if (!Array.isArray(output.images) || !output.images.length) {
      output.images = [{ id: "image-1", visualKind: output.visualKind || "scene", visualSrc: output.visualSrc || visualAssets.scene.src, visualLabel: output.visualLabel || visualAssets.scene.label, visualAlt: output.visualAlt || visualAssets.scene.alt, visualHeadline: output.visualHeadline || "", visualSubline: output.visualSubline || "", role: "封面" }];
    }
    output.images.forEach(image => fillImageMeta(image, platform));
    if (!output.activeImageId || !output.images.some(image => image.id === output.activeImageId)) output.activeImageId = output.images[0].id;
    const image = output.images.find(item => item.id === output.activeImageId) || output.images[0];
    output.visualKind = image.visualKind; output.visualSrc = image.visualSrc; output.visualLabel = image.visualLabel; output.visualAlt = image.visualAlt; output.visualHeadline = image.visualHeadline; output.visualSubline = image.visualSubline;
    return output.images;
  }
  function syncOutputImage(output, image) {
    if (!output || !image) return;
    output.activeImageId = image.id;
    output.visualKind = image.visualKind; output.visualSrc = image.visualSrc; output.visualLabel = image.visualLabel; output.visualAlt = image.visualAlt; output.visualHeadline = image.visualHeadline; output.visualSubline = image.visualSubline;
  }
  function outputImages(output) { return ensureOutputMedia(output, state.draft.activePlatform); }
  function setOutputImage(output, kind) {
    const images = ensureOutputMedia(output), image = images.find(item => item.id === output.activeImageId) || images[0], visual = assetOf(kind);
    if (!visual) return;
    Object.assign(image, { visualKind: kind, visualSrc: visual.src, visualLabel: visual.label, visualAlt: visual.alt });
    syncOutputImage(output, image); output.imageEdited = true;
  }
  function makeMultiImage(output, platform = "其他平台") {
    const images = ensureOutputMedia(output, platform);
    output.imageMode = "multi";
    if (!output.candidates) output.candidates = Object.keys(candidateAssets);
    if (images.length > 1) return images;
    const first = images[0];
    images.push(...mediaKinds.filter(kind => kind !== first.visualKind).map((kind, index) => {
      const visual = visualAssets[kind];
      return { id: `image-${index + 2}`, visualKind: kind, visualSrc: visual.src, visualLabel: visual.label, visualAlt: visual.alt, visualHeadline: index === 0 ? "先从实际用途开始" : "把关心的问题说清楚", visualSubline: index === 0 ? "封面 · 使用场景概念示意" : `${visual.label} · 概念示意`, role: index === 0 ? "场景" : "补充" };
    }));
    images.forEach(image => fillImageMeta(image, platform));
    output.imageMode = "multi"; return images;
  }
  function enrichStrategy(s, d) {
    const clean = Object.fromEntries(Object.entries(s).map(([k, v]) => [k, typeof v === "string" ? G.respectExclusions(v, d.excludedScenes) : v]));
    const p = D.products.find(p => p.id === d.product);
    const audience = G.respectExclusions(d.audience, d.excludedScenes), scene = G.respectExclusions(d.scene, d.excludedScenes);
    const goal = d.goal || d.task, angle = clean.angle % 3;
    const profiles = {
      awareness: { theme: "从日常任务认识产品特点", content: "以一个使用片段开场，将已核实的产品特点与任务对应，让顾客知道这些信息与自己的用途有什么关系", reason: "这次要帮助顾客认识产品，用具体任务解释特点，比单列参数更容易理解", body: "了解一台电脑，不妨先从自己每天要完成的任务看起。哪些产品特点与这些任务有关？先看有来源的介绍，再判断是否值得继续了解。", action: "继续了解有来源的产品信息，也欢迎提出想了解的特点。", output: "产品特点介绍" },
      consultation: { theme: "买笔记本，先想清用途和软件需求", content: "围绕用途、常用软件与预算制作选购问题图文，结合有来源的产品信息说明比较时值得关注什么，结尾邀请有进一步了解需求的顾客咨询", reason: "这次希望顾客进一步咨询，先给出能对照自身情况的选购问题，顾客更容易说清想了解什么", body: "准备了解笔记本电脑时，可以先想想主要用途、常用软件和预算。软件的名称、版本和具体任务，都是比较产品时值得关注的信息；适配与配置需要对应型号的可靠资料支持。", action: "想进一步了解，可以带着常用软件与具体用途联系门店咨询。", output: "选购咨询图文" },
      needs: { theme: "这台电脑适合我吗？从实际任务开始判断", content: "制作一份使用需求自查图文，按任务、软件与预算列出选购关注点，再用有来源的产品资料帮助顾客判断是否值得比较，也保留继续使用现有设备的选择", reason: "这次要帮助顾客判断是否适合自己，先形成自己的比较标准，比直接推荐换新更符合这个目标", body: "先列出最常用的任务、软件与预算，再看看现有设备是否已经够用。确有比较需要时，把关注点与有来源的产品资料逐项对照；没有核实的适配结论先留空。", action: "整理两项最重要的选购标准，再决定是否继续比较产品。", output: "选购自查清单" },
      store: { theme: "带着真实任务到店，了解值得关注的产品信息", content: "用任务场景和到店了解清单说明顾客可以关注什么，结尾给出先联系确认、再安排到访的路径；未核实的展示与体验服务不写成承诺", reason: "这次希望吸引到店，先说明到店值得了解什么，再交代确认安排的路径，避免只发空泛邀请", body: "选电脑时，可以把最想完成的任务和软件问题列成清单。计划到店了解前，先联系门店确认对应型号、展示内容、地址与时间，再决定是否到访。", action: "先联系门店核对展示型号和服务安排，再决定是否到店。", output: "到店了解邀请" },
      launch: { theme: "认识新品，先看清值得了解的产品信息", content: "围绕经核实的新品身份、产品定位和特点制作资料导读，解释它们与使用任务的联系，未确认的上市信息和功能明确留空", reason: "这次准备介绍新品，先把产品身份与信息来源说清楚，才能让顾客分清已知特点和仍需确认的内容", body: "认识新品，可以先从具体型号、资料来源和自己的用途开始。哪些信息已经核实，哪些仍需确认？在有依据的前提下了解产品特点，不用未知功能填补卖点。", action: "查看核实后的产品资料，再选择想进一步了解的特点。", output: "新品信息导读" },
      season: { theme: "新任务开始前，先盘点设备需求", content: "以新学习或工作安排为引子制作设备自查图文，帮助顾客检查现有设备与任务的关系，再决定是否有必要进一步了解产品", reason: "时间节点只提供沟通时机，以实际任务和现有设备为起点，才能避免把新阶段直接当成换新需求", body: "即将开始新的学习或工作任务，不一定需要换电脑。先记录用途、常用软件和现有设备遇到的问题，确有不足时再按标准查证产品信息。", action: "按实际任务检查现有设备，再决定是否进一步了解。", output: "设备需求自查" }
    };
    const profile = profiles[goal] || profiles.needs;
    const confirmedAudience = audience && d.fieldStatus.audience === "confirmed" ? audience : "";
    const confirmedScene = scene && d.fieldStatus.scene === "confirmed" ? scene : "";
    const channels = d.fieldStatus.platforms === "confirmed" ? d.platforms : [];
    const creative = d.fieldStatus.creative === "confirmed" ? d.creative : "";
    const taskSubject = confirmedScene || (confirmedAudience ? `${confirmedAudience}的实际用途` : "日常使用任务");
    const angles = [
      { title: profile.theme, description: `用${taskSubject}的一个片段串起内容`, body: `从${taskSubject}中的一件事开始，看看哪些信息值得关注。`, format: "场景图文" },
      { title: goal === "needs" ? "用实际需求对照产品资料，判断是否适合" : `${profile.theme}：值得关注的三个问题`, description: "按具体问题、资料说明和待确认项分段，便于逐项阅读", body: "选电脑时，不妨想清楚三件事：最常用来做什么、哪些特点有资料可查，还有哪些问题需要进一步了解。", format: "问题导读" },
      { title: `${profile.output}：${confirmedScene || "日常任务"}中，哪些需求最重要？`, description: "围绕必须满足与可以延后的需求组织对照内容", body: "把必须满足的需求与可以延后的需求分开，不急着用参数数量替自己下结论。", format: "选购对照图文" }
    ];
    // One presentation pass: preferences never rewrite effective fields or reparse the transcript.
    const a = angles[angle], note = String(d.strategyAdjustment || "");
    const sceneFirst = /场景|真实使用|使用任务/.test(note), fewerSpecs = /少.*参数|减少参数|不讲参数/.test(note), natural = /自然|口语|亲切/.test(note);
    const title = creative || a.title;
    const productNote = p ? `围绕${p.name}（演示目录）组织内容，具体特点只在资料核实后使用` : "未指定型号，先形成不依赖具体规格的内容框架";
    const platformNote = channels.length ? `以${channels.join("、")}的阅读方式呈现` : "先按通用图文组织，发布平台待确认";
    const coreIdea = `${creative ? `以「${creative}」为主题，` : ""}${profile.content}。${sceneFirst ? `画面从${taskSubject}展开` : a.description}；${platformNote}。` + (fewerSpecs ? "减少参数罗列，重点说明实际任务与已核实信息的联系。" : "");
    const reason = `${confirmedAudience ? `面向已确认的${confirmedAudience}，` : ""}${profile.reason}。${confirmedScene ? `已明确的${confirmedScene}可作为内容主线；` : ""}${p ? `${p.name}仅作为讨论对象，` : ""}${channels.length ? `按${channels.join("、")}组织内容` : "平台未定，先保留通用框架"}，不预设产品适配或推广效果。`;
    const copy = `${creative ? `这次一起看看「${creative}」。` : ""}${confirmedScene ? `如果你正在关注${confirmedScene}，` : ""}${profile.body} ${sceneFirst ? a.body.replace("从", "可以从") : a.body}`;
    const presented = { ...clean, name: title, claim: title, coreIdea, contentFormat: channels.includes("视频号") ? "口播短视频脚本" : channels.includes("门店海报") ? "门店海报文案" : channels.includes("公众号") ? "公众号文章" : a.format, opening: natural ? `最近用电脑完成什么任务？${title}` : title, copy, cta: profile.action, recommendationReason: reason, previewTitle: creative || (confirmedScene ? `${confirmedScene}：${profile.theme}` : profile.theme), adjustmentNote: note, contentTheme: creative || profile.theme, productIntegration: productNote, executionAdvice: "发布前核对型号与官方资料；顾客咨询后按已核实信息回应，无法确认的内容如实说明。" };
    const finalStrategy = { ...presented, ...strategyVisual(presented, d), goal: d.goal, product: d.product, confirmedAudience, platforms: [...channels], fieldStatus: { ...d.fieldStatus }, scene: confirmedScene, creative, factBasis: p ? `${p.name}：${p.facts[0]}。来源为原型示例目录，仅名称与系列资料；无已核实的配置与性能。` : "尚未选择型号，无已核实的产品规格资料。" };
    if (natural) finalStrategy.narrative = "用日常提问与简洁回应自然展开";
    return Object.fromEntries(Object.entries(finalStrategy).map(([key, value]) => [key, typeof value === "string" ? G.respectExclusions(value, d.excludedScenes) : Array.isArray(value) ? value.map(item => typeof item === "string" ? G.respectExclusions(item, d.excludedScenes) : item) : value]));
  }

  function strategyOptions(d = state.draft) {
    if (d.opportunity || ["needs", "awareness", "consultation"].includes(d.goal)) {
      const source = d.opportunity || { id: "free-task", title: G.names[d.goal], evidence: "来自当前有效任务摘要；规则生成的建议，未验证市场需求。", unknown: "具体产品资料、受众与门店条件待核实。" };
      return opportunityStrategies({ ...d, opportunity: source }).map(s => enrichStrategy(s, d));
    }
    const p = D.products.find(p => p.id === d.product);
    const t = D.tasks.find(t => t.id === d.task) || D.tasks[0];
    const audience = audienceLabel(d);
    const sceneText = [d.scene, d.audience].join(" ");
    const scene = /差旅|出差/.test(sceneText) ? "差旅办公" : /课程|学生|学习/.test(sceneText) ? "课程学习与资料整理" : (p?.category === "日常办公" ? "日常资料处理" : "使用场景");
    const sets = {
      seeding: [["从真实的一天切入", `用${scene}的一天串起选购关注点`, "场景图文", "用具体使用片段让顾客对照自己的习惯，避免空泛性能口号。", "说说你的使用场景，一起整理选购要点。"], ["先聊困扰，再聊选择", "把选购问题整理成顾客能回答的三个问题", "选购问答", "从用途、携带频率和预算出发，降低信息理解门槛。", "留下常用软件与预算，获取咨询建议。"], ["把体验交给顾客判断", `围绕${p ? ` ${p.name} ` : "具体型号"}的实机观察清单`, "观察清单", "引导顾客自己比较屏幕、键盘和携带感受，不替顾客下结论。", "到店前先确认实机展示情况。"]],
      launch: [["一页认识新品", "先核实型号，再梳理值得了解的信息", "产品信息卡", "先解决顾客对新品身份与信息来源的疑问，未核实功能不进入卖点。", "咨询已确认的具体型号与配置。"], ["从旧习惯发现新需求", "用原有设备的日常困扰建立换新问题清单", "新旧需求对照", "以需求变化切入，不制造产品参数上的虚假对比。", "带着使用需求了解新品。"], ["先了解，再决定", "把新品介绍变成一份到店咨询路线", "咨询向导", "适合信息尚不完整时发布，让顾客知道下一步如何了解。", "确认门店安排后到店咨询。"]],
      store: [["带着问题来选电脑", "先提供选购清单，再发出到店邀请", "咨询邀请", "把到店价值放在解决顾客问题上，不虚构体验服务。", "出发前确认地址与营业时间。"], ["先在线聊清需求", "通过用途与预算问答衔接门店咨询", "互动问答", "先降低沟通成本，再由顾客决定是否到店。", "私信常用软件和预算范围。"], ["把选购路径讲清楚", "让顾客知道咨询前可以准备什么", "到店准备清单", "明确行动步骤，减少顾客对咨询流程的不确定感。", "确认展示与服务安排后到访。"]],
      season: [["换新前先整理需求", "围绕节点给出设备需求整理清单", "节点选购清单", "日期只是沟通时点，实际设备需求才是推荐理由。", "先整理用途，再决定是否换新。"], ["给新的阶段留出准备时间", "把准备周期与具体学习办公任务相连", "准备指南", "适合有明确新阶段计划的顾客，关联不足时应调整方向。", "带着使用计划到店咨询。"], ["不急着换，先看是否适合", "用设备自查问题判断是否存在换新需求", "设备需求自查", "尊重顾客现有设备与预算，不因节点临近强推购买。", "按真实需求比较具体型号。"]]
    };
    const alternatives = {
      seeding: [["让顾客带着软件来提问", "从常用软件清单出发讨论适配性", "软件需求清单", "先了解具体用途，再由门店核实软件兼容与配置，避免泛化推荐。", "列出常用软件，咨询具体型号是否适合。"], ["一张清单做选购取舍", "对照用途、携带方式与预算确定优先级", "选购取舍表", "把讨论从参数多少转为哪些需求更重要，帮助顾客形成比较标准。", "选出最重要的两项需求，再比较产品。"], ["先收集问题，再写下一篇", "用互动征集了解顾客真正想知道的事", "留言征集", "客群线索不足时先收集问题，再据此选择后续内容，结果需门店验证。", "留下选电脑时最想问的一个问题。"]],
      launch: [["把未知信息讲清楚", "用已知与待确认清单介绍演示产品", "产品信息问答", "信息不完整时，公开待核实项比用推测填补卖点更可靠。", "查看具体型号的已核实资料。"], ["新品是否适合你的任务", "围绕具体软件与使用频率收集问题", "适配性问答", "让顾客提出实际任务，由门店补充产品资料，不预先承诺性能提升。", "告诉门店常用软件与使用频率。"], ["先做好产品素材核对", "用产品身份与图片匹配建立传播基础", "官方资料导读", "适合新品传播准备阶段，先核对图片、型号和来源再写产品介绍。", "确认产品资料后了解具体功能。"]],
      store: [["到店之前先发问题清单", "让顾客提前整理需要咨询的内容", "咨询准备卡", "从顾客最关心的问题出发，并提醒先确认门店服务与展示。", "整理用途与问题，再联系门店确认。"], ["用一条私信开始沟通", "先收集一个需求，再讨论到店安排", "私信互动", "降低首次沟通成本，不承诺门店尚未确认的服务。", "私信最常用电脑完成的一件事。"], ["把到访信息单独说清", "核实地址、时间与展示后再发邀请", "到访信息卡", "适合明确有到访意愿的顾客，减少信息缺失带来的无效到访。", "联系确认地址、营业时间与展示安排。"]],
      season: [["给现有设备做一次自查", "先识别真实问题，再判断是否需要换新", "设备自查表", "把日期节点用作整理需求的提醒，避免制造不必要的购买压力。", "记录现有设备的具体使用问题。"], ["按任务倒排准备计划", "从已确定的学习或工作安排规划设备准备", "准备时间表", "只有顾客确有新任务时才建立节点关联，具体时间由顾客确认。", "确认任务与软件，再安排咨询。"], ["从预算与必要性出发", "讨论哪些需求必须满足，哪些可以延后", "需求优先级清单", "不把节点当作促销理由，帮助顾客做适合自己的安排。", "先确定预算与必要需求，再做选择。"]]
    };
    if (d.goal === "consultation") sets.seeding = [
      ["从选购取舍开始咨询", "把用途与预算转为可讨论的选择标准", "选购咨询卡", "优先推动购买咨询，先梳理取舍，不替顾客承诺适配结论。", "私信你的用途和预算，向门店咨询具体型号。"],
      ["用软件问题开启沟通", "先核实软件任务，再讨论候选配置", "软件问答", "用具体问题连接咨询，兼容性与配置结论需核验。", "列出常用软件与版本，联系门店核实。"],
      ["让比较更有依据", "带着个人需求清单比较具体型号", "选购比较清单", "帮助顾客形成咨询问题，不编造性能对比或购买结果。", "先整理最重要的两项需求，再咨询型号取舍。"]
    ];
    const items = d.round % 2 ? alternatives[t.id] : sets[t.id];
    const offset = d.round % items.length;
    return items.map((_, i) => {
      const n = (i + offset) % items.length, s = items[n];
      return { id: `${t.id}-${n}-r${d.round}`, name: s[0], claim: s[1], audience, format: `${s[2]} · ${d.platforms.join(" / ")}`, reason: s[3], cta: s[4], evidence: `产品：${p ? "原型目录中的演示选项" : "尚未指定"}；任务：${t.name}；平台：${d.platforms.length ? "用户选择或默认建议" : "尚未指定"}。`, unknown: "具体型号、配置、实际客群、门店素材与服务需核实。", adjustment: d.adjustment, angle: n, opening: s[1], copy: `${s[1]}。${s[3]}`, plan: `${s[1]} → 核实产品资料与条件 → ${s[4]}` };
    }).map(s => enrichStrategy(s, d));
  }
  const selectedStrategy = () => {
    const d = state.draft;
    if (state.page === "results" && d.outputContext?.taskId === d.taskId) return d.outputContext.strategy;
    if (d.strategyContext?.taskId === d.taskId && d.strategyContext.strategyId === d.strategyId) return d.strategyContext.strategy;
    return recommendedStrategy();
  };
  function strategyBrief(d, s) {
    const p = D.products.find(p => p.id === d.product);
    return JSON.parse(JSON.stringify({ taskId: d.taskId, strategyId: s.id, strategy: s, task: { product: d.product, productFacts: p ? { name: p.name, facts: p.facts, source: "原型示例目录；具体配置与适配待核验" } : null, confirmedFacts: d.facts, goal: d.goal, audience: d.audience, platforms: s.platforms, scene: d.scene, creative: d.creative, strategyAdjustment: d.strategyAdjustment, fieldStatus: d.fieldStatus, opportunity: d.opportunity, excludedScenes: d.excludedScenes } }));
  }
  function selectStrategy(s) {
    if (!s) return;
    state.draft.strategyId = s.id;
    state.draft.strategyContext = strategyBrief(state.draft, s);
  }
  function recommendedStrategy(options = strategyOptions()) {
    if (!options.length) return null;
    const d = state.draft;
    const prompt = d.scene || ""; // Current effective state only; never reparse historical input.
    const preferred = d.focus === "experience" || d.goal === "store" ? 0
      : d.focus === "sources" || d.focus === "match" || d.goal === "needs" ? 1
        : d.focus === "private" || d.focus === "faq" ? 1 : d.goal === "consultation" ? 0
          : d.goal === "awareness" ? (prompt ? 2 : d.product ? 1 : 0)
            : d.task === "launch" ? 0 : d.task === "season" ? 2 : /软件|资料|来源|参数/.test(prompt) ? 1 : /到店|门店|体验/.test(prompt) ? 2 : 0;
    const candidate = options.find(s => s.angle === (preferred + d.round) % 3) || options[0];
    const scene = d.scene && d.fieldStatus.scene === "confirmed" ? d.scene : "";
    const audience = d.audience && d.fieldStatus.audience === "confirmed" ? d.audience : "";
    const product = D.products.find(p => p.id === d.product);
    const platform = d.fieldStatus.platforms === "confirmed" ? d.platforms.join(" / ") : "";
    return { ...candidate, recommendationBasis: { "当前产品": product?.name || "待确认", "推广目标": G.names[d.goal] || "待确认", "目标受众": audience || "待确认", "使用场景": scene || "待确认", "发布平台": platform || "待确认", "推广主题": d.creative || candidate.contentTheme, "任务来源": d.opportunity?.title || "前序需求对话" } };
  }

  function createOutputs(d = state.draft, requestedPlatforms) {
    const t = D.tasks.find(t => t.id === d.task), p = D.products.find(p => p.id === d.product) || { name: "华为 PC 选购方向" };
    const brief = state.page === "results" && d.outputContext?.taskId === d.taskId ? d.outputContext : d.strategyContext;
    const s = brief?.taskId === d.taskId ? brief.strategy : strategyOptions(d).find(s => s.id === d.strategyId) || strategyOptions(d)[0];
    const baseOpening = s.angle === 0 ? "回到自己的日常用途，你最关注电脑的哪一点？" : s.angle === 1 ? "选电脑前，先问自己三个问题：用来做什么、是否经常携带、预算是多少？" : "比起直接下决定，不妨先列一份实机观察与咨询清单。";
    const revisedOpenings = ["先把一天中最常用电脑完成的任务列出来，再决定要比较什么。", "先想清三个取舍：使用任务、携带方式和预算范围，再向门店咨询。", "带着自己的问题观察实机，让比较有依据；具体展示安排需先确认。"];
    const opening = s.opening ? ((d.generationRound || 0) % 2 ? `${s.opening} 先从你的实际任务开始。` : s.opening) : (d.generationRound || 0) % 2 ? revisedOpenings[s.angle] : baseOpening;
    const taskBody = {
      seeding: `${opening}\n\n这次可以从 ${p.name} 开始了解。带着常用软件和真实使用习惯，观察屏幕、输入与携带体验，再决定它是否适合自己。\n\n${s.cta}`,
      launch: `${opening}\n\n本次以 ${p.name} 为新品介绍的演示对象，传播前需先确认具体型号与上市信息。可以先整理产品身份、官方资料与顾客希望了解的问题，再介绍经核实的功能。\n\n${s.cta}`,
      store: `${opening}\n\n如果正在了解 ${p.name}，可以先联系门店沟通使用需求，再决定是否到店咨询。${d.opportunity?.id === "local" ? "附近地标仅用于了解环境，实际客群与需求仍需确认。" : ""}\n\n${s.cta} 门店地址、营业时间、实机展示及服务以门店确认结果为准。`,
      season: `进入新的学习或工作阶段前，可以先看看现有设备是否满足需要。\n\n${opening}\n\n正在了解 ${p.name} 的顾客，可以先列出用途、软件和预算，再向门店咨询。不因日期节点临近而急着做换新决定。\n\n${s.cta}`
    };
    if (s.copy) taskBody[d.task] = `${opening}\n\n${s.copy}\n\n${s.cta} ${d.product ? `如果正在了解${p.name}，具体配置与适配性请以对应型号的可靠资料为准。` : "本次尚未指定型号，可先整理自己的选购关注点。"}`;
    const requirements = [d.short ? "简短" : "", d.noPrice ? "不提价格" : "", /差旅/.test(d.scene || "") ? "差旅" : ""].filter(Boolean);
    const outputPlatforms = requestedPlatforms || (d.fieldStatus.platforms === "confirmed" && d.platforms.length ? d.platforms : ["通用草稿"]);
    return Object.fromEntries(outputPlatforms.map(platform => {
      let title = d.task === "launch" ? `${p.name}，先了解这些信息` : s.angle === 1 ? "选电脑前，先聊聊你的日常" : s.angle === 2 ? "先看看，再决定是否适合" : t.title;
      if (s.copy) title = s.name;
      let body = taskBody[d.task];
      if (platform === "小红书") { title = `选电脑笔记｜${title}`; body += `\n\n#华为PC #电脑选购 #${({ store: "到店了解", needs: "选购清单", consultation: "选购问题", awareness: "产品了解", launch: "新品资料", season: "设备自查" })[s.goal || d.goal] || "使用场景"}`; }
      if (platform === "视频号") { title = `选电脑聊一聊：${s.name}`; body = `【开场提问】\n${opening}\n\n【镜头与口播】\n${taskBody[d.task]}\n\n【结尾】\n${s.cta}`; }
      if (d.audience) body = `这次，想和${d.audience}聊聊选电脑。` + body;
      if (platform === "微信朋友圈") body = body.split("\n\n").slice(0, 3).join("\n\n");
      if (platform === "公众号") body = `导语｜${opening}\n\n${body}`;
      body += "\n\n具体型号、配置、价格及活动信息以核实结果为准。";
      if (platform === "门店海报") {
        const posterSub = G.respectExclusions(s.scene ? `${s.scene}，从实际用途开始` : "了解有依据的产品信息，再决定是否适合", d.excludedScenes);
        const posterPoints = [...new Set([s.claim, s.name, s.cta].filter(Boolean))].slice(0, 3);
        body = [`【主标题】${title}`, `【副标题】${posterSub}`, "【核心卖点】", ...posterPoints.map((point, index) => `${index + 1}. ${G.respectExclusions(point, d.excludedScenes)}`), "【活动说明】价格、赠品与活动内容须以门店核实结果为准；本海报不预先承诺未核实信息，不拉伸或错配型号图片。"].join("\n");
      }
      body = G.respectExclusions(applyRequirements(body, requirements.join("；"), d.tone), d.excludedScenes);
      const goal = s.goal || d.goal || d.task;
      const headlines = { awareness: "从你的日常，认识一台电脑", consultation: "选电脑，带着问题来聊聊", needs: "适合自己，比急着换新更重要", store: "带着真实任务，了解一台电脑", launch: "认识新产品，先读懂资料", season: "新计划开始，先看看设备够不够用" };
      const sublines = { awareness: "从实际用途出发，了解有依据的产品信息", consultation: "用途、软件、预算，让选购沟通更具体", needs: "列出必要需求，再对照可靠资料", store: "展示型号与到访安排，请先联系门店确认", launch: "具体型号与上市信息，需经可靠资料确认", season: "新阶段不等于必须换新，按实际需要判断" };
      const visual = visualAssets[s.visualKind] || visualAssets.scene;
      const output = { title: G.respectExclusions(title, d.excludedScenes), body, cta: s.cta, requirementNote: requirements.join("；"), tone: d.tone, shortened: false, edited: false, imageEdited: false, strategy: JSON.parse(JSON.stringify(s)), visualKind: s.visualKind || "scene", visualSrc: visual.src, visualLabel: visual.label, visualAlt: visual.alt, visualNote: "本地演示素材 · 通用电脑插画，非指定型号实拍；非实时 AI 生成", visualHeadline: G.respectExclusions(s.creative || (s.scene ? `${s.scene}，从实际用途开始` : headlines[goal]) || s.previewTitle || s.name, d.excludedScenes), visualSubline: G.respectExclusions(sublines[goal] || s.previewNote, d.excludedScenes), layout: s.angle === 1 ? "editorial" : "scene", images: [{ id: "image-1", visualKind: s.visualKind || "scene", visualSrc: visual.src, visualLabel: visual.label, visualAlt: visual.alt, visualHeadline: G.respectExclusions(s.creative || (s.scene ? `${s.scene}，从实际用途开始` : headlines[goal]) || s.previewTitle || s.name, d.excludedScenes), visualSubline: G.respectExclusions(sublines[goal] || s.previewNote, d.excludedScenes), role: "封面", source: demoImageSource, caption: imageCaption(platform, visual.label, "封面"), position: platformSpec(platform).poster ? "海报主视觉" : "封面（首图）" }], activeImageId: "image-1", imageMode: "single" };
      makeMultiImage(output, platform);
      output.initial = JSON.parse(JSON.stringify(output));
      return [platform, output];
    }));
  }
  function applyRequirements(body, requirement, tone) {
    if (/短|精简/.test(requirement)) body = body.split("\n\n").filter(Boolean).slice(0, 2).join("\n\n") + "\n\n具体信息请向门店核实。";
    if (/差旅|出差/.test(requirement) && !/(?:不要|不写|不提|取消)[^，；。]*?(?:差旅|出差)/.test(requirement)) body = "差旅途中，处理资料和临时办公时，你最关注哪些设备使用体验？\n\n" + body;
    if (/不提价格/.test(requirement)) body = body.replace(/、价格/g, "").replace(/价格、/g, "").replace(/价格/g, "相关信息");
    if (tone === "简洁专业") body = "选购建议\n\n" + body.replace(/聊聊/g, "沟通").replace(/不妨/g, "建议");
    if (tone === "轻松亲切") body = "想和你聊聊选电脑这件小事。\n\n" + body;
    return body;
  }
  // Pure helpers are shared with the offline behavior tests.
  window.MarketingPrototypeModel = { fresh, strategyOptions, createOutputs, calendarDay, opportunityState, eligibleOpportunities, dailyOpportunity, nextOpportunity, placePosition, geoDistanceText, geoDemoMode };
  function navigate(page, focus = true) {
    if (!routes.includes(page)) page = "home";
    if (["guide", "analysis"].includes(page)) ensureGuide();
    if (page === "results" && !Object.keys(state.draft.outputs).length) page = "analysis";
    state.page = page; save();
    const snapshot = routeSnapshot();
    if (!navigationReady) { history.replaceState(snapshot, "", `#${page}`); navigationReady = true; }
    else if (location.hash !== `#${page}`) history.pushState(snapshot, "", `#${page}`);
    else history.replaceState(snapshot, "", `#${page}`);
    render();
    if (focus) { window.scrollTo({ top: 0, behavior: "instant" }); const heading = $("#mc-work-page h1") || $(".mc-home-head h1"); heading?.setAttribute("tabindex", "-1"); heading?.focus({ preventScroll: true }); }
  }
  function steps(current) {
    return `<div class="mc-step-row">${button(`${icon("arrow-left")} 返回首页`, "home", "mc-back")}<ol class="mc-steps" aria-label="创作进度">${["需求引导", "推广策略", "推广成果"].map((label, i) => `<li class="${i + 1 === current ? "current" : i + 1 < current ? "done" : ""}" ${i + 1 === current ? 'aria-current="step"' : ""}><span>${String(i + 1).padStart(2, "0")}</span>${label}</li>`).join("")}</ol></div>`;
  }
  function pageHead(title, sub, action = "") { return `<div class="mc-page-head"><div><h1>${title}</h1><p>${sub}</p></div>${action}</div>`; }
  function opportunityCards() {
    const items = opportunityExplorerItems(), o = featuredOpportunity(items);
    if (!o) return `<div class="mc-empty mc-opportunity-empty"><h3>暂时没有依据充分的特殊机会</h3><p>可以从产品特点、使用场景或顾客选购问题开始，先整理值得进一步了解的方向。</p><div class="mc-opportunity-actions">${button("探索产品特点", "explore-product", "mc-secondary")}${button("查看门店设置", "settings", "mc-link")}</div></div>`;
    const alternatives = items.filter(item => item.id !== o.id);
    const action = o.type === "时间节点" ? "查看时间节点" : o.type === "门店场景" ? "查看周边场景" : "查看产品探索";
    return `<article class="mc-featured" aria-labelledby="mc-featured-title"><div class="mc-featured-copy"><div class="mc-featured-meta"><span>${esc(opportunityTypeLabel(o.type))}</span><span class="mc-opportunity-status ${o.verification !== "ready" ? "needs-confirmation" : ""}">${esc(o.status)}</span></div><h3 id="mc-featured-title" aria-live="polite">${esc(o.title)}</h3><p class="mc-featured-description">${esc(o.description)}</p><p class="mc-featured-reason"><strong>值得关注</strong>${esc(o.reason)}</p><div class="mc-opportunity-actions">${button(`${action} ${icon("arrow-up-right")}`, "preview-opportunity", "mc-primary", `data-id="${esc(o.id)}"`)}</div></div><div class="mc-featured-visual" aria-hidden="true"><div class="mc-art ${o.visual === "store" ? "mc-art-three" : "mc-art-one"}"><strong>${o.visual === "store" ? "从一次<br>好提问开始" : "让选择<br>更有依据"}</strong>${o.visual === "store" ? '<span class="mc-portal"></span>' : '<span class="mc-laptop"></span>'}</div></div></article><div class="mc-featured-tools"><details class="mc-opportunity-details"><summary>查看推荐依据与其他推广机会 ${icon("arrow-up-right")}</summary><div class="mc-opportunity-evidence"><dl class="mc-definition"><dt>推荐依据</dt><dd>${esc(o.evidence)}</dd><dt>相关产品</dt><dd>华为 PC 示例目录；仅提供名称与系列，具体功能和场景适配待核验。</dd><dt>适用场景</dt><dd>${esc(o.scene)}</dd><dt>待确认信息</dt><dd>${esc(o.unknown)}</dd><dt>建议准备</dt><dd>${o.preparationDays} 天；${o.daysUntil ? `距建议执行窗口 ${o.daysUntil} 天` : "已进入建议执行窗口"}。排期以门店实际安排为准。</dd></dl><p class="mc-muted">当前推荐使用模拟机会与样例排期，按日期筛选；未接入实时市场数据，也不代表官方活动或已核实需求。</p>${o.id === "local" ? button("补充门店线索", "settings", "mc-link") : ""}<h4>其他可探索的机会</h4>${alternatives.length ? `<ul class="mc-other-opportunities">${alternatives.map(item => `<li><div><strong>${esc(item.title)}</strong><span>${esc(opportunityTypeLabel(item.type))} · ${esc(item.status)}</span></div>${button("查看机会", "preview-opportunity", "mc-link", `data-id="${esc(item.id)}"`)}</li>`).join("")}</ul>` : '<p class="mc-muted">目前只有这一条符合条件的机会。</p>'}</div></details><div class="mc-switch-control"><span>${items.length > 1 ? `${items.length} 条可探索` : "目前仅此一条"}</span>${button(`${icon("refresh-cw")} 换一条推荐`, "next-opportunity", "mc-link", items.length < 2 ? 'disabled aria-label="暂无其他符合条件的推荐"' : "")}</div></div>`;
  }
  function renderHomeProducts() {
    const selected = D.products.find(p => p.id === state.homeProduct);
    $("#mc-home-product-selection").innerHTML = selected ? `<span class="mc-home-product-tag">${esc(selected.name)}${button("移除", "home-product-remove", "mc-link", `aria-label="移除 ${esc(selected.name)}"`)}</span>` : `<span class="mc-home-product-none">${state.homeProductDeferred ? "暂不指定产品，工作台中可补选" : "暂未选择产品，可直接开始"}</span>`;
    $("#mc-home-product-search").value = homeProductQuery;
    const matches = D.searchProducts(homeProductQuery);
    $("#mc-home-product-count").textContent = matches.length ? `${matches.length} 个匹配条目 · 仅名称示例` : "暂未找到匹配产品";
    $("#mc-home-product-results").innerHTML = matches.map(p => button(`<span><strong>${esc(p.name)}</strong><small>${esc(p.family || "MateBook 系列")} · 演示条目</small></span>${state.homeProduct === p.id ? `${icon("check")}<span>已选</span>` : "<span>选择</span>"}`, "home-product-select", "mc-home-product-option", `data-id="${esc(p.id)}" aria-pressed="${state.homeProduct === p.id}"`)).join("") || '<p class="mc-muted">请换个关键词，或暂不选择产品。不会自动补全目录外型号。</p>';
  }
  const homePlatformOptions = [["微信朋友圈", "熟人扩散"], ["小红书", "种草搜索"], ["公众号", "深度图文"], ["视频号", "短视频"], ["门店海报", "到店转化"]];
  function renderHomePlatforms() {
    const menu = $("#mc-home-platform-menu");
    const toggleText = $("#mc-platform-toggle-text");
    const toggle = $("#mc-platform-toggle");
    const sel = state.draft.platforms;
    if (toggleText) toggleText.textContent = sel.length > 1 ? `${sel[0]} 等 ${sel.length} 个` : (sel[0] || "请选择");
    if (!menu) return;
    if (toggle) toggle.setAttribute("aria-expanded", String(homePlatformMenuOpen));
    if (!homePlatformMenuOpen) { menu.hidden = true; return; }
    menu.hidden = false;
    const names = homePlatformOptions.map(([name]) => name).concat(platforms.filter(p => !homePlatformOptions.some(([n]) => n === p))).filter(p => p !== "视频号");
    menu.innerHTML = names.map(p => `<button type="button" role="menuitemcheckbox" aria-checked="${sel.includes(p)}" class="mc-platform-option ${sel.includes(p) ? "is-chosen" : ""}" data-action="home-platform" data-id="${esc(p)}">${sel.includes(p) ? icon("check") : ""}<span>${esc(p)}</span></button>`).join("") + `<p class="mc-platform-menu-hint">至少选择一个；会带入后续策略与成果</p>`;
  }
  function renderHome() {
    $("#mc-prompt").value = state.homePrompt;
    renderHomeProducts();
    renderHomePlatforms();
    $("#mc-task-feedback").textContent = "不必准备完整方案 · 产品与推广内容须人工复核";
    // 首页推荐区已移除（推广机会页保留完整推荐），此处守卫兼容旧页面结构
    const cards = $("#mc-opportunity-cards");
    if (cards) cards.innerHTML = opportunityCards();
    const recDate = $("#mc-recommendation-date");
    if (recDate) recDate.textContent = new Date().toLocaleDateString("zh-CN", { month: "long", day: "numeric" });
  }
  const choice = (label, value, selected, action, extra = "") => button(`${selected ? icon("check") : ""}${esc(label)}`, action, `mc-choice ${selected ? "selected" : ""}`, `data-id="${esc(value)}" aria-pressed="${selected}" ${extra}`);
  function opportunitySource(o) {
    return `<div class="mc-source mc-opportunity-source"><span class="mc-muted">所选机会 · ${esc(opportunityTypeLabel(o.type))} · ${esc(o.status || "样例排期待确认")}</span><strong>${esc(o.title)}</strong><p>${esc(o.description)}</p><p><b>推荐理由</b> ${esc(o.reason)}</p><details><summary>推荐依据与待核实信息</summary><p>${esc(o.evidence)}</p><p>探索方向：${esc(o.direction)}</p><p>待核实：${esc(o.unknown)}</p><p>模拟机会与样例排期，不代表热点、已核实需求或产品适配；目标由本次对话确认。</p></details></div>`;
  }
  function summary() {
    const d = state.draft;
    return `<section class="mc-panel mc-summary"><div class="mc-panel-heading"><h2>这次要完成的事</h2><span class="mc-tag">${task().name}</span></div><p id="mc-demand-summary">${esc(d.prompt.trim() || task().prompt)}</p><details><summary>修改需求</summary><label class="mc-field"><span>需求摘要</span><textarea data-field="prompt" rows="2" placeholder="可按需修改，也可以只选择任务后继续">${esc(d.prompt)}</textarea></label><p class="mc-muted">沿用本次需求，修改后会同步到创作流程。</p></details>${d.opportunity ? `<div class="mc-source"><strong>已继承推广机会：${esc(d.opportunity.title)}</strong><p>初步理解：先围绕${esc(d.opportunity.scene || "当前场景")}组织问题，再核验所选产品能否支撑内容（前端模拟）。</p><p>${esc(d.opportunity.evidence)}</p><p>待确认：${esc(d.opportunity.unknown || "产品资料与实际客群")} 推荐方向为未确认假设。</p><p>产品匹配按需进行；当前资料不足以判断具体型号适配性，也不要求先选产品。</p>${button("清除机会，保留任务", "clear-opportunity", "mc-link")}</div>` : ""}</section>`;
  }
  const G = window.MarketingGuidance;
  function ensureGuide() {
    if (!state.guide || !Array.isArray(state.guide.events)) {
      const d = state.draft;
      const seed = d.product ? { product: d.product, goal: d.goal || ({ seeding: "awareness", store: "store", launch: "launch", season: "season" })[d.task], audience: d.audience, platforms: d.platforms } : {};
      state.guide = G.create(d.opportunity ? "" : d.prompt, seed);
      if (Object.keys(d.fieldStatus || {}).length) {
        state.guide = G.create(d.opportunity ? "" : d.prompt);
        state.guide.events.push({ kind: "choice", text: "恢复已确认的任务摘要", patch: { product: d.product, productDeferred: !d.product, goal: d.goal, audience: d.audience, platforms: [...d.platforms], scene: d.scene, creative: d.creative || "", excludedScenes: [...d.excludedScenes], short: d.short, noPrice: d.noPrice } });
      }
      state.guide.defaultPlatforms = [...d.platforms];
    }
    if (Object.hasOwn(state.guide, "pendingPrompt")) {
      const text = state.guide.pendingPrompt; delete state.guide.pendingPrompt;
      if (text.trim()) state.guide.events.push({ kind: "text", text });
    }
    return state.guide;
  }
  function guideContext() { return G.resolve(ensureGuide(), state.draft.opportunity); }
  function syncGuide() {
    const c = guideContext(), d = state.draft;
    Object.assign(d, { product: c.product, goal: c.goal, focus: c.focus, task: c.task, audience: c.audience, platforms: c.platforms, extra: "", scene: c.scene, creative: c.creative, tone: c.tone || "自然真诚", excludedScenes: c.excludedScenes, fieldStatus: c.fieldStatus, short: c.short, noPrice: c.noPrice });
    // Freeze each response once. Later answers may change the summary, never past messages.
    const g = ensureGuide();
    if (d.opportunity && !g.intro) g.intro = G.opportunityIntro(d.opportunity, c);
    if (!g.welcome) g.welcome = G.response(G.resolve(g, d.opportunity, 0), null, 0);
    g.events.forEach((event, i) => {
      if (typeof event.response === "string") return;
      if (g.thinking && i === g.events.length - 1) return; // 「正在思考」节拍结束后再补上回复
      event.response = G.response(G.resolve(g, d.opportunity, i + 1), event, i + 1);
    });
    save();
    return c;
  }
  function startGuide() {
    const prompt = $("#mc-prompt").value;
    state.homePrompt = prompt;
    state.draft = { ...fresh(), prompt };
    state.guide = G.create(prompt, homeProductSeed());
    state.guide.defaultPlatforms = [...(state.store.platforms.length ? state.store.platforms : ["微信朋友圈"])];
    syncGuide(); navigate("guide");
  }
  function homeProductSeed() {
    // Only explicit homepage configuration travels forward; never reuse a task's product.
    if (state.homeProduct) return { product: state.homeProduct };
    return state.homeProductDeferred ? { product: "", productDeferred: true } : {};
  }
  function addGuideChoice(text, patch) {
    const g = ensureGuide();
    g.events.push({ kind: "choice", text, patch });
    beginThinking(g);
    invalidate(); syncGuide();
  }
  function browserEnv() {
    return typeof requestAnimationFrame === "function" && typeof document !== "undefined" && typeof document.hasFocus === "function";
  }
  function beginThinking(g) {
    // 仅在真实浏览器里给 AI 回复一个短暂的「正在思考」节拍；测试与静态环境保持同步渲染。
    if (!browserEnv()) return;
    g.thinking = true;
    setTimeout(() => {
      const gg = ensureGuide();
      if (!gg.thinking) return;
      gg.thinking = false;
      invalidate(); syncGuide(); render();
      const input = $("#guide-input"); if (input) input.focus();
    }, 420);
  }
  function optionsBlock(question, buttonsHtml, extra) {
    return `<div class="mc-options"><p class="mc-options-q">${esc(question)}</p><div class="mc-guide-options">${buttonsHtml}</div>${extra || ""}</div>`;
  }
  function guideActions(c, g) {
    const stage = G.stage(c);
    if (stage === "product-conflict") return `<h3>请确认本次讨论产品</h3><p>首页所选产品与输入型号不一致，确认前不生成策略。</p><div class="mc-choice-row">${c.productConflict.map(id => button(esc(D.products.find(p => p.id === id)?.name || id), "guide-product", "mc-secondary", `data-id="${id}"`)).join("")}${button("暂不指定产品", "guide-skip-product", "mc-link")}</div>`;
    if (g.editing) return `<form id="guide-summary-form" class="mc-guide-edit"><h3>修改已理解的需求</h3><label class="mc-field"><span>推广目标</span><select name="goal"><option value="" ${!c.goal ? "selected" : ""}>尚未明确</option>${Object.entries(G.names).map(([id, name]) => `<option value="${id}" ${c.goal === id ? "selected" : ""}>${name}</option>`).join("")}</select></label><label class="mc-field"><span>目标受众（可留空）</span><input name="audience" value="${esc(c.audience)}"></label><label class="mc-field"><span>产品（演示目录）</span><select name="product"><option value="">暂不指定型号</option>${D.products.map(p => `<option value="${p.id}" ${c.product === p.id ? "selected" : ""}>${esc(p.name)}</option>`).join("")}</select></label><div class="mc-choice-row"><button type="submit" class="mc-primary">保存修改</button>${button("取消", "guide-cancel", "mc-secondary")}</div></form>`;
    if (stage === "clarification" && !g.panel) return `<h3>请确认本次修改</h3><p>${esc(c.clarification)}</p><div class="mc-choice-row">${button("确认沿用当前摘要", "guide-confirm-current", "mc-secondary")}${button("修改需求摘要", "guide-edit", "mc-link")}</div>`;
    if (g.panel === "platform") return `<div class="mc-options"><p class="mc-options-q">内容要发到哪里？可以随时更换。</p><div class="mc-choice-row">${platforms.map(p => choice(p, p, c.platforms.includes(p), "guide-platform")).join("")}</div><p class="mc-muted">${esc(platformHint(c.platforms))}</p>${button("完成", "guide-close-panel", "mc-primary")}</div>`;
    if (stage === "opportunity-goal") return optionsBlock("这条机会，你希望顾客最后做什么？", G.opportunityGoals(c.opportunity).map(item => button(`<strong>${esc(item.title)}</strong><span>${esc(item.note)}</span>`, "guide-goal", "mc-guide-option", `data-id="${item.id}"`)).join(""), button("让规则给个建议", "guide-auto", "mc-link"));
    if (stage === "opportunity-focus") return optionsBlock("围绕这个目标，先聚焦哪一个重点？", G.focusOptions(c).map(item => button(`<strong>${esc(item.title)}</strong><span>${esc(item.note)}</span>`, "guide-focus", "mc-guide-option", `data-id="${item.id}"`)).join(""), button("先比较策略，细节稍后补充", "guide-strategies", "mc-link"));
    if (stage === "direction") return optionsBlock("可以从这几个方向里挑一个开始，都是供参考的建议。", G.directions(g.directionRound).map(item => button(`<strong>${esc(item.title)}</strong><span>${esc(item.note)}</span>`, "guide-direction", "mc-guide-option", `data-id="${item.id}"`)).join(""), `<div class="mc-choice-row">${button("换一组方向", "guide-directions", "mc-link")}${button("让规则给个建议", "guide-auto", "mc-link")}</div>`);
    if (stage === "priority") return optionsBlock("这次先做哪一个目标？", G.goals.map(item => choice(item.label, item.id, false, "guide-goal")).join(""), button("让规则给个建议", "guide-auto", "mc-secondary"));
    if (stage === "product") return `<div class="mc-options"><div class="mc-panel-heading"><p class="mc-options-q">还差一个讨论对象，先比较两个候选（演示标签，仅用于讨论）</p><span class="mc-tag">演示数据</span></div><div class="mc-guide-products">${G.candidates(c, D.products, g.candidateRound).map(p => button(`${icon("laptop")}<strong>${esc(p.name)}</strong><span>${esc(p.demoReason)}</span><small>待核实：具体型号、规格、软件适配及门店展示。</small><b>选择这个讨论对象 ${icon("arrow-up-right")}</b>`, "guide-product", "mc-guide-option", `data-id="${p.id}"`)).join("")}</div><p class="mc-muted">依据仅为模拟选题标签，不代表真实在售、性能排序或适配结论。</p><div class="mc-choice-row">${button("换一组候选", "guide-candidates", "mc-link")}${button("暂不指定产品，继续", "guide-skip-product", "mc-link")}</div></div>`;
    if (stage === "ready" && c.fieldStatus.tone !== "confirmed" && !g.toneAsked) {
      const toneNotes = { "自然真诚": "像平时聊天一样介绍，不堆砌参数", "简洁专业": "直接给结论和选购建议", "轻松亲切": "轻松一点，先拉近距离" };
      return optionsBlock("生成前还有一个可选问题：这次内容想要什么语气？选好后进入策略比较，也可以稍后在总结卡里换。", ["自然真诚", "简洁专业", "轻松亲切"].map(t => button(`<strong>${esc(t)}</strong><span>${esc(toneNotes[t])}</span>`, "guide-tone", "mc-guide-option", `data-id="${t}"`)).join(""), button("就按自然真诚来", "guide-tone-default", "mc-link"));
    }
    const focus = G.focusOptions(c).find(item => item.id === c.focus);
    const unknowns = [!c.product && !c.productDeferred ? "具体型号" : "", !c.audience ? "目标受众" : "", c.opportunity?.unknown ? "机会附带的待确认项" : ""].filter(Boolean);
    return `<div class="mc-ready-card"><p class="mc-options-q">信息够了，可以直接比较策略；以下是目前掌握的内容。</p><dl class="mc-ready-summary">
      <div><dt>推广目标</dt><dd>${esc(G.names[c.goal] || "待明确")}</dd></div>
      <div><dt>目标受众</dt><dd>${esc(c.audience || "未指定，策略中保留待核实")}</dd></div>
      <div><dt>内容方向</dt><dd>${esc(focus?.title || "待选择重点")}</dd></div>
      <div><dt>发布渠道</dt><dd>${esc(c.platforms.join(" / ") || "暂未指定")}</dd></div>
      <div><dt>内容语气</dt><dd>${esc(c.tone || "自然真诚（默认）")}</dd></div>
      <div><dt>待核实</dt><dd>${esc(unknowns.join("、") || "产品资料与门店服务需常规核实")}</dd></div>
    </dl><div class="mc-tone-row" role="group" aria-label="内容语气"><span>语气</span>${["自然真诚", "简洁专业", "轻松亲切"].map(t => button(esc(t), "guide-tone", `mc-tone-chip${(c.tone || "自然真诚") === t ? " is-on" : ""}`, `data-id="${t}"`)).join("")}</div><div class="mc-choice-row">${button(`进入推广策略 ${icon("arrow-up-right")}`, "guide-strategies", "mc-primary")}${button("修改需求", "guide-edit", "mc-link")}</div></div>`;
  }
  function guidePage() {
    const g = ensureGuide(), c = syncGuide();
    const title = state.draft.opportunity?.title || (c.goal ? `${G.names[c.goal]}的推广任务` : "一起梳理这次推广想法");
    let agentSeen = Boolean(state.draft.opportunity);
    function agentMsg(text) {
      const paras = String(text).split(/\n\n+/).map(part => `<p>${esc(part)}</p>`).join("");
      const tag = agentSeen ? "" : `<span class="mc-msg-tag">${icon("sparkles")} Agent · 规则模拟</span>`;
      agentSeen = true;
      return `<div class="mc-msg mc-msg-agent${tag ? " is-first" : ""}">${tag}${paras}</div>`;
    }
    function userMsg(text) {
      return `<div class="mc-msg mc-msg-user"><p>${esc(text)}</p></div>`;
    }
    const transcript = g.events.map(event => userMsg(event.text) + agentMsg(event.response)).join("");
    const focusName = G.focusOptions(c).find(item => item.id === c.focus)?.title;
    const productName = D.products.find(p => p.id === c.product)?.name;
    const confirmed = [
      c.goal ? ["推广目标", G.names[c.goal]] : null,
      focusName ? ["内容重点", focusName] : null,
      c.audience ? ["目标受众", c.audience] : null,
      productName ? ["讨论产品", productName] : (c.productDeferred ? ["讨论产品", "暂不指定型号"] : null),
      c.platforms.length && c.fieldStatus.platforms === "confirmed" ? ["发布渠道", c.platforms.join(" / ")] : null,
      c.scene ? ["使用场景", c.scene] : null,
      c.creative ? ["创意方向", c.creative] : null,
      c.fieldStatus.tone === "confirmed" && c.tone ? ["内容语气", c.tone] : null,
    ].filter(Boolean);
    const pending = [
      c.goal ? null : ["推广目标", "影响策略走向，先定一个", button("补充", "guide-prefill", "mc-link mc-sum-action", `data-text="这次推广目标是帮顾客建立产品认知"`)],
      c.audience ? null : ["目标受众", "默认按到店顾客处理", button("补充", "guide-prefill", "mc-link mc-sum-action", `data-text="主要面向到店咨询的顾客"`)],
      productName || c.productDeferred ? null : ["讨论产品", "不选也能继续", button("补充", "guide-prefill", "mc-link mc-sum-action", `data-text="想重点讨论 HUAWEI MateBook 14"`)],
      c.platforms.length ? null : ["发布渠道", "至少保留一个", button("选择", "guide-channels", "mc-link mc-sum-action")],
    ].filter(Boolean);
    const optional = [
      c.short ? ["篇幅要求", "简短"] : null,
      c.noPrice ? ["价格口径", "不提价格"] : null,
      c.notes.length ? ["补充想法", `${c.notes.length} 条已记录`] : null,
      state.store.location ? ["门店位置", state.store.location] : null,
    ].filter(Boolean);
    function groupHtml(heading, rows, cls) {
      if (!rows.length) return "";
      return `<div class="mc-sum-group ${cls}"><h3>${heading}</h3><ul>${rows.map(r => `<li><small>${esc(r[0])}</small><span>${esc(r[1])}</span>${r[2] || ""}</li>`).join("")}</ul></div>`;
    }
    const readyBanner = G.stage(c) === "ready" ? `<div class="mc-sum-ready"><span>信息已足够，可以比较策略</span>${button("进入推广策略", "guide-strategies", "mc-link")}</div>` : "";
    const emptyState = agentMsg(g.welcome) + `<div class="mc-suggest-row">${["这次主推 HUAWEI MateBook 14，吸引顾客到店体验", "趁开学季，面向附近大学生做推广", "用朋友圈和小红书发布，内容简短一点"].map(text => button(esc(text), "guide-suggest", "mc-suggest", `data-text="${esc(text)}"`)).join("")}</div>`;
    const opportunityIntro = state.draft.opportunity ? opportunitySource(state.draft.opportunity) + agentMsg(g.intro) : "";
    const lastEvent = g.events.at(-1);
    const thinking = Boolean(g.thinking) && Boolean(lastEvent) && typeof lastEvent.response !== "string";
    const typingBubble = thinking ? `<div class="mc-msg mc-msg-agent mc-msg-typing" aria-label="正在思考"><span class="mc-typing-dots"><i></i><i></i><i></i></span></div>` : "";
    return `${steps(1)}${pageHead(esc(title), "像聊天一样补充想法就行。当前使用前端规则模拟，未连接真实 AI。", button("重新开始", "guide-restart", "mc-link"))}${geoContextCard()}<div class="mc-guide-layout"><section class="mc-panel mc-conversation"><div class="mc-transcript" role="log" aria-label="任务对话">${opportunityIntro}${transcript || (state.draft.opportunity ? "" : emptyState)}${typingBubble}</div><form id="guide-compose" class="mc-guide-compose"><textarea id="guide-input" rows="2" aria-label="输入你的想法，回车发送" placeholder="说说你这次想怎么推广……">${esc(g.composer || "")}</textarea><button type="submit" class="mc-primary">发送</button></form><div class="mc-guide-actions" aria-live="polite">${thinking ? "" : guideActions(c, g)}</div></section><aside class="mc-panel mc-guide-summary"><div class="mc-panel-heading"><h2>已理解的需求</h2>${button("修改", "guide-edit", "mc-link")}</div>${readyBanner}${groupHtml("已确认", confirmed, "is-confirmed")}${groupHtml("待确认", pending, "is-pending")}${groupHtml("可选补充", optional, "is-optional")}<div class="mc-sum-foot"><details><summary>最初的想法</summary><p class="mc-original-prompt">${esc(state.draft.prompt || "从空白任务开始")}</p></details><p class="mc-muted">${esc(c.platformSource)} · 产品资料与门店服务需核实，这里记录的是本次任务意图。</p></div></aside></div>`;
  }

  function config() {
    const d = state.draft;
    const storePrompt = d.task === "store" && !state.store.location.trim() ? `<div class="mc-source"><strong>到店信息可稍后完善</strong><p>还没有填写门店位置。可先继续分析，发布前再到门店设置补充。</p></div>` : "";
    return `${steps(1)}${pageHead("按需补充产品与渠道", "仅在需要时调整产品与渠道；也可以返回引导继续讨论。", button("返回需求引导", "guide", "mc-secondary"))}${summary()}<section class="mc-panel"><div class="mc-panel-heading"><h2>推广哪款产品</h2><span class="mc-muted">演示目录 · 无规格与价格承诺</span></div><div class="mc-product-tools"><label class="mc-search"><span class="sr-only">搜索产品</span><input id="product-search" type="search" placeholder="搜索产品名称" autocomplete="off"></label><label class="mc-search"><span class="sr-only">产品类别</span><select id="product-filter"><option value="">所有类别</option>${[...new Set(D.products.map(p => p.category))].map(category => `<option>${esc(category)}</option>`).join("")}</select></label></div><div class="mc-products">${D.products.map(p => `<button type="button" class="mc-product-card ${d.product === p.id ? "selected" : ""}" data-action="product" data-id="${p.id}" data-category="${p.category}" aria-pressed="${d.product === p.id}"><span class="mc-product-drawing" aria-hidden="true">${icon("laptop")}</span><strong>${esc(p.name)}</strong><span>${p.category} · 演示</span><small>${esc(p.note)}</small><span class="mc-product-state">${d.product === p.id ? `${icon("check")} 已选产品` : "选择产品"}</span></button>`).join("")}</div><p id="product-empty" class="mc-muted" hidden>未找到匹配产品，请换一个关键词。</p></section><section class="mc-panel"><h2>发布到哪里</h2><div class="mc-choice-row">${platforms.map(p => choice(p, p, d.platforms.includes(p), "platform")).join("")}</div><p class="mc-muted" id="platform-hint">${platformHint(d.platforms)}</p></section>${storePrompt}<div class="mc-action-bar"><p id="config-status" role="status">${product() ? "已选产品与发布平台，可开始分析。" : "可以不指定型号，先比较推广策略。"}</p>${button(`开始推广分析 ${icon("arrow-up-right")}`, "analyze", "mc-primary", d.platforms.length ? "" : "disabled")}</div>`;
  }
  function platformHint(selected) { return selected.map(p => ({ "微信朋友圈": "朋友圈：短段落与咨询引导", "小红书": "小红书：标题、场景叙事与标签（建议 3-6 张图）", "公众号": "公众号：导语、分段正文与结尾引导（建议 2-4 张图）", "视频号": "视频号：口播与镜头建议", "门店海报": "门店海报：主副标题、3 个以内卖点与活动说明（主视觉 1 张）", "其他平台": "其他平台：通用图文草稿" }[p])).join("；"); }
  function strategyImage(s) {
    return `<figure class="mc-creative-preview"><img src="${esc(s.visualSrc)}" alt="${esc(s.visualAlt)}" width="640" height="400" decoding="async"><div class="mc-preview-composition"><span>${esc(s.visualLabel)} · 内容构想</span><strong>${esc(s.previewTitle || s.name)}</strong><small>${esc(s.previewNote || "概念示意，仅供创意参考")}</small></div><figcaption>本地演示插画 · 非指定型号实拍</figcaption><span class="mc-preview-fallback" hidden></span></figure>`;
  }
  function analysis() {
    const d = state.draft, p = product(), options = strategyOptions();
    const selected = selectedStrategy();
    const confirmed = (key, value) => d.fieldStatus[key] === "confirmed" && value ? value : "待确认";
    const fields = [["当前产品", confirmed("product", p?.name)], ["推广目标", confirmed("goal", G.names[d.goal])], ["目标受众", confirmed("audience", d.audience)], ["发布平台", confirmed("platforms", d.platforms.join(" / "))]];
    const impact = d.goal === "store"
      ? "可以先确认推广方向；门店地址、可展示型号与体验服务会影响到店承诺，未核实前内容只引导顾客先联系确认。"
      : "待确认信息不会阻止继续。产品配置、软件适配和实际受众未核实前，不会写成确定卖点或需求。";
    const alternatives = options.filter(s => s.id !== selected?.id);
    const facts = p ? p.name + " 来自本地演示目录，仅作为讨论对象；型号规格、配置与适配需核实。来源资料：" + p.facts.join("；") : "尚未选择具体型号，当前方向不依赖未经核实的产品规格。";
    const fieldHtml = fields.map(([k, v]) => "<div><dt>" + esc(k) + "</dt><dd>" + esc(v) + "</dd></div>").join("");
    const alternativeHtml = alternatives.map(s => "<article><div><strong>" + esc(s.name) + "</strong><p>" + esc(s.coreIdea) + "</p></div>" + button("改用这个方向", "strategy", "mc-link", "data-id=\"" + esc(s.id) + "\"") + "</article>").join("");
    const lead = selected ? "<article class=\"mc-lead-strategy\">" + strategyImage(selected) + "<div class=\"mc-lead-copy\"><div class=\"mc-lead-status\"><span>AI 主推方向</span><span>规则模拟</span></div><h2>" + esc(selected.name) + "</h2><div class=\"mc-lead-block\"><span class=\"mc-lead-label\">" + icon("sparkles") + "方案说明</span><p class=\"mc-lead-idea\">" + esc(selected.coreIdea) + "</p></div><div class=\"mc-lead-block mc-lead-compliance\"><span class=\"mc-lead-label\">" + icon("shield-check") + "合规与待确认</span><ul><li>" + esc(selected.unknown) + "</li><li>" + esc(selected.executionAdvice || "发布前核对型号与官方资料；无法确认的内容如实说明。") + "</li>" + (d.complianceNotes || []).map(n => "<li class=\"mc-note-confirmed\">" + icon("check") + "<span>" + esc(n) + "（店员已确认）</span></li>").join("") + "</ul></div><div class=\"mc-creative-tags\"><span>" + esc(selected.expression) + "</span>" + (selected.platforms.length ? "<span>" + esc(selected.platforms.join(" / ")) + "</span>" : "") + "</div><details class=\"mc-creative-evidence\"><summary>查看推荐依据与待确认信息</summary><dl class=\"mc-definition\"><dt>当前有效依据</dt><dd>" + esc(Object.entries(selected.recommendationBasis || {}).map(([k, v]) => k + "：" + v).join("；")) + "</dd><dt>产品资料与来源</dt><dd>" + esc(selected.factBasis) + "</dd><dt>策略判断</dt><dd>" + esc(selected.evidence + " " + (selected.relation || "") + " " + (selected.executionAdvice || selected.plan || "")) + "</dd><dt>视觉建议</dt><dd>" + esc(selected.visualStyle + "。" + (selected.visualNote || "概念示意，不代表最终成图。")) + "</dd><dt>待人工确认</dt><dd>" + esc(selected.unknown + " " + (d.opportunity?.unknown || "")) + "</dd><dt>行动引导</dt><dd>" + esc(selected.cta) + "</dd></dl></details><div class=\"mc-lead-actions\">" + button("确认方向，生成推广图文", "generate", "mc-primary") + "</div></div></article>" : "<div class=\"mc-empty\"><p>暂时无法形成推荐方向，请返回需求引导补充一个关键信息。</p>" + button("返回需求引导", "guide", "mc-secondary") + "</div>";
    return "<div class=\"mc-strategy-page\">" + steps(2) + pageHead("这次推广，我们建议这样做", "结合前面的需求，查看推荐主题与内容构想，确认后继续创作。", button("返回需求引导", "guide", "mc-secondary")) + geoContextCard() + "<section class=\"mc-task-brief\" aria-label=\"当前任务摘要\"><dl>" + fieldHtml + "</dl><p class=\"mc-brief-impact\">" + esc(impact) + "</p><details class=\"mc-task-details\"><summary>查看任务详情</summary><div class=\"mc-task-detail-grid\"><section><h3>任务与资料来源</h3><p>" + esc(d.prompt || "从推广机会开始探索") + "</p><p>" + esc(facts) + "</p><p>平台状态：" + (d.fieldStatus.platforms === "confirmed" ? "来自任务确认" : "尚未确认") + "。当前渠道：" + esc(d.fieldStatus.platforms === "confirmed" ? d.platforms.join(" / ") : "未指定（引导页建议可另行确认）") + "。</p>" + button("按需调整产品与渠道", "config", "mc-link") + "</section><section><h3>推断与待核实</h3><p>策略由当前有效任务状态和有限前端规则整理，属于原型模拟，不代表真实 AI 推理或客群调研。</p><p>产品配置、软件适配、价格库存、真实受众、门店展示与服务均需人工核实。</p>" + (d.opportunity ? "<strong>当前推广机会：" + esc(d.opportunity.title) + "</strong><p>" + esc(d.opportunity.description) + "</p><p>推荐理由：" + esc(d.opportunity.reason) + "</p><p>依据：" + esc(d.opportunity.evidence) + "</p><p>待确认：" + esc(d.opportunity.unknown) + "</p>" : "") + "</section></div></details></section><section class=\"mc-strategy-section\"><div class=\"mc-section-head\"><h2>主推推广方向</h2><span class=\"mc-muted\">规则推荐 · 原型模拟</span></div>" + lead + "<div class=\"mc-strategy-controls\"><div class=\"mc-compliance-coach\"><span class=\"mc-lead-label\">" + icon("sparkles") + "AI 引导 · 完善合规与待确认</span><p class=\"mc-coach-question\">" + (selected ? esc("还有信息待确认：" + selected.unknown + "如果已经核实，直接把结果告诉我，我会记入合规清单，生成内容时保留提醒。") : "") + "</p><div class=\"mc-adjust-row\"><label class=\"mc-field\"><span class=\"mc-sr-only\">记录核实结果</span><input id=\"compliance-note\" value=\"" + "" + "\" placeholder=\"例如：门店已有 MateBook 14 体验机，本周可约；价格已按最新海报核对……\"></label>" + button("记录核实结果", "add-compliance-note", "mc-secondary") + "</div><details class=\"mc-adjust-more\"><summary>想调整推广方向本身？</summary><div class=\"mc-adjust-row\"><label class=\"mc-field\"><span>调整当前方向</span><input id=\"strategy-adjustment\" value=\"" + "" + "\" placeholder=\"想调整什么？例如：更突出真实使用场景、少讲参数、表达得更自然……\"></label>" + button("调整方向", "adjust-strategy", "mc-secondary") + "</div></details></div><div class=\"mc-strategy-footer\"><p class=\"mc-muted\">当前推荐和内容仍为有限规则模拟。</p></div></div></section></div>";
  }
  function supportingContent() { return G.respectExclusions(supportingContentRaw(), state.draft.excludedScenes); }
  function supportingContentRaw() {
    const d = state.draft, p = product() || { name: "华为 PC 选购方向" }, s = selectedStrategy();
    if (s?.visualStyle) return [["选定创意", `${s.name}：${s.coreIdea}`], ["表达与视觉建议", `${s.expression}；${s.visualStyle}。概念参考不代表真实产品外观；最终素材需授权与核实。`], ["预计内容", s.expectedOutputs.join("；")], ["行动引导", s.cta], ["资料依据", s.factBasis], ["待核实", s.unknown]].map(([title,text]) => `<section class="mc-result-support"><h3>${title}</h3><p>${esc(text)}</p></section>`).join("");
    if (d.opportunity) return [["机会与目标", `${d.opportunity.title} · ${G.names[d.goal] || "待确认"}`], ["执行建议（模拟）", s?.plan], ["下一步行动", s?.cta], ["待核实", s?.unknown]].map(([title, text]) => `<section class="mc-result-support"><h3>${title}</h3><p>${esc(text)}</p></section>`).join("");
    const content = {
      seeding: [["内容结构", task().structure.join(" → ")], ["配图与素材建议", "用门店确认可使用的实机图，搭配真实办公或学习场景；不制作虚假顾客证言。"], ["行动引导", s?.cta]],
      launch: [["产品信息摘要", `${p.name} 为演示产品选项；上市时间、具体配置与新品身份均待核验。`], ["重点传播与差异化", `以「${s?.name}」组织信息。只有经核实的产品功能才可转为卖点，不使用未经验证的竞品比较。`], ["素材搭配", "使用已获授权的官方产品图与经核实的功能信息卡。"]],
      store: [["门店沟通建议", "从用途、预算和软件需求开始咨询。是否提供体验、预约或指导服务需门店确认。"], ["到店行动路径", `${state.store.location ? `门店填写的位置：${state.store.location}。` : "尚未填写门店位置。"}先联系确认 → 了解展示与服务 → 自主决定是否到店。`], ["邀请素材建议", "优先使用经允许的店面、陈列与产品照片；不虚构活动、赠品和优惠。"]],
      season: [["节点与需求关联", d.opportunity ? d.opportunity.evidence : "尚未指定真实节日。可先用新学习或工作阶段的设备准备作为主题，关联弱时返回调整策略。"], ["推广主题", s?.claim], ["发布时机与素材", "建议在顾客需要做设备规划时沟通；具体排期由门店决定。搭配需求自查清单，不虚构节日活动。"]]
    };
    return content[d.task].map(([title, text]) => `<section class="mc-result-support"><h3>${title}</h3><p>${esc(text)}</p></section>`).join("");
  }
  const factItems = [
    { id: "specs", label: "具体型号与配置", placeholder: "填写官方或门店核实的型号、资料来源" },
    { id: "price", label: "价格、库存与促销", placeholder: "填写核实结果，或注明本次不涉及" },
    { id: "service", label: "门店地址与服务", placeholder: "确认地址、营业时间、展示及服务范围" }
  ];
  function factsPanel() {
    return `<section class="mc-panel mc-facts"><div class="mc-panel-heading"><h2>事实核验</h2><span class="mc-tag">人工确认</span></div><div class="mc-verified"><strong>已确认信息</strong><p>任务类型、产品选项与渠道来自你的选择。产品参数尚未自动核验。</p></div>${factItems.map(f => {
      const value = state.draft.facts[f.id];
      return `<details ${value?.confirmed ? "" : "open"}><summary><span>${f.label}</span><span class="mc-fact-status ${value?.confirmed ? "confirmed" : ""}">${value?.confirmed ? "用户已确认" : "待确认"}</span></summary><label class="mc-field"><span class="sr-only">${f.label}核验备注</span><input data-fact-note="${f.id}" value="${esc(value?.note || "")}" placeholder="${f.placeholder}"></label>${button(value?.confirmed ? "修改并重新确认" : "我已核实并确认", "confirm-fact", "mc-link", `data-id="${f.id}"`)}</details>`;
    }).join("")}<div class="mc-expression"><strong>推广表达建议</strong><p>避免“最强”“保证”等绝对化表达；不将受众推断、演示产品资料当成核实事实。</p></div></section>`;
  }
  // 知识库依据为演示结构：接入 ima 后由真实检索结果（事实点、资料标题、来源与命中片段）替换。
  function knowledgeEvidence(d = state.draft, strategy = {}) {
    const p = product();
    const items = [];
    if (p) items.push({ fact: p.facts[0] || p.name, title: `${p.name} · 产品名称与系列`, source: "原型演示目录（模拟知识库条目）", status: "supported" });
    if (p?.facts?.[1]) items.push({ fact: p.facts[1], title: `${p.name} · 配置与适配资料`, source: "待 ima 知识库检索补充", status: "needs_confirmation" });
    items.push({ fact: strategy.factBasis || "尚未形成产品事实依据", title: "策略事实依据", source: "当前任务上下文", status: !strategy.factBasis || /未核实|待核验|尚未/.test(strategy.factBasis) ? "needs_confirmation" : "supported" });
    return items;
  }
  const complianceRules = [
    { id: "absolute", label: "绝对化用语", pattern: /最[好强优划算新快高]|第一|顶级|极致|完美|全网最低|百分之百|100%|绝无仅有/g, advice: "改为可核实的具体描述，不用绝对化排名" },
    { id: "promise", label: "效果或资质承诺", pattern: /保证|一定能|肯定能|永久|终身|包过|无效退款/g, advice: "删除承诺，或改为待确认的客观信息" },
    { id: "price", label: "价格与促销表述", pattern: /[0-9]+\s*元|\d+(?:\.\d+)?\s*折|直降|限时|秒杀|补贴|优惠券|赠品/g, advice: "价格、优惠与补贴必须有资料依据，否则删除" },
    { id: "compare", label: "无依据对比", pattern: /比.{1,12}(更好|更强|更快|更值得)|碾压|吊打|远超|领先所有/g, advice: "删除对比，或补充可核实的依据" },
    { id: "rival", label: "竞品相关表述", pattern: /苹果(?!汁)|联想|Lenovo|戴尔|Dell|华硕|惠普|小米(?!粥)|荣耀/g, advice: "避免提及或贬低竞品，不引用无法核实的竞品信息" }
  ];
  function complianceScan(title = "", body = "") {
    const text = `${title}\n${body}`;
    return complianceRules.map(rule => ({ id: rule.id, label: rule.label, advice: rule.advice, hits: [...new Set(text.match(rule.pattern) || [])] }));
  }
  function evidencePanelHtml() {
    const items = knowledgeEvidence();
    const statusLabel = { supported: "有依据", needs_confirmation: "待核实" };
    return `<details class="mc-result-evidence"><summary>知识库依据（模拟检索）</summary><p class="mc-muted">演示结构：接入 ima 知识库后，此面板替换为真实检索结果（事实点、资料标题、来源与命中片段）。</p><ul class="mc-evidence-list">${items.map(item => `<li><span class="mc-fact-status ${item.status === "supported" ? "confirmed" : ""}">${statusLabel[item.status]}</span><strong>${esc(item.title)}</strong><p>${esc(item.fact)}</p><small>来源：${esc(item.source)}</small></li>`).join("")}</ul></details>`;
  }
  function compliancePanelHtml() {
    const scan = complianceScan(oSafeTitle(), oSafeBody());
    const flagged = scan.filter(rule => rule.hits.length);
    return `<details class="mc-result-compliance"><summary>合规检查（规则模拟） · ${flagged.length ? `发现 ${flagged.length} 类需复核表述` : "未检出常见风险表述"}</summary><p class="mc-muted">规则模拟扫描：绝对化用语、虚假承诺、价格误导、无依据对比与竞品表述。接入真实核查后替换为服务端结果。</p><ul class="mc-compliance-list">${scan.map(rule => `<li class="${rule.hits.length ? "is-flagged" : "is-passed"}"><strong>${esc(rule.label)}</strong>${rule.hits.length ? `<span>命中：${rule.hits.map(esc).join("、")}</span><em>${esc(rule.advice)}</em>` : "<span>未检出</span>"}</li>`).join("")}</ul></details>`;
  }
  function oSafeTitle() { const o = state.draft.outputs[state.draft.activePlatform]; return o ? o.title : ""; }
  function oSafeBody() { const o = state.draft.outputs[state.draft.activePlatform]; return o ? o.body : ""; }
  function refreshCompliance() {
    try {
      const el = document.querySelector(".mc-result-compliance");
      if (!el || typeof el.hasAttribute !== "function") return;
      const open = el.hasAttribute("open");
      el.outerHTML = compliancePanelHtml();
      const next = document.querySelector(".mc-result-compliance");
      if (open && next && typeof next.setAttribute === "function") next.setAttribute("open", "");
    } catch { /* 模拟 DOM 或无面板时跳过实时刷新，重新渲染时仍会更新 */ }
  }
  function results() {
    const d = state.draft;
    if (!d.outputs[d.activePlatform]) d.activePlatform = Object.keys(d.outputs)[0];
    const o = d.outputs[d.activePlatform];
    const images = ensureOutputMedia(o, d.activePlatform);
    if (o.imageMode !== "multi") makeMultiImage(o, d.activePlatform);
    const activeImage = images.find(image => image.id === o.activeImageId) || images[0];
    syncOutputImage(o, activeImage);
    const strategy = o.strategy || selectedStrategy() || {};
    const context = d.outputContext?.taskId === d.taskId ? d.outputContext : d.strategyContext;
    const taskData = context?.task || {};
    const summary = [
      ["推广主题", strategy.contentTheme || strategy.name || task().name],
      ["产品", product()?.name || "暂不指定型号"],
      ["发布平台", d.activePlatform === "通用草稿" ? "未指定 · 通用图文" : d.activePlatform]
    ];
    const visual = assetOf(activeImage.visualKind) || visualAssets.scene;
    const changed = o.edited || o.imageEdited || o.copyEdited || o.visualTextEdited;
    const status = changed ? "已修改 · 待人工核验" : "初稿 · 待人工核验";
    if (!o.candidates) o.candidates = Object.keys(candidateAssets);
    const imageChoices = o.candidates.map(kind => {
      const item = assetOf(kind);
      if (!item) return "";
      const usedElsewhere = images.some(image => image.id !== activeImage.id && image.visualKind === kind);
      return `<button type="button" class="mc-image-choice ${activeImage.visualKind === kind ? "is-selected" : ""}" data-action="choose-image" data-id="${kind}" aria-pressed="${activeImage.visualKind === kind}"><img src="${item.src}" alt="${esc(item.alt)}"><span>${esc(item.label)}${usedElsewhere ? " · 与该图交换" : ""}</span></button>`;
    }).join("");
    const thumbs = (o.imageMode === "multi" ? images : []).map((image, index) => `<button type="button" class="mc-result-thumb ${image.id === activeImage.id ? "is-selected" : ""}" data-action="select-result-image" data-id="${esc(image.id)}" aria-label="查看第 ${index + 1} 张图片"><img src="${esc(image.visualSrc)}" alt="${esc(image.visualAlt || image.visualLabel)}"><span>${index + 1}</span></button>`).join("");
    const platformSelect = `<label class="mc-result-platform-select"><span>发布预览平台</span><select id="result-platform-select">${[...new Set(["通用草稿", ...Object.keys(d.outputs), ...platforms])].map(p => `<option value="${esc(p)}" ${p === d.activePlatform ? "selected" : ""}>${esc(p)}</option>`).join("")}</select></label>`;
    return `<div class="mc-results-page">${steps(3)}${pageHead("推广成果工作台", "查看作品，编辑图文，确认后复制或导出。", button("返回调整策略", "analysis", "mc-secondary"))}
      <section class="mc-result-summary" aria-label="当前推广任务"><div>${summary.map(([label, value]) => `<div><span>${label}</span><strong>${esc(value)}</strong></div>`).join("")}</div><span class="mc-result-status">${status}</span></section>
      <div class="mc-results-workbench">
        <section class="mc-result-stage" aria-label="当前推广作品"><div class="mc-stage-head"><div><h2>当前推广作品</h2><p class="mc-muted">第 ${images.findIndex(image => image.id === activeImage.id) + 1} / ${images.length} 张 · ${esc(d.activePlatform === "通用草稿" ? "通用图文" : d.activePlatform)}</p></div>${button("放大图片", "preview-image", "mc-link")}</div>
          <article class="mc-publication-preview" data-platform="${esc(d.activePlatform)}" aria-label="图片预览"><div class="mc-preview-heading"><h3>${esc(activeImage.role || "封面")} · ${esc(activeImage.visualLabel || visual.label)}</h3><span>本地演示素材</span></div><div class="mc-publication-card">
          <div class="mc-result-poster" data-result-preview data-layout="${esc(o.layout || "scene")}"><img data-result-image data-publication-image src="${esc(activeImage.visualSrc || visual.src)}" alt="${esc(activeImage.visualAlt || visual.alt)}" width="800" height="600" decoding="async"><div class="mc-result-poster-copy"><span data-result-visual-label>${esc(activeImage.visualLabel || visual.label)} · 概念示意</span><input id="output-visual-headline" class="mc-poster-headline" data-result-visual-headline data-publication-headline value="${esc(activeImage.visualHeadline || strategy.previewTitle || strategy.name || "推广内容构想")}" aria-label="图片主标题（点击直接编辑）" placeholder="图片主标题"><input id="output-visual-subline" class="mc-poster-subline" data-result-visual-subline data-publication-subline value="${esc(activeImage.visualSubline || strategy.previewNote || "围绕当前推广方向组织画面")}" aria-label="图片副标题（点击直接编辑）" placeholder="图片副标题（可选）"></div><span class="mc-result-image-note">本地演示插画 · 非指定型号实拍 · 图上文字可直接点击编辑</span><span class="mc-preview-fallback" hidden></span></div></div></article>
          ${thumbs ? `<div class="mc-result-thumbnails" aria-label="图片序列"><div class="mc-slider-track">${thumbs}</div></div>` : ""}
          <div class="mc-artwork-actions">${button("添加一张图片", "add-result-image", "mc-secondary")}${button("上移当前图", "move-image-up", "mc-link")}${button("下移当前图", "move-image-down", "mc-link")}${button("删除当前图", "remove-result-image", "mc-link")}</div>
          <div class="mc-stage-replace"><h3>AI 生成备选</h3><p class="mc-muted">生成图片时已一并产出备选，点击即可替换“${esc(activeImage.role || "当前图")}”，不改动其他图片与文案。</p><div class="mc-image-options" role="group" aria-label="AI 生成备选图">${imageChoices}</div><p class="mc-muted">前端模拟生成 · 概念插画，不是华为具体型号实拍。</p></div>
          <details class="mc-image-plan"><summary>配图方案 · 来源与插入位置（演示）</summary><p class="mc-muted">${esc(d.activePlatform === "通用草稿" ? "通用草稿" : d.activePlatform)}：${esc(platformSpec(d.activePlatform).structure)}；建议配图 ${esc(platformSpec(d.activePlatform).imageLabel)}。当前 ${images.length} 张${platformSpec(d.activePlatform).poster ? "，海报仅使用主视觉 1 张，不拉伸或错配型号" : "，可添加为多图作品"}。</p><ul>${images.map((image, index) => `<li><strong>${index + 1}. ${esc(image.role || "配图")}</strong><span>来源：${esc(image.source)}</span><span>说明：${esc(image.caption)}</span><span>建议插入位置：${esc(image.position)}</span></li>`).join("")}</ul></details>
        </section>
        <section class="mc-panel mc-result-copy" aria-label="发布文案">
        <div class="mc-pane-bar"><div><h3>发布文案</h3><p class="mc-muted mc-regen-note">「重新生成图文」可选择整套图文、仅图片或仅文案，生成后可撤销，未选范围内的手动修改保留。</p></div>${button("重新生成图文…", "open-regenerate", "mc-link")}</div>
          <div class="mc-doc-editor">
            <input id="output-title" class="mc-doc-title" value="${esc(o.title)}" aria-label="发布标题" placeholder="发布标题">
            <textarea id="output-body" class="mc-doc-body" rows="6" aria-label="${d.activePlatform === "视频号" ? "口播与镜头脚本" : "发布正文"}">${esc(o.body)}</textarea>
            <div class="mc-editor-meta"><span id="output-count">${o.body.length} 字</span><span>自动保存在当前浏览器，预览同步更新</span></div>
          </div>
          ${d.previousOutputs || o.previousCopy ? `<div class="mc-copy-undo">${d.previousOutputs ? button("撤销重新生成", "undo-regenerate", "mc-link") : ""}${o.previousCopy ? button("撤销文案重生成", "undo-copy", "mc-link") : ""}</div>` : ""}
          <div class="mc-delivery">${button("复制文案", "copy", "mc-primary")}<div class="mc-delivery-secondary">${button(`${icon("download")} 下载图片 SVG`, "download-poster", "mc-link")}${button("导出图文说明 MD", "export", "mc-link")}<details class="mc-copy-options"><summary>更多</summary>${button("复制完整图文说明", "copy-all", "mc-link")}</details></div></div>
          <details class="mc-fold mc-result-advanced"><summary>平台、行动引导与局部调整</summary>${platformSelect}<label class="mc-field"><span>顾客行动引导（正文未包含时，复制/导出自动附加在结尾）</span><input id="output-cta" value="${esc(o.cta || "")}"></label><div class="mc-editor-tools">${button("优化标题", "improve-title", "mc-secondary")}${button("缩短内容", "shorten", "mc-secondary")}${button("恢复初稿", "restore-draft", "mc-secondary", o.initial ? "" : "disabled")}${o.previousBody !== undefined ? button("恢复修改前正文", "restore-body", "mc-secondary") : ""}${button("整体重新生成", "regenerate", "mc-link")}</div>
          <label class="mc-field mc-result-adjustment"><span>局部调整</span><textarea id="result-requirement" rows="2" placeholder="例如：更简洁、不提价格、加入差旅场景">${esc(d.adjustment)}</textarea></label>
          <label class="mc-field"><span>内容语气</span><select id="result-tone">${["自然真诚", "简洁专业", "轻松亲切"].map(t => `<option ${o.tone === t ? "selected" : ""}>${t}</option>`).join("")}</select></label>
          ${button("按要求调整正文", "update-output", "mc-secondary")}<p class="mc-muted">仅执行当前支持的明确规则；其他要求作为备注保留，不会用模板覆盖手写正文。</p>
          ${button("更换推广角度", "change-angle", "mc-link")}</details>
          <details class="mc-fold mc-checks"><summary>内容校验（模拟） · 合规${complianceScan(o.title, o.body).filter(rule => rule.hits.length).length ? `发现 ${complianceScan(o.title, o.body).filter(rule => rule.hits.length).length} 类待复核` : "未检出风险"} · 依据 ${knowledgeEvidence().length} 条 · ${factItems.filter(f => !d.facts[f.id]?.confirmed).length ? `${factItems.filter(f => !d.facts[f.id]?.confirmed).length} 项待确认` : "信息已确认"}</summary><p class="mc-muted">以下规则扫描与检索均为前端模拟，不代表真实合规审查或真实知识库结果。</p><div class="mc-checks-body">${evidencePanelHtml()}${compliancePanelHtml()}<details class="mc-result-fact-details"><summary>有信息待确认 · 查看核验详情</summary><p class="mc-muted">参数、价格、优惠、库存及门店服务未经自动核验，不作确定承诺。</p><p class="mc-muted mc-result-visual-context">当前视觉方向：${esc(strategy.visualStyle || "待确认")}。页面中的图片为本地概念示意，不代表指定型号实拍。</p>${factsPanel()}</details></div></details>
        </section>
      </div>
      <dialog class="mc-regenerate-dialog" aria-labelledby="mc-regenerate-title"><div class="mc-dialog-heading"><h2 id="mc-regenerate-title">重新生成</h2>${button("关闭", "close-regenerate", "mc-link")}</div><p>所选范围内的手动修改会被替换；范围外内容保留，生成后可撤销。</p><fieldset><legend>生成范围</legend><label><input type="radio" name="regenerate-scope" value="all" checked>整套图文</label><label><input type="radio" name="regenerate-scope" value="image">仅当前图片</label><label><input type="radio" name="regenerate-scope" value="copy">仅文案</label></fieldset><label class="mc-field"><span>调整方向</span><select id="regenerate-direction"><option value="default">沿用当前方向，换一版表达</option><option value="scene">更突出使用场景</option><option value="concise">整体更简洁</option><option value="warm">表达更自然亲切</option></select></label><div class="mc-dialog-actions">${button("取消", "close-regenerate", "mc-secondary")}${button("确认重新生成", "confirm-regenerate", "mc-primary")}</div><p class="mc-muted">前端模拟生成，不调用真实 AI。重新生成可撤销。</p></dialog>
      </div>`;
  }
  function settings() {
    const s = state.store;
    return `${pageHead("门店设置", "只填写你了解的信息。本地推广机会会保留推断与待验证边界。")}<form id="store-form" class="mc-panel mc-settings"><h2>门店基础信息</h2><label class="mc-field"><span>门店位置或商圈</span><input name="location" value="${esc(s.location)}" placeholder="填写实际位置，例如：杭州市某商圈" maxlength="200"></label><label class="mc-field"><span>附近地标</span><input name="landmarks" value="${esc(s.landmarks)}" placeholder="例如：附近高校、写字楼或商业中心" maxlength="250"></label><label class="mc-field"><span>主要目标客群</span><input name="audience" value="${esc(s.audience)}" placeholder="由门店实际观察填写，可留空" maxlength="250"></label><fieldset><legend>常用推广平台</legend><div class="mc-choice-row">${platforms.map(p => `<label class="mc-checkbox"><input type="checkbox" name="platforms" value="${p}" ${s.platforms.includes(p) ? "checked" : ""}>${p}</label>`).join("")}</div></fieldset><p class="mc-muted">信息保存在当前浏览器，不会自动上传，也不会据此认定实际客群。地图选址的正式流程在「推广机会 · 周边场景」中完成（搜索门店 → 周边分布 → 围绕这里策划）。</p><div class="mc-settings-footer"><button class="mc-primary" type="submit">保存门店信息</button>${button("返回首页", "home", "mc-secondary")}</div></form>`;
  }
  function historyPage() {
    return `${pageHead("创作记录", "保存在当前浏览器的草稿，可继续编辑或导出。", button("开始新创作", "new", "mc-primary"))}${state.history.length ? `<section class="mc-panel mc-history-list"><h2>${state.history.length} 份本地草稿</h2>${state.history.map(r => `<article class="mc-history-row"><div><span class="mc-tag">${esc(D.tasks.find(t => t.id === r.draft.task)?.name)}</span><h3>${esc(Object.values(r.draft.outputs)[0]?.title || "未命名草稿")}</h3><p>${esc(D.products.find(p => p.id === r.draft.product)?.name || "暂不指定型号")} · ${esc(r.draft.platforms.join(" / "))}</p><small>${esc(new Date(r.updatedAt).toLocaleString("zh-CN"))} · 模拟成果</small></div><div class="mc-history-actions">${button("继续编辑", "open-record", "mc-secondary", `data-id="${esc(r.id)}"`)}${button("删除", "delete-record", "mc-link mc-history-delete", `data-id="${esc(r.id)}" aria-label="删除记录：${esc(Object.values(r.draft.outputs)[0]?.title || "未命名草稿")}"`)}</div></article>`).join("")}</section>` : `<div class="mc-empty"><h2>还没有创作草稿</h2><p>完成一次推广创作后，成果会自动保存在这里。</p>${button("开始第一次创作", "home", "mc-primary")}</div>`}`;
  }
  function initResultSlider() {
    const viewport = typeof document !== "undefined" && document.querySelector ? document.querySelector(".mc-result-thumbnails") : null;
    if (!viewport || typeof viewport.querySelectorAll !== "function" || !viewport.addEventListener) return;
    const track = viewport.querySelector(".mc-slider-track");
    const items = track && track.querySelectorAll ? Array.from(track.querySelectorAll(".mc-result-thumb")) : [];
    if (!track || !items.length) return;
    viewport.classList.add("mc-slider");
    const reduce = typeof window !== "undefined" && window.matchMedia && window.matchMedia("(prefers-reduced-motion: reduce)").matches;
    const current = Math.max(0, items.findIndex(el => el.classList.contains("is-selected")));
    const baseX = i => viewport.clientWidth / 2 - (items[i].offsetLeft + items[i].offsetWidth / 2);
    const minX = () => baseX(items.length - 1), maxX = () => baseX(0);
    let x = baseX(current), startX = 0, startBase = x, dragging = false, moved = false;
    const clampX = val => {
      if (val > maxX()) return maxX() + (val - maxX()) * 0.35;
      if (val < minX()) return minX() + (val - minX()) * 0.35;
      return val;
    };
    const apply = (val, animate) => {
      track.style.transition = animate && !reduce ? "transform .42s cubic-bezier(.22,.8,.3,1)" : "none";
      track.style.transform = `translateX(${val}px)`;
      items.forEach((el, i) => {
        const center = items[i].offsetLeft + items[i].offsetWidth / 2 + val - viewport.clientWidth / 2;
        const ratio = Math.max(-1, Math.min(1, center / (viewport.clientWidth * 0.75)));
        const img = el.querySelector("img");
        if (img && !reduce) img.style.transform = `translateX(${(-ratio * 24).toFixed(1)}px) scale(1.14)`;
        el.style.opacity = String(1 - Math.min(0.45, Math.abs(ratio) * 0.5));
        el.style.transform = `scale(${(1 - Math.min(0.08, Math.abs(ratio) * 0.1)).toFixed(3)})`;
      });
    };
    const snap = () => {
      let best = 0, dist = Infinity;
      for (let i = 0; i < items.length; i++) { const dX = Math.abs(baseX(i) - x); if (dX < dist) { dist = dX; best = i; } }
      x = baseX(best); apply(x, true);
      if (best !== current) items[best].click();
    };
    apply(x, false);
    viewport.addEventListener("pointerdown", e => {
      dragging = true; moved = false; startX = e.clientX; startBase = x;
      viewport.classList.add("is-dragging");
      if (viewport.setPointerCapture) { try { viewport.setPointerCapture(e.pointerId); } catch (err) { /* noop */ } }
    });
    viewport.addEventListener("pointermove", e => {
      if (!dragging) return;
      const dx = e.clientX - startX;
      if (Math.abs(dx) > 6) moved = true;
      x = clampX(startBase + dx); apply(x, false);
    });
    const finish = e => {
      if (!dragging) return;
      dragging = false; viewport.classList.remove("is-dragging");
      if (!moved && e && typeof e.clientX === "number") {
        let thumb = typeof document.elementFromPoint === "function" ? document.elementFromPoint(e.clientX, e.clientY)?.closest?.(".mc-result-thumb") : null;
        if (!thumb && e.target?.closest) thumb = e.target.closest(".mc-result-thumb");
        if (!thumb) thumb = items.find(el => { const r = el.getBoundingClientRect(); return e.clientX >= r.left && e.clientX <= r.right && e.clientY >= r.top && e.clientY <= r.bottom; });
        if (thumb && items.includes(thumb)) { snap(); thumb.click(); return; }
      }
      snap();
    };
    viewport.addEventListener("pointerup", finish);
    viewport.addEventListener("pointercancel", finish);
    viewport.addEventListener("click", e => { if (moved) { e.preventDefault(); e.stopPropagation(); moved = false; } }, true);
    viewport.addEventListener("wheel", e => {
      const delta = Math.abs(e.deltaX) > Math.abs(e.deltaY) ? e.deltaX : e.deltaY;
      if (!delta) return;
      e.preventDefault();
      x = clampX(x - delta * 0.9); apply(x, false);
      clearTimeout(viewport._snapTimer);
      viewport._snapTimer = setTimeout(snap, 160);
    }, { passive: false });
  }
  function render() {
    const home = state.page === "home";
    $("#mc-create-page").hidden = !home;
    $("#mc-work-page").hidden = home;
    $("#mc-page-label").textContent = ({ home: "推广创作", guide: "AI 引导工作台", config: "推广创作", analysis: "推广创作", results: "推广创作", settings: "门店设置", history: "创作记录", opportunities: "推广机会" })[state.page];
    document.querySelectorAll(".mc-nav [data-page]").forEach(el => { const active = el.dataset.page === (["guide", "config", "analysis", "results"].includes(state.page) ? "home" : state.page); el.classList.toggle("is-active", active); if (active) el.setAttribute("aria-current", "page"); else el.removeAttribute("aria-current"); });
    if (home) renderHome();
    else $("#mc-work-page").innerHTML = ({ guide: guidePage, config, analysis, results, settings, history: historyPage, opportunities: opportunityExplorerPage })[state.page]();
    document.querySelectorAll(".mc-creative-preview img, .mc-result-poster img, .mc-publication-image img").forEach(img => {
      const showFallback = () => {
        img.hidden = true;
        const fallback = img.parentElement.querySelector(".mc-preview-fallback");
        if (!fallback) { img.parentElement.classList.add("image-unavailable"); return; }
        fallback.hidden = false;
        fallback.innerHTML = `<svg viewBox="0 0 640 400" role="img" aria-label="备用概念示意：任务资料桌面"><rect width="640" height="400" fill="#eceff0"/><path d="M0 320 640 190v210H0" fill="#d9d8d2"/><g transform="rotate(-12 320 200)"><rect x="140" y="65" width="330" height="250" rx="9" fill="#fff"/><rect x="175" y="100" width="100" height="100" rx="3" fill="#c9d8d2"/><path d="M295 115h135m-135 28h100m-255 90h240m-240 26h180" stroke="#9aa8b0" stroke-width="9"/><circle cx="412" cy="274" r="23" fill="#c95f6e"/></g></svg><small>参考图暂不可用 · 已显示备用概念构图</small>`;
      };
      img.addEventListener("error", showFallback, { once: true });
      if (img.complete && !img.naturalWidth) showFallback();
    });
    document.querySelectorAll("i[data-lucide]").forEach(el => { el.outerHTML = icon(el.dataset.lucide); });
    initResultSlider();
    if (state.page === "guide") {
      const n = state.guide && state.guide.events ? state.guide.events.length : 0;
      if (lastGuideEvents !== null && n > lastGuideEvents && typeof window !== "undefined" && typeof window.scrollTo === "function") {
        const run = () => {
          const de = document.documentElement || document.body;
          const f = typeof document.getElementById === "function" ? document.getElementById("guide-compose") : null;
          if (f && typeof f.getBoundingClientRect === "function" && typeof f.offsetHeight === "number") {
            const top = f.getBoundingClientRect().top + (window.scrollY || 0) - (window.innerHeight || 0) + f.offsetHeight + 20;
            window.scrollTo({ top: Math.max(0, Math.min(top, de ? de.scrollHeight : top)), behavior: "smooth" });
          } else {
            window.scrollTo({ top: de ? de.scrollHeight : 0, behavior: "smooth" });
          }
        };
        run();
        if (typeof setTimeout === "function") setTimeout(run, 400);
      }
      lastGuideEvents = n;
    }
    const view = home ? $("#mc-create-page") : $("#mc-work-page");
    view.classList.remove("mc-enter"); void view.offsetWidth; view.classList.add("mc-enter");
  }
  function record() {
    if (!Object.keys(state.draft.outputs).length) return;
    if (!state.draft.recordId || !state.history.some(r => r.id === state.draft.recordId)) state.draft.recordId = `draft-${Date.now()}-${Math.random().toString(36).slice(2, 7)}`;
    const entry = { id: state.draft.recordId, draft: JSON.parse(JSON.stringify(state.draft)), guide: state.guide ? JSON.parse(JSON.stringify(state.guide)) : null, updatedAt: new Date().toISOString() };
    state.history = [entry, ...state.history.filter(r => r.id !== entry.id)].slice(0, 25); save();
  }
  let generating = false;
  async function generate() {
    if (generating) return;
    if (Object.keys(state.draft.outputs).length && !window.confirm("生成新方向将替换当前成果（包括手动编辑）。原稿已保存在创作记录中。是否继续？")) return;
    if (Object.keys(state.draft.outputs).length) { record(); state.draft.recordId = null; }
    selectStrategy(selectedStrategy());
    generating = true;
    const el = $('[data-action="generate"]');
    if (el) { el.disabled = true; el.textContent = "正在整理模拟成果…"; }
    $("#mc-work-page").setAttribute("aria-busy", "true");
    const generationDraft = state.draft, snapshot = JSON.stringify(state.draft);
    try {
      await new Promise(resolve => setTimeout(resolve, 550));
      if (generationDraft !== state.draft || JSON.stringify(state.draft) !== snapshot) { render(); toast("配置已变更，请按当前方向重新生成。"); return; }
      state.draft.outputs = createOutputs(); state.draft.outputContext = JSON.parse(JSON.stringify(state.draft.strategyContext)); state.draft.activePlatform = Object.keys(state.draft.outputs)[0]; state.draft.revision++;
      record();
      if (state.page === "analysis") navigate("results");
      else toast("模拟草稿已保存到创作记录。");
    } catch { render(); toast("模拟生成未完成，请重试；已有草稿仍保留在创作记录中。"); }
    finally { generating = false; $("#mc-work-page").removeAttribute("aria-busy"); }
  }
  function currentOutput() { return state.draft.outputs[state.draft.activePlatform]; }
  function updateResultPreview() {
    if (state.page !== "results") return;
    const o = currentOutput();
    const image = outputImages(o).find(item => item.id === o.activeImageId);
    const fields = { "[data-publication-title]": o.title, "[data-publication-body]": o.body, "[data-publication-cta]": o.cta && !o.body.includes(o.cta) ? o.cta : "", "[data-result-visual-headline]": image?.visualHeadline || "", "[data-publication-headline]": image?.visualHeadline || "", "[data-result-visual-subline]": image?.visualSubline || "", "[data-publication-subline]": image?.visualSubline || "", ".mc-result-status": "已修改 · 待人工核验" };
    Object.entries(fields).forEach(([selector, text]) => { const node = $(selector); if (!node) return; if ("value" in node && (node.tagName === "INPUT" || node.tagName === "TEXTAREA")) { if (document.activeElement !== node) node.value = text || ""; } else node.textContent = text || ""; });
  }
  function publicationText(o, includeTitle = true, includeAction = true) {
    return [includeTitle ? o.title : "", o.body, includeAction && o.cta && !o.body.includes(o.cta) ? o.cta : ""].filter(Boolean).join("\n\n");
  }
  function fullText() {
    const d = state.draft;
    const outputs = Object.entries(d.outputs).map(([p, o]) => `## ${p}\n\n${publicationText(o)}\n\n图片主标题：${o.visualHeadline || "未填写"}\n图片副标题：${o.visualSubline || "未填写"}\n素材：${o.visualLabel || "使用场景"}（${o.visualSrc || visualAssets.scene.src}）\n素材说明：${o.visualNote || "本地演示素材，非指定型号实拍"}\n视觉方向：${o.strategy?.visualStyle || "待确认"}${o.requirementNote ? `\n\n编辑备注（待人工落实）：${o.requirementNote}` : ""}`).join("\n\n");
    const notes = factItems.map(f => `${f.label}：${d.facts[f.id]?.confirmed ? "用户已确认" : "待确认"}；${d.facts[f.id]?.note || "暂无核验备注"}`).join("\n");
    const evidence = knowledgeEvidence().map(item => `${item.title}｜${item.fact}（来源：${item.source}；${item.status === "supported" ? "有依据" : "待核实"}）`).join("\n");
    const activeOutput = d.outputs[d.activePlatform];
    const compliance = complianceScan(activeOutput?.title, activeOutput?.body).map(rule => `${rule.label}：${rule.hits.length ? `命中 ${rule.hits.join("、")}；建议${rule.advice}` : "未检出"}`).join("\n");
    return `# ${task().deliverable} · 模拟草稿\n\n产品：${product()?.name || "华为 PC 选购"}\n策略：${selectedStrategy()?.name || "已选方向"}\n${d.opportunity ? `机会：${d.opportunity.title}\n依据：${d.opportunity.evidence}\n` : ""}\n${outputs}\n\n## 配套内容\n${supportingContent().replace(/<[^>]*>/g, "\n").replace(/\n{3,}/g, "\n\n")}\n\n## 知识库依据（模拟检索）\n${evidence}\n\n## 合规检查（规则模拟）\n${compliance}\n\n## 事实核验\n${notes}\n\n演示草稿，未自动发布。产品参数与门店服务需人工核实。`;
  }
  async function copy(all = false) {
    const o = currentOutput(), text = all ? fullText() : publicationText(o, true, false);
    try {
      if (!navigator.clipboard?.writeText) throw new Error("Clipboard unavailable");
      await navigator.clipboard.writeText(text); toast(all ? "已复制图文文案、素材信息与核验说明；图片请单独下载。" : "当前平台的发布标题与正文已复制。完整图文包含独立行动引导。");
    } catch {
      const area = document.createElement("textarea"); area.value = text; area.style.position = "fixed"; area.style.opacity = "0"; document.body.append(area); area.select();
      let ok = false; try { ok = document.execCommand("copy"); } catch { /* Manual selection below. */ } area.remove();
      if (ok) toast("当前成果已复制。"); else { $("#output-body").focus(); $("#output-body").select(); toast("浏览器限制复制，已选中正文，请按 ⌘C / Ctrl+C。"); }
    }
  }
  function updateOutput() {
    const o = currentOutput(), requirement = $("#result-requirement").value.trim();
    const tone = $("#result-tone").value;
    // Supported local transforms use the actual edited text; never rebuild from templates.
    const supported = /^(?:更短|简短|精简|缩短(?:内容)?|不提价格|不写价格|差旅|出差)$/;
    const parts = requirement.split(/[，；,;。\n]+/).map(t => t.trim()).filter(Boolean);
    const accepted = parts.filter(t => supported.test(t));
    const unsupported = parts.filter(t => !supported.test(t));
    const before = o.body;
    o.body = applyRequirements(before, accepted.join("；"), tone !== o.tone ? tone : "");
    o.tone = tone; o.requirementNote = requirement;
    if (o.body !== before) { o.previousBody = before; o.edited = true; }
    record(); render(); toast(unsupported.length ? "未支持的要求未自动执行，已保留为备注；正文仅应用明确支持的调整。" : "已基于当前正文进行局部调整，没有重新套用模板。");
  }
  async function downloadPoster() {
    const o = currentOutput();
    const visual = visualAssets[o.visualKind] || visualAssets.scene;
    try {
      // Only bundle our local catalog assets; no user URL is fetched or exported.
      const response = await fetch(visual.src);
      if (!response.ok) throw new Error("Local asset unavailable");
      const source = await response.text();
      if (!source.trim().startsWith("<svg")) throw new Error("Invalid image asset");
      const bytes = new TextEncoder().encode(source);
      const embedded = `data:image/svg+xml;base64,${btoa(Array.from(bytes, byte => String.fromCharCode(byte)).join(""))}`;
      const wrap = (text, count) => {
        const chars = Array.from(String(text || ""));
        return Array.from({ length: Math.ceil(chars.length / count) }, (_, i) => chars.slice(i * count, (i + 1) * count).join(""));
      };
      const titleLines = wrap(o.visualHeadline, 20), subLines = wrap(o.visualSubline, 32);
      const width = 1000, margin = 58, artHeight = o.layout === "editorial" ? 500 : 563;
      const labelTop = 39, headlineTop = 91, headlineSize = 36, subSize = 21;
      const headlineHeight = titleLines.length * 48, subTop = headlineTop + headlineHeight + 8;
      const copyHeight = 48 + headlineHeight + subLines.length * 32 + 34;
      const imageTop = o.layout === "editorial" ? 0 : copyHeight;
      const copyTop = o.layout === "editorial" ? artHeight : 0;
      const captionHeight = 38, height = artHeight + copyHeight + captionHeight;
      const labelY = copyTop + labelTop, titleY = copyTop + headlineTop;
      const subY = copyTop + subTop;
      const titleSvg = titleLines.map((line, i) => `<text x="${margin}" y="${titleY + i * 48}" font-size="${headlineSize}" font-weight="600" fill="#24272d">${esc(line)}</text>`).join("");
      const subSvg = subLines.map((line, i) => `<text x="${margin}" y="${subY + i * 32}" font-size="${subSize}" fill="#46515d">${esc(line)}</text>`).join("");
      const svg = `<svg xmlns="http://www.w3.org/2000/svg" width="${width}" height="${height}" viewBox="0 0 ${width} ${height}"><rect width="${width}" height="${height}" fill="#fff"/><image href="${embedded}" x="0" y="${imageTop}" width="${width}" height="${artHeight}" preserveAspectRatio="xMidYMid slice"/><rect x="0" y="${copyTop}" width="${width}" height="${copyHeight}" fill="#fff"/><g font-family="Arial, PingFang SC, Microsoft YaHei, sans-serif"><text x="${margin}" y="${labelY}" font-size="16" fill="#a7273a">${esc(visual.label)} · 概念示意</text>${titleSvg}${subSvg}<rect y="${height - captionHeight}" width="${width}" height="${captionHeight}" fill="#fff"/><text x="${margin / 2}" y="${height - 14}" font-size="13" fill="#525c65">本地演示素材 · 通用电脑示意，非指定型号实拍 · 使用前须人工核验</text></g></svg>`;
      downloadBlob(new Blob([svg], { type: "image/svg+xml;charset=utf-8" }), `华为PC-${task().name}-概念海报.svg`);
      toast("已下载包含当前图片内文案的概念海报 SVG，发布前请核验。");
    } catch { toast("本地图片素材读取失败，未导出图片；文案与编辑仍已保留。请重试。"); }
  }
  function downloadBlob(blob, filename) {
    const url = URL.createObjectURL(blob), link = document.createElement("a");
    link.href = url; link.download = filename; document.body.append(link); link.click(); link.remove();
    setTimeout(() => URL.revokeObjectURL(url), 2000);
  }
  let switchingOpportunity = false;
  async function switchOpportunity(id) {
    if (switchingOpportunity) return;
    const items = opportunityExplorerItems(), current = featuredOpportunity(items);
    const next = id ? items.find(o => o.id === id) : nextOpportunity(items, current?.id, state.recommendation.seen);
    if (!next || next.id === current?.id) return toast("目前没有其他符合条件的推荐。");
    const region = $(state.page === "home" ? "#mc-opportunity-cards" : ".mc-opportunity-list"), page = state.page;
    if (!region) return;
    const reduced = window.matchMedia?.("(prefers-reduced-motion: reduce)").matches;
    switchingOpportunity = true;
    try {
      region.setAttribute("aria-busy", "true");
      if (!reduced && region.animate) await region.animate([{ opacity: 1 }, { opacity: 0, transform: "translateY(3px)" }], { duration: 110, easing: "ease-in" }).finished;
      if (state.page !== page) return;
      // Recheck after the animation in case a candidate just expired at midnight.
      if (!opportunityExplorerItems().some(o => o.id === next.id)) { render(); return; }
      const seen = state.recommendation.seen;
      const completed = !items.some(o => o.id !== current.id && !seen.includes(o.id));
      state.recommendation = { day: calendarDay(), id: next.id, seen: completed ? [next.id] : [...new Set([...seen, next.id])] };
      save(); region.innerHTML = opportunityCards();
      if (!reduced && region.animate) await region.animate([{ opacity: 0, transform: "translateY(4px)" }, { opacity: 1, transform: "translateY(0)" }], { duration: 170, easing: "ease-out" }).finished;
      region.querySelector?.('[data-action="next-opportunity"]')?.focus({ preventScroll: true });
      if (completed && !id) toast("已浏览当前所有有效机会，重新从其他方向探索。");
    } finally { region.removeAttribute("aria-busy"); switchingOpportunity = false; }
  }
  document.addEventListener("click", async e => {
    if (homePlatformMenuOpen && !(e.target.closest && e.target.closest(".mc-platform-picker"))) {
      homePlatformMenuOpen = false; renderHomePlatforms();
    }
    const nav = e.target.closest("[data-page]");
    if (nav) {
      if (nav.dataset.page === "opportunities") { state.opportunityExplorer.activeView = ""; state.opportunityExplorer.selectedOpportunity = ""; }
      return navigate(nav.dataset.page);
    }
    const el = e.target.closest("[data-action]"); if (!el || el.disabled) return;
    const a = el.dataset.action, id = el.dataset.id, d = state.draft;
    if (routes.includes(a)) {
      if (a === "opportunities") { state.opportunityExplorer.activeView = ""; state.opportunityExplorer.selectedOpportunity = ""; }
      return navigate(a);
    }
    if (a === "scroll-rec") {
      const target = $("#mc-gallery");
      if (target) target.scrollIntoView({ behavior: window.matchMedia("(prefers-reduced-motion: reduce)").matches ? "auto" : "smooth", block: "start" });
      return;
    }
    if (a === "side-collapse") {
      const app = $(".mc-app");
      if (!app) return;
      const collapsed = app.classList.toggle("collapsed");
      el.setAttribute("aria-label", collapsed ? "展开侧边栏" : "收起侧边栏");
      try { localStorage.setItem("mc-side-collapsed", collapsed ? "1" : ""); } catch { /* 私有模式下忽略 */ }
      return;
    }
    if (a === "home-product-select" || a === "home-product-remove" || a === "home-product-defer") {
      if (a === "home-product-select" && !D.products.some(p => p.id === id)) return;
      state.homeProduct = a === "home-product-select" ? id : "";
      state.homeProductDeferred = a === "home-product-defer";
      homeProductQuery = "";
      renderHomeProducts(); save();
      $("#mc-home-product-picker").open = false;
      if (a === "home-product-defer") { $("#mc-prompt").focus(); toast("本次暂不指定产品，可描述想法后开始创作。工作台中仍可补选。"); }
      else { $("#mc-home-product-picker summary")?.focus(); toast(state.homeProduct ? "已选择演示产品，可继续描述推广想法。" : "已移除产品，可切换或直接开始。"); }
      return;
    }
    if (a.startsWith("guide-")) {
      const g = ensureGuide(), c = guideContext();
      if (a === "guide-suggest" || a === "guide-prefill") { const gg = ensureGuide(); const text = el.dataset.text || ""; if (text) { gg.composer = gg.composer && gg.composer.trim() ? gg.composer.replace(/\s+$/, "") + "，" + text : text; } save(); render(); const input = $("#guide-input"); if (input) { input.focus(); input.setSelectionRange(input.value.length, input.value.length); } return; }
      if (a === "guide-confirm-current") addGuideChoice("就按现在的需求摘要来", { clarification: "" });
      if (a === "guide-edit") { g.editing = true; g.panel = null; }
      if (a === "guide-cancel") g.editing = null;
      if (a === "guide-channels") { g.panel = "platform"; g.editing = null; }
      if (a === "guide-close-panel") g.panel = null;
      if (a === "guide-platform") {
        const selected = c.platforms.includes(id);
        if (selected && c.platforms.length === 1) return toast("至少保留一个发布渠道。");
        addGuideChoice(selected ? `先不在 ${id} 发布了` : `再加上 ${id}`, { platforms: selected ? c.platforms.filter(p => p !== id) : [...c.platforms, id] });
      }
      if (a === "guide-direction" || a === "guide-goal") addGuideChoice(`这次先做「${G.names[id]}」`, { goal: id });
      if (a === "guide-auto") { const recommendation = G.recommend(c); addGuideChoice(`先按「${G.names[recommendation.goal]}」来吧`, recommendation); }
      if (a === "guide-focus") { const item = G.focusOptions(c).find(item => item.id === id); if (item) addGuideChoice(item.title, { focus: id, productRequested: Boolean(item.productRequested), note: item.note }); }
      if (a === "guide-product") addGuideChoice(`就选 ${D.products.find(p => p.id === id)?.name || id} 吧`, { product: id });
      if (a === "guide-tone") addGuideChoice(`语气用「${id}」`, { tone: id });
      if (a === "guide-tone-default") addGuideChoice("就按自然真诚来", { tone: "自然真诚" });
      if (a === "guide-candidates") { g.candidateRound++; addGuideChoice("换一组候选看看", {}); }
      if (a === "guide-directions") { g.directionRound++; addGuideChoice("换一组方向看看", {}); }
      if (a === "guide-reselect-product") addGuideChoice("重新选一个讨论产品", { product: "", productDeferred: false, productRequested: true });
      if (a === "guide-skip-product") addGuideChoice("这次先不指定型号", { product: "", productDeferred: true });
      if (a === "guide-strategies") {
        if (c.productConflict.length || c.clarification) return toast("请先确认存在歧义的修改或产品型号。");
        if (c.opportunity && !c.goal) { toast("先确认这条机会的推广目标，或让模拟规则给出建议。"); render(); return; }
        if (!c.goal || !c.product) addGuideChoice("先看策略，没定的回头再补", { goal: c.goal || "awareness", productDeferred: !c.product });
        syncGuide(); navigate("analysis"); return;
      }
      if (a === "guide-restart") {
        if (!window.confirm("重新开始会清空当前对话；已保存的成果仍在创作记录中。继续吗？")) return;
        state.homePrompt = ""; state.homeProduct = ""; state.homeProductDeferred = false; state.draft = fresh(); state.guide = G.create(); state.guide.defaultPlatforms = [...(state.store.platforms.length ? state.store.platforms : ["微信朋友圈"])];
      }
      save(); render(); return;
    }
    if (a === "task") { if (d.task !== id) { invalidate(); d.opportunity = null; } d.task = id; renderHome(); save(); toast(`已选择${task().name}，可继续补充要求。`); }
    if (a === "new") { state.homePrompt = ""; state.homeProduct = ""; state.homeProductDeferred = false; homeProductQuery = ""; state.draft = fresh(); state.guide = null; state.draft.platforms = [...state.store.platforms]; if (!state.draft.platforms.length) state.draft.platforms = ["微信朋友圈"]; navigate("home"); }
    if (a === "home-platform-toggle") { homePlatformMenuOpen = !homePlatformMenuOpen; renderHomePlatforms(); return; }
    if (a === "home-platform") {
      const pl = state.draft.platforms; const i = pl.indexOf(id);
      if (i >= 0) { if (pl.length === 1) return toast("至少选择一个发布平台。"); pl.splice(i, 1); }
      else pl.push(id);
      renderHomePlatforms(); save();
      return;
    }
    if (a === "next-opportunity") { await switchOpportunity(id); return; }
    if (a === "preview-opportunity") {
      const o = opportunityList().find(item => item.id === id);
      if (!o) return toast("这条机会已不在有效期内，请选择当前推荐。");
      state.opportunityExplorer = { ...state.opportunityExplorer, activeView: o.type === "时间节点" ? "date" : o.type === "门店场景" ? "place" : "", month: opportunityDate(o).slice(0, 7) || state.opportunityExplorer.month, selectedDate: o.type === "时间节点" ? opportunityDate(o) : state.opportunityExplorer.selectedDate, mapFilter: o.id === "local" ? "all" : state.opportunityExplorer.mapFilter, selectedPlace: o.id === "local" ? "place-shopping" : state.opportunityExplorer.selectedPlace, selectedOpportunity: o.type === "产品探索" ? o.id : "" };
      navigate("opportunities");
      return;
    }
    if (a === "opportunity-month") {
      state.opportunityExplorer.activeView = "date";
      const current = monthDate(state.opportunityExplorer.month || monthKey());
      current.setMonth(current.getMonth() + (id === "prev" ? -1 : 1));
      state.opportunityExplorer.month = monthKey(current);
      state.opportunityExplorer.selectedDate = "";
      save(); render();
      return;
    }
    if (a === "opportunity-date") {
      state.opportunityExplorer.activeView = "date";
      state.opportunityExplorer.selectedDate = id;
      save(); render();
      document.querySelector("#mc-opportunity-date-explorer")?.scrollIntoView?.({ behavior: "smooth", block: "start" });
      return;
    }
    if (a === "opportunity-map-filter") {
      state.opportunityExplorer.activeView = "place";
      state.opportunityExplorer.mapFilter = id;
      state.opportunityExplorer.selectedPlace = "";
      save(); render();
      document.querySelector("#mc-opportunity-place-explorer")?.scrollIntoView?.({ behavior: "smooth", block: "start" });
      return;
    }
    if (a === "opportunity-place") {
      state.opportunityExplorer.activeView = "place";
      state.opportunityExplorer.selectedPlace = id;
      save(); render();
      return;
    }
    if (a === "opportunity-focus-date") {
      const o = opportunityList().find(item => item.id === id);
      if (!o) return toast("这条机会已不在有效期内，请选择当前推荐。");
      state.opportunityExplorer = { ...state.opportunityExplorer, activeView: "date", month: opportunityDate(o).slice(0, 7), selectedDate: opportunityDate(o) };
      save(); render();
      document.querySelector("#mc-opportunity-date-explorer")?.scrollIntoView?.({ behavior: "smooth", block: "start" });
      return;
    }
    if (a === "opportunity-focus-opportunity") {
      state.opportunityExplorer.activeView = ""; state.opportunityExplorer.selectedOpportunity = id;
      save(); render();
      document.querySelector("#mc-opportunity-product-detail")?.scrollIntoView?.({ behavior: "smooth", block: "start" });
      return;
    }
    if (a === "opportunity-collapse") {
      const view = state.opportunityExplorer.activeView;
      const action = view === "date" ? "opportunity-focus-date" : view === "place" ? "opportunity-focus-place" : "opportunity-focus-opportunity";
      state.opportunityExplorer.activeView = ""; state.opportunityExplorer.selectedOpportunity = "";
      save(); render();
      document.querySelector(`[data-action="${action}"]`)?.focus({ preventScroll: false });
      return;
    }
    if (a === "opportunity-focus-place") {
      state.opportunityExplorer.activeView = "place";
      state.opportunityExplorer.mapFilter = "all";
      if (id === "local" && !geoState().store) state.opportunityExplorer.selectedPlace = "place-shopping";
      save(); render();
      document.querySelector("#mc-opportunity-place-explorer")?.scrollIntoView?.({ behavior: "smooth", block: "start" });
      return;
    }
    if (a === "opportunity-demo-geo") {
      // 演示：直接填入契约示例响应（合成数据），流程与真实接口完全一致。
      const g0 = geoState();
      g0.demo = true; g0.city = "杭州"; g0.keyword = "华为授权服务中心（城西银泰）";
      g0.searchStatus = "done"; g0.searchError = ""; g0.searchResult = demoGeoSearch("示例门店", "杭州");
      g0.store = null; g0.selectedStorePoiId = ""; g0.nearbyByCat = {}; g0.selectedNearby = []; g0.geoContext = null; g0.contextStatus = "idle"; g0.contextError = "";
      state.opportunityExplorer.activeView = "place";
      save(); render();
      document.querySelector("#mc-opportunity-place-explorer")?.scrollIntoView?.({ behavior: "smooth", block: "start" });
      return toast("已填入演示搜索数据（合成），选择门店后加载周边。");
    }
    if (a === "geo-search" || a === "geo-search-retry") {
      const city = String(document.querySelector("#mc-geo-city")?.value ?? "").trim();
      const keyword = String(document.querySelector("#mc-geo-keyword")?.value ?? "").trim();
      if (a === "geo-search" && !keyword) { render(); return toast("请填写门店或地点名称。"); }
      const g0 = geoState();
      g0.city = city; g0.keyword = keyword || g0.keyword;
      if (!g0.keyword) { render(); return toast("请填写门店或地点名称。"); }
      g0.demo = false; // 真实搜索：离开演示数据模式
      g0.searchStatus = "loading"; g0.searchError = "";
      save(); render();
      try {
        const data = await searchStoresApi({ keyword: g0.keyword, city: g0.city || undefined });
        const g1 = geoState();
        g1.searchStatus = "done";
        g1.searchResult = data;
        // 新查询快照会使旧门店引用失效（契约 404/410 语义），清空下游状态。
        g1.store = null; g1.selectedStorePoiId = ""; g1.nearbyByCat = {}; g1.selectedNearby = []; g1.geoContext = null; g1.contextStatus = "idle"; g1.contextError = "";
      } catch (e) {
        const g1 = geoState();
        g1.searchStatus = "error"; g1.searchError = geoErrorMessage(e);
      }
      save(); render();
      return;
    }
    if (a === "geo-select-store") {
      const g0 = geoState();
      const poi = (g0.searchResult?.items || []).find(p => p.poi_id === id);
      if (!poi) return toast("该候选已不在当前查询快照中，请重新搜索。");
      g0.store = JSON.parse(JSON.stringify(poi));
      g0.selectedStorePoiId = poi.poi_id;
      g0.nearbyByCat = {}; g0.selectedNearby = []; g0.geoContext = null; g0.contextStatus = "idle"; g0.contextError = "";
      save(); render();
      for (const cat of g0.activeCategories) geoFetchNearbyCategory(cat);
      return;
    }
    if (a === "geo-radius") {
      const g0 = geoState();
      const r = Number(id);
      if (!g0.store || !Number.isFinite(r) || g0.radius === r) return;
      g0.radius = r;
      g0.selectedNearby = []; g0.geoContext = null; g0.contextStatus = "idle"; g0.contextError = "";
      save(); render();
      for (const cat of g0.activeCategories) geoFetchNearbyCategory(cat);
      return;
    }
    if (a === "geo-category") {
      const g0 = geoState();
      if (!g0.store) return;
      const on = g0.activeCategories.includes(id);
      g0.activeCategories = on ? g0.activeCategories.filter(c => c !== id) : [...g0.activeCategories, id];
      save(); render();
      if (!on) geoFetchNearbyCategory(id);
      return;
    }
    if (a === "geo-category-retry") { if (geoState().store) geoFetchNearbyCategory(id); return; }
    if (a === "geo-toggle-nearby") {
      const g0 = geoState();
      const has = g0.selectedNearby.includes(id);
      if (!has && g0.selectedNearby.length >= GEO_NEARBY_MAX) { render(); return toast(`最多选择 ${GEO_NEARBY_MAX} 个周边地点。`); }
      g0.selectedNearby = has ? g0.selectedNearby.filter(x => x !== id) : [...g0.selectedNearby, id];
      g0.geoContext = null; g0.contextStatus = "idle"; g0.contextError = "";
      save(); render();
      return;
    }
    if (a === "geo-plan") {
      const g0 = geoState();
      if (!g0.store || !g0.searchResult?.query_id) return;
      if (g0.geoContext && !geoContextExpired(g0)) return;
      const nearbyRefs = geoAllNearby(g0).filter(p => g0.selectedNearby.includes(p.poi_id)).map(p => ({ query_id: p.query_id, poi_id: p.poi_id }));
      g0.contextStatus = "loading"; g0.contextError = "";
      save(); render();
      try {
        const ctx = await createGeoContextApi({ storeRef: { query_id: g0.searchResult.query_id, poi_id: g0.selectedStorePoiId }, nearbyRefs });
        const g1 = geoState();
        g1.contextStatus = "done";
        g1.geoContext = ctx;
        geoEnterChat(ctx, g1.demo);
      } catch (e) {
        const g1 = geoState();
        g1.contextStatus = "error";
        g1.contextError = geoErrorMessage(e);
        save(); render();
      }
      return;
    }
    if (a === "opportunity-scenario") {
      const rec = opportunityList().find(x => (x.scenarios || []).some(s => s.id === id));
      if (!rec) { render(); return toast("这条机会已不在有效期内，请选择当前推荐。"); }
      const s = rec.scenarios.find(x => x.id === id);
      const source = { ...rec, title: s.name, description: s.hook, direction: s.direction, scene: `${s.name}（样例场景）；${rec.scene}`, scenario: { id: s.id, name: s.name } };
      state.draft = { ...fresh(), opportunity: { ...source }, task: rec.task, prompt: state.homePrompt || s.direction };
      state.guide = G.create(state.homePrompt, homeProductSeed());
      state.guide.defaultPlatforms = [...(state.store.platforms.length ? state.store.platforms : ["微信朋友圈"])];
      navigate("guide"); return;
    }
    if (a === "explore-product") { state.draft = fresh(); state.guide = null; navigate("guide"); return; }
    if (a === "opportunity") {
      if (id === "setup") return navigate("settings");
      const o = opportunityList().find(x => x.id === id);
      if (!o) { render(); return toast("这条机会已不在有效期内，请选择当前推荐。"); }
      const place = id === "local" && state.page === "opportunities" ? mockPlaces.find(p => p.id === state.opportunityExplorer.selectedPlace) : null;
      const source = place ? { ...o, place: { id: place.id, name: place.name, type: place.type, demo: true }, scene: `${place.name}（概念地点）；${place.theme}`, direction: `${place.theme} ${o.direction}`, unknown: `${o.unknown} ${place.detail}` } : o;
      state.draft = { ...fresh(), opportunity: { ...source }, task: o.task, prompt: state.homePrompt || source.direction };
      state.guide = G.create(state.homePrompt, homeProductSeed());
      state.guide.defaultPlatforms = [...(state.store.platforms.length ? state.store.platforms : ["微信朋友圈"])];
      navigate("guide"); return;
    }
    if (a === "clear-opportunity") { ensureGuide(); invalidate(); d.opportunity = null; d.geo = null; syncGuide(); render(); save(); toast("已清除机会依据与地理上下文，保留其他配置。"); }
    if (a === "product") { addGuideChoice(`修改演示讨论产品：${D.products.find(p => p.id === id)?.name}`, { product: id }); render(); toast("产品已选择。"); }
    if (a === "platform") {
      if (d.platforms.includes(id) && d.platforms.length === 1) return toast("至少保留一个发布平台。");
      const selected = d.platforms.includes(id) ? d.platforms.filter(p => p !== id) : [...d.platforms, id]; addGuideChoice(`调整渠道：${id}`, { platforms: selected }); render();
    }
    if (a === "analyze") { const c = syncGuide(); if (c.clarification || c.productConflict.length) { navigate("guide"); return; } addGuideChoice("沿用产品与渠道", { product: c.product, productDeferred: !c.product, platforms: c.platforms }); navigate("analysis"); }
    if (a === "strategy") { const s = strategyOptions().find(s => s.id === id); if (!s) return toast("这个方向已失效，请使用当前推荐。"); selectStrategy(recommendedStrategy([s])); save(); render(); toast("已改用这个方向，可直接确认生成。"); }
    if (a === "shuffle") { d.round++; d.strategyId = ""; d.strategyContext = null; save(); render(); toast("已整理另一组模拟方向，原有成果和已确认需求保持不变。"); }
    if (a === "decide") {
      const c = guideContext();
      if (c.productConflict.length || c.clarification) { navigate("guide"); return toast("有一项修改需要先确认，再继续推荐。"); }
      const s = recommendedStrategy(); selectStrategy(s); save(); render(); toast("已采用当前有效需求下的规则推荐，可直接确认方向。");
    }
    if (a === "result-tab") { state.resultTab = id; render(); }
    if (a === "add-compliance-note") {
      const input = $("#compliance-note"), text = input ? input.value.trim() : ""; if (!text) return toast("先填写核实结果。");
      state.draft.complianceNotes = [...(state.draft.complianceNotes || []), text]; state.draft.revision++; save(); render(); toast("已记入合规清单，生成内容时会保留提醒。");
    }
    if (a === "adjust-strategy") {
      const text = $("#strategy-adjustment").value.trim(); if (!text) return toast("先填写想调整的方向。");
      // Separate creative preferences from field changes; raw history never becomes a strategy input.
      const clauses = text.split(/[，；,;。、\n]+/).map(t => t.trim()).filter(Boolean);
      const preferences = clauses.filter(t => /^(?:请|可以)?(?:更|再|希望|想)?(?:突出|强调)?(?:真实使用场景|真实使用|使用任务|场景)(?:一些|一点)?$|^(?:请)?(?:减少参数(?:介绍|罗列)?|少讲参数|不讲参数|表达(?:得)?更自然|让表达更自然|更自然|自然一些|更口语(?:化)?|更亲切|更突出真实使用场景)$/.test(t));
      const fieldText = clauses.filter(t => !preferences.includes(t)).join("；");
      const info = G.interpret(fieldText);
      if (info.warnings.length) return toast(info.warnings.join(" "));
      if (clauses.some(t => !preferences.includes(t) && !G.interpret(t).recognized && !G.interpret(t).warnings.length)) return toast("这项调整超出当前规则支持范围，方向和原稿保持不变。可尝试更突出真实使用场景、减少参数介绍或更自然。");
      if (fieldText && !info.recognized && !info.warnings.length) return toast("当前模拟规则无法可靠执行这项调整，方向和原稿保持不变；请明确修改产品、目标、受众、平台或使用支持的表达调整。");
      if (Object.keys(d.outputs).length) {
        if (!window.confirm("更新推广方向会使当前成果失效，包括手动编辑。原稿将保存在创作记录，可随时恢复。是否继续？")) return;
        record();
      }
      const previous = d.strategyAdjustment || "";
      if (fieldText) ensureGuide().events.push({ kind: "text", text: fieldText });
      invalidate(); const c = syncGuide();
      if (c.clarification || c.productConflict.length) { d.strategyAdjustment = previous; navigate("guide"); return; }
      d.strategyAdjustment = [...new Set([previous, ...preferences].filter(Boolean))].join("；");
      d.adjustment = ""; save(); render(); toast("已更新主推方向；已确认的其他需求保持不变。当前仍为有限规则模拟。");
    }
    if (a === "generate") { if (guideContext().productConflict.length || guideContext().clarification) return toast("请先回到需求引导确认修改。"); if (!selectedStrategy()) return toast("暂时无法形成方向，请返回需求引导补充信息。"); await generate(); }
    if (a === "output-platform") { d.activePlatform = id; save(); render(); }
    if (a === "toggle-materials") { $(".mc-image-picker-dialog")?.showModal?.(); }
    if (a === "choose-image" || a === "change-image") {
      const o = currentOutput(), keys = mediaKinds;
      ensureOutputMedia(o);
      const kind = a === "choose-image" ? id : keys[(keys.indexOf(o.visualKind) + 1) % keys.length];
      if (!assetOf(kind)) return;
      const occupied = o.imageMode === "multi" ? o.images.find(image => image.id !== o.activeImageId && image.visualKind === kind) : null;
      if (occupied) { const current = o.images.find(image => image.id === o.activeImageId), previousKind = current.visualKind, previous = assetOf(previousKind); Object.assign(occupied, { visualKind: previousKind, visualSrc: previous.src, visualLabel: previous.label, visualAlt: previous.alt }); }
      setOutputImage(o, kind); $(".mc-image-picker-dialog")?.close?.(); record(); render(); toast(occupied ? "已交换两张图片的素材，图片文字与发布文案保持不变。" : "已替换当前图片，其他图片与文案保持不变。");
    }
    if (a === "close-image-picker") $(".mc-image-picker-dialog")?.close?.();
    if (a === "select-result-image") { const o = currentOutput(), image = outputImages(o).find(item => item.id === id); if (!image) return; syncOutputImage(o, image); record(); render(); }
    if (a === "toggle-image-mode") {
      const o = currentOutput();
      if (o.imageMode === "multi") { ensureOutputMedia(o); o.imageMode = "single"; toast("已切换为单图预览；其余图片仍保存在草稿中。"); }
      else { makeMultiImage(o, state.draft.activePlatform); syncOutputImage(o, o.images[0]); toast("已加入不同主题的概念图，可调整顺序或逐张替换。"); }
      record(); render();
    }
    if (a === "add-result-image") {
      const o = currentOutput(), images = outputImages(o), kind = mediaKinds.find(item => !images.some(image => image.visualKind === item));
      if (!kind) return toast("当前本地素材目录最多提供三种不同概念图。");
      const visual = visualAssets[kind], image = { id: `image-${Date.now()}`, visualKind: kind, visualSrc: visual.src, visualLabel: visual.label, visualAlt: visual.alt, visualHeadline: "补充了解相关信息", visualSubline: `${visual.label} · 概念示意`, role: "补充" };
      images.push(image); syncOutputImage(o, image); o.imageMode = "multi"; record(); render(); toast("已添加一张不同主题的概念图。");
    }
    if (a === "move-image-up" || a === "move-image-down") {
      const o = currentOutput(), images = outputImages(o), index = images.findIndex(image => image.id === o.activeImageId), next = index + (a === "move-image-up" ? -1 : 1);
      if (next < 0 || next >= images.length) return toast("当前图片已在序列边界。");
      [images[index], images[next]] = [images[next], images[index]]; record(); render();
    }
    if (a === "remove-result-image") {
      const o = currentOutput(), images = outputImages(o), index = images.findIndex(image => image.id === o.activeImageId);
      if (images.length <= 1) return toast("作品至少保留一张图片。");
      images.splice(index, 1); syncOutputImage(o, images[Math.max(0, index - 1)] || images[0]); record(); render(); toast("已移除当前图片。");
    }
    if (a === "open-regenerate") $(".mc-regenerate-dialog")?.showModal?.();
    if (a === "close-regenerate") $(".mc-regenerate-dialog")?.close?.();
    if (a === "confirm-regenerate") {
      const dialog = $(".mc-regenerate-dialog"), scope = dialog?.querySelector?.('[name="regenerate-scope"]:checked')?.value || "all", direction = $("#regenerate-direction")?.value || "default", o = currentOutput();
      if (!o) return;
      d.previousOutputs = JSON.parse(JSON.stringify(d.outputs));
      const image = outputImages(o).find(item => item.id === o.activeImageId);
      const rotateVisual = () => {
        const desired = direction === "scene" ? "scene" : direction === "concise" ? "editorial" : direction === "warm" ? "dialogue" : mediaKinds[(mediaKinds.indexOf(image.visualKind) + 1) % mediaKinds.length];
        setOutputImage(o, desired);
        image.visualHeadline = direction === "concise" ? "从实际用途看重点" : direction === "warm" ? "先聊聊你的日常需求" : direction === "scene" ? "把真实使用场景说清楚" : `${image.visualLabel} · ${o.strategy?.contentTheme || "推广方向"}`;
        image.visualSubline = direction === "concise" ? "精简信息，突出当前重点" : direction === "warm" ? "用自然表达邀请继续了解" : "本地概念示意 · 使用前核验资料";
        syncOutputImage(o, image);
      };
      const regenerateCopyForDirection = () => {
        const next = createOutputs(d, [d.activePlatform])[d.activePlatform];
        const suffix = direction === "concise" ? "\n\n先整理自己的实际用途，再核对对应产品资料。" : direction === "warm" ? "\n\n如果你也在了解电脑，欢迎带着实际问题继续交流。" : direction === "scene" ? "\n\n可以从每天要完成的实际任务开始了解，再对照可靠资料。" : "";
        Object.assign(o, { title: direction === "concise" ? `${next.title}｜简明参考` : direction === "warm" ? `${next.title}，聊聊你的使用需求` : next.title, body: `${next.body}${suffix}`, cta: next.cta, edited: true, copyEdited: true });
      };
      if (scope === "image") rotateVisual();
      else if (scope === "copy") regenerateCopyForDirection();
      else { regenerateCopyForDirection(); rotateVisual(); o.layout = direction === "concise" ? "editorial" : direction === "scene" ? "scene" : direction === "warm" ? "dialogue" : o.layout; }
      d.generationRound = (d.generationRound || 0) + 1; o.initial ||= JSON.parse(JSON.stringify(o));
      dialog?.close?.(); record(); render(); toast("已按所选范围生成模拟版本；范围外手动修改保留，可撤销。");
    }
    if (a === "preview-image") {
      const dialog = document.createElement("dialog"); dialog.className = "mc-image-dialog";
      const poster = $(".mc-result-poster").cloneNode(true);
      const close = document.createElement("button"); close.textContent = "关闭预览"; close.type = "button"; close.className = "mc-secondary";
      dialog.append(close, poster); $("#marketing-creator-home").append(dialog);
      close.addEventListener("click", () => dialog.close()); dialog.addEventListener("close", () => dialog.remove(), { once: true }); dialog.showModal();
    }
    if (a === "download-poster") { if (e.target.closest("button").disabled) return; const btn = e.target.closest("button"); btn.disabled = true; try { await downloadPoster(); } finally { btn.disabled = false; } }
    if (a === "restore-draft") {
      const o = currentOutput(); if (!o.initial || !window.confirm("恢复初稿将替换当前平台的图片与文案，其他平台草稿保持不变。是否继续？")) return;
      d.outputs[d.activePlatform] = { ...JSON.parse(JSON.stringify(o.initial)), initial: JSON.parse(JSON.stringify(o.initial)) }; record(); render(); toast("已恢复当前平台初稿。");
    }
    if (a === "undo-regenerate" && d.previousOutputs) { d.outputs = d.previousOutputs; delete d.previousOutputs; const s = currentOutput()?.strategy; if (s) { selectStrategy(s); d.outputContext = JSON.parse(JSON.stringify(d.strategyContext)); } record(); render(); toast("已恢复重新生成前的各平台草稿与图片选择。"); }
    if (a === "improve-title") { d.revision++; const o = currentOutput(); const theme = o.strategy.contentTheme || o.strategy.name; o.title = `${d.revision % 2 ? "选电脑参考" : "一起了解"}｜${theme}`; o.edited = true; record(); render(); toast("已替换为另一版模拟标题。"); }
    if (a === "shorten") { const o = currentOutput(); o.previousBody = o.body; o.edited = true; o.body = o.body.split("\n\n").slice(0, 2).join("\n\n") + "\n\n具体产品与门店信息请先核实。"; o.shortened = true; record(); render(); toast("已缩短当前正文，请复核保留的信息。"); }
    if (a === "restore-body") { const o = currentOutput(); if (o.previousBody !== undefined) { o.body = o.previousBody; o.edited = true; delete o.previousBody; record(); render(); toast("已恢复修改前的正文。"); } }
    if (a === "regenerate-copy") {
      if (!window.confirm("仅重写当前平台的发布标题、正文与行动引导，图片及图片文字保持不变。将替换手动文案，可撤销恢复。是否继续？")) return;
      const o = currentOutput();
      const previousCopy = { title: o.title, body: o.body, cta: o.cta, requirementNote: o.requirementNote, tone: o.tone };
      d.generationRound = (d.generationRound || 0) + 1;
      const next = createOutputs(d, [d.activePlatform])[d.activePlatform];
      Object.assign(o, { title: next.title, body: next.body, cta: next.cta, requirementNote: next.requirementNote, tone: next.tone, previousCopy, copyEdited: true });
      record(); render(); toast("已按当前策略生成另一版模拟文案；图片与图片文字保持不变，可撤销。");
    }
    if (a === "undo-copy") { const o = currentOutput(); if (o.previousCopy) { Object.assign(o, o.previousCopy); delete o.previousCopy; record(); render(); toast("已恢复改写前的文案。"); } }
    if (a === "change-angle") { if (!window.confirm("更换角度将替换所有平台的当前编辑内容，可以撤销。是否继续？")) return; const nextAngle = ((selectedStrategy()?.angle || 0) + 1) % 3; d.round++; const s = strategyOptions().find(s => s.angle === nextAngle); if (!s) return; d.previousOutputs = JSON.parse(JSON.stringify(d.outputs)); const outputPlatforms = Object.keys(d.outputs); selectStrategy(s); d.outputContext = JSON.parse(JSON.stringify(d.strategyContext)); d.outputs = createOutputs(d, outputPlatforms); record(); render(); toast("已切换策略角度，并更新各平台模拟草稿；可撤销恢复。"); }
    if (a === "regenerate") { if (!window.confirm("重新生成将替换所有平台的当前编辑内容，是否继续？")) return; d.previousOutputs = JSON.parse(JSON.stringify(d.outputs)); d.revision++; d.generationRound = (d.generationRound || 0) + 1; d.outputs = createOutputs(d, Object.keys(d.outputs)); Object.values(d.outputs).forEach(o => { o.layout = d.generationRound % 2 ? "editorial" : "scene"; o.initial = JSON.parse(JSON.stringify({ ...o, initial: undefined })); }); record(); render(); toast("已生成新的模拟草稿。"); }
    if (a === "update-output") updateOutput();
    if (a === "confirm-fact") { const input = document.querySelector(`[data-fact-note="${id}"]`); const note = input.value.trim(); if (!note) { input.focus(); return toast("请先填写核验结果或资料来源，再确认。"); } d.facts[id] = { note, confirmed: true }; record(); render(); toast("已记录你的人工确认；正文未自动替换，请按核实信息编辑。"); }
    if (a === "copy") await copy();
    if (a === "copy-all") await copy(true);
    if (a === "export") { const blob = new Blob([fullText()], { type: "text/markdown;charset=utf-8" }); const url = URL.createObjectURL(blob), link = document.createElement("a"); link.href = url; link.download = `华为PC-${task().name}-模拟草稿.md`; document.body.append(link); link.click(); link.remove(); setTimeout(() => URL.revokeObjectURL(url), 2000); toast("已导出各平台草稿、配套内容与核验备注。"); }
    if (a === "open-record") { const entry = state.history.find(r => r.id === id); if (entry) { state.draft = { ...fresh(), ...JSON.parse(JSON.stringify(entry.draft)) }; state.guide = entry.guide ? JSON.parse(JSON.stringify(entry.guide)) : null; navigate("results"); } }
    if (a === "delete-record") {
      const entry = state.history.find(r => r.id === id);
      if (!entry) return;
      const title = Object.values(entry.draft.outputs)[0]?.title || "未命名草稿";
      if (!window.confirm(`删除创作记录“${title}”？删除后无法恢复；当前正在编辑的作品不会被清空。`)) return;
      state.history = state.history.filter(r => r.id !== id);
      if (state.draft.recordId === id) state.draft.recordId = null;
      save(); render(); toast("创作记录已删除。");
    }
  });
  document.addEventListener("input", e => {
    const el = e.target, d = state.draft;
    if (el.id === "mc-prompt") { state.homePrompt = el.value; save(); }
    if (el.id === "mc-home-product-search") { homeProductQuery = el.value; renderHomeProducts(); }
    if (el.id === "guide-input") { ensureGuide().composer = el.value; save(); }
    if (el.dataset.field) {
      if (d[el.dataset.field] !== el.value) invalidate();
      d[el.dataset.field] = el.value;
      if (el.dataset.field === "prompt") { (state.guide || ensureGuide()).pendingPrompt = el.value; $("#mc-demand-summary").textContent = d.prompt.trim() || task().prompt; }
      save();
    }
    if (el.dataset.factNote) { d.facts[el.dataset.factNote] = { note: el.value, confirmed: false }; record(); const status = el.closest("details").querySelector(".mc-fact-status"); status.textContent = "待确认"; status.classList.remove("confirmed"); }
    const outputFields = { "output-title": "title", "output-body": "body", "output-visual-headline": "visualHeadline", "output-visual-subline": "visualSubline", "output-cta": "cta" };
    if (outputFields[el.id]) {
      const o = currentOutput(), key = outputFields[el.id];
      const activeImage = outputImages(o).find(item => item.id === o.activeImageId);
      if (key === "cta" && o.cta && o.body.includes(o.cta)) { o.body = o.body.replace(o.cta, el.value); $("#output-body").value = o.body; }
      o[key] = el.value; o.edited = true;
      if (key === "visualHeadline" || key === "visualSubline") {
        if (activeImage) activeImage[key] = el.value;
        o.visualTextEdited = true;
      }
      $("#output-count").textContent = `${o.body.length} 字`; record(); updateResultPreview(); refreshCompliance();
    }
    if (el.id === "result-requirement") { d.adjustment = el.value; save(); }
    if (["product-search", "product-filter"].includes(el.id)) filterProducts();
  });
  document.addEventListener("change", e => {
    if (e.target.id === "product-filter") filterProducts();
    if (e.target.id === "result-platform-select") {
      const d = state.draft, platform = e.target.value;
      if (!["通用草稿", ...platforms].includes(platform)) return;
      if (!d.outputs[platform]) Object.assign(d.outputs, createOutputs(d, [platform]));
      d.activePlatform = platform; record(); render(); toast("已切换发布预览；其他平台编辑与已确认任务渠道均保留。");
    }
  });
  function filterProducts() {
    const query = $("#product-search").value, category = $("#product-filter").value;
    const matches = new Set(D.searchProducts(query, category).map(p => p.id));
    let count = 0;
    document.querySelectorAll(".mc-product-card").forEach(el => { el.hidden = !matches.has(el.dataset.id); if (!el.hidden) count++; });
    $("#product-empty").hidden = count > 0;
  }
  document.addEventListener("keydown", e => {
    if (e.target && e.target.id === "guide-input" && e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      if (e.target.form && typeof e.target.form.requestSubmit === "function") e.target.form.requestSubmit();
    }
  });
  document.addEventListener("submit", e => {
    if (e.target.id === "guide-compose") {
      e.preventDefault(); const g = ensureGuide(), text = $("#guide-input").value;
      if (!text.trim()) return toast("先输入一点想法，或选择上方建议。");
      g.events.push({ kind: "text", text }); g.composer = ""; g.editing = null; g.panel = null;
      beginThinking(ensureGuide());
      invalidate(); syncGuide(); render();
      $("#guide-input").focus(); return;
    }
    if (e.target.id === "guide-summary-form") {
      e.preventDefault(); const form = new FormData(e.target), product = form.get("product");
      addGuideChoice("修改先前回答", { goal: form.get("goal"), audience: form.get("audience").trim(), product, productDeferred: !product });
      ensureGuide().editing = null; render(); return;
    }
    if (e.target.id !== "store-form") return; e.preventDefault();
    const form = new FormData(e.target);
    state.store = { ...state.store, location: form.get("location").trim(), landmarks: form.get("landmarks").trim(), audience: form.get("audience").trim(), platforms: form.getAll("platforms") };
    save(); toast("门店信息已保存，本地推广机会已更新。");
  });
  $("#mc-continue").addEventListener("click", startGuide);
  window.addEventListener("popstate", event => {
    const saved = event.state;
    if (saved?.marketingPrototype) {
      // Keep latest edits within one task, restore snapshots when crossing task boundaries.
      if (saved.draft.taskId !== state.draft.taskId) { state.draft = saved.draft; state.guide = saved.guide; }
      state.page = saved.page === "results" && !Object.keys(state.draft.outputs).length ? "analysis" : saved.page;
      if (saved.opportunityExplorer) state.opportunityExplorer = saved.opportunityExplorer;
      if (state.page !== saved.page) history.replaceState(routeSnapshot(), "", `#${state.page}`);
      save(); render();
    } else navigate(location.hash.slice(1), false);
  });
  window.addEventListener("hashchange", () => {
    const page = location.hash.slice(1);
    if (page !== state.page) navigate(page, false);
  });
  function refreshRecommendations() {
    if (state.recommendation?.day !== calendarDay() && ["home", "opportunities"].includes(state.page)) render();
  }
  document.addEventListener("visibilitychange", () => { if (!document.hidden) refreshRecommendations(); });
  function scheduleDayRefresh() {
    const now = new Date(), midnight = new Date(now.getFullYear(), now.getMonth(), now.getDate() + 1);
    setTimeout(() => { refreshRecommendations(); scheduleDayRefresh(); }, midnight - now + 50);
  }
  scheduleDayRefresh();
  navigate(routes.includes(location.hash.slice(1)) ? location.hash.slice(1) : state.page, false);
  if (storageWarning) toast("本地状态未能恢复；当前操作仍可继续，重要成果请导出。");
})();
