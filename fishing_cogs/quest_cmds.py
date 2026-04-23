import asyncio
import datetime
import io
import os
import random

import aiohttp
import discord
from discord import app_commands
from discord.ext import commands
from PIL import Image, ImageDraw, ImageFont

try:
    from pilmoji import Pilmoji
except ImportError:
    pass

from fishing_core.database import db
from fishing_core.shared import FISH_DATA, RECIPES, kst
from fishing_core.utils import (
    aqua_autocomplete,
    check_boat_tier,
    inv_autocomplete,
    recipe_autocomplete,
)
from fishing_core.views import QuestDeliveryView


class QuestCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @app_commands.command(name="출석", description="하루에 한 번 출석체크하고 1000 코인을 받습니다!")
    async def 출석(self, interaction: discord.Interaction):
        await db.get_user_data(interaction.user.id)
        today = datetime.datetime.now(kst).strftime('%Y-%m-%d')

        async with db.conn.execute("SELECT last_daily FROM user_data WHERE user_id=?", (interaction.user.id,)) as cursor:
            last_daily = (await cursor.fetchone())[0]

        if last_daily == today:
            return await interaction.response.send_message("❌ 오늘은 이미 출석하셨습니다! 내일 다시 와주세요.", ephemeral=True)

        reward = 1000
        await db.execute("UPDATE user_data SET coins = coins + ?, stamina = max_stamina, last_daily = ? WHERE user_id = ?", (reward, today, interaction.user.id))
        await db.commit()

        await interaction.response.send_message(f"✅ 출석 완료! 보상으로 `{reward} C`를 받고 **행동력(체력)이 모두 회복**되었습니다! ⚡ (잔액 확인: `/인벤토리`)")

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

        embed = discord.Embed(title=f"📖 {display_name}님의 낚시 도감", color=0x9b59b6)
        if target.avatar:
            embed.set_thumbnail(url=target.avatar.url)

        embed.add_field(name="현재 수집률", value=f"**{collected_count} / {total_fish} 종** (`{percent:.1f}%`)", inline=False)
        embed.add_field(name="도감 등급", value=f"**{dex_rank}**", inline=False)

        if collected_names:
            recent_fish = "\n".join([f"• {name}" for name in collected_names[-5:]])
            embed.add_field(name="최근 발견한 어종", value=recent_fish, inline=False)

            async with db.conn.execute("SELECT item_name, max_size FROM fish_records WHERE user_id=? ORDER BY max_size DESC LIMIT 5", (target.id,)) as cursor:
                records = await cursor.fetchall()
            if records:
                record_str = "\n".join([f"🏆 **{name}** : `{size} cm`" for name, size in records])
                embed.add_field(name="월척 기록 (Top 5)", value=record_str, inline=False)
        else:
            embed.add_field(name="최근 발견한 어종", value="아직 발견한 물고기가 없습니다.", inline=False)

        await interaction.response.send_message(embed=embed)

    @app_commands.command(name="한강물", description="모든 측정소의 한강 수온을 확인합니다. (우회 접속)")
    async def 한강물(self, interaction: discord.Interaction):
        await interaction.response.defer()

        try:
            api_key = os.getenv('SEOUL_API_KEY', 'sample')
            proxy_url = "https://seoul-proxy.mingm7115.workers.dev"
            url = f"{proxy_url}/{api_key}/json/WPOSInformationTime/1/10/"

            timeout = aiohttp.ClientTimeout(total=15)

            async with aiohttp.ClientSession(timeout=timeout) as session:
                async with session.get(url) as response:
                    if response.status == 200:
                        data = await response.json()

                        if 'WPOSInformationTime' not in data:
                            return await interaction.followup.send("❌ 데이터를 불러올 수 없습니다. API 키를 확인해주세요.")

                        rows = data['WPOSInformationTime']['row']

                        latest_data = {}
                        for item in rows:
                            site = item['MSRSTN_NM']
                            if site not in latest_data:
                                latest_data[site] = item

                        embed = discord.Embed(title="🌊 한강 주요 지점 실시간 수온", color=0x00a8ff)

                        operational_sites = 0
                        for site, info in latest_data.items():
                            temp = info['WATT']
                            date = info['YMD']
                            hour = info['HR']

                            if temp == "점검중":
                                temp_text = "🛠️ 점검 중"
                            else:
                                temp_text = f"**{temp}°C**"
                                operational_sites += 1

                            embed.add_field(name=f"📍 {site}", value=temp_text, inline=True)

                        if operational_sites == 0:
                            embed.description = "⚠️ 현재 모든 측정소가 점검 중입니다."
                        else:
                            embed.description = f"현재 {operational_sites}개 측정소가 정상 작동 중입니다. 🎣"

                        first_date = rows[0]['YMD']
                        first_hour = rows[0]['HR']
                        embed.set_footer(text=f"측정 일시: {first_date[:4]}-{first_date[4:6]}-{first_date[6:8]} {first_hour}시 기준")

                        await interaction.followup.send(embed=embed)
                    else:
                        await interaction.followup.send(f"❌ 서버 응답 오류: {response.status}")

        except Exception as e:
            await interaction.followup.send(f"❌ 연결 실패: 프록시 서버 또는 네트워크를 확인해주세요. (`{e}`)")

    @app_commands.command(name="요리", description="잡은 물고기로 요리를 만들어 버프를 얻거나 비싸게 팝니다.")
    @app_commands.autocomplete(선택=recipe_autocomplete)
    @check_boat_tier(2)
    async def 요리(self, interaction: discord.Interaction, 선택: str):
        recipe = RECIPES.get(선택)
        if not recipe:
            return await interaction.response.send_message("❌ 존재하지 않는 레시피입니다.", ephemeral=True)

        for item, amt in recipe["ingredients"].items():
            async with db.conn.execute("SELECT amount FROM inventory WHERE user_id=? AND item_name=?", (interaction.user.id, item)) as cursor:
                res = await cursor.fetchone()
                if not res or res[0] < amt:
                    return await interaction.response.send_message(f"❌ 재료가 부족합니다! (필요: `{item}` {amt}마리)", ephemeral=True)

        for item, amt in recipe["ingredients"].items():
            await db.execute("UPDATE inventory SET amount = amount - ? WHERE user_id=? AND item_name=?", (amt, interaction.user.id, item))

        if recipe["buff_type"] == "sell_only":
            await db.execute("INSERT INTO inventory (user_id, item_name, amount) VALUES (?, ?, 1) ON CONFLICT(user_id, item_name) DO UPDATE SET amount = amount + 1", (interaction.user.id, 선택))
            msg = f"👨‍🍳 **{선택}** 완성! 가방에 보관되었습니다. 시장에 비싸게 파세요!"
        else:
            end_time = datetime.datetime.now(kst) + datetime.timedelta(minutes=recipe["duration"])
            end_time_str = end_time.strftime('%Y-%m-%d %H:%M:%S')

            if 선택 == "복어 지리탕 🍲" and random.random() < 0.1:
                async with db.conn.execute("SELECT coins FROM user_data WHERE user_id=?", (interaction.user.id,)) as cursor:
                    c_coins = (await cursor.fetchone())[0]

                if c_coins < 5000:
                    await db.execute("UPDATE user_data SET stamina = 0 WHERE user_id=?", (interaction.user.id,))
                    msg = "🤢 **독극물 중독!!** 복어 독에 쓰러졌습니다... 병원비조차 없어 바닥에 쓰러져 기절합니다! (체력 0 초기화)\n*버프는 적용되었습니다.*"
                else:
                    await db.execute("UPDATE user_data SET coins = coins - 5000 WHERE user_id=?", (interaction.user.id,))
                    msg = "🤢 **아야!** 복어 독에 당했습니다... 해독비로 `5,000C`를 썼지만, 버프는 적용되었습니다."
            else:
                msg = f"😋 **{선택}**을(를) 맛있게 먹었습니다!\n**효과:** {recipe['description']}"

            await db.execute("INSERT OR REPLACE INTO active_buffs (user_id, buff_type, end_time) VALUES (?, ?, ?)",
                             (interaction.user.id, recipe["buff_type"], end_time_str))

        await db.commit()
        await interaction.response.send_message(msg)

    @app_commands.command(name="의뢰", description="항구 게시판에서 오늘의 특별한 낚시 의뢰를 확인합니다.")
    @check_boat_tier(2)
    async def 의뢰(self, interaction: discord.Interaction):
        await db.get_user_data(interaction.user.id)
        today = datetime.datetime.now(kst).strftime('%Y-%m-%d')

        async with db.conn.execute("SELECT quest_date, quest_item, quest_amount, quest_reward, quest_is_cleared FROM user_data WHERE user_id=?", (interaction.user.id,)) as cursor:
            res = await cursor.fetchone()
            if not res:
                res = ('', '', 0, 0, 0)
            q_date, q_item, q_amount, q_reward, q_cleared = res

        if q_date != today:
            quest_pool = [fish for fish, data in FISH_DATA.items() if data["grade"] in ["일반", "희귀", "초희귀"]]
            q_item = random.choice(quest_pool)
            q_amount = random.randint(1, 3)
            q_reward = FISH_DATA[q_item]["price"] * q_amount * random.randint(3, 5)
            q_cleared = 0
            q_date = today

            await db.execute("UPDATE user_data SET quest_date=?, quest_item=?, quest_amount=?, quest_reward=?, quest_is_cleared=0 WHERE user_id=?",
                             (q_date, q_item, q_amount, q_reward, interaction.user.id))
            await db.commit()

        if q_cleared == 1:
            embed = discord.Embed(title="📜 오늘의 항구 의뢰", description="오늘의 의뢰는 이미 완료했습니다!\n마을이 평화롭네요. 내일 다시 와주세요.", color=0x95a5a6)
            return await interaction.response.send_message(embed=embed)

        embed = discord.Embed(title="📜 오늘의 항구 의뢰", description="마을 촌장님이 급하게 생선을 찾고 있습니다!", color=0xe67e22)
        embed.add_field(name="🎯 타겟 어종", value=f"**{q_item}**", inline=True)
        embed.add_field(name="🔢 필요 수량", value=f"`{q_amount}마리`", inline=True)
        embed.add_field(name="💰 납품 보상", value=f"`{q_reward:,} C`", inline=False)

        async with db.conn.execute("SELECT amount FROM inventory WHERE user_id=? AND item_name=?", (interaction.user.id, q_item)) as cursor:
            res = await cursor.fetchone()
        current = res[0] if res else 0

        embed.set_footer(text=f"내 가방에 보유한 수량: {current} / {q_amount}")

        view = QuestDeliveryView(interaction.user, q_item, q_amount, q_reward)
        await interaction.response.send_message(embed=embed, view=view)

    @app_commands.command(name="전시", description="가방에 있는 물고기를 수족관에 전시합니다. (슬롯 확장 가능)")
    @app_commands.autocomplete(물고기=inv_autocomplete)
    @check_boat_tier(3)
    async def 전시(self, interaction: discord.Interaction, 물고기: str):
        async with db.conn.execute("SELECT aquarium_slots FROM user_data WHERE user_id=?", (interaction.user.id,)) as cursor:
            res = await cursor.fetchone()
        max_slots = res[0] if res else 5

        async with db.conn.execute("SELECT COUNT(*) FROM aquarium WHERE user_id=?", (interaction.user.id,)) as cursor:
            count = (await cursor.fetchone())[0]

        if count >= max_slots:
            return await interaction.response.send_message(f"❌ 수족관이 꽉 찼습니다! (최대 {max_slots}마리). `/전시해제`를 하거나 `/수족관확장`을 이용하세요.", ephemeral=True)

        async with db.conn.execute("SELECT amount FROM inventory WHERE user_id=? AND item_name=?", (interaction.user.id, 물고기)) as cursor:
            res = await cursor.fetchone()
        if not res or res[0] <= 0:
            return await interaction.response.send_message(f"❌ 가방에 **{물고기}**가 없습니다!", ephemeral=True)

        await db.execute("UPDATE inventory SET amount = amount - 1 WHERE user_id=? AND item_name=?", (interaction.user.id, 물고기))
        await db.execute("INSERT INTO aquarium (user_id, item_name) VALUES (?, ?)", (interaction.user.id, 물고기))
        await db.commit()

        await interaction.response.send_message(f"✨ **{물고기}**을(를) 수족관에 멋지게 전시했습니다! (`/수족관`으로 확인해보세요!)")

    @app_commands.command(name="전시해제", description="수족관에 전시된 물고기를 다시 가방으로 되돌립니다.")
    @app_commands.autocomplete(물고기=aqua_autocomplete)
    async def 전시해제(self, interaction: discord.Interaction, 물고기: str):
        async with db.conn.execute("SELECT item_name FROM aquarium WHERE user_id=? AND item_name=?", (interaction.user.id, 물고기)) as cursor:
            res = await cursor.fetchone()
        if not res:
            return await interaction.response.send_message(f"❌ 수족관에 **{물고기}**가 없습니다!", ephemeral=True)

        await db.execute("DELETE FROM aquarium WHERE user_id=? AND item_name=?", (interaction.user.id, 물고기))
        await db.execute("INSERT INTO inventory (user_id, item_name, amount) VALUES (?, ?, 1) ON CONFLICT(user_id, item_name) DO UPDATE SET amount = amount + 1", (interaction.user.id, 물고기))
        await db.commit()

        await interaction.response.send_message(f"🎒 **{물고기}**을(를) 수족관에서 조심스럽게 꺼내 가방에 넣었습니다.")

    @app_commands.command(name="수족관", description="나 또는 다른 유저의 수족관을 구경합니다. (이미지로 렌더링)")
    async def 수족관(self, interaction: discord.Interaction, 유저: discord.Member = None):
        target = 유저 or interaction.user

        await interaction.response.defer() # 렌더링 시간 확보용

        async with db.conn.execute("SELECT item_name FROM aquarium WHERE user_id=?", (target.id,)) as cursor:
            items = await cursor.fetchall()

        title = await db.get_user_title(target.id)
        display_name = f"{title} {target.name}" if title else target.name

        embed = discord.Embed(title=f"🏛️ {display_name}님의 수족관", color=0x00ffff)
        if not items:
            embed.description = "수족관이 텅 비어있습니다... 휑~ 🌬️\n(`/전시` 명령어로 물고기를 전시해보세요!)"
            return await interaction.followup.send(embed=embed)

        try:
            # --- 1. 배경 및 조명 효과 (그라데이션 + 빛줄기) ---
            width, height = 800, 600
            img = Image.new("RGBA", (width, height), (10, 30, 60, 255))
            draw = ImageDraw.Draw(img)

            # 수직 그라데이션 (LightSeaGreen -> MidnightBlue)
            for y in range(height):
                r = int(32 + (25 - 32) * (y / height))
                g = int(178 + (25 - 178) * (y / height))
                b = int(170 + (112 - 170) * (y / height))
                draw.line([(0, y), (width, y)], fill=(r, g, b, 255))

            # 햇살 효과 (God Rays)
            for i in range(6):
                ray_x = random.randint(-100, width)
                ray_width = random.randint(40, 120)
                alpha = random.randint(10, 25) # 더 투명하게 조정
                points = [
                    (ray_x, 0),
                    (ray_x + ray_width, 0),
                    (ray_x + ray_width - 200, height),
                    (ray_x - 200, height),
                ]
                draw.polygon(points, fill=(255, 255, 255, alpha))

            # 장식용 물방울
            for _ in range(30):
                x, y = random.randint(0, 800), random.randint(0, 530)
                r = random.randint(2, 6)
                draw.ellipse([x-r, y-r, x+r, y+r], outline=(255, 255, 255, 80), width=1)

            # 바닥 모래 (텍스처 느낌을 위해 약간의 노이즈 추가)
            draw.rectangle([0, 530, 800, 600], fill=(194, 178, 128, 255))
            for _ in range(500):
                sx, sy = random.randint(0, 799), random.randint(530, 599)
                draw.point((sx, sy), fill=(160, 140, 100, 255))

            # --- 2. 물고기 배치 로직 (충돌 감지 랜덤) ---
            placed_coords = []
            min_dist = 110 # 물고기간 최소 거리

            fish_to_draw = []
            for (name,) in items:
                grade = FISH_DATA[name]["grade"]
                parts = name.split(" ")
                emoji = parts[-1] if len(parts) > 1 and len(parts[-1]) <= 2 else "🐟"

                # 좌표 찾기 (최대 100번 시도)
                found_spot = False
                for _ in range(100):
                    x = random.randint(80, 720)
                    y = random.randint(80, 480) # 모래 위쪽
                    if all(((x-px)**2 + (y-py)**2)**0.5 > min_dist for px, py in placed_coords):
                        placed_coords.append((x, y))
                        fish_to_draw.append({"name": name, "emoji": emoji, "grade": grade, "x": x, "y": y})
                        found_spot = True
                        break
                if not found_spot: # 공간 부족 시 겹치더라도 배치
                    x, y = random.randint(80, 720), random.randint(80, 480)
                    fish_to_draw.append({"name": name, "emoji": emoji, "grade": grade, "x": x, "y": y})

            # --- 3. 렌더링 ---
            try:
                # 윈도우/리눅스 폰트 경로 호환성
                font_paths = ["malgunbd.ttf", "/usr/share/fonts/truetype/noto/NotoSansCJK-Bold.ttc", "arial.ttf"]
                font = None
                for path in font_paths:
                    try:
                        font = ImageFont.truetype(path, 60)
                        break
                    except Exception:
                        continue
                if not font:
                    font = ImageFont.load_default()
            except Exception:
                font = ImageFont.load_default()

            grade_colors = {
                "일반": (200, 200, 200), "희귀": (100, 200, 255), "초희귀": (200, 100, 255),
                "에픽": (255, 100, 100), "레전드": (255, 200, 0), "신화": (255, 50, 50), "히든": (255, 255, 255),
            }

            with Pilmoji(img) as pilmoji:
                for fish in fish_to_draw:
                    cx, cy = fish["x"], fish["y"]
                    color = grade_colors.get(fish["grade"], (255, 255, 255))

                    # [에픽] 이상 또는 특정 등급만 발광 효과
                    if fish["grade"] in ["에픽", "레전드", "신화", "히든", "태고", "환상", "미스터리", "해신(海神)"]:
                        for r in range(60, 0, -10):
                            alpha = int(40 * (r / 60)) # 더 은은하게 조정
                            draw.ellipse([cx-r, cy-r, cx+r, cy+r], fill=(color[0], color[1], color[2], alpha))

                    # 물고기 이모지 렌더링
                    pilmoji.text((cx-35, cy-35), fish["emoji"], fill=(255, 255, 255), font=font)

            # 임베드 설명 구성 (이미지 내부 텍스트 대신 임베드로 이동)
            fish_list_str = ""
            for (name,) in items:
                grade = FISH_DATA[name]["grade"]
                fish_list_str += f"• **{name}** `[{grade}]` \n"

            embed.description = f"🌊 **수족관에 전시된 물고기들**\n\n{fish_list_str}"

            buf = io.BytesIO()
            img.save(buf, format='PNG')
            buf.seek(0)

            file = discord.File(buf, filename="aquarium.png")
            embed.set_image(url="attachment://aquarium.png")
            embed.set_footer(text=f"수족관 공간: {len(items)} / (확장 가능)")

            await interaction.followup.send(embed=embed, file=file)

        except Exception:
            # PIL 에러 등 예방
            desc = ""
            for (name,) in items:
                grade = FISH_DATA[name]["grade"]
                desc += f"**{name}** `[{grade}]`\n"
            embed.description = f"*(이미지 렌더링 오류 발생. 텍스트로 대체합니다)*\n\n{desc}"
            await interaction.followup.send(embed=embed)

    @app_commands.command(name="수족관확장", description="코인을 지불하여 수족관 전시 슬롯을 하나 추가합니다.")
    async def 수족관확장(self, interaction: discord.Interaction):
        coins, _, _ = await db.get_user_data(interaction.user.id)

        async with db.conn.execute("SELECT aquarium_slots FROM user_data WHERE user_id=?", (interaction.user.id,)) as cursor:
            res = await cursor.fetchone()
        current_slots = res[0] if res else 5

        if current_slots >= 20:
            return await interaction.response.send_message("❌ 수족관은 이미 최대 크기(20슬롯)로 확장되었습니다!", ephemeral=True)

        cost = 300000 * (current_slots - 4) # 5슬롯->6슬롯 갈때 30만, 그 이후 60만...

        if coins < cost:
            return await interaction.response.send_message(f"❌ 코인이 부족합니다. 다음 슬롯 확장에 `{cost:,} C`가 필요합니다.", ephemeral=True)

        await db.execute("UPDATE user_data SET coins = coins - ?, aquarium_slots = aquarium_slots + 1 WHERE user_id=?", (cost, interaction.user.id))
        await db.commit()

        await interaction.response.send_message(f"🏗️ `{cost:,} C`를 지불하여 수족관을 한 칸 확장했습니다! (현재 최대 슬롯: **{current_slots + 1}칸**)")

    @app_commands.command(name="칭호장착", description="자신의 업적에 맞는 칭호를 장착하여 닉네임 앞에 표시합니다.")
    @app_commands.choices(선택=[
        app_commands.Choice(name="해제 (칭호 없애기)", value=""),
        app_commands.Choice(name="🌱 초보 낚시꾼 (기본)", value="[초보]"),
        app_commands.Choice(name="🎣 베테랑 어부 (낚싯대 Lv.20+)", value="[베테랑]"),
        app_commands.Choice(name="👑 전설의 강태공 (낚싯대 Lv.50+)", value="[전설]"),
        app_commands.Choice(name="🐉 해신의 선택받은 자 (용왕 포획자)", value="[해신]"),
        app_commands.Choice(name="💰 수산시장 참치 (코인 500만+)", value="[만수르]"),
    ])
    async def 칭호장착(self, interaction: discord.Interaction, 선택: app_commands.Choice[str]):
        coins, rod_tier, rating = await db.get_user_data(interaction.user.id)
        title = 선택.value

        # 권한 체크
        if title == "[베테랑]" and rod_tier < 20:
            return await interaction.response.send_message("❌ 낚싯대를 20레벨 이상으로 강화해야 장착할 수 있습니다.", ephemeral=True)
        if title == "[전설]" and rod_tier < 50:
            return await interaction.response.send_message("❌ 낚싯대를 50레벨 이상으로 강화해야 장착할 수 있습니다.", ephemeral=True)
        if title == "[해신]":
            async with db.conn.execute("SELECT amount FROM inventory WHERE user_id=? AND item_name='용왕 👑'", (interaction.user.id,)) as cursor:
                res = await cursor.fetchone()
            if not res or res[0] <= 0:
                return await interaction.response.send_message("❌ '용왕 👑'을 낚아야만 얻을 수 있는 신성한 칭호입니다.", ephemeral=True)
        if title == "[만수르]" and coins < 5000000:
            return await interaction.response.send_message("❌ 5,000,000 코인 이상 보유한 진정한 부자만 장착할 수 있습니다.", ephemeral=True)

        await db.execute("UPDATE user_data SET title=? WHERE user_id=?", (title, interaction.user.id))
        await db.commit()

        display = title if title else "없음"
        await interaction.response.send_message(f"📛 칭호가 **{display}**(으)로 변경되었습니다! 이제 커맨드 사용 시 새로운 이름이 나타납니다.")

    @app_commands.command(name="감정", description="코인을 지불하고 '가라앉은 보물상자 🧰'를 열어 대박을 노립니다!")
    async def 감정(self, interaction: discord.Interaction):
        fee = 2000
        coins, _, _ = await db.get_user_data(interaction.user.id)

        async with db.conn.execute("SELECT amount FROM inventory WHERE user_id=? AND item_name='가라앉은 보물상자 🧰'", (interaction.user.id,)) as cursor:
            res = await cursor.fetchone()

        if not res or res[0] <= 0:
            return await interaction.response.send_message("❌ 가방에 '가라앉은 보물상자 🧰'가 없습니다. (상점에서 자석 미끼를 사서 낚아보세요!)", ephemeral=True)

        if coins < fee:
            return await interaction.response.send_message(f"❌ 감정 비용이 부족합니다. 열쇠공을 부르려면 `{fee} C`가 필요합니다.", ephemeral=True)

        await db.execute("UPDATE inventory SET amount = amount - 1 WHERE user_id=? AND item_name='가라앉은 보물상자 🧰'", (interaction.user.id,))
        await db.execute("UPDATE user_data SET coins = coins - ? WHERE user_id=?", (fee, interaction.user.id))
        await db.commit()

        await interaction.response.send_message("🧰 녹슨 상자의 자물쇠에 열쇠를 꽂고 강하게 비틀고 있습니다...")
        await asyncio.sleep(2.0)
        await interaction.edit_original_response(content="🧰 *덜컹...* 굳게 닫혀있던 자물쇠가 풀리며 먼지가 일어납니다!")
        await asyncio.sleep(1.5)

        rand = random.random()
        if rand < 0.4:
            reward_msg = "아뿔싸... 텅 빈 상자였습니다. 바닥에 굴러다니는 **낡은 고철 ⚙️** (5개)만 주웠습니다."
            await db.execute("INSERT INTO inventory (user_id, item_name, amount) VALUES (?, ?, 5) ON CONFLICT(user_id, item_name) DO UPDATE SET amount = amount + 5", (interaction.user.id, "낡은 고철 ⚙️"))

        elif rand < 0.75:
            reward_coin = random.randint(20000, 40000)
            reward_msg = f"✨ 번쩍이는 금은보화가 가득합니다! 귀금속을 팔아 **`{reward_coin:,} C`**를 얻었습니다."
            await db.execute("UPDATE user_data SET coins = coins + ? WHERE user_id=?", (reward_coin, interaction.user.id))

        elif rand < 0.98:
            reward_item = "해적의 금화 🪙"
            reward_amt = random.randint(15, 30)
            reward_msg = f"🎉 **잭팟!!** 고대 해적의 유물인 **{reward_item}** {reward_amt}개를 무더기로 발견했습니다!"
            await db.execute("INSERT INTO inventory (user_id, item_name, amount) VALUES (?, ?, ?) ON CONFLICT(user_id, item_name) DO UPDATE SET amount = amount + ?", (interaction.user.id, reward_item, reward_amt, reward_amt))

        else:
            reward_item = "💎 GSM 황금 키보드"
            reward_coin = 100000
            reward_msg = f"🚨 **[기적] 상자 밑바닥에서 엄청난 빛이 뿜어져 나옵니다!!!**\n**`{reward_coin:,} C`**와 함께 전설의 아이템 **{reward_item}**를 손에 넣었습니다!"
            await db.execute("UPDATE user_data SET coins = coins + ? WHERE user_id=?", (reward_coin, interaction.user.id))
            await db.execute("INSERT INTO inventory (user_id, item_name, amount) VALUES (?, ?, 1) ON CONFLICT(user_id, item_name) DO UPDATE SET amount = amount + 1", (interaction.user.id, reward_item))

        await db.commit()
        await interaction.edit_original_response(content=f"🧰 **녹슨 상자가 마침내 열렸습니다!**\n\n{reward_msg}")

    @app_commands.command(name="지도합성", description="찢어진 지도 조각(A,B,C,D) 4종을 모아 '고대 해적의 보물지도 🗺️'를 완성합니다. (수량 지정 가능)")
    async def 지도합성(self, interaction: discord.Interaction, 수량: int = 1):
        if 수량 < 1:
            return await interaction.response.send_message("❌ 최소 1개 이상 합성해야 합니다.", ephemeral=True)

        pieces = ["찢어진 지도 조각 A 🧩", "찢어진 지도 조각 B 🧩", "찢어진 지도 조각 C 🧩", "찢어진 지도 조각 D 🧩"]

        async with db.conn.execute("SELECT item_name, amount FROM inventory WHERE user_id=? AND amount > 0", (interaction.user.id,)) as cursor:
            inv_items = {row[0]: row[1] for row in await cursor.fetchall()}

        for p in pieces:
            if inv_items.get(p, 0) < 수량:
                return await interaction.response.send_message(f"❌ 조각이 부족합니다!\n(달성 불가: **{p}**가 {수량}개 필요하지만 {inv_items.get(p, 0)}개 있음)\n낚시를 통해 4부위를 모두 모아보세요.", ephemeral=True)

        for p in pieces:
            await db.execute("UPDATE inventory SET amount = amount - ? WHERE user_id=? AND item_name=?", (수량, interaction.user.id, p))

        await db.execute("INSERT INTO inventory (user_id, item_name, amount) VALUES (?, ?, ?) ON CONFLICT(user_id, item_name) DO UPDATE SET amount = amount + ?", (interaction.user.id, "고대 해적의 보물지도 🗺️", 수량, 수량))
        await db.commit()

        embed = discord.Embed(title=f"🗺️ 보물지도 {수량}장 합성 성공!", description=f"보유 중인 조각들을 이어 붙여 **고대 해적의 보물지도 🗺️** {수량}장을 대량으로 완성했습니다!\n`/지도사용` 명령어를 통해 망자의 해역으로 떠나보세요.", color=0xf1c40f)
        await interaction.response.send_message(embed=embed)

    @app_commands.command(name="지도사용", description="'고대 해적의 보물지도'를 사용하여 특별한 해역 버프(30분)를 개방합니다.")
    async def 지도사용(self, interaction: discord.Interaction):
        async with db.conn.execute("SELECT amount FROM inventory WHERE user_id=? AND item_name='고대 해적의 보물지도 🗺️'", (interaction.user.id,)) as cursor:
            res = await cursor.fetchone()

        if not res or res[0] < 1:
            return await interaction.response.send_message("❌ 가방에 **고대 해적의 보물지도 🗺️**가 없습니다!", ephemeral=True)

        await db.execute("UPDATE inventory SET amount = amount - 1 WHERE user_id=? AND item_name='고대 해적의 보물지도 🗺️'", (interaction.user.id,))

        end_time = datetime.datetime.now(kst) + datetime.timedelta(minutes=30)
        end_time_str = end_time.strftime('%Y-%m-%d %H:%M:%S')

        buffs = ["ghost_sea_open", "deep_sea_rift", "golden_tide"]
        weights = [30, 40, 30]
        chosen_buff = random.choices(buffs, weights=weights, k=1)[0]

        await db.execute("INSERT OR REPLACE INTO active_buffs (user_id, buff_type, end_time) VALUES (?, ?, ?)", (interaction.user.id, chosen_buff, end_time_str))
        await db.commit()

        if chosen_buff == "ghost_sea_open":
            embed = discord.Embed(title="☠️ 망자의 해역 개방...", description="지도의 낡은 좌표를 따라 안개가 자욱한 해역에 도착했습니다.\n\n앞으로 **30분 동안**, 당신의 낚싯대에는 물고기 대신 **해적의 금화 🪙, 낡은 고철 ⚙️, 가라앉은 보물상자 🧰**만 걸려 올라올 것입니다!", color=0x2c3e50)
        elif chosen_buff == "deep_sea_rift":
            embed = discord.Embed(title="🌊 심해의 균열 발견!", description="지도가 가리킨 곳에서 바다가 갈라진 깊은 심연이 보입니다.\n\n앞으로 **30분 동안**, **[심해] 속성** 어종들의 낚시 등장 확률이 3배 상승합니다!", color=0x1abc9c)
        else:
            embed = discord.Embed(title="✨ 황금 조류 발견!", description="지도를 따라가니 눈부시게 빛나는 따뜻한 해류를 만났습니다.\n\n앞으로 **30분 동안**, 낚시 타이밍 판정 시간이 매우 넉넉해져 물고기를 낚을 확률이 대폭 상승합니다!", color=0xf1c40f)

        await interaction.response.send_message(embed=embed)

    @app_commands.command(name="조각교환", description="같은 지도 조각 3개를 다른 무작위 조각 1개로 교환합니다.")
    @app_commands.choices(조각=[
        app_commands.Choice(name="찢어진 지도 조각 A 🧩", value="찢어진 지도 조각 A 🧩"),
        app_commands.Choice(name="찢어진 지도 조각 B 🧩", value="찢어진 지도 조각 B 🧩"),
        app_commands.Choice(name="찢어진 지도 조각 C 🧩", value="찢어진 지도 조각 C 🧩"),
        app_commands.Choice(name="찢어진 지도 조각 D 🧩", value="찢어진 지도 조각 D 🧩"),
    ])
    async def 조각교환(self, interaction: discord.Interaction, 조각: app_commands.Choice[str]):
        target_piece = 조각.value
        all_pieces = ["찢어진 지도 조각 A 🧩", "찢어진 지도 조각 B 🧩", "찢어진 지도 조각 C 🧩", "찢어진 지도 조각 D 🧩"]

        async with db.conn.execute("SELECT amount FROM inventory WHERE user_id=? AND item_name=?", (interaction.user.id, target_piece)) as cursor:
            res = await cursor.fetchone()

        current = res[0] if res else 0
        if current < 3:
            return await interaction.response.send_message(f"❌ **{target_piece}**가 3개 이상 필요합니다. (보유: {current}개)", ephemeral=True)

        reward_pieces = [p for p in all_pieces if p != target_piece]
        reward_piece = random.choice(reward_pieces)

        await db.execute("UPDATE inventory SET amount = amount - 3 WHERE user_id=? AND item_name=?", (interaction.user.id, target_piece))
        await db.execute("INSERT INTO inventory (user_id, item_name, amount) VALUES (?, ?, 1) ON CONFLICT(user_id, item_name) DO UPDATE SET amount = amount + 1", (interaction.user.id, reward_piece))
        await db.commit()

        await interaction.response.send_message(f"♻️ 교환 성공! 낡은 교환원이 **{target_piece}** 3개를 받고 **{reward_piece}** 1개를 주었습니다!")

    @app_commands.command(name="도감보상", description="수집한 어종 수에 따른 특별 보상을 수령합니다.")
    async def 도감보상(self, interaction: discord.Interaction):
        import json

        from fishing_core.shared import FISH_DATA

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

        embed = discord.Embed(title="📜 어종 도감 수집 보상", color=0x3498db)
        embed.description = f"현재 수집한 어종: **{dex_count} / {total_species}** 종\n\n"

        can_claim = False
        new_rewards = []

        for m in milestones:
            is_claimed = claimed.get(m["id"], False)
            if not is_claimed and dex_count >= m["count"]:
                # 보상 지급 대상
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

async def setup(bot):
    await bot.add_cog(QuestCog(bot))
