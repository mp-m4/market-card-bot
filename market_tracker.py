import os
import time
import threading
import requests
from http.server import HTTPServer, BaseHTTPRequestHandler

# ---------------- CONFIGURATION ----------------
DISCORD_WEBHOOK_URL = "https://discord.com/api/webhooks/1550072537877184583/LLpc9TsH7Dc4JUGSrA4l2wmXOA6UNWH3pC4vG6RBWlbw4uZSfVfY3FRsInjEM2cv1WmA"

# Replace '123456789012345678' with your actual @marketLurker Role ID from Discord
ROLE_PING = "<@&123456789012345678>"  

# MuhRO MarketDB Endpoints
ACTIVE_VENDING_API = "https://flux.muhro.eu/?module=marketdb&action=api&name=v_vending"
LAST_SALES_API = "https://flux.muhro.eu/?module=marketdb&action=api&name=vending_last_sales_latest"

CHECK_INTERVAL_SECONDS = 60
PING_DELAY_SECONDS = 2  # Pause in seconds between sending alerts
# -----------------------------------------------

# Memory tracking to avoid duplicate pings
alerted_listings = set()
alerted_sales = set()


# --- KEEP-ALIVE SERVER FOR RENDER ---
class SimpleHTTPRequestHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"MuhRO Market Bot is active and running!")

def run_web_server():
    port = int(os.environ.get("PORT", 10000))
    server = HTTPServer(("0.0.0.0", port), SimpleHTTPRequestHandler)
    server.serve_forever()


# --- HELPER FUNCTIONS ---
def send_discord_alert(content_text, title, color, price, amount, datetime_str):
    """Sends a formatted embed message to Discord with Rate Limit protection."""
    payload = {
        "content": content_text,
        "embeds": [
            {
                "title": title,
                "color": color,
                "fields": [
                    {"name": "Price", "value": f"{price:,} Zeny", "inline": True},
                    {"name": "Quantity", "value": str(amount), "inline": True},
                    {"name": "Date & Time", "value": str(datetime_str), "inline": True}
                ],
                "footer": {"text": "MuhRO MVP Market Tracker"}
            }
        ]
    }
    
    while True:
        try:
            response = requests.post(DISCORD_WEBHOOK_URL, json=payload, timeout=10)
            
            if response.status_code == 204:
                print(f"[{time.strftime('%H:%M:%S')}] Discord alert sent successfully.")
                break
            elif response.status_code == 429:
                retry_after = response.json().get("retry_after", 2)
                print(f"[{time.strftime('%H:%M:%S')}] Rate limited by Discord. Retrying in {retry_after}s...")
                time.sleep(retry_after)
            else:
                print(f"[{time.strftime('%H:%M:%S')}] Discord HTTP Error: {response.status_code}")
                break
        except Exception as e:
            print(f"[{time.strftime('%H:%M:%S')}] Failed to post to Discord: {e}")
            break


def parse_zeny(raw_price, currency):
    """Parses Zeny values safely."""
    try:
        parsed = int(str(raw_price).replace(",", ""))
        if "1m" in str(currency).lower() or (parsed < 1000000 and "zeny" not in str(currency).lower()):
            return parsed * 1000000
        return parsed
    except ValueError:
        return 0


def is_watched_item(item_name):
    """Checks if the item matches [MVP] or 'MVP Card Ticket'."""
    name_lower = item_name.lower()
    return "[mvp]" in name_lower or "mvp card ticket" in name_lower


# --- MARKET CHECKERS ---
def process_active_listings():
    """Checks for newly listed watched items."""
    timestamp = time.strftime('%H:%M:%S')
    current_datetime = time.strftime('%Y-%m-%d %H:%M:%S')
    headers = {'User-Agent': 'Mozilla/5.0'}
    
    try:
        res = requests.get(ACTIVE_VENDING_API, headers=headers, timeout=10)
        if res.status_code != 200:
            return
        data = res.json()
    except Exception:
        return

    items = data if isinstance(data, list) else data.get("items", [])
    current_scan_ids = set()

    for item in items:
        name = item.get("name") or item.get("item_name") or ""
        total_zeny = parse_zeny(item.get("price"), item.get("currency"))
        amount = item.get("amount") or item.get("count") or 1
        
        listing_time = (
            item.get("date") or 
            item.get("created_at") or 
            item.get("time") or 
            current_datetime
        )

        listing_id = f"{name}-{total_zeny}-{amount}"

        if is_watched_item(name):
            current_scan_ids.add(listing_id)
            if listing_id not in alerted_listings:
                print(f"[{timestamp}] 🚨 NEW LISTING: {name} for {total_zeny:,} Zeny")
                
                send_discord_alert(
                    content_text=f"🚨 **NEW MATCHED ITEM LISTED ON MARKET!** {ROLE_PING}",
                    title=f"👑 {name}",
                    color=15158332,
                    price=total_zeny,
                    amount=amount,
                    datetime_str=listing_time
                )
                alerted_listings.add(listing_id)
                time.sleep(PING_DELAY_SECONDS)

    alerted_listings.intersection_update(current_scan_ids)


def process_recent_sales():
    """Checks for newly sold watched items."""
    timestamp = time.strftime('%H:%M:%S')
    current_datetime = time.strftime('%Y-%m-%d %H:%M:%S')
    headers = {'User-Agent': 'Mozilla/5.0'}
    
    try:
        res = requests.get(LAST_SALES_API, headers=headers, timeout=10)
        if res.status_code != 200:
            return
        data = res.json()
    except Exception:
        return

    sales = data if isinstance(data, list) else data.get("items", [])

    for sale in sales:
        name = sale.get("name") or sale.get("item_name") or ""
        total_zeny = parse_zeny(sale.get("price"), sale.get("currency"))
        amount = sale.get("amount") or sale.get("count") or 1
        
        sold_time = (
            sale.get("date") or 
            sale.get("sold_at") or 
            sale.get("time") or 
            current_datetime
        )

        sale_id = f"{name}-{total_zeny}-{amount}-{sold_time}"

        if is_watched_item(name):
            if sale_id not in alerted_sales:
                print(f"[{timestamp}] 💰 ITEM SOLD: {name} for {total_zeny:,} Zeny at {sold_time}")
                
                send_discord_alert(
                    content_text=f"💰 **MATCHED ITEM HAS BEEN SOLD!** {ROLE_PING}",
                    title=f"💸 SOLD: {name}",
                    color=3066993,
                    price=total_zeny,
                    amount=amount,
                    datetime_str=sold_time
                )
                alerted_sales.add(sale_id)
                time.sleep(PING_DELAY_SECONDS)

    if len(alerted_sales) > 500:
        alerted_sales.clear()


# --- ENTRY POINT ---
if __name__ == "__main__":
    print("==================================================")
    print(" MuhRO [MVP] & MVP Card Ticket Tracker Started")
    print(f" Checking every {CHECK_INTERVAL_SECONDS} seconds...")
    print(f" Ping delay set to {PING_DELAY_SECONDS} seconds per alert.")
    print("==================================================")
    
    # 1. Start the keep-alive web server on a background thread for Render
    threading.Thread(target=run_web_server, daemon=True).start()

    # 2. Infinite market monitoring loop
    while True:
        process_active_listings()
        process_recent_sales()
        time.sleep(CHECK_INTERVAL_SECONDS)
