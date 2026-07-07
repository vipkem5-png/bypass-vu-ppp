import os
import re
import time
import asyncio
import logging
import threading
import schedule

import discord
from discord import app_commands
from discord.ext import commands

import config
from bypass import bypass, is_shortlink, ALL_DOMAINS, DOMAIN_MAP
from bypass.router import reload_dynamic, register_alert_callback, _dynamic_handlers
from bypass.health import get_stats
from bypass.cache import cache_size
from bypass.crawler import crawl_new_domains
from bypass.ai_healer import heal

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler("bot.log", encoding="utf-8"),
    ]
)
log = logging.getLogger("main")

URL_REGEX = re.compile(r"https?://[^\s<>\"']+", re.IGNORECASE)
COOLDOWN: dict[int, float] = {}

intents = discord.Intents.default()
intents.message_content = True
bot = commands.Bot(command_prefix="!", intents=intents)


# ── Embed builder ─────────────────────────────────────────────────

def build_embed(result: dict) -> discord.Embed:
    tags = []
    if result.get("cached"):   tags.append("`cached`")
    if result.get("healing"):  tags.append("`🔧 healing...`")
    if result.get("method"):   tags.append(f"`{result['method']}`")
    tag_str = "  ".join(tags)

    if result["status"] == "error":
        e = discord.Embed(
            title="❌ Bypass thất bại" + (" — đang tự sửa 🤖" if result.get("healing") else ""),
            color=0xe74c3c
        )
        e.add_field(name="Link gốc", value=f"`{result['original'][:200]}`", inline=False)
        e.add_field(name="Lỗi", value=result.get("error", "?")[:300], inline=False)
        if result.get("healing"):
            e.add_field(name="🧠 AI Healer", value="Đang phân tích trang và tự viết handler mới...", inline=False)
        e.set_footer(text=f"{result['domain']}  {tag_str}")
        return e

    changed = result["changed"]
    e = discord.Embed(
        title="✅ Bypass thành công" if changed else "🔗 URL không đổi",
        color=0x2ecc71 if changed else 0x95a5a6
    )
    e.add_field(name="🔗 Link gốc", value=f"`{result['original'][:200]}`", inline=False)
    e.add_field(name="🎯 Link đích", value=result["final"][:500], inline=False)
    e.set_footer(text=f"{result['domain']}  {tag_str}")
    return e


def check_cooldown(uid: int) -> float:
    return max(0, config.COOLDOWN_SECS - (time.time() - COOLDOWN.get(uid, 0)))


# ── Alert callback từ router ──────────────────────────────────────

async def discord_heal_alert(domain: str, result: dict):
    ch = bot.get_channel(config.ALERT_CHANNEL_ID)
    if not ch:
        return
    if result["success"]:
        e = discord.Embed(title="🤖 AI Healer — Thành công", color=0x2ecc71)
        e.add_field(name="Domain", value=f"`{domain}`", inline=True)
        e.add_field(name="Handler size", value=f"{result.get('code_length', '?')} chars", inline=True)
        e.add_field(name="Test URL", value=result.get("final_url", "?")[:200], inline=False)
    else:
        e = discord.Embed(title="🚨 AI Healer — Thất bại", color=0xe74c3c)
        e.add_field(name="Domain", value=f"`{domain}`", inline=True)
        e.add_field(name="Lý do", value=result.get("reason", "?")[:300], inline=False)
    await ch.send(embed=e)


register_alert_callback(discord_heal_alert)


# ── Slash: /bypass ────────────────────────────────────────────────

@bot.tree.command(name="bypass", description="Bypass link rút gọn VN + quốc tế")
@app_commands.describe(url="URL cần bypass")
async def slash_bypass(interaction: discord.Interaction, url: str):
    w = check_cooldown(interaction.user.id)
    if w > 0:
        return await interaction.response.send_message(f"⏳ {w:.1f}s", ephemeral=True)
    COOLDOWN[interaction.user.id] = time.time()
    await interaction.response.defer(thinking=True)
    result = await bypass(url)
    await interaction.followup.send(embed=build_embed(result))


# ── Slash: /status ────────────────────────────────────────────────

@bot.tree.command(name="status", description="Health + stats toàn bộ hệ thống")
async def slash_status(interaction: discord.Interaction):
    stats = get_stats()
    dead = [d for d, s in stats.items() if s["status"] == "dead"]
    degraded = [d for d, s in stats.items() if s["status"] == "degraded"]

    e = discord.Embed(title="📊 System Status", color=0x3498db)
    e.add_field(name="🌐 Total domains", value=str(len(ALL_DOMAINS) + len(_dynamic_handlers)), inline=True)
    e.add_field(name="🤖 AI handlers", value=str(len(_dynamic_handlers)), inline=True)
    e.add_field(name="💾 Cache", value=str(cache_size()), inline=True)
    e.add_field(name="🏓 Latency", value=f"{bot.latency*1000:.0f}ms", inline=True)
    e.add_field(name="💀 Dead domains", value=", ".join(f"`{d}`" for d in dead) or "None", inline=False)
    e.add_field(name="⚠️ Degraded", value=", ".join(f"`{d}`" for d in degraded) or "None", inline=False)
    await interaction.response.send_message(embed=e)


# ── Slash: /heal (admin only) ────────────────────────────────────

