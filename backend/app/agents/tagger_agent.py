"""
Tagger Agent (金融打标与板块分类智能体)
职责单一：
1. 专注于金融语义分析与实体-板块精准对齐
2. 严格按【东方财富 86 个官方行业分类标准】与【国内/国外宏观】进行两级分类
3. 提取核心概念、细分赛道与主题标签 (category_tags)
4. 判定事件类型 (event_type)
"""
import re
import json
from typing import Dict, List, Optional, Any
from pydantic import BaseModel, Field

from app.core.logger import app_logger, log_agent_action
from app.core.llm_factory import LLMFactory


class TaggingResult(BaseModel):
    """打标智能体标准化输出结果"""
    category_type: str = Field(..., description="一级分类: 宏观 / 行业板块")
    sub_category: str = Field(..., description="二级细分: 国内宏观/国外宏观 或 东方财富 86 个官方标准行业板块名称")
    sector: str = Field(..., description="所属板块标准名称 (与 sub_category 保持一致)")
    event_type: str = Field(..., description="事件分类: 宏观政策 / 产业动态 / 公司业绩 / 地缘政治 / 市场流动性 / 其他")
    category_tags: List[str] = Field(default_factory=list, description="细分概念/主题/产业链环节标签列表")


TAGGER_SYSTEM_PROMPT = """你是一位资深的买方金融投研分类与标签专家。
你的唯一任务是：深入分析给定的财经新闻/快讯内容，严格按照【东方财富行业分类标准】与【宏观分类体系】进行高精度的板块归属判定与概念打标。

请严格遵守以下分类与打标规则：

【两阶段分类流程 —— 必须严格“先大分类，后小分类”，顺序不可颠倒】：

1. 【第一阶段：大类判定 (category_type)】
   - 只能输出 "宏观" 或 "行业板块" 之一。
   - 这是第一步：务必先判定出 category_type，再进入第二阶段的细分；严禁跳过本步直接细分。
   - 判定依据：新闻主体围绕宏观政策 / 经济总量与宏观指标 / 央行货币政策 / 全球宏观与流动性 → "宏观"；围绕具体产业、具体公司、具体个股及其产品、业绩、成交 → "行业板块"。
   - 【个股/板块成交量 与 宏观流动性的关键区分 —— 必须严格掌握】：
     * 只涉及"单只个股 或 某一板块"的成交额、成交量、换手率、量价异动、个股资金流向 → 属于"个股/板块交易行为"，category_type 必须为 "行业板块"，归入该股（或该板块）所属的东方财富行业；其 event_type 一般为 "产业动态" 或 "其他"。
     * 只有涉及"市场整体 / 宏观资金面"的表述 —— 如 沪深两市全市场成交总量、央行公开市场操作、DR007/SHIBOR、社融、M2、准备金率、LPR、北向全市场资金净流入、全市场融资融券余额 —— 才归 "宏观"，event_type 为 "市场流动性"。

2. 【第二阶段：细分分类 (sub_category & sector)】
   - 必须依据第一阶段判定的 category_type 走对应分支（category_type 为哪个，就只走哪个分支）：
   - 若 category_type 为 "宏观"：
     * 国内宏观：涉及中国央行、货币政策、降准降息、财政赤字与发债、发改委宏观调控、国内GDP/PMI/社融/通胀(CPI/PPI)等经济指标、国内金融监管，输出 "国内宏观"
     * 国外宏观：涉及美联储/海外央行政策、美债收益率、美元/外汇汇率波动、海外地缘政治、国际大宗商品异动、全球宏观经济，输出 "国外宏观"
   - 若 category_type 为 "行业板块"：
     必须精准归入以下【东方财富 86 个官方标准行业板块库】中的一个具体行业名称（严禁自造词，必须 100% 严格使用东财官方标准板块名称）：
     【电子与硬科技】：半导体、消费电子、光学光电子、元件、电子化学品、电子元件、软件开发、互联网服务、计算机设备、IT服务、通信设备、通信服务、游戏、数字媒体、影视院线、广告营销、出版
     【高端制造与新能源】：光伏设备、电池、风电设备、电网设备、电源设备、汽车整车、汽车零部件、汽车服务、电机、通用设备、专用设备、自动化设备、工程机械、仪器仪表、轨交设备、航空机场、航天航空、船舶制造
     【医药生物与大健康】：化学制药、中药、生物制品、医疗器械、医疗服务、医药商业
     【大消费与商贸农业】：酿酒行业、食品饮料、农牧饲渔、农化制品、商业百货、旅游酒店、美容护理、纺织服装、家电行业、轻工制造、家居用品
     【大金融与地产建材】：银行、证券、保险、多元金融、房地产开发、房地产服务、工程建设、水泥建材、装修装饰、装修建材
     【周期与能源资源】：有色金属、贵金属、小金属、钢铁行业、煤炭行业、石油行业、燃气、化学原料、化学制品、橡胶制品、塑料制品、玻璃玻纤、造纸印刷
     【公用环保与交运物流】：电力行业、公用事业、环保行业、综合行业、航运港口、公路铁路、物流行业

3. 【事件类型 (event_type)】
   只能从以下枚举中选择一个最匹配的类型：
   - "宏观政策"：央行、财政部、发改委等部委政策出台与调控
   - "产业动态"：行业技术突破、产能扩建、产业规划、上下游供需变化
   - "公司业绩"：财报披露、业绩预告、分红、营收与净利异动
   - "地缘政治"：国际冲突、贸易摩擦、制裁与出口管制
   - "市场流动性"：仅指市场整体/宏观资金面 —— 央行公开市场操作、DR007/SHIBOR、社融、M2、准备金率、LPR、全市场成交总量、北向全市场资金、全市场融资融券余额、ETF申赎。单只个股或单一板块的成交额/换手/量价异动属"个股交易行为"，应归其所属行业板块，本类除外。
   - "其他"：无法明确归入上述分类的常规市场资讯

4. 【概念与主题打标 (category_tags)】
   提炼 2~5 个代表该新闻核心概念、产业链环节或市场热点的标签（例如：`["先进封装", "第三代半导体", "国产替代"]`、`["固态电池", "低空经济", "海外建厂"]` 等）。

【输出格式要求】：
必须且只能输出严格的纯 JSON 对象，格式如下：
{
  "category_type": "行业板块",
  "sub_category": "半导体",
  "sector": "半导体",
  "event_type": "产业动态",
  "category_tags": ["芯片设计", "先进制程", "算力芯片"]
}
或（宏观示例）：
{
  "category_type": "宏观",
  "sub_category": "国内宏观",
  "sector": "国内宏观",
  "event_type": "宏观政策",
  "category_tags": ["货币政策", "降准降息", "流动性投放"]
}
"""


