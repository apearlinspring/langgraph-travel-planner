# RAG（检索增强生成）Retrieval Evaluation（召回评估）

本报告用于验证本地知识库能否把查询召回到正确的产品样板、知识分类和依据来源；它不连接真实向量库或外部模型。

- version: `rag_retrieval_eval.v1`
- scenarios: `15`
- documents: `19`
- top_k_values: `3, 5`

## Summary（汇总）

| strategy | top_k | source recall | category recall | source type recall | hit rate | MRR |
|---|---:|---:|---:|---:|---:|---:|
| baseline_bm25 | 3 | 86.67% | 90.00% | 93.33% | 93.33% | 0.9333 |
| baseline_bm25 | 5 | 90.00% | 90.00% | 93.33% | 93.33% | 0.9333 |
| metadata_aware_bm25 | 3 | 90.00% | 93.33% | 93.33% | 93.33% | 0.9333 |
| metadata_aware_bm25 | 5 | 100.00% | 100.00% | 100.00% | 100.00% | 0.9500 |

## Metadata-aware Delta（元数据增强差值）

- top_k: `3`
- source_recall_delta: `3.33%`
- category_recall_delta: `3.33%`
- hit_rate_delta: `0.00%`
- mrr_delta: `0.0000`

## Scenario Details（场景明细）

