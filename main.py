import os
import logging
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    CallbackQueryHandler,
    ContextTypes,
    ConversationHandler,
    MessageHandler,
    filters
)

# Set up logging.
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO
)
logger = logging.getLogger(__name__)

# Global storage.
# registered_users: Maps user_id to a display name.
registered_users = {}

# transactions: Maps transaction_id to a transaction dictionary.
# Each transaction has:
#  - "id": transaction id,
#  - "spender": user_id of the person who paid,
#  - "amount": total amount spent,
#  - "description": expense description,
#  - "share": (amount / total_registered),
#  - "debts": dict mapping debtor_id to status ("pending", "marked", "confirmed").
transactions = {}
next_transaction_id = 1  # Simple counter for transaction IDs.

# Conversation states.
AMOUNT, DESCRIPTION = range(2)

# ---------- Command Handlers & Conversation for Adding Expense ----------

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Register the user and show the main menu."""
    user = update.effective_user
    name = user.username or user.first_name
    if user.id not in registered_users:
        registered_users[user.id] = name
    main_menu = InlineKeyboardMarkup([
        [InlineKeyboardButton("Add Expense", callback_data="menu_add_expense")],
        [InlineKeyboardButton("View Summary", callback_data="menu_view_summary")]
    ])
    await update.message.reply_text(
        f"Welcome, {name}! You are now registered in the friends circle.",
        reply_markup=main_menu
    )

async def add_expense_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """
    Entry point for adding an expense.
    This is triggered either by the /addexpense command or when the user taps "Add Expense".
    """
    if update.callback_query:
        await update.callback_query.answer()
        await update.callback_query.message.reply_text(
            "Please enter the amount you spent (you can include commas):"
        )
    else:
        await update.message.reply_text(
            "Please enter the amount you spent (you can include commas):"
        )
    return AMOUNT

async def add_expense_amount(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Receive and process the amount."""
    text = update.message.text.strip().replace(",", "")
    try:
        amount = float(text)
    except ValueError:
        await update.message.reply_text(
            "That doesn't look like a valid number. Please enter the amount again:"
        )
        return AMOUNT
    context.user_data["expense_amount"] = amount
    await update.message.reply_text("Great! Now please enter a description for the expense:")
    return DESCRIPTION

