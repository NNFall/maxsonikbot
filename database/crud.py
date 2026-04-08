from __future__ import annotations

from datetime import datetime
from typing import Any
import aiosqlite


def _utcnow() -> str:
    return datetime.utcnow().isoformat(timespec='seconds')


async def add_user(db_path: str, user_id: int, utm_source: str | None = None, referrer_id: int | None = None) -> None:
    async with aiosqlite.connect(db_path) as db:
        await db.execute(
            'INSERT OR IGNORE INTO users (user_id, utm_source, referrer_id, created_at) VALUES (?, ?, ?, ?)'
            , (user_id, utm_source, referrer_id, _utcnow())
        )
        if utm_source:
            await db.execute(
                'UPDATE users SET utm_source = COALESCE(utm_source, ?) WHERE user_id = ?'
                , (utm_source, user_id)
            )
        if referrer_id and referrer_id != user_id:
            await db.execute(
                'UPDATE users SET referrer_id = COALESCE(referrer_id, ?) WHERE user_id = ?'
                , (referrer_id, user_id)
            )
        await db.commit()


async def get_user(db_path: str, user_id: int) -> dict[str, Any] | None:
    async with aiosqlite.connect(db_path) as db:
        db.row_factory = aiosqlite.Row
        cur = await db.execute('SELECT * FROM users WHERE user_id = ?', (user_id,))
        row = await cur.fetchone()
        return dict(row) if row else None


async def list_user_ids(db_path: str) -> list[int]:
    async with aiosqlite.connect(db_path) as db:
        cur = await db.execute('SELECT user_id FROM users ORDER BY created_at ASC')
        rows = await cur.fetchall()
        return [int(row[0]) for row in rows]


async def count_users(db_path: str) -> int:
    async with aiosqlite.connect(db_path) as db:
        cur = await db.execute('SELECT COUNT(*) FROM users')
        row = await cur.fetchone()
        return int(row[0]) if row else 0


async def get_balance(db_path: str, user_id: int) -> int:
    async with aiosqlite.connect(db_path) as db:
        cur = await db.execute('SELECT balance FROM users WHERE user_id = ?', (user_id,))
        row = await cur.fetchone()
        return int(row[0]) if row else 0


async def update_balance(db_path: str, user_id: int, delta: int) -> None:
    async with aiosqlite.connect(db_path) as db:
        await db.execute('UPDATE users SET balance = balance + ? WHERE user_id = ?', (delta, user_id))
        await db.commit()


async def set_balance(db_path: str, user_id: int, value: int) -> None:
    async with aiosqlite.connect(db_path) as db:
        await db.execute('UPDATE users SET balance = ? WHERE user_id = ?', (value, user_id))
        await db.commit()


async def set_has_purchased(db_path: str, user_id: int, value: int = 1) -> None:
    async with aiosqlite.connect(db_path) as db:
        await db.execute('UPDATE users SET has_purchased = ? WHERE user_id = ?', (value, user_id))
        await db.commit()


async def set_referrer_rewarded(db_path: str, user_id: int, value: int = 1) -> None:
    async with aiosqlite.connect(db_path) as db:
        await db.execute('UPDATE users SET referrer_rewarded = ? WHERE user_id = ?', (value, user_id))
        await db.commit()


async def set_free_trial_used(db_path: str, user_id: int, value: int = 1) -> None:
    async with aiosqlite.connect(db_path) as db:
        await db.execute('UPDATE users SET free_trial_used = ? WHERE user_id = ?', (value, user_id))
        await db.commit()


async def list_effects(
    db_path: str,
    active_only: bool = True,
    effect_type: str | None = None,
) -> list[dict[str, Any]]:
    query = 'SELECT * FROM effects'
    params: list[Any] = []
    where = []
    if active_only:
        where.append('is_active = 1')
    if effect_type:
        where.append('type = ?')
        params.append(effect_type)
    if where:
        query += ' WHERE ' + ' AND '.join(where)
    query += ' ORDER BY sort_order DESC, id ASC'
    async with aiosqlite.connect(db_path) as db:
        db.row_factory = aiosqlite.Row
        cur = await db.execute(query, tuple(params))
        rows = await cur.fetchall()
        return [dict(row) for row in rows]


