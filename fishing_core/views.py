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
            embed = EmbedFactory.build(title="💨 너무 일찍 당겼습니다!", description=f"낚싯줄을 던지자마자 당겨버렸습니다.\n잠시 입질을 기다리던 **{self.target_fish}**(이)가 놀라 도망갔습니다.", type="default")
            return await interaction.response.edit_message(content=None, embed=embed, view=None)
        
        self.resolved = True
        self.stop()
        
        elapsed = datetime.datetime.now(kst).timestamp() - self.start_time
        
        # [난이도 조정] 등급별 반응 시간 유동적 적용 (기존 1.5초 일괄 적용에서 상향)
        fish_data = FISH_DATA.get(self.target_fish, {"grade": "일반"})
        grade = fish_data.get("grade", "일반")
        
        # 등급별 제한 시간 (초)
        limit_map = {
            "일반": 3.0, "희귀": 3.0, "초희귀": 2.5, "에픽": 2.2, "소형 포식자": 2.5,
            "대형 포식자": 2.0, "레전드": 1.8, "신화": 1.8, "태고": 1.5, "환상": 1.5
        }
        time_limit = limit_map.get(grade, 2.0)
        
        if elapsed > time_limit:
            embed = EmbedFactory.build(title="💨 타이밍이 늦었습니다!", description=f"찰나의 순간, **{self.target_fish}**(이)가 미끼만 쏙 빼먹고 깊은 바다로 도망갔습니다.\n(반응 속도: `{elapsed:.2f}초` / 제한: `{time_limit}초`)", type="default")
            return await interaction.response.edit_message(content=None, embed=embed, view=None)
        
        if grade in ["대형 포식자", "레전드", "신화", "태고", "환상", "미스터리"]:
            # 힘겨루기 시작
            from fishing_core.views import TensionFishingView
            tension_view = TensionFishingView(self.user, self.target_fish, self.rod_tier, grade, self, elapsed)
            await interaction.response.edit_message(embed=tension_view.get_embed(), view=tension_view)
        else:
            await self.on_bite_success(interaction, elapsed, grade)

    async def on_bite_success(self, interaction: discord.Interaction, elapsed: float, grade: str):
        try:
            # 1. 기초 정보 수집 (메모리 상의 시세 데이터 참조)
            from fishing_core.shared import MARKET_PRICES
            price = MARKET_PRICES.get(self.target_fish, FISH_DATA.get(self.target_fish, {}).get("price", 100))

            # 2. 임베드 생성
            embed = EmbedFactory.build(title="✨ 낚시 성공! 월척입니다!", type="success")
            embed.set_author(name=f"{self.user.name}님의 포획 기록", icon_url=self.user.display_avatar.url)
            embed.description = f"**{self.target_fish}** (을)를 성공적으로 낚아올렸습니다!\n입질 반응 속도: `{elapsed:.2f}초`"
            embed.add_field(name="🧬 어종 등급", value=format_grade_label(grade), inline=True)
            embed.add_field(name="💰 현재 시세", value=f"`{price:,} C`", inline=True)

            grade_images = {
                "일반": "https://images.unsplash.com/photo-1524704659698-9ff3121ef3c4?w=400",
                "희귀": "https://images.unsplash.com/photo-1544551763-47a0159f963f?w=400",
                "초희귀": "https://images.unsplash.com/photo-1559130464-473ff4653658?w=400",
                "에픽": "https://images.unsplash.com/photo-1516684732162-798a0062be99?w=400",
                "레전드": "https://images.unsplash.com/photo-1534043464124-3be32fe000c9?w=400",
                "신화": "https://images.unsplash.com/photo-1498654203945-36283ca79272?w=400"
            }
            embed.set_thumbnail(url=grade_images.get(grade, grade_images["일반"]))

            # 3. 특수 로직 (크라켄 등)
            if self.target_fish == "심해의 파멸, 크라켄 🦑":
                async with db.conn.execute("SELECT user_id, coins FROM user_data WHERE user_id != ? AND coins > 1000 ORDER BY RANDOM() LIMIT 1", (self.user.id,)) as cursor:
                    target = await cursor.fetchone()
                if target:
                    stolen_amount = int(target[1] * 0.1)
                    await db.execute("UPDATE user_data SET coins = coins - ? WHERE user_id = ?", (stolen_amount, target[0]))
                    await db.execute("UPDATE user_data SET coins = coins + ? WHERE user_id = ?", (stolen_amount, self.user.id))
                    await db.commit()
                    embed.add_field(name="🦑 크라켄의 촉수 발동!", value=f"심연에서 뻗어 나온 거대한 촉수가 누군가의 금고를 부수고 `{stolen_amount:,} C`를 훔쳐 당신에게 가져왔습니다!!", inline=False)

            # 4. 더블 캐치 처리 및 응답 전송
            action_view = FishActionView(self.user, self.target_fish)
            double_msg = ""
            if getattr(self, "double_catch", False):
                await action_view._add_to_inventory()
                double_msg = " (👯 **더블 캐치!** 요리 효과로 한 마리 더 낚았습니다!)"

            # 응답 시도
            if not interaction.response.is_done():
                await interaction.response.edit_message(content=f"🎊 앗, 낚았습니다!{double_msg} 이 물고기를 어떻게 할까요?", embed=embed, view=action_view)
            else:
                await interaction.followup.send(content=f"🎊 앗, 낚았습니다!{double_msg} 이 물고기를 어떻게 할까요?", embed=embed, view=action_view)
            
            action_view.message = await interaction.original_response()

            # 5. 후속 처리 (업적, 튜토리얼, 재앙 알림) - 비동기로 진행해도 무방
            async with db.conn.execute("SELECT COUNT(*) FROM fish_dex WHERE user_id=?", (self.user.id,)) as cursor:
                dex_res = await cursor.fetchone()
                dex_count = dex_res[0] if dex_res else 0
            
            await AchievementService.check_achievement(self.user.id, "FIRST_CATCH")
            if grade in ["레전드", "신화", "태고", "환상", "미스터리"]:
                await AchievementService.check_achievement(self.user.id, "LEGENDARY_FISHER")

            if dex_count == 1:
                tutorial_embed = EmbedFactory.build(title="🌱 첫 낚시 성공을 축하합니다!", type="success")
                tutorial_embed.description = "방금 낚은 물고기는 당신의 첫 기록이 되었습니다!\n\n💡 `/가이드`를 통해 성장 로드맵을 확인하세요!"
                await interaction.followup.send(embed=tutorial_embed, ephemeral=True)

            if grade in ["태고", "환상", "미스터리", "신화"]:
                await db.log_action(self.user.id, "CATCH_RARE_FISH", f"Fish: {self.target_fish}, Grade: {grade}")
                if self.target_fish == "메갈로돈 🦈":
                    alert_embed = EmbedFactory.build(title="🦖 [경고] 바다가 공포에 질려 침묵합니다...", description=f"**{self.user.mention}**님이 거대 포식자 **{self.target_fish}**를 포획했습니다!", type="warning")
                    await interaction.channel.send(content="@here", embed=alert_embed)
                elif self.target_fish == "심해의 파멸, 크라켄 🦑":
                    alert_embed = EmbedFactory.build(title="🦑 [재앙 경고] 거대한 촉수가 솟구칩니다!!!", description=f"**{self.user.mention}**님이 전설의 재앙 **{self.target_fish}**를 심연에서 끌어올렸습니다!!!", type="error")
                    await interaction.channel.send(content="@here", embed=alert_embed)

        except Exception as e:
            logger.error(f"on_bite_success 오류: {e}")
            import traceback
            error_msg = f"❌ 낚시 처리 중 오류가 발생했습니다.\n```py\n{traceback.format_exc()[:500]}```"
            if not interaction.response.is_done():
                await interaction.response.send_message(error_msg, ephemeral=True)
            else:
                await interaction.followup.send(error_msg, ephemeral=True)


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
            if self.tension >= 100:
                msg = f"💥 낚싯줄이 팽팽하게 당겨지더니 끊어져 버렸습니다!\n**{self.target_fish}**(이)가 줄을 끊고 달아났습니다."
            else:
                msg = f"💨 낚싯줄이 너무 느슨해져 바늘이 빠졌습니다!\n**{self.target_fish}**(이)가 유유히 바다로 사라졌습니다."
            
            # 바다 빠짐 연출 강화
            if self.grade in ["레전드", "신화", "태고", "환상", "미스터리", "대형 포식자"] and random.random() < 0.2:
                duration_minutes = 30
                end_time = (datetime.datetime.now(kst) + datetime.timedelta(minutes=duration_minutes)).isoformat()
                await db.execute("INSERT INTO active_buffs (user_id, buff_type, end_time) VALUES (?, 'wet_clothes', ?) ON CONFLICT(user_id, buff_type) DO UPDATE SET end_time = ?", (self.user.id, end_time, end_time))
                await db.commit()
                
                fall_embed = EmbedFactory.build(title="🌊 으아아아! 바다에 빠졌습니다!!", type="error")
                fall_embed.description = f"**{self.target_fish}**의 엄청난 괴력에 이기지 못하고 배 밖으로 튕겨 나갔습니다!\n\n**[효과]**\n- 💨 **젖은 옷 (디버프)**: {duration_minutes}분 동안 낚시 대기 시간이 증가합니다.\n- 💔 **체력 감소**: 충격으로 인해 체력이 `20` 감소합니다."
                fall_embed.set_image(url="https://images.unsplash.com/photo-1519046904884-53103b34b206?w=800") # 거친 파도 이미지
                
                await db.execute("UPDATE user_data SET stamina = MAX(0, stamina - 20) WHERE user_id=?", (self.user.id,))
                await db.commit()
                
                return await interaction.response.edit_message(content=None, embed=fall_embed, view=None)
            
            await db.commit()
            fail_embed = EmbedFactory.build(title="❌ 포획 실패!", description=msg, type="default")
            return await interaction.response.edit_message(content=None, embed=fail_embed, view=None)

        if self.turn >= self.max_turns:
            if not (20 <= self.tension <= 80):
                self.stop()
                fail_embed = EmbedFactory.build(title="❌ 힘싸움 패배!", description=f"끝내 기력을 다한 **{self.target_fish}**를 제압하지 못했습니다. 물고기가 바늘을 털고 도망갔습니다.", type="default")
                return await interaction.response.edit_message(content=None, embed=fail_embed, view=None)
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
        super().__init__(timeout=120)
        self.user = user
        self.my_fish = my_fish
        self.npc_fish = npc_fish
        self.turn = 1
        self.ap_gain = 1
        self.my_ap = 1
        self.npc_ap = 1
        self.my_alloc = {'atk': 0, 'blk': 0}
        
        p1_pwr = FISH_DATA.get(my_fish, {}).get('power', 10)
        p2_pwr = FISH_DATA.get(npc_fish, {}).get('power', 10)
        self.my_hp = self.my_max_hp = p1_pwr * 12
        self.npc_hp = self.npc_max_hp = p2_pwr * 12
        self.my_pwr = p1_pwr
        self.npc_pwr = p2_pwr
        self.battle_log = f'🌊 **{npc_fish}**와(과) 마주쳤습니다!'

    def generate_embed(self):
        embed = EmbedFactory.build(title=f'⚔️ 전략 수산 배틀 (Turn {self.turn})', type='error')
        embed.set_author(name=f'{self.user.name}님의 전투', icon_url=self.user.display_avatar.url)
        
        def hp_bar(hp, mhp): return create_progress_bar(hp, mhp, length=10)
        def ap_bar(ap): return '🟦' * ap + '⬜' * (8 - ap)
            
        embed.add_field(name=f'🔵 {self.user.name} (나)', value=f'**{self.my_fish}**\nHP: {hp_bar(self.my_hp, self.my_max_hp)} `{self.my_hp:,}`\nAP: {ap_bar(self.my_ap)} `({self.my_ap}/8)`', inline=False)
        embed.add_field(name='━━━━━ VS ━━━━━', value=f'✨ 다음 턴 AP 수급: `+{self.ap_gain + 1}`', inline=False)
        embed.add_field(name='🔴 야생의 적', value=f'**{self.npc_fish}**\nHP: {hp_bar(self.npc_hp, self.npc_max_hp)} `{self.npc_hp:,}`\nAP: {ap_bar(self.npc_ap)} `({self.npc_ap}/8)`', inline=False)
        
        embed.add_field(name='📜 전투 로그', value=f'```md\n{self.battle_log}```', inline=False)
        embed.set_footer(text='💡 팁: 공격 포인트를 모으면 데미지가 기하급수적으로 증가합니다!')
        
        file = discord.File('assets/battle/battle_start.png', filename='battle_start.png')
        embed.set_image(url='attachment://battle_start.png')
        return embed, file

    async def _update_view(self, interaction):
        embed, file = self.generate_embed()
        await interaction.edit_original_response(embed=embed, attachments=[file], view=self)

    async def _handle_point(self, interaction, type):
        if interaction.user != self.user: 
            return await interaction.response.send_message('❌ 당신의 전투가 아닙니다!', ephemeral=True)
        
        current_spent = self.my_alloc['atk'] + self.my_alloc['blk']
        if current_spent >= self.my_ap: 
            return await interaction.response.send_message('⚠️ **AP 부족!** 더 이상 포인트를 배분할 수 없습니다.', ephemeral=True)
        
        self.my_alloc[type] += 1
        mult = BattleService.MULTIPLIERS.get(self.my_alloc['atk'], 0.0)
        
        # 예쁜 전략 확인 메시지
        status_embed = EmbedFactory.build(title='🛡️ 전략 배분 현황', type='info')
        status_embed.description = f'현재 {self.user.mention}님이 배분한 포인트입니다.'
        status_embed.add_field(name='⚔️ 공격 투자', value=f'`{self.my_alloc["atk"]} pt` (배율: **{mult}x**)', inline=True)
        status_embed.add_field(name='🛡️ 방어 투자', value=f'`{self.my_alloc["blk"]} pt`', inline=True)
        status_embed.add_field(name='💎 남은 AP', value=f'`{self.my_ap - (self.my_alloc["atk"] + self.my_alloc["blk"])} pt`', inline=True)
        
        if not interaction.response.is_done():
            await interaction.response.send_message(embed=status_embed, ephemeral=True)
        else:
            await interaction.followup.send(embed=status_embed, ephemeral=True)
        await self._update_view(interaction)

    @discord.ui.button(label='공격 +1', style=discord.ButtonStyle.danger, emoji='⚔️')
    async def btn_atk_plus(self, interaction, button):
        await self._handle_point(interaction, 'atk')

    @discord.ui.button(label='방어 +1', style=discord.ButtonStyle.primary, emoji='🛡️')
    async def btn_blk_plus(self, interaction, button):
        await self._handle_point(interaction, 'blk')

    @discord.ui.button(label='초기화', style=discord.ButtonStyle.secondary, emoji='🔄')
    async def btn_reset(self, interaction, button):
        if interaction.user != self.user: return
        self.my_alloc = {'atk': 0, 'blk': 0}
        await interaction.response.send_message('✅ 배분된 포인트가 초기화되었습니다.', ephemeral=True)
        await self._update_view(interaction)

    @discord.ui.button(label='전투 개시', style=discord.ButtonStyle.success, emoji='🔥')
    async def btn_confirm(self, interaction, button):
        if interaction.user != self.user: return
        await interaction.response.defer()
        
        npc_alloc = {'atk': 0, 'blk': 0}
        temp_ap = self.npc_ap
        while temp_ap > 0:
            choice = random.choice(['atk', 'blk', 'rsv'])
            if choice == 'rsv': break
            npc_alloc[choice] += 1
            temp_ap -= 1
            
        my_res = BattleService.calculate_ap_battle(self.my_pwr, self.my_alloc['atk'], npc_alloc['blk'])
        npc_res = BattleService.calculate_ap_battle(self.npc_pwr, npc_alloc['atk'], self.my_alloc['blk'])
        
        d1, d2 = my_res['damage'], npc_res['damage']
        self.npc_hp -= d1
        self.my_hp -= d2
        
        log = f'[Turn {self.turn} 결과]\n'
        log += f'🔵 나: 공격 {self.my_alloc["atk"]}pt, 방어 {self.my_alloc["blk"]}pt'
        log += f' -> {d1:,} 피해!\n' if d1 > 0 else ' -> 막힘!\n'
        log += f'🔴 적: 공격 {npc_alloc["atk"]}pt, 방어 {npc_alloc["blk"]}pt'
        log += f' -> {d2:,} 피해!\n' if d2 > 0 else ' -> 막힘!\n'
        self.battle_log = log
        
        if self.npc_hp <= 0: return await self.end_battle(interaction, True)
        if self.my_hp <= 0: return await self.end_battle(interaction, False)
        
        self.my_ap = min(8, (self.my_ap - (self.my_alloc['atk'] + self.my_alloc['blk'])) + self.ap_gain + 1)
        self.npc_ap = min(8, (self.npc_ap - (npc_alloc['atk'] + npc_alloc['blk'])) + self.ap_gain + 1)
        if self.ap_gain < 3: self.ap_gain += 1
        self.turn += 1
        self.my_alloc = {'atk': 0, 'blk': 0}
        await self._update_view(interaction)

    async def end_battle(self, interaction, is_win):
        self.stop()
        embed = EmbedFactory.build(title='🏆 전투 종료' if is_win else '💀 전투 패배', type='success' if is_win else 'error')
        embed.set_author(name=f'{self.user.name}님의 전투 결과', icon_url=self.user.display_avatar.url)
        
        if is_win:
            reward = int(self.npc_pwr * random.randint(5, 10))
            await db.execute('UPDATE user_data SET coins = coins + ? WHERE user_id = ?', (reward, self.user.id))
            await db.commit()
            embed.description = f'치열한 전투 끝에 승리하셨습니다!\n💰 획득 보상: `{reward:,} C`'
            file_name = 'battle_victory.png'
        else:
            embed.description = '야생의 물고기에게 패배하여 도망쳤습니다...'
            file_name = 'battle_defeat.png'
            
        file = discord.File(f'assets/battle/{file_name}', filename=file_name)
        embed.set_image(url=f'attachment://{file_name}')
        await interaction.edit_original_response(content=None, embed=embed, attachments=[file], view=None)

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
        self.battle_log = '⚔️ 전략적으로 포인트를 배분하여 승리하세요!'
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
            p1_status = '✅ 준비됨' if self.p1_ready else '🤔 배분 중'
            p2_status = '✅ 준비됨' if self.p2_ready else '🤔 배분 중'
            embed.add_field(name='🛡️ 전략 준비 상태', value=f'{self.p1.name}: {p1_status} | {self.p2.name}: {p2_status}', inline=False)
        
        embed.add_field(name='📜 최근 전투 로그', value=f'```md\n{self.battle_log}```', inline=False)
        file = discord.File('assets/battle/battle_start.png', filename='battle_start.png')
        embed.set_image(url='attachment://battle_start.png')
        return embed, file

    async def _update_view(self, interaction):
        embed, file = self.generate_embed()
        await interaction.edit_original_response(embed=embed, attachments=[file], view=self)

    async def _handle_point(self, interaction, type):
        is_p1 = (interaction.user == self.p1)
        is_p2 = (interaction.user == self.p2)
        if not is_p1 and not is_p2: return
        
        ready = self.p1_ready if is_p1 else self.p2_ready
        if ready: return await interaction.response.send_message('❌ 이미 결정을 완료했습니다!', ephemeral=True)
        
        alloc = self.p1_alloc if is_p1 else self.p2_alloc
        ap = self.p1_ap if is_p1 else self.p2_ap
        
        if alloc['atk'] + alloc['blk'] >= ap: 
            return await interaction.response.send_message('⚠️ **AP 부족!**', ephemeral=True)
        
        alloc[type] += 1
        mult = BattleService.MULTIPLIERS.get(alloc['atk'], 0.0)
        
        status_embed = EmbedFactory.build(title='🛡️ 내 전략 확인', type='info')
        status_embed.description = '상대에게는 보이지 않는 나만의 전략 정보입니다.'
        status_embed.add_field(name='⚔️ 공격', value=f'`{alloc["atk"]} pt` (배율: **{mult}x**)', inline=True)
        status_embed.add_field(name='🛡️ 방어', value=f'`{alloc["blk"]} pt`', inline=True)
        status_embed.add_field(name='💎 잔여 AP', value=f'`{ap - (alloc["atk"] + alloc["blk"])} pt`', inline=True)
        
        if not interaction.response.is_done():
            await interaction.response.send_message(embed=status_embed, ephemeral=True)
        else:
            await interaction.followup.send(embed=status_embed, ephemeral=True)
        await self._update_view(interaction)

    @discord.ui.button(label='공격+', style=discord.ButtonStyle.danger, emoji='⚔️')
    async def btn_atk_plus(self, interaction, button):
        await self._handle_point(interaction, 'atk')

    @discord.ui.button(label='방어+', style=discord.ButtonStyle.primary, emoji='🛡️')
    async def btn_blk_plus(self, interaction, button):
        await self._handle_point(interaction, 'blk')

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
            await interaction.response.send_message('✅ 전략이 확정되었습니다. 상대방의 결정을 기다립니다...', ephemeral=True)
            await self._update_view(interaction)

    async def resolve_turn(self, interaction):
        p1_res = BattleService.calculate_ap_battle(self.p1_pwr, self.p1_alloc['atk'], self.p2_alloc['blk'])
        p2_res = BattleService.calculate_ap_battle(self.p2_pwr, self.p2_alloc['atk'], self.p1_alloc['blk'])
        d1, d2 = p1_res['damage'], p2_res['damage']
        self.p2_hp -= d1
        self.p1_hp -= d2
        
        log = f'[Turn {self.turn_count} 결과]\n'
        log += f'🔵 {self.p1.name}: 공격 {self.p1_alloc["atk"]}pt / {d1:,} 피해!\n'
        log += f'🔴 {self.p2.name}: 공격 {self.p2_alloc["atk"]}pt / {d2:,} 피해!\n'
        self.battle_log = log
        
        if self.p1_hp <= 0 or self.p2_hp <= 0:
            if self.p1_hp <= 0:
                self.p1_idx += 1
                if self.p1_idx >= len(self.p1_deck): return await self.end_battle(interaction, self.p2, self.p1)
                self._init_fish(1)
            if self.p2_hp <= 0:
                self.p2_idx += 1
                if self.p2_idx >= len(self.p2_deck): return await self.end_battle(interaction, self.p1, self.p2)
                self._init_fish(2)

        self.p1_ap = min(8, (self.p1_ap - (self.p1_alloc['atk'] + self.p1_alloc['blk'])) + self.ap_gain + 1)
        self.p2_ap = min(8, (self.p2_ap - (self.p2_alloc['atk'] + self.p2_alloc['blk'])) + self.ap_gain + 1)
        if self.ap_gain < 3: self.ap_gain += 1
        self.turn_count += 1
        self.p1_ready = self.p2_ready = False
        self.p1_alloc = self.p2_alloc = {'atk': 0, 'blk': 0}
        
        embed, file = self.generate_embed(reveal=True)
        await interaction.edit_original_response(embed=embed, attachments=[file], view=self)

    async def end_battle(self, interaction, winner, loser):
        from fishing_core.database import db
        self.stop()
        async with db.conn.execute('SELECT coins FROM user_data WHERE user_id=?', (loser.id,)) as cursor:
            res = await cursor.fetchone()
        loser_coins = res[0] if res else 0
        steal = int(loser_coins * random.uniform(0.05, 0.10))
        if steal > 0:
            await db.execute('UPDATE user_data SET coins = coins - ? WHERE user_id=?', (steal, loser.id))
            await db.execute('UPDATE user_data SET coins = coins + ? WHERE user_id=?', (steal, winner.id))
            await db.commit()
        
        embed = EmbedFactory.build(title='⚔️ 대전 종료', type='warning')
        embed.description = f'👑 **{winner.name}** 승리!\n💰 약탈 금액: `{steal:,} C`'
        file = discord.File('assets/battle/battle_victory.png', filename='battle_victory.png')
        embed.set_image(url='attachment://battle_victory.png')
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
        self.per_page = 12
        self.filter_grade = "전체"

    def make_embed(self):
        coins, rod_tier, rating, boat_str, stamina, max_stamina, title = self.stats
        display_name = f"{title} {self.target.name}" if title else self.target.name
        
        embed = EmbedFactory.build(title=f"🎒 {display_name}님의 가방", type="info")
        if self.target.display_avatar:
            embed.set_thumbnail(url=self.target.display_avatar.url)

        # 상단 요약 정보
        hp_bar = create_progress_bar(stamina, max_stamina, length=8)
        embed.description = (
            f"🪙 **보유 코인:** `{coins:,} C` | 🏆 **점수:** `{rating:,}`\n"
            f"🎣 **낚싯대:** `Lv.{rod_tier}` | 🛳️ **선박:** `{boat_str}`\n"
            f"⚡ **행동력:** {hp_bar} `{stamina}/{max_stamina}`"
        )

        # 아이템 필터링 및 페이징
        start = self.current_page * self.per_page
        end = start + self.per_page
        items_slice = self.all_items[start:end]

        if not items_slice:
            embed.add_field(name="가방이 텅 비어있습니다.", value="낚시를 해서 물고기를 잡아보세요!", inline=False)
        else:
            item_list = []
            for name, amt, locked in items_slice:
                lock_icon = "🔒" if locked else ""
                grade = FISH_DATA.get(name, {}).get("grade", "일반")
                gl = format_grade_label(grade)
                item_list.append(f"{lock_icon} **{name}** `x{amt}` {gl}")
            
            # 2열로 배치
            half = (len(item_list) + 1) // 2
            col1 = "\n".join(item_list[:half])
            col2 = "\n".join(item_list[half:])
            
            embed.add_field(name=f"📦 보유 물품 (필터: {self.filter_grade})", value=col1 or " ", inline=True)
            embed.add_field(name="\u200b", value=col2 or " ", inline=True)

        total_pages = (len(self.all_items) - 1) // self.per_page + 1
        embed.set_footer(text=f"페이지 {self.current_page + 1} / {total_pages} | 총 {len(self.all_items)}종 보유")
        return embed

    @discord.ui.select(
        placeholder="등급별 필터 선택",
        options=[
            discord.SelectOption(label="전체 보기", value="전체", emoji="🌈"),
            discord.SelectOption(label="일반", value="일반", emoji="⚪"),
            discord.SelectOption(label="희귀", value="희귀", emoji="🔵"),
            discord.SelectOption(label="초희귀", value="초희귀", emoji="🟣"),
            discord.SelectOption(label="소형 포식자", value="소형 포식자", emoji="🦈"),
            discord.SelectOption(label="대형 포식자", value="대형 포식자", emoji="🦖"),
            discord.SelectOption(label="레전드 이상", value="레전드+", emoji="✨"),
        ]
    )
    async def filter_items(self, interaction: discord.Interaction, select: discord.ui.Select):
        if interaction.user != self.user: return
        val = select.values[0]
        self.filter_grade = val
        self.current_page = 0
        
        if val == "전체":
            self.all_items = self.original_items
        elif val == "레전드+":
            target_grades = ["레전드", "신화", "히든", "태고", "환상", "미스터리", "해신(海神)"]
            self.all_items = [i for i in self.original_items if FISH_DATA.get(i[0], {}).get("grade") in target_grades]
        else:
            self.all_items = [i for i in self.original_items if FISH_DATA.get(i[0], {}).get("grade") == val]
            
        await interaction.response.edit_message(embed=self.make_embed(), view=self)

    @discord.ui.button(label="◀ 이전", style=discord.ButtonStyle.secondary)
    async def prev(self, interaction, btn):
        if interaction.user != self.user: return
        if self.current_page > 0:
            self.current_page -= 1
        await interaction.response.edit_message(embed=self.make_embed(), view=self)

    @discord.ui.button(label="다음 ▶", style=discord.ButtonStyle.secondary)
    async def next(self, interaction, btn):
        if interaction.user != self.user: return
        if (self.current_page+1)*self.per_page < len(self.all_items):
            self.current_page += 1
        await interaction.response.edit_message(embed=self.make_embed(), view=self)



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
        embed.description = "시세는 30분마다 변동됩니다. 비쌀 때 팔아 이득을 챙기세요!"
        
        for f, p in items:
            status = MarketService.get_price_status(f)
            ratio_str = f"({status['status']})"
            embed.add_field(name=f"{f}", value=f"**{p:,} C**\n{ratio_str}", inline=True)
            
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
            discord.SelectOption(label="고급 미끼 🪱", value="고급 미끼 🪱", description="500 C | 희귀 어종 확률 증가"),
            discord.SelectOption(label="자석 미끼 🧲", value="자석 미끼 🧲", description="800 C | 보물상자 확률 증가"),
            discord.SelectOption(label="초급 그물망 🕸️", value="초급 그물망 🕸️", description="500 C | 한 번에 5마리 포획"),
            discord.SelectOption(label="튼튼한 그물망 🕸️", value="튼튼한 그물망 🕸️", description="1,200 C | 한 번에 10마리 포획"),
            discord.SelectOption(label="에너지 드링크 ⚡", value="에너지 드링크 ⚡", description="1,500 C | 체력 50 회복 (오버플로우 가능)"),
            discord.SelectOption(label="가속 포션 💨", value="가속 포션 💨", description="3,000 C | 30분간 낚시 대기 시간 단축"),
            discord.SelectOption(label="특수 떡밥 🎣", value="특수 떡밥 🎣", description="2,000 C | 30분간 희귀 등급 이상 확률 증가"),
            discord.SelectOption(label="레이드 작살 🔱", value="레이드 작살 🔱", description="5,000 C | 레이드 보스 데미지 2배"),
        ]
    )
    async def select_item(self, interaction: discord.Interaction, select: discord.ui.Select):
        if interaction.user != self.user: return
        from fishing_core.views import ShopQuantityModal
        await interaction.response.send_modal(ShopQuantityModal(select.values[0]))

