import json
import logging
from functools import lru_cache
from pathlib import Path
from typing import Any


POLICY_PATH = Path(__file__).resolve().parents[2] / "config" / "guardrails_policy.json"


logger = logging.getLogger(__name__)


@lru_cache(maxsize=1)
def get_guardrails_policy() -> dict[str, Any]:
    logger.info("Carregando guardrails de %s", POLICY_PATH)
    with POLICY_PATH.open("r", encoding="utf-8") as policy_file:
        return json.load(policy_file)


def get_guidance_message() -> str:
    policy = get_guardrails_policy()
    guidance = policy.get("guidance_message")
    if isinstance(guidance, str) and guidance.strip():
        return guidance
    return "Pergunta fora do escopo suportado para as ferramentas disponíveis."


def guardrails_policy_for_prompt() -> str:
    policy = get_guardrails_policy()
    return json.dumps(policy, ensure_ascii=True, indent=2)
