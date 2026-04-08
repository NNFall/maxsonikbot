from __future__ import annotations

import asyncio
import base64
import json
import logging
import mimetypes
import time
from pathlib import Path
from typing import Any

import requests

logger = logging.getLogger(__name__)

ASPECT_RATIOS = {
    '16:9': 16 / 9,
    '4:3': 4 / 3,
    '3:2': 3 / 2,
    '1:1': 1.0,
    '2:3': 2 / 3,
    '3:4': 3 / 4,
    '9:16': 9 / 16,
}


def closest_aspect_ratio(width: int, height: int) -> str:
    if width <= 0 or height <= 0:
        return '16:9'
    ratio = width / height
    return min(ASPECT_RATIOS.items(), key=lambda item: abs(item[1] - ratio))[0]


def _headers(api_token: str) -> dict[str, str]:
    return {
        'Authorization': f'Token {api_token}',
        'Content-Type': 'application/json',
    }


def encode_image(image_path: str) -> str:
    path = Path(image_path)
    raw = path.read_bytes()
    b64 = base64.b64encode(raw).decode('ascii')
    mime, _ = mimetypes.guess_type(str(path))
    if not mime:
        mime = 'image/jpeg'
    return f"data:{mime};base64,{b64}"


def create_prediction(
    image_input: str,
    prompt: str,
    duration: int,
    api_token: str,
    api_url: str,
    model_version: str,
    image_field: str = 'image',
    aspect_ratio: str | None = None,
    webhook_url: str | None = None,
    timeout_sec: int = 30,
) -> dict[str, Any]:
    if not api_token:
        raise RuntimeError('REPLICATE_API_TOKEN is empty')
    if not model_version:
        raise RuntimeError('REPLICATE_MODEL_VERSION is empty')

    input_data: dict[str, Any] = {
        image_field: image_input,
        'prompt': prompt,
        'duration': duration,
    }
    if aspect_ratio:
        input_data['aspect_ratio'] = aspect_ratio

    payload: dict[str, Any] = {
        'version': model_version,
        'input': input_data,
    }

    if webhook_url:
        payload['webhook'] = webhook_url

    response = requests.post(api_url, headers=_headers(api_token), data=json.dumps(payload), timeout=timeout_sec)
    response.raise_for_status()
    return response.json()


def get_prediction(api_token: str, prediction_id: str, api_url: str) -> dict[str, Any]:
    if not api_token:
        raise RuntimeError('REPLICATE_API_TOKEN is empty')

    url = f"{api_url.rstrip('/')}/{prediction_id}"
    response = requests.get(url, headers=_headers(api_token), timeout=30)
    response.raise_for_status()
    return response.json()


def extract_output_url(payload: dict[str, Any]) -> str | None:
    output = payload.get('output')
    if isinstance(output, str):
        return output
    if isinstance(output, list) and output:
        if isinstance(output[0], str):
            return output[0]
    if isinstance(output, dict):
        if isinstance(output.get('video'), str):
            return output['video']
        if isinstance(output.get('url'), str):
            return output['url']
    return None


async def poll_prediction(
    prediction_id: str,
    api_token: str,
    api_url: str,
    interval_sec: int = 10,
    timeout_sec: int = 900,
    log_every: int = 1,
) -> dict[str, Any]:
    start = time.time()
    last_status = None
    poll_count = 0

    while True:
        poll_count += 1
        prediction = await asyncio.to_thread(get_prediction, api_token, prediction_id, api_url)
        status = prediction.get('status')
        if status != last_status:
            logger.info('Replicate status prediction_id=%s status=%s', prediction_id, status)
            last_status = status
        elif log_every and poll_count % log_every == 0:
            logger.info('Replicate status prediction_id=%s status=%s (still)', prediction_id, status)

        if status in ('succeeded',):
            return prediction
        if status in ('failed', 'canceled'):
            err = prediction.get('error')
            if not err and isinstance(prediction.get('logs'), str):
                err = prediction.get('logs')
            if err:
                logger.error('Replicate failed prediction_id=%s status=%s error=%s', prediction_id, status, err)
                raise RuntimeError(f'Replicate failed: {status}. {err}')
            logger.error('Replicate failed prediction_id=%s status=%s', prediction_id, status)
            raise RuntimeError(f'Replicate failed: {status}')

        if time.time() - start > timeout_sec:
            raise TimeoutError('Replicate generation timed out')

        await asyncio.sleep(interval_sec)
