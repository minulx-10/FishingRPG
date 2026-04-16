import discord
from discord.ext import commands, tasks
from discord import app_commands
import sqlite3
import datetime
import random
import asyncio
from discord.ui import View, Button
import os # 추가
from dotenv import load_dotenv # 추가

# ==========================================
# 1. 봇 기본 설정 및 준비
# ==========================================
intents = discord.Intents.default()
bot = commands.Bot(command_prefix='!', intents=intents)
bot.remove_command('help')

kst = datetime.timezone(datetime.timedelta(hours=9))

# 관리자(개발자) ID 설정 (본인의 디스코드 숫자 ID로 변경하세요)
SUPER_ADMIN_ID = 771274777443696650

def is_developer():
    return app_commands.check(lambda i: i.user.id == SUPER_ADMIN_ID)

# ==========================================
# 2. 데이터베이스 (SQLite3) 초기화
# ==========================================
conn = sqlite3.connect('fishing_rpg.db', check_same_thread=False)
cursor = conn.cursor()

# 유저 정보 테이블
cursor.execute('''
    CREATE TABLE IF NOT EXISTS user_data (
        user_id INTEGER PRIMARY KEY,
        coins INTEGER DEFAULT 0,
        rod_tier INTEGER DEFAULT 1,
        rating INTEGER DEFAULT 1000
    )
''')
# 인벤토리 테이블
cursor.execute('''
    CREATE TABLE IF NOT EXISTS inventory (
        user_id INTEGER,
        item_name TEXT,
        amount INTEGER DEFAULT 0,
        PRIMARY KEY (user_id, item_name)
    )
''')
conn.commit()

# 기존 유저 테이블에 출석체크용 날짜 컬럼 추가 (이미 있으면 무시됨)
try:
    cursor.execute("ALTER TABLE user_data ADD COLUMN last_daily TEXT DEFAULT ''")
    conn.commit()
except sqlite3.OperationalError:
    pass # 이미 컬럼이 존재함

def get_user_data(user_id):
    cursor.execute("INSERT OR IGNORE INTO user_data (user_id) VALUES (?)", (user_id,))
    cursor.execute("SELECT coins, rod_tier, rating FROM user_data WHERE user_id=?", (user_id,))
    conn.commit()
    return cursor.fetchone()

# ==========================================
# 3. 게임 핵심 데이터 (물고기 도감 & 시세)
# ==========================================
# 속성 상성: 표층 > 심해 > 암초 > 표층
FISH_DATA = {
    "낡은 장화 🥾": {"grade": "일반", "prob": 100, "base_window": 3.5, "price": 5, "power": 1, "element": "무속성"},
    "싱싱한 고등어 🐟": {"grade": "일반", "prob": 60, "base_window": 3.0, "price": 50, "power": 5, "element": "표층"},
    "특급 참치 🍣": {"grade": "희귀", "prob": 25, "base_window": 2.5, "price": 300, "power": 20, "element": "표층"},
    "암초의 돌돔 🐠": {"grade": "초희귀", "prob": 12, "base_window": 2.0, "price": 1000, "power": 45, "element": "암초"},
    "전설의 흰수염고래 🐋": {"grade": "에픽", "prob": 5, "base_window": 1.5, "price": 2500, "power": 100, "element": "심해"},
    "심해의 용궁 가디언 🐉": {"grade": "레전드", "prob": 0.5, "base_window": 1.3, "price": 15000, "power": 500, "element": "심해"},
    "💎 GSM 황금 키보드": {"grade": "히든", "prob": 0.01, "base_window": 1.2, "price": 500000, "power": 9999, "element": "무속성"}
}

# 전역 시세 저장소 (시장판매 시 사용)
MARKET_PRICES = {fish: data["price"] for fish, data in FISH_DATA.items()}

# 시세 변동 루프 (매 10분마다 실행)
@tasks.loop(minutes=10)
async def market_update_loop():
    for fish, data in FISH_DATA.items():
        # 0.5배 ~ 2.0배 사이로 무작위 변동
        fluctuation = random.uniform(0.5, 2.0)
        MARKET_PRICES[fish] = int(data["price"] * fluctuation)
    print(f"[{datetime.datetime.now(kst).strftime('%H:%M')}] 📈 수산시장 시세가 변동되었습니다!")

