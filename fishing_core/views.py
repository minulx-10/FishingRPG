import discord
from discord.ui import View, Button
import random
import datetime
from .database import db
from .shared import FISH_DATA, MARKET_PRICES, get_element_multiplier

class FishActionView(View):
    def __init__(self, user, target_fish):
        super().__init__(timeout=30)
        self.user = user
        self.target_fish = target_fish
        self.action_taken = False 

    @discord.ui.button(label="가방에 보관 (판매용)", style=discord.ButtonStyle.primary, emoji="🎒")
    async def btn_inv(self, interaction: discord.Interaction, button: Button):
        if interaction.user != self.user or self.action_taken: return
        self.action_taken = True
        
        await db.execute("INSERT INTO inventory (user_id, item_name, amount) VALUES (?, ?, 1) ON CONFLICT(user_id, item_name) DO UPDATE SET amount = amount + 1", (self.user.id, self.target_fish))
        await db.commit()
        await interaction.response.edit_message(content=f"🎒 **{self.target_fish}**를 가방에 안전하게 넣었습니다!", view=None)

    @discord.ui.button(label="잠금 보관 (배틀용)", style=discord.ButtonStyle.success, emoji="🔒")
    async def btn_bucket(self, interaction: discord.Interaction, button: Button):
        if interaction.user != self.user or self.action_taken: return
        self.action_taken = True
        
        await db.execute("INSERT INTO inventory (user_id, item_name, amount, is_locked) VALUES (?, ?, 1, 1) ON CONFLICT(user_id, item_name) DO UPDATE SET amount = amount + 1, is_locked = 1", (self.user.id, self.target_fish))
        await db.commit()
        await interaction.response.edit_message(content=f"🔒 **{self.target_fish}**를 잠금 보관했습니다! 판매에서 보호되며 배틀에 출전할 수 있습니다.", view=None)

    @discord.ui.button(label="바로 판매", style=discord.ButtonStyle.danger, emoji="💰")
    async def btn_sell(self, interaction: discord.Interaction, button: Button):
        if interaction.user != self.user or self.action_taken: return
        self.action_taken = True
        
        price = MARKET_PRICES.get(self.target_fish, FISH_DATA.get(self.target_fish, {}).get("price", 100))
        await db.execute("UPDATE user_data SET coins = coins + ? WHERE user_id = ?", (price, self.user.id))
        await db.commit()
        await interaction.response.edit_message(content=f"💰 **{self.target_fish}**를 시장에 바로 넘겨서 `{price} C`를 벌었습니다!", view=None)


