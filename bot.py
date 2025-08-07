"""
Main entry point for the Telegram astrology bot.

This script wires together the various modules – configuration, database
access, astrological calculations, payment processing, referral
handling and the Telegram API – into a cohesive application. The bot
guides the user through registration, stores their preferences, sends
personalised daily messages and manages subscriptions via Telegram
Payments.

Run this module directly to launch the bot. Ensure that you have
configured the BOT_TOKEN and PAYMENT_PROVIDER_TOKEN in config.py before
deploying.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, time
from enum import Enum, auto
from typing import Any, Dict, Optional

from telegram import (
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Update,
    ReplyKeyboardRemove,
)
from telegram.constants import ParseMode
from telegram.ext import (
    Application,
    CallbackQueryHandler,
    CommandHandler,
    ConversationHandler,
    MessageHandler,
    ContextTypes,
    filters,
    PreCheckoutQueryHandler,
)

import config
from astrology import compute_natal_positions, generate_message
from database import Database
from payments import build_subscription_invoice, handle_pre_checkout, handle_successful_payment
from referral import get_referral_link, get_referral_status


logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)


class RegState(Enum):
    """Enumeration of conversation states during registration."""

    NAME = auto()
    BIRTH_DATE = auto()
    BIRTH_TIME = auto()
    BIRTH_PLACE = auto()
    MESSAGE_TIME = auto()
    CONFIRM = auto()


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Entry point for the /start command.

    If the user is already registered, greet them and show menu options. If
    they are new, begin the registration process. Any referral code
    present as an argument to /start will be stored in context for later
    processing when the user completes registration.
    """
    user = update.effective_user
    chat_id = update.effective_chat.id if update.effective_chat else None
    if not user or chat_id is None:
        return ConversationHandler.END

    db: Database = context.bot_data["db"]
    existing = db.get_user(user.id)
    # Extract referral code from command argument if present
    ref_code = None
    args = context.args if hasattr(context, "args") else []
    if args:
        ref_code = args[0]
    # If user already exists, greet and show menu
    if existing:
        await update.message.reply_text(
            f"Привет, {existing['name']}! Ты уже зарегистрирован(а). "
            "Используй /menu, чтобы изменить настройки или узнать статус рефералов."
        )
        return ConversationHandler.END
    # Store referral code in user_data to use later when saving
    context.user_data["ref_code"] = ref_code
    # Begin registration
    await update.message.reply_text(
        "Добро пожаловать во Вселенную! ✨\n"
        "Я помогу рассчитать твой персональный астропрогноз.\n"
        "Давай начнём с твоего имени. Как тебя зовут?",
        reply_markup=ReplyKeyboardRemove(),
    )
    return RegState.NAME