def get_element_multiplier(atk_elem, def_elem):
    if atk_elem == "무속성" or def_elem == "무속성": return 1.0
    if atk_elem == "표층" and def_elem == "심해": return 1.5
    if atk_elem == "심해" and def_elem == "암초": return 1.5
    if atk_elem == "암초" and def_elem == "표층": return 1.5
    if atk_elem == def_elem: return 1.0
    return 0.8 # 역상성일 경우 데미지 감소

# ==========================================
# 4. 상호작용 UI (버튼 뷰)
# ==========================================

# [1] 낚시 미니게임 UI
class FishingView(View):
    def __init__(self, user, target_fish, rod_tier):
        super().__init__(timeout=15) # 15초 지나면 버튼 비활성화
        self.user = user
        self.target_fish = target_fish
        
        # 🌟 낚싯대 등급당 0.2초씩 보호시간 부여 (강화 체감 대폭 상향!)
        base_window = FISH_DATA[target_fish]["base_window"]
        bonus_time = (rod_tier - 1) * 0.2 
        
        # 서버 지연을 고려해 아무리 어려워도 무조건 1.0초 이상은 보장
        self.limit_time = max(1.0, base_window + bonus_time) 
        
        self.is_bite = False  
        self.start_time = 0

    @discord.ui.button(label="대기 중...", style=discord.ButtonStyle.secondary, emoji="🎣", custom_id="fish_btn")
    async def fish_button(self, interaction: discord.Interaction, button: Button):
        if interaction.user != self.user:
            return await interaction.response.send_message("남의 낚싯대입니다! 🚫", ephemeral=True)
        
        self.stop() # 뷰 종료 (버튼 더 이상 못 누르게 함)
        
        if not self.is_bite:
            return await interaction.response.edit_message(content="🎣 앗! 너무 일찍 챘습니다. 물고기가 도망갔어요! 💨", view=None)
            
        elapsed = datetime.datetime.now().timestamp() - self.start_time
        
        if elapsed <= self.limit_time:
            # 성공 처리
            cursor.execute("INSERT INTO inventory (user_id, item_name, amount) VALUES (?, ?, 1) ON CONFLICT(user_id, item_name) DO UPDATE SET amount = amount + 1", (self.user.id, self.target_fish))
            conn.commit()
            
            grade = FISH_DATA[self.target_fish]["grade"]
            embed = discord.Embed(title=f"🎉 낚시 성공! [{grade}]", description=f"**{self.target_fish}**을(를) 낚았습니다!", color=0x00ff00)
            embed.add_field(name="반응 속도", value=f"`{elapsed:.3f}초` (판정 한도: {self.limit_time:.2f}초)")
            await interaction.response.edit_message(content="🎊 앗, 낚았습니다!", embed=embed, view=None)
        else:
            # 실패 처리
            await interaction.response.edit_message(content=f"⏰ 너무 늦었습니다! `{elapsed:.3f}초` 걸림.\n(놓친 물고기: **{self.target_fish}** / 제한: {self.limit_time:.2f}초)", view=None)

