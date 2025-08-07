"""
Configuration settings for the Telegram astrology bot.

This module stores constants such as the bot token, payment provider token,
administrator identifiers and other defaults used throughout the application.

Before running the bot you MUST replace the placeholder strings with your
actual Telegram bot token and payment provider token. You may also adjust
the pricing and referral bonus values to suit your needs.
"""

from datetime import timedelta

# Telegram bot API token.  
# Obtain this value by creating a bot via the BotFather (https://t.me/botfather)
# and replace the placeholder below.
BOT_TOKEN: str = "REPLACE_WITH_YOUR_BOT_TOKEN"

# Payment provider token for Telegram Payments.  
# You can obtain this from your payment provider (for example, Stripe or the
# official Telegram test provider).  
# See https://core.telegram.org/bots/payments for details.
PAYMENT_PROVIDER_TOKEN: str = "REPLACE_WITH_YOUR_PROVIDER_TOKEN"

# List of Telegram user IDs that have administrative privileges.  
# Administrators can use commands such as /broadcast to send messages to all
# registered users.  
# Populate this list with your own Telegram user ID and any additional admin IDs.
ADMIN_IDS: list[int] = []

# Referral program settings.  
# When a new user registers using a referral link, the owner of that link will
# receive REFERRAL_BONUS points. You may adjust this value as needed.
REFERRAL_BONUS: int = 10

# Subscription settings.  
# PRICE is the amount (in the smallest currency unit, e.g. cents or kopeks)
# charged for a subscription period.  
# PERIOD defines the duration of the subscription (e.g. one month).  
# CURRENCY must be an ISO 4217 currency code recognised by Telegram Payments.
SUBSCRIPTION_PRICE: int = 49900  # price in cents (e.g. 499.00 RUB)
SUBSCRIPTION_CURRENCY: str = "RUB"
SUBSCRIPTION_PERIOD: timedelta = timedelta(days=30)

# Default daily dispatch time for users who do not specify a time.  
# Format is HH:MM using 24‑hour time.  
# Users can later change this via the /menu command.
DEFAULT_MESSAGE_TIME: str = "09:00"

# Path to the SQLite database file used by the bot.  
# The database will be created automatically on first run.
DATABASE_PATH: str = "data/astrology_bot.db"
