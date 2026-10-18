# 华为 PC 营销图文 Agent

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
node --test tests/test_ui.cjs
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
