"use strict";
// Run against the existing preview. Uses a real Chromium browser; no network AI calls.
// PLAYWRIGHT_MODULE may name an installed Playwright module outside this repository.
const { chromium } = require(process.env.PLAYWRIGHT_MODULE || "playwright");
const assert = require("node:assert/strict");
const fs = require("node:fs/promises");
const path = require("node:path");
const os = require("node:os");
(async () => {
  const outputDir = process.env.QA_OUTPUT_DIR || path.join(os.tmpdir(), "huawei-state-regression");
  await fs.mkdir(outputDir, { recursive: true });
  const browser = await chromium.launch({ headless: true, ...(process.env.CHROME_PATH ? { executablePath: process.env.CHROME_PATH } : {}) });
  const errors = [], checks = [];
  try {
    const context = await browser.newContext({ viewport: { width: 1440, height: 1000 }, reducedMotion: "reduce", permissions: ["clipboard-read", "clipboard-write"] });
    const page = await context.newPage();
    page.on("pageerror", e => errors.push(e.message));
    page.on("console", m => { if (m.type() === "error") errors.push(m.text()); });
    await page.clock.install({ time: new Date("2026-10-21T12:00:00+08:00") });
    const base = process.env.PROTOTYPE_URL || "http://127.0.0.1:7860/";
    const act = (action, id) => page.locator(`[data-action="${action}"]${id ? `[data-id="${id}"]` : ""}:visible`).first();
    const saved = () => page.evaluate(() => JSON.parse(localStorage.getItem("huawei-marketing-prototype-v1")));
    const reset = async text => {
      await page.goto(`${base}#home`); await page.evaluate(() => localStorage.clear()); await page.reload();
      if (text !== undefined) { await page.locator("#mc-prompt").fill(text); await page.locator("#mc-continue").click(); }
    };
    const say = async text => { await page.locator("#guide-input").fill(text); await page.locator("#guide-compose button").click(); };
    const finish = async () => { await act("guide-strategies").click(); await act("generate").click(); await page.waitForURL("**/#results"); };
    const body = () => page.locator("#output-body").inputValue();
    const waitForPreview = () => page.waitForFunction(() => {
      const img = document.querySelector(".mc-creative-preview img");
      return img?.complete && img.naturalWidth > 0;
    });
    const search = async query => { const picker = page.locator("#mc-home-product-picker"); if (await picker.getAttribute("open") === null) await picker.locator("summary").click(); await page.locator("#mc-home-product-search").fill(query); };
    await reset();
    await search("d16"); assert.equal(await page.locator(".mc-home-product-option:visible").count(), 1);
    await act("home-product-select", "matebook-d-16").click();
    await search("X Pro"); await act("home-product-select", "matebook-x-pro").click();
    assert.equal((await saved()).homeProduct, "matebook-x-pro");
    await act("home-product-remove").click(); await search("不存在的99999");
    assert.match(await page.locator("#mc-home-product-count").innerText(), /暂未找到匹配产品/);
    await page.locator("#mc-home-product-picker summary").click();
    checks.push("product keyword filtering / select / switch / remove / no-match");

    const acceptanceBriefs = [];
    for (const [goal, text] of [["consultation", "促进产品咨询"], ["awareness", "建立产品认知"], ["needs", "帮助顾客判断产品是否适合自己"]]) {
      await reset(`推广 MateBook 16，${text}`); await act("guide-strategies").click();
      assert.match(await page.locator(".mc-task-brief").innerText(), /发布平台\s*待确认/);
      assert.match(await page.locator(".mc-expected-output").innerText(), /通用推广文案/);
      assert.doesNotMatch(await page.locator(".mc-lead-strategy").innerText(), /首次行动|收集咨询线索|一对一提问/);
      await waitForPreview();
      assert.equal(await page.locator(".mc-creative-preview img").evaluate(img => img.complete && img.naturalWidth > 0), true);
      await page.screenshot({ path: path.join(outputDir, `task-${goal}.png`), fullPage: true, animations: "disabled" });
      await act("generate").click(); await page.waitForURL("**/#results");
      const d = (await saved()).draft;
      assert.equal(d.outputContext.strategy.goal, goal); assert.equal(d.outputContext.task.product, "matebook-16");
      assert.deepEqual(d.outputContext.task.platforms, []); assert.equal(d.activePlatform, "通用草稿");
      assert.ok((await body()).includes(d.outputContext.strategy.copy));
      acceptanceBriefs.push(d.outputContext.strategy);
    }
    for (const key of ["name", "coreIdea", "copy", "cta"]) assert.equal(new Set(acceptanceBriefs.map(s => s[key])).size, 3, key);
    assert.equal(new Set(acceptanceBriefs.map(s => s.expectedOutputs.join("|"))).size, 3);
    checks.push("acceptance A/B/C: MateBook 16 produces distinct primary themes, content, actions and deliverables with an unconfirmed platform");

    await reset("面向大学生推广 MateBook 16，促进产品咨询，用小红书");
    await act("guide-strategies").click();
    await page.locator("#strategy-adjustment").fill("不要面向大学生了，改为退休老人；不要小红书，改发视频号；主题改为日常用途与软件选购参考");
    await act("adjust-strategy").click();
    assert.match(await page.locator(".mc-lead-copy h2").innerText(), /日常用途与软件选购参考/);
    await page.reload();
    assert.doesNotMatch(await page.locator(".mc-lead-strategy").innerText(), /大学生|小红书/);
    await page.locator("#strategy-adjustment").fill("主题改为续航保证20小时");
    const beforeRiskyTheme = (await saved()).draft;
    await act("adjust-strategy").click(); assert.deepEqual((await saved()).draft, beforeRiskyTheme);
    assert.match(await page.locator("#mc-toast").innerText(), /核实/);
    await act("generate").click(); await page.waitForURL("**/#results");
    assert.match(await body(), /退休老人/); assert.doesNotMatch(await body(), /大学生|小红书/);
    assert.match(await body(), /日常用途与软件选购参考/);
    await page.locator("#output-body").fill("任务 E：我的手动正文，返回策略页不能覆盖。");
    await act("analysis").click();
    await page.locator("#strategy-adjustment").fill("清空主题");
    page.once("dialog", d => d.dismiss()); await act("adjust-strategy").click();
    await page.goBack(); await page.waitForURL("**/#results");
    assert.equal(await body(), "任务 E：我的手动正文，返回策略页不能覆盖。");
    checks.push("acceptance D/E: changed audience, video platform and explicit theme survive reload; unsupported claims rejected; manual output preserved on cancellation");

    await reset("面向大学生推广 MateBook 14，建立产品认知，用小红书");
    await act("guide-strategies").click();
    assert.equal(await page.locator(".mc-lead-strategy").count(), 1);
    assert.equal(await page.locator(".mc-alternative-list:visible").count(), 0);
    assert.equal(await page.locator("#output-body").count(), 0);
    assert.match(await page.locator(".mc-lead-status").innerText(), /规则模拟/);
    for (const width of [1440, 768, 390]) {
      await page.setViewportSize({ width, height: 1000 });
      assert.equal(await page.evaluate(() => document.documentElement.scrollWidth > innerWidth + 1), false, `strategy overflow ${width}`);
      await waitForPreview();
      assert.equal(await page.locator(".mc-creative-preview img").evaluate(img => img.complete && img.naturalWidth > 0), true);
      await page.screenshot({ path: path.join(outputDir, `strategy-${width}.png`), fullPage: true, animations: "disabled" });
    }
    await page.setViewportSize({ width: 1440, height: 1000 });
    await page.locator(".mc-creative-preview img").evaluate(img => { img.src = "data:image/png;base64,invalid"; });
    await page.locator(".mc-preview-fallback:not([hidden])").waitFor();
    assert.match(await page.locator(".mc-preview-fallback").innerText(), /备用概念构图/);
    assert.equal(await act("generate").isEnabled(), true);
    await page.reload();
    await waitForPreview();
    assert.equal(await page.locator(".mc-creative-preview img").evaluate(img => img.complete && img.naturalWidth > 0), true);
    checks.push("invalid image data displays a local fallback without blocking confirmation; reload restores reference");
    await page.locator(".mc-task-details > summary").click();
    assert.match(await page.locator(".mc-task-detail-grid").innerText(), /原型模拟/);
    await page.locator(".mc-task-details > summary").click();
    await page.locator(".mc-alternatives > summary").click();
    const alternativeId = await act("strategy").getAttribute("data-id");
    await act("strategy").click();
    assert.equal((await saved()).draft.strategyId, alternativeId);
    await page.locator("#strategy-adjustment").fill("更突出真实使用场景、减少参数介绍、表达得更自然");
    await act("adjust-strategy").click();
    assert.match(await page.locator(".mc-lead-strategy").innerText(), /减少参数罗列/);
    assert.equal((await saved()).page, "analysis");
    await act("generate").click(); await page.waitForURL("**/#results");
    const creativeBrief = (await saved()).draft.outputContext;
    assert.equal(creativeBrief.task.product, "matebook-14");
    assert.match(creativeBrief.strategy.adjustmentNote, /减少参数介绍/);
    assert.equal(creativeBrief.strategy.visualKind, "scene");
    assert.match(await body(), /最近用电脑|减少参数罗列/);
    assert.deepEqual((await saved()).draft.outputs["小红书"].strategy, creativeBrief.strategy);
    await page.locator("#output-body").fill("策略切换不得静默覆盖这段手工正文。");
    await act("analysis").click();
    await page.locator("#strategy-adjustment").fill("更自然");
    page.once("dialog", d => d.dismiss()); await act("adjust-strategy").click();
    // The strategy page intentionally has no "results" action. Use the native
    // Back path to verify the preserved task snapshot and edited body.
    await page.goBack(); await page.waitForURL("**/#results");
    assert.equal(await body(), "策略切换不得静默覆盖这段手工正文。");
    checks.push("single lead / folded alternatives and evidence / direct confirmation / one-sentence adjustment / full creative transfer / edit preservation / three strategy viewport sizes");

    await reset("给 MateBook 14 建立产品认知，面向附近大学生，用小红书发布");
    const firstReply = await page.locator(".mc-message-agent").first().innerText();
    await say("不要面向大学生了，改为退休老人；不推广 MateBook 14，改为 MateBook X Pro；不要小红书，改发朋友圈");
    assert.equal((await saved()).draft.product, "matebook-x-pro"); assert.equal((await saved()).draft.audience, "退休老人");
    assert.deepEqual((await saved()).draft.platforms, ["微信朋友圈"]);
    assert.equal(await page.locator(".mc-message-agent").first().innerText(), firstReply);
    await finish(); assert.match(await body(), /MateBook X Pro/); assert.match(await body(), /退休老人/); assert.doesNotMatch(await body(), /MateBook 14|大学生|小红书/);
    checks.push("replacement affects summary, strategy, generated copy; old messages frozen");

    const manual = "我手写的第一段，不允许模板覆盖。\n\n我手写的第二段。\n\n我手写的结尾。";
    await page.locator("#output-body").fill(manual);
    const expand = async selector => { const el = page.locator(selector); if (await el.getAttribute("open") === null) await el.locator(":scope > summary").click(); };
    await expand(".mc-result-advanced");
    await page.locator("#result-requirement").fill("把第二段改写成一首七言诗"); await act("update-output").click();
    assert.equal(await body(), manual); assert.match(await page.locator("#mc-toast").innerText(), /未支持/);
    await expand(".mc-result-advanced"); await page.locator("#result-requirement").fill("更短"); await act("update-output").click();
    assert.match(await body(), /我手写的第一段/); assert.match(await body(), /我手写的第二段/);
    await expand(".mc-result-advanced"); await act("restore-body").click(); assert.equal(await body(), manual);
    await act("copy").click(); assert.ok((await page.evaluate(() => navigator.clipboard.readText())).endsWith(manual));
    const downloadEvent = page.waitForEvent("download"); await act("export").click(); const download = await downloadEvent;
    const exportPath = path.join(outputDir, "edited-export.md"); await download.saveAs(exportPath);
    assert.match(await fs.readFile(exportPath, "utf8"), /我手写的第一段/);
    await expand(".mc-result-advanced");
    for (const action of ["regenerate", "change-angle"]) { page.once("dialog", d => d.dismiss()); await act(action).click(); assert.equal(await body(), manual); }
    await expand(".mc-result-fact-details");
    await page.locator('[data-fact-note="specs"]').fill("人工记录：本演示未核实配置，不发布性能结论");
    await act("confirm-fact", "specs").click(); assert.equal((await saved()).draft.facts.specs.confirmed, true);
    await page.screenshot({ path: path.join(outputDir, "edited-results.png"), fullPage: true, animations: "disabled" });
    await page.goBack(); await page.waitForURL("**/#analysis");
    await page.goBack(); await page.waitForURL("**/#guide");
    assert.equal(await page.locator(".mc-message-agent").first().innerText(), firstReply);
    await page.goForward(); await page.goForward(); await page.waitForURL("**/#results"); assert.equal(await body(), manual);
    await page.reload(); assert.equal(await body(), manual);
    checks.push("manual edit / supported local update / unsupported preservation / undo / exact copy / actual export / cancellation / fact confirmation / native Back and Forward / reload");

    await reset("面向附近大学生推广 MateBook 14，建立产品认知，用小红书");
    await finish();
    assert.equal(await page.locator(".mc-publication-preview").count(), 1);
    assert.equal(await page.locator(".mc-result-artwork img").count(), 1);
    assert.equal(await page.locator(".mc-result-support").count(), 0);
    assert.equal(await page.locator(".mc-result-fact-details").getAttribute("open"), null);
    assert.equal(await page.locator(".mc-result-poster img").evaluate(img => img.complete && img.naturalWidth > 0), true);
    await page.locator("#output-title").fill("手动发布标题");
    await page.locator(".mc-image-text-fields > summary").click();
    await page.locator("#output-visual-headline").fill("手动图片主标题");
    await page.locator("#output-visual-subline").fill("手动图片副标题");
    await page.locator("#output-body").fill("面向顾客的手动正文，预览应立即同步。");
    await page.locator("#output-cta").fill("了解经核实的产品资料");
    assert.equal(await page.locator("[data-publication-title]").innerText(), "手动发布标题");
    assert.equal(await page.locator("[data-publication-headline]").innerText(), "手动图片主标题");
    assert.equal(await page.locator("[data-publication-body]").innerText(), "面向顾客的手动正文，预览应立即同步。");
    assert.equal(await page.locator("[data-publication-cta]").innerText(), "了解经核实的产品资料");
    await expand(".mc-result-advanced");
    await page.locator("#result-platform-select").selectOption("视频号");
    assert.match(await page.locator("#output-body").inputValue(), /镜头与口播/);
    assert.equal((await saved()).draft.outputs["小红书"].title, "手动发布标题");
    await expand(".mc-result-advanced"); await page.locator("#result-platform-select").selectOption("小红书");
    assert.equal(await page.locator("#output-title").inputValue(), "手动发布标题");
    await act("toggle-materials").click(); await act("choose-image", "dialogue").click(); await page.waitForFunction(() => { const img = document.querySelector("[data-result-image]"); return img?.complete && img.naturalWidth > 0; });
    assert.match((await saved()).draft.outputs["小红书"].visualNote, /本地演示素材/);
    assert.match(await page.locator("[data-result-image]").getAttribute("src"), /result-dialogue\.svg/);
    await act("toggle-image-mode").click();
    assert.equal(await page.locator(".mc-result-thumbnails .mc-result-thumb").count(), 3);
    assert.equal(await page.locator(".mc-result-thumbnails img").evaluateAll(imgs => new Set(imgs.map(img => img.getAttribute("src"))).size), 3);
    await act("select-result-image", "image-2").click();
    assert.equal((await saved()).draft.outputs["小红书"].activeImageId, "image-2");
    await act("toggle-materials").click(); assert.equal(await page.locator(".mc-image-picker-dialog").evaluate(dialog => dialog.open), true);
    await act("choose-image", "dialogue").click();
    assert.equal((await saved()).draft.outputs["小红书"].images[1].visualKind, "dialogue");
    await act("move-image-up").click(); assert.equal((await saved()).draft.outputs["小红书"].images[0].id, "image-2");
    await act("remove-result-image").click(); assert.equal((await saved()).draft.outputs["小红书"].images.length, 2);
    const textBeforeImageGeneration = await body();
    await act("open-regenerate").click();
    await page.locator('.mc-regenerate-dialog input[name="regenerate-scope"][value="image"]').check();
    await page.locator("#regenerate-direction").selectOption("scene"); await act("confirm-regenerate").click();
    assert.equal(await body(), textBeforeImageGeneration); assert.equal((await saved()).draft.outputs["小红书"].images.length, 2);
    const imageBeforeCopyGeneration = (await saved()).draft.outputs["小红书"].visualSrc;
    await act("open-regenerate").click();
    await page.locator('.mc-regenerate-dialog input[name="regenerate-scope"][value="copy"]').check();
    await page.locator("#regenerate-direction").selectOption("concise"); await act("confirm-regenerate").click();
    assert.notEqual(await body(), textBeforeImageGeneration); assert.equal((await saved()).draft.outputs["小红书"].visualSrc, imageBeforeCopyGeneration);
    await act("undo-regenerate").click(); assert.equal(await body(), textBeforeImageGeneration);
    assert.equal(await page.locator(".mc-publication-preview").count(), 1);
    await act("toggle-image-mode").click(); assert.equal(await page.locator(".mc-result-thumbnails .mc-result-thumb").count(), 0);
    const copyBefore = (await saved()).draft.outputs["小红书"];
    await act("open-regenerate").click(); await act("close-regenerate").click(); assert.equal(await body(), copyBefore.body);
    await act("open-regenerate").click();
    await page.locator('.mc-regenerate-dialog input[name="regenerate-scope"][value="copy"]').check();
    await page.locator("#regenerate-direction").selectOption("warm"); await act("confirm-regenerate").click();
    assert.notEqual(await body(), copyBefore.body);
    assert.equal(await page.locator("#output-visual-headline").inputValue(), copyBefore.visualHeadline);
    assert.equal(await page.locator("[data-result-image]").getAttribute("src"), copyBefore.visualSrc);
    await act("undo-regenerate").click(); assert.equal(await body(), copyBefore.body);
    await page.reload();
    assert.equal(await page.locator("#output-title").inputValue(), "手动发布标题");
    assert.equal(await page.locator("#output-visual-headline").inputValue(), "手动图片主标题");
    assert.match(await page.locator("[data-result-image]").getAttribute("src"), /result-dialogue\.svg/);
    const posterDownloadEvent = page.waitForEvent("download"); await act("download-poster").click();
    const posterDownload = await posterDownloadEvent, posterPath = path.join(outputDir, "edited-poster.svg");
    await posterDownload.saveAs(posterPath);
    const posterSvg = await fs.readFile(posterPath, "utf8");
    assert.match(posterSvg, /^<svg xmlns="http:\/\/www\.w3\.org\/2000\/svg" width="1000"/);
    assert.match(posterSvg, /data:image\/svg\+xml;base64,/);
    assert.match(posterSvg, /手动图片主标题/); assert.match(posterSvg, /手动图片副标题/);
    assert.match(posterSvg, /概念示意/); assert.match(posterSvg, /非指定型号实拍/);
    const posterXmlError = await page.evaluate(svg => new DOMParser().parseFromString(svg, "image/svg+xml").querySelector("parsererror")?.textContent || "", posterSvg);
    assert.equal(posterXmlError, "");
    await page.locator("#output-body").fill("重新生成确认后仍可撤销的手写内容。");
    page.once("dialog", dialog => dialog.accept()); await act("regenerate").click();
    assert.notEqual(await body(), "重新生成确认后仍可撤销的手写内容。");
    await act("undo-regenerate").click(); assert.equal(await body(), "重新生成确认后仍可撤销的手写内容。");
    for (const width of [390, 768, 1440]) {
      await page.setViewportSize({ width, height: 1000 });
      assert.equal(await page.evaluate(() => document.documentElement.scrollWidth > innerWidth + 1), false, `workbench overflow ${width}`);
      await page.screenshot({ path: path.join(outputDir, `results-${width}.png`), fullPage: true, animations: "disabled" });
    }
    await page.setViewportSize({ width: 1440, height: 1000 });
    checks.push("results workbench: one publication canvas; multi-image selection, replacement, order and deletion; range-based regeneration dialog and undo; image/copy independence; platform drafts and manual edits survive reload; SVG export; responsive widths");

    await reset("推广 MateBook X Pro，建立产品认知，面向经常出差的顾客，用小红书");
    await say("改为面向大学生的学习用途，不要差旅内容");
    assert.equal((await saved()).draft.audience, "附近大学生"); await act("guide-strategies").click();
    for (let n = 0; n < 3; n++) { assert.doesNotMatch(await page.locator(".mc-lead-strategy").innerText(), /差旅|出差/); await page.locator(".mc-alternatives > summary").click(); await act("shuffle").click(); }
    await act("generate").click(); await page.waitForURL("**/#results"); assert.doesNotMatch(await body(), /差旅|出差/);
    checks.push("negated scene stays excluded from shuffled strategies and copy");

    await reset("面向大学生介绍 MateBook 14，建立产品认知，用小红书");
    await say("清空受众；清空平台；不要指定任何产品，先不选型号");
    await page.reload(); assert.deepEqual((await saved()).draft.platforms, []);
    await finish(); assert.equal((await saved()).draft.activePlatform, "通用草稿"); assert.doesNotMatch(await body(), /大学生|MateBook 14|小红书/);
    checks.push("intentional field clears survive refresh; no product/channel required; generic draft is explicit");

    await reset(); await search("MateBook 14"); await act("home-product-select", "matebook-14").click();
    await page.locator("#mc-prompt").fill("推广 MateBook X Pro，建立产品认知"); await page.locator("#mc-continue").click();
    assert.match(await page.locator(".mc-guide-actions").innerText(), /不一致/);
    assert.equal(await act("guide-strategies").count(), 0); await act("guide-product", "matebook-x-pro").click(); await finish();
    assert.doesNotMatch(await body(), /MateBook 14/); checks.push("homepage/text product conflict visibly confirmed before strategies");

    const claims = [];
    for (const goal of ["awareness", "needs", "consultation", "store"]) {
      await reset();
      if (!await act("opportunity", "date-refresh").count()) {
        await page.locator(".mc-opportunity-details summary").click();
        await act("preview-opportunity", "date-refresh").click();
      }
      await act("opportunity", "date-refresh").click();
      assert.match(await page.locator(".mc-opportunity-source").innerText(), /推荐理由/);
      const initialReply = await page.locator(".mc-message-agent").first().innerText();
      if (goal === "awareness") {
        await act("guide-edit").click(); await page.locator('[name="goal"]').selectOption(goal);
        await page.locator("#guide-summary-form button[type=submit]").click();
      } else await act("guide-goal", goal).click();
      assert.equal(await page.locator(".mc-message-agent").first().innerText(), initialReply);
      await say("用小红书发布");
      await page.locator('[data-action="guide-focus"]').first().click();
      await act("guide-strategies").click(); await page.locator(".mc-alternatives > summary").click(); await act("shuffle").click();
      claims.push(await page.locator(".mc-lead-strategy").innerText());
      await act("generate").click(); await page.waitForURL("**/#results");
      assert.match(await body(), /具体|任务|问题|用途/);
      assert.equal((await saved()).draft.opportunity.id, "date-refresh");
    }
    assert.equal(new Set(claims).size, 4);
    checks.push("opportunity context and first response preserved; four goals give distinct shuffled strategies and working results");

    await act("home").click(); await page.locator("#mc-prompt").fill("推广 MateBook 14，建立产品认知"); await page.locator("#mc-continue").click();
    assert.equal((await saved()).draft.opportunity, null); await say("改成那个更适合的");
    assert.match(await page.locator(".mc-guide-actions").innerText(), /请确认本次修改/);
    await act("guide-confirm-current").click(); await act("guide-strategies").click();
    checks.push("free-entry isolation and ambiguous input confirmation");

    await act("home").click();
    const previousOpportunity = await act("opportunity").getAttribute("data-id");
    await act("next-opportunity").click();
    await page.waitForFunction(previous => document.querySelector('#mc-opportunity-cards [data-action=opportunity]')?.dataset.id !== previous && !document.querySelector('#mc-opportunity-cards[aria-busy=true]'), previousOpportunity);
    const id = await act("opportunity").getAttribute("data-id");
    await page.locator(".mc-opportunity-details summary").click(); assert.ok(await page.locator('[data-action="preview-opportunity"]:visible').count());
    await act("opportunity").click(); assert.equal((await saved()).draft.opportunity.id, id);
    const source = await page.locator(".mc-opportunity-source").innerText(); assert.match(source, /推荐理由/);
    await page.locator('[data-page="history"]').click(); await act("open-record").click(); assert.equal((await saved()).page, "results");
    for (const width of [390, 768, 1440]) {
      await page.setViewportSize({ width, height: 1000 });
      assert.equal(await page.evaluate(() => document.documentElement.scrollWidth > innerWidth + 1), false, `results overflow ${width}`);
      await act("analysis").click(); await act("guide").click();
      assert.equal(await page.evaluate(() => document.documentElement.scrollWidth > innerWidth + 1), false, `guide overflow ${width}`);
      await act("home").click();
      assert.equal(await page.evaluate(() => document.documentElement.scrollWidth > innerWidth + 1), false, `home overflow ${width}`);
      await page.screenshot({ path: path.join(outputDir, `home-${width}.png`), fullPage: true, animations: "disabled" });
      await page.locator('[data-page="history"]').click(); await act("open-record").click();
    }
    checks.push("recommendation rotation / evidence / context switching / history / mobile and desktop layout");
    assert.deepEqual(errors, []);
    const report = { passed: true, checks, consoleErrors: errors, outputDir };
    await fs.writeFile(path.join(outputDir, "report.json"), JSON.stringify(report, null, 2));
    console.log(JSON.stringify(report, null, 2));
  } finally { await browser.close(); }
})().catch(error => { console.error(error); process.exitCode = 1; });
