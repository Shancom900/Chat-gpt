import subprocess
import sys

def install(package):
    subprocess.check_call([sys.executable, "-m", "pip", "install", package])

# Auto-install critical dependencies
for pkg in ["openai", "firebase-admin", "requests", "python-telegram-bot"]:
    try:
        __import__(pkg.replace("-", "_"))
    except ImportError:
        print(f"Installing missing package: {pkg}")
        install(pkg)
        import logging
from datetime import datetime, timedelta
import json
import requests
import openai
import firebase_admin
from firebase_admin import credentials, firestore
from telegram import Update, LabeledPrice
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    ContextTypes,
    PreCheckoutQueryHandler,
    MessageHandler,
    filters,
)

# Enable logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# --- CONFIGURATION ---

# Your Telegram Bot Token here
TELEGRAM_BOT_TOKEN = "8025458623:AAHXF_luXYdSEMBWC8Gicanwj4xspnWxAqA"

# Firebase service account key JSON file path
FIREBASE_JSON = "chat-gpt-9a6ea-firebase-adminsdk-fbsvc-985588b55b.json"

# OpenAI API key
OPENAI_API_KEY = "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"

# Gemini API key
GEMINI_API_KEY = "AIzaSyA0hwuydsWmv8X1t23XDpI5-krb8hzh0XM"

# Telegram Payments provider token for Stars (⭐) payments
PROVIDER_TOKEN = "6073714100:TEST:TG_aKZaxXp68ryHzPvMG0breEwA"

# Admin Telegram IDs (strings)
ADMINS = ["7598595878"]

# Models available to users (free tier)
AVAILABLE_MODELS = {
    "gpt-4o-mini": "OpenAI GPT-4o Mini (Free)",
    "deepseek": "DeepSeek V3 (Free)",
    "gemini": "Google Gemini 2.5 (Free)",
}

# Usage limits and cooldowns per tier
TIERS = {
    "free": {"text_limit": 50, "image_limit": 5, "cooldown": 20},
    "premium": {"text_limit": 100, "image_limit": 10, "cooldown": 0},
    "premium_x2": {"text_limit": 200, "image_limit": 20, "cooldown": 0},
}

# --- INITIALIZE SERVICES ---

# Firebase init
cred = credentials.Certificate(FIREBASE_JSON)
firebase_admin.initialize_app(cred)
db = firestore.client()

# OpenAI init
openai.api_key = OPENAI_API_KEY


# --- HELPER FUNCTIONS ---


def reset_if_needed(data, doc_ref):
    now = datetime.utcnow()
    last_reset = data.get("last_reset")
    if last_reset:
        # Convert Firestore timestamp to datetime if needed
        if hasattr(last_reset, "replace"):
            last_reset = last_reset.replace(tzinfo=None)
        else:
            try:
                last_reset = datetime.strptime(last_reset, "%Y-%m-%dT%H:%M:%S.%fZ")
            except Exception:
                last_reset = now - timedelta(hours=39)
    else:
        last_reset = now - timedelta(hours=39)

    if (now - last_reset).total_seconds() > 38 * 3600:
        doc_ref.set(
            {
                "text_used": 0,
                "image_used": 0,
                "last_reset": now,
            },
            merge=True,
        )
        data["text_used"] = 0
        data["image_used"] = 0
        data["last_reset"] = now

    return data


def call_gpt_4o_mini(prompt):
    try:
        response = openai.ChatCompletion.create(
            model="gpt-4o-mini",
            messages=[{"role": "user", "content": prompt}],
        )
        return response["choices"][0]["message"]["content"]
    except Exception as e:
        return f"OpenAI API error: {e}"


def call_deepseek(prompt):
    # Placeholder for unofficial free DeepSeek API (replace with real if available)
    return "DeepSeek API is currently not integrated."


