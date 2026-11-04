import asyncio
import html
import json
import os
import re
import sys
import urllib.parse
import urllib.request
from datetime import datetime
from playwright.async_api import async_playwright

sys.stdout.reconfigure(encoding='utf-8')

# Đường dẫn file
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
ENV_FILE = os.path.join(BASE_DIR, ".env")
DB_FILE = os.path.join(BASE_DIR, "seen_posts.json")

def load_config():
    config = {
        "TELEGRAM_BOT_TOKEN": os.environ.get("TELEGRAM_BOT_TOKEN", ""),
        "TELEGRAM_CHAT_ID": os.environ.get("TELEGRAM_CHAT_ID", ""),
        "CHECK_INTERVAL_SECONDS": int(os.environ.get("CHECK_INTERVAL_SECONDS", 120)),
        "PAGE_URL": os.environ.get("PAGE_URL", "https://www.facebook.com/ctsv.huit")
    }
    if os.path.exists(ENV_FILE):
        with open(ENV_FILE, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    key, val = line.split("=", 1)
                    if not config.get(key.strip()):
                        config[key.strip()] = val.strip()
    return config

CONFIG = load_config()

def send_telegram(text: str, reply_markup=None):
    token = CONFIG["TELEGRAM_BOT_TOKEN"]
    chat_id = CONFIG["TELEGRAM_CHAT_ID"]
    if not token or not chat_id:
        print("[LỖI] Thiếu TELEGRAM_BOT_TOKEN hoặc TELEGRAM_CHAT_ID trong .env")
        return False

    url = f"https://api.telegram.org/bot{token}/sendMessage"
    payload = {
        "chat_id": chat_id,
        "text": text,
        "parse_mode": "HTML",
        "disable_web_page_preview": False
    }
    if reply_markup:
        payload["reply_markup"] = json.dumps(reply_markup)

    try:
        data = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(url, data=data, headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=10) as resp:
            return resp.status == 200
    except Exception as e:
        print(f"[LỖI GỬI TELEGRAM]: {e}")
        return False

def load_seen_posts():
    if os.path.exists(DB_FILE):
        try:
            with open(DB_FILE, "r", encoding="utf-8") as f:
                return set(json.load(f))
        except Exception:
            return set()
    return set()

def save_seen_posts(seen: set):
    # Không cắt ngẫu nhiên các ID: tránh gửi lại bài cũ khi set đổi thứ tự.
    post_list = sorted(seen)
    with open(DB_FILE, "w", encoding="utf-8") as f:
        json.dump(post_list, f, ensure_ascii=False, indent=2)

def extract_forms(text: str):
    """Tìm tất cả các link form (Google Form, MS Form, v.v.) trong nội dung"""
    patterns = [
        r'https?://(?:forms\.gle|docs\.google\.com/forms|forms\.office\.com|goo\.gl/forms)[^\s\)\"\'>]+',
        r'https?://[^\s\)\"\'>]+(?:form|dang-ky|dangky)[^\s\)\"\'>]*'
    ]
    forms = []
    for pat in patterns:
        matches = re.findall(pat, text, re.IGNORECASE)
        for m in matches:
            clean = m.rstrip(".,;!?")
            if clean not in forms:
                forms.append(clean)
    return forms

def is_post_link(link: str) -> bool:
    try:
        parsed = urllib.parse.urlparse(link)