async def add_expense_description(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Receive the description, record the expense, and notify debtors."""
    description = update.message.text.strip()
    amount = context.user_data.get("expense_amount")
    spender_id = update.effective_user.id
    # Ensure the spender is registered.
    if spender_id not in registered_users:
        registered_users[spender_id] = update.effective_user.username or update.effective_user.first_name

    total_participants = len(registered_users)
    if total_participants == 0:
        await update.message.reply_text("No participants registered. Please register first.")
        return ConversationHandler.END

    # Split the expense equally among all registered users.
    share = amount / total_participants
    global next_transaction_id
    transaction_id = next_transaction_id
    next_transaction_id += 1

    # Create a debts dictionary for all users except the spender.
    debts = {uid: "pending" for uid in registered_users if uid != spender_id}

    transactions[transaction_id] = {
        "id": transaction_id,
        "spender": spender_id,
        "amount": amount,
        "description": description,
        "share": share,
        "debts": debts
    }

    await update.message.reply_text(
        f"Expense recorded: '{description}' for {amount:.2f}.\n"
        f"Each participant's share is {share:.2f}."
    )

    # Notify each debtor with an inline "Paid" button.
    for debtor_id in debts:
        try:
            keyboard = InlineKeyboardMarkup([
                [InlineKeyboardButton("Paid", callback_data=f"paid:{transaction_id}")]
            ])
            await context.bot.send_message(
                chat_id=debtor_id,
                text=(
                    f"You owe {share:.2f} for expense '{description}' "
                    f"covered by {registered_users[spender_id]}."
                ),
                reply_markup=keyboard
            )
        except Exception as e:
            logger.warning(f"Could not send notification to user {debtor_id}: {e}")

    # Show the main menu again.
    main_menu = InlineKeyboardMarkup([
        [InlineKeyboardButton("Add Expense", callback_data="menu_add_expense")],
        [InlineKeyboardButton("View Summary", callback_data="menu_view_summary")]
    ])
    await update.message.reply_text("What would you like to do next?", reply_markup=main_menu)
    return ConversationHandler.END

async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Cancel the add expense conversation."""
    if update.message:
        await update.message.reply_text("Expense addition cancelled.")
    elif update.callback_query:
        await update.callback_query.message.reply_text("Expense addition cancelled.")
    return ConversationHandler.END

# ---------- Summary Command ----------

async def summary(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    Provide a summary showing two sections:
      • 📥 People who owe you (expenses you paid)
      • 📤 You owe (expenses you are a debtor in)
    """
    user = update.effective_user
    if user.id not in registered_users:
        await update.message.reply_text("You are not registered. Please use /start to register.")
        return

    owe_me = []
    i_owe = []
    for tx in transactions.values():
        if tx["spender"] == user.id:
            for debtor, status in tx["debts"].items():
                owe_me.append(
                    f"{registered_users.get(debtor, str(debtor))}: owes {tx['share']:.2f} [{status}] for '{tx['description']}'"
                )
        elif user.id in tx["debts"]:
            status = tx["debts"][user.id]
            i_owe.append(
                f"To {registered_users.get(tx['spender'], str(tx['spender']))}: owe {tx['share']:.2f} [{status}] for '{tx['description']}'"
            )
    message = ""
    if owe_me:
        message += "📥 *People who owe you:*\n" + "\n".join(owe_me) + "\n\n"
    if i_owe:
        message += "📤 *You owe:*\n" + "\n".join(i_owe)
    if not message:
        message = "No transactions to show."
    await update.message.reply_text(message, parse_mode="Markdown")

# ---------- Main Menu Callback Handler ----------

async def menu_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    Handle main menu buttons:
      • "Add Expense" starts the add expense conversation.
      • "View Summary" displays the summary.
    """
    query = update.callback_query
    await query.answer()
    data = query.data
    if data == "menu_add_expense":
        # Trigger the expense conversation.
        await add_expense_start(update, context)
    elif data == "menu_view_summary":
        # Directly show the summary.
        user = update.effective_user
        if user.id not in registered_users:
            registered_users[user.id] = user.username or user.first_name
        owe_me = []
        i_owe = []
        for tx in transactions.values():
            if tx["spender"] == user.id:
                for debtor, status in tx["debts"].items():
                    owe_me.append(
                        f"{registered_users.get(debtor, str(debtor))}: owes {tx['share']:.2f} [{status}] for '{tx['description']}'"
                    )
            elif user.id in tx["debts"]:
                status = tx["debts"][user.id]
                i_owe.append(
                    f"To {registered_users.get(tx['spender'], str(tx['spender']))}: owe {tx['share']:.2f} [{status}] for '{tx['description']}'"
                )
        message = ""
        if owe_me:
            message += "📥 *People who owe you:*\n" + "\n".join(owe_me) + "\n\n"
        if i_owe:
            message += "📤 *You owe:*\n" + "\n".join(i_owe)
        if not message:
            message = "No transactions to show."
        await query.message.reply_text(message, parse_mode="Markdown")

# ---------- Callback Handler for Payment Actions ----------

async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    Handle inline button presses for:
      • "Paid": a debtor marks the expense as paid.
      • "Confirm Payment": the spender confirms receipt.
    """
    query = update.callback_query
    data = query.data
    user = query.from_user
    await query.answer()

    if data.startswith("paid:"):
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

        tx["debts"][user.id] = "marked"
        await query.edit_message_text("Payment marked. Waiting for the spender to confirm.")

        # Notify the spender with a "Confirm Payment" button.
        spender_id = tx["spender"]
        try:
            keyboard = InlineKeyboardMarkup([
                [InlineKeyboardButton("Confirm Payment", callback_data=f"confirm:{tx_id}:{user.id}")]
            ])
            await context.bot.send_message(
                chat_id=spender_id,
                text=(
                    f"{registered_users.get(user.id)} marked as paid for expense '{tx['description']}' "
                    f"(Share: {tx['share']:.2f})."
                ),
                reply_markup=keyboard
            )
        except Exception as e:
            logger.warning(f"Could not notify spender {spender_id}: {e}")

    elif data.startswith("confirm:"):
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
        if user.id != tx["spender"]:
            await query.edit_message_text("Only the spender can confirm payments.")
            return

        if debtor_id not in tx["debts"]:
            await query.edit_message_text("Debtor not found in this transaction.")
            return

        if tx["debts"][debtor_id] != "marked":
            await query.edit_message_text("This payment is not marked as paid.")
            return

        tx["debts"][debtor_id] = "confirmed"
        await query.edit_message_text("Payment confirmed.")

        try:
            await context.bot.send_message(
                chat_id=debtor_id,
                text=(
                    f"Your payment for expense '{tx['description']}' (Share: {tx['share']:.2f}) "
                    f"has been confirmed by {registered_users.get(user.id)}."
                )
            )
        except Exception as e:
            logger.warning(f"Could not notify debtor {debtor_id}: {e}")

# ---------- Main Function ----------

def main():
    TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
    if not TOKEN:
        logger.error("TELEGRAM_BOT_TOKEN environment variable not set.")
        return

    application = ApplicationBuilder().token(TOKEN).build()

    # /start command.
    application.add_handler(CommandHandler("start", start))
    
    # Conversation handler for adding an expense.
    add_expense_conv = ConversationHandler(
        entry_points=[
            CommandHandler("addexpense", add_expense_start),
            CallbackQueryHandler(add_expense_start, pattern="^menu_add_expense$")
        ],
        states={
            AMOUNT: [MessageHandler(filters.TEXT & ~filters.COMMAND, add_expense_amount)],
            DESCRIPTION: [MessageHandler(filters.TEXT & ~filters.COMMAND, add_expense_description)]
        },
        fallbacks=[CommandHandler("cancel", cancel)]
    )
    application.add_handler(add_expense_conv)
    
    # /summary command.
    application.add_handler(CommandHandler("summary", summary))
    
    # Handlers for main menu buttons and payment actions.
    application.add_handler(CallbackQueryHandler(menu_callback, pattern="^menu_"))
    application.add_handler(CallbackQueryHandler(button_handler, pattern="^(paid:|confirm:)"))
    
    application.run_polling()

if __name__ == "__main__":
    main()
