import discord
from discord.ext import commands, tasks
from discord import app_commands
import aiosqlite # 🌟 sqlite3 대신 aiosqlite 사용!
import datetime
import random
import asyncio
from discord.ui import View, Button
import os
from dotenv import load_dotenv
import json

# ==========================================
# 1. 봇 기본 설정 및 준비
# ==========================================
intents = discord.Intents.default()
bot = commands.Bot(command_prefix='!', intents=intents)
bot.remove_command('help')

kst = datetime.timezone(datetime.timedelta(hours=9))
SUPER_ADMIN_ID = 771274777443696650
db = None # 🌟 전역 데이터베이스 객체

def is_developer():
    return app_commands.check(lambda i: i.user.id == SUPER_ADMIN_ID)

# ==========================================
# 2. 데이터베이스 비동기 초기화 및 함수
# ==========================================
async def init_db():
    global db
    db = await aiosqlite.connect('fishing_rpg.db')
    
    await db.execute('''
        CREATE TABLE IF NOT EXISTS user_data (
            user_id INTEGER PRIMARY KEY,
            coins INTEGER DEFAULT 0,
            rod_tier INTEGER DEFAULT 1,
            rating INTEGER DEFAULT 1000
        )
    ''')
    await db.execute('''
        CREATE TABLE IF NOT EXISTS inventory (
            user_id INTEGER,
            item_name TEXT,
            amount INTEGER DEFAULT 0,
            PRIMARY KEY (user_id, item_name)
        )
    ''')
    await db.execute('''
        CREATE TABLE IF NOT EXISTS bucket (
            user_id INTEGER,
            item_name TEXT,
            amount INTEGER DEFAULT 0,
            PRIMARY KEY (user_id, item_name)
        )
    ''')
    
    try:
        await db.execute("ALTER TABLE user_data ADD COLUMN last_daily TEXT DEFAULT ''")
    except aiosqlite.OperationalError:
        pass # 이미 컬럼이 존재함

    await db.commit()

# 🌟 모든 DB 접근 함수에 async/await 추가
async def get_user_data(user_id):
    await db.execute("INSERT OR IGNORE INTO user_data (user_id) VALUES (?)", (user_id,))
    async with db.execute("SELECT coins, rod_tier, rating FROM user_data WHERE user_id=?", (user_id,)) as cursor:
        res = await cursor.fetchone()
    await db.commit()
    return res

# ==========================================
# 3. 게임 핵심 데이터 (물고기 도감 & 시세)
# ==========================================
def load_fish_data():
    try:
        with open('fish_data.json', 'r', encoding='utf-8') as f:
            return json.load(f)
    except FileNotFoundError:
        print("❌ 오류: fish_data.json 파일이 없습니다! 봇이 종료됩니다.")
        exit()

FISH_DATA = load_fish_data()
MARKET_PRICES = {fish: data["price"] for fish, data in FISH_DATA.items()}

@tasks.loop(minutes=10)
async def market_update_loop():
    for fish, data in FISH_DATA.items():
        fluctuation = random.uniform(0.5, 2.0)
        MARKET_PRICES[fish] = int(data["price"] * fluctuation)
    print(f"[{datetime.datetime.now(kst).strftime('%H:%M')}] 📈 수산시장 시세가 변동되었습니다!")

def get_element_multiplier(atk_elem, def_elem):
    if atk_elem == "무속성" or def_elem == "무속성": return 1.0
    if atk_elem == "표층" and def_elem == "심해": return 1.5
    if atk_elem == "심해" and def_elem == "암초": return 1.5
    if atk_elem == "암초" and def_elem == "표층": return 1.5
    if atk_elem == def_elem: return 1.0
    return 0.8 

