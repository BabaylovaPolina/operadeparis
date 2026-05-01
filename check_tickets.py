#!/usr/bin/env python3
import asyncio
import os
import re
import httpx
from playwright.async_api import async_playwright
from datetime import datetime

TELEGRAM_TOKEN = os.environ["TELEGRAM_TOKEN"]
CHAT_ID = os.environ["CHAT_ID"]
URL = "https://www.operadeparis.fr/en/season-25-26/ballet/la-dame-aux-camelias"


async def send_telegram(message: str):
    api_url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    async with httpx.AsyncClient() as client:
        resp = await client.post(api_url, json={
            "chat_id": CHAT_ID,
            "text": message,
            "disable_web_page_preview": True,
        })
        resp.raise_for_status()


async def check_tickets() -> list[str]:
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

        await page.goto(URL, wait_until="networkidle", timeout=60000)
        await page.wait_for_timeout(3000)
        await page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
        await page.wait_for_timeout(2000)

        # Expand the per-date calendar
        btn = await page.query_selector("a:has-text('SEE AVAILABILITY'), button:has-text('SEE AVAILABILITY')")
        if btn:
            await btn.click()
            await page.wait_for_timeout(4000)
        else:
            await page.evaluate("const el = document.querySelector('#calendar'); if(el) el.scrollIntoView()")
            await page.wait_for_timeout(3000)

        # Calendar format: day number alone on a line, then day name, then "May"
        # e.g. "08\n\nFriday\nMay\n\n7:30 pm\n\nSold out\n..."
        lines = (await page.inner_text("body")).splitlines()
        await browser.close()

        available = []
        for i, line in enumerate(lines):
            if not re.match(r'^(0?[89]|1[0-7])$', line.strip()):
                continue
            lookahead = " ".join(lines[i:i + 6])
            if "May" not in lookahead:
                continue
            block = "\n".join(lines[i:i + 15])
            day = line.strip()
            if "sold out" not in block.lower():
                available.append(f"{day} May\n{block.strip()[:200]}")

        return available


async def main():
    now = datetime.utcnow().strftime("%Y-%m-%d %H:%M UTC")
    print(f"[{now}] Checking tickets…")
    try:
        available = await check_tickets()
        if available:
            shows = "\n\n".join(f"• {s}" for s in available[:5])
            msg = f"🎭 Билеты на Даму с камелиями!\n\nСвободные даты 8–17 мая: {len(available)}\n\n{shows}\n\n{URL}"
            await send_telegram(msg)
            print(f"✅ Alert sent — {len(available)} show(s) available")
        else:
            await send_telegram(
                f"🔍 Проверила билеты на Даму с камелиями (8–17 мая) — пока всё распродано.\n\n{URL}"
            )
            print(f"❌ No tickets for May 8–17")
    except Exception as e:
        print(f"ERROR: {e}")
        try:
            await send_telegram(f"⚠️ Ошибка при проверке билетов Оперы Гарнье: {e}")
        except Exception:
            pass
        raise


if __name__ == "__main__":
    asyncio.run(main())
