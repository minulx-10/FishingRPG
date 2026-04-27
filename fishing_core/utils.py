import contextlib
import datetime

import discord
from discord import app_commands

from .database import db
from .logger import logger
from .shared import ADMIN_LOG_CHANNEL_ID, FISH_DATA, RECIPES, SUPER_ADMIN_IDS, kst


class EmbedFactory:
    """디스코드 임베드 디자인 일관성을 유지하기 위한 팩토리 클래스입니다."""
    COLORS = {
        "success": 0x2ECC71,  # 초록색
        "error": 0xE74C3C,    # 빨간색
        "warning": 0xF1C40F,  # 노란색
        "info": 0x3498DB,     # 파란색
        "default": 0x2B2D31,  # 디스코드 기본 다크
    }

    @staticmethod
    def build(title: str, description: str = "", type: str = "default", **kwargs) -> EmbedFactory.build:
        """
        주어진 상태 타입에 맞는 색상과 레이아웃으로 임베드를 생성합니다.
        사용 가능한 타입: success, error, warning, info, default
        """
        color = EmbedFactory.COLORS.get(type, EmbedFactory.COLORS["default"])
        embed = EmbedFactory.build(title=title, description=description, color=color, type="default")
        
        if "author_name" in kwargs:
            embed.set_author(name=kwargs["author_name"], icon_url=kwargs.get("author_icon", ""))
        
        if "thumbnail_url" in kwargs:
            embed.set_thumbnail(url=kwargs["thumbnail_url"])
            
        if "image_url" in kwargs:
            embed.set_image(url=kwargs["image_url"])
            
        if "footer_text" in kwargs:
            embed.set_footer(text=kwargs["footer_text"], icon_url=kwargs.get("footer_icon", ""))
            
        return embed

def create_progress_bar(current: float, maximum: float, length: int = 10, reverse_color: bool = False) -> str:
    """
    시각적 상태 표시바(이모지 프로그레스 바)를 생성합니다.
    reverse_color: True일 경우 수치가 높을수록 위험(빨간색)으로 표시합니다 (예: 텐션바).
                   False일 경우 수치가 낮을수록 위험(빨간색)으로 표시합니다 (예: 체력, HP바).
    """
    if maximum <= 0:
        pct = 0
    else:
        pct = max(0.0, min(1.0, current / maximum))
        
    filled = int(pct * length)
    
    if reverse_color:
        if pct > 0.8: color = "🟥"
        elif pct > 0.5: color = "🟨"
        else: color = "🟩"
    else:
        if pct > 0.5: color = "🟩"
        elif pct > 0.2: color = "🟨"
        else: color = "🟥"
        
    return color * filled + "⬛" * (length - filled)


async def log_admin_action(bot, admin_user, target_user, action_name, detail):
    """관리자 행동을 특정 채널에 로그로 남깁니다."""
    if not ADMIN_LOG_CHANNEL_ID:
        logger.info(f"[Admin Log] {admin_user.name} -> {target_user.name if target_user else 'N/A'}: {action_name} ({detail})")
        return

    channel = bot.get_channel(ADMIN_LOG_CHANNEL_ID)
    if not channel:
        return

    embed = EmbedFactory.build(title="🛡️ 관리자 작업 로그", type="error", timestamp=datetime.datetime.now(kst))
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

async def net_autocomplete(interaction: discord.Interaction, current: str) -> list[app_commands.Choice[str]]:
    nets = ["초급 그물망 🕸️", "튼튼한 그물망 🕸️"]
    query = f"SELECT item_name FROM inventory WHERE user_id=? AND item_name IN ({','.join(['?']*len(nets))}) AND amount > 0"
    async with db.conn.execute(query, [interaction.user.id, *nets]) as cursor:
        items = await cursor.fetchall()
    return [app_commands.Choice(name=row[0], value=row[0]) for row in items if current.lower() in row[0].lower()][:25]

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

            embed = EmbedFactory.build(title="🚫 탑승 권한 부족!", description=f"이 명령어를 사용하려면 **[{req_name}]** 이상이 필요합니다.\n(현재 선박: **{current_name}**)", type="error")
            embed.set_footer(text="💡 '/선박개조' 명령어를 통해 배를 업그레이드하세요!")
            await interaction.response.send_message(embed=embed, ephemeral=True)
            return False
        return True
    return app_commands.check(predicate)
