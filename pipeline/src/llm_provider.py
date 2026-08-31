"""LLM provider wrapper module supporting vLLM local server and OpenAI API compat."""

import time
import requests
from typing import Optional
from langchain_core.language_models.chat_models import BaseChatModel
from langchain_openai import ChatOpenAI
from pipeline.src.config import Config, config as default_config, is_kaggle_environment


def check_vllm_health(api_base: str, timeout: int = 3) -> bool:
    """Check if the LLM server endpoint (vLLM, Ollama, or OpenAI-compatible) is responsive."""
    try:
        base = api_base.rstrip("/")
        # 1. Check standard OpenAI /v1/models endpoint
        models_url = f"{base}/models" if base.endswith("/v1") else f"{base}/v1/models"
        try:
            r = requests.get(models_url, timeout=timeout)
            if r.status_code == 200:
                return True
        except Exception:
            pass

        # 2. Check root / or /health
        root_url = base.replace("/v1", "")
        for ep in ["", "/health"]:
            try:
                r = requests.get(f"{root_url}{ep}", timeout=timeout)
                if r.status_code == 200:
                    return True
            except Exception:
                pass
        return False
    except Exception:
        return False


def get_llm(
    cfg: Optional[Config] = None,
    temperature: Optional[float] = None,
    max_tokens: Optional[int] = None,
    timeout: Optional[int] = None,
    max_retries: Optional[int] = None,
    **kwargs,
) -> BaseChatModel:
    """Factory function to instantiate ChatOpenAI connecting to self-hosted vLLM or local Ollama server."""
    cfg = cfg or default_config
    temp = temperature if temperature is not None else cfg.TEMPERATURE
    tokens = max_tokens if max_tokens is not None else cfg.MAX_TOKENS

    # Read environment variables directly to ensure runtime overrides (e.g. Kaggle Ollama at port 11434) are honored
    import os
    model_name = os.getenv("MODEL_NAME", cfg.MODEL_NAME)
    api_base = os.getenv("LLM_API_BASE", cfg.LLM_API_BASE)
    api_key = os.getenv("LLM_API_KEY", cfg.LLM_API_KEY)

    # Set timeout to 30s max
    raw_timeout = timeout if timeout is not None else getattr(cfg, "LLM_TIMEOUT", 30)
    effective_timeout = min(raw_timeout, 30)
    retries = max_retries if max_retries is not None else getattr(cfg, "MAX_RETRIES", 2)

    # Disable thinking mode for Qwen / DeepSeek models on Ollama by setting think=False
    model_kwargs = kwargs.pop("model_kwargs", {})
    extra_body = model_kwargs.pop("extra_body", {})
    extra_body.update({
        "think": False,
        "options": {
            "think": False,
            "temperature": temp,
        }
    })
    model_kwargs["extra_body"] = extra_body

    llm_kwargs = {
        "model": model_name,
        "base_url": api_base,
        "api_key": api_key,
        "temperature": temp,
        "max_tokens": tokens,
        "timeout": effective_timeout,
        "request_timeout": effective_timeout,
        "max_retries": retries,
        "streaming": False,
        "model_kwargs": model_kwargs,
        **kwargs,
    }

    return ChatOpenAI(**llm_kwargs)



