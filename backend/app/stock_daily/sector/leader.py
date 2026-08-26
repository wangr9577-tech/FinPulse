"""强势板块领涨股选取：取各源领涨股并集的前 1-2 只。"""
from app.stock_daily.models import SectorQuote


def pick_leaders(quotes: list[SectorQuote], top: int = 2) -> list[str]:
    """从同板块多源 quote 的领涨股中取并集前 top 只（去重保序）。"""
    seen: list[str] = []
    for q in quotes:
        for stock in q.leader_stocks:
            if stock and stock not in seen:
                seen.append(stock)
    return seen[:top]
