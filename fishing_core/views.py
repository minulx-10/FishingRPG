import datetime
import random

import discord
from discord.ui import Button, View

from fishing_core.database import db
from fishing_core.services.achievement_service import AchievementService
from fishing_core.services.battle_service import BattleService
from fishing_core.shared import (
    FISH_DATA,
    format_grade_label,
    kst,
)


class FishActionView(View):
    def __init__(self, user, fish_name):
        super().__init__(timeout=60)
        self.user = user
        self.fish_name = fish_name
        self.message = None

    async def _add_to_inventory(self, is_locked=0):
        async with db.conn.execute("SELECT amount FROM inventory WHERE user_id=? AND item_name=?", (self.user.id, self.fish_name)) as cursor:
            res = await cursor.fetchone()
        if res:
            await db.execute("UPDATE inventory SET amount = amount + 1 WHERE user_id=? AND item_name=?", (self.user.id, self.fish_name))
        else:
            await db.execute("INSERT INTO inventory (user_id, item_name, amount, is_locked) VALUES (?, ?, 1, ?)", (self.user.id, self.fish_name, is_locked))
        await db.commit()

    @discord.ui.button(label="가방에 넣기", style=discord.ButtonStyle.primary, emoji="🎒")
    async def put_in_bag(self, interaction: discord.Interaction, button: Button):
        if interaction.user != self.user: return
        await self._add_to_inventory()
        await interaction.response.edit_message(content=f"✅ **{self.fish_name}**(을)를 가방에 넣었습니다.", embed=None, view=None)
        self.stop()

    @discord.ui.button(label="즉시 판매", style=discord.ButtonStyle.success, emoji="💰")
    async def sell_now(self, interaction: discord.Interaction, button: Button):
        if interaction.user != self.user: return
        price = FISH_DATA.get(self.fish_name, {}).get("price", 100)
        
        # [신규] 물고기 시세(마켓) 적용
        async with db.conn.execute("SELECT current_price FROM market_prices WHERE item_name=?", (self.fish_name,)) as cursor:
            res = await cursor.fetchone()
        if res: price = res[0]

        await db.execute("UPDATE user_data SET coins = coins + ? WHERE user_id = ?", (price, self.user.id))
        await db.commit()
        await interaction.response.edit_message(content=f"💰 **{self.fish_name}**(을)를 {price} C에 판매했습니다.", embed=None, view=None)
        self.stop()

    @discord.ui.button(label="방생하기", style=discord.ButtonStyle.secondary, emoji="🌊")
    async def release_fish(self, interaction: discord.Interaction, button: Button):
        if interaction.user != self.user: return
        await interaction.response.edit_message(content=f"🌊 **{self.fish_name}**(을)를 다시 바다로 돌려보냈습니다. 공덕이 쌓입니다...", embed=None, view=None)
        self.stop()