class FishingView(View):
    def __init__(self, user, target_fish, rod_tier):
        super().__init__(timeout=15) 
        self.user = user
        self.target_fish = target_fish
        self.rod_tier = rod_tier 
        self.is_bite = False  
        self.start_time = 0
        self.message = None 

        fish_info = FISH_DATA.get(self.target_fish, {"base_window": 2.0, "grade": "일반"})
        base_window = fish_info["base_window"]
        bonus_time = (self.rod_tier - 1) * 0.2 
        self.limit_time = max(1.0, base_window + bonus_time)

    async def on_timeout(self):
        for child in self.children:
            child.disabled = True
            
        if self.message:
            try:
                await self.message.edit(content="⏰ 낚시 시간이 초과되어 낚싯대를 거두었습니다.", view=self)
            except:
                pass

    @discord.ui.button(label="대기 중...", style=discord.ButtonStyle.secondary, emoji="🎣", custom_id="fish_btn")
    async def fish_button(self, interaction: discord.Interaction, button: Button):
        if interaction.user != self.user:
            return await interaction.response.send_message("남의 낚싯대입니다! 🚫", ephemeral=True)
        
        self.stop() 
        
        if not self.is_bite:
            return await interaction.response.edit_message(content="🎣 앗! 너무 일찍 챘습니다. 물고기가 도망갔어요! 💨", view=None)
        
        try:
            elapsed = datetime.datetime.now().timestamp() - self.start_time
            fish_info = FISH_DATA.get(self.target_fish, {"grade": "보물"})
            grade = fish_info["grade"]
            
            if elapsed <= self.limit_time:
                if grade in ["에픽", "레전드", "신화", "태고", "환상", "미스터리"]:
                    tension_view = TensionFishingView(self.user, self.target_fish, self.rod_tier, grade, self, elapsed)
                    await interaction.response.edit_message(content=f"❗ 거대한 물고기가 걸렸습니다! 힘겨루기 시작!", embed=tension_view.get_embed(), view=tension_view)
                else:
                    await self.on_bite_success(interaction, elapsed, grade)
            else:
                fail_msg = f"⏰ 너무 늦었습니다! `{elapsed:.3f}초` 걸림.\n(놓친 물고기: **{self.target_fish}** / 제한: {self.limit_time:.2f}초)"
                if grade in ["레전드", "신화", "태고", "환상", "미스터리"] and self.rod_tier > 1:
                    if random.random() < 0.5:
                        await db.execute("UPDATE user_data SET rod_tier = rod_tier - 1 WHERE user_id = ?", (self.user.id,))
                        fail_msg += "\n\n💥 **[치명적 손상]** 괴수의 힘을 이기지 못하고 **낚싯대가 부러졌습니다!** (낚싯대 레벨 1 하락)"
                
                if self.target_fish == "둔클레오스테우스 🦖":
                    async with db.conn.execute("SELECT item_name FROM inventory WHERE user_id=? AND amount > 0 AND is_locked=0", (self.user.id,)) as cursor:
                        items = await cursor.fetchall()
                    if items:
                        from fishing_core.shared import FISH_DATA
                        most_exp = max(items, key=lambda x: FISH_DATA.get(x[0], {}).get("price", 0))[0]
                        await db.execute("UPDATE inventory SET amount = amount - 1 WHERE user_id=? AND item_name=?", (self.user.id, most_exp))
                        fail_msg += f"\n\n🦖 **[강철의 턱]** 둔클레오스테우스가 도망치며 당신의 가방을 찢어 가장 비싼 물고기(**{most_exp}**)를 먹어치웠습니다!"
                
                await db.commit()
                await interaction.response.edit_message(content=fail_msg, view=None)
        except Exception as e:
            import traceback
            tb = traceback.format_exc()
            try:
                await interaction.response.edit_message(content=f"❌ 낚시 처리 중 오류:\n```py\n{tb[:1800]}\n```", view=None)
            except:
                await interaction.followup.send(f"❌ 낚시 처리 중 오류:\n```py\n{tb[:1800]}\n```", ephemeral=True)

    async def on_bite_success(self, interaction, elapsed, grade):
        try:
            await db.execute("INSERT OR IGNORE INTO fish_dex (user_id, item_name) VALUES (?, ?)", (self.user.id, self.target_fish))
            
            # 개체값(크기) 생성
            power = FISH_DATA.get(self.target_fish, {}).get("power", 10)
            fish_size = round(random.uniform(max(power * 1.5, 0.1), max(power * 2.5, 0.5)), 2)
            
            async with db.conn.execute("SELECT max_size FROM fish_records WHERE user_id=? AND item_name=?", (self.user.id, self.target_fish)) as cursor:
                record_res = await cursor.fetchone()
                
            is_new_record = False
            if not record_res:
                await db.execute("INSERT INTO fish_records (user_id, item_name, max_size) VALUES (?, ?, ?)", (self.user.id, self.target_fish, fish_size))
                is_new_record = True
            elif fish_size > record_res[0]:
                await db.execute("UPDATE fish_records SET max_size=? WHERE user_id=? AND item_name=?", (fish_size, self.user.id, self.target_fish))
                is_new_record = True
                
            await db.commit()
            
            embed = discord.Embed(title=f"🎉 낚시 성공! [{grade}]", description=f"**{self.target_fish}**를 낚았습니다!", color=0x00ff00)
            
            record_mark = " 🆕 **[최대 크기 신기록!]**" if is_new_record else ""
            embed.add_field(name="측정 크기", value=f"`{fish_size} cm`{record_mark}", inline=False)
            embed.add_field(name="반응 속도", value=f"`{elapsed:.3f}초` (판정 한도: {self.limit_time:.2f}초)", inline=False)
            
            if random.random() < 0.05:
                piece = random.choice(["찢어진 지도 조각 A 🧩", "찢어진 지도 조각 B 🧩", "찢어진 지도 조각 C 🧩", "찢어진 지도 조각 D 🧩"])
                await db.execute("INSERT INTO inventory (user_id, item_name, amount) VALUES (?, ?, 1) ON CONFLICT(user_id, item_name) DO UPDATE SET amount = amount + 1", (self.user.id, piece))
                await db.commit()
                embed.add_field(name="🗺️ 바다의 파편 발견!", value=f"물고기와 함께 **{piece}**가 딸려왔습니다! (4부위를 모아 합성하세요)", inline=False)

            if self.target_fish == "심해의 파멸, 크라켄 🦑":
                async with db.conn.execute("SELECT user_id, coins FROM user_data WHERE user_id != ? AND coins > 1000 AND peace_mode=0 ORDER BY RANDOM() LIMIT 1", (self.user.id,)) as cursor:
                    target = await cursor.fetchone()
                
                if target:
                    stolen_amount = int(target[1] * 0.1)
                    await db.execute("UPDATE user_data SET coins = coins - ? WHERE user_id = ?", (stolen_amount, target[0]))
                    await db.execute("UPDATE user_data SET coins = coins + ? WHERE user_id = ?", (stolen_amount, self.user.id))
                    await db.commit()
                    embed.add_field(name="🦑 크라켄의 촉수 발동!", value=f"심연에서 뻗어 나온 거대한 촉수가 누군가의 금고를 부수고 `{stolen_amount:,} C`를 훔쳐 당신에게 가져왔습니다!!", inline=False)
            
            action_view = FishActionView(self.user, self.target_fish)
            await interaction.response.edit_message(content="🎊 앗, 낚았습니다! 이 물고기를 어떻게 할까요?", embed=embed, view=action_view)
        except Exception as e:
            import traceback
            tb = traceback.format_exc()
            try:
                await interaction.response.edit_message(content=f"❌ 낚시 결과 처리 중 오류:\n```py\n{tb[:1800]}\n```", view=None)
            except:
                await interaction.followup.send(f"❌ 낚시 결과 처리 중 오류:\n```py\n{tb[:1800]}\n```", ephemeral=True)
        
        if grade in ["태고", "환상", "미스터리", "신화"]:
            alert_embed = None
            if self.target_fish == "메갈로돈 🦈":
                alert_embed = discord.Embed(title="🦖 [경고] 바다가 공포에 질려 침묵합니다...", description=f"**{self.user.mention}**님이 낚싯대를 부러뜨릴 듯한 괴력을 이겨내고,\n역사상 가장 거대한 포식자 **{self.target_fish}**를 현세에 끌어올렸습니다!!!", color=0x8b4513)
                alert_embed.set_footer(text="거대한 등지느러미가 해수면을 가릅니다...")
            elif self.target_fish == "둔클레오스테우스 🦖":
                alert_embed = discord.Embed(title="🦖 [경고] 태고의 바다가 갈라집니다!", description=f"**{self.user.mention}**님이 강철 턱을 가진 고생대의 포식자,\n**{self.target_fish}**를 낚아 올렸습니다!!!", color=0x8b4513)
                alert_embed.set_footer(text="무언가 으스러지는 끔찍한 소리가 들려옵니다...")
            elif self.target_fish == "모사사우루스 🦖":
                alert_embed = discord.Embed(title="🦖 [경고] 해수면이 거칠게 요동칩니다!", description=f"**{self.user.mention}**님이 백악기 바다의 절대 지배자,\n**{self.target_fish}**의 눈을 뜨게 만들었습니다!!!", color=0x8b4513)
                alert_embed.set_footer(text="포효 소리에 모든 물고기들이 숨어버립니다...")
            elif self.target_fish == "바다의 파괴자, 루스카 🐙":
                alert_embed = discord.Embed(title="🌪️ [위험] 블루홀의 저주가 시작됩니다...", description=f"**{self.user.mention}**님이 상어와 문어의 끔찍한 혼종,\n**{self.target_fish}**를 수면 밖으로 건져냈습니다!!!", color=0x9932cc)
                alert_embed.set_footer(text="바닷물이 검은 먹물로 물들기 시작합니다...")
            elif self.target_fish == "움직이는 섬, 자라탄 🐢":
                alert_embed = discord.Embed(title="🏝️ [경고] 거대한 대지가 움직이기 시작합니다!", description=f"**{self.user.mention}**님이 낚은 것은 단순한 물고기가 아닙니다!\n지도에 없던 섬, **{self.target_fish}**가 바다 한가운데서 솟아올랐습니다!!!", color=0x9932cc)
                alert_embed.set_footer(text="섬의 숲과 흙이 바다로 무너져 내립니다...")
            elif self.target_fish == "여섯 개의 머리, 스킬라 🐉":
                alert_embed = discord.Embed(title="🐉 [위험] 비명소리가 바다를 뒤덮습니다...", description=f"**{self.user.mention}**님이 해협에 숨겨진 재앙,\n**{self.target_fish}**의 굶주린 턱 여섯 개를 한 번에 낚아 올렸습니다!!!", color=0x9932cc)
                alert_embed.set_footer(text="수많은 눈동자들이 당신을 주시합니다...")
            elif self.target_fish == "네스호의 그림자, 네시 🦕":
                alert_embed = discord.Embed(title="🌫️ [미스터리] 안개가 짙게 깔리기 시작합니다...", description=f"**{self.user.mention}**님의 낚싯대 끝에서 미확인 수장룡,\n**{self.target_fish}**의 거대한 실루엣이 모습을 드러냈습니다!!!", color=0x2f4f4f)
                alert_embed.set_footer(text="카메라 셔터 소리만 정적을 채웁니다...")
            elif self.target_fish == "심연의 울음소리, 더 블룹 🔊":
                alert_embed = discord.Embed(title="🔊 [미스터리] 원인 불명의 거대 음파가 감지되었습니다!", description=f"**{self.user.mention}**님이 지구상에 존재할 수 없는 크기의 무언가,\n**{self.target_fish}**의 결정체를 심연에서 끌어올렸습니다!!!", color=0x2f4f4f)
                alert_embed.set_footer(text="기괴하고 거대한 울음소리가 서버를 뒤흔듭니다...")
            elif self.target_fish == "남극의 인간형 거수, 닝겐 👻":
                alert_embed = discord.Embed(title="👻 [미스터리] 얼어붙은 바다 아래서 끔찍한 시선이 느껴집니다...", description=f"**{self.user.mention}**님이 새하얀 기형의 괴생명체,\n**{self.target_fish}**와 정면으로 눈이 마주쳤습니다!!!", color=0x2f4f4f)
                alert_embed.set_footer(text="물결 아래에서 기괴하게 웃고 있는 형상이 보입니다...")
            elif self.target_fish == "심연의 지배자, 레비아탄 🌋":
                alert_embed = discord.Embed(title="🌋 [재앙 경고] 바닷물이 끓어오르고 붉게 물듭니다!!!", description=f"**{self.user.mention}**님이 성서 속의 재앙 그 자체,\n**{self.target_fish}**를 깨워 세상에 종말을 선고했습니다!!!", color=0xff0000)
                alert_embed.set_footer(text="압도적인 열기가 모든 것을 태워버릴 듯합니다...")
            elif self.target_fish == "심해의 파멸, 크라켄 🦑":
                alert_embed = discord.Embed(title="🦑 [재앙 경고] 거대한 촉수들이 해수면을 산산조각 냅니다!!!", description=f"**{self.user.mention}**님이 수백 척의 배를 가라앉힌 북유럽의 악몽,\n**{self.target_fish}**를 심연에서 건져 올렸습니다!!!", color=0xff0000)
                alert_embed.set_footer(text="바다가 검게 물들고, 하늘마저 촉수로 뒤덮입니다...")
            elif self.target_fish == "세계를 감싼 뱀, 요르문간드 🐍":
                alert_embed = discord.Embed(title="🐍 [재앙 경고] 전 세계의 해수면이 동시에 상승합니다!!!", description=f"**{self.user.mention}**님이 낚싯줄을 당기자, 자신의 꼬리를 물고 있던 재앙의 뱀\n**{self.target_fish}**가 똬리를 풀고 지구를 흔듭니다!!!", color=0xff0000)
                alert_embed.set_footer(text="거대한 비늘이 대지를 부수며 솟아오릅니다...")
            elif self.target_fish == "대소용돌이의 재앙, 카리브디스 🌀":
                alert_embed = discord.Embed(title="🌀 [재앙 경고] 바다 한가운데 끝없는 구멍이 열렸습니다!!!", description=f"**{self.user.mention}**님이 모든 것을 집어삼키는 죽음의 소용돌이,\n**{self.target_fish}**를 강제로 멈춰 세웠습니다!!!", color=0xff0000)
                alert_embed.set_footer(text="물살이 주변의 모든 빛과 소리를 빨아들입니다...")
            elif self.target_fish == "바다의 원혼, 우미보즈 🌑":
                alert_embed = discord.Embed(title="🌑 [재앙 경고] 달빛마저 가려진 칠흑 같은 어둠이 강림합니다...", description=f"**{self.user.mention}**님이 낚싯대로 끌어올린 것은 물고기가 아닙니다!\n밤바다의 거대한 원혼, **{self.target_fish}**가 배를 짓누릅니다!!!", color=0xff0000)
                alert_embed.set_footer(text="검은 그림자가 두 눈을 번뜩이며 내려다봅니다...")
            elif self.target_fish == "이름 없는 심해의 고대신 (크툴루) 👁️":
                alert_embed = discord.Embed(title="👁️ [재앙 경고] 정신이 산산조각 날 것 같은 환청이 들려옵니다!!!", description=f"**{self.user.mention}**님이 결코 깨워선 안 될 우주의 공포,\n**{self.target_fish}**를 심연에서 건져 올렸습니다!!!", color=0xff0000)
                alert_embed.set_footer(text="Ph'nglui mglw'nafh... 이성이 붕괴되기 시작합니다...")
            elif self.target_fish == "죽음의 선율, 세이렌의 군주 🧜‍♀️":
                alert_embed = discord.Embed(title="🎵 [재앙 경고] 아름다운 노랫소리가 들립니다...", description=f"**{self.user.mention}**님이 선원들을 홀리는 죽음의 선율,\n**{self.target_fish}**를 마주했습니다!!!", color=0xff0000)
                alert_embed.set_footer(text="노래를 듣는 순간 바다로 뛰어들고 싶은 충동이 듭니다...")
            elif self.target_fish == "강철 지느러미, 아스피도켈론 🐢":
                alert_embed = discord.Embed(title="🛡️ [재앙 경고] 거대한 지형의 변화가 감지되었습니다!!!", description=f"**{self.user.mention}**님이 등에 숲을 짊어진 불괴의 요새,\n**{self.target_fish}**를 낚아 바다의 지형을 바꿨습니다!!!", color=0xff0000)
                alert_embed.set_footer(text="절대 뚫리지 않는 강철의 파도가 일어납니다...")
            elif self.target_fish == "차원의 포식자, 보이드 샤크 🌌":
                alert_embed = discord.Embed(title="🌌 [재앙 경고] 공간이 일그러지며 차원의 균열이 발생했습니다!!!", description=f"**{self.user.mention}**님이 현실을 찢고 나온 공허의 상어,\n**{self.target_fish}**를 이 세계로 낚아챘습니다!!!", color=0xff0000)
                alert_embed.set_footer(text="괴수 주변의 시간과 공간이 빨려 들어갑니다...")
            elif self.target_fish == "벼락의 신수, 이쿠치 ⚡":
                alert_embed = discord.Embed(title="⚡ [재앙 경고] 수천 개의 번개가 바다를 내리칩니다!!!", description=f"**{self.user.mention}**님이 전설의 뇌전 뱀,\n**{self.target_fish}**를 구름 위로 낚아 올렸습니다!!!", color=0xff0000)
                alert_embed.set_footer(text="숨 막히는 전압이 공기를 태워버립니다...")
            elif self.target_fish == "황금의 눈먼 왕, 엘도라도 리바이어던 👑":
                alert_embed = discord.Embed(title="👑 [재앙 경고] 심해에서 찬란한 황금빛이 폭발합니다!!!", description=f"**{self.user.mention}**님이 황금 제국의 수호룡,\n**{self.target_fish}**를 빛의 기둥과 함께 소환했습니다!!!", color=0xffd700)
                alert_embed.set_footer(text="순금의 비늘이 바다 전체를 황금빛으로 물들입니다...")
            elif self.target_fish == "얼어붙은 분노, 이미르의 눈물 ❄️":
                alert_embed = discord.Embed(title="❄️ [재앙 경고] 주변의 바다가 순식간에 얼어붙습니다!!!", description=f"**{self.user.mention}**님이 빙하의 괴수,\n**{self.target_fish}**를 깨워 빙하기를 선고했습니다!!!", color=0xff0000)
                alert_embed.set_footer(text="내쉬는 숨결 하나에 온 세상이 얼어붙습니다...")

            if alert_embed is not None:
                await interaction.channel.send(content="@here", embed=alert_embed)

