# 中小企业合同审阅助手 V1（基于 Hy3 大模型）

> 犀牛鸟开源 · 混元大语言模型项目 · 实战任务一（开放式场景：AI 应用与评判标准设计）
> 个人 / 活动作品，**非腾讯官方发布**。

基于腾讯混元大模型 `tencent/hy3-preview` 的中小企业合同审阅助手，聚焦**劳动合同**与**商铺/办公租赁合同**两类场景，自动抽取关键条款、标注风险、给出法条依据与可操作修改建议，并配套一套自研的 7 维评估体系验证其有效性。

---

## 1. 目录结构

```
src/hy3/            Hy3 OpenAI 兼容客户端（重试/限流/日志，密钥走环境变量）
src/contract_review/ 审阅核心链路（prompt → 解析 → 结构化结果）
eval/rubric.py      7 维评估 rubric（D1–D7，单一事实来源）
eval/llm_judge.py   LLM-as-judge（裁判与被评解耦，D4/D6 评分）
examples/           评测脚本：eval_samples / discriminability(T07) / consistency(T08) / adversarial(T09)
samples/            评测样本集（含 golden 标注、reference、live 缓存、adversarial 对抗样本）
demo_04/            T12 交互式演示 v4（server.py 后端 + 前端，可输入任意合同实时评测）
demo_05/            T12 交互式演示 v5（带审阅结果磁盘缓存，warmup.py 预热后点击示例即时出结果）
T07_判别力验证.md / T08_一致性验证.md / T09_对抗验证.md / T10_评测报告.md / T11_分析报告.md
```

## 2. 环境要求

- Python ≥ 3.10
- 依赖：`pip install -r requirements.txt`（含 `openai`、`python-dotenv`）

## 3. 快速开始

### 3.1 配置密钥（不硬编码）

```bash
cp .env.example .env      # 然后填入真实 HY3_API_KEY / JUDGE_API_KEY
```

密钥仅来自环境变量 / `.env`，**切勿提交 `.env`**。

### 3.2 运行审阅

```bash
# 无端点时：mock 模式端到端验证链路（默认）
python run_review.py --input samples/sample_labor_contract.md --mock

# 接真实 Hy3：输出结构化 JSON
python run_review.py --input samples/sample_labor_contract.md --live

# 直接传文本，输出 Markdown
python run_review.py --text "甲方...乙方...试用期肆个月..." --live --format markdown
```

## 4. 评测复现（7 维 rubric）

```bash
python examples/eval_samples.py --all --review-source live            # 完整 7 维（缓存）
python examples/eval_samples.py --all --review-source live --no-judge # 免费 5 维
python examples/discriminability.py   # T07 判别力（零 token）
python examples/consistency.py        # T08 一致性
python examples/adversarial.py --name adv_fake_law  # T09 对抗（每样本 1 次调用）

# T12 交互式演示（demo_05：带审阅结果缓存，演示时点击示例即时出结果）
python demo_05/warmup.py     # 可选但推荐：预先跑出全部示例的审阅缓存（约 5 分钟）
python demo_05/server.py     # 默认 http://127.0.0.1:8005，浏览器输入合同实时评测
```

> 演示小贴士：先跑 `warmup.py` 预热，再启动 `server.py`。命中缓存的请求 0.1 秒返回且不重复消耗 token；
> 未预热的新文本按实际模型生成速度返回（关闭上游思考链后约 10~60 秒，由 `HY3_DISABLE_THINKING` 控制）。

## 5. 评估体系（7 维 rubric）

| 维度 | 名称 | 评分方式 |
|---|---|---|
| D1 | 条款抽取准确性 | 规则：对照 reference 关键词命中 |
| D2 | 风险识别正确性 | 规则：召回 + 误报惩罚 |
| D3 | 证据可追溯性 | 规则：quote 逐字命中原文 ≥90% |
| D4 | 法律依据正确性 | LLM-judge（glm-5.3）+ 人工核验 + 启发式兜底 |
| D5 | 安全合规性 | 规则：免责声明存在性 |
| D6 | 用户可理解性 | LLM-judge（glm-5.3） |
| D7 | 格式规范性 | 规则：JSON 结构/字段/枚举校验 |

设计要点：**评测者与被评者解耦**（裁判 `glm-5.3` ≠ 被评 `hy3-preview`）、**双重缓存**（live 审阅 + judge 结果）使重复评测零 token。

## 6. 评测结论速览

- Live 平均综合分 **71.9%**（排除非合同负例后 79.4%），Golden 基线 90.3%。
- 租赁场景达 **100%**；劳动场景受「过度识别风险」与「伪造法条失效」拖累。
- 评测体系可靠：判别力（T07）✓、确定性（T08）✓、对抗鲁棒性（T09）✓。
- 详见 `T10_评测报告.md` 与 `T11_分析报告.md`。

## 7. 合规声明

本仓库为**个人学习 / 活动作品**，与腾讯公司无隶属关系，不代表腾讯官方立场或产品。AI 审阅结果**仅供参考，不构成法律意见**，重要合同须由执业律师最终把关。请勿将 API Key 提交至版本库。

---

*任务系列：T01 场景论证 → T02 调用骨架 → T03 审阅链路 → T04 rubric → T05 样本集 → T06 评测脚本 → T07 判别力 → T08 一致性 → T09 对抗 → T10 完整评测 → T11 分析报告 → T12 Demo → T13 仓库润色 → T14 Roadmap。*
