import os
import logging
from telegram import Update, ReplyKeyboardMarkup, ReplyKeyboardRemove
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    MessageHandler,
    ConversationHandler,
    ContextTypes,
    filters,
)

# Set up logging.
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO
)
logger = logging.getLogger(__name__)

# Global storage.
# registered_users: maps user_id to display name.
registered_users = {}

# transactions: maps transaction_id to a dict with details.
# Each transaction has:
#   "id": transaction id,
#   "spender": user_id of the person who paid,
#   "amount": total amount,
#   "description": expense description,
#   "share": (amount split among selected participants),
#   "debts": dict mapping each debtor's user_id to status ("pending", "marked", "confirmed")
transactions = {}
next_transaction_id = 1  # Simple counter.

# --- Conversation State Constants ---
# Registration
REG_NAME = 0
# Add Expense Conversation
AE_AMOUNT = 0
AE_DESCRIPTION = 1
AE_PARTICIPANTS = 2
# Mark as Paid Conversation
MP_SELECT = 0
# Confirm Payment Conversation
CP_SELECT = 0
CP_DEBTOR = 1

# --- Utility: Main Menu Keyboard ---
def get_main_menu():
    return ReplyKeyboardMarkup(
        [["Add Expense 🤑", "View Summary 📊"], ["Mark as Paid 💸", "Confirm Payment ✅"]],
        resize_keyboard=True,
        one_time_keyboard=False,
    )

# --- Registration Conversation ---
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    user = update.effective_user
    if user.id in registered_users:
        await update.message.reply_text(
            f"Welcome back, {registered_users[user.id]}! How far? 😎",
            reply_markup=get_main_menu()
        )
        return ConversationHandler.END
    else:
        await update.message.reply_text(
            "Hey there! Abeg, type your display name (make e cool):",
            reply_markup=ReplyKeyboardRemove(),
        )
        return REG_NAME

