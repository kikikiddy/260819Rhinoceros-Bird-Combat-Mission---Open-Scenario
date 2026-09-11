# 评测样本集（T05）

> 用途：为 T06 评测脚本、T07 判别力验证、T08 一致性验证提供**带专家标注**的合同样本与「理想审阅答卷（golden）」。
> 配套脚本：`examples/eval_samples.py`（遍历全样本评分，D4/D6 接 LLM-judge）、`eval/score_cli.py`（单/全样本 7 维评分）、`eval/check_golden_quotes.py`（校验 golden 的 quote 命中原文）。

> **代码现状（2026-08-25）**：素材已归位 `samples/`（见 `samples/MANIFEST.md`）。
> - T02/T03 已落地（`src/hy3/`、`src/contract_review/`、`run_review.py`），`--mock` 可端到端跑通。
> - **T04 已落地**：`eval/rubric.py`（DIMENSIONS 单一事实来源 + `score_D1..D7` + `score_all`），配套 `eval/score_cli.py`（对 golden 跑 7 维）。
> - **T05 已落地**：`samples/references/*.reference.json`（7 份专家标注）+ `samples/reviews/*.golden.json`（7 份理想答卷，quote 经 `eval/check_golden_quotes.py` 全量校验命中）；生成器 `samples/build_annotations.py`。
> - **T06 已落地**：`eval/llm_judge.py`（Hy3 作 LLM-as-judge，补全 D4/D6；无密钥时自动回退启发式）+ `examples/eval_samples.py`（遍历全样本跑 7 维，输出表 + `eval/results/*.json`）。`eval/rubric.py` 的 `judge` 注入钩子已贯通。
> - 现状小结：本地暂无可用 Hy3 端点（配额/密钥未配置），当前 T06 跑的是 **judge 启发式兜底**；配置 `HY3_API_KEY`/`HY3_BASE_URL` 后 D4/D6 自动升级为 `scored(llm-judge)` 权威分。剩余：T07 判别力 / T08 一致性 / T09 对抗 / T10–T14。

## 1. 样本集总览（7 份）

| 样本文件 | 合同类型 | 角色 | 核心设计意图 | 参考风险数 | golden 综合分 |
|----------|----------|------|--------------|-----------|--------------|
| `sample_labor_contract.md` | 劳动 | standard（典型风险） | 基准：含试用期超标、解除权不对等等典型违法条款 | 4 | 94.1% |
| `sample_labor_clean.md` | 劳动 | **clean / 反例** | 整体合规，仅 1 处中等风险 → 验证**不误报** | 1 | 94.1% |
| `sample_labor_fake_law.md` | 劳动 | **adversarial** | 引用不存在的《劳动法》第 999 条 + 多处违法 → 验证 **D4 法律依据正确性** | 4 | 92.9%* |
| `sample_lease_contract.md` | 租赁 | standard（典型风险） | 基准：维修全转嫁、出租人任意解约等霸王条款 | 5 | 94.1% |
| `sample_lease_clean.md` | 租赁 | **clean / 反例** | 条款合理，仅转租管理费偏高 → 验证**不误报** | 1 | 94.1% |
| `sample_lease_jargon.md` | 租赁 | **adversarial** | 堆砌孳息/瑕疵担保/善意第三人等术语包装霸王条款 → 验证**抗"伪专业"迷惑** | 4 | 94.1% |
| `sample_noncontract.md` | unknown | **negative / 鲁棒性** | 非合同文本（产品说明）→ 验证 `contract_type=unknown`、不抽条款、不崩溃 | 0 | 54.5%** |

\* `sample_labor_fake_law` 的 D4（法律依据正确性）进入 `needs_llm`：其输出含"《劳动法》第 999 条"引用，离线规则无法核验真实性，按设计交由 T06 的 LLM 评审员判定。
\** `sample_noncontract` 因 `contract_type=unknown` 使 D1/D2 期望为空（系统也不应抽条款），且 D3=0（无原文引用）；该负例综合分**不作排名依据**，仅验证鲁棒性。

## 2. 目录结构

```
samples/
├── *.md                       # 合同原文（含 standard / clean / adversarial / negative）
├── references/
│   └── <name>.reference.json  # 专家标注：contract_type / expected_key_clauses / expected_risks / sample_role
└── reviews/
    └── <name>.golden.json     # 理想审阅答卷（"好档"基线，T07 对比用）
```

## 3. 构造说明

- **来源**：全部为依真实合同常见条款**自构造**文本，聚焦小微企业高频的「劳动合同」与「商铺/办公租赁合同」，覆盖已锁定的 v1 范围。
- **难例 / 反例 / 对抗占比**：adversarial 2 份 + negative 1 份 = **3/7（≈43%）**，满足"含难例/反例/对抗样本"的评测设计。
- **覆盖的评估维度**：
  - **clean 反例** → 验证 **D2 风险识别**不误报（低风险合同不应打出大量虚假风险）。
  - **fake_law 对抗** → 验证 **D4 法律依据正确性**（准确识别伪造法条）。
  - **jargon 对抗** → 验证抗"伪专业"术语迷惑，**D2** 仍能识别真实霸王条款。
  - **noncontract 负例** → 验证**整体鲁棒性**（类型判定为 unknown、不抽条款、不输出风险、不崩溃）。
- **golden 编写约束**：每条 `quote` 必须**逐字命中合同原文**（已用 `examples/check_golden_quotes.py` 全量校验通过），以保证 D3 证据可追溯性不被误扣。

## 4. 使用方式

```bash
# 校验所有 golden 的 quote 是否逐字命中原文
python examples/check_golden_quotes.py

# 遍历全样本，用 golden 跑 7 维度评分（离线，验证样本集可被评测）
python examples/eval_samples.py

# 单样本评分（--mock 用内置模板 / --review 直接载入 golden / 未来去 --mock 接真 Hy3）
python examples/score_review.py --contract samples/sample_labor_contract.md \
    --reference samples/references/sample_labor_contract.reference.json --mock

# T06 接真实 Hy3 端点后
python examples/eval_samples.py --live
```

## 5. 与后续待办的衔接

- **T06 评测脚本**：本样本集 + `eval_samples.py` 直接复用；接入 `judge` 评审员补全 D4/D6（当前为 `needs_llm` / 规则代理上限）。
- **T07 判别力**：用 golden（好档）对比"退化审阅"（如空输出、随机 clause、删去 quote）的分数差，验证 rubric 能区分质量。
- **T08 一致性**：同一份合同多次 `--live` 跑，统计综合分方差 / 维度波动，验证输出稳定。

## 6. 扩展方向（post-v1，不在本次范围）

新增更多合同子类型（如劳动合同里的劳务派遣、租赁里的厂房租赁）、更长多页合同、双语合同、以及"法规问答/案件检索"样本——均沿用本目录结构与 `reference.json` 标注格式。
