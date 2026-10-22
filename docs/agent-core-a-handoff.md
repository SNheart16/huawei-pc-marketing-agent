# A 模块交付说明

本说明对应 `feat/agent-core-a` 的需求理解、检索、事实核查、策略与统一 API。保留旧 `POST /api/run` 的 JSON v1.0 以及 `/backend.html`；新增工作流使用独立 v2 envelope，未修改 UI。

## 交付范围

已实现并完成真实 HTTP 验收：需求理解及按需续答、只读产品检索、FactRecord 转换、生成前核查、真实策略生成及全文审查、显式策略确认、真实 handoff、最终成稿文字核查，以及任务隔离、版本冲突和结果失效保护。检索成功的 `retrieved` 事实必须先取得有效核查资格，不能直接用于策略。

尚未实现或待团队联调：新版 UI 调用 v2、图文模块消费 handoff 后生成成稿、真实生图、图片视觉识别及素材授权核验。当前首页是既有本地模拟原型；`/backend.html` 使用旧 `/api/run`，不代表新版多轮工作流已接好。图片核查仍为 `unknown`，不宣称整套图文可直接发布。

## 启动与配置

推荐 Python 3.11+；本次交付在 Python 3.14.5 验证。根服务、后端客户端和离线 Python 测试仅使用标准库，`huawei-marketing-agent/requirements.txt` 当前没有第三方包，无需安装或升级依赖。只有使用 ima 在线来源或运行前端 Node 测试时需要 Node.js（建议 20+）；local 检索不需要 Node。

从仓库根目录运行（Windows 可将 `python` 换为 `py -3`）：

```powershell
python --version
python -B app.py --port 7860
```

访问 `http://127.0.0.1:7860/`，旧接口页为 `/backend.html`；v2 通过同一服务的 HTTP 路由调用。`GET /api/health` 只表示导入状态，不证明模型或知识来源可用。停止服务用 `Ctrl+C`。服务只监听 `127.0.0.1`。

程序直接读取启动进程的环境变量，不会自动加载 `.env`；`.env.example` 也不会自动生效。应在同一终端设置好环境再启动，凭证由成员各自在本机安全配置，不写入源码、请求 JSON 或日志。以下只列变量名称、用途与非敏感默认行为：

| 变量 | 用途及适用范围 |
| --- | --- |
| `LLM_API_KEY` | 当前模型服务凭证，真实需求理解、策略和语义核查需要 |
| `LLM_BASE_URL` | 模型服务 HTTPS 基址，不得含凭证或查询参数 |
| `LLM_MODEL` | 当前服务支持的模型名称 |
| `LLM_API_TYPE` | 可选，`chat_completions`（默认）或 `responses` |
| `KNOWLEDGE_SOURCE_MODE` | `ima`（未设置时默认）、`local` 或 `auto`；本地验收显式选 `local` |
| `LOCAL_KB_PATH` | local/auto 所需的仓库外只读知识库目录；不提交、不回传完整路径 |
| `IMA_OPENAPI_CLIENTID`、`IMA_OPENAPI_APIKEY` | ima/auto 在线读取所需凭证；local 不需要 |
| `USE_MOCK` | 旧流程的模式开关及真实演示检查；真实联调设置 `false`。v2 不以 mock 回退 |
| `SYSTEM_PROMPT_PATH` | 旧 `/api/run` 系统提示词的可选覆盖路径 |
| `AGENT_UNDERSTANDING_PROMPT_PATH` | v2 需求理解提示词可选覆盖路径 |
| `FACT_CHECK_PROMPT_PATH` | v2 事实语义核查提示词可选覆盖路径 |
| `STRATEGY_PROMPT_PATH` | v2 策略提示词可选覆盖路径 |
| `STRATEGY_LLM_TIMEOUT_SECONDS` | 策略专用模型调用超时，默认 120 秒；不修改其他接口超时 |

