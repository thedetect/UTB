"""
Referral system utilities for the Telegram astrology bot.

This module provides helper functions to generate and display referral
links as well as retrieve a user's referral status. The referral code
stored in the database is used as the unique key in links shared with
friends. When a new user starts the bot with a referral code, the
referrer is credited with bonus points.
"""

from __future__ import annotations

from typing import Tuple

import config
from database import Database


def get_referral_link(bot_username: str, referral_code: str) -> str:
    """Return a full t.me link with an encoded referral code.

    A user can share this link with friends. When someone opens it, the
    bot will receive the referral code as the argument to the /start
    command, e.g. /start ABC123.
    """
    return f"https://t.me/{bot_username}?start={referral_code}"


def get_referral_status(db: Database, user_id: int) -> Tuple[int, int]:
    """Return the number of referred users and total points for the given user."""
    return db.get_referral_status(user_id)
