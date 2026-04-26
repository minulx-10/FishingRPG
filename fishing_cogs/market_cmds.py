import discord
from discord import app_commands
from discord.ext import commands

from fishing_core.database import db
from fishing_core.shared import FISH_DATA, MARKET_PRICES, RECIPES, format_grade_label, get_grade_order
from fishing_core.utils import (
    check_boat_tier,
    fish_autocomplete,
    inv_autocomplete,
    locked_autocomplete,
)
from fishing_core.views import MarketPaginationView


class MarketCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @app_commands.command(name="시세", description="현재 수산시장의 글로벌 시세를 확인합니다.")
    @app_commands.autocomplete(검색어=fish_autocomplete)
    async def 시세(self, interaction: discord.Interaction, 검색어: str = None):
        if 검색어:
            if 검색어 not in MARKET_PRICES:
                return await interaction.response.send_message(f"❌ '{검색어}'에 대한 정보가 수산시장에 없습니다.", ephemeral=True)

            base = FISH_DATA[검색어]["price"]
            current_price = MARKET_PRICES[검색어]
            ratio = current_price / base
            status = "📈 떡상" if ratio > 1.2 else ("📉 떡락" if ratio < 0.8 else "➖ 평범")
            grade = FISH_DATA[검색어].get("grade", "일반")

            embed = discord.Embed(title=f"📊 {검색어} 시세 정보", color=0xf1c40f)
            embed.add_field(name="등급", value=f"**{format_grade_label(grade)}**", inline=True)
            embed.add_field(name="현재 시장가", value=f"**{current_price} C**", inline=True)
            embed.add_field(name="시세 상태", value=status, inline=True)
            return await interaction.response.send_message(embed=embed)

        view = MarketPaginationView(MARKET_PRICES)
        await interaction.response.send_message(embed=view.make_embed(), view=view)

    @app_commands.command(name="판매", description="인벤토리에 있는 물고기를 일괄 판매합니다. (등급 필터를 사용할 수 있습니다)")
    @app_commands.describe(제외1="판매하지 않고 보호할 아이템 1", 제외2="판매하지 않고 보호할 아이템 2", 제외3="판매하지 않고 보호할 아이템 3", 등급필터="지정한 등급 이하만 판매합니다.")
    @app_commands.choices(등급필터=[
        app_commands.Choice(name="일반만", value="일반"),
        app_commands.Choice(name="희귀이하", value="희귀"),
        app_commands.Choice(name="초희귀이하", value="초희귀"),
        app_commands.Choice(name="대형 포식자 이하", value="대형 포식자"),
        app_commands.Choice(name="레전드이하", value="레전드"),
        app_commands.Choice(name="태고이하", value="태고"),
        app_commands.Choice(name="전체 (추천 안함)", value="전체"),
    ])
    @app_commands.autocomplete(제외1=inv_autocomplete, 제외2=inv_autocomplete, 제외3=inv_autocomplete)
    async def 판매(self, interaction: discord.Interaction, 제외1: str = None, 제외2: str = None, 제외3: str = None, 등급필터: str = "전체"):
        await interaction.response.defer()

        async with db.conn.execute("SELECT item_name, amount FROM inventory WHERE user_id=? AND amount > 0 AND is_locked=0", (interaction.user.id,)) as cursor:
            items = await cursor.fetchall()

        protected_items = ["낡은 고철 ⚙️", "가라앉은 보물상자 🧰", "고급 미끼 🪱", "자석 미끼 🧲", "찢어진 지도 조각 A 🧩", "찢어진 지도 조각 B 🧩", "찢어진 지도 조각 C 🧩", "찢어진 지도 조각 D 🧩", "레이드 작살 🔱"]
        user_excludes = [x for x in [제외1, 제외2, 제외3] if x is not None]
        protected_items.extend(user_excludes)

        target_grade_lv = get_grade_order(등급필터) if 등급필터 != "전체" else 999

        sellable_items = []
        for name, amt in items:
            if name in protected_items: continue

            # 등급 필터링
            fish_grade = FISH_DATA.get(name, {}).get("grade", "일반")
            if get_grade_order(fish_grade) > target_grade_lv:
                continue

            sellable_items.append((name, amt))

        if not sellable_items:
            return await interaction.followup.send(f"❌ 판매할 수 있는 물고기가 없습니다!\n(필터: {등급필터} 이하 / 모두 보호 처리되었거나 가방이 비어있음)", ephemeral=True)

        total_earned = 0
        msg = f"**[💰 수산시장 일괄 판매 영수증 - {등급필터} 필터]**\n"

        if user_excludes:
            msg += f"*(🛡️ 선택 보호됨: {', '.join(user_excludes)})*\n\n"

        from fishing_core.shared import env_state
        current_weather = env_state.get("CURRENT_WEATHER", "☀️ 맑음")
        weather_bonus_msg = ""
        if current_weather == "☀️ 맑음":
            weather_bonus_msg = "*(☀️ 맑은 날씨 보너스: 일반/희귀 어종 가격 1.3배 적용 중!)*\n"

        for name, amt in sellable_items:
            if name in MARKET_PRICES:
                price = MARKET_PRICES[name]
            elif name in FISH_DATA:
                price = FISH_DATA[name]["price"]
            elif name in RECIPES and "price" in RECIPES[name]:
                price = RECIPES[name]["price"]
            else:
                price = 0

            # 맑은 날 일반/희귀 보너스
            item_grade = FISH_DATA.get(name, {}).get("grade", "일반")
            if current_weather == "☀️ 맑음" and item_grade in ["일반", "희귀"]:
                price = int(price * 1.3)

            # 칭호 보너스 (갑부: 판매 수익 5% 추가)
            title = await db.get_user_title(interaction.user.id)
            if title == "[갑부]":
                price = int(price * 1.05)

            item_total = price * amt
            total_earned += item_total
            grade_label = format_grade_label(item_grade) if name in FISH_DATA else "📦 아이템"
            msg += f"• {name} `{grade_label}` {amt}마리 : `{item_total:,} C` (개당 {price:,}C)\n"

        delete_targets = [(interaction.user.id, name) for name, amt in sellable_items]
        sales_logs = [(name, amt, amt) for name, amt in sellable_items]

        await db.executemany("DELETE FROM inventory WHERE user_id = ? AND item_name = ?", delete_targets)
        await db.executemany("INSERT INTO market_sales (item_name, amount_sold) VALUES (?, ?) ON CONFLICT(item_name) DO UPDATE SET amount_sold = amount_sold + ?", sales_logs)
        await db.execute("UPDATE user_data SET coins = coins + ? WHERE user_id = ?", (total_earned, interaction.user.id))
        await db.commit()

        msg = f"{weather_bonus_msg}{msg}\n**총 수익: +{total_earned:,} C**"

        if len(msg) > 1900:
            msg = msg[:1900] + "\n... (목록이 너무 길어 생략됨) ...\n" + f"\n**총 수익: +{total_earned:,} C**"

        await interaction.followup.send(msg)

    @app_commands.command(name="개별판매", description="가방에 있는 특정 물고기/아이템을 원하는 수량만큼 판매합니다.")
    @app_commands.autocomplete(물고기=inv_autocomplete)
    async def 개별판매(self, interaction: discord.Interaction, 물고기: str, 수량: int):
        target_fish = 물고기

        if 수량 <= 0:
            return await interaction.response.send_message("❌ 수량은 1마리 이상이어야 합니다.", ephemeral=True)

        async with db.conn.execute("SELECT amount, is_locked FROM inventory WHERE user_id=? AND item_name=?", (interaction.user.id, target_fish)) as cursor:
            res = await cursor.fetchone()
        current_amount, is_locked = res if res else (0, 0)

        if is_locked == 1:
            return await interaction.response.send_message(f"❌ **{target_fish}**는 잠금(보호) 처리되어 판매할 수 없습니다. 먼저 `/잠금해제`를 사용하세요.", ephemeral=True)

        if current_amount < 수량:
            return await interaction.response.send_message(f"❌ 가방에 **{target_fish}**가 부족합니다. (현재 보유: {current_amount}마리)", ephemeral=True)

        price_per_item = MARKET_PRICES.get(target_fish, FISH_DATA[target_fish]["price"])

        # 칭호 보너스 (갑부: 판매 수익 5% 추가)
        title = await db.get_user_title(interaction.user.id)
        if title == "[갑부]":
            price_per_item = int(price_per_item * 1.05)

        total_earned = price_per_item * 수량

        await db.execute("UPDATE inventory SET amount = amount - ? WHERE user_id=? AND item_name=?", (수량, interaction.user.id, target_fish))
        await db.execute("INSERT INTO market_sales (item_name, amount_sold) VALUES (?, ?) ON CONFLICT(item_name) DO UPDATE SET amount_sold = amount_sold + ?", (target_fish, 수량, 수량))
        await db.execute("UPDATE user_data SET coins = coins + ? WHERE user_id=?", (total_earned, interaction.user.id))
        await db.commit()

        await interaction.response.send_message(f"💰 **{target_fish}** {수량}마리를 팔아서 총 `{total_earned:,} C`를 얻었습니다! (개당 {price_per_item}C)")

    @app_commands.command(name="상점", description="유용한 아이템을 구경할 수 있는 상점입니다.")
    @check_boat_tier(2)
    async def 상점(self, interaction: discord.Interaction):
        embed = discord.Embed(title="🏪 수산시장 아이템 상점", color=0xf1c40f)
        embed.add_field(name="고급 미끼 🪱 (가격: 500 C)", value="다음 낚시 때 일반 어종을 피하고 희귀 어종 등장 확률을 올려줍니다.", inline=False)
        embed.add_field(name="자석 미끼 🧲 (가격: 800 C)", value="물고기는 낚이지 않지만, 바다 밑에 가라앉은 고철이나 보물을 확정적으로 건져냅니다.", inline=False)
        embed.add_field(name="에너지 드링크 ⚡ (가격: 1,500 C)", value="즉시 행동력(체력)을 **50⚡** 회복합니다. (최대치 초과 불가)", inline=False)
        embed.add_field(name="가속 포션 💨 (가격: 3,000 C)", value="30분간 낚시 입질 대기 시간이 50% 단축됩니다.", inline=False)
        embed.add_field(name="특수 떡밥 🎣 (가격: 2,000 C)", value="30분간 희귀 등급 이상 물고기 확률이 1.5배 증가합니다.", inline=False)
        embed.add_field(name="레이드 작살 🔱 (가격: 5,000 C)", value="다음 레이드 공격 시 데미지가 2배로 증가합니다! (1회용)", inline=False)
        await interaction.response.send_message(embed=embed)

    @app_commands.command(name="구매", description="상점에서 아이템을 구매합니다.")
    @app_commands.choices(아이템=[
        app_commands.Choice(name="고급 미끼 🪱", value="고급 미끼 🪱"),
        app_commands.Choice(name="자석 미끼 🧲", value="자석 미끼 🧲"),
        app_commands.Choice(name="에너지 드링크 ⚡", value="에너지 드링크 ⚡"),
        app_commands.Choice(name="가속 포션 💨", value="가속 포션 💨"),
        app_commands.Choice(name="특수 떡밥 🎣", value="특수 떡밥 🎣"),
        app_commands.Choice(name="레이드 작살 🔱", value="레이드 작살 🔱"),
    ])
    @check_boat_tier(2)
    async def 구매(self, interaction: discord.Interaction, 아이템: app_commands.Choice[str], 수량: int = 1):
        if 수량 <= 0:
            return await interaction.response.send_message("❌ 수량은 1개 이상이어야 합니다.", ephemeral=True)

        coins, _, _ = await db.get_user_data(interaction.user.id)

        # 아이템별 가격 매핑
        item_prices = {
            "고급 미끼 🪱": 500,
            "자석 미끼 🧲": 800,
            "에너지 드링크 ⚡": 1500,
            "가속 포션 💨": 3000,
            "특수 떡밥 🎣": 2000,
            "레이드 작살 🔱": 5000,
        }

        unit_price = item_prices.get(아이템.value, 500)
        price = unit_price * 수량

        if coins < price:
            return await interaction.response.send_message(f"❌ 코인이 부족합니다! (필요: {price:,} C / 현재: {coins:,} C)", ephemeral=True)

        # 에너지 드링크는 즉시 사용 (인벤토리 저장 대신 체력 회복)
        if 아이템.value == "에너지 드링크 ⚡":
            heal_amount = 50 * 수량
            await db.execute("UPDATE user_data SET coins = coins - ? WHERE user_id = ?", (price, interaction.user.id))
            await db.execute("UPDATE user_data SET stamina = MIN(max_stamina, stamina + ?) WHERE user_id = ?", (heal_amount, interaction.user.id))
            await db.commit()
            async with db.conn.execute("SELECT stamina, max_stamina FROM user_data WHERE user_id=?", (interaction.user.id,)) as cursor:
                st_res = await cursor.fetchone()
            return await interaction.response.send_message(f"⚡ 에너지 드링크를 {수량}개 마셨습니다! 체력 +{heal_amount}⚡ (현재: {st_res[0]}/{st_res[1]}⚡)")

        # 가속 포션/특수 떡밥은 버프로 적용
        import datetime

        from fishing_core.shared import kst

        if 아이템.value == "가속 포션 💨":
            await db.execute("UPDATE user_data SET coins = coins - ? WHERE user_id = ?", (price, interaction.user.id))
            end_time = datetime.datetime.now(kst) + datetime.timedelta(minutes=30 * 수량)
            end_time_str = end_time.strftime('%Y-%m-%d %H:%M:%S')
            await db.execute("INSERT OR REPLACE INTO active_buffs (user_id, buff_type, end_time) VALUES (?, ?, ?)",
                             (interaction.user.id, "fishing_speed_up", end_time_str))
            await db.commit()
            return await interaction.response.send_message(f"💨 가속 포션을 사용했습니다! **{30*수량}분** 동안 낚시 대기 시간이 단축됩니다. (남은 코인: `{coins - price:,} C`)")

        if 아이템.value == "특수 떡밥 🎣":
            await db.execute("UPDATE user_data SET coins = coins - ? WHERE user_id = ?", (price, interaction.user.id))
            end_time = datetime.datetime.now(kst) + datetime.timedelta(minutes=30 * 수량)
            end_time_str = end_time.strftime('%Y-%m-%d %H:%M:%S')
            await db.execute("INSERT OR REPLACE INTO active_buffs (user_id, buff_type, end_time) VALUES (?, ?, ?)",
                             (interaction.user.id, "rare_boost", end_time_str))
            await db.commit()
            return await interaction.response.send_message(f"🎣 특수 떡밥을 뿌렸습니다! **{30*수량}분** 동안 희귀 이상 어종 확률이 1.5배 증가합니다. (남은 코인: `{coins - price:,} C`)")

        # 나머지 아이템은 인벤토리 저장 (미끼, 레이드 작살)
        await db.execute("UPDATE user_data SET coins = coins - ? WHERE user_id = ?", (price, interaction.user.id))
        await db.execute("INSERT INTO inventory (user_id, item_name, amount) VALUES (?, ?, ?) ON CONFLICT(user_id, item_name) DO UPDATE SET amount = amount + ?", (interaction.user.id, 아이템.value, 수량, 수량))
        await db.commit()

        await interaction.response.send_message(f"🛍️ **{아이템.value}** {수량}개를 구매했습니다! (남은 코인: `{coins - price:,} C`)")

    @app_commands.command(name="잠금", description="특정 물고기나 아이템을 일괄 판매 대상에서 제외하고 배틀용으로 보호합니다.")
    @app_commands.autocomplete(물고기=inv_autocomplete)
    async def 잠금(self, interaction: discord.Interaction, 물고기: str):
        async with db.conn.execute("SELECT amount, is_locked FROM inventory WHERE user_id=? AND item_name=?", (interaction.user.id, 물고기)) as cursor:
            res = await cursor.fetchone()

        if not res or res[0] <= 0:
            return await interaction.response.send_message(f"❌ 가방에 **{물고기}**가 없습니다.", ephemeral=True)

        if res[1] == 1:
            return await interaction.response.send_message(f"⚠️ **{물고기}**는 이미 잠금 처리되어 있습니다.", ephemeral=True)

        await db.execute("UPDATE inventory SET is_locked=1 WHERE user_id=? AND item_name=?", (interaction.user.id, 물고기))
        await db.commit()
        await interaction.response.send_message(f"🔒 **{물고기}**가 잠금(보호) 처리되었습니다! 이제 일괄 판매 시 제외되며 배틀 출전이 가능합니다.")

    @app_commands.command(name="잠금해제", description="잠금(보호) 처리된 물고기의 잠금을 해제합니다.")
    @app_commands.autocomplete(물고기=locked_autocomplete)
    async def 잠금해제(self, interaction: discord.Interaction, 물고기: str):
        async with db.conn.execute("SELECT amount, is_locked FROM inventory WHERE user_id=? AND item_name=?", (interaction.user.id, 물고기)) as cursor:
            res = await cursor.fetchone()

        if not res or res[0] <= 0:
            return await interaction.response.send_message(f"❌ 가방에 **{물고기}**가 없습니다.", ephemeral=True)

        if res[1] == 0:
            return await interaction.response.send_message(f"⚠️ **{물고기}**는 잠겨있지 않습니다.", ephemeral=True)

        await db.execute("UPDATE inventory SET is_locked=0 WHERE user_id=? AND item_name=?", (interaction.user.id, 물고기))
        await db.commit()
        await interaction.response.send_message(f"🔓 **{물고기}**의 잠금을 해제했습니다! 이제 판매할 수 있습니다.")

    @app_commands.command(name="일괄잠금", description="현재 가방에 있는 모든 물고기를 일괄 잠금(보호) 처리합니다.")
    async def 일괄잠금(self, interaction: discord.Interaction):
        await db.execute("UPDATE inventory SET is_locked=1 WHERE user_id=? AND amount > 0", (interaction.user.id,))
        await db.commit()
        await interaction.response.send_message("🔒 가방에 있는 모든 물고기를 **일괄 잠금** 처리했습니다! (판매 시 보호됨)")

    @app_commands.command(name="일괄해제", description="현재 가방에 있는 모든 물고기의 잠금을 일괄 해제합니다.")
    async def 일괄해제(self, interaction: discord.Interaction):
        await db.execute("UPDATE inventory SET is_locked=0 WHERE user_id=? AND amount > 0", (interaction.user.id,))
        await db.commit()
        await interaction.response.send_message("🔓 가방에 있는 모든 물고기의 **잠금을 일괄 해제**했습니다! (이제 판매가 가능합니다)")

    @app_commands.command(name="칭호상점", description="어마어마한 코인을 지불하여 명예로운 칭호를 구매합니다. (엔드게임 콘텐츠)")
    async def 칭호상점(self, interaction: discord.Interaction):
        embed = discord.Embed(title="🎖️ 명예의 전당 - 칭호 상점", color=0xe67e22)
        embed.description = "부와 명예를 모두 가진 자만이 달 수 있는 특별한 칭호들입니다."
        embed.add_field(name="[갑부] 💰", value="가격: `1,000,000 C`", inline=False)
        embed.add_field(name="[강태공] 🎣", value="가격: `5,000,000 C`", inline=False)
        embed.add_field(name="[바다의 왕] 🔱", value="가격: `20,000,000 C`", inline=False)
        embed.add_field(name="[대부호] 💎", value="가격: `50,000,000 C`", inline=False)
        embed.add_field(name="[해신] 🌊", value="가격: `100,000,000 C`", inline=False)
        embed.set_footer(text="💡 구매 즉시 해당 칭호가 적용됩니다.")

        view = TitleShopView()
        await interaction.response.send_message(embed=embed, view=view)

