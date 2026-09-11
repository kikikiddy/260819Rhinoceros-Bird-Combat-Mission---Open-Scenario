"""生成 T05 专家标注：samples/references/*.reference.json 与 samples/reviews/*.golden.json。

所有 golden 中 risk.quote 均逐字摘自对应合同原文（由 eval/check_golden_quotes.py 校验）。
运行：python samples/build_annotations.py
"""

from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent
REF_DIR = ROOT / "references"
GOLDEN_DIR = ROOT / "reviews"
REF_DIR.mkdir(exist_ok=True)
GOLDEN_DIR.mkdir(exist_ok=True)

DISCLAIMER = "本结果由 AI 辅助生成，仅供参考，不构成法律意见，建议由执业律师最终把关。"

# ---------------------------------------------------------------------------
# 1) 劳动合同（典型风险）
# ---------------------------------------------------------------------------
REF_LABOR_CONTRACT = {
    "contract_type": "labor",
    "sample_role": "standard",
    "expected_key_clauses": [
        {"name": "合同期限与试用期", "keywords": ["试用期", "贰年"]},
        {"name": "工作内容与地点", "keywords": ["工作地点", "单方调整"]},
        {"name": "劳动报酬", "keywords": ["月工资", "6000"]},
        {"name": "社会保险", "keywords": ["社会保险"]},
        {"name": "劳动合同解除", "keywords": ["解除", "经济补偿"]},
        {"name": "违约责任", "keywords": ["违约金", "50万元"]},
        {"name": "争议解决", "keywords": ["争议", "法院"]},
    ],
    "expected_risks": [
        {"topic": "试用期超过法定上限", "level": "高", "keywords": ["试用期为肆个月"]},
        {"topic": "用人单位单方任意解除且免补偿", "level": "高", "keywords": ["随时解除劳动合同", "无需支付经济补偿"]},
        {"topic": "畸高违约金且甲方免责", "level": "高", "keywords": ["违约金50万元", "甲方违约不承担责任"]},
        {"topic": "工作地点单方调整", "level": "中", "keywords": ["单方调整"]},
    ],
}
GOLDEN_LABOR_CONTRACT = {
    "contract_type": "labor",
    "summary": "该劳动合同存在试用期超期、用人单位单方任意解除且免补偿、畸高违约金及工作地点单方调整等多处违法与不利条款，需重点修改。",
    "key_clauses": [
        {"name": "合同期限与试用期", "content": "贰年期限，试用期肆个月"},
        {"name": "工作内容与地点", "content": "甲方可单方调整工作地点"},
        {"name": "劳动报酬", "content": "月工资6000元，加班工资另行协商"},
        {"name": "社会保险", "content": "依法缴纳社保（个人部分自担）"},
        {"name": "劳动合同解除", "content": "甲方随时解除免补偿；乙方须提前六月通知"},
        {"name": "违约责任", "content": "乙方保密违约金50万，甲方违约不担责"},
        {"name": "争议解决", "content": "向甲方所在地法院起诉"},
    ],
    "risks": [
        {"level": "高", "clause": "合同期限与试用期", "quote": "试用期为肆个月",
         "risk": "贰年固定期限合同试用期法定上限为2个月，4个月违反《劳动合同法》第十九条。",
         "suggestion": "将试用期改为不超过2个月，并相应调整试用期工资。"},
        {"level": "高", "clause": "劳动合同解除", "quote": "甲方可随时解除劳动合同且无需支付经济补偿",
         "risk": "用人单位任意解除且免付经济补偿，违反法定解除情形与经济补偿规定。",
         "suggestion": "明确仅在《劳动合同法》第三十九/四十条规定情形下解除，并依法支付经济补偿。"},
        {"level": "高", "clause": "违约责任", "quote": "乙方违反保密义务须支付违约金50万元",
         "risk": "对劳动者约定畸高违约金，超出《劳动合同法》第二十五条允许范围（仅限服务期与竞业限制）。甲方违约不承担责任亦显失公平。",
         "suggestion": "删除普通保密违约金，改以实际损失赔偿或签订专项保密/竞业协议。"},
        {"level": "中", "clause": "工作内容与地点", "quote": "甲方可根据经营需要单方调整",
         "risk": "单方调整工作地点扩大用人单位权利，易实质变更劳动条件。",
         "suggestion": "约定调整须经双方协商一致，或限于同城且不降低待遇。"},
    ],
    "disclaimer": DISCLAIMER,
}