async def get_effect(db_path: str, effect_id: int) -> dict[str, Any] | None:
    async with aiosqlite.connect(db_path) as db:
        db.row_factory = aiosqlite.Row
        cur = await db.execute('SELECT * FROM effects WHERE id = ?', (effect_id,))
        row = await cur.fetchone()
        return dict(row) if row else None


async def get_effect_by_name(db_path: str, button_name: str, effect_type: str | None = None) -> dict[str, Any] | None:
    async with aiosqlite.connect(db_path) as db:
        db.row_factory = aiosqlite.Row
        if effect_type:
            cur = await db.execute(
                'SELECT * FROM effects WHERE button_name = ? AND type = ?',
                (button_name, effect_type),
            )
        else:
            cur = await db.execute('SELECT * FROM effects WHERE button_name = ?', (button_name,))
        row = await cur.fetchone()
        return dict(row) if row else None


async def add_effect(
    db_path: str,
    button_name: str,
    prompt: str,
    demo_file_id: str | None = None,
    demo_type: str | None = None,
    effect_type: str = 'video',
) -> int:
    async with aiosqlite.connect(db_path) as db:
        cur_max = await db.execute('SELECT COALESCE(MAX(sort_order), 0) FROM effects')
        max_sort = (await cur_max.fetchone())[0]
        cur = await db.execute(
            'INSERT INTO effects (button_name, prompt, demo_file_id, demo_type, type, sort_order, created_at) '
            'VALUES (?, ?, ?, ?, ?, ?, ?)'
            , (button_name, prompt, demo_file_id, demo_type, effect_type, int(max_sort) + 1, _utcnow())
        )
        await db.commit()
        return int(cur.lastrowid)


async def deactivate_effect(db_path: str, effect_id: int) -> None:
    async with aiosqlite.connect(db_path) as db:
        await db.execute('UPDATE effects SET is_active = 0 WHERE id = ?', (effect_id,))
        await db.commit()


async def set_effect_top(db_path: str, effect_id: int) -> None:
    async with aiosqlite.connect(db_path) as db:
        cur_max = await db.execute('SELECT COALESCE(MAX(sort_order), 0) FROM effects')
        max_sort = (await cur_max.fetchone())[0]
        await db.execute('UPDATE effects SET sort_order = ? WHERE id = ?', (int(max_sort) + 1, effect_id))
        await db.commit()


async def create_transaction(
    db_path: str,
    user_id: int,
    amount: int,
    currency: str,
    credits: int,
    provider: str,
    status: str,
    provider_payment_id: str | None = None,
    payload: str | None = None,
) -> int:
    async with aiosqlite.connect(db_path) as db:
        cur = await db.execute(
            '''
            INSERT INTO transactions (user_id, amount, currency, credits, provider, status, provider_payment_id, payload, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            '''
            , (user_id, amount, currency, credits, provider, status, provider_payment_id, payload, _utcnow())
        )
        await db.commit()
        return int(cur.lastrowid)


async def update_transaction_status(
    db_path: str,
    tx_id: int,
    status: str,
    provider_payment_id: str | None = None,
    payload: str | None = None,
) -> None:
    async with aiosqlite.connect(db_path) as db:
        await db.execute(
            '''
            UPDATE transactions
            SET status = ?, provider_payment_id = COALESCE(?, provider_payment_id), payload = COALESCE(?, payload)
            WHERE id = ?
            '''
            , (status, provider_payment_id, payload, tx_id)
        )
        await db.commit()


async def get_transaction(db_path: str, tx_id: int) -> dict[str, Any] | None:
    async with aiosqlite.connect(db_path) as db:
        db.row_factory = aiosqlite.Row
        cur = await db.execute('SELECT * FROM transactions WHERE id = ?', (tx_id,))
        row = await cur.fetchone()
        return dict(row) if row else None


