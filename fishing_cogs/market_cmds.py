import discord
from discord.ext import commands
from discord import app_commands

from fishing_core.database import db
from fishing_core.shared import FISH_DATA, MARKET_PRICES, RECIPES
from fishing_core.utils import fish_autocomplete, inv_autocomplete, check_boat_tier
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
            
            embed = discord.Embed(title=f"📊 {검색어} 시세 정보", color=0xf1c40f)
            embed.add_field(name="현재 시장가", value=f"**{current_price} C**", inline=True)
            embed.add_field(name="시세 상태", value=status, inline=True)
            return await interaction.response.send_message(embed=embed)
            
        view = MarketPaginationView(MARKET_PRICES)
        await interaction.response.send_message(embed=view.make_embed(), view=view)

    @app_commands.command(name="판매", description="인벤토리에 있는 물고기를 일괄 판매합니다. (특정 물고기를 판매에서 제외할 수 있습니다)")
    @app_commands.describe(제외1="판매하지 않고 보호할 아이템 1", 제외2="판매하지 않고 보호할 아이템 2", 제외3="판매하지 않고 보호할 아이템 3")
    @app_commands.autocomplete(제외1=inv_autocomplete, 제외2=inv_autocomplete, 제외3=inv_autocomplete)
    async def 판매(self, interaction: discord.Interaction, 제외1: str = None, 제외2: str = None, 제외3: str = None):
        await interaction.response.defer()

        async with db.conn.execute("SELECT item_name, amount FROM inventory WHERE user_id=? AND amount > 0", (interaction.user.id,)) as cursor:
            items = await cursor.fetchall()
        
        protected_items = ["낡은 고철 ⚙️", "가라앉은 보물상자 🧰", "고급 미끼 🪱", "자석 미끼 🧲", "찢어진 지도 조각 A 🧩", "찢어진 지도 조각 B 🧩", "찢어진 지도 조각 C 🧩", "찢어진 지도 조각 D 🧩"]
        user_excludes = [x for x in [제외1, 제외2, 제외3] if x is not None]
        protected_items.extend(user_excludes)
        
        sellable_items = [(name, amt) for name, amt in items if name not in protected_items]
        
        if not sellable_items:
            return await interaction.followup.send("❌ 판매할 수 있는 물고기가 없습니다!\n(모두 보호 처리되었거나 가방이 텅 비어있습니다.)", ephemeral=True)
            
        total_earned = 0
        msg = "**[💰 수산시장 일괄 판매 영수증]**\n"
        
        if user_excludes:
            msg += f"*(🛡️ 선택 보호됨: {', '.join(user_excludes)})*\n\n"

        for name, amt in sellable_items:
            if name in MARKET_PRICES:
                price = MARKET_PRICES[name]
            elif name in FISH_DATA:
                price = FISH_DATA[name]["price"]
            elif name in RECIPES and "price" in RECIPES[name]:
                price = RECIPES[name]["price"]
            else:
                price = 0 
                
            item_total = price * amt
            total_earned += item_total
            msg += f"• {name} {amt}마리 : `{item_total:,} C` (개당 {price:,}C)\n"
        
        delete_targets = [(interaction.user.id, name) for name, amt in sellable_items]

        await db.executemany("DELETE FROM inventory WHERE user_id = ? AND item_name = ?", delete_targets)
        await db.execute("UPDATE user_data SET coins = coins + ? WHERE user_id = ?", (total_earned, interaction.user.id))
        await db.commit()
        
        msg += f"\n**총 수익: +{total_earned:,} C**"
        
        if len(msg) > 1900:
            msg = msg[:1900] + "\n... (목록이 너무 길어 생략됨) ...\n" + f"\n**총 수익: +{total_earned:,} C**"

        await interaction.followup.send(msg)

    @app_commands.command(name="개별판매", description="가방에 있는 특정 물고기/아이템을 원하는 수량만큼 판매합니다.")
    @app_commands.autocomplete(물고기=inv_autocomplete)
    async def 개별판매(self, interaction: discord.Interaction, 물고기: str, 수량: int):
        target_fish = 물고기
        
        if 수량 <= 0:
            return await interaction.response.send_message("❌ 수량은 1마리 이상이어야 합니다.", ephemeral=True)
            
        async with db.conn.execute("SELECT amount FROM inventory WHERE user_id=? AND item_name=?", (interaction.user.id, target_fish)) as cursor:
            res = await cursor.fetchone()
        current_amount = res[0] if res else 0
        
        if current_amount < 수량:
            return await interaction.response.send_message(f"❌ 가방에 **{target_fish}**가 부족합니다. (현재 보유: {current_amount}마리)", ephemeral=True)
        
        price_per_item = MARKET_PRICES.get(target_fish, FISH_DATA[target_fish]["price"])
        total_earned = price_per_item * 수량
        
        await db.execute("UPDATE inventory SET amount = amount - ? WHERE user_id=? AND item_name=?", (수량, interaction.user.id, target_fish))
        await db.execute("UPDATE user_data SET coins = coins + ? WHERE user_id=?", (total_earned, interaction.user.id))
        await db.commit()
        
        await interaction.response.send_message(f"💰 **{target_fish}** {수량}마리를 팔아서 총 `{total_earned:,} C`를 얻었습니다! (개당 {price_per_item}C)")

    @app_commands.command(name="상점", description="유용한 아이템을 구경할 수 있는 상점입니다.")
    @check_boat_tier(2)
    async def 상점(self, interaction: discord.Interaction):
        embed = discord.Embed(title="🏪 수산시장 아이템 상점", color=0xf1c40f)
        embed.add_field(name="고급 미끼 🪱 (가격: 500 C)", value="다음 낚시 때 일반 어종을 피하고 희귀 어종 등장 확률을 올려줍니다.", inline=False)
        embed.add_field(name="자석 미끼 🧲 (가격: 800 C)", value="물고기는 낚이지 않지만, 바다 밑에 가라앉은 고철이나 보물을 확정적으로 건져냅니다.", inline=False)
        await interaction.response.send_message(embed=embed)

    @app_commands.command(name="구매", description="상점에서 아이템을 구매합니다.")
    @app_commands.choices(아이템=[
        app_commands.Choice(name="고급 미끼 🪱", value="고급 미끼 🪱"),
        app_commands.Choice(name="자석 미끼 🧲", value="자석 미끼 🧲")
    ])
    @check_boat_tier(2)
    async def 구매(self, interaction: discord.Interaction, 아이템: app_commands.Choice[str], 수량: int = 1):
        if 수량 <= 0: 
            return await interaction.response.send_message("❌ 수량은 1개 이상이어야 합니다.", ephemeral=True)
            
        coins, _, _ = await db.get_user_data(interaction.user.id)
        price = 500 * 수량 if 아이템.value == "고급 미끼 🪱" else 800 * 수량
        
        if coins < price:
            return await interaction.response.send_message(f"❌ 코인이 부족합니다! (필요: {price} C / 현재: {coins} C)", ephemeral=True)
        
        await db.execute("UPDATE user_data SET coins = coins - ? WHERE user_id = ?", (price, interaction.user.id))
        await db.execute("INSERT INTO inventory (user_id, item_name, amount) VALUES (?, ?, ?) ON CONFLICT(user_id, item_name) DO UPDATE SET amount = amount + ?", (interaction.user.id, 아이템.value, 수량, 수량))
        await db.commit()
        
        await interaction.response.send_message(f"🛍️ **{아이템.value}** {수량}개를 구매했습니다! (남은 코인: `{coins - price} C`)")

async def setup(bot):
    await bot.add_cog(MarketCog(bot))
