import os
import logging
import asyncio
import nest_asyncio  # <-- added import
nest_asyncio.apply()  # <-- patch the running loop

from telegram import (
    Update,
    ReplyKeyboardMarkup,
    ReplyKeyboardRemove,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
)
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    MessageHandler,
    CallbackQueryHandler,
    ConversationHandler,
    ContextTypes,
    filters,
)
import db

# Set up logging.
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO
)
logger = logging.getLogger(__name__)

# Conversation state constants.
# Registration
REG_NAME = 0
# Add Expense Conversation:
AE_AMOUNT = 0
AE_DESCRIPTION = 1
AE_SELECT = 2
# Mark as Paid Conversation:
MP_SELECT = 0
# Confirm Payment Conversation:
CP_SELECT = 0
CP_DEBTOR = 1

# Utility: Main Menu Keyboard.
def get_main_menu():
    return ReplyKeyboardMarkup(
        [["Add Expense 🤑", "View Summary 📊"], ["Mark as Paid 💸", "Confirm Payment ✅"]],
        resize_keyboard=True,
        one_time_keyboard=False,
    )

# --- Registration Conversation ---
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    user = update.effective_user
    display_name = await db.get_user(user.id)
    if display_name:
        await update.message.reply_text(
            f"Welcome back, {display_name}! How far? 😎",
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
    await db.create_or_update_user(user.id, name)
    await update.message.reply_text(
        f"Registration complete! Welcome, {name}! Let's make money moves together 💪",
        reply_markup=get_main_menu(),
    )
    return ConversationHandler.END

# --- Add Expense Conversation ---
async def ae_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    user = update.effective_user
    if not await db.get_user(user.id):
        await update.message.reply_text("No wahala—register first with /start, abeg.")
        return ConversationHandler.END
    await update.message.reply_text(
        "How much did you spend? (Feel free to use commas) 😂",
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
    # Initialize selected participants list.
    context.user_data["selected_participants"] = []
    # Begin selection using inline keyboard.
    return await ae_select_start(update, context)

async def ae_select_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    spender_id = update.effective_user.id
    # Get all registered users from the database.
    all_users = await db.get_all_users()  # Returns list of dicts: {"user_id": ..., "display_name": ...}
    # Available participants: all except the spender and those already selected.
    selected = context.user_data.get("selected_participants", [])
    available = [u for u in all_users if u["user_id"] != spender_id and u["user_id"] not in selected]
    keyboard = []
    for user_record in available:
        keyboard.append([InlineKeyboardButton(user_record["display_name"], callback_data=f"select_{user_record['user_id']}")])
    keyboard.append([InlineKeyboardButton("Done", callback_data="select_done")])
    selected_names = ", ".join([str(uid) for uid in selected]) or "None"
    text = f"Select participants for this expense.\nAlready selected: {selected_names}"
    if update.message:
        sent = await update.message.reply_text(text, reply_markup=InlineKeyboardMarkup(keyboard))
    else:
        sent = await update.callback_query.message.reply_text(text, reply_markup=InlineKeyboardMarkup(keyboard))
    context.user_data["select_msg_id"] = sent.message_id
    context.user_data["select_chat_id"] = sent.chat.id
    return AE_SELECT

async def ae_select_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    data = query.data
    spender_id = query.from_user.id
    if data == "select_done":
        selected = context.user_data.get("selected_participants", [])
        if not selected:
            await query.edit_message_text("No participants selected. Expense canceled.", reply_markup=get_main_menu())
            return ConversationHandler.END
        amount = context.user_data.get("ae_amount")
        description = context.user_data.get("ae_description")
        num = len(selected)
        share = amount / num
        tx_id = await db.add_transaction(spender_id, amount, description, share, selected)
        await query.edit_message_text(
            f"Expense recorded: '{description}' for ₦{amount:.2f}.\nEach selected friend owes ₦{share:.2f}."
        )
        # Notify each selected participant.
        for debtor in selected:
            try:
                debtor_disp = await db.get_user(debtor)
                spender_disp = await db.get_user(spender_id)
                await context.bot.send_message(
                    chat_id=debtor,
                    text=(
                        f"Hey {debtor_disp}! You owe ₦{share:.2f} for '{description}' by {spender_disp}.\n"
                        "Mark as paid when you settle up. No be small matter oo! 😉"
                    )
                )
            except Exception as e:
                logger.warning(f"Could not notify user {debtor}: {e}")
        return ConversationHandler.END
    else:
        try:
            uid = int(data.split("_")[1])
        except Exception:
            await query.answer("Invalid selection.")
            return AE_SELECT
        if "selected_participants" not in context.user_data:
            context.user_data["selected_participants"] = []
        if uid not in context.user_data["selected_participants"]:
            context.user_data["selected_participants"].append(uid)
        all_users = await db.get_all_users()
        available = [u for u in all_users if u["user_id"] != spender_id and u["user_id"] not in context.user_data["selected_participants"]]
        keyboard = []
        for user_record in available:
            keyboard.append([InlineKeyboardButton(user_record["display_name"], callback_data=f"select_{user_record['user_id']}")])
        keyboard.append([InlineKeyboardButton("Done", callback_data="select_done")])
        selected = context.user_data.get("selected_participants", [])
        selected_names = ", ".join([str(uid) for uid in selected]) or "None"
        text = f"Select participants for this expense.\nAlready selected: {selected_names}"
        await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard))
        return AE_SELECT

