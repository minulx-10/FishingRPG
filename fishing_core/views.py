import datetime
import random

import discord
from discord.ui import Button, View

from .database import db
from .shared import (
    FISH_DATA,
    MARKET_PRICES,
    format_grade_label,
    get_element_multiplier,
    get_grade_color,
    get_grade_order,
)


class FishActionView(View):
    def __init__(self, user, target_fish):
        super().__init__(timeout=60)
        self.user = user
        self.target_fish = target_fish
        self.action_taken = False
        self.message = None

    async def _add_to_inventory(self, lock=None):
        if self.action_taken: return None

        # 인벤토리 용량 체크
        async with db.conn.execute("SELECT boat_tier FROM user_data WHERE user_id=?", (self.user.id,)) as cursor:
            res = await cursor.fetchone()
        tier = res[0] if res else 1

        capacity_map = {1: 30, 2: 50, 3: 80, 4: 120, 5: 200, 6: 9999}
        max_species = capacity_map.get(tier, 30)

        async with db.conn.execute("SELECT COUNT(*) FROM inventory WHERE user_id=?", (self.user.id,)) as cursor:
            current_species = (await cursor.fetchone())[0]

        async with db.conn.execute("SELECT amount FROM inventory WHERE user_id=? AND item_name=?", (self.user.id, self.target_fish)) as cursor:
            has_fish = await cursor.fetchone()

        if not has_fish and current_species >= max_species:
            return "capacity_full"

        self.action_taken = True
        fish_grade = FISH_DATA.get(self.target_fish, {}).get("grade", "일반")

        if lock is None:
            # 에픽 등급 이상은 자동 잠금 처리
            is_high_grade = get_grade_order(fish_grade) >= get_grade_order("에픽")
            lock_val = 1 if is_high_grade else 0
        else:
            lock_val = 1 if lock else 0

        await db.execute("INSERT INTO inventory (user_id, item_name, amount, is_locked) VALUES (?, ?, 1, ?) ON CONFLICT(user_id, item_name) DO UPDATE SET amount = amount + 1, is_locked = MAX(is_locked, ?)", (self.user.id, self.target_fish, lock_val, lock_val))
        await db.commit()

        lock_msg = " (🔒 자동 잠금됨)" if lock_val else ""
        return f"**{self.target_fish}**를 가방에 안전하게 넣었습니다!{lock_msg}"

    async def on_timeout(self):
        if self.action_taken: return

        result = await self._add_to_inventory()
        if self.message:
            try:
                if result == "capacity_full":
                    await self.message.edit(content=f"⏰ 시간 초과! 가방이 가득 차서 **{self.target_fish}**를 놓쳐버렸습니다...", view=None)
                elif result:
                    await self.message.edit(content=f"⏰ 시간 초과로 **{self.target_fish}**가 자동으로 가방에 보관되었습니다.", view=None)
            except Exception:
                pass

    @discord.ui.button(label="가방에 보관 (판매용)", style=discord.ButtonStyle.primary, emoji="🎒")
    async def btn_inv(self, interaction: discord.Interaction, button: Button):
        if interaction.user != self.user: return None

        result = await self._add_to_inventory()
        if result == "capacity_full":
            return await interaction.response.send_message("🚫 가방이 가득 찼습니다! 어종 수를 줄이거나 선박을 개조하세요.", ephemeral=True)
        if result:
            await interaction.response.edit_message(content=f"🎒 {result}", view=None)

    @discord.ui.button(label="잠금 보관 (배틀용)", style=discord.ButtonStyle.success, emoji="🔒")
    async def btn_bucket(self, interaction: discord.Interaction, button: Button):
        if interaction.user != self.user: return None

        result = await self._add_to_inventory(lock=True)
        if result == "capacity_full":
            return await interaction.response.send_message("🚫 가방이 가득 찼습니다! 어종 수를 줄이거나 선박을 개조하세요.", ephemeral=True)
        if result:
            await interaction.response.edit_message(content=f"🔒 {result}", view=None)

    @discord.ui.button(label="바로 판매", style=discord.ButtonStyle.danger, emoji="💰")
    async def btn_sell(self, interaction: discord.Interaction, button: Button):
        if interaction.user != self.user or self.action_taken: return None
        self.action_taken = True

        fish_grade = FISH_DATA.get(self.target_fish, {}).get("grade", "일반")

        if get_grade_order(fish_grade) >= get_grade_order("에픽"):
            return await interaction.response.send_message(f"⚠️ **{fish_grade}** 등급 이상의 물고기는 '바로 판매'가 불가능합니다. 실수 방지를 위해 가방에 보관 후 개별 판매하거나 잠금을 해제하세요.", ephemeral=True)

        price = MARKET_PRICES.get(self.target_fish, FISH_DATA.get(self.target_fish, {}).get("price", 100))
        await db.execute("UPDATE user_data SET coins = coins + ? WHERE user_id = ?", (price, self.user.id))
        await db.commit()
        await interaction.response.edit_message(content=f"💰 **{self.target_fish}**를 시장에 바로 넘겨서 `{price} C`를 벌었습니다!", view=None)