async def reg_name(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    name = update.message.text.strip()
    user = update.effective_user
    registered_users[user.id] = name
    await update.message.reply_text(
        f"Registration complete! Welcome, {name}! Let's make money moves together 💪",
        reply_markup=get_main_menu(),
    )
    return ConversationHandler.END

# --- Add Expense Conversation ---
async def ae_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    user = update.effective_user
    if user.id not in registered_users:
        await update.message.reply_text("No wahala—register first with /start, abeg.")
        return ConversationHandler.END
    await update.message.reply_text(
        "How much did you spend? (Feel free to use commas, no stress) 😂",
        reply_markup=ReplyKeyboardRemove(),
    )
    return AE_AMOUNT

async def ae_amount(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    text = update.message.text.strip().replace(",", "")
    try:
        amount = float(text)
    except ValueError:
        await update.message.reply_text("Wetin be dis? Enter a proper number for the amount:")
        return AE_AMOUNT
    context.user_data["ae_amount"] = amount
    await update.message.reply_text("Now, drop a brief description (e.g., 'Chop suya for party'):")
    return AE_DESCRIPTION

async def ae_description(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    description = update.message.text.strip()
    context.user_data["ae_description"] = description
    await update.message.reply_text(
        "Enter a comma-separated list of display names to share the bill with.\n"
        "Type 'all' to bill everyone (except you), if una dey tight together:"
    )
    return AE_PARTICIPANTS

async def ae_participants(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    text = update.message.text.strip()
    amount = context.user_data.get("ae_amount")
    description = context.user_data.get("ae_description")
    spender_id = update.effective_user.id

    # Determine participants.
    if text.lower() == "all" or text == "":
        participants = [uid for uid in registered_users if uid != spender_id]
    else:
        names = [n.strip() for n in text.split(",") if n.strip()]
        participants = []
        for uid, disp in registered_users.items():
            if uid == spender_id:
                continue
            if any(disp.lower() == n.lower() for n in names):
                participants.append(uid)
        if not participants:
            await update.message.reply_text("E no work oh. No valid names found. Try again or type 'all':")
            return AE_PARTICIPANTS

    num = len(participants)
    if num == 0:
        await update.message.reply_text("No participants selected. You dey enjoy alone? Abeg try again.")
        return ConversationHandler.END
    share = amount / num

    global next_transaction_id
    tx_id = next_transaction_id
    next_transaction_id += 1
    transactions[tx_id] = {
        "id": tx_id,
        "spender": spender_id,
        "amount": amount,
        "description": description,
        "share": share,
        "debts": {uid: "pending" for uid in participants},
    }

    await update.message.reply_text(
        f"Expense recorded: '{description}' for ₦{amount:.2f}.\nEach selected friend owes ₦{share:.2f}.",
        reply_markup=get_main_menu(),
    )

    # Notify each participant with a friendly message.
    for debtor in participants:
        try:
            await context.bot.send_message(
                chat_id=debtor,
                text=(
                    f"Hey {registered_users.get(debtor)}! You owe ₦{share:.2f} for '{description}' by {registered_users[spender_id]}. "
                    "When you pay, mark am as paid using the 'Mark as Paid' option. No be small matter oo! 😉"
                )
            )
        except Exception as e:
            logger.warning(f"Could not notify user {debtor}: {e}")
    return ConversationHandler.END

# --- Mark as Paid Conversation ---
async def mp_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    user = update.effective_user
    if user.id not in registered_users:
        await update.message.reply_text("Register first with /start, my guy.", reply_markup=get_main_menu())
        return ConversationHandler.END
    # List pending transactions where the user is a debtor.
    pending = []
    for tx in transactions.values():
        if user.id in tx["debts"] and tx["debts"][user.id] == "pending":
            pending.append(tx)
    if not pending:
        await update.message.reply_text("Chai! You no get any pending payment at all.", reply_markup=get_main_menu())
        return ConversationHandler.END
    msg = "Pending payments:\n"
    for tx in pending:
        msg += f"ID {tx['id']}: You owe ₦{tx['share']:.2f} for '{tx['description']}' by {registered_users.get(tx['spender'], 'Unknown')}\n"
    msg += "\nEnter the transaction ID you want to mark as paid:"
    await update.message.reply_text(msg, reply_markup=ReplyKeyboardRemove())
    return MP_SELECT

async def mp_select(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    text = update.message.text.strip()
    try:
        tx_id = int(text)
    except ValueError:
        await update.message.reply_text("Abeg, enter a valid transaction ID:")
        return MP_SELECT
    user = update.effective_user
    tx = transactions.get(tx_id)
    if not tx or user.id not in tx["debts"] or tx["debts"][user.id] != "pending":
        await update.message.reply_text("Transaction no dey or don already process. Try again:")
        return MP_SELECT
    tx["debts"][user.id] = "marked"
    await update.message.reply_text("Marked as paid! Waiting for confirmation from the spender.", reply_markup=get_main_menu())
    # Notify the spender.
    spender_id = tx["spender"]
    try:
        await context.bot.send_message(
            chat_id=spender_id,
            text=(
                f"{registered_users[user.id]} don mark payment for transaction {tx_id} ('{tx['description']}').\n"
                "When you confirm, select 'Confirm Payment' from the menu."
            )
        )
    except Exception as e:
        logger.warning(f"Could not notify spender {spender_id}: {e}")
    return ConversationHandler.END

# --- Confirm Payment Conversation ---
async def cp_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    user = update.effective_user
    # List transactions for which the user (as spender) has marked payments.
    pending_conf = []
    for tx in transactions.values():
        if tx["spender"] == user.id:
            for debtor, status in tx["debts"].items():
                if status == "marked":
                    pending_conf.append(tx)
                    break
    if not pending_conf:
        await update.message.reply_text("No payment confirmation pending for you, boss!", reply_markup=get_main_menu())
        return ConversationHandler.END
    msg = "Payments pending confirmation:\n"
    for tx in pending_conf:
        marked_debtors = [registered_users.get(d, str(d)) for d, status in tx["debts"].items() if status == "marked"]
        msg += f"ID {tx['id']}: Marked by: {', '.join(marked_debtors)} for '{tx['description']}' (each owes ₦{tx['share']:.2f})\n"
    msg += "\nEnter the transaction ID to confirm payment:"
    await update.message.reply_text(msg, reply_markup=ReplyKeyboardRemove())
    return CP_SELECT

async def cp_select(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    text = update.message.text.strip()
    try:
        tx_id = int(text)
    except ValueError:
        await update.message.reply_text("Enter a valid transaction ID, please:")
        return CP_SELECT
    user = update.effective_user
    tx = transactions.get(tx_id)
    if not tx or tx["spender"] != user.id:
        await update.message.reply_text("No transaction found or you no be spender for that transaction. Try again:")
        return CP_SELECT
    marked_debtors = [d for d, status in tx["debts"].items() if status == "marked"]
    if not marked_debtors:
        await update.message.reply_text("No marked payment for this transaction.", reply_markup=get_main_menu())
        return ConversationHandler.END
    if len(marked_debtors) > 1:
        await update.message.reply_text("Multiple marked payments found. Type the debtor's display name to confirm:")
        context.user_data["cp_tx_id"] = tx_id
        return CP_DEBTOR
    debtor_id = marked_debtors[0]
    tx["debts"][debtor_id] = "confirmed"
    await update.message.reply_text(f"Payment confirmed for {registered_users.get(debtor_id)}. Cheers!", reply_markup=get_main_menu())
    try:
        await context.bot.send_message(
            chat_id=debtor_id,
            text=f"Your payment for '{tx['description']}' (ID {tx_id}) has been confirmed by {registered_users[user.id]}. Thanks o! 🙌"
        )
    except Exception as e:
        logger.warning(f"Could not notify debtor {debtor_id}: {e}")
    return ConversationHandler.END

async def cp_debtor(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    debtor_name = update.message.text.strip().lower()
    tx_id = context.user_data.get("cp_tx_id")
    user = update.effective_user
    tx = transactions.get(tx_id)
    if not tx or tx["spender"] != user.id:
        await update.message.reply_text("Something no set. Try again later.", reply_markup=get_main_menu())
        return ConversationHandler.END
    marked_debtors = [d for d, status in tx["debts"].items() if status == "marked"]
    debtor_id = None
    for d in marked_debtors:
        if registered_users.get(d, "").lower() == debtor_name:
            debtor_id = d
            break
    if debtor_id is None:
        await update.message.reply_text("No matching debtor found. Type the correct name:")
        return CP_DEBTOR
    tx["debts"][debtor_id] = "confirmed"
    await update.message.reply_text(f"Payment confirmed for {registered_users.get(debtor_id)}.", reply_markup=get_main_menu())
    try:
        await context.bot.send_message(
            chat_id=debtor_id,
            text=f"Your payment for '{tx['description']}' (ID {tx_id}) has been confirmed by {registered_users[user.id]}. You dey alright! 👍"
        )
    except Exception as e:
        logger.warning(f"Could not notify debtor {debtor_id}: {e}")
    return ConversationHandler.END

# --- View Summary Handler ---
async def view_summary(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = update.effective_user
    if user.id not in registered_users:
        await update.message.reply_text("Abeg register first with /start.", reply_markup=get_main_menu())
        return
    owe_me = []
    i_owe = []
    for tx in transactions.values():
        if tx["spender"] == user.id:
            for debtor, status in tx["debts"].items():
                owe_me.append(f"{registered_users.get(debtor, str(debtor))}: owes ₦{tx['share']:.2f} [{status}] for '{tx['description']}'")
        elif user.id in tx["debts"]:
            i_owe.append(f"To {registered_users.get(tx['spender'], str(tx['spender']))}: owe ₦{tx['share']:.2f} [{tx['debts'][user.id]}] for '{tx['description']}'")
    msg = ""
    if owe_me:
        msg += "📥 *People who owe you:*\n" + "\n".join(owe_me) + "\n\n"
    if i_owe:
        msg += "📤 *You owe:*\n" + "\n".join(i_owe)
    if not msg:
        msg = "No transactions to show. Enjoy your day, oga!"
    await update.message.reply_text(msg, reply_markup=get_main_menu(), parse_mode="Markdown")

# --- Main Function ---
def main():
    TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
    if not TOKEN:
        logger.error("TELEGRAM_BOT_TOKEN environment variable not set.")
        return

    application = ApplicationBuilder().token(TOKEN).build()

    # Registration Conversation Handler (triggered by /start)
    reg_conv_handler = ConversationHandler(
        entry_points=[CommandHandler("start", start)],
        states={
            REG_NAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, reg_name)]
        },
        fallbacks=[],
    )
    application.add_handler(reg_conv_handler)

    # Add Expense Conversation Handler (triggered by "Add Expense" or /addexpense)
    add_expense_conv = ConversationHandler(
        entry_points=[MessageHandler(filters.Regex("^Add Expense 🤑$"), ae_start),
                      CommandHandler("addexpense", ae_start)],
        states={
            AE_AMOUNT: [MessageHandler(filters.TEXT & ~filters.COMMAND, ae_amount)],
            AE_DESCRIPTION: [MessageHandler(filters.TEXT & ~filters.COMMAND, ae_description)],
            AE_PARTICIPANTS: [MessageHandler(filters.TEXT & ~filters.COMMAND, ae_participants)],
        },
        fallbacks=[CommandHandler("cancel", lambda update, context: update.message.reply_text("Cancelled.", reply_markup=get_main_menu()))],
    )
    application.add_handler(add_expense_conv)

    # Mark as Paid Conversation Handler (triggered by "Mark as Paid")
    mark_paid_conv = ConversationHandler(
        entry_points=[MessageHandler(filters.Regex("^Mark as Paid 💸$"), mp_start)],
        states={
            MP_SELECT: [MessageHandler(filters.TEXT & ~filters.COMMAND, mp_select)]
        },
        fallbacks=[CommandHandler("cancel", lambda update, context: update.message.reply_text("Cancelled.", reply_markup=get_main_menu()))],
    )
    application.add_handler(mark_paid_conv)

    # Confirm Payment Conversation Handler (triggered by "Confirm Payment")
    confirm_payment_conv = ConversationHandler(
        entry_points=[MessageHandler(filters.Regex("^Confirm Payment ✅$"), cp_start)],
        states={
            CP_SELECT: [MessageHandler(filters.TEXT & ~filters.COMMAND, cp_select)],
            CP_DEBTOR: [MessageHandler(filters.TEXT & ~filters.COMMAND, cp_debtor)],
        },
        fallbacks=[CommandHandler("cancel", lambda update, context: update.message.reply_text("Cancelled.", reply_markup=get_main_menu()))],
    )
    application.add_handler(confirm_payment_conv)

    # View Summary Handler (triggered by "View Summary" or /summary)
    application.add_handler(MessageHandler(filters.Regex("^View Summary 📊$"), view_summary))
    application.add_handler(CommandHandler("summary", view_summary))

    application.run_polling()

if __name__ == "__main__":
    main()
