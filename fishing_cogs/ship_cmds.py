import discord
from discord.ext import commands
from discord import app_commands

from fishing_core.database import db

class ShipCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @app_commands.command(name="강화", description="코인을 지불하여 낚싯대를 업그레이드합니다. (타이밍 판정 및 확률 증가)")
    async def 강화(self, interaction: discord.Interaction):
        coins, rod_tier, rating = await db.get_user_data(interaction.user.id)
        
        # 레벨이 오를수록 기하급수적으로 증가 (기본가 5000, 계수 1.3배수 방식)
        cost = int(5000 * (1.3 ** (rod_tier - 1)))
        
        if coins < cost:
            return await interaction.response.send_message(f"❌ 코인이 부족합니다. (필요: `{cost:,} C` / 현재: `{coins:,} C`)", ephemeral=True)
            
        await db.execute("UPDATE user_data SET coins = coins - ?, rod_tier = rod_tier + 1 WHERE user_id = ?", (cost, interaction.user.id))
        await db.commit()
        await interaction.response.send_message(f"✨ 캉! 캉! 캉! ... 낚싯대가 **Lv.{rod_tier + 1}** 로 강화되었습니다!\n(낚시 판정 시간이 늘어나고, 희귀 물고기 획득률이 상승합니다!)")

    @app_commands.command(name="선박개조", description="코인과 고철을 모아 배를 다음 티어로 업그레이드하고 새로운 기능을 해금합니다!")
    async def 선박개조(self, interaction: discord.Interaction):
        coins, rod_tier, rating = await db.get_user_data(interaction.user.id)
        
        async with db.conn.execute("SELECT boat_tier FROM user_data WHERE user_id=?", (interaction.user.id,)) as cursor:
            res = await cursor.fetchone()
        current_tier = res[0] if res else 1

        async with db.conn.execute("SELECT amount FROM inventory WHERE user_id=? AND item_name='낡은 고철 ⚙️'", (interaction.user.id,)) as cursor:
            scrap_res = await cursor.fetchone()
        scrap_amount = scrap_res[0] if scrap_res else 0

        upgrade_costs = {
            1: {"coins": 10000, "scrap": 0, "next": "어선 🚤", "unlock": "/요리, /의뢰, /상점, /구매"},
            2: {"coins": 50000, "scrap": 15, "next": "쇄빙선 🛳️", "unlock": "/전시, /배틀"},
            3: {"coins": 150000, "scrap": 30, "next": "잠수함 ⛴️", "unlock": "/수산대전(PvP), 신화 어종 포획 가능"},
            4: {"coins": 2000000, "scrap": 150, "next": "차원함선 🛸", "unlock": "이계/차원 어종 포획 및 극후반 심연의 바다 접근 가능"}
        }

        if current_tier >= 5:
            return await interaction.response.send_message("✨ 이미 최고의 선박인 **[차원함선 🛸]**을 보유하고 있습니다!", ephemeral=True)

        req = upgrade_costs[current_tier]
        
        if coins < req["coins"] or scrap_amount < req["scrap"]:
            embed = discord.Embed(title="❌ 재료 부족", description="선박을 개조하기 위한 자원이 부족합니다.", color=0xe74c3c)
            embed.add_field(name="필요 코인", value=f"`{req['coins']:,} C` (보유: `{coins:,} C`)", inline=True)
            if req["scrap"] > 0:
                embed.add_field(name="필요 고철 ⚙️", value=f"`{req['scrap']}개` (보유: `{scrap_amount}개`)", inline=True)
                embed.set_footer(text="💡 상점에서 자석 미끼를 구매해 바다에서 고철을 건져올리세요!")
            else:
                embed.set_footer(text="💡 열심히 낚시를 해서 코인을 모아보세요!")
            return await interaction.response.send_message(embed=embed, ephemeral=True)

        await db.execute("UPDATE user_data SET coins = coins - ?, boat_tier = boat_tier + 1 WHERE user_id = ?", (req["coins"], interaction.user.id))
        if req["scrap"] > 0:
            await db.execute("UPDATE inventory SET amount = amount - ? WHERE user_id=? AND item_name='낡은 고철 ⚙️'", (req["scrap"], interaction.user.id))
        await db.commit()

        embed = discord.Embed(title="🎉 선박 개조 완료!", description=f"뚝딱뚝딱... 쾅!\n배가 **[{req['next']}]**(으)로 업그레이드 되었습니다!", color=0x2ecc71)
        embed.add_field(name="🔓 새로운 기능 해금!", value=f"`{req['unlock']}` 명령어를 이제 사용할 수 있습니다.", inline=False)
        await interaction.response.send_message(embed=embed)

async def setup(bot):
    await bot.add_cog(ShipCog(bot))