# --- Mark as Paid Conversation ---
async def mp_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    user = update.effective_user
    if not await db.get_user(user.id):
        await update.message.reply_text("Register first with /start, my guy.", reply_markup=get_main_menu())
        return ConversationHandler.END
    pending = await db.get_pending_debts_for_user(user.id)
    if not pending:
        await update.message.reply_text("Chai! You no get any pending payment at all.", reply_markup=get_main_menu())
        return ConversationHandler.END
    msg = "Pending payments:\n"
    for tx in pending:
        spender_disp = await db.get_user(tx["spender"])
        msg += f"ID {tx['id']}: You owe ₦{tx['share']:.2f} for '{tx['description']}' by {spender_disp}\n"
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
    pending = await db.get_pending_debts_for_user(user.id)
    tx = None
    for t in pending:
        if t["id"] == tx_id:
            tx = t
            break
    if not tx:
        await update.message.reply_text("Transaction no dey or don already process. Try again:")
        return MP_SELECT
    await db.mark_debt_as_marked(tx_id, user.id)
    await update.message.reply_text("Marked as paid! Waiting for confirmation from the spender.", reply_markup=get_main_menu())
    try:
        spender_disp = await db.get_user(tx["spender"])
        await context.bot.send_message(
            chat_id=tx["spender"],
            text=(
                f"{await db.get_user(user.id)} don mark payment for transaction {tx_id} ('{tx['description']}').\n"
                "When you confirm, select 'Confirm Payment' from the menu."
            )
        )
    except Exception as e:
        logger.warning(f"Could not notify spender {tx['spender']}: {e}")
    return ConversationHandler.END

# --- Confirm Payment Conversation ---
async def cp_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    user = update.effective_user
    pending_conf = await db.get_pending_confirmations_for_spender(user.id)
    if not pending_conf:
        await update.message.reply_text("No payment confirmation pending for you, boss!", reply_markup=get_main_menu())
        return ConversationHandler.END
    msg = "Payments pending confirmation:\n"
    for tx in pending_conf:
        marked = await db.get_marked_debtors(tx["id"])
        marked_names = []
        for debtor in marked:
            name = await db.get_user(debtor)
            marked_names.append(name)
        msg += f"ID {tx['id']}: Marked by: {', '.join(marked_names)} for '{tx['description']}' (each owes ₦{tx['share']:.2f})\n"
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
    pending_conf = await db.get_pending_confirmations_for_spender(user.id)
    tx = None
    for t in pending_conf:
        if t["id"] == tx_id:
            tx = t
            break
    if not tx:
        await update.message.reply_text("Transaction not found or you no be spender for that transaction. Try again:")
        return CP_SELECT
    marked_debtors = await db.get_marked_debtors(tx_id)
    if not marked_debtors:
        await update.message.reply_text("No marked payment for this transaction.", reply_markup=get_main_menu())
        return ConversationHandler.END
    if len(marked_debtors) > 1:
        await update.message.reply_text("Multiple marked payments found. Type the debtor's display name to confirm:")
        context.user_data["cp_tx_id"] = tx_id
        return CP_DEBTOR
    debtor_id = marked_debtors[0]
    await db.confirm_debt(tx_id, debtor_id)
    debtor_disp = await db.get_user(debtor_id)
    await update.message.reply_text(f"Payment confirmed for {debtor_disp}. Cheers!", reply_markup=get_main_menu())
    try:
        await context.bot.send_message(
            chat_id=debtor_id,
            text=f"Your payment for '{tx['description']}' (ID {tx_id}) has been confirmed by {await db.get_user(user.id)}. Thanks o! 🙌"
        )
    except Exception as e:
        logger.warning(f"Could not notify debtor {debtor_id}: {e}")
    return ConversationHandler.END