class FishingView(View):
    def __init__(self, user, target_fish, rod_tier, bot):
        super().__init__(timeout=60)
        self.user = user
        self.target_fish = target_fish
        self.rod_tier = rod_tier
        self.bot = bot
        self.is_bite = False
        self.resolved = False
        self.start_time = 0.0
        self.message = None

    @discord.ui.button(label="대기 중...", style=discord.ButtonStyle.secondary, emoji="🎣")
    async def hook(self, interaction: discord.Interaction, button: Button):
        if interaction.user != self.user: return
        if not self.is_bite:
            self.resolved = True
            self.stop()
            return await interaction.response.edit_message(content="❌ 너무 일찍 당겼습니다! 물고기가 놀라 도망갔습니다.", embed=None, view=None)
        
        self.resolved = True
        self.stop()
        
        elapsed = datetime.datetime.now(kst).timestamp() - self.start_time
        if elapsed > 1.5:
            return await interaction.response.edit_message(content="💨 물고기가 미끼만 먹고 도망갔습니다! (타이밍이 늦었습니다)", embed=None, view=None)
        
        # 성공! 등급 확인
        fish_data = FISH_DATA.get(self.target_fish, {"grade": "일반"})
        grade = fish_data.get("grade", "일반")
        
        if grade in ["대형 포식자", "레전드", "신화", "태고", "환상", "미스터리"]:
            # 힘겨루기 시작
            from fishing_core.views import TensionFishingView
            tension_view = TensionFishingView(self.user, self.target_fish, self.rod_tier, grade, self, elapsed)
            await interaction.response.edit_message(embed=tension_view.get_embed(), view=tension_view)
        else:
            await self.on_bite_success(interaction, elapsed, grade)

    async def on_bite_success(self, interaction, elapsed, grade):
        try:
            embed = discord.Embed(title="🎣 낚시 성공!", color=0x00ff00)
            embed.add_field(name="어종", value=f"**{self.target_fish}**", inline=True)
            embed.add_field(name="등급", value=format_grade_label(grade), inline=True)
            
            # [신규] 크라켄 약탈 로직
            if self.target_fish == "심해의 파멸, 크라켄 🦑":
                async with db.conn.execute("SELECT user_id, coins FROM user_data WHERE user_id != ? AND coins > 1000 AND peace_mode=0 ORDER BY RANDOM() LIMIT 1", (self.user.id,)) as cursor:
                    target = await cursor.fetchone()
                if target:
                    stolen_amount = int(target[1] * 0.1)
                    await db.execute("UPDATE user_data SET coins = coins - ? WHERE user_id = ?", (target[0], stolen_amount))
                    await db.execute("UPDATE user_data SET coins = coins + ? WHERE user_id = ?", (self.user.id, stolen_amount))
                    await db.commit()
                    embed.add_field(name="🦑 크라켄의 촉수 발동!", value=f"심연에서 뻗어 나온 거대한 촉수가 누군가의 금고를 부수고 `{stolen_amount:,} C`를 훔쳐 당신에게 가져왔습니다!!", inline=False)

            action_view = FishActionView(self.user, self.target_fish)
            
            # 더블 캐치 처리
            double_msg = ""
            if getattr(self, "double_catch", False):
                await action_view._add_to_inventory()
                double_msg = " (👯 **더블 캐치!** 요리 효과로 한 마리 더 낚았습니다!)"
            
            await interaction.response.edit_message(content=f"🎊 앗, 낚았습니다!{double_msg} 이 물고기를 어떻게 할까요?", embed=embed, view=action_view)
            action_view.message = await interaction.original_response()

            # [신규] 초보자 튜토리얼 트리거
            async with db.conn.execute("SELECT COUNT(*) FROM fish_dex WHERE user_id=?", (self.user.id,)) as cursor:
                dex_count = (await cursor.fetchone())[0]
            
            # [업적] 첫 낚시 성공 및 등급별 업적
            await AchievementService.check_achievement(self.user.id, "FIRST_CATCH")
            if grade in ["레전드", "신화", "태고", "환상", "미스터리"]:
                await AchievementService.check_achievement(self.user.id, "LEGENDARY_FISHER")

            if dex_count == 1:
                tutorial_embed = discord.Embed(title="🌱 첫 낚시 성공을 축하합니다!", color=0x2ecc71)
                tutorial_embed.description = (
                    "방금 낚은 물고기는 당신의 첫 기록이 되었습니다!\n\n"
                    "💡 **앞으로 무엇을 하면 좋을까요?**\n"
                    "1. `/판매` 명령어로 물고기를 팔아 코인을 모으세요.\n"
                    "2. `/강화` 명령어로 낚싯대를 업그레이드하세요.\n"
                    "3. `/도움말`을 입력하면 더 많은 명령어를 볼 수 있습니다.\n"
                    "4. `/가이드`를 통해 성장 로드맵을 확인하세요!"
                )
                await interaction.followup.send(embed=tutorial_embed, ephemeral=True)

            # [재앙 알림]
            if grade in ["태고", "환상", "미스터리", "신화"]:
                await db.log_action(self.user.id, "CATCH_RARE_FISH", f"Fish: {self.target_fish}, Grade: {grade}")
                alert_embed = None
                if self.target_fish == "메갈로돈 🦈":
                    alert_embed = discord.Embed(title="🦖 [경고] 바다가 공포에 질려 침묵합니다...", description=f"**{self.user.mention}**님이 역사상 가장 거대한 포식자 **{self.target_fish}**를 현세에 끌어올렸습니다!!!", color=0x8b4513)
                elif self.target_fish == "심해의 파멸, 크라켄 🦑":
                    alert_embed = discord.Embed(title="🦑 [재앙 경고] 거대한 촉수들이 해수면을 산산조각 냅니다!!!", description=f"**{self.user.mention}**님이 수백 척의 배를 가라앉힌 북유럽의 악몽, **{self.target_fish}**를 심연에서 건져 올렸습니다!!!", color=0xff0000)
                
                if alert_embed:
                    await interaction.channel.send(content="@here", embed=alert_embed)

        except Exception:
            import traceback
            await interaction.followup.send(f"❌ 오류 발생: {traceback.format_exc()[:1000]}", ephemeral=True)

