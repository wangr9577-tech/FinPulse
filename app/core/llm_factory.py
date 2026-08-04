"""
LangChain / LangGraph 环境集成与 LLM 工厂模块 (LLM Factory)
配置 API Key、超时控制、指数退避重试 (Tenacity) 及 V4-Flash / V4-Pro 双阶模型实例化
内建无 Key 状态下的 Graceful Fallback / Dummy LLM 运行机制
"""
import os
from typing import Dict, Any, Optional, List
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type

from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import BaseMessage, HumanMessage, AIMessage, SystemMessage
from langchain_core.outputs import ChatResult, ChatGeneration
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.runnables import RunnableSequence
from langgraph.graph import StateGraph, START, END

from app.core.logger import app_logger, log_agent_action


class DummyMockLLM(BaseChatModel):
    """
    当缺少真实 LLM API Key 或处于测试环境时使用的 Dummy LLM 兜底实现
    完全遵循 LangChain BaseChatModel 接口契约
    """
    model_name: str = "Mock-V4-Flash-Dummy"

    def _generate(
        self,
        messages: List[BaseMessage],
        stop: Optional[List[str]] = None,
        run_manager: Optional[Any] = None,
        **kwargs: Any,
    ) -> ChatResult:
        last_msg = messages[-1].content if messages else ""
        mock_response = (
            f"[Dummy LLM Output ({self.model_name})]: 已成功接收 Prompt 请求 ('{last_msg[:40]}...')。"
            f"系统响应正常，LangChain 管道联调测试通过！"
        )
        generation = ChatGeneration(message=AIMessage(content=mock_response))
        return ChatResult(generations=[generation])

    @property
    def _llm_type(self) -> str:
        return "dummy_mock_llm"


from pathlib import Path
from dotenv import load_dotenv

# 自动加载根目录或 backend 目录的 .env 文件
env_path_root = Path(__file__).resolve().parent.parent.parent.parent / ".env"
env_path_backend = Path(__file__).resolve().parent.parent.parent / ".env"
if env_path_root.exists():
    load_dotenv(dotenv_path=env_path_root)
elif env_path_backend.exists():
    load_dotenv(dotenv_path=env_path_backend)
else:
    load_dotenv()


class LLMFactory:
    """
    LLM 工厂：管理 Data Agent (Flash) 与 Analyst Agent (Pro) 的 LangChain 实例化
    支持自动从 .env 文件读取 API Key、Base URL 及模型选型
    """
    def __init__(
        self,
        api_key: Optional[str] = None,
        base_url: Optional[str] = None,
        request_timeout: float = 30.0,
        max_retries: int = 3
    ):
        self.api_key = api_key or os.getenv("LLM_API_KEY") or os.getenv("OPENAI_API_KEY") or os.getenv("GEMINI_API_KEY")
        self.base_url = base_url or os.getenv("LLM_BASE_URL", "https://api.openai.com/v1")
        self.request_timeout = request_timeout
        self.max_retries = max_retries
        self.flash_model_name = os.getenv("FLASH_MODEL_NAME", "gpt-4o-mini")
        self.pro_model_name = os.getenv("PRO_MODEL_NAME", "gpt-4o")

    def _is_invalid_key(self, key: Optional[str]) -> bool:
        if not key:
            return True
        k = key.lower()
        return k.startswith("mock") or k.startswith("your_") or "here" in k

    def get_flash_llm(self) -> BaseChatModel:
        """
        获取第二层 Data Agent 初筛模型 (V4-Flash / DeepSeek-Chat)
        要求：极高吞吐、低延迟、格式化打分与实体提取
        """
        if self._is_invalid_key(self.api_key):
            app_logger.warning(
                f"⚠️未检测到真实 LLM API Key (当前为占位符)，已启动 Dummy Mock LLM ({self.flash_model_name} 模式)。"
                f"如需接入真实 DeepSeek 模型，请在 .env 中填入您的真实 sk-xxx 密钥。"
            )
            return DummyMockLLM(model_name=f"Mock-{self.flash_model_name}")

        try:
            from langchain_openai import ChatOpenAI
            return ChatOpenAI(
                model=self.flash_model_name,
                api_key=self.api_key,
                base_url=self.base_url,
                timeout=self.request_timeout,
                max_retries=self.max_retries,
                temperature=0.1
            )
        except Exception as e:
            app_logger.error(f"LangChain DeepSeek/OpenAI 初始化异常: {e}，自动回退至 Dummy LLM")
            return DummyMockLLM(model_name=f"Mock-{self.flash_model_name}")

    def get_pro_llm(self) -> BaseChatModel:
        """
        获取第三层 Analyst Agent 深度研报模型 (V4-Pro 思考模式 / DeepSeek-Reasoner)
        要求：长文本推理、深度归因与逻辑研报撰写
        """
        if self._is_invalid_key(self.api_key):
            app_logger.warning(
                f"⚠️未检测到真实 LLM API Key (当前为占位符)，已启动 Dummy Mock LLM ({self.pro_model_name} 模式)。"
                f"如需接入真实 DeepSeek 模型，请在 .env 中填入您的真实 sk-xxx 密钥。"
            )
            return DummyMockLLM(model_name=f"Mock-{self.pro_model_name}")

        try:
            from langchain_openai import ChatOpenAI
            return ChatOpenAI(
                model=self.pro_model_name,
                api_key=self.api_key,
                base_url=self.base_url,
                timeout=self.request_timeout,
                max_retries=self.max_retries,
                temperature=0.3
            )
        except Exception as e:
            app_logger.error(f"原厂 LangChain Pro 初始化失败: {e}，回退至 Dummy LLM")
            return DummyMockLLM(model_name=f"Mock-{self.pro_model_name}")

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=2, max=10),
        retry=retry_if_exception_type(Exception),
        reraise=True
    )
    def invoke_with_circuit_breaker(self, llm: BaseChatModel, prompt: str) -> str:
        """带指数退避重试 (Tenacity) 与超时熔断机制的底层调用封装"""
        log_agent_action("LangChain-LLM", "Invoking", f"Prompt length: {len(prompt)}")
        res = llm.invoke([HumanMessage(content=prompt)])
        return res.content


def build_demo_langgraph_pipeline():
    """
    构建并返回一个最小化 LangGraph 工作流图 (StateGraph Demo)
    演示 7.28 规划中 LangGraph Agent 逻辑节点的组合能力
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
