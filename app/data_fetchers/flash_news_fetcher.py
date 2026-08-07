"""
高频半结构化快讯与硬科技/全球宏观全量抓取引擎 (Full-Scale Flash & Global News Fetcher Engine)

全量 13 大媒体与投研数据源矩阵：
1. 新浪财经 (7x24直播快讯) - A股、港美股与宏观高频直播 (API 直连)
2. 东方财富网 (7x24快讯) - 证券与全市场快讯 (NewsAPI 直连)
3. 36氪 (硬科技/AI/快讯) - 人工智能、科技独角兽与 TMT (官方 RSS / API)
4. 财联社 (7x24电报) - 国内政策与大盘异动 (电报 RSSHub 容灾)
5. 华尔街见闻 (全球快讯) - 全球宏观与大类资产
6. IT之家 (半导体/芯片) - 芯片厂商动态与算力硬件 (官方 RSS)
7. 钛媒体 (硬科技/科技) - 科技趋势与半导体 (官方 RSS)
8. EE Times China (电子工程专辑) - 芯片设计与晶圆产能
9. 机器之心 - AI大模型前沿与算法论文
10. 量子位 - 智能硬件与AI产业动态
11. Reuters (路透社) - 全球宏观、地缘政治与美联储
12. Bloomberg (彭博社) - 全球大类资产与市场头条
13. Yahoo Finance - 美股市场异动与隔夜宏观

核心特性：
- 13 大数据源全量并发拉取，互补无死角覆盖
- 统一支持 **24h/1h 时间倒序早停熔断机制 (Early-Exit Short-Circuit)**
- 统一输出标准化 Pydantic `RawNewsSchema`
"""

import asyncio
import json
import logging
import re
import uuid
from datetime import datetime, timedelta, timezone
from typing import Dict, List, Optional, Any
import httpx
import feedparser
from bs4 import BeautifulSoup


from app.models.news_schema import RawNewsSchema

# 配置全局日志
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
logger = logging.getLogger("FlashNewsFetcher")


