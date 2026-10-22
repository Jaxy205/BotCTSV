import asyncio
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
    # ponytail: giữ tối đa 100 ID gần nhất để file luôn nhẹ
    post_list = list(seen)[-100:]
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

async def check_fanpage(browser, seen_posts):
    context = await browser.new_context(
        user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        viewport={"width": 1280, "height": 900}
    )
    page = await context.new_page()
    new_found = 0

    try:
        now_str = datetime.now().strftime("%H:%M:%S - %d/%m/%Y")
        print(f"[{now_str}] Đang quét fanpage CTSV...")
        await page.goto(CONFIG["PAGE_URL"], wait_until="networkidle", timeout=30000)
        await page.wait_for_timeout(2000)

        # Đóng popup đăng nhập Facebook nếu xuất hiện
        for selector in ['div[aria-label="Đóng"]', 'div[aria-label="Close"]', 'div[role="button"][aria-label*="Đóng"]']:
            try:
                btn = page.locator(selector).first
                if await btn.is_visible():
                    await btn.click()
                    break
            except Exception:
                pass

        # Lấy danh sách link bài viết
        links = await page.eval_on_selector_all("a[href]", "elements => elements.map(e => e.href)")
        clean_post_links = []
        for l in links:
            if ("/posts/" in l or "permalink.php" in l) and "ctsv.huit" in l:
                clean_url = l.split("?")[0]
                if clean_url not in clean_post_links:
                    clean_post_links.append(clean_url)

        # Lấy nội dung text bài viết đầu trang
        articles = await page.locator('div[role="feed"] > div, div[role="article"]').all()
        post_texts = []
        for art in articles[:5]:
            try:
                txt = await art.inner_text()
                if len(txt.strip()) > 30:
                    post_texts.append(txt.strip())
            except Exception:
                pass

        top_text = post_texts[0] if post_texts else ""
        forms_found = extract_forms(top_text)

        # Định danh bài viết bằng ID trong link hoặc hash tiêu đề
        for link in clean_post_links[:3]:
            post_id = link.rstrip("/").split("/")[-1]
            if post_id not in seen_posts:
                seen_posts.add(post_id)
                new_found += 1
                
                # Kiểm tra độ ưu tiên (CTXH / Form)
                is_ctxh = any(kw in top_text.lower() for kw in ["ctxh", "công tác xã hội", "đăng ký", "slot", "tình nguyện"])
                has_form = len(forms_found) > 0

                header = "🚨 <b>[CÓ LINK ĐĂNG KÝ CTXH MỚI]</b> 🚨\n" if (is_ctxh or has_form) else "📢 <b>BÀI VIẾT MỚI TỪ CTSV HUIT</b>\n"
                
                msg_lines = [header]
                if forms_found:
                    msg_lines.append("⚡ <b>LINK FORM ĐIỀN NGAY:</b>")
                    for f in forms_found:
                        msg_lines.append(f"👉 <a href='{f}'>{f}</a>")
                    msg_lines.append("")

                # Trích dẫn nội dung bài viết
                preview = top_text[:400] + ("..." if len(top_text) > 400 else "")
                msg_lines.append(f"📝 <b>Nội dung tóm tắt:</b>\n{preview}\n")
                msg_lines.append(f"🔗 <a href='{link}'>Xem bài viết gốc trên Facebook</a>")

                message = "\n".join(msg_lines)
                
                # Nút bấm mở link form nhanh trên Telegram
                keyboard = None
                if forms_found:
                    keyboard = {
                        "inline_keyboard": [
                            [{"text": "🚀 MỞ FORM ĐĂNG KÝ NGAY", "url": forms_found[0]}],
                            [{"text": "📖 Mở bài viết Facebook", "url": link}]
                        ]
                    }
                else:
                    keyboard = {
                        "inline_keyboard": [
                            [{"text": "📖 Xem bài viết Facebook", "url": link}]
                        ]
                    }

                print(f"[BÀI MỚI PHÁT HIỆN]: {link}")
                send_telegram(message, reply_markup=keyboard)

        if new_found > 0:
            save_seen_posts(seen_posts)
            print(f"-> Đã gửi thông báo {new_found} bài mới qua Telegram.")
        else:
            print("-> Không có bài viết mới.")

    except Exception as e:
        print(f"[LỖI QUÉT TRANG]: {e}")
    finally:
        await context.close()

async def main():
    seen_posts = load_seen_posts()
    is_once = "--once" in sys.argv or os.environ.get("RUN_ONCE") == "true"
    
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        if is_once:
            print("=== BOT CHẠY CHẾ ĐỘ 1 LẦN (GITHUB ACTIONS) ===")
            await check_fanpage(browser, seen_posts)
            await browser.close()
            return

        interval = int(CONFIG.get("CHECK_INTERVAL_SECONDS", 120))
        print(f"=== BOT THEO DÕI CTSV HUIT ĐÃ KHỞI CHẠY ===")
        print(f"Chu kỳ quét: {interval} giây/lần.")
        print("Nhấn Ctrl + C để dừng bot.")

        try:
            while True:
                await check_fanpage(browser, seen_posts)
                await asyncio.sleep(interval)
        except KeyboardInterrupt:
            print("\nĐã dừng bot.")
        finally:
            await browser.close()

if __name__ == "__main__":
    asyncio.run(main())
