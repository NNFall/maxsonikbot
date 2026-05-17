from __future__ import annotations

import asyncio
import json
import logging
import re
import time
from typing import Any

import requests

from config import load_config
from prompts.dream_prompts import followup_user_prompt, full_user_prompt, system_prompt, teaser_user_prompt

logger = logging.getLogger(__name__)

HTML_TAG_RE = re.compile(r"<[^>]+>")

SECTION_TITLES = {
    "короткое толкование": "🌙 Короткое толкование",
    "краткое значение": "🌙 Краткое значение",
    "символы и знаки": "🔮 Символы и знаки",
    "предупреждение": "⚠️ Предупреждение",
    "эмоциональный смысл": "💭 Эмоциональный смысл",
    "практический совет": "🧭 Практический совет",
    "уточнение по сну": "💬 Уточнение по сну",
}


def _extract_text_from_json(payload: dict[str, Any]) -> str | None:
    choices = payload.get("choices")
    if isinstance(choices, list) and choices:
        first = choices[0]
        if isinstance(first, dict):
            message = first.get("message")
            if isinstance(message, dict):
                content = message.get("content")
                if isinstance(content, str) and content.strip():
                    return content.strip()
            text = first.get("text")
            if isinstance(text, str) and text.strip():
                return text.strip()

    output = payload.get("output")
    if isinstance(output, str) and output.strip():
        return output.strip()
    if isinstance(output, list) and output:
        text = "\n".join(item for item in output if isinstance(item, str)).strip()
        if text:
            return text
    return None


def _html_to_markdown(text: str) -> str:
    text = re.sub(r"<\s*b\s*>(.*?)<\s*/\s*b\s*>", r"**\1**", text, flags=re.IGNORECASE | re.DOTALL)
    text = re.sub(r"<\s*i\s*>(.*?)<\s*/\s*i\s*>", r"_\1_", text, flags=re.IGNORECASE | re.DOTALL)
    text = re.sub(r"<\s*code\s*>(.*?)<\s*/\s*code\s*>", r"`\1`", text, flags=re.IGNORECASE | re.DOTALL)
    return HTML_TAG_RE.sub("", text)


def _section_key(line: str) -> str:
    value = line.strip()
    value = re.sub(r"^[\s>*_`#-]+|[\s>*_`#:-]+$", "", value)
    value = re.sub(r"^[^\wа-яА-ЯёЁ]+", "", value)
    value = re.sub(r"\s+", " ", value).strip().lower()
    return value


def _format_dream_sections(text: str) -> str:
    lines: list[str] = []
    for raw_line in text.split("\n"):
        line = raw_line.strip()
        key = _section_key(line)
        title = SECTION_TITLES.get(key)
        if title:
            lines.append(f"**{title}**")
        else:
            lines.append(raw_line)
    return "\n".join(lines).strip()


def _normalize_model_text(text: str) -> str:
    return _format_dream_sections(_html_to_markdown(text.replace("\r\n", "\n").strip()))


def _kie_model_candidates(model: str) -> list[str]:
    model = (model or "").strip()
    if not model:
        return []

    aliases = {
        "gemini-3-flash": "gemini-2.5-flash",
        "gemini-3-pro": "gemini-2.5-pro",
    }
    items = [model]
    alias = aliases.get(model)
    if alias:
        items.append(alias)
    if model.startswith("gemini-") and "flash" in model and "gemini-2.5-flash" not in items:
        items.append("gemini-2.5-flash")
    return items


def _user_prompt(dream_text: str, mode: str) -> str:
    if mode == "teaser":
        return teaser_user_prompt(dream_text)
    return full_user_prompt(dream_text)


def _call_kie_text(dream_text: str, mode: str) -> str:
    cfg = load_config()
    if not cfg.kie_api_key or not cfg.kie_base_url:
        raise RuntimeError("Kie text key/base_url is not configured")

    headers = {
        "Authorization": f"Bearer {cfg.kie_api_key}",
        "Content-Type": "application/json",
    }
    payload = {
        "messages": [
            {"role": "system", "content": system_prompt(mode)},
            {"role": "user", "content": _user_prompt(dream_text, mode)},
        ],
        "temperature": 0.7,
    }

    base = cfg.kie_base_url.rstrip("/")
    last_error: Exception | None = None
    for model_name in _kie_model_candidates(cfg.kie_text_model):
        url = f"{base}/{model_name}/v1/chat/completions"
        try:
            logger.info("Dream text request via Kie model=%s url=%s mode=%s", model_name, url, mode)
            response = requests.post(url, headers=headers, json=payload, timeout=90)
            response.raise_for_status()
            data = response.json()
            if isinstance(data, dict) and data.get("code") and data.get("code") != 200:
                raise RuntimeError(f'Kie error code={data.get("code")} msg={data.get("msg")}')
            text = _extract_text_from_json(data)
            if not text:
                raise RuntimeError(f"Kie response has no content: {data}")
            logger.info("Dream text success via Kie model=%s mode=%s", model_name, mode)
            return _normalize_model_text(text)
        except Exception as e:
            last_error = e
            logger.warning("Kie dream text failed model=%s error=%s", model_name, e)

    if last_error:
        raise last_error
    raise RuntimeError("No Kie model candidates available")


