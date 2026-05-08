import os
import json
import logging
from dotenv import load_dotenv
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    MessageHandler,
    CallbackQueryHandler,
    ContextTypes,
    filters,
)
from search.search import search, SearchResult

load_dotenv()

logging.basicConfig(level=logging.INFO)

TELEGRAM_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
WHITELIST = set(os.getenv("TELEGRAM_WHITELIST", "").split(","))  # comma separated IDs


# ── Auth guard ────────────────────────────────────────────────────────────────

def is_authorized(user_id: int) -> bool:
    return str(user_id) in WHITELIST


async def deny(update: Update):
    await update.message.reply_text(
        "⛔ You are not authorized to use this bot. Contact your admin to get access."
    )


# ── Helpers ───────────────────────────────────────────────────────────────────

def format_result(i: int, r: SearchResult) -> str:
    return (
        f"*{i}. {r.heading}*\n"
        f"{r.text[:300]}{'...' if len(r.text) > 300 else ''}\n"
        f"📄 [View in docs]({r.source_url})"
    )


def flag_keyboard(query: str, result_text: str) -> InlineKeyboardMarkup:
    payload = json.dumps({"q": query[:50], "a": result_text[:50]})
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🚩 Flag this answer", callback_data=f"flag:{payload}")]
    ])


# ── Handlers ──────────────────────────────────────────────────────────────────

async def start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not is_authorized(update.effective_user.id):
        return await deny(update)

    await update.message.reply_text(
        "👋 Welcome to the Orcta Docs bot!\n\n"
        "Just type any question and I'll search the internal docs.\n\n"
        "Commands:\n"
        "/guidelines — get the coding enforcement prompt\n"
        "/versions — list indexed doc versions\n"
        "/help — show this message"
    )


async def handle_message(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not is_authorized(update.effective_user.id):
        return await deny(update)

    query = update.message.text.strip()
    await update.message.reply_text("🔍 Searching docs...")

    results = search(query)

    if not results:
        await update.message.reply_text(
            "❌ No relevant results found. Try rephrasing your question."
        )
        return

    # send each result as a separate message with a flag button
    for i, r in enumerate(results, 1):
        await update.message.reply_text(
            format_result(i, r),
            parse_mode="Markdown",
            reply_markup=flag_keyboard(query, r.text),
            disable_web_page_preview=False,
        )


async def guidelines(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not is_authorized(update.effective_user.id):
        return await deny(update)

    prompt = """
*Orcta Tech Coding Guidelines*

1. Always call `search_docs` before implementing anything touching internal APIs.
2. Never use an external library if an internal equivalent is documented.
3. If search returns no results, ask for clarification — don't guess.
4. Always cite the source URL from the search result.
5. When in doubt, search again with a more specific query.

Copy this into your agent's system prompt to enforce internal standards.
    """.strip()

    await update.message.reply_text(prompt, parse_mode="Markdown")


async def versions(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not is_authorized(update.effective_user.id):
        return await deny(update)

    import psycopg2
    POSTGRES_URL = os.getenv("POSTGRES_URL")
    conn = psycopg2.connect(POSTGRES_URL)
    cur = conn.cursor()
    cur.execute("SELECT DISTINCT doc_version FROM doc_chunks ORDER BY doc_version;")
    vs = [row[0] for row in cur.fetchall()]
    conn.close()

    await update.message.reply_text(
        "*Indexed doc versions:*\n" + "\n".join(f"• {v}" for v in vs),
        parse_mode="Markdown",
    )


async def handle_flag(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    query_obj = update.callback_query
    await query_obj.answer()

    try:
        payload = json.loads(query_obj.data.replace("flag:", "", 1))
        import valkey as vk_lib
        vk = vk_lib.Valkey(
            host=os.getenv("VALKEY_HOST", "localhost"),
            port=int(os.getenv("VALKEY_PORT", 6379)),
        )
        vk.lpush("flags:answers", json.dumps({
            "query": payload["q"],
            "answer": payload["a"],
            "issue": "flagged via telegram",
            "user_id": query_obj.from_user.id,
        }))
        await query_obj.edit_message_reply_markup(reply_markup=None)
        await query_obj.message.reply_text("✅ Flagged — thanks for the feedback.")
    except Exception as e:
        await query_obj.message.reply_text(f"❌ Could not flag: {e}")


# ── Entry point ───────────────────────────────────────────────────────────────

if __name__ == "__main__":
    app = ApplicationBuilder().token(TELEGRAM_TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("help", start))
    app.add_handler(CommandHandler("guidelines", guidelines))
    app.add_handler(CommandHandler("versions", versions))
    app.add_handler(CallbackQueryHandler(handle_flag, pattern="^flag:"))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

    app.run_polling()