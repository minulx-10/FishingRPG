import datetime
import json
import random

import discord
from discord import app_commands
from discord.ext import commands

from fishing_core.database import db
from fishing_core.services.market_service import MarketService
from fishing_core.shared import FISH_DATA, MARKET_PRICES, RECIPES, env_state, format_grade_label, get_grade_order, kst
from fishing_core.utils import (
    EmbedFactory,
    check_boat_tier,
    fish_autocomplete,
    inv_autocomplete,
    locked_autocomplete,
)
from fishing_core.views_v2 import MarketPaginationView, ShopView


class MarketCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    async def _merchant_item_autocomplete(self, interaction: discord.Interaction, current: str) -> list[app_commands.Choice[str]]:
        state = await self._get_wandering_merchant_state()
        choices = []
        for offer in state["offers"]:
            if current.lower() not in offer["item_name"].lower():
                continue
            stock_tag = "품절" if offer["stock"] <= 0 else f"재고 {offer['stock']}"
            choices.append(app_commands.Choice(name=f"{offer['item_name']} ({stock_tag})", value=offer["item_name"]))
        return choices[:25]

    async def _get_wandering_merchant_state(self, force_refresh: bool = False) -> dict:
        async with db.conn.execute("SELECT value FROM server_state WHERE key='WANDERING_MERCHANT_STATE'") as cursor:
            row = await cursor.fetchone()

        now = datetime.datetime.now(kst)
        if row and not force_refresh:
            try:
                state = json.loads(row[0])
                expires_at = state.get("expires_at", "")
                if expires_at and now < datetime.datetime.fromisoformat(expires_at):
                    return state
            except (json.JSONDecodeError, ValueError, TypeError):
                pass

        common_pool = [
            {"item_name": "고급 미끼 🪱", "price": 380, "stock": 12, "user_limit": 4, "category": "소모품", "source": "inventory", "amount": 1, "description": "상점보다 조금 저렴한 희귀 낚시용 미끼"},
            {"item_name": "자석 미끼 🧲", "price": 650, "stock": 8, "user_limit": 3, "category": "소모품", "source": "inventory", "amount": 1, "description": "고철과 보물을 끌어오는 특수 미끼"},
            {"item_name": "레이드 작살 🔱", "price": 4200, "stock": 5, "user_limit": 2, "category": "전투", "source": "inventory", "amount": 1, "description": "다음 레이드 공격을 크게 강화하는 일회용 장비"},
            {"item_name": "가라앉은 보물상자 🧰", "price": 2800, "stock": 4, "user_limit": 2, "category": "희귀품", "source": "inventory", "amount": 1, "description": "언제 열어도 설레는 수상한 보물상자"},
        ]
        rare_pool = [
            {"item_name": "찢어진 지도 조각 A 🧩", "price": 1800, "stock": 3, "user_limit": 1, "category": "지도 조각", "source": "inventory", "amount": 1, "description": "보물지도 합성에 필요한 조각"},
            {"item_name": "찢어진 지도 조각 B 🧩", "price": 1800, "stock": 3, "user_limit": 1, "category": "지도 조각", "source": "inventory", "amount": 1, "description": "보물지도 합성에 필요한 조각"},
            {"item_name": "찢어진 지도 조각 C 🧩", "price": 1800, "stock": 3, "user_limit": 1, "category": "지도 조각", "source": "inventory", "amount": 1, "description": "보물지도 합성에 필요한 조각"},
            {"item_name": "찢어진 지도 조각 D 🧩", "price": 1800, "stock": 3, "user_limit": 1, "category": "지도 조각", "source": "inventory", "amount": 1, "description": "보물지도 합성에 필요한 조각"},
            {"item_name": "특급 참치 초밥 🍣", "price": 1200, "stock": 4, "user_limit": 2, "category": "완성 요리", "source": "inventory", "amount": 1, "description": "바로 되팔 수 있는 완성 요리"},
            {"item_name": "황실 캐비어 카나페 🍘", "price": 4200, "stock": 2, "user_limit": 1, "category": "완성 요리", "source": "inventory", "amount": 1, "description": "고급 시장에 넘기기 좋은 사치 요리"},
            {"item_name": "전설의 3대장 돔구이 🍱", "price": 2200, "stock": 3, "user_limit": 1, "category": "완성 요리", "source": "inventory", "amount": 1, "description": "완성된 인기 요리. 바로 판매 가능"},
        ]

        offers = [*random.sample(common_pool, k=2), random.choice(rare_pool)]
        expires_at = now + datetime.timedelta(hours=5)
        state = {
            "merchant_id": now.strftime("%Y%m%d%H%M%S"),
            "created_at": now.isoformat(),
            "expires_at": expires_at.isoformat(),
            "offers": offers,
        }

        await db.execute(
            "INSERT INTO server_state (key, value) VALUES ('WANDERING_MERCHANT_STATE', ?) "
            "ON CONFLICT(key) DO UPDATE SET value = ?",
            (json.dumps(state, ensure_ascii=False), json.dumps(state, ensure_ascii=False)),
        )
        return state

    async def trigger_merchant_encounter(self, interaction: discord.Interaction):
        """낚시 중 떠돌이 상인 소식을 발견했을 때 호출됩니다."""
        # Phase 5: 소문이 발견될 때마다 품목을 무조건 새로 갱신 (사용자 요청: 매번 변경)
        await self._get_wandering_merchant_state(force_refresh=True)
        msg = "📢 **[소문]** 근처 해역에 새로운 떠돌이 상인이 나타났다는 소식이 들려옵니다! `/떠상` 명령어로 확인해보세요."
        await interaction.channel.send(msg)


    async def _get_user_merchant_state(self, user_id: int) -> dict:
        async with db.conn.execute("SELECT merchant_purchase_state FROM user_data WHERE user_id=?", (user_id,)) as cursor:
            row = await cursor.fetchone()
        if not row or not row[0]:
            return {"merchant_id": "", "counts": {}}
        try:
            state = json.loads(row[0])
        except json.JSONDecodeError:
            return {"merchant_id": "", "counts": {}}
        state.setdefault("merchant_id", "")
        state.setdefault("counts", {})
        return state

    async def _save_user_merchant_state(self, user_id: int, state: dict) -> None:
        await db.execute(
            "UPDATE user_data SET merchant_purchase_state = ? WHERE user_id = ?",
            (json.dumps(state, ensure_ascii=False), user_id),
        )

    @staticmethod
    def _format_remaining(expires_at: str) -> str:
        try:
            remaining = datetime.datetime.fromisoformat(expires_at) - datetime.datetime.now(kst)
        except ValueError:
            return "알 수 없음"
        if remaining.total_seconds() <= 0:
            return "곧 교체됨"
        total_minutes = int(remaining.total_seconds() // 60)
        hours, minutes = divmod(total_minutes, 60)
        return f"{hours}시간 {minutes}분"

    async def _show_wandering_merchant(self, interaction: discord.Interaction) -> None:
        await db.get_user_data(interaction.user.id)
        state = await self._get_wandering_merchant_state()
        user_state = await self._get_user_merchant_state(interaction.user.id)
        if user_state.get("merchant_id") != state["merchant_id"]:
            user_state = {"merchant_id": state["merchant_id"], "counts": {}}
            await self._save_user_merchant_state(interaction.user.id, user_state)

        embed = EmbedFactory.build(title="🧳 떠돌이 상인", style="warning")
        embed.description = (
            "먼 바다를 떠돌던 상인이 잠시 정박했습니다.\n"
            "이번 물건은 재고가 적고, 1인 구매 제한이 있습니다."
        )

        for idx, offer in enumerate(state["offers"], start=1):
            bought = int(user_state["counts"].get(offer["item_name"], 0))
            remaining_limit = max(0, int(offer["user_limit"]) - bought)
            stock_text = f"`{offer['stock']}`"
            status_text = "🟥 품절" if offer["stock"] <= 0 else "🟩 구매 가능"
            title_prefix = "⭐" if idx == len(state["offers"]) else "🧳"
            embed.add_field(
                name=f"{title_prefix} {offer['item_name']} · `{offer['category']}`",
                value=(
                    f"{offer['description']}\n"
                    f"가격: `{offer['price']:,} C` | 남은 재고: {stock_text} | 상태: {status_text}\n"
                    f"내 남은 구매 가능 수량: `{remaining_limit}`"
                ),
                inline=False,
            )

        embed.set_footer(text=f"⭐ 마지막 상품은 오늘의 진귀품 | 다음 교체까지: {self._format_remaining(state['expires_at'])}")
        await interaction.response.send_message(embed=embed)

    async def _buy_from_wandering_merchant(self, interaction: discord.Interaction, item_name: str, quantity: int) -> None:
        if quantity <= 0:
            return await interaction.response.send_message("❌ 수량은 1개 이상이어야 합니다.", ephemeral=True)

        user_id = interaction.user.id
        await db.get_user_data(user_id)
        
        # 트랜잭션 내에서 모든 검증과 처리를 수행하여 레이스 컨디션 방지
        async with db.transaction():
            # 최신 상인 상태와 유저 상태 가져오기
            state = await self._get_wandering_merchant_state()
            user_state = await self._get_user_merchant_state(user_id)
            
            if user_state.get("merchant_id") != state["merchant_id"]:
                user_state = {"merchant_id": state["merchant_id"], "counts": {}}

            offer = next((entry for entry in state["offers"] if entry["item_name"] == item_name), None)
            if offer is None:
                return await interaction.response.send_message("❌ 지금 떠돌이 상인이 그 물건은 팔고 있지 않습니다.", ephemeral=True)

            if offer["stock"] <= 0:
                return await interaction.response.send_message("❌ 해당 상품은 이미 품절되었습니다.", ephemeral=True)

            if offer["stock"] < quantity:
                return await interaction.response.send_message(f"❌ 재고가 부족합니다. (남은 재고: {offer['stock']}개)", ephemeral=True)

            purchased = int(user_state["counts"].get(item_name, 0))
            if purchased + quantity > int(offer["user_limit"]):
                remain = max(0, int(offer["user_limit"]) - purchased)
                return await interaction.response.send_message(f"❌ 개인 구매 한도를 초과합니다. (남은 가능 수량: {remain}개)", ephemeral=True)

            coins, _, _ = await db.get_user_data(user_id)
            total_price = int(offer["price"]) * quantity
            if coins < total_price:
                return await interaction.response.send_message(f"❌ 코인이 부족합니다! (필요: {total_price:,} C / 현재: {coins:,} C)", ephemeral=True)

            # 실제 구매 처리
            await db.execute("UPDATE user_data SET coins = coins - ? WHERE user_id = ?", (total_price, user_id))
            await db.modify_inventory(user_id, item_name, quantity)

            # 상태 업데이트
            offer["stock"] -= quantity
            user_state["counts"][item_name] = purchased + quantity

            await self._save_user_merchant_state(user_id, user_state)
            await db.execute(
                "UPDATE server_state SET value = ? WHERE key = 'WANDERING_MERCHANT_STATE'",
                (json.dumps(state, ensure_ascii=False),),
            )
            
            await db.log_action(user_id, "MERCHANT_BUY", f"Item: {item_name}, Quantity: {quantity}, Spent: {total_price} C")

        await interaction.response.send_message(
            f"🧳 떠돌이 상인에게서 **{item_name}** {quantity}개를 구매했습니다! "
            f"(총 `{total_price:,} C` 사용 / 남은 재고: `{offer['stock']}`)"
        )

    @app_commands.command(name="시세", description="현재 수산시장의 글로벌 시세를 확인합니다.")
    @app_commands.autocomplete(검색어=fish_autocomplete)
    async def 시세(self, interaction: discord.Interaction, 검색어: str = None):
        if 검색어:
            status_info = MarketService.get_price_status(검색어)
            grade = FISH_DATA[검색어].get("grade", "일반")

            embed = EmbedFactory.build(title=f"📊 {검색어} 시세 정보", style="warning")
            embed.add_field(name="등급", value=f"**{format_grade_label(grade)}**", inline=True)
            embed.add_field(name="현재 시장가", value=f"**{status_info['current']} C**", inline=True)
            embed.add_field(name="시세 상태", value=status_info['status'], inline=True)
            return await interaction.response.send_message(embed=embed)

        view = MarketPaginationView(MARKET_PRICES)
        await interaction.response.send_message(embed=view.make_embed(), view=view)

    @app_commands.command(name="떠돌이상인", description="지금 정박 중인 떠돌이 상인의 상품을 확인합니다.")
    async def 떠돌이상인(self, interaction: discord.Interaction):
        await self._show_wandering_merchant(interaction)

    @app_commands.command(name="떠상", description="`/떠돌이상인`의 축약 명령어입니다.")
    async def 떠상(self, interaction: discord.Interaction):
        await self._show_wandering_merchant(interaction)

    @app_commands.command(name="떠상구매", description="떠돌이 상인에게서 한정 상품을 구매합니다.")
    @app_commands.autocomplete(상품명=_merchant_item_autocomplete)
    async def 떠상구매(self, interaction: discord.Interaction, 상품명: str, 수량: int = 1):
        await self._buy_from_wandering_merchant(interaction, 상품명, 수량)

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

        protected_items = ["낡은 고철 ⚙️", "가라앉은 보물상자 🧰", "고급 미끼 🪱", "자석 미끼 🧲", "찢어진 지도 조각 A 🧩", "찢어진 지도 조각 B 🧩", "찢어진 지도 조각 C 🧩", "찢어진 지도 조각 D 🧩", "레이드 작살 🔱", "초급 그물망 🕸️", "튼튼한 그물망 🕸️"]
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

        current_weather = env_state.get("CURRENT_WEATHER", "☀️ 맑음")
        for name, amt in sellable_items:
            base_price = 0
            if name in FISH_DATA: base_price = FISH_DATA[name]["price"]
            elif name in RECIPES and "price" in RECIPES[name]: base_price = RECIPES[name]["price"]
            
            price = await MarketService.calculate_sell_price(interaction.user.id, name, base_price, current_weather)
            
            item_total = price * amt
            total_earned += item_total
            item_grade = FISH_DATA.get(name, {}).get("grade", "아이템")
            grade_label = format_grade_label(item_grade) if name in FISH_DATA else "📦 아이템"
            msg += f"• {name} `{grade_label}` {amt}마리 : `{item_total:,} C` (개당 {price:,}C)\n"

        delete_targets = [(interaction.user.id, name) for name, amt in sellable_items]
        sales_logs = [(name, amt, amt) for name, amt in sellable_items]

        async with db.transaction():
            await db.executemany("DELETE FROM inventory WHERE user_id = ? AND item_name = ?", delete_targets)
            await db.executemany("INSERT INTO market_sales (item_name, amount_sold) VALUES (?, ?) ON CONFLICT(item_name) DO UPDATE SET amount_sold = amount_sold + ?", sales_logs)
            await db.execute("UPDATE user_data SET coins = coins + ? WHERE user_id = ?", (total_earned, interaction.user.id))
            await db.log_action(interaction.user.id, "MARKET_SELL_ALL", f"Total Earned: {total_earned} C, Items: {len(sellable_items)} types")

        msg = f"{msg}\n**총 수익: +{total_earned:,} C**"

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

        current_weather = env_state.get("CURRENT_WEATHER", "☀️ 맑음")
        base_price = FISH_DATA.get(target_fish, {}).get("price", 0)
        price_per_item = await MarketService.calculate_sell_price(interaction.user.id, target_fish, base_price, current_weather)

        if price_per_item <= 0:
            return await interaction.response.send_message(f"❌ **{target_fish}**는 현재 시장에 판매할 수 없는 아이템입니다.", ephemeral=True)

        total_earned = price_per_item * 수량

        async with db.transaction():
            await db.execute("UPDATE inventory SET amount = amount - ? WHERE user_id=? AND item_name=?", (수량, interaction.user.id, target_fish))
            await db.execute("INSERT INTO market_sales (item_name, amount_sold) VALUES (?, ?) ON CONFLICT(item_name) DO UPDATE SET amount_sold = amount_sold + ?", (target_fish, 수량, 수량))
            await db.execute("UPDATE user_data SET coins = coins + ? WHERE user_id=?", (total_earned, interaction.user.id))
            await db.log_action(interaction.user.id, "MARKET_SELL_ITEM", f"Item: {target_fish}, Amount: {수량}, Total Earned: {total_earned} C")
        
        # 삭제 후 0개인 항목 정리 (선택사항이나 깔끔함 유지)
        await db.execute("DELETE FROM inventory WHERE user_id=? AND item_name=? AND amount <= 0", (interaction.user.id, target_fish))

        await interaction.response.send_message(f"💰 **{target_fish}** {수량}마리를 팔아서 총 `{total_earned:,} C`를 얻었습니다! (개당 {price_per_item}C)")

    @app_commands.command(name="상점", description="유용한 아이템을 구경할 수 있는 상점입니다.")
    @check_boat_tier(2)
    async def 상점(self, interaction: discord.Interaction):
        embed = EmbedFactory.build(title="🏪 수산시장 아이템 상점", style="warning")
        embed.add_field(name="고급 미끼 🪱 (가격: 500 C)", value="다음 낚시 때 일반 어종을 피하고 희귀 어종 등장 확률을 올려줍니다.", inline=False)
        embed.add_field(name="자석 미끼 🧲 (가격: 800 C)", value="물고기는 낚이지 않지만, 바다 밑에 가라앉은 고철이나 보물을 확정적으로 건져냅니다.", inline=False)
        embed.add_field(name="초급 그물망 🕸️ (가격: 500 C)", value="얕은 바다를 훑어 잡어, 조개류, 고철을 한 번에 5개까지 건져올립니다.", inline=False)
        embed.add_field(name="튼튼한 그물망 🕸️ (가격: 1,200 C)", value="좀 더 넓게 긁어 조개류와 소형 어종을 한 번에 10개까지 수확합니다.", inline=False)
        embed.add_field(name="에너지 드링크 ⚡ (가격: 1,500 C)", value="즉시 행동력(체력)을 **50⚡** 회복합니다. (최대치 초과 불가)", inline=False)
        embed.add_field(name="가속 포션 💨 (가격: 3,000 C)", value="30분간 낚시 입질 대기 시간이 50% 단축됩니다.", inline=False)
        embed.add_field(name="특수 떡밥 🎣 (가격: 2,000 C)", value="30분간 희귀 등급 이상 물고기 확률이 1.5배 증가합니다.", inline=False)
        embed.add_field(name="레이드 작살 🔱 (가격: 5,000 C)", value="다음 레이드 공격 시 데미지가 2배로 증가합니다! (1회용)", inline=False)
        view = ShopView(interaction.user, [])
        await interaction.response.send_message(embed=embed, view=view)

    @app_commands.command(name="구매", description="상점에서 아이템을 구매합니다.")
    @app_commands.choices(아이템=[
        app_commands.Choice(name="고급 미끼 🪱", value="고급 미끼 🪱"),
        app_commands.Choice(name="자석 미끼 🧲", value="자석 미끼 🧲"),
        app_commands.Choice(name="초급 그물망 🕸️", value="초급 그물망 🕸️"),
        app_commands.Choice(name="튼튼한 그물망 🕸️", value="튼튼한 그물망 🕸️"),
        app_commands.Choice(name="에너지 드링크 ⚡", value="에너지 드링크 ⚡"),
        app_commands.Choice(name="가속 포션 💨", value="가속 포션 💨"),
        app_commands.Choice(name="특수 떡밥 🎣", value="특수 떡밥 🎣"),
        app_commands.Choice(name="레이드 작살 🔱", value="레이드 작살 🔱"),
    ])
    @check_boat_tier(2)
    async def 구매(self, interaction: discord.Interaction, 아이템: app_commands.Choice[str], 수량: int = 1):
        result = await MarketService.process_purchase(interaction.user.id, 아이템.value, 수량)
        await interaction.response.send_message(result["message"], ephemeral=not result["success"])

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
        await interaction.response.send_message(f"🔓 **{물고기}**의 잠금을 해제했습니다! 이제 판매할 수 있습니다.")

    @app_commands.command(name="일괄잠금", description="현재 가방에 있는 모든 물고기를 일괄 잠금(보호) 처리합니다.")
    async def 일괄잠금(self, interaction: discord.Interaction):
        await db.execute("UPDATE inventory SET is_locked=1 WHERE user_id=? AND amount > 0", (interaction.user.id,))
        await interaction.response.send_message("🔒 가방에 있는 모든 물고기를 **일괄 잠금** 처리했습니다! (판매 시 보호됨)")

    @app_commands.command(name="일괄해제", description="현재 가방에 있는 모든 물고기의 잠금을 일괄 해제합니다.")
    async def 일괄해제(self, interaction: discord.Interaction):
        await db.execute("UPDATE inventory SET is_locked=0 WHERE user_id=? AND amount > 0", (interaction.user.id,))
        await interaction.response.send_message("🔓 가방에 있는 모든 물고기의 **잠금을 일괄 해제**했습니다! (이제 판매가 가능합니다)")

    @app_commands.command(name="칭호상점", description="어마어마한 코인을 지불하여 명예로운 칭호를 구매합니다. (엔드게임 콘텐츠)")
    async def 칭호상점(self, interaction: discord.Interaction):
        embed = EmbedFactory.build(title="🎖️ 명예의 전당 - 칭호 상점", style="warning")
        embed.description = "부와 명예를 모두 가진 자만이 달 수 있는 특별한 칭호들입니다."
        embed.add_field(name="[갑부] 💰", value="가격: `1,000,000 C`", inline=False)
        embed.add_field(name="[강태공] 🎣", value="가격: `5,000,000 C`", inline=False)
        embed.add_field(name="[바다의 왕] 🔱", value="가격: `20,000,000 C`", inline=False)
        embed.add_field(name="[대부호] 💎", value="가격: `50,000,000 C`", inline=False)
        embed.add_field(name="[해신] 🌊", value="가격: `100,000,000 C`", inline=False)
        embed.set_footer(text="💡 구매 즉시 해당 칭호가 적용됩니다.")

        view = TitleShopView()
        await interaction.response.send_message(embed=embed, view=view)

    @app_commands.command(name="선물", description="다른 유저에게 내 가방에 있는 물고기나 아이템을 선물합니다.")
    @app_commands.autocomplete(물건=inv_autocomplete)
    async def 선물(self, interaction: discord.Interaction, 유저: discord.Member, 물건: str, 수량: int = 1):
        if 유저.id == interaction.user.id:
            return await interaction.response.send_message("❌ 자기 자신에게는 선물할 수 없습니다.", ephemeral=True)
            
        if 수량 <= 0:
            return await interaction.response.send_message("❌ 수량은 1개 이상이어야 합니다.", ephemeral=True)
            
        async with db.conn.execute("SELECT amount, is_locked FROM inventory WHERE user_id=? AND item_name=?", (interaction.user.id, 물건)) as cursor:
            res = await cursor.fetchone()
            
        if not res or res[0] < 수량:
            return await interaction.response.send_message(f"❌ 가방에 **{물건}**이(가) 부족합니다.", ephemeral=True)
            
        if res[1] == 1:
            return await interaction.response.send_message(f"🔒 **{물건}**은(는) 잠금 상태이므로 선물할 수 없습니다.", ephemeral=True)
            
        async with db.transaction():
            # 내 가방에서 차감
            await db.execute("UPDATE inventory SET amount = amount - ? WHERE user_id=? AND item_name=?", (수량, interaction.user.id, 물건))
            # 상대방 가방에 추가
            await db.modify_inventory(유저.id, 물건, 수량)
            # 0개 이하인 항목 삭제
            await db.execute("DELETE FROM inventory WHERE user_id=? AND item_name=? AND amount <= 0", (interaction.user.id, 물건))
            
            await db.log_action(interaction.user.id, "ITEM_GIFT", f"To: {유저.name}, Item: {물건}, Qty: {수량}")
            
        from fishing_core.utils import EmbedFactory
        embed = EmbedFactory.build(title="🎁 선물이 도착했습니다!", style="info")
        embed.description = f"**{interaction.user.name}**님이 **{유저.name}**님에게 선물을 보냈습니다!"
        embed.add_field(name="📦 선물 품목", value=f"**{물건}** x{수량}")
        embed.set_thumbnail(url="https://images.unsplash.com/photo-1549465220-1a8b9238cd48?w=400")
        
        await interaction.response.send_message(f"✅ **{유저.name}**님에게 **{물건}** {수량}개를 선물했습니다!", embed=embed)
        # 상대방에게 알림 (가급적)
        try:
            await 유저.send(f"🔔 **{interaction.user.name}**님이 당신에게 **{물건}** {수량}개를 선물했습니다! 가방을 확인해보세요.")
        except Exception:
            pass

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

        await interaction.response.send_message(f"🎊 축하합니다! `{price:,} C`를 지불하고 **[{selected}]** 칭호를 획득했습니다!")

async def setup(bot):
    await bot.add_cog(MarketCog(bot))
