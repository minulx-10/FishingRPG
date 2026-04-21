import discord
from discord.ext import commands
from discord import app_commands
import subprocess

from fishing_core.utils import is_developer
from fishing_core.database import db
from fishing_core.shared import reload_data

class AdminCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @app_commands.command(name="코인지급", description="[관리자 전용] 특정 유저에게 코인을 강제로 지급합니다.")
    @is_developer()
    async def 코인지급(self, interaction: discord.Interaction, target: discord.Member, amount: int):
        await db.get_user_data(target.id)
        await db.execute("UPDATE user_data SET coins = coins + ? WHERE user_id = ?", (amount, target.id))
        await db.commit()
        await interaction.response.send_message(f"💰 관리자 권한으로 **{target.name}**님에게 `{amount:,} C`를 지급했습니다!")

    @app_commands.command(name="데이터새로고침", description="[관리자 전용] GitHub에서 최신 데이터를 가져온 후 봇 재시작 없이 반영합니다.")
    @is_developer()
    async def 데이터새로고침(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True) 
        
        try:
            process = subprocess.Popen(["git", "pull"], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
            stdout, stderr = process.communicate()
            
            reload_data()
            
            msg = f"✅ 최신 데이터를 깃허브에서 가져와 성공적으로 반영했습니다!\n```bash\n{stdout}```"
            await interaction.followup.send(msg)
            
        except Exception as e:
            await interaction.followup.send(f"❌ 데이터 업데이트 중 오류가 발생했습니다.\n**상세 오류:** `{e}`")

async def setup(bot):
    await bot.add_cog(AdminCog(bot))
