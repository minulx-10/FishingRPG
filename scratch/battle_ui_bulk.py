
import os

file_path = r'c:\Users\master\Documents\Server\fishing_core\views.py'

with open(file_path, 'r', encoding='utf-8') as f:
    lines = f.readlines()

def replace_class_content(lines, class_name, new_content):
    start = -1
    end = -1
    for i, line in enumerate(lines):
        if f'class {class_name}(' in line:
            start = i
        if start != -1 and i > start and (line.startswith('class ') or line.startswith('def ') == False and line.strip() == "" and i+1 < len(lines) and lines[i+1].startswith('class ')):
            # This is tricky. Let's look for the next class.
            pass
    
    # Better: find start and end indices accurately
    start_idx = -1
    for i, line in enumerate(lines):
        if line.startswith(f"class {class_name}"):
            start_idx = i
            break
    
    if start_idx == -1: return lines
    
    end_idx = len(lines)
    for i in range(start_idx + 1, len(lines)):
        if lines[i].startswith("class "):
            end_idx = i
            break
            
    return lines[:start_idx] + [new_content] + lines[end_idx:]

# --- NEW BattleView ---
new_bv = """class BattleView(View):
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
        embed.add_field(name=f'🔵 {self.user.name} (나)', value=f'**{self.my_fish}**\\nHP: {hp_bar(self.my_hp, self.my_max_hp)} `{self.my_hp:,}`\\nAP: {ap_bar(self.my_ap)} `({self.my_ap}/8)`', inline=False)
        embed.add_field(name='━━━━━ VS ━━━━━', value=f'✨ 다음 턴 AP 수급: `+{self.ap_gain + 1}`', inline=False)
        embed.add_field(name='🔴 야생의 적', value=f'**{self.npc_fish}**\\nHP: {hp_bar(self.npc_hp, self.npc_max_hp)} `{self.npc_hp:,}`\\nAP: {ap_bar(self.npc_ap)} `({self.npc_ap}/8)`', inline=False)
        embed.add_field(name='📜 전투 로그', value=f'```md\\n{self.battle_log}```', inline=False)
        embed.set_footer(text='💡 팁: 공격 포인트를 모으면 데미지가 기하급수적으로 증가합니다!')
        file = discord.File('assets/battle/battle_start.png', filename='battle_start.png')
        embed.set_image(url='attachment://battle_start.png')
        return embed, file

    async def _update_view(self, interaction):
        embed, file = self.generate_embed()
        await interaction.edit_original_response(embed=embed, attachments=[file], view=self)

    @discord.ui.select(placeholder="⚔️ 공격 포인트 선택", options=[discord.SelectOption(label=f"{i} pt", value=str(i)) for i in range(9)])
    async def select_atk(self, interaction, select):
        if interaction.user != self.user: return
        val = int(select.values[0])
        if val + self.my_alloc['blk'] > self.my_ap:
            return await interaction.response.send_message(f'⚠️ 보유 AP({self.my_ap})를 초과할 수 없습니다!', ephemeral=True)
        self.my_alloc['atk'] = val
        await self._show_status(interaction)

    @discord.ui.select(placeholder="🛡️ 방어 포인트 선택", options=[discord.SelectOption(label=f"{i} pt", value=str(i)) for i in range(9)])
    async def select_blk(self, interaction, select):
        if interaction.user != self.user: return
        val = int(select.values[0])
        if val + self.my_alloc['atk'] > self.my_ap:
            return await interaction.response.send_message(f'⚠️ 보유 AP({self.my_ap})를 초과할 수 없습니다!', ephemeral=True)
        self.my_alloc['blk'] = val
        await self._show_status(interaction)

    async def _show_status(self, interaction):
        from fishing_core.services.battle_service import BattleService
        mult = BattleService.MULTIPLIERS.get(self.my_alloc['atk'], 0.0)
        status_embed = EmbedFactory.build(title='🛡️ 전략 배분 현황', type='info')
        status_embed.add_field(name='⚔️ 공격', value=f'`{self.my_alloc["atk"]} pt` (**{mult}x**)', inline=True)
        status_embed.add_field(name='🛡️ 방어', value=f'`{self.my_alloc["blk"]} pt`', inline=True)
        status_embed.add_field(name='💎 남은 AP', value=f'`{self.my_ap - sum(self.my_alloc.values())} pt`', inline=True)
        if not interaction.response.is_done(): await interaction.response.send_message(embed=status_embed, ephemeral=True)
        else: await interaction.followup.send(embed=status_embed, ephemeral=True)
        await self._update_view(interaction)

    @discord.ui.button(label='초기화', style=discord.ButtonStyle.secondary, emoji='🔄')
    async def btn_reset(self, interaction, button):
        if interaction.user != self.user: return
        self.my_alloc = {'atk': 0, 'blk': 0}
        await interaction.response.send_message('✅ 초기화 완료', ephemeral=True)
        await self._update_view(interaction)

    @discord.ui.button(label='전투 개시', style=discord.ButtonStyle.success, emoji='🔥')
    async def btn_confirm(self, interaction, button):
        if interaction.user != self.user: return
        await interaction.response.defer()
        from fishing_core.services.battle_service import BattleService
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
        log = f'[Turn {self.turn} 결과]\\n🔵 나: 공격 {self.my_alloc["atk"]}pt / {d1:,} 피해!\\n🔴 적: 공격 {npc_alloc["atk"]}pt / {d2:,} 피해!\\n'
        self.battle_log = log
        if self.npc_hp <= 0: return await self.end_battle(interaction, True)
        if self.my_hp <= 0: return await self.end_battle(interaction, False)
        self.my_ap = min(8, (self.my_ap - sum(self.my_alloc.values())) + self.ap_gain + 1)
        self.npc_ap = min(8, (self.npc_ap - sum(npc_alloc.values())) + self.ap_gain + 1)
        if self.ap_gain < 3: self.ap_gain += 1
        self.turn += 1
        self.my_alloc = {'atk': 0, 'blk': 0}
        await self._update_view(interaction)

    async def end_battle(self, interaction, is_win):
        self.stop()
        embed = EmbedFactory.build(title='🏆 승리' if is_win else '💀 패배', type='success' if is_win else 'error')
        if is_win:
            reward = int(self.npc_pwr * random.randint(5, 10))
            await db.execute('UPDATE user_data SET coins = coins + ? WHERE user_id = ?', (reward, self.user.id))
            await db.commit()
            embed.description = f'승리했습니다! 💰 보상: `{reward:,} C`'
            file_name = 'battle_victory.png'
        else:
            embed.description = '패배했습니다...'
            file_name = 'battle_defeat.png'
        file = discord.File(f'assets/battle/{file_name}', filename=file_name)
        embed.set_image(url=f'attachment://{file_name}')
        await interaction.edit_original_response(content=None, embed=embed, attachments=[file], view=None)
"""