# ==========================================
# 4. 상호작용 UI (버튼 뷰)
# ==========================================
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
        await interaction.response.edit_message(content=f"🎒 **{self.target_fish}**을(를) 가방에 안전하게 넣었습니다!", view=None)

    @discord.ui.button(label="통에 보관 (배틀용)", style=discord.ButtonStyle.success, emoji="🪣")
    async def btn_bucket(self, interaction: discord.Interaction, button: Button):
        if interaction.user != self.user or self.action_taken: return
        self.action_taken = True
        
        await db.execute("INSERT INTO bucket (user_id, item_name, amount) VALUES (?, ?, 1) ON CONFLICT(user_id, item_name) DO UPDATE SET amount = amount + 1", (self.user.id, self.target_fish))
        await db.commit()
        await interaction.response.edit_message(content=f"🪣 **{self.target_fish}**을(를) 통에 담았습니다! 이제 배틀에 출전할 수 있습니다.", view=None)

    @discord.ui.button(label="바로 판매", style=discord.ButtonStyle.danger, emoji="💰")
    async def btn_sell(self, interaction: discord.Interaction, button: Button):
        if interaction.user != self.user or self.action_taken: return
        self.action_taken = True
        
        price = MARKET_PRICES.get(self.target_fish, FISH_DATA[self.target_fish]["price"])
        await db.execute("UPDATE user_data SET coins = coins + ? WHERE user_id = ?", (price, self.user.id))
        await db.commit()
        await interaction.response.edit_message(content=f"💰 **{self.target_fish}**을(를) 시장에 바로 넘겨서 `{price} C`를 벌었습니다!", view=None)

class FishingView(View):
    def __init__(self, user, target_fish, rod_tier):
        super().__init__(timeout=15) 
        self.user = user
        self.target_fish = target_fish
        
        base_window = FISH_DATA[target_fish]["base_window"]
        bonus_time = (rod_tier - 1) * 0.2 
        self.limit_time = max(1.0, base_window + bonus_time) 
        
        self.is_bite = False  
        self.start_time = 0

    @discord.ui.button(label="대기 중...", style=discord.ButtonStyle.secondary, emoji="🎣", custom_id="fish_btn")
    async def fish_button(self, interaction: discord.Interaction, button: Button):
        if interaction.user != self.user:
            return await interaction.response.send_message("남의 낚싯대입니다! 🚫", ephemeral=True)
        
        self.stop() 
        
        if not self.is_bite:
            return await interaction.response.edit_message(content="🎣 앗! 너무 일찍 챘습니다. 물고기가 도망갔어요! 💨", view=None)
            
        elapsed = datetime.datetime.now().timestamp() - self.start_time
        
        if elapsed <= self.limit_time:
            grade = FISH_DATA[self.target_fish]["grade"]
            embed = discord.Embed(title=f"🎉 낚시 성공! [{grade}]", description=f"**{self.target_fish}**을(를) 낚았습니다!", color=0x00ff00)
            embed.add_field(name="반응 속도", value=f"`{elapsed:.3f}초` (판정 한도: {self.limit_time:.2f}초)")
            
            action_view = FishActionView(self.user, self.target_fish)
            await interaction.response.edit_message(content="🎊 앗, 낚았습니다! 이 물고기를 어떻게 할까요?", embed=embed, view=action_view)
        else:
            await interaction.response.edit_message(content=f"⏰ 너무 늦었습니다! `{elapsed:.3f}초` 걸림.\n(놓친 물고기: **{self.target_fish}** / 제한: {self.limit_time:.2f}초)", view=None)

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
        embed.add_field(name=f"🔵 {self.user.name}의 [{self.my_elem}]", 
                        value=f"**{self.my_fish}**\n체력: {self.my_hp}/{self.my_max_hp} {my_hp_bar}\nAP: ⚡x{self.my_ap}", inline=True)
        embed.add_field(name="VS", value="⚡", inline=True)
        npc_hp_bar = "🟥" * max(0, int((self.npc_hp / self.npc_max_hp) * 5)) + "⬛" * (5 - max(0, int((self.npc_hp / self.npc_max_hp) * 5)))
        embed.add_field(name=f"🔴 야생의 [{self.npc_elem}]", 
                        value=f"**{self.npc_fish}**\n체력: {self.npc_hp}/{self.npc_max_hp} {npc_hp_bar}\nAP: ⚡x{self.npc_ap}", inline=True)
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