# [2] 턴제 PvE 배틀 UI
class BattleView(View):
    def __init__(self, user, my_fish, npc_fish):
        super().__init__(timeout=60)
        self.user = user
        self.my_fish = my_fish
        self.npc_fish = npc_fish
        
        # 스탯 초기화
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
        
        # 내 상태
        my_hp_bar = "🟩" * max(0, int((self.my_hp / self.my_max_hp) * 5)) + "⬛" * (5 - max(0, int((self.my_hp / self.my_max_hp) * 5)))
        embed.add_field(name=f"🔵 {self.user.name}의 [{self.my_elem}]", 
                        value=f"**{self.my_fish}**\n체력: {self.my_hp}/{self.my_max_hp} {my_hp_bar}\nAP: ⚡x{self.my_ap}", inline=True)
        
        embed.add_field(name="VS", value="⚡", inline=True)

        # NPC 상태
        npc_hp_bar = "🟥" * max(0, int((self.npc_hp / self.npc_max_hp) * 5)) + "⬛" * (5 - max(0, int((self.npc_hp / self.npc_max_hp) * 5)))
        embed.add_field(name=f"🔴 야생의 [{self.npc_elem}]", 
                        value=f"**{self.npc_fish}**\n체력: {self.npc_hp}/{self.npc_max_hp} {npc_hp_bar}\nAP: ⚡x{self.npc_ap}", inline=True)
        
        embed.add_field(name="📜 전투 로그", value=f"```\n{self.battle_log}\n```", inline=False)
        return embed

    async def execute_turn(self, interaction: discord.Interaction, action: str):
        self.battle_log = ""
        
        # 1. 플레이어 행동
        if action == "attack":
            self.is_my_defending = False
            mult = get_element_multiplier(self.my_elem, self.npc_elem)
            dmg = int(self.my_atk * self.my_ap * mult)
            if self.is_npc_defending: dmg //= 2
            
            self.npc_hp -= dmg
            elem_txt = "(효과 발군!)" if mult > 1.0 else ("(효과 미미...)" if mult < 1.0 else "")
            self.battle_log += f"🔵 {self.my_fish}의 공격! 💥 {dmg} 피해! {elem_txt}\n"
            self.my_ap = 1 # AP 소모
        else: # defend
            self.is_my_defending = True
            self.my_ap += 1
            self.battle_log += f"🔵 {self.my_fish} 방어 태세! 피해 반감 & AP 1 회복.\n"

        # NPC 사망 체크
        if self.npc_hp <= 0:
            return await self.end_battle(interaction, is_win=True)

        # 2. NPC 행동 (간단한 AI)
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

        # 플레이어 사망 체크
        if self.my_hp <= 0:
            return await self.end_battle(interaction, is_win=False)

        self.turn += 1
        await interaction.response.edit_message(embed=self.generate_embed(), view=self)

    async def end_battle(self, interaction, is_win):
        self.stop() # 버튼 비활성화
        embed = self.generate_embed()
        
        if is_win:
            reward_rp = random.randint(10, 30)
            reward_coin = FISH_DATA[self.npc_fish]["power"] * 5
            cursor.execute("UPDATE user_data SET rating = rating + ?, coins = coins + ? WHERE user_id = ?", (reward_rp, reward_coin, self.user.id))
            conn.commit()
            embed.description = f"🎉 **승리했습니다!** (보상: +{reward_rp} RP, +{reward_coin} C)"
            embed.color = 0x00ff00
        else:
            lose_rp = random.randint(5, 15)
            cursor.execute("UPDATE user_data SET rating = MAX(0, rating - ?) WHERE user_id = ?", (lose_rp, self.user.id))
            conn.commit()
            embed.description = f"💀 **패배했습니다...** (패널티: -{lose_rp} RP)"
            embed.color = 0x555555

        # 뷰를 제거하고 메시지 업데이트
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
    coins, rod_tier, rating = get_user_data(interaction.user.id)
    
    # 🌟 미끼 보유 여부 확인 및 차감 로직 추가
    cursor.execute("SELECT amount FROM inventory WHERE user_id=? AND item_name='고급 미끼 🪱'", (interaction.user.id,))
    bait_res = cursor.fetchone()
    has_bait = bait_res and bait_res[0] > 0
    
    if has_bait:
        cursor.execute("UPDATE inventory SET amount = amount - 1 WHERE user_id=? AND item_name='고급 미끼 🪱'", (interaction.user.id,))
        conn.commit()
        bait_text = " (🪱 고급 미끼 사용됨!)"
    else:
        bait_text = ""

    # 낚싯대 티어에 따른 확률 보정
    roll = random.uniform(0, 100) / (1 + (rod_tier - 1) * 0.2) 
    
    # 🌟 미끼가 있으면 확률 주사위 값을 절반으로 깎아서 희귀도 대폭 상승!
    if has_bait:
        roll = roll * 0.5 
    
    # 확률표를 역순으로 확인하여 등급 판정
    target_fish = "낡은 장화 🥾"
    for fish, data in reversed(list(FISH_DATA.items())):
        if roll <= data["prob"]:
            target_fish = fish
            break

    view = FishingView(interaction.user, target_fish, rod_tier)
    await interaction.response.send_message(f"🌊 찌를 던졌습니다... 조용히 기다리세요.{bait_text}\n(내 낚싯대: Lv.{rod_tier})", view=view)
    
    # 비동기 대기 (2~6초) - 서버 멈춤 현상 없음
    wait_time = random.uniform(2, 6)
    await asyncio.sleep(wait_time)
    
    view.is_bite = True
    view.start_time = datetime.datetime.now().timestamp()
    
    # 버튼 UI 업데이트
    for item in view.children:
        item.label = "지금 챔질하세요!!!!"
        item.style = discord.ButtonStyle.success
        item.emoji = "‼️"
    
    try:
        await interaction.edit_original_response(content="❗ **찌가 격렬하게 흔들립니다! 지금 누르세요!!!**", view=view)
    except: 
        pass # 이미 취소됐거나 지워졌을 경우 예외처리

