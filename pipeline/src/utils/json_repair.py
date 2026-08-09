"""JSON Repair utility module for handling truncated or malformed LLM outputs."""

import json
import logging
from typing import Any, Dict
import json_repair

logger = logging.getLogger(__name__)


def safe_parse_json(content: str) -> Dict[str, Any]:
    """Parse JSON string with automatic repair fallback.
    
    Args:
        content: Raw string response from LLM
        
    Returns:
        Parsed dictionary.
    """
    if not content or not content.strip():
        return {}

    # Strip markdown codeblocks if present
    cleaned = content.strip()
    if cleaned.startswith("```json"):
        cleaned = cleaned[7:]
    elif cleaned.startswith("```"):
        cleaned = cleaned[3:]
    if cleaned.endswith("```"):
        cleaned = cleaned[:-3]
    cleaned = cleaned.strip()

    # Direct JSON parse attempt
    try:
        return json.loads(cleaned)
    except json.JSONDecodeError:
        logger.warning("Direct JSON decode failed, attempting json-repair...")

    # Fallback with json_repair
    try:
        repaired = json_repair.repair_json(cleaned, return_objects=True)
        if isinstance(repaired, dict):
            return repaired
        elif isinstance(repaired, str):
            return json.loads(repaired)
        return {}
    except Exception as e:
        logger.error(f"Failed to repair JSON output: {e}")
        return {}
