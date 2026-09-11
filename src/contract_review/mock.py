"""离线 mock 审阅，用于无真实 Hy3 端点时验证链路与输出结构。

按合同文本启发式分类后，返回与真实审阅同结构的 ReviewResult，保证端到端可跑通。
仅用于开发/演示，不代表真实审阅质量。
"""

from __future__ import annotations

from .review import ReviewResult, DEFAULT_DISCLAIMER


def _classify(text: str) -> str:
    # 仅当同时出现甲乙两方称谓，才视为真实合同（排除仅"提及"合同名词的说明类文本）
    if "甲方" not in text or "乙方" not in text:
        return "unknown"
    if any(k in text for k in ("租赁", "出租", "承租", "租金", "押金", "商铺", "租赁标的")):
        return "lease"
    if any(k in text for k in ("劳动合同", "用人单位", "劳动者", "试用期", "竞业")):
        return "labor"
    return "unknown"


_MOCK_LABOR = ReviewResult(
    contract_type="labor",
    summary="劳动合同存在试用期超标、单方解除、高额违约金等多处风险，需修改。",
    key_clauses=[
        {"name": "合同期限与试用期", "content": "贰年期限，试用期肆个月"},
        {"name": "工作地点", "content": "甲方可单方调整工作地点"},
        {"name": "劳动报酬", "content": "月工资 6000 元，加班工资另行协商"},
        {"name": "解除条件", "content": "甲方可随时解除且不补偿；乙方须提前六个月通知"},
        {"name": "违约责任", "content": "乙方保密违约金 50 万元，甲方违约不担责"},
    ],
    risks=[
        {
            "level": "高",
            "clause": "试用期",
            "quote": "试用期为肆个月",
            "risk": "贰年期合同试用期法定上限为 2 个月，4 个月违反《劳动合同法》第十九条。",
            "suggestion": "将试用期改为不超过 2 个月，并相应调整试用期工资。",
        },
        {
            "level": "高",
            "clause": "解除劳动合同",
            "quote": "甲方可随时解除劳动合同且无需支付经济补偿",
            "risk": "用人单位单方任意解除且免补偿，违反法定解除条件与经济补偿规则。",
            "suggestion": "明确解除须符合《劳动合同法》第三十九/四十条情形，并依法支付经济补偿。",
        },
        {
            "level": "高",
            "clause": "违约责任",
            "quote": "乙方违反保密义务须支付违约金50万元",
            "risk": "对劳动者设定畸高违约金，超出《劳动合同法》第二十五条允许约定的违约金范围（仅限培训服务期与竞业限制）。",
            "suggestion": "删除普通保密违约金条款，改以损失赔偿或专项保密协议处理。",
        },
        {
            "level": "中",
            "clause": "工作地点",
            "quote": "甲方可根据经营需要单方调整",
            "risk": "单方调整工作地点扩大用人单位权利，易导致实质变更劳动条件。",
            "suggestion": "约定调整须经双方协商一致，或限定在同一城市范围内且不降低待遇。",
        },
    ],
    disclaimer=DEFAULT_DISCLAIMER,
    source="mock",
)


_MOCK_LEASE = ReviewResult(
    contract_type="lease",
    summary="商铺租赁存在维修责任全转嫁、出租方任意解约、提前退租违约金偏高等风险。",
    key_clauses=[
        {"name": "租赁期限", "content": "3 年，含免租期 30 日"},
        {"name": "租金与递增", "content": "月租 20000 元，每年递增 8%"},
        {"name": "押金", "content": "3 个月租金，退租后 60 日内无息退还"},
        {"name": "维修责任", "content": "一切维修养护由承租方承担"},
        {"name": "提前退租", "content": "押金不退并另付三个月租金作违约金"},
        {"name": "合同解除", "content": "甲方可随时收回商铺"},
    ],
    risks=[
        {
            "level": "高",
            "clause": "合同解除",
            "quote": "甲方有权随时收回商铺，乙方须于三日內腾退",
            "risk": "出租方任意解约且不担责，剥夺承租方稳定性，属霸王条款。",
            "suggestion": "约定出租方仅可在法定/约定情形下解约，并设置合理提前通知与违约赔偿。",
        },
        {
            "level": "高",
            "clause": "维修责任",
            "quote": "房屋及附属设施的一切维修养护责任均由乙方承担",
            "risk": "将全部维修责任转嫁承租方，违反《民法典》出租人保持租赁物适租义务。",
            "suggestion": "主体结构及固有设施由出租方负责，承租方仅对使用不当造成的损坏负责。",
        },
        {
            "level": "中",
            "clause": "提前退租",
            "quote": "押金不予退还，并另付三个月租金作为违约金",
            "risk": "押金不退叠加高额违约金，违约责任过重。",
            "suggestion": "二选一：或扣减押金，或按实际损失支付违约金，避免重复计罚。",
        },
        {
            "level": "中",
            "clause": "争议解决",
            "quote": "向甲方所在地法院起诉",
            "risk": "管辖偏置出租方所在地，增加承租方维权成本。",
            "suggestion": "改为租赁物所在地或原告所在地法院管辖。",
        },
    ],
    disclaimer=DEFAULT_DISCLAIMER,
    source="mock",
)


_MOCK_UNKNOWN = ReviewResult(
    contract_type="unknown",
    summary="未识别为劳动合同或租赁合同，无法审阅。",
    key_clauses=[],
    risks=[],
    disclaimer=DEFAULT_DISCLAIMER,
    source="mock",
)


def mock_review(contract_text: str) -> ReviewResult:
    ct = _classify(contract_text)
    base = {"labor": _MOCK_LABOR, "lease": _MOCK_LEASE, "unknown": _MOCK_UNKNOWN}[ct]
    return ReviewResult(**{**base.__dict__, "source": "mock"})