模型配置读取进程环境中的 `LLM_API_KEY`、`LLM_BASE_URL`、`LLM_MODEL`（以及客户端支持的可选 `LLM_API_TYPE`）。不得打印或向接口调用方回传环境值。本地验收使用 `KNOWLEDGE_SOURCE_MODE=local`、`USE_MOCK=false` 和仓库外的 `LOCAL_KB_PATH`；本地目录由使用者在启动环境中设置，不硬编码进源码、提交样例或复制知识库到仓库。

本地知识库副本和 ima 官方脚本需另行准备，不随 A 交付复制或打包。ima 脚本路径为 `huawei-marketing-agent/ima-skill/ima-skill/ima_api.cjs`，由后端目录计算，不使用少一层目录的错误路径。`ima` 只读在线来源；`auto` 只在明确配额、服务不可用或超时情况下回退，不以型号/事实冲突、缺凭证或普通 API 错误为由切换来源。一次检索不静默混合本地与在线事实。本次本地验收成功不能宣称在线 ima 同步验证成功。

旧流程 `SYSTEM_PROMPT_PATH` 是可选覆盖；未设置时按模块 `__file__` 计算仓库默认 `prompts/system.md`。v2 默认提示词分别为仓库 `prompts/understanding-system.md`、`fact-check-system.md`、`strategy-system.md`、`final-check-system.md`，均按代码位置查找，不依赖终端目录。需求理解可选 `AGENT_UNDERSTANDING_PROMPT_PATH`，策略可选 `STRATEGY_PROMPT_PATH`。`STRATEGY_LLM_TIMEOUT_SECONDS` 仅影响策略 LLM 调用，默认 120 秒，不扩大全局所有接口超时。

## 前端调用顺序

```text
understand → continue（按需）→ research → facts/check →
strategy/generate → strategy/confirm → strategy/handoff →
图文模块生成 → facts/check-final
```

1. `POST /api/agent/understand` 建立任务；缺信息时用 `/api/agent/continue`。保留原始需求与对话，当前明确修改、清空和排除优先于历史。
2. 需求足够后显式调用 `/api/agent/research`；它不会在需求理解阶段自动执行。FactRecord 初始为 `retrieved`，不是核查通过。
3. `/api/facts/check` 核查所需候选事实及改写；只提交 `claim` 与当前服务器 `fact_references`。检查 `eligible_fact_ids`，不能自行提交 supported 或编造 source_ref。
4. `/api/strategy/generate` 只使用有效事实白名单，独立审查策略全部文字；至多一次定向修正，失败时不进入待确认。
5. 用户明确接受后 `/api/strategy/confirm`，必须绑定当前 `task_id`、`expected_revision`、`strategy_id` 和 `strategy_version`。模型或客户端不能自报已确认。
6. `/api/strategy/handoff` 返回同一当前确认策略、采用的事实原文与来源、有效核查、平台要求、用户限制和未确认事项。
7. 图文模块消费 handoff 生成并保留用户可编辑成稿；该生成模块尚未接入，不由 A 的核查接口代替。
8. 图文模块完成成稿后 `/api/facts/check-final` 独立核查完整 content；策略通过不能替代成稿核查。

每一步使用上一步实际返回的 `task.revision`，不能按示例硬编码。`success=true` 只表示处理成功；工作流状态、单条事实支持、文字可用、图片未知和整套素材完成情况是独立概念。HTTP 409 表示版本或确认条件不再满足，应刷新任务并让用户重新判断；HTTP 502 提供安全错误和恢复建议，不能切换 mock 假装通过。

## 前端同学的接入位置

根目录 `app.py` 已把八个 v2 POST 路由交给 `huawei-marketing-agent/src/workflow_service.py`，无需改变旧 `/api/run`。新版首页脚本为 `ui/prototype.js`，引导状态在 `ui/guidance.js`，演示目录在 `ui/prototype-data.js`。接入时保留现有界面与布局，将模拟理解、策略和成果逻辑逐段替换为真实接口；`ui/app.js` 属于 `/backend.html` 的旧接口脚本，不是 v2 接入完成的依据。

先按 [understand-request.json](examples/understand-request.json) 接通创建任务和摘要/追问展示，随后按上面的顺序接入。机会入口保留 `source=opportunity` 及 `opportunity_context`，不得把演示目录或前端用户自报状态当作已核实事实。

