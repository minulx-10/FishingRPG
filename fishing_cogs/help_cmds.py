import discord
from discord import app_commands
from discord.ext import commands

from fishing_core.shared import SUPER_ADMIN_IDS
from fishing_core.utils import EmbedFactory
from fishing_core.views_v2 import TutorialView


class HelpView(discord.ui.View):
    def __init__(self, user, is_admin=False):
        super().__init__(timeout=120)
        self.user = user
        self.is_admin = is_admin

        # 관리자 권한에 따라 옵션 필터링
        options = [
            discord.SelectOption(label="메인 메뉴", description="도움말 처음으로 돌아갑니다.", emoji="🏠", value="main"),
            discord.SelectOption(label="낚시 및 바다", description="물고기를 낚고 환경을 확인하는 명령어", emoji="🎣", value="fishing"),
            discord.SelectOption(label="상점 및 시세", description="아이템 구매 및 물고기 판매, 시세 확인", emoji="💰", value="market"),
            discord.SelectOption(label="가방 및 보호", description="내 상태 확인 및 아이템 잠금 설정", emoji="🎒", value="inventory"),
            discord.SelectOption(label="전투 및 레이드", description="NPC/PvP 배틀 및 월드 보스 레이드", emoji="⚔️", value="battle"),
            discord.SelectOption(label="도감 및 의뢰", description="수집 기록, 요리, 일일 퀘스트 및 수족관", emoji="📜", value="quest"),
            discord.SelectOption(label="강화 및 개조", description="낚싯대 강화 및 선박 티어 업그레이드", emoji="🛠️", value="upgrade"),
            discord.SelectOption(label="아이템 및 기타", description="보물상자 감정, 지도 합성 및 기타 유틸리티", emoji="📦", value="misc"),
        ]

        if self.is_admin:
            options.append(discord.SelectOption(label="관리자 전용", description="서버 관리 및 데이터 제어 명령어", emoji="🛡️", value="admin"))

        self.add_item(HelpSelect(options))