@bot.tree.command(name="인벤토리", description="내 가방과 현재 스탯을 확인합니다.")
async def 인벤토리(interaction: discord.Interaction):
    coins, rod_tier, rating = get_user_data(interaction.user.id)
    cursor.execute("SELECT item_name, amount FROM inventory WHERE user_id=? AND amount > 0", (interaction.user.id,))
    items = cursor.fetchall()
    
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
    cursor.execute("SELECT item_name, amount FROM inventory WHERE user_id=? AND amount > 0", (interaction.user.id,))
    items = cursor.fetchall()
    
    if not items:
        return await interaction.response.send_message("❌ 판매할 물고기가 없습니다!", ephemeral=True)
        
    total_earned = 0
    msg = "**[💰 수산시장 판매 영수증]**\n"
    
    for name, amt in items:
        price_per_item = MARKET_PRICES.get(name, FISH_DATA[name]["price"])
        earned = price_per_item * amt
        total_earned += earned
        msg += f"• {name} x{amt}: `{earned:,} C` (개당 {price_per_item}C)\n"
        
    cursor.execute("UPDATE user_data SET coins = coins + ? WHERE user_id = ?", (total_earned, interaction.user.id))
    cursor.execute("DELETE FROM inventory WHERE user_id = ?", (interaction.user.id,))
    conn.commit()
    
    msg += f"\n**총 수익: +{total_earned:,} C**"
    await interaction.response.send_message(msg)

@bot.tree.command(name="강화", description="코인을 지불하여 낚싯대를 업그레이드합니다. (타이밍 판정 및 확률 증가)")
async def 강화(interaction: discord.Interaction):
    coins, rod_tier, rating = get_user_data(interaction.user.id)
    cost = rod_tier * 2000 
    
    if coins < cost:
        return await interaction.response.send_message(f"❌ 코인이 부족합니다. (필요: `{cost:,} C` / 현재: `{coins:,} C`)", ephemeral=True)
        
    cursor.execute("UPDATE user_data SET coins = coins - ?, rod_tier = rod_tier + 1 WHERE user_id = ?", (cost, interaction.user.id))
    conn.commit()
    await interaction.response.send_message(f"✨ 캉! 캉! 캉! ... 낚싯대가 **Lv.{rod_tier + 1}** 로 강화되었습니다!\n(낚시 판정 시간이 늘어나고, 희귀 물고기 획득률이 상승합니다!)")