# ==========================================
# 5. 슬래시 명령어 (Slash Commands)
# ==========================================
@bot.tree.command(name="낚시", description="찌를 던져 물고기를 낚습니다! (타이밍 미니게임)")
async def 낚시(interaction: discord.Interaction):
    coins, rod_tier, rating = await get_user_data(interaction.user.id)
    
    async with db.execute("SELECT amount FROM inventory WHERE user_id=? AND item_name='고급 미끼 🪱'", (interaction.user.id,)) as cursor:
        bait_res = await cursor.fetchone()
    has_bait = bait_res and bait_res[0] > 0
    
    if has_bait:
        await db.execute("UPDATE inventory SET amount = amount - 1 WHERE user_id=? AND item_name='고급 미끼 🪱'", (interaction.user.id,))
        await db.commit()
        bait_text = " (🪱 고급 미끼 사용됨!)"
    else:
        bait_text = ""

    roll = random.uniform(0, 100) / (1 + (rod_tier - 1) * 0.2) 
    if has_bait: roll = roll * 0.5 
    
    target_fish = "낡은 장화 🥾"
    for fish, data in reversed(list(FISH_DATA.items())):
        if roll <= data["prob"]:
            target_fish = fish
            break

    view = FishingView(interaction.user, target_fish, rod_tier)
    await interaction.response.send_message(f"🌊 찌를 던졌습니다... 조용히 기다리세요.{bait_text}\n(내 낚싯대: Lv.{rod_tier})", view=view)
    
    wait_time = random.uniform(2, 6)
    await asyncio.sleep(wait_time)
    
    view.is_bite = True
    view.start_time = datetime.datetime.now().timestamp()
    
    for item in view.children:
        item.label = "지금 챔질하세요!!!!"
        item.style = discord.ButtonStyle.success
        item.emoji = "‼️"
    
    try:
        await interaction.edit_original_response(content="❗ **찌가 격렬하게 흔들립니다! 지금 누르세요!!!**", view=view)
    except: 
        pass 

@bot.tree.command(name="인벤토리", description="내 가방과 현재 스탯을 확인합니다.")
async def 인벤토리(interaction: discord.Interaction):
    coins, rod_tier, rating = await get_user_data(interaction.user.id)
    async with db.execute("SELECT item_name, amount FROM inventory WHERE user_id=? AND amount > 0", (interaction.user.id,)) as cursor:
        items = await cursor.fetchall()
    
    embed = discord.Embed(title=f"🎒 {interaction.user.name}의 인벤토리", color=0x3498db)
    embed.add_field(name="🏆 전투 레이팅", value=f"`{rating} RP`", inline=True)
    embed.add_field(name="💰 보유 코인", value=f"`{coins:,} C`", inline=True)
    embed.add_field(name="🎣 낚싯대 레벨", value=f"`Lv.{rod_tier}`", inline=True)
    
    if items:
        item_list = "\n".join([f"• {name}: {amt}개" for name, amt in items])
        embed.add_field(name="🐟 물고기 도감", value=item_list, inline=False)
    else:
        embed.add_field(name="🐟 물고기 도감", value="텅 비었습니다...", inline=False)
    await interaction.response.send_message(embed=embed)

@bot.tree.command(name="시세", description="현재 수산시장의 글로벌 시세를 확인합니다.")
async def 시세(interaction: discord.Interaction):
    embed = discord.Embed(title="📊 현재 수산시장 시세표", description="매 10분마다 시세가 변동됩니다. 떡상할 때 일괄 판매하세요!", color=0xf1c40f)
    for fish, current_price in MARKET_PRICES.items():
        base = FISH_DATA[fish]["price"]
        ratio = current_price / base
        status = "📈 떡상" if ratio > 1.2 else ("📉 떡락" if ratio < 0.8 else "➖ 평범")
        embed.add_field(name=fish, value=f"현재가: **{current_price} C**\n(기준가: {base}C / {status})", inline=True)
    await interaction.response.send_message(embed=embed)

@bot.tree.command(name="판매", description="인벤토리에 있는 모든 물고기를 현재 시세로 일괄 판매합니다.")
async def 판매(interaction: discord.Interaction):
    async with db.execute("SELECT item_name, amount FROM inventory WHERE user_id=? AND amount > 0", (interaction.user.id,)) as cursor:
        items = await cursor.fetchall()
    
    if not items:
        return await interaction.response.send_message("❌ 판매할 물고기가 없습니다!", ephemeral=True)
        
    total_earned = 0
    msg = "**[💰 수산시장 판매 영수증]**\n"
    
    for name, amt in items:
        price_per_item = MARKET_PRICES.get(name, FISH_DATA[name]["price"])
        earned = price_per_item * amt
        total_earned += earned
        msg += f"• {name} x{amt}: `{earned:,} C` (개당 {price_per_item}C)\n"
        
    await db.execute("UPDATE user_data SET coins = coins + ? WHERE user_id = ?", (total_earned, interaction.user.id))
    await db.execute("DELETE FROM inventory WHERE user_id = ?", (interaction.user.id,))
    await db.commit()
    
    msg += f"\n**총 수익: +{total_earned:,} C**"
    await interaction.response.send_message(msg)

