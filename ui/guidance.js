/* Deterministic frontend prototype. No model, product validation, or market inference. */
(() => {
  "use strict";
  const goals = [
    { id: "store", label: "吸引顾客到店体验", task: "store" },
    { id: "needs", label: "帮助顾客明确选购需求", task: "seeding" },
    { id: "awareness", label: "建立产品认知", task: "seeding" },
    { id: "consultation", label: "促进产品咨询", task: "seeding" }
  ];
  const names = { needs: "帮助顾客明确选购需求", store: "吸引顾客到店体验", awareness: "建立产品认知", consultation: "促进产品咨询", launch: "介绍新品信息", season: "围绕节点整理需求" };
  const compact = value => String(value).normalize("NFKC").toLowerCase().replace(/[\s\p{P}\p{S}]+/gu, "");
  const aliases = window.MarketingPrototypeData.products.map(p => [p.id, [p.name, p.name.replace(/^HUAWEI\s*/i, ""), ...(p.aliases || [])].map(compact).map(name => new RegExp(name.replace(/[.*+?^${}()|[\]\\]/g, "\\$&") + "(?![a-z0-9])", "i"))]);
  const sceneRules = [
    ["travel", /差旅|出差|移动办公|通勤/, "差旅办公"],
    ["study", /课程|学习|校园|大学生|学生/, "学习用途"],
    ["office", /日常办公|职场|上班族|办公人群/, "日常办公"]
  ];
  const mentions = value => aliases.filter(([, rules]) => rules.some(rule => rule.test(compact(value)))).map(([id]) => id);
  // Only bounded, explicit expressions are interpreted. Transcript text is never a fallback value.
  function interpret(text) {
    const patch = {}, warnings = [], excluded = [], removedProducts = [], removedPlatforms = [];
    const allProducts = [], goalIds = [];
    const removedAudiences = [];
    let lastNegativeField = "";
    const clauses = String(text || "").replace(/((?:主题|创意))(?:改成|改为|换成)/g, "$1：").replace(/(?:改成|改为|换成|改发)/g, "，改为").split(/[，。；,;\n]+/).map(t => t.trim()).filter(Boolean);
    for (const clause of clauses) {
      // An explicit creative brief is an effective field, not a new source of product facts.
      const theme = clause.match(/^(?:推广)?(?:主题|创意)(?:改为|改成|换成|是|为|：|:)\s*(.+)$/)?.[1]?.trim();
      if (/^(?:清空|清除|取消)(?:推广)?(?:主题|创意)$/.test(clause)) { patch.creative = ""; continue; }
      if (theme) {
        if (theme.length > 60 || /优惠|折|赠|库存|有货|性能|续航|小时|元|%|保证|一定|独家/.test(theme)) warnings.push("这项创意包含需要核实的承诺或超出当前主题规则，请确认资料后再调整；原主题不会被替换。");
        else patch.creative = theme;
        continue;
      }
      const negative = /^(?:请)?(?:不要|不再|不想|不需要|不以|不做|不考虑|不推广|不面向|不是|取消|清空|清除|移除|去掉|先不|暂不)/.test(clause);
      const ids = mentions(clause);
      const channels = ["微信朋友圈", "小红书", "视频号", "其他平台"].filter(p => clause.includes(p) || (p === "微信朋友圈" && clause.includes("朋友圈")));
      if (/不(?:要|再)?(?:指定|选择|确定|推广)(?:任何)?产品|先不选型号|暂不(?:选择|指定)(?:产品|型号)|清空产品|清除产品/.test(clause)) {
        patch.product = ""; patch.productMentions = []; patch.productDeferred = true; lastNegativeField = "product";
      } else if (negative && ids.length) { removedProducts.push(...ids); lastNegativeField = "product"; }
      else if (ids.length) { if (/^改为/.test(clause)) allProducts.length = 0; allProducts.push(...ids); patch.productDeferred = false; }
      else if (/MateBook|笔记本型号/i.test(clause) && /改成|改为|换成|更换/.test(clause)) warnings.push("型号未在演示目录中可靠识别，请搜索或选择讨论产品。");
      if (/清(?:空|除)(?:发布)?(?:平台|渠道)|不(?:指定|选择)(?:发布)?(?:平台|渠道)|暂不(?:指定|选择)(?:发布)?(?:平台|渠道)/.test(clause)) {
        patch.platforms = []; lastNegativeField = "platforms";
      } else if (negative && channels.length) { removedPlatforms.push(...channels); lastNegativeField = "platforms"; }
      else if (channels.length) patch.platforms = channels;
      if (!channels.length && /平台|渠道/.test(clause) && /改|换/.test(clause) && !Object.hasOwn(patch, "platforms")) warnings.push("发布渠道未被当前模拟目录可靠识别，请确认渠道选择。");
      const audience = /退休老人|老年人|银发/.test(clause) ? "退休老人" : /大学生|高校|校园/.test(clause) ? "附近大学生" : /学生|课程|学习/.test(clause) ? "有学习需求的顾客" : /差旅|出差|通勤/.test(clause) ? "经常出差、需要移动办公的顾客" : /上班族|办公人群|职场/.test(clause) ? "有办公需求的顾客" : "";
      const explicitAudience = clause.match(/(?:面向|受众(?:改为|改成|是|为|：|:))\s*(.+?)(?=，|；|推广|介绍|用小红书|用朋友圈|$)/)?.[1]?.replace(/了$/, "").trim();
      if (/清(?:空|除)(?:目标)?(?:受众|人群)|暂不(?:指定|确定)(?:受众|人群)|不(?:指定|限制)(?:受众|人群)/.test(clause)) { patch.audience = ""; lastNegativeField = "audience"; }
      else if (negative && /面向|受众|人群|大学生|学生|退休老人|老年人/.test(clause)) { if (audience) removedAudiences.push(audience); else patch.audience = ""; lastNegativeField = "audience"; }
      else if (!negative && (audience || explicitAudience)) patch.audience = audience || explicitAudience;
      else if (lastNegativeField === "audience" && /^(?:改为|改成|换成)/.test(clause) && clause.length < 32) patch.audience = clause.replace(/^(?:改为|改成|换成)/, "");
      for (const [id, rule, label] of sceneRules) if (rule.test(clause)) {
        if (negative) { excluded.push(id); }
        else patch.scene = label;
      }
      if (/清(?:空|除)场景|暂不指定场景/.test(clause)) patch.scene = "";
      const found = [];
      if (/到店|来店|进店|引流|店里体验/.test(clause)) found.push("store");
      if (/认知|种草|了解产品|介绍产品|产品介绍|推广产品/.test(clause)) found.push("awareness");
      if (/明确选购需求|梳理选购需求|帮.*理清需求|(?:帮助|帮).*判断.*(?:适合|合适)|产品.*是否适合自己/.test(clause)) found.push("needs");
      if (/购买咨询|产品咨询|咨询购买|购买意向|转化|成交|促进购买/.test(clause)) found.push("consultation");
      if (!found.length && /新品|上市/.test(clause)) found.push("launch");
      if (!found.length && /节日|节点|开学/.test(clause)) found.push("season");
      if (negative && found.length) { patch.goal = ""; lastNegativeField = "goal"; }
      else if (found.length) { if (/^改为/.test(clause)) goalIds.length = 0; goalIds.push(...found); }
      if (/清(?:空|除)(?:推广)?目标|暂不确定目标/.test(clause)) patch.goal = "";
      if (/更短|简短|精简|缩短/.test(clause) && !negative) patch.short = true;
      if (/不提价格|不写价格|不要价格/.test(clause)) patch.noPrice = true;
      if (/恢复完整长度|不要缩短/.test(clause)) patch.short = false;
      if (/可以提价格/.test(clause)) patch.noPrice = false;
      if (/改为|改成|换成|取消|清空|清除|不要|不再/.test(clause) && !ids.length && !channels.length && !audience && !explicitAudience && !found.length && !sceneRules.some(([,r]) => r.test(clause)) && !/产品|型号|平台|渠道|受众|人群|场景|目标|价格|缩短/.test(clause)) warnings.push("这项修改超出当前模拟规则，请在需求摘要中确认，或明确指出要修改的字段。");
    }
    const products = [...new Set(allProducts)].filter(id => !removedProducts.includes(id));
    if (products.length) { patch.product = products.length === 1 ? products[0] : ""; patch.productMentions = products; }
    if (goalIds.length) { patch.goal = goalIds[0]; patch.priorities = [...new Set(goalIds)]; }
    return { patch, warnings, products, goalIds, removedProducts, removedPlatforms, removedAudiences, excluded, recognized: Boolean(Object.keys(patch).length || removedProducts.length || removedPlatforms.length || removedAudiences.length || excluded.length) };
  }
  function recognize(text) {
    const info = interpret(text);
    return { ...info, audience: info.patch.audience || "", platforms: info.patch.platforms || [] };
  }
  function create(prompt = "", seed = {}) {
    const events = [];
    if (prompt.trim()) events.push({ kind: "text", text: prompt });
    if (Object.keys(seed).length) {
      const textProducts = interpret(prompt).products;
      const patch = seed.product && textProducts.length && !textProducts.includes(seed.product)
        ? { product: "", productConflict: [...new Set([seed.product, ...textProducts])] } : seed;
      events.push({ kind: "choice", text: "沿用已有任务信息", patch });
    }
    return { version: 2, events, candidateRound: 0, directionRound: 0, composer: "", editing: null, panel: null };
  }
  function resolve(guide, opportunity, through = guide.events.length) {
    const c = { opportunity, focus: "", productRequested: false, goal: "", task: opportunity?.task || "seeding", product: "", productDeferred: false, audience: "", scene: "", creative: "", excludedScenes: [], short: false, noPrice: false, fieldStatus: { product: "unset", audience: "unset", platforms: "unset", scene: "unset", creative: "unset", goal: "unset" }, platforms: Array.isArray(guide.defaultPlatforms) ? [...guide.defaultPlatforms] : ["微信朋友圈"], platformSource: "建议默认，可修改", priorities: [], notes: [], recognized: Boolean(opportunity), productMentions: [], productConflict: [], clarification: "" };
    for (const event of guide.events.slice(0, through)) {
      const info = event.kind === "text" ? interpret(event.text) : null;
      const patch = { ...(info?.patch || event.patch || {}) };
      if (info) {
        if (info.removedProducts.includes(c.product) && !Object.hasOwn(patch, "product")) { patch.product = ""; patch.productDeferred = true; }
        if (info.removedPlatforms.length && !Object.hasOwn(patch, "platforms")) patch.platforms = c.platforms.filter(p => !info.removedPlatforms.includes(p));
        if (info.removedAudiences.includes(c.audience) && !Object.hasOwn(patch, "audience")) patch.audience = "";
        if (info.excluded.some(id => sceneRules.find(([key]) => key === id)?.[1].test(c.scene)) && !Object.hasOwn(patch, "scene")) patch.scene = "";
        c.productMentions = c.productMentions.filter(id => !info.removedProducts.includes(id));
        c.excludedScenes = [...new Set([...c.excludedScenes, ...info.excluded])];
        if (patch.scene) { const id = sceneRules.find(([,r]) => r.test(patch.scene))?.[0]; c.excludedScenes = c.excludedScenes.filter(v => v !== id); }
        c.clarification = info.warnings.join(" ");
        if (event !== guide.events[0]) c.notes.push(event.text);
      } else if (Object.keys(patch).length) c.clarification = "";
      if (Object.hasOwn(patch, "goal") && patch.goal !== c.goal) { c.focus = ""; c.productRequested = false; }
      for (const field of Object.keys(c.fieldStatus)) if (Object.hasOwn(patch, field)) c.fieldStatus[field] = Array.isArray(patch[field]) ? (patch[field].length ? "confirmed" : "cleared") : patch[field] ? "confirmed" : "cleared";
      Object.assign(c, patch);
      if (Object.hasOwn(patch, "product") && !patch.productConflict) { c.productConflict = []; c.productMentions = patch.productMentions || (patch.product ? [patch.product] : []); }
      if (patch.goal) { c.priorities = patch.priorities?.length > 1 ? patch.priorities : []; c.task = goals.find(g => g.id === patch.goal)?.task || patch.task || patch.goal; }
      if (Object.hasOwn(patch, "goal") && !patch.goal) { c.priorities = []; c.task = "seeding"; }
      if (patch.product) c.productDeferred = false;
      if (Object.hasOwn(patch, "platforms")) c.platformSource = c.platforms.length ? "由你确认" : "已清除，稍后再确定";
      if (patch.note) c.notes.push(patch.note);
      c.recognized ||= info?.recognized || Boolean(Object.keys(patch).length);
    }
    return c;
  }
  function respectExclusions(value, excluded = []) {
    let text = String(value);
    const words = { travel: /差旅|出差|移动办公|通勤/g, study: /课程学习|学习|课程|校园|大学生|学生/g, office: /日常办公|职场|上班族|办公人群/g };
    for (const id of excluded) if (words[id]) text = text.replace(words[id], "实际使用");
    return text;
  }
  function stage(c) {
    if (c.productConflict?.length) return "product-conflict";
    if (c.clarification) return "clarification";
    if (!c.goal) return c.opportunity ? "opportunity-goal" : "direction";
    if (c.priorities.length > 1) return "priority";
    if (c.opportunity && !c.focus) return "opportunity-focus";
    if (!c.product && !c.productDeferred && (!c.opportunity || c.productRequested)) return "product";
    return "ready";
  }
  function response(c, event, count) {
    if (c.productConflict?.length) return "首页选择与文字中提到的产品不同，请确认本次讨论型号；确认前不会生成策略。";
    if (c.clarification) return `这段补充已原样保留。当前模拟规则还不能可靠提取其中的全部修改。${c.clarification}`;
    const read = event?.kind === "text" ? recognize(event.text) : null;
    const ack = read && !read.recognized ? "这段补充已原样保留。当前模拟规则还不能可靠提取其中的新目标或型号，你可以选择下方方向，也可以继续描述。" : c.audience ? `已记下：面向${c.audience}，${names[c.goal] || "推广目标还待明确"}。` : `当前方向：${names[c.goal] || "先梳理值得尝试的推广方向"}。`;
    if (read && !read.recognized) return ack;
    if (!count && c.opportunity) return opportunityIntro(c.opportunity, c);
    if (!count) return "不必先准备完整方案。可以说一个想解决的问题，或从下方选择一个方向；没有型号和渠道也能先看策略。";
    const questions = {
      "opportunity-goal": "这条机会的推广目标还未确认。选择当前更希望顾客完成的一件事；也可由模拟规则提出有理由的建议。",
      "opportunity-focus": focusQuestion(c),
      direction: "先探索下面哪一个方向？这些是供选择的建议，不代表已验证的市场机会。",
      priority: "你提到了多个目标。这次哪一个更优先？也可以由模拟规则给出建议。",
      product: c.productMentions.length > 1 ? "你提到了多个型号。先选一个作为本次讨论对象，或暂不指定型号。" : "还没有确定主推型号。下面按演示选题标签列出候选，仅用于讨论；真实性能和适配性需要核验。",
      ready: "已有信息足以整理第一版策略。不再重复询问已明确的产品和目标；受众、渠道等可随时修改，未确认的条件会保留为待核实项。"
    };
    const focus = focusOptions(c).find(item => item.id === c.focus);
    const next = c.opportunity && stage(c) === "ready" ? `围绕「${c.opportunity.title}」，将优先做${focus?.title || names[c.goal]}。${focus?.note || ""}可以先比较策略，不必现在指定产品或渠道；门店条件与产品适配仍待核实。` : questions[stage(c)];
    return `${ack}${event?.patch?.recommendationReason ? `\n\n规则建议理由：${event.patch.recommendationReason}` : ""}\n\n${next}`;
  }

  // Opportunity profiles describe editorial hypotheses, never customer demand or product suitability.
  function profile(o) {
    const profiles = {
      "date-refresh": { goals: ["store", "needs", "consultation"], auto: "needs", intro: "新学习或工作任务可以成为介绍华为 PC 的切入点：先问顾客打算完成什么，再核验哪些产品信息与任务相关。这样能把泛泛的参数介绍变成有比较依据的沟通，也允许顾客继续使用现有设备。", reason: "这条机会尚未给出具体型号、体验条件或购买意愿，先帮助顾客明确选购标准更稳妥，之后再判断是否需要产品比较或到店沟通。" },
      "software-questions": { goals: ["needs", "consultation", "awareness"], auto: "needs", intro: "软件名称与版本能帮助店员问出具体工作任务，再查证华为 PC 型号的兼容性与配置要求。可以先做软件任务问答，而不是直接声称产品能运行某个软件。", reason: "软件与配置都还未核实，先收集任务、版本和使用频率，再形成选购标准，比直接介绍产品性能更有依据。" },
      "consultation-list": { goals: ["store", "consultation", "needs"], auto: "store", intro: "这条机会把华为 PC 的选购问题与到店前沟通连起来：内容先说明顾客能准备哪些问题，再引导联系门店核对展示和服务安排。到店价值需要被具体说明，不能默认门店已有体验条件。", reason: "机会本身聚焦到店前准备，可优先设计有条件的到店路径；地址、实机与服务未确认前，只能引导联系核实，不承诺体验。" },
      local: { goals: ["awareness", "needs", "consultation"], auto: "awareness", intro: "门店周边线索只能提出观察问题，不能证明实际客群。可先征集顾客的学习或办公用途，再核验哪些华为 PC 信息值得介绍，避免把附近地标直接写成购买需求。", reason: "目前只有环境线索，先收集真实问题与内容反馈，比直接引流或推型号更合适；客群和推广效果仍需门店验证。" }
    };
    return profiles[o?.id] || { goals: ["needs", "awareness", "consultation"], auto: "needs", intro: "可把这条机会作为华为 PC 内容选题的假设，先理解使用任务，再核实产品信息是否足以支撑介绍。", reason: "现有依据不足以认定产品适配，建议先明确需求和比较标准。" };
  }
  function opportunityIntro(o, c) {
    return `${profile(o).intro}\n\n这是推广思路，尚未验证真实顾客需求或购买意愿。${c?.goal ? `已沿用你补充的目标「${names[c.goal]}」，接下来只确认影响策略的重点。` : "推广目标还没有确定：不同目标将形成不同的内容与行动路径，请先选一个重点。"}`;
  }
  const goalLabels = { store: "吸引顾客到店体验", needs: "帮助顾客明确选购需求", consultation: "促进产品咨询", awareness: "建立产品认知" };
  const goalNotes = { store: "围绕真实使用场景设计体验内容，展示与服务需先确认。", needs: "从用途、软件与预算切入，帮助顾客形成比较标准。", consultation: "围绕顾客关心的问题，设计进一步沟通的入口。", awareness: "先收集问题，再介绍经核实的产品信息。" };
  const opportunityGoals = o => profile(o).goals.map(id => ({ id, title: goalLabels[id], note: goalNotes[id] }));
  function recommend(c) {
    const id = c.opportunity ? profile(c.opportunity).auto : c.goal || "awareness";
    return { goal: id, recommendationReason: c.opportunity ? profile(c.opportunity).reason : "先从已有信息明确需求与问题，再核验适配；这不是已验证的效果预测。" };
  }
  function focusQuestion(c) {
    return ({ store: "先把到店的价值说清楚：更希望顾客对照实际任务观察产品，还是先确认到访路径？体验条件尚待核实。", needs: "先选一种需求梳理方式：做任务与软件清单，还是建立产品比较依据？不预设顾客必须换新。", consultation: "先确定如何开启沟通：集中解答具体问题，还是从一个使用任务开始逐步补充信息？", awareness: "当前线索不足以判断需求。先征集使用问题，还是准备一份可核验资料的导读？" })[c.goal] || "本次先围绕哪一个内容重点展开？";
  }
  function focusOptions(c) {
    const subject = c.opportunity?.id === "software-questions" ? "软件版本、具体任务与使用频率" : c.opportunity?.id === "local" ? "门店实际收集到的用途问题" : "学习或工作任务、常用软件与预算";
    return ({
      store: [{ id: "experience", title: "先设计场景体验内容", note: "列出顾客可以带来的真实任务，再向门店确认展示型号和可提供的体验。" }, { id: "visit", title: "先理清到店行动路径", note: "先线上收集问题，核对地址、时间和服务后，再由顾客决定是否到访。" }],
      needs: [{ id: "checklist", title: "先做需求梳理清单", note: `收集${subject}，检查现有设备是否够用，不急着指定型号。` }, { id: "match", title: "先建立产品比较依据", note: "可查看演示产品候选；用任务与资料来源建立比较表，适配结论待核实。", productRequested: true }],
      consultation: [{ id: "faq", title: "用具体问题开启咨询", note: `围绕${subject}设计问答，不提前承诺产品结论。` }, { id: "private", title: "从一个用途问题开始沟通", note: "让顾客先说一项使用任务，再按需补充软件与频率，由店员按资料回复。" }],
      awareness: [{ id: "listen", title: "先征集真实使用问题", note: "以回复和门店观察收集线索；地标不等于客群，反馈不等于购买需求。" }, { id: "sources", title: "先组织可核验的资料导读", note: "核对具体型号、资料来源和用途关联，再准备产品介绍。" }]
    })[c.goal] || [{ id: "checklist", title: "先梳理任务与资料", note: "围绕当前机会核对依据，再决定产品沟通方向。" }];
  }

  function candidates(c, products, round = 0) {
    // These tags describe demo editorial topics, never hardware abilities or actual stock.
    const topics = {
      "matebook-14": { tags: ["学习", "咨询"], reason: "演示选题标签含学习需求访谈，可用于整理课程与软件问题。" },
      "matebook-d": { tags: ["办公", "咨询"], reason: "演示选题标签含日常办公问答，可用于整理用途与预算问题。" },
      "matebook-x-pro": { tags: ["差旅", "认知"], reason: "演示选题标签含移动场景观察，可用于整理携带与使用方式问题。" }
    };
    const desired = /学生|学习/.test(c.audience) ? "学习" : /差旅|出差/.test(c.audience) ? "差旅" : c.goal === "store" || c.goal === "consultation" ? "咨询" : "办公";
    const list = products.filter(p => !c.productMentions.length || c.productMentions.includes(p.id)).map(p => ({ ...p, demoReason: topics[p.id]?.reason || "作为示例目录中的一个待比较选项。", topicMatch: topics[p.id]?.tags.includes(desired) ? 0 : 1 })).sort((a, b) => a.topicMatch - b.topicMatch);
    const offset = list.length ? round % list.length : 0;
    return [...list.slice(offset), ...list.slice(0, offset)].slice(0, 2);
  }
  const directions = round => (round % 2 ? [
    { id: "awareness", title: "先收集常用软件问题", note: "先问需求，再准备产品适配问答；兼容性待核实。" },
    { id: "consultation", title: "做一份选购取舍清单", note: "围绕用途与预算展开咨询，不预设购买结论。" },
    { id: "store", title: "把咨询前的准备讲清楚", note: "明确顾客可准备的问题，到访条件需门店确认。" }
  ] : [
    { id: "store", title: "让顾客带着问题来咨询", note: "从用途与疑问切入；是否提供体验服务待确认。" },
    { id: "awareness", title: "从使用场景认识产品", note: "收集真实任务，核验后再介绍产品功能。" },
    { id: "consultation", title: "帮助顾客做选购比较", note: "先梳理需求和预算，再讨论是否适合。" }
  ]);
  window.MarketingGuidance = { goals, names, recognize, create, resolve, stage, response, candidates, directions, opportunityIntro, opportunityGoals, recommend, focusOptions, focusQuestion, interpret, respectExclusions };
})();
