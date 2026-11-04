
                header = "🚨 <b>[CÓ LINK ĐĂNG KÝ CTXH MỚI]</b> 🚨\n" if (is_ctxh or has_form) else "📢 <b>BÀI VIẾT MỚI TỪ CTSV HUIT</b>\n"
                
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

                if is_ctxh or has_form:
                    await asyncio.sleep(1.5)
                    alert_1 = "🚨🚨🚨 <b>BÁO ĐỘNG ĐỎ: CÓ FORM CTXH MỚI!</b> 🚨🚨🚨\n👉 Bấm vào form điền ngay kẻo full slot bạn ơi!"
                    send_telegram(alert_1)
                    
                    await asyncio.sleep(1.5)
                    alert_2 = "⚡⚡⚡ <b>ĐỪNG BỎ LỠ!</b> Kiểm tra form đăng ký ngay lập tức! ⚡⚡⚡"
                    send_telegram(alert_2)

            except Exception as art_err:
                print(f"[Lỗi đọc bài]: {art_err}")
                raise

        # 2. Fallback: chỉ dùng nếu không lấy được URL từ container.
        # Không nhầm "tất cả bài đã xem" với "không bóc tách được".
        if not processed_ids:
            page_links = await page.locator("a[href]").evaluate_all(
                "elements => elements.map(e => e.href)"
            )
            fallback_found = False
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
                    "📢 <b>BÀI VIẾT MỚI TỪ CTSV HUIT</b>\n\n"
                    f'<a href="{html.escape(post_url, quote=True)}">Xem bài viết gốc trên Facebook</a>'
                )
                kb = {"inline_keyboard": [[{"text": "📖 Xem bài viết Facebook", "url": post_url}]]}
                print(f"[BÀI MỚI FALLBACK]: {post_url}")
                if not send_telegram(msg, reply_markup=kb):
                    raise RuntimeError(f"Gửi Telegram fallback thất bại: {post_url}")
                seen_posts.add(post_id)
                new_found += 1
                save_seen_posts(seen_posts)
                # Giữ giới hạn 1 bài trong fallback như bản gốc.
                break
            if not fallback_found:
                raise RuntimeError("Không tìm thấy khối bài viết hoặc link bài đăng; có thể Facebook chặn tải nội dung")

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
