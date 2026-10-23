# Agent API v2

本文档定义 A 侧最小工作流的结构化交接协议。v2 使用统一响应包：接口处理成功时为 `{"success": true, "data": {...}, "error": null}`；参数、版本或服务失败时 `success=false`，`error` 包含安全的 `code` 和 `message`，必要时可在 `error.details` 附带当前任务快照。该协议不改变旧的 `POST /api/run` 与 JSON v1.0。

配置、启动、前端接入位置、离线测试及真实验收范围见 [A 模块交付说明](agent-core-a-handoff.md)。程序不会自动加载 `.env`；本地知识库和 ima 官方脚本需另行准备。新版首页目前仍是前端模拟原型，`/backend.html` 仍用旧接口；本协议不表示 UI 已接入，也不包含真实生图或图片视觉识别。

## 接入顺序与版本使用

```text
understand → continue（按需）→ research → facts/check →
strategy/generate → strategy/confirm → strategy/handoff →
图文模块生成 → facts/check-final
```

以上八个 v2 接口均为 POST，HTTP 地址与根目录 `app.py` 相同。`understand` 创建服务器任务；后续请求必须使用本进程实际返回的 `task_id` 和最新 `task.revision` 作为 `expected_revision`。`strategy/generate` 返回的策略 ID/版本用于 confirm；确认成功后还须将更新后的任务 revision 用于 handoff 和 check-final。示例中的合成 ID 与固定版本仅为结构演示，不可跨示例或跨服务直接复用。`data.handoff.task` 也是当前任务快照；接口失败时按实际 `data.task` 或 `error.details.task`（如有）恢复，不能自行将 revision 加一猜测。

新版 UI 接入须保留字段明确清空和手动编辑保护；用户修改需求、策略或成稿后，撤下受影响的旧核查/确认状态。HTTP 错误不能回退模拟成果。root Handler 请求体上限为 64 KiB（UTF-8 字节），包括完整 JSON；成稿契约的字段限制不扩大该 HTTP 上限。

## 实现边界

当前实现包含真实 LLM 需求理解、结构校验、进程内任务隔离、显式字段更新/清空、乐观版本控制、产品检索、生成前事实核查、真实策略生成、策略全文事实审查、明确策略确认、确认后的图文模块交接，以及独立的最终成稿文字核查。图文生成模块和图片视觉核验尚未接入；最终核查不会生成或改写成稿。

任务快照区分：

- `user_input`：创建任务时的原始输入，不被后续回答覆盖；
- `conversation`：按时间追加的用户/助手轮次；
- 顶层产品、受众、平台、目标、场景、限制条件：当前有效状态；
- `field_status`：每个字段为 `unset`、`confirmed` 或 `cleared`。清空必须通过 `clear_fields` 明确表达，不能从历史对话恢复。

## 路由

`field_status=confirmed` 仅表示需求字段有用户确认或被当前用户明确提供，不表示产品信息已从知识库核验。

### `POST /api/agent/understand`

先创建并保存任务及原始用户输入，再调用真实 LLM 理解。模型摘要、字段建议、缺失字段和最多一个追问位于既有 envelope 字段中。缺少核心需求时状态为 `collecting_requirements`；产品、受众、平台、目标与场景已有值时可进入 `ready_for_strategy`。这个状态仅表示需求足以进入策略阶段，不表示检索或事实核验已完成。LLM 失败时返回安全错误和已保存任务快照，可按最新 `task.revision` 重试。

请求示例见 [understand-request.json](examples/understand-request.json)，响应结构示例见 [understand-response.json](examples/understand-response.json)。`task.revision` 由服务端管理。字段缺失不等于 HTTP 处理失败：只要模型调用与请求处理成功，`success=true`，但任务维持 `collecting_requirements` 并返回最多一个 `understanding.questions` 条目。请求和原始任务在模型调用失败前已保存。

### `POST /api/agent/continue`