# ---------------------------------------------------------------------------
# 2) 劳动合同（clean 反例）
# ---------------------------------------------------------------------------
REF_LABOR_CLEAN = {
    "contract_type": "labor",
    "sample_role": "clean",
    "expected_key_clauses": [
        {"name": "合同期限", "keywords": ["合同期限", "试用期"]},
        {"name": "工作内容与地点", "keywords": ["工作地点"]},
        {"name": "劳动报酬", "keywords": ["工资", "8000"]},
        {"name": "社会保险", "keywords": ["社会保险"]},
        {"name": "保密义务", "keywords": ["保密"]},
        {"name": "竞业限制", "keywords": ["竞业限制", "补偿"]},
        {"name": "合同解除", "keywords": ["解除", "通知"]},
    ],
    "expected_risks": [
        {"topic": "加班费计算基数未约定", "level": "中", "keywords": ["加班费计算基数", "未与劳动者约定"]},
    ],
}
GOLDEN_LABOR_CLEAN = {
    "contract_type": "labor",
    "summary": "该劳动合同整体合规，仅存在「加班费计算基数未约定」一处中等风险，建议补充明确。",
    "key_clauses": [
        {"name": "合同期限", "content": "固定期限3年，试用期2个月"},
        {"name": "工作内容与地点", "content": "产品经理，杭州市西湖区"},
        {"name": "劳动报酬", "content": "试用期6400/转正8000，次月10日前发"},
        {"name": "社会保险", "content": "依法缴纳五险"},
        {"name": "保密义务", "content": "在职及离职保密，无保密补偿（合法）"},
        {"name": "竞业限制", "content": "离职2年内不竞业，按月付30%补偿（合规）"},
        {"name": "合同解除", "content": "协商一致或乙方提前30日通知可解除"},
    ],
    "risks": [
        {"level": "中", "clause": "劳动报酬", "quote": "甲方未与劳动者约定加班费计算基数",
         "risk": "未约定加班费计算基数，发生加班时易就计算标准产生争议。",
         "suggestion": "补充约定加班费计算基数（如以基本工资或月工资为基数）及支付标准。"},
    ],
    "disclaimer": DISCLAIMER,
}

# ---------------------------------------------------------------------------
# 3) 劳动合同（fake_law 对抗）
# ---------------------------------------------------------------------------
REF_LABOR_FAKE = {
    "contract_type": "labor",
    "sample_role": "adversarial",
    "expected_key_clauses": [
        {"name": "合同期限与试用期", "keywords": ["试用期", "6个月"]},
        {"name": "工资", "keywords": ["工资", "5000"]},
        {"name": "解除劳动合同", "keywords": ["解除", "劳动法"]},
        {"name": "竞业限制", "keywords": ["竞业限制", "补偿"]},
        {"name": "保密", "keywords": ["保密", "补偿"]},
        {"name": "工资扣除", "keywords": ["扣减", "工资"]},
    ],
    "expected_risks": [
        {"topic": "引用伪造法条《劳动法》第999条作解除依据", "level": "高", "keywords": ["劳动法》第999条", "任何理由单方解除"]},
        {"topic": "竞业限制3年且不支付补偿", "level": "高", "keywords": ["3年内", "不支付竞业限制补偿"]},
        {"topic": "工资扣减违法且累计无上限", "level": "高", "keywords": ["扣减当日工资", "不设上限"]},
        {"topic": "过度/永久保密义务且无补偿", "level": "中", "keywords": ["永久保守", "不支付任何补偿"]},
    ],
}
GOLDEN_LABOR_FAKE = {
    "contract_type": "labor",
    "summary": "该劳动合同多处违法，且引用不存在的《劳动法》第999条作为解除依据，竞业限制、工资扣减、保密条款均严重失衡，需全面重写。",
    "key_clauses": [
        {"name": "合同期限与试用期", "content": "3年期限，试用期6个月"},
        {"name": "工资", "content": "月5000，试用期4000"},
        {"name": "解除劳动合同", "content": "引《劳动法》第999条，甲方任意解除免补偿"},
        {"name": "竞业限制", "content": "离职3年不竞业，无补偿"},
        {"name": "保密", "content": "永久保密，无补偿"},
        {"name": "工资扣除", "content": "迟到扣当日工资，累计无上限"},
    ],
    "risks": [
        {"level": "高", "clause": "解除劳动合同", "quote": "根据《中华人民共和国劳动法》第999条规定，甲方有权在任何时候以任何理由单方解除劳动合同，且无需向乙方支付经济补偿",
         "risk": "《劳动法》并无第999条，属伪造法条；且用人单位任意解除免补偿违反法定规则。",
         "suggestion": "删除伪造法条引用，解除须符合《劳动合同法》第三十九/四十条，并依法支付经济补偿。"},
        {"level": "高", "clause": "竞业限制", "quote": "乙方离职后3年内不得从事与甲方有竞争关系的业务，甲方不支付竞业限制补偿",
         "risk": "竞业限制期限不得超过2年，且解除或终止后须按月支付补偿，否则条款无效。",
         "suggestion": "将期限改为不超过2年，并明确按月支付不低于离职前工资30%的竞业补偿。"},
        {"level": "高", "clause": "工资扣除", "quote": "乙方每迟到一次扣减当日工资，每月迟到累计扣款不设上限",
         "risk": "按日扣工资且累计无上限，易使实发工资低于最低工资，违反工资支付规定。",
         "suggestion": "迟到扣款应合理，单次扣款不得超过当日工资20%且扣后不低于最低工资，并设月度上限。"},
        {"level": "中", "clause": "保密", "quote": "乙方应永久保守甲方一切信息秘密，离职后亦同，甲方不支付任何补偿",
         "risk": "要求永久、无范围保密且零补偿，义务过重、范围过宽，缺乏可执行边界。",
         "suggestion": "明确保密范围与期限（如离职后2-3年），对超出法定范围的保密可约定合理补偿。"},
    ],
    "disclaimer": DISCLAIMER,
}

