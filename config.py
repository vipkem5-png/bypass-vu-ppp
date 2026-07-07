import os
from dotenv import load_dotenv
load_dotenv()

DISCORD_TOKEN       = os.getenv("DISCORD_TOKEN")
ANTHROPIC_API_KEY   = os.getenv("ANTHROPIC_API_KEY")
ALERT_CHANNEL_ID    = int(os.getenv("ALERT_CHANNEL_ID", "0"))
ADMIN_USER_IDS      = list(map(int, os.getenv("ADMIN_IDS", "").split(",") if os.getenv("ADMIN_IDS") else []))

COOLDOWN_SECS       = 5
MAX_AUTO_DETECT     = 5
CACHE_TTL           = 1800        # 30 phút
HEALTH_FAIL_THRESH  = 3           # Die sau 3 lần fail liên tiếp
AI_HEAL_ENABLED     = True
CRAWLER_INTERVAL_H  = 6          # Crawl GitHub mỗi 6 tiếng