读取既有任务并先按版本保存本轮回答，然后在不持有任务仓库锁的情况下调用真实 LLM 理解。模型返回后会再次校验 revision；若期间任务已变化，丢弃模型结果并返回 HTTP 409 `VERSION_CONFLICT`。`expected_revision` 必填；`updates` 和 `clear_fields` 表达明确的结构化修改，后者优先于模型建议和历史记录，两者不能包含同一字段。请求样例见 [continue-request.json](examples/continue-request.json)。

`data.interpretation.implementation_status` 标为 `IMPLEMENTED`，并返回摘要和最多一个问题。LLM 建议的字段值必须能在本轮回答、显式表单更新或机会上下文中找到原文依据；用户明确清空的字段不会从历史恢复。更新任何策略输入都会使旧策略失效；更改产品还会清除该任务的旧事实记录。对于 `source=opportunity`，服务保留 `opportunity_context` 与 source 标签。

机会上下文只允许填充 `unset` 字段，不能覆盖用户已确认或已清空的字段。模型的问题仅作建议，服务端按当前缺失字段选取一个核心问题，避免重复询问已知内容。模型调用成功也不会将任何产品事实标记为已核验。一次成功的理解会增加 revision；continue 保存本轮输入和理解结果会各增加一次，调用方必须使用返回的 revision，不能硬编码版本号。

### `POST /api/agent/research`

产品检索是独立的显式操作；`understand` 和 `continue` 不会隐式启动检索。仅当当前任务的产品已确认且必要需求完整时才能检索。请求只接受 `task_id` 与 `expected_revision`：

```json
{"task_id":"task-...","expected_revision":2}
```

服务端先将任务转为 `researching` 并递增 revision，再在不持有任务仓库锁的情况下调用 `ProductResearchService`。服务复用 `KnowledgeService` 的 `ima`、`local` 或 `auto` 选择规则，且一次检索只使用一个主要来源。完成写入前会重新核对任务 revision 与产品型号；若期间任务已被修改或产品被清空/更换，返回 HTTP 409 `VERSION_CONFLICT`，丢弃该次检索结果，不污染新任务状态。事实和策略输入被产品变更时，旧事实及依赖策略会失效。

成功响应将研究结果放在 `data.research`，任务快照放在 `data.task`。`success=true` 仅表示 API 按契约完成处理，不代表事实通过核查或策略已生成。`research.status` 的含义如下：

- `success`：检索取得可关联来源的事实记录；记录仍为 `retrieved`，并非已核实。
- `partial`：取得部分资料，但存在缺项、过期信息或有效性未知等限制；已提取记录仍需核查。
- `needs_input`：未指定产品或现有信息不足以定位精确型号；不会保存事实。
- `conflict`：型号有歧义或同型号来源存在明确冲突；不会把冲突事实写入任务。
- `error`：限额、超时、来源读取或返回格式错误；不会伪造事实。任务保留在可基于最新 revision 重试的失败状态。

HTTP 成功路径允许 `research.status` 为 `success` 或 `partial`，并只保存校验通过的 FactRecord。型号/来源冲突、缺少可提取事实及来源故障使用 `success=false` 与安全错误码，同时返回最新任务快照、研究诊断和恢复建议。错误包括 `PRODUCT_REQUIRED`、`REQUIREMENTS_INCOMPLETE`、`PRODUCT_NEEDS_INPUT`、`PRODUCT_MODEL_CONFLICT`、`SOURCE_CONFLICT`、`NO_EXTRACTABLE_FACTS`、`KNOWLEDGE_QUOTA_LIMITED`、`KNOWLEDGE_SOURCE_UNAVAILABLE`、`VERSION_CONFLICT` 和 `NOT_IMPLEMENTED`（后者不用于本检索路由）。

FactRecord 的 `evidence_text` 是实际取得资料中的逐字片段，`source_ref` 指向对应资料；无法确认来源类别时 `source_type=other`。`retrieved_at` 仅表示本次检索时间，不能当成资料发布时间或有效期；未明确注明有效期时 `valid_until=null`，当前有效性未知。明确过期的记录标记 `stale` 并令结果为 `partial`。价格、库存、优惠、活动及服务承诺不会作为稳定产品事实保存。检索服务不让模型置信度替代来源证据，也不把场景推断、用户输入或演示资料当成已核验事实。`local` 来源必须返回 `knowledge_source.live=false`，不会声称实时在线核验。

