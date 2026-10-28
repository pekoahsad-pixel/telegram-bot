import os
from dotenv import load_dotenv

load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN", "").strip()

raw_channel_id = os.getenv("CHANNEL_ID", "-1004457993462").strip()
try:
    CHANNEL_ID = int(raw_channel_id)
except ValueError:
    CHANNEL_ID = raw_channel_id

CHANNEL_URL = os.getenv("CHANNEL_URL", "https://t.me/+hAQ2w-jufjIzMzZi").strip()

raw_admin_id = os.getenv("ADMIN_ID", "6640124805").strip()
ADMIN_ID = int(raw_admin_id) if raw_admin_id.isdigit() else 6640124805

ADMIN_USERNAME = os.getenv("ADMIN_USERNAME", "@hetero777").strip()
XROCKET_API_KEY = os.getenv("XROCKET_API_KEY", "").strip()
