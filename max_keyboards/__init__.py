from .admin_kb import admin_help_attachments
from .common_kb import help_attachments, menu_only_attachments
from .mailer_kb import mailer_attachments
from .main_menu import main_menu_attachments
from .payment_kb import (
    choose_subscription_attachments,
    choose_subscription_prompt_attachments,
    pay_url_attachments,
    payment_success_attachments,
    subscription_manage_attachments,
)
from .tarot_kb import tarot_after_reading_attachments, tarot_open_full_attachments

__all__ = [
    "admin_help_attachments",
    "help_attachments",
    "main_menu_attachments",
    "menu_only_attachments",
    "mailer_attachments",
    "choose_subscription_prompt_attachments",
    "choose_subscription_attachments",
    "pay_url_attachments",
    "payment_success_attachments",
    "subscription_manage_attachments",
    "tarot_open_full_attachments",
    "tarot_after_reading_attachments",
]
