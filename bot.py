import subprocess
import sys

# Auto-install required packages
def install(package):
    subprocess.check_call([sys.executable, "-m", "pip", "install", package])

for pkg in ["openai", "firebase-admin", "requests", "python-telegram-bot", "python-dotenv"]:
    try:
        __import__(pkg.replace("-", "_"))
    except ImportError:
        print(f"Installing missing package: {pkg}")
        install(pkg)

import logging
from datetime import datetime, timedelta
import os
import json
from dotenv import load_dotenv
import openai
import requests
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

# Load .env values
load_dotenv()
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
PROVIDER_TOKEN = os.getenv("PROVIDER_TOKEN")
FIREBASE_CREDENTIAL_JSON = os.getenv("FIREBASE_CREDENTIAL_JSON")
ADMINS = [os.getenv("ADMIN_ID", "7598595878")]

# Firebase init
firebase_json = json.loads(FIREBASE_CREDENTIAL_JSON)
cred = credentials.Certificate(firebase_json)
firebase_admin.initialize_app(cred)
db = firestore.client()

openai.api_key = OPENAI_API_KEY

# Logging
logging.basicConfig(level=logging.INFO)

AVAILABLE_MODELS = {
    "gpt-4o-mini": "OpenAI GPT-4o Mini (Free)",
    "deepseek": "DeepSeek V3 (Free)",
    "gemini": "Google Gemini 2.5 (Free)",
}

TIERS = {
    "free": {"text_limit": 50, "image_limit": 5, "cooldown": 20},
    "premium": {"text_limit": 100, "image_limit": 10, "cooldown": 0},
    "premium_x2": {"text_limit": 200, "image_limit": 20, "cooldown": 0},
}

def reset_if_needed(data, doc_ref):
    now = datetime.utcnow()
    last_reset = data.get("last_reset", now - timedelta(hours=39))
    if isinstance(last_reset, str):
        try:
            last_reset = datetime.strptime(last_reset, "%Y-%m-%dT%H:%M:%S.%fZ")
        except:
            last_reset = now - timedelta(hours=39)
    if (now - last_reset).total_seconds() > 38 * 3600:
        doc_ref.set({
            "text_used": 0,
            "image_used": 0,
            "last_reset": now
        }, merge=True)
        data["text_used"] = 0
        data["image_used"] = 0
        data["last_reset"] = now
    return data

def call_gpt_4o_mini(prompt):
    try:
        res = openai.ChatCompletion.create(
            model="gpt-4o-mini",
            messages=[{"role": "user", "content": prompt}]
        )
        return res["choices"][0]["message"]["content"]
    except Exception as e:
        return f"OpenAI error: {e}"

def call_gemini(prompt):
    try:
        res = requests.post(
            f"https://generativelanguage.googleapis.com/v1beta2/models/text-bison-001:generateText?key={GEMINI_API_KEY}",
            headers={"Content-Type": "application/json"},
            json={"prompt": {"text": prompt}, "temperature": 0.7}
        )
        return res.json()["candidates"][0]["output"]
    except Exception as e:
        return f"Gemini error: {e}"

def call_deepseek(prompt):
    return "DeepSeek not integrated yet."

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Welcome! Use /ask, /model, /buy.")

async def ask(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = str(update.effective_user.id)
    prompt = " ".join(context.args)
    if not prompt:
        await update.message.reply_text("Use /ask followed by your question.")
        return

    doc_ref = db.collection("users").document(user_id)
    doc = doc_ref.get()
    now = datetime.utcnow()
    data = doc.to_dict() if doc.exists else {
        "tier": "free", "text_used": 0, "image_used": 0,
        "model": "gpt-4o-mini", "last_reset": now
    }

    data = reset_if_needed(data, doc_ref)
    limits = TIERS.get(data["tier"], TIERS["free"])

    if data["text_used"] >= limits["text_limit"]:
        await update.message.reply_text("❌ You've reached your daily limit.")
        return

    model = data.get("model", "gpt-4o-mini")
    if model == "gpt-4o-mini":
        reply = call_gpt_4o_mini(prompt)
    elif model == "gemini":
        reply = call_gemini(prompt)
    else:
        reply = call_deepseek(prompt)

    data["text_used"] += 1
    doc_ref.set(data, merge=True)
    await update.message.reply_text(reply)

async def model(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = str(update.effective_user.id)
    if not context.args:
        msg = "Available models:\n" + "\n".join([f"{k}: {v}" for k, v in AVAILABLE_MODELS.items()])
        await update.message.reply_text(msg)
        return

    choice = context.args[0]
    if choice not in AVAILABLE_MODELS:
        await update.message.reply_text("Invalid model.")
        return

    db.collection("users").document(user_id).set({"model": choice}, merge=True)
    await update.message.reply_text(f"Model set to {AVAILABLE_MODELS[choice]}")

async def buy(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_invoice(
        title="Premium Plan",
        description="Get access to premium AI tools",
        payload="premium_plan_20",
        provider_token=PROVIDER_TOKEN,
        currency="XTR",
        prices=[LabeledPrice("Premium Plan ⭐20", 20)],
        start_parameter="purchase-premium",
        photo_url="https://telegra.ph/file/4eb39db6d71c79245169a.jpg",
        photo_size=512,
        photo_width=512,
        photo_height=512
    )

async def precheckout_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.pre_checkout_query.answer(ok=True)

async def successful_payment_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = str(update.effective_user.id)
    db.collection("users").document(user_id).set({"tier": "premium"}, merge=True)
    await update.message.reply_text("✅ Premium activated!")

async def main():
    app = ApplicationBuilder().token(TELEGRAM_BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("ask", ask))
    app.add_handler(CommandHandler("model", model))
    app.add_handler(CommandHandler("buy", buy))
    app.add_handler(PreCheckoutQueryHandler(precheckout_callback))
    app.add_handler(MessageHandler(filters.SUCCESSFUL_PAYMENT, successful_payment_callback))
    await app.run_polling()

if __name__ == "__main__":
    import asyncio
    asyncio.run(main())
