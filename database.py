import sqlite3
import time
from typing import Optional, Tuple

DB_PATH = "bot_database.db"


def get_connection():
    return sqlite3.connect(DB_PATH)


def init_db():
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS users (
                user_id INTEGER PRIMARY KEY,
                username TEXT,
                first_name TEXT,
                referrer_id INTEGER,
                sub_expires_at INTEGER DEFAULT 0,
                has_purchased INTEGER DEFAULT 0,
                promo_code TEXT DEFAULT NULL,
                created_at INTEGER
            )
            """
        )
        conn.commit()


def get_user(user_id: int) -> Optional[dict]:
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute(
            "SELECT user_id, username, first_name, referrer_id, sub_expires_at, has_purchased, promo_code FROM users WHERE user_id = ?",
            (user_id,),
        )
        row = cursor.fetchone()
        if row:
            return {
                "user_id": row[0],
                "username": row[1],
                "first_name": row[2],
                "referrer_id": row[3],
                "sub_expires_at": row[4],
                "has_purchased": row[5],
                "promo_code": row[6],
            }
        return None


def register_user(user_id: int, username: Optional[str], first_name: str, referrer_id: Optional[int] = None) -> bool:
    """Регистрирует нового пользователя. Возвращает True, если пользователь новый."""
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT user_id FROM users WHERE user_id = ?", (user_id,))
        if cursor.fetchone():
            # Пользователь уже зарегистрирован, обновим username / first_name
            cursor.execute(
                "UPDATE users SET username = ?, first_name = ? WHERE user_id = ?",
                (username, first_name, user_id),
            )
            conn.commit()
            return False

        # Нельзя пригласить самого себя
        valid_referrer = referrer_id if (referrer_id and referrer_id != user_id) else None

        cursor.execute(
            """
            INSERT INTO users (user_id, username, first_name, referrer_id, created_at)
            VALUES (?, ?, ?, ?, ?)
            """,
            (user_id, username, first_name, valid_referrer, int(time.time())),
        )
        conn.commit()
        return True


def get_referral_stats(user_id: int) -> Tuple[int, bool]:
    """Возвращает (кол-во приглашенных друзей, есть ли хотя бы одна покупка)."""
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT COUNT(*), SUM(has_purchased) FROM users WHERE referrer_id = ?", (user_id,))
        count, purchased_sum = cursor.fetchone()
        count = count or 0
        has_purchased = bool(purchased_sum and purchased_sum > 0)
        return count, has_purchased


def set_user_promo(user_id: int, promo_code: str):
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("UPDATE users SET promo_code = ? WHERE user_id = ?", (promo_code, user_id))
        conn.commit()


def activate_subscription(user_id: int, days: int = 30):
    now = int(time.time())
    expires = now + (days * 86400)
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute(
            "UPDATE users SET sub_expires_at = ?, has_purchased = 1 WHERE user_id = ?",
            (expires, user_id),
        )
        conn.commit()