适配器入口可独立调用：

```python
from src.product_research_service import ProductResearchService

result = ProductResearchService().retrieve_product_facts(
    "完整产品型号"
)
```

此服务复用 `KnowledgeService`、`ImaClient` 和 `LocalKbClient`，不重新实现来源客户端。在线响应需如实标识 `live`；本地副本不等于在线资料。本接口只完成读取与 FactRecord 转换；有事实记录时 `next_action=check_facts`。FactRecord 初始状态始终为 `retrieved`，不能因为检索成功就作为已核实事实或直接用于策略。

请求与响应结构见 [research-request.json](examples/research-request.json) 和 [research-response.json](examples/research-response.json)。这些文件均为使用合成型号、合成来源和合成证据的契约示例，不是线上接口实际响应或产品事实。真实只读 HTTP 测试必须显式运行：

```powershell
python -B huawei-marketing-agent/scripts/product_research_http_demo.py --live --source-mode local
```

脚本执行真实 understand 后使用返回的 `task_id` 和 `revision` 调用 research；仅在显式传入 `--live` 时运行，不保存知识库正文或完整响应。`--source-mode local` 只覆盖该演示进程，不改变持久环境配置。

### 显式启用的两轮真实 HTTP 演示

在仓库根目录运行 `python huawei-marketing-agent/scripts/requirements_http_demo.py --live`。仅在带 `--live` 时才发送测试需求到当前配置的 LLM；未带标志会在调用前退出。脚本启动当前仓库的 Handler，使用操作系统分配的新端口，依次调用 understand 和 continue，并将第一轮实际返回的 task_id/revision 用于第二轮。结束后只关闭本脚本的服务，不复用或停止已有服务，不保存完整响应文件。

测试输入由脚本内的合成需求组成，不读取知识库或环境配置值作为模型输入。场景覆盖模糊需求追问、机会来源继承、补齐需求、自然语言修改受众、显式清空场景。LLM 配置只检查存在性；`LLM_API_TYPE` 未设置时沿用 LLMClient 的 chat_completions 默认值。默认离线 unittest 不执行本脚本。

### `POST /api/strategy/generate`

请求只包含 `task_id`、`expected_revision`，不接受客户端提交候选事实、策略内容或确认状态：

```json
{"task_id":"task-...","expected_revision":6}
```

需求必须完整、产品检索快照仍有效，且至少有一条当前通过核查、未过期且与精确型号一致的事实。只有这些事实会被提供给策略模型；`retrieved`、未核查、过期、冲突或其他任务中的记录没有使用资格。没有可用事实时返回 `NO_VERIFIED_FACTS`，不调用策略模型。

模型须生成一个主推 StrategyDraft，覆盖 `task_summary`、`topic`、`audience`、`audience_need`、`core_message`、`content_angle`、`content_format`、`content_outline`、`cta`、`fact_references`、`assumptions`、`pending_confirmations` 和 `risk_notes`。CTA 可以为空。受众描述沿用用户确认内容；受众需求解释属于推断，必须列入 `assumptions`。不能把校园客流、购买意愿、性能效果或其他常识推断升级成产品事实。

服务端独立审查所有对外策略字段，包括主题、核心表达、提纲、CTA、假设、待确认项与风险备注，而不是只核查 `fact_references`。模型同时提交内部 `fact_claims` 映射；`field_path` 必须指向契约中的标量字段或实际存在的 `content_outline[i].section`、`content_outline[i].purpose`、`assumptions[i]`、`pending_confirmations[i]`、`risk_notes[i]` 项，且 `claim` 必须是该字段中的连续原文；映射只可引用当前可用 fact ID。随后每条事实表达都会经 `FactChecker` 对照服务端原始检索快照。来源、型号、配置、数字、单位与限制条件必须一致。已有负面核查项若没有被策略引用，不会单独阻断无关的有效事实。策略最多进行一次针对阻断项的修正并完整重新核查；仍有不支持项时返回 `STRATEGY_FACTS_UNSUPPORTED` 及具体阻断项，不保存待确认策略，也不降低核查要求。若 LLM 请求被服务端以 HTTP 错误拒绝，错误可附安全 HTTP 状态码，不包含凭证或原始响应内容。

模型调用失败时，接口保留任务和已核查事实，返回安全错误及 `retry_strategy` 建议。连接失败、请求超时、上游 HTTP 错误、JSON 解析失败、响应结构无效分别返回 `STRATEGY_CONNECTION_FAILED`、`STRATEGY_REQUEST_TIMEOUT`、`STRATEGY_UPSTREAM_HTTP_ERROR`、`STRATEGY_JSON_INVALID`、`STRATEGY_RESPONSE_INVALID`；程序内部异常返回 HTTP 500 与 `STRATEGY_INTERNAL_ERROR`。事实核查阻断仍返回 HTTP 422 与 `STRATEGY_FACTS_UNSUPPORTED`，不归类为网络或模型不可用。失败策略不会进入待确认状态。

成功或失败响应的 `data.diagnostics` 提供本次请求的总耗时、模型调用次数、实际上游请求次数及阶段列表。阶段为 `setup`、`initial_generation`、`strategy_audit`、`fact_check` 或 `repair`，分别记录耗时、状态和异常类型白名单；确有上游 HTTP 响应时才提供状态码及通过白名单的 `request_id`。一次 JSON 格式修正可能对应两次上游请求，诊断会分别计数。诊断不包含异常正文、请求头、配置值、提示词、知识库正文或完整模型响应，也不缓存进程间的历史原因。没有保存原因的旧故障不能据此恢复根因。

策略陈述按语义区分事实、内容规划、约束、用户上下文、明确假设和来源限制。纯规划（如“建议采用三张图呈现”）与约束（如“不要写证据未支持的参数”）属于 `not_applicable`，不需要产品证据，也不授予事实使用资格。不能只凭“采用”“支持”等单个词判事实。混合表达必须拆出实际事实子句（如“采用双栏排版，突出其配备某处理器”中的处理器断言）并交给现有 FactChecker；任何策略字段都不跳过全文独立审查。内部审查 `kind=uncertain` 会产生 `needs_confirmation` 阻断项。事实映射仍须逐字定位到策略字段，但策略相对来源可以忠实改写；引用、型号、数字、单位、配置及适用条件的检查保持不变。

成功时 HTTP 200、`success=true` 表示策略生成及核查流程已按契约完成，不代表每条候选事实都通过，也不代表用户已确认。`data.fact_check.results` 是本策略各事实表达的逐项结果；本策略只有全部必要表达为 `supported` 才保存。`data.task.workflow_status=awaiting_user_confirmation`，策略状态为 `pending`，`next_action=confirm_strategy`。策略 ID、策略版本、任务绑定和确认状态全部由服务端产生。完整响应示例见 [strategy-generate-response.json](examples/strategy-generate-response.json)；它是合成契约示例，不是真实调用结果。

### `POST /api/strategy/confirm`（补充确认契约）

本路由用于明确确认，生成接口不会隐式确认。请求必须同时绑定当前 `task_id`、`expected_revision`、`strategy_id` 和 `strategy_version`。仅当策略仍是当前任务唯一有效版本、状态为 `pending`，且保存的完整策略核查及所用事实仍有效时，任务才会进入 `strategy_confirmed`。客户端不能自报 confirmed。需求输入、产品或证据发生变化后，旧策略会失效并留在历史快照中；确认过期版本返回 HTTP 409。新的策略版本必须重新确认。请求和成功响应示例见 [strategy-confirm-request.json](examples/strategy-confirm-request.json) 与 [strategy-confirm-response.json](examples/strategy-confirm-response.json)。