# ---------------------------------------------------------------------------
# 4) 商铺租赁（典型风险）
# ---------------------------------------------------------------------------
REF_LEASE_CONTRACT = {
    "contract_type": "lease",
    "sample_role": "standard",
    "expected_key_clauses": [
        {"name": "租赁标的", "keywords": ["商铺", "餐饮"]},
        {"name": "租赁期限与免租期", "keywords": ["租赁期限", "免租期"]},
        {"name": "租金与递增", "keywords": ["租金", "递增"]},
        {"name": "押金", "keywords": ["押金"]},
        {"name": "维修责任", "keywords": ["维修"]},
        {"name": "转租", "keywords": ["转租"]},
        {"name": "提前退租", "keywords": ["提前退租"]},
        {"name": "费用承担", "keywords": ["费用"]},
        {"name": "合同解除", "keywords": ["收回商铺"]},
        {"name": "争议解决", "keywords": ["法院"]},
    ],
    "expected_risks": [
        {"topic": "维修责任全转嫁承租方", "level": "高", "keywords": ["一切维修养护责任均由乙方承担"]},
        {"topic": "出租方任意解约且不担责", "level": "高", "keywords": ["随时收回商铺", "不承担责任"]},
        {"topic": "提前退租违约金过重", "level": "中", "keywords": ["押金不予退还", "三个月租金作为违约金"]},
        {"topic": "争议管辖偏置出租方", "level": "中", "keywords": ["甲方所在地法院起诉"]},
        {"topic": "费用承担全转嫁", "level": "中", "keywords": ["一切费用均由乙方承担"]},
    ],
}
GOLDEN_LEASE_CONTRACT = {
    "contract_type": "lease",
    "summary": "该商铺租赁合同含多处霸王条款：维修责任全转嫁、出租方任意解约、提前退租违约金过重、管辖偏置、费用全担，承租方风险极高。",
    "key_clauses": [
        {"name": "租赁标的", "content": "示例广场B1-08商铺，经营餐饮"},
        {"name": "租赁期限与免租期", "content": "3年，含免租期30日"},
        {"name": "租金与递增", "content": "月租2万，年增8%"},
        {"name": "押金", "content": "3个月租金，退租60日无息退"},
        {"name": "维修责任", "content": "一切维修养护由乙方承担"},
        {"name": "转租", "content": "须经甲方书面同意"},
        {"name": "提前退租", "content": "押金不退+3月租金违约金"},
        {"name": "费用承担", "content": "水电气物业公摊全由乙方担"},
        {"name": "合同解除", "content": "甲方随时收回商铺不担责"},
        {"name": "争议解决", "content": "甲方所在地法院管辖"},
    ],
    "risks": [
        {"level": "高", "clause": "维修责任", "quote": "租赁期内房屋及附属设施的一切维修养护责任均由乙方承担",
         "risk": "将全部维修责任转嫁承租方，违反出租人保持租赁物适租的义务。",
         "suggestion": "改由出租方负责主体结构及固有设施自然损耗维修，承租方仅对使用不当损坏负责。"},
        {"level": "高", "clause": "合同解除", "quote": "甲方有权随时收回商铺，乙方须于三日內腾退，甲方不承担责任",
         "risk": "出租方任意解约且不担责，剥夺承租方稳定使用权。",
         "suggestion": "约定仅可在法定/约定情形解约，并设置合理提前通知期与违约赔偿。"},
        {"level": "中", "clause": "提前退租", "quote": "乙方提前退租的，押金不予退还，并另付三个月租金作为违约金",
         "risk": "押金不退叠加高额违约金，责任过重。",
         "suggestion": "二选一：扣减押金或按实际损失付违约金，避免重复计罚。"},
        {"level": "中", "clause": "争议解决", "quote": "向甲方所在地法院起诉",
         "risk": "管辖偏置出租方所在地，增加承租方维权成本。",
         "suggestion": "改为租赁物所在地或原告所在地法院管辖。"},
        {"level": "中", "clause": "费用承担", "quote": "租赁期间的水、电、物业、公摊等一切费用均由乙方承担",
         "risk": "将本可由出租方承担的物业/公摊费用全转嫁，负担过重。",
         "suggestion": "明确水电能耗由乙方承担，物业/公摊按租赁面积合理分摊或约定上限。"},
    ],
    "disclaimer": DISCLAIMER,
}

