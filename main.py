import os
import logging
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    CallbackQueryHandler,
    ContextTypes
)

# Enable logging
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO
)
logger = logging.getLogger(__name__)

# Global storage
# registered_users: Maps user_id to a display name.
registered_users = {}

# transactions: Maps transaction_id (an integer) to a dictionary.
# Each transaction is structured as:
# {
#    "id": transaction_id,
#    "spender": <user_id of person who paid>,
#    "amount": <total amount spent>,
#    "description": <expense description>,
#    "share": <equal share for each debtor>,
#    "debts": { debtor_id: status, ... }  # Status: "pending", "marked", "confirmed"
# }
transactions = {}
next_transaction_id = 1  # Simple counter for transaction IDs

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Register the user and welcome them."""
    user = update.effective_user
    name = user.username if user.username else user.first_name
    if user.id not in registered_users:
        registered_users[user.id] = name
        await update.message.reply_text(
            f"Hi {name}! You have been registered in the friends circle.\n"
            "You can add an expense with /addexpense <amount> <description>\n"
            "and check your summary with /summary."
        )
    else:
        await update.message.reply_text("You are already registered in the friends circle.")

async def register(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Explicit registration (alias of /start)."""
    user = update.effective_user
    name = user.username if user.username else user.first_name
    if user.id in registered_users:
        await update.message.reply_text("You are already registered.")
    else:
        registered_users[user.id] = name
        await update.message.reply_text("You have been registered in the friends circle!")