@bot.tree.command(name="heal", description="[Admin] Tự động fix handler của domain")
@app_commands.describe(url="URL mẫu của domain cần heal")
async def slash_heal(interaction: discord.Interaction, url: str):
    if interaction.user.id not in config.ADMIN_USER_IDS:
        return await interaction.response.send_message("❌ Admin only.", ephemeral=True)
    await interaction.response.defer(thinking=True)
    from urllib.parse import urlparse
    domain = urlparse(url).netloc.lower().lstrip("www.")
    result = await heal(domain, url, reason="manual admin trigger")
    reload_dynamic()
    e = discord.Embed(
        title="✅ Heal thành công" if result["success"] else "❌ Heal thất bại",
        color=0x2ecc71 if result["success"] else 0xe74c3c
    )
    e.add_field(name="Domain", value=f"`{domain}`")
    if result["success"]:
        e.add_field(name="Result", value=result.get("final_url", "?")[:200])
    else:
        e.add_field(name="Reason", value=result.get("reason", "?")[:300])
    await interaction.followup.send(embed=e)


# ── Slash: /crawl (admin only) ────────────────────────────────────

@bot.tree.command(name="crawl", description="[Admin] Crawl GitHub tìm domain bypass mới")
async def slash_crawl(interaction: discord.Interaction):
    if interaction.user.id not in config.ADMIN_USER_IDS:
        return await interaction.response.send_message("❌ Admin only.", ephemeral=True)
    await interaction.response.defer(thinking=True)
    new_domains = await crawl_new_domains()
    e = discord.Embed(title="🔍 Crawl kết quả", color=0x9b59b6)
    if new_domains:
        e.add_field(
            name=f"🆕 {len(new_domains)} domain mới",
            value="\n".join(f"`{d}`" for d in new_domains[:25]),
            inline=False
        )
        e.set_footer(text="Dùng /heal <url-mẫu> để add handler cho domain mới")
    else:
        e.description = "Không tìm được domain mới."
    await interaction.followup.send(embed=e)


# ── Slash: /supported ────────────────────────────────────────────

@bot.tree.command(name="supported", description="Danh sách site được hỗ trợ")
async def slash_supported(interaction: discord.Interaction):
    static_list = "\n".join(f"`{d}`" for d in sorted(DOMAIN_MAP.keys()))
    ai_list = "\n".join(f"`{d}` 🤖" for d in sorted(_dynamic_handlers.keys())) or "—"
    e = discord.Embed(title="🌐 Supported Sites", color=0x9b59b6)
    e.add_field(name=f"Static ({len(DOMAIN_MAP)})", value=static_list[:1000], inline=True)
    e.add_field(name=f"AI Dynamic ({len(_dynamic_handlers)})", value=ai_list[:500], inline=True)
    await interaction.response.send_message(embed=e, ephemeral=True)


# ── Prefix: !bypass ───────────────────────────────────────────────

@bot.command(name="bypass", aliases=["bp"])
async def prefix_bypass(ctx: commands.Context, url: str):
    w = check_cooldown(ctx.author.id)
    if w > 0:
        return await ctx.reply(f"⏳ {w:.1f}s", mention_author=False)
    COOLDOWN[ctx.author.id] = time.time()
    async with ctx.typing():
        result = await bypass(url)
        await ctx.reply(embed=build_embed(result), mention_author=False)


# ── Auto detect ───────────────────────────────────────────────────

@bot.event
async def on_message(message: discord.Message):
    if message.author.bot:
        return
    urls = [u for u in URL_REGEX.findall(message.content) if is_shortlink(u)]
    if urls and check_cooldown(message.author.id) == 0:
        COOLDOWN[message.author.id] = time.time()
        embeds = []
        for url in urls[:config.MAX_AUTO_DETECT]:
            r = await bypass(url)
            if r["changed"] or r["status"] == "error":
                embeds.append(build_embed(r))
        if embeds:
            await message.reply(embeds=embeds, mention_author=False)
    await bot.process_commands(message)


# ── Background: auto crawl mỗi 6h ───────────────────────────────

def _run_scheduler():
    import time as _time
    while True:
        schedule.run_pending()
        _time.sleep(60)


async def _auto_crawl_job():
    log.info("[CRAWL] Auto crawl starting...")
    new_domains = await crawl_new_domains()
    if new_domains:
        ch = bot.get_channel(config.ALERT_CHANNEL_ID)
        if ch:
            e = discord.Embed(title="🔍 Auto Crawl — Tìm thấy domain mới", color=0x3498db)
            e.add_field(name="Domains", value="\n".join(f"`{d}`" for d in new_domains[:20]))
            e.set_footer(text="Dùng /heal <url-mẫu> để test và add")
            await ch.send(embed=e)


# ── Startup ───────────────────────────────────────────────────────

@bot.event
async def on_ready():
    await bot.tree.sync()
    log.info(f"[✓] {bot.user} online | {len(ALL_DOMAINS)} domains | {len(_dynamic_handlers)} AI handlers")

    # Crawl job mỗi 6 tiếng
    schedule.every(config.CRAWLER_INTERVAL_H).hours.do(
        lambda: asyncio.create_task(_auto_crawl_job())
    )
    threading.Thread(target=_run_scheduler, daemon=True).start()

    print(f"\n{'='*50}")
    print(f"  {bot.user}  |  V3 Self-Healing Engine")
    print(f"  Domains: {len(ALL_DOMAINS)} static + {len(_dynamic_handlers)} AI")
    print(f"  Commands: /bypass /status /heal /crawl /supported")
    print(f"{'='*50}\n")


bot.run(config.DISCORD_TOKEN)
