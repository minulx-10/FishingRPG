import discord
from discord.ext import commands
from discord import app_commands
import random

from fishing_core.database import db

# 선박 티어별 스태미나 최대치 매핑
TIER_MAX_STAMINA = {1: 100, 2: 120, 3: 150, 4: 180, 5: 220, 6: 300}

class ShipCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @app_commands.command(name="강화", description="코인(과 재료)을 지불하여 낚싯대를 업그레이드합니다. (Lv.10+ 부터 확률 적용)")
    async def 강화(self, interaction: discord.Interaction):
        coins, rod_tier, rating = await db.get_user_data(interaction.user.id)
        
        # 레벨이 오를수록 기하급수적으로 증가 (기본가 5000, 계수 1.3배수 방식)
        cost = int(5000 * (1.3 ** (rod_tier - 1)))
        
        # Lv.11+ 부터 고철 추가 소모
        if rod_tier >= 30:
            scrap_needed = 10
        elif rod_tier >= 20:
            scrap_needed = 5
        elif rod_tier >= 10:
            scrap_needed = 2
        else:
            scrap_needed = 0
        
        if coins < cost:
            return await interaction.response.send_message(f"❌ 코인이 부족합니다. (필요: `{cost:,} C` / 현재: `{coins:,} C`)", ephemeral=True)
        
        # 고철 체크
        if scrap_needed > 0:
            async with db.conn.execute("SELECT amount FROM inventory WHERE user_id=? AND item_name='낡은 고철 ⚙️'", (interaction.user.id,)) as cursor:
                scrap_res = await cursor.fetchone()
            scrap_amount = scrap_res[0] if scrap_res else 0
            if scrap_amount < scrap_needed:
                return await interaction.response.send_message(
                    f"❌ 재료가 부족합니다!\n"
                    f"• 필요 코인: `{cost:,} C` ✅\n"
                    f"• 필요 고철 ⚙️: `{scrap_needed}개` (보유: `{scrap_amount}개`) ❌",
                    ephemeral=True
                )
        
        # 성공 확률 및 하락 위험 계산
        is_transcendence = rod_tier >= 50
        if rod_tier < 10:
            success_rate = 1.0
            drop_rate = 0.0
        elif rod_tier < 20:
            success_rate = 0.90
            drop_rate = 0.0
        elif rod_tier < 30:
            success_rate = 0.80
            drop_rate = 0.0
        elif rod_tier < 50:
            success_rate = 0.70
            drop_rate = 0.0
        else:
            # 초월 강화 (Lv.50+)
            success_rate = 0.40  # 40% 성공
            drop_rate = 0.30     # 30% 하락 / 30% 유지
        
        # 비용 차감 (성공/실패 무관)
        await db.execute("UPDATE user_data SET coins = coins - ? WHERE user_id = ?", (cost, interaction.user.id))
        if scrap_needed > 0:
            await db.execute("UPDATE inventory SET amount = amount - ? WHERE user_id=? AND item_name='낡은 고철 ⚙️'", (scrap_needed, interaction.user.id))
        
        # 강화 판정
        roll = random.random()
        if roll < success_rate:
            # 성공!
            await db.execute("UPDATE user_data SET rod_tier = rod_tier + 1 WHERE user_id = ?", (interaction.user.id,))
            await db.commit()
            
            new_level = rod_tier + 1
            msg = f"✨ {'🔥 **[초월 성공]** 🔥' if is_transcendence else '캉! 캉! 캉! ...'} 낚싯대가 **Lv.{new_level}** 로 강화되었습니다!"
            
            # 마일스톤 알림 (50강 이후는 10단위로 계속 알림)
            if new_level % 10 == 0:
                # 서버 알림
                try:
                    await interaction.channel.send(f"📢 **[대속보]** {interaction.user.mention}님의 낚싯대가 **Lv.{new_level}**에 도달하는 기염을 토했습니다!!")
                except: pass
            
            await interaction.response.send_message(msg)
        else:
            # 실패 판정 (하락 vs 유지)
            roll_drop = random.random()
            if is_transcendence and roll_drop < drop_rate:
                # 하락
                await db.execute("UPDATE user_data SET rod_tier = MAX(50, rod_tier - 1) WHERE user_id = ?", (interaction.user.id,))
                await db.commit()
                await interaction.response.send_message(
                    f"💀 **[강화 실패]** 낚싯대에 균열이 생기며 레벨이 하락했습니다... (Lv.{rod_tier} → Lv.{max(50, rod_tier-1)})\n"
                    f"• 소모된 코인: `{cost:,} C`"
                )
            else:
                # 유지
                await db.commit()
                await interaction.response.send_message(
                    f"💨 캉... 쿵! 강화에 실패하여 낚싯대의 레벨이 **유지**되었습니다. (Lv.{rod_tier})\n"
                    f"• 소모된 코인: `{cost:,} C`" + (f"\n• 소모된 고철: `{scrap_needed}개`" if scrap_needed > 0 else "") +
                    f"\n*(성공 확률: {int(success_rate*100)}%)*"
                )

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
            3: {"coins": 150000, "scrap": 30, "next": "전투함 ⚓", "unlock": "강화된 선체, 중간 해역 접근 가능"},
            4: {"coins": 800000, "scrap": 80, "next": "잠수함 ⛴️", "unlock": "/수산대전(PvP), 신화 어종 포획 가능"},
            5: {"coins": 2000000, "scrap": 150, "next": "차원함선 🛸", "unlock": "이계/차원 어종 포획 및 극후반 심연의 바다 접근 가능"}
        }

        if current_tier >= 6:
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

        # 스태미나 최대치 업데이트
        new_tier = current_tier + 1
        new_max_stamina = TIER_MAX_STAMINA.get(new_tier, 100)

        await db.execute("UPDATE user_data SET coins = coins - ?, boat_tier = boat_tier + 1, max_stamina = ?, stamina = ? WHERE user_id = ?", 
                         (req["coins"], new_max_stamina, new_max_stamina, interaction.user.id))
        if req["scrap"] > 0:
            await db.execute("UPDATE inventory SET amount = amount - ? WHERE user_id=? AND item_name='낡은 고철 ⚙️'", (req["scrap"], interaction.user.id))
        await db.commit()

        embed = discord.Embed(title="🎉 선박 개조 완료!", description=f"뚝딱뚝딱... 쾅!\n배가 **[{req['next']}]**(으)로 업그레이드 되었습니다!", color=0x2ecc71)
        embed.add_field(name="🔓 새로운 기능 해금!", value=f"`{req['unlock']}` 명령어를 이제 사용할 수 있습니다.", inline=False)
        embed.add_field(name="⚡ 체력 최대치 증가!", value=f"최대 체력이 **{new_max_stamina}⚡**로 증가했습니다! (전부 회복됨)", inline=False)
        await interaction.response.send_message(embed=embed)

async def setup(bot):
    await bot.add_cog(ShipCog(bot))
