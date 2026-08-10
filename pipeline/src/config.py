"""Configuration module for Cocopila Agent Pipeline."""

import os
from dataclasses import dataclass
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()


def is_kaggle_environment() -> bool:
    """Check if the execution environment is Kaggle."""
    return os.path.exists("/kaggle/working")


@dataclass
class Config:
    """System configuration parameters."""

    # LLM Settings
    MODEL_NAME: str = os.getenv("MODEL_NAME", "Qwen/Qwen3.5-2B")
    LLM_API_BASE: str = os.getenv(
        "LLM_API_BASE",
        "http://localhost:8000/v1" if is_kaggle_environment() else "http://localhost:8000/v1",
    )
    LLM_API_KEY: str = os.getenv("LLM_API_KEY", "EMPTY")
    TEMPERATURE: float = float(os.getenv("TEMPERATURE", "0.0"))
    MAX_TOKENS: int = int(os.getenv("MAX_TOKENS", "1024"))

    # vLLM Server Settings
    VLLM_PORT: int = int(os.getenv("VLLM_PORT", "8000"))
    VLLM_GPU_MEMORY_UTIL: float = float(os.getenv("VLLM_GPU_MEMORY_UTIL", "0.85"))
    VLLM_MAX_MODEL_LEN: int = int(os.getenv("VLLM_MAX_MODEL_LEN", "4096"))

    # Paths
    BASE_DIR: Path = Path("/kaggle/working/cocopila") if is_kaggle_environment() else Path(__file__).resolve().parent.parent
    DATA_DIR: Path = Path(os.getenv("DATA_DIR", BASE_DIR / "data"))
    PROMPTS_DIR: Path = Path(os.getenv("PROMPTS_DIR", BASE_DIR / "src" / "prompts"))

    # Agent Execution Settings
    MAX_RETRIES: int = int(os.getenv("MAX_RETRIES", "3"))
    EXECUTION_TIMEOUT: int = int(os.getenv("EXECUTION_TIMEOUT", "10"))

    def get_prompt_path(self, filename: str) -> Path:
        """Get absolute path to a prompt template YAML file."""
        return self.PROMPTS_DIR / filename


# Global default configuration instance
config = Config()
