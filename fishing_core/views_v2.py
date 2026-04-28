import datetime
import random

import discord
from discord.ui import Button, View

from fishing_core.database import db
from fishing_core.logger import logger
from fishing_core.services.achievement_service import AchievementService
from fishing_core.services.battle_service import BattleService
from fishing_core.shared import (
    FISH_DATA,
    format_grade_label,
    kst,
)
from fishing_core.utils import EmbedFactory, create_progress_bar


class FishActionView(View):
    def __init__(self, user, fish_name):
        super().__init__(timeout=60)
        self.user = user
        self.fish_name = fish_name
        self.message = None

    async def _add_to_inventory(self, is_locked=0):
        async with db.transaction():
            await db.modify_inventory(self.user.id, self.fish_name, 1)
            if is_locked:
                await db.execute("UPDATE inventory SET is_locked = 1 WHERE user_id=? AND item_name=?", (self.user.id, self.fish_name))

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
        
        async with db.conn.execute("SELECT current_price FROM market_prices WHERE item_name=?", (self.fish_name,)) as cursor:
            res = await cursor.fetchone()
        if res: price = res[0]

        async with db.transaction():
            await db.execute("UPDATE user_data SET coins = coins + ? WHERE user_id = ?", (price, self.user.id))
        
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
            embed = EmbedFactory.build(title="💨 너무 일찍 당겼습니다!", description=f"낚싯줄을 던지자마자 당겨버렸습니다.\n잠시 입질을 기다리던 **{self.target_fish}**(이)가 놀라 도망갔습니다.", type="default")
            return await interaction.response.edit_message(content=None, embed=embed, view=None)
        
        self.resolved = True
        self.stop()
        
        elapsed = datetime.datetime.now(kst).timestamp() - self.start_time
        fish_data = FISH_DATA.get(self.target_fish, {"grade": "일반"})
        grade = fish_data.get("grade", "일반")
        
        limit_map = {
            "일반": 3.0, "희귀": 3.0, "초희귀": 2.5, "에픽": 2.2, "소형 포식자": 2.5,
            "대형 포식자": 2.0, "레전드": 1.8, "신화": 1.8, "태고": 1.5, "환상": 1.5
        }
        time_limit = limit_map.get(grade, 2.0)
        
        if elapsed > time_limit:
            embed = EmbedFactory.build(title="💨 타이밍이 늦었습니다!", description=f"찰나의 순간, **{self.target_fish}**(이)가 미끼만 쏙 빼먹고 깊은 바다로 도망갔습니다.\n(반응 속도: `{elapsed:.2f}초` / 제한: `{time_limit}초`)", type="default")
            return await interaction.response.edit_message(content=None, embed=embed, view=None)
        
        if grade in ["대형 포식자", "레전드", "신화", "태고", "환상", "미스터리"]:
            # 같은 파일 내 클래스이므로 직접 참조
            tension_view = TensionFishingView(self.user, self.target_fish, self.rod_tier, grade, self, elapsed)
            await interaction.response.edit_message(embed=tension_view.get_embed(), view=tension_view)
        else:
            await self.on_bite_success(interaction, elapsed, grade)

    async def on_bite_success(self, interaction: discord.Interaction, elapsed: float, grade: str):
        try:
            from fishing_core.shared import MARKET_PRICES
            price = MARKET_PRICES.get(self.target_fish, FISH_DATA.get(self.target_fish, {}).get("price", 100))

            # [Phase 3] 프리미엄 색상 및 전역 공지
            embed_type = "success"
            if grade in ["레전드", "신화", "태고", "환상", "미스터리"]:
                embed_type = "legend" if grade == "레전드" else "mythic"
                from fishing_core.utils import broadcast_legendary_catch
                self.bot.loop.create_task(broadcast_legendary_catch(self.bot, self.user, self.target_fish, grade))

            embed = EmbedFactory.build(title="✨ 낚시 성공! 월척입니다!", type=embed_type)
            embed.set_author(name=f"{self.user.name}님의 포획 기록", icon_url=self.user.display_avatar.url)
            embed.description = f"**{self.target_fish}** (을)를 성공적으로 낚아올렸습니다!\n입질 반응 속도: `{elapsed:.2f}초`"
            embed.add_field(name="🧬 어종 등급", value=format_grade_label(grade), inline=True)
            embed.add_field(name="💰 현재 시세", value=f"`{price:,} C`", inline=True)

            # 트랜잭션 시작
            stolen_amount = 0
            async with db.transaction():
                if self.target_fish == "심해의 파멸, 크라켄 🦑":
                    async with db.conn.execute("SELECT user_id, coins FROM user_data WHERE user_id != ? AND coins > 1000 ORDER BY RANDOM() LIMIT 1", (self.user.id,)) as cursor:
                        target = await cursor.fetchone()
                    if target:
                        stolen_amount = int(target[1] * 0.1)
                        await db.execute("UPDATE user_data SET coins = coins - ? WHERE user_id = ?", (stolen_amount, target[0]))
                        await db.execute("UPDATE user_data SET coins = coins + ? WHERE user_id = ?", (stolen_amount, self.user.id))

                double_msg = ""
                if getattr(self, "double_catch", False):
                    await db.modify_inventory(self.user.id, self.target_fish, 1)
                    double_msg = " (👯 **더블 캐치!**)"

                await AchievementService.check_achievement(self.user.id, "FIRST_CATCH")
                if grade in ["레전드", "신화", "태고", "환상", "미스터리"]:
                    await AchievementService.check_achievement(self.user.id, "LEGENDARY_FISHER")

            if stolen_amount > 0:
                embed.add_field(name="🦑 크라켄의 촉수!", value=f"`{stolen_amount:,} C`를 훔쳐왔습니다!", inline=False)

            # [Phase 1] 자동 설정 체크
            user_data = await db.get_full_user_data(self.user.id)
            auto_bag = user_data.get("auto_bag", False)
            auto_sell = user_data.get("auto_sell", False)

            if auto_bag:
                await db.modify_inventory(self.user.id, self.target_fish, 1)
                await interaction.response.edit_message(content=f"🎊 낚았습니다!{double_msg}\n✅ **자동 가방 넣기** 설정으로 가방에 보관되었습니다.", embed=embed, view=None)
            elif auto_sell:
                # 시세 조회
                async with db.conn.execute("SELECT current_price FROM market_prices WHERE item_name=?", (self.target_fish,)) as cursor:
                    res = await cursor.fetchone()
                sell_price = res[0] if res else FISH_DATA.get(self.target_fish, {}).get("price", 100)
                
                async with db.transaction():
                    await db.execute("UPDATE user_data SET coins = coins + ? WHERE user_id = ?", (sell_price, self.user.id))
                
                await interaction.response.edit_message(content=f"🎊 낚았습니다!{double_msg}\n💰 **자동 즉시 판매** 설정으로 `{sell_price:,} C`에 판매되었습니다.", embed=embed, view=None)
            else:
                action_view = FishActionView(self.user, self.target_fish)
                await interaction.response.edit_message(content=f"🎊 낚았습니다!{double_msg}", embed=embed, view=action_view)
                action_view.message = await interaction.original_response()

        except Exception as e:
            logger.error(f"on_bite_success 오류: {e}")


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
        embed = EmbedFactory.build(title="🎣 거대 괴수와 힘겨루기!", type="info")
        embed.description = f"텐션을 **20% ~ 80%** 사이로 유지하세요!\n(남은 턴: {self.max_turns - self.turn + 1})"
        bar_count = 10
        filled = int(self.tension / 10)
        bar_str = "🟩" * filled + "⬛" * (bar_count - filled)
        embed.add_field(name=f"현재 텐션: {self.tension}%", value=bar_str, inline=False)
        return embed

    async def execute_turn(self, interaction, action):
        if action == "당기기": self.tension += random.randint(15, 25)
        else: self.tension -= random.randint(15, 25)
        self.tension += random.choice([-15, -10, 10, 15])
        
        if self.tension >= 100 or self.tension <= 0:
            self.stop()
            async with db.transaction():
                if self.grade in ["레전드", "신화", "태고", "환상", "미스터리", "대형 포식자"] and random.random() < 0.2:
                    end_time = (datetime.datetime.now(kst) + datetime.timedelta(minutes=30)).isoformat()
                    await db.execute("INSERT INTO active_buffs (user_id, buff_type, end_time) VALUES (?, 'wet_clothes', ?) ON CONFLICT(user_id, buff_type) DO UPDATE SET end_time = ?", (self.user.id, end_time, end_time))
                    await db.execute("UPDATE user_data SET stamina = MAX(0, stamina - 20) WHERE user_id=?", (self.user.id,))
                    return await interaction.response.edit_message(content="🌊 바다에 빠졌습니다!!", embed=None, view=None)
            return await interaction.response.edit_message(content="❌ 도망갔습니다.", embed=None, view=None)

        if self.turn >= self.max_turns:
            self.stop()
            if 20 <= self.tension <= 80: await self.parent_view.on_bite_success(interaction, self.elapsed, self.grade)
            else: await interaction.response.edit_message(content="❌ 힘싸움 패배!", embed=None, view=None)
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
        super().__init__(timeout=120)
        self.user = user
        self.my_fish = my_fish
        self.npc_fish = npc_fish
        self.turn = 1
        self.my_ap = 1
        self.npc_ap = 1
        p1_pwr = FISH_DATA.get(my_fish, {}).get('power', 10)
        p2_pwr = FISH_DATA.get(npc_fish, {}).get('power', 10)
        self.my_hp = p1_pwr * 12
        self.npc_hp = p2_pwr * 12
        self.my_pwr = p1_pwr
        self.npc_pwr = p2_pwr

    def generate_embed(self):
        embed = EmbedFactory.build(title=f'⚔️ 배틀 (Turn {self.turn})', type='error')
        embed.add_field(name=f'🔵 {self.user.name}', value=f'HP: {self.my_hp}', inline=True)
        embed.add_field(name='🔴 적', value=f'HP: {self.npc_hp}', inline=True)
        
        # 기본 배틀 배경 이미지
        file = discord.File("assets/battle/battle_start.png", filename="battle.png")
        embed.set_image(url="attachment://battle.png")
        return embed, file

    @discord.ui.button(label='공격', style=discord.ButtonStyle.danger)
    async def btn_confirm(self, interaction, button):
        if interaction.user != self.user: return
        self.npc_hp -= self.my_pwr
        self.my_hp -= self.npc_pwr
        if self.npc_hp <= 0:
            async with db.transaction():
                await db.execute('UPDATE user_data SET coins = coins + 100 WHERE user_id = ?', (self.user.id,))
            return await interaction.response.edit_message(content="🏆 승리!", embed=None, view=None, attachments=[])
        if self.my_hp <= 0: 
            return await interaction.response.edit_message(content="💀 패배...", embed=None, view=None, attachments=[])
        self.turn += 1
        embed, file = self.generate_embed()
        await interaction.response.edit_message(embed=embed, attachments=[file])


