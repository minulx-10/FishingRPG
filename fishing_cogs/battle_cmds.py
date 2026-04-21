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
        async with db.conn.execute("SELECT item_name FROM inventory WHERE user_id=? AND amount > 0 AND is_locked=1", (interaction.user.id,)) as cursor:
            items = await cursor.fetchall()
        
        if not items:
            return await interaction.response.send_message("❌ 잠금(보호) 처리된 물고기가 없습니다! 인벤토리에서 `/잠금` 명령어로 전사를 보호하세요.", ephemeral=True)
        
        my_best_fish = None
        max_power = -1
        for (name,) in items:
            power = 99999 if name == "용왕 👑" else FISH_DATA.get(name, {}).get("power", -1)
            if power > max_power:
                max_power = power
                my_best_fish = name
                
        if max_power == -1 or not my_best_fish:
            return await interaction.response.send_message("❌ 출전할 유효한 물고기가 없습니다! (잠금된 목록에 일반 아이템만 존재합니다)", ephemeral=True)
                
        npc_pool = [name for name, data in FISH_DATA.items() if data.get("grade") != "히든"]
        npc_fish = random.choice(npc_pool)
        
        view = BattleView(interaction.user, my_best_fish, npc_fish)
        await interaction.response.send_message(embed=view.generate_embed(), view=view)

    @app_commands.command(name="잠금목록", description="나 또는 특정 유저의 가방에서 잠금(보호 및 배틀용) 처리된 목록을 확인합니다.")
    async def 잠금목록(self, interaction: discord.Interaction, 유저: discord.Member = None):
        target = 유저 or interaction.user
        async with db.conn.execute("SELECT item_name, amount FROM inventory WHERE user_id=? AND amount > 0 AND is_locked=1", (target.id,)) as cursor:
            items = await cursor.fetchall()
        
        embed = discord.Embed(title=f"🔒 {target.name}의 잠금(보호) 목록", color=0x2ecc71)
        if items:
            item_list = ""
            for name, amt in items:
                power = 99999 if name == "용왕 👑" else FISH_DATA.get(name, {}).get("power", 0)
                if power > 0:
                    item_list += f"• {name}: {amt}마리 (전투력: {power}⚡)\n"
                else:
                    item_list += f"• {name}: {amt}개\n"
            embed.add_field(name="보존된 아이템 및 전사", value=item_list, inline=False)
        else:
            embed.add_field(name="텅 비었습니다...", value="`/잠금` 명령어를 통해 중요한 물고기와 아이템을 판매로부터 보호하세요.", inline=False)
        await interaction.response.send_message(embed=embed)

    @app_commands.command(name="수산대전", description="다른 유저를 지목하여 마라맛 PvP 배틀(약탈)을 겁니다!")
    @check_boat_tier(4)
    async def 수산대전(self, interaction: discord.Interaction, 상대: discord.Member):
        if interaction.user == 상대:
            return await interaction.response.send_message("❌ 자기 자신과는 싸울 수 없습니다!", ephemeral=True)
        if 상대.bot:
            return await interaction.response.send_message("❌ 봇과는 싸울 수 없습니다!", ephemeral=True)

        await db.get_user_data(interaction.user.id)
        await db.get_user_data(상대.id)
        
        async with db.conn.execute("SELECT peace_mode FROM user_data WHERE user_id=?", (상대.id,)) as cursor:
            res = await cursor.fetchone()
        if res and res[0] == 1:
            return await interaction.response.send_message(f"❌ '{상대.name}'님은 현재 **평화 모드** 🕊️ 상태입니다. (약탈 불가)", ephemeral=True)

        async with db.conn.execute("SELECT item_name FROM inventory WHERE user_id=? AND amount > 0 AND is_locked=1", (interaction.user.id,)) as cursor:
            items1 = await cursor.fetchall()
        if not items1:
            return await interaction.response.send_message("❌ 내 잠금 목록이 비어있습니다! `/잠금`으로 출전할 물고기를 보존하세요.", ephemeral=True)

        async with db.conn.execute("SELECT item_name FROM inventory WHERE user_id=? AND amount > 0 AND is_locked=1", (상대.id,)) as cursor:
            items2 = await cursor.fetchall()
        if not items2:
            return await interaction.response.send_message(f"❌ 상대방({상대.name})의 잠금 목록이 비어있어 약탈할 수 없습니다!", ephemeral=True)

        def get_top3_fish(items):
            fish_list = []
            for (name,) in items:
                p = 99999 if name == "용왕 👑" else FISH_DATA.get(name, {}).get("power", -1)
                if p > 0:
                    fish_list.append((name, p))
            fish_list.sort(key=lambda x: x[1], reverse=True)
            return fish_list[:3]

        p1_deck = get_top3_fish(items1)
        p2_deck = get_top3_fish(items2)
        
        if not p1_deck: return await interaction.response.send_message("❌ 내 잠금 목록에 출전 가능한 유효한 물고기가 없습니다!", ephemeral=True)
        if not p2_deck: return await interaction.response.send_message(f"❌ 상대방({상대.name})에게 유효한 배틀 물고기가 없어 약탈할 수 없습니다!", ephemeral=True)

        # 현재 뷰(View)가 단일 개체 출전(p1_fish, p2_fish)만 지원하므로,
        # 향후 뷰를 3v3 용으로 개편하기 전까지는 각 덱의 첫 번째(에이스)로 출전시킵니다.
        p1_fish_name = p1_deck[0][0]
        p2_fish_name = p2_deck[0][0]

        async with db.conn.execute("SELECT title FROM user_data WHERE user_id=?", (interaction.user.id,)) as cursor:
            res = await cursor.fetchone()
        title1 = res[0] if res else ""
        display_name1 = f"{title1} {interaction.user.name}" if title1 else interaction.user.name

        view = PvPBattleView(interaction.user, 상대, p1_fish_name, p2_fish_name)
        
        await interaction.response.send_message(
            f"⚔️ {상대.mention}! **{display_name1}**님이 수산대전을 걸어왔습니다!\n(방어하지 못하면 코인과 RP를 약탈당합니다!)", 
            embed=view.generate_embed(), 
            view=view
        )

    @app_commands.command(name="평화모드", description="수산대전(PvP) 약탈을 거부하는 평화 모드를 켜거나 끕니다.")
    async def 평화모드(self, interaction: discord.Interaction):
        async with db.conn.execute("SELECT peace_mode FROM user_data WHERE user_id=?", (interaction.user.id,)) as cursor:
            res = await cursor.fetchone()
        
        current_mode = res[0] if res else 0
        new_mode = 1 if current_mode == 0 else 0
        status_text = "켜졌습니다 🕊️ (이제 다른 유저가 나를 약탈할 수 없습니다)" if new_mode == 1 else "꺼졌습니다 ⚔️ (이제 다른 유저와 PvP 전투가 가능합니다)"
        
        await db.execute("UPDATE user_data SET peace_mode=? WHERE user_id=?", (new_mode, interaction.user.id))
        await db.commit()
        
        await interaction.response.send_message(f"✅ 평화 모드가 **{status_text}**")

async def setup(bot):
    await bot.add_cog(BattleCog(bot))
