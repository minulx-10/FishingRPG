import discord
from discord.ext import commands
from discord import app_commands
import random
import datetime
import asyncio

from fishing_core.database import db
from fishing_core.shared import FISH_DATA, kst, env_state
from fishing_core.views import FishingView
from fishing_core.utils import bait_autocomplete

class FishingCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.equipped_baits = {}

    @app_commands.command(name="미끼장착", description="자동으로 소모할 미끼를 장착하거나 해제합니다.")
    @app_commands.autocomplete(미끼이름=bait_autocomplete)
    async def 미끼장착(self, interaction: discord.Interaction, 미끼이름: str):
        if 미끼이름 == "none":
            self.equipped_baits.pop(interaction.user.id, None)
            return await interaction.response.send_message("✅ 자동 장착된 미끼를 해제했습니다.")
            
        async with db.conn.execute("SELECT amount FROM inventory WHERE user_id=? AND item_name=?", (interaction.user.id, 미끼이름)) as cursor:
            res = await cursor.fetchone()
        
        if not res or res[0] <= 0:
            return await interaction.response.send_message(f"❌ 가방에 **{미끼이름}**가 없습니다! 소지하고 있는 미끼만 장착할 수 있습니다.", ephemeral=True)
            
        self.equipped_baits[interaction.user.id] = 미끼이름
        await interaction.response.send_message(f"✅ **{미끼이름}**를 낚싯대에 장착했습니다!\n이제 `/낚시` 시 이 미끼가 가방에서 자동으로 소모됩니다.")

    @app_commands.command(name="낚시", description="찌를 던져 물고기(또는 보물)를 낚습니다! (타이밍 미니게임 / 체력 10 소모)")
    @app_commands.autocomplete(사용할미끼=bait_autocomplete)
    async def 낚시(self, interaction: discord.Interaction, 사용할미끼: str = "none"):
        coins, rod_tier, rating = await db.get_user_data(interaction.user.id)
        
        async with db.conn.execute("SELECT stamina, max_stamina, title FROM user_data WHERE user_id=?", (interaction.user.id,)) as cursor:
            stamina_res = await cursor.fetchone()
        current_stamina, max_stamina, title = stamina_res if stamina_res else (100, 100, "")
        display_name = f"{title} {interaction.user.name}" if title else interaction.user.name
        
        if current_stamina < 10:
            return await interaction.response.send_message(f"❌ 행동력(체력)이 부족하여 낚싯대를 던질 수 없습니다!\n(필요 체력: 10 / 현재: {current_stamina}⚡)\n💡 `/출석`이나 `/요리`를 통해 체력을 회복하세요.", ephemeral=True)
            
        bait_used = 사용할미끼
        if bait_used == "none" and interaction.user.id in self.equipped_baits:
            bait_used = self.equipped_baits[interaction.user.id]
            
        bait_text = ""
        
        if bait_used != "none":
            async with db.conn.execute("SELECT amount FROM inventory WHERE user_id=? AND item_name=?", (interaction.user.id, bait_used)) as cursor:
                bait_res = await cursor.fetchone()
            
            if not bait_res or bait_res[0] <= 0:
                if interaction.user.id in self.equipped_baits and self.equipped_baits[interaction.user.id] == bait_used:
                    self.equipped_baits.pop(interaction.user.id, None)
                    return await interaction.response.send_message(f"❌ 장착된 **{bait_used}**를 모두 소모했습니다! (자동 장착 해제)\n상점에서 미끼를 다시 구매하세요.", ephemeral=True)
                else:
                    return await interaction.response.send_message(f"❌ 가방에 **{bait_used}**가 없습니다! 상점에서 먼저 구매해주세요.", ephemeral=True)
                
            await db.execute("UPDATE inventory SET amount = amount - 1 WHERE user_id=? AND item_name=?", (interaction.user.id, bait_used))
            await db.commit()
            bait_text = f" ({bait_used} 사용됨!)"

        await db.execute("UPDATE user_data SET stamina = stamina - 10 WHERE user_id=?", (interaction.user.id,))

        now_str = datetime.datetime.now(kst).strftime('%Y-%m-%d %H:%M:%S')
        async with db.conn.execute("SELECT buff_type FROM active_buffs WHERE user_id=? AND end_time > ?", (interaction.user.id, now_str)) as cursor:
            active_buffs = [row[0] for row in await cursor.fetchall()]

        candidates = []
        weights = []
        
        if "ghost_sea_open" in active_buffs:
            ghost_items = {"해적의 금화 🪙": 60, "가라앉은 보물상자 🧰": 25, "낡은 고철 ⚙️": 15}
            for item, prob in ghost_items.items():
                candidates.append(item)
                weights.append(prob)
            bait_text += "\n*(☠️ 망자의 해역: 주변에 물고기의 기척이 전혀 없습니다...)*"
        else:
            for fish, data in FISH_DATA.items():
                base_prob = data["prob"]
                grade = data["grade"]
                
                if bait_used == "자석 미끼 🧲":
                    if fish not in ["낡은 고철 ⚙️", "해적의 금화 🪙", "가라앉은 보물상자 🧰"]:
                        continue
                    base_prob *= 2.0 
                elif bait_used == "고급 미끼 🪱":
                    if grade == "일반":
                        base_prob *= 0.1
                    elif grade in ["희귀", "초희귀"]:
                        base_prob *= 1.5

                if "deep_sea_rift" in active_buffs and data["element"] == "심해":
                    base_prob *= 3.0
                elif "deep_sea_boost" in active_buffs and data["element"] == "심해":
                    base_prob *= 2.0
                    
                if grade in ["에픽", "레전드", "신화"]:
                    base_prob *= (1 + (rod_tier * 0.1))

                candidates.append(fish)
                weights.append(base_prob)
            
        if not candidates:
            target_fish = "낡은 장화 🥾"
        else:
            target_fish = random.choices(candidates, weights=weights, k=1)[0]

        now_hour = datetime.datetime.now(kst).hour
        if target_fish == "바다의 원혼, 우미보즈 🌑" and not (0 <= now_hour < 4):
            target_fish = "낡은 장화 🥾"
            bait_text += "\n*(으스스한 기운이 맴돌았지만, 날이 밝아 흩어졌습니다...)*"
                
        if target_fish == "네스호의 그림자, 네시 🦕" and env_state["CURRENT_WEATHER"] not in ["🌧️ 비", "🌫️ 안개"]:
            target_fish = "낡은 장화 🥾"
            bait_text += "\n*(거대한 그림자가 지나갔지만, 날씨가 맑아 깊은 곳으로 숨어버렸습니다...)*"

        # 황금 조류 효과: 판정 한도 +1.5초
        effective_rod_tier = rod_tier + 7.5 if "golden_tide" in active_buffs else rod_tier
        view = FishingView(interaction.user, target_fish, effective_rod_tier)
        await interaction.response.send_message(f"🌊 **{display_name}**님이 찌를 던졌습니다... 조용히 기다리세요.{bait_text}\n(내 낚싯대: Lv.{rod_tier} / 체력: {current_stamina-10}⚡)", view=view)
        
        wait_min, wait_max = (1, 3) if "cooldown_reduction" in active_buffs else (2, 6)
        wait_time = random.uniform(wait_min, wait_max)
        await asyncio.sleep(wait_time)
        
        view.is_bite = True
        view.start_time = datetime.datetime.now().timestamp()
        
        for item in view.children:
            item.label = "지금 챔질하세요!!!!"
            item.style = discord.ButtonStyle.success
            item.emoji = "‼️"
        
        try:
            msg = await interaction.edit_original_response(content="❗ **찌가 격렬하게 흔들립니다! 지금 누르세요!!!**", view=view)
            view.message = msg 
        except: 
            pass

    @app_commands.command(name="인벤토리", description="나 또는 특정 유저의 가방과 스탯을 확인합니다.")
    async def 인벤토리(self, interaction: discord.Interaction, 유저: discord.Member = None):
        target = 유저 or interaction.user
        coins, rod_tier, rating = await db.get_user_data(target.id)
        
        async with db.conn.execute("SELECT boat_tier FROM user_data WHERE user_id=?", (target.id,)) as cursor:
            res = await cursor.fetchone()
        current_tier = res[0] if res else 1
        tier_names = {1: "나룻배 🛶", 2: "어선 🚤", 3: "쇄빙선 🛳️", 4: "잠수함 ⛴️"}
        boat_str = tier_names.get(current_tier, f"Lv.{current_tier}")

        async with db.conn.execute("SELECT item_name, amount FROM inventory WHERE user_id=? AND amount > 0", (target.id,)) as cursor:
            items = await cursor.fetchall()
        
        embed = discord.Embed(title=f"🎒 {target.name}의 인벤토리", color=0x3498db)
        embed.add_field(name="🏆 전투 레이팅", value=f"`{rating} RP`", inline=True)
        embed.add_field(name="💰 보유 코인", value=f"`{coins:,} C`", inline=True)
        embed.add_field(name="⛵ 선박 등급", value=f"**{boat_str}**", inline=True)
        embed.add_field(name="🎣 낚싯대 레벨", value=f"`Lv.{rod_tier}`", inline=True)
        
        if items:
            item_list = "\n".join([f"• {name}: {amt}개" for name, amt in items])
            embed.add_field(name="🐟 물고기 도감", value=item_list, inline=False)
        else:
            embed.add_field(name="🐟 물고기 도감", value="텅 비었습니다...", inline=False)
            
        async with db.conn.execute("SELECT stamina, max_stamina FROM user_data WHERE user_id=?", (target.id,)) as cursor:
            stamina_res = await cursor.fetchone()
        stamina, max_stamina = stamina_res if stamina_res else (100, 100)
        embed.set_footer(text=f"⚡ 남은 체력: {stamina} / {max_stamina}")
        
        await interaction.response.send_message(embed=embed)

    @app_commands.command(name="휴식", description="여관에서 3,000 코인을 지불하고 행동력(체력)을 즉시 전부 회복합니다.")
    async def 휴식(self, interaction: discord.Interaction):
        coins, _, _ = await db.get_user_data(interaction.user.id)
        
        async with db.conn.execute("SELECT stamina, max_stamina FROM user_data WHERE user_id=?", (interaction.user.id,)) as cursor:
            res = await cursor.fetchone()
        stamina, max_stamina = res if res else (100, 100)
        
        if stamina >= max_stamina:
            return await interaction.response.send_message("✨ 체력이 이미 가득 차 있습니다! 휴식이 필요하지 않습니다.", ephemeral=True)
            
        cost = 3000
        if coins < cost:
            return await interaction.response.send_message(f"❌ 코인이 부족합니다. (필요: `{cost:,} C` / 현재: `{coins:,} C`)\n💡 시간이 지나면 10분마다 15씩 지속적으로 자연 회복됩니다.", ephemeral=True)
            
        await db.execute("UPDATE user_data SET coins = coins - ?, stamina = max_stamina WHERE user_id=?", (cost, interaction.user.id))
        await db.commit()
        
        await interaction.response.send_message(f"🛌 `{cost:,} C`를 지불하고 여관에서 푹 쉬었습니다! (체력 {max_stamina}⚡ 전부 회복 완료)")

    @app_commands.command(name="바다", description="현재 바다의 시간대와 날씨 환경을 확인합니다.")
    async def 바다(self, interaction: discord.Interaction):
        now_hour = datetime.datetime.now(kst).hour
        if 6 <= now_hour < 18: time_str = "☀️ 낮"
        elif 18 <= now_hour < 24: time_str = "🌙 밤"
        else: time_str = "🌑 새벽"

        embed = discord.Embed(title="🌊 현재 바다 상황", color=0x3498db)
        embed.add_field(name="현재 시간대", value=f"**{time_str}** (`{now_hour}시`)", inline=True)
        embed.add_field(name="현재 날씨", value=f"**{env_state['CURRENT_WEATHER']}**", inline=True)
        
        hints = ""
        if 0 <= now_hour < 4: hints += "- ⚠️ [신화] 우미보즈가 출몰할 수 있는 으스스한 시간입니다.\n"
        if env_state["CURRENT_WEATHER"] in ["🌧️ 비", "🌫️ 안개"]: hints += "- ⚠️ [미스터리] 네시가 활동하기 좋은 날씨입니다.\n"
        if not hints: hints = "- 평화로운 바다입니다. 낚시하기 딱 좋네요!"
        
        embed.add_field(name="생태계 정보", value=hints, inline=False)
        await interaction.response.send_message(embed=embed)

async def setup(bot):
    await bot.add_cog(FishingCog(bot))
