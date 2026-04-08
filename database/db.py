from __future__ import annotations

import asyncio
from pathlib import Path
from datetime import datetime
import aiosqlite


def _utcnow() -> str:
    return datetime.utcnow().isoformat(timespec='seconds')


async def init_db(db_path: str) -> None:
    path = Path(db_path)
    path.parent.mkdir(parents=True, exist_ok=True)

    async with aiosqlite.connect(path) as db:
        await db.execute('PRAGMA journal_mode=WAL;')
        await db.execute(
            '''
            CREATE TABLE IF NOT EXISTS users (
                user_id INTEGER PRIMARY KEY,
                balance INTEGER NOT NULL DEFAULT 0,
                utm_source TEXT,
                referrer_id INTEGER,
                has_purchased INTEGER NOT NULL DEFAULT 0,
                referrer_rewarded INTEGER NOT NULL DEFAULT 0,
                free_trial_used INTEGER NOT NULL DEFAULT 0,
                created_at TEXT NOT NULL
            )
            '''
        )
        await db.execute(
            '''
            CREATE TABLE IF NOT EXISTS effects (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                button_name TEXT NOT NULL,
                prompt TEXT NOT NULL,
                demo_file_id TEXT,
                demo_type TEXT,
                type TEXT NOT NULL DEFAULT 'video',
                is_active INTEGER NOT NULL DEFAULT 1,
                sort_order INTEGER NOT NULL DEFAULT 0,
                created_at TEXT NOT NULL
            )
            '''
        )
        await db.execute(
            '''
            CREATE TABLE IF NOT EXISTS transactions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                amount INTEGER NOT NULL,
                currency TEXT NOT NULL,
                credits INTEGER NOT NULL,
                provider TEXT NOT NULL,
                status TEXT NOT NULL,
                provider_payment_id TEXT,
                payload TEXT,
                created_at TEXT NOT NULL
            )
            '''
        )
        await db.execute(
            '''
            CREATE TABLE IF NOT EXISTS promocodes (
                code TEXT PRIMARY KEY,
                credits INTEGER NOT NULL,
                is_active INTEGER NOT NULL DEFAULT 1,
                used_by INTEGER,
                used_at TEXT,
                created_at TEXT NOT NULL
            )
            '''
        )
        await db.execute(
            '''
            CREATE TABLE IF NOT EXISTS pending_actions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                tx_id INTEGER NOT NULL,
                user_id INTEGER NOT NULL,
                action_type TEXT NOT NULL,
                action_payload TEXT NOT NULL,
                is_active INTEGER NOT NULL DEFAULT 1,
                created_at TEXT NOT NULL
            )
            '''
        )
        await db.execute(
            '''
            CREATE TABLE IF NOT EXISTS admins (
                user_id INTEGER PRIMARY KEY,
                added_by INTEGER,
                created_at TEXT NOT NULL
            )
            '''
        )
        await db.execute(
            '''
            CREATE TABLE IF NOT EXISTS subscriptions (
                user_id INTEGER PRIMARY KEY,
                plan_id TEXT NOT NULL,
                provider TEXT NOT NULL,
                auto_renew INTEGER NOT NULL DEFAULT 0,
                payment_method_id TEXT,
                current_period_start TEXT NOT NULL,
                current_period_end TEXT NOT NULL,
                status TEXT NOT NULL,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
            '''
        )
        await db.execute(
            '''
            CREATE TABLE IF NOT EXISTS mailer_state (
                id INTEGER PRIMARY KEY CHECK (id = 1),
                last_effect_id INTEGER,
                last_type TEXT,
                last_video_id INTEGER,
                last_photo_id INTEGER,
                updated_at TEXT NOT NULL
            )
            '''
        )
        await db.commit()


async def ensure_schema(db_path: str) -> None:
    async with aiosqlite.connect(db_path) as db:
        # add sort_order to effects if missing
        cur = await db.execute('PRAGMA table_info(effects)')
        cols = [row[1] for row in await cur.fetchall()]
        cur_users = await db.execute('PRAGMA table_info(users)')
        user_cols = [row[1] for row in await cur_users.fetchall()]
        if 'free_trial_used' not in user_cols:
            await db.execute('ALTER TABLE users ADD COLUMN free_trial_used INTEGER NOT NULL DEFAULT 0')
        if 'sort_order' not in cols:
            await db.execute('ALTER TABLE effects ADD COLUMN sort_order INTEGER NOT NULL DEFAULT 0')
        if 'type' not in cols:
            await db.execute('ALTER TABLE effects ADD COLUMN type TEXT NOT NULL DEFAULT "video"')
        await db.execute('UPDATE effects SET sort_order = id WHERE sort_order = 0')
        await db.execute('UPDATE effects SET type = "video" WHERE type IS NULL OR type = ""')
        await db.commit()

        cur = await db.execute('PRAGMA table_info(mailer_state)')
        cols = [row[1] for row in await cur.fetchall()]
        if 'last_type' not in cols:
            await db.execute('ALTER TABLE mailer_state ADD COLUMN last_type TEXT')
        if 'last_video_id' not in cols:
            await db.execute('ALTER TABLE mailer_state ADD COLUMN last_video_id INTEGER')
        if 'last_photo_id' not in cols:
            await db.execute('ALTER TABLE mailer_state ADD COLUMN last_photo_id INTEGER')
        await db.commit()


async def ensure_indexes(db_path: str) -> None:
    async with aiosqlite.connect(db_path) as db:
        await db.execute('CREATE INDEX IF NOT EXISTS idx_users_utm ON users(utm_source);')
        await db.execute('CREATE INDEX IF NOT EXISTS idx_tx_user ON transactions(user_id);')
        await db.execute('CREATE INDEX IF NOT EXISTS idx_tx_status ON transactions(status);')
        await db.execute('CREATE INDEX IF NOT EXISTS idx_effects_active ON effects(is_active);')
        await db.execute('CREATE INDEX IF NOT EXISTS idx_effects_sort ON effects(sort_order);')
        await db.execute('CREATE INDEX IF NOT EXISTS idx_promocodes_active ON promocodes(is_active);')
        await db.execute('CREATE INDEX IF NOT EXISTS idx_pending_tx ON pending_actions(tx_id);')
        await db.execute('CREATE INDEX IF NOT EXISTS idx_subscriptions_end ON subscriptions(current_period_end);')
        await db.commit()


async def setup(db_path: str) -> None:
    await init_db(db_path)
    await ensure_schema(db_path)
    await ensure_indexes(db_path)


if __name__ == '__main__':
    asyncio.run(setup('database/database.db'))
