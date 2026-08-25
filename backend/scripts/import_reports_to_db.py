# -*- coding: utf-8 -*-
import re
from pathlib import Path
from datetime import datetime
from pymongo import MongoClient

c = MongoClient('mongodb://localhost:27017')
db = c['intelligent_research_db']

out_dir = Path(__file__).resolve().parent.parent / "output"
html_files = sorted(list(out_dir.glob("*.html")))

docs = []
for idx, html_path in enumerate(html_files, 1):
    m = re.search(r'(\d{8})_(\d{6})', html_path.name)
    if m:
        dt_str = m.group(1) + m.group(2)
        gen_time = datetime.strptime(dt_str, '%Y%m%d%H%M%S')
    else:
        gen_time = datetime(2026, 8, 12, 17, 42, 30)
        
    title = html_path.stem
    pdf_path = html_path.with_suffix('.pdf')
    time_fmt = gen_time.strftime('%Y%m%d_%H%M%S')
    date_display = gen_time.strftime('%Y-%m-%d %H:%M')
    
    docs.append({
        'report_id': f'rep_{time_fmt}',
        'title': f'智能投研综合研报 (择时六面图与产业链分析) - {date_display}',
        'timestamp': gen_time,
        'generation_time': gen_time,
        'target_industries': ['半导体与芯片', '硬科技与人工智能', '大消费与白酒', '高股息与红利'],
        'macro_alert': {'is_triggered': False, 'events': []},
        'content_markdown': f'# {title}\n\n该研报已成功生成。',
        'html_url': f'/static/{html_path.name}',
        'pdf_url': f'/static/{pdf_path.name}' if pdf_path.exists() else None,
        'charts_data': {}
    })

db['market_insight_reports'].drop()
if docs:
    db['market_insight_reports'].insert_many(docs)
    print(f'Inserted {len(docs)} historical insight reports into MongoDB!')
