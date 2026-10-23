# 卡片引导与结构化场景：前端交接

本轮只扩展后端契约，没有修改 UI，也没有完成新版前端联调。接口保留现有 envelope、`questions: string[]`、`understanding` 与 `interpretation` 字段。

兼容性只读检查了 `origin/feat/task-b-content-delivery`（B 交付提交 `462530a`）：其 `ui/content-workbench.js` 从策略对象调用 `/api/content/*`，`content_b` 请求以 `task_id`、`confirmed`、`platform`、`strategy`、`product_context` 为主；`ui/prototype.js` 未发现 `question_cards`、`card_answers` 或 `scenario_inputs`。因此本轮 A API 向后兼容旧客户端，但尚未完成 B 工作台对结构化场景的字段映射或端到端联调。不要把本说明理解为 B 已合并到 A 分支。

## 接口与字段

- `POST /api/agent/understand` 可选接收 `scenario_inputs`。
- `POST /api/agent/continue` 可选接收 `scenario_inputs`、`card_answers`；原有 `task_id`、`expected_revision`、`user_input`、`updates`、`clear_fields` 保持兼容。
- 卡片响应位于 `data.understanding.question_cards` 或 `data.interpretation.question_cards`。`task.question_cards` 是当前任务快照中的服务端状态。
- 场景快照位于 `task.scenario_inputs`。`time`、`store`、`usage` 各自保留值、状态、来源和 `unverified` 标记。

## 提交与恢复

1. 创建任务后保存真实返回的 `task_id` 和 `task.revision`，并渲染 `understanding.questions` / `question_cards`。
2. 选择卡片时，仅把服务端返回的 `question_id` 与一个或多个 `option_id` 发入 `card_answers`；单选只能一个，多选至少一个。可同时提交补充自由文本。
3. 自由编辑结构化场景时可用 `scenario_inputs` 原始输入字段；清空用白名单 `clear_fields`。不要发送客户端自设的来源或核验状态。
4. 每次成功继续对话后，用响应中的最新 `task.revision` 替换本地版本，并用新响应覆盖卡片列表。不要自行递增 revision 或复用旧卡片。
5. `409 VERSION_CONFLICT` 或 `409 QUESTION_CARD_STALE` 时读取 `GET /api/tasks/{task_id}` 或错误快照，展示最新状态后让用户重新选择；不要自动重放旧卡片答案。`409 INPUT_CONFLICT` 表示同一场景字段同时以卡片和结构化字段修改/清空，请保留用户意图后选一种输入重发。
6. `INVALID_CARD_ANSWER`、`INVALID_REQUEST` 显示安全错误，不更新前端任务快照。请求期间显示等待状态并禁用重复提交；模型失败时使用错误/恢复字段中的最新任务版本。

自由文本可与卡片答案同轮提交。明确改口必须以本轮文本为依据，由需求理解结果更新对应场景值；服务端会丢弃无原文依据的模型建议。若语义抽取未得到预期结果，保留用户原文，用最新版本再提交明确的 `scenario_inputs` 更新。

## 场景语义

`scene` 是既有营销场景，不等同于 `scenario_inputs.usage.text`。后者描述顾客实际使用电脑的场景；`time` 是推广时间背景，`store` 是用户输入的门店位置/附近地标。未提交字段保留；数组更新替换旧数组；清空会写入 `cleared`。场景变更使当前策略和确认失效，但不单独删除仍适用的产品事实。

时间、地点、地标和使用场景的来源标记由服务端管理，状态为 `unverified`。不得把用户输入展示成地图、距离、周边设施或客流核实结果。卡片选项是用户的需求/策划方向，不是产品能力证明。

请求与响应示例见 `docs/examples/guided-*.json`；字段、错误及版本语义见 `docs/agent-api-v2.md`。示例 ID 与版本全部是占位值。策略/检索/handoff 后续接入及新版 UI 均未在本轮真实联调。
