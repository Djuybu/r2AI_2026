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
    MODEL_NAME: str = os.getenv("MODEL_NAME", "qwen3.5:9b")
    LLM_API_BASE: str = os.getenv(
        "LLM_API_BASE",
        "http://localhost:11434/v1" if is_kaggle_environment() else "http://localhost:11434/v1",
    )
    LLM_API_KEY: str = os.getenv("LLM_API_KEY", "ollama")
    TEMPERATURE: float = float(os.getenv("TEMPERATURE", "0.0"))
    MAX_TOKENS: int = int(os.getenv("MAX_TOKENS", "1024"))

    # vLLM Server Settings
    VLLM_PORT: int = int(os.getenv("VLLM_PORT", "8000"))
    VLLM_GPU_MEMORY_UTIL: float = float(os.getenv("VLLM_GPU_MEMORY_UTIL", "0.85"))
    VLLM_MAX_MODEL_LEN: int = int(os.getenv("VLLM_MAX_MODEL_LEN", "4096"))

    # Paths
    BASE_DIR: Path = Path("/kaggle/working/r2AI_2026/pipeline") if is_kaggle_environment() else Path(__file__).resolve().parent.parent
    DATA_DIR: Path = Path(os.getenv("DATA_DIR", BASE_DIR / "data"))
    PROMPTS_DIR: Path = Path(os.getenv("PROMPTS_DIR", BASE_DIR / "src" / "prompts"))

    # Agent Execution Settings
    MAX_RETRIES: int = int(os.getenv("MAX_RETRIES", "1"))
    EXECUTION_TIMEOUT: int = int(os.getenv("EXECUTION_TIMEOUT", "50"))
    LLM_TIMEOUT: int = int(os.getenv("LLM_TIMEOUT", "3"))
    USE_FAST_PATH: bool = False

    def __post_init__(self):
        """Resolve relative paths dynamically for robustness."""
        self.DATA_DIR = self._resolve_path("DATA_DIR", self.DATA_DIR)
        self.PROMPTS_DIR = self._resolve_path("PROMPTS_DIR", self.PROMPTS_DIR)

    def _resolve_path(self, env_var_name: str, default_path: Path) -> Path:
        val = os.getenv(env_var_name)
        if not val:
            return default_path.resolve()

        path = Path(val)
        if path.is_absolute():
            return path.resolve()

        # Try CWD
        cwd_resolved = path.resolve()
        if cwd_resolved.exists():
            return cwd_resolved

        # Try relative to BASE_DIR
        base_resolved = (self.BASE_DIR / path).resolve()
        if base_resolved.exists():
            return base_resolved

        # Try relative to BASE_DIR.parent (workspace root)
        workspace_resolved = (self.BASE_DIR.parent / path).resolve()
        if workspace_resolved.exists():
            return workspace_resolved

        return default_path.resolve()

    def get_prompt_path(self, filename: str) -> Path:
        """Get absolute path to a prompt template YAML file."""
        return self.PROMPTS_DIR / filename



# Global default configuration instance
config = Config()