class PvPBattleView(View):
    def __init__(self, p1, p2, p1_deck, p2_deck):
        super().__init__(timeout=300)
        self.p1, self.p2 = p1, p2
        self.p1_deck, self.p2_deck = p1_deck, p2_deck
        self.p1_idx, self.p2_idx = 0, 0
        self.turn_count = 1
        self.ap_gain = 1
        self.p1_ap = self.p2_ap = 1
        self.p1_alloc = {'atk': 0, 'blk': 0}
        self.p2_alloc = {'atk': 0, 'blk': 0}
        self.p1_ready = self.p2_ready = False
        self.battle_log = '⚔️ 전략적으로 포인트를 배분하세요!'
        self.is_offline_target = False
        self._init_fish(1)
        self._init_fish(2)

    def _init_fish(self, p_num):
        if p_num == 1:
            name, pwr = self.p1_deck[self.p1_idx]
            self.p1_fish, self.p1_pwr = name, pwr
            self.p1_hp = self.p1_max_hp = pwr * 12
        else:
            name, pwr = self.p2_deck[self.p2_idx]
            self.p2_fish, self.p2_pwr = name, pwr
            self.p2_hp = self.p2_max_hp = pwr * 12

    def generate_embed(self, reveal=False):
        embed = EmbedFactory.build(title=f'⚔️ 전략 수산대전 (Turn {self.turn_count})', type='warning')
        def hp_bar(hp, mhp): return create_progress_bar(hp, mhp, length=10)
        def ap_bar(ap): return '🟦' * ap + '⬜' * (8 - ap)
        
        embed.add_field(name=f'🔵 {self.p1.name}', value=f'**{self.p1_fish}**\nHP: {hp_bar(self.p1_hp, self.p1_max_hp)} `{self.p1_hp:,}`\nAP: {ap_bar(self.p1_ap)} `({self.p1_ap})`', inline=False)
        embed.add_field(name='━━━━━ VS ━━━━━', value=f'✨ 다음 턴 AP 수급: `+{self.ap_gain + 1}`', inline=False)
        embed.add_field(name=f'🔴 {self.p2.name}', value=f'**{self.p2_fish}**\nHP: {hp_bar(self.p2_hp, self.p2_max_hp)} `{self.p2_hp:,}`\nAP: {ap_bar(self.p2_ap)} `({self.p2_ap})`', inline=False)
        
        if not reveal:
            p1_s = '✅ 완료' if self.p1_ready else '🤔 고민 중'
            p2_s = '✅ 완료' if self.p2_ready else '🤔 고민 중'
            embed.add_field(name='🛡️ 전략 준비', value=f'{self.p1.name}: {p1_s} | {self.p2.name}: {p2_s}', inline=False)
        
        embed.add_field(name='📜 로그', value=f'```md\n{self.battle_log}```', inline=False)
        
        # 배틀 이미지
        file = discord.File("assets/battle/battle_start.png", filename="battle.png")
        embed.set_image(url="attachment://battle.png")
        return embed, file

    async def _update_view(self, interaction):
        embed, file = self.generate_embed()
        await interaction.edit_original_response(embed=embed, attachments=[file], view=self)

    @discord.ui.select(placeholder="⚔️ 공격 포인트 선택", options=[discord.SelectOption(label=f"{i} pt", value=str(i)) for i in range(9)])
    async def select_atk(self, interaction, select):
        is_p1 = (interaction.user == self.p1)
        is_p2 = (interaction.user == self.p2)
        if not is_p1 and not is_p2: return
        
        ready = self.p1_ready if is_p1 else self.p2_ready
        if ready: return await interaction.response.send_message('❌ 이미 완료했습니다!', ephemeral=True)
        
        val = int(select.values[0])
        alloc = self.p1_alloc if is_p1 else self.p2_alloc
        ap = self.p1_ap if is_p1 else self.p2_ap
        
        if val + alloc['blk'] > ap: return await interaction.response.send_message('⚠️ AP 초과!', ephemeral=True)
        alloc['atk'] = val
        await self._show_status(interaction, is_p1)

    @discord.ui.select(placeholder="🛡️ 방어 포인트 선택", options=[discord.SelectOption(label=f"{i} pt", value=str(i)) for i in range(9)])
    async def select_blk(self, interaction, select):
        is_p1 = (interaction.user == self.p1)
        is_p2 = (interaction.user == self.p2)
        if not is_p1 and not is_p2: return
        
        ready = self.p1_ready if is_p1 else self.p2_ready
        if ready: return await interaction.response.send_message('❌ 이미 완료했습니다!', ephemeral=True)
        
        val = int(select.values[0])
        alloc = self.p1_alloc if is_p1 else self.p2_alloc
        ap = self.p1_ap if is_p1 else self.p2_ap
        
        if val + alloc['atk'] > ap: return await interaction.response.send_message('⚠️ AP 초과!', ephemeral=True)
        alloc['blk'] = val
        await self._show_status(interaction, is_p1)

    async def _show_status(self, interaction, is_p1):
        alloc = self.p1_alloc if is_p1 else self.p2_alloc
        ap = self.p1_ap if is_p1 else self.p2_ap
        
        mult = BattleService.MULTIPLIERS.get(alloc['atk'], 0.0)
        status_embed = EmbedFactory.build(title='🛡️ 내 전략 현황', type='info')
        status_embed.add_field(name='⚔️ 공격', value=f'`{alloc["atk"]} pt` (**{mult}x**)', inline=True)
        status_embed.add_field(name='🛡️ 방어', value=f'`{alloc["blk"]} pt`', inline=True)
        status_embed.add_field(name='💎 남은 AP', value=f'`{ap - sum(alloc.values())} pt`', inline=True)
        
        if not interaction.response.is_done(): 
            await interaction.response.send_message(embed=status_embed, ephemeral=True)
        else: 
            await interaction.followup.send(embed=status_embed, ephemeral=True)
        await self._update_view(interaction)

    @discord.ui.button(label='초기화', style=discord.ButtonStyle.secondary, emoji='🔄')
    async def btn_reset(self, interaction, button):
        if interaction.user == self.p1: self.p1_alloc = {'atk': 0, 'blk': 0}
        elif interaction.user == self.p2: self.p2_alloc = {'atk': 0, 'blk': 0}
        else: return
        await interaction.response.send_message('✅ 초기화 완료', ephemeral=True)
        await self._update_view(interaction)

    @discord.ui.button(label='✅ 결정', style=discord.ButtonStyle.success)
    async def btn_confirm(self, interaction, button):
        if interaction.user == self.p1: self.p1_ready = True
        elif interaction.user == self.p2: self.p2_ready = True
        else: return
        
        if self.p1_ready and self.p2_ready:
            await interaction.response.defer()
            await self.resolve_turn(interaction)
        else:
            await interaction.response.send_message('✅ 전략이 확정되었습니다. 상대방을 기다립니다...', ephemeral=True)
            await self._update_view(interaction)

    async def resolve_turn(self, interaction):
        p1_res = BattleService.calculate_ap_battle(self.p1_pwr, self.p1_alloc['atk'], self.p2_alloc['blk'])
        p2_res = BattleService.calculate_ap_battle(self.p2_pwr, self.p2_alloc['atk'], self.p1_alloc['blk'])
        
        d1, d2 = p1_res['damage'], p2_res['damage']
        
        # 오프라인 타겟 페널티
        if self.is_offline_target:
            d1 = int(d1 * 0.7)
            
        self.p2_hp -= d1
        self.p1_hp -= d2
        
        self.battle_log = f'[Turn {self.turn_count} 결과]\n🔵 {self.p1.name}: {d1:,} 피해!\n🔴 {self.p2.name}: {d2:,} 피해!'
        
        if self.p1_hp <= 0 or self.p2_hp <= 0:
            if self.p1_hp <= 0:
                self.p1_idx += 1
                if self.p1_idx >= len(self.p1_deck): 
                    return await self.end_battle(interaction, self.p2, self.p1)
                self._init_fish(1)
            if self.p2_hp <= 0:
                self.p2_idx += 1
                if self.p2_idx >= len(self.p2_deck): 
                    return await self.end_battle(interaction, self.p1, self.p2)
                self._init_fish(2)
        
        self.p1_ap = min(8, (self.p1_ap - sum(self.p1_alloc.values())) + self.ap_gain + 1)
        self.p2_ap = min(8, (self.p2_ap - sum(self.p2_alloc.values())) + self.ap_gain + 1)
        
        if self.ap_gain < 3: self.ap_gain += 1
        self.turn_count += 1
        self.p1_ready = self.p2_ready = False
        self.p1_alloc = {'atk': 0, 'blk': 0}
        self.p2_alloc = {'atk': 0, 'blk': 0}
        
        embed, file = self.generate_embed(reveal=True)
        await interaction.edit_original_response(embed=embed, attachments=[file], view=self)

    async def end_battle(self, interaction, winner, loser):
        self.stop()
        embed = EmbedFactory.build(title='⚔️ 전투 종료', type='warning')
        embed.description = f'👑 **{winner.name}** 승리!\n💀 **{loser.name}** 패배...'
        
        # 승리 보상 (약탈)
        async with db.transaction():
            async with db.conn.execute("SELECT coins FROM user_data WHERE user_id=?", (loser.id,)) as cursor:
                res = await cursor.fetchone()
            loser_coins = res[0] if res else 0
            steal_amt = int(loser_coins * (0.05 if self.is_offline_target else 0.15))
            
            await db.execute("UPDATE user_data SET coins = coins - ? WHERE user_id=?", (steal_amt, loser.id))
            await db.execute("UPDATE user_data SET coins = coins + ? WHERE user_id=?", (steal_amt, winner.id))
            
            # 레이팅 변동
            await db.execute("UPDATE user_data SET rating = rating + 25 WHERE user_id=?", (winner.id,))
            await db.execute("UPDATE user_data SET rating = MAX(0, rating - 15) WHERE user_id=?", (loser.id,))
            
        embed.add_field(name="💰 약탈 결과", value=f"**{winner.name}**님이 **{steal_amt:,} C**를 약탈했습니다!")
        
        file = discord.File("assets/battle/battle_victory.png", filename="victory.png")
        embed.set_image(url="attachment://victory.png")
        await interaction.edit_original_response(content=None, embed=embed, attachments=[file], view=None)


