import os
from dotenv import load_dotenv

load_dotenv()  # подхватывает переменные из .env, если он есть рядом с проектом


def _require(name: str) -> str:
    value = os.getenv(name)
    if not value:
        raise RuntimeError(
            f"Не задана переменная окружения {name}. "
            f"Скопируйте .env.example в .env и заполните её.")
    return value


BOT_TOKEN = _require("BOT_TOKEN")
BOT_USERNAME = os.getenv("BOT_USERNAME", "")
ADMIN_IDS = [int(x) for x in os.getenv("ADMIN_IDS", "").split(",") if x.strip()]

CRYPTOBOT_TOKEN = _require("CRYPTOBOT_TOKEN")

# Экономика
STARTING_BALANCE = 100
SEARCH_PRICE = 5
REWARD_PER_CHAT = 1
REWARD_PER_PRIVATE_CHAT = 0  # приватные чаты не проверяются (см. README) — награда за них
                            # обнулена, чтобы боты/фермы не генерировали случайные
                            # инвайт-ссылки ради бесплатных коинов
REFERRAL_BONUS = 10
REPORT_PENALTY = 1
REPORTS_TO_REMOVE = 3

# Антиспам
MIN_MEMBERS = 10
SUBMIT_COOLDOWN_SEC = 15
MAX_RESULTS = 50

# Оплата
PAYMENT_TIMEOUT_SEC = 900       # 15 минут на оплату счёта CryptoBot
PAYMENT_POLL_INTERVAL_SEC = 10  # как часто опрашивать статус счёта

# Пакеты: коины / Stars / USDT
PACKAGES = [
    {"coins": 100,  "stars": 37,  "usdt": 0.75},
    {"coins": 500,  "stars": 150, "usdt": 3.0},
    {"coins": 1500, "stars": 375, "usdt": 7.5},
]