def _replicate_headers(token: str) -> dict[str, str]:
    return {
        "Authorization": f"Token {token}",
        "Content-Type": "application/json",
    }


def _poll_replicate_prediction(get_url: str, headers: dict[str, str]) -> str:
    for _ in range(180):
        response = requests.get(get_url, headers=headers, timeout=45)
        response.raise_for_status()
        payload = response.json()
        status = payload.get("status")

        if status == "succeeded":
            text = _extract_text_from_json(payload)
            if not text:
                raise RuntimeError("Replicate output is empty")
            return _normalize_model_text(text)

        if status in ("failed", "canceled"):
            raise RuntimeError(f"Replicate text failed: {payload.get('error') or status}")

        time.sleep(1)

    raise TimeoutError("Replicate text prediction timed out")


def _call_replicate_text(dream_text: str, mode: str) -> str:
    cfg = load_config()
    if not cfg.replicate_api_token:
        raise RuntimeError("Replicate token is not configured")

    base = cfg.replicate_base_url.rstrip("/")
    headers = _replicate_headers(cfg.replicate_api_token)
    prompt = f"{system_prompt(mode)}\n\n{_user_prompt(dream_text, mode)}"

    if cfg.replicate_text_model:
        model_path = cfg.replicate_text_model.strip().strip("/")
        create_url = f"{base}/v1/models/{model_path}/predictions"
        create_payload = {"input": {"prompt": prompt}}
        logger.info("Dream text request via Replicate model=%s mode=%s", cfg.replicate_text_model, mode)
        create_response = requests.post(create_url, headers=headers, data=json.dumps(create_payload), timeout=90)
        create_response.raise_for_status()
        prediction = create_response.json()
        get_url = (prediction.get("urls") or {}).get("get")
        if not get_url:
            prediction_id = prediction.get("id")
            if not prediction_id:
                raise RuntimeError("Replicate text prediction id is missing")
            get_url = f"{base}/v1/predictions/{prediction_id}"
        return _poll_replicate_prediction(get_url, headers)

    if cfg.replicate_text_version:
        create_url = f"{base}/v1/predictions"
        create_payload = {
            "version": cfg.replicate_text_version,
            "input": {"prompt": prompt},
        }
        logger.info("Dream text request via Replicate version=%s mode=%s", cfg.replicate_text_version, mode)
        create_response = requests.post(create_url, headers=headers, data=json.dumps(create_payload), timeout=90)
        create_response.raise_for_status()
        prediction = create_response.json()
        get_url = (prediction.get("urls") or {}).get("get")
        if not get_url:
            prediction_id = prediction.get("id")
            if not prediction_id:
                raise RuntimeError("Replicate text prediction id is missing")
            get_url = f"{base}/v1/predictions/{prediction_id}"
        return _poll_replicate_prediction(get_url, headers)

    raise RuntimeError("Replicate text model/version is not configured")


def _fallback_text(dream_text: str, mode: str) -> str:
    if mode == "teaser":
        return (
            "**🌙 Короткое толкование**\n"
            "Этот сон может показывать внутреннее напряжение, ожидание перемен или попытку психики разобрать важную ситуацию. "
            "Обратите внимание на самый яркий образ сна: чаще всего именно он несет главный эмоциональный сигнал.\n\n"
            "Полный разбор покажет символы, предупреждение, эмоциональный смысл и практический совет."
        )

    return (
        "**🌙 Краткое значение**\n"
        "Сон может отражать внутренний запрос на ясность и попытку разобраться с тем, что в реальности пока не проговорено.\n\n"
        "**🔮 Символы и знаки**\n"
        "Главные образы сна стоит читать как подсказки о вашем эмоциональном фоне: что притягивает внимание, там обычно есть напряжение или желание.\n\n"
        "**⚠️ Предупреждение**\n"
        "Не принимайте сон как прямое предсказание. Он скорее показывает тему, к которой стоит отнестись внимательнее.\n\n"
        "**💭 Эмоциональный смысл**\n"
        "Похоже, психика пытается переработать переживания, ожидания или сомнения, связанные с описанной ситуацией.\n\n"
        "**🧭 Практический совет**\n"
        f"Запишите сон в 2-3 фразах и отметьте, какая часть из описания \"{dream_text[:120]}\" вызывает самый сильный отклик."
    )


async def generate_dream_interpretation_text(dream_text: str, mode: str) -> str:
    try:
        return await asyncio.to_thread(_call_kie_text, dream_text, mode)
    except Exception as kie_error:
        logger.warning("Dream text via Kie failed: %s", kie_error)

    try:
        return await asyncio.to_thread(_call_replicate_text, dream_text, mode)
    except Exception as replicate_error:
        logger.warning("Dream text via Replicate failed: %s", replicate_error)

    return _fallback_text(dream_text, mode)


