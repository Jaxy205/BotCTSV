
"""Theo doi bai dang cong khai cua fanpage CTSV HUIT.

Moi bai moi -> 1 tin Telegram. Noi dung co 'CTXH' / 'cong tac xa hoi'
-> canh bao. Link form neu co -> nut mo nhanh.

Luu y: Facebook co the gioi han so bai hien thi khi khong dang nhap;
script khong the dam bao phat hien cac bai Facebook khong tai ve.
"""

import asyncio
import html
import json
import os
import re
import sys
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime
from pathlib import Path

from playwright.async_api import async_playwright

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

BASE_DIR = Path(__file__).resolve().parent
DB_FILE = BASE_DIR / "seen_posts.json"
DEBUG_DIR = BASE_DIR / "debug"


def load_config():
    config = {
        "TELEGRAM_BOT_TOKEN": os.environ.get("TELEGRAM_BOT_TOKEN", ""),
        "TELEGRAM_CHAT_ID": os.environ.get("TELEGRAM_CHAT_ID", ""),
        "PAGE_URL": os.environ.get("PAGE_URL", "https://www.facebook.com/ctsv.huit"),
        "CHECK_INTERVAL_SECONDS": os.environ.get("CHECK_INTERVAL_SECONDS", "120"),
    }
    env_file = BASE_DIR / ".env"
    if env_file.exists():
        for line in env_file.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                key, value = line.split("=", 1)
                if key.strip() in config and not os.environ.get(key.strip()):
                    config[key.strip()] = value.strip().strip('"').strip("'")
    return config


CONFIG = load_config()


def load_seen_posts():
    if not DB_FILE.exists():
        return set()
    try:
        raw = json.loads(DB_FILE.read_text(encoding="utf-8"))
        if not isinstance(raw, list) or any(not isinstance(x, str) for x in raw):
            raise ValueError("seen_posts.json phai la mang chuoi ID")
        return set(raw)
    except (ValueError, OSError) as exc:
        raise RuntimeError(f"Khong doc duoc seen_posts.json: {exc}") from exc


