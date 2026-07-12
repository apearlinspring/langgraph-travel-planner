# RAG（检索增强生成）Retrieval Evaluation（召回评估）

本报告用于验证本地知识库能否把查询召回到正确的产品样板、知识分类和依据来源；它不连接真实向量库或外部模型。

- version: `rag_retrieval_eval.v1`
- scenarios: `27`
- documents: `26`
- top_k_values: `3, 5`

## Status Semantics（状态语义）

`passed` 表示当前命令在当前本地知识文档和标注场景下通过；`blocked` 表示缺少真实依赖、候选库安全门失败或运行前置条件不足，不能被解释为验收通过。

本离线报告只证明确定性召回评测结果，不代表真实向量库、真实 embedding（嵌入向量）或在线 Agent（智能体）验收已经通过。

## Mixed-corpus Safety Gate（混合库安全门）

公开知识安全需要单独跑 mixed-corpus（公开+内部混合候选库）对抗验收：

```powershell
uv run python scripts\evaluate_rag_retrieval.py --mixed-corpus-safety --top-k 3 --json
```

这条验收不预先删除内部文档候选，而是在排序阶段使用场景的 `expected_visibilities` / `forbidden_*` 元数据提示，并在返回前执行 forbidden-hit 护栏。如果失败，acceptance preflight（验收预检）的 `rag_mixed_corpus_safety` 应进入 `blocked`。

## Summary（汇总）

| strategy | top_k | source recall | category recall | source type recall | visibility recall | hit rate | safety pass | MRR |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| baseline_bm25 | 3 | 96.30% | 98.15% | 100.00% | 100.00% | 100.00% | 100.00% | 0.9630 |
| baseline_bm25 | 5 | 98.15% | 98.15% | 100.00% | 100.00% | 100.00% | 100.00% | 0.9630 |
| metadata_aware_bm25 | 3 | 98.15% | 100.00% | 100.00% | 100.00% | 100.00% | 100.00% | 0.9815 |
| metadata_aware_bm25 | 5 | 100.00% | 100.00% | 100.00% | 100.00% | 100.00% | 100.00% | 0.9815 |

## Metadata-aware Delta（元数据增强差值）

- top_k: `3`
- source_recall_delta: `1.85%`
- category_recall_delta: `1.85%`
- hit_rate_delta: `0.00%`
- mrr_delta: `0.0185`

## Coverage Summary（场景覆盖摘要）

- public_safety_scenarios: `11`
- expected_categories: `destinations=11, pricing=2, products=10, report=1, risk=2, scenic_tickets=1, sop=1`
- tags: `accessible=1, agency_plan=15, beijing=1, boundary=1, budget=1, city_break=1, couple=4, destination=11, family=5, free_planning=11, governance=1, guilin=2, hangzhou=4, internal=16, lodging=2, low_stress=1, metadata=1, nanjing=1, negative_safety=7, pricing=3, products=10, public=11, realistic_sample=1, report=1, risk=2, scenic_tickets=1, senior=2, sop=1, team=1, tibet=1, ticket_price=1, value=1, weak_match=1, xiamen=2, xian=2, xinjiang=1`

## Scenario Details（场景明细）