| scenario | strategy | top_k | source recall | category recall | first relevant rank | top sources |
|---|---|---:|---:|---:|---:|---|
| retrieval_public_xian_culture_food | baseline_bm25 | 3 | 0.00% | 0.00% |  | data/documents/internal/products/xian_family_light_custom.md<br>data/documents/internal/pricing/pricing_rules.md<br>data/documents/internal/products/xinjiang_private_group_8d.md |
| retrieval_public_xian_culture_food | baseline_bm25 | 5 | 0.00% | 0.00% |  | data/documents/internal/products/xian_family_light_custom.md<br>data/documents/internal/pricing/pricing_rules.md<br>data/documents/internal/products/xinjiang_private_group_8d.md |
| retrieval_public_xian_culture_food | metadata_aware_bm25 | 3 | 0.00% | 0.00% |  | data/documents/internal/products/xian_family_light_custom.md<br>data/documents/internal/pricing/pricing_rules.md<br>data/documents/internal/products/xinjiang_private_group_8d.md |
| retrieval_public_xian_culture_food | metadata_aware_bm25 | 5 | 100.00% | 100.00% | 4 | data/documents/internal/products/xian_family_light_custom.md<br>data/documents/internal/pricing/pricing_rules.md<br>data/documents/internal/products/xinjiang_private_group_8d.md |
| retrieval_product_family_low_stress | baseline_bm25 | 3 | 50.00% | 100.00% | 1 | data/documents/internal/products/route_templates.md<br>data/documents/internal/products/xian_family_light_custom.md<br>data/documents/internal/products/suzhou_senior_slow_custom.md |
| retrieval_product_family_low_stress | baseline_bm25 | 5 | 100.00% | 100.00% | 1 | data/documents/internal/products/route_templates.md<br>data/documents/internal/products/xian_family_light_custom.md<br>data/documents/internal/products/suzhou_senior_slow_custom.md |
| retrieval_product_family_low_stress | metadata_aware_bm25 | 3 | 50.00% | 100.00% | 1 | data/documents/internal/products/route_templates.md<br>data/documents/internal/products/xian_family_light_custom.md<br>data/documents/internal/products/suzhou_senior_slow_custom.md |
| retrieval_product_family_low_stress | metadata_aware_bm25 | 5 | 100.00% | 100.00% | 1 | data/documents/internal/products/route_templates.md<br>data/documents/internal/products/xian_family_light_custom.md<br>data/documents/internal/products/suzhou_senior_slow_custom.md |
| retrieval_product_senior_accessible | baseline_bm25 | 3 | 100.00% | 100.00% | 1 | data/documents/internal/products/route_templates.md<br>data/documents/internal/products/suzhou_senior_slow_custom.md<br>data/documents/internal/products/xian_family_light_custom.md |
| retrieval_product_senior_accessible | baseline_bm25 | 5 | 100.00% | 100.00% | 1 | data/documents/internal/products/route_templates.md<br>data/documents/internal/products/suzhou_senior_slow_custom.md<br>data/documents/internal/products/xian_family_light_custom.md |
| retrieval_product_senior_accessible | metadata_aware_bm25 | 3 | 100.00% | 100.00% | 1 | data/documents/internal/products/suzhou_senior_slow_custom.md<br>data/documents/internal/products/route_templates.md<br>data/documents/internal/products/xian_family_light_custom.md |
| retrieval_product_senior_accessible | metadata_aware_bm25 | 5 | 100.00% | 100.00% | 1 | data/documents/internal/products/suzhou_senior_slow_custom.md<br>data/documents/internal/products/route_templates.md<br>data/documents/internal/products/xian_family_light_custom.md |
| retrieval_product_xian_family_catalog_fields | baseline_bm25 | 3 | 100.00% | 100.00% | 1 | data/documents/internal/products/xian_family_light_custom.md<br>data/documents/internal/products/route_templates.md<br>data/documents/internal/products/xiamen_couple_relaxed.md |
| retrieval_product_xian_family_catalog_fields | baseline_bm25 | 5 | 100.00% | 100.00% | 1 | data/documents/internal/products/xian_family_light_custom.md<br>data/documents/internal/products/route_templates.md<br>data/documents/internal/products/xiamen_couple_relaxed.md |
| retrieval_product_xian_family_catalog_fields | metadata_aware_bm25 | 3 | 100.00% | 100.00% | 1 | data/documents/internal/products/xian_family_light_custom.md<br>data/documents/internal/products/route_templates.md<br>data/documents/internal/products/xiamen_couple_relaxed.md |
| retrieval_product_xian_family_catalog_fields | metadata_aware_bm25 | 5 | 100.00% | 100.00% | 1 | data/documents/internal/products/xian_family_light_custom.md<br>data/documents/internal/products/route_templates.md<br>data/documents/internal/products/xiamen_couple_relaxed.md |
| retrieval_product_team_budget_transparency | baseline_bm25 | 3 | 100.00% | 100.00% | 1 | data/documents/internal/products/changsha_team_budget_transparency.md<br>data/documents/internal/products/route_templates.md<br>data/documents/internal/pricing/real_world_pricing_and_contract_rules.md |
| retrieval_product_team_budget_transparency | baseline_bm25 | 5 | 100.00% | 100.00% | 1 | data/documents/internal/products/changsha_team_budget_transparency.md<br>data/documents/internal/products/route_templates.md<br>data/documents/internal/pricing/real_world_pricing_and_contract_rules.md |
| retrieval_product_team_budget_transparency | metadata_aware_bm25 | 3 | 100.00% | 100.00% | 1 | data/documents/internal/products/changsha_team_budget_transparency.md<br>data/documents/internal/products/route_templates.md<br>data/documents/internal/pricing/real_world_pricing_and_contract_rules.md |
| retrieval_product_team_budget_transparency | metadata_aware_bm25 | 5 | 100.00% | 100.00% | 1 | data/documents/internal/products/changsha_team_budget_transparency.md<br>data/documents/internal/products/route_templates.md<br>data/documents/internal/pricing/real_world_pricing_and_contract_rules.md |
| retrieval_product_couple_relaxed | baseline_bm25 | 3 | 100.00% | 100.00% | 1 | data/documents/internal/products/xiamen_couple_relaxed.md<br>data/documents/internal/products/route_templates.md<br>data/documents/internal/products/yunnan_couple_family_6d.md |
| retrieval_product_couple_relaxed | baseline_bm25 | 5 | 100.00% | 100.00% | 1 | data/documents/internal/products/xiamen_couple_relaxed.md<br>data/documents/internal/products/route_templates.md<br>data/documents/internal/products/yunnan_couple_family_6d.md |
| retrieval_product_couple_relaxed | metadata_aware_bm25 | 3 | 100.00% | 100.00% | 1 | data/documents/internal/products/xiamen_couple_relaxed.md<br>data/documents/internal/products/route_templates.md<br>data/documents/internal/products/yunnan_couple_family_6d.md |
| retrieval_product_couple_relaxed | metadata_aware_bm25 | 5 | 100.00% | 100.00% | 1 | data/documents/internal/products/xiamen_couple_relaxed.md<br>data/documents/internal/products/route_templates.md<br>data/documents/internal/products/yunnan_couple_family_6d.md |
| retrieval_product_xinjiang_destination_only | baseline_bm25 | 3 | 100.00% | 100.00% | 1 | data/documents/internal/products/xinjiang_private_group_8d.md<br>data/documents/internal/products/real_world_product_patterns.md<br>data/documents/internal/products/route_templates.md |
| retrieval_product_xinjiang_destination_only | baseline_bm25 | 5 | 100.00% | 100.00% | 1 | data/documents/internal/products/xinjiang_private_group_8d.md<br>data/documents/internal/products/real_world_product_patterns.md<br>data/documents/internal/products/route_templates.md |
| retrieval_product_xinjiang_destination_only | metadata_aware_bm25 | 3 | 100.00% | 100.00% | 1 | data/documents/internal/products/xinjiang_private_group_8d.md<br>data/documents/internal/products/real_world_product_patterns.md<br>data/documents/internal/products/route_templates.md |
| retrieval_product_xinjiang_destination_only | metadata_aware_bm25 | 5 | 100.00% | 100.00% | 1 | data/documents/internal/products/xinjiang_private_group_8d.md<br>data/documents/internal/products/real_world_product_patterns.md<br>data/documents/internal/products/route_templates.md |
| retrieval_product_tibet_budgeted_couple | baseline_bm25 | 3 | 100.00% | 100.00% | 1 | data/documents/internal/products/route_templates.md<br>data/documents/internal/products/tibet_couple_light_custom_7d.md<br>data/documents/internal/products/guilin_free_planning_optimizer.md |
| retrieval_product_tibet_budgeted_couple | baseline_bm25 | 5 | 100.00% | 100.00% | 1 | data/documents/internal/products/route_templates.md<br>data/documents/internal/products/tibet_couple_light_custom_7d.md<br>data/documents/internal/products/guilin_free_planning_optimizer.md |
| retrieval_product_tibet_budgeted_couple | metadata_aware_bm25 | 3 | 100.00% | 100.00% | 1 | data/documents/internal/products/route_templates.md<br>data/documents/internal/products/tibet_couple_light_custom_7d.md<br>data/documents/internal/products/guilin_free_planning_optimizer.md |
| retrieval_product_tibet_budgeted_couple | metadata_aware_bm25 | 5 | 100.00% | 100.00% | 1 | data/documents/internal/products/route_templates.md<br>data/documents/internal/products/tibet_couple_light_custom_7d.md<br>data/documents/internal/products/guilin_free_planning_optimizer.md |
| retrieval_product_xian_family_value | baseline_bm25 | 3 | 100.00% | 100.00% | 1 | data/documents/internal/products/route_templates.md<br>data/documents/internal/products/xian_family_light_custom.md<br>data/documents/destinations/xian.md |
| retrieval_product_xian_family_value | baseline_bm25 | 5 | 100.00% | 100.00% | 1 | data/documents/internal/products/route_templates.md<br>data/documents/internal/products/xian_family_light_custom.md<br>data/documents/destinations/xian.md |
| retrieval_product_xian_family_value | metadata_aware_bm25 | 3 | 100.00% | 100.00% | 1 | data/documents/internal/products/xian_family_light_custom.md<br>data/documents/destinations/xian.md<br>data/documents/internal/products/route_templates.md |
| retrieval_product_xian_family_value | metadata_aware_bm25 | 5 | 100.00% | 100.00% | 1 | data/documents/internal/products/xian_family_light_custom.md<br>data/documents/destinations/xian.md<br>data/documents/internal/products/route_templates.md |
| retrieval_product_free_planning_boundary | baseline_bm25 | 3 | 100.00% | 100.00% | 1 | data/documents/internal/products/guilin_free_planning_optimizer.md<br>data/documents/internal/products/route_templates.md<br>data/documents/internal/products/changsha_team_budget_transparency.md |
| retrieval_product_free_planning_boundary | baseline_bm25 | 5 | 100.00% | 100.00% | 1 | data/documents/internal/products/guilin_free_planning_optimizer.md<br>data/documents/internal/products/route_templates.md<br>data/documents/internal/products/changsha_team_budget_transparency.md |
| retrieval_product_free_planning_boundary | metadata_aware_bm25 | 3 | 100.00% | 100.00% | 1 | data/documents/internal/products/guilin_free_planning_optimizer.md<br>data/documents/internal/products/route_templates.md<br>data/documents/internal/products/changsha_team_budget_transparency.md |
| retrieval_product_free_planning_boundary | metadata_aware_bm25 | 5 | 100.00% | 100.00% | 1 | data/documents/internal/products/guilin_free_planning_optimizer.md<br>data/documents/internal/products/route_templates.md<br>data/documents/internal/products/changsha_team_budget_transparency.md |
| retrieval_pricing_inclusions_exclusions | baseline_bm25 | 3 | 100.00% | 100.00% | 1 | data/documents/internal/pricing/real_world_pricing_and_contract_rules.md<br>data/documents/internal/pricing/pricing_rules.md<br>data/documents/internal/report/report_standard.md |
| retrieval_pricing_inclusions_exclusions | baseline_bm25 | 5 | 100.00% | 100.00% | 1 | data/documents/internal/pricing/real_world_pricing_and_contract_rules.md<br>data/documents/internal/pricing/pricing_rules.md<br>data/documents/internal/report/report_standard.md |
| retrieval_pricing_inclusions_exclusions | metadata_aware_bm25 | 3 | 100.00% | 100.00% | 1 | data/documents/internal/pricing/real_world_pricing_and_contract_rules.md<br>data/documents/internal/pricing/pricing_rules.md<br>data/documents/internal/report/report_standard.md |
| retrieval_pricing_inclusions_exclusions | metadata_aware_bm25 | 5 | 100.00% | 100.00% | 1 | data/documents/internal/pricing/real_world_pricing_and_contract_rules.md<br>data/documents/internal/pricing/pricing_rules.md<br>data/documents/internal/report/report_standard.md |
| retrieval_sop_consultant_flow | baseline_bm25 | 3 | 100.00% | 100.00% | 1 | data/documents/internal/sop/real_world_consultant_sop.md<br>data/documents/internal/sop/service_sop.md<br>data/documents/internal/report/report_standard.md |
| retrieval_sop_consultant_flow | baseline_bm25 | 5 | 100.00% | 100.00% | 1 | data/documents/internal/sop/real_world_consultant_sop.md<br>data/documents/internal/sop/service_sop.md<br>data/documents/internal/report/report_standard.md |
| retrieval_sop_consultant_flow | metadata_aware_bm25 | 3 | 100.00% | 100.00% | 1 | data/documents/internal/sop/real_world_consultant_sop.md<br>data/documents/internal/sop/service_sop.md<br>data/documents/internal/report/report_standard.md |
| retrieval_sop_consultant_flow | metadata_aware_bm25 | 5 | 100.00% | 100.00% | 1 | data/documents/internal/sop/real_world_consultant_sop.md<br>data/documents/internal/sop/service_sop.md<br>data/documents/internal/report/report_standard.md |
| retrieval_risk_weather_elderly | baseline_bm25 | 3 | 100.00% | 100.00% | 1 | data/documents/internal/risk/risk_playbook.md<br>data/documents/internal/risk/real_world_compliance_risk_rules.md<br>data/documents/internal/pricing/pricing_rules.md |
| retrieval_risk_weather_elderly | baseline_bm25 | 5 | 100.00% | 100.00% | 1 | data/documents/internal/risk/risk_playbook.md<br>data/documents/internal/risk/real_world_compliance_risk_rules.md<br>data/documents/internal/pricing/pricing_rules.md |
| retrieval_risk_weather_elderly | metadata_aware_bm25 | 3 | 100.00% | 100.00% | 1 | data/documents/internal/risk/real_world_compliance_risk_rules.md<br>data/documents/internal/risk/risk_playbook.md<br>data/documents/internal/sop/real_world_consultant_sop.md |
| retrieval_risk_weather_elderly | metadata_aware_bm25 | 5 | 100.00% | 100.00% | 1 | data/documents/internal/risk/real_world_compliance_risk_rules.md<br>data/documents/internal/risk/risk_playbook.md<br>data/documents/internal/sop/real_world_consultant_sop.md |
| retrieval_report_delivery_contract | baseline_bm25 | 3 | 100.00% | 100.00% | 1 | data/documents/internal/report/report_standard.md<br>data/documents/internal/report/real_world_report_delivery_patterns.md<br>data/documents/internal/sop/service_sop.md |
| retrieval_report_delivery_contract | baseline_bm25 | 5 | 100.00% | 100.00% | 1 | data/documents/internal/report/report_standard.md<br>data/documents/internal/report/real_world_report_delivery_patterns.md<br>data/documents/internal/sop/service_sop.md |
| retrieval_report_delivery_contract | metadata_aware_bm25 | 3 | 100.00% | 100.00% | 1 | data/documents/internal/report/real_world_report_delivery_patterns.md<br>data/documents/internal/report/report_standard.md<br>data/documents/internal/pricing/pricing_rules.md |
| retrieval_report_delivery_contract | metadata_aware_bm25 | 5 | 100.00% | 100.00% | 1 | data/documents/internal/report/real_world_report_delivery_patterns.md<br>data/documents/internal/report/report_standard.md<br>data/documents/internal/pricing/pricing_rules.md |
| retrieval_contract_no_locked_price | baseline_bm25 | 3 | 50.00% | 50.00% | 1 | data/documents/internal/risk/real_world_compliance_risk_rules.md<br>data/documents/internal/products/xian_family_light_custom.md<br>data/documents/internal/report/report_standard.md |
| retrieval_contract_no_locked_price | baseline_bm25 | 5 | 50.00% | 50.00% | 1 | data/documents/internal/risk/real_world_compliance_risk_rules.md<br>data/documents/internal/products/xian_family_light_custom.md<br>data/documents/internal/report/report_standard.md |
| retrieval_contract_no_locked_price | metadata_aware_bm25 | 3 | 100.00% | 100.00% | 1 | data/documents/internal/pricing/pricing_rules.md<br>data/documents/internal/risk/real_world_compliance_risk_rules.md<br>data/documents/internal/report/report_standard.md |
| retrieval_contract_no_locked_price | metadata_aware_bm25 | 5 | 100.00% | 100.00% | 1 | data/documents/internal/pricing/pricing_rules.md<br>data/documents/internal/risk/real_world_compliance_risk_rules.md<br>data/documents/internal/report/report_standard.md |
