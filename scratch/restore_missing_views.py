
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