# ---------------------------------------------------------------------------
# 5) 商铺租赁（clean 反例）
# ---------------------------------------------------------------------------
REF_LEASE_CLEAN = {
    "contract_type": "lease",
    "sample_role": "clean",
    "expected_key_clauses": [
        {"name": "租赁标的与期限", "keywords": ["商铺", "租期"]},
        {"name": "租金与押金", "keywords": ["租金", "押金"]},
        {"name": "维修责任", "keywords": ["维修"]},
        {"name": "转租", "keywords": ["转租", "管理费"]},
        {"name": "提前解约", "keywords": ["提前解约"]},
        {"name": "免责", "keywords": ["不可抗力"]},
    ],
    "expected_risks": [
        {"topic": "转租收取20%管理费偏高", "level": "中", "keywords": ["20%作为管理费"]},
    ],
}
GOLDEN_LEASE_CLEAN = {
    "contract_type": "lease",
    "summary": "该商铺租赁合同条款基本公平合理，仅「转租收取租金20%管理费」一项偏高，建议协商下调。",
    "key_clauses": [
        {"name": "租赁标的与期限", "content": "南京鼓楼区商铺，租期2年"},
        {"name": "租金与押金", "content": "月租8000，押金1月，7日无息退"},
        {"name": "维修责任", "content": "主体/固有设施甲方负责，使用不当乙方负责"},
        {"name": "转租", "content": "经甲方同意，收转租租金20%管理费"},
        {"name": "提前解约", "content": "任一方提前30日通知，无违约金"},
        {"name": "免责", "content": "不可抗力双方互不担责"},
    ],
    "risks": [
        {"level": "中", "clause": "转租", "quote": "甲方收取转租租金的20%作为管理费",
         "risk": "转租管理费比例偏高，且无对应服务说明，加重承租方转租成本。",
         "suggestion": "将管理费比例下调（如5%-10%）或明确对应服务内容。"},
    ],
    "disclaimer": DISCLAIMER,
}