class FishingView(View):
    def __init__(self, user, target_fish, rod_tier):
        super().__init__(timeout=30)
        self.user = user
        self.target_fish = target_fish
        self.rod_tier = rod_tier
        self.is_bite = False
        self.start_time = 0
        self.message = None
        self.resolved = False

        fish_info = FISH_DATA.get(self.target_fish, {"base_window": 2.0, "grade": "일반"})
        base_window = fish_info["base_window"]
        bonus_time = (self.rod_tier - 1) * 0.2
        self.limit_time = max(1.0, base_window + bonus_time)

    def _target_label(self) -> str:
        grade = FISH_DATA.get(self.target_fish, {}).get("grade", "일반")
        return f"**{self.target_fish}** `{format_grade_label(grade)}`"

    def _escaped_message(self, reason: str, detail: str = "") -> str:
        msg = f"{reason}\n놓친 대상: {self._target_label()}"
        if detail:
            msg += f"\n{detail}"
        return msg

    async def on_timeout(self):
        if self.resolved:
            return

        self.resolved = True
        for child in self.children:
            child.disabled = True

        if self.message:
            try:
                await self.message.edit(content="⏰ 입질이 오기 전에 낚싯대를 거두었습니다.\n이번엔 아무것도 걸리지 않았습니다.", view=self)
            except Exception:
                pass

    @discord.ui.button(label="대기 중...", style=discord.ButtonStyle.secondary, emoji="🎣", custom_id="fish_btn")
    async def fish_button(self, interaction: discord.Interaction, button: Button):
        if interaction.user != self.user:
            return await interaction.response.send_message("남의 낚싯대입니다! 🚫", ephemeral=True)

        if self.resolved:
            return await interaction.response.send_message("이미 낚시 결과가 정리되었습니다. 새로 `/낚시`를 시도해주세요.", ephemeral=True)

        self.stop()

        if not self.is_bite:
            self.resolved = True
            return await interaction.response.edit_message(
                content="🎣 앗, 너무 일찍 챘습니다!\n아직 입질이 오지 않아 찌 아래의 그림자만 흩어졌습니다. 💨",
                view=None,
            )

        # 입질 시 임베드 색상 변경 (심미성 개선)
        embed = discord.Embed(title="❗ 챔질 성공!", color=0xffd700) # 황금색
        embed.description = "물고기가 바늘에 걸렸습니다! 힘껏 당기는 중..."

        try:
            elapsed = datetime.datetime.now().timestamp() - self.start_time
            fish_info = FISH_DATA.get(self.target_fish, {"grade": "보물"})
            grade = fish_info["grade"]

            if elapsed <= self.limit_time:
                if grade in ["대형 포식자", "레전드", "신화", "태고", "환상", "미스터리"]:
                    tension_view = TensionFishingView(self.user, self.target_fish, self.rod_tier, grade, self, elapsed)
                    await interaction.response.edit_message(content="❗ 거대한 물고기가 걸렸습니다! 힘겨루기 시작!", embed=tension_view.get_embed(), view=tension_view)
                else:
                    await self.on_bite_success(interaction, elapsed, grade)
            else:
                self.resolved = True
                fail_msg = self._escaped_message(
                    f"⏰ 챔질이 너무 늦었습니다! (`{elapsed:.3f}초` / 제한 `{self.limit_time:.2f}초`)",
                    "물고기가 바늘 끝을 스치고 깊은 곳으로 사라졌습니다.",
                )
                if grade in ["레전드", "신화", "태고", "환상", "미스터리"] and self.rod_tier > 1 and random.random() < 0.5:
                    await db.execute("UPDATE user_data SET rod_tier = rod_tier - 1 WHERE user_id = ?", (self.user.id,))
                    fail_msg += "\n\n💥 **[치명적 손상]** 괴수의 힘을 이기지 못하고 **낚싯대가 부러졌습니다!** (낚싯대 레벨 1 하락)"

                if self.target_fish == "둔클레오스테우스 🦖":
                    async with db.conn.execute("SELECT item_name FROM inventory WHERE user_id=? AND amount > 0 AND is_locked=0", (self.user.id,)) as cursor:
                        items = await cursor.fetchall()
                    if items:
                        most_exp = max(items, key=lambda x: FISH_DATA.get(x[0], {}).get("price", 0))[0]
                        await db.execute("UPDATE inventory SET amount = amount - 1 WHERE user_id=? AND item_name=?", (self.user.id, most_exp))
                        fail_msg += f"\n\n🦖 **[강철의 턱]** 둔클레오스테우스가 도망치며 당신의 가방을 찢어 가장 비싼 물고기(**{most_exp}**)를 먹어치웠습니다!"

                await db.commit()
                await interaction.response.edit_message(content=fail_msg, view=None)
        except Exception:
            import traceback
            tb = traceback.format_exc()
            try:
                await interaction.response.edit_message(content=f"❌ 낚시 처리 중 오류:\n```py\n{tb[:1800]}\n```", view=None)
            except Exception:
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

            self.resolved = True

            embed = discord.Embed(
                title=f"🎉 낚시 성공! [{format_grade_label(grade)}]",
                description=f"**{self.target_fish}**를 낚았습니다!",
                color=get_grade_color(grade),
            )

            # 에픽 이상 화려한 이미지 연출 (예시 이미지 사용)
            if grade in ["레전드", "신화", "태고", "환상", "미스터리"] and "크라켄" in self.target_fish:
                embed.set_thumbnail(url="https://media.giphy.com/media/v1.Y2lkPTc5MGI3NjExNHJqZ3R4Z3R4Z3R4Z3R4Z3R4Z3R4Z3R4Z3R4Z3R4Z3R4Z3R4Z3R4JmVwPXYxX2ludGVybmFsX2dpZl9ieV9pZCZjdD1n/l41lTfuxV5RWRsBPO/giphy.gif")

            record_mark = " 🆕 **[최대 크기 신기록!]**" if is_new_record else ""
            embed.add_field(name="측정 크기", value=f"`{fish_size} cm`{record_mark}", inline=True)
            embed.add_field(name="반응 속도", value=f"`{elapsed:.3f}초` (한도: {self.limit_time:.2f}s)", inline=True)

            if random.random() < 0.05:
                piece = random.choice(["찢어진 지도 조각 A 🧩", "찢어진 지도 조각 B 🧩", "찢어진 지도 조각 C 🧩", "찢어진 지도 조각 D 🧩"])
                await db.execute("INSERT INTO inventory (user_id, item_name, amount) VALUES (?, ?, 1) ON CONFLICT(user_id, item_name) DO UPDATE SET amount = amount + 1", (self.user.id, piece))
                await db.commit()
                embed.add_field(name="🗺️ 바다의 파편 발견!", value=f"물고기와 함께 **{piece}**가 딸려왔습니다!", inline=False)

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
            
            # 더블 캐치 처리
            double_msg = ""
            if getattr(self, "double_catch", False):
                await action_view._add_to_inventory() # 추가로 한 마리 더 넣음
                double_msg = " (👯 **더블 캐치!** 요리 효과로 한 마리 더 낚았습니다!)"
            
            await interaction.response.edit_message(content=f"🎊 앗, 낚았습니다!{double_msg} 이 물고기를 어떻게 할까요?", embed=embed, view=action_view)
            action_view.message = await interaction.original_response()
        except Exception:
            import traceback
            tb = traceback.format_exc()
            try:
                await interaction.response.edit_message(content=f"❌ 낚시 결과 처리 중 오류:\n```py\n{tb[:1800]}\n```", view=None)
            except Exception:
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

        # 텐션 바 디자인 고도화 (그라데이션)
        # 0-20(빨강), 20-30(노랑), 30-70(초록), 70-80(노랑), 80-100(빨강)
        bar_count = 10
        filled_segments = int(self.tension / 10)

        bar_str = ""
        for i in range(1, bar_count + 1):
            if i <= filled_segments:
                if i <= 2 or i >= 9: bar_str += "🟥"
                elif i in {3, 8}: bar_str += "🟨"
                else: bar_str += "🟩"
            else:
                bar_str += "⬛"

        status_emoji = "🟢" if 20 <= self.tension <= 80 else "🔴"
        status_text = "안전" if 20 <= self.tension <= 80 else "위험!"

        embed.add_field(name=f"현재 텐션: {self.tension}%", value=f"{bar_str} ({status_emoji} {status_text})", inline=False)
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
                msg = self.parent_view._escaped_message(
                    "💥 줄이 버티지 못하고 끊어졌습니다! (텐션 100% 초과)",
                    "괴수가 마지막으로 몸부림치며 수면 아래로 사라졌습니다.",
                )
                if self.grade in ["레전드", "신화", "태고", "환상", "미스터리"] and self.rod_tier > 1 and random.random() < 0.5:
                    await db.execute("UPDATE user_data SET rod_tier = rod_tier - 1 WHERE user_id = ?", (self.user.id,))
                    msg += "\n\n💥 **[치명적 손상]** 괴수의 힘을 이기지 못하고 **낚싯대가 부러졌습니다!** (레벨 1 하락)"
            else:
                msg = self.parent_view._escaped_message(
                    "💨 텐션이 너무 풀려 바늘이 빠졌습니다! (텐션 0% 미만)",
                    "간신히 걸렸던 물고기가 몸을 비틀어 달아났습니다.",
                )

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
                return await interaction.response.edit_message(
                    content=self.parent_view._escaped_message(
                        "💨 마지막 힘겨루기에서 균형이 무너졌습니다!",
                        "거대한 그림자가 수면 아래로 멀어져 갑니다.",
                    ),
                    embed=None,
                    view=None,
                )
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

        # 최신 로그 강조
        logs = self.battle_log.strip().split("\n")
        latest = f"**> {logs[-1]}**" if logs else ""
        history = "\n".join(logs[-4:-1]) if len(logs) > 1 else ""

        embed.add_field(name="📜 전투 로그", value=f"{history}\n{latest}", inline=False)
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

            # [신규] 특수 스킬 적용
            skill_msg = ""
            fish_grade = FISH_DATA.get(self.my_fish, {}).get("grade", "일반")
            if fish_grade in ["레전드", "신화", "태고", "환상", "미스터리"] and random.random() < 0.2:
                dmg *= 2
                skill_msg += "\n⚔️ **[연속 공격]** 데미지 2배!"
            if fish_grade in ["신화", "태고", "환상", "미스터리"]:
                heal = int(dmg * 0.2)
                self.my_hp = min(self.my_max_hp, self.my_hp + heal)
                skill_msg += f"\n🩸 **[흡혈]** {heal} HP 회복!"
            if fish_grade in ["태고", "환상", "미스터리"] and random.random() < 0.15:
                self.npc_ap = 0
                skill_msg += "\n💫 **[기절]** 상대 AP 제거!"

            self.battle_log += f"🔵 {self.my_fish}의 공격! 💥 {dmg} 피해! {elem_txt}{skill_msg}\n"
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

        self.p1_title = ""
        self.p2_title = ""
        self.bot = None
        self.is_offline_target = False

        # --- Phase 3 추가 사항 ---
        # 1. 속성 공명 (3마리 동일 속성 시 공격력 20% 증가)
        self.p1_resonance = False
        self.p2_resonance = False

        p1_elements = [FISH_DATA.get(f[0], {}).get("element", "무속성") for f in p1_deck]
        if len(set(p1_elements)) == 1 and p1_elements[0] != "무속성":
            self.p1_resonance = True
            self.battle_log += f"✨ **[속성 공명]** {p1.name}님의 전사들이 모두 [{p1_elements[0]}] 속성으로 결집하여 공격력이 20% 상승합니다!\n"

        p2_elements = [FISH_DATA.get(f[0], {}).get("element", "무속성") for f in p2_deck]
        if len(set(p2_elements)) == 1 and p2_elements[0] != "무속성":
            self.p2_resonance = True
            self.battle_log += f"✨ **[속성 공명]** {p2.name}님의 전사들이 모두 [{p2_elements[0]}] 속성으로 결집하여 공격력이 20% 상승합니다!\n"
        # -----------------------

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

        # 최신 로그 강조
        logs = self.battle_log.strip().split("\n")
        latest = f"**> {logs[-1]}**" if logs else ""
        history = "\n".join(logs[-4:-1]) if len(logs) > 1 else ""

        embed.add_field(name="📜 전투 로그", value=f"{history}\n{latest}", inline=False)
        return embed

    async def execute_turn(self, interaction: discord.Interaction, action: str):
        if interaction.user != self.current_turn_user:
            return await interaction.response.send_message("❌ 당신의 턴이 아닙니다! 기다리세요.", ephemeral=True)

        is_p1 = (interaction.user == self.p1)
        attacker_name = self.p1.name if is_p1 else self.p2.name

        # 첫 턴에 칭호 정보 로드 (비동기 생성자가 불가능하므로 첫 실행 시점에 로드)
        if not self.p1_title:
            self.p1_title = await db.get_user_title(self.p1.id)
            self.p2_title = await db.get_user_title(self.p2.id)

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

            # 속성 공명 보너스 (20%)
            if (is_p1 and self.p1_resonance) or (not is_p1 and self.p2_resonance):
                dmg = int(dmg * 1.2)

            # 칭호 보너스 (바다의 왕: PvP 공격력 10% 증가)
            attacker_title = self.p1_title if is_p1 else self.p2_title
            if attacker_title == "[바다의 왕]":
                dmg = int(dmg * 1.1)

            if defender_defending: dmg //= 2

            attacker_fish = self.p1_fish if is_p1 else self.p2_fish
            defender_fish = self.p2_fish if is_p1 else self.p1_fish

            # 특수 스킬 적용 (고도화)
            skill_msg = ""
            fish_grade = FISH_DATA.get(attacker_fish, {}).get("grade", "일반")

            # [연속 공격] 레전드 이상 20% 확률로 2회 공격
            if fish_grade in ["레전드", "신화", "태고", "환상", "미스터리"] and random.random() < 0.2:
                dmg *= 2
                skill_msg += f"\n⚔️ **[연속 공격]** {attacker_fish}(이)가 폭풍 같은 연타를 가합니다! (데미지 2배)"

            # [흡혈] 신화 이상 데미지의 20% 체력 회복
            if fish_grade in ["신화", "태고", "환상", "미스터리"]:
                heal = int(dmg * 0.2)
                if is_p1: self.p1_hp = min(self.p1_max_hp, self.p1_hp + heal)
                else: self.p2_hp = min(self.p2_max_hp, self.p2_hp + heal)
                skill_msg += f"\n🩸 **[흡혈]** 적의 생명력을 흡수하여 `{heal}` HP를 회복했습니다!"

            # [스턴] 태고 이상 15% 확률로 상대 AP 0으로 초기화
            if fish_grade in ["태고", "환상", "미스터리"] and random.random() < 0.15:
                if is_p1: self.p2_ap = 0
                else: self.p1_ap = 0
                skill_msg += "\n💫 **[기절]** 상대가 괴수의 위압감에 압도당해 행동력(AP)을 잃었습니다!"

            if attacker_fish == "리비아탄 멜빌레이 🐋" and "상어" in defender_fish:
                dmg *= 2
                skill_msg += "\n🐋 **[태고의 격돌]** 상어의 천적! 대미지가 2배로 증폭되었습니다!"
            if attacker_fish == "헬리코프리온 🦈":
                if is_p1: self.p2_atk = max(1, int(self.p2_atk * 0.9))
                else: self.p1_atk = max(1, int(self.p1_atk * 0.9))
                skill_msg += "\n🦈 **[회전 톱날]** 상대의 턱을 부숴 공격력을 10% 영구 감소시킵니다!"
            if attacker_fish == "죽음의 선율, 세이렌의 군주 🧜‍♀️" and random.random() < 0.3:
                if is_p1: self.p2_ap = max(0, self.p2_ap - 1)
                else: self.p1_ap = max(0, self.p1_ap - 1)
                skill_msg += "\n🎵 **[매혹]** 노래에 홀린 상대의 행동력(AP)이 1 깎였습니다!"

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

        # === Phase 3: 연속 공격 패널티 로직 ===
        async with db.conn.execute("SELECT pvp_last_target, pvp_consecutive_count FROM user_data WHERE user_id=?", (winner.id,)) as cursor:
            res = await cursor.fetchone()
        last_target, con_count = res if res else (0, 0)

        penalty_msg = ""
        reward_rp = random.randint(15, 30)
        reward_coin = random.randint(500, 2000)

        if last_target == loser.id:
            con_count += 1
            # 연속 공격 패널티 강화: 2회(50%), 3회(10%), 4회 이상(0%)
            if con_count == 2: reduction = 0.5
            elif con_count == 3: reduction = 0.1
            else: reduction = 0.0

            if con_count >= 2:
                reward_rp = max(1, int(reward_rp * reduction))
                reward_coin = max(100, int(reward_coin * reduction))
                penalty_msg = f"\n⚠️ **연속 공격 패널티!** ({con_count}회 연속) 보상이 {int((1-reduction)*100)}% 감소했습니다."
        else:
            con_count = 1

        # 오프라인 보호 (추가 감면)
        if self.is_offline_target:
            reward_coin = int(reward_coin * 0.4) # 60% 감소
            reward_rp = max(1, int(reward_rp * 0.5)) # 50% 감소
            penalty_msg += "\n🕊️ **오프라인 보호 발동!** 상대의 미접속 기간이 길어 약탈량이 크게 줄었습니다."

        await db.execute("UPDATE user_data SET pvp_last_target=?, pvp_consecutive_count=? WHERE user_id=?", (loser.id, con_count, winner.id))
        # === 패널티 로직 끝 ===

        await db.execute("UPDATE user_data SET rating = rating + ?, coins = coins + ? WHERE user_id = ?", (reward_rp, reward_coin, winner.id))
        await db.execute("UPDATE user_data SET rating = MAX(0, rating - ?), coins = MAX(0, coins - ?) WHERE user_id = ?", (reward_rp, int(reward_coin * 0.5), loser.id))
        await db.commit()

        embed.description = f"🏆 **{winner.mention}님의 승리!!**\n\n**승자({winner.name}):** `+{reward_rp} RP`, `+{reward_coin} C`{penalty_msg}\n**패자({loser.name}):** `-{reward_rp} RP`, `-{int(reward_coin * 0.5)} C` (약탈당함!)"
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
        self.all_items = list(items.items())
        self.filtered_items = self.all_items
        self.per_page = per_page
        self.current_page = 0
        self.grade_filter = "전체"

    def make_embed(self):
        start = self.current_page * self.per_page
        end = start + self.per_page
        current_items = self.filtered_items[start:end]

        embed = discord.Embed(title=f"📊 수산시장 시세표 ({self.grade_filter})", description=f"총 {len(self.filtered_items)}종의 물고기 시세입니다.", color=0xf1c40f)
        for fish, current_price in current_items:
            base = FISH_DATA.get(fish, {}).get("price", 100)
            ratio = current_price / base
            status = "📈 떡상" if ratio > 1.2 else ("📉 떡락" if ratio < 0.8 else "➖ 평범")
            grade = FISH_DATA.get(fish, {}).get("grade", "일반")
            embed.add_field(name=f"{fish} [{format_grade_label(grade)}]", value=f"현재가: **{current_price} C**\n({status})", inline=True)

        max_page = max(1, (len(self.filtered_items)-1)//self.per_page + 1)
        embed.set_footer(text=f"페이지: {self.current_page + 1} / {max_page}")
        return embed

    @discord.ui.select(placeholder="등급별 필터", options=[
        discord.SelectOption(label="전체 보기", value="전체"),
        discord.SelectOption(label="일반~초희귀", value="기본"),
        discord.SelectOption(label="에픽~레전드", value="고급"),
        discord.SelectOption(label="태고~신화", value="특수"),
    ])
    async def filter_grade(self, interaction: discord.Interaction, select: discord.ui.Select):
        self.grade_filter = select.values[0]
        self.current_page = 0

        if self.grade_filter == "전체":
            self.filtered_items = self.all_items
        elif self.grade_filter == "기본":
            self.filtered_items = [i for i in self.all_items if FISH_DATA.get(i[0], {}).get("grade") in ["일반", "희귀", "초희귀"]]
        elif self.grade_filter == "고급":
            self.filtered_items = [i for i in self.all_items if FISH_DATA.get(i[0], {}).get("grade") in ["에픽", "레전드"]]
        elif self.grade_filter == "특수":
            self.filtered_items = [i for i in self.all_items if FISH_DATA.get(i[0], {}).get("grade") in ["태고", "환상", "미스터리", "신화"]]

        await interaction.response.edit_message(embed=self.make_embed(), view=self)

    @discord.ui.button(label="◀ 이전", style=discord.ButtonStyle.secondary)
    async def prev_btn(self, interaction: discord.Interaction, button: Button):
        if self.current_page > 0:
            self.current_page -= 1
            await interaction.response.edit_message(embed=self.make_embed(), view=self)
        else:
            await interaction.response.defer()

    @discord.ui.button(label="다음 ▶", style=discord.ButtonStyle.secondary)
    async def next_btn(self, interaction: discord.Interaction, button: Button):
        if (self.current_page + 1) * self.per_page < len(self.filtered_items):
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
        if interaction.user != self.user: return None

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

class InventoryView(View):
    def __init__(self, user, target_user, items, stats):
        super().__init__(timeout=120)
        self.user = user
        self.target_user = target_user
        self.all_items = items # List of (name, amt, is_locked)
        self.stats = stats # (coins, rod_tier, rating, boat_str, stamina, max_stamina, title)
        self.current_page = 0
        self.per_page = 15
        self.category = "전체" # 전체, 물고기, 아이템, 잠금

        self.filtered_items = self.all_items

    def filter_items(self):
        if self.category == "전체":
            self.filtered_items = self.all_items
        elif self.category == "물고기":
            self.filtered_items = [i for i in self.all_items if i[0] in FISH_DATA]
        elif self.category == "아이템":
            self.filtered_items = [i for i in self.all_items if i[0] not in FISH_DATA]
        elif self.category == "잠금":
            self.filtered_items = [i for i in self.all_items if i[2] == 1] # is_locked

    def make_embed(self):
        coins, rod_tier, rating, boat_str, stamina, max_stamina, title = self.stats
        display_name = f"{title} {self.target_user.name}" if title else self.target_user.name

        embed = discord.Embed(title=f"🎒 {display_name}의 인벤토리 ({self.category})", color=0x3498db)
        embed.add_field(name="🏆 레이팅", value=f"`{rating} RP`", inline=True)
        embed.add_field(name="💰 보유 코인", value=f"`{coins:,} C`", inline=True)
        embed.add_field(name="⛵ 선박", value=f"**{boat_str}**", inline=True)

        start = self.current_page * self.per_page
        end = start + self.per_page
        page_items = self.filtered_items[start:end]

        if page_items:
            item_str = ""
            for name, amt, locked in page_items:
                lock_icon = "🔒" if locked else "📦"
                if name in FISH_DATA:
                    grade = FISH_DATA.get(name, {}).get("grade", "일반")
                    item_str += f"{lock_icon} **{name}** `{format_grade_label(grade)}`: {amt}개\n"
                else:
                    item_str += f"{lock_icon} **{name}**: {amt}개\n"
            embed.add_field(name=f"내역 ({len(self.filtered_items)}종)", value=item_str, inline=False)
        else:
            embed.add_field(name="내역", value="해당 카테고리에 아이템이 없습니다.", inline=False)

        max_page = max(1, (len(self.filtered_items) - 1) // self.per_page + 1)
        embed.set_footer(text=f"⚡ 체력: {stamina}/{max_stamina} | 페이지: {self.current_page + 1}/{max_page}")
        return embed

    @discord.ui.select(placeholder="카테고리 선택", options=[
        discord.SelectOption(label="전체 보기", value="전체", emoji="📁"),
        discord.SelectOption(label="물고기만", value="물고기", emoji="🐟"),
        discord.SelectOption(label="기타 아이템", value="아이템", emoji="🛠️"),
        discord.SelectOption(label="잠금 물품", value="잠금", emoji="🔒"),
    ])
    async def select_category(self, interaction: discord.Interaction, select: discord.ui.Select):
        if interaction.user != self.user: return
        self.category = select.values[0]
        self.current_page = 0
        self.filter_items()
        await interaction.response.edit_message(embed=self.make_embed(), view=self)

    @discord.ui.button(label="◀ 이전", style=discord.ButtonStyle.secondary)
    async def prev_page(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user != self.user: return
        if self.current_page > 0:
            self.current_page -= 1
            await interaction.response.edit_message(embed=self.make_embed(), view=self)
        else:
            await interaction.response.defer()

    @discord.ui.button(label="다음 ▶", style=discord.ButtonStyle.secondary)
    async def next_page(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user != self.user: return
        if (self.current_page + 1) * self.per_page < len(self.filtered_items):
            self.current_page += 1
            await interaction.response.edit_message(embed=self.make_embed(), view=self)
        else:
            await interaction.response.defer()

