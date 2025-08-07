"""
Payment handling module for the Telegram astrology bot.

This module defines helper functions and handlers to facilitate the sale
of subscriptions through Telegram Payments. It integrates with the
database module to record successful payments and update subscription
status accordingly.

Please note that to accept real payments you must set up a payment
provider (for example, Stripe) and obtain a provider token from
@BotFather. For testing purposes, you can use the test provider token
"TEST:...". See https://core.telegram.org/bots/payments for more
information.
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import List

from telegram import LabeledPrice, Message, Update
from telegram.ext import ContextTypes

import config
from database import Database


def build_subscription_invoice(user_id: int) -> dict:
    """Construct the invoice payload for a subscription purchase.

    :param user_id: Telegram user ID to embed in the payload for later
                    identification when processing the successful payment.
    :return: A dictionary containing arguments for ``bot.send_invoice``.
    """
    title = "Астропрогноз – ежемесячная подписка"
    description = (
        "Полный доступ к ежедневным персональным прогнозам, ритуалам и цитатам."\
        "\nПодписка обновляется автоматически каждый месяц."
    )
    # The payload string is used to identify the purchase in the success callback.
    payload = f"subscription_{user_id}"
    prices: List[LabeledPrice] = [LabeledPrice(label="Подписка на месяц", amount=config.SUBSCRIPTION_PRICE)]
    invoice = {
        "title": title,
        "description": description,
        "payload": payload,
        "provider_token": config.PAYMENT_PROVIDER_TOKEN,
        "currency": config.SUBSCRIPTION_CURRENCY,
        "prices": prices,
        "max_tip_amount": 0,
        "need_name": False,
        "need_phone_number": False,
        "need_email": False,
        "need_shipping_address": False,
    }
    return invoice


async def handle_pre_checkout(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Respond to pre‑checkout queries sent by Telegram.

    This handler simply answers the pre‑checkout query affirmatively. You
    could implement additional verification here (e.g. ensuring that the
    payload matches a valid subscription), but for simplicity we accept
    all queries. If you return False with an error message, the payment
    process will be aborted.
    """
    query = update.pre_checkout_query
    if not query:
        return
    await query.answer(ok=True)


async def handle_successful_payment(update: Update, context: ContextTypes.DEFAULT_TYPE, db: Database) -> None:
    """Process a successful payment and update the user's subscription.

    :param update: Update containing the successful payment
    :param context: Callback context
    :param db: Instance of the database module
    """
    message = update.message
    if not message or not message.successful_payment:
        return
    payment = message.successful_payment
    payload = payment.invoice_payload
    logging.info("Successful payment received: %s", payment.to_dict())
    # Extract user id from payload; format is "subscription_<user_id>"
    try:
        user_id = int(payload.split("_")[1])
    except (IndexError, ValueError):
        user_id = message.from_user.id
    # Record the payment in the database
    db.record_payment(
        payment_id=payment.provider_payment_charge_id,
        user_id=user_id,
        amount=payment.total_amount,
        currency=payment.currency,
        status="successful",
    )
    # Update subscription expiry
    expiry = datetime.utcnow() + config.SUBSCRIPTION_PERIOD
    db.set_subscription(user_id, expiry)
    # Notify the user
    await message.reply_text(
        "Спасибо за вашу оплату! Вашa подписка активирована на "
        f"{config.SUBSCRIPTION_PERIOD.days} дней. Приятного чтения!"
    )
