"""标题情绪分桶：利好直出 / 中性待复核 / 利空或例行中性舍弃。"""
from dataclasses import dataclass, field

from app.stock_daily import rules
from app.stock_daily.models import AnalysisResult, Announcement


@dataclass
class PlanResult:
    positive: list[tuple[Announcement, AnalysisResult]] = field(default_factory=list)  # 标题判定利好
    pending: list[Announcement] = field(default_factory=list)                          # 中性且非例行，待下载复核
    discarded: int = 0                                                                 # 利空 + 例行中性


def plan_by_title(announcements: list[Announcement], judge_fn) -> PlanResult:
    """对每条公告调用 judge_fn（应返回 AnalysisResult），按情绪分桶。

    - 利好 → positive；利空 → discarded；
    - 中性 → 命中例行词表则 discarded，否则进 pending 待复核。
    """
    result = PlanResult()
    for ann in announcements:
        j = judge_fn(ann)
        if j.sentiment == "利好":
            result.positive.append((ann, j))
        elif j.sentiment == "利空":
            result.discarded += 1
        else:  # 中性
            if rules.is_routine(ann):
                result.discarded += 1
            else:
                result.pending.append(ann)
    return result
