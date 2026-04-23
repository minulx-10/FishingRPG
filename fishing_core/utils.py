import contextlib
import datetime

import discord
from discord import app_commands

from .database import db
from .logger import logger
from .shared import ADMIN_LOG_CHANNEL_ID, FISH_DATA, RECIPES, SUPER_ADMIN_IDS, kst


async def log_admin_action(bot, admin_user, target_user, action_name, detail):
    """관리자 행동을 특정 채널에 로그로 남깁니다."""
    if not ADMIN_LOG_CHANNEL_ID:
        logger.info(f"[Admin Log] {admin_user.name} -> {target_user.name if target_user else 'N/A'}: {action_name} ({detail})")
        return

    channel = bot.get_channel(ADMIN_LOG_CHANNEL_ID)
    if not channel:
        return

    embed = discord.Embed(title="🛡️ 관리자 작업 로그", color=0xe74c3c, timestamp=datetime.datetime.now(kst))
    embed.add_field(name="실행자", value=f"{admin_user.mention} ({admin_user.id})", inline=True)
    if target_user:
        embed.add_field(name="대상", value=f"{target_user.mention} ({target_user.id})", inline=True)
    embed.add_field(name="명령어", value=f"`/{action_name}`", inline=False)
    embed.add_field(name="상세 내용", value=detail, inline=False)

    with contextlib.suppress(Exception):
        await channel.send(embed=embed)

async def bait_autocomplete(interaction: discord.Interaction, current: str) -> list[app_commands.Choice[str]]:
    baits = ["고급 미끼 🪱", "자석 미끼 🧲"]
    query = f"SELECT item_name FROM inventory WHERE user_id=? AND item_name IN ({','.join(['?']*len(baits))}) AND amount > 0"
    async with db.conn.execute(query, [interaction.user.id, *baits]) as cursor:
        items = await cursor.fetchall()
    choices = [app_commands.Choice(name="미끼 없음 (기본)", value="none")]
    for row in items:
        if current.lower() in row[0].lower():
            choices.append(app_commands.Choice(name=row[0], value=row[0]))
    return choices[:25]

async def fish_autocomplete(interaction: discord.Interaction, current: str) -> list[app_commands.Choice[str]]:
    choices = [app_commands.Choice(name=fish, value=fish) for fish in FISH_DATA if current.lower() in fish.lower()]
    return choices[:25]

async def inv_autocomplete(interaction: discord.Interaction, current: str) -> list[app_commands.Choice[str]]:
    async with db.conn.execute("SELECT item_name FROM inventory WHERE user_id=? AND amount > 0", (interaction.user.id,)) as cursor:
        items = await cursor.fetchall()
    return [app_commands.Choice(name=row[0], value=row[0]) for row in items if current.lower() in row[0].lower()][:25]

async def aqua_autocomplete(interaction: discord.Interaction, current: str) -> list[app_commands.Choice[str]]:
    async with db.conn.execute("SELECT item_name FROM aquarium WHERE user_id=?", (interaction.user.id,)) as cursor:
        items = await cursor.fetchall()
    return [app_commands.Choice(name=row[0], value=row[0]) for row in items if current.lower() in row[0].lower()][:25]

async def locked_autocomplete(interaction: discord.Interaction, current: str) -> list[app_commands.Choice[str]]:
    async with db.conn.execute("SELECT item_name FROM inventory WHERE user_id=? AND amount > 0 AND is_locked=1", (interaction.user.id,)) as cursor:
        items = await cursor.fetchall()
    return [app_commands.Choice(name=row[0], value=row[0]) for row in items if current.lower() in row[0].lower()][:25]

async def recipe_autocomplete(interaction: discord.Interaction, current: str) -> list[app_commands.Choice[str]]:
    return [app_commands.Choice(name=r, value=r) for r in RECIPES if current.lower() in r.lower()][:25]


def is_developer():
    return app_commands.check(lambda i: i.user.id in SUPER_ADMIN_IDS)

def check_boat_tier(min_tier: int):
    async def predicate(interaction: discord.Interaction):
        await db.execute("INSERT OR IGNORE INTO user_data (user_id) VALUES (?)", (interaction.user.id,))
        async with db.conn.execute("SELECT boat_tier FROM user_data WHERE user_id=?", (interaction.user.id,)) as cursor:
            res = await cursor.fetchone()

        tier = res[0] if res else 1
        if tier < min_tier:
            tier_names = {1: "나룻배 🛶", 2: "어선 🚤", 3: "쇄빙선 🛳️", 4: "전투함 ⚓", 5: "잠수함 ⛴️", 6: "차원함선 🛸"}
            req_name = tier_names.get(min_tier, f"Lv.{min_tier}")
            current_name = tier_names.get(tier, f"Lv.{tier}")

            embed = discord.Embed(title="🚫 탑승 권한 부족!", description=f"이 명령어를 사용하려면 **[{req_name}]** 이상이 필요합니다.\n(현재 선박: **{current_name}**)", color=0xe74c3c)
            embed.set_footer(text="💡 '/선박개조' 명령어를 통해 배를 업그레이드하세요!")
            await interaction.response.send_message(embed=embed, ephemeral=True)
            return False
        return True
    return app_commands.check(predicate)