def save_seen_posts(seen):
    """Ghi atomically de tranh JSON bi cat neu job dung giua chung."""
    tmp = DB_FILE.with_name(DB_FILE.name + ".tmp")
    tmp.write_text(
        json.dumps(sorted(seen), ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    os.replace(tmp, DB_FILE)


def normalize_post_url(link):
    """Tra ve (post_id, url) cho link bai CTSV; nguoc lai None."""
    if not isinstance(link, str):
        return None
    try:
        parsed = urllib.parse.urlsplit(link)
        host = (parsed.hostname or "").lower()
        if parsed.scheme not in ("http", "https") or host not in (
            "facebook.com", "www.facebook.com", "m.facebook.com"
        ):
            return None

        path = parsed.path.rstrip("/")
        path_lower = path.lower()
        prefix = "/ctsv.huit/posts/"

        if path_lower.startswith(prefix):
            post_id = path[len(prefix):].split("/", 1)[0]
            if not post_id:
                return None
            url = "https://www.facebook.com/ctsv.huit/posts/" + urllib.parse.quote(
                urllib.parse.unquote(post_id), safe=""
            )
            clean_id = urllib.parse.unquote(post_id)
            return (
                clean_id if clean_id.startswith("pfbid") else "fbid:" + clean_id
            ), url

        if path_lower in ("/permalink.php", "/story.php"):
            query = urllib.parse.parse_qs(parsed.query)
            story_id = query.get("story_fbid", [""])[0]
            if not story_id:
                return None

            q = {"story_fbid": story_id}
            if query.get("id", [""])[0]:
                q["id"] = query["id"][0]

            url = (
                "https://www.facebook.com"
                + path_lower
                + "?"
                + urllib.parse.urlencode(q)
            )
            post_id = story_id if story_id.startswith("pfbid") else "fbid:" + story_id
            return post_id, url

    except (ValueError, TypeError):
        return None
    return None


def is_ctxh(text):
    return bool(
        re.search(
            r"(?<!\w)ctxh(?!\w)|công\s+tác\s+xã\s+hội",
            text,
            flags=re.IGNORECASE,
        )
    )


def extract_forms(text, links=()):
    pattern = r"https?://[^\s\"'<>\\)]+"
    candidates = re.findall(pattern, text) + list(links)
    out = []

    for value in candidates:
        url = str(value).rstrip(".,;!?)]}")

        try:
            parsed = urllib.parse.urlsplit(url)
            host = (parsed.hostname or "").lower()

            if host == "l.facebook.com":
                target = urllib.parse.parse_qs(parsed.query).get("u", [""])[0]
                if not target:
                    continue
                url = target
                parsed = urllib.parse.urlsplit(url)
                host = (parsed.hostname or "").lower()

        except ValueError:
            continue

        if parsed.scheme not in ("http", "https") or not host:
            continue

        is_form = (
            host == "forms.gle"
            or host in ("forms.office.com", "forms.microsoft.com")
            or (host == "docs.google.com" and parsed.path.startswith("/forms/"))
            or (
                host not in (
                    "facebook.com", "www.facebook.com", "m.facebook.com"
                )
                and any(
                    s in url.lower()
                    for s in ("/form", "dang-ky", "dangky")
                )
            )
        )

        if is_form and url not in out:
            out.append(url)

    return out[:5]


def send_telegram(message, keyboard=None):
    token = CONFIG["TELEGRAM_BOT_TOKEN"]
    chat_id = CONFIG["TELEGRAM_CHAT_ID"]

    if not token or not chat_id:
        raise RuntimeError(
            "Thieu TELEGRAM_BOT_TOKEN hoac TELEGRAM_CHAT_ID"
        )

    payload = {
        "chat_id": chat_id,
        "text": message,
        "parse_mode": "HTML",
        "disable_web_page_preview": False,
    }

    if keyboard:
        payload["reply_markup"] = keyboard

    req = urllib.request.Request(
        f"https://api.telegram.org/bot{token}/sendMessage",
        data=json.dumps(
            payload, ensure_ascii=False
        ).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )

    try:
        with urllib.request.urlopen(req, timeout=15) as response:
            result = json.load(response)
            return response.status == 200 and result.get("ok") is True

    except urllib.error.HTTPError as exc:
        print(f"[TELEGRAM] HTTP error {exc.code}")
        return False

    except (urllib.error.URLError, ValueError, OSError) as exc:
        print(f"[TELEGRAM] Loi ket noi: {type(exc).__name__}")
        return False


def make_message(post):
    text = post["text"].strip()
    alt_text = post.get("alt", "")
    combined = text + "\n" + alt_text

    ctxh = is_ctxh(combined)
    forms = extract_forms(combined, post["links"])

    title = (
        "🚨 <b>BÀI MỚI CÓ CTXH – KIỂM TRA NGAY</b>"
        if ctxh
        else "📢 <b>BÀI MỚI TỪ CTSV HUIT</b>"
    )

    parts = [title]

    if ctxh:
        parts.append("⚠️ Phát hiện từ khóa CTXH / Công tác xã hội.")

    if text:
        preview = text[:700] + ("…" if len(text) > 700 else "")
        parts.append("📝 " + html.escape(preview))
    else:
        parts.append(
            "⚠️ Chưa trích xuất được nội dung chữ của bài đăng."
        )

    if forms:
        parts.append(
            "📝 <b>Link form:</b> " + html.escape(forms[0])
        )

    parts.append(
        '<a href="'
        + html.escape(post["url"], quote=True)
        + '">Xem bài viết Facebook</a>'
    )

    buttons = []

    if forms:
        buttons.append([
            {"text": "📝 Mở form đăng ký", "url": forms[0]}
        ])

    buttons.append([
        {"text": "📖 Xem bài Facebook", "url": post["url"]}
    ])

    return "\n\n".join(parts), {"inline_keyboard": buttons}


EXTRACT_JS = r"""
anchors => anchors.filter(a => /\/posts\/|permalink\.php|story\.php/i.test(a.href)).map(a => {
    const card = a.closest('div[role="article"], div[role="feed"] > div, [data-pagelet*="FeedUnit"]');
    return {
        url: a.href,
        text: card ? (card.innerText || '').slice(0, 6000) : '',
        links: card ? Array.from(card.querySelectorAll('a[href]')).map(x => x.href).slice(0, 60) : [],
        alt: card ? Array.from(card.querySelectorAll('img[alt]')).map(x => x.alt || '').join(' ').slice(0, 1200) : ''
    };
})
"""


async def collect_posts(page):
    posts = {}

    for round_index in range(3):
        await page.wait_for_timeout(
            1800 if round_index == 0 else 1600
        )

        raw = await page.locator("a[href]").evaluate_all(EXTRACT_JS)

        for item in raw:
            normalized = normalize_post_url(item.get("url", ""))

            if not normalized:
                continue

            post_id, url = normalized

            candidate = {
                "id": post_id,
                "url": url,
                "text": item.get("text") or "",
                "alt": item.get("alt") or "",
                "links": item.get("links") or [],
            }

            current = posts.get(post_id)

            if not current:
                posts[post_id] = candidate
            else:
                if len(candidate["text"]) > len(current["text"]):
                    current["text"] = candidate["text"]
                    current["alt"] = candidate["alt"]

                current["links"] = list(
                    dict.fromkeys(
                        current["links"] + candidate["links"]
                    )
                )

        print(
            f"[DEBUG] Luot {round_index + 1}: "
            f"{len(raw)} link nghi la bai, "
            f"{len(posts)} ID hop le"
        )

        if round_index < 2:
            await page.evaluate(
                "window.scrollBy(0, Math.max(700, window.innerHeight * 0.8))"
            )

    return posts


async def save_debug_image(page):
    DEBUG_DIR.mkdir(exist_ok=True)
    path = DEBUG_DIR / "facebook_page.png"

    try:
        await page.screenshot(
            path=str(path),
            full_page=True,
            timeout=12000,
        )
        print(f"[DEBUG] Da luu anh: {path}")

    except Exception as exc:
        print(
            "[DEBUG] Khong chup duoc anh: "
            f"{type(exc).__name__}"
        )


async def check_fanpage(browser, seen_posts):
    context = await browser.new_context(
        locale="vi-VN",
        viewport={"width": 1280, "height": 900},
    )

    try:
        page = await context.new_page()

        print(
            f"[{datetime.now():%H:%M:%S - %d/%m/%Y}] "
            "Dang quet CTSV HUIT"
        )

        response = await page.goto(
            CONFIG["PAGE_URL"],
            wait_until="domcontentloaded",
            timeout=35000,
        )

        print(
            f"[DEBUG] HTTP: "
            f"{response.status if response else 'unknown'} "
            f"| URL: {page.url}"
        )

        print(
            f"[DEBUG] Tieu de: {(await page.title())[:120]}"
        )

        posts = await collect_posts(page)

        await save_debug_image(page)

        print(
            f"[DEBUG] Co {len(posts)} bai co URL hop le; "
            f"DB da ghi nhan {len(seen_posts)} ID"
        )

        if not posts:
            raise RuntimeError(
                "Khong co link bai Facebook nao. "
                "Kiem tra artifact facebook-debug."
            )

        if len(posts) < 3:
            print(
                "[CANH BAO] Facebook chi tra ve rat it bai. "
                "Co the bi gioi han khi chua dang nhap."
            )

        found = 0

        for post in posts.values():
            if post["id"] in seen_posts:
                continue

            print(
                f"[MOI] {post['url']} | "
                f"noi dung {len(post['text'])} ky tu"
            )

            msg, keyboard = make_message(post)

            if not send_telegram(msg, keyboard):
                raise RuntimeError(
                    "Gui Telegram that bai; "
                    "khong danh dau bai nay da doc"
                )

            seen_posts.add(post["id"])
            save_seen_posts(seen_posts)
            found += 1

        print(
            f"[KET QUA] Nhin thay {len(posts)} bai; "
            f"gui moi {found}; "
            f"da xem {len(posts) - found}"
        )

    finally:
        await context.close()


async def main():
    seen_posts = load_seen_posts()

    once = (
        "--once" in sys.argv
        or os.environ.get("RUN_ONCE", "").lower() == "true"
    )

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)

        try:
            if once:
                await check_fanpage(browser, seen_posts)
            else:
                interval = int(CONFIG["CHECK_INTERVAL_SECONDS"])

                while True:
                    await check_fanpage(browser, seen_posts)
                    await asyncio.sleep(interval)

        finally:
            await browser.close()


if __name__ == "__main__":
    asyncio.run(main())
