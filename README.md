# 华为产品推广工作台


## 复赛集成演示

本轮在独立集成分支连接 A 需求理解、卡片与场景、检索核查、策略确认及 B 图文工作台。真实演示入口为 `/demo.html`；使用步骤、配置和边界见 [演示操作手册](docs/demo-runbook.md)，本轮实际验证范围见 [联调报告](docs/demo-integration-report.md)。这些实测结果不与历史验收混淆：接口导入、API 处理成功、文字核查通过与整套图文可发布是不同状态。

本轮暂停地图；图片视觉及内嵌文字核查仍为 `unknown`，不能宣称整套图文已核验或可直接发布。原首页保留最新 main 的前端原型；B 独立历史样例 `?content_demo=study` 使用演示策略，不可代替真实链路。

B 模块说明见 [B 接口交接](docs/TASK_B_HANDOFF.md) 和 [历史 B 验收](docs/TEST_RESULTS.md)。本轮默认采用预生成素材，生图 API 已禁用；历史 `layout`/`ai_reference` 说明不代表当前演示模式。B 历史文档中“A 尚未提供最终核查”的说法来自旧基线，本集成分支通过适配连接 A 已有接口。历史截图与实际响应成果保留在原 B 提交，本轮集成不将其加入 Git，也不把它们当作本轮验收证据。

预生成素材交付入口：[素材放置与清单维护](ui/assets/pregenerated/README.md)、[实际清单](ui/assets/pregenerated/manifest.json) 及 [页面操作](docs/demo-runbook.md)。公众号、朋友圈、小红书分别选择和排序图片，保留各自草稿；当前 X Pro 每栏 3 张可选。型号不明及 MateBook 14 素材不得混入 X Pro。图片保持视觉核查 `unknown`、授权待确认，不因使用固定素材而视为已核验或可直接发布。

## A 模块接入

