import os
from dataclasses import dataclass

from dotenv import load_dotenv

load_dotenv()


def _get_env(name: str, default: str | None = None) -> str | None:
    return os.getenv(name, default)


@dataclass(frozen=True)
class Config:
    bot_token: str
    max_bot_token: str
    kie_api_key: str
    kie_base_url: str
    kie_api_url: str
    kie_image_model: str
    kie_text_image_model: str
    kie_text_url: str
    kie_text_model: str
    replicate_api_token: str
    replicate_base_url: str
    replicate_api_url: str
    replicate_model_version: str
    replicate_image_field: str
    replicate_text_model: str
    replicate_text_version: str
    yookassa_shop_id: str
    yookassa_secret_key: str
    yookassa_receipt_email: str
    yookassa_receipt_phone: str
    yookassa_tax_system_code: str
    yookassa_vat_code: str
    yookassa_item_name: str
    yookassa_payment_subject: str
    yookassa_payment_mode: str
    admin_ids: list[int]
    admin_notify_ids: list[int]
    database_path: str
    media_temp_dir: str
    tarot_cards_dir: str
    tarot_background_path: str
    tarot_layout_path: str
    tarot_progress_sticker_id: str
    tarot_progress_sticker_code: str
    tarot_progress_sticker_url: str
    tarot_progress_text: str
    ref_bonus: int
    tarot_spread_cost: int
    effect_cost: int
    custom_cost_per_sec: int
    photo_effect_cost: int
    photo_custom_cost: int
    stars_rub_rate: float
    stars_provider_token: str
    system_prompt: str
    ffmpeg_path: str
    replicate_aspect_ratio_mode: str
    sub_week_price_rub: int
    sub_week_price_stars: int
    sub_week_generations: int
    sub_week_days: int
    sub_month_price_rub: int
    sub_month_price_stars: int
    sub_month_generations: int
    sub_month_days: int
    support_contact: str
    offer_url: str