### `POST /api/strategy/handoff`

图文模块使用此明确接口读取确认交接对象。请求与确认使用相同字段，并须提供确认后当前返回的 `expected_revision`。只有当前任务处于 `strategy_confirmed`、strategy ID/version 匹配且策略审查和采用事实仍有效时才返回交接。响应包含当前任务快照、已确认策略、策略采用的 FactRecord 原文和来源、有效事实核查结果、策略审查记录、知识来源限制、平台与用户约束、待确认项，以及 `images` 和 `image_status`。当前图片尚未在策略阶段验证，因此保持 `images=[]`、`image_status="unknown"`，不能据此宣称素材已确认。不得将未核查候选事实当作可用卖点。结构示例见 [creative-handoff.json](examples/creative-handoff.json)；该文件是合成 fixture。

### `POST /api/facts/check`

此路由是独立的生成前检查入口，不会由 `continue` 或 research 隐式调用。请求必须使用当前任务版本；每条陈述只能提交文本和服务器 FactRecord ID，不接受客户端提供的 `supported` 状态、`source_ref` 或证据原文：

```json
{"task_id":"task-...","expected_revision":4,"claims":[{"claim":"待核查陈述","fact_references":["fact-..."]}]}
```

服务端从当前任务及私有检索快照取证。不存在、伪造、演示目录、用户输入或其他任务的引用不能成为证据。候选 FactRecord 可直接核对原文切片；改写陈述可调用配置的 LLM 作语义辅助，但服务端还会逐字核对引文、型号、参数、数字/单位、否定与条件。引用无法复核、模型异常或判断不确定时不会标记为 supported。来源冲突会标为 conflicting；价格、库存、优惠或服务承诺没有有效范围和当前依据时不得作为稳定事实。场景推断和受众需求使用 `not_applicable`，不授予产品事实资格。

每条结果包括 `claim`、`status`、`evidence`、`source_refs`、`reason`、`suggested_action`，并绑定 `task_id`、`task_revision` 和 `fact_references`。状态为 `supported`、`unsupported`、`conflicting`、`needs_confirmation` 或 `not_applicable`。`supported` 严格表示“当前陈述得到本次可用来源支持”，不代表资料最新或已获官方认证。结果保留 `knowledge_source`、来源类别、警告及各状态计数；local 来源保持 `live=false`。

API `success=true` 仅表示请求已按契约处理，不表示批次全部通过。批次中失败的陈述不会自动阻断无关事实。`data.fact_check.eligible_fact_ids` 是本次及历史有效检查后允许策略引用的当前事实集合；只把与候选 FactRecord 原 claim 完全对应且状态为 supported 的事实列入，改写结果本身不替代原事实。策略生成只从这个白名单选取事实，并在策略中再次进行逐项核查。

LLM 调用期间不持有任务仓库锁；完成后会再次核对任务版本和证据快照。版本变化返回 HTTP 409 `VERSION_CONFLICT`，过期结果不保存。后续产品/证据变化会将旧检查标为无效并把事实状态恢复为 `retrieved` 或清除相关事实；审计记录仍保留原检索记录、核查证据与旧版本绑定。模型失败时独立判定仍会保留，未完成项为 `needs_confirmation`，接口返回 `success=false` 并给出恢复建议，不丢弃检索任务。

结构示例见 [facts-check-request.json](examples/facts-check-request.json) 与 [facts-check-response.json](examples/facts-check-response.json)。它们只使用合成型号、来源和证据，不是实际产品结论。真实核查 HTTP 演示必须显式传入 `--live`：

```powershell
python -B huawei-marketing-agent/scripts/facts_check_http_demo.py --live --source-mode local
```

脚本会用实际返回的 task ID 与 revision 依次调用 understand、research、facts/check；只输出结果摘要和有限长度的证据片段，不保存完整知识库正文或响应。

### `POST /api/facts/check-final`