class TensionFishingView(View):
    def __init__(self, user, target_fish, rod_tier, grade, parent_view, elapsed):
        super().__init__(timeout=20)
        self.user = user
        self.target_fish = target_fish
        self.rod_tier = rod_tier
        self.grade = grade
        self.parent_view = parent_view
        self.elapsed = elapsed
        self.tension = 50
        self.turn = 1
        self.max_turns = 3 if grade == "에픽" else (4 if grade == "레전드" else 5)

    def get_embed(self):
        embed = discord.Embed(title="🎣 거대 괴수와 힘겨루기!", color=0x3498db)
        embed.description = f"물고기가 강하게 저항합니다! 텐션을 **20% ~ 80%** 사이로 유지하세요!\n(남은 턴: {self.max_turns - self.turn + 1})"
        
        bars = int(self.tension / 10)
        tension_str = "🟥" * bars + "⬛" * (10 - bars)
        
        status = "🟢 안전" if 20 <= self.tension <= 80 else "🔴 위험!"
        embed.add_field(name=f"현재 텐션: {self.tension}%", value=f"{tension_str} ({status})", inline=False)
        return embed

    async def execute_turn(self, interaction, action):
        if action == "당기기":
            self.tension += random.randint(15, 25)
        else:
            self.tension -= random.randint(15, 25)

        fish_action = random.choice([-15, -10, 10, 15])
        self.tension += fish_action

        if self.tension >= 100 or self.tension <= 0:
            self.stop()
            if self.tension >= 100:
                msg = f"💥 줄이 끊어졌습니다! (텐션 100% 초과)\n놓친 물고기: **{self.target_fish}**"
                if self.grade in ["레전드", "신화", "태고", "환상", "미스터리"] and self.rod_tier > 1 and random.random() < 0.5:
                    await db.execute("UPDATE user_data SET rod_tier = rod_tier - 1 WHERE user_id = ?", (self.user.id,))
                    msg += "\n\n💥 **[치명적 손상]** 괴수의 힘을 이기지 못하고 **낚싯대가 부러졌습니다!** (레벨 1 하락)"
            else:
                msg = f"💨 물고기가 바늘을 털고 도망갔습니다! (텐션 0% 미만)\n놓친 물고기: **{self.target_fish}**"
                
            if self.target_fish == "둔클레오스테우스 🦖":
                async with db.conn.execute("SELECT item_name FROM inventory WHERE user_id=? AND amount > 0 AND is_locked=0", (self.user.id,)) as cursor:
                    items = await cursor.fetchall()
                if items:
                    from fishing_core.shared import FISH_DATA
                    most_exp = max(items, key=lambda x: FISH_DATA.get(x[0], {}).get("price", 0))[0]
                    await db.execute("UPDATE inventory SET amount = amount - 1 WHERE user_id=? AND item_name=?", (self.user.id, most_exp))
                    msg += f"\n\n🦖 **[강철의 턱]** 둔클레오스테우스가 도망치며 가장 비싼 물고기(**{most_exp}**)를 먹어치웠습니다!"
            
            await db.commit()
            return await interaction.response.edit_message(content=msg, embed=None, view=None)

        if self.turn >= self.max_turns:
            if not (20 <= self.tension <= 80):
                self.stop()
                return await interaction.response.edit_message(content=f"💨 아깝게 놓쳤습니다! 마지막 텐션 조절에 실패했습니다.\n놓친 물고기: **{self.target_fish}**", embed=None, view=None)
            else:
                self.stop()
                await self.parent_view.on_bite_success(interaction, self.elapsed, self.grade)
        else:
            self.turn += 1
            await interaction.response.edit_message(embed=self.get_embed(), view=self)

    @discord.ui.button(label="당기기 (텐션 증가)", style=discord.ButtonStyle.danger, emoji="🔥")
    async def btn_pull(self, interaction: discord.Interaction, button: Button):
        if interaction.user != self.user: return
        await self.execute_turn(interaction, "당기기")

    @discord.ui.button(label="풀기 (텐션 감소)", style=discord.ButtonStyle.primary, emoji="💧")
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
        embed = discord.Embed(title=f"⚔️ 턴제 수산 배틀 (Turn {self.turn})", color=0xff0000)
        my_hp_bar = "🟩" * max(0, int((self.my_hp / self.my_max_hp) * 5)) + "⬛" * (5 - max(0, int((self.my_hp / self.my_max_hp) * 5)))
        embed.add_field(name=f"🔵 {self.user.name}의 [{self.my_elem}]", value=f"**{self.my_fish}**\n체력: {self.my_hp}/{self.my_max_hp} {my_hp_bar}\nAP: ⚡x{self.my_ap}", inline=True)
        embed.add_field(name="VS", value="⚡", inline=True)
        npc_hp_bar = "🟥" * max(0, int((self.npc_hp / self.npc_max_hp) * 5)) + "⬛" * (5 - max(0, int((self.npc_hp / self.npc_max_hp) * 5)))
        embed.add_field(name=f"🔴 야생의 [{self.npc_elem}]", value=f"**{self.npc_fish}**\n체력: {self.npc_hp}/{self.npc_max_hp} {npc_hp_bar}\nAP: ⚡x{self.npc_ap}", inline=True)
        embed.add_field(name="📜 전투 로그", value=f"```\n{self.battle_log}\n```", inline=False)
        return embed

    async def execute_turn(self, interaction: discord.Interaction, action: str):
        self.battle_log = ""
        if action == "attack":
            self.is_my_defending = False
            mult = get_element_multiplier(self.my_elem, self.npc_elem)
            dmg = int(self.my_atk * self.my_ap * mult)
            if self.is_npc_defending: dmg //= 2
            
            self.npc_hp -= dmg
            elem_txt = "(효과 발군!)" if mult > 1.0 else ("(효과 미미...)" if mult < 1.0 else "")
            self.battle_log += f"🔵 {self.my_fish}의 공격! 💥 {dmg} 피해! {elem_txt}\n"
            self.my_ap = 1 
        else: 
            self.is_my_defending = True
            self.my_ap += 1
            self.battle_log += f"🔵 {self.my_fish} 방어 태세! 피해 반감 & AP 1 회복.\n"

        if self.npc_hp <= 0:
            return await self.end_battle(interaction, is_win=True)

        npc_action = "attack" if (random.random() > 0.4 and self.npc_ap > 0) else "defend"
        
        if npc_action == "attack":
            self.is_npc_defending = False
            mult = get_element_multiplier(self.npc_elem, self.my_elem)
            dmg = int(self.npc_atk * self.npc_ap * mult)
            if self.is_my_defending: dmg //= 2
            
            self.my_hp -= dmg
            self.battle_log += f"🔴 {self.npc_fish}의 반격! 💥 {dmg} 피해!\n"
            self.npc_ap = 1
        else:
            self.is_npc_defending = True
            self.npc_ap += 1
            self.battle_log += f"🔴 {self.npc_fish} 방어 태세. 기를 모읍니다.\n"

        if self.my_hp <= 0:
            return await self.end_battle(interaction, is_win=False)

        self.turn += 1
        await interaction.response.edit_message(embed=self.generate_embed(), view=self)

    async def end_battle(self, interaction, is_win):
        self.stop() 
        embed = self.generate_embed()
        
        if is_win:
            reward_rp = random.randint(10, 30)
            reward_coin = FISH_DATA[self.npc_fish]["power"] * 5
            await db.execute("UPDATE user_data SET rating = rating + ?, coins = coins + ? WHERE user_id = ?", (reward_rp, reward_coin, self.user.id))
            await db.commit()
            embed.description = f"🎉 **승리했습니다!** (보상: +{reward_rp} RP, +{reward_coin} C)"
            embed.color = 0x00ff00
        else:
            lose_rp = random.randint(5, 15)
            await db.execute("UPDATE user_data SET rating = MAX(0, rating - ?) WHERE user_id = ?", (lose_rp, self.user.id))
            await db.commit()
            embed.description = f"💀 **패배했습니다...** (패널티: -{lose_rp} RP)"
            embed.color = 0x555555

        await interaction.response.edit_message(embed=embed, view=None)

    @discord.ui.button(label="공격 (AP소모)", style=discord.ButtonStyle.danger, emoji="⚔️")
    async def btn_attack(self, interaction: discord.Interaction, button: Button):
        if interaction.user != self.user: return
        await self.execute_turn(interaction, "attack")

    @discord.ui.button(label="방어/기모으기 (AP+1)", style=discord.ButtonStyle.primary, emoji="🛡️")
    async def btn_defend(self, interaction: discord.Interaction, button: Button):
        if interaction.user != self.user: return
        await self.execute_turn(interaction, "defend")

