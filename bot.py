import os
import json
import asyncio
import websockets
from telegram import Bot

# ---------------- ENV ----------------
TG_TOKEN = os.getenv("TG_TOKEN")
TG_CHAT_ID = os.getenv("TG_CHAT_ID")
DEBUG = os.getenv("DEBUG", "1") == "1"

STATE_FILE = "state.json"
TARGET_CATALOG_ID = 48  # دقیقا همان صفحه‌ای که گفتی

bot = Bot(token=TG_TOKEN)

# آدرس استریم رسمی اعلان‌ها
# Binance Open Platform "Announcements" topic
WS_URL = "wss://ws-api.binance.com:443/ws-api/v3"

def load_state():
    try:
        with open(STATE_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {"last_id": None}

def save_state(state):
    with open(STATE_FILE, "w", encoding="utf-8") as f:
        json.dump(state, f, ensure_ascii=False)

async def send_to_telegram(title, url, date=""):
    msg = f"🆕 Binance New Listing (Catalog 48)\n\n{title}\n{date}\n{url}"
    await bot.send_message(chat_id=TG_CHAT_ID, text=msg, disable_web_page_preview=False)

async def listen_announcements():
    state = load_state()
    last_id = state.get("last_id")

    # پیام subscribe مطابق مستند رسمی Announcement Stream
    subscribe_msg = {
        "method": "SUBSCRIBE",
        "params": ["com_announcement_en"],
        "id": 1
    }

    while True:
        try:
            async with websockets.connect(WS_URL, ping_interval=20, ping_timeout=20) as ws:
                await ws.send(json.dumps(subscribe_msg))
                if DEBUG:
                    print("Subscribed to Binance announcements stream.")

                async for raw in ws:
                    data = json.loads(raw)

                    # بعضی پیام‌ها ack هستند؛ فقط event های واقعی را می‌گیریم
                    payload = data.get("result") or data.get("params") or data
                    if not isinstance(payload, dict):
                        continue

                    # ساختار نمونه طبق docs: catalogId, title, publishDate, code/...
                    catalog_id = payload.get("catalogId")
                    title = payload.get("title")
                    publish_ms = payload.get("publishDate")
                    code = payload.get("code")

                    if catalog_id != TARGET_CATALOG_ID:
                        continue

                    # id یکتا
                    ann_id = payload.get("id") or code or publish_ms
                    if ann_id == last_id:
                        continue

                    url = f"https://www.binance.com/en/support/announcement/{code}" if code else "https://www.binance.com/en/support/announcement/list/48"
                    date = ""
                    if publish_ms:
                        date = str(publish_ms)

                    await send_to_telegram(title, url, date)

                    state["last_id"] = ann_id
                    save_state(state)

                    if DEBUG:
                        print("Sent:", title)

        except Exception as e:
            if DEBUG:
                print("WS error, reconnecting:", e)
            await asyncio.sleep(5)

async def main():
    if not TG_TOKEN or not TG_CHAT_ID:
        raise RuntimeError("Set TG_TOKEN and TG_CHAT_ID env vars.")
    await listen_announcements()

if __name__ == "__main__":
    asyncio.run(main())