async def get_transaction_by_payload(db_path: str, payload: str, provider: str) -> dict[str, Any] | None:
    async with aiosqlite.connect(db_path) as db:
        db.row_factory = aiosqlite.Row
        cur = await db.execute(
            '''
            SELECT *
            FROM transactions
            WHERE payload = ? AND provider = ?
            ORDER BY CASE status WHEN 'pending' THEN 0 ELSE 1 END, created_at DESC
            LIMIT 1
            ''',
            (payload, provider),
        )
        row = await cur.fetchone()
        return dict(row) if row else None


async def count_promo_used_users(db_path: str) -> int:
    async with aiosqlite.connect(db_path) as db:
        cur = await db.execute('SELECT COUNT(DISTINCT used_by) FROM promocodes WHERE used_by IS NOT NULL')
        row = await cur.fetchone()
        return int(row[0]) if row else 0


async def count_paid_users(db_path: str) -> int:
    async with aiosqlite.connect(db_path) as db:
        cur = await db.execute('SELECT COUNT(*) FROM users WHERE has_purchased = 1')
        row = await cur.fetchone()
        return int(row[0]) if row else 0


async def count_paid_transactions_by_currency(db_path: str, currency: str) -> int:
    async with aiosqlite.connect(db_path) as db:
        cur = await db.execute(
            'SELECT COUNT(*) FROM transactions WHERE status = ? AND currency = ?',
            ('paid', currency),
        )
        row = await cur.fetchone()
        return int(row[0]) if row else 0


async def count_paid_users_by_currency(db_path: str, currency: str) -> int:
    async with aiosqlite.connect(db_path) as db:
        cur = await db.execute(
            'SELECT COUNT(DISTINCT user_id) FROM transactions WHERE status = ? AND currency = ?',
            ('paid', currency),
        )
        row = await cur.fetchone()
        return int(row[0]) if row else 0


async def sum_paid_by_currency(db_path: str) -> list[tuple[str, int]]:
    async with aiosqlite.connect(db_path) as db:
        cur = await db.execute(
            'SELECT currency, COALESCE(SUM(amount), 0) FROM transactions WHERE status = ? GROUP BY currency',
            ('paid',),
        )
        rows = await cur.fetchall()
        return [(row[0], int(row[1])) for row in rows]


async def get_pending_transaction_by_user(
    db_path: str,
    user_id: int,
    provider: str | None = None,
) -> dict[str, Any] | None:
    query = 'SELECT * FROM transactions WHERE user_id = ? AND status = ?'
    params: list[Any] = [user_id, 'pending']
    if provider:
        query += ' AND provider = ?'
        params.append(provider)
    query += ' ORDER BY created_at DESC LIMIT 1'
    async with aiosqlite.connect(db_path) as db:
        db.row_factory = aiosqlite.Row
        cur = await db.execute(query, tuple(params))
        row = await cur.fetchone()
        return dict(row) if row else None


async def create_promocode(db_path: str, code: str, credits: int) -> None:
    async with aiosqlite.connect(db_path) as db:
        await db.execute(
            'INSERT INTO promocodes (code, credits, created_at) VALUES (?, ?, ?)'
            , (code, credits, _utcnow())
        )
        await db.commit()


async def get_promocode(db_path: str, code: str) -> dict[str, Any] | None:
    async with aiosqlite.connect(db_path) as db:
        db.row_factory = aiosqlite.Row
        cur = await db.execute('SELECT * FROM promocodes WHERE code = ?', (code,))
        row = await cur.fetchone()
        return dict(row) if row else None


async def use_promocode(db_path: str, code: str, user_id: int) -> int | None:
    async with aiosqlite.connect(db_path) as db:
        db.row_factory = aiosqlite.Row
        cur = await db.execute(
            'SELECT * FROM promocodes WHERE code = ? AND is_active = 1 AND used_by IS NULL'
            , (code,)
        )
        row = await cur.fetchone()
        if not row:
            return None
        credits = int(row['credits'])
        await db.execute(
            'UPDATE promocodes SET used_by = ?, used_at = ?, is_active = 0 WHERE code = ?'
            , (user_id, _utcnow(), code)
        )
        await db.commit()
        return credits