class FlashNewsFetcher:
    """
    全量全渠道高频快讯、硬科技与全球宏观投研采集引擎
    """

    def __init__(
        self,
        request_timeout: Optional[float] = None,
        rsshub_instances: Optional[List[str]] = None,
        source_urls: Optional[Dict[str, str]] = None,
    ):
        """
        :param request_timeout: HTTP 单次请求超时时间（秒，默认优先使用 config 配置）
        :param rsshub_instances: RSSHub 降级镜像节点列表（默认优先使用 config.RSSHUB_INSTANCES）
        :param source_urls: 各大媒体/投研源 URL 字典（默认优先使用 config.NEWS_SOURCE_URLS）
        """
        from app.core.config import settings
        self.request_timeout = request_timeout if request_timeout is not None else settings.CRAWL_REQUEST_TIMEOUT
        self.max_hours = settings.REPORT_HOURS_BACK
        self.rsshub_instances = rsshub_instances if rsshub_instances is not None else settings.RSSHUB_INSTANCES
        self.source_urls = source_urls if source_urls is not None else settings.NEWS_SOURCE_URLS
        self.user_agent = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"



    def _get_headers(self, referer: str = "") -> Dict[str, str]:
        """生成标准 HTTP 请求头"""
        headers = {
            "User-Agent": self.user_agent,
            "Accept": "application/json, text/plain, text/xml, application/xml, */*",
            "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
            "Cache-Control": "no-cache",
        }
        if referer:
            headers["Referer"] = referer
        return headers

    def _clean_html(self, text: str) -> str:
        """剥离 HTML 标签与多余空格"""
        if not text:
            return ""
        soup = BeautifulSoup(text, "html.parser")
        clean_text = soup.get_text(separator=" ")
        clean_text = re.sub(r"\s+", " ", clean_text).strip()
        return clean_text

    def _is_within_time_window(self, pub_dt: datetime, cutoff_dt: datetime) -> bool:
        """校验时间戳是否/在时间窗口内 (统一转换为 UTC 比较)"""
        pub_utc = pub_dt if pub_dt.tzinfo else pub_dt.replace(tzinfo=timezone.utc)
        cutoff_utc = cutoff_dt if cutoff_dt.tzinfo else cutoff_dt.replace(tzinfo=timezone.utc)
        return pub_utc >= cutoff_utc

    # =========================================================================
    # 1. 新浪财经 (7x24直播快讯) - 原生 API 直连
    # =========================================================================
    async def fetch_sina_7x24(self, client: httpx.AsyncClient, cutoff_dt: datetime) -> List[RawNewsSchema]:
        url = self.source_urls["sina_7x24"]
        headers = self._get_headers(referer="https://finance.sina.com.cn/7x24/")
        items: List[RawNewsSchema] = []

        try:
            logger.info("[新浪财经 7x24] 拉取高频直播快讯...")
            resp = await client.get(url, headers=headers, timeout=self.request_timeout)
            if resp.status_code != 200:
                return []

            res_json = resp.json()
            feed_dict = res_json.get("result", {}).get("data", {}).get("feed", {})
            feed_list = feed_dict.get("list", []) if isinstance(feed_dict, dict) else []

            for raw_item in feed_list:
                if not isinstance(raw_item, dict):
                    continue

                time_str = raw_item.get("create_time") or raw_item.get("update_time") or ""
                if not time_str:
                    continue

                try:
                    naive_dt = datetime.strptime(time_str, "%Y-%m-%d %H:%M:%S")
                    pub_dt = naive_dt.replace(tzinfo=timezone(timedelta(hours=8))).astimezone(timezone.utc)
                except Exception:
                    pub_dt = datetime.now(timezone.utc)

                if not self._is_within_time_window(pub_dt, cutoff_dt):
                    logger.info(f"[新浪财经 Early-Exit] 遇到 >{self.max_hours}h 旧条目，熔断终止。")
                    break

                rich_text = self._clean_html(raw_item.get("rich_text", ""))
                if not rich_text:
                    continue

                news_id = f"sina_{raw_item.get('id')}"
                title_match = re.match(r"【(.*?)】", rich_text)
                title = title_match.group(1) if title_match else (rich_text[:35] + "..." if len(rich_text) > 35 else rich_text)
                tags = [t["name"] for t in raw_item.get("tag", []) if isinstance(t, dict) and "name" in t]

                items.append(
                    RawNewsSchema(
                        news_id=news_id,
                        source="新浪财经",
                        title=title,
                        content=rich_text,
                        publish_time=pub_dt,
                        category_tags=tags if tags else ["7x24快讯", "A股/宏观"],
                        sector="国内宏观与金融流动性",
                        importance=3 if "【" in rich_text or raw_item.get("is_focus") == 1 else 1,
                        channel_type="json_api",
                        raw_payload=raw_item,
                    )
                )

            logger.info(f"[新浪财经] 成功抓取 {len(items)} 条 {self.max_hours}h 增量快讯！")
            return items
        except Exception as e:
            logger.error(f"[新浪财经] 抓取失败: {e}")
            return []

    # =========================================================================
    # 2. 东方财富网 (7x24快讯) - 官方 NewsAPI 直连
    # =========================================================================
    async def fetch_eastmoney(self, client: httpx.AsyncClient, cutoff_dt: datetime) -> List[RawNewsSchema]:
        url = self.source_urls["eastmoney"]
        headers = self._get_headers(referer="https://kuaixun.eastmoney.com/")
        items: List[RawNewsSchema] = []

        try:
            logger.info("[东方财富网] 拉取 7x24 快讯 NewsAPI...")
            resp = await client.get(url, headers=headers, timeout=self.request_timeout)
            if resp.status_code != 200:
                return []

            res_json = resp.json()
            news_list = res_json.get("news", [])

            for raw_item in news_list:
                time_str = raw_item.get("showtime") or raw_item.get("ordertime") or ""
                if time_str:
                    try:
                        naive_dt = datetime.strptime(time_str, "%Y-%m-%d %H:%M:%S")
                        pub_dt = naive_dt.replace(tzinfo=timezone(timedelta(hours=8))).astimezone(timezone.utc)
                    except Exception:
                        pub_dt = datetime.now(timezone.utc)
                else:
                    pub_dt = datetime.now(timezone.utc)

                if not self._is_within_time_window(pub_dt, cutoff_dt):
                    logger.info(f"[东方财富 Early-Exit] 遇到旧条目，熔断终止。")
                    break

                title = raw_item.get("title") or ""
                digest = self._clean_html(raw_item.get("digest") or title)
                news_id = f"eastmoney_{raw_item.get('newsid') or raw_item.get('id')}"

                items.append(
                    RawNewsSchema(
                        news_id=news_id,
                        source="东方财富网",
                        title=title if title else digest[:35],
                        content=digest,
                        publish_time=pub_dt,
                        category_tags=["7x24快讯", "A股"],
                        sector="国内宏观与金融流动性",
                        importance=2 if "重磅" in title or "央行" in title else 1,
                        channel_type="json_api",
                        raw_payload=raw_item,
                    )
                )

            logger.info(f"[东方财富网] 成功抓取 {len(items)} 条 {self.max_hours}h 增量快讯！")
            return items
        except Exception as e:
            logger.error(f"[东方财富网] 抓取失败: {e}")
            return []

    # =========================================================================
    # 3. 36氪 (硬科技 / AI / 快讯) - 官方 RSS 直连
    # =========================================================================
    async def fetch_36kr(self, client: httpx.AsyncClient, cutoff_dt: datetime) -> List[RawNewsSchema]:
        logger.info("[36氪] 拉取硬科技与快讯通道...")
        url = self.source_urls["36kr"]
        return await self._fetch_rss_direct(client, "36氪", url, cutoff_dt, ["硬科技", "AI/TMT"], default_sector="硬科技/人工智能")

    # =========================================================================
    # 4. 财联社 (7x24电报)
    # =========================================================================
    async def fetch_cailianpress(self, client: httpx.AsyncClient, cutoff_dt: datetime) -> List[RawNewsSchema]:
        logger.info("[财联社 7x24] 正在拉取电报频道...")
        route = self.source_urls["cailianpress_route"]
        return await self._fallback_rsshub(client, "财联社", route, cutoff_dt, default_sector="国内宏观与金融流动性")

    # =========================================================================
    # 5. 华尔街见闻 (全球实时快讯)
    # =========================================================================
    async def fetch_wallstreetcn(self, client: httpx.AsyncClient, cutoff_dt: datetime) -> List[RawNewsSchema]:
        logger.info("[华尔街见闻] 拉取全球实时快讯...")
        route = self.source_urls["wallstreetcn_route"]
        return await self._fallback_rsshub(client, "华尔街见闻", route, cutoff_dt, default_sector="海外宏观与地缘政治")

    # =========================================================================
    # 6. IT之家 (半导体/芯片专栏) - 官方 RSS
    # =========================================================================
    async def fetch_ithome(self, client: httpx.AsyncClient, cutoff_dt: datetime) -> List[RawNewsSchema]:
        logger.info("[IT之家] 拉取半导体与芯片专栏...")
        url = self.source_urls["ithome"]
        return await self._fetch_rss_direct(client, "IT之家", url, cutoff_dt, ["半导体", "芯片", "硬件"], default_sector="半导体与芯片")

    # =========================================================================
    # 7. 钛媒体 (硬科技频道) - 官方 RSS
    # =========================================================================
    async def fetch_tmtpost(self, client: httpx.AsyncClient, cutoff_dt: datetime) -> List[RawNewsSchema]:
        logger.info("[钛媒体] 拉取硬科技资讯频道...")
        url = self.source_urls["tmtpost"]
        return await self._fetch_rss_direct(client, "钛媒体", url, cutoff_dt, ["硬科技", "半导体"], default_sector="硬科技/人工智能")

    # =========================================================================
    # 8. EE Times China (电子工程专辑)
    # =========================================================================
    async def fetch_eetchina(self, client: httpx.AsyncClient, cutoff_dt: datetime) -> List[RawNewsSchema]:
        logger.info("[EE Times China] 拉取电子工程专辑与芯片产能动态...")
        gnews_url = self.source_urls["eetchina_gnews"]
        route = self.source_urls["eetchina_route"]
        items = await self._fetch_rss_direct(client, "EE Times China", gnews_url, cutoff_dt, ["半导体", "晶圆产能", "芯片设计"], default_sector="半导体与芯片")
        if items:
            return items
        return await self._fallback_rsshub(client, "EE Times China", route, cutoff_dt, default_sector="半导体与芯片")

    # =========================================================================
    # 9. 机器之心 (Jiqizhixin)
    # =========================================================================
    async def fetch_jiqizhixin(self, client: httpx.AsyncClient, cutoff_dt: datetime) -> List[RawNewsSchema]:
        logger.info("[机器之心] 拉取 AI 大模型与论文算法前沿...")
        gnews_url = self.source_urls["jiqizhixin_gnews"]
        route = self.source_urls["jiqizhixin_route"]
        items = await self._fetch_rss_direct(client, "机器之心", gnews_url, cutoff_dt, ["AI前沿", "大模型", "算法论文"], default_sector="硬科技/人工智能")
        if items:
            return items
        return await self._fallback_rsshub(client, "机器之心", route, cutoff_dt, default_sector="硬科技/人工智能")

    # =========================================================================
    # 10. 量子位 (QbitAI)
    # =========================================================================
    async def fetch_qbitai(self, client: httpx.AsyncClient, cutoff_dt: datetime) -> List[RawNewsSchema]:
        logger.info("[量子位] 拉取前沿科技与智能硬件动态...")
        gnews_url = self.source_urls["qbitai_gnews"]
        route = self.source_urls["qbitai_route"]
        items = await self._fetch_rss_direct(client, "量子位", gnews_url, cutoff_dt, ["硬科技", "AI产业", "智能硬件"], default_sector="硬科技/人工智能")
        if items:
            return items
        return await self._fallback_rsshub(client, "量子位", route, cutoff_dt, default_sector="硬科技/人工智能")

    # =========================================================================
    # 11. Reuters (路透社)
    # =========================================================================
    async def fetch_reuters(self, client: httpx.AsyncClient, cutoff_dt: datetime) -> List[RawNewsSchema]:
        logger.info("[Reuters 路透社] 拉取全球宏观与地缘政治...")
        gnews_url = self.source_urls["reuters_gnews"]
        route = self.source_urls["reuters_route"]
        items = await self._fetch_rss_direct(client, "Reuters", gnews_url, cutoff_dt, ["海外宏观", "地缘政治", "美联储"], default_sector="海外宏观与地缘政治")
        if items:
            return items
        return await self._fallback_rsshub(client, "Reuters", route, cutoff_dt, default_sector="海外宏观与地缘政治")

    # =========================================================================
    # 12. Bloomberg (彭博社)
    # =========================================================================
    async def fetch_bloomberg(self, client: httpx.AsyncClient, cutoff_dt: datetime) -> List[RawNewsSchema]:
        logger.info("[Bloomberg 彭博社] 拉取全球市场头条与外资动态...")
        bloomberg_rss = self.source_urls["bloomberg_rss"]
        gnews_url = self.source_urls["bloomberg_gnews"]
        items = await self._fetch_rss_direct(client, "Bloomberg", bloomberg_rss, cutoff_dt, ["全球市场", "外资流向", "彭博头条"], default_sector="海外宏观与地缘政治")
        if items:
            return items
        return await self._fetch_rss_direct(client, "Bloomberg", gnews_url, cutoff_dt, ["全球市场", "彭博头条"], default_sector="海外宏观与地缘政治")

    # =========================================================================
    # 13. Yahoo Finance
    # =========================================================================
    async def fetch_yahoofinance(self, client: httpx.AsyncClient, cutoff_dt: datetime) -> List[RawNewsSchema]:
        logger.info("[Yahoo Finance] 拉取美股市场与隔夜宏观...")
        yf_rss = self.source_urls.get("yahoofinance_rss", "https://finance.yahoo.com/news/rssindex")
        yf_index_rss = self.source_urls.get("yahoofinance_index_rss", "https://feeds.finance.yahoo.com/rss/2.0/headline?s=^GSPC&region=US&lang=en-US")
        items = await self._fetch_rss_direct(client, "Yahoo Finance", yf_rss, cutoff_dt, ["美股", "隔夜宏观", "全球股市"], default_sector="海外宏观与地缘政治")
        if items:
            return items
        return await self._fetch_rss_direct(client, "Yahoo Finance", yf_index_rss, cutoff_dt, ["美股", "标普500"], default_sector="海外宏观与地缘政治")

    # =========================================================================
    # 通用 RSS 辅助解析与字段提取函数
    # =========================================================================
    def _extract_rss_entry_fields(self, entry: Any, rss_url: str = "") -> tuple[str, str]:
        """
        解析 feedparser entry，提取并清洗 title 和 content。
        1. 优先提取 entry.content (Atom/RSS2.0 全文)；无全文时依次提取 summary/description。
        2. 清洗 HTML 标签，单向降级确定 final_content 与 final_title。
        """
        raw_title = getattr(entry, "title", "").strip()
        if " - " in raw_title and "Google News" in rss_url:
            raw_title = raw_title.rsplit(" - ", 1)[0].strip()

        # 优先提取 entry.content (RSS/Atom 全文)
        raw_content = ""
        entry_content = getattr(entry, "content", None)
        if isinstance(entry_content, list) and len(entry_content) > 0:
            content_pieces = []
            for item in entry_content:
                if isinstance(item, dict) and "value" in item:
                    content_pieces.append(item["value"])
                elif hasattr(item, "value"):
                    content_pieces.append(getattr(item, "value", ""))
            raw_content = " ".join(content_pieces).strip()

        raw_summary = getattr(entry, "summary", getattr(entry, "description", "")).strip()

        clean_content = self._clean_html(raw_content) if raw_content else ""
        clean_summary = self._clean_html(raw_summary) if raw_summary else ""

        # 单向唯一链条兜底：正文 (全文 -> 摘要 -> 标题)，标题 (原生标题 -> 摘要截取 -> 正文截取)
        final_content = clean_content or clean_summary or raw_title
        final_title = raw_title or (clean_summary[:35] if clean_summary else clean_content[:35])

        return final_title, final_content

    async def _fetch_rss_direct(
        self, client: httpx.AsyncClient, source_name: str, rss_url: str, cutoff_dt: datetime, default_tags: List[str], default_sector: str = "其他板块"
    ) -> List[RawNewsSchema]:
        items: List[RawNewsSchema] = []
        try:
            resp = await client.get(rss_url, headers=self._get_headers(), timeout=self.request_timeout)
            if resp.status_code != 200:
                return []

            feed = feedparser.parse(resp.text)
            for entry in feed.entries:
                published_parsed = getattr(entry, "published_parsed", None) or getattr(entry, "updated_parsed", None)
                if published_parsed:
                    pub_dt = datetime(*published_parsed[:6], tzinfo=timezone.utc)
                else:
                    pub_dt = datetime.now(timezone.utc)

                if not self._is_within_time_window(pub_dt, cutoff_dt):
                    logger.info(f"[{source_name} RSS Early-Exit] 遇到 >{self.max_hours}h 前旧条目，熔断终止。")
                    break

                title, content = self._extract_rss_entry_fields(entry, rss_url)

                items.append(
                    RawNewsSchema(
                        news_id=self._get_next_id(f"rss_{source_name}"),
                        source=source_name,
                        title=title,
                        content=content,
                        publish_time=pub_dt,
                        category_tags=default_tags,
                        sector=default_sector,
                        importance=2 if any(k in title + content for k in ["Fed", "China", "AI", "Chip", "芯片", "关税", "央行"]) else 1,
                        channel_type="rss_channel",
                        raw_payload={"link": getattr(entry, "link", "")},
                    )
                )

            logger.info(f"[{source_name}] 成功解析 {len(items)} 条 {self.max_hours}h 增量资讯！")
            return items
        except Exception as e:
            logger.debug(f"[{source_name} RSS 异常]: {e}")
            return []

    async def _fallback_rsshub(
        self, client: httpx.AsyncClient, source_name: str, route: str, cutoff_dt: datetime, default_sector: str = "其他板块"
    ) -> List[RawNewsSchema]:
        items: List[RawNewsSchema] = []

        for domain in self.rsshub_instances:
            url = f"{domain}{route}"

            try:
                resp = await client.get(url, headers=self._get_headers(), timeout=self.request_timeout)
                if resp.status_code != 200:
                    continue

                feed = feedparser.parse(resp.text)
                for entry in feed.entries:
                    published_parsed = getattr(entry, "published_parsed", None) or getattr(entry, "updated_parsed", None)
                    if published_parsed:
                        pub_dt = datetime(*published_parsed[:6], tzinfo=timezone.utc)
                    else:
                        pub_dt = datetime.now(timezone.utc)

                    if not self._is_within_time_window(pub_dt, cutoff_dt):
                        break

                    title, content = self._extract_rss_entry_fields(entry)

                    items.append(
                        RawNewsSchema(
                            news_id=self._get_next_id(f"rsshub_{source_name}"),
                            source=source_name,
                            title=title,
                            content=content,
                            publish_time=pub_dt,
                            category_tags=["RSSHub资讯"],
                            sector=default_sector,
                            importance=1,
                            channel_type="rsshub",
                            raw_payload={"link": getattr(entry, "link", "")},
                        )
                    )

                if items:
                    logger.info(f"[RSSHub 成功] {source_name} 拉取到 {len(items)} 条增量数据！")
                    return items
            except Exception:
                continue

        return items

    # =========================================================================
    # 14. 高股息板块 (红利/派息/央国企分红) - 专题 RSS 专属源
    # =========================================================================
    async def fetch_high_dividend(self, client: httpx.AsyncClient, cutoff_dt: datetime) -> List[RawNewsSchema]:
        logger.info("[高股息板块] 拉取红利派息、高股息率与央国企市值管理专题资讯...")
        gnews_url = self.source_urls["dividend_gnews"]
        items = await self._fetch_rss_direct(client, "高股息/红利专题", gnews_url, cutoff_dt, ["高股息", "红利板块"], default_sector="高股息/红利板块")
        logger.info(f"[高股息板块] 成功整合 {len(items)} 条高股息/红利专题资讯！")
        return items

    # =========================================================================
    # 15. 低估值板块 (破净/估值修复/破发/回购) - 专题 RSS 专属源
    # =========================================================================
    async def fetch_low_valuation(self, client: httpx.AsyncClient, cutoff_dt: datetime) -> List[RawNewsSchema]:
        logger.info("[低估值板块] 拉取破净、破发、估值修复与股份回购专题资讯...")
        gnews_url = self.source_urls["lowval_gnews"]
        items = await self._fetch_rss_direct(client, "低估值/破净专题", gnews_url, cutoff_dt, ["低估值", "破净板块"])
        logger.info(f"[低估值板块] 成功整合 {len(items)} 条低估值/破净专题资讯！")
        return items

    # =========================================================================
    # 16. 消费板块 (大消费/白酒/食品/零售) - 专题 RSS 专属源
    # =========================================================================
    async def fetch_consumer_sector(self, client: httpx.AsyncClient, cutoff_dt: datetime) -> List[RawNewsSchema]:
        logger.info("[消费板块] 拉取大消费、白酒、零售与消费品牌专题资讯...")
        gnews_url = self.source_urls["consumer_gnews"]
        items = await self._fetch_rss_direct(client, "大消费专题新闻", gnews_url, cutoff_dt, ["大消费", "消费板块"])
        logger.info(f"[消费板块] 成功整合 {len(items)} 条大消费专题资讯！")
        return items

    # =========================================================================
    # 核心并发调度入口：全量 16 大数据源并发轮询
    # =========================================================================
    async def fetch_all_flash_news(self) -> List[RawNewsSchema]:
        now_utc = datetime.now(timezone.utc)
        cutoff_dt = now_utc - timedelta(hours=self.max_hours)
        logger.info(f"🚀 [Data Agent] 开启全量 16 大媒体、专题与投研源 24h 增量并发抓取...")

        async with httpx.AsyncClient(verify=False, follow_redirects=True) as client:
            tasks = [
                # 1. 7x24 直播与证券快讯
                self.fetch_sina_7x24(client, cutoff_dt),
                self.fetch_eastmoney(client, cutoff_dt),
                self.fetch_cailianpress(client, cutoff_dt),
                self.fetch_wallstreetcn(client, cutoff_dt),
                # 2. 硬科技、芯片与 TMT 资讯
                self.fetch_36kr(client, cutoff_dt),
                self.fetch_ithome(client, cutoff_dt),
                self.fetch_tmtpost(client, cutoff_dt),
                self.fetch_eetchina(client, cutoff_dt),
                # 3. AI 大模型与学术/产业前沿
                self.fetch_jiqizhixin(client, cutoff_dt),
                self.fetch_qbitai(client, cutoff_dt),
                # 4. 全球宏观与海外投研
                self.fetch_reuters(client, cutoff_dt),
                self.fetch_bloomberg(client, cutoff_dt),
                self.fetch_yahoofinance(client, cutoff_dt),
                # 5. 三大热门板块专题资讯 (高股息、低估值、消费)
                self.fetch_high_dividend(client, cutoff_dt),
                self.fetch_low_valuation(client, cutoff_dt),
                self.fetch_consumer_sector(client, cutoff_dt),
            ]
            results = await asyncio.gather(*tasks, return_exceptions=True)

        all_news: List[RawNewsSchema] = []
        seen_keys = set()

        for res in results:
            if isinstance(res, Exception):
                logger.error(f"子模块运行异常: {res}")
                continue
            for item in res:
                # 基于新闻标题与发布分钟级的联合 Key 去重，确保完全消除重复新闻
                dedup_key = f"{item.title}_{item.publish_time.strftime('%Y%m%d%H%M') if item.publish_time else ''}"
                if dedup_key not in seen_keys:
                    seen_keys.add(dedup_key)
                    all_news.append(item)

        # 统一按发布时间倒序排列
        all_news.sort(key=lambda x: x.publish_time, reverse=True)

        # 按照增量入库顺序，统一重新赋予从 1 开始严格递增的 news_id (news_1, news_2, news_3...)
        for idx, item in enumerate(all_news, 1):
            item.news_id = f"news_{idx}"

        logger.info(f"🎉 [Data Agent] 全量抓取完成！本轮共成功整合 {len(all_news)} 条增量唯一资讯卡片 (已按入库顺序赋予自增 ID: news_1 ~ news_{len(all_news)})。")
        return all_news