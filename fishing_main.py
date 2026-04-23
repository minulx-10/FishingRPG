import datetime
import os
import sys

# Trigger deployment for JSON fix
import discord
from discord import app_commands
from discord.ext import commands
from dotenv import load_dotenv

from fishing_core.database import db
from fishing_core.logger import logger
from fishing_core.shared import ADMIN_LOG_CHANNEL_ID, init_shared_data, kst
from fishing_core.web_server import start_web_server

intents = discord.Intents.default()
bot = commands.Bot(command_prefix='!', intents=intents)
bot.remove_command('help')

COGS = [
    "fishing_cogs.fishing_cmds",
    "fishing_cogs.market_cmds",
    "fishing_cogs.ship_cmds",
    "fishing_cogs.battle_cmds",
    "fishing_cogs.quest_cmds",
    "fishing_cogs.admin_cmds",
    "fishing_cogs.help_cmds",
    "fishing_cogs.prayer_cmds",
    "fishing_cogs.events",
]

@bot.event
async def setup_hook():
    await db.init_db() 
    await init_shared_data() # 비동기 데이터 초기화
    for cog in COGS:
        try:
            await bot.load_extension(cog)
            logger.info(f"Cog 로드 완료: {cog}")
        except Exception as e:
            logger.error(f"Cog 로드 실패: {cog}", exc_info=e)
            
    await bot.tree.sync()
    bot.loop.create_task(start_web_server(bot))

@bot.tree.interaction_check
async def update_username_cache(interaction: discord.Interaction):
    try:
        now_str = datetime.datetime.now(kst).isoformat()
        await db.execute("UPDATE user_data SET username = ?, last_active = ? WHERE user_id = ?", (interaction.user.name, now_str, interaction.user.id))
        await db.commit()
    except Exception as e:
        logger.warning(f"사용자 정보 캐싱 실패 ({interaction.user.name}): {e}")
    return True

@bot.event
async def on_ready():
    logger.info(f"🎣 수산시장 낚시 RPG 봇 로딩 완료: {bot.user.name}")
    await bot.change_presence(activity=discord.Game("/낚시 | /시세 | /배틀 | /바다")) 

@bot.tree.error
async def on_app_command_error(interaction: discord.Interaction, error: app_commands.AppCommandError):
    """슬래시 명령어 실행 중 발생하는 에러를 전역적으로 처리합니다."""
    
    if isinstance(error, app_commands.CommandOnCooldown):
        await interaction.response.send_message(f"⏰ 쿨다운 중입니다! {error.retry_after:.1f}초 후에 다시 시도해주세요.", ephemeral=True)
    elif isinstance(error, app_commands.CheckFailure):
        await interaction.response.send_message("🚫 이 명령어를 사용할 권한이 없습니다.", ephemeral=True)
    elif isinstance(error, app_commands.MissingPermissions):
        await interaction.response.send_message("🚫 필요한 권한이 부족합니다.", ephemeral=True)
    else:
        logger.error(f"명령어 실행 중 예외 발생: {interaction.command.name if interaction.command else '알 수 없음'}", exc_info=error)
        
        if ADMIN_LOG_CHANNEL_ID:
            try:
                channel = bot.get_channel(ADMIN_LOG_CHANNEL_ID)
                if channel:
                    error_msg = f"⚠️ **명령어 에러 발생**\n- 명령어: `/{interaction.command.name if interaction.command else 'unknown'}`\n- 사용자: {interaction.user.name} ({interaction.user.id})\n- 에러: `{error}`"
                    await channel.send(error_msg)
            except Exception:
                pass

        if not interaction.response.is_done():
            await interaction.response.send_message("❌ 명령어를 처리하는 중에 오류가 발생했습니다. 잠시 후 다시 시도해주세요.", ephemeral=True)
        else:
            await interaction.followup.send("❌ 명령어를 처리하는 중에 오류가 발생했습니다. 잠시 후 다시 시도해주세요.", ephemeral=True)

if __name__ == "__main__":
    load_dotenv() 
    TOKEN = os.getenv('DISCORD_TOKEN') 
    if not TOKEN:
        logger.critical("DISCORD_TOKEN이 .env 파일에 설정되어 있지 않습니다!")
        sys.exit(1)
    bot.run(TOKEN)
