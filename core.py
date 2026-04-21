import aiosqlite
import json
import datetime

# 기본 설정 및 권한
KST = datetime.timezone(datetime.timedelta(hours=9))
SUPER_ADMIN_IDS = [771274777443696650, 861106310439632896, 1478295213389774920]

# 데이터베이스 전역 객체
db = None

# 환경 및 게임 상태 전역 변수
CURRENT_WEATHER = "☀️ 맑음"
WEATHER_TYPES = ["☀️ 맑음", "☁️ 흐림", "🌧️ 비", "🌩️ 폭풍우", "🌫️ 안개"]

def load_json(filepath):
    """JSON 파일을 로드하여 반환합니다."""
    try:
        with open(filepath, 'r', encoding='utf-8') as f:
            return json.load(f)
    except FileNotFoundError:
        return {}

FISH_DATA = load_json('fish_data.json')
RECIPES = load_json('recipes.json')
MARKET_PRICES = {fish: data.get("price", 0) for fish, data in FISH_DATA.items()}

def get_element_multiplier(atk_elem, def_elem):
    """속성별 상성 배율을 계산합니다."""
    if atk_elem == "무속성" or def_elem == "무속성": return 1.0
    if atk_elem == "표층" and def_elem == "심해": return 1.5
    if atk_elem == "심해" and def_elem == "암초": return 1.5
    if atk_elem == "암초" and def_elem == "표층": return 1.5
    if atk_elem == def_elem: return 1.0
    return 0.8 

async def init_db():
    """데이터베이스 연결 및 테이블 초기화"""
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
    await db.execute('CREATE TABLE IF NOT EXISTS inventory (user_id INTEGER, item_name TEXT, amount INTEGER DEFAULT 0, PRIMARY KEY (user_id, item_name))')
    await db.execute('CREATE TABLE IF NOT EXISTS bucket (user_id INTEGER, item_name TEXT, amount INTEGER DEFAULT 0, PRIMARY KEY (user_id, item_name))')
    await db.execute('CREATE TABLE IF NOT EXISTS fish_dex (user_id INTEGER, item_name TEXT, PRIMARY KEY (user_id, item_name))')
    await db.execute('CREATE TABLE IF NOT EXISTS active_buffs (user_id INTEGER, buff_type TEXT, end_time TEXT, PRIMARY KEY (user_id, buff_type))')
    await db.execute('CREATE TABLE IF NOT EXISTS aquarium (user_id INTEGER, item_name TEXT, PRIMARY KEY (user_id, item_name))')
    await db.execute('CREATE INDEX IF NOT EXISTS idx_active_buffs_end_time ON active_buffs (user_id, end_time)')
    
    # 신규 컬럼 업데이트 (존재하지 않을 경우 대비)
    columns_to_add = [
        ("user_data", "last_daily", "TEXT DEFAULT ''"),
        ("user_data", "boat_tier", "INTEGER DEFAULT 1"),
        ("user_data", "quest_date", "TEXT DEFAULT ''"),
        ("user_data", "quest_item", "TEXT DEFAULT ''"),
        ("user_data", "quest_amount", "INTEGER DEFAULT 0"),
        ("user_data", "quest_reward", "INTEGER DEFAULT 0"),
        ("user_data", "quest_is_cleared", "INTEGER DEFAULT 0")
    ]
    
    for table, col, dtype in columns_to_add:
        try:
            await db.execute(f"ALTER TABLE {table} ADD COLUMN {col} {dtype}")
        except aiosqlite.OperationalError:
            pass

    await db.commit()

async def get_user_data(user_id):
    """유저의 기본 정보를 조회 (없으면 생성 후 반환)"""
    async with db.execute("SELECT coins, rod_tier, rating FROM user_data WHERE user_id=?", (user_id,)) as cursor:
        res = await cursor.fetchone()
    
    if not res:
        await db.execute("INSERT INTO user_data (user_id) VALUES (?)", (user_id,))
        await db.commit()
        return (0, 1, 1000)
        
    return res