class TensionFishingView(View):
    def __init__(self, user, target_fish, rod_tier, grade, parent_view, elapsed):
        super().__init__(timeout=40)
        self.user = user
        self.target_fish = target_fish
        self.rod_tier = rod_tier
        self.grade = grade
        self.parent_view = parent_view
        self.elapsed = elapsed
        self.tension = 50
        self.turn = 1
        self.max_turns = 3 if grade == "대형 포식자" else (4 if grade == "레전드" else 5)

    def get_embed(self):
        embed = discord.Embed(title="🎣 거대 괴수와 힘겨루기!", color=0x3498db)
        embed.description = f"물고기가 강하게 저항합니다! 텐션을 **20% ~ 80%** 사이로 유지하세요!\n(남은 턴: {self.max_turns - self.turn + 1})"
        bar_count = 10
        filled_segments = int(self.tension / 10)
        bar_str = ""
        for i in range(1, bar_count + 1):
            if i <= filled_segments:
                if i <= 2 or i >= 9: bar_str += "🟥"
                elif i in {3, 8}: bar_str += "🟨"
                else: bar_str += "🟩"
            else: bar_str += "⬛"
        status_emoji = "🟢" if 20 <= self.tension <= 80 else "🔴"
        status_text = "안전" if 20 <= self.tension <= 80 else "위험!"
        embed.add_field(name=f"현재 텐션: {self.tension}%", value=f"{bar_str} ({status_emoji} {status_text})", inline=False)
        return embed

    async def execute_turn(self, interaction, action):
        if action == "당기기": self.tension += random.randint(15, 25)
        else: self.tension -= random.randint(15, 25)
        self.tension += random.choice([-15, -10, 10, 15])
        if self.tension >= 100 or self.tension <= 0:
            self.stop()
            msg = "💥 줄이 끊어졌습니다!" if self.tension >= 100 else "💨 바늘이 빠졌습니다!"
            
            # 바다 빠짐 연출 강화
            if self.grade in ["레전드", "신화", "태고", "환상", "미스터리", "대형 포식자"] and random.random() < 0.2:
                duration_minutes = 30
                end_time = (datetime.datetime.now(kst) + datetime.timedelta(minutes=duration_minutes)).isoformat()
                await db.execute("INSERT INTO active_buffs (user_id, buff_type, end_time) VALUES (?, 'wet_clothes', ?) ON CONFLICT(user_id, buff_type) DO UPDATE SET end_time = ?", (self.user.id, end_time, end_time))
                await db.commit()
                
                fall_embed = discord.Embed(title="🌊 으아아아! 바다에 빠졌습니다!!", color=0xe74c3c)
                fall_embed.description = f"물고기의 엄청난 힘에 이기지 못하고 배 밖으로 튕겨 나갔습니다!\n\n**[효과]**\n- 💨 **젖은 옷 (디버프)**: {duration_minutes}분 동안 낚시 대기 시간이 증가합니다.\n- 💔 **체력 감소**: 충격으로 인해 체력이 `20` 감소합니다."
                fall_embed.set_image(url="https://images.unsplash.com/photo-1519046904884-53103b34b206?w=800") # 거친 파도 이미지
                
                await db.execute("UPDATE user_data SET stamina = MAX(0, stamina - 20) WHERE user_id=?", (self.user.id,))
                await db.commit()
                
                return await interaction.response.edit_message(content=None, embed=fall_embed, view=None)
            
            await db.commit()
            return await interaction.response.edit_message(content=msg, embed=None, view=None)
        if self.turn >= self.max_turns:
            if not (20 <= self.tension <= 80):
                self.stop()
                return await interaction.response.edit_message(content="💨 힘겨루기 실패!", embed=None, view=None)
            self.stop()
            await self.parent_view.on_bite_success(interaction, self.elapsed, self.grade)
        else:
            self.turn += 1
            await interaction.response.edit_message(embed=self.get_embed(), view=self)

    @discord.ui.button(label="당기기", style=discord.ButtonStyle.danger, emoji="🔥")
    async def btn_pull(self, interaction: discord.Interaction, button: Button):
        if interaction.user != self.user: return
        await self.execute_turn(interaction, "당기기")

    @discord.ui.button(label="풀기", style=discord.ButtonStyle.primary, emoji="💧")
    async def btn_release(self, interaction: discord.Interaction, button: Button):
        if interaction.user != self.user: return
        await self.execute_turn(interaction, "풀기")

