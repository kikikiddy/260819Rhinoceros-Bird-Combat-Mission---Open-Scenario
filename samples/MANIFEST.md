# 样本集清单（T05 规划落地 · 与 SAMPLES.md 对齐）

> 本目录即 `SAMPLES.md` 规划的 `samples/` 样本集。本文档为**素材盘点**，确认 7 份 `sample_*.md` 已就位；`references/` 与 `reviews/` 为 T05 待补交付。
> 素材均为自构造文本，聚焦 v1 锁定的「劳动合同 + 商铺/办公租赁合同」。

## 1. 素材盘点（已就位）

| 文件 | 合同类型 | 角色 | 设计意图 | 参考风险数 | 覆盖评估维度 |
|------|----------|------|----------|-----------|--------------|
| `sample_labor_contract.md` | 劳动 | standard（典型风险） | 基准：试用期超标、解除权不对等、畸高违约金 | 4 | 全部 7 维 |
| `sample_labor_clean.md` | 劳动 | **clean / 反例** | 整体合规，仅 1 处中等风险 → 验证 **D2 不误报** | 1 | D2 为主 |
| `sample_labor_fake_law.md` | 劳动 | **adversarial** | 引用不存在的《劳动法》第 999 条 + 多处违法 → 验证 **D4 法律依据正确性** | 4 | D4 为主 |
| `sample_lease_contract.md` | 租赁 | standard（典型风险） | 基准：维修全转嫁、出租人任意解约等霸王条款 | 4–5 | 全部 7 维 |
| `sample_lease_clean.md` | 租赁 | **clean / 反例** | 条款合理，仅转租管理费偏高 → 验证 **D2 不误报** | 1 | D2 为主 |
| `sample_lease_jargon.md` | 租赁 | **adversarial** | 堆砌孳息/瑕疵担保/善意第三人等术语包装霸王条款 → 验证抗"伪专业"迷惑 | 4 | D2 为主 |
| `sample_noncontract.md` | unknown | **negative / 鲁棒性** | 非合同文本（产品说明）→ 验证 `contract_type=unknown`、不抽条款、不崩溃 | 0 | D1/D2 期望为空 |

**对齐结论**：经逐份核对，素材内容与 `SAMPLES.md` 第 1 节描述**完全一致**（类型、角色、风险数、对抗意图均吻合）。难例/反例/对抗占比 = 3/7（≈43%），满足"含难例/反例/对抗样本"要求。

## 2. 目录结构

```
samples/
├── sample_*.md                 # 合同原文（已就位 ✅）
├── references/                 # 专家标注（T05 已建 ✅）
│   └── <name>.reference.json   # contract_type / expected_key_clauses / expected_risks / sample_role
├── reviews/                    # 理想审阅答卷 golden（T05 已建 ✅）
│   └── <name>.golden.json      # "好档"基线（T07 判别力对比用），quote 逐字命中原文
├── build_annotations.py        # T05 标注生成器（可复现）
└── MANIFEST.md                 # 本文档
```

## 3. 与后续待办的衔接

- **T04 评估维度 rubric**：维度定义见 `METHODOLOGY.md` / `eval/rubric.py`（**已建**），`eval/score_cli.py` 可对 golden 跑 7 维。
- **T05 评测样本集**：`references/*.reference.json` 与 `reviews/*.golden.json` 已补全（**已建**）；`golden` 中每条 `quote` 经 `eval/check_golden_quotes.py` 全量校验命中。
- **T06 评测脚本**：复用本目录 + `eval/` 评分逻辑，一键对样本集出分（D4/D6 接 LLM-as-judge，注入 `score_all(judge=...)`）。
- **T07 判别力**：用 `golden`（好档）对比"退化审阅"（空输出/删 quote）验证分数单调可分。
- **T08 一致性**：同一份合同多次 `--live` 跑，统计综合分方差。

## 4. 快速验证（T03 链路版）

素材已可被审阅链路直接消费，无需 Hy3 端点即可端到端演示：

```bash
python run_review.py --input samples/sample_labor_contract.md --mock --format json
python run_review.py --input samples/sample_noncontract.md   --mock --format json   # 应得 unknown + 空条款/风险
```
