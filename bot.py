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
        if (parsed.hostname or "").lower() not in ("facebook.com", "www.facebook.com", "m.facebook.com"):
            return False
        path = parsed.path.lower()
        query = urllib.parse.parse_qs(parsed.query)
        return (
            ("/ctsv.huit/posts/" in path)
            or (path.endswith("/permalink.php") and bool(query.get("story_fbid")))
            or (path.endswith("/story.php") and bool(query.get("story_fbid")))
        )
    except (ValueError, TypeError):
        return False


def get_post_id(url: str):
    if not is_post_link(url):
        return None
    parsed = urllib.parse.urlparse(url)
    query = urllib.parse.parse_qs(parsed.query)
    if query.get("story_fbid"):
        return "fbid:" + query["story_fbid"][0]
    if "/posts/" in parsed.path:
        return parsed.path.rstrip("/").split("/")[-1]
    return None


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
        response = await page.goto(CONFIG["PAGE_URL"], wait_until="domcontentloaded", timeout=35000)
        print(f"[DEBUG] HTTP status: {response.status if response else 'unknown'}")
        print(f"[DEBUG] Final URL: {page.url}")
        await page.wait_for_timeout(2000)

        # Xử lý các loại popup: Đăng nhập, Cookie consent trên server nước ngoài
        popup_selectors = [
            'div[aria-label="Đóng"]', 'div[aria-label="Close"]', 'div[role="button"][aria-label*="Đóng"]',
            'button[data-cookiebanner="accept_button"]', 'button:has-text("Allow all cookies")',
            'button:has-text("Decline optional cookies")', 'button:has-text("Chấp nhận tất cả")',
            'div[aria-label="Allow all cookies"]', 'div[aria-label="Decline optional cookies"]',
            '[aria-label="Decline optional cookies"]', '[data-testid="cookie-policy-manage-dialog-accept-button"]'
        ]
        for selector in popup_selectors:
            try:
                btn = page.locator(selector).first
                if await btn.is_visible():
                    await btn.click()
                    await page.wait_for_timeout(1000)
                    break
            except Exception:
                pass

        # Cuộn để Facebook tải thêm nội dung rồi chờ render.
        await page.evaluate("window.scrollBy(0, 1000)")
        await page.wait_for_timeout(2500)

        # Luôn tạo ảnh chẩn đoán, kể cả khi workflow thành công.
        debug_dir = os.path.join(BASE_DIR, "debug")
        os.makedirs(debug_dir, exist_ok=True)
        screenshot_path = os.path.join(debug_dir, "facebook_page.png")
        try:
            await page.screenshot(
                path=screenshot_path,
                full_page=True,
                timeout=15000,
                animations="disabled",
            )
            print(f"[DEBUG] Đã lưu ảnh Facebook: {screenshot_path}")
        except Exception as screenshot_error:
            print(f"[DEBUG] Không thể lưu ảnh Facebook: {screenshot_error}")

        # 1. Tìm theo từng khối bài viết (Feed item)
        article_locator = page.locator('div[role="feed"] > div, div[role="article"]')
        article_count = await article_locator.count()
        post_link_count = await page.locator('a[href*="/posts/"]').count()
        print(f"[DEBUG] Số khối bài viết: {article_count}")
        print(f"[DEBUG] Số link /posts/: {post_link_count}")
        print(f"[DEBUG] Page title: {(await page.title())[:160]}")
        articles = await article_locator.all()
        processed_ids = set()
        recognized_posts = False

        for art in articles[:6]:
            try:
                art_text = (await art.inner_text()).strip()
                if len(art_text) < 30:
                    continue

                # Lấy link bài viết bên trong chính khối này
                art_links = await art.locator("a[href]").evaluate_all(
                    "elements => elements.map(e => e.href)"
                )
                post_url = None
                for l in art_links:
                    if is_post_link(l):
                        # Giữ query của permalink.php/story_fbid: bỏ query sẽ hỏng link.
                        post_url = l.split("#", 1)[0]
                        break

                if not post_url:
                    continue

                post_id = get_post_id(post_url)
                if not post_id:
                    continue
                recognized_posts = True
                if post_id in seen_posts or post_id in processed_ids:
                    continue

                processed_ids.add(post_id)

                forms_found = extract_forms(art_text)
                is_ctxh = bool(re.search(r"(?<!\w)ctxh(?!\w)|công\s+tác\s+xã\s+hội", art_text, re.IGNORECASE))
                has_form = len(forms_found) > 0

                header = "🚨 <b>BÀI MỚI LIÊN QUAN CTXH</b> 🚨\n" if is_ctxh else "📢 <b>BÀI VIẾT MỚI TỪ CTSV HUIT</b>\n"
                
                msg_lines = [header]
                if forms_found:
                    msg_lines.append("⚡ <b>LINK FORM ĐIỀN NGAY:</b>")
                    for f in forms_found:
                        msg_lines.append(f'👉 <a href="{html.escape(f, quote=True)}">{html.escape(f)}</a>')
                    msg_lines.append("")

                preview = art_text[:400] + ("..." if len(art_text) > 400 else "")
                msg_lines.append(f"📝 <b>Nội dung tóm tắt:</b>\n{html.escape(preview)}\n")
                msg_lines.append(f'🔗 <a href="{html.escape(post_url, quote=True)}">Xem bài viết gốc trên Facebook</a>')

                message = "\n".join(msg_lines)
                keyboard = {
                    "inline_keyboard": [
                        [{"text": "🚀 MỞ FORM ĐĂNG KÝ NGAY", "url": forms_found[0]}],
                        [{"text": "📖 Xem bài viết Facebook", "url": post_url}]
                    ]
                } if forms_found else {
                    "inline_keyboard": [
                        [{"text": "📖 Xem bài viết Facebook", "url": post_url}]
                    ]
                }

                print(f"[BÀI MỚI PHÁT HIỆN]: {post_url}")
                if not send_telegram(message, reply_markup=keyboard):
                    raise RuntimeError(f"Gửi Telegram thất bại: {post_url}")
                seen_posts.add(post_id)
                new_found += 1
                save_seen_posts(seen_posts)


            except Exception as art_err:
                print(f"[Lỗi đọc bài]: {art_err}")
                raise

        # 2. Fallback: chỉ dùng nếu không lấy được URL từ container.
        # Không nhầm "tất cả bài đã xem" với "không bóc tách được".
        if not recognized_posts:
            print("[DEBUG] Chưa nhận diện bài từ khối; đang thử fallback.")
            page_links = await page.locator("a[href]").evaluate_all(
                "elements => elements.map(e => e.href)"
            )
            fallback_found = False
            print(f"[DEBUG] Tổng số liên kết trên trang: {len(page_links)}")
            for link in page_links:
                if not is_post_link(link):
                    continue
                post_url = link.split("#", 1)[0]
                post_id = get_post_id(post_url)
                if not post_id:
                    continue
                fallback_found = True
                if post_id in seen_posts:
                    continue
                msg = (
                    "📢 <b>BÀI VIẾT MỚI TỪ CTSV HUIT</b>\n"
                    "⚠️ Chưa lấy được nội dung để xác định CTXH.\n\n"
                    f'<a href="{html.escape(post_url, quote=True)}">Xem bài viết gốc trên Facebook</a>'
                )
                kb = {"inline_keyboard": [[{"text": "📖 Xem bài viết Facebook", "url": post_url}]]}
                print(f"[BÀI MỚI FALLBACK]: {post_url}")
                if not send_telegram(msg, reply_markup=kb):
                    raise RuntimeError(f"Gửi Telegram fallback thất bại: {post_url}")
                seen_posts.add(post_id)
                new_found += 1
                save_seen_posts(seen_posts)
                # Tiếp tục để không bỏ sót các link bài mới trong fallback.
            if not fallback_found:
                # Save a diagnostic screenshot; do not store secrets or full HTML.
                debug_dir = os.path.join(BASE_DIR, "debug")
                os.makedirs(debug_dir, exist_ok=True)
                screenshot_path = os.path.join(debug_dir, "facebook_page.png")
                try:
                    await page.screenshot(path=screenshot_path, full_page=False, timeout=10000)
                    print(f"[DEBUG] Đã chụp trang vào: {screenshot_path}")
                except Exception as shot_err:
                    print(f"[DEBUG] Không chụp được ảnh: {shot_err}")
                # Page text snippet is diagnostic only, not used as evidence of a post.
                body_sample = await page.locator("body").inner_text(timeout=5000)
                print(f"[DEBUG] Page body (first 350 chars): {body_sample[:350]!r}")
                raise RuntimeError("Trang Facebook không chứa bài theo các bộ chọn hiện có; xem debug/facebook_page.png để xác định nguyên nhân")

        print(f"[DEBUG] Đã nhận diện bài từ khối: {recognized_posts}; số thông báo mới: {new_found}")
        if new_found > 0:
            save_seen_posts(seen_posts)
            print(f"-> Đã gửi thành công {new_found} bài mới qua Telegram.")
        else:
            print("-> Không có bài viết mới.")

    except Exception as e:
        print(f"[LỖI QUÉT TRANG]: {e}")
        raise  # Báo workflow thất bại, thay vì hiển thị màu xanh giả.
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
