/*
 * 前端模拟数据（成员 B 维护）
 * 仅用于在后端 run_agent() 就绪前演示页面结构，不代表真实 ima 检索结果。
 * 所有事实、图片均为演示占位，接入真实后端后自动停用。
 */
(function () {
  "use strict";

  const PRODUCT = "HUAWEI MateBook 14（演示型号）";
  const SRC = "P1-产品参数库 / 演示资料 article.md";

  const FACTS = {
    collab:   { topic: "多设备协同", claim: "支持华为多屏协同，可与华为手机、平板跨设备互传文件" },
    portable: { topic: "便携", claim: "金属轻薄机身设计，便于日常随身携带（具体重量以参数库原文为准）" },
    battery:  { topic: "续航", claim: "参数库列有电池容量与续航说明，文案只引用原文数值" },
    screen:   { topic: "屏幕", claim: "配备高分辨率护眼屏，资料含低蓝光相关说明" },
    security: { topic: "安全", claim: "支持指纹电源键，一按开机并登录" },
    meeting:  { topic: "会议", claim: "资料包含 AI 通话降噪相关功能说明" },
    perf:     { topic: "性能", claim: "提供多种处理器配置，具体以所选配置资料为准" },
    ease:     { topic: "易用", claim: "预装电脑管家，提供系统优化与服务入口" }
  };

  const TAIL = {
    "多设备协同": "手机里的资料拖到电脑上就能接着编辑，笔记和纪要少一步转存。",
    "便携": "放进通勤包不额外占地方，教室、图书馆、高铁之间来回更轻松。",
    "续航": "实际续航与使用方式有关，这里只引用官方资料中的说明。",
    "屏幕": "长时间看文献、表格和设计稿时更友好。",
    "安全": "离开座位合上屏幕，回来手指一按即可继续。",
    "会议": "在嘈杂环境开线上会议，对方听得更清楚。",
    "性能": "不同配置对应不同强度的任务，建议到店按需挑选。",
    "易用": "家里老人孩子都能更快上手，日常维护也更省心。"
  };

  const HEADLINE = {
    "多设备协同": "多屏协同 · 资料随手流转",
    "便携": "轻薄随行 · 说走就走",
    "续航": "从容一整天的底气",
    "屏幕": "看得清，也看得久",
    "安全": "一按即开 · 安心办公",
    "会议": "会议清晰 · 随处在线",
    "性能": "按需选配 · 刚好够用",
    "易用": "全家上手 · 省心好用"
  };

  const SCENES = {
    "开学季":   { problem: "刚上大学，需要一台能上课、写论文、随身带的电脑", stage: "购前比较", keys: ["portable", "battery", "collab"], angle: "学习、携带、续航与多设备协同" },
    "职场办公": { problem: "经常出差开会，需要在路上处理文档并保证数据安全", stage: "换机评估", keys: ["meeting", "security", "collab", "portable"], angle: "会议、差旅、文档处理与安全" },
    "内容创作": { problem: "需要准确看色，素材在设备之间快速流转", stage: "性能考量", keys: ["screen", "perf", "collab"], angle: "屏幕、性能与素材流转" },
    "家庭换新": { problem: "旧电脑卡顿，想换一台全家都能上手的电脑", stage: "换新决策", keys: ["ease", "screen", "collab"], angle: "易用、全家共用与数据迁移" },
    "企业采购": { problem: "团队批量采购，关注管理、稳定与服务", stage: "方案比选", keys: ["security", "ease", "perf"], angle: "部署管理、稳定性与服务" },
    "门店到访": { problem: "路过门店，想先上手体验再决定", stage: "到店体验", keys: ["collab"], angle: "一个明确卖点 + 到店理由" },
    "新品首发": { problem: "关注新品，想知道有什么变化、适不适合自己", stage: "新品关注", keys: ["screen", "portable", "collab"], angle: "新品变化与适合人群" },
    "节日营销": { problem: "想送一台实用的电脑作为礼物", stage: "礼品选择", keys: ["portable", "collab", "ease"], angle: "使用场景与选择建议" }
  };

  const PLATFORMS = {
    "公众号":     { min: 2, max: 4, use: 3, tone: "专业、条理清晰", structure: "标题 / 导语 / 分段正文 / 结尾行动引导" },
    "小红书":     { min: 3, max: 6, use: 4, tone: "口语化、场景化，不写个人亲历", structure: "口语化标题 / 短段落 / 使用场景 / 话题标签" },
    "门店朋友圈": { min: 1, max: 3, use: 2, tone: "简短、亲切", structure: "短文案 / 一个核心卖点 / 咨询或到店引导" },
    "门店海报":   { min: 1, max: 1, use: 1, tone: "醒目、克制", structure: "主标题 / 副标题 / ≤3 个卖点 / 活动说明" }
  };

  const MEDIA = [
    { name: "产品主图-正面", role: "主图" },
    { name: "使用场景图-桌面", role: "场景图" },
    { name: "多屏协同示意图", role: "功能图" },
    { name: "侧面接口细节图", role: "细节图" },
    { name: "机身配色合集", role: "外观图" },
    { name: "键盘与触控板特写", role: "细节图" }
  ];

  const PRICE_RE = /价格|多少钱|优惠|补贴|国补|折扣|降价|赠品|库存|券/;
  const MODEL_RE = /matebook|matestation|擎云|[a-z]+\s*\d{2}|\d{2}\s*[a-z]?/i;

  function pickFacts(sceneName) {
    const s = SCENES[sceneName] || SCENES["开学季"];
    return s.keys.map((k) => ({ ...FACTS[k], key: k, source: SRC, model: PRODUCT }));
  }

  function buildMedia(platform, n, posFn) {
    return MEDIA.slice(0, n).map((m, i) => ({
      ...m,
      url: "",
      source: "ima 知识库 / 演示图片库",
      model: PRODUCT,
      status: "usable",
      position: posFn(i),
      insert_after: i,
      caption: `${m.role}：用于说明「${m.name.split("-")[0]}」，演示占位`
    }));
  }

  function buildContent(input, facts) {
    const aud = input.audience || "目标用户";
    const scene = input.scene || "日常";
    const s = SCENES[scene] || SCENES["开学季"];
    const p = input.platform;
    const core = facts[0];

    if (p === "公众号") {
      return {
        content: {
          title: `${scene}选电脑，${aud}先想清楚这 ${facts.length} 件事`,
          lead: `${s.problem}。本文从${s.angle}几个角度，结合华为官方产品资料，帮你判断 ${PRODUCT} 是否合适。`,
          sections: facts.map((f, i) => ({ heading: `${i + 1}. ${f.topic}`, text: `${f.claim}。${TAIL[f.topic]}` })),
          cta: "欢迎到附近华为门店上手体验，或在后台留言预约导购讲解。",
          tags: []
        },
        media: buildMedia(p, 3, (i) => ["导语后", "第 1 段后", "第 2 段后"][i])
      };
    }
    if (p === "小红书") {
      return {
        content: {
          title: `${aud}看过来｜${scene}挑电脑，这几点值得看`,
          body: [
            `如果你也是${aud}，正在为${scene}挑电脑，可以先看看这几点：`,
            ...facts.map((f) => `✅ ${f.topic}：${f.claim}`),
            `适合场景：${s.problem.replace(/^./, (c) => c)}。`,
            "以上信息整理自华为官方产品资料，具体配置建议到店对比。"
          ].join("\n\n"),
          cta: "先收藏，到店时对照着看",
          tags: ["#华为MateBook", `#${scene}`, `#${aud}`, "#笔记本电脑怎么选", "#多屏协同"]
        },
        media: buildMedia(p, 4, (i) => ["封面", "第 2 张", "第 3 张", "第 4 张"][i])
      };
    }
    if (p === "门店朋友圈") {
      return {
        content: {
          title: "",
          body: `${scene}来店里看看 ${PRODUCT}：${core.claim}。`,
          cta: "本周可到店上手体验，有问题直接私信我。",
          tags: [],
          selling_points: [core.topic]
        },
        media: buildMedia(p, 2, (i) => ["九宫格第 1 张", "九宫格第 2 张"][i])
      };
    }
    // 门店海报
    return {
      content: {
        title: HEADLINE[core.topic] || core.topic,
        subtitle: `${aud} · ${scene}推荐 ${PRODUCT}`,
        selling_points: facts.slice(0, 3).map((f) => f.claim.split("，")[0]),
        activity: "",
        cta: "欢迎进店体验",
        tags: []
      },
      media: buildMedia(p, 1, () => "主视觉")
    };
  }

  function checksFor(platform, facts, media, extra) {
    const spec = PLATFORMS[platform];
    const usable = media.filter((m) => m.status === "usable").length;
    const list = [
      { item: "model_match", label: "型号一致性", result: "pass", reason: `事实与图片均对应「${PRODUCT}」`, blocking: false },
      { item: "fact_trace", label: "事实可追溯", result: "pass", reason: `${facts.length} 条事实均附资料来源`, blocking: false },
      {
        item: "image_count", label: "图片数量",
        result: usable >= spec.min ? "pass" : "warning",
        reason: `${platform}要求 ${spec.min}–${spec.max} 张，当前可用 ${usable} 张`,
        blocking: false
      },
      { item: "absolute_words", label: "绝对化用语", result: "pass", reason: "未检出「最强」「第一」「100%」等表述", blocking: false },
      { item: "price_claim", label: "价格 / 优惠", result: "pass", reason: "文案未涉及价格、补贴、库存", blocking: false },
      { item: "experience", label: "虚构体验", result: "pass", reason: "未使用第一人称亲历叙述", blocking: false }
    ];
    if (facts.some((f) => f.key === "battery")) {
      list.push({ item: "battery_value", label: "续航数值", result: "unknown", reason: "演示资料未含续航原文数值，文案未写具体数字", blocking: false });
    }
    return list.concat(extra || []);
  }

  function trace(upTo, mark, detail) {
    const steps = ["scene", "strategy", "retrieve", "facts", "layout", "generate", "verify", "compliance", "export"];
    const idx = upTo == null ? steps.length : steps.indexOf(upTo);
    return steps.map((k, i) => ({
      step: k,
      status: i < idx ? "done" : i === idx ? mark : "skipped",
      detail: i === idx ? detail : ""
    }));
  }

  function run(input, forced) {
    const p = input.platform || "公众号";
    const text = `${input.goal || ""} ${input.extra_requirements || ""}`;
    const product = (input.product_query || "").trim();
    const sceneName = input.scene || "";
    const s = SCENES[sceneName] || SCENES["开学季"];
    const spec = PLATFORMS[p] || PLATFORMS["公众号"];

    const scenario = {
      audience: input.audience || "待确认",
      scene: sceneName || "待确认",
      platform: p,
      goal: input.goal || "",
      problem: s.problem,
      stage: s.stage,
      strategy: `${spec.tone}；切入点：${s.angle}`,
      structure: spec.structure
    };

    let status = forced && forced !== "auto" ? forced : null;
    const vague = !MODEL_RE.test(product);
    const askPrice = PRICE_RE.test(text);
    if (!status) {
      if (vague) status = "needs_input";
      else if (askPrice) status = "needs_input";
      else status = "success";
    }

    const empty = { title: "", subtitle: "", lead: "", body: "", sections: [], cta: "", tags: [], selling_points: [], activity: "" };

    if (status === "needs_input") {
      const questions = vague
        ? [
            "请确认具体型号（例如 MateBook 14 / MateBook X Pro），知识库中存在多款相近机型。",
            "主要用途是什么？学习办公、出差移动，还是设计创作？",
            "对屏幕尺寸或重量有偏好吗？"
          ]
        : [
            "知识库中没有该型号的价格或优惠资料，请提供活动依据（活动名称、时间、官方来源）。",
            "如果暂时没有活动依据，是否改为只生成产品介绍？"
          ];
      return {
        status,
        scenario: { ...scenario, strategy: "信息不足，暂停生成并追问" },
        evidence: { facts: vague ? [] : pickFacts(sceneName).slice(0, 2), media: [] },
        content: empty,
        checks: [
          vague
            ? { item: "model_match", label: "型号识别", result: "fail", reason: `「${product || "空"}」无法对应到唯一型号`, blocking: true }
            : { item: "price_claim", label: "价格 / 优惠", result: "fail", reason: "用户要求价格推广，但知识库无依据", blocking: true }
        ],
        questions,
        conflicts: [],
        error: null,
        trace: trace(vague ? "scene" : "facts", "paused", vague ? "型号模糊，需用户确认" : "价格无依据，需补充材料"),
        _mock: true
      };
    }

    if (status === "conflict") {
      const facts = pickFacts(sceneName);
      return {
        status,
        scenario,
        evidence: { facts, media: buildMedia(p, 2, () => "待定") },
        content: empty,
        checks: [{ item: "model_match", label: "配置冲突", result: "fail", reason: "两份资料对同一型号的内存配置描述不一致", blocking: true }],
        questions: ["请确认本次推广的具体配置版本，或指定以哪份资料为准。"],
        conflicts: [
          {
            field: "内存配置",
            a: { value: "16GB 版本", source: "P1-产品参数库 / MateBook 14 article.md" },
            b: { value: "仅提供 32GB 版本", source: "P3-门店物料 / 新品海报文案.md" }
          }
        ],
        error: null,
        trace: trace("verify", "paused", "资料冲突，停止输出"),
        _mock: true
      };
    }

    if (status === "error") {
      return {
        status,
        scenario,
        evidence: { facts: [], media: [] },
        content: empty,
        checks: [],
        questions: [],
        conflicts: [],
        error: { code: "IMA_TIMEOUT", message: "ima 知识库检索超时（演示）", retry: "检查网络与环境变量后重试；如持续失败，改用 get_knowledge_list 目录回退。" },
        trace: trace("retrieve", "failed", "search_knowledge 超时"),
        _mock: true
      };
    }

    const facts = pickFacts(sceneName);
    const built = buildContent({ ...input, platform: p }, facts);
    let media = built.media;
    let extraChecks = [];
    let questions = [];

    if (status === "partial") {
      media = media.slice(0, Math.max(1, spec.min - 1));
      media.push({ ...MEDIA[4], url: "", source: "ima 知识库 / 未知目录", model: "MateBook 14s（疑似）", status: "model_mismatch", position: "未使用", caption: "型号与当前产品不一致，已排除" });
      if (spec.min > 1) {
        extraChecks.push({ item: "image_model", label: "图片型号", result: "warning", reason: "1 张图片型号不匹配，已排除，未用重复图片凑数", blocking: false });
      }
      questions = [`${p}需至少 ${spec.min} 张可用图片，请从知识库补充同型号图片后再发布。`];
    }

    return {
      status,
      scenario,
      evidence: { facts, media },
      content: { ...empty, ...built.content },
      checks: checksFor(p, facts, media, extraChecks),
      questions,
      conflicts: [],
      error: null,
      trace: trace(null),
      _mock: true
    };
  }

  window.MOCK = { run, PLATFORMS, SCENES };
})();
