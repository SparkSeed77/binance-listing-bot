import os, json, time, re, asyncio, requests, hashlib
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
    {"name": "binance_html", "url": BINANCE_HTML_URL},  # فالو‌بک آخر
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

# ---------- الگوهای دقیق‌تر ----------
LISTING_PATTERN = re.compile(
    r"(binance will list|binance lists|listed on binance|will be listed on binance)",
    re.I
)

PAIR_PATTERN = re.compile(
    r"(new trading pair|trading pair|spot trading|futures trading)",
    re.I
)

def normalize_id(text: str):
    # یک id پایدار کوتاه برای state
    return hashlib.sha256(text.encode("utf-8")).hexdigest()

def parse_listedon(html):
    soup = BeautifulSoup(html, "html.parser")
    items = []

    for row in soup.select("table tr"):
        cols = [c.get_text(" ", strip=True) for c in row.select("td,th")]
        if len(cols) < 2:
            continue

        joined = " | ".join(cols).strip()

        if PAIR_PATTERN.search(joined):
            continue

        if LISTING_PATTERN.search(joined):
            title = joined
            items.append({
                "id": normalize_id(title),
                "title": title,
                "date": cols[0] if cols else "",
                "url": "https://listedon.org/en/exchange/binance",
            })

    return dedupe(items)

def parse_coinlistingdate(html):
    soup = BeautifulSoup(html, "html.parser")
    items = []

    # فقط تگ‌های لینک/عنوان را بررسی می‌کنیم تا متن مقاله جمع نشود
    for el in soup.select("a, h2, h3"):
        t = el.get_text(" ", strip=True)
        if not t:
            continue

        # حذف متن‌های خیلی بلند (مقاله/description)
        if len(t) > 220:
            continue

        if PAIR_PATTERN.search(t):
            continue

        # سخت‌گیرتر: ترجیحاً با "Binance Will List" شروع شود
        if LISTING_PATTERN.search(t) and re.search(r"binance will list", t, re.I):
            items.append({
                "id": normalize_id(t),
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
        if not title or not href:
            continue

        # حذف متن‌های بلند احتمالی
        if len(title) > 220:
            continue

        if PAIR_PATTERN.search(title):
            continue

        if LISTING_PATTERN.search(title):
            url = "https://www.binance.com" + href if href.startswith("/") else href
            items.append({
                "id": normalize_id(url),
                "title": title,
                "date": "",
                "url": url
            })

    return dedupe(items)

def fetch_from_source(src, timeout=40):
    r = session.get(src["url"], timeout=timeout)
    r.raise_for_status()
    html = r.text

    if src["name"] == "listedon":
        return parse_listedon(html)
    if src["name"] == "coinlistingdate":
        return parse_coinlistingdate(html)
    if src["name"] == "binance_html":
        return parse_binance_html(html)

    return []

def fetch_items():
    for src in FEEDS:
        for attempt in range(2):
            try:
                items = fetch_from_source(src)
                if items:
                    if DEBUG:
                        print(f"Using source: {src['name']} ({len(items)} items)")
                    return items
            except RequestException as e:
                if DEBUG:
                    print(f"Source failed: {src['name']} attempt {attempt+1} -> {e}")
                time.sleep(2 + attempt)
    return []

def truncate_for_telegram(text: str, limit=3500):
    # تلگرام 4096 کاراکتر limit دارد؛ 3500 امن‌تر است
    if len(text) <= limit:
        return text
    return text[:limit-3] + "..."

async def send_item(it):
    msg = (
        "🆕 Binance New Listing (Catalog 48-like)\n\n"
        f"{it.get('title','')}\n"
        f"{it.get('date','')}\n"
        f"{it.get('url','')}"
    )
    msg = truncate_for_telegram(msg)

    await bot.send_message(
        chat_id=TELEGRAM_CHAT_ID,
        text=msg,
        disable_web_page_preview=False
    )

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
