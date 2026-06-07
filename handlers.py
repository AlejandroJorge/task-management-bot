from telegram import Update
from telegram.ext import ContextTypes


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text(
        "Hello! I'm your bot. Send me anything and I'll respond."
    )


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text(
        "/start - greet the bot\n"
        "/help  - show this message\n"
        "or just send any text"
    )


async def echo(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    # Replace this with your actual message logic
    await update.message.reply_text(f"You said: {update.message.text}")