class PvPBattleView(View):
    def __init__(self, p1, p2, p1_deck, p2_deck):
        super().__init__(timeout=120)
        self.p1 = p1
        self.p2 = p2
        self.p1_deck = p1_deck
        self.p2_deck = p2_deck
        
        self.p1_idx = 0
        self.p2_idx = 0

        self.p1_ap = 1
        self.p1_defending = False
        
        self.p2_ap = 1
        self.p2_defending = False

        self._init_fish(1)
        self._init_fish(2)

        self.turn_count = 1
        self.current_turn_user = p1
        self.battle_log = f"⚔️ {p1.name}님이 {p2.name}님에게 3v3 수산대전을 걸었습니다!\n"

    def _init_fish(self, p_num):
        if p_num == 1:
            name, pwr = self.p1_deck[self.p1_idx]
            self.p1_fish = name
            self.p1_max_hp = self.p1_hp = pwr * 10
            self.p1_atk = pwr
            self.p1_elem = FISH_DATA.get(name, {}).get("element", "무")
            self.p1_ap = 1
            self.p1_defending = False
        else:
            name, pwr = self.p2_deck[self.p2_idx]
            self.p2_fish = name
            self.p2_max_hp = self.p2_hp = pwr * 10
            self.p2_atk = pwr
            self.p2_elem = FISH_DATA.get(name, {}).get("element", "무")
            self.p2_ap = 1
            self.p2_defending = False

    def generate_embed(self):
        embed = discord.Embed(title=f"⚔️ 3v3 릴레이 수산대전 (Turn {self.turn_count})", color=0xff0000)
        embed.description = f"**현재 턴:** {self.current_turn_user.mention} 님의 행동을 기다리는 중..."

        def get_hp_bar(hp, max_hp):
            ratio = hp / max_hp if max_hp > 0 else 0
            filled = max(0, int(ratio * 5))
            return "🟩" * filled + "⬛" * (5 - filled)

        p1_hp_bar = get_hp_bar(self.p1_hp, self.p1_max_hp)
        p1_deck_status = "".join(["🟢" if i >= self.p1_idx else "🔴" for i in range(len(self.p1_deck))])
        
        p2_hp_bar = get_hp_bar(self.p2_hp, self.p2_max_hp)
        p2_deck_status = "".join(["🟢" if i >= self.p2_idx else "🔴" for i in range(len(self.p2_deck))])

        embed.add_field(name=f"🔵 {self.p1.name} [{self.p1_elem}]", value=f"엔트리: {p1_deck_status}\n**{self.p1_fish}**\n체력: {self.p1_hp}/{self.p1_max_hp} {p1_hp_bar}\nAP: ⚡x{self.p1_ap}", inline=True)
        embed.add_field(name="VS", value="⚡", inline=True)
        embed.add_field(name=f"🔴 {self.p2.name} [{self.p2_elem}]", value=f"엔트리: {p2_deck_status}\n**{self.p2_fish}**\n체력: {self.p2_hp}/{self.p2_max_hp} {p2_hp_bar}\nAP: ⚡x{self.p2_ap}", inline=True)
        
        log_display = "\n".join(self.battle_log.split("\n")[-6:]) 
        embed.add_field(name="📜 전투 로그", value=f"```\n{log_display}\n```", inline=False)
        return embed

    async def execute_turn(self, interaction: discord.Interaction, action: str):
        if interaction.user != self.current_turn_user:
            return await interaction.response.send_message("❌ 당신의 턴이 아닙니다! 기다리세요.", ephemeral=True)

        is_p1 = (interaction.user == self.p1)
        attacker_name = self.p1.name if is_p1 else self.p2.name
        
        if action == "attack":
            if is_p1: self.p1_defending = False
            else: self.p2_defending = False

            attacker_elem = self.p1_elem if is_p1 else self.p2_elem
            defender_elem = self.p2_elem if is_p1 else self.p1_elem
            mult = get_element_multiplier(attacker_elem, defender_elem)
            
            attacker_atk = self.p1_atk if is_p1 else self.p2_atk
            attacker_ap = self.p1_ap if is_p1 else self.p2_ap
            defender_defending = self.p2_defending if is_p1 else self.p1_defending
            
            dmg = int(attacker_atk * attacker_ap * mult)
            if defender_defending: dmg //= 2
            
            attacker_fish = self.p1_fish if is_p1 else self.p2_fish
            defender_fish = self.p2_fish if is_p1 else self.p1_fish
            
            # 특수 스킬 적용
            skill_msg = ""
            if attacker_fish == "리비아탄 멜빌레이 🐋" and "상어" in defender_fish:
                dmg *= 2
                skill_msg = "\n🐋 **[태고의 격돌]** 상어의 천적! 대미지가 2배로 증폭되었습니다!"
            if attacker_fish == "헬리코프리온 🦈":
                if is_p1: self.p2_atk = max(1, int(self.p2_atk * 0.9))
                else: self.p1_atk = max(1, int(self.p1_atk * 0.9))
                skill_msg = "\n🦈 **[회전 톱날]** 상대의 턱을 부숴 공격력을 10% 영구 감소시킵니다!"
            if attacker_fish == "죽음의 선율, 세이렌의 군주 🧜‍♀️" and random.random() < 0.3:
                if is_p1: self.p2_ap = max(0, self.p2_ap - 1)
                else: self.p1_ap = max(0, self.p1_ap - 1)
                skill_msg = "\n🎵 **[매혹]** 노래에 홀린 상대의 행동력(AP)이 1 깎였습니다!"

            if is_p1:
                self.p2_hp -= dmg
                self.p1_ap = 1
            else:
                self.p1_hp -= dmg
                self.p2_ap = 1

            elem_txt = "(효과 발군!)" if mult > 1.0 else ("(효과 미미...)" if mult < 1.0 else "")
            self.battle_log += f"[{attacker_name}] {attacker_fish}의 공격! 💥 {dmg} 피해! {elem_txt}{skill_msg}\n"

        else: 
            if is_p1:
                self.p1_defending = True
                self.p1_ap += 1
            else:
                self.p2_defending = True
                self.p2_ap += 1
            self.battle_log += f"[{attacker_name}] 방어 태세! 피해 반감 & AP 1 회복.\n"

        if self.p1_hp <= 0:
            self.battle_log += f"💀 {self.p1.name}님의 {self.p1_fish}(이)가 쓰러졌습니다!\n"
            self.p1_idx += 1
            if self.p1_idx < len(self.p1_deck):
                self._init_fish(1)
                self.battle_log += f"🟢 {self.p1.name}님이 다음 전사로 {self.p1_fish}(을)를 꺼냈습니다!\n"
        
        if self.p2_hp <= 0:
            self.battle_log += f"💀 {self.p2.name}님의 {self.p2_fish}(이)가 쓰러졌습니다!\n"
            self.p2_idx += 1
            if self.p2_idx < len(self.p2_deck):
                self._init_fish(2)
                self.battle_log += f"🟢 {self.p2.name}님이 다음 전사로 {self.p2_fish}(을)를 꺼냈습니다!\n"

        if self.p1_idx >= len(self.p1_deck) or self.p2_idx >= len(self.p2_deck):
            winner = self.p1 if self.p2_idx >= len(self.p2_deck) else self.p2
            loser = self.p2 if self.p2_idx >= len(self.p2_deck) else self.p1
            return await self.end_battle(interaction, winner, loser)

        self.current_turn_user = self.p2 if is_p1 else self.p1
        self.turn_count += 1
        await interaction.response.edit_message(embed=self.generate_embed(), view=self)

    async def end_battle(self, interaction, winner, loser):
        self.stop() 
        embed = self.generate_embed()
        
        reward_rp = random.randint(15, 30)
        reward_coin = random.randint(500, 2000) 
        
        await db.execute("UPDATE user_data SET rating = rating + ?, coins = coins + ? WHERE user_id = ?", (reward_rp, reward_coin, winner.id))
        await db.execute("UPDATE user_data SET rating = MAX(0, rating - ?), coins = MAX(0, coins - ?) WHERE user_id = ?", (reward_rp, int(reward_coin * 0.5), loser.id))
        await db.commit()

        embed.description = f"🏆 **{winner.mention}님의 승리!!**\n\n**승자({winner.name}):** `+{reward_rp} RP`, `+{reward_coin} C`\n**패자({loser.name}):** `-{reward_rp} RP`, `-{int(reward_coin * 0.5)} C` (약탈당함!)"
        embed.color = 0x00ff00

        await interaction.response.edit_message(embed=embed, view=None)

    @discord.ui.button(label="공격 (AP소모)", style=discord.ButtonStyle.danger, emoji="⚔️")
    async def btn_attack(self, interaction: discord.Interaction, button: Button):
        await self.execute_turn(interaction, "attack")

    @discord.ui.button(label="방어/기모으기 (AP+1)", style=discord.ButtonStyle.primary, emoji="🛡️")
    async def btn_defend(self, interaction: discord.Interaction, button: Button):
        await self.execute_turn(interaction, "defend")

