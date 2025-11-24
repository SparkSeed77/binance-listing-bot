import os, json, time, re, asyncio, requests
from bs4 import BeautifulSoup
from telegram import Bot
from requests.exceptions import RequestException

TELEGRAM_BOT_TOKEN = os.getenv("TG_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TG_CHAT_ID")
POLL_SECONDS = int(os.getenv("POLL_SECONDS", "300"))
DEBUG = os.getenv("DEBUG", "1") == "1"
STATE_FILE = "state.json"

BINANCE_HTML_URL = "https://www.binance.com/en/support/announcement/list/48"

FEEDS = [
    {"name": "listedon", "url": "https://listedon.org/en/exchange/binance"},
    {"name": "coinlistingdate", "url": "https://coinlistingdate.com/exchange/binance"},
    {"name": "binance_html", "url": BINANCE_HTML_URL},
]

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/125.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "en-US,en;q=0.9",
    "Connection": "keep-alive",
}

session = requests.Session()
session.headers.update(HEADERS)
bot = Bot(token=TELEGRAM_BOT_TOKEN)

def load_state():
    if os.path.exists(STATE_FILE):
        try:
            with open(STATE_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    return {"last_id": None}

def save_state(state):
    with open(STATE_FILE, "w", encoding="utf-8") as f:
        json.dump(state, f, ensure_ascii=False)

def dedupe(items):
    uniq = {}
    for it in items:
        uniq[it["id"]] = it
    return list(uniq.values())[:20]

def parse_listedon(html):
    soup = BeautifulSoup(html, "html.parser")
    items = []
    for row in soup.select("table tr"):
        cols = [c.get_text(" ", strip=True) for c in row.select("td,th")]
        if len(cols) >= 2:
            joined = " | ".join(cols)
            if re.search(r"(new trading pair|listed on binance|binance will list)", joined, re.I):
                title = joined.strip()
                items.append({
                    "id": title,
                    "title": title,
                    "date": cols[0] if cols else "",
                    "url": "https://listedon.org/en/exchange/binance",
                })
    return dedupe(items)

def parse_coinlistingdate(html):
    soup = BeautifulSoup(html, "html.parser")
    items = []
    for el in soup.select("a, h2, h3, li, div"):
        t = el.get_text(" ", strip=True)
        if t and re.search(r"(binance will list|listed on binance|binance listing|new listing on binance)", t, re.I):
            items.append({
                "id": t,
                "title": t,
                "date": "",
                "url": "https://coinlistingdate.com/exchange/binance",
            })
    return dedupe(items)

def parse_binance_html(html):
    soup = BeautifulSoup(html, "html.parser")
    items = []
    for a in soup.select('a[href*="/en/support/announcement/"]'):
        title = a.get_text(strip=True)
        href = a.get("href")
        if title and href:
            url = "https://www.binance.com" + href if href.startswith("/") else href
            items.append({"id": url, "title": title, "date": "", "url": url})
    return dedupe(items)

def fetch_from_source(src, timeout=40):
    r = session.get(src["url"], timeout=timeout)
    r.raise_for_status()
    html = r.text
    if src["name"] == "listedon": return parse_listedon(html)
    if src["name"] == "coinlistingdate": return parse_coinlistingdate(html)
    if src["name"] == "binance_html": return parse_binance_html(html)
    return []

def fetch_items():
    for src in FEEDS:
        for attempt in range(2):
            try:
                items = fetch_from_source(src)
                if items:
                    if DEBUG: print(f"Using source: {src['name']} ({len(items)} items)")
                    return items
            except RequestException as e:
                if DEBUG: print(f"Source failed: {src['name']} attempt {attempt+1} -> {e}")
                time.sleep(2 + attempt)
    return []

async def send_item(it):
    msg = (
        "🆕 Binance Listing News\n\n"
        f"{it.get('title','')}\n"
        f"{it.get('date','')}\n"
        f"{it.get('url','')}"
    )
    await bot.send_message(chat_id=TELEGRAM_CHAT_ID, text=msg, disable_web_page_preview=False)

async def main_loop_async():
    state = load_state()
    last_id = state.get("last_id")

    start_items = fetch_items()
    if DEBUG:
        print(f"Startup fetch: {len(start_items)} items")
        for it in start_items[:3]:
            print("-", it["title"])

    while True:
        items = fetch_items()
        if items:
            new_items = []
            for it in items:
                if it["id"] == last_id:
                    break
                new_items.append(it)

            for it in reversed(new_items):
                await send_item(it)

            state["last_id"] = items[0]["id"]
            save_state(state)

        await asyncio.sleep(POLL_SECONDS)

if __name__ == "__main__":
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        raise RuntimeError("Please set TG_TOKEN and TG_CHAT_ID env vars.")
    asyncio.run(main_loop_async())
