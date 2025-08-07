"""
Database helper module for the Telegram astrology bot.

This module encapsulates all interactions with the underlying SQLite
database. It defines a simple schema to store user information, referral
relationships, and payment records. High‑level functions are provided to
create and retrieve users, update their preferences, manage subscription
status, and account for referral bonuses.

All methods in this module are synchronous because SQLite is local and
relatively fast. For larger deployments you may wish to replace SQLite
with a full‑fledged database and implement asynchronous I/O accordingly.
"""

from __future__ import annotations

import os
import secrets
import sqlite3
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional, Tuple

from config import DATABASE_PATH, REFERRAL_BONUS, SUBSCRIPTION_PERIOD


class Database:
    """Wrapper around a SQLite database used by the bot."""

    def __init__(self, db_path: str = DATABASE_PATH) -> None:
        self.db_path = db_path
        # Ensure parent directory exists
        os.makedirs(os.path.dirname(db_path), exist_ok=True)
        self.conn = sqlite3.connect(self.db_path, check_same_thread=False)
        self.conn.row_factory = sqlite3.Row
        self._create_tables()

    def _create_tables(self) -> None:
        """Create the required tables if they do not already exist."""
        cur = self.conn.cursor()
        # Users table stores all personal data and subscription info
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS users (
                user_id INTEGER PRIMARY KEY,
                chat_id INTEGER NOT NULL,
                name TEXT,
                birth_date TEXT,
                birth_time TEXT,
                birth_place TEXT,
                message_time TEXT,
                registered_on TEXT,
                referral_code TEXT UNIQUE,
                referred_by TEXT,
                points INTEGER DEFAULT 0,
                is_subscribed INTEGER DEFAULT 0,
                subscription_expiry TEXT
            )
            """
        )
        # Referrals table keeps a record of who invited whom
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS referrals (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                referrer_code TEXT NOT NULL,
                referred_user_id INTEGER NOT NULL,
                timestamp TEXT NOT NULL
            )
            """
        )
        # Payments table tracks successful payments for future auditing
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS payments (
                payment_id TEXT PRIMARY KEY,
                user_id INTEGER NOT NULL,
                amount INTEGER NOT NULL,
                currency TEXT NOT NULL,
                status TEXT NOT NULL,
                timestamp TEXT NOT NULL
            )
            """
        )
        self.conn.commit()

    # ------------------------------------------------------------------
    # User management
    # ------------------------------------------------------------------
    def add_user(
        self,
        user_id: int,
        chat_id: int,
        name: str,
        birth_date: str,
        birth_time: str,
        birth_place: str,
        message_time: str,
        referred_by: Optional[str] = None,
    ) -> None:
        """Insert a new user into the database.

        If the user already exists, this call has no effect.
        """
        if self.get_user(user_id) is not None:
            return
        referral_code = self._generate_unique_code()
        now = datetime.utcnow().isoformat()
        self.conn.execute(
            """
            INSERT INTO users (
                user_id, chat_id, name, birth_date, birth_time,
                birth_place, message_time, registered_on,
                referral_code, referred_by
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                user_id,
                chat_id,
                name,
                birth_date,
                birth_time,
                birth_place,
                message_time,
                now,
                referral_code,
                referred_by,
            ),
        )
        # If the user was referred by someone, credit that user
        if referred_by:
            # Add a record to the referrals table
            self.conn.execute(
                """
                INSERT INTO referrals (referrer_code, referred_user_id, timestamp)
                VALUES (?, ?, ?)
                """,
                (referred_by, user_id, now),
            )
            # Award points to referrer
            self.conn.execute(
                """
                UPDATE users
                SET points = points + ?
                WHERE referral_code = ?
                """,
                (REFERRAL_BONUS, referred_by),
            )
        self.conn.commit()

    def get_user(self, user_id: int) -> Optional[sqlite3.Row]:
        """Retrieve a user's record by their Telegram user ID."""
        cur = self.conn.execute(
            "SELECT * FROM users WHERE user_id = ?", (user_id,)
        )
        row = cur.fetchone()
        return row

    def update_user(self, user_id: int, **kwargs: Any) -> None:
        """Update one or more columns of a user's record.

        Keyword arguments correspond to columns in the users table. Only
        provided keys will be updated. Example:

            db.update_user(12345, name="Alice", message_time="10:00")
        """
        if not kwargs:
            return
        columns = ", ".join(f"{key} = ?" for key in kwargs.keys())
        params = list(kwargs.values()) + [user_id]
        self.conn.execute(
            f"UPDATE users SET {columns} WHERE user_id = ?",
            params,
        )
        self.conn.commit()

    def delete_user(self, user_id: int) -> None:
        """Remove a user from the database (useful for testing)."""
        self.conn.execute("DELETE FROM users WHERE user_id = ?", (user_id,))
        self.conn.commit()

    def get_users_by_time(self, message_time: str) -> List[sqlite3.Row]:
        """Return all users who have subscribed to receive their daily message at the given time.

        The time should be in HH:MM format using a 24‑hour clock. The
        returned rows include both subscribed and unsubscribed users;
        business logic elsewhere should handle free trials and subscription
        status.
        """
        cur = self.conn.execute(
            "SELECT * FROM users WHERE message_time = ?",
            (message_time,),
        )
        return cur.fetchall()

    def get_all_users(self) -> List[sqlite3.Row]:
        """Return a list of all user records."""
        cur = self.conn.execute("SELECT * FROM users")
        return cur.fetchall()

    # ------------------------------------------------------------------
    # Referral management
    # ------------------------------------------------------------------
    def _generate_unique_code(self) -> str:
        """Generate a unique referral code consisting of hexadecimal characters."""
        while True:
            code = secrets.token_hex(4)  # 8 characters
            cur = self.conn.execute(
                "SELECT 1 FROM users WHERE referral_code = ?", (code,)
            )
            if cur.fetchone() is None:
                return code

    def get_referral_code(self, user_id: int) -> Optional[str]:
        """Return the referral code associated with a user."""
        row = self.get_user(user_id)
        if row:
            return row["referral_code"]
        return None

    def get_referrer_by_code(self, code: str) -> Optional[int]:
        """Return the user ID of the referrer associated with a referral code."""
        cur = self.conn.execute(
            "SELECT user_id FROM users WHERE referral_code = ?",
            (code,),
        )
        row = cur.fetchone()
        return row["user_id"] if row else None

    def get_referral_status(self, user_id: int) -> Tuple[int, int]:
        """Return the number of referrals and the total bonus points for a user."""
        # Count referrals
        code = self.get_referral_code(user_id)
        if not code:
            return (0, 0)
        cur = self.conn.execute(
            "SELECT COUNT(*) FROM referrals WHERE referrer_code = ?",
            (code,),
        )
        count = cur.fetchone()[0]
        # Points
        row = self.get_user(user_id)
        points = row["points"] if row else 0
        return (count, points)

    # ------------------------------------------------------------------
    # Subscription management
    # ------------------------------------------------------------------
    def set_subscription(self, user_id: int, expiry: datetime) -> None:
        """Update a user's subscription status and expiry date."""
        self.conn.execute(
            "UPDATE users SET is_subscribed = 1, subscription_expiry = ? WHERE user_id = ?",
            (expiry.isoformat(), user_id),
        )
        self.conn.commit()

    def check_subscription(self, user_id: int) -> bool:
        """Return True if the user has an active subscription, otherwise False."""
        row = self.get_user(user_id)
        if not row:
            return False
        if row["is_subscribed"] != 1 or not row["subscription_expiry"]:
            return False
        expiry = datetime.fromisoformat(row["subscription_expiry"])
        return expiry > datetime.utcnow()

    # ------------------------------------------------------------------
    # Payment management
    # ------------------------------------------------------------------
    def record_payment(
        self, payment_id: str, user_id: int, amount: int, currency: str, status: str
    ) -> None:
        """Insert a payment record into the database."""
        now = datetime.utcnow().isoformat()
        self.conn.execute(
            """
            INSERT OR REPLACE INTO payments (payment_id, user_id, amount, currency, status, timestamp)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (payment_id, user_id, amount, currency, status, now),
        )
        self.conn.commit()