async def count_users_by_utm(db_path: str, utm_source: str) -> int:
    async with aiosqlite.connect(db_path) as db:
        cur = await db.execute('SELECT COUNT(*) FROM users WHERE utm_source = ?', (utm_source,))
        row = await cur.fetchone()
        return int(row[0]) if row else 0


async def count_buyers_by_utm(db_path: str, utm_source: str) -> int:
    async with aiosqlite.connect(db_path) as db:
        cur = await db.execute('SELECT COUNT(*) FROM users WHERE utm_source = ? AND has_purchased = 1', (utm_source,))
        row = await cur.fetchone()
        return int(row[0]) if row else 0


async def sum_payments_by_utm(db_path: str, utm_source: str) -> list[tuple[str, int]]:
    async with aiosqlite.connect(db_path) as db:
        cur = await db.execute(
            '''
            SELECT t.currency, COALESCE(SUM(t.amount), 0)
            FROM transactions t
            JOIN users u ON u.user_id = t.user_id
            WHERE u.utm_source = ? AND t.status = 'paid'
            GROUP BY t.currency
            '''
            , (utm_source,)
        )
        rows = await cur.fetchall()
        return [(row[0], int(row[1])) for row in rows]


async def get_referrer(db_path: str, user_id: int) -> int | None:
    async with aiosqlite.connect(db_path) as db:
        cur = await db.execute('SELECT referrer_id FROM users WHERE user_id = ?', (user_id,))
        row = await cur.fetchone()
        if not row:
            return None
        return int(row[0]) if row[0] is not None else None


async def get_referrer_rewarded(db_path: str, user_id: int) -> int:
    async with aiosqlite.connect(db_path) as db:
        cur = await db.execute('SELECT referrer_rewarded FROM users WHERE user_id = ?', (user_id,))
        row = await cur.fetchone()
        return int(row[0]) if row else 0


async def is_admin(db_path: str, user_id: int) -> bool:
    async with aiosqlite.connect(db_path) as db:
        cur = await db.execute('SELECT 1 FROM admins WHERE user_id = ?', (user_id,))
        row = await cur.fetchone()
        return bool(row)


async def add_admin(db_path: str, user_id: int, added_by: int) -> None:
    async with aiosqlite.connect(db_path) as db:
        await db.execute(
            'INSERT OR IGNORE INTO admins (user_id, added_by, created_at) VALUES (?, ?, ?)',
            (user_id, added_by, _utcnow()),
        )
        await db.commit()


async def remove_admin(db_path: str, user_id: int) -> None:
    async with aiosqlite.connect(db_path) as db:
        await db.execute('DELETE FROM admins WHERE user_id = ?', (user_id,))
        await db.commit()


async def list_admins(db_path: str) -> list[int]:
    async with aiosqlite.connect(db_path) as db:
        cur = await db.execute('SELECT user_id FROM admins ORDER BY created_at ASC')
        rows = await cur.fetchall()
        return [int(row[0]) for row in rows]


async def upsert_subscription(
    db_path: str,
    user_id: int,
    plan_id: str,
    provider: str,
    auto_renew: int,
    payment_method_id: str | None,
    current_period_start: str,
    current_period_end: str,
    status: str,
) -> None:
    async with aiosqlite.connect(db_path) as db:
        await db.execute(
            '''
            INSERT INTO subscriptions
                (user_id, plan_id, provider, auto_renew, payment_method_id, current_period_start, current_period_end, status, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(user_id) DO UPDATE SET
                plan_id=excluded.plan_id,
                provider=excluded.provider,
                auto_renew=excluded.auto_renew,
                payment_method_id=excluded.payment_method_id,
                current_period_start=excluded.current_period_start,
                current_period_end=excluded.current_period_end,
                status=excluded.status,
                updated_at=excluded.updated_at
            ''',
            (
                user_id,
                plan_id,
                provider,
                auto_renew,
                payment_method_id,
                current_period_start,
                current_period_end,
                status,
                _utcnow(),
                _utcnow(),
            ),
        )
        await db.commit()


