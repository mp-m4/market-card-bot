import os
import time
import threading
import requests
from http.server import HTTPServer, BaseHTTPRequestHandler

# ---------------- CONFIGURATION ----------------
DISCORD_WEBHOOK_URL = "https://discord.com/api/webhooks/1550072537877184583/LLpc9TsH7Dc4JUGSrA4l2wmXOA6UNWH3pC4vG6RBWlbw4uZSfVfY3FRsInjEM2cv1WmA"

# MuhRO MarketDB Endpoints
ACTIVE_VENDING_API = "https://flux.muhro.eu/?module=marketdb&action=api&name=v_vending"
LAST_SALES_API = "https://flux.muhro.eu/?module=marketdb&action=api&name=vending_last_sales_latest"

CHECK_INTERVAL_SECONDS = 300  # 5 minutes
PING_DELAY_SECONDS = 2  # Pause in seconds between sending alerts
# -----------------------------------------------

# Memory tracking to avoid duplicate pings
alerted_listings = set()
alerted_sales = set()

# Global flags to control initial silent warm-ups
is_initial_listings_warmup = True
is_initial_sales_warmup = True


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
            
            if response.status_code in (200, 204):
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


def parse_zeny(raw_price, currency="zeny"):
    """Parses Zeny values safely from numbers or strings."""
    if raw_price is None:
        return 0
    try:
        clean_str = str(raw_price).replace(",", "").strip()
        parsed = int(float(clean_str))
        
        if "1m" in str(currency).lower() or (parsed < 1000000 and "zeny" not in str(currency).lower() and parsed > 0):
            return parsed * 1000000
        return parsed
    except (ValueError, TypeError):
        return 0


def parse_sale_data(sale_dict):
    """Safely extracts price and quantity for sold items across all possible API keys."""
    # 1. Extract Quantity
    amount = 1
    for key in ["amount", "count", "qty", "quantity", "num"]:
        val = sale_dict.get(key)
        if val is not None:
            try:
                parsed_val = int(str(val).replace(",", "").strip())
                if parsed_val > 0:
                    amount = parsed_val
                    break
            except ValueError:
                pass

    # 2. Extract Price across potential Flux market keys
    raw_price = (
        sale_dict.get("price") or 
        sale_dict.get("total_price") or 
        sale_dict.get("cost") or 
        sale_dict.get("total") or 
        sale_dict.get("zeny") or 
        sale_dict.get("unit_price") or
        0
    )

    currency = sale_dict.get("currency") or sale_dict.get("type") or "zeny"
    total_zeny = parse_zeny(raw_price, currency)

    if sale_dict.get("unit_price") and not (sale_dict.get("price") or sale_dict.get("total_price")):
        unit_price = parse_zeny(sale_dict.get("unit_price"), currency)
        if unit_price > 0:
            total_zeny = unit_price * amount

    return total_zeny, amount


def is_watched_item(item_name):
    """Checks if the item matches [MVP] or 'MVP Card Ticket'."""
    name_lower = item_name.lower()
    return "[mvp]" in name_lower or "mvp card ticket" in name_lower


# --- MARKET CHECKERS ---
def process_active_listings():
    """Checks for newly listed watched items."""
    global is_initial_listings_warmup
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
        
        # Quantity extraction for active listings
        amount = 1
        for key in ["amount", "count", "qty", "quantity"]:
            val = item.get(key)
            if val is not None:
                try:
                    amount = int(str(val).replace(",", "").strip())
                    break
                except ValueError:
                    pass

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
                if not is_initial_listings_warmup:
                    print(f"[{timestamp}] 🚨 NEW LISTING: {name} (x{amount}) for {total_zeny:,} Zeny")
                    
                    send_discord_alert(
                        content_text="🚨 **NEW MATCHED ITEM LISTED ON MARKET!**",
                        title=f"👑 {name}",
                        color=15158332,
                        price=total_zeny,
                        amount=amount,
                        datetime_str=listing_time
                    )
                    time.sleep(PING_DELAY_SECONDS)
                
                alerted_listings.add(listing_id)

    alerted_listings.intersection_update(current_scan_ids)

    if is_initial_listings_warmup:
        print(f"[{timestamp}] ✅ Active listings warm-up complete. Cached {len(alerted_listings)} existing listings silently.")
        is_initial_listings_warmup = False


def process_recent_sales():
    """Checks for newly sold watched items."""
    global is_initial_sales_warmup
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
        total_zeny, amount = parse_sale_data(sale)
        
        sold_time = (
            sale.get("date") or 
            sale.get("sold_at") or 
            sale.get("time") or 
            current_datetime
        )

        sale_id = f"{name}-{total_zeny}-{amount}-{sold_time}"

        if is_watched_item(name):
            if sale_id not in alerted_sales:
                if not is_initial_sales_warmup:
                    print(f"[{timestamp}] 💰 ITEM SOLD: {name} (x{amount}) for {total_zeny:,} Zeny at {sold_time}")
                    
                    send_discord_alert(
                        content_text="💰 **MATCHED ITEM HAS BEEN SOLD!**",
                        title=f"💸 SOLD: {name}",
                        color=3066993,
                        price=total_zeny,
                        amount=amount,
                        datetime_str=sold_time
                    )
                    time.sleep(PING_DELAY_SECONDS)
                
                alerted_sales.add(sale_id)

    if is_initial_sales_warmup:
        print(f"[{timestamp}] ✅ Sales history warm-up complete. Cached {len(alerted_sales)} historical sales silently.")
        is_initial_sales_warmup = False

    if len(alerted_sales) > 500:
        alerted_sales.clear()


# --- ENTRY POINT ---
if __name__ == "__main__":
    print("==================================================")
    print(" MuhRO [MVP] & MVP Card Ticket Tracker Started")
    print(f" Checking every {CHECK_INTERVAL_SECONDS} seconds...")
    print(f" Ping delay set to {PING_DELAY_SECONDS} seconds per alert.")
    print("==================================================")
    
    threading.Thread(target=run_web_server, daemon=True).start()

    while True:
        process_active_listings()
        process_recent_sales()
        time.sleep(CHECK_INTERVAL_SECONDS)
