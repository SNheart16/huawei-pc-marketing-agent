# 地理信息功能 · 前后端对接说明（契约 v0.1）

> 状态：前端已按 `docs/geo-api-contract-v0.1.json`（后端 A v0.1 草案，OpenAPI 3.1）完成对接。
> 本文是前端实现说明与对齐确认；**字段名以契约原文为准，本文不重新定义**。
> 前端负责人：搜索面板、候选列表、周边分类/半径、地图标记、「围绕这里策划」、聊天页地理上下文卡片。

---

## 1. 四个对齐点（确认）

1. **同一份契约**：前端不修改任何字段名；演示数据严格按契约 Poi / envelope 结构构造（`location.coordinate_system: "GCJ-02"`、`source.provider: "amap"`、`verification_scope: "provider_record_only"` 等字段齐全）。
2. **坐标与单位**：统一 GCJ-02，经纬度字段 `lng` / `lat`，距离单位米（`distance_m` / `radius_m`）。前端只做透传与相对定位，不做坐标转换。
3. **沿用现有聊天任务**：地点进入聊天 = 前端持 `geo_context_id`，经现有 understand / continue 提交：
   ```json
   { "scenario_inputs": { "store": { "geo_context_id": "<服务端返回值>" } } }
   ```
   沿用实际 `task_id` 与最新 revision，不新建任务。
4. **凭证分离**：前端永不接触后端 Web 服务 Key；浏览器侧只使用网页 JS API Key（当前原型未接地图 SDK，用等比示意图替代瓦片，后续接 SDK 时同样只用 JS Key）。

## 2. 三接口的前端调用映射

| 契约接口 | 前端调用时机 | 关键请求参数 |
| --- | --- | --- |
| `GET /api/geo/search` | 周边场景页点「搜索门店」（或重试） | `keyword`、`city`、`page`、`page_size=10` |
| `GET /api/geo/nearby` | 选中门店后，对**每个激活分类各发一次**（category 必填） | `lng`、`lat`、`radius`、`category`、`page`、`page_size=20` |
| `POST /api/geo/context` | 点「围绕这里策划」 | `store_ref:{query_id,poi_id}` + `nearby_refs[]`（≤10，来自各分类结果的 `query_id`+`poi_id`） |

前端实现要点：

- envelope 统一校验：`success !== true || !data` 即视为失败，错误信息取 `error.code` 映射为中文提示。
- **新搜索使旧引用失效**：搜索成功后前端主动清空已选门店/周边/已生成上下文（对应契约 404/410 语义）；半径变更、切换分类、增删周边选择也会使旧 `geo_context_id` 失效（重新点「围绕这里策划」生成新上下文）。
- `nearby` 每个分类独立 loading / 失败 / 重试；单分类失败不阻塞其他分类。
- 「围绕这里策划」已生成且未过期时按钮禁用；过期后显示「地点选择已过期，请重新查询并选择。」（对应 410）。
- 前端在手填流程（无 `geo_context_id`）保留不变，与契约 `clear_fields` 兼容。

## 3. 错误码 → 前端提示映射

| code | 前端提示（摘要） |
| --- | --- |
| `GEO_NOT_CONFIGURED` / `GEO_PROVIDER_AUTH_FAILED` | 地图服务未配置或凭证无效（后端环境变量），可先用演示数据体验 |
| `GEO_RATE_LIMITED` | 地图查询过于频繁，请稍后重试 |
| `GEO_TIMEOUT` | 地图服务请求超时，请重试 |
| `GEO_CONTEXT_EXPIRED` (410) | 地点选择已过期，请重新查询并选择。 |
| 其他 4xx/5xx / 网络异常 | 原始 message 或「地图服务暂时不可用」 |

## 4. 降级矩阵

| 场景 | 前端表现 |
| --- | --- |
| 未搜索门店 | 概念示意图（固定点位）+「搜索并选择门店后，这里按真实距离展示周边分布」 |
| URL 带 `?demo-geo` 或点「使用演示数据」 | 三接口全部走内置合成数据（`geo-query-demo-*` / `geo-context-demo-001`），全程标注「演示模拟数据」 |
| search 失败 | 搜索面板内错误条 + 「重试」 |
| 单分类 nearby 失败 | 该分类错误条 + 「重试」，其他分类不受影响 |
| context 失败（含 410） | 停留在周边场景页，计划块内错误提示，可重新选择后再次生成 |

## 5. 演示数据声明

内置示例（SYNTHETIC_*）全部是**合成数据**，只用于前端先行开发交互，**不代表已接通高德**。真实联调时后端实现三个接口后，前端零改动切换（去掉演示入口即可）。

## 6. 边界声明（按后端要求）

- 地图查到附近学校后，Agent 只能**提议**主题（如校园主题），再由工作人员确认目标受众；
- 前端在任何界面都不展示「学生客流」「购买意愿」等推断结论；来源卡片统一标注 `provider_record_only` 与 limitations；
- `draft.geo.scenarioInputs` 即将来 understand / continue 的提交载荷，已在聊天页卡片中可视化展示，便于联调核对。

## 7. 待联调清单

- [ ] 后端实现 `/api/geo/search`、`/api/geo/nearby`、`/api/geo/context`（含错误 envelope）
- [ ] 聊天服务解析 `scenario_inputs.store.geo_context_id`，将地点带入追问、策略与 handoff
- [ ] 端到端：搜索 → 周边 → 生成上下文 → understand/continue 提交 → Agent 围绕地点继续对话
