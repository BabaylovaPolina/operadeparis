#!/usr/bin/env python3
import asyncio
import os
import re
import httpx
from playwright.async_api import async_playwright
from datetime import datetime

TELEGRAM_TOKEN = os.environ["TELEGRAM_TOKEN"]
CHAT_ID = os.environ["CHAT_ID"]

SHOWS = [
    {
        "name": "Дама с камелиями",
        "url": "https://www.operadeparis.fr/en/season-25-26/ballet/la-dame-aux-camelias",
        "days": r'^(0?[89]|1[0-7])$',  # May 8–17
    },
]


async def send_telegram(message: str):
    api_url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    async with httpx.AsyncClient() as client:
        resp = await client.post(api_url, json={
            "chat_id": CHAT_ID,
            "text": message,
            "disable_web_page_preview": True,
        })
        resp.raise_for_status()


async def check_show(page, show: dict) -> list[str]:
    await page.goto(show["url"], wait_until="networkidle", timeout=60000)
    await page.wait_for_timeout(3000)
    await page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
    await page.wait_for_timeout(2000)

    btn = await page.query_selector(
        "a:has-text('SEE AVAILABILITY'), button:has-text('SEE AVAILABILITY'),"
        "a:has-text('VIEW PRICES AND BOOK'), button:has-text('VIEW PRICES AND BOOK')"
    )
    if btn:
        await btn.click()
        await page.wait_for_timeout(4000)
    else:
        await page.evaluate("const el = document.querySelector('#calendar'); if(el) el.scrollIntoView()")
        await page.wait_for_timeout(3000)

    lines = (await page.inner_text("body")).splitlines()

    available = []
    for i, line in enumerate(lines):
        if not re.match(show["days"], line.strip()):
            continue
        lookahead = " ".join(lines[i:i + 6])
        if "May" not in lookahead:
            continue
        block_lines = lines[i:i + 25]
        block = "\n".join(block_lines)

        # Print HTML for first date to understand category structure
        if line.strip() == "08":
            print(f"=== HTML for 08 May (structure sample) ===")
            els = await page.query_selector_all("[class*='session'], [class*='performance'], li[class*='item']")
            for el in els:
                el_text = await el.inner_text()
                if "08" in el_text and "May" in el_text and "7:30" in el_text:
                    print((await el.inner_html())[:3000])
                    break
            print("=== END ===")

        if "sold out" not in block.lower():
            status = "последние места" if "last seats" in block.lower() else "есть билеты"
            available.append((line.strip(), status))

    return available


async def main():
    now = datetime.utcnow().strftime("%Y-%m-%d %H:%M UTC")
    print(f"[{now}] Checking tickets…")
    try:
        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=True)
            context = await browser.new_context(
                user_agent=(
                    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/124.0.0.0 Safari/537.36"
                ),
                locale="en-US",
            )
            page = await context.new_page()

            results = {}
            for show in SHOWS:
                available = await check_show(page, show)
                results[show["name"]] = (available, show["url"])
                print(f"{show['name']}: {[(d, c) for d, c in available] if available else 'sold out'}")

            await browser.close()

        lines = []
        any_available = False
        for name, (available, url) in results.items():
            if available:
                any_available = True
                dates_str = "\n".join(f"  {d} мая — {cats}" for d, cats in available)
                lines.append(f"🎭 {name} — есть билеты!\n{dates_str}\n{url}")
            else:
                lines.append(f"🔍 {name} — всё распродано")

        msg = "\n\n".join(lines)
        await send_telegram(msg)
        print(f"✅ Alert sent")

    except Exception as e:
        print(f"ERROR: {e}")
        try:
            await send_telegram(f"⚠️ Ошибка при проверке билетов: {e}")
        except Exception:
            pass
        raise


if __name__ == "__main__":
    asyncio.run(main())