async def get_subscription(db_path: str, user_id: int) -> dict[str, Any] | None:
    async with aiosqlite.connect(db_path) as db:
        db.row_factory = aiosqlite.Row
        cur = await db.execute('SELECT * FROM subscriptions WHERE user_id = ?', (user_id,))
        row = await cur.fetchone()
        return dict(row) if row else None


async def cancel_subscription(db_path: str, user_id: int) -> None:
    async with aiosqlite.connect(db_path) as db:
        await db.execute(
            'UPDATE subscriptions SET auto_renew = 0, status = ?, updated_at = ? WHERE user_id = ?',
            ('inactive', _utcnow(), user_id),
        )
        await db.commit()


async def expire_subscription(db_path: str, user_id: int) -> None:
    async with aiosqlite.connect(db_path) as db:
        await db.execute(
            '''
            UPDATE subscriptions
            SET status = ?, auto_renew = 0, payment_method_id = NULL, updated_at = ?
            WHERE user_id = ?
            ''',
            ('expired', _utcnow(), user_id),
        )
        await db.commit()


async def set_subscription_period_end(db_path: str, user_id: int, current_period_end: str) -> None:
    async with aiosqlite.connect(db_path) as db:
        await db.execute(
            'UPDATE subscriptions SET current_period_end = ?, updated_at = ? WHERE user_id = ?',
            (current_period_end, _utcnow(), user_id),
        )
        await db.commit()




async def list_due_subscriptions(db_path: str, now_iso: str) -> list[dict[str, Any]]:
    async with aiosqlite.connect(db_path) as db:
        db.row_factory = aiosqlite.Row
        cur = await db.execute(
            '''
            SELECT * FROM subscriptions
            WHERE status = 'active' AND auto_renew = 1 AND current_period_end <= ?
            ''',
            (now_iso,),
        )
        rows = await cur.fetchall()
        return [dict(row) for row in rows]


async def list_expired_subscriptions(db_path: str, now_iso: str) -> list[dict[str, Any]]:
    async with aiosqlite.connect(db_path) as db:
        db.row_factory = aiosqlite.Row
        cur = await db.execute(
            '''
            SELECT * FROM subscriptions
            WHERE status IN ('active', 'inactive') AND auto_renew = 0 AND current_period_end <= ?
            ''',
            (now_iso,),
        )
        rows = await cur.fetchall()
        return [dict(row) for row in rows]


async def is_subscription_active(db_path: str, user_id: int, now_iso: str) -> bool:
    async with aiosqlite.connect(db_path) as db:
        cur = await db.execute(
            '''
            SELECT 1 FROM subscriptions
            WHERE user_id = ? AND status IN ('active', 'inactive') AND current_period_end >= ?
            ''',
            (user_id, now_iso),
        )
        row = await cur.fetchone()
        return bool(row)


async def list_active_subscription_user_ids(db_path: str, now_iso: str) -> list[int]:
    async with aiosqlite.connect(db_path) as db:
        cur = await db.execute(
            '''
            SELECT user_id FROM subscriptions
            WHERE status IN ('active', 'inactive') AND current_period_end >= ?
            ''',
            (now_iso,),
        )
        rows = await cur.fetchall()
        return [int(row[0]) for row in rows]


async def get_mailer_state(db_path: str) -> dict[str, Any] | None:
    async with aiosqlite.connect(db_path) as db:
        db.row_factory = aiosqlite.Row
        cur = await db.execute('SELECT * FROM mailer_state WHERE id = 1')
        row = await cur.fetchone()
        return dict(row) if row else None


