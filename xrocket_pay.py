import logging
from typing import Optional, Tuple
import httpx

from config import XROCKET_API_KEY

logger = logging.getLogger(__name__)

BASE_URL = "https://pay.api.xrocket.exchange/api/v1"


def get_headers() -> dict:
    return {
        "Accept": "application/json",
        "Authorization": f"Bearer {XROCKET_API_KEY}",
    }


async def create_invoice(amount: str = "8.5", currency: str = "USDT") -> Optional[Tuple[str, str]]:
    """Создает инвойс в xRocket. Возвращает (invoice_id, payment_link) или None при ошибке."""
    if not XROCKET_API_KEY:
        logger.error("XROCKET_API_KEY не задан")
        return None

    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.post(
                f"{BASE_URL}/invoices",
                headers=get_headers(),
                json={
                    "priceAmount": str(amount),
                    "priceCurrency": currency,
                },
            )
            if resp.status_code in (200, 201):
                data = resp.json()
                inv_id = str(data.get("id"))
                link = data.get("links", {}).get("telegramBotLink")
                return inv_id, link
            else:
                logger.error("Ошибка создания инвойса xRocket [%s]: %s", resp.status_code, resp.text)
                return None
    except Exception as e:
        logger.error("Исключение при создании инвойса xRocket: %s", e)
        return None


async def check_invoice_paid(invoice_id: str) -> bool:
    """Проверяет, оплачен ли инвойс."""
    if not XROCKET_API_KEY or not invoice_id:
        return False

    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get(
                f"{BASE_URL}/invoices?status=paid",
                headers=get_headers(),
            )
            if resp.status_code == 200:
                data = resp.json()
                items = data.get("items", [])
                for item in items:
                    if str(item.get("id")) == str(invoice_id):
                        return True
            return False
    except Exception as e:
        logger.error("Исключение при проверке инвойса xRocket: %s", e)
        return False