class InventoryView(View):
    def __init__(self, user, target, items, stats):
        super().__init__(timeout=60)
        self.user = user
        self.target = target
        self.original_items = items
        self.all_items = items
        self.stats = stats
        self.current_page = 0
        self.per_page = 10
        self.filter_grade = "전체"

    def make_embed(self):
        coins, rod_tier, rating, boat_str, stamina, max_stamina, title = self.stats
        display_name = f"{title} {self.target.name}" if title else self.target.name
        
        embed = EmbedFactory.build(title=f"🎒 {display_name}님의 가방", type="info")
        
        # 요약 정보 및 총 가치 계산
        from fishing_core.shared import MARKET_PRICES
        total_value = 0
        for name, amt, _ in self.original_items:
            price = MARKET_PRICES.get(name, FISH_DATA.get(name, {}).get("price", 0))
            total_value += price * amt

        hp_bar = create_progress_bar(stamina, max_stamina, length=8)
        embed.description = (
            f"🪙 **보유 코인:** `{coins:,} C` | 🏆 **랭킹 점수:** `{rating:,}`\n"
            f"🎣 **낚싯대:** `Lv.{rod_tier}` | 🛳️ **선박:** `{boat_str}`\n"
            f"⚡ **행동력:** {hp_bar} `{stamina}/{max_stamina}`\n"
            f"💰 **가방 총 가치:** 약 `{total_value:,} C`"
        )

        # 필터링 적용
        from fishing_core.shared import get_grade_order
        if self.filter_grade == "전체":
            filtered = self.original_items
        elif self.filter_grade == "일반":
            filtered = [x for x in self.original_items if FISH_DATA.get(x[0], {}).get("grade", "아이템") == "일반"]
        elif self.filter_grade == "희귀+":
            filtered = [x for x in self.original_items if get_grade_order(FISH_DATA.get(x[0], {}).get("grade", "")) >= 2]
        elif self.filter_grade == "아이템":
            filtered = [x for x in self.original_items if x[0] not in FISH_DATA]
        else:
            filtered = self.original_items
        
        self.all_items = filtered

        # 페이징
        start = self.current_page * self.per_page
        end = start + self.per_page
        items_slice = self.all_items[start:end]

        if not items_slice:
            embed.add_field(name="비어있음", value=f"보유한 **{self.filter_grade}** 아이템이 없습니다.", inline=False)
        else:
            item_list = []
            for name, amt, locked in items_slice:
                lock_icon = "🔒" if locked else ""
                grade = FISH_DATA.get(name, {}).get("grade", "아이템")
                gl = format_grade_label(grade)
                
                # 시세가 기본가보다 높으면 🔥 표시
                hot_icon = ""
                if name in FISH_DATA:
                    base_price = FISH_DATA[name].get("price", 0)
                    curr_price = MARKET_PRICES.get(name, base_price)
                    if curr_price > base_price * 1.2: # 20% 이상 비쌀 때
                        hot_icon = "🔥 "
                
                item_list.append(f"{lock_icon} {hot_icon}**{name}** `x{amt}` {gl}")
            
            embed.add_field(name=f"📦 보유 물품 ({self.filter_grade})", value="\n".join(item_list), inline=False)

        total_pages = max(1, (len(self.all_items) - 1) // self.per_page + 1)
        embed.set_footer(text=f"페이지 {self.current_page + 1} / {total_pages} | 총 {len(self.all_items)}종")
        return embed

    @discord.ui.button(label="전체", style=discord.ButtonStyle.primary)
    async def filter_all(self, interaction, btn):
        if interaction.user != self.user: return
        self.filter_grade = "전체"
        self.current_page = 0
        await interaction.response.edit_message(embed=self.make_embed(), view=self)

    @discord.ui.button(label="일반", style=discord.ButtonStyle.secondary)
    async def filter_common(self, interaction, btn):
        if interaction.user != self.user: return
        self.filter_grade = "일반"
        self.current_page = 0
        await interaction.response.edit_message(embed=self.make_embed(), view=self)

    @discord.ui.button(label="희귀+", style=discord.ButtonStyle.success)
    async def filter_rare(self, interaction, btn):
        if interaction.user != self.user: return
        self.filter_grade = "희귀+"
        self.current_page = 0
        await interaction.response.edit_message(embed=self.make_embed(), view=self)

    @discord.ui.button(label="아이템", style=discord.ButtonStyle.secondary)
    async def filter_items(self, interaction, btn):
        if interaction.user != self.user: return
        self.filter_grade = "아이템"
        self.current_page = 0
        await interaction.response.edit_message(embed=self.make_embed(), view=self)

    @discord.ui.button(label="◀ 이전", style=discord.ButtonStyle.secondary, row=2)
    async def prev(self, interaction, btn):
        if interaction.user != self.user: return
        if self.current_page > 0:
            self.current_page -= 1
        await interaction.response.edit_message(embed=self.make_embed(), view=self)

    @discord.ui.button(label="다음 ▶", style=discord.ButtonStyle.secondary, row=2)
    async def next(self, interaction, btn):
        if interaction.user != self.user: return
        if (self.current_page + 1) * self.per_page < len(self.all_items):
            self.current_page += 1
        await interaction.response.edit_message(embed=self.make_embed(), view=self)


class QuestDeliveryView(View):
    def __init__(self, user, item, amount, reward):
        super().__init__(timeout=60)
        self.user = user
        self.item = item
        self.amount = amount
        self.reward = reward

    @discord.ui.button(label="📦 납품하기", style=discord.ButtonStyle.success)
    async def deliver(self, interaction: discord.Interaction, button: Button):
        if interaction.user != self.user: return
        
        async with db.conn.execute("SELECT amount FROM inventory WHERE user_id=? AND item_name=?", (self.user.id, self.item)) as cursor:
            res = await cursor.fetchone()
        current = res[0] if res else 0

        if current < self.amount:
            return await interaction.response.send_message(f"❌ 물고기가 부족합니다! ({current}/{self.amount})", ephemeral=True)

        async with db.transaction():
            await db.execute("UPDATE inventory SET amount = amount - ? WHERE user_id=? AND item_name=?", (self.amount, self.user.id, self.item))
            await db.execute("UPDATE user_data SET coins = coins + ?, quest_is_cleared = 1 WHERE user_id = ?", (self.reward, self.user.id))
            await db.log_action(self.user.id, "QUEST_CLEAR", f"Item: {self.item}, Reward: {self.reward}")

        await interaction.response.edit_message(content=f"🎊 납품 완료! 보상으로 `{self.reward:,} C`를 획득했습니다!", embed=None, view=None)

class MarketPaginationView(View):
    def __init__(self, items, per_page=10):
        super().__init__(timeout=120)
        self.all_items = list(items.items())
        self.per_page = per_page
        self.current_page = 0

    def make_embed(self):
        from fishing_core.services.market_service import MarketService
        start = self.current_page * self.per_page
        items = self.all_items[start:start+self.per_page]
        embed = EmbedFactory.build(title="📊 실시간 수산시장 시세판", type="warning")
        embed.description = "시세는 30분마다 변동됩니다."
        for f, p in items:
            status = MarketService.get_price_status(f)
            embed.add_field(name=f"{f}", value=f"**{p:,} C**\n({status['status']})", inline=True)
        total = (len(self.all_items) - 1) // self.per_page + 1
        embed.set_footer(text=f"페이지 {self.current_page + 1} / {total}")
        return embed

    @discord.ui.button(label="◀ 이전", style=discord.ButtonStyle.secondary)
    async def prev(self, interaction, btn):
        if self.current_page > 0:
            self.current_page -= 1
        await interaction.response.edit_message(embed=self.make_embed(), view=self)

    @discord.ui.button(label="다음 ▶", style=discord.ButtonStyle.secondary)
    async def next(self, interaction, btn):
        if (self.current_page+1)*self.per_page < len(self.all_items):
            self.current_page += 1
        await interaction.response.edit_message(embed=self.make_embed(), view=self)


class ShopView(View):
    def __init__(self, user, items_data):
        super().__init__(timeout=60)
        self.user = user
        self.items_data = items_data

    @discord.ui.select(
        placeholder="🛒 구매할 물품을 선택하세요",
        options=[
            discord.SelectOption(label="고급 미끼 🪱", value="고급 미끼 🪱", description="500 C"),
            discord.SelectOption(label="자석 미끼 🧲", value="자석 미끼 🧲", description="800 C"),
            discord.SelectOption(label="초급 그물망 🕸️", value="초급 그물망 🕸️", description="500 C"),
            discord.SelectOption(label="튼튼한 그물망 🕸️", value="튼튼한 그물망 🕸️", description="1,200 C"),
            discord.SelectOption(label="에너지 드링크 ⚡", value="에너지 드링크 ⚡", description="1,500 C"),
            discord.SelectOption(label="가속 포션 💨", value="가속 포션 💨", description="3,000 C"),
            discord.SelectOption(label="특수 떡밥 🎣", value="특수 떡밥 🎣", description="2,000 C"),
            discord.SelectOption(label="레이드 작살 🔱", value="레이드 작살 🔱", description="5,000 C"),
        ]
    )
    async def select_item(self, interaction: discord.Interaction, select: discord.ui.Select):
        if interaction.user != self.user: return
        # views_v2 내의 클래스를 직접 사용하도록 수정 (순환 참조 방지)
        modal = ShopQuantityModal(select.values[0])
        await interaction.response.send_modal(modal)

class ShopQuantityModal(discord.ui.Modal):
    def __init__(self, item_name):
        super().__init__(title=f"🛒 {item_name} 구매")
        self.item_name = item_name
        self.quantity = discord.ui.TextInput(label="구매 수량", default="1", min_length=1, max_length=3)
        self.add_item(self.quantity)

    async def on_submit(self, interaction: discord.Interaction):
        try:
            amt = int(self.quantity.value)
            if amt <= 0: raise ValueError
        except ValueError:
            return await interaction.response.send_message("❌ 수량 오류", ephemeral=True)
            
        from fishing_core.services.market_service import MarketService
        result = await MarketService.process_purchase(interaction.user.id, self.item_name, amt)
        await interaction.response.send_message(result["message"], ephemeral=not result["success"])
class RecipeBookView(View):
    def __init__(self, recipes):
        super().__init__(timeout=120)
        self.recipes = list(recipes.items())
        self.current_page = 0
        self.per_page = 5 # 한 페이지에 5개씩 (가독성 고려)

    def make_embed(self):
        start = self.current_page * self.per_page
        end = start + self.per_page
        items = self.recipes[start:end]
        
        embed = EmbedFactory.build(title="👨‍🍳 수산시장 요리 도감", type="warning")
        embed.description = f"잡은 물고기를 사용하여 특별한 요리를 만듭니다. `/요리` 명령어로 제작 가능합니다.\n(총 {len(self.recipes)}종의 레시피 보유)"
        
        for name, data in items:
            ingredients = []
            for item, amt in data["ingredients"].items():
                display_item = "아무 물고기 🐟" if item == "*ANY_FISH*" else item
                ingredients.append(f"{display_item} x{amt}")
            
            ing_str = ", ".join(ingredients)
            duration = f"({data['duration']}분 지속)" if data.get("duration") else ""
            
            embed.add_field(
                name=f"🍲 {name} {duration}",
                value=f"**재료:** {ing_str}\n**효과:** {data['description']}",
                inline=False
            )
            
        total_pages = (len(self.recipes) - 1) // self.per_page + 1
        embed.set_footer(text=f"페이지 {self.current_page + 1} / {total_pages}")
        return embed

    @discord.ui.button(label="◀ 이전", style=discord.ButtonStyle.secondary)
    async def prev(self, interaction, btn):
        if self.current_page > 0:
            self.current_page -= 1
        await interaction.response.edit_message(embed=self.make_embed(), view=self)

    @discord.ui.button(label="다음 ▶", style=discord.ButtonStyle.secondary)
    async def next(self, interaction, btn):
        if (self.current_page + 1) * self.per_page < len(self.recipes):
            self.current_page += 1
        await interaction.response.edit_message(embed=self.make_embed(), view=self)
