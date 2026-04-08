from __future__ import annotations

import asyncio
import json
import logging
import time
from pathlib import Path
from typing import Any

import requests

UPLOAD_MAX_ATTEMPTS = 3
UPLOAD_RETRY_DELAY_SEC = 2

logger = logging.getLogger(__name__)

DEFAULT_CREATE_TASK_URL = 'https://api.kie.ai/api/v1/jobs/createTask'
DEFAULT_RECORD_URL = 'https://api.kie.ai/api/v1/jobs/recordInfo'
DEFAULT_UPLOAD_URL = 'https://kieai.redpandaai.co/api/file-stream-upload'


def _headers(api_key: str) -> dict[str, str]:
    return {'Authorization': f'Bearer {api_key}'}


def upload_file(
    file_path: str,
    api_key: str,
    upload_path: str = 'images/user-uploads',
    upload_url: str = DEFAULT_UPLOAD_URL,
    timeout_sec: int = 60,
    max_attempts: int = UPLOAD_MAX_ATTEMPTS,
) -> str:
    if not api_key:
        raise RuntimeError('KIE_API_KEY is empty')

    path = Path(file_path)
    if not path.exists():
        raise FileNotFoundError(str(path))

    last_error: Exception | None = None
    for attempt in range(1, max_attempts + 1):
        try:
            with path.open('rb') as f:
                files = {'file': (path.name, f)}
                data = {'uploadPath': upload_path}
                response = requests.post(
                    upload_url,
                    headers=_headers(api_key),
                    data=data,
                    files=files,
                    timeout=timeout_sec,
                )
                response.raise_for_status()
                payload = response.json()

            success = payload.get('successFlag')
            if success is None:
                success = payload.get('success')
            if success is not True:
                raise RuntimeError(f'Kie upload failed: {json.dumps(payload)[:500]}')

            download_url = payload.get('data', {}).get('downloadUrl')
            if not download_url:
                raise RuntimeError(f'Kie upload missing downloadUrl: {json.dumps(payload)[:500]}')

            return download_url
        except requests.HTTPError as e:
            status = e.response.status_code if e.response is not None else None
            if status and status < 500:
                raise
            last_error = e
        except Exception as e:
            last_error = e

        if attempt < max_attempts:
            time.sleep(UPLOAD_RETRY_DELAY_SEC * attempt)

    if last_error:
        raise last_error
    raise RuntimeError('Kie upload failed: unknown error')


def create_task(
    image_url: str,
    prompt: str,
    duration: int,
    api_key: str,
    api_url: str = DEFAULT_CREATE_TASK_URL,
    callback_url: str | None = None,
    timeout_sec: int = 30,
) -> str:
    if not api_key:
        raise RuntimeError('KIE_API_KEY is empty')

    payload: dict[str, Any] = {
        'model': 'grok-imagine/image-to-video',
        'input': {
            'image_urls': [image_url],
            'prompt': prompt,
            'duration': str(duration),
            'mode': 'normal',
        },
    }
    if callback_url:
        payload['callBackUrl'] = callback_url

    response = requests.post(api_url, headers=_headers(api_key), json=payload, timeout=timeout_sec)
    response.raise_for_status()
    try:
        data = response.json()
    except Exception:
        raise RuntimeError(f'Kie createTask invalid JSON: {response.text[:500]}')

    if not isinstance(data, dict):
        raise RuntimeError(f'Kie createTask invalid response: {str(data)[:500]}')

    task_id = None
    data_block = data.get('data')
    if isinstance(data_block, dict):
        task_id = data_block.get('taskId') or data_block.get('task_id')
    if not task_id:
        task_id = data.get('taskId') or data.get('task_id')
    if not task_id:
        raise RuntimeError(f'Kie createTask missing taskId: {json.dumps(data)[:500]}')
    return str(task_id)