@bot.tree.command(name="강화", description="코인을 지불하여 낚싯대를 업그레이드합니다. (타이밍 판정 및 확률 증가)")
async def 강화(interaction: discord.Interaction):
    coins, rod_tier, rating = await get_user_data(interaction.user.id)
    cost = rod_tier * 2000 
    
    if coins < cost:
        return await interaction.response.send_message(f"❌ 코인이 부족합니다. (필요: `{cost:,} C` / 현재: `{coins:,} C`)", ephemeral=True)
        
    await db.execute("UPDATE user_data SET coins = coins - ?, rod_tier = rod_tier + 1 WHERE user_id = ?", (cost, interaction.user.id))
    await db.commit()
    await interaction.response.send_message(f"✨ 캉! 캉! 캉! ... 낚싯대가 **Lv.{rod_tier + 1}** 로 강화되었습니다!\n(낚시 판정 시간이 늘어나고, 희귀 물고기 획득률이 상승합니다!)")

@bot.tree.command(name="배틀", description="나의 가장 강한 물고기로 야생의 NPC 물고기와 턴제 배틀을 진행합니다!")
async def 배틀(interaction: discord.Interaction):
    await get_user_data(interaction.user.id) 
    
    async with db.execute("SELECT item_name FROM bucket WHERE user_id=? AND amount > 0", (interaction.user.id,)) as cursor:
        items = await cursor.fetchall()
    
    if not items:
        return await interaction.response.send_message("❌ 통(배틀용)이 비어있습니다! 낚시 후 '통에 보관'을 선택해 전사를 포획하세요.", ephemeral=True)
    
    my_best_fish = None
    max_power = -1
    for (name,) in items:
        power = FISH_DATA[name]["power"]
        if power > max_power:
            max_power = power
            my_best_fish = name
            
    npc_pool = [name for name, data in FISH_DATA.items() if data["grade"] != "히든"]
    npc_fish = random.choice(npc_pool)
    
    view = BattleView(interaction.user, my_best_fish, npc_fish)
    await interaction.response.send_message(embed=view.generate_embed(), view=view)

@bot.tree.command(name="출석", description="하루에 한 번 출석체크하고 1000 코인을 받습니다!")
async def 출석(interaction: discord.Interaction):
    await get_user_data(interaction.user.id) 
    today = datetime.datetime.now(kst).strftime('%Y-%m-%d')
    
    async with db.execute("SELECT last_daily FROM user_data WHERE user_id=?", (interaction.user.id,)) as cursor:
        last_daily = (await cursor.fetchone())[0]
    
    if last_daily == today:
        return await interaction.response.send_message("❌ 오늘은 이미 출석하셨습니다! 내일 다시 와주세요.", ephemeral=True)
    
    reward = 1000
    await db.execute("UPDATE user_data SET coins = coins + ?, last_daily = ? WHERE user_id = ?", (reward, today, interaction.user.id))
    await db.commit()
    
    await interaction.response.send_message(f"✅ 출석 완료! 보상으로 `{reward} C`를 받았습니다. (잔액 확인: `/인벤토리`)")

@bot.tree.command(name="상점", description="유용한 아이템을 구경할 수 있는 상점입니다.")
async def 상점(interaction: discord.Interaction):
    embed = discord.Embed(title="🏪 수산시장 아이템 상점", color=0xf1c40f)
    embed.add_field(name="고급 미끼 🪱 (가격: 500 C)", 
                    value="다음 낚시 때 희귀 물고기 등장 확률을 대폭 올려줍니다.\n명령어: `/구매 아이템:고급 미끼 🪱 수량:1`", inline=False)
    await interaction.response.send_message(embed=embed)

@bot.tree.command(name="구매", description="상점에서 아이템을 구매합니다.")
@app_commands.choices(아이템=[
    app_commands.Choice(name="고급 미끼 🪱", value="고급 미끼 🪱")
])
async def 구매(interaction: discord.Interaction, 아이템: app_commands.Choice[str], 수량: int = 1):
    if 수량 <= 0: 
        return await interaction.response.send_message("❌ 수량은 1개 이상이어야 합니다.", ephemeral=True)
        
    coins, _, _ = await get_user_data(interaction.user.id)
    price = 500 * 수량
    
    if coins < price:
        return await interaction.response.send_message(f"❌ 코인이 부족합니다! (필요: {price} C / 현재: {coins} C)", ephemeral=True)
    
    await db.execute("UPDATE user_data SET coins = coins - ? WHERE user_id = ?", (price, interaction.user.id))
    await db.execute("INSERT INTO inventory (user_id, item_name, amount) VALUES (?, ?, ?) ON CONFLICT(user_id, item_name) DO UPDATE SET amount = amount + ?", (interaction.user.id, 아이템.value, 수량, 수량))
    await db.commit()
    
    await interaction.response.send_message(f"🛍️ **{아이템.value}** {수량}개를 구매했습니다! (남은 코인: `{coins - price} C`)")

