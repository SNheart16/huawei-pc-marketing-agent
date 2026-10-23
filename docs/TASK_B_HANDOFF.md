# 任务书 B 交付与接口交接

> 当前图片交付模式：以 [预生成素材说明](../ui/assets/pregenerated/README.md) 和 [演示手册](demo-runbook.md) 为准。默认 `image_mode=pregenerated`，服务端拒绝 `ai_reference`，无需生图凭证，不调用生图 API；真实文案模型调用保留。公众号、朋友圈、小红书分别选图、排序并导出原图，完整排版图片不重复叠字。素材视觉核查仍 `unknown`，授权仍待确认。下文 `layout`/`ai_reference`、旧生图按钮及历史真实图片验收均为 B 原始交付记录，不能当作当前演示模式或本轮实测结果。

> 复赛集成补充：下文保留 B 在 `462530a` 的历史交付基线；不代表本轮真实链路通过。当前集成以 [demo-runbook.md](demo-runbook.md) 为准，统一从 `/demo.html` 操作。新增 `POST /api/content/from-handoff` 由服务端读取 A 当前已确认策略并适配 B，`/api/content/validate` 对绑定成果调用 A 现有最终核查。A 的正式请求响应见 [agent-api-v2.md](agent-api-v2.md)，下文“check-final 尚未提供”及旧 B→A 远程格式不是当前 A 契约。历史任务/成果 ID 不可在新服务复用；历史截图保留在原 B 提交，不加入本轮 Git，也不作为本轮验收证据。

基线为 `main` 的 `4a57c27f97402000ce9b9a9a8707687d7fe233e5`，2026-10-22 14:54:55 +0800。交付分支 `feat/task-b-content-delivery`。本次新增 B 模块，不实现 A 的需求理解、知识检索、策略生成或事实核查。团队可从此分支审阅、合并 B 的更新；本机配置与运行数据不随代码交付。

## 运行

在仓库根目录运行 `powershell -File .\start-content-b.ps1`，或 `python -X utf8 app.py --port 7861`。

启动脚本会读取本仓库被 Git 忽略的 `.env.content.local`；也可用 `-Config` 指定其他配置路径。直接运行 `app.py` 只读取进程环境。2026-10-23 已用用户提供的服务配置验证 `gpt-4.1` 文案和 `gpt-image-2` 参考图生图，真实成果可通过 `?content_asset=asset-1529c1f57abb468fba1ec14cf95e9cc3` 打开，无需再次生成扣费。

- 主应用：`http://127.0.0.1:7861/`
- B 独立演示：`http://127.0.0.1:7861/?content_demo=study`
- 旧真实模型页面：`http://127.0.0.1:7861/backend.html`
- 端到端脚本：`python -X utf8 scripts/demo_content_b.py --port 7861 --example study`
- 真实服务验收：以上脚本添加 `--live`，调用文案模型并生成一张图片，会消耗已配置服务额度；默认不调用。
- 自动化测试：`python -X utf8 -m unittest discover -s tests -p "test_*.py"`；`node --test tests/test_prototype.cjs tests/test_ui.cjs tests/test_content_bridge.cjs`

只监听本机，无用户登录与多门店权限系统，不能直接作为公网生产服务。标准库即可运行。浏览器负责 SVG 转 PNG，不需要额外图像依赖。

## 成员边界

| 部分 | 负责成员 | 本次处理 |
|---|---|---|
| AI 引导、产品知识检索、机会与策略 | A / 对应成员 | 未改动 guidance.js、prototype-data.js、agent.py、知识库实现 |
| 策略交给成果模块 | A 与 B | 完整 JSON 契约；原型只有概念资料时不提升为已核实事实 |
| 文案、图片、编辑、局部重生成、版本、保存和导出 | B | 新增 content_b，复用现有工作台布局 |
| 最终事实核查 | A | B 通过配置地址调用；未配置或失败则 pending，不编造通过结果 |
| 门店素材授权与产品终审 | 业务 / 素材管理员 | 目录保留来源、授权和视觉核查状态；来源不等于授权 |

共享文件变更仅为 app.py 的 B 路由分派、index.html 加载 B 脚本与样例入口、prototype.js 的成果适配点、.gitignore。其他逻辑集中在新文件，便于成员独立合并。

## 已实现与真实边界

