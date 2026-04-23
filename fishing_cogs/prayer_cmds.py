import discord
from discord.ext import commands
from discord import app_commands
from fishing_core.database import db
from fishing_core.shared import FISH_DATA, kst
import random
import datetime

class PrayerCommands(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        # 스페셜 물고기 풀 (이름과 개별 가중치)
        # 총합 3.6% (0.036)
        self.special_pool = {
            "용왕 🐉👑": 0.001,        # 0.1%
            "심연의 천사, 라합 🐉⚖️": 0.002,   # 0.2%
            "구원의 뿔, 마츠야 🐟🦄": 0.003,    # 0.3%
            "신기루의 지배자, 신(蜃) 🦪🌫️": 0.004, # 0.4%
            "뼈 고래, 바케쿠지라 🐋💀": 0.005,  # 0.5%
            "굽이치는 수호자, 타니와 🦎🌀": 0.006, # 0.6%
            "성난 호수의 주인, 아바이아 🐍🌧️": 0.007, # 0.7%
            "눈밭의 범고래, 아클루트 🐋🐺": 0.008   # 0.8%
        }

    async def _sacrifice_fish_by_grade(self, user_id, target_grade, count):
        """특정 등급의 물고기를 지정된 수량만큼 제물로 바침 (잠금되지 않은 것 우선)"""
        async with db.conn.execute("SELECT item_name, amount FROM inventory WHERE user_id = ? AND amount > 0 AND is_locked = 0", (user_id,)) as cursor:
            items = await cursor.fetchall()
        
        candidates = []
        for item_name, amount in items:
            fish_info = FISH_DATA.get(item_name)
            if fish_info and fish_info.get("grade") == target_grade:
                candidates.append({"name": item_name, "amount": amount})
        
        if sum(c["amount"] for c in candidates) < count:
            return False
            
        remaining = count
        for c in candidates:
            if remaining <= 0: break
            take = min(c["amount"], remaining)
            if take == c["amount"]:
                await db.execute("DELETE FROM inventory WHERE user_id = ? AND item_name = ?", (user_id, c["name"]))
            else:
                await db.execute("UPDATE inventory SET amount = amount - ? WHERE user_id = ? AND item_name = ?", (take, user_id, c["name"]))
            remaining -= take
        return True

    async def _sacrifice_ancient_plus(self, user_id):
        """태고 이상(태고, 환상, 미스터리, 신화) 물고기 1마리를 제물로 바침"""
        async with db.conn.execute("SELECT item_name, amount FROM inventory WHERE user_id = ? AND amount > 0 AND is_locked = 0", (user_id,)) as cursor:
            items = await cursor.fetchall()
        
        target_grades = ['태고', '환상', '미스터리', '신화']
        for item_name, amount in items:
            fish_info = FISH_DATA.get(item_name)
            if fish_info and fish_info.get("grade") in target_grades:
                if amount == 1:
                    await db.execute("DELETE FROM inventory WHERE user_id = ? AND item_name = ?", (user_id, item_name))
                else:
                    await db.execute("UPDATE inventory SET amount = amount - 1 WHERE user_id = ? AND item_name = ?", (user_id, item_name))
                return True
        return False

    @app_commands.command(name="바다기도", description="심연의 바다에 제물을 바쳐 전설 속의 신수를 부릅니다.")
    @app_commands.choices(제물=[
        app_commands.Choice(name="💰 40,000 코인 (기본 확률 3.6%)", value="gold"),
        app_commands.Choice(name="🟣 에픽 어종 10마리 (+5% 확률 보너스)", value="epic"),
        app_commands.Choice(name="🟡 전설 어종 3마리 (+10% 확률 보너스)", value="legend"),
        app_commands.Choice(name="🔴 태고 이상 어종 1마리 (+25% 확률 보너스)", value="ancient")
    ])
    async def pray_to_sea(self, interaction: discord.Interaction, 제물: app_commands.Choice[str]):
        user_id = interaction.user.id
        await interaction.response.defer()

        bonus_chance = 0.0
        sacrifice_success = False
        fail_reason = ""

        # 1. 제물 지불 로직
        if 제물.value == "gold":
            async with db.conn.execute("SELECT coins FROM user_data WHERE user_id = ?", (user_id,)) as cursor:
                res = await cursor.fetchone()
            coins = res[0] if res else 0
            if coins < 40000:
                fail_reason = "❌ 코인이 부족합니다! (40,000 C 필요)"
            else:
                await db.execute("UPDATE user_data SET coins = coins - 40000 WHERE user_id = ?", (user_id,))
                sacrifice_success = True
                bonus_chance = 0.0

        elif 제물.value == "epic":
            if await self._sacrifice_fish_by_grade(user_id, "에픽", 10):
                sacrifice_success = True
                bonus_chance = 0.05
            else:
                fail_reason = "❌ 제물이 부족합니다! (잠금되지 않은 **에픽** 등급 물고기 10마리 필요)"

        elif 제물.value == "legend":
            if await self._sacrifice_fish_by_grade(user_id, "레전드", 3):
                sacrifice_success = True
                bonus_chance = 0.10
            else:
                fail_reason = "❌ 제물이 부족합니다! (잠금되지 않은 **레전드** 등급 물고기 3마리 필요)"

        elif 제물.value == "ancient":
            if await self._sacrifice_ancient_plus(user_id):
                sacrifice_success = True
                bonus_chance = 0.25
            else:
                fail_reason = "❌ 제물이 부족합니다! (잠금되지 않은 **태고 이상** 등급 물고기 1마리 필요)"

        if not sacrifice_success:
            return await interaction.followup.send(fail_reason)

        await db.commit()

        # 2. 확률 계산
        base_chance = sum(self.special_pool.values()) # 0.036 (3.6%)
        total_success_chance = base_chance + bonus_chance

        # 3. 결과 판정
        roll = random.random()
        
        if roll <= total_success_chance:
            # 성공! 가중치에 따라 어종 결정
            names = list(self.special_pool.keys())
            weights = list(self.special_pool.values())
            caught_fish = random.choices(names, weights=weights, k=1)[0]
            
            # 인벤토리 추가 및 도감 등록
            await db.execute("INSERT INTO inventory (user_id, item_name, amount) VALUES (?, ?, 1) ON CONFLICT(user_id, item_name) DO UPDATE SET amount = amount + 1", (user_id, caught_fish))
            await db.execute("INSERT OR IGNORE INTO fish_dex (user_id, item_name) VALUES (?, ?)", (user_id, caught_fish))
            
            # 기록 갱신 (크기 생성)
            power = FISH_DATA.get(caught_fish, {}).get("power", 1000)
            fish_size = round(random.uniform(power * 1.5, power * 2.5), 2)
            await db.execute("INSERT INTO fish_records (user_id, item_name, max_size) VALUES (?, ?, ?) ON CONFLICT(user_id, item_name) DO UPDATE SET max_size = MAX(max_size, excluded.max_size)", (user_id, caught_fish, fish_size))
            
            await db.commit()

            embed = discord.Embed(
                title="🌊 심연의 바다가 요동칩니다!", 
                description=f"간절한 기도가 바다의 심장부에 닿았습니다.\n수평선 너머에서 **전설 속의 신수**가 모습을 드러냅니다!\n\n🎉 **획득:** `{caught_fish}` (`{fish_size} cm`)",
                color=0x00FFFF
            )
            embed.set_thumbnail(url="https://media.giphy.com/media/v1.Y2lkPTc5MGI3NjExOHJqZ3R4Z3R4Z3R4Z3R4Z3R4Z3R4Z3R4Z3R4Z3R4Z3R4Z3R4Z3R4JmVwPXYxX2ludGVybmFsX2dpZl9ieV9pZCZjdD1n/l41lTfuxV5RWRsBPO/giphy.gif")
            embed.set_footer(text=f"적용 확률: {total_success_chance*100:.1f}% (보너스: +{bonus_chance*100:.1f}%)")
            await interaction.followup.send(content=f"{interaction.user.mention}", embed=embed)
            
            # 공지 (용왕 획득 시)
            if caught_fish == "용왕 🐉👑":
                await interaction.channel.send(f"📢 **[전설]** {interaction.user.name}님이 기도를 통해 바다의 진정한 주인, **{caught_fish}**를 알현했습니다!!!")

        else:
            embed = discord.Embed(
                title="🌑 바다가 고요하게 가라앉습니다...", 
                description="당신의 정성은 거품이 되어 심해로 흩어졌습니다. 바다는 아무런 응답이 없습니다.",
                color=0x2b2d31
            )
            embed.set_footer(text=f"성공 확률: {total_success_chance*100:.1f}% | 꽝 확률: {(1-total_success_chance)*100:.1f}%")
            await interaction.followup.send(content=f"{interaction.user.mention}", embed=embed)

async def setup(bot):
    await bot.add_cog(PrayerCommands(bot))