class MarketPaginationView(View):
    def __init__(self, items, per_page=10):
        super().__init__(timeout=120)
        self.items = list(items.items())
        self.per_page = per_page
        self.current_page = 0

    def make_embed(self):
        start = self.current_page * self.per_page
        end = start + self.per_page
        current_items = self.items[start:end]
        
        embed = discord.Embed(title="📊 현재 수산시장 시세표", description=f"총 {len(self.items)}종의 물고기 시세입니다.", color=0xf1c40f)
        for fish, current_price in current_items:
            base = FISH_DATA[fish]["price"]
            ratio = current_price / base
            status = "📈 떡상" if ratio > 1.2 else ("📉 떡락" if ratio < 0.8 else "➖ 평범")
            embed.add_field(name=fish, value=f"현재가: **{current_price} C**\n({status})", inline=True)
        
        embed.set_footer(text=f"페이지: {self.current_page + 1} / {int((len(self.items)-1)/self.per_page) + 1}")
        return embed

    @discord.ui.button(label="◀ 이전", style=discord.ButtonStyle.secondary)
    async def prev_btn(self, interaction: discord.Interaction, button: Button):
        if self.current_page > 0:
            self.current_page -= 1
            await interaction.response.edit_message(embed=self.make_embed(), view=self)
        else:
            await interaction.response.defer()

    @discord.ui.button(label="다음 ▶", style=discord.ButtonStyle.secondary)
    async def next_btn(self, interaction: discord.Interaction, button: Button):
        if (self.current_page + 1) * self.per_page < len(self.items):
            self.current_page += 1
            await interaction.response.edit_message(embed=self.make_embed(), view=self)
        else:
            await interaction.response.defer()