class TaggerAgent:
    """
    TaggerAgent：独立的金融新闻分类与概念打标智能体
    """
    def __init__(self, llm_factory: Optional[LLMFactory] = None):
        self.llm_factory = llm_factory or LLMFactory()
        self.llm = self.llm_factory.get_llm()

    def _repair_json_string(self, text: str) -> str:
        """强化版 JSON 字符串修补与清洗"""
        clean_text = text.strip()

        # 1. 剥离 Markdown 代码块包裹
        if "```json" in clean_text:
            clean_text = clean_text.split("```json")[1].split("```")[0].strip()
        elif "```" in clean_text:
            clean_text = clean_text.split("```")[1].split("```")[0].strip()

        # 2. 查找首个 '{' 和最后一个 '}'
        start_idx = clean_text.find('{')
        if start_idx != -1:
            clean_text = clean_text[start_idx:]

        # 3. 若结尾缺少 '}' 则修补补齐
        end_idx = clean_text.rfind('}')
        if end_idx != -1:
            clean_text = clean_text[:end_idx + 1]
        else:
            clean_text += '}'

        # 4. 修复尾随逗号
        clean_text = re.sub(r',\s*\}', '}', clean_text)
        clean_text = re.sub(r',\s*\]', ']', clean_text)

        return clean_text

    def _parse_llm_json_response(self, response_text: str) -> TaggingResult:
        """从 LLM 返回的文本中解析 TaggingResult"""
        try:
            clean_json_str = self._repair_json_string(response_text)
            data = json.loads(clean_json_str)

            # 必需字段校验
            required = ["category_type", "sub_category", "event_type"]
            missing = [f for f in required if f not in data or not data[f]]
            if missing:
                app_logger.error(f"[Tagger Agent] LLM 返回缺少分类必需字段: {missing}")
                raise ValueError(f"[Tagger Agent] LLM 返回缺少必需字段: {missing}")

            cat_type = data.get("category_type", "行业板块").strip()
            if cat_type not in ["宏观", "行业板块"]:
                # 兜底只依据 sub_category 是否显式含"宏观"来归宏观，否则一律归行业板块；
                # 不用"国内/海外/国外"等宽泛关键字，避免把个股/板块成交类误掰成宏观。
                cat_type = "宏观" if "宏观" in str(data.get("sub_category", "")) else "行业板块"

            sub_cat = data.get("sub_category", "").strip()
            sector = data.get("sector", "").strip() or sub_cat
            event_type = data.get("event_type", "产业动态").strip()
            tags = data.get("category_tags", [])
            if isinstance(tags, str):
                tags = [tags]

            return TaggingResult(
                category_type=cat_type,
                sub_category=sub_cat,
                sector=sector,
                event_type=event_type,
                category_tags=tags
            )
        except Exception as e:
            app_logger.error(f"[Tagger Agent] JSON 解析失败: {e}, 原始内容: {response_text[:200]}")
            raise ValueError(f"Tagger Agent JSON 解析失败: {e}")

    def tag(
        self,
        news_item: Dict[str, Any],
        extracted_facts: Optional[List[str]] = None,
        entities: Optional[List[str]] = None
    ) -> TaggingResult:
        """单篇新闻资讯打标与板块分类主入口"""
        news_id = news_item.get("news_id", "unknown")
        title = news_item.get("title") or ""
        content = news_item.get("content", "")
        source = news_item.get("source", "")
        existing_tags = news_item.get("category_tags", [])

        context_parts = [
            f"新闻标题: {title}",
            f"新闻正文: {content}",
            f"新闻来源: {source}",
        ]
        if existing_tags:
            context_parts.append(f"原始预置标签: {existing_tags}")
        if extracted_facts:
            context_parts.append(f"提取核心事实: {' | '.join(extracted_facts)}")
        if entities:
            context_parts.append(f"涉及核心实体: {', '.join(entities)}")

        user_prompt = "\n".join(context_parts)
        log_agent_action("TaggerAgent", "Tagging", f"news_id={news_id}")

        try:
            prompt = f"{TAGGER_SYSTEM_PROMPT}\n\n【待打标新闻】:\n{user_prompt}"
            response_text = self.llm_factory.invoke_with_circuit_breaker(self.llm, prompt)
            result = self._parse_llm_json_response(response_text)
            app_logger.info(f"[Tagger Agent] 成功打标 (news_id={news_id}, 板块={result.sector}, 类型={result.category_type}, 事件={result.event_type})")
            return result
        except Exception as e:
            app_logger.error(f"[Tagger Agent] 执行打标异常: {e}")
            raise e

    def tag_batch(self, news_list: List[Dict[str, Any]]) -> List[TaggingResult]:
        """批量新闻打标接口"""
        results = []
        log_agent_action("TaggerAgent", "BatchTagging", f"Processing {len(news_list)} items")
        for item in news_list:
            res = self.tag(item)
            results.append(res)
        return results