**实际运行的能力**：HTTP 生成任务与真实阶段事件、完整策略输入校验、已核实且同型号事实的筛选、独立文案字段、原始官方来源照片的确定性排版、多图分工、PNG/SVG/ZIP 导出、单图替换和排序、局部重生成、SQLite 持久化、乐观版本锁、有限并发、幂等请求、版本恢复、失败保留原稿、删除隔离、最终核查请求及结果绑定。

**离线策略整理模式**：`copy_mode=assembly` 仅将传入的主题、核心表达、提纲和有效事实组织成稿，按平台控制长度；不宣称调用大模型。调整支持段落重排与“简洁”类压缩，不支持任意自然语言改写。

**文案模型适配**：`copy_mode=llm` 复用已有 `src.llm_client.LLMClient`，完整传递策略、事实、平台限制、语气、避用表达、风险与调整方向。JSON 格式最多一次修复；质量最多再生成一次。请求超时或失败不降级冒充 AI 成功。环境未配置时返回 `MODEL_UNAVAILABLE`。原型入口检测到 LLM 配置后使用模型模式；三个演示按钮保持显式离线模式。直接导入 A 的请求可指定模式。

**图片能力**：`image_mode=layout` 实际生成可访问的 SVG 排版文件，照片本体不由 AI 重绘；第二、三张承担清单与选购参考，未指定型号时只生成主题信息卡。`image_mode=ai_reference` 通过配置的 `/images/edits` 上传登记的同型号原图与提示词，生成并落盘真实 PNG；生成图明确标记为待核验，不能声称产品像素未变。已有三张电影感海报仍归入历史创意参考档案，与实时成果分开标识。

AI 图片保留 `generation_model/generation_prompt/generation_endpoint/source_sha256/image_sha256`。`text_content` 是要求模型绘制的文字，`text_content_status=intended_not_ocr_verified` 表明尚未 OCR 核验，A 必须检查实际图片。生图请求默认超时 300 秒，可配置 5–600 秒；不自动重试。一个图片请求失败即停止当前任务后续付费图片调用，首次任务保留已有文案，重生成保留旧版本。服务仅接受 base64 PNG；临时图片 URL 不会直接充当成果。

**未联通部分**：A 的 `/api/facts/check-final` 不在当前主分支实现中，需对方接入。图片完整视觉核验、授权确认、多用户权限、远端存储和自动发布不在本次已完成能力中。文案与生图服务已经真实验证，不等于 A 的最终审核通过。

## A → B 生成请求

调用 `POST /api/content/generate`，完整例子见 `content_b/examples.json`。请求结构：

```json
{
  "task_id": "task-001",
  "confirmed": true,
  "platform": "小红书",
  "copy_mode": "assembly",
  "image_mode": "layout",
  "image_count": 2,
  "art_direction": "editorial",
  "idempotency_key": "one-key-per-request",
  "strategy": {
    "strategy_id": "strategy-001",
    "topic": "开学前，先列一张任务清单",
    "audience": "正在准备新学期的同学",
    "audience_need": "常用软件和学习任务如何确认",
    "core_message": "先整理实际用途，再选择电脑。",
    "content_outline": ["列出常用软件和版本。", "逐一核对具体型号资料。"],
    "content_angle": "任务清单",
    "content_format": "场景参考图文",
    "cta": "",
    "tone": "自然真诚",
    "constraints": "不写无依据的价格和适配承诺",
    "avoid": ["最强", "闭眼入"],
    "assumptions": ["受众需求来自任务设定"],
    "pending_confirmations": [],
    "risk_notes": []
  },
  "product_context": {"model": "HUAWEI MateBook Pro S", "facts": []}
}
```

事实条目格式：`fact_id, claim, source_ref, status, product_model, valid_until`。仅 `supported/verified`、有来源、与请求完整型号严格一致、未过期的事实进入文案素材；其余记录在 `excluded_facts`。`valid_until` 若提供须为带时区 ISO 时间。B 不判断一个来源是否在业务上可靠；这仍由 A 完成。缺事实允许做不含具体规格的使用问题内容。

平台支持小红书、公众号 / 微信公众号、微信朋友圈 / 门店朋友圈、门店海报、通用草稿。字数限制为本项目编辑规则，不宣称是平台官方限制。`image_count` 为 1–3，按内容需求指定；视觉方向 `editorial/warm/minimal`。

