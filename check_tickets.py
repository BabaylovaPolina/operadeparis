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


async def check_show(page, show: dict) -> list[tuple[str, str]]:
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

    rows = await page.query_selector_all("[class*='performances__row']")
    available = []

    for row in rows:
        # Get day number
        day_el = await row.query_selector("[class*='performances__date-left'] span")
        if not day_el:
            continue
        day = (await day_el.inner_text()).strip()
        if not re.match(show["days"], day):
            continue

        # Confirm it's May
        month_els = await row.query_selector_all("[class*='performances__date-right'] span")
        months = [await el.inner_text() for el in month_els]
        if "May" not in " ".join(months):
            continue

        # Find available categories: li WITHOUT --disabled class
        avail_cats = await row.query_selector_all(
            ".component-performances__categories-li:not(.component-performances__categories-li--disabled)"
        )
        if not avail_cats:
            continue

        cats = []
        for cat in avail_cats:
            title_el = await cat.query_selector(".component-performances__categories-li-title")
            price_el = await cat.query_selector(".price")
            if title_el and price_el:
                title = (await title_el.inner_text()).strip()
                price = (await price_el.inner_text()).strip()
                cats.append(f"{title} ({price})")

        # Check status tag (Last seats, etc.)
        status = "есть билеты"
        tag_els = await row.query_selector_all("[class*='performances__tags-li']")
        for tag_el in tag_els:
            tag_text = (await tag_el.inner_text()).strip().lower()
            if "last" in tag_text:
                status = "последние места"

        cat_str = ", ".join(cats) if cats else "уточняется"
        available.append((day, f"{status} — {cat_str}"))

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
                print(f"{show['name']}: {available or 'sold out'}")

            await browser.close()

        msg_lines = []
        for name, (available, url) in results.items():
            if available:
                dates_str = "\n".join(f"  {d} мая — {info}" for d, info in available)
                msg_lines.append(f"🎭 {name} — есть билеты!\n{dates_str}\n{url}")
            else:
                msg_lines.append(f"🔍 {name} — всё распродано")

        await send_telegram("\n\n".join(msg_lines))
        print("✅ Alert sent")

    except Exception as e:
        print(f"ERROR: {e}")
        try:
            await send_telegram(f"⚠️ Ошибка при проверке билетов: {e}")
        except Exception:
            pass
        raise


if __name__ == "__main__":
    asyncio.run(main())
