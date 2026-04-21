import discord
from discord.ext import commands
from discord import app_commands
import random

from fishing_core.database import db
from fishing_core.shared import FISH_DATA
from fishing_core.utils import check_boat_tier, inv_autocomplete
from fishing_core.views import BattleView, PvPBattleView

class BattleCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @app_commands.command(name="배틀", description="나의 가장 강한 물고기로 야생의 NPC 물고기와 턴제 배틀을 진행합니다!")
    @check_boat_tier(3)
    async def 배틀(self, interaction: discord.Interaction):
        await db.get_user_data(interaction.user.id) 
        
        async with db.conn.execute("SELECT item_name FROM bucket WHERE user_id=? AND amount > 0", (interaction.user.id,)) as cursor:
            items = await cursor.fetchall()
        
        if not items:
            return await interaction.response.send_message("❌ 통(배틀용)이 비어있습니다! 낚시 후 '통에 보관'을 선택해 전사를 포획하세요.", ephemeral=True)
        
        my_best_fish = None
        max_power = -1
        for (name,) in items:
            power = FISH_DATA[name]["power"]
            if power > max_power:
                max_power = power
                my_best_fish = name
                
        npc_pool = [name for name, data in FISH_DATA.items() if data["grade"] != "히든"]
        npc_fish = random.choice(npc_pool)
        
        view = BattleView(interaction.user, my_best_fish, npc_fish)
        await interaction.response.send_message(embed=view.generate_embed(), view=view)

    @app_commands.command(name="통", description="나 또는 특정 유저의 배틀 대기조(통)를 확인합니다.")
    async def 통(self, interaction: discord.Interaction, 유저: discord.Member = None):
        target = 유저 or interaction.user
        async with db.conn.execute("SELECT item_name, amount FROM bucket WHERE user_id=? AND amount > 0", (target.id,)) as cursor:
            items = await cursor.fetchall()
        
        embed = discord.Embed(title=f"🪣 {target.name}의 통 (배틀 대기조)", color=0x2ecc71)
        if items:
            item_list = "\n".join([f"• {name}: {amt}마리 (전투력: {FISH_DATA[name]['power']}⚡)" for name, amt in items])
            embed.add_field(name="출전 가능한 물고기", value=item_list, inline=False)
        else:
            embed.add_field(name="텅 비었습니다...", value="낚시 성공 후 '통에 보관'을 누르거나 `/통보관`을 사용하세요.", inline=False)
        await interaction.response.send_message(embed=embed)

    @app_commands.command(name="통보관", description="가방(인벤토리)에 있는 물고기를 통(배틀용)으로 옮깁니다.")
    @app_commands.autocomplete(물고기=inv_autocomplete)
    async def 통보관(self, interaction: discord.Interaction, 물고기: str, 수량: int = 1):
        if 수량 <= 0: return await interaction.response.send_message("❌ 수량은 1 이상이어야 합니다.", ephemeral=True)
        
        async with db.conn.execute("SELECT amount FROM inventory WHERE user_id=? AND item_name=?", (interaction.user.id, 물고기)) as cursor:
            res = await cursor.fetchone()
        current = res[0] if res else 0
        if current < 수량: return await interaction.response.send_message(f"❌ 가방에 **{물고기}**가 부족합니다. (보유: {current}마리)", ephemeral=True)

        await db.execute("UPDATE inventory SET amount = amount - ? WHERE user_id=? AND item_name=?", (수량, interaction.user.id, 물고기))
        await db.execute("INSERT INTO bucket (user_id, item_name, amount) VALUES (?, ?, ?) ON CONFLICT(user_id, item_name) DO UPDATE SET amount = amount + ?", (interaction.user.id, 물고기, 수량, 수량))
        await db.commit()
        await interaction.response.send_message(f"🎒➡️🪣 **{물고기}** {수량}마리를 배틀 출전용 통으로 옮겼습니다!")

    @app_commands.command(name="통꺼내기", description="통(배틀용)에 있는 물고기를 가방(인벤토리)으로 다시 가져옵니다.")
    async def 통꺼내기(self, interaction: discord.Interaction, 물고기: str, 수량: int = 1):
        if 수량 <= 0: return await interaction.response.send_message("❌ 수량은 1 이상이어야 합니다.", ephemeral=True)
        
        async with db.conn.execute("SELECT amount FROM bucket WHERE user_id=? AND item_name=?", (interaction.user.id, 물고기)) as cursor:
            res = await cursor.fetchone()
        current = res[0] if res else 0
        if current < 수량: return await interaction.response.send_message(f"❌ 통에 **{물고기}**가 없거나 부족합니다. (보유: {current}마리)", ephemeral=True)

        await db.execute("UPDATE bucket SET amount = amount - ? WHERE user_id=? AND item_name=?", (수량, interaction.user.id, 물고기))
        await db.execute("INSERT INTO inventory (user_id, item_name, amount) VALUES (?, ?, ?) ON CONFLICT(user_id, item_name) DO UPDATE SET amount = amount + ?", (interaction.user.id, 물고기, 수량, 수량))
        await db.commit()
        await interaction.response.send_message(f"🪣➡️🎒 **{물고기}** {수량}마리를 통에서 가방으로 꺼냈습니다!")

    @app_commands.command(name="수산대전", description="다른 유저를 지목하여 마라맛 PvP 배틀(약탈)을 겁니다!")
    @check_boat_tier(4)
    async def 수산대전(self, interaction: discord.Interaction, 상대: discord.Member):
        if interaction.user == 상대:
            return await interaction.response.send_message("❌ 자기 자신과는 싸울 수 없습니다!", ephemeral=True)
        if 상대.bot:
            return await interaction.response.send_message("❌ 봇과는 싸울 수 없습니다!", ephemeral=True)

        await db.get_user_data(interaction.user.id)
        await db.get_user_data(상대.id)

        async with db.conn.execute("SELECT item_name FROM bucket WHERE user_id=? AND amount > 0", (interaction.user.id,)) as cursor:
            items1 = await cursor.fetchall()
        if not items1:
            return await interaction.response.send_message("❌ 내 통(배틀용)이 비어있습니다! `/낚시` 후 통에 보관하세요.", ephemeral=True)

        async with db.conn.execute("SELECT item_name FROM bucket WHERE user_id=? AND amount > 0", (상대.id,)) as cursor:
            items2 = await cursor.fetchall()
        if not items2:
            return await interaction.response.send_message(f"❌ 상대방({상대.name})의 통이 비어있어 약탈할 수 없습니다!", ephemeral=True)

        def get_best_fish(items):
            best = None
            max_p = -1
            for (name,) in items:
                p = FISH_DATA[name]["power"]
                if p > max_p:
                    max_p = p
                    best = name
            return best

        p1_fish = get_best_fish(items1)
        p2_fish = get_best_fish(items2)

        view = PvPBattleView(interaction.user, 상대, p1_fish, p2_fish)
        
        await interaction.response.send_message(
            f"⚔️ {상대.mention}! **{interaction.user.name}**님이 수산대전을 걸어왔습니다!\n(방어하지 못하면 코인과 RP를 약탈당합니다!)", 
            embed=view.generate_embed(), 
            view=view
        )

async def setup(bot):
    await bot.add_cog(BattleCog(bot))