async def add_expense(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    Add an expense.
    Usage: /addexpense <amount> <description>
    The bot calculates each friend’s share (excluding the spender) and sends each debtor
    an inline “Paid” button to mark their payment.
    """
    global next_transaction_id
    user = update.effective_user
    spender_id = user.id

    if spender_id not in registered_users:
        await update.message.reply_text("You are not registered. Use /register to join the friends circle.")
        return

    args = context.args
    if len(args) < 2:
        await update.message.reply_text("Usage: /addexpense <amount> <description>")
        return

    try:
        amount = float(args[0])
    except ValueError:
        await update.message.reply_text("Invalid amount. Please enter a numeric value.")
        return

    description = " ".join(args[1:])
    # Calculate share: Divide by number of other registered users.
    num_debtors = len(registered_users) - 1
    if num_debtors <= 0:
        await update.message.reply_text("No other participants registered to share the expense.")
        return

    share = amount / num_debtors
    transaction_id = next_transaction_id
    next_transaction_id += 1

    # Build debts dictionary: each friend (except spender) starts with status "pending"
    debts = {uid: "pending" for uid in registered_users if uid != spender_id}

    # Store the transaction.
    transactions[transaction_id] = {
        "id": transaction_id,
        "spender": spender_id,
        "amount": amount,
        "description": description,
        "share": share,
        "debts": debts
    }

    await update.message.reply_text(
        f"Expense added: '{description}' for {amount:.2f}.\nEach friend owes {share:.2f}."
    )

    # Notify each debtor with an inline "Paid" button.
    for debtor_id in debts:
        try:
            keyboard = InlineKeyboardMarkup([
                [InlineKeyboardButton("Paid", callback_data=f"paid:{transaction_id}")]
            ])
            await context.bot.send_message(
                chat_id=debtor_id,
                text=(f"You owe {share:.2f} for expense: '{description}' covered by {registered_users[spender_id]}."),
                reply_markup=keyboard
            )
        except Exception as e:
            logger.warning(f"Could not send notification to user {debtor_id}: {e}")

async def summary(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    Provide a summary for the user.
    For expenses you covered, list each friend along with the status of their payment.
    For expenses you owe, list the details along with your payment status.
    """
    user = update.effective_user
    if user.id not in registered_users:
        await update.message.reply_text("You are not registered. Use /register to join the friends circle.")
        return

    owed_to_you = []
    you_owe = []

    for tx in transactions.values():
        # If the user is the spender, list each debtor’s status.
        if tx["spender"] == user.id:
            for debtor, status in tx["debts"].items():
                owed_to_you.append(
                    f"{registered_users.get(debtor, str(debtor))}: owes {tx['share']:.2f} [{status}] for '{tx['description']}'"
                )
        # If the user is a debtor in this transaction.
        elif user.id in tx["debts"]:
            status = tx["debts"][user.id]
            you_owe.append(
                f"To {registered_users.get(tx['spender'], str(tx['spender']))}: owe {tx['share']:.2f} [{status}] for '{tx['description']}'"
            )

    if not owed_to_you and not you_owe:
        await update.message.reply_text("No transactions to show.")
        return

    msg = ""
    if owed_to_you:
        msg += "People who owe you:\n" + "\n".join(owed_to_you) + "\n\n"
    if you_owe:
        msg += "You owe:\n" + "\n".join(you_owe)
    await update.message.reply_text(msg)

async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    Handle callback queries from inline buttons.
    - When a debtor clicks "Paid", mark their status as 'marked' and notify the spender.
    - When the spender clicks "Confirm Payment", mark the debtor’s payment as 'confirmed'
      and notify them.
    """
    query = update.callback_query
    data = query.data
    user = query.from_user
    await query.answer()  # Acknowledge the callback

    if data.startswith("paid:"):
        # Format: paid:<transaction_id>
        try:
            _, tx_id_str = data.split(":")
            tx_id = int(tx_id_str)
        except (ValueError, IndexError):
            await query.edit_message_text("Invalid callback data.")
            return

        if tx_id not in transactions:
            await query.edit_message_text("Transaction not found.")
            return

        tx = transactions[tx_id]
        if user.id not in tx["debts"]:
            await query.edit_message_text("You are not a debtor in this transaction.")
            return
        if tx["debts"][user.id] != "pending":
            await query.edit_message_text("You have already marked this expense as paid.")
            return

        # Mark the debtor's payment as "marked" (pending confirmation from spender)
        tx["debts"][user.id] = "marked"
        await query.edit_message_text("Payment marked. Waiting for the spender to confirm.")

        # Notify the spender with an inline "Confirm Payment" button.
        spender_id = tx["spender"]
        try:
            keyboard = InlineKeyboardMarkup([
                [InlineKeyboardButton("Confirm Payment", callback_data=f"confirm:{tx_id}:{user.id}")]
            ])
            await context.bot.send_message(
                chat_id=spender_id,
                text=(f"{registered_users.get(user.id)} marked as paid for expense "
                      f"'{tx['description']}' (Share: {tx['share']:.2f})."),
                reply_markup=keyboard
            )
        except Exception as e:
            logger.warning(f"Could not notify spender {spender_id}: {e}")

    elif data.startswith("confirm:"):
        # Format: confirm:<transaction_id>:<debtor_id>
        try:
            _, tx_id_str, debtor_id_str = data.split(":")
            tx_id = int(tx_id_str)
            debtor_id = int(debtor_id_str)
        except (ValueError, IndexError):
            await query.edit_message_text("Invalid callback data.")
            return

        if tx_id not in transactions:
            await query.edit_message_text("Transaction not found.")
            return

        tx = transactions[tx_id]
        # Only the spender can confirm a payment.
        if user.id != tx["spender"]:
            await query.edit_message_text("Only the spender can confirm payments.")
            return

        if debtor_id not in tx["debts"]:
            await query.edit_message_text("Debtor not found in this transaction.")
            return

        if tx["debts"][debtor_id] != "marked":
            await query.edit_message_text("This payment is not marked as paid.")
            return

        # Confirm the payment.
        tx["debts"][debtor_id] = "confirmed"
        await query.edit_message_text("Payment confirmed.")

        # Notify the debtor that their payment has been confirmed.
        try:
            await context.bot.send_message(
                chat_id=debtor_id,
                text=(f"Your payment for expense '{tx['description']}' "
                      f"(Share: {tx['share']:.2f}) has been confirmed by {registered_users.get(user.id)}.")
            )
        except Exception as e:
            logger.warning(f"Could not notify debtor {debtor_id}: {e}")

def main():
    TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
    if not TOKEN:
        logger.error("TELEGRAM_BOT_TOKEN environment variable not set.")
        return

    application = ApplicationBuilder().token(TOKEN).build()

    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("register", register))
    application.add_handler(CommandHandler("addexpense", add_expense))
    application.add_handler(CommandHandler("summary", summary))
    application.add_handler(CallbackQueryHandler(button_handler))

    # This call is blocking and handles the event loop internally.
    application.run_polling()

if __name__ == '__main__':
    main()