请求沿用 `task_id`、`expected_revision`、`strategy_id`、`strategy_version` 和 `content`，必须绑定当前已确认且事实仍有效的策略。`content` 的五个必填字段仍为 `title`、`body`、`cta`、`plain_text`（均为字符串）和 `images`（数组）；CTA 可为空。可选增加 `selling_points`、`tags`、`additional_text`（字符串数组）及 `fact_references`（FactRecord ID 数组）。不接受客户端核查状态、证据或单独 claims；即使不提供任何引用，也会独立提取全文事实。

图片项可包含 `name`、`caption`、`description`、`alt`、`text`、`product_model`、`source`（文字），以及 `url`（字符串或 null）、`source_ref`、`status`、`fact_references`。所有非空展示文字均纳入独立覆盖检查；未知字段拒绝处理，不能藏入其他未审查文字。`status=confirmed` 不构成视觉证据。服务不抓取 URL，不推断图片外观或内嵌文字。

核查读取服务端当前已确认策略、采用的有效事实及私有原资料快照，独立提取标题、正文、CTA、卖点、标签、补充文字和图片说明中的事实。复用生成前 fact_checker 逐项核对证据、引用、精确型号、数字/单位、配置和适用条件，并检查价格、优惠、服务承诺、绝对化表达、用户限制及策略一致性。规划、约束与明确标记的推断单独分类；建议句夹带的事实仍需核查。未经支持的事实必须删除或忠实改写后重新检查，免责声明不构成通过依据。

成功处理返回 HTTP 200、`success=true`、`data.task`、`data.final_check` 和 `next_action`。这与文字或整套素材是否通过独立：

- `text_check.status` 为 `passed`、`blocked` 或 `needs_confirmation`；逐项 `results` 含 `field_path` 和既有 FactCheckResult（`claim/status/evidence/source_refs/reason/suggested_action` 等），另有 `counts` 和 `blocking_items`。
- `image_check.status` 始终为 `unknown`，`visual_check_performed=false`、`confirmed_count=0`；图片像素、内嵌文字、型号对应及授权均未核验。空图片数组也返回明确缺项，不代表图片核查通过。
- 文字通过且图片未知时，`overall.status=partial`、`text_usable=true`，`usable_text` 原样保留提交的四个文字字段；`completed=false`、`ready_to_publish=false`。文字不通过时整体为 `blocked`，`usable_text=null`，不会覆盖用户编辑的原成稿。
- `knowledge_source`、`warnings` 如实保留 local/live=false、other 来源可靠性以及有效期未知限制，不能宣称实时或官方认证。

绑定包含 `task_id`、`task_revision`（开始核查时的版本）、`saved_task_revision`、`strategy_id/version`、服务器生成的 `content_version`、`content_digest`（SHA-256）和 `check_id`。摘要对整个 content 规范 JSON 计算，包含图片、引用和所有文本：UTF-8，键排序，无空白分隔符，`ensure_ascii=False`。调用方不应自行填核查版本或摘要。

一次请求在模型调用前登记成稿，增加 task revision 并使旧最终核查失效；正常保存后再增加一次 revision。模型调用期间不持有仓库锁，保存前重新校验任务、策略、产品和证据。并发修改返回 HTTP 409；模型/审查异常返回安全的 HTTP 502、实际最新 task 与恢复建议，不伪造通过。失败的新成稿也不会沿用旧成稿的通过状态。产品、证据、策略输入或确认策略改变时相关旧核查失效。

客户端手动编辑后应立即撤下旧的核查通过标志，重新提交完整 content；服务端无法观察尚未提交的浏览器编辑。消费结果时必须比对当前内容摘要及策略版本。进程内可通过 `REPOSITORY.get_final_checks(task_id, content=current_content)` 取得按当前内容复核有效性的深拷贝审计记录，不提供覆盖文案的接口。

请求和文字通过/图片未知响应见 [final-check-request.json](examples/final-check-request.json)、[final-check-response.json](examples/final-check-response.json)。这些是合成契约示例，不是真实产品核查结果。真实核查验收使用下一节命令；手工验收成稿不是图文模块生成结果。