# ---------------------------------------------------------------------------
# 6) 商铺租赁（jargon 对抗）
# ---------------------------------------------------------------------------
REF_LEASE_JARGON = {
    "contract_type": "lease",
    "sample_role": "adversarial",
    "expected_key_clauses": [
        {"name": "标的物", "keywords": ["标的物", "办公单元"]},
        {"name": "不可抗力与风险负担", "keywords": ["不可抗力", "瑕疵担保"]},
        {"name": "违约责任", "keywords": ["违约金", "提前终止"]},
        {"name": "免责", "keywords": ["不承担责任"]},
        {"name": "租金与押金", "keywords": ["租金", "押金"]},
    ],
    "expected_risks": [
        {"topic": "不可抗力风险全转嫁乙方", "level": "高", "keywords": ["概由乙方自行承担", "不承担任何瑕疵担保责任"]},
        {"topic": "甲方提前终止无责/乙方违约金过重", "level": "高", "keywords": ["甲方提前终止无需承担任何责任", "六个月租金之违约金"]},
        {"topic": "甲方免责一切瑕疵担保与第三方权利", "level": "高", "keywords": ["均不承担责任", "善意第三人权利"]},
        {"topic": "术语堆砌掩盖单方免责", "level": "中", "keywords": ["孳息", "瑕疵担保", "善意第三人"]},
    ],
}
GOLDEN_LEASE_JARGON = {
    "contract_type": "lease",
    "summary": "该租赁协议用「孳息」「瑕疵担保」「善意第三人」等专业术语包装，实质将不可抗力、瑕疵担保、违约责任等风险全转嫁乙方，属伪专业霸王条款。",
    "key_clauses": [
        {"name": "标的物", "content": "成都写字楼办公单元"},
        {"name": "不可抗力与风险负担", "content": "不可抗力全由乙方承担，甲方免瑕疵担保"},
        {"name": "违约责任", "content": "乙方提前终止付6月租金违约金；甲方无责"},
        {"name": "免责", "content": "甲方对权利/物理瑕疵及第三方权利不担责"},
        {"name": "租金与押金", "content": "月租1.2万，押金2月，30日退"},
    ],
    "risks": [
        {"level": "高", "clause": "不可抗力与风险负担", "quote": "不可抗力事件发生引致之全部损害、损失及不能履行之后果，概由乙方自行承担，甲方不承担任何瑕疵担保责任与赔偿义务",
         "risk": "事先免除出租人法定瑕疵担保责任、将不可抗力风险全转嫁，违反《民法典》相关规定。",
         "suggestion": "删除「概由乙方承担」，约定不可抗力按法定分担，出租人保持租赁物适租与权利无瑕疵。"},
        {"level": "高", "clause": "违约责任", "quote": "乙方如需提前终止本协议，应向甲方支付相当于六个月租金之违约金；甲方提前终止无需承担任何责任",
         "risk": "双方违约责任严重不对等，甲方免责、乙方重罚。",
         "suggestion": "约定双方对等解约责任，违约金以实际损失为限（通常≤1-2月租金）。"},
        {"level": "高", "clause": "免责", "quote": "甲方对标的物之一切权利瑕疵、物理瑕疵及第三方主张之善意第三人权利，均不承担责任",
         "risk": "全面免除出租人对权利瑕疵与物理瑕疵的担保责任，剥夺承租方救济。",
         "suggestion": "删除该免责，明确出租人对租赁物权利无瑕疵、物理适租负责。"},
        {"level": "中", "clause": "条款表述", "quote": "占有、使用、收益及孳息归属事宜",
         "risk": "堆砌法律术语掩盖单方免责实质，非法律用户难以识别风险。",
         "suggestion": "用通俗语言重述双方权利义务，去除伪专业包装。"},
    ],
    "disclaimer": DISCLAIMER,
}

# ---------------------------------------------------------------------------
# 7) 非合同（negative 鲁棒性）
# ---------------------------------------------------------------------------
REF_NONCONTRACT = {
    "contract_type": "unknown",
    "sample_role": "negative",
    "expected_key_clauses": [],
    "expected_risks": [],
}
GOLDEN_NONCONTRACT = {
    "contract_type": "unknown",
    "summary": "输入文本为产品使用说明，非劳动合同或租赁合同，无法审阅。",
    "key_clauses": [],
    "risks": [],
    "disclaimer": DISCLAIMER,
}

ANNOTATIONS = {
    "sample_labor_contract": (REF_LABOR_CONTRACT, GOLDEN_LABOR_CONTRACT),
    "sample_labor_clean": (REF_LABOR_CLEAN, GOLDEN_LABOR_CLEAN),
    "sample_labor_fake_law": (REF_LABOR_FAKE, GOLDEN_LABOR_FAKE),
    "sample_lease_contract": (REF_LEASE_CONTRACT, GOLDEN_LEASE_CONTRACT),
    "sample_lease_clean": (REF_LEASE_CLEAN, GOLDEN_LEASE_CLEAN),
    "sample_lease_jargon": (REF_LEASE_JARGON, GOLDEN_LEASE_JARGON),
    "sample_noncontract": (REF_NONCONTRACT, GOLDEN_NONCONTRACT),
}


def main() -> None:
    for name, (ref, golden) in ANNOTATIONS.items():
        (REF_DIR / f"{name}.reference.json").write_text(
            json.dumps(ref, ensure_ascii=False, indent=2), encoding="utf-8")
        (GOLDEN_DIR / f"{name}.golden.json").write_text(
            json.dumps(golden, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"written: {name} (ref risks={len(ref['expected_risks'])})")


if __name__ == "__main__":
    main()
