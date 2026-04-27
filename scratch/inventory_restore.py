
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
            embed.add_field(name="​", value=col2 or " ", inline=True)

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
