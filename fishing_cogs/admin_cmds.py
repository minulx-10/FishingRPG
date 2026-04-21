import discord
from discord.ext import commands
from discord import app_commands
import subprocess

from fishing_core.utils import is_developer
from fishing_core.database import db
from fishing_core.shared import reload_data

class AdminCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @app_commands.command(name="코인지급", description="[관리자 전용] 특정 유저에게 코인을 강제로 지급합니다.")
    @is_developer()
    async def 코인지급(self, interaction: discord.Interaction, target: discord.Member, amount: int):
        await db.get_user_data(target.id)
        await db.execute("UPDATE user_data SET coins = coins + ? WHERE user_id = ?", (amount, target.id))
        await db.commit()
        await interaction.response.send_message(f"💰 관리자 권한으로 **{target.name}**님에게 `{amount:,} C`를 지급했습니다!")

    @app_commands.command(name="아이템지급", description="[관리자 전용] 특정 유저에게 아이템을 강제 지급합니다.")
    @is_developer()
    async def 아이템지급(self, interaction: discord.Interaction, target: discord.Member, 아이템명: str, 수량: int):
        await db.execute("INSERT INTO inventory (user_id, item_name, amount) VALUES (?, ?, ?) ON CONFLICT(user_id, item_name) DO UPDATE SET amount = amount + ?", (target.id, 아이템명, 수량, 수량))
        await db.commit()
        await interaction.response.send_message(f"🎁 관리자 권한으로 **{target.name}**님에게 `{아이템명}` {수량}개를 지급했습니다!")

    @app_commands.command(name="아이템회수", description="[관리자 전용] 특정 유저의 아이템을 강제 회수(삭제)합니다.")
    @is_developer()
    async def 아이템회수(self, interaction: discord.Interaction, target: discord.Member, 아이템명: str, 수량: int):
        await db.execute("UPDATE inventory SET amount = MAX(0, amount - ?) WHERE user_id = ? AND item_name = ?", (수량, target.id, 아이템명))
        await db.execute("DELETE FROM inventory WHERE amount <= 0")
        await db.commit()
        await interaction.response.send_message(f"🗑️ 관리자 권한으로 **{target.name}**님의 `{아이템명}` {수량}개를 강제 회수했습니다!")

    @app_commands.command(name="유저스탯변경", description="[관리자 전용] 특정 유저의 스탯(선박, 낚싯대, 레이팅)을 설정합니다.")
    @app_commands.choices(항목=[
        app_commands.Choice(name="선박 티어 (boat_tier)", value="boat_tier"),
        app_commands.Choice(name="낚싯대 레벨 (rod_tier)", value="rod_tier"),
        app_commands.Choice(name="전투 레이팅 (rating)", value="rating")
    ])
    @is_developer()
    async def 유저스탯변경(self, interaction: discord.Interaction, target: discord.Member, 항목: app_commands.Choice[str], 값: int):
        await db.get_user_data(target.id) 
        if 항목.value == "boat_tier":
            await db.execute("UPDATE user_data SET boat_tier = ? WHERE user_id = ?", (값, target.id))
        elif 항목.value == "rod_tier":
            await db.execute("UPDATE user_data SET rod_tier = ? WHERE user_id = ?", (값, target.id))
        elif 항목.value == "rating":
            await db.execute("UPDATE user_data SET rating = ? WHERE user_id = ?", (값, target.id))
        await db.commit()
        await interaction.response.send_message(f"⚙️ 관리자 권한으로 **{target.name}**님의 `{항목.name}`을(를) **{값}**(으)로 설정했습니다!")

    @app_commands.command(name="전체공지", description="[관리자 전용] 멋진 임베드로 전체 공지사항을 띄웁니다.")
    @is_developer()
    async def 전체공지(self, interaction: discord.Interaction, 제목: str, 내용: str):
        embed = discord.Embed(title=f"📢 [시스템 공지] {제목}", description=내용.replace('\\n', '\n'), color=0xff0000)
        embed.set_footer(text="수산시장 관리국에서 발송된 메시지입니다.")
        await interaction.channel.send(content="@everyone", embed=embed)
        await interaction.response.send_message("공지 발송 완료!", ephemeral=True)

    @app_commands.command(name="시세조작", description="[관리자 전용] 특정 물고기의 현재 시세를 강제로 고정시킵니다.")
    @is_developer()
    async def 시세조작(self, interaction: discord.Interaction, 어종명: str, 가격: int):
        from fishing_core.shared import MARKET_PRICES, FISH_DATA
        if 어종명 not in FISH_DATA:
            return await interaction.response.send_message(f"❌ 데이터베이스에 없는 어종입니다: {어종명}", ephemeral=True)
            
        MARKET_PRICES[어종명] = 가격
        await interaction.response.send_message(f"⚖️ 관리자 권한으로 **{어종명}**의 시장 시세를 **{가격} C**로 강제 조작했습니다!")

    @app_commands.command(name="웹대시보드", description="[관리자 전용] 외부 관리자를 위해 임시로 암호화된 터널 접속 링크를 생성합니다.")
    @is_developer()
    async def 웹대시보드(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        import os
        import subprocess
        import re
        import asyncio
        
        port = int(os.getenv("WEB_PORT", 8888))
        
        try:
            if hasattr(self.bot, 'tunnel_proc') and self.bot.tunnel_proc and self.bot.tunnel_proc.returncode is None:
                self.bot.tunnel_proc.terminate()
                
            # cloudflared 프로세스를 비동기로 실행하여 URL 추출
            process = await asyncio.create_subprocess_exec(
                'cloudflared', 'tunnel', '--url', f'http://localhost:{port}', '--no-autoupdate',
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.STDOUT
            )
            self.bot.tunnel_proc = process
            
            # 출력 로그에서 trycloudflare.com 도메인을 찾음
            tunnel_url = None
            is_ready = False
            
            async def read_stdout():
                nonlocal tunnel_url, is_ready
                while True:
                    try:
                        line = await process.stdout.readline()
                        if not line: break
                        line = line.decode('utf-8').strip()
                        print(f"[Cloudflared] {line}") # 디버그용 출력
                        
                        if not tunnel_url:
                            match = re.search(r"https://[a-zA-Z0-9-]+\.trycloudflare\.com", line)
                            if match:
                                tunnel_url = match.group(0)
                                
                        if "Registered tunnel connection" in line:
                            is_ready = True
                    except:
                        break

            # 백그라운드에서 로그를 계속 읽어 파이프가 막히지 않게 함
            asyncio.create_task(read_stdout())
            
            # URL과 연결 준비 완료 대기 (최대 15초)
            for _ in range(15):
                if tunnel_url and is_ready: break
                await asyncio.sleep(1.0)
            
            if tunnel_url:
                await interaction.followup.send(f"🌐 **임시 대시보드 터널 생성 완료!**\n동료 관리자에게 아래 링크를 공유하세요. (새로 생성 시 기존 주소는 폭파됩니다)\n👉 **{tunnel_url}**\n*(접속 시 봇에 설정된 비밀번호가 필요합니다)*\n\n⚠️ *참고: 링크를 클릭해도 안 열린다면 전세계 DNS 전파 중이므로 **5~10초 후** 다시 새로고침하세요!*", ephemeral=True)
            else:
                await interaction.followup.send("❌ 터널을 생성했지만 원격 연결을 보장할 수 없습니다. (학교 방화벽이 터널을 차단했거나 연결 속도가 너무 느림)", ephemeral=True)
                
        except FileNotFoundError:
            await interaction.followup.send("❌ 서버에 `cloudflared`가 설치되어 있지 않아 터널링을 열 수 없습니다.", ephemeral=True)
        except Exception as e:
            await interaction.followup.send(f"❌ 오류 발생: {str(e)}", ephemeral=True)

    @app_commands.command(name="데이터새로고침", description="[관리자 전용] GitHub에서 최신 데이터를 가져온 후 봇 재시작 없이 반영합니다.")
    @is_developer()
    async def 데이터새로고침(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True) 
        
        try:
            process = subprocess.Popen(["git", "pull"], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
            stdout, stderr = process.communicate()
            
            reload_data()
            
            msg = f"✅ 최신 데이터를 깃허브에서 가져와 성공적으로 반영했습니다!\n```bash\n{stdout}```"
            await interaction.followup.send(msg)
            
        except Exception as e:
            await interaction.followup.send(f"❌ 데이터 업데이트 중 오류가 발생했습니다.\n**상세 오류:** `{e}`")

async def setup(bot):
    await bot.add_cog(AdminCog(bot))
