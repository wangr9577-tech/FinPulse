"""
LangChain / LangGraph 环境集成与 LLM 工厂模块 (LLM Factory)
配置 API Key、超时控制、指数退避重试 (Tenacity) 及 V4-Flash / V4-Pro 双阶模型实例化
绝无 Dummy / Mock 兜底逻辑，若配置不完整或 API 调用失败则直接抛出异常
"""
import os
from typing import Dict, Any, Optional, List
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type

from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import HumanMessage
from langchain_openai import ChatOpenAI
from langgraph.graph import StateGraph, START, END

from app.core.config import settings
from app.core.logger import app_logger, log_agent_action


class LLMFactory:
    """
    LLM 工厂：管理 Data Agent (Flash) 与 Analyst Agent (Pro) 的 LangChain 实例化
    纯净从系统配置中心 (app.core.config.settings) 读取配置，无 Key 或调用失败时抛出异常
    """
    def __init__(self):
        self.api_key = settings.LLM_API_KEY
        self.base_url = settings.LLM_BASE_URL
        self.request_timeout = settings.LLM_REQUEST_TIMEOUT
        self.max_retries = settings.LLM_MAX_RETRIES
        self.model_name = settings.LLM_MODEL_NAME

        if not self.api_key:
            raise ValueError("未检测到有效的 LLM_API_KEY！请在 .env 配置文件中设置 LLM_API_KEY。")

    def get_llm(self) -> BaseChatModel:
        """
        获取统一 LLM 智能体模型 (读取 LLM_MODEL_NAME)
        """
        return ChatOpenAI(
            model=self.model_name,
            api_key=self.api_key,
            base_url=self.base_url,
            timeout=self.request_timeout,
            max_retries=self.max_retries,
            temperature=0.1
        )

    def get_flash_llm(self) -> BaseChatModel:
        """兼容性接口：获取统一 LLM 模型"""
        return self.get_llm()

    def get_pro_llm(self) -> BaseChatModel:
        """兼容性接口：获取统一 LLM 模型"""
        return self.get_llm()

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=2, max=10),
        retry=retry_if_exception_type(Exception),
        reraise=True
    )
    def invoke_with_circuit_breaker(self, llm: BaseChatModel, prompt: str) -> str:
        """带指数退避重试 (Tenacity) 与超时熔断机制的底层调用封装

        注意：DeepSeek 在高并发/过载时可能返回 HTTP 200 但 content 为空字符串，
        空字符串不会触发 ChatOpenAI 内部异常，从而绕过 Tenacity 重试，最终在
        下游 json.loads("") 处抛 JSONDecodeError 使整条流水线崩溃。
        这里将「空回包」显式升维为可重试异常，让 Tenacity 真正退避重试。
        """
        log_agent_action("LangChain-LLM", "Invoking", f"Prompt length: {len(prompt)}")
        res = llm.invoke([HumanMessage(content=prompt)])
        content = res.content
        if content is None or not str(content).strip():
            raise ValueError("LLM 返回空内容 (HTTP 200 但无正文)，视为可重试失败")
        return content


def build_demo_langgraph_pipeline():
    """
    构建并返回一个最小化 LangGraph 工作流图 (StateGraph Demo)
    演示 LangGraph Agent 逻辑节点的组合能力
    """
    class AgentState(dict):
        news_input: str
        cleaned_text: str
        data_agent_score: int
        analysis_summary: str

    def node_clean_text(state: AgentState) -> AgentState:
        text = state.get("news_input", "").strip()
        state["cleaned_text"] = f"[Cleaned] {text}"
        return state

    def node_data_agent_screen(state: AgentState) -> AgentState:
        factory = LLMFactory()
        llm = factory.get_flash_llm()
        prompt = f"评估此新闻重要度: {state['cleaned_text']}"
        res = factory.invoke_with_circuit_breaker(llm, prompt)
        state["data_agent_score"] = 5
        state["analysis_summary"] = str(res)
        return state

    workflow = StateGraph(AgentState)
    workflow.add_node("clean_text", node_clean_text)
    workflow.add_node("data_agent_screen", node_data_agent_screen)

    workflow.add_edge(START, "clean_text")
    workflow.add_edge("clean_text", "data_agent_screen")
    workflow.add_edge("data_agent_screen", END)

    return workflow.compile()
