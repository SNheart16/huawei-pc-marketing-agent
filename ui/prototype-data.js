(() => {
  const products = [
    { id: "matebook-x-pro", name: "HUAWEI MateBook X Pro", category: "轻薄本", note: "产品名称为原型示例；型号规格与配置请以门店资料核实。", facts: ["华为 MateBook 系列笔记本电脑", "具体型号、配置及功能需门店核验"] },
    { id: "matebook-14", name: "HUAWEI MateBook 14", category: "轻薄本", note: "仅用于展示流程，不代表实时在售型号。", facts: ["华为 MateBook 系列笔记本电脑", "屏幕、处理器及续航参数需门店核验"] },
    { id: "matebook-d", name: "HUAWEI MateBook D 系列", category: "日常办公", note: "系列级演示选项；具体代际与配置需确认。", facts: ["华为 MateBook D 系列笔记本电脑", "具体产品代际与配置需门店核验"] },
    // Name-only mock entries: extend this catalog, never invent a search result.
    ...[
      ["matebook-d-14", "D 14", ["D14", "华为D14"]],
      ["matebook-d-16", "D 16", ["D16", "华为D16"]],
      ["matebook-16", "16", ["华为16"]],
      ["matebook-16s", "16s", ["华为16s"]],
      ["matebook-x", "X", ["华为X"]]
    ].map(([id, model, aliases]) => ({ id, name: `HUAWEI MateBook ${model}`, model, family: model.startsWith("D") ? "MateBook D 系列" : "MateBook 系列", aliases, category: "型号示例", note: "演示目录中的名称条目，不代表当前在售；代际、配置和适配情况待核实。", facts: ["仅收录产品名称作为讨论对象", "具体型号、配置、价格与在售状态待核实"] }))
  ];

  Object.assign(products[0], { model: "X Pro", family: "MateBook 系列", aliases: ["X Pro", "华为XPro"] });
  Object.assign(products[1], { model: "14", family: "MateBook 系列", aliases: ["华为14"] });
  Object.assign(products[2], { model: "D 系列", family: "MateBook D 系列", aliases: ["MateBook D", "华为D系列"] });

  const normalizeProductQuery = value => String(value || "").normalize("NFKC").toLowerCase().replace(/[\s\p{P}\p{S}]+/gu, "");
  function searchProducts(query = "", category = "") {
    const terms = String(query).trim().split(/\s+/).map(normalizeProductQuery).filter(Boolean);
    return products.filter(p => {
      const haystack = normalizeProductQuery([p.name, p.model, p.family, ...(p.aliases || []), p.name.replace(/HUAWEI/i, "华为")].filter(Boolean).join(" "));
      return (!category || p.category === category) && terms.every(term => haystack.includes(term));
    });
  }

  const tasks = [
    { id: "seeding", name: "产品种草", icon: "sparkles", prompt: "适合围绕真实使用场景介绍体验，避免未经核实的性能承诺。", deliverable: "场景体验分享", title: "把日常灵感，带到每一处", body: "最近在整理一份适合移动办公的电脑清单。选设备时，我会先想想自己最常在哪些地方工作：通勤路上、会议间隙，还是临时需要处理资料的时候。\n\n如果你也在了解华为 MateBook，可以到店看看实机，再结合自己的使用习惯和预算慢慢比较。具体型号、配置与价格以门店实际信息为准。\n\n你最常用电脑处理什么事情？欢迎聊聊。", structure: ["场景开篇", "体验观察", "到店了解"] },
    { id: "launch", name: "新品推广", icon: "badge-plus", prompt: "围绕新品信息建立传播重点，型号和上市信息请先核验。", deliverable: "新品信息介绍", title: "认识华为 MateBook 新品", body: "一款新电脑是否适合自己，可以从使用场景开始了解。\n\n这次我们整理了华为 MateBook 的产品介绍，方便你到店查看实机、咨询具体型号与配置。关于上市时间、功能参数和价格，请以官方信息及门店核实结果为准。\n\n欢迎预约到店了解（是否需要预约，请先与门店确认）。", structure: ["新品主题", "已知信息", "咨询引导"] },
    { id: "store", name: "到店引流", icon: "map-pin", prompt: "邀请顾客到店咨询或了解产品；门店体验与服务内容待确认。", deliverable: "到店咨询邀请", title: "想选一台适合自己的电脑？", body: "看参数之外，也可以先说说你的日常需求：主要用于学习、办公，还是内容创作？\n\n欢迎到附近的华为门店咨询 MateBook 系列产品。门店地址、营业时间、实机展示和服务安排请出发前向门店确认。\n\n把你的预算和常用软件告诉我们，一起梳理选购时需要关注的信息。", structure: ["需求提问", "到店邀请", "行动路径"] },
    { id: "season", name: "节日推广", icon: "calendar-days", prompt: "结合已确认的日期节点与产品需求，避免生硬节日套话。", deliverable: "节点主题内容", title: "为新的学习与工作阶段做准备", body: "进入新的学习或工作阶段前，不妨先整理一下自己的设备需求：常用软件有哪些？是否需要经常携带？预算范围又是多少？\n\n如果正在了解华为 MateBook，可以到店咨询具体型号与配置，再按自己的场景做选择。产品参数、价格及门店活动信息以核实结果为准。\n\n把准备工作做在前面，让选择更从容。", structure: ["节点关联", "需求梳理", "咨询引导"] }
  ];

  const opportunities = [
    // Finite sample schedules, never rolled forward with the clock. These are planning
    // examples, not live demand, official campaigns, or verified product capabilities.
    { id: "consultation-list", type: "门店场景", title: "从选购问题开始，整理到店前信息", description: "先把用途、软件和需要核实的事项列清楚，再判断是否需要进一步了解门店安排。", reason: "具体问题比泛泛介绍更容易找到可靠资料；地址、展示和服务条件仍需单独确认。", evidence: "建议依据：先收集用途与软件需求，再判断产品适配。未接入客流、市场需求或门店服务数据。", task: "store", direction: "围绕选购问题整理到店前准备：先收集用途与常用软件，再核对门店能提供的信息，不预设顾客需要到店。", scene: "顾客选购自查与到店前准备", unknown: "门店地址、营业时间、实机展示与可提供的服务。", displayStart: "2026-10-12", windowStart: "2026-10-19", validUntil: "2026-10-21", preparationDays: 7, verification: "ready", relevance: "high", storeFit: true, actionable: true, visual: "store" },
    { id: "software-questions", type: "产品探索", title: "从常用软件和任务出发，整理选购问题", description: "先把常用软件、版本和实际任务整理出来，再核对哪些产品信息值得进一步了解。", reason: "已有目录只能提供讨论对象；把问题具体化后，才知道还需要哪些型号资料。", evidence: "建议依据：软件任务可作为选购问题的起点。产品目录仅含示例名称，尚无兼容性或性能核验资料。", task: "seeding", direction: "围绕顾客常用软件与具体任务整理产品选购问题，先记录需求，再核验华为 PC 具体型号资料，不预先承诺兼容或性能。", scene: "软件任务梳理、产品资料核对与选购准备", unknown: "实际使用的软件版本、配置需求、具体型号及官方资料。", displayStart: "2026-10-12", windowStart: "2026-10-20", validUntil: "2026-11-20", preparationDays: 3, verification: "ready", relevance: "high", storeFit: true, actionable: true, visual: "product" },
    { id: "date-refresh", type: "时间节点", title: "从真实任务出发，找到适合介绍的华为 PC 方向", description: "从顾客接下来的学习或工作任务聊起，梳理用途与软件需求，再用可核实的华为 PC 资料组织选购内容。", reason: "先把实际任务问清楚，再介绍相关产品信息，避免只罗列参数，也不预设顾客需要换新。", evidence: "建议依据：先确认顾客的新阶段计划，再安排选购沟通。时间为样例内容排期，不代表节日、官方活动或市场热点。", task: "season", direction: "探索学习或工作任务如何转为华为 PC 的选购沟通内容；推广目标待用户选择，不预设换新、购买意愿或产品适配。", scene: "已有学习或工作计划的顾客、选购前需求自查", unknown: "顾客计划与时间、真实设备需求、具体产品资料。", displayStart: "2026-10-15", windowStart: "2026-11-05", validUntil: "2026-11-25", preparationDays: 7, verification: "ready", relevance: "high", storeFit: true, actionable: true, visual: "product" },
    { id: "local", type: "门店场景", title: "从周边场景，发现下一次沟通主题", description: "先核对门店周边环境，再探索适合询问顾客的学习或办公话题。", reason: "地标能提供沟通线索，但实际客群与需求仍要通过门店观察确认。", evidence: "尚未填写门店信息，不对当地客群作判断。", task: "seeding", direction: "先收集顾客设备用途，再探索适合门店的推广方向，不把周边地标等同于实际购买需求。", scene: "门店周边客群观察与内容选题", unknown: "门店位置、附近地标、真实客群与购买需求。", displayStart: "2026-10-12", windowStart: "2026-10-19", validUntil: "2026-11-15", preparationDays: 5, verification: "pending", relevance: "high", storeFit: true, actionable: true, visual: "store" }
  ];

  const opportunityPlaces = [
    { id: "place-school", type: "school", name: "学习场景示意点", direction: "北侧", theme: "从课程资料整理与常用软件出发，梳理值得了解的产品信息。", detail: "演示地点只用于构造提问方向，不代表真实学校、距离或客流。", facts: "可结合产品名称与已有资料组织问题；软件适配和配置仍需核实。" },
    { id: "place-business", type: "business", name: "办公场景示意点", direction: "东南侧", theme: "围绕移动办公、资料处理等任务，制作有依据的选购问题。", detail: "办公区为概念地点，不能推断真实办公人群或购买需求。", facts: "可讨论用途、软件和携带方式；具体型号特点待核验。" },
    { id: "place-shopping", type: "shopping", name: "商圈场景示意点", direction: "西侧", theme: "用一张简洁的需求清单，帮助路过顾客快速找到咨询切入点。", detail: "商圈为概念地点，不代表真实商场名称、位置或客流。", facts: "可使用示例目录中的产品名称；价格、库存、优惠和门店服务待确认。" }
  ];

  window.MarketingPrototypeData = { products, tasks, opportunities, opportunityPlaces, searchProducts };
})();