- 明确清空通过 `/api/agent/continue` 的 `clear_fields` 提交，明确修改通过 `updates` 提交；同一字段不能同时出现。不能把空值重新用历史、机会或默认值补回。
- 保存服务端当前 `task_id/revision` 与 `strategy_id/strategy_version`。所有后续写请求携带最新 `expected_revision`；示例中的 `task-example-*`、`task-synthetic-*` 和版本数值仅为占位，不能直接复用。
- 当前任务或草稿变更后，过期响应不得覆盖手动编辑；重新生成前保留原稿并取得明确确认。成稿一经本地编辑，应立即撤下旧核查标记，重新核查完整内容。
- 耗时调用显示等待状态，禁用重复提交，并按 API 文档设置足够的 HTTP 等待。浏览器等待超时不等于服务端请求已取消，不要自动重复调用模型。
- 错误显示安全 `error.code/message` 与恢复动作，不回退模拟成果。版本冲突按返回的最新任务快照处理；任务因重启丢失时需重新创建。不得显示异常堆栈或配置值。

## 图文模块对接

API 细节与可解析样例见 [agent-api-v2.md](agent-api-v2.md)。同学可直接使用 `docs/examples/creative-handoff.json` 理解输入、`final-check-request.json` 理解最终核查请求、`final-check-response.json` 理解文字通过但图片未完成的输出。这些是合成契约样例，不是真实检索或生成结果。

只把 handoff 中当前采用且有效的 `fact_records` 用作卖点；保留精确型号、配置、适用条件、fact ID、证据原文和相对来源。把推断放在 assumptions，不升级为产品事实。不把未知图片当作已确认图片。提交最终核查时保留完整标题、正文、CTA、plain_text、图片文字，以及实际展示的卖点/标签/补充文字。不能只报主动选择的 claims 来绕过全文检查。

最终核查不会改写成稿。`text_check.status=passed` 时 `usable_text` 原样保留四个主文字字段；有阻断时必须删除或改写相应事实，再提交完整新成稿。不得只加免责声明。图片没有视觉识别能力，`image_check.status=unknown`、`confirmed_count=0`，即使图片说明文字通过，像素、内嵌文字、外观、型号对应和授权仍未核验。没有图片同样属于未完成，不能显示“图文全部通过”。

接入第一步是在策略确认后用当前版本调用 [strategy-handoff-request.json](examples/strategy-handoff-request.json) 对应路由，读取 `data.handoff`。生成时只使用其中 `fact_records`，不要重新读取任务全部候选或 fixture。提交最终核查必须保留实际展示的全部文字，不能只提交已标引的句子；具体必填字段见 API 文档和 final-check 示例。

| 结果层级 | 正确处理 |
| --- | --- |
| HTTP 2xx、`success=true` | 接口已处理，继续读取工作流及逐项结论；不显示“全部核验通过” |
| 单条 `supported` | 仅表示本次可用来源支持该陈述，不保证最新或官方认证；策略只用有效 `eligible_fact_ids` |
| `text_check.status=passed` | 当前完整文字可用；原样保留 `usable_text`，不得代表图片通过 |
| `overall.status=partial` | 当前文字通过但图片未知；可保留可用文字并显示待补项，不能宣称整套图文完成或可发布 |
| `overall.status=blocked` | 不采用被阻断成稿，按逐项建议删除/改写再检查；`needs_confirmation` 也不能当作通过 |

当前视觉核查缺失，因此本实现不会返回整套图文 `passed`，`completed` 和 `ready_to_publish` 均为 `false`。不要为配合 UI 把 partial 改写成 passed。

## 版本与编辑保护

任务、策略 ID/version、确认状态、事实使用资格及成稿版本均由服务端管理。事实绑定服务器本次检索快照；模型判断不能替代原文和来源。产品或证据变化使旧事实相关核查和策略失效；受众、平台、目标、场景和其他策略输入变化使策略及其确认失效，未受影响事实可以保留。历史策略与核查审计只读保留，不能用旧确认批准新版本。