| scenario | strategy | top_k | source recall | category recall | safety | first relevant rank | top sources |
|---|---|---:|---:|---:|---|---:|---|
| retrieval_public_xian_culture_food | baseline_bm25 | 3 | 100.00% | 100.00% | pass | 1 | data/documents/destinations/nanjing.md<br>data/documents/destinations/xian.md<br>data/documents/destinations/xiamen.md |
| retrieval_public_xian_culture_food | baseline_bm25 | 5 | 100.00% | 100.00% | pass | 1 | data/documents/destinations/nanjing.md<br>data/documents/destinations/xian.md<br>data/documents/destinations/xiamen.md |
| retrieval_public_xian_culture_food | metadata_aware_bm25 | 3 | 100.00% | 100.00% | pass | 1 | data/documents/destinations/xian.md<br>data/documents/destinations/nanjing.md<br>data/documents/destinations/xiamen.md |
| retrieval_public_xian_culture_food | metadata_aware_bm25 | 5 | 100.00% | 100.00% | pass | 1 | data/documents/destinations/xian.md<br>data/documents/destinations/nanjing.md<br>data/documents/destinations/xiamen.md |
| retrieval_public_no_internal_product_leak | baseline_bm25 | 3 | 100.00% | 100.00% | pass | 1 | data/documents/destinations/xian.md<br>data/documents/destinations/hangzhou.md<br>data/documents/destinations/xiamen.md |
| retrieval_public_no_internal_product_leak | baseline_bm25 | 5 | 100.00% | 100.00% | pass | 1 | data/documents/destinations/xian.md<br>data/documents/destinations/hangzhou.md<br>data/documents/destinations/xiamen.md |
| retrieval_public_no_internal_product_leak | metadata_aware_bm25 | 3 | 100.00% | 100.00% | pass | 1 | data/documents/destinations/xian.md<br>data/documents/destinations/xiamen.md<br>data/documents/destinations/hangzhou.md |
| retrieval_public_no_internal_product_leak | metadata_aware_bm25 | 5 | 100.00% | 100.00% | pass | 1 | data/documents/destinations/xian.md<br>data/documents/destinations/xiamen.md<br>data/documents/destinations/hangzhou.md |
| retrieval_public_xian_lodging_no_agency_quote | baseline_bm25 | 3 | 100.00% | 100.00% | pass | 1 | data/documents/destinations/xian.md<br>data/documents/destinations/hangzhou.md<br>data/documents/destinations/xiamen.md |
| retrieval_public_xian_lodging_no_agency_quote | baseline_bm25 | 5 | 100.00% | 100.00% | pass | 1 | data/documents/destinations/xian.md<br>data/documents/destinations/hangzhou.md<br>data/documents/destinations/xiamen.md |
| retrieval_public_xian_lodging_no_agency_quote | metadata_aware_bm25 | 3 | 100.00% | 100.00% | pass | 1 | data/documents/destinations/xian.md<br>data/documents/destinations/hangzhou.md<br>data/documents/destinations/xiamen.md |
| retrieval_public_xian_lodging_no_agency_quote | metadata_aware_bm25 | 5 | 100.00% | 100.00% | pass | 1 | data/documents/destinations/xian.md<br>data/documents/destinations/hangzhou.md<br>data/documents/destinations/xiamen.md |
| retrieval_public_nanjing_culture_food_no_internal | baseline_bm25 | 3 | 100.00% | 100.00% | pass | 1 | data/documents/destinations/nanjing.md<br>data/documents/destinations/hangzhou.md<br>data/documents/destinations/xiamen.md |
| retrieval_public_nanjing_culture_food_no_internal | baseline_bm25 | 5 | 100.00% | 100.00% | pass | 1 | data/documents/destinations/nanjing.md<br>data/documents/destinations/hangzhou.md<br>data/documents/destinations/xiamen.md |
| retrieval_public_nanjing_culture_food_no_internal | metadata_aware_bm25 | 3 | 100.00% | 100.00% | pass | 1 | data/documents/destinations/nanjing.md<br>data/documents/destinations/hangzhou.md<br>data/documents/destinations/xiamen.md |
| retrieval_public_nanjing_culture_food_no_internal | metadata_aware_bm25 | 5 | 100.00% | 100.00% | pass | 1 | data/documents/destinations/nanjing.md<br>data/documents/destinations/hangzhou.md<br>data/documents/destinations/xiamen.md |
| retrieval_public_beijing_senior_low_stress | baseline_bm25 | 3 | 100.00% | 100.00% | pass | 1 | data/documents/destinations/beijing.md<br>data/documents/destinations/nanjing.md<br>data/documents/destinations/xiamen.md |
| retrieval_public_beijing_senior_low_stress | baseline_bm25 | 5 | 100.00% | 100.00% | pass | 1 | data/documents/destinations/beijing.md<br>data/documents/destinations/nanjing.md<br>data/documents/destinations/xiamen.md |
| retrieval_public_beijing_senior_low_stress | metadata_aware_bm25 | 3 | 100.00% | 100.00% | pass | 1 | data/documents/destinations/beijing.md<br>data/documents/destinations/nanjing.md<br>data/documents/destinations/xiamen.md |
| retrieval_public_beijing_senior_low_stress | metadata_aware_bm25 | 5 | 100.00% | 100.00% | pass | 1 | data/documents/destinations/beijing.md<br>data/documents/destinations/nanjing.md<br>data/documents/destinations/xiamen.md |
| retrieval_public_hangzhou_west_lake_slow_trip | baseline_bm25 | 3 | 100.00% | 100.00% | pass | 1 | data/documents/destinations/hangzhou.md<br>data/documents/destinations/nanjing.md<br>data/documents/destinations/xiamen.md |
| retrieval_public_hangzhou_west_lake_slow_trip | baseline_bm25 | 5 | 100.00% | 100.00% | pass | 1 | data/documents/destinations/hangzhou.md<br>data/documents/destinations/nanjing.md<br>data/documents/destinations/xiamen.md |
| retrieval_public_hangzhou_west_lake_slow_trip | metadata_aware_bm25 | 3 | 100.00% | 100.00% | pass | 1 | data/documents/destinations/hangzhou.md<br>data/documents/destinations/nanjing.md<br>data/documents/destinations/xiamen.md |
| retrieval_public_hangzhou_west_lake_slow_trip | metadata_aware_bm25 | 5 | 100.00% | 100.00% | pass | 1 | data/documents/destinations/hangzhou.md<br>data/documents/destinations/nanjing.md<br>data/documents/destinations/xiamen.md |
| retrieval_public_hangzhou_no_internal_quote | baseline_bm25 | 3 | 100.00% | 100.00% | pass | 1 | data/documents/destinations/hangzhou.md<br>data/documents/destinations/xian.md<br>data/documents/destinations/xiamen.md |
| retrieval_public_hangzhou_no_internal_quote | baseline_bm25 | 5 | 100.00% | 100.00% | pass | 1 | data/documents/destinations/hangzhou.md<br>data/documents/destinations/xian.md<br>data/documents/destinations/xiamen.md |
| retrieval_public_hangzhou_no_internal_quote | metadata_aware_bm25 | 3 | 100.00% | 100.00% | pass | 1 | data/documents/destinations/hangzhou.md<br>data/documents/destinations/xian.md<br>data/documents/destinations/xiamen.md |
| retrieval_public_hangzhou_no_internal_quote | metadata_aware_bm25 | 5 | 100.00% | 100.00% | pass | 1 | data/documents/destinations/hangzhou.md<br>data/documents/destinations/xian.md<br>data/documents/destinations/xiamen.md |
| retrieval_public_xiamen_seaside_couple_trip | baseline_bm25 | 3 | 100.00% | 100.00% | pass | 1 | data/documents/destinations/xiamen.md<br>data/documents/destinations/hangzhou.md<br>data/documents/destinations/guilin.md |
| retrieval_public_xiamen_seaside_couple_trip | baseline_bm25 | 5 | 100.00% | 100.00% | pass | 1 | data/documents/destinations/xiamen.md<br>data/documents/destinations/hangzhou.md<br>data/documents/destinations/guilin.md |
| retrieval_public_xiamen_seaside_couple_trip | metadata_aware_bm25 | 3 | 100.00% | 100.00% | pass | 1 | data/documents/destinations/xiamen.md<br>data/documents/destinations/hangzhou.md<br>data/documents/destinations/xian.md |
| retrieval_public_xiamen_seaside_couple_trip | metadata_aware_bm25 | 5 | 100.00% | 100.00% | pass | 1 | data/documents/destinations/xiamen.md<br>data/documents/destinations/hangzhou.md<br>data/documents/destinations/xian.md |
| retrieval_public_xiamen_no_internal_product | baseline_bm25 | 3 | 100.00% | 100.00% | pass | 1 | data/documents/destinations/xiamen.md<br>data/documents/destinations/hangzhou.md<br>data/documents/destinations/xian.md |
| retrieval_public_xiamen_no_internal_product | baseline_bm25 | 5 | 100.00% | 100.00% | pass | 1 | data/documents/destinations/xiamen.md<br>data/documents/destinations/hangzhou.md<br>data/documents/destinations/xian.md |
| retrieval_public_xiamen_no_internal_product | metadata_aware_bm25 | 3 | 100.00% | 100.00% | pass | 1 | data/documents/destinations/xiamen.md<br>data/documents/destinations/xian.md<br>data/documents/destinations/hangzhou.md |
| retrieval_public_xiamen_no_internal_product | metadata_aware_bm25 | 5 | 100.00% | 100.00% | pass | 1 | data/documents/destinations/xiamen.md<br>data/documents/destinations/xian.md<br>data/documents/destinations/hangzhou.md |
| retrieval_public_guilin_landscape_family_trip | baseline_bm25 | 3 | 100.00% | 100.00% | pass | 1 | data/documents/destinations/guilin.md<br>data/documents/destinations/hangzhou.md<br>data/documents/destinations/nanjing.md |
| retrieval_public_guilin_landscape_family_trip | baseline_bm25 | 5 | 100.00% | 100.00% | pass | 1 | data/documents/destinations/guilin.md<br>data/documents/destinations/hangzhou.md<br>data/documents/destinations/nanjing.md |
| retrieval_public_guilin_landscape_family_trip | metadata_aware_bm25 | 3 | 100.00% | 100.00% | pass | 1 | data/documents/destinations/guilin.md<br>data/documents/destinations/hangzhou.md<br>data/documents/destinations/nanjing.md |
| retrieval_public_guilin_landscape_family_trip | metadata_aware_bm25 | 5 | 100.00% | 100.00% | pass | 1 | data/documents/destinations/guilin.md<br>data/documents/destinations/hangzhou.md<br>data/documents/destinations/nanjing.md |
| retrieval_public_guilin_no_internal_optimizer | baseline_bm25 | 3 | 100.00% | 100.00% | pass | 1 | data/documents/destinations/guilin.md<br>data/documents/destinations/xian.md<br>data/documents/destinations/hangzhou.md |
| retrieval_public_guilin_no_internal_optimizer | baseline_bm25 | 5 | 100.00% | 100.00% | pass | 1 | data/documents/destinations/guilin.md<br>data/documents/destinations/xian.md<br>data/documents/destinations/hangzhou.md |
| retrieval_public_guilin_no_internal_optimizer | metadata_aware_bm25 | 3 | 100.00% | 100.00% | pass | 1 | data/documents/destinations/guilin.md<br>data/documents/destinations/xian.md<br>data/documents/destinations/hangzhou.md |
| retrieval_public_guilin_no_internal_optimizer | metadata_aware_bm25 | 5 | 100.00% | 100.00% | pass | 1 | data/documents/destinations/guilin.md<br>data/documents/destinations/xian.md<br>data/documents/destinations/hangzhou.md |
| retrieval_product_family_low_stress | baseline_bm25 | 3 | 50.00% | 100.00% | pass | 1 | data/documents/internal/products/route_templates.md<br>data/documents/internal/products/xian_family_light_custom.md<br>data/documents/internal/risk/real_world_compliance_risk_rules.md |
| retrieval_product_family_low_stress | baseline_bm25 | 5 | 100.00% | 100.00% | pass | 1 | data/documents/internal/products/route_templates.md<br>data/documents/internal/products/xian_family_light_custom.md<br>data/documents/internal/risk/real_world_compliance_risk_rules.md |
| retrieval_product_family_low_stress | metadata_aware_bm25 | 3 | 50.00% | 100.00% | pass | 1 | data/documents/internal/products/route_templates.md<br>data/documents/internal/products/xian_family_light_custom.md<br>data/documents/internal/products/suzhou_senior_slow_custom.md |
| retrieval_product_family_low_stress | metadata_aware_bm25 | 5 | 100.00% | 100.00% | pass | 1 | data/documents/internal/products/route_templates.md<br>data/documents/internal/products/xian_family_light_custom.md<br>data/documents/internal/products/suzhou_senior_slow_custom.md |
| retrieval_product_senior_accessible | baseline_bm25 | 3 | 100.00% | 100.00% | pass | 1 | data/documents/internal/products/route_templates.md<br>data/documents/internal/products/suzhou_senior_slow_custom.md<br>data/documents/internal/products/xian_family_light_custom.md |
| retrieval_product_senior_accessible | baseline_bm25 | 5 | 100.00% | 100.00% | pass | 1 | data/documents/internal/products/route_templates.md<br>data/documents/internal/products/suzhou_senior_slow_custom.md<br>data/documents/internal/products/xian_family_light_custom.md |
| retrieval_product_senior_accessible | metadata_aware_bm25 | 3 | 100.00% | 100.00% | pass | 1 | data/documents/internal/products/suzhou_senior_slow_custom.md<br>data/documents/internal/products/route_templates.md<br>data/documents/internal/products/xian_family_light_custom.md |
| retrieval_product_senior_accessible | metadata_aware_bm25 | 5 | 100.00% | 100.00% | pass | 1 | data/documents/internal/products/suzhou_senior_slow_custom.md<br>data/documents/internal/products/route_templates.md<br>data/documents/internal/products/xian_family_light_custom.md |
| retrieval_product_xian_family_catalog_fields | baseline_bm25 | 3 | 100.00% | 100.00% | pass | 1 | data/documents/internal/products/xian_family_light_custom.md<br>data/documents/internal/products/route_templates.md<br>data/documents/internal/products/xiamen_couple_relaxed.md |
| retrieval_product_xian_family_catalog_fields | baseline_bm25 | 5 | 100.00% | 100.00% | pass | 1 | data/documents/internal/products/xian_family_light_custom.md<br>data/documents/internal/products/route_templates.md<br>data/documents/internal/products/xiamen_couple_relaxed.md |
| retrieval_product_xian_family_catalog_fields | metadata_aware_bm25 | 3 | 100.00% | 100.00% | pass | 1 | data/documents/internal/products/xian_family_light_custom.md<br>data/documents/internal/risk/real_world_compliance_risk_rules.md<br>data/documents/internal/sop/real_world_consultant_sop.md |
| retrieval_product_xian_family_catalog_fields | metadata_aware_bm25 | 5 | 100.00% | 100.00% | pass | 1 | data/documents/internal/products/xian_family_light_custom.md<br>data/documents/internal/risk/real_world_compliance_risk_rules.md<br>data/documents/internal/sop/real_world_consultant_sop.md |
| retrieval_product_team_budget_transparency | baseline_bm25 | 3 | 100.00% | 100.00% | pass | 1 | data/documents/internal/products/changsha_team_budget_transparency.md<br>data/documents/internal/products/route_templates.md<br>data/documents/internal/pricing/real_world_pricing_and_contract_rules.md |
| retrieval_product_team_budget_transparency | baseline_bm25 | 5 | 100.00% | 100.00% | pass | 1 | data/documents/internal/products/changsha_team_budget_transparency.md<br>data/documents/internal/products/route_templates.md<br>data/documents/internal/pricing/real_world_pricing_and_contract_rules.md |
| retrieval_product_team_budget_transparency | metadata_aware_bm25 | 3 | 100.00% | 100.00% | pass | 1 | data/documents/internal/products/changsha_team_budget_transparency.md<br>data/documents/internal/pricing/real_world_pricing_and_contract_rules.md<br>data/documents/internal/pricing/pricing_rules.md |
| retrieval_product_team_budget_transparency | metadata_aware_bm25 | 5 | 100.00% | 100.00% | pass | 1 | data/documents/internal/products/changsha_team_budget_transparency.md<br>data/documents/internal/pricing/real_world_pricing_and_contract_rules.md<br>data/documents/internal/pricing/pricing_rules.md |
| retrieval_product_couple_relaxed | baseline_bm25 | 3 | 100.00% | 100.00% | pass | 1 | data/documents/internal/products/xiamen_couple_relaxed.md<br>data/documents/internal/products/route_templates.md<br>data/documents/internal/products/yunnan_couple_family_6d.md |
| retrieval_product_couple_relaxed | baseline_bm25 | 5 | 100.00% | 100.00% | pass | 1 | data/documents/internal/products/xiamen_couple_relaxed.md<br>data/documents/internal/products/route_templates.md<br>data/documents/internal/products/yunnan_couple_family_6d.md |
| retrieval_product_couple_relaxed | metadata_aware_bm25 | 3 | 100.00% | 100.00% | pass | 1 | data/documents/internal/products/xiamen_couple_relaxed.md<br>data/documents/internal/pricing/pricing_rules.md<br>data/documents/internal/sop/real_world_consultant_sop.md |
| retrieval_product_couple_relaxed | metadata_aware_bm25 | 5 | 100.00% | 100.00% | pass | 1 | data/documents/internal/products/xiamen_couple_relaxed.md<br>data/documents/internal/pricing/pricing_rules.md<br>data/documents/internal/sop/real_world_consultant_sop.md |
| retrieval_product_xinjiang_destination_only | baseline_bm25 | 3 | 100.00% | 100.00% | pass | 1 | data/documents/internal/products/xinjiang_private_group_8d.md<br>data/documents/internal/products/route_templates.md<br>data/documents/internal/products/real_world_product_patterns.md |
| retrieval_product_xinjiang_destination_only | baseline_bm25 | 5 | 100.00% | 100.00% | pass | 1 | data/documents/internal/products/xinjiang_private_group_8d.md<br>data/documents/internal/products/route_templates.md<br>data/documents/internal/products/real_world_product_patterns.md |
| retrieval_product_xinjiang_destination_only | metadata_aware_bm25 | 3 | 100.00% | 100.00% | pass | 1 | data/documents/internal/products/xinjiang_private_group_8d.md<br>data/documents/internal/pricing/pricing_rules.md<br>data/documents/internal/risk/real_world_compliance_risk_rules.md |
| retrieval_product_xinjiang_destination_only | metadata_aware_bm25 | 5 | 100.00% | 100.00% | pass | 1 | data/documents/internal/products/xinjiang_private_group_8d.md<br>data/documents/internal/pricing/pricing_rules.md<br>data/documents/internal/risk/real_world_compliance_risk_rules.md |
| retrieval_product_tibet_budgeted_couple | baseline_bm25 | 3 | 100.00% | 100.00% | pass | 1 | data/documents/internal/products/route_templates.md<br>data/documents/internal/products/tibet_couple_light_custom_7d.md<br>data/documents/internal/scenic_tickets/scenic_ticket_reference.md |
| retrieval_product_tibet_budgeted_couple | baseline_bm25 | 5 | 100.00% | 100.00% | pass | 1 | data/documents/internal/products/route_templates.md<br>data/documents/internal/products/tibet_couple_light_custom_7d.md<br>data/documents/internal/scenic_tickets/scenic_ticket_reference.md |
| retrieval_product_tibet_budgeted_couple | metadata_aware_bm25 | 3 | 100.00% | 100.00% | pass | 1 | data/documents/internal/products/tibet_couple_light_custom_7d.md<br>data/documents/internal/scenic_tickets/scenic_ticket_reference.md<br>data/documents/internal/sop/real_world_consultant_sop.md |
| retrieval_product_tibet_budgeted_couple | metadata_aware_bm25 | 5 | 100.00% | 100.00% | pass | 1 | data/documents/internal/products/tibet_couple_light_custom_7d.md<br>data/documents/internal/scenic_tickets/scenic_ticket_reference.md<br>data/documents/internal/sop/real_world_consultant_sop.md |
| retrieval_product_xian_family_value | baseline_bm25 | 3 | 100.00% | 100.00% | pass | 1 | data/documents/internal/products/route_templates.md<br>data/documents/internal/products/xian_family_light_custom.md<br>data/documents/internal/products/yunnan_couple_family_6d.md |
| retrieval_product_xian_family_value | baseline_bm25 | 5 | 100.00% | 100.00% | pass | 1 | data/documents/internal/products/route_templates.md<br>data/documents/internal/products/xian_family_light_custom.md<br>data/documents/internal/products/yunnan_couple_family_6d.md |
| retrieval_product_xian_family_value | metadata_aware_bm25 | 3 | 100.00% | 100.00% | pass | 1 | data/documents/internal/products/xian_family_light_custom.md<br>data/documents/internal/risk/real_world_compliance_risk_rules.md<br>data/documents/internal/risk/risk_playbook.md |
| retrieval_product_xian_family_value | metadata_aware_bm25 | 5 | 100.00% | 100.00% | pass | 1 | data/documents/internal/products/xian_family_light_custom.md<br>data/documents/internal/risk/real_world_compliance_risk_rules.md<br>data/documents/internal/risk/risk_playbook.md |
| retrieval_product_xian_to_hangzhou_5d_budget | baseline_bm25 | 3 | 100.00% | 100.00% | pass | 1 | data/documents/internal/products/xian_to_hangzhou_5d_agency_sample.md<br>data/documents/internal/products/route_templates.md<br>data/documents/internal/products/xian_family_light_custom.md |
| retrieval_product_xian_to_hangzhou_5d_budget | baseline_bm25 | 5 | 100.00% | 100.00% | pass | 1 | data/documents/internal/products/xian_to_hangzhou_5d_agency_sample.md<br>data/documents/internal/products/route_templates.md<br>data/documents/internal/products/xian_family_light_custom.md |
| retrieval_product_xian_to_hangzhou_5d_budget | metadata_aware_bm25 | 3 | 100.00% | 100.00% | pass | 1 | data/documents/internal/products/xian_to_hangzhou_5d_agency_sample.md<br>data/documents/internal/products/xian_family_light_custom.md<br>data/documents/internal/pricing/real_world_pricing_and_contract_rules.md |
| retrieval_product_xian_to_hangzhou_5d_budget | metadata_aware_bm25 | 5 | 100.00% | 100.00% | pass | 1 | data/documents/internal/products/xian_to_hangzhou_5d_agency_sample.md<br>data/documents/internal/products/xian_family_light_custom.md<br>data/documents/internal/pricing/real_world_pricing_and_contract_rules.md |
| retrieval_scenic_ticket_hangzhou_references | baseline_bm25 | 3 | 100.00% | 100.00% | pass | 2 | data/documents/internal/products/xian_to_hangzhou_5d_agency_sample.md<br>data/documents/internal/scenic_tickets/scenic_ticket_reference.md<br>data/documents/internal/products/real_world_product_patterns.md |
| retrieval_scenic_ticket_hangzhou_references | baseline_bm25 | 5 | 100.00% | 100.00% | pass | 2 | data/documents/internal/products/xian_to_hangzhou_5d_agency_sample.md<br>data/documents/internal/scenic_tickets/scenic_ticket_reference.md<br>data/documents/internal/products/real_world_product_patterns.md |
| retrieval_scenic_ticket_hangzhou_references | metadata_aware_bm25 | 3 | 100.00% | 100.00% | pass | 2 | data/documents/internal/products/xian_to_hangzhou_5d_agency_sample.md<br>data/documents/internal/scenic_tickets/scenic_ticket_reference.md<br>data/documents/internal/pricing/pricing_rules.md |
| retrieval_scenic_ticket_hangzhou_references | metadata_aware_bm25 | 5 | 100.00% | 100.00% | pass | 2 | data/documents/internal/products/xian_to_hangzhou_5d_agency_sample.md<br>data/documents/internal/scenic_tickets/scenic_ticket_reference.md<br>data/documents/internal/pricing/pricing_rules.md |
| retrieval_product_free_planning_boundary | baseline_bm25 | 3 | 100.00% | 100.00% | pass | 1 | data/documents/internal/products/guilin_free_planning_optimizer.md<br>data/documents/internal/products/route_templates.md<br>data/documents/internal/products/changsha_team_budget_transparency.md |
| retrieval_product_free_planning_boundary | baseline_bm25 | 5 | 100.00% | 100.00% | pass | 1 | data/documents/internal/products/guilin_free_planning_optimizer.md<br>data/documents/internal/products/route_templates.md<br>data/documents/internal/products/changsha_team_budget_transparency.md |
| retrieval_product_free_planning_boundary | metadata_aware_bm25 | 3 | 100.00% | 100.00% | pass | 1 | data/documents/internal/products/guilin_free_planning_optimizer.md<br>data/documents/internal/pricing/pricing_rules.md<br>data/documents/internal/scenic_tickets/scenic_ticket_reference.md |
| retrieval_product_free_planning_boundary | metadata_aware_bm25 | 5 | 100.00% | 100.00% | pass | 1 | data/documents/internal/products/guilin_free_planning_optimizer.md<br>data/documents/internal/pricing/pricing_rules.md<br>data/documents/internal/scenic_tickets/scenic_ticket_reference.md |
| retrieval_pricing_inclusions_exclusions | baseline_bm25 | 3 | 100.00% | 100.00% | pass | 1 | data/documents/internal/pricing/real_world_pricing_and_contract_rules.md<br>data/documents/internal/pricing/pricing_rules.md<br>data/documents/internal/report/report_standard.md |
| retrieval_pricing_inclusions_exclusions | baseline_bm25 | 5 | 100.00% | 100.00% | pass | 1 | data/documents/internal/pricing/real_world_pricing_and_contract_rules.md<br>data/documents/internal/pricing/pricing_rules.md<br>data/documents/internal/report/report_standard.md |
| retrieval_pricing_inclusions_exclusions | metadata_aware_bm25 | 3 | 100.00% | 100.00% | pass | 1 | data/documents/internal/pricing/pricing_rules.md<br>data/documents/internal/pricing/real_world_pricing_and_contract_rules.md<br>data/documents/internal/report/report_standard.md |
| retrieval_pricing_inclusions_exclusions | metadata_aware_bm25 | 5 | 100.00% | 100.00% | pass | 1 | data/documents/internal/pricing/pricing_rules.md<br>data/documents/internal/pricing/real_world_pricing_and_contract_rules.md<br>data/documents/internal/report/report_standard.md |
| retrieval_sop_consultant_flow | baseline_bm25 | 3 | 100.00% | 100.00% | pass | 1 | data/documents/internal/sop/real_world_consultant_sop.md<br>data/documents/internal/sop/service_sop.md<br>data/documents/internal/report/report_standard.md |
| retrieval_sop_consultant_flow | baseline_bm25 | 5 | 100.00% | 100.00% | pass | 1 | data/documents/internal/sop/real_world_consultant_sop.md<br>data/documents/internal/sop/service_sop.md<br>data/documents/internal/report/report_standard.md |
| retrieval_sop_consultant_flow | metadata_aware_bm25 | 3 | 100.00% | 100.00% | pass | 1 | data/documents/internal/sop/real_world_consultant_sop.md<br>data/documents/internal/sop/service_sop.md<br>data/documents/internal/report/report_standard.md |
| retrieval_sop_consultant_flow | metadata_aware_bm25 | 5 | 100.00% | 100.00% | pass | 1 | data/documents/internal/sop/real_world_consultant_sop.md<br>data/documents/internal/sop/service_sop.md<br>data/documents/internal/report/report_standard.md |
| retrieval_risk_weather_elderly | baseline_bm25 | 3 | 100.00% | 100.00% | pass | 1 | data/documents/internal/risk/risk_playbook.md<br>data/documents/internal/risk/real_world_compliance_risk_rules.md<br>data/documents/internal/pricing/pricing_rules.md |
| retrieval_risk_weather_elderly | baseline_bm25 | 5 | 100.00% | 100.00% | pass | 1 | data/documents/internal/risk/risk_playbook.md<br>data/documents/internal/risk/real_world_compliance_risk_rules.md<br>data/documents/internal/pricing/pricing_rules.md |
| retrieval_risk_weather_elderly | metadata_aware_bm25 | 3 | 100.00% | 100.00% | pass | 1 | data/documents/internal/risk/real_world_compliance_risk_rules.md<br>data/documents/internal/risk/risk_playbook.md<br>data/documents/internal/products/tibet_couple_light_custom_7d.md |
| retrieval_risk_weather_elderly | metadata_aware_bm25 | 5 | 100.00% | 100.00% | pass | 1 | data/documents/internal/risk/real_world_compliance_risk_rules.md<br>data/documents/internal/risk/risk_playbook.md<br>data/documents/internal/products/tibet_couple_light_custom_7d.md |
| retrieval_report_delivery_contract | baseline_bm25 | 3 | 100.00% | 100.00% | pass | 1 | data/documents/internal/report/real_world_report_delivery_patterns.md<br>data/documents/internal/report/report_standard.md<br>data/documents/internal/sop/service_sop.md |
| retrieval_report_delivery_contract | baseline_bm25 | 5 | 100.00% | 100.00% | pass | 1 | data/documents/internal/report/real_world_report_delivery_patterns.md<br>data/documents/internal/report/report_standard.md<br>data/documents/internal/sop/service_sop.md |
| retrieval_report_delivery_contract | metadata_aware_bm25 | 3 | 100.00% | 100.00% | pass | 1 | data/documents/internal/report/real_world_report_delivery_patterns.md<br>data/documents/internal/report/report_standard.md<br>data/documents/internal/pricing/pricing_rules.md |
| retrieval_report_delivery_contract | metadata_aware_bm25 | 5 | 100.00% | 100.00% | pass | 1 | data/documents/internal/report/real_world_report_delivery_patterns.md<br>data/documents/internal/report/report_standard.md<br>data/documents/internal/pricing/pricing_rules.md |
| retrieval_contract_no_locked_price | baseline_bm25 | 3 | 50.00% | 50.00% | pass | 2 | data/documents/internal/products/route_templates.md<br>data/documents/internal/risk/real_world_compliance_risk_rules.md<br>data/documents/internal/products/xian_to_hangzhou_5d_agency_sample.md |
| retrieval_contract_no_locked_price | baseline_bm25 | 5 | 50.00% | 50.00% | pass | 2 | data/documents/internal/products/route_templates.md<br>data/documents/internal/risk/real_world_compliance_risk_rules.md<br>data/documents/internal/products/xian_to_hangzhou_5d_agency_sample.md |
| retrieval_contract_no_locked_price | metadata_aware_bm25 | 3 | 100.00% | 100.00% | pass | 1 | data/documents/internal/pricing/pricing_rules.md<br>data/documents/internal/risk/real_world_compliance_risk_rules.md<br>data/documents/internal/products/route_templates.md |
| retrieval_contract_no_locked_price | metadata_aware_bm25 | 5 | 100.00% | 100.00% | pass | 1 | data/documents/internal/pricing/pricing_rules.md<br>data/documents/internal/risk/real_world_compliance_risk_rules.md<br>data/documents/internal/products/route_templates.md |