class DragonKingBlessingView(View):
    def __init__(self):
        super().__init__(timeout=300)
        self.claimed_users = set()

    @discord.ui.button(label="고개 조아리기", style=discord.ButtonStyle.success, emoji="🙇")
    async def bow_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await db.get_user_data(interaction.user.id)
        
        if interaction.user.id in self.claimed_users:
            return await interaction.response.send_message("👑 용왕님: \"이미 축복을 내렸느니라. 과한 욕심은 화를 부르는 법이지.\"", ephemeral=True)

        self.claimed_users.add(interaction.user.id)
        rand_val = random.randint(1, 1000)

        if rand_val == 1: 
            bonus_coin = 500000
            msg = "👑 **[전설적인 축복]** 용왕이 당신을 보며 파안대소합니다!\n"
            msg += f"💰 `{bonus_coin:,} C`를 하사받았습니다!\n\n"
            msg += "*\"허허, 마음에 쏙 드는구나! 혹시... 육지에 두고 왔다는 그 간도 나에게 줄 수 있겠느냐?\"*"
        elif rand_val <= 30: 
            bonus_coin = random.randint(100000, 499999)
            msg = f"✨ **[특별한 시선]** 용왕이 당신을 눈여겨봅니다...\n💰 `{bonus_coin:,} C`를 하사받았습니다!"
        elif rand_val <= 200: 
            bonus_coin = random.randint(10000, 99999)
            msg = f"🌊 용왕이 당신을 더욱 축복합니다.\n💰 `{bonus_coin:,} C`를 하사받았습니다."
        else: 
            bonus_coin = random.randint(500, 9999)
            msg = f"🐢 용왕의 소소한 축복이 닿았습니다.\n💰 `{bonus_coin:,} C`를 획득했습니다."

        await db.execute("UPDATE user_data SET coins = coins + ? WHERE user_id = ?", (bonus_coin, interaction.user.id))
        await db.commit()
        await interaction.response.send_message(msg, ephemeral=True)