def _call_kie_followup(dream_text: str, followup: str, last_answer: str, mode: str) -> str:
    cfg = load_config()
    if not cfg.kie_api_key or not cfg.kie_base_url:
        raise RuntimeError("Kie text key/base_url is not configured")

    headers = {
        "Authorization": f"Bearer {cfg.kie_api_key}",
        "Content-Type": "application/json",
    }
    payload = {
        "messages": [
            {"role": "system", "content": system_prompt("followup")},
            {"role": "user", "content": followup_user_prompt(dream_text, followup, last_answer, mode)},
        ],
        "temperature": 0.6,
    }

    base = cfg.kie_base_url.rstrip("/")
    last_error: Exception | None = None
    for model_name in _kie_model_candidates(cfg.kie_text_model):
        url = f"{base}/{model_name}/v1/chat/completions"
        try:
            logger.info("Dream followup via Kie model=%s url=%s", model_name, url)
            response = requests.post(url, headers=headers, json=payload, timeout=90)
            response.raise_for_status()
            data = response.json()
            if isinstance(data, dict) and data.get("code") and data.get("code") != 200:
                raise RuntimeError(f'Kie error code={data.get("code")} msg={data.get("msg")}')
            text = _extract_text_from_json(data)
            if not text:
                raise RuntimeError(f"Kie response has no content: {data}")
            return _normalize_model_text(text)
        except Exception as e:
            last_error = e
            logger.warning("Kie dream followup failed model=%s error=%s", model_name, e)

    if last_error:
        raise last_error
    raise RuntimeError("No Kie model candidates available")


def _call_replicate_followup(dream_text: str, followup: str, last_answer: str, mode: str) -> str:
    cfg = load_config()
    if not cfg.replicate_api_token:
        raise RuntimeError("Replicate token is not configured")

    base = cfg.replicate_base_url.rstrip("/")
    headers = _replicate_headers(cfg.replicate_api_token)
    prompt = f"{system_prompt('followup')}\n\n{followup_user_prompt(dream_text, followup, last_answer, mode)}"

    if cfg.replicate_text_model:
        model_path = cfg.replicate_text_model.strip().strip("/")
        create_url = f"{base}/v1/models/{model_path}/predictions"
        create_payload = {"input": {"prompt": prompt}}
        logger.info("Dream followup via Replicate model=%s", cfg.replicate_text_model)
        create_response = requests.post(create_url, headers=headers, data=json.dumps(create_payload), timeout=90)
        create_response.raise_for_status()
        prediction = create_response.json()
        get_url = (prediction.get("urls") or {}).get("get")
        if not get_url:
            prediction_id = prediction.get("id")
            if not prediction_id:
                raise RuntimeError("Replicate followup prediction id is missing")
            get_url = f"{base}/v1/predictions/{prediction_id}"
        return _poll_replicate_prediction(get_url, headers)

    if cfg.replicate_text_version:
        create_url = f"{base}/v1/predictions"
        create_payload = {"version": cfg.replicate_text_version, "input": {"prompt": prompt}}
        logger.info("Dream followup via Replicate version=%s", cfg.replicate_text_version)
        create_response = requests.post(create_url, headers=headers, data=json.dumps(create_payload), timeout=90)
        create_response.raise_for_status()
        prediction = create_response.json()
        get_url = (prediction.get("urls") or {}).get("get")
        if not get_url:
            prediction_id = prediction.get("id")
            if not prediction_id:
                raise RuntimeError("Replicate followup prediction id is missing")
            get_url = f"{base}/v1/predictions/{prediction_id}"
        return _poll_replicate_prediction(get_url, headers)

    raise RuntimeError("Replicate text model/version is not configured")


def _fallback_followup(dream_text: str, followup: str) -> str:
    return (
        "**💬 Уточнение по сну**\n"
        f"По вашему вопросу \"{followup}\" главный ориентир такой: этот образ лучше читать не буквально, "
        "а как сигнал эмоции или ситуации, которая требует внимания.\n\n"
        f"В контексте сна \"{dream_text[:120]}\" важнее всего отметить, что именно вы чувствовали во сне и после пробуждения."
    )


async def generate_dream_followup_text(dream_text: str, followup: str, last_answer: str, mode: str) -> str:
    try:
        return await asyncio.to_thread(_call_kie_followup, dream_text, followup, last_answer, mode)
    except Exception as kie_error:
        logger.warning("Dream followup via Kie failed: %s", kie_error)

    try:
        return await asyncio.to_thread(_call_replicate_followup, dream_text, followup, last_answer, mode)
    except Exception as replicate_error:
        logger.warning("Dream followup via Replicate failed: %s", replicate_error)

    return _fallback_followup(dream_text, followup)
