from __future__ import annotations

import asyncio
import json
import logging
import re
import time
from typing import Any

import requests

from config import load_config
from prompts.tarot_prompts import (
    continuation_user_prompt,
    followup_user_prompt,
    full_user_prompt,
    system_prompt,
    teaser_user_prompt,
)
from services.tarot_deck import DrawnCard

logger = logging.getLogger(__name__)

HTML_TAG_RE = re.compile(r'<[^>]+>')


def _orientation_text(card: DrawnCard) -> str:
    return 'перевернутая' if card.is_reversed else 'прямая'


def _cards_for_prompt(cards: list[DrawnCard]) -> str:
    lines = []
    for idx, card in enumerate(cards, start=1):
        lines.append(f'{idx}. {card.card.title} ({_orientation_text(card)})')
    return '\n'.join(lines)


def _user_prompt(question: str, cards: list[DrawnCard], mode: str) -> str:
    if mode == 'teaser':
        first = cards[0]
        first_line = f'{first.card.title} ({_orientation_text(first)})'
        return teaser_user_prompt(question, first_line)
    return full_user_prompt(question, _cards_for_prompt(cards))


def _followup_prompt(
    question: str,
    followup: str,
    cards: list[DrawnCard],
    last_answer: str,
    mode: str,
) -> str:
    return followup_user_prompt(question, followup, _cards_for_prompt(cards), last_answer, mode)


def _continuation_prompt(
    question: str,
    first_card: DrawnCard,
    first_text: str,
    cards: list[DrawnCard],
) -> str:
    first_line = f'{first_card.card.title} ({_orientation_text(first_card)})'
    return continuation_user_prompt(question, first_line, first_text, _cards_for_prompt(cards))


def _extract_text_from_json(payload: dict[str, Any]) -> str | None:
    choices = payload.get('choices')
    if isinstance(choices, list) and choices:
        first = choices[0]
        if isinstance(first, dict):
            message = first.get('message')
            if isinstance(message, dict):
                content = message.get('content')
                if isinstance(content, str) and content.strip():
                    return content.strip()
            text = first.get('text')
            if isinstance(text, str) and text.strip():
                return text.strip()

    output = payload.get('output')
    if isinstance(output, str) and output.strip():
        return output.strip()
    if isinstance(output, list) and output:
        text = '\n'.join(item for item in output if isinstance(item, str)).strip()
        if text:
            return text
    return None


def _html_to_markdown(text: str) -> str:
    text = re.sub(r'<\s*b\s*>(.*?)<\s*/\s*b\s*>', r'*\1*', text, flags=re.IGNORECASE | re.DOTALL)
    text = re.sub(r'<\s*i\s*>(.*?)<\s*/\s*i\s*>', r'_\1_', text, flags=re.IGNORECASE | re.DOTALL)
    text = re.sub(r'<\s*code\s*>(.*?)<\s*/\s*code\s*>', r'`\1`', text, flags=re.IGNORECASE | re.DOTALL)
    text = HTML_TAG_RE.sub('', text)
    return text


def _normalize_model_text(text: str) -> str:
    text = text.replace('\r\n', '\n').strip()
    text = _html_to_markdown(text)
    return text


def _kie_model_candidates(model: str) -> list[str]:
    model = (model or '').strip()
    if not model:
        return []

    aliases = {
        'gemini-3-flash': 'gemini-2.5-flash',
        'gemini-3-pro': 'gemini-2.5-pro',
    }
    items = [model]
    alias = aliases.get(model)
    if alias:
        items.append(alias)
    # Safety fallback for generic Gemini naming
    if model.startswith('gemini-') and 'flash' in model and 'gemini-2.5-flash' not in items:
        items.append('gemini-2.5-flash')
    return items