## FactRecord

每条资料事实至少包含 `fact_id`、精确 `product_model`、`claim`、逐字 `evidence_text`、`source_ref`、`source_type`、ISO 8601 的 `retrieved_at`、可空 `valid_until` 和 `status`。标为 `retrieved` 或 `supported` 的事实必须带原文和来源。模型置信度不是契约字段，也不能替代证据。

## 工作流和结果语义

`collecting_requirements` 表示需求仍需补充或理解尚未实际完成；`researching` 表示真实检索已开始；`ready_for_strategy` 表示需求信息足够进入策略阶段，**不表示产品事实已检索或核验**；`awaiting_user_confirmation` 表示策略已生成但未确认；`strategy_confirmed` 表示策略 ID/版本已明确确认；`failed` 表示当前步骤明确失败。事实是否支持仍只能看对应 FactRecord/FactCheckResult。FactRecord 在研究阶段只能为 `retrieved`；只有与有效核查结果绑定的候选原事实才可成为 `supported` 并进入后续策略白名单。`not_applicable`、`needs_confirmation`、`unsupported` 或 `conflicting` 均不授予资格。

当前内部集成点包括 `begin_research(task_id, expected_revision)`、`complete_research(task_id, expected_revision, fact_records)`、`fact_check_snapshot`、`complete_fact_check`、`strategy_snapshot`、`add_strategy(task_id, expected_revision, draft, assessment, context)`、`confirm_strategy(...)` 和 `creative_handoff(...)`。`complete_research` 拒绝同一任务混入多个精确产品型号；`add_strategy` 会复核策略核查凭据、证据快照与当前白名单。图文模块优先使用 `POST /api/strategy/handoff`，而不是直接访问仓库内部对象。

以下语义相互独立，调用方不得混为一谈：

- `success` 是 HTTP/API 层是否按契约处理了请求；
- `workflow_status` 是任务目前实际进行到哪一步；
- `FactCheckResult.status` 是单条事实的核查结论。

例如完整需求的 `understand` 返回 HTTP 201、`success=true` 与 `workflow_status=ready_for_strategy`，只表示需求理解完成、可进入下一步；并不表示知识库检索或事实核查已完成。策略生成会读取当前事实白名单、生成并再次核查策略，然后等待明确确认。最终核查处理成功也可能返回文字阻断或图片未知；不表示整套图文完成。最终图文生成模块尚未接入。

## 并发、隔离和存储限制

仓库以锁保护并发读写，版本检查与变更在同一临界区执行；每个响应均为深拷贝快照。不同 `task_id` 之间不共享上下文。存储仅在当前 Python 进程内有效，进程重启后任务清空；它不是持久化方案，也没有用户身份鉴权，不应直接暴露到公网。

## 图文模块交接

图文生成模块应只消费 `strategy_confirmed` 的 TaskContext 快照、已确认 Strategy 和对应 FactRecord。每条文案事实都应映射到 `fact_references`；下游请求需保留 `task_id`、`task_revision`、`strategy_id` 和 `strategy_version`，并调用 `facts/check-final`。交接结构示例见 [creative-handoff.json](examples/creative-handoff.json)。其中标注的合成字段只展示结构，不是产品资料或核查通过结果。未经确认或返回 `NOT_IMPLEMENTED` 时，不得显示成功发布状态。

### 显式启用的完整策略 HTTP 演示

在仓库根目录运行：

```powershell
$env:STRATEGY_LLM_TIMEOUT_SECONDS = "120"
python -B huawei-marketing-agent/scripts/strategy_http_demo.py --live --source-mode local --keep-server-on-failure
```