def call_gemini(prompt):
    url = f"https://generativelanguage.googleapis.com/v1beta2/models/text-bison-001:generateText?key={GEMINI_API_KEY}"
    headers = {"Content-Type": "application/json"}
    data = {"prompt": {"text": prompt}, "temperature": 0.7, "maxTokens": 256}
    try:
        res = requests.post(url, json=data, headers=headers, timeout=10)
        if res.status_code == 200:
            return res.json()["candidates"][0]["output"]
        else:
            return f"Gemini API error: {res.status_code}"
    except Exception as e:
        return f"Gemini request failed: {e}"


# --- COMMAND HANDLERS ---


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = (
        "Welcome! Use /ask <question> to chat with AI.\n"
        "Use /wow <prompt> for AI images.\n"
        "Use /model to select AI model.\n"
        "Use /buy to get premium access with Telegram Stars."
    )
    await update.message.reply_text(msg)


async def ask(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = str(update.effective_user.id)
    prompt = " ".join(context.args)
    if not prompt:
        await update.message.reply_text("Please add a prompt. Example:\n/ask What is AI?")
        return

    doc_ref = db.collection("users").document(user_id)
    doc = doc_ref.get()
    now = datetime.utcnow()

    if doc.exists:
        data = doc.to_dict()
    else:
        data = {
            "tier": "free",
            "last_used": now - timedelta(seconds=60),
            "text_used": 0,
            "image_used": 0,
            "model": "gpt-4o-mini",
            "last_reset": now,
        }

    data = reset_if_needed(data, doc_ref)

    tier = data.get("tier", "free")
    limits = TIERS.get(tier, TIERS["free"])
    last_used = data.get("last_used", now - timedelta(minutes=1))

    if (now - last_used).total_seconds() < limits["cooldown"]:
        await update.message.reply_text(
            "⏳ Please wait before sending another prompt."
        )
        return

    if data["text_used"] >= limits["text_limit"]:
        await update.message.reply_text(
            "❌ You've hit your daily limit. Upgrade to premium for more."
        )
        return

    model_choice = data.get("model", "gpt-4o-mini")

    if model_choice == "gpt-4o-mini":
        reply = call_gpt_4o_mini(prompt)
    elif model_choice == "deepseek":
        reply = call_deepseek(prompt)
    elif model_choice == "gemini":
        reply = call_gemini(prompt)
    else:
        reply = "❌ Model not supported."

    doc_ref.set(
        {
            "tier": tier,
            "last_used": now,
            "text_used": data["text_used"] + 1,
            "model": model_choice,
        },
        merge=True,
    )

    await update.message.reply_text(reply)


async def wow(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = str(update.effective_user.id)
    prompt = " ".join(context.args)
    if not prompt:
        await update.message.reply_text(
            "Send your image prompt after /wow.\nExample: `/wow a cyberpunk cat`",
            parse_mode="Markdown",
        )
        return

    doc_ref = db.collection("users").document(user_id)
    doc = doc_ref.get()
    now = datetime.utcnow()

    if doc.exists:
        data = doc.to_dict()
    else:
        data = {
            "tier": "free",
            "last_used": now - timedelta(seconds=60),
            "text_used": 0,
            "image_used": 0,
            "model": "gpt-4o-mini",
            "last_reset": now,
        }

    data = reset_if_needed(data, doc_ref)

    tier = data.get("tier", "free")
    limits = TIERS.get(tier, TIERS["free"])
    last_used = data.get("last_used", now - timedelta(minutes=1))

    if (now - last_used).total_seconds() < limits["cooldown"]:
        await update.message.reply_text("⏳ Please wait a few seconds before next command.")
        return

    if data["image_used"] >= limits["image_limit"]:
        await update.message.reply_text(
            "❌ You've hit your daily image limit. Upgrade to premium for more."
        )
        return

    # Generate image via OpenAI DALL·E 3
    try:
        response = openai.Image.create(
            model="dall-e-3",
            prompt=prompt,
            n=1,
            size="1024x1024",
        )
        image_url = response["data"][0]["url"]
    except Exception as e:
        await update.message.reply_text(f"Image error: {e}")
        return

    doc_ref.set(
        {
            "tier": tier,
            "last_used": now,
            "text_used": data.get("text_used", 0),
            "image_used": data.get("image_used", 0) + 1,
            "model": data.get("model", "gpt-4o-mini"),
        },
        merge=True,
    )

    await update.message.reply_photo(photo=image_url, caption="Here's your AI image!")


async def model(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = str(update.effective_user.id)
    if not context.args:
        msg = "*Choose a model:*\n" + "\n".join(
            [f"- `{k}` = {v}" for k, v in AVAILABLE_MODELS.items()]
        )
        await update.message.reply_text(msg, parse_mode="Markdown")
        return

    chosen = context.args[0]
    if chosen not in AVAILABLE_MODELS:
        await update.message.reply_text(
            f"❌ Invalid model.\nAvailable:\n" + ", ".join(AVAILABLE_MODELS.keys())
        )
        return

    db.collection("users").document(user_id).set({"model": chosen}, merge=True)
    await update.message.reply_text(
        f"✅ Model set to: *{AVAILABLE_MODELS[chosen]}*", parse_mode="Markdown"
    )


async def addpremium(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if str(update.effective_user.id) not in ADMINS:
        await update.message.reply_text("❌ You are not authorized.")
        return

    if len(context.args) < 2:
        await update.message.reply_text("Usage: /addpremium <user_id> <tier>")
        return

    user_id, tier = context.args[0], context.args[1]
    if tier not in TIERS:
        await update.message.reply_text(
            f"❌ Invalid tier. Choose one of: {', '.join(TIERS.keys())}"
        )
        return

    db.collection("users").document(user_id).set({"tier": tier}, merge=True)
    await update.message.reply_text(f"✅ User {user_id} upgraded to `{tier}`")


async def removepremium(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if str(update.effective_user.id) not in ADMINS:
        await update.message.reply_text("❌ You are not authorized.")
        return

    if len(context.args) < 1:
        await update.message.reply_text("Usage: /removepremium <user_id>")
        return

    user_id = context.args[0]
    db.collection("users").document(user_id).set({"tier": "free"}, merge=True)
    await update.message.reply_text(f"✅ User {user_id} downgraded to `free`")


async def buy(update: Update, context: ContextTypes.DEFAULT_TYPE):
    prices = [LabeledPrice("Premium Plan ⭐20", 20)]
    await update.message.reply_invoice(
        title="Premium Subscription",
        description="Get access to premium AI tools.",
        payload="premium_plan_20",
        provider_token=PROVIDER_TOKEN,
        currency="XTR",  # Telegram Stars
        prices=prices,
        start_parameter="premium_purchase",
        photo_url="https://telegra.ph/file/4eb39db6d71c79245169a.jpg",
        photo_size=512,
        photo_width=512,
        photo_height=512,
    )


async def precheckout_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.pre_checkout_query
    await query.answer(ok=True)


async def successful_payment_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = str(update.effective_user.id)
    payload = update.message.successful_payment.invoice_payload

    if payload == "premium_plan_20":
        # Upgrade user tier in Firebase
        db.collection("users").document(user_id).set({"tier": "premium"}, merge=True)
        await update.message.reply_text(
            "🎉 Thank you for purchasing Premium! You now have full access."
        )


# --- MAIN ---

async def main():
    app = ApplicationBuilder().token(TELEGRAM_BOT_TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("ask", ask))
    app.add_handler(CommandHandler("wow", wow))
    app.add_handler(CommandHandler("model", model))
    app.add_handler(CommandHandler("buy", buy))

    app.add_handler(CommandHandler("addpremium", addpremium))
    app.add_handler(CommandHandler("removepremium", removepremium))

    app.add_handler(PreCheckoutQueryHandler(precheckout_callback))
    app.add_handler(MessageHandler(filters.SUCCESSFUL_PAYMENT, successful_payment_callback))

    await app.run_polling()


if __name__ == "__main__":
    import asyncio

    asyncio.run(main())