def _call_kie_text(question: str, cards: list[DrawnCard], mode: str) -> str:
    cfg = load_config()
    if not cfg.kie_api_key or not cfg.kie_base_url:
        raise RuntimeError('Kie text key/base_url is not configured')

    headers = {
        'Authorization': f'Bearer {cfg.kie_api_key}',
        'Content-Type': 'application/json',
    }
    payload = {
        'messages': [
            {'role': 'system', 'content': system_prompt(mode)},
            {'role': 'user', 'content': _user_prompt(question, cards, mode)},
        ],
        'temperature': 0.7,
    }

    base = cfg.kie_base_url.rstrip('/')
    last_error: Exception | None = None

    for model_name in _kie_model_candidates(cfg.kie_text_model):
        url = f'{base}/{model_name}/v1/chat/completions'
        try:
            logger.info('Tarot text request via Kie model=%s url=%s mode=%s', model_name, url, mode)
            response = requests.post(url, headers=headers, json=payload, timeout=90)
            response.raise_for_status()
            data = response.json()
            if isinstance(data, dict) and data.get('code') and data.get('code') != 200:
                raise RuntimeError(f'Kie error code={data.get("code")} msg={data.get("msg")}')
            text = _extract_text_from_json(data)
            if not text:
                raise RuntimeError(f'Kie response has no content: {data}')
            logger.info('Tarot text success via Kie model=%s mode=%s', model_name, mode)
            return _normalize_model_text(text)
        except Exception as e:
            last_error = e
            logger.warning('Kie text endpoint failed model=%s error=%s', model_name, e)

    if last_error:
        raise last_error
    raise RuntimeError('No Kie model candidates available')


def _replicate_headers(token: str) -> dict[str, str]:
    return {
        'Authorization': f'Token {token}',
        'Content-Type': 'application/json',
    }


def _poll_replicate_prediction(get_url: str, headers: dict[str, str]) -> str:
    for _ in range(180):
        response = requests.get(get_url, headers=headers, timeout=45)
        response.raise_for_status()
        payload = response.json()
        status = payload.get('status')

        if status == 'succeeded':
            text = _extract_text_from_json(payload)
            if not text:
                raise RuntimeError('Replicate output is empty')
            return _normalize_model_text(text)

        if status in ('failed', 'canceled'):
            raise RuntimeError(f'Replicate text failed: {payload.get("error") or status}')

        time.sleep(1)

    raise TimeoutError('Replicate text prediction timed out')


def _call_replicate_text(question: str, cards: list[DrawnCard], mode: str) -> str:
    cfg = load_config()
    if not cfg.replicate_api_token:
        raise RuntimeError('Replicate token is not configured')

    base = cfg.replicate_base_url.rstrip('/')
    headers = _replicate_headers(cfg.replicate_api_token)
    prompt = f'{system_prompt(mode)}\n\n{_user_prompt(question, cards, mode)}'

    if cfg.replicate_text_model:
        model_path = cfg.replicate_text_model.strip().strip('/')
        create_url = f'{base}/v1/models/{model_path}/predictions'
        create_payload = {'input': {'prompt': prompt}}
        logger.info('Tarot text request via Replicate model=%s mode=%s', cfg.replicate_text_model, mode)
        create_response = requests.post(create_url, headers=headers, data=json.dumps(create_payload), timeout=90)
        create_response.raise_for_status()
        prediction = create_response.json()
        get_url = (prediction.get('urls') or {}).get('get')
        if not get_url:
            prediction_id = prediction.get('id')
            if not prediction_id:
                raise RuntimeError('Replicate text prediction id is missing')
            get_url = f'{base}/v1/predictions/{prediction_id}'
        return _poll_replicate_prediction(get_url, headers)

    if cfg.replicate_text_version:
        create_url = f'{base}/v1/predictions'
        create_payload = {
            'version': cfg.replicate_text_version,
            'input': {'prompt': prompt},
        }
        logger.info('Tarot text request via Replicate version=%s mode=%s', cfg.replicate_text_version, mode)
        create_response = requests.post(create_url, headers=headers, data=json.dumps(create_payload), timeout=90)
        create_response.raise_for_status()
        prediction = create_response.json()
        get_url = (prediction.get('urls') or {}).get('get')
        if not get_url:
            prediction_id = prediction.get('id')
            if not prediction_id:
                raise RuntimeError('Replicate text prediction id is missing')
            get_url = f'{base}/v1/predictions/{prediction_id}'
        return _poll_replicate_prediction(get_url, headers)

    raise RuntimeError('Replicate text model/version is not configured')