# --- NEW PvPBattleView ---
new_pvp = """class PvPBattleView(View):
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
        embed.add_field(name=f'🔵 {self.p1.name}', value=f'**{self.p1_fish}**\\nHP: {hp_bar(self.p1_hp, self.p1_max_hp)} `{self.p1_hp:,}`\\nAP: {ap_bar(self.p1_ap)} `({self.p1_ap})`', inline=False)
        embed.add_field(name='━━━━━ VS ━━━━━', value=f'✨ 다음 턴 AP 수급: `+{self.ap_gain + 1}`', inline=False)
        embed.add_field(name=f'🔴 {self.p2.name}', value=f'**{self.p2_fish}**\\nHP: {hp_bar(self.p2_hp, self.p2_max_hp)} `{self.p2_hp:,}`\\nAP: {ap_bar(self.p2_ap)} `({self.p2_ap})`', inline=False)
        if not reveal:
            p1_s = '✅ 완료' if self.p1_ready else '🤔 고민 중'
            p2_s = '✅ 완료' if self.p2_ready else '🤔 고민 중'
            embed.add_field(name='🛡️ 전략 준비', value=f'{self.p1.name}: {p1_s} | {self.p2.name}: {p2_s}', inline=False)
        embed.add_field(name='📜 로그', value=f'```md\\n{self.battle_log}```', inline=False)
        file = discord.File('assets/battle/battle_start.png', filename='battle_start.png')
        embed.set_image(url='attachment://battle_start.png')
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
        from fishing_core.services.battle_service import BattleService
        mult = BattleService.MULTIPLIERS.get(alloc['atk'], 0.0)
        status_embed = EmbedFactory.build(title='🛡️ 내 전략 현황', type='info')
        status_embed.add_field(name='⚔️ 공격', value=f'`{alloc["atk"]} pt` (**{mult}x**)', inline=True)
        status_embed.add_field(name='🛡️ 방어', value=f'`{alloc["blk"]} pt`', inline=True)
        status_embed.add_field(name='💎 남은 AP', value=f'`{ap - sum(alloc.values())} pt`', inline=True)
        if not interaction.response.is_done(): await interaction.response.send_message(embed=status_embed, ephemeral=True)
        else: await interaction.followup.send(embed=status_embed, ephemeral=True)
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
        from fishing_core.services.battle_service import BattleService
        p1_res = BattleService.calculate_ap_battle(self.p1_pwr, self.p1_alloc['atk'], self.p2_alloc['blk'])
        p2_res = BattleService.calculate_ap_battle(self.p2_pwr, self.p2_alloc['atk'], self.p1_alloc['blk'])
        d1, d2 = p1_res['damage'], p2_res['damage']
        self.p2_hp -= d1
        self.p1_hp -= d2
        log = f'[Turn {self.turn_count} 결과]\\n🔵 {self.p1.name}: {d1:,} 피해!\\n🔴 {self.p2.name}: {d2:,} 피해!\\n'
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
        self.p1_ap = min(8, (self.p1_ap - sum(self.p1_alloc.values())) + self.ap_gain + 1)
        self.p2_ap = min(8, (self.p2_ap - sum(self.p2_alloc.values())) + self.ap_gain + 1)
        if self.ap_gain < 3: self.ap_gain += 1
        self.turn_count += 1
        self.p1_ready = self.p2_ready = False
        self.p1_alloc = self.p2_alloc = {'atk': 0, 'blk': 0}
        embed, file = self.generate_embed(reveal=True)
        await interaction.edit_original_response(embed=embed, attachments=[file], view=self)

    async def end_battle(self, interaction, winner, loser):
        self.stop()
        embed = EmbedFactory.build(title='⚔️ 종료', type='warning')
        embed.description = f'👑 **{winner.name}** 승리!'
        file = discord.File('assets/battle/battle_victory.png', filename='battle_victory.png')
        embed.set_image(url='attachment://battle_victory.png')
        await interaction.edit_original_response(content=None, embed=embed, attachments=[file], view=None)
"""

lines = replace_class_content(lines, "BattleView", new_bv)
lines = replace_class_content(lines, "PvPBattleView", new_pvp)

with open(file_path, 'w', encoding='utf-8') as f:
    f.writelines(lines)
print("Update Success")
