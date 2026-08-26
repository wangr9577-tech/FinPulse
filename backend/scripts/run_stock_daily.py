"""
定时入口：跑一天的「上市公司每日公告 + 选股报告」并写入 Mongo。

用法（每交易日 18:00 由 Windows 任务计划调用）：
    python scripts/run_stock_daily.py                  # 跑今天
    python scripts/run_stock_daily.py --date 2026-08-25  # 跑指定日期

跑完的结果落在 Mongo 集合 daily_stock_reports，前端投资日报页面通过
GET /api/v1/stock-daily/latest 读取展示。网络/DeepSeek key 缺失时降级为
available:false（前端空态），不产生任何编造数据。
"""

import argparse
import asyncio
from datetime import date

from app.db.mongodb import MongoDBClient
from app.stock_daily.runner import run_for_date


async def _main(ann_date: date) -> int:
    result = await run_for_date(ann_date)
    doc = {
        "date": result["date"],
        "report_type": "investment_daily",
        "available": result.get("available", False),
        "data": result.get("data"),
        "run_meta": result.get("run_meta"),
    }
    db_client = MongoDBClient.get_instance()
    await db_client.connect()
    await db_client.save_daily_stock_report(doc)
    if result.get("available"):
        n = result["data"]
        detail = n.get("announcements") or {}
        print(
            f"[OK] 投资日报已生成并入库: {result['date']} | "
            f"公告 {detail.get('total', 0)} 条, "
            f"强势板块 {len(n.get('sectors_strong', []))}, "
            f"选股 {len((n.get('stock_picks') or {}).get('picks', []))}, "
            f"业绩预告 {len(n.get('forecasts', []))}"
        )
    else:
        print(f"[EMPTY] {result['date']} 无可用数据（非交易日或数据源不可达），未生成内容。")
    await db_client.close()
    return 0


def main():
    parser = argparse.ArgumentParser(description="跑一天投资日报并写入 Mongo")
    parser.add_argument("--date", dest="ann_date", default=None,
                        help="指定日期 YYYY-MM-DD（默认今天）")
    args = parser.parse_args()
    ann_date = date.fromisoformat(args.ann_date) if args.ann_date else date.today()
    asyncio.run(_main(ann_date))


if __name__ == "__main__":
    main()
