import asyncpg
import os

DATABASE_URL = os.getenv("DATABASE_URL")
pool = None

async def init_db():
    global pool
    pool = await asyncpg.create_pool(DATABASE_URL)

async def close_db():
    await pool.close()

async def create_or_update_user(user_id: int, display_name: str):
    async with pool.acquire() as conn:
        await conn.execute("""
            INSERT INTO users(user_id, display_name)
            VALUES($1, $2)
            ON CONFLICT (user_id) DO UPDATE SET display_name = EXCLUDED.display_name
        """, user_id, display_name)

async def get_user(user_id: int):
    async with pool.acquire() as conn:
        row = await conn.fetchrow("SELECT display_name FROM users WHERE user_id = $1", user_id)
        return row["display_name"] if row else None

async def get_all_users():
    async with pool.acquire() as conn:
        rows = await conn.fetch("SELECT user_id, display_name FROM users")
        return [{"user_id": row["user_id"], "display_name": row["display_name"]} for row in rows]

async def add_transaction(spender_id: int, amount: float, description: str, share: float, debtor_ids: list) -> int:
    async with pool.acquire() as conn:
        async with conn.transaction():
            row = await conn.fetchrow("""
                INSERT INTO transactions(spender, amount, description, share)
                VALUES($1, $2, $3, $4)
                RETURNING id
            """, spender_id, amount, description, share)
            tx_id = row["id"]
            for debtor in debtor_ids:
                await conn.execute("""
                    INSERT INTO debts(transaction_id, debtor_id, status)
                    VALUES($1, $2, 'pending')
                """, tx_id, debtor)
            return tx_id

async def get_pending_debts_for_user(user_id: int):
    async with pool.acquire() as conn:
        rows = await conn.fetch("""
            SELECT t.id, t.amount, t.description, t.share, t.spender
            FROM transactions t
            JOIN debts d ON t.id = d.transaction_id
            WHERE d.debtor_id = $1 AND d.status = 'pending'
        """, user_id)
        return rows

async def mark_debt_as_marked(tx_id: int, debtor_id: int):
    async with pool.acquire() as conn:
        await conn.execute("""
            UPDATE debts SET status = 'marked'
            WHERE transaction_id = $1 AND debtor_id = $2
        """, tx_id, debtor_id)

async def get_pending_confirmations_for_spender(spender_id: int):
    async with pool.acquire() as conn:
        rows = await conn.fetch("""
            SELECT t.id, t.amount, t.description, t.share
            FROM transactions t
            WHERE t.spender = $1 AND EXISTS (
                SELECT 1 FROM debts d WHERE d.transaction_id = t.id AND d.status = 'marked'
            )
        """, spender_id)
        return rows

async def confirm_debt(tx_id: int, debtor_id: int):
    async with pool.acquire() as conn:
        await conn.execute("""
            UPDATE debts SET status = 'confirmed'
            WHERE transaction_id = $1 AND debtor_id = $2
        """, tx_id, debtor_id)

async def get_summary_for_user(user_id: int):
    async with pool.acquire() as conn:
        owe_me = await conn.fetch("""
            SELECT d.debtor_id, d.status, t.id, t.share, t.description
            FROM transactions t
            JOIN debts d ON t.id = d.transaction_id
            WHERE t.spender = $1
        """, user_id)
        i_owe = await conn.fetch("""
            SELECT t.spender, d.status, t.id, t.share, t.description
            FROM transactions t
            JOIN debts d ON t.id = d.transaction_id
            WHERE d.debtor_id = $1
        """, user_id)
        return owe_me, i_owe

async def get_marked_debtors(tx_id: int):
    async with pool.acquire() as conn:
        rows = await conn.fetch("""
            SELECT debtor_id FROM debts
            WHERE transaction_id = $1 AND status = 'marked'
        """, tx_id)
        return [row["debtor_id"] for row in rows]
