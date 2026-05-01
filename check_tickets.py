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

# Dates 8 May to 17 May
DATE_PATTERN = re.compile(
    r'\b(0?[89]|1[0-7])\s+May\b|\bMay\s+(0?[89]|1[0-7])\b',
    re.IGNORECASE
)
SOLD_OUT_WORDS = ["sold out", "complet", "unavailable", "épuisé", "indisponible"]


async def send_telegram(message: str):
    api_url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    async with httpx.AsyncClient() as client:
        resp = await client.post(api_url, json={
            "chat_id": CHAT_ID,
            "text": message,
            "parse_mode": "HTML",
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

        print(f"Loading page...")
        await page.goto(URL, wait_until="networkidle", timeout=60000)
        await page.wait_for_timeout(3000)
        # Scroll to trigger lazy-loaded calendar
        await page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
        await page.wait_for_timeout(2000)

        available = []

        # Try known Opera de Paris selectors first
        candidate_selectors = [
            ".c-calendar-list__item",
            ".calendar-list__item",
            "[class*='calendar'] li",
            "[class*='session-item']",
            "[class*='performance-item']",
            "[class*='event-item']",
            "li[data-date]",
        ]

        items = []
        for sel in candidate_selectors:
            found = await page.query_selector_all(sel)
            if found:
                print(f"Selector '{sel}' → {len(found)} items")
                items = found
                break

        # Dump raw page text to see actual structure and date format
        full_text = await page.inner_text("body")
        print("=== PAGE TEXT (first 5000 chars) ===")
        print(full_text[:5000])
        print("=== END ===")

        # Scan for any lines containing "May" or "mai" near our dates
        lines = full_text.splitlines()
        for i, line in enumerate(lines):
            if re.search(r'\b(mai|may)\b', line, re.IGNORECASE):
                ctx = "\n".join(lines[max(0, i - 1): i + 3])
                print(f"DATE LINE: {ctx!r}")

        await browser.close()
        return available


async def main():
    now = datetime.utcnow().strftime("%Y-%m-%d %H:%M UTC")
    print(f"[{now}] Checking tickets…")
    try:
        available = await check_tickets()
        if available:
            shows = "\n\n".join(f"• {s}" for s in available[:5])
            msg = (
                "🎭 <b>Билеты на Даму с камелиями!</b>\n\n"
                f"Свободные даты 8–17 мая: <b>{len(available)}</b>\n\n"
                f"{shows}\n\n"
                f'🔗 <a href="{URL}">Купить билеты</a>'
            )
            await send_telegram(msg)
            print(f"✅ Alert sent — {len(available)} show(s) available")
        else:
            print("❌ No tickets for May 8–17")
    except Exception as e:
        print(f"ERROR: {e}")
        try:
            await send_telegram(f"⚠️ Ошибка при проверке билетов Оперы Гарнье: {e}")
        except Exception:
            pass
        raise


if __name__ == "__main__":
    asyncio.run(main())
