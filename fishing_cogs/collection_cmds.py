import datetime
import json
import random

import discord
from discord import app_commands
from discord.ext import commands

from fishing_core.database import db
from fishing_core.shared import FISH_DATA, format_grade_label, kst
from fishing_core.utils import EmbedFactory


class CollectionCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        try:
            with open("collections.json", encoding="utf-8") as f:
                self.collections = json.load(f)
        except Exception:
            self.collections = {}

    @app_commands.command(name="도감", description="나 또는 특정 유저가 지금까지 발견한 모든 물고기 기록과 수집률을 확인합니다.")
    async def 도감(self, interaction: discord.Interaction, 유저: discord.Member = None):
        target = 유저 or interaction.user
        async with db.conn.execute("SELECT item_name FROM fish_dex WHERE user_id=?", (target.id,)) as cursor:
            dex_items = await cursor.fetchall()

        collected_names = [item[0] for item in dex_items]
        total_fish = len(FISH_DATA)
        collected_count = len(collected_names)
        percent = (collected_count / total_fish) * 100

        if percent == 100: dex_rank = "👑 그랜드 마스터 앵글러"
        elif percent >= 70: dex_rank = "🥇 엘리트 어류학자"
        elif percent >= 50: dex_rank = "🥈 어류학자"
        elif percent >= 30: dex_rank = "🥉 낚시계의 새싹"
        elif percent >= 10: dex_rank = "🌱 낚시계의 떡잎"
        else: dex_rank = "🥚 초보 낚시꾼"

        title = await db.get_user_title(target.id)
        display_name = f"{title} {target.name}" if title else target.name

        embed = EmbedFactory.build(title=f"📖 {display_name}님의 낚시 도감", type="info")
        if target.avatar:
            embed.set_thumbnail(url=target.avatar.url)

        embed.add_field(name="현재 수집률", value=f"**{collected_count} / {total_fish} 종** (`{percent:.1f}%`)", inline=False)
        embed.add_field(name="도감 등급", value=f"**{dex_rank}**", inline=False)

        if collected_names:
            recent_fish = "\n".join(
                [f"• {name} `{format_grade_label(FISH_DATA.get(name, {}).get('grade', '일반'))}`" for name in collected_names[-5:]]
            )
            embed.add_field(name="최근 발견한 어종", value=recent_fish, inline=False)

            async with db.conn.execute("SELECT item_name, max_size FROM fish_records WHERE user_id=? ORDER BY max_size DESC LIMIT 5", (target.id,)) as cursor:
                records = await cursor.fetchall()
            if records:
                record_str = "\n".join(
                    [f"🏆 **{name}** `{format_grade_label(FISH_DATA.get(name, {}).get('grade', '일반'))}` : `{size} cm`" for name, size in records]
                )
                embed.add_field(name="월척 기록 (Top 5)", value=record_str, inline=False)
        else:
            embed.add_field(name="최근 발견한 어종", value="아직 발견한 물고기가 없습니다.", inline=False)

        await interaction.response.send_message(embed=embed)

    @app_commands.command(name="도감보상", description="수집한 어종 수에 따른 특별 보상을 수령합니다.")
    async def 도감보상(self, interaction: discord.Interaction):
        async with db.conn.execute("SELECT COUNT(*) FROM fish_dex WHERE user_id=?", (interaction.user.id,)) as cursor:
            dex_count = (await cursor.fetchone())[0]

        async with db.conn.execute("SELECT dex_rewards FROM user_data WHERE user_id=?", (interaction.user.id,)) as cursor:
            res = await cursor.fetchone()
        claimed = json.loads(res[0]) if res and res[0] else {}

        milestones = [
            {"count": 20, "reward_c": 5000, "title": "신입 어부", "id": "20"},
            {"count": 50, "reward_c": 20000, "title": "어부의 혼", "id": "50"},
            {"count": 100, "reward_c": 100000, "title": "바다의 지배자", "id": "100"},
            {"count": 150, "reward_c": 500000, "title": "용왕의 친구", "id": "150"},
        ]

        total_species = len(FISH_DATA)
        milestones.append({"count": total_species, "reward_c": 1000000, "title": "전설의 낚시꾼", "id": "full"})

        embed = EmbedFactory.build(title="📜 어종 도감 수집 보상", type="info")
        embed.description = f"현재 수집한 어종: **{dex_count} / {total_species}** 종\n\n"

        can_claim = False
        new_rewards = []

        for m in milestones:
            is_claimed = claimed.get(m["id"], False)
            if not is_claimed and dex_count >= m["count"]:
                claimed[m["id"]] = True
                await db.execute("UPDATE user_data SET coins = coins + ?, title = ? WHERE user_id=?", (m["reward_c"], f"[{m['title']}]", interaction.user.id))
                can_claim = True
                new_rewards.append(f"• {m['count']}종 달성 보상: `{m['reward_c']:,} C` + 칭호 `[{m['title']}]` ✅")
                status = "🎁 수령 완료!"
            else:
                status = "✅ 수령 완료" if is_claimed else (f"🔒 미달성 (목표: {m['count']}종)" if dex_count < m["count"] else "🎁 수령 가능")

            embed.add_field(
                name=f"{m['count']}종 달성 보상",
                value=f"• 보상: `{m['reward_c']:,} C` + 칭호 `[{m['title']}]` \n• 상태: **{status}**",
                inline=False,
            )

        if can_claim:
            await db.execute("UPDATE user_data SET dex_rewards = ? WHERE user_id=?", (json.dumps(claimed), interaction.user.id))
            await db.commit()
            reward_txt = "\n".join(new_rewards)
            await interaction.response.send_message(f"🎉 **축하합니다! 새로운 보상을 수령했습니다!**\n{reward_txt}", embed=embed)
        else:
            await interaction.response.send_message("💡 아직 수령할 수 있는 새로운 보상이 없습니다. 더 많은 물고기를 낚아보세요!", embed=embed, ephemeral=True)

    @app_commands.command(name="컬렉션", description="특정 어종 그룹을 모두 수집하여 특별한 보상을 수령합니다.")
    async def 컬렉션(self, interaction: discord.Interaction):
        async with db.conn.execute("SELECT item_name FROM fish_dex WHERE user_id=?", (interaction.user.id,)) as cursor:
            dex_items = [row[0] for row in await cursor.fetchall()]
        
        async with db.conn.execute("SELECT claimed_collections FROM user_data WHERE user_id=?", (interaction.user.id,)) as cursor:
            res = await cursor.fetchone()
        claimed = json.loads(res[0]) if res and res[0] else {}

        embed = EmbedFactory.build(title="📜 어류 수집 세트 컬렉션", type="warning")
        embed.description = "특정 물고기들을 모두 도감에 등록하면 특별한 보상을 드립니다!\n\n"

        can_claim_any = False
        newly_claimed = []

        for set_name, data in self.collections.items():
            required_fish = data["fish"]
            collected_in_set = [f for f in required_fish if f in dex_items]
            is_complete = len(collected_in_set) == len(required_fish)
            is_claimed = claimed.get(set_name, False)

            status = "✅ 수령 완료" if is_claimed else ("🎁 보상 수령 가능!" if is_complete else f"⏳ 진행 중 ({len(collected_in_set)}/{len(required_fish)})")
            fish_list_str = ", ".join([f"**{f}**" if f in dex_items else f"~~{f}~~" for f in required_fish])
            
            embed.add_field(
                name=f"{set_name} ({status})",
                value=f"• 대상: {fish_list_str}\n• 보상: `{data['reward_coins']:,} C` + 칭호 `{data['reward_title']}`",
                inline=False
            )

            if is_complete and not is_claimed:
                claimed[set_name] = True
                await db.execute("UPDATE user_data SET coins = coins + ?, title = ? WHERE user_id=?", (data["reward_coins"], data["reward_title"], interaction.user.id))
                can_claim_any = True
                newly_claimed.append(f"🎉 **[{set_name}]** 컬렉션 완성! `{data['reward_coins']:,} C` + 칭호 `{data['reward_title']}` 획득!")

        if can_claim_any:
            await db.execute("UPDATE user_data SET claimed_collections = ? WHERE user_id=?", (json.dumps(claimed), interaction.user.id))
            await db.commit()
            msg = "\n".join(newly_claimed)
            await interaction.response.send_message(f"🎊 **축하합니다! 컬렉션을 완성하여 보상을 수령했습니다!**\n{msg}", embed=embed)
        else:
            await interaction.response.send_message(embed=embed)

    @app_commands.command(name="지도합성", description="찢어진 지도 조각(A,B,C,D) 4종을 모아 '고대 해적의 보물지도 🗺️'를 완성합니다.")
    async def 지도합성(self, interaction: discord.Interaction, 수량: int = 1):
        if 수량 < 1:
            return await interaction.response.send_message("❌ 최소 1개 이상 합성해야 합니다.", ephemeral=True)

        pieces = ["찢어진 지도 조각 A 🧩", "찢어진 지도 조각 B 🧩", "찢어진 지도 조각 C 🧩", "찢어진 지도 조각 D 🧩"]

        async with db.conn.execute("SELECT item_name, amount FROM inventory WHERE user_id=? AND amount > 0", (interaction.user.id,)) as cursor:
            inv_items = {row[0]: row[1] for row in await cursor.fetchall()}

        for p in pieces:
            if inv_items.get(p, 0) < 수량:
                return await interaction.response.send_message(f"❌ 조각이 부족합니다!\n(부족: **{p}**가 {수량}개 필요하지만 {inv_items.get(p, 0)}개 있음)", ephemeral=True)

        for p in pieces:
            await db.execute("UPDATE inventory SET amount = amount - ? WHERE user_id=? AND item_name=?", (수량, interaction.user.id, p))

        await db.execute("INSERT INTO inventory (user_id, item_name, amount) VALUES (?, '고대 해적의 보물지도 🗺️', ?) ON CONFLICT(user_id, item_name) DO UPDATE SET amount = amount + ?", (interaction.user.id, 수량, 수량))
        await db.commit()

        embed = EmbedFactory.build(title="🗺️ 보물지도 합성 성공!", description=f"조각들을 정교하게 이어 붙여 **고대 해적의 보물지도 🗺️** {수량}장을 완성했습니다!", type="warning")
        await interaction.response.send_message(embed=embed)

    @app_commands.command(name="지도사용", description="'고대 해적의 보물지도'를 사용하여 특별한 해역 버프(30분)를 개방합니다.")
    async def 지도사용(self, interaction: discord.Interaction):
        async with db.conn.execute("SELECT amount FROM inventory WHERE user_id=? AND item_name='고대 해적의 보물지도 🗺️'", (interaction.user.id,)) as cursor:
            res = await cursor.fetchone()

        if not res or res[0] < 1:
            return await interaction.response.send_message("❌ 가방에 **고대 해적의 보물지도 🗺️**가 없습니다!", ephemeral=True)

        await db.execute("UPDATE inventory SET amount = amount - 1 WHERE user_id=? AND item_name='고대 해적의 보물지도 🗺️'", (interaction.user.id,))

        end_time = (datetime.datetime.now(kst) + datetime.timedelta(minutes=30)).strftime('%Y-%m-%d %H:%M:%S')
        buffs = ["ghost_sea_open", "deep_sea_rift", "golden_tide"]
        chosen_buff = random.choice(buffs)

        await db.execute("INSERT OR REPLACE INTO active_buffs (user_id, buff_type, end_time) VALUES (?, ?, ?)", (interaction.user.id, chosen_buff, end_time))
        await db.commit()

        if chosen_buff == "ghost_sea_open":
            title, desc = "☠️ 망자의 해역 개방...", "앞으로 **30분 동안**, 물고기 대신 **해적의 금화 🪙, 낡은 고철 ⚙️, 보물상자 🧰**만 낚입니다!"
        elif chosen_buff == "deep_sea_rift":
            title, desc = "🌊 심해의 균열 발견!", "앞으로 **30분 동안**, **[심해] 속성** 어종들의 등장 확률이 3배 상승합니다!"
        else:
            title, desc = "✨ 황금 조류 발견!", "앞으로 **30분 동안**, 낚시 타이밍이 매우 넉넉해져 성공 확률이 대폭 상승합니다!"

        embed = EmbedFactory.build(title=title, description=desc, type="warning")
        await interaction.response.send_message(embed=embed)

    @app_commands.command(name="조각교환", description="같은 지도 조각 3개를 다른 무작위 조각 1개로 교환합니다.")
    @app_commands.choices(조각=[
        app_commands.Choice(name="A 조각 🧩", value="찢어진 지도 조각 A 🧩"),
        app_commands.Choice(name="B 조각 🧩", value="찢어진 지도 조각 B 🧩"),
        app_commands.Choice(name="C 조각 🧩", value="찢어진 지도 조각 C 🧩"),
        app_commands.Choice(name="D 조각 🧩", value="찢어진 지도 조각 D 🧩"),
    ])
    async def 조각교환(self, interaction: discord.Interaction, 조각: app_commands.Choice[str]):
        async with db.conn.execute("SELECT amount FROM inventory WHERE user_id=? AND item_name=?", (interaction.user.id, 조각.value)) as cursor:
            res = await cursor.fetchone()

        if not res or res[0] < 3:
            return await interaction.response.send_message(f"❌ **{조각.name}**가 3개 이상 필요합니다.", ephemeral=True)

        all_pieces = ["찢어진 지도 조각 A 🧩", "찢어진 지도 조각 B 🧩", "찢어진 지도 조각 C 🧩", "찢어진 지도 조각 D 🧩"]
        reward_piece = random.choice([p for p in all_pieces if p != 조각.value])

        await db.execute("UPDATE inventory SET amount = amount - 3 WHERE user_id=? AND item_name=?", (interaction.user.id, 조각.value))
        await db.execute("INSERT INTO inventory (user_id, item_name, amount) VALUES (?, ?, 1) ON CONFLICT(user_id, item_name) DO UPDATE SET amount = amount + 1", (interaction.user.id, reward_piece))
        await db.commit()

        await interaction.response.send_message(f"♻️ 교환 성공! **{조각.name}** 3개를 주고 **{reward_piece}** 1개를 얻었습니다!")

    @app_commands.command(name="조개열기", description="가방에 있는 조개를 열어 진주를 찾습니다.")
    @app_commands.choices(조개종류=[
        app_commands.Choice(name="바지락 🐚 (5%)", value="바지락 🐚"),
        app_commands.Choice(name="홍합 🐚 (7%)", value="홍합 🐚"),
        app_commands.Choice(name="소라 🐚 (10%)", value="소라 🐚"),
        app_commands.Choice(name="가리비 🐚 (12%)", value="가리비 🐚"),
        app_commands.Choice(name="진주조개 🦪 (25%)", value="진주조개 🦪"),
    ])
    async def 조개열기(self, interaction: discord.Interaction, 조개종류: str, 수량: int = 1):
        if 수량 <= 0: return await interaction.response.send_message("❌ 수량은 1개 이상이어야 합니다.", ephemeral=True)

        async with db.conn.execute("SELECT amount FROM inventory WHERE user_id=? AND item_name=?", (interaction.user.id, 조개종류)) as cursor:
            row = await cursor.fetchone()
        if not row or row[0] < 수량: return await interaction.response.send_message("❌ 조개가 부족합니다.", ephemeral=True)

        rates = {"바지락 🐚": 0.05, "홍합 🐚": 0.07, "소라 🐚": 0.10, "가리비 🐚": 0.12, "진주조개 🦪": 0.25}
        rate = rates.get(조개종류, 0.05)
        success = sum(1 for _ in range(수량) if random.random() < rate)

        await db.execute("UPDATE inventory SET amount = amount - ? WHERE user_id=? AND item_name=?", (수량, interaction.user.id, 조개종류))
        if success > 0:
            await db.execute("INSERT INTO inventory (user_id, item_name, amount) VALUES (?, '진주 ⚪', ?) ON CONFLICT(user_id, item_name) DO UPDATE SET amount = amount + ?", (interaction.user.id, success, success))
        await db.commit()

        embed = EmbedFactory.build(title="🐚 조개 열기 결과", type="info")
        if success > 0:
            embed.add_field(name="✨ 획득 성공!", value=f"**진주 ⚪** {success}개를 발견했습니다!", inline=False)
        else:
            embed.description = "아쉽게도 진주는 들어있지 않았습니다."
        await interaction.response.send_message(embed=embed)

    @app_commands.command(name="진주상점", description="모은 진주를 특별한 보상으로 교환합니다.")
    async def 진주상점(self, interaction: discord.Interaction):
        # 기존 진주상점 로직 유지... (코드 간소화를 위해 주요 부분만 포함하거나 전체 유지)
        from discord.ui import Select, View
        
        async with db.conn.execute("SELECT amount FROM inventory WHERE user_id=? AND item_name='진주 ⚪'", (interaction.user.id,)) as cursor:
            row = await cursor.fetchone()
        pearl_count = row[0] if row else 0

        embed = EmbedFactory.build(title="⚪ 진주 비밀 상점", type="info")
        embed.description = f"보유 중인 진주: **{pearl_count}개**"
        
        shop_items = {
            "blessing": {"name": "🌊 바다의 축복 (영구)", "desc": "최대 행동력 +10 증가", "price": 15},
            "luck": {"name": "🍀 심해의 행운 (7일)", "desc": "레전드 이상 확률 5% 증가", "price": 5},
            "map": {"name": "📜 고대의 보물지도", "desc": "보물지도 1장 획득", "price": 3},
            "title": {"name": "🏷️ [진주 수집가] 칭호", "desc": "특별 칭호 획득", "price": 10},
        }

        for k, v in shop_items.items():
            embed.add_field(name=f"{v['name']} (⚪ {v['price']}개)", value=v['desc'], inline=False)

        class PearlShopSelect(Select):
            def __init__(self):
                options = [discord.SelectOption(label=v['name'], description=v['desc'], value=k) for k, v in shop_items.items()]
                super().__init__(placeholder="구매할 물품 선택...", options=options)

            async def callback(self, interaction: discord.Interaction):
                item_key = self.values[0]
                item = shop_items[item_key]
                async with db.conn.execute("SELECT amount FROM inventory WHERE user_id=? AND item_name='진주 ⚪'", (interaction.user.id,)) as cursor:
                    row = await cursor.fetchone()
                if not row or row[0] < item['price']: return await interaction.response.send_message("❌ 진주가 부족합니다.", ephemeral=True)

                await db.execute("UPDATE inventory SET amount = amount - ? WHERE user_id=? AND item_name='진주 ⚪'", (item['price'], interaction.user.id))
                if item_key == "blessing": await db.execute("UPDATE user_data SET max_stamina = MIN(300, max_stamina + 10) WHERE user_id=?", (interaction.user.id,))
                elif item_key == "luck":
                    end_time = (datetime.datetime.now(kst) + datetime.timedelta(days=7)).isoformat()
                    await db.execute("INSERT INTO active_buffs (user_id, buff_type, end_time) VALUES (?, 'deep_sea_luck', ?) ON CONFLICT(user_id, buff_type) DO UPDATE SET end_time = ?", (interaction.user.id, end_time, end_time))
                elif item_key == "map": await db.execute("INSERT INTO inventory (user_id, item_name, amount) VALUES (?, '고대 해적의 보물지도 🗺️', 1) ON CONFLICT(user_id, item_name) DO UPDATE SET amount = amount + 1", (interaction.user.id,))
                elif item_key == "title": await db.execute("UPDATE user_data SET title='[진주 수집가]' WHERE user_id=?", (interaction.user.id,))
                
                await db.commit()
                await interaction.response.send_message(f"✅ **{item['name']}** 구매 완료!", ephemeral=True)

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
            {"name": "🐚 조개 수집가", "items": ["바지락 🐚", "홍합 🐚", "소라 🐚", "가리비 🐚", "진주조개 🦪"], "bonus": "행동력 소모 -1 (확률 10%)", "desc": "해안가 조개 완수"},
            {"name": "🦖 태고의 지배자", "items": ["메갈로돈 🦈", "둔클레오스테우스 🦖", "모사사우루스 🦖"], "bonus": "판매 가격 +5% 증가", "desc": "고대 생명체 완수"},
            {"name": "💀 심연의 공포", "items": ["심해의 파멸, 크라켄 🦑", "심연의 지배자, 레비아탄 🌋", "세계를 감싼 뱀, 요르문간드 🐍"], "bonus": "레이드 대미지 +10% 증가", "desc": "심해의 공포 완수"}
        ]

        embed = EmbedFactory.build(title="📜 컬렉션 세트 효과", type="warning")
        for s in sets:
            collected = sum(1 for item in s["items"] if item in dex_items or item in inv_items)
            status = "✅ 활성화됨" if collected == len(s["items"]) else f"❌ 비활성 ({collected}/{len(s['items'])})"
            embed.add_field(name=f"{s['name']} ({status})", value=f"**효과:** {s['bonus']}\n**조건:** {', '.join(s['items'])}", inline=False)
        await interaction.response.send_message(embed=embed)


async def setup(bot):
    await bot.add_cog(CollectionCog(bot))