最终核查绑定 task、策略 ID/version、evidence_revision、content_version 和完整内容 SHA-256。模型调用前登记新 content 并使旧结果失效，调用完成前后均复核版本；模型失败也不会让新编辑沿用旧通过状态。只返回深拷贝；模型外部调用期间不持仓库锁。

前端手动编辑任何成稿字段或图片元数据时，必须立即撤下旧通过状态，并重新提交 content。服务端无法察觉尚未提交的本地编辑；消费核查结果时还需比较当前策略版本和 content_digest。最终接口正常处理会登记、保存各增加一次 task revision，必须使用返回值。

## 测试与已完成验收

离线测试不访问真实模型或知识来源。在仓库根目录运行：

```powershell
python -B -m unittest discover -s tests -p "test_*.py" -v
node --test tests/test_prototype.cjs tests/test_ui.cjs
```

然后在 `huawei-marketing-agent` 目录运行：

```powershell
python -B -m unittest discover -s tests -v
```

A 最终核查阶段的 Python 基线为根目录 24 项、后端 268 项，共 292 项通过，包含旧 `/api/run` 回归、契约校验、版本/任务隔离、事实/策略/最终核查及失效保护。本次交付复核同样通过这 292 项 Python 测试及 89 项 Node 测试。离线测试使用合成证据和替身模型，不证明上游在线可用；前端 Node 测试覆盖既有原型，不代表新版 UI 已接入 v2。

已完成并由用户验收的真实范围：同一新服务内 understand → research → facts/check → strategy/generate → confirm → handoff → check-final。知识来源为 local、`live=false`，精确型号为 `HUAWEI MateBook X Pro 酷睿 Ultra 微绒典藏版`，6 份文档提取 27 条候选，没有混入 2021 型号。核查子集包含 2 条 supported、1 条冲突与 1 条无依据优惠 unsupported；策略只采用取得资格的事实，真实生成、独立核查、确认及同策略 handoff 成功。

最终核查 A 忠实使用 handoff 事实，正文与 plain_text 的两处表达均 supported，文字 passed、整体 partial；B 篡改数值并加入无依据价格/优惠，两字段共 4 项 unsupported，整体 blocked，`usable_text=null`。两次图片均 unknown；B 提交后 A 的旧核查失效。这是基于真实策略和证据手工构造的“核查验收输入”，不是图文生成模块已完成的证明。真实服务已停止，旧内存任务不可复用；文档示例只用占位 ID。本轮整理交付不重复付费验收。

显式运行 `python -B huawei-marketing-agent/scripts/strategy_http_demo.py --live --source-mode local --keep-server-on-failure --check-final`。脚本在同一新服务中完成理解到最终核查，按真实返回版本前进。A 使用真实 handoff 手工构造忠实文字；B 篡改数值并添加无依据价格优惠。两者明确是“核查验收输入”，不是完整图文生成器输出。不会保存真实知识库全文或完整响应。无 `--live` 时拒绝真实调用；失败不自动无限重试，可保留进程和任务诊断。

分阶段演示也都必须显式带 `--live`：`requirements_http_demo.py`（需求理解/续答）、`product_research_http_demo.py`（到检索）、`facts_check_http_demo.py`（到生成前核查）、`strategy_http_demo.py`（到确认/交接，`--check-final` 扩展最终核查）。文件均位于 `huawei-marketing-agent/scripts/`。真实调用会发送必要任务文本和产品证据片段并可能计费；默认 unittest 不执行这些真实调用。

## 已知限制

任务仅保存在服务端进程内，退出/重启即丢失，不能把上一进程的 task ID 用在新进程。当前无持久化、登录鉴权或跨进程共享，应仅绑定本机回环地址。来源为 local 时必须保留 `live=false`；`source_type=other` 不自动判错，也不能升级为官方。retrieved_at 是检索时间，valid_until=null 表示资料有效期未知。

已实现 A 侧需求理解、独立产品检索、前后事实核查、策略生成/全文审查、明确确认、真实 handoff、版本隔离与失效。待团队联调：新版 UI 接入 v2、图文生成模块消费 handoff 并提交成稿、视觉识别及素材授权核验。持久化与鉴权需另行规划，不能把当前内存工作流当成上线部署完成。
