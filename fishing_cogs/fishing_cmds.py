from fishing_core.utils import EmbedFactory
import asyncio
import datetime
import random

import discord
from discord import app_commands
from discord.ext import commands

from fishing_core.database import db
from fishing_core.services.fishing_service import FishingService
from fishing_core.shared import FISH_DATA, WEATHER_TYPES, env_state, kst
from fishing_core.utils import bait_autocomplete, net_autocomplete
from fishing_core.views import FishingView, InventoryView


class FishingCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.equipped_baits = {}

    async def _cast_net(self, interaction: discord.Interaction, net_name: str, 수량: int = 1):
        if 수량 < 1:
            return await interaction.response.send_message("❌ 최소 1개 이상의 그물망을 던져야 합니다.", ephemeral=True)
            
        await db.get_user_data(interaction.user.id)
        async with db.conn.execute("SELECT stamina FROM user_data WHERE user_id=?", (interaction.user.id,)) as cursor:
            stamina_row = await cursor.fetchone()
        current_stamina = stamina_row[0] if stamina_row else 150

        stamina_cost = (12 if net_name == "초급 그물망 🕸️" else 20) * 수량
        if current_stamina < stamina_cost:
            return await interaction.response.send_message(
                f"❌ 행동력이 부족합니다! (필요: {stamina_cost}⚡ / 현재: {current_stamina}⚡)\n"
                "💡 `/휴식`, `/휴`, 에너지 드링크로 회복한 뒤 다시 시도해보세요.",
                ephemeral=True,
            )

        async with db.conn.execute(
            "SELECT amount FROM inventory WHERE user_id=? AND item_name=?",
            (interaction.user.id, net_name),
        ) as cursor:
            net_row = await cursor.fetchone()
        if not net_row or net_row[0] < 수량:
            return await interaction.response.send_message(f"❌ **{net_name}**이(가) 부족합니다! (보유: {net_row[0] if net_row else 0}개 / 필요: {수량}개)", ephemeral=True)

        pools = {
            "초급 그물망 🕸️": {
                "draws": 5 * 수량,
                "weights": {
                    "낡은 고철 ⚙️": 20,
                    "바지락 🐚": 18,
                    "홍합 🐚": 18,
                    "새우 🦐": 16,
                    "멸치 🐟": 15,
                    "까나리 🐟": 15,
                    "정어리 🐟": 12,
                    "소라 🐚": 10,
                    "가리비 🐚": 8,
                    "해적의 금화 🪙": 3,
                },
            },
            "튼튼한 그물망 🕸️": {
                "draws": 10 * 수량,
                "weights": {
                    "낡은 고철 ⚙️": 18,
                    "바지락 🐚": 16,
                    "홍합 🐚": 16,
                    "새우 🦐": 14,
                    "가리비 🐚": 12,
                    "소라 🐚": 12,
                    "꽃게 🦀": 10,
                    "쭈꾸미 🐙": 10,
                    "전갱이 🐟": 10,
                    "싱싱한 고등어 🐟": 8,
                    "해적의 금화 🪙": 4,
                },
            },
        }

        config = pools[net_name]
        candidates = list(config["weights"].keys())
        weights = list(config["weights"].values())
        catches = random.choices(candidates, weights=weights, k=config["draws"])

        summary: dict[str, int] = {}
        for item in catches:
            summary[item] = summary.get(item, 0) + 1

        await db.execute("UPDATE user_data SET stamina = stamina - ? WHERE user_id=?", (stamina_cost, interaction.user.id))
        await db.execute("UPDATE inventory SET amount = amount - ? WHERE user_id=? AND item_name=?", (수량, interaction.user.id, net_name))

        insert_rows = [(interaction.user.id, item, amount, amount) for item, amount in summary.items()]
        await db.executemany(
            "INSERT INTO inventory (user_id, item_name, amount) VALUES (?, ?, ?) "
            "ON CONFLICT(user_id, item_name) DO UPDATE SET amount = amount + ?",
            insert_rows,
        )
        await db.commit()

        result_lines = []
        total_value = 0
        for item, amount in summary.items():
            unit_price = FISH_DATA.get(item, {}).get("price", 0)
            total_value += unit_price * amount
            result_lines.append(f"• **{item}** x{amount}")

        embed = EmbedFactory.build(title=f"🕸️ {net_name} {수량}개 투망 결과", type="info")
        embed.description = "그물망을 넓게 던져 한 번에 여러 자원을 건져 올렸습니다."
        embed.add_field(name="획득 목록", value="\n".join(result_lines), inline=False)
        embed.add_field(name="예상 판매 가치", value=f"`{total_value:,} C`", inline=True)
        embed.add_field(name="소모 행동력", value=f"`{stamina_cost}⚡`", inline=True)
        embed.set_footer(text="그물망은 빠른 자원 수급용입니다. 희귀 대물은 일반 낚시로 노려보세요.")
        await interaction.response.send_message(embed=embed)

    async def _show_inventory(self, interaction: discord.Interaction, target: discord.Member):
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

        view = InventoryView(interaction.user, target, items, stats)
        await interaction.response.send_message(embed=view.make_embed(), view=view)

    async def _rest_user(self, interaction: discord.Interaction):
        coins, _, _ = await db.get_user_data(interaction.user.id)

        async with db.conn.execute("SELECT stamina, max_stamina, boat_tier, last_free_rest FROM user_data WHERE user_id=?", (interaction.user.id,)) as cursor:
            res = await cursor.fetchone()
        stamina = res[0] if res else 100
        max_stamina = res[1] if res else 100
        boat_tier = res[2] if res else 1
        last_free_rest = res[3] if res else ""

        if stamina >= max_stamina:
            return await interaction.response.send_message("✨ 체력이 이미 가득 차 있습니다! 휴식이 필요하지 않습니다.", ephemeral=True)

        today = datetime.datetime.now(kst).strftime('%Y-%m-%d')
        is_free = last_free_rest != today

        tier_costs = {1: 500, 2: 1000, 3: 1800, 4: 2800, 5: 4000}
        cost = tier_costs.get(boat_tier, 2500)

        if is_free:
            await db.execute("UPDATE user_data SET stamina = max_stamina, last_free_rest = ? WHERE user_id=?", (today, interaction.user.id))
            await db.commit()
            return await interaction.response.send_message(f"🛌 오늘의 **무료 휴식**을 사용했습니다! (체력 {max_stamina}⚡ 전부 회복 완료)\n💡 *내일 다시 무료 휴식이 충전됩니다.*")

        if coins < cost:
            return await interaction.response.send_message(f"❌ 코인이 부족합니다. (필요: `{cost:,} C` / 현재: `{coins:,} C`)\n💡 오늘의 무료 휴식은 이미 사용했습니다. 시간이 지나면 10분마다 자연 회복됩니다.", ephemeral=True)

        await db.execute("UPDATE user_data SET coins = coins - ?, stamina = max_stamina WHERE user_id=?", (cost, interaction.user.id))
        await db.commit()
        await interaction.response.send_message(f"🛌 `{cost:,} C`를 지불하고 여관에서 푹 쉬었습니다! (체력 {max_stamina}⚡ 전부 회복 완료)")

    async def _forecast_weather(self, interaction: discord.Interaction):
        coins, _, _ = await db.get_user_data(interaction.user.id)
        if coins < 3000:
            return await interaction.response.send_message(f"❌ 코인이 부족합니다. (필요: `3,000 C` / 현재: `{coins:,} C`)", ephemeral=True)

        await db.execute("UPDATE user_data SET coins = coins - 3000 WHERE user_id=?", (interaction.user.id,))
        await db.commit()

        if "WEATHER_QUEUE" not in env_state:
            env_state["WEATHER_QUEUE"] = [random.choices(WEATHER_TYPES, weights=[40, 25, 20, 5, 10], k=1)[0] for _ in range(3)]

        q = env_state["WEATHER_QUEUE"]
        embed = EmbedFactory.build(title="📡 수산시장 기상청 정밀 예보", type="info")
        embed.description = "위성 사진과 기압골 데이터를 분석한 결과입니다."
        embed.add_field(name="1시간 뒤", value=q[0], inline=True)
        embed.add_field(name="2시간 뒤", value=q[1], inline=True)
        embed.add_field(name="3시간 뒤", value=q[2], inline=True)
        embed.set_footer(text="⚠️ 기상 상황은 급변할 수 있으며, 기우제 발생 시 예보가 빗나갈 수 있습니다.")

        await interaction.response.send_message(embed=embed)

    @app_commands.command(name="미끼장착", description="자동으로 소모할 미끼를 장착하거나 해제합니다.")
    @app_commands.checks.cooldown(1, 3.0, key=lambda i: i.user.id)
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
    @app_commands.checks.cooldown(1, 3.0, key=lambda i: i.user.id)
    @app_commands.autocomplete(사용할미끼=bait_autocomplete)
    async def 낚시(self, interaction: discord.Interaction, 사용할미끼: str = "none"):
        _, rod_tier, _ = await db.get_user_data(interaction.user.id)

        async with db.conn.execute("SELECT stamina, title, boat_tier, current_region FROM user_data WHERE user_id=?", (interaction.user.id,)) as cursor:
            stamina_res = await cursor.fetchone()
        current_stamina, title, current_tier, region = stamina_res if stamina_res else (100, "", 1, "연안")
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
                return await interaction.response.send_message(f"❌ 가방에 **{bait_used}**가 없습니다! 상점에서 먼저 구매해주세요.", ephemeral=True)

            await db.execute("UPDATE inventory SET amount = amount - 1 WHERE user_id=? AND item_name=?", (interaction.user.id, bait_used))
            await db.commit()
            bait_text = f" ({bait_used} 사용됨!)"

        now_str = datetime.datetime.now(kst).strftime('%Y-%m-%d %H:%M:%S')
        async with db.conn.execute("SELECT buff_type FROM active_buffs WHERE user_id=? AND end_time > ?", (interaction.user.id, now_str)) as cursor:
            active_buffs = [row[0] for row in await cursor.fetchall()]

        candidates, weights = FishingService.calculate_fish_probabilities(
            interaction.user.id, rod_tier, bait_used, active_buffs, title, env_state["CURRENT_WEATHER"], region
        )

        target_fish = "낡은 장화 🥾" if not candidates else random.choices(candidates, weights=weights, k=1)[0]

        now_hour = datetime.datetime.now(kst).hour
        if target_fish == "바다의 원혼, 우미보즈 🌑" and not (0 <= now_hour < 4):
            target_fish = "낡은 장화 🥾"
            if bait_used != "none":
                await db.execute("UPDATE inventory SET amount = amount + 1 WHERE user_id=? AND item_name=?", (interaction.user.id, bait_used))
                await db.commit()
                bait_text = " *(조건 미달로 미끼가 보존되었습니다!)*"
            else:
                bait_text += "\n*(으스스한 기운이 맴돌았지만, 날이 밝아 흩어졌습니다...)*"

        if target_fish == "네스호의 그림자, 네시 🦕" and env_state["CURRENT_WEATHER"] not in ["🌧️ 비", "🌫️ 안개", "🌩️ 폭풍우"]:
            target_fish = "낡은 장화 🥾"
            if bait_used != "none":
                await db.execute("UPDATE inventory SET amount = amount + 1 WHERE user_id=? AND item_name=?", (interaction.user.id, bait_used))
                await db.commit()
                bait_text = " *(조건 미달로 미끼가 보존되었습니다!)*"
            else:
                bait_text += "\n*(거대한 그림자가 지나갔지만, 깊은 곳으로 숨어버렸습니다...)*"

        if env_state["CURRENT_WEATHER"] == "🌩️ 폭풍우":
            bait_text += "\n*(거친 폭풍우가 몰아칩니다! 심연의 괴수들이 활동하기 시작합니다!)*"

        effective_rod_tier = rod_tier + 7.5 if "golden_tide" in active_buffs else rod_tier
        if "fishing_speed_up" in active_buffs:
            effective_rod_tier += 2.0
        if "common_success_boost" in active_buffs:
            effective_rod_tier += 3.0
        elif "premium_success_boost" in active_buffs:
            effective_rod_tier += 8.0
        if "prayer_success_boost" in active_buffs:
            effective_rod_tier += 2.0

        stamina_cost = 5 if current_tier == 1 else 10
        if "stamina_save_1" in active_buffs:
            stamina_cost = max(1, stamina_cost - 1)
        elif "stamina_save_2" in active_buffs:
            stamina_cost = max(1, stamina_cost - 2)
        if "prayer_stamina_save" in active_buffs:
            stamina_cost = max(1, stamina_cost - 1)
        
        if current_stamina < stamina_cost:
            return await interaction.response.send_message(f"❌ 행동력이 부족합니다! (필요: {stamina_cost}⚡ / 현재: {current_stamina}⚡)\n`/출석`을 하거나 상점에서 에너지 드링크를 구매하세요.", ephemeral=True)

        await db.execute("UPDATE user_data SET stamina = stamina - ? WHERE user_id=?", (stamina_cost, interaction.user.id))

        double_catch = False
        if ("double_catch_chance" in active_buffs and random.random() < 0.25) or \
           ("prayer_double_catch" in active_buffs and random.random() < 0.20):
            double_catch = True

        view = FishingView(interaction.user, target_fish, effective_rod_tier, self.bot)
        view.double_catch = double_catch
        embed = EmbedFactory.build(title="🎣 찌를 던졌습니다!", description=f"**{display_name}**님이 미끼를 던지고 입질을 기다립니다...{bait_text}", type="info")
        embed.set_image(url="https://media.giphy.com/media/v1.Y2lkPTc5MGI3NjExNHJqZ3R4Z3R4Z3R4Z3R4Z3R4Z3R4Z3R4Z3R4Z3R4Z3R4Z3R4JmVwPXYxX2ludGVybmFsX2dpZl9ieV9pZCZjdD1n/l41lTfuxV5RWRsBPO/giphy.gif")
        embed.set_footer(text=f"내 낚싯대: Lv.{rod_tier} | 체력: {current_stamina-stamina_cost}⚡")

        await interaction.response.send_message(embed=embed, view=view)

        # [신규] 떠돌이 상인 소문 시스템 (3% 확률로 상인 출현/유지 소식)
        if random.random() < 0.03:
            market_cog = self.bot.get_cog("MarketCog")
            if market_cog:
                try:
                    await market_cog.trigger_merchant_encounter(interaction)
                except Exception:
                    pass

        # 입질 대기 시간 계산
        if "wet_clothes" in active_buffs:
            bait_text += "\n*(🌊 바다에 빠져 몸이 무겁습니다... 낚시 속도가 느려집니다!)*"

        wait_time = FishingService.get_waiting_time(active_buffs, title)
        await asyncio.sleep(wait_time)

        if view.is_finished() or view.resolved:
            return

        view.is_bite = True
        view.start_time = datetime.datetime.now(kst).timestamp()

        for item in view.children:
            item.label = "지금 챔질하세요!!!!"
            item.style = discord.ButtonStyle.success
            item.emoji = "‼️"

        try:
            embed = EmbedFactory.build(title="❗ 입질 발생!!!!", description="**찌가 격렬하게 흔들립니다! 지금 당기세요!!!**", type="error")
            embed.set_image(url="https://media.giphy.com/media/v1.Y2lkPTc5MGI3NjExNHJqZ3R4Z3R4Z3R4Z3R4Z3R4Z3R4Z3R4Z3R4Z3R4Z3R4Z3R4JmVwPXYxX2ludGVybmFsX2dpZl9ieV9pZCZjdD1n/l41lTfuxV5RWRsBPO/giphy.gif")
            msg = await interaction.edit_original_response(content=None, embed=embed, view=view)
            view.message = msg
        except Exception:
            pass

    @app_commands.command(name="그물망", description="그물망을 던져 잡어와 자원을 한 번에 건져올립니다.")
    @app_commands.autocomplete(그물종류=net_autocomplete)
    async def 그물망(self, interaction: discord.Interaction, 그물종류: str, 수량: int = 1):
        await self._cast_net(interaction, 그물종류, 수량)

    @app_commands.command(name="그물", description="`/그물망`의 축약 명령어입니다.")
    @app_commands.autocomplete(그물종류=net_autocomplete)
    async def 그물(self, interaction: discord.Interaction, 그물종류: str, 수량: int = 1):
        await self._cast_net(interaction, 그물종류, 수량)

    @app_commands.command(name="인벤토리", description="나 또는 특정 유저의 가방과 스탯을 확인합니다.")
    @app_commands.checks.cooldown(1, 5.0, key=lambda i: i.user.id)
    async def 인벤토리(self, interaction: discord.Interaction, 유저: discord.Member = None):
        target = 유저 or interaction.user
        await self._show_inventory(interaction, target)

    @app_commands.command(name="인벤", description="`/인벤토리`의 축약 명령어입니다.")
    @app_commands.checks.cooldown(1, 5.0, key=lambda i: i.user.id)
    async def 인벤(self, interaction: discord.Interaction, 유저: discord.Member = None):
        target = 유저 or interaction.user
        await self._show_inventory(interaction, target)

    @app_commands.command(name="휴식", description="여관에서 코인을 지불하고 행동력(체력)을 즉시 전부 회복합니다. (일일 1회 무료!)")
    @app_commands.checks.cooldown(1, 5.0, key=lambda i: i.user.id)
    async def 휴식(self, interaction: discord.Interaction):
        await self._rest_user(interaction)

    @app_commands.command(name="휴", description="`/휴식`의 축약 명령어입니다.")
    @app_commands.checks.cooldown(1, 5.0, key=lambda i: i.user.id)
    async def 휴(self, interaction: discord.Interaction):
        await self._rest_user(interaction)


    @app_commands.command(name="이동", description="원하는 해역으로 이동합니다. (선박 등급 필요 및 체력 20 소모)")
    @app_commands.choices(해역=[
        app_commands.Choice(name="연안 (Lv.1+)", value="연안"),
        app_commands.Choice(name="먼 바다 (Lv.2+)", value="먼 바다"),
        app_commands.Choice(name="산호초 (Lv.3+)", value="산호초"),
        app_commands.Choice(name="심해 (Lv.4+)", value="심해"),
        app_commands.Choice(name="북해 (Lv.5+)", value="북해"),
    ])
    async def 이동(self, interaction: discord.Interaction, 해역: app_commands.Choice[str]):
        user_id = interaction.user.id
        async with db.conn.execute("SELECT boat_tier, current_region, stamina FROM user_data WHERE user_id=?", (user_id,)) as cursor:
            res = await cursor.fetchone()
        
        boat_tier, current_region, stamina = res if res else (1, "연안", 100)
        
        if current_region == 해역.value:
            return await interaction.response.send_message(f"📍 이미 **{해역.value}**에 위치해 있습니다.", ephemeral=True)
            
        target_config = FishingService.REGION_CONFIG.get(해역.value)
        if not target_config:
            return await interaction.response.send_message("❌ 존재하지 않는 해역입니다.", ephemeral=True)
            
        min_tier = target_config["min_tier"]
        if boat_tier < min_tier:
            return await interaction.response.send_message(f"🚫 **{해역.value}**에 진입하기 위해서는 선박 Lv.{min_tier} 이상의 배가 필요합니다. (현재: Lv.{boat_tier})", ephemeral=True)
            
        if stamina < 20:
            return await interaction.response.send_message(f"🔋 항해에 필요한 체력이 부족합니다. (필요: 20⚡ / 현재: {stamina}⚡)", ephemeral=True)
            
        await db.execute("UPDATE user_data SET current_region = ?, stamina = stamina - 20 WHERE user_id = ?", (해역.value, user_id))
        await db.commit()
        
        embed = EmbedFactory.build(title="🛳️ 항해를 시작합니다!", description=f"**{current_region}**에서 출발하여 **{해역.value}**에 무사히 도착했습니다!", type="info")
        embed.add_field(name="⛽ 소모 체력", value="-20⚡", inline=True)
        embed.add_field(name="📍 현재 위치", value=f"**{해역.value}**", inline=True)
        embed.set_image(url="https://images.unsplash.com/photo-1476514525535-07fb3b4ae5f1?w=800")
        
        await interaction.response.send_message(embed=embed)

    @app_commands.command(name="업적", description="나의 업적 달성 현황과 보상을 확인합니다.")
    async def 업적(self, interaction: discord.Interaction):
        from fishing_core.services.achievement_service import AchievementService
        achievements = await AchievementService.get_user_achievements(interaction.user.id)
        
        embed = EmbedFactory.build(title=f"🏆 {interaction.user.name}님의 업적 현황", type="warning")
        
        comp_count = sum(1 for a in achievements if a["is_completed"])
        embed.description = f"현재 **{len(achievements)}개** 중 **{comp_count}개**의 업적을 달성했습니다."
        
        for a in achievements:
            status = "✅ 달성" if a["is_completed"] else "🔒 미달성"
            reward_txt = f"(보상: `{a['reward']:,} C`)" if not a["is_completed"] else f"(달성일: `{a['completed_at'][:10]}`)"
            embed.add_field(
                name=f"{a['name']} {status}",
                value=f"{a['desc']}\n{reward_txt}",
                inline=False
            )
            
        embed.set_footer(text="업적은 활동을 통해 자동으로 달성되며 보상이 지급됩니다.")
        await interaction.response.send_message(embed=embed)

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
            "안개": "fog.png",
        }

        target_image = None
        for key, filename in weather_images.items():
            if key in weather:
                target_image = filename
                break

        from pathlib import Path
        file = None
        if target_image and Path(f"assets/weather/{target_image}").exists():
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

            if "폭풍우" in weather:
                bg_url = "https://images.unsplash.com/photo-1466611653911-95081537e5b7?w=800"
            elif "비" in weather:
                bg_url = "https://images.unsplash.com/photo-1515694346937-94d85e41e6f0?w=800"

        async with db.conn.execute("SELECT current_region FROM user_data WHERE user_id=?", (interaction.user.id,)) as cursor:
            res = await cursor.fetchone()
        region = res[0] if res else "연안"

        embed = EmbedFactory.build(title=f"🌊 {region} - 현재 바다 상황", type="info")
        embed.add_field(name="현재 시간대", value=f"**{time_str}** (`{now_hour}시`)", inline=True)
        embed.add_field(name="현재 날씨", value=f"**{weather}**", inline=True)
        embed.add_field(name="현재 해역", value=f"**{region}**", inline=True)

        hints = f"📍 현재 **{region}**에서 항해 중입니다.\n"
        if 0 <= now_hour < 4:
            hints += "- ⚠️ [신화] 우미보즈가 출몰할 수 있는 으스스한 시간입니다.\n"
        if weather in ["🌧️ 비", "🌫️ 안개"]:
            hints += "- ⚠️ [미스터리] 네시가 활동하기 좋은 날씨입니다.\n"
        if not hints:
            hints = "- 평화로운 바다입니다. 낚시하기 딱 좋네요!"

        embed.add_field(name="생태계 정보", value=hints, inline=False)
        embed.set_image(url=bg_url)

        if file:
            await interaction.response.send_message(embed=embed, file=file)
        else:
            await interaction.response.send_message(embed=embed)


    @app_commands.command(name="기상예측", description="기상청의 위성 자료를 분석하여 향후 3시간의 날씨 변화를 예측합니다. (비용: 3,000 C)")
    async def 기상예측(self, interaction: discord.Interaction):
        await self._forecast_weather(interaction)

    @app_commands.command(name="예보", description="`/기상예측`의 축약 명령어입니다.")
    async def 예보(self, interaction: discord.Interaction):
        await self._forecast_weather(interaction)

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

            embed = EmbedFactory.build(title="🌩️ 기우제 성공! 하늘이 응답했습니다!", type="warning")
            embed.description = f"**{interaction.user.name}**님의 마지막 정성이 닿았습니다!\n총 `{new_total:,} C`가 모여 바다에 **강력한 폭풍우**가 몰아치기 시작합니다!"
            embed.set_image(url="https://media.giphy.com/media/v1.Y2lkPTc5MGI3NjExNHJqZ3R4Z3R4Z3R4Z3R4Z3R4Z3R4Z3R4Z3R4Z3R4Z3R4Z3R4Z3R4JmVwPXYxX2ludGVybmFsX2dpZl9ieV9pZCZjdD1n/l41lTfuxV5RWRsBPO/giphy.gif") # 천둥 이미지 (예시)
            await interaction.response.send_message(embed=embed)
            await interaction.channel.send("📢 **[시스템]** 기우제 성공으로 인해 날씨가 **🌩️ 폭풍우**로 고정되었습니다! (1시간 지속)")
        else:
            embed = EmbedFactory.build(title="🙏 기우제 정성 모집 중...", type="info")
            embed.description = f"**{interaction.user.name}**님이 `{기부금:,} C`를 기부하셨습니다!\n\n현재 모인 정성: `{new_total:,} / {target_amount:,} C`\n목표 도달 시 바다에 **폭풍우**가 찾아옵니다!"
            progress = int((new_total / target_amount) * 10)
            bar = "🟦" * progress + "⬜" * (10 - progress)
            embed.add_field(name="진행도", value=f"{bar} ({progress*10}%)", inline=False)
            await interaction.response.send_message(embed=embed)

async def setup(bot):
    await bot.add_cog(FishingCog(bot))