class TitleShopView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=60)

    @discord.ui.select(placeholder="구매할 칭호를 선택하세요", options=[
        discord.SelectOption(label="[갑부] 💰", value="갑부", description="1,000,000 C"),
        discord.SelectOption(label="[강태공] 🎣", value="강태공", description="5,000,000 C"),
        discord.SelectOption(label="[바다의 왕] 🔱", value="바다의 왕", description="20,000,000 C"),
        discord.SelectOption(label="[대부호] 💎", value="대부호", description="50,000,000 C"),
        discord.SelectOption(label="[해신] 🌊", value="해신", description="100,000,000 C"),
    ])
    async def select_title(self, interaction: discord.Interaction, select: discord.ui.Select):
        title_prices = {
            "갑부": 1000000,
            "강태공": 5000000,
            "바다의 왕": 20000000,
            "대부호": 50000000,
            "해신": 100000000,
        }

        selected = select.values[0]
        price = title_prices[selected]

        coins, _, _ = await db.get_user_data(interaction.user.id)
        if coins < price:
            return await interaction.response.send_message(f"❌ 코인이 부족합니다! (필요: {price:,} C / 현재: {coins:,} C)", ephemeral=True)

        await db.execute("UPDATE user_data SET coins = coins - ?, title = ? WHERE user_id=?", (price, f"[{selected}]", interaction.user.id))
        await db.commit()

        await interaction.response.send_message(f"🎊 축하합니다! `{price:,} C`를 지불하고 **[{selected}]** 칭호를 획득했습니다!")

async def setup(bot):
    await bot.add_cog(MarketCog(bot))