class BattleView(View):
    def __init__(self, user, my_fish, npc_fish):
        super().__init__(timeout=60)
        self.user = user
        self.my_fish = my_fish
        self.npc_fish = npc_fish
        self.my_max_hp = self.my_hp = FISH_DATA[my_fish]["power"] * 10
        self.my_atk = FISH_DATA[my_fish]["power"]
        self.my_ap = 1
        self.my_elem = FISH_DATA[my_fish]["element"]
        self.is_my_defending = False
        self.npc_max_hp = self.npc_hp = FISH_DATA[npc_fish]["power"] * 10
        self.npc_atk = FISH_DATA[npc_fish]["power"]
        self.npc_ap = 1
        self.npc_elem = FISH_DATA[npc_fish]["element"]
        self.is_npc_defending = False
        self.turn = 1
        self.battle_log = "전투가 시작되었습니다!\n"

    def generate_embed(self):
        embed = discord.Embed(title=f"⚔️ 수산 배틀 (Turn {self.turn})", color=0xff0000)
        def hp_bar(hp, mhp): return "🟩" * max(0, int((hp/mhp)*5)) + "⬛" * (5-max(0, int((hp/mhp)*5)))
        embed.add_field(name=f"🔵 {self.user.name}", value=f"**{self.my_fish}**\nHP: {self.my_hp}/{self.my_max_hp} {hp_bar(self.my_hp, self.my_max_hp)}", inline=True)
        embed.add_field(name="VS", value="⚡", inline=True)
        embed.add_field(name="🔴 야생", value=f"**{self.npc_fish}**\nHP: {self.npc_hp}/{self.npc_max_hp} {hp_bar(self.npc_hp, self.npc_max_hp)}", inline=True)
        embed.add_field(name="📜 로그", value=self.battle_log.strip().split("\n")[-1], inline=False)
        return embed

    async def execute_turn(self, interaction, action):
        if action == "attack":
            res = BattleService.calculate_damage(self.my_fish, self.npc_fish, is_defending=self.is_npc_defending)
            dmg = res["damage"]
            self.npc_hp -= dmg
            self.battle_log += f"🔵 {self.my_fish} 공격! {dmg} 피해! ({res['description']})\n"
            self.is_npc_defending = False # 리셋
        else:
            self.is_my_defending = True
            self.battle_log += f"🔵 {self.my_fish} 방어 자세!\n"
            
        if self.npc_hp <= 0: return await self.end_battle(interaction, True)
        
        # NPC의 반격 (단순화)
        npc_res = BattleService.calculate_damage(self.npc_fish, self.my_fish, is_defending=self.is_my_defending)
        npc_dmg = npc_res["damage"]
        self.my_hp -= npc_dmg
        self.battle_log += f"🔴 {self.npc_fish} 반격! {npc_dmg} 피해! ({npc_res['description']})\n"
        self.is_my_defending = False # 리셋
        
        if self.my_hp <= 0: return await self.end_battle(interaction, False)
        
        self.turn += 1
        await interaction.response.edit_message(embed=self.generate_embed(), view=self)

    async def end_battle(self, interaction, is_win):
        self.stop()
        msg = "🎉 승리!" if is_win else "💀 패배..."
        await interaction.response.edit_message(content=msg, embed=None, view=None)

    @discord.ui.button(label="공격", style=discord.ButtonStyle.danger)
    async def btn_attack(self, interaction: discord.Interaction, button: Button):
        if interaction.user != self.user: return
        await self.execute_turn(interaction, "attack")

    @discord.ui.button(label="방어", style=discord.ButtonStyle.primary)
    async def btn_defend(self, interaction: discord.Interaction, button: Button):
        if interaction.user != self.user: return
        await self.execute_turn(interaction, "defend")