@bot.tree.command(name="배틀", description="나의 가장 강한 물고기로 야생의 NPC 물고기와 턴제 배틀을 진행합니다!")
async def 배틀(interaction: discord.Interaction):
    get_user_data(interaction.user.id) # 유저 데이터 초기화 보장
    
    # 1. 내 가방에서 가장 전투력이 높은 물고기 찾기
    cursor.execute("SELECT item_name FROM inventory WHERE user_id=? AND amount > 0", (interaction.user.id,))
    items = cursor.fetchall()
    
    if not items:
        return await interaction.response.send_message("❌ 가방이 비어있습니다! 먼저 `/낚시`를 통해 전사를 포획하세요.", ephemeral=True)
    
    my_best_fish = None
    max_power = -1
    for (name,) in items:
        power = FISH_DATA[name]["power"]
        if power > max_power:
            max_power = power
            my_best_fish = name
            
    # 2. 야생의 NPC 물고기 랜덤 생성 (히든 등급 제외)
    npc_pool = [name for name, data in FISH_DATA.items() if data["grade"] != "히든"]
    npc_fish = random.choice(npc_pool)
    
    # 3. 배틀 뷰 생성 및 시작
    view = BattleView(interaction.user, my_best_fish, npc_fish)
    await interaction.response.send_message(embed=view.generate_embed(), view=view)

@bot.tree.command(name="출석", description="하루에 한 번 출석체크하고 1000 코인을 받습니다!")
async def 출석(interaction: discord.Interaction):
    get_user_data(interaction.user.id) # 유저 데이터 초기화 보장
    
    # 오늘 날짜 구하기 (한국 시간 기준)
    today = datetime.datetime.now(kst).strftime('%Y-%m-%d')
    
    cursor.execute("SELECT last_daily FROM user_data WHERE user_id=?", (interaction.user.id,))
    last_daily = cursor.fetchone()[0]
    
    if last_daily == today:
        return await interaction.response.send_message("❌ 오늘은 이미 출석하셨습니다! 내일 다시 와주세요.", ephemeral=True)
    
    reward = 1000
    cursor.execute("UPDATE user_data SET coins = coins + ?, last_daily = ? WHERE user_id = ?", (reward, today, interaction.user.id))
    conn.commit()
    
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
        
    coins, _, _ = get_user_data(interaction.user.id)
    price = 500 * 수량
    
    if coins < price:
        return await interaction.response.send_message(f"❌ 코인이 부족합니다! (필요: {price} C / 현재: {coins} C)", ephemeral=True)
    
    # 코인 차감 및 인벤토리에 아이템 지급
    cursor.execute("UPDATE user_data SET coins = coins - ? WHERE user_id = ?", (price, interaction.user.id))
    cursor.execute("INSERT INTO inventory (user_id, item_name, amount) VALUES (?, ?, ?) ON CONFLICT(user_id, item_name) DO UPDATE SET amount = amount + ?", (interaction.user.id, 아이템.value, 수량, 수량))
    conn.commit()
    
    await interaction.response.send_message(f"🛍️ **{아이템.value}** {수량}개를 구매했습니다! (남은 코인: `{coins - price} C`)")

# ==========================================
# 6. 관리자 전용 직권 명령어 (어뷰징 관리, 이벤트용)
# ==========================================
@bot.tree.command(name="코인지급", description="[관리자 전용] 특정 유저에게 코인을 강제로 지급합니다.")
@is_developer()
async def 코인지급(interaction: discord.Interaction, target: discord.Member, amount: int):
    get_user_data(target.id)
    cursor.execute("UPDATE user_data SET coins = coins + ? WHERE user_id = ?", (amount, target.id))
    conn.commit()
    await interaction.response.send_message(f"💰 관리자 권한으로 **{target.name}**님에게 `{amount:,} C`를 지급했습니다!")

# ==========================================
# 7. 봇 이벤트 
# ==========================================
@bot.event
async def setup_hook():
    # 슬래시 커맨드를 디스코드 서버에 동기화
    await bot.tree.sync()

@bot.event
async def on_ready():
    print(f'🎣 수산시장 낚시 RPG 봇 로딩 완료: {bot.user.name}')
    await bot.change_presence(activity=discord.Game("/낚시 | /시세 | /배틀"))
    
    # 시세 변동 루프 시작
    if not market_update_loop.is_running():
        market_update_loop.start()

if __name__ == "__main__":
    # .env 파일(쪽지)에서 내용물을 불러와라!
    load_dotenv() 
    
    # 쪽지에 적힌 DISCORD_TOKEN 값을 가져와라!
    TOKEN = os.getenv('DISCORD_TOKEN') 
    
    bot.run(TOKEN)