class ShopQuantityModal(discord.ui.Modal):
    def __init__(self, item_name):
        super().__init__(title=f"🛒 {item_name} 구매")
        self.item_name = item_name
        self.quantity = discord.ui.TextInput(
            label="구매 수량",
            placeholder="구매할 수량을 입력하세요 (예: 1, 10, 50)",
            min_length=1,
            max_length=3,
            default="1"
        )
        self.add_item(self.quantity)

    async def on_submit(self, interaction: discord.Interaction):
        try:
            amt = int(self.quantity.value)
            if amt <= 0: raise ValueError
        except ValueError:
            return await interaction.response.send_message("❌ 수량은 1 이상의 숫자여야 합니다.", ephemeral=True)
            
        from fishing_core.services.market_service import MarketService
        result = await MarketService.process_purchase(interaction.user.id, self.item_name, amt)
        await interaction.response.send_message(result["message"], ephemeral=not result["success"])

class TutorialView(View):
    def __init__(self, user):
        super().__init__(timeout=120)
        self.user = user
        self.page = 0
        self.pages = [
            {
                "title": "🔰 초보자 쾌속 성장 가이드 (1/4)",
                "desc": "수산시장 RPG에 오신 것을 환영합니다! 아래 순서대로 따라오시면 금방 강태공이 될 수 있습니다.",
                "fields": [
                    ("1️⃣ 낚시의 기초 (잡기)", "`/낚시` 명령어를 입력하세요. 찌가 움직일 때 버튼을 눌러야 합니다.\n타이밍이 생명이니 집중하세요! (초보자는 체력 소모가 절반입니다)", False),
                    ("2️⃣ 자금 확보 (팔기)", "잡은 물고기는 `/판매`로 한꺼번에 팔 수 있습니다.\n`/시세`를 확인해 비쌀 때 파는 것이 핵심입니다.", False),
                ]
            },
            {
                "title": "🛠️ 스펙업과 경제 (2/4)",
                "desc": "더 큰 물고기, 더 많은 돈을 벌기 위한 필수 과정입니다.",
                "fields": [
                    ("📈 강화 (낚싯대)", "번 돈으로 `/강화`를 하세요. 낚싯대 레벨이 높을수록 전설급 물고기가 더 잘 낚입니다.", False),
                    ("🛳️ 개조 (선박)", "`/선박개조`를 통해 최대 체력(⚡)과 해역 진입 권한을 늘리세요.", False),
                    ("🏪 상점 활용", "`/상점`에서 미끼나 포션을 사면 낚시 효율이 극대화됩니다.", False),
                ]
            },
            {
                "title": "⚔️ 전투와 수족관 (3/4)",
                "desc": "낚시는 시작일 뿐입니다. 진정한 바다의 주인이 되어보세요.",
                "fields": [
                    ("🔒 아이템 잠금", "강한 물고기를 잡았다면 `/잠금` 하세요! 일괄 판매에서 보호됩니다.", False),
                    ("🤺 배틀 (NPC/PvP)", "잠금된 물고기를 데리고 `/배틀`이나 `/수산대전`에 참여하세요.", False),
                    ("🐠 수족관", "`/수족관`에 물고기를 넣어두면 시간이 흐르며 자동으로 코인을 생산합니다.", False),
                ]
            },
            {
                "title": "📜 의뢰와 요리 (4/4)",
                "desc": "단조로운 낚시에 활력을 불어넣는 시스템입니다.",
                "fields": [
                    ("📝 일일 의뢰", "`/의뢰`를 확인하고 목표 물고기를 가져가면 큰 보상을 얻습니다.", False),
                    ("🍳 요리 시스템", "잡은 물고기로 `/요리`를 만드세요. 강력한 버프를 얻거나 비싸게 팔 수 있습니다.", False),
                ]
            }
        ]

    def make_embed(self):
        p = self.pages[self.page]
        embed = EmbedFactory.build(title=p["title"], description=p["desc"], type="success")
        for name, val, inline in p["fields"]:
            embed.add_field(name=name, value=val, inline=inline)
        embed.set_footer(text=f"더 자세한 정보는 /도움말 을 확인하세요! (페이지 {self.page+1}/{len(self.pages)})")
        return embed

    @discord.ui.button(label="◀", style=discord.ButtonStyle.secondary)
    async def prev(self, interaction, btn):
        if interaction.user != self.user: return
        self.page = (self.page - 1) % len(self.pages)
        await interaction.response.edit_message(embed=self.make_embed())

    @discord.ui.button(label="▶", style=discord.ButtonStyle.secondary)
    async def next(self, interaction, btn):
        if interaction.user != self.user: return
        self.page = (self.page + 1) % len(self.pages)
        await interaction.response.edit_message(embed=self.make_embed())