def load_config() -> Config:
    admin_ids = [int(x) for x in os.getenv('ADMIN_IDS', '').split(',') if x.strip().isdigit()]
    admin_notify_ids = [int(x) for x in os.getenv('ADMIN_NOTIFY_IDS', '').split(',') if x.strip().isdigit()]

    return Config(
        bot_token=_get_env('BOT_TOKEN', '') or '',
        max_bot_token=_get_env('MAX_BOT_TOKEN', '') or '',
        kie_api_key=_get_env('KIE_API_KEY', '') or '',
        kie_base_url=_get_env('KIE_BASE_URL', 'https://api.kie.ai') or 'https://api.kie.ai',
        kie_api_url=_get_env('KIE_API_URL', 'https://api.kie.ai/api/v1/jobs/createTask') or '',
        kie_image_model=_get_env('KIE_IMAGE_MODEL', 'grok-imagine/image-to-image') or 'grok-imagine/image-to-image',
        kie_text_image_model=_get_env('KIE_TEXT_IMAGE_MODEL', 'grok-imagine/text-to-image') or 'grok-imagine/text-to-image',
        kie_text_url=_get_env('KIE_TEXT_URL', '') or '',
        kie_text_model=_get_env('KIE_TEXT_MODEL', '') or '',
        replicate_api_token=_get_env('REPLICATE_API_TOKEN', '') or '',
        replicate_base_url=_get_env('REPLICATE_BASE_URL', 'https://api.replicate.com') or 'https://api.replicate.com',
        replicate_api_url=_get_env('REPLICATE_API_URL', 'https://api.replicate.com/v1/predictions') or '',
        replicate_model_version=_get_env('REPLICATE_MODEL_VERSION', '') or '',
        replicate_image_field=_get_env('REPLICATE_IMAGE_FIELD', 'image') or 'image',
        replicate_text_model=_get_env('REPLICATE_TEXT_MODEL', '') or '',
        replicate_text_version=_get_env('REPLICATE_TEXT_VERSION', '') or '',
        yookassa_shop_id=_get_env('YOOKASSA_SHOP_ID', '') or '',
        yookassa_secret_key=_get_env('YOOKASSA_SECRET_KEY', '') or '',
        yookassa_receipt_email=_get_env('YOOKASSA_RECEIPT_EMAIL', '') or '',
        yookassa_receipt_phone=_get_env('YOOKASSA_RECEIPT_PHONE', '') or '',
        yookassa_tax_system_code=_get_env('YOOKASSA_TAX_SYSTEM_CODE', '') or '',
        yookassa_vat_code=_get_env('YOOKASSA_VAT_CODE', '1') or '1',
        yookassa_item_name=_get_env('YOOKASSA_ITEM_NAME', 'Подписка на расклады') or 'Подписка на расклады',
        yookassa_payment_subject=_get_env('YOOKASSA_PAYMENT_SUBJECT', '') or '',
        yookassa_payment_mode=_get_env('YOOKASSA_PAYMENT_MODE', '') or '',
        admin_ids=admin_ids,
        admin_notify_ids=admin_notify_ids or admin_ids,
        database_path=_get_env('DATABASE_PATH', 'database/database.db') or 'database/database.db',
        media_temp_dir=_get_env('MEDIA_TEMP_DIR', 'media/temp') or 'media/temp',
        tarot_cards_dir=_get_env('TAROT_CARDS_DIR', 'media/tarot/cards') or 'media/tarot/cards',
        tarot_background_path=_get_env('TAROT_BACKGROUND_PATH', 'media/tarot/backgrounds/main.png') or 'media/tarot/backgrounds/main.png',
        tarot_layout_path=_get_env('TAROT_LAYOUT_PATH', 'media/tarot/layout.json') or 'media/tarot/layout.json',
        tarot_progress_sticker_id=_get_env('TAROT_PROGRESS_STICKER_ID', '') or '',
        tarot_progress_sticker_code=_get_env('TAROT_PROGRESS_STICKER_CODE', '') or '',
        tarot_progress_sticker_url=_get_env('TAROT_PROGRESS_STICKER_URL', '') or '',
        tarot_progress_text=_get_env('TAROT_PROGRESS_TEXT', '✨ Выполняю расклад, смотрю ваши карты...') or '✨ Выполняю расклад, смотрю ваши карты...',
        ref_bonus=int(_get_env('REF_BONUS', '20') or '20'),
        tarot_spread_cost=int(_get_env('TAROT_SPREAD_COST', '1') or '1'),
        effect_cost=int(_get_env('EFFECT_COST', '10') or '10'),
        custom_cost_per_sec=int(_get_env('CUSTOM_COST_PER_SEC', '5') or '5'),
        photo_effect_cost=int(_get_env('PHOTO_EFFECT_COST', '4') or '4'),
        photo_custom_cost=int(_get_env('PHOTO_CUSTOM_COST', '4') or '4'),
        stars_rub_rate=float(_get_env('STARS_RUB_RATE', '2.0') or '2.0'),
        stars_provider_token=_get_env('STARS_PROVIDER_TOKEN', '') or '',
        system_prompt=_get_env('SYSTEM_PROMPT', '') or '',
        ffmpeg_path=_get_env('FFMPEG_PATH', 'ffmpeg') or 'ffmpeg',
        replicate_aspect_ratio_mode=_get_env('REPLICATE_ASPECT_RATIO_MODE', 'match') or 'match',
        sub_week_price_rub=int(_get_env('SUB_WEEK_PRICE_RUB', '199') or '199'),
        sub_week_price_stars=int(_get_env('SUB_WEEK_PRICE_STARS', '199') or '199'),
        sub_week_generations=int(_get_env('SUB_WEEK_GENERATIONS', '15') or '15'),
        sub_week_days=int(_get_env('SUB_WEEK_DAYS', '7') or '7'),
        sub_month_price_rub=int(_get_env('SUB_MONTH_PRICE_RUB', '499') or '499'),
        sub_month_price_stars=int(_get_env('SUB_MONTH_PRICE_STARS', '499') or '499'),
        sub_month_generations=int(_get_env('SUB_MONTH_GENERATIONS', '100') or '100'),
        sub_month_days=int(_get_env('SUB_MONTH_DAYS', '30') or '30'),
        support_contact=_get_env('SUPPORT_CONTACT', '@your_tracksupport') or '@your_tracksupport',
        offer_url=_get_env('OFFER_URL', 'https://example.com/oferta') or 'https://example.com/oferta',
    )
