import random
import discord
from discord import app_commands
from discord.ext import commands
from fishing_core.database import db
from fishing_core.shared import kst, FISH_DATA

class CollectionCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @app_commands.command(name="조개열기", description="가방에 있는 조개를 열어 진주를 찾습니다.")
    @app_commands.describe(조개종류="열어볼 조개의 종류를 선택하세요.", 수량="열어볼 수량을 입력하세요. (미입력 시 1개)")
    @app_commands.choices(조개종류=[
        app_commands.Choice(name="바지락 🐚 (5%)", value="바지락 🐚"),
        app_commands.Choice(name="홍합 🐚 (7%)", value="홍합 🐚"),
        app_commands.Choice(name="소라 🐚 (10%)", value="소라 🐚"),
        app_commands.Choice(name="가리비 🐚 (12%)", value="가리비 🐚"),
        app_commands.Choice(name="진주조개 🦪 (25%)", value="진주조개 🦪"),
    ])
    async def 조개열기(self, interaction: discord.Interaction, 조개종류: str, 수량: int = 1):
        if 수량 <= 0:
            return await interaction.response.send_message("❌ 수량은 1개 이상이어야 합니다.", ephemeral=True)

        async with db.conn.execute(
            "SELECT amount FROM inventory WHERE user_id=? AND item_name=?",
            (interaction.user.id, 조개종류)
        ) as cursor:
            row = await cursor.fetchone()

        if not row or row[0] < 수량:
            return await interaction.response.send_message(f"❌ **{조개종류}**가 부족합니다. (현재: {row[0] if row else 0}개)", ephemeral=True)

        # 확률 설정
        rates = {
            "바지락 🐚": 0.05,
            "홍합 🐚": 0.07,
            "소라 🐚": 0.10,
            "가리비 🐚": 0.12,
            "진주조개 🦪": 0.25
        }
        rate = rates.get(조개종류, 0.05)

        success_count = 0
        for _ in range(수량):
            if random.random() < rate:
                success_count += 1

        # 인벤토리 업데이트
        await db.execute(
            "UPDATE inventory SET amount = amount - ? WHERE user_id=? AND item_name=?",
            (수량, interaction.user.id, 조개종류)
        )
        
        if success_count > 0:
            await db.execute(
                "INSERT INTO inventory (user_id, item_name, amount) VALUES (?, '진주 ⚪', ?) "
                "ON CONFLICT(user_id, item_name) DO UPDATE SET amount = amount + ?",
                (interaction.user.id, success_count, success_count)
            )

        await db.commit()

        embed = discord.Embed(title="🐚 조개 열기 결과", color=0xFFFFFF if success_count == 0 else 0x00FFFF)
        embed.description = f"**{조개종류}** {수량}개를 정성스럽게 열어보았습니다."
        
        if success_count > 0:
            embed.add_field(name="✨ 획득 성공!", value=f"조개 속에서 영롱하게 빛나는 **진주 ⚪** {success_count}개를 발견했습니다!", inline=False)
            embed.set_thumbnail(url="https://cdn-icons-png.flaticon.com/512/2908/2908307.png")
        else:
            embed.add_field(name="💨 획득 실패", value="아쉽게도 알맹이만 있고 진주는 들어있지 않았습니다.", inline=False)
            
        embed.set_footer(text=f"남은 {조개종류}: {row[0] - 수량}개")
        await interaction.response.send_message(embed=embed)

    @app_commands.command(name="진주상점", description="모은 진주를 특별한 보상으로 교환합니다.")
    async def 진주상점(self, interaction: discord.Interaction):
        from discord.ui import Select, View
        
        async with db.conn.execute("SELECT amount FROM inventory WHERE user_id=? AND item_name='진주 ⚪'", (interaction.user.id,)) as cursor:
            row = await cursor.fetchone()
        pearl_count = row[0] if row else 0

        embed = discord.Embed(title="⚪ 진주 비밀 상점", color=0x00FFFF)
        embed.description = f"바다의 눈물이라 불리는 진주를 모아오셨군요.\n현재 보유 중인 진주: **{pearl_count}개**"
        
        shop_items = {
            "blessing": {"name": "🌊 바다의 축복 (영구)", "desc": "최대 행동력 +10 증가", "price": 15},
            "luck": {"name": "🍀 심해의 행운 (7일)", "desc": "레전드 이상 등급 확률 5% 증가", "price": 5},
            "map": {"name": "📜 고대의 보물지도", "desc": "고대 해적의 보물지도 1장 획득", "price": 3},
            "title": {"name": "🏷️ [진주 수집가] 칭호", "desc": "특별한 칭호를 영구 획득", "price": 10},
        }

        for k, v in shop_items.items():
            embed.add_field(name=f"{v['name']} (⚪ {v['price']}개)", value=v['desc'], inline=False)

        class PearlShopSelect(Select):
            def __init__(self):
                options = [
                    discord.SelectOption(label=v['name'], description=v['desc'], value=k)
                    for k, v in shop_items.items()
                ]
                super().__init__(placeholder="구매할 물품을 선택하세요...", options=options)

            async def callback(self, interaction: discord.Interaction):
                item_key = self.values[0]
                item = shop_items[item_key]
                
                async with db.conn.execute("SELECT amount FROM inventory WHERE user_id=? AND item_name='진주 ⚪'", (interaction.user.id,)) as cursor:
                    row = await cursor.fetchone()
                current_pearls = row[0] if row else 0

                if current_pearls < item['price']:
                    return await interaction.response.send_message(f"❌ 진주가 부족합니다! (필요: {item['price']}개 / 보유: {current_pearls}개)", ephemeral=True)

                # 구매 처리
                await db.execute("UPDATE inventory SET amount = amount - ? WHERE user_id=? AND item_name='진주 ⚪'", (item['price'], interaction.user.id))
                
                msg = f"✅ **{item['name']}**(을)를 구매했습니다!"
                
                if item_key == "blessing":
                    await db.execute("UPDATE user_data SET max_stamina = max_stamina + 10 WHERE user_id=?", (interaction.user.id,))
                elif item_key == "luck":
                    import datetime
                    end_time = (datetime.datetime.now(kst) + datetime.timedelta(days=7)).isoformat()
                    await db.execute("INSERT INTO active_buffs (user_id, buff_type, end_time) VALUES (?, 'deep_sea_luck', ?) ON CONFLICT(user_id, buff_type) DO UPDATE SET end_time = ?", (interaction.user.id, end_time, end_time))
                elif item_key == "map":
                    await db.execute("INSERT INTO inventory (user_id, item_name, amount) VALUES (?, '고대 해적의 보물지도 🗺️', 1) ON CONFLICT(user_id, item_name) DO UPDATE SET amount = amount + 1", (interaction.user.id,))
                elif item_key == "title":
                    await db.execute("UPDATE user_data SET title='[진주 수집가]' WHERE user_id=?", (interaction.user.id,))
                
                await db.commit()
                await interaction.response.send_message(msg, ephemeral=True)

        view = View()
        view.add_item(PearlShopSelect())
        await interaction.response.send_message(embed=embed, view=view, ephemeral=True)

    @app_commands.command(name="세트효과", description="수집한 물고기/아이템 세트에 따른 영구 효과를 확인합니다.")
    async def 세트효과(self, interaction: discord.Interaction):
        async with db.conn.execute("SELECT item_name FROM fish_dex WHERE user_id=?", (interaction.user.id,)) as cursor:
            dex_items = {row[0] for row in await cursor.fetchall()}
            
        async with db.conn.execute("SELECT item_name FROM inventory WHERE user_id=? AND amount > 0", (interaction.user.id,)) as cursor:
            inv_items = {row[0] for row in await cursor.fetchall()}

        sets = [
            {
                "name": "🐚 조개 수집가",
                "items": ["바지락 🐚", "홍합 🐚", "소라 🐚", "가리비 🐚", "진주조개 🦪"],
                "bonus": "행동력 소모 -1 (확률 10%)",
                "desc": "바닷가의 흔한 조개들을 모두 모았습니다."
            },
            {
                "name": "🦖 태고의 지배자",
                "items": ["메갈로돈 🦈", "둔클레오스테우스 🦖", "모사사우루스 🦖"],
                "bonus": "판매 가격 +5% 증가",
                "desc": "멸종된 고대 괴수들을 도감에 등록했습니다."
            },
            {
                "name": "💀 심연의 공포",
                "items": ["심해의 파멸, 크라켄 🦑", "심연의 지배자, 레비아탄 🌋", "세계를 감싼 뱀, 요르문간드 🐍"],
                "bonus": "레이드 대미지 +10% 증가",
                "desc": "심해의 가장 깊은 곳에 잠든 재앙들을 마주했습니다."
            }
        ]

        embed = discord.Embed(title="📜 컬렉션 세트 효과", color=0xf1c40f)
        embed.description = "특정 조건을 만족하면 자동으로 효과가 상시 적용됩니다."

        for s in sets:
            # 도감 또는 인벤토리에 있으면 수집한 것으로 간주 (일반 아이템은 인벤토리, 물고기는 도감)
            collected = 0
            for item in s["items"]:
                if item in dex_items or item in inv_items:
                    collected += 1
            
            status = "✅ 활성화됨" if collected == len(s["items"]) else f"❌ 비활성 ({collected}/{len(s['items'])})"
            items_str = ", ".join(s["items"])
            embed.add_field(
                name=f"{s['name']} ({status})",
                value=f"**효과:** {s['bonus']}\n**조건:** {items_str}\n*{s['desc']}*",
                inline=False
            )

        await interaction.response.send_message(embed=embed)

async def setup(bot):
    await bot.add_cog(CollectionCog(bot))
