import discord
from discord.ext import commands
from discord import app_commands
import random
import datetime
import asyncio

import io
import os

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
        
        async with db.conn.execute("SELECT stamina, max_stamina, title, boat_tier FROM user_data WHERE user_id=?", (interaction.user.id,)) as cursor:
            stamina_res = await cursor.fetchone()
        current_stamina, max_stamina, title, current_tier = stamina_res if stamina_res else (100, 100, "", 1)
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

        # 뉴비 체력 소모 감소 (선박 티어 1인 경우 5소모, 그 외 10소모)
        stamina_cost = 5 if current_tier == 1 else 10
        await db.execute("UPDATE user_data SET stamina = stamina - ? WHERE user_id=?", (stamina_cost, interaction.user.id))

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
                    
                # 1. 강화 레벨 보너스
                if grade in ["에픽", "레전드", "신화"]:
                    base_prob *= (1 + (rod_tier * 0.1))

                # 2. [신규] 버프 효과 체크 (가속 포션, 특수 떡밥)
                async with db.conn.execute("SELECT buff_type FROM active_buffs WHERE user_id=? AND end_time > datetime('now', '+9 hours')", (interaction.user.id,)) as cursor:
                    active_buffs = [row[0] for row in await cursor.fetchall()]
                
                if "rare_boost" in active_buffs and grade not in ["일반", "희귀"]:
                    base_prob *= 1.5  # 특수 떡밥: 희귀 이상 확률 1.5배

                # 3. 날씨 연동 글로벌 확률 펌핑 (핫타임) - 밸런스 조정됨
                current_weather = env_state["CURRENT_WEATHER"]
                if current_weather == "☀️ 맑음" and grade in ["일반", "희귀"]:
                    base_prob *= 1.3  # 맑은 날: 일반/희귀 어종 확률 증가 (안정적 수입)
                elif current_weather == "🌧️ 비" and grade == "에픽":
                    base_prob *= 1.5  # 비: 에픽 확률 소폭 증가 (기존 2.0 → 1.5)
                elif current_weather == "🌫️ 안개" and grade == "레전드":
                    base_prob *= 2.0  # 안개: 레전드 확률 증가 (기존 3.0 → 2.0)
                elif current_weather == "🌩️ 폭풍우" and grade in ["신화", "태고", "환상", "미스터리"]:
                    base_prob *= 2.0  # 폭풍우: 최고급 확률 증가 (기존 5.0 → 2.0)

                # 4. [신규] 칭호 보너스 (해신: 신화/미스터리/태고 확률 1.3배)
                if title == "[해신]" and grade in ["신화", "미스터리", "태고", "환상"]:
                    base_prob *= 1.3

                candidates.append(fish)
                weights.append(base_prob)
            
        if not candidates:
            target_fish = "낡은 장화 🥾"
        else:
            target_fish = random.choices(candidates, weights=weights, k=1)[0]

        now_hour = datetime.datetime.now(kst).hour
        if target_fish == "바다의 원혼, 우미보즈 🌑" and not (0 <= now_hour < 4):
            target_fish = "낡은 장화 🥾"
            # 조건 미달로 잡어 낚인 경우 미끼 복구 (UX 개선)
            if bait_used != "none":
                await db.execute("UPDATE inventory SET amount = amount + 1 WHERE user_id=? AND item_name=?", (interaction.user.id, bait_used))
                await db.commit()
                bait_text = " *(조건 미달로 미끼가 보존되었습니다!)*"
            else:
                bait_text += "\n*(으스스한 기운이 맴돌았지만, 날이 밝아 흩어졌습니다...)*"
                
        if target_fish == "네스호의 그림자, 네시 🦕" and env_state["CURRENT_WEATHER"] not in ["🌧️ 비", "🌫️ 안개", "🌩️ 폭풍우"]:
            target_fish = "낡은 장화 🥾"
            # 조건 미달로 잡어 낚인 경우 미끼 복구 (UX 개선)
            if bait_used != "none":
                await db.execute("UPDATE inventory SET amount = amount + 1 WHERE user_id=? AND item_name=?", (interaction.user.id, bait_used))
                await db.commit()
                bait_text = " *(조건 미달로 미끼가 보존되었습니다!)*"
            else:
                bait_text += "\n*(거대한 그림자가 지나갔지만, 깊은 곳으로 숨어버렸습니다...)*"

        # 폭풍우 시 안내 추가
        if env_state["CURRENT_WEATHER"] == "🌩️ 폭풍우":
            bait_text += "\n*(거친 폭풍우가 몰아칩니다! 심연의 괴수들이 활동하기 시작합니다!)*"

        # 황금 조류 효과 및 요리 버프 연동
        effective_rod_tier = rod_tier + 7.5 if "golden_tide" in active_buffs else rod_tier
        
        if "fishing_speed_up" in active_buffs:
            effective_rod_tier += 2.0  # 낚시 속도 증가 버프 (난이도 하락)
            
        # 낚시 대기 시각 효과 (찌 애니메이션)
        view = FishingView(interaction.user, target_fish, effective_rod_tier)
        embed = discord.Embed(title="🎣 찌를 던졌습니다!", description=f"**{display_name}**님이 미끼를 던지고 입질을 기다립니다...{bait_text}", color=0x3498db)
        embed.set_image(url="https://media.giphy.com/media/v1.Y2lkPTc5MGI3NjExOHJqZ3R4Z3R4Z3R4Z3R4Z3R4Z3R4Z3R4Z3R4Z3R4Z3R4Z3R4Z3R4JmVwPXYxX2ludGVybmFsX2dpZl9ieV9pZCZjdD1n/l41lTfuxV5RWRsBPO/giphy.gif") # 낚시 대기 GIF
        embed.set_footer(text=f"내 낚싯대: Lv.{rod_tier} | 체력: {current_stamina-stamina_cost}⚡")
        
        await interaction.response.send_message(embed=embed, view=view)
        
        # 입질 대기 시간 계산
        if "fishing_speed_up" in active_buffs:
            wait_min, wait_max = 0.5, 2.0
        elif "cooldown_reduction" in active_buffs:
            wait_min, wait_max = 1.0, 3.0
        else:
            wait_min, wait_max = 2.0, 6.0
            
        # 칭호 보너스 (강태공: 대기 시간 15% 단축)
        if title == "[강태공]":
            wait_min *= 0.85
            wait_max *= 0.85

        wait_time = random.uniform(wait_min, wait_max)
        await asyncio.sleep(wait_time)
        
        view.is_bite = True
        view.start_time = datetime.datetime.now().timestamp()
        
        for item in view.children:
            item.label = "지금 챔질하세요!!!!"
            item.style = discord.ButtonStyle.success
            item.emoji = "‼️"
        
        try:
            # 입질 시 메시지 업데이트 (시각적 피드백 강화)
            embed = discord.Embed(title="❗ 입질 발생!!!!", description="**찌가 격렬하게 흔들립니다! 지금 당기세요!!!**", color=0xff0000)
            embed.set_image(url="https://media.giphy.com/media/v1.Y2lkPTc5MGI3NjExNHJqZ3R4Z3R4Z3R4Z3R4Z3R4Z3R4Z3R4Z3R4Z3R4Z3R4Z3R4Z3R4JmVwPXYxX2ludGVybmFsX2dpZl9ieV9pZCZjdD1n/l41lTfuxV5RWRsBPO/giphy.gif") # 입질 GIF (동일한거 쓰거나 다른걸로 교체)
            
            msg = await interaction.edit_original_response(content=None, embed=embed, view=view)
            view.message = msg 
        except: 
            pass

    @app_commands.command(name="인벤토리", description="나 또는 특정 유저의 가방과 스탯을 확인합니다.")
    async def 인벤토리(self, interaction: discord.Interaction, 유저: discord.Member = None):
        target = 유저 or interaction.user
        coins, rod_tier, rating = await db.get_user_data(target.id)
        
        async with db.conn.execute("SELECT boat_tier, stamina, max_stamina FROM user_data WHERE user_id=?", (target.id,)) as cursor:
            res = await cursor.fetchone()
        current_tier, stamina, max_stamina = res if res else (1, 100, 100)
        
        tier_names = {1: "나룻배 🛶", 2: "어선 🚤", 3: "쇄빙선 🛳️", 4: "전투함 ⚓", 5: "잠수함 ⛴️", 6: "차원함선 🛸"}
        boat_str = tier_names.get(current_tier, f"Lv.{current_tier}")

        async with db.conn.execute("SELECT item_name, amount, is_locked FROM inventory WHERE user_id=? AND amount > 0", (target.id,)) as cursor:
            items = await cursor.fetchall()
        
        title = await db.get_user_title(target.id)
        stats = (coins, rod_tier, rating, boat_str, stamina, max_stamina, title)
        
        from fishing_core.views import InventoryView
        view = InventoryView(interaction.user, target, items, stats)
        await interaction.response.send_message(embed=view.make_embed(), view=view)

    @app_commands.command(name="휴식", description="여관에서 코인을 지불하고 행동력(체력)을 즉시 전부 회복합니다. (일일 1회 무료!)")
    async def 휴식(self, interaction: discord.Interaction):
        coins, _, _ = await db.get_user_data(interaction.user.id)
        
        async with db.conn.execute("SELECT stamina, max_stamina, boat_tier, last_free_rest FROM user_data WHERE user_id=?", (interaction.user.id,)) as cursor:
            res = await cursor.fetchone()
        stamina = res[0] if res else 100
        max_stamina = res[1] if res else 100
        boat_tier = res[2] if res else 1
        last_free_rest = res[3] if res else ""
        
        if stamina >= max_stamina:
            return await interaction.response.send_message("✨ 체력이 이미 가득 차 있습니다! 휴식이 필요하지 않습니다.", ephemeral=True)
        
        # 일일 1회 무료 휴식 체크
        today = datetime.datetime.now(kst).strftime('%Y-%m-%d')
        is_free = (last_free_rest != today)
        
        # 선박 티어별 차등 비용 (가성비 개선)
        tier_costs = {1: 500, 2: 1000, 3: 1800, 4: 2800, 5: 4000}
        cost = tier_costs.get(boat_tier, 2500)
        
        if is_free:
            await db.execute("UPDATE user_data SET stamina = max_stamina, last_free_rest = ? WHERE user_id=?", (today, interaction.user.id))
            await db.commit()
            await interaction.response.send_message(f"🛌 오늘의 **무료 휴식**을 사용했습니다! (체력 {max_stamina}⚡ 전부 회복 완료)\n💡 *내일 다시 무료 휴식이 충전됩니다.*")
        else:
            if coins < cost:
                return await interaction.response.send_message(f"❌ 코인이 부족합니다. (필요: `{cost:,} C` / 현재: `{coins:,} C`)\n💡 오늘의 무료 휴식은 이미 사용했습니다. 시간이 지나면 10분마다 자연 회복됩니다.", ephemeral=True)
            
            await db.execute("UPDATE user_data SET coins = coins - ?, stamina = max_stamina WHERE user_id=?", (cost, interaction.user.id))
            await db.commit()
            await interaction.response.send_message(f"🛌 `{cost:,} C`를 지불하고 여관에서 푹 쉬었습니다! (체력 {max_stamina}⚡ 전부 회복 완료)")

    @app_commands.command(name="바다", description="현재 바다의 시간대와 날씨 환경을 확인합니다.")
    async def 바다(self, interaction: discord.Interaction):
        now_hour = datetime.datetime.now(kst).hour
        weather = env_state['CURRENT_WEATHER']
        
        if 6 <= now_hour < 18: 
            time_str = "☀️ 낮"
        elif 18 <= now_hour < 24: 
            time_str = "🌙 밤"
        else: 
            time_str = "🌑 새벽"

        weather_images = {
            "맑음": "clear.png",
            "흐림": "cloudy.jpg",
            "비": "rain.png",
            "폭풍우": "storm.png",
            "안개": "fog.png"
        }
        
        target_image = None
        for key, filename in weather_images.items():
            if key in weather:
                target_image = filename
                break
        
        file = None
        if target_image and os.path.exists(f"assets/weather/{target_image}"):
            file = discord.File(f"assets/weather/{target_image}", filename="weather.png")
            bg_url = "attachment://weather.png"
        else:
            # 로컬 파일이 없을 경우 기존 Unsplash URL 유지
            if 6 <= now_hour < 18: 
                bg_url = "https://images.unsplash.com/photo-1507525428034-b723cf961d3e?w=800"
            elif 18 <= now_hour < 24: 
                bg_url = "https://images.unsplash.com/photo-1500417148159-aa994266934d?w=800"
            else: 
                bg_url = "https://images.unsplash.com/photo-1494948141550-9a3b2bc87860?w=800"

            if "폭풍우" in weather: bg_url = "https://images.unsplash.com/photo-1466611653911-95081537e5b7?w=800"
            elif "비" in weather: bg_url = "https://images.unsplash.com/photo-1515694346937-94d85e41e6f0?w=800"

        embed = discord.Embed(title="🌊 현재 바다 상황", color=0x3498db)
        embed.add_field(name="현재 시간대", value=f"**{time_str}** (`{now_hour}시`)", inline=True)
        embed.add_field(name="현재 날씨", value=f"**{weather}**", inline=True)
        
        hints = ""
        if 0 <= now_hour < 4: hints += "- ⚠️ [신화] 우미보즈가 출몰할 수 있는 으스스한 시간입니다.\n"
        if weather in ["🌧️ 비", "🌫️ 안개"]: hints += "- ⚠️ [미스터리] 네시가 활동하기 좋은 날씨입니다.\n"
        if not hints: hints = "- 평화로운 바다입니다. 낚시하기 딱 좋네요!"
        
        embed.add_field(name="생태계 정보", value=hints, inline=False)
        embed.set_image(url=bg_url)
        
        if file:
            await interaction.response.send_message(embed=embed, file=file)
        else:
            await interaction.response.send_message(embed=embed)

    @app_commands.command(name="기상예측", description="기상청의 위성 자료를 분석하여 향후 3시간의 날씨 변화를 예측합니다. (비용: 3,000 C)")
    async def 기상예측(self, interaction: discord.Interaction):
        coins, _, _ = await db.get_user_data(interaction.user.id)
        if coins < 3000:
            return await interaction.response.send_message(f"❌ 코인이 부족합니다. (필요: `3,000 C` / 현재: `{coins:,} C`)", ephemeral=True)
        
        await db.execute("UPDATE user_data SET coins = coins - 3000 WHERE user_id=?", (interaction.user.id,))
        await db.commit()
        
        from fishing_core.shared import WEATHER_TYPES
        # 현재 시간 기준으로 1시간, 2시간, 3시간 뒤 날씨를 시뮬레이션 (랜덤이지만 유저에게는 예측으로 보여줌)
        # 실제 시스템은 1시간마다 weather_update_loop가 돌며 변경하므로, 
        # 이 예측을 실제 적용하기 위해선 env_state에 큐를 쌓아두는 것이 좋음.
        
        if "WEATHER_QUEUE" not in env_state:
            env_state["WEATHER_QUEUE"] = [random.choices(WEATHER_TYPES, weights=[40, 25, 20, 5, 10], k=1)[0] for _ in range(3)]
        
        q = env_state["WEATHER_QUEUE"]
        embed = discord.Embed(title="📡 수산시장 기상청 정밀 예보", color=0x3498db)
        embed.description = "위성 사진과 기압골 데이터를 분석한 결과입니다."
        embed.add_field(name="1시간 뒤", value=q[0], inline=True)
        embed.add_field(name="2시간 뒤", value=q[1], inline=True)
        embed.add_field(name="3시간 뒤", value=q[2], inline=True)
        embed.set_footer(text="⚠️ 기상 상황은 급변할 수 있으며, 기우제 발생 시 예보가 빗나갈 수 있습니다.")
        
        await interaction.response.send_message(embed=embed)

    @app_commands.command(name="기우제", description="전 서버 유저들과 힘을 합쳐 코인을 모으고 바다의 날씨를 강제로 변경합니다!")
    async def 기우제(self, interaction: discord.Interaction, 기부금: int):
        if 기부금 < 1000:
            return await interaction.response.send_message("❌ 최소 기부금은 `1,000 C`입니다.", ephemeral=True)
        
        coins, _, _ = await db.get_user_data(interaction.user.id)
        if coins < 기부금:
            return await interaction.response.send_message(f"❌ 코인이 부족합니다. (현재 보유: `{coins:,} C`)", ephemeral=True)
        
        await db.execute("UPDATE user_data SET coins = coins - ? WHERE user_id=?", (기부금, interaction.user.id))
        
        # 현재 누적액 확인
        async with db.conn.execute("SELECT value FROM server_state WHERE key='RITUAL_COINS'") as cursor:
            res = await cursor.fetchone()
        current_total = int(res[0]) if res else 0
        new_total = current_total + 기부금
        
        target_amount = 500000 # 기우제 성공 목표액
        
        await db.execute("INSERT OR REPLACE INTO server_state (key, value) VALUES ('RITUAL_COINS', ?)", (str(new_total),))
        await db.commit()
        
        if new_total >= target_amount:
            # 기우제 성공! 날씨 변경 (폭풍우로 고정)
            await db.execute("INSERT OR REPLACE INTO server_state (key, value) VALUES ('RITUAL_COINS', '0')", ())
            env_state["CURRENT_WEATHER"] = "🌩️ 폭풍우"
            # 예보 큐 초기화
            env_state.pop("WEATHER_QUEUE", None)
            await db.commit()
            
            embed = discord.Embed(title="🌩️ 기우제 성공! 하늘이 응답했습니다!", color=0xffd700)
            embed.description = f"**{interaction.user.name}**님의 마지막 정성이 닿았습니다!\n총 `{new_total:,} C`가 모여 바다에 **강력한 폭풍우**가 몰아치기 시작합니다!"
            embed.set_image(url="https://media.giphy.com/media/v1.Y2lkPTc5MGI3NjExNHJqZ3R4Z3R4Z3R4Z3R4Z3R4Z3R4Z3R4Z3R4Z3R4Z3R4Z3R4Z3R4JmVwPXYxX2ludGVybmFsX2dpZl9ieV9pZCZjdD1n/l41lTfuxV5RWRsBPO/giphy.gif") # 천둥 이미지 (예시)
            await interaction.response.send_message(embed=embed)
            await interaction.channel.send("📢 **[시스템]** 기우제 성공으로 인해 날씨가 **🌩️ 폭풍우**로 고정되었습니다! (1시간 지속)")
        else:
            embed = discord.Embed(title="🙏 기우제 정성 모집 중...", color=0x3498db)
            embed.description = f"**{interaction.user.name}**님이 `{기부금:,} C`를 기부하셨습니다!\n\n현재 모인 정성: `{new_total:,} / {target_amount:,} C`\n목표 도달 시 바다에 **폭풍우**가 찾아옵니다!"
            progress = int((new_total / target_amount) * 10)
            bar = "🟦" * progress + "⬜" * (10 - progress)
            embed.add_field(name="진행도", value=f"{bar} ({progress*10}%)", inline=False)
            await interaction.response.send_message(embed=embed)

async def setup(bot):
    await bot.add_cog(FishingCog(bot))