class PvPBattleView(View):
    def __init__(self, p1, p2, p1_deck, p2_deck):
        super().__init__(timeout=120)
        self.p1, self.p2 = p1, p2
        self.p1_deck, self.p2_deck = p1_deck, p2_deck
        self.p1_idx, self.p2_idx = 0, 0
        self.turn_count = 1
        self.current_turn_user = p1
        self.battle_log = "전투 시작!\n"
        self._init_fish(1)
        self._init_fish(2)

    def _init_fish(self, p_num):
        if p_num == 1:
            name, pwr = self.p1_deck[self.p1_idx]
            self.p1_fish = name
            self.p1_hp = self.p1_max_hp = pwr * 10
            self.p1_atk = pwr
            self.p1_elem = FISH_DATA.get(name, {}).get("element", "무")
        else:
            name, pwr = self.p2_deck[self.p2_idx]
            self.p2_fish = name
            self.p2_hp = self.p2_max_hp = pwr * 10
            self.p2_atk = pwr
            self.p2_elem = FISH_DATA.get(name, {}).get("element", "무")

    def generate_embed(self):
        embed = discord.Embed(title=f"⚔️ 3v3 PvP (Turn {self.turn_count})", color=0xff0000)
        embed.description = f"현재 턴: {self.current_turn_user.mention}"
        embed.add_field(name=f"🔵 {self.p1.name}", value=f"**{self.p1_fish}**\nHP: {self.p1_hp}/{self.p1_max_hp}", inline=True)
        embed.add_field(name="VS", value="⚡", inline=True)
        embed.add_field(name=f"🔴 {self.p2.name}", value=f"**{self.p2_fish}**\nHP: {self.p2_hp}/{self.p2_max_hp}", inline=True)
        return embed

    async def execute_turn(self, interaction, action):
        if interaction.user != self.current_turn_user: return
        is_p1 = (interaction.user == self.p1)
        
        attacker_fish = self.p1_fish if is_p1 else self.p2_fish
        defender_fish = self.p2_fish if is_p1 else self.p1_fish
        
        if action == "attack":
            res = BattleService.calculate_damage(attacker_fish, defender_fish)
            dmg = res["damage"]
            if is_p1: self.p2_hp -= dmg
            else: self.p1_hp -= dmg
            self.battle_log = f"{'🔵' if is_p1 else '🔴'} {attacker_fish}의 공격! {dmg} 피해! ({res['description']})"
            
        if self.p1_hp <= 0:
            self.p1_idx += 1
            if self.p1_idx >= len(self.p1_deck): return await self.end_battle(interaction, self.p2, self.p1)
            self._init_fish(1)
            self.battle_log += f"\n🔵 {self.p1.name}님의 다음 물고기 {self.p1_fish} 출격!"
            
        if self.p2_hp <= 0:
            self.p2_idx += 1
            if self.p2_idx >= len(self.p2_deck): return await self.end_battle(interaction, self.p1, self.p2)
            self._init_fish(2)
            self.battle_log += f"\n🔴 {self.p2.name}님의 다음 물고기 {self.p2_fish} 출격!"
            
        self.current_turn_user = self.p2 if is_p1 else self.p1
        self.turn_count += 1
        
        embed = self.generate_embed()
        embed.add_field(name="📜 로그", value=self.battle_log, inline=False)
        await interaction.response.edit_message(embed=embed, view=self)

    async def end_battle(self, interaction, winner, loser):
        self.stop()
        
        # 코인 약탈 로직 (패배자 코인의 5~10%)
        async with db.conn.execute("SELECT coins FROM user_data WHERE user_id=?", (loser.id,)) as cursor:
            res = await cursor.fetchone()
        loser_coins = res[0] if res else 0
        
        steal_amount = int(loser_coins * random.uniform(0.05, 0.10))
        if getattr(self, "is_offline_target", False):
            steal_amount = int(steal_amount * 0.5) # 오프라인 시 50%만 약탈
            
        if steal_amount > 0:
            await db.execute("UPDATE user_data SET coins = coins - ? WHERE user_id=?", (steal_amount, loser.id))
            await db.execute("UPDATE user_data SET coins = coins + ? WHERE user_id=?", (steal_amount, winner.id))
            await db.log_action(winner.id, "PVP_WIN", f"Winner: {winner.name}, Loser: {loser.name}, Stole: {steal_amount} C")
            await db.log_action(loser.id, "PVP_LOSS", f"Winner: {winner.name}, Loser: {loser.name}, Lost: {steal_amount} C")
            
            # [업적] 수산대전 첫 승리
            await AchievementService.check_achievement(winner.id, "BATTLE_WARRIOR")
            
            await db.commit()
            
            msg = f"🏆 {winner.mention} 승리! ({loser.name}님으로부터 `{steal_amount:,} C`를 약탈했습니다!)"
        else:
            msg = f"🏆 {winner.mention} 승리!"
            
        await interaction.response.edit_message(content=msg, embed=None, view=None)

    @discord.ui.button(label="공격", style=discord.ButtonStyle.danger)
    async def btn_attack(self, interaction: discord.Interaction, button: Button):
        await self.execute_turn(interaction, "attack")