def _fallback_text(question: str, cards: list[DrawnCard], mode: str) -> str:
    if mode == 'teaser':
        first = cards[0]
        reverse = ' (перевернутая)' if first.is_reversed else ''
        return (
            'Давайте посмотрим, что говорят карты:\n\n'
            'Сначала коротко настроимся на ваш вопрос и общий фон ситуации. '
            'Карты показывают направление, а детали раскрываются постепенно.\n\n'
            f'*Первая карта — {first.card.title}{reverse}*\n'
            'Она указывает на текущее состояние вокруг вашего вопроса и то, что уже начинает формироваться. '
            'Если хотите полную картину, откройте остальные карты расклада.'
        )

    positions = [
        '1. Текущая ситуация вокруг вопроса',
        '2. Ключевое препятствие или узел',
        '3. Совет и направление',
    ]
    parts: list[str] = [
        'Давайте посмотрим, что говорят карты:\n\n'
        'Сначала обозначим общий фон запроса. Карты показывают тенденции и опорные точки.'
    ]
    for idx, card in enumerate(cards):
        reverse = ' (перевернутая)' if card.is_reversed else ''
        parts.append(
            f'*{positions[idx]} — {card.card.title}{reverse}*\n'
            'Карта подсказывает, как эта позиция проявляется именно в вашем вопросе.'
        )

    parts.append(
        f'*Резюме:* по вопросу "{question}" потенциал положительный, '
        'если действовать системно и учитывать сигналы расклада.'
    )
    return '\n\n'.join(parts)


async def generate_tarot_reading_text(question: str, cards: list[DrawnCard], mode: str) -> str:
    try:
        return await asyncio.to_thread(_call_kie_text, question, cards, mode)
    except Exception as kie_error:
        logger.warning('Tarot text via Kie failed: %s', kie_error)

    try:
        return await asyncio.to_thread(_call_replicate_text, question, cards, mode)
    except Exception as replicate_error:
        logger.warning('Tarot text via Replicate failed: %s', replicate_error)

    return _fallback_text(question, cards, mode)


def _call_kie_followup(
    question: str,
    followup: str,
    cards: list[DrawnCard],
    last_answer: str,
    mode: str,
) -> str:
    cfg = load_config()
    if not cfg.kie_api_key or not cfg.kie_base_url:
        raise RuntimeError('Kie text key/base_url is not configured')

    headers = {
        'Authorization': f'Bearer {cfg.kie_api_key}',
        'Content-Type': 'application/json',
    }
    payload = {
        'messages': [
            {'role': 'system', 'content': system_prompt('followup')},
            {'role': 'user', 'content': _followup_prompt(question, followup, cards, last_answer, mode)},
        ],
        'temperature': 0.6,
    }

    base = cfg.kie_base_url.rstrip('/')
    last_error: Exception | None = None

    for model_name in _kie_model_candidates(cfg.kie_text_model):
        url = f'{base}/{model_name}/v1/chat/completions'
        try:
            logger.info('Tarot followup via Kie model=%s url=%s', model_name, url)
            response = requests.post(url, headers=headers, json=payload, timeout=90)
            response.raise_for_status()
            data = response.json()
            if isinstance(data, dict) and data.get('code') and data.get('code') != 200:
                raise RuntimeError(f'Kie error code={data.get("code")} msg={data.get("msg")}')
            text = _extract_text_from_json(data)
            if not text:
                raise RuntimeError(f'Kie response has no content: {data}')
            return _normalize_model_text(text)
        except Exception as e:
            last_error = e
            logger.warning('Kie followup failed model=%s error=%s', model_name, e)

    if last_error:
        raise last_error
    raise RuntimeError('No Kie model candidates available')