def create_image_task(
    prompt: str,
    model: str,
    api_key: str,
    api_url: str = DEFAULT_CREATE_TASK_URL,
    image_url: str | None = None,
    aspect_ratio: str = '1:1',
    resolution: str = '1K',
    cfg: int = 4,
    timeout_sec: int = 60,
) -> str:
    if not api_key:
        raise RuntimeError('KIE_API_KEY is empty')
    if not model:
        raise RuntimeError('KIE_IMAGE_MODEL is empty')

    def _post(payload: dict[str, Any]) -> dict[str, Any]:
        response = requests.post(api_url, headers=_headers(api_key), json=payload, timeout=timeout_sec)
        response.raise_for_status()
        try:
            data = response.json()
        except Exception:
            raise RuntimeError(f'Kie createTask invalid JSON: {response.text[:500]}')
        if not isinstance(data, dict):
            raise RuntimeError(f'Kie createTask invalid response: {str(data)[:500]}')
        return data

    def _extract_task_id(data: dict[str, Any]) -> str | None:
        data_block = data.get('data')
        if isinstance(data_block, dict):
            task_id = data_block.get('taskId') or data_block.get('task_id')
            if task_id:
                return str(task_id)
        task_id = data.get('taskId') or data.get('task_id')
        return str(task_id) if task_id else None

    input_data: dict[str, Any] = {
        'prompt': prompt,
        'aspect_ratio': aspect_ratio,
        'resolution': resolution,
        'cfg': cfg,
    }
    if image_url:
        input_data['image_urls'] = [image_url]

    payload: dict[str, Any] = {
        'model': model,
        'input': input_data,
    }

    data = _post(payload)
    task_id = _extract_task_id(data)
    if not task_id:
        raise RuntimeError(f'Kie createTask missing taskId: {json.dumps(data)[:500]}')
    return task_id


def get_task(task_id: str, api_key: str, api_url: str = DEFAULT_RECORD_URL, timeout_sec: int = 30) -> dict[str, Any]:
    if not api_key:
        raise RuntimeError('KIE_API_KEY is empty')

    params = {'taskId': task_id}
    response = requests.get(api_url, headers=_headers(api_key), params=params, timeout=timeout_sec)
    response.raise_for_status()
    return response.json()


def extract_result_url(record: dict[str, Any]) -> str | None:
    data = record.get('data') or {}
    result_json = data.get('resultJson') or data.get('result_json')
    if not result_json:
        return None

    try:
        parsed = json.loads(result_json) if isinstance(result_json, str) else result_json
    except json.JSONDecodeError:
        return None

    if isinstance(parsed, dict):
        if isinstance(parsed.get('resultUrl'), str):
            return parsed['resultUrl']
        if isinstance(parsed.get('resultUrls'), list) and parsed['resultUrls']:
            return parsed['resultUrls'][0]

    if isinstance(parsed, list) and parsed:
        if isinstance(parsed[0], str):
            return parsed[0]

    return None


def extract_result_urls(record: dict[str, Any]) -> list[str]:
    data = record.get('data') or {}
    result_json = data.get('resultJson') or data.get('result_json')
    if not result_json:
        return []

    try:
        parsed = json.loads(result_json) if isinstance(result_json, str) else result_json
    except json.JSONDecodeError:
        return []

    if isinstance(parsed, dict):
        urls = parsed.get('resultUrls')
        if isinstance(urls, list):
            return [u for u in urls if isinstance(u, str)]
        if isinstance(parsed.get('resultUrl'), str):
            return [parsed.get('resultUrl')]

    if isinstance(parsed, list):
        return [u for u in parsed if isinstance(u, str)]

    return []


def extract_state(record: dict[str, Any]) -> str | None:
    data = record.get('data') or {}
    return data.get('state')


def extract_error(record: dict[str, Any]) -> str | None:
    data = record.get('data') or {}
    return data.get('failMsg') or data.get('error')


async def poll_task(
    task_id: str,
    api_key: str,
    api_url: str = DEFAULT_RECORD_URL,
    interval_sec: int = 20,
    timeout_sec: int = 900,
) -> dict[str, Any]:
    start = time.time()
    last_state = None

    while True:
        record = await asyncio.to_thread(get_task, task_id, api_key, api_url)
        state = (extract_state(record) or 'unknown').lower()
        if state != last_state:
            logger.info('Kie task status task_id=%s state=%s', task_id, state)
            last_state = state

        if state in ('success', 'succeeded'):
            return record
        if state in ('failed', 'fail', 'canceled'):
            error = extract_error(record) or 'unknown error'
            raise RuntimeError(f'Kie task failed: {error}')

        if time.time() - start > timeout_sec:
            raise TimeoutError('Kie task timed out')

        await asyncio.sleep(interval_sec)