class QuestDeliveryView(View):
    def __init__(self, user, item, amount, reward):
        super().__init__(timeout=60)
        self.user = user
        self.item = item
        self.amount = amount
        self.reward = reward

    @discord.ui.button(label="📦 의뢰 납품하기", style=discord.ButtonStyle.success)
    async def deliver_btn(self, interaction: discord.Interaction, button: Button):
        if interaction.user != self.user: return

        async with db.conn.execute("SELECT amount FROM inventory WHERE user_id=? AND item_name=?", (self.user.id, self.item)) as cursor:
            res = await cursor.fetchone()

        current_amount = res[0] if res else 0

        if current_amount < self.amount:
            return await interaction.response.send_message(f"❌ 가방에 물고기가 부족합니다! (현재: {current_amount} / 필요: {self.amount})", ephemeral=True)

        await db.execute("UPDATE inventory SET amount = amount - ? WHERE user_id=? AND item_name=?", (self.amount, self.user.id, self.item))
        await db.execute("UPDATE user_data SET coins = coins + ?, quest_is_cleared = 1 WHERE user_id=?", (self.reward, self.user.id))
        await db.commit()

        embed = discord.Embed(title="🎉 의뢰 완료!", description=f"항구 촌장님께 **{self.item}** {self.amount}마리를 납품했습니다!\n보상으로 두둑한 `{self.reward:,} C`를 받았습니다!", color=0xf1c40f)
        await interaction.response.edit_message(embed=embed, view=None)