文案方式可选 `assembly/llm`，图片方式可选 `layout/ai_reference`。直接 API 请求省略方式时均为无模型模式；原型文案入口在配置存在时使用 llm，进入生成前须在 B 的弹窗明确选择海报方式，配置可用时预选 AI 方式。成果页另有“生成 AI 海报”直接入口，保留已编辑文案。三个演示策略按钮保持离线模式。没有同型号原图时须上传或明确选择无产品外观的信息卡，不会静默把信息卡当作产品海报。

`POST /api/content/references` 接收 `model/image_base64/source_ref(可选)`，只支持最大 8MB 的 PNG/JPEG。返回 `catalog_id`，可作为生成或重生成请求的 `reference_id`。原图、登记元数据保存到数据目录的 `references/`，不更改静态素材目录和 A 的产品知识。登记不等于型号/版权已验证；授权仍为 unconfirmed。`GET /api/content/references/ref-{uuid}.png|jpg` 可获取实际原图。参考图按完整型号严格隔离，缺失或不匹配时在文案模型调用前拒绝。

成果页“重新生成”也可分别切换文案与图片方式，并标明服务额度使用。方式切换只影响选定范围，单改图片不会调用文案模型或改写文案。连接错误与等待超时分别返回 IMAGE_CONNECTION / IMAGE_TIMEOUT，错误在成果页持续可见，不只出现短暂 toast。

首次响应 HTTP 202：

```json
{"success":true,"data":{"job_id":"job-…","status":"pending","asset_id":null,"events":[]},"error":null}
```

随后 `GET /api/content/jobs/{job_id}`，实际阶段依次为 `pending → generating_copy → generating_images → checking → completed/failed`，未执行的重生成阶段跳过。完成后用返回的 `asset_id` 获取成果。`completed` 表示生成流程结束，是否可发布只认 `can_publish`，不能把 completed 当作核查通过；图片部分失败时成果自身 `status=partial`。

成果含 `asset_id/task_id/strategy_id/copy/images/platform/version/parent_version/request/status/fact_check_status/fact_check/content_hash/can_publish/publish_blockers/generation_mode/errors/saved/created_at/updated_at`。图片含真实 URL、角色、来源类型与引用、素材 ID、授权状态、视觉状态、渲染方法、图内文本、尺寸、原图 SHA-256 和关联任务。

## B → A 最终核查

配置 `FACT_CHECK_FINAL_URL`，例如 `http://127.0.0.1:8000/api/facts/check-final`；远程地址须 HTTPS。可设置 `FACT_CHECK_API_KEY`。B 不新增一个假 A 接口。

请求包含：`schema_version=content-b/1.0`、asset/task/strategy ID、最终 `copy`、完整 `images`（含 `text_content`）、完整 `strategy`、`fact_references`、`sources`、`content_hash`。可从 `GET /api/content/{asset_id}/check-payload` 获取精确示例，UI 也可导出给 A。

当前媒体 URL 是本机 B 服务的相对地址。A 同机联调时需以 B 的本地地址解析并获取文件；远程 A 无法直接访问用户的 localhost，需双方另行约定图片上传/共享存储，再适配媒体传递。导出包已包含实际文件，可先用于离线联调。不得因收到提示词或预期图中文字就回传图片已核验。

A 成功响应：

```json
{
  "success": true,
  "data": {
    "status": "passed",
    "content_hash": "必须原样回传本次请求的哈希",
    "coverage": "complete",
    "claims": [{
      "claim": "被核查的陈述",
      "status": "supported",
      "source_refs": ["来源标识"],
      "reason": "支持该陈述的理由",
      "suggested_action": "保留"
    }],
    "verified_image_ids": [],
    "reason": "最终文案核查结果"
  },
  "error": null
}
```

顶层状态只接受 `passed/blocked/pending`；逐项状态按 A 任务书的 `supported/unsupported/conflicting/needs_confirmation/not_applicable`。有未支持、冲突或待确认项，即使顶层 passed，B 也阻断。已支持事实必须有 source_refs。`coverage` 未声明 complete 不算完整核查。哈希不一致拒收，防止旧稿结论用于新稿。`verified_image_ids` 仅列 A 确实核验过的当前图片，包括图内文字；无法识别就留空，不能宣称全部视觉已核实。

即使文案 passed，缺图片核验或素材授权仍 `can_publish=false`。调用失败、响应非法、超时只保留待核查成果。手动修改、换图、排序、恢复、重生成都会失效旧核查。