async def set_mailer_state(
    db_path: str,
    last_effect_id: int | None,
    last_type: str | None = None,
    last_video_id: int | None = None,
    last_photo_id: int | None = None,
) -> None:
    async with aiosqlite.connect(db_path) as db:
        await db.execute(
            '''
            INSERT INTO mailer_state (id, last_effect_id, last_type, last_video_id, last_photo_id, updated_at)
            VALUES (1, ?, ?, ?, ?, ?)
            ON CONFLICT(id) DO UPDATE SET
                last_effect_id=excluded.last_effect_id,
                last_type=COALESCE(excluded.last_type, last_type),
                last_video_id=COALESCE(excluded.last_video_id, last_video_id),
                last_photo_id=COALESCE(excluded.last_photo_id, last_photo_id),
                updated_at=excluded.updated_at
            ''',
            (last_effect_id, last_type, last_video_id, last_photo_id, _utcnow()),
        )
        await db.commit()


async def count_active_subscriptions(db_path: str, now_iso: str) -> int:
    async with aiosqlite.connect(db_path) as db:
        cur = await db.execute(
            '''
            SELECT COUNT(*) FROM subscriptions
            WHERE status = 'active' AND current_period_end >= ?
            ''',
            (now_iso,),
        )
        row = await cur.fetchone()
        return int(row[0]) if row else 0


async def count_active_subscriptions_by_plan(db_path: str, now_iso: str) -> dict[str, int]:
    async with aiosqlite.connect(db_path) as db:
        cur = await db.execute(
            '''
            SELECT plan_id, COUNT(*) FROM subscriptions
            WHERE status = 'active' AND current_period_end >= ?
            GROUP BY plan_id
            ''',
            (now_iso,),
        )
        rows = await cur.fetchall()
        return {row[0]: int(row[1]) for row in rows}


async def mark_subscription_status(db_path: str, user_id: int, status: str) -> None:
    async with aiosqlite.connect(db_path) as db:
        await db.execute('UPDATE subscriptions SET status = ?, updated_at = ? WHERE user_id = ?', (status, _utcnow(), user_id))
        await db.commit()


async def list_utm_stats(db_path: str) -> list[dict[str, Any]]:
    async with aiosqlite.connect(db_path) as db:
        db.row_factory = aiosqlite.Row
        cur = await db.execute(
            '''
            SELECT
                utm_source,
                COUNT(*) AS users,
                SUM(CASE WHEN has_purchased = 1 THEN 1 ELSE 0 END) AS buyers
            FROM users
            GROUP BY utm_source
            ORDER BY users DESC
            '''
        )
        rows = await cur.fetchall()
        return [dict(row) for row in rows]


async def list_utm_payments(db_path: str) -> list[tuple[str | None, str, int]]:
    async with aiosqlite.connect(db_path) as db:
        cur = await db.execute(
            '''
            SELECT u.utm_source, t.currency, COALESCE(SUM(t.amount), 0)
            FROM transactions t
            JOIN users u ON u.user_id = t.user_id
            WHERE t.status = 'paid'
            GROUP BY u.utm_source, t.currency
            '''
        )
        rows = await cur.fetchall()
        return [(row[0], row[1], int(row[2])) for row in rows]


async def create_pending_action(
    db_path: str,
    tx_id: int,
    user_id: int,
    action_type: str,
    action_payload: str,
) -> None:
    async with aiosqlite.connect(db_path) as db:
        await db.execute(
            '''
            INSERT INTO pending_actions (tx_id, user_id, action_type, action_payload, created_at)
            VALUES (?, ?, ?, ?, ?)
            ''',
            (tx_id, user_id, action_type, action_payload, _utcnow()),
        )
        await db.commit()


async def consume_pending_action(db_path: str, tx_id: int) -> dict[str, Any] | None:
    async with aiosqlite.connect(db_path) as db:
        db.row_factory = aiosqlite.Row
        cur = await db.execute(
            'SELECT * FROM pending_actions WHERE tx_id = ? AND is_active = 1',
            (tx_id,),
        )
        row = await cur.fetchone()
        if not row:
            return None
        await db.execute('UPDATE pending_actions SET is_active = 0 WHERE id = ?', (row['id'],))
        await db.commit()
        return dict(row)