async def ask_birth_date(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Capture the user's name and ask for their birth date."""
    text = update.message.text.strip()
    context.user_data["name"] = text
    await update.message.reply_text(
        "Укажи дату рождения в формате ДД.ММ.ГГГГ (например, 27.11.1997):"
    )
    return RegState.BIRTH_DATE


def _parse_date(text: str) -> Optional[str]:
    """Helper to parse a date string in DD.MM.YYYY format and return ISO date."""
    try:
        dt = datetime.strptime(text, "%d.%m.%Y")
        return dt.strftime("%Y-%m-%d")
    except Exception:
        return None


async def ask_birth_time(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Validate and store the user's birth date, then ask for birth time."""
    date_str = _parse_date(update.message.text.strip())
    if not date_str:
        await update.message.reply_text("Пожалуйста, введи дату в формате ДД.ММ.ГГГГ.")
        return RegState.BIRTH_DATE
    context.user_data["birth_date"] = date_str
    await update.message.reply_text(
        "Укажи время рождения (часы и минуты, например, 18:25):"
    )
    return RegState.BIRTH_TIME


def _parse_time(text: str) -> Optional[str]:
    """Helper to parse a time string in HH:MM format."""
    try:
        dt = datetime.strptime(text, "%H:%M")
        return dt.strftime("%H:%M")
    except Exception:
        return None


async def ask_birth_place(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Validate and store birth time, then ask for birth place."""
    time_str = _parse_time(update.message.text.strip())
    if not time_str:
        await update.message.reply_text("Пожалуйста, введи время в формате ЧЧ:ММ.")
        return RegState.BIRTH_TIME
    context.user_data["birth_time"] = time_str
    await update.message.reply_text(
        "Укажи место рождения (город, страна):"
    )
    return RegState.BIRTH_PLACE


async def ask_message_time(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Store birth place and ask for the preferred daily message time."""
    context.user_data["birth_place"] = update.message.text.strip()
    await update.message.reply_text(
        "В какое время присылать тебе ежедневное сообщение? (ЧЧ:ММ, например, 10:05)"
    )
    return RegState.MESSAGE_TIME


async def confirm_registration(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Validate message time, summarise the provided data and ask for confirmation."""
    time_str = _parse_time(update.message.text.strip())
    if not time_str:
        await update.message.reply_text("Введите время в формате ЧЧ:ММ, например 08:30.")
        return RegState.MESSAGE_TIME
    context.user_data["message_time"] = time_str
    name = context.user_data.get("name")
    birth_date = context.user_data.get("birth_date")
    birth_time = context.user_data.get("birth_time")
    birth_place = context.user_data.get("birth_place")
    message_time = context.user_data.get("message_time")
    summary = (
        f"Спасибо! Вот твои данные:\n\n"
        f"Имя: {name}\n"
        f"Дата рождения: {datetime.strptime(birth_date, '%Y-%m-%d').strftime('%d.%m.%Y')}\n"
        f"Место рождения: {birth_place}\n"
        f"Время рождения: {birth_time}\n"
        f"Время сообщения: {message_time}\n\n"
        "Нажми кнопку ниже, чтобы поговорить со Вселенной!"
    )
    keyboard = InlineKeyboardMarkup(
        [[InlineKeyboardButton("Поговорить со Вселенной", callback_data="confirm_profile")]]
    )
    await update.message.reply_text(summary, reply_markup=keyboard)
    return RegState.CONFIRM


async def handle_confirm_profile(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Persist user data into the database and send the first forecast."""
    query = update.callback_query
    await query.answer()
    user = update.effective_user
    chat_id = update.effective_chat.id if update.effective_chat else None
    if not user or chat_id is None:
        return ConversationHandler.END
    db: Database = context.bot_data["db"]
    # Retrieve stored data from user_data
    name = context.user_data.get("name")
    birth_date = context.user_data.get("birth_date")
    birth_time = context.user_data.get("birth_time")
    birth_place = context.user_data.get("birth_place")
    message_time = context.user_data.get("message_time", config.DEFAULT_MESSAGE_TIME)
    ref_code = context.user_data.get("ref_code")
    # Insert into database
    db.add_user(
        user_id=user.id,
        chat_id=chat_id,
        name=name,
        birth_date=birth_date,
        birth_time=birth_time,
        birth_place=birth_place,
        message_time=message_time,
        referred_by=ref_code,
    )
    # Schedule daily message
    await schedule_daily_job(context, user.id, message_time)
    # Send first forecast
    natal_positions = compute_natal_positions(birth_date, birth_time)
    forecast = generate_message(name, natal_positions)
    await query.message.reply_text(
        "Твой первый астропрогноз:\n\n" + forecast
    )
    # Provide referral link
    bot_username = (await context.bot.get_me()).username
    my_code = db.get_referral_code(user.id)
    if my_code:
        link = get_referral_link(bot_username, my_code)
        await query.message.reply_text(
            "Твоя реферальная ссылка: " + link + "\n" +
            "Поделись ею с друзьями и получай бонусные баллы!"
        )
    return ConversationHandler.END


async def schedule_daily_job(context: ContextTypes.DEFAULT_TYPE, user_id: int, message_time: str) -> None:
    """Schedule or reschedule the daily job for a user at the specified time."""
    # Cancel existing job for this user if present
    job_name = f"daily_{user_id}"
    # Remove existing jobs with this name
    current_jobs = context.job_queue.get_jobs_by_name(job_name)
    for job in current_jobs:
        job.schedule_removal()
    # Parse time string into a time object
    hour, minute = map(int, message_time.split(":"))
    target_time = time(hour=hour, minute=minute)
    # Schedule a daily repeating job
    # Note: job_queue attaches timezone automatically based on the bot's
    # configuration. If you need a specific timezone, you can pass
    # timezone=pytz.timezone('Europe/Berlin'), but Telegram servers use
    # UTC by default. Here we leave it unset for simplicity.
    context.job_queue.run_daily(
        send_daily_message,
        time=target_time,
        name=job_name,
        data={"user_id": user_id},
    )


async def send_daily_message(context: ContextTypes.DEFAULT_TYPE) -> None:
    """Send the personalised daily message to a user."""
    job_data = context.job.data or {}
    user_id = job_data.get("user_id")
    if not user_id:
        return
    db: Database = context.bot_data["db"]
    user = db.get_user(user_id)
    if not user:
        return
    # Check subscription: if expired, skip sending after a grace period
    is_subscribed = db.check_subscription(user_id)
    if not is_subscribed:
        # Optionally send a reminder only once when subscription expires
        # For demonstration, we'll send a free message anyway but remind about subscription
        logger.info(f"User {user_id} does not have an active subscription. Sending trial message.")
    # Build forecast
    name = user["name"]
    natal_positions = compute_natal_positions(user["birth_date"], user["birth_time"])
    forecast = generate_message(name, natal_positions)
    # Append subscription reminder if not subscribed
    if not is_subscribed:
        forecast += (
            "\n\n🔔 Чтобы получать неограниченные прогнозы и бонусы, оформите "
            "подписку через меню /menu."
        )
    try:
        await context.bot.send_message(chat_id=user["chat_id"], text=forecast)
    except Exception as exc:
        logger.error("Failed to send daily message to %s: %s", user_id, exc)


async def menu(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Present the main menu to the user."""
    user = update.effective_user
    if not user:
        return
    db: Database = context.bot_data["db"]
    record = db.get_user(user.id)
    if not record:
        await update.message.reply_text(
            "Ты ещё не зарегистрирован(а). Используй /start, чтобы начать."
        )
        return
    # Build menu keyboard
    keyboard = [
        [InlineKeyboardButton("Изменить данные", callback_data="edit_data")],
        [InlineKeyboardButton("Изменить время", callback_data="edit_time")],
        [InlineKeyboardButton("Статус рефералов", callback_data="ref_status")],
        [InlineKeyboardButton("Купить подписку", callback_data="buy_subscription")],
    ]
    await update.message.reply_text(
        "Выбери действие:", reply_markup=InlineKeyboardMarkup(keyboard)
    )


async def handle_menu_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle menu button presses via callback queries."""
    query = update.callback_query
    await query.answer()
    data = query.data
    db: Database = context.bot_data["db"]
    user = update.effective_user
    if not user:
        return
    if data == "edit_data":
        # Ask for updated name
        await query.message.reply_text(
            "Какое имя вписать?", reply_markup=ReplyKeyboardRemove()
        )
        context.user_data["edit_field"] = "name"
        return
    elif data == "edit_time":
        await query.message.reply_text(
            "Введи новое время для ежедневного сообщения (ЧЧ:ММ):"
        )
        context.user_data["edit_field"] = "message_time"
        return
    elif data == "ref_status":
        count, points = get_referral_status(db, user.id)
        code = db.get_referral_code(user.id)
        bot_username = (await context.bot.get_me()).username
        link = get_referral_link(bot_username, code) if code else ""
        await query.message.reply_text(
            f"Приглашено друзей: {count}\n"
            f"Бонусные баллы: {points}\n"
            f"Твоя реферальная ссылка: {link}"
        )
        return
    elif data == "buy_subscription":
        # Send invoice
        invoice = build_subscription_invoice(user.id)
        await context.bot.send_invoice(
            chat_id=query.message.chat_id,
            **invoice
        )
        return


async def handle_edit_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Process user input for editing data (name or message_time)."""
    field = context.user_data.get("edit_field")
    if not field:
        return
    db: Database = context.bot_data["db"]
    user = update.effective_user
    if not user:
        return
    text = update.message.text.strip()
    if field == "name":
        db.update_user(user.id, name=text)
        await update.message.reply_text("Имя успешно обновлено!")
    elif field == "message_time":
        new_time = _parse_time(text)
        if not new_time:
            await update.message.reply_text("Введите время в формате ЧЧ:ММ.")
            return
        db.update_user(user.id, message_time=new_time)
        await schedule_daily_job(context, user.id, new_time)
        await update.message.reply_text("Время сообщения обновлено!")
    # Clear state
    context.user_data.pop("edit_field", None)


async def broadcast(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Send a broadcast message to all users (admins only)."""
    user = update.effective_user
    if not user or user.id not in config.ADMIN_IDS:
        await update.message.reply_text("У тебя нет прав для этой команды.")
        return
    if not context.args:
        await update.message.reply_text("Использование: /broadcast ваше сообщение")
        return
    message_text = " ".join(context.args)
    db: Database = context.bot_data["db"]
    count = 0
    for row in db.get_all_users():
        try:
            await context.bot.send_message(chat_id=row["chat_id"], text=message_text)
            count += 1
        except Exception as exc:
            logger.error("Ошибка при рассылке пользователю %s: %s", row["user_id"], exc)
    await update.message.reply_text(f"Сообщение отправлено {count} пользователям.")


def build_application() -> Application:
    """Create and configure the Telegram application."""
    application = Application.builder().token(config.BOT_TOKEN).build()
    # Initialise database and store in bot_data for global access
    db = Database()
    application.bot_data["db"] = db
    # On startup, schedule jobs for existing users
    async def on_startup(app: Application) -> None:
        """Schedule daily jobs for all existing users when the bot starts."""
        for row in db.get_all_users():
            mt = row["message_time"] or config.DEFAULT_MESSAGE_TIME
            # Cancel any existing job (shouldn't exist on startup) and schedule
            # manually using the application's job_queue
            job_name = f"daily_{row['user_id']}"
            # Remove any stale jobs
            for job in app.job_queue.get_jobs_by_name(job_name):
                job.schedule_removal()
            hour, minute = map(int, mt.split(":"))
            target_time = time(hour=hour, minute=minute)
            app.job_queue.run_daily(
                send_daily_message,
                time=target_time,
                name=job_name,
                data={"user_id": row["user_id"]},
            )
    application.post_init.append(on_startup)
    # Conversation handler for registration
    conv_handler = ConversationHandler(
        entry_points=[CommandHandler("start", start)],
        states={
            RegState.NAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, ask_birth_date)],
            RegState.BIRTH_DATE: [MessageHandler(filters.TEXT & ~filters.COMMAND, ask_birth_time)],
            RegState.BIRTH_TIME: [MessageHandler(filters.TEXT & ~filters.COMMAND, ask_birth_place)],
            RegState.BIRTH_PLACE: [MessageHandler(filters.TEXT & ~filters.COMMAND, ask_message_time)],
            RegState.MESSAGE_TIME: [MessageHandler(filters.TEXT & ~filters.COMMAND, confirm_registration)],
            RegState.CONFIRM: [CallbackQueryHandler(handle_confirm_profile, pattern="^confirm_profile$")],
        },
        fallbacks=[CommandHandler("start", start)],
        allow_reentry=True,
    )
    # Register handlers
    application.add_handler(conv_handler)
    application.add_handler(CommandHandler("menu", menu))
    application.add_handler(CommandHandler("broadcast", broadcast))
    # Menu callback handler
    application.add_handler(CallbackQueryHandler(handle_menu_callback, pattern="^(edit_data|edit_time|ref_status|buy_subscription)$"))
    # Handlers for editing input
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_edit_message))
    # Payment handlers
    application.add_handler(PreCheckoutQueryHandler(handle_pre_checkout))
    application.add_handler(MessageHandler(filters.SUCCESSFUL_PAYMENT, lambda update, context: handle_successful_payment(update, context, db)))
    return application


def main() -> None:
    """Run the bot."""
    application = build_application()
    logger.info("Starting bot...")
    application.run_polling()


if __name__ == "__main__":
    main()
