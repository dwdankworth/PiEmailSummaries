from __future__ import annotations
from functools import wraps

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
from telegram import Update
from telegram.ext import Application, CommandHandler, ContextTypes

from common.config import load_config
from common.logging_utils import get_logger
from telegram_bot.service import get_status, record_bot_event, run_digest, search_digest_items

LOGGER = get_logger("telegram-bot")


def authorized_only(handler):
    """Decorator that restricts command handlers to the configured chat."""

    @wraps(handler)
    async def wrapper(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        config = context.application.bot_data["config"]
        chat_id = str(update.effective_chat.id)
        if chat_id != config.telegram_chat_id:
            LOGGER.warning(
                "Unauthorized access attempt",
                extra={"extra_json": {"chat_id": chat_id, "command": handler.__name__}},
            )
            await update.effective_message.reply_text("Unauthorized")
            return
        return await handler(update, context)

    return wrapper


@authorized_only
async def digest_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    config = context.application.bot_data["config"]
    try:
        count = run_digest(config)
        record_bot_event("digest_command", {"count": count})
        await update.effective_message.reply_text(
            f"Digest complete. Delivered {count} undelivered summary item(s)."
        )
    except Exception as exc:
        LOGGER.exception("Digest command failed", extra={"extra_json": {"error": str(exc)}})
        await update.effective_message.reply_text(f"Digest failed: {exc}")


@authorized_only
async def status_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    config = context.application.bot_data["config"]
    status = get_status(config)
    record_bot_event(
        "status_command",
        {"pending_queue_size": int(status.get("pending_queue_size", 0))},
    )
    text = (
        "System status\n"
        f"- Last fetch time: {status.get('last_fetch_time')}\n"
        f"- Pending queue size: {status.get('pending_queue_size')}\n"
        f"- Last summarizer run: {status.get('last_summarizer_run')}\n"
        f"- Ollama model loaded: {status.get('ollama_model_loaded')}\n"
        f"- Undelivered processed count: {status.get('undelivered_processed_count')}"
    )
    await update.effective_message.reply_text(text)


@authorized_only
async def search_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    keyword = " ".join(context.args).strip()
    if not keyword:
        await update.effective_message.reply_text("Usage: /search <keyword>")
        return
    results = search_digest_items(keyword)
    record_bot_event("search_command", {"keyword": keyword, "result_count": len(results)})
    if not results:
        await update.effective_message.reply_text("No matching summaries found.")
        return
    body = "\n".join(f"• {line}" for line in results)
    await update.effective_message.reply_text(body[:3900])


def _run_scheduled_digest(application: Application) -> None:
    config = application.bot_data["config"]
    try:
        count = run_digest(config)
        LOGGER.info("Scheduled digest completed", extra={"extra_json": {"count": count}})
    except Exception as exc:
        LOGGER.exception("Scheduled digest failed", extra={"extra_json": {"error": str(exc)}})


async def on_startup(application: Application) -> None:
    config = application.bot_data["config"]
    record_bot_event("bot_started", {"chat_id": config.telegram_chat_id})


def main() -> None:
    config = load_config()
    if not config.telegram_bot_token:
        raise ValueError("telegram_bot_token must be set in config.yaml")

    application = (
        Application.builder()
        .token(config.telegram_bot_token)
        .post_init(on_startup)
        .build()
    )
    application.bot_data["config"] = config
    application.add_handler(CommandHandler("digest", digest_command))
    application.add_handler(CommandHandler("status", status_command))
    application.add_handler(CommandHandler("search", search_command))

    # Allow up to 15 minutes of grace so jobs still fire after device
    # sleep / wake cycles instead of being silently skipped (default is 1 s).
    scheduler = BackgroundScheduler(
        timezone=config.timezone,
        job_defaults={"misfire_grace_time": 900},
    )
    for index, cron_expr in enumerate(config.digest_schedule):
        scheduler.add_job(
            _run_scheduled_digest,
            trigger=CronTrigger.from_crontab(cron_expr, timezone=config.timezone),
            args=[application],
            id=f"telegram-digest-{index}",
            replace_existing=True,
            max_instances=1,
            coalesce=True,
        )
    scheduler.start()
    LOGGER.info("Telegram bot scheduler started", extra={"extra_json": {"schedules": config.digest_schedule, "timezone": config.timezone}})
    try:
        application.run_polling()
    finally:
        scheduler.shutdown(wait=False)


if __name__ == "__main__":
    main()