def _call_replicate_followup(
    question: str,
    followup: str,
    cards: list[DrawnCard],
    last_answer: str,
    mode: str,
) -> str:
    cfg = load_config()
    if not cfg.replicate_api_token:
        raise RuntimeError('Replicate token is not configured')

    base = cfg.replicate_base_url.rstrip('/')
    headers = _replicate_headers(cfg.replicate_api_token)
    prompt = f'{system_prompt("followup")}\n\n{_followup_prompt(question, followup, cards, last_answer, mode)}'

    if cfg.replicate_text_model:
        model_path = cfg.replicate_text_model.strip().strip('/')
        create_url = f'{base}/v1/models/{model_path}/predictions'
        create_payload = {'input': {'prompt': prompt}}
        logger.info('Tarot followup via Replicate model=%s', cfg.replicate_text_model)
        create_response = requests.post(create_url, headers=headers, data=json.dumps(create_payload), timeout=90)
        create_response.raise_for_status()
        prediction = create_response.json()
        get_url = (prediction.get('urls') or {}).get('get')
        if not get_url:
            prediction_id = prediction.get('id')
            if not prediction_id:
                raise RuntimeError('Replicate followup prediction id is missing')
            get_url = f'{base}/v1/predictions/{prediction_id}'
        return _poll_replicate_prediction(get_url, headers)

    if cfg.replicate_text_version:
        create_url = f'{base}/v1/predictions'
        create_payload = {'version': cfg.replicate_text_version, 'input': {'prompt': prompt}}
        logger.info('Tarot followup via Replicate version=%s', cfg.replicate_text_version)
        create_response = requests.post(create_url, headers=headers, data=json.dumps(create_payload), timeout=90)
        create_response.raise_for_status()
        prediction = create_response.json()
        get_url = (prediction.get('urls') or {}).get('get')
        if not get_url:
            prediction_id = prediction.get('id')
            if not prediction_id:
                raise RuntimeError('Replicate followup prediction id is missing')
            get_url = f'{base}/v1/predictions/{prediction_id}'
        return _poll_replicate_prediction(get_url, headers)

    raise RuntimeError('Replicate text model/version is not configured')


def _fallback_followup(question: str, followup: str, cards: list[DrawnCard], mode: str) -> str:
    first = cards[0] if cards else None
    card_line = ''
    if first:
        reverse = ' (перевернутая)' if first.is_reversed else ''
        card_line = f' Первая карта — {first.card.title}{reverse}.'
    return (
        'Давайте посмотрим, что говорят карты:\n\n'
        f'Кратко напомню: основной смысл расклада по вопросу "{question}" '
        f'связан с текущим фоном и направлениями изменений.{card_line}\n\n'
        f'По вашему уточнению "{followup}" — это означает, что важнее всего '
        'не форсировать события, а наблюдать за сигналами и принимать решения по мере готовности.'
    )


async def generate_tarot_followup_text(
    question: str,
    followup: str,
    cards: list[DrawnCard],
    last_answer: str,
    mode: str,
) -> str:
    try:
        return await asyncio.to_thread(_call_kie_followup, question, followup, cards, last_answer, mode)
    except Exception as kie_error:
        logger.warning('Tarot followup via Kie failed: %s', kie_error)

    try:
        return await asyncio.to_thread(_call_replicate_followup, question, followup, cards, last_answer, mode)
    except Exception as replicate_error:
        logger.warning('Tarot followup via Replicate failed: %s', replicate_error)

    return _fallback_followup(question, followup, cards, mode)


def _call_kie_continuation(
    question: str,
    first_card: DrawnCard,
    first_text: str,
    cards: list[DrawnCard],
) -> str:
    cfg = load_config()
    if not cfg.kie_api_key or not cfg.kie_base_url:
        raise RuntimeError('Kie text key/base_url is not configured')

    headers = {
        'Authorization': f'Bearer {cfg.kie_api_key}',
        'Content-Type': 'application/json',
    }
    payload = {
        'messages': [
            {'role': 'system', 'content': system_prompt('continuation')},
            {'role': 'user', 'content': _continuation_prompt(question, first_card, first_text, cards)},
        ],
        'temperature': 0.7,
    }

    base = cfg.kie_base_url.rstrip('/')
    last_error: Exception | None = None

    for model_name in _kie_model_candidates(cfg.kie_text_model):
        url = f'{base}/{model_name}/v1/chat/completions'
        try:
            logger.info('Tarot continuation via Kie model=%s url=%s', model_name, url)
            response = requests.post(url, headers=headers, json=payload, timeout=90)
            response.raise_for_status()
            data = response.json()
            if isinstance(data, dict) and data.get('code') and data.get('code') != 200:
                raise RuntimeError(f'Kie error code={data.get("code")} msg={data.get("msg")}')
            text = _extract_text_from_json(data)
            if not text:
                raise RuntimeError(f'Kie response has no content: {data}')
            return _normalize_model_text(text)
        except Exception as e:
            last_error = e
            logger.warning('Kie continuation failed model=%s error=%s', model_name, e)

    if last_error:
        raise last_error
    raise RuntimeError('No Kie model candidates available')