async def cp_debtor(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    debtor_name = update.message.text.strip().lower()
    tx_id = context.user_data.get("cp_tx_id")
    user = update.effective_user
    marked_debtors = await db.get_marked_debtors(tx_id)
    debtor_id = None
    for d in marked_debtors:
        name = (await db.get_user(d)).lower()
        if name == debtor_name:
            debtor_id = d
            break
    if debtor_id is None:
        await update.message.reply_text("No matching debtor found. Type the correct name:")
        return CP_DEBTOR
    await db.confirm_debt(tx_id, debtor_id)
    await update.message.reply_text(f"Payment confirmed for {await db.get_user(debtor_id)}.", reply_markup=get_main_menu())
    try:
        await context.bot.send_message(
            chat_id=debtor_id,
            text=f"Your payment for transaction ID {tx_id} has been confirmed by {await db.get_user(user.id)}. You dey alright! 👍"
        )
    except Exception as e:
        logger.warning(f"Could not notify debtor {debtor_id}: {e}")
    return ConversationHandler.END

# --- View Summary Handler ---
async def view_summary(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = update.effective_user
    if not await db.get_user(user.id):
        await update.message.reply_text("Abeg register first with /start.", reply_markup=get_main_menu())
        return
    owe_me, i_owe = await db.get_summary_for_user(user.id)
    msg = ""
    if owe_me:
        lines = []
        for row in owe_me:
            debtor_disp = await db.get_user(row["debtor_id"])
            lines.append(f"{debtor_disp}: owes ₦{row['share']:.2f} [{row['status']}] for '{row['description']}'")
        msg += "📥 *People who owe you:*\n" + "\n".join(lines) + "\n\n"
    if i_owe:
        lines = []
        for row in i_owe:
            spender_disp = await db.get_user(row["spender"])
            lines.append(f"To {spender_disp}: owe ₦{row['share']:.2f} [{row['status']}] for '{row['description']}'")
        msg += "📤 *You owe:*\n" + "\n".join(lines)
    if not msg:
        msg = "No transactions to show. Enjoy your day, oga!"
    await update.message.reply_text(msg, reply_markup=get_main_menu(), parse_mode="Markdown")

# --- Async Main Function ---
async def main():
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

    # Add Expense Conversation Handler (triggered by "Add Expense 🤑" or /addexpense)
    add_expense_conv = ConversationHandler(
        entry_points=[MessageHandler(filters.Regex("^Add Expense 🤑$"), ae_start),
                      CommandHandler("addexpense", ae_start)],
        states={
            AE_AMOUNT: [MessageHandler(filters.TEXT & ~filters.COMMAND, ae_amount)],
            AE_DESCRIPTION: [MessageHandler(filters.TEXT & ~filters.COMMAND, ae_description)],
            AE_SELECT: [CallbackQueryHandler(ae_select_callback, pattern="^(select_).*")],
        },
        fallbacks=[CommandHandler("cancel", lambda update, context: update.message.reply_text("Cancelled.", reply_markup=get_main_menu()))],
    )
    application.add_handler(add_expense_conv)

    # Mark as Paid Conversation Handler (triggered by "Mark as Paid 💸")
    mark_paid_conv = ConversationHandler(
        entry_points=[MessageHandler(filters.Regex("^Mark as Paid 💸$"), mp_start)],
        states={
            MP_SELECT: [MessageHandler(filters.TEXT & ~filters.COMMAND, mp_select)]
        },
        fallbacks=[CommandHandler("cancel", lambda update, context: update.message.reply_text("Cancelled.", reply_markup=get_main_menu()))],
    )
    application.add_handler(mark_paid_conv)

    # Confirm Payment Conversation Handler (triggered by "Confirm Payment ✅")
    confirm_payment_conv = ConversationHandler(
        entry_points=[MessageHandler(filters.Regex("^Confirm Payment ✅$"), cp_start)],
        states={
            CP_SELECT: [MessageHandler(filters.TEXT & ~filters.COMMAND, cp_select)],
            CP_DEBTOR: [MessageHandler(filters.TEXT & ~filters.COMMAND, cp_debtor)],
        },
        fallbacks=[CommandHandler("cancel", lambda update, context: update.message.reply_text("Cancelled.", reply_markup=get_main_menu()))],
    )
    application.add_handler(confirm_payment_conv)

    # View Summary Handler (triggered by "View Summary 📊" or /summary)
    application.add_handler(MessageHandler(filters.Regex("^View Summary 📊$"), view_summary))
    application.add_handler(CommandHandler("summary", view_summary))

    # Initialize the database pool.
    await db.init_db()
    # Run polling (this call is blocking until the bot is stopped).
    await application.run_polling()
    # On shutdown, close the database pool.
    await db.close_db()

if __name__ == "__main__":
    asyncio.run(main())
