"""LLM provider wrapper module supporting vLLM local server and OpenAI API compat."""

import time
import requests
from typing import Optional
from langchain_core.language_models.chat_models import BaseChatModel
from langchain_openai import ChatOpenAI
from pipeline.src.config import Config, config as default_config, is_kaggle_environment


def check_vllm_health(api_base: str, timeout: int = 2) -> bool:
    """Check if the vLLM server endpoint is responsive."""
    try:
        # Extract base URL (remove /v1 if present)
        health_url = api_base.rstrip("/").replace("/v1", "") + "/health"
        response = requests.get(health_url, timeout=timeout)
        return response.status_code == 200
    except Exception:
        return False


def get_llm(
    cfg: Optional[Config] = None,
    temperature: Optional[float] = None,
    max_tokens: Optional[int] = None,
) -> BaseChatModel:
    """Factory function to instantiate ChatOpenAI connecting to self-hosted vLLM or local server."""
    cfg = cfg or default_config
    temp = temperature if temperature is not None else cfg.TEMPERATURE
    tokens = max_tokens if max_tokens is not None else cfg.MAX_TOKENS

    # Construct server URL
    api_base = cfg.LLM_API_BASE

    return ChatOpenAI(
        model=cfg.MODEL_NAME,
        openai_api_base=api_base,
        openai_api_key=cfg.LLM_API_KEY,
        temperature=temp,
        max_tokens=tokens,
        streaming=False,
    )