脚本使用当前仓库 Handler 和系统分配的新回环端口，依次调用 understand → research → facts/check → strategy/generate → strategy/confirm → strategy/handoff，每一步沿用上一步实际返回的任务和策略版本。它只核查少量精确型号候选事实，同时提交一条无依据优惠作为负面检查；未被策略采用的负面陈述不会阻断其他可用事实。完整策略、逐项核查及交接采用的证据节选仅输出到终端，不保存知识库正文、缓存或完整响应。未传 `--live` 时不会启动服务或调用任何模型/知识来源。失败时立即报告实际阶段、错误和阻断项，不确认策略、不自动重试整条链路。使用 `--keep-server-on-failure` 时，失败后保留同一服务、端口和当前 task_id/revision；可以继续向该端口诊断，Ctrl+C 才关闭服务。成功后正常停止自己的服务。未传保留选项则仍自动清理服务。

`STRATEGY_LLM_TIMEOUT_SECONDS` 是可选的策略专用超时（秒），未设置时为 120；每次策略请求读取，必须为有限正数。它仅传给策略生成、独立策略审查和修正所使用的 LLMClient；不改变需求理解、检索、独立 `/api/facts/check` 或 v1 `/api/run` 的超时。服务端注入的共享 fact_checker 沿用自己的配置。不会自动增加时间或重试网络请求，已有的一次 JSON 格式修复和最多一次策略定向修正边界保持不变。本次诊断若 120 秒仍超时，应停止增加时间并检查上游服务。

策略请求按白名单投影：当前有效需求、已获使用资格的事实（完整 claim/evidence_text、型号、限定及来源）和来源限制；不发送对话历史、原始知识库文档、未核查候选或测试样例。`diagnostics.stages[].request_size` 只记录 `system_prompt_chars`（含客户端 JSON 指令）、`payload_chars`（实际 JSON 序列化字符数）、`fact_count` 和 `history_turn_count=0`，不返回请求正文。阶段耗时、调用次数和安全错误分类继续保留。

HTTP 演示客户端对策略路由的等待上限为 `max(240, 12 × max(60, 策略超时) + 60)` 秒；120 秒配置对应 1500 秒。这覆盖最多两次策略尝试中的生成、审查、语义核查及各自既有的一次格式重试，并留清理余量；这个 HTTP 等待上限不增加任何模型调用。除下节 `check-final` 的 1200 秒验收等待外，其他路由仍为 240 秒。调用方应避免使用比整个策略工作流更短的 HTTP 等待时间，并显示等待状态、防止重复提交；HTTP 等待超时不表示服务端模型调用已撤销。

示例文件均为合成契约，不是真实生成结果。产品变化会使旧事实、核查和策略失效；受众、平台、目标或其他策略输入变化会使策略和确认失效，但保留未受影响的产品事实及核查。历史策略快照只读保留，新策略必须重新确认。

### 包含最终核查的显式真实验收

```powershell
$env:STRATEGY_LLM_TIMEOUT_SECONDS = "120"
python -B huawei-marketing-agent/scripts/strategy_http_demo.py --live --source-mode local --keep-server-on-failure --check-final
```

在同一个新回环服务中完成 understand → research → facts/check → strategy/generate → confirm → handoff 后，脚本根据真实交接事实手工构造标为“核查验收输入”的成稿：A 忠实完整引用采用事实；B 篡改首个数值（如存在）并添加无依据价格优惠，且不主动提供引用。两次按实际最新 revision 提交 check-final，验证文字通过/阻断、图片 unknown，以及编辑后 A 的旧审计失效。失败即报告阶段并保留服务，不无限重试。不代表图文模块已经生成最终素材。

演示只对短验收成稿使用 1200 秒的最终核查 HTTP 等待，覆盖全文审查与少量逐项语义核查；不改变模型请求超时或增加重试。调用方应按成稿规模设置足够的 HTTP 等待，不能把等待超时当作已经撤销服务端请求。

确认语义：若引用记录与精确型号已由服务器原资料快照核对，对应重复的“发布前确认型号对应关系”改为已核对说明，并保留来源可靠性/时效限制。尚未核实的关键型号、配置或证据缺口会阻断生成或确认，不能靠删除提示消除；表达偏好和来源展示格式等非关键事项可留作待确认项。完整交付说明见 [agent-core-a-handoff.md](agent-core-a-handoff.md)。
