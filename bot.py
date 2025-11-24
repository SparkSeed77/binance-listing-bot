import os, json, time
import requests
from bs4 import BeautifulSoup
from telegram import Bot

# Telegram env vars
TELEGRAM_BOT_TOKEN = os.getenv("TG_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TG_CHAT_ID")

# how often to poll (seconds)
POLL_SECONDS = int(os.getenv("POLL_SECONDS", "300"))

STATE_FILE = "state.json"

CATALOG_ID = 48
API_URL = (
    "https://www.binance.com/gateway-api/v1/public/cms/article/list/query"
    f"?type=1&catalogId={CATALOG_ID}&pageNo=1&pageSize=20"
)
HTML_URL = "https://www.binance.com/en/support/announcement/list/48"

bot = Bot(token=TELEGRAM_BOT_TOKEN)

def load_state():
    if os.path.exists(STATE_FILE):
        with open(STATE_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    return {"last_id": None}

def save_state(state):
    with open(STATE_FILE, "w", encoding="utf-8") as f:
        json.dump(state, f)

def fetch_via_api():
    r = requests.get(API_URL, timeout=15)
    r.raise_for_status()
    data = r.json()

    articles = data["data"]["articles"]
    items = []
    for a in articles:
        items.append({
            "id": a.get("id") or a.get("code"),
            "title": a["title"],
            "date": a.get("releaseDate", "")[:10],
            "url": "https://www.binance.com/en/support/announcement/" + a["code"]
        })
    return items

def fetch_via_html():
    r = requests.get(HTML_URL, timeout=15)
    r.raise_for_status()
    soup = BeautifulSoup(r.text, "html.parser")

    items = []
    for a in soup.select('a[href*="/en/support/announcement/"]'):
        title = a.get_text(strip=True)
        href = a.get("href")
        if not title or not href:
            continue
        url = "https://www.binance.com" + href if href.startswith("/") else href
        items.append({
            "id": url,
            "title": title,
            "date": "",
            "url": url
        })

    uniq = {}
    for it in items:
        uniq[it["id"]] = it

    return list(uniq.values())[:20]

def fetch_items():
    try:
        return fetch_via_api()
    except Exception as e:
        print("API failed, fallback to HTML:", e)
        return fetch_via_html()

def send_item(it):
    msg = f"🆕 Binance Listing News\n\n{it['title']}\n{it.get('date','')}\n{it['url']}"
    bot.send_message(chat_id=TELEGRAM_CHAT_ID, text=msg, disable_web_page_preview=False)

def main_loop():
    state = load_state()
    last_id = state.get("last_id")

    while True:
        items = fetch_items()
        if not items:
            time.sleep(POLL_SECONDS)
            continue

        new_items = []
        for it in items:
            if it["id"] == last_id:
                break
            new_items.append(it)

        for it in reversed(new_items):
            send_item(it)

        state["last_id"] = items[0]["id"]
        save_state(state)

        time.sleep(POLL_SECONDS)

if __name__ == "__main__":
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        raise RuntimeError("Please set TG_TOKEN and TG_CHAT_ID env vars.")
    main_loop()