def _call_replicate_continuation(
    question: str,
    first_card: DrawnCard,
    first_text: str,
    cards: list[DrawnCard],
) -> str:
    cfg = load_config()
    if not cfg.replicate_api_token:
        raise RuntimeError('Replicate token is not configured')

    base = cfg.replicate_base_url.rstrip('/')
    headers = _replicate_headers(cfg.replicate_api_token)
    prompt = f'{system_prompt("continuation")}\n\n{_continuation_prompt(question, first_card, first_text, cards)}'

    if cfg.replicate_text_model:
        model_path = cfg.replicate_text_model.strip().strip('/')
        create_url = f'{base}/v1/models/{model_path}/predictions'
        create_payload = {'input': {'prompt': prompt}}
        logger.info('Tarot continuation via Replicate model=%s', cfg.replicate_text_model)
        create_response = requests.post(create_url, headers=headers, data=json.dumps(create_payload), timeout=90)
        create_response.raise_for_status()
        prediction = create_response.json()
        get_url = (prediction.get('urls') or {}).get('get')
        if not get_url:
            prediction_id = prediction.get('id')
            if not prediction_id:
                raise RuntimeError('Replicate continuation prediction id is missing')
            get_url = f'{base}/v1/predictions/{prediction_id}'
        return _poll_replicate_prediction(get_url, headers)

    if cfg.replicate_text_version:
        create_url = f'{base}/v1/predictions'
        create_payload = {'version': cfg.replicate_text_version, 'input': {'prompt': prompt}}
        logger.info('Tarot continuation via Replicate version=%s', cfg.replicate_text_version)
        create_response = requests.post(create_url, headers=headers, data=json.dumps(create_payload), timeout=90)
        create_response.raise_for_status()
        prediction = create_response.json()
        get_url = (prediction.get('urls') or {}).get('get')
        if not get_url:
            prediction_id = prediction.get('id')
            if not prediction_id:
                raise RuntimeError('Replicate continuation prediction id is missing')
            get_url = f'{base}/v1/predictions/{prediction_id}'
        return _poll_replicate_prediction(get_url, headers)

    raise RuntimeError('Replicate text model/version is not configured')


def _fallback_continuation(
    question: str,
    first_card: DrawnCard,
    first_text: str,
    cards: list[DrawnCard],
) -> str:
    second = cards[0] if len(cards) > 0 else None
    third = cards[1] if len(cards) > 1 else None
    second_line = ''
    third_line = ''
    if second:
        reverse = ' (перевернутая)' if second.is_reversed else ''
        second_line = f'*2) {second.card.title}{reverse}*\nКарта подсказывает ключевое препятствие.'
    if third:
        reverse = ' (перевернутая)' if third.is_reversed else ''
        third_line = f'*3) {third.card.title}{reverse}*\nКарта дает совет и направление.'
    return (
        'Давайте посмотрим, что говорят карты:\n\n'
        f'Кратко напомню: {first_text}\n\n'
        f'{second_line}\n\n{third_line}\n\n'
        f'*Резюме:* по вопросу \"{question}\" важно учитывать эти два сигнала и двигаться постепенно.'
    )


async def generate_tarot_continuation_text(
    question: str,
    first_card: DrawnCard,
    first_text: str,
    cards: list[DrawnCard],
) -> str:
    try:
        return await asyncio.to_thread(_call_kie_continuation, question, first_card, first_text, cards)
    except Exception as kie_error:
        logger.warning('Tarot continuation via Kie failed: %s', kie_error)

    try:
        return await asyncio.to_thread(_call_replicate_continuation, question, first_card, first_text, cards)
    except Exception as replicate_error:
        logger.warning('Tarot continuation via Replicate failed: %s', replicate_error)

    return _fallback_continuation(question, first_card, first_text, cards)
