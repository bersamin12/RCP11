"""Provider-agnostic model layer (PRD X.5). Default: OpenRouter + DeepSeek."""

import json
import re
from typing import TypeVar

from langchain_core.messages import HumanMessage, SystemMessage
from langchain_openai import ChatOpenAI
from pydantic import BaseModel, ValidationError

from rcp.config import get_settings

T = TypeVar("T", bound=BaseModel)


def get_chat_model(temperature: float | None = None) -> ChatOpenAI:
    s = get_settings()
    kwargs: dict = {}
    if s.rcp_reasoning:
        kwargs["extra_body"] = {"reasoning": {"enabled": True}}
    return ChatOpenAI(
        model=s.rcp_model,
        api_key=s.openrouter_api_key,
        base_url=s.rcp_base_url,
        temperature=s.rcp_temperature if temperature is None else temperature,
        timeout=180,
        **kwargs,
    )


def _extract_json(text: str) -> str:
    text = re.sub(r"```(?:json)?", "", text).strip("` \n")
    start = min((i for i in (text.find("{"), text.find("[")) if i >= 0), default=-1)
    if start < 0:
        raise ValueError(f"no JSON found in model output: {text[:200]}")
    # Walk to the matching close bracket of the first JSON value.
    decoder = json.JSONDecoder()
    obj, _end = decoder.raw_decode(text[start:])
    return json.dumps(obj)


def llm_json(prompt: str, schema: type[T], system: str = "", retries: int = 2) -> T:
    """Ask the model for JSON matching a pydantic schema; validate and retry on failure."""
    model = get_chat_model()
    sys_text = (
        (system + "\n\n" if system else "")
        + "Respond with ONLY a JSON object matching this JSON Schema (no prose, no code fences):\n"
        + json.dumps(schema.model_json_schema(), indent=None)
    )
    messages = [SystemMessage(content=sys_text), HumanMessage(content=prompt)]
    last_err: Exception | None = None
    for _ in range(retries + 1):
        reply = model.invoke(messages)
        text = reply.content if isinstance(reply.content, str) else str(reply.content)
        try:
            return schema.model_validate_json(_extract_json(text))
        except (ValueError, ValidationError) as err:
            last_err = err
            messages += [reply, HumanMessage(content=f"Invalid: {err}. Return ONLY corrected JSON.")]
    raise RuntimeError(f"LLM did not produce valid {schema.__name__}: {last_err}")
