# API v2 示例说明

本目录均为可解析的契约示例，不是当前模型或知识库的完整实际响应；请求中的任务 ID、版本和事实引用必须替换成当前任务实际返回的值。

| 文件 | 用途 | 是否是真实调用结果 |
| --- | --- | --- |
| `understand-request.json` | 前端创建需求理解任务 | 否，示例请求 |
| `understand-response.json` | 前端适配需求摘要和任务快照 | 否，成功路径的结构示例；需求理解已接入真实模型 |
| `continue-request.json` | 使用 task_id/revision 继续需求理解 | 否，示例请求 |
| `guided-understand-request.json` | 首轮提交基础需求与时间、门店场景输入 | 否，契约请求示例 |
| `guided-card-response.json` | 卡片问题及服务端任务快照 | 否，契约响应示例；question/option ID 和 revision 均为占位，不是真实调用结果 |
| `guided-card-continue-request.json` | 提交卡片选择并用自由文本补充 | 否，契约请求示例 |
| `guided-free-edit-continue-request.json` | 用自由文本修改平台与实际使用场景 | 否，契约请求示例 |
| `guided-clear-continue-request.json` | 显式清空门店位置字段 | 否，契约请求示例 |
| `guided-ready-response.json` | 信息充分且不再追问的响应 | 否，契约响应示例；ID 和 revision 为占位 |
| `research-request.json` | 显式触发产品只读检索 | 否，示例请求 |
| `research-response.json` | 检索结果、来源、事实记录和下一步 | 否，合成型号、合成证据与来源的结构示例；检索服务已实现 |
| `facts-check-request.json` | 对当前候选或改写陈述发起生成前事实核查 | 否，合成任务和事实 ID 的请求示例 |
| `facts-check-response.json` | 逐项结论、来源限制和可用事实白名单 | 否，合成证据的结构示例；生成前核查已实现 |
| `strategy-generate-request.json` | 使用当前任务版本生成一个策略 | 否，示例请求 |
| `strategy-generate-response.json` | 待确认策略及策略表达逐项核查 | 否，合成结构示例；真实策略生成与全文核查已实现 |
| `strategy-confirm-request.json` | 绑定当前任务版本、策略 ID 和版本确认 | 否，示例请求 |
| `strategy-confirm-response.json` | 服务端确认状态与最新任务版本 | 否，合成结构示例；确认服务已实现 |
| `strategy-handoff-request.json` | 确认后读取当前图文交接 | 否，示例请求 |
| `creative-handoff.json` | `/api/strategy/handoff` 返回的已确认策略、采用事实与来源限制 | 否，合成结构示例；交接与最终核查已实现，图文生成模块尚未接入 |
| `final-check-request.json` | 绑定当前确认策略并提交完整成稿 | 否，合成文字与事实 ID 的核查请求 |
| `final-check-response.json` | 文字 passed、图片 unknown、整体 partial 的分层结论 | 否，合成结构示例；独立最终核查已实现，不代表图文模块生成结果 |

不得将 `creative-handoff.json` 中的 `supported` fixture 当作真实核查结果。实际检索取得的记录为 `retrieved` 或 `stale`，不会因为模型判断或知识库标题中写了“已确认”就升级为核验通过。

真实两步 HTTP 演示（在仓库根目录显式运行）：

```powershell
python -B huawei-marketing-agent/scripts/product_research_http_demo.py --live --source-mode local
```

脚本只展示实际请求与响应节选，不将真实原文、图片或完整检索结果写入本目录。没有 `--live` 时不会调用模型或知识库。前端同学使用前三份示例、research、facts/check、strategy/generate 和 strategy/confirm 请求/响应；图文同学使用 `strategy-handoff-request.json`、`creative-handoff.json` 和 FactRecord，必须在真实策略明确确认后读取交接，不得消费未确认策略或 fixture。

真实三步核查演示：

```powershell
python -B huawei-marketing-agent/scripts/facts_check_http_demo.py --live --source-mode local
```

同一任务使用本轮实际 revision；核查只引用服务端已检索证据。示例响应中出现 supported 只是结构演示，真实策略应读取当前有效检查的 `eligible_fact_ids`，不能采信前端手填状态。

完整真实策略与确认演示：

```powershell
python -B huawei-marketing-agent/scripts/strategy_http_demo.py --live --source-mode local
```

示例版本从 facts/check 的 revision=5 开始，生成后为 6、确认后为 7。真实调用不可写死这些数字。交接中的图片状态为 `unknown`，不代表已有可用图片。

最终核查验收使用 `python -B huawei-marketing-agent/scripts/strategy_http_demo.py --live --source-mode local --keep-server-on-failure --check-final`。脚本从真实 handoff 手工构造“核查验收输入”，验证忠实事实、篡改数值/无依据优惠、图片 unknown 与旧结果失效；不代表图文生成模块已完成。前端接入最终结果分层展示需要 final-check 请求/响应；图文同学先读取真实 handoff，再按 final-check 请求提交完整成稿。

所有示例 ID 都是占位：每步必须读取实际返回的当前任务版本和策略版本。真实验收结果仅在 [交付说明](../agent-core-a-handoff.md) 中汇总范围，不在本目录保存真实请求响应转储或可复用的旧内存任务。

卡片与结构化场景的前端接入步骤见 [卡片引导交接说明](../card-guidance-frontend-handoff.md)。上述新增示例是可解析的契约示例，不是本轮真实模型响应或新版 UI 联调结果。
