import asyncio
import os
import re

import discord
from discord import app_commands
from discord.ext import commands

from fishing_core.database import db
from fishing_core.logger import logger
from fishing_core.shared import FISH_DATA, MARKET_PRICES, reload_data_async
from fishing_core.utils import EmbedFactory, fish_autocomplete, is_developer, log_admin_action


class AdminCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @app_commands.command(name="코인지급", description="[관리자 전용] 특정 유저에게 코인을 강제로 지급합니다.")
    @is_developer()
    async def 코인지급(self, interaction: discord.Interaction, target: discord.Member, amount: int):
        async with db.transaction():
            await db.execute("UPDATE user_data SET coins = coins + ? WHERE user_id = ?", (amount, target.id))
        await log_admin_action(self.bot, interaction.user, target, "코인지급", f"수량: `{amount:,} C`")
        await interaction.response.send_message(f"💰 관리자 권한으로 **{target.name}**님에게 `{amount:,} C`를 지급했습니다!")

    @app_commands.command(name="아이템지급", description="[관리자 전용] 특정 유저에게 아이템을 강제 지급합니다.")
    @app_commands.autocomplete(아이템명=fish_autocomplete)
    @is_developer()
    async def 아이템지급(self, interaction: discord.Interaction, target: discord.Member, 아이템명: str, 수량: int):
        async with db.transaction():
            await db.execute("INSERT INTO inventory (user_id, item_name, amount) VALUES (?, ?, ?) ON CONFLICT(user_id, item_name) DO UPDATE SET amount = amount + ?", (target.id, 아이템명, 수량, 수량))
        await log_admin_action(self.bot, interaction.user, target, "아이템지급", f"아이템: `{아이템명}` / 수량: `{수량}`")
        await interaction.response.send_message(f"🎁 관리자 권한으로 **{target.name}**님에게 `{아이템명}` {수량}개를 지급했습니다!")

    @app_commands.command(name="아이템회수", description="[관리자 전용] 특정 유저의 아이템을 강제 회수(삭제)합니다.")
    @app_commands.autocomplete(아이템명=fish_autocomplete)
    @is_developer()
    async def 아이템회수(self, interaction: discord.Interaction, target: discord.Member, 아이템명: str, 수량: int):
        async with db.conn.execute("SELECT amount FROM inventory WHERE user_id = ? AND item_name = ?", (target.id, 아이템명)) as cursor:
            res = await cursor.fetchone()
        
        if not res or res[0] <= 0:
            return await interaction.response.send_message(f"❌ **{target.name}**님은 `{아이템명}`을(를) 소지하고 있지 않습니다.", ephemeral=True)

        async with db.transaction():
            await db.execute("UPDATE inventory SET amount = MAX(0, amount - ?) WHERE user_id = ? AND item_name = ?", (수량, target.id, 아이템명))
            await db.execute("DELETE FROM inventory WHERE amount <= 0")
        await log_admin_action(self.bot, interaction.user, target, "아이템회수", f"아이템: `{아이템명}` / 수량: `{수량}`")
        await interaction.response.send_message(f"🗑️ 관리자 권한으로 **{target.name}**님의 `{아이템명}` {수량}개를 강제 회수했습니다!")

    @app_commands.command(name="유저스탯변경", description="[관리자 전용] 특정 유저의 스탯(선박, 낚싯대, 레이팅)을 설정합니다.")
    @app_commands.choices(항목=[
        app_commands.Choice(name="선박 티어 (boat_tier)", value="boat_tier"),
        app_commands.Choice(name="낚싯대 레벨 (rod_tier)", value="rod_tier"),
        app_commands.Choice(name="전투 레이팅 (rating)", value="rating"),
    ])
    @is_developer()
    async def 유저스탯변경(self, interaction: discord.Interaction, target: discord.Member, 항목: app_commands.Choice[str], 값: int):
        async with db.transaction():
            if 항목.value == "boat_tier":
                await db.execute("UPDATE user_data SET boat_tier = ? WHERE user_id = ?", (값, target.id))
            elif 항목.value == "rod_tier":
                await db.execute("UPDATE user_data SET rod_tier = ? WHERE user_id = ?", (값, target.id))
            elif 항목.value == "rating":
                await db.execute("UPDATE user_data SET rating = ? WHERE user_id = ?", (값, target.id))
        await log_admin_action(self.bot, interaction.user, target, "유저스탯변경", f"항목: `{항목.name}` / 변경된 값: `{값}`")
        await interaction.response.send_message(f"⚙️ 관리자 권한으로 **{target.name}**님의 `{항목.name}`을(를) **{값}**(으)로 설정했습니다!")

    @app_commands.command(name="전체공지", description="[관리자 전용] 멋진 임베드로 전체 공지사항을 띄웁니다.")
    @is_developer()
    async def 전체공지(self, interaction: discord.Interaction, 제목: str, 내용: str):
        embed = EmbedFactory.build(title=f"📢 [시스템 공지] {제목}", description=내용.replace('\\n', '\n'), type="error")
        embed.set_footer(text="수산시장 관리국에서 발송된 메시지입니다.")
        await interaction.channel.send(content="@everyone", embed=embed)
        await interaction.response.send_message("공지 발송 완료!", ephemeral=True)

    @app_commands.command(name="시세조작", description="[관리자 전용] 특정 물고기의 현재 시세를 강제로 고정시킵니다.")
    @is_developer()
    async def 시세조작(self, interaction: discord.Interaction, 어종명: str, 가격: int):
        if 어종명 not in FISH_DATA:
            return await interaction.response.send_message(f"❌ 데이터베이스에 없는 어종입니다: {어종명}", ephemeral=True)

        MARKET_PRICES[어종명] = 가격
        await log_admin_action(self.bot, interaction.user, None, "시세조작", f"어종: `{어종명}` / 강제 시세: `{가격:,} C`")
        await interaction.response.send_message(f"⚖️ 관리자 권한으로 **{어종명}**의 시장 시세를 **{가격} C**로 강제 조작했습니다!")

    @app_commands.command(name="웹대시보드", description="[관리자 전용] 외부 관리자를 위해 임시로 암호화된 터널 접속 링크를 생성합니다.")
    @is_developer()
    async def 웹대시보드(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)

        port = int(os.getenv("WEB_PORT", "8888"))

        try:
            if hasattr(self.bot, 'tunnel_proc') and self.bot.tunnel_proc and self.bot.tunnel_proc.returncode is None:
                self.bot.tunnel_proc.terminate()

            # 학교 방화벽이 cloudflared 아웃바운드를 차단하므로 순수 SSH 터널링인 localhost.run 사용
            # ssh -R 80:localhost:8888 nokey@localhost.run -o StrictHostKeyChecking=no
            process = await asyncio.create_subprocess_exec(
                'ssh', '-R', f'80:localhost:{port}', 'nokey@localhost.run', '-o', 'StrictHostKeyChecking=no',
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.STDOUT,
            )
            self.bot.tunnel_proc = process

            # 출력 로그에서 lhr.life 도메인을 찾음
            tunnel_url = None
            is_ready = False

            async def read_stdout():
                nonlocal tunnel_url, is_ready
                while True:
                    try:
                        line = await process.stdout.readline()
                        if not line:
                            break
                        line = line.decode('utf-8').strip()
                        logger.info(f"[SSH Tunnel] {line}")  # 디버그용 출력

                        if not tunnel_url:
                            # localhost.run은 접속 시 https://xxxx.lhr.life 형태의 주소를 뱉음
                            match = re.search(r"https://[a-zA-Z0-9-]+\.lhr\.(life|dev|net)", line)
                            if match:
                                tunnel_url = match.group(0)
                                is_ready = True

                    except Exception:
                        break

            # 백그라운드에서 로그를 계속 읽어 파이프가 막히지 않게 함
            asyncio.create_task(read_stdout())

            # URL과 연결 준비 완료 대기 (최대 15초)
            for _ in range(15):
                if tunnel_url and is_ready:
                    break
                await asyncio.sleep(1.0)

            if tunnel_url:
                await interaction.followup.send(f"🌐 **임시 대시보드 터널 생성 완료!**\n동료 관리자에게 아래 링크를 공유하세요. (새로 생성 시 기존 주소는 폭파됩니다)\n👉 **{tunnel_url}**\n*(접속 시 봇에 설정된 비밀번호가 필요합니다)*\n\n⚠️ *참고: 학교 방화벽을 우회하는 SSH 기반의 고속 터널링 기술로 교체되었습니다!*", ephemeral=True)
            else:
                await interaction.followup.send("❌ 터널을 생성했지만 원격 연결을 보장할 수 없습니다. (포트 차단 등 장애 발생)", ephemeral=True)

        except Exception as e:
            await interaction.followup.send(f"❌ 오류 발생: {e!s}", ephemeral=True)

    @app_commands.command(name="데이터새로고침", description="[관리자 전용] GitHub에서 최신 데이터를 가져온 후 봇 재시작 없이 반영합니다.")
    @is_developer()
    async def 데이터새로고침(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)

        try:
            # 동기적 Popen 대신 비동기 subprocess 사용 (이벤트 루프 블로킹 방지)
            process = await asyncio.create_subprocess_exec(
                "git", "pull",
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, _ = await process.communicate()

            # 디코딩 처리
            stdout_text = stdout.decode('utf-8')

            await reload_data_async()

            msg = f"✅ 최신 데이터를 깃허브에서 가져와 성공적으로 반영했습니다!\n```bash\n{stdout_text}```"
            await interaction.followup.send(msg)

        except Exception as e:
            await interaction.followup.send(f"❌ 데이터 업데이트 중 오류가 발생했습니다.\n**상세 오류:** `{e}`")

    @app_commands.command(name="시스템리로드", description="[관리자 전용] 봇 재시작 없이 모듈(코드)만 즉시 핫 리로드(Hot Reload)합니다.")
    @app_commands.describe(동기화="슬래시 커맨드 변경사항이 있을 때만 True로 설정하세요 (API 제한 방지)")
    @is_developer()
    async def 시스템리로드(self, interaction: discord.Interaction, 동기화: bool = False):
        await interaction.response.defer(ephemeral=True)

        cogs = [
            "fishing_cogs.fishing_cmds",
            "fishing_cogs.market_cmds",
            "fishing_cogs.ship_cmds",
            "fishing_cogs.battle_cmds",
            "fishing_cogs.quest_cmds",
            "fishing_cogs.help_cmds",
            "fishing_cogs.prayer_cmds",
            "fishing_cogs.collection_cmds",
            "fishing_cogs.events",
            "fishing_cogs.admin_cmds",
        ]

        reloaded = []
        failed = []

        for cog in cogs:
            try:
                await self.bot.reload_extension(cog)
                reloaded.append(cog.split('.')[-1])
            except Exception as e:
                failed.append(f"{cog}: {e!s}")

        # 잦은 봇 정지를 막기 위해, 커맨드 인자(옵션) 추가 등을 수정했을 때만 수동으로 동기화하도록 변경
        if 동기화:
            await self.bot.tree.sync()
            sync_msg = "(슬래시 커맨드 동기화 됨)"
        else:
            sync_msg = "(명령어 동기화 생략됨)"

        msg = f"🔄 **시스템 핫 리로드 완료! (무중단 업데이트)** {sync_msg}\n✅ 성공 ({len(reloaded)}개): `{', '.join(reloaded)}`"
        if failed:
            msg += f"\n❌ 실패 ({len(failed)}개):\n```\n" + '\n'.join(failed) + "\n```"

        await interaction.followup.send(msg)

    @app_commands.command(name="데이터점검", description="[관리자 전용] 데이터베이스의 정합성을 검사하고 비정상 데이터를 찾아냅니다.")
    @is_developer()
    async def 데이터점검(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        
        issues = []
        
        # 1. 음수 코인 체크
        async with db.conn.execute("SELECT user_id, coins FROM user_data WHERE coins < 0") as cursor:
            neg_coins = await cursor.fetchall()
            for uid, coin in neg_coins:
                issues.append(f"🔴 유저 <@{uid}>: 음수 코인 보유 ({coin:,} C)")

        # 2. 인벤토리 비정상 수량 (0 이하)
        async with db.conn.execute("SELECT user_id, item_name, amount FROM inventory WHERE amount <= 0") as cursor:
            inv_issues = await cursor.fetchall()
            for uid, item, amt in inv_issues:
                issues.append(f"🟠 유저 <@{uid}>: 아이템 '{item}' 수량 비정상 ({amt})")

        # 3. 고립된 아이템 (데이터에 없는 아이템)
        from fishing_core.shared import RECIPES
        async with db.conn.execute("SELECT DISTINCT item_name FROM inventory") as cursor:
            items_in_inv = await cursor.fetchall()
            for (item,) in items_in_inv:
                if item not in FISH_DATA and item not in RECIPES and "미끼" not in item and "그물망" not in item and "조각" not in item and "상자" not in item and "작살" not in item:
                    issues.append(f"🟡 정의되지 않은 아이템 발견: '{item}'")

        # 4. 필수 스탯 누락 (기본값 설정 여부)
        async with db.conn.execute("SELECT user_id FROM user_data WHERE boat_tier IS NULL OR rod_tier IS NULL OR max_stamina IS NULL") as cursor:
            stat_issues = await cursor.fetchall()
            for (uid,) in stat_issues:
                issues.append(f"🔴 유저 <@{uid}>: 필수 스탯(선박/낚싯대/체력) 누락")

        if not issues:
            return await interaction.followup.send("✅ **데이터 정합성 검사 완료!** 발견된 이상 데이터가 없습니다.", ephemeral=True)
        
        msg = "🔍 **데이터베이스 정합성 검사 결과**\n" + "\n".join(issues)
        if len(msg) > 1950:
            msg = msg[:1950] + "\n... (중략) ..."
        
        await interaction.followup.send(msg, ephemeral=True)

async def setup(bot):
    await bot.add_cog(AdminCog(bot))
