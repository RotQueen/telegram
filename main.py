"""Telegram bot that relays messages between customer and executor chats.

Run with long polling (recommended for Railway):
1. Set environment variables:
   - BOT_TOKEN: Telegram bot token.
   - ADMIN_USER_ID: Telegram ID of admin (owner Tanya / @askeditme). Optional if constant matches.
   - DB_PATH: (optional) path to SQLite DB file, defaults to projects.db.
2. Install dependencies: `pip install -r requirements.txt`.
3. Start the bot: `python main.py`.
"""
from __future__ import annotations

import logging
from typing import Optional

from telegram import Message, Update
from telegram.error import TelegramError
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

from config import Config, load_config
from storage import Project, SQLiteProjectRepository

logger = logging.getLogger(__name__)


def is_admin(update: Update, config: Config) -> bool:
    user = update.effective_user
    return bool(user and user.id == config.admin_user_id)


async def ensure_admin(update: Update, config: Config) -> bool:
    if is_admin(update, config):
        return True
    if update.effective_message:
        await update.effective_message.reply_text("Эта команда доступна только администратору.")
    return False


def build_project_status(project: Project) -> str:
    customer_status = (
        f"привязан ({project.customer_chat_id})" if project.customer_chat_id else "не привязан"
    )
    executor_status = (
        f"привязан ({project.executor_chat_id})" if project.executor_chat_id else "не привязан"
    )
    active_status = "активен" if project.is_active else "неактивен"
    return (
        f"{project.slug}: заказчик — {customer_status}, исполнители — {executor_status}, статус — {active_status}"
    )


async def create_project_handler(
    update: Update, context: ContextTypes.DEFAULT_TYPE, config: Config, repo: SQLiteProjectRepository
) -> None:
    if not await ensure_admin(update, config):
        return
    if not context.args:
        await update.effective_message.reply_text("Использование: /create_project <slug>")
        return
    slug = context.args[0]
    chat_id = update.effective_chat.id
    try:
        repo.create_project(slug, chat_id)
    except ValueError as exc:
        await update.effective_message.reply_text(str(exc))
        return
    await update.effective_message.reply_text(
        f"Проект {slug} создан. Теперь зайдите в чат с заказчиками и выполните /bind_customer {slug}."
    )


async def bind_customer_handler(
    update: Update, context: ContextTypes.DEFAULT_TYPE, config: Config, repo: SQLiteProjectRepository
) -> None:
    if not await ensure_admin(update, config):
        return
    if not context.args:
        await update.effective_message.reply_text("Использование: /bind_customer <slug>")
        return
    slug = context.args[0]
    chat_id = update.effective_chat.id
    try:
        project = repo.bind_customer_chat(slug, chat_id)
    except ValueError as exc:
        await update.effective_message.reply_text(str(exc))
        return
    await update.effective_message.reply_text(
        f"Проект {project.slug}: чат заказчика успешно привязан."
    )


async def project_info_handler(
    update: Update, context: ContextTypes.DEFAULT_TYPE, repo: SQLiteProjectRepository
) -> None:
    chat_id = update.effective_chat.id
    found = repo.find_by_chat_id(chat_id)
    if not found:
        await update.effective_message.reply_text("Этот чат не привязан ни к одному проекту.")
        return
    project, role = found
    role_name = "чат исполнителей" if role == "executor" else "чат заказчиков"
    await update.effective_message.reply_text(
        f"Проект: {project.slug}\nТип чата: {role_name}\nСтатус: {'активен' if project.is_active else 'неактивен'}"
    )


async def list_projects_handler(
    update: Update, context: ContextTypes.DEFAULT_TYPE, config: Config, repo: SQLiteProjectRepository
) -> None:
    if not await ensure_admin(update, config):
        return
    projects = repo.list_projects()
    if not projects:
        await update.effective_message.reply_text("Проектов пока нет.")
        return
    lines = ["Список проектов:"]
    for project in projects:
        lines.append(build_project_status(project))
    await update.effective_message.reply_text("\n".join(lines))


