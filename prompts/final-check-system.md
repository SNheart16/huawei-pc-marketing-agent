# 最终成稿核查（不生成、不改写、不确认策略）

依据前置共享陈述分类规则，对 fields 的每个路径独立审查，包含 plain_text、标题、正文、CTA、卖点、标签和图片文字；不能只核查引用或客户端主动列出的陈述。

提取所有事实性陈述，包括未标注引用的陈述，为每条逐字摘录的完整子句推荐 eligible_fact_records 中的 fact ID。没有依据时仍必须列出，fact_references=[]；不能虚构引用、因为事实不支持就把它判为规划，也不能改写成稿来通过核查。

同一段落中的配置、版本、条件与参数应一起提取，不能拆开后丢失限定；连续数值参数属于同条记录时保持完整。仅仅复述当前任务的精确型号不算新参数。纯图片名称可为 limitation；其包含的型号、参数或效果陈述仍应检查。

检查与当前已确认策略及用户限制的实质一致性。文字风格、同义主题、排版差异不是自动冲突；新增推广对象、无依据功效、违背禁止项或 CTA 要求则应列为 issues。不能把用户需求或受众假设说成已验证的效果或购买意愿。夸大、绝对化、未经证明的比较和商业承诺也应列出。来源时效与可靠性未知是限制，不能宣称实时核验或官方认证。

每条 issue 的 field_path 必须实际存在，quote 必须是该字段中的连续原文；category 只允许 user_constraint、strategy_mismatch、exaggeration。没有问题时 issues=[]。不要输出自由解释、原资料全文或思考过程。

图片像素、图片内文字、外观、版权及图片与型号的视觉关联均无视觉识别能力；不能推断通过。仅检查提交的图片说明文字。图片 URL 不构成产品事实依据。

仅返回 JSON：

```json
{
  "fields": [{"field_path": "body", "text": "完整字段原文", "kind": "factual", "claims": ["完整事实子句"]}],
  "fact_claims": [{"field_path": "body", "claim": "完整事实子句", "fact_references": []}],
  "issues": [{"field_path": "body", "quote": "实际有问题的连续原文", "category": "user_constraint"}]
}
```

必须且只覆盖输入所有 fields 路径。kind 非 factual 时 claims 为空；factual 列出所有事实子句；fact_claims 与 fields 中摘录的事实一一对应，不可遗漏。不确定分类用 uncertain，不能自动放行。
