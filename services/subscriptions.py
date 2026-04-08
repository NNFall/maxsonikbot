from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta

from config import load_config


@dataclass(frozen=True)
class Plan:
    id: str
    title: str
    price_rub: int
    price_stars: int
    generations: int
    days: int


def get_plans() -> dict[str, Plan]:
    cfg = load_config()
    return {
        'week': Plan(
            id='week',
            title='Неделя',
            price_rub=cfg.sub_week_price_rub,
            price_stars=cfg.sub_week_price_stars,
            generations=cfg.sub_week_generations,
            days=cfg.sub_week_days,
        ),
        'month': Plan(
            id='month',
            title='Месяц',
            price_rub=cfg.sub_month_price_rub,
            price_stars=cfg.sub_month_price_stars,
            generations=cfg.sub_month_generations,
            days=cfg.sub_month_days,
        ),
    }


def get_plan(plan_id: str) -> Plan | None:
    return get_plans().get(plan_id)


def calc_period(days: int) -> tuple[str, str]:
    start = datetime.utcnow()
    end = start + timedelta(days=days)
    return start.isoformat(timespec='seconds'), end.isoformat(timespec='seconds')