async def unlink_project_handler(
    update: Update, context: ContextTypes.DEFAULT_TYPE, config: Config, repo: SQLiteProjectRepository
) -> None:
    if not await ensure_admin(update, config):
        return
    if not context.args:
        await update.effective_message.reply_text("Использование: /unlink_project <slug>")
        return
    slug = context.args[0]
    chat_id = update.effective_chat.id
    try:
        project = repo.unlink_chat(slug, chat_id)
    except ValueError as exc:
        await update.effective_message.reply_text(str(exc))
        return
    await update.effective_message.reply_text(
        f"Проект {project.slug}: чат отвязан, проект деактивирован."
    )


def caption_for_role(role: str) -> str:
    return "🧑‍🎨 Сообщение от команды." if role == "executor" else "👤 Сообщение от клиента."


def build_media_caption(role: str, original_caption: Optional[str]) -> str:
    base = caption_for_role(role)
    if original_caption:
        return f"{base}\n{original_caption}"
    return base


def prefix_for_role(role: str) -> str:
    return "🧑‍🎨 Сообщение от команды: " if role == "executor" else "👤 Сообщение от клиента: "


async def relay_message(update: Update, context: ContextTypes.DEFAULT_TYPE, repo: SQLiteProjectRepository) -> None:
    message: Optional[Message] = update.effective_message
    if not message:
        return
    if message.from_user and message.from_user.is_bot:
        return
    chat_id = message.chat_id
    found = repo.find_by_chat_id(chat_id)
    if not found:
        return
    project, role = found
    target_chat_id = project.customer_chat_id if role == "executor" else project.executor_chat_id
    if not target_chat_id:
        await message.reply_text("В проекте не привязан парный чат. Обратитесь к администратору.")
        return

    caption = build_media_caption(role, message.caption)
    caption = caption_for_role(role)
    text_prefix = prefix_for_role(role)

    try:
        if message.text:
            await context.bot.send_message(target_chat_id, f"{text_prefix}{message.text}")
        elif message.document:
            await context.bot.send_document(
                target_chat_id, message.document.file_id, caption=caption
            )
        elif message.photo:
            photo = message.photo[-1]
            await context.bot.send_photo(target_chat_id, photo.file_id, caption=caption)
        elif message.voice:
            await context.bot.send_voice(target_chat_id, message.voice.file_id, caption=caption)
        elif message.audio:
            await context.bot.send_audio(target_chat_id, message.audio.file_id, caption=caption)
        elif message.video:
            await context.bot.send_video(target_chat_id, message.video.file_id, caption=caption)
        else:
            await message.reply_text("Тип сообщения не поддерживается для пересылки.")
    except TelegramError as exc:
        logger.exception("Failed to relay message for project %s: %s", project.slug, exc)
        await message.reply_text("Не удалось отправить сообщение в парный чат. Проверьте настройки бота.")


async def help_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.effective_message.reply_text(
        "Доступные команды:\n"
        "/project_info — информация о проекте, к которому привязан чат.\n"
        "Команды администратора: /create_project, /bind_customer, /list_projects, /unlink_project."
    )


async def on_error(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    logger.exception("Update %s caused error", update, exc_info=context.error)


def build_application(config: Config, repo: SQLiteProjectRepository):
    application = ApplicationBuilder().token(config.bot_token).build()

    application.add_handler(CommandHandler("start", help_handler))
    application.add_handler(CommandHandler("help", help_handler))
    application.add_handler(
        CommandHandler(
            "create_project",
            lambda u, c: create_project_handler(u, c, config=config, repo=repo),
        )
    )
    application.add_handler(
        CommandHandler(
            "bind_customer",
            lambda u, c: bind_customer_handler(u, c, config=config, repo=repo),
        )
    )
    application.add_handler(
        CommandHandler(
            "project_info", lambda u, c: project_info_handler(u, c, repo=repo)
        )
    )
    application.add_handler(
        CommandHandler("list_projects", lambda u, c: list_projects_handler(u, c, config, repo))
    )
    application.add_handler(
        CommandHandler(
            "unlink_project",
            lambda u, c: unlink_project_handler(u, c, config=config, repo=repo),
        )
    )

    application.add_handler(
        MessageHandler(~filters.COMMAND & filters.ALL, lambda u, c: relay_message(u, c, repo=repo))
    )
    application.add_error_handler(on_error)
    return application


def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    )
    config = load_config()
    logger.info("Starting bot with admin %s", config.admin_user_id)
    repo = SQLiteProjectRepository(config.db_path)

    app = build_application(config, repo)
    # Long polling startup for Railway or any host without webhooks.
    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