class MarketPaginationView(View):
    def __init__(self, items, per_page=10):
        super().__init__(timeout=120)
        self.all_items = list(items.items())
        self.per_page = per_page
        self.current_page = 0

    def make_embed(self):
        start = self.current_page * self.per_page
        items = self.all_items[start:start+self.per_page]
        embed = discord.Embed(title="📊 수산시장 시세", color=0xf1c40f)
        for f, p in items: embed.add_field(name=f, value=f"{p} C", inline=True)
        return embed

    @discord.ui.button(label="이전")
    async def prev(self, interaction, btn):
        if self.current_page > 0:
            self.current_page -= 1
            await interaction.response.edit_message(embed=self.make_embed())

    @discord.ui.button(label="다음")
    async def next(self, interaction, btn):
        if (self.current_page+1)*self.per_page < len(self.all_items):
            self.current_page += 1
            await interaction.response.edit_message(embed=self.make_embed())

class DragonKingBlessingView(View):
    def __init__(self):
        super().__init__(timeout=300)
    @discord.ui.button(label="고개 조아리기", style=discord.ButtonStyle.success, emoji="🙇")
    async def bow(self, interaction, btn):
        coin = random.randint(1000, 5000)
        await db.execute("UPDATE user_data SET coins = coins + ? WHERE user_id = ?", (coin, interaction.user.id))
        await db.commit()
        await interaction.response.send_message(f"👑 축복을 받았습니다! (+{coin} C)", ephemeral=True)

class QuestDeliveryView(View):
    def __init__(self, user, item, amount, reward):
        super().__init__(timeout=60)
        self.user, self.item, self.amount, self.reward = user, item, amount, reward
    @discord.ui.button(label="📦 납품하기", style=discord.ButtonStyle.success)
    async def deliver(self, interaction, btn):
        if interaction.user != self.user: return
        await db.execute("UPDATE user_data SET coins = coins + ? WHERE user_id = ?", (self.reward, self.user.id))
        await db.log_action(self.user.id, "QUEST_COMPLETE", f"Item: {self.item}, Amount: {self.amount}, Reward: {self.reward} C")
        await db.commit()
        await interaction.response.edit_message(content=f"✅ 납품 완료! (+{self.reward:,} C)", view=None)

class InventoryView(View):
    def __init__(self, user, target_user, items, stats):
        super().__init__(timeout=120)
        self.user, self.target_user, self.all_items, self.stats = user, target_user, items, stats
        self.current_page = 0
        self.per_page = 15

    def make_embed(self):
        coins, rod, rating, boat, stam, max_stam, title = self.stats
        embed = discord.Embed(title=f"🎒 {self.target_user.name}의 가방", color=0x3498db)
        embed.add_field(name="💰 코인", value=f"{coins:,} C")
        start = self.current_page * self.per_page
        items = self.all_items[start:start+self.per_page]
        if items: embed.description = "\n".join([f"**{n}**: {a}개" for n, a, _ in items])
        else: embed.description = "가방이 텅 비었습니다."
        return embed

    @discord.ui.button(label="이전")
    async def prev(self, interaction, btn):
        if self.current_page > 0:
            self.current_page -= 1
            await interaction.edit_original_response(embed=self.make_embed())

    @discord.ui.button(label="다음")
    async def next(self, interaction, btn):
        if (self.current_page+1)*self.per_page < len(self.all_items):
            self.current_page += 1
            await interaction.edit_original_response(embed=self.make_embed())
