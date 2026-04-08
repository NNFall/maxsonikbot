from __future__ import annotations

import uuid
from typing import Any
from yookassa import Configuration, Payment


def configure(shop_id: str, secret_key: str) -> None:
    if not shop_id or not secret_key:
        raise RuntimeError('YOOKASSA_SHOP_ID or YOOKASSA_SECRET_KEY is empty')
    Configuration.account_id = shop_id
    Configuration.secret_key = secret_key


def create_payment(
    amount_rub: int,
    description: str,
    return_url: str,
    metadata: dict[str, Any],
    save_payment_method: bool = False,
    receipt: dict[str, Any] | None = None,
) -> Payment:
    payload: dict[str, Any] = {
            'amount': {
                'value': f"{amount_rub:.2f}",
                'currency': 'RUB',
            },
            'confirmation': {
                'type': 'redirect',
                'return_url': return_url,
            },
            'capture': True,
            'description': description,
            'metadata': metadata,
            'save_payment_method': save_payment_method,
        }
    if receipt:
        payload['receipt'] = receipt
    payment = Payment.create(payload, uuid.uuid4().hex)
    return payment


def create_recurrent_payment(
    amount_rub: int,
    description: str,
    payment_method_id: str,
    metadata: dict[str, Any],
    receipt: dict[str, Any] | None = None,
) -> Payment:
    payload: dict[str, Any] = {
            'amount': {
                'value': f"{amount_rub:.2f}",
                'currency': 'RUB',
            },
            'payment_method_id': payment_method_id,
            'capture': True,
            'description': description,
            'metadata': metadata,
        }
    if receipt:
        payload['receipt'] = receipt
    payment = Payment.create(payload, uuid.uuid4().hex)
    return payment


def get_payment(payment_id: str) -> Payment:
    return Payment.find_one(payment_id)
