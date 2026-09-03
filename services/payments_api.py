
"""API CryptoBot: создание инвойсов, проверка статуса."""
import aiohttp
from config import CRYPTOBOT_TOKEN

CRYPTOBOT_API = "https://pay.crypt.bot/api"


async def cryptobot_create_invoice(coins: int, usdt_price: float):
    async with aiohttp.ClientSession() as s:
        async with s.post(
            f"{CRYPTOBOT_API}/createInvoice",
            headers={"Crypto-Pay-API-Token": CRYPTOBOT_TOKEN},
            json={
                "asset": "USDT",
                "amount": str(usdt_price),
                "description": f"{coins} коинов — Night Parser",
                "payload": f"coins:{coins}",
            },
        ) as r:
            data = await r.json()
            if not data.get("ok"):
                return None
            inv = data["result"]
            return {"invoice_id": inv["invoice_id"], "pay_url": inv["pay_url"]}


async def cryptobot_get_invoice(invoice_id):
    async with aiohttp.ClientSession() as s:
        async with s.get(
            f"{CRYPTOBOT_API}/getInvoices",
            headers={"Crypto-Pay-API-Token": CRYPTOBOT_TOKEN},
            params={"invoice_ids": invoice_id},
        ) as r:
            data = await r.json()
            if not data.get("ok"):
                return None
            items = data["result"]["items"]
            return items[0] if items else None


def payment_is_paid(inv) -> bool:
    if not inv:
        return False
    status = str(inv.get("status", "")).lower()
    return status in ("paid", "success", "finished")
