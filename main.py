import os
import logging
from telegram import Update
from telegram.ext import Updater, CommandHandler, CallbackContext

# Enable logging
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO
)
logger = logging.getLogger(__name__)

# Global dictionaries to store user info and ledger balances.
# - participants: maps user_id to a display name.
# - ledger: maps user_id to a net balance.
participants = {}
ledger = {}

def start(update: Update, context: CallbackContext) -> None:
    """Handles the /start command and registers the user."""
    user = update.effective_user
    name = user.username if user.username else user.first_name
    participants[user.id] = name
    if user.id not in ledger:
        ledger[user.id] = 0.0
    update.message.reply_text(
        f"Hi {name}! I'm your bill splitting bot.\n"
        "Use /addexpense <amount> <description> to add an expense, "
        "and /summary to see everyone's balance."
    )

def add_expense(update: Update, context: CallbackContext) -> None:
    """
    Handles the /addexpense command.
    Usage: /addexpense <amount> <description>
    When a user adds an expense, the bot splits the amount equally among all registered participants.
    """
    user = update.effective_user
    name = user.username if user.username else user.first_name
    participants[user.id] = name
    if user.id not in ledger:
        ledger[user.id] = 0.0

    args = context.args
    if len(args) < 2:
        update.message.reply_text("Usage: /addexpense <amount> <description>")
        return

    try:
        amount = float(args[0])
    except ValueError:
        update.message.reply_text("Please provide a valid number for the amount.")
        return

    description = " ".join(args[1:])

    # Calculate the share for each user.
    num_users = len(ledger)
    if num_users < 2:
        update.message.reply_text("There must be at least 2 participants to split the expense.")
        return

    share = amount / num_users

    # Update the ledger:
    # The spender's net balance increases by (amount - their share)
    ledger[user.id] += (amount - share)
    # Every other participant's balance decreases by their share.
    for uid in ledger:
        if uid != user.id:
            ledger[uid] -= share

    # Build a response message.
    msg = (
        f"{name} added an expense:\n"
        f"Description: {description}\n"
        f"Amount: {amount:.2f}\n"
        f"Each person's share: {share:.2f}"
    )
    update.message.reply_text(msg)

    # Optionally, send direct notifications to other participants.
    for uid in ledger:
        if uid != user.id:
            try:
                context.bot.send_message(
                    chat_id=uid,
                    text=f"You owe {share:.2f} due to {name}'s expense: {description}"
                )
            except Exception as e:
                logger.warning(f"Could not send direct message to user {uid}: {e}")

def summary(update: Update, context: CallbackContext) -> None:
    """
    Provides a summary of the current ledger showing each participant's net balance.
    Positive balance indicates others owe the user, while a negative balance means the user owes money.
    """
    if not ledger:
        update.message.reply_text("No expenses have been recorded yet.")
        return

    msg = "Summary of Balances:\n"
    for uid, balance in ledger.items():
        user_name = participants.get(uid, str(uid))
        msg += f"{user_name}: {balance:.2f}\n"
    update.message.reply_text(msg)

def main():
    """Starts the Telegram bot."""
    # Get the token from environment variables.
    TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
    if not TOKEN:
        logger.error("TELEGRAM_BOT_TOKEN environment variable is not set.")
        return

    updater = Updater(TOKEN)
    dispatcher = updater.dispatcher

    # Register command handlers.
    dispatcher.add_handler(CommandHandler("start", start))
    dispatcher.add_handler(CommandHandler("addexpense", add_expense))
    dispatcher.add_handler(CommandHandler("summary", summary))

    # Start the Bot.
    updater.start_polling()
    logger.info("Bot started. Waiting for commands...")
    updater.idle()

if __name__ == '__main__':
    main()