@bot.tree.command(name="통", description="배틀에 출전할 수 있는 통(배틀 전용 저장소)을 확인합니다.")
async def 통(interaction: discord.Interaction):
    async with db.execute("SELECT item_name, amount FROM bucket WHERE user_id=? AND amount > 0", (interaction.user.id,)) as cursor:
        items = await cursor.fetchall()
    
    embed = discord.Embed(title=f"🪣 {interaction.user.name}의 통 (배틀 대기조)", color=0x2ecc71)
    if items:
        item_list = "\n".join([f"• {name}: {amt}마리 (전투력: {FISH_DATA[name]['power']}⚡)" for name, amt in items])
        embed.add_field(name="출전 가능한 물고기", value=item_list, inline=False)
    else:
        embed.add_field(name="텅 비었습니다...", value="낚시 성공 후 '통에 보관'을 눌러주세요.", inline=False)
    await interaction.response.send_message(embed=embed)

async def fish_autocomplete(interaction: discord.Interaction, current: str) -> list[app_commands.Choice[str]]:
    choices = [
        app_commands.Choice(name=fish, value=fish)
        for fish in FISH_DATA.keys() if current.lower() in fish.lower()
    ]
    return choices[:25]

@bot.tree.command(name="개별판매", description="가방에 있는 특정 물고기를 원하는 수량만큼 판매합니다.")
@app_commands.autocomplete(물고기=fish_autocomplete)
async def 개별판매(interaction: discord.Interaction, 물고기: str, 수량: int):
    target_fish = 물고기
    
    if 수량 <= 0:
        return await interaction.response.send_message("❌ 수량은 1마리 이상이어야 합니다.", ephemeral=True)
        
    async with db.execute("SELECT amount FROM inventory WHERE user_id=? AND item_name=?", (interaction.user.id, target_fish)) as cursor:
        res = await cursor.fetchone()
    current_amount = res[0] if res else 0
    
    if current_amount < 수량:
        return await interaction.response.send_message(f"❌ 가방에 **{target_fish}**가 부족합니다. (현재 보유: {current_amount}마리)", ephemeral=True)
    
    price_per_item = MARKET_PRICES.get(target_fish, FISH_DATA[target_fish]["price"])
    total_earned = price_per_item * 수량
    
    await db.execute("UPDATE inventory SET amount = amount - ? WHERE user_id=? AND item_name=?", (수량, interaction.user.id, target_fish))
    await db.execute("UPDATE user_data SET coins = coins + ? WHERE user_id=?", (total_earned, interaction.user.id))
    await db.commit()
    
    await interaction.response.send_message(f"💰 **{target_fish}** {수량}마리를 팔아서 총 `{total_earned:,} C`를 얻었습니다! (개당 {price_per_item}C)")

# ==========================================
# 6. 관리자 전용 직권 명령어 (어뷰징 관리, 이벤트용)
# ==========================================
@bot.tree.command(name="코인지급", description="[관리자 전용] 특정 유저에게 코인을 강제로 지급합니다.")
@is_developer()
async def 코인지급(interaction: discord.Interaction, target: discord.Member, amount: int):
    await get_user_data(target.id)
    await db.execute("UPDATE user_data SET coins = coins + ? WHERE user_id = ?", (amount, target.id))
    await db.commit()
    await interaction.response.send_message(f"💰 관리자 권한으로 **{target.name}**님에게 `{amount:,} C`를 지급했습니다!")

# ==========================================
# 7. 봇 이벤트 
# ==========================================
@bot.event
async def setup_hook():
    await init_db() # 🌟 봇 켜질 때 DB 초기화 먼저 실행!
    await bot.tree.sync()

@bot.event
async def on_ready():
    print(f'🎣 수산시장 낚시 RPG 봇 로딩 완료: {bot.user.name}')
    await bot.change_presence(activity=discord.Game("/낚시 | /시세 | /배틀"))
    
    if not market_update_loop.is_running():
        market_update_loop.start()

if __name__ == "__main__":
    load_dotenv() 
    TOKEN = os.getenv('DISCORD_TOKEN') 
    bot.run(TOKEN)