class HelpSelect(discord.ui.Select):
    def __init__(self, options):
        super().__init__(placeholder="원하는 카테고리를 선택하세요", min_values=1, max_values=1, options=options)

    async def callback(self, interaction: discord.Interaction):
        if interaction.user.id != self.view.user.id:
            return await interaction.response.send_message("❌ 이 도움말 메뉴는 명령어를 입력한 본인만 조작할 수 있습니다.", ephemeral=True)

        category = self.values[0]
        embed = self.get_embed(category)
        await interaction.response.edit_message(embed=embed, view=self.view)

    def get_embed(self, category):
        if category == "main":
            embed = EmbedFactory.build(title="🎣 수산시장 RPG 도움말 센터", style="info")
            embed.description = "아래 드롭다운 메뉴를 클릭하여 카테고리별 명령어 설명을 확인하세요!\n\n" \
                                "💡 **팁**: 모든 명령어는 슬래시(`/`)로 시작합니다.\n" \
                                "⚓ **초보자 가이드**: `/낚시`로 물고기를 잡고 `/판매`로 돈을 벌어 `/강화`하세요!"
            embed.add_field(name="📋 카테고리 안내", value="• **🎣 낚시**: 물고기를 낚는 기초 명령어\n"
                                                      "• **💰 상점**: 경제 활동 및 시세 정보\n"
                                                      "• **🎒 가방**: 인벤토리 관리 및 보호\n"
                                                      "• **⚔️ 전투**: 배틀, PvP, 월드 레이드\n"
                                                      "• **📜 도감**: 수집, 요리, 의뢰, 수족관\n"
                                                      "• **🛠️ 강화**: 스펙업의 핵심, 강화와 개조\n"
                                                      "• **📦 기타**: 보물상자 및 유틸리티")
            return embed

        if category == "fishing":
            embed = EmbedFactory.build(title="🎣 낚시 및 바다 명령어", style="info")
            embed.add_field(name="`/낚시 [미끼]`", value="찌를 던져 물고기를 낚습니다. 타이밍 판정에 성공해야 합니다.\n(체력 10 소모 / 뉴비 5 소모)", inline=False)
            embed.add_field(name="`/그물망 [그물]`", value="그물망을 던져 여러 마리를 한꺼번에 낚습니다.", inline=False)
            embed.add_field(name="`/미끼장착 [미끼이름]`", value="자동으로 소모할 미끼를 장착하거나 해제합니다.", inline=False)
            embed.add_field(name="`/이동 [해역]`", value="다른 해역으로 이동하여 새로운 어종을 만납니다.", inline=False)
            embed.add_field(name="`/바다`", value="현재 바다의 시간대와 날씨 환경을 확인합니다.", inline=False)
            embed.add_field(name="`/기상예측`", value="향후 3시간의 날씨 변화를 미리 확인합니다. (3,000 C 소모)", inline=False)
            embed.add_field(name="`/기우제 [기부금]`", value="유저들과 힘을 합쳐 날씨를 **🌩️ 폭풍우**로 변경합니다.", inline=False)
            embed.add_field(name="`/기도`", value="오늘의 운세를 점쳐 2시간 버프/디버프를 받습니다. (일 1회)", inline=False)
            embed.add_field(name="`/바다기도 [제물]`", value="심연의 바다에 제물을 바쳐 전설 속의 신수를 부릅니다.", inline=False)
            return embed

        if category == "market":
            embed = EmbedFactory.build(title="💰 상점 및 시세 명령어", style="warning")
            embed.add_field(name="`/시세 [어종]`", value="현재 수산시장의 실시간 글로벌 시세를 확인합니다.", inline=False)
            embed.add_field(name="`/판매 [제외...] [등급필터]`", value="가방 속 물고기를 일괄 판매합니다. 특정 아이템을 보호할 수 있습니다.", inline=False)
            embed.add_field(name="`/개별판매 [물고기] [수량]`", value="특정 물고기를 원하는 수량만큼만 골라서 판매합니다.", inline=False)
            embed.add_field(name="`/상점`", value="미끼, 포션, 작살 등 유용한 소비 아이템 목록을 봅니다.", inline=False)
            embed.add_field(name="`/구매 [아이템] [수량]`", value="상점에서 아이템을 구매합니다.", inline=False)
            embed.add_field(name="`/칭호상점`", value="어마어마한 코인을 지불하여 명예로운 칭호를 획득합니다.", inline=False)
            return embed

        if category == "inventory":
            embed = EmbedFactory.build(title="🎒 가방 및 보호 명령어", style="success")
            embed.add_field(name="`/인벤토리 [유저]`", value="가방 내용물, 코인, 선박, 강화 레벨, 체력을 확인합니다.", inline=False)
            embed.add_field(name="`/잠금 [아이템]` / `/잠금해제`", value="특정 아이템을 일괄 판매에서 제외하고 배틀용으로 보호합니다.", inline=False)
            embed.add_field(name="`/일괄잠금` / `/일괄해제`", value="가방 안의 모든 물고기를 한꺼번에 잠그거나 해제합니다.", inline=False)
            embed.add_field(name="`/잠금목록 [유저]`", value="현재 잠금(보호) 처리된 아이템과 전사 목록을 봅니다.", inline=False)
            embed.add_field(name="`/칭호장착 [선택]`", value="보유한 칭호 중 하나를 골라 닉네임 앞에 장착합니다.", inline=False)
            embed.add_field(name="`/휴식`", value="여관에서 푹 쉬어 체력을 즉시 회복합니다. (일 1회 무료)", inline=False)
            return embed

        if category == "battle":
            embed = EmbedFactory.build(title="⚔️ 전투 및 레이드 명령어", style="error")
            embed.add_field(name="`/배틀`", value="잠금된 전사 중 가장 강한 물고기로 NPC와 턴제 전투를 벌입니다.", inline=False)
            embed.add_field(name="`/수산대전 [상대]`", value="다른 유저와 3v3 릴레이 PvP 배틀을 벌여 코인과 RP를 약탈합니다.", inline=False)
            embed.add_field(name="`/평화모드`", value="PvP 약탈을 거부하는 상태로 전환합니다. (공격도 불가능)", inline=False)
            embed.add_field(name="`/레이드`", value="서버 유저들과 힘을 합쳐 월드 보스 '아포칼립스'를 토벌합니다.", inline=False)
            embed.add_field(name="`/호위설정 [물고기]`", value="오프라인 상태에서 나를 지켜줄 호위 전사를 지정합니다.", inline=False)
            return embed

        if category == "quest":
            embed = EmbedFactory.build(title="📜 도감 및 의뢰 명령어", style="default")
            embed.add_field(name="`/도감 [유저]`", value="지금까지 발견한 어종 기록과 수집률, 월척 기록을 확인합니다.", inline=False)
            embed.add_field(name="`/도감보상`", value="수집한 어종 수에 따라 코인과 특별 칭호를 수령합니다.", inline=False)
            embed.add_field(name="`/의뢰`", value="매일 바뀌는 항구 게시판의 낚시 의뢰를 확인하고 납품합니다.", inline=False)
            embed.add_field(name="`/요리 [레시피]`", value="잡은 물고기로 요리를 만들어 강력한 버프를 얻습니다.", inline=False)
            embed.add_field(name="`/수족관 [유저]`", value="내가 전시한 물고기들을 이미지로 렌더링하여 감상합니다.", inline=False)
            embed.add_field(name="`/전시 [물고기]` / `/전시해제`", value="물고기를 수족관에 넣거나 다시 꺼냅니다.", inline=False)
            embed.add_field(name="`/수족관확장`", value="코인을 지불하여 수족관 전시 슬롯을 추가합니다.", inline=False)
            embed.add_field(name="`/양식수확`", value="수족관에 전시된 물고기가 번식한 치어를 수확합니다.", inline=False)
            embed.add_field(name="`/세트효과`", value="수집한 물고기 세트에 따른 영구 효과를 확인합니다.", inline=False)
            return embed

        if category == "upgrade":
            embed = EmbedFactory.build(title="🛠️ 강화 및 개조 명령어", style="default")
            embed.add_field(name="`/강화`", value="낚싯대 레벨을 올립니다. 레벨이 높을수록 대물과 희귀종 확률이 증가합니다.", inline=False)
            embed.add_field(name="`/선박개조`", value="배를 업그레이드하여 최대 체력을 늘리고 새로운 기능을 해금합니다.", inline=False)
            embed.set_footer(text="💡 Lv.50 강화부터는 레벨 하락 위험이 있는 '초월 강화'가 시작됩니다.")
            return embed

        if category == "misc":
            embed = EmbedFactory.build(title="📦 아이템 및 기타 명령어", style="default")
            embed.add_field(name="`/감정`", value="'가라앉은 보물상자 🧰'를 열어 대박 아이템을 노립니다.", inline=False)
            embed.add_field(name="`/지도합성 [수량]`", value="찢어진 지도 조각(A,B,C,D) 4종을 모아 보물지도를 완성합니다.", inline=False)
            embed.add_field(name="`/조각교환 [조각]`", value="같은 지도 조각 3개를 다른 무작위 조각 1개로 교환합니다.", inline=False)
            embed.add_field(name="`/지도사용`", value="보물지도를 사용해 30분간 특수 해역(망자/심해/황금)을 개방합니다.", inline=False)
            embed.add_field(name="`/조개열기 [조개] [수량]`", value="가방의 조개를 열어 진주를 찾습니다.", inline=False)
            embed.add_field(name="`/진주상점`", value="모은 진주를 특별한 보상으로 교환합니다.", inline=False)
            embed.add_field(name="`/출석`", value="매일 한 번 출석체크하여 코인 보상과 체력 회복을 받습니다.", inline=False)
            embed.add_field(name="`/한강물`", value="실시간 한강 수온 정보를 확인합니다. (응? 🎣)", inline=False)
            return embed

        if category == "admin":
            embed = EmbedFactory.build(title="🛡️ 관리자 전용 명령어", style="error")
            embed.add_field(name="`/코인지급` / `/아이템지급` / `/회수`", value="유저의 재화나 아이템을 관리합니다.", inline=False)
            embed.add_field(name="`/유저스탯변경`", value="선박 티어, 낚싯대 레벨, RP 등을 강제 설정합니다.", inline=False)
            embed.add_field(name="`/전체공지`", value="모든 채널에 관리자 공지사항을 발송합니다.", inline=False)
            embed.add_field(name="`/시세조작`", value="특정 어종의 시장 가격을 강제로 고정합니다.", inline=False)
            embed.add_field(name="`/시스템리로드` / `/데이터새로고침`", value="코드나 데이터를 무중단으로 즉시 반영합니다.", inline=False)
            embed.add_field(name="`/웹대시보드`", value="관리용 웹 인터페이스 접속 터널을 생성합니다.", inline=False)
            return embed


class HelpCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @app_commands.command(name="도움말", description="수산시장 RPG의 모든 명령어 설명과 사용법을 확인합니다.")
    async def 도움말_slash(self, interaction: discord.Interaction):
        await self._send_help(interaction)

    @commands.command(name="도움말", aliases=["help", "도움"])
    async def 도움말_prefix(self, ctx: commands.Context):
        await self._send_help(ctx)

    async def _send_help(self, ctx_or_inter):
        user = ctx_or_inter.user if isinstance(ctx_or_inter, discord.Interaction) else ctx_or_inter.author
        is_admin = user.id in SUPER_ADMIN_IDS
        view = HelpView(user, is_admin)

        embed = EmbedFactory.build(title="🎣 수산시장 RPG 도움말 센터", style="info")
        embed.description = "아래 드롭다운 메뉴를 클릭하여 카테고리별 명령어 설명을 확인하세요!\n\n" \
                            "💡 **팁**: 모든 명령어는 슬래시(`/`)로 시작합니다.\n" \
                            "⚓ **초보자 가이드**: `/낚시`로 물고기를 잡고 `/판매`로 돈을 벌어 `/강화`하세요!"
        embed.add_field(name="📋 카테고리 안내", value="• **🎣 낚시**: 물고기를 낚는 기초 명령어\n"
                                                  "• **💰 상점**: 경제 활동 및 시세 정보\n"
                                                  "• **🎒 가방**: 인벤토리 관리 및 보호\n"
                                                  "• **⚔️ 전투**: 배틀, PvP, 월드 레이드\n"
                                                  "• **📜 도감**: 수집, 요리, 의뢰, 수족관\n"
                                                  "• **🛠️ 강화**: 스펙업의 핵심, 강화와 개조\n"
                                                  "• **📦 기타**: 보물상자 및 유틸리티")

        if is_admin:
            embed.set_footer(text="🛡️ 관리자 권한이 감지되었습니다. 전용 카테고리가 활성화되었습니다.")

        if isinstance(ctx_or_inter, discord.Interaction):
            await ctx_or_inter.response.send_message(embed=embed, view=view)
        else:
            await ctx_or_inter.send(embed=embed, view=view)

    @app_commands.command(name="가이드", description="뉴비를 위한 수산시장 RPG 쾌속 성장 가이드를 확인합니다.")
    async def 가이드(self, interaction: discord.Interaction):
        view = TutorialView(interaction.user)
        await interaction.response.send_message(embed=view.make_embed(), view=view)


async def setup(bot):
    await bot.add_cog(HelpCog(bot))