## 编辑与交付路由

| 请求 | 用途 |
|---|---|
| `POST /api/content/regenerate` | `asset_id, expected_version, scope(all/copy/images/image), image_id(单图时), adjustment, art_direction, copy_mode, image_mode, idempotency_key` |
| `PATCH /api/content/{asset_id}` | `expected_version` 加 `copy` 局部字段 / `image_order` 完整 ID 列表 / `replacement:{image_id,catalog_id}` / `remove_image_id` |
| `POST /api/content/validate` | `asset_id, expected_version`，提交 A 核查 |
| `POST /api/content/save` | `asset_id, expected_version`，正式保存为可回看的审核草稿；`publish:true` 仅检查发布门槛，不自动发帖 |
| `GET /api/content` | 读取服务端已保存成果；可按 `task_id` 过滤 |
| `GET /api/content/{asset_id}` | 读取预览或已保存成果 |
| `GET /api/content/{asset_id}/versions` | 历史版本元数据 |
| `POST /api/content/restore` | `asset_id, expected_version, version`，恢复为新版本 |
| `GET /api/content/{asset_id}/export` | ZIP：文案、实际 SVG/PNG、元数据、A 核查请求 |
| `DELETE /api/content/{asset_id}` | `expected_version`，只删该成果记录与版本，不删共享素材 |
| `GET /api/content/catalog` | 可选同型号素材目录；`model` 精确筛选 |
| `GET /api/content/capabilities` | 配置存在性；不代表真实服务已验证 |

统一失败：`{"success":false,"data":null,"error":{"code":"VERSION_CONFLICT","message":"…"}}`。400 输入非法，404 不存在，409 正在操作 / 版本冲突 / 幂等键冲突，422 内容或发布门槛未满足，429 队列满，502/503 上游格式或服务错误。生成失败保留原成果；首次部分图片失败保留成功文案与图片。重生成图片部分失败则不提交新版本。

## 配置与存储

配置示例 `content_b/.env.example`。启动脚本只加载指定文件的允许字段，不执行 shell 表达式，已有进程环境变量优先。直接运行 app.py 仍只读取进程环境。不要提交 `.env.content.local` 或真实密钥；此文件已确认被 Git 忽略，网页也无法访问仓库根配置。

`CONTENT_DATA_DIR` 默认仓库 `.content-data`，SQLite 保存成果、每次修改快照和任务事件，`media/` 保存自包含 SVG 或 PNG，`prompts/` 保存每次生图提示词。已经生成的图片没有远端临时 URL 过期问题；源文件被删除时明确失败。重启会将未完成任务标记失败，原稿可恢复。

素材目录 `content_b/catalog.json` 由素材管理员维护。只能按完整型号匹配本地登记素材，UI 不接受任意远程 URL，以免无效地址、临时地址或错误型号冒充成果。业务方拿到授权凭据后才可将对应 `rights_status` 改为 approved；当前示例均 unconfirmed。用户提供的其他品牌海报仅用于分析构图，没有作为可发布素材复制进目录。

## 合并与联调顺序

1. A 按本文发一份完整策略请求。若现有字段不同，只改 `content-workbench.js` 的入口适配函数，不重写 A。
2. A 实现 check-final 的哈希回传、逐项核查、覆盖范围和可核验图片列表。任何字段变更先同步本契约。
3. 配好模型与 A 地址，先用单个任务测试生成、改字、换图、重查；确认错误不是模拟成功。
4. 再跑多任务与并发修改测试，最后确认授权与交付包。

## 已知限制

- 已完成真实文案与生图联调；A 最终核查尚未联通。规则整理、真实排版、实时 AI 生成与待核查状态均明确区分。
- 自由文案的事实正确性由 A 负责；B 的本地风险词和数值规则不是完整事实核查或法律合规审核。
- 浏览器创作记录保留本地快照，服务端已保存成果是独立持久层，可通过成果页读取。删除服务端记录不会擦除当前浏览器草稿；继续操作会提示记录不存在。
- 多平台生成逐平台提交，前一平台成功会保留；不把跨平台生成声称为数据库原子事务。
- 版本与媒体目前无自动清理策略，防止删除共享素材；长期部署需容量管理。不能多进程同时运行同一 CONTENT_DATA_DIR。
- 跨设备用户鉴权、云存储、门店权限和真正发布操作属于后续部署工作，不在这次 B 任务中冒充完成。