A 侧真实需求理解、产品检索、生成前后事实核查、策略生成/确认和图文交接已完成端到端验收。接入请先阅读 [A 模块交付说明](docs/agent-core-a-handoff.md)、[API v2](docs/agent-api-v2.md) 和 [可解析契约示例](docs/examples/README.md)。当前团队仓库为 [huawei-pc-marketing-agent](https://github.com/SNheart16/huawei-pc-marketing-agent)。

新版首页尚未接入 v2；`/backend.html` 保留旧 `/api/run` 联调行为。图文生成模块消费 handoff 的联调、真实生图和图片视觉核查仍待完成，图片核查保持 `unknown`。下文保留既有前端原型与旧接口说明。

## 复赛前端交互原型 V1（当前首页）

当前 `/` 为复赛迭代后的前端原型（品牌：华为产品推广工作台），使用本地模拟数据，不需要配置模型或知识库凭证。

```bash
python3 app.py --port 7860
```

打开 <http://127.0.0.1:7860/>，体验「首页 → AI 引导工作台 → 推广策略选择 → 推广成果工作台」。门店设置和创作记录保存在当前浏览器。

**首页**：输入想法、在开始创作左侧选好发布平台后即可开始；产品为可选的轻量搜索单选，可明确「暂不指定」。不会预先要求目标、人群或渠道。空态建议从推广执行视角出发（主推什么、借什么节点、在哪发、什么要求）。

**AI 引导工作台**：聊天气泡式的对话引导。规则识别自由输入中的产品、目标、受众、渠道、篇幅、价格口径与语气；选项点击和自由输入都会推进对话，发送后有短暂的「正在思考」节拍。右侧面板分「已确认／待确认／可选补充」三层并与对话实时同步；信息足够时给出总结卡与「进入推广策略」主操作。生成前会主动确认一次内容语气（自然真诚／简洁专业／轻松亲切），语气选择直达生成链路，成果页仍可再调。当前为前端规则模拟，界面保留「Agent · 规则模拟」标识，不伪装真实 AI。对话、摘要与成果保存在浏览器本地，重新开始会清空当前对话，已保存成果留在创作记录。

**推广机会**：三类机会入口——真实场景、地理位置、时间节点，复用同一引导流程；机会仅携带快照与依据说明，不代表已核实的顾客需求。产品搜索读取 `ui/prototype-data.js` 的 8 个演示目录条目，按名称、型号、系列与别名筛选；目录没有的产品显示「暂未找到匹配产品」，不会猜测补全。当前数据结构仅支持一个讨论产品，不支持同时比较多个已选型号。

**推广成果**：策略确认后生成图文草稿，支持按平台切换、编辑文案与图片文字、复制、下载概念海报 SVG 或导出 Markdown；重新生成可撤销，刷新后保留编辑。图片为本地演示素材（`ui/assets/result-*.svg`），非指定型号实拍、非实时 AI 生成。策略与文案调整由前端规则模拟，不代表真实 Agent、用户调研或产品参数核验；价格、库存、促销、规格与门店服务均需人工核实，最终发布前须确认产品事实与门店条件。

成果工作台采用单一发布预览与紧凑编辑双栏，切换平台时保留各平台草稿。更换图片或模拟重新生成图片仅切换本地素材，不重置文案；仅改写文案需确认并支持撤销；局部调整、恢复与人工核验默认折叠。下载交付为实际 SVG 海报，完整图文说明导出为 Markdown（图片另行下载），不包含真实 AI 生图或自动发布能力。已确认策略快照用于生成图文，不从历史输入重新推断已清除的字段。

原有真实接口联调页面保留在 <http://127.0.0.1:7860/backend.html>（侧栏「真实接口联调」），使用下文的模型与知识来源配置。**下文的初赛说明与平台输出边界适用于该接口页面，不代表当前原型已联网或已部署。**

推荐交互验证：在「推广机会」展开任一类别的推荐依据与待核实信息，从机会卡片进入引导流程，依次验证目标确认、对话补充、右侧摘要同步、语气确认与策略生成。机会日期按浏览器本地日历计算；样例排期不会自动延期，全部过期后显示空状态。离线测试固定时钟，覆盖开始展示、准备期、执行窗口、到期日与轮换；示例数据位于 `ui/prototype-data.js`，正式使用前应替换为经核验的机会与排期。

## 前端结构说明与联调指引

### 文件职责

| 文件 | 职责 |
| --- | --- |
| `ui/index.html` | 单页骨架：侧边导航与页面容器，按 hash 路由渲染 |
| `ui/prototype.js` | 主交互：路由渲染、引导对话事件流、策略与成果生成（前端规则模拟）、localStorage 持久化 |
| `ui/guidance.js` | 引导规则引擎：自由文本解析（产品／目标／受众／渠道／篇幅／语气）、回复生成、机会画像 |
| `ui/prototype-data.js` | 演示数据：产品目录（8 条）、机会样例排期、策略素材、图片索引 |
| `ui/prototype.css` | 基础组件与页面样式 |
| `ui/home-base.css`、`ui/home-fx.js` | 首页视觉与动效 |
| `ui/guide-v2.css` | 引导工作台各轮迭代的视觉覆盖（聊天气泡、三层面板、语气 chips 等） |
| `ui/backend.html`、`ui/app.js`、`ui/styles.css` | 真实接口联调页（旧 `/api/run` 行为），与原型首页相互独立 |
| `ui/mock.js` | 保留文件，当前正式页面生成路径不使用它回退模拟结果 |

### 前后端边界（现状）

- `/`（原型首页）当前完全前端模拟：状态存浏览器 localStorage，无网络请求；接入真实 Agent 时以 [API v2](docs/agent-api-v2.md) 为准。
- `/backend.html` 走旧版 `POST /api/run` 六字段契约（`product_query`、`audience`、`scene`、`platform`、`goal`、`extra_requirements`），供联调真实模型与知识库；五态响应（`success`／`partial`／`needs_input`／`conflict`／`error`）的展示与复制权限约定见下文「使用与接口」。
- 地理信息接口的历史提议见 [地理接口契约](docs/backend-api-contract-geo.md) 与 [v0.1 JSON](docs/geo-api-contract-v0.1.json)。本轮暂停地图，演示服务不提供 `/api/geo/*`；手填门店仍属于用户输入。
- 前端对后端响应的处理约定（五态渲染、复制权限、`content.images` 与证据关联、图片可访问性检查）由 `tests/test_prototype.cjs` 中的 v1.0 契约用例锁定；改动接口行为时请同步更新测试。

### 前端回归

```bash
node --test tests/test_prototype.cjs tests/test_ui.cjs   # 99 项契约与行为测试
python -m unittest discover -s tests -p 'test_*.py' -v      # HTTP 服务与桥接测试
```

## 原有接口版本说明

面向门店导购、销售及门店／渠道运营人员的营销内容辅助工具。根据产品、目标受众、业务场景和发布平台，从指定知识来源整理产品证据，经两阶段模型调用生成文案与配图方案，并展示来源、检查结果和待确认信息。

- 代码仓库：<https://github.com/SNheart16/desktop-tutorial>
- 魔搭空间：<https://www.modelscope.cn/studios/SNheart/huawei-pc-marketing-agent>

> 当前为初赛开发版本，前后端与提示词已整合到 main。魔搭空间已创建，应用部署状态以空间页面为准。离线测试使用受控数据，不代表真实 ima 或模型调用已经验证；本地副本也不等同于在线 ima 检索。

## 功能与边界

- 输入产品型号、受众、场景、平台、目标和补充要求。
- 通过在线 ima 或明确配置的本地只读副本获取资料；每次检索使用单一来源，不混合线上和本地证据。
- 先规划场景策略与事实证据，再生成平台内容；程序检查来源、原文引用、型号、必要结构和部分营销风险。
- 展示事实、图片、来源状态、风险和补充问题；复制后端返回的最终 `plain_text`。
- 型号不明确或资料冲突时暂停；真实后端失败时返回错误，不自动生成模拟文案。

| 平台 | 输出形式 | 默认建议配图 |
| --- | --- | --- |
| 小红书 | 口语化标题、短段落、场景说明、标签及行动引导 | 3–6 张 |
| 公众号 | 标题、导语、分节正文及行动引导 | 2–4 张 |
| 门店朋友圈 | 围绕一个核心卖点的短文案及咨询引导 | 1–3 张 |
| 门店海报 | 主标题、副标题、最多三个卖点及主视觉建议 | 1 张 |

以上为系统策划规则，并非赛事官方字数或图片数量限制。海报交付是文案与主视觉方案，不是已排版的海报图片；当前不承诺自动发布、公众号排版或下载导出。

## 项目结构

```text
.
├── app.py                         # HTTP 服务、静态页面与真实后端桥接
├── ui/                            # 前端页面、样式与交互
├── prompts/system.md              # 团队系统提示词
├── tests/
│   ├── focused-cases-v1-draft.json # 业务测试输入与预期行为，非自动测试报告
│   ├── test_frontend_server.py     # 离线 HTTP 桥接测试
│   └── test_ui.cjs                 # 离线前端契约测试
└── huawei-marketing-agent/
    ├── .env.example                # 配置示例，不包含真实凭证
    ├── config.py
    ├── requirements.txt
    ├── scripts/check_env.py        # 仅检查变量是否存在
    ├── src/
    │   ├── agent.py                # 证据规划、生成及程序检查
    │   ├── knowledge_service.py    # 单一知识来源路由与受控降级
    │   ├── ima_client.py           # 官方脚本的只读调用封装
    │   ├── local_kb_client.py      # 外部本地副本只读检索
    │   ├── llm_client.py           # 模型 API 客户端
    │   └── contracts.py
    └── tests/                     # 后端离线测试
```

`ui/mock.js` 是保留文件，当前正式页面生成路径不使用它回退模拟结果。

## 本地启动

### 1. 获取代码与准备环境

需要 Python（建议 3.11 或更新版本）。在线 ima 调用还需要 Node.js 和对应官方脚本；运行前端契约测试建议使用 Node.js 20 或更新版本。当前 Python 服务和客户端使用标准库，`requirements.txt` 暂无第三方安装项。

```bash
git clone https://github.com/SNheart16/desktop-tutorial.git
cd desktop-tutorial
git switch main
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r huawei-marketing-agent/requirements.txt
```

私有仓库需要先完成 GitHub 身份验证。Windows 可用 `.venv\Scripts\Activate.ps1` 激活环境。

### 2. 配置模型与提示词

程序读取进程环境变量，**不会自动加载 `.env` 文件**。以下示例适用于 macOS／Linux；替换占位内容，在本机设置真实凭证，勿提交到仓库。

```bash
export USE_MOCK=false
export LLM_API_KEY='替换为模型服务密钥'
export LLM_BASE_URL='https://替换为模型服务域名/v1'
export LLM_MODEL='替换为服务支持的模型名称'
export LLM_API_TYPE=chat_completions
```

`LLM_API_TYPE` 支持 `chat_completions`（默认）或 `responses`，取决于服务商接口能力。模型地址必须是 HTTPS，不能包含凭证或查询参数。仓库不固定某一模型，需自行配置兼容服务。

默认加载仓库根目录的 `prompts/system.md`，不依赖启动终端的工作目录。需要替换提示词时：

```bash
export SYSTEM_PROMPT_PATH='/你的绝对路径/system.md'
```

### 3. 选择知识来源

**本地只读副本：**

```bash
export KNOWLEDGE_SOURCE_MODE=local
export LOCAL_KB_PATH='/你的绝对路径/知识库只读副本'
```

副本需来自指定知识库并保留真实来源。当前本地文本检索支持 `.md`、`.markdown`、`.txt`，图片扫描支持 JPG、PNG、WebP；PDF 等原始文件需先准备可核验的文本材料。完整型号应体现在标题、身份字段或独立目录中，避免混合多个型号。

本地图片文件存在不代表已获得可用于页面展示的图片 URL；缺少可确认链接时，结果可能为 `partial`。本地来源始终显示 `live=false`，不宣称在线检索成功。

**在线 ima：**

```bash
export KNOWLEDGE_SOURCE_MODE=ima
export IMA_OPENAPI_CLIENTID='替换为 ima Client ID'
export IMA_OPENAPI_APIKEY='替换为 ima API Key'
```

在线客户端还依赖以下官方脚本，当前仓库未包含该脚本，需按官方分发说明准备：

```text
huawei-marketing-agent/ima-skill/ima-skill/ima_api.cjs
```

确保 `node` 可从 PATH 调用，凭证有指定共享知识库的读取权限，并留意服务额度。客户端仅允许知识库搜索、列表、知识搜索和素材信息等只读接口。

`KNOWLEDGE_SOURCE_MODE=auto` 可启用受控降级：仅在代码识别的额度、不可用或超时情形下改用已配置的本地副本；不将线上部分结果与本地结果拼接，也不通过换源绕过型号歧义或冲突。降级状态通过 `knowledge_source` 展示。

### 4. 启动与访问

在仓库根目录运行：

```bash
python app.py --port 7860
```

打开 <http://127.0.0.1:7860>，填写任务后生成。停止服务使用 `Ctrl+C`。

检查服务是否能够导入后端：

```bash
curl http://127.0.0.1:7860/api/health
```

返回 `backend=true` 只代表后端可导入，不证明凭证有效、知识库可访问或模型调用成功。修改环境变量或提示词路径后重启服务。

可运行以下脚本查看变量是否设置（不会输出变量值；不负责验证凭证有效性）：

```bash
python huawei-marketing-agent/scripts/check_env.py
```

## 使用与接口

1. 输入知识库中可确认的完整型号，选择人群、场景与平台。
2. 输入内容目标；不要把用户填写的价格当成已核实的事实。
3. 生成后查看来源模式、资料引用、图片检查和风险提示。
4. 对文案和配图进行人工终审，再复制发布。

`POST /api/run` 接收以下字符串字段：

```json
{
  "product_query": "替换为知识库可确认的完整型号",
  "audience": "大学新生",
  "scene": "开学季",
  "platform": "小红书",
  "goal": "围绕有资料支持的学习需求组织文案",
  "extra_requirements": "不添加无依据价格或个人体验"
}
```

除 `extra_requirements` 外，其余五项为必填。响应顶层为 `schema_version`、`status`、`status_message`、`knowledge_source`、`scenario`、`evidence`、`content` 和 `checks`。

| 状态 | 含义与前端行为 |
| --- | --- |
| `success` | 完成当前证据范围内的生成和程序检查，发布前仍需人工确认 |
| `partial` | 已生成文案，但图片或非关键资料存在缺口；允许复制并持续显示缺失提示 |
| `needs_input` | 需要补充型号或任务依据，`content=null`，禁止复制最终文案 |
| `conflict` | 相关型号或事实存在冲突，暂停生成并请求人工确认 |
| `error` | 配置、检索、模型或程序检查未完成，禁止复制最终文案 |

图片对象统一位于 `content.images`，通过 `image_id`、`evidence_ids` 与事实关联；`evidence[].media_ids` 不重复保存图片对象。检查结果使用 `pass/warning/fail/unknown`。图片可访问性检查不等同于视觉型号审核。

## 测试

在仓库根目录运行前端服务与页面契约测试：

```bash
python -m unittest discover -s tests -p 'test_*.py' -v
node --test tests/test_prototype.cjs tests/test_ui.cjs
```

在后端目录运行后端测试：

```bash
cd huawei-marketing-agent
python -m unittest discover -s tests -v
```

以上测试使用临时资料、替身客户端或合成响应，不需要真实密钥，也不验证线上服务可用性。业务用例位于 `tests/focused-cases-v1-draft.json`，需绑定真实型号、证据和图片后执行，不能把预期状态视为实际通过结果。

## 已知限制与部署说明

- 系统采用保守的完整原文事实引用及证据编号检查，可能阻断合理改写；程序检查不是独立事实鉴定或法律合规保证。
- 当前不采用商业时效信息作为生成事实；价格／活动推广需要补充经时效核验的依据，不能仅凭提示词放行。
- 线上 ima 受权限、官方脚本与额度影响；本地资料需要另行核实来源、配置与时效。
- 页面中的流程进度是等待后端的交互提示，不代表已取得每个阶段的实时调用日志。
- 服务默认仅监听 `127.0.0.1`，无身份验证，适合本地演示。当前启动命令不能直接作为公网生产部署方案。
- 部署魔搭需另行适配平台启动方式、监听地址和端口，并配置凭证与可用资料；创建空间或上传静态页面不等于真实 Agent 已部署。
- 不提交真实 `.env`、密钥、本地知识库原文或带鉴权参数的素材链接；评审访问私有仓库时需另行安排权限。

团队分工：A 负责知识检索、模型调用与后端；B 负责界面与交互；C 负责系统提示词、业务用例与作品说明。后续以真实运行记录更新能力状态与效果数据。
