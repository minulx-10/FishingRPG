import aiosqlite

class DBManager:
    def __init__(self):
        self.conn = None

    async def init_db(self):
        self.conn = await aiosqlite.connect('fishing_rpg.db')
        
        await self.conn.execute('''
            CREATE TABLE IF NOT EXISTS user_data (
                user_id INTEGER PRIMARY KEY,
                coins INTEGER DEFAULT 0,
                rod_tier INTEGER DEFAULT 1,
                rating INTEGER DEFAULT 1000
            )
        ''')
        await self.conn.execute('''
            CREATE TABLE IF NOT EXISTS inventory (
                user_id INTEGER,
                item_name TEXT,
                amount INTEGER DEFAULT 0,
                PRIMARY KEY (user_id, item_name)
            )
        ''')
        await self.conn.execute('''
            CREATE TABLE IF NOT EXISTS bucket (
                user_id INTEGER,
                item_name TEXT,
                amount INTEGER DEFAULT 0,
                PRIMARY KEY (user_id, item_name)
            )
        ''')
        await self.conn.execute('''
            CREATE TABLE IF NOT EXISTS fish_dex (
                user_id INTEGER,
                item_name TEXT,
                PRIMARY KEY (user_id, item_name)
            )
        ''')
        await self.conn.execute('''
            CREATE TABLE IF NOT EXISTS active_buffs (
                user_id INTEGER,
                buff_type TEXT,
                end_time TEXT,
                PRIMARY KEY (user_id, buff_type)
            )
        ''')
        await self.conn.execute('''
            CREATE TABLE IF NOT EXISTS aquarium (
                user_id INTEGER,
                item_name TEXT,
                PRIMARY KEY (user_id, item_name)
            )
        ''')
        await self.conn.execute('''
            CREATE TABLE IF NOT EXISTS market_sales (
                item_name TEXT PRIMARY KEY,
                amount_sold INTEGER DEFAULT 0
            )
        ''')
        await self.conn.execute('''
            CREATE TABLE IF NOT EXISTS admin_sessions (
                token TEXT PRIMARY KEY,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        ''')
        await self.conn.execute('''
            CREATE TABLE IF NOT EXISTS server_state (
                key TEXT PRIMARY KEY,
                value TEXT
            )
        ''')

        await self.conn.execute('CREATE INDEX IF NOT EXISTS idx_active_buffs_end_time ON active_buffs (user_id, end_time)')
        
        try:
            await self.conn.execute("ALTER TABLE user_data ADD COLUMN last_daily TEXT DEFAULT ''")
        except aiosqlite.OperationalError:
            pass 

        try:
            await self.conn.execute("ALTER TABLE user_data ADD COLUMN boat_tier INTEGER DEFAULT 1")
        except aiosqlite.OperationalError:
            pass

        try:
            await self.conn.execute("ALTER TABLE user_data ADD COLUMN quest_date TEXT DEFAULT ''")
            await self.conn.execute("ALTER TABLE user_data ADD COLUMN quest_item TEXT DEFAULT ''")
            await self.conn.execute("ALTER TABLE user_data ADD COLUMN quest_amount INTEGER DEFAULT 0")
            await self.conn.execute("ALTER TABLE user_data ADD COLUMN quest_reward INTEGER DEFAULT 0")
            await self.conn.execute("ALTER TABLE user_data ADD COLUMN quest_is_cleared INTEGER DEFAULT 0")
        except aiosqlite.OperationalError:
            pass

        try:
            await self.conn.execute("ALTER TABLE inventory ADD COLUMN is_locked INTEGER DEFAULT 0")
        except aiosqlite.OperationalError:
            pass

        try:
            await self.conn.execute("ALTER TABLE user_data ADD COLUMN stamina INTEGER DEFAULT 100")
            await self.conn.execute("ALTER TABLE user_data ADD COLUMN max_stamina INTEGER DEFAULT 100")
        except aiosqlite.OperationalError:
            pass

        try:
            await self.conn.execute("ALTER TABLE user_data ADD COLUMN peace_mode INTEGER DEFAULT 0")
        except aiosqlite.OperationalError:
            pass

        try:
            await self.conn.execute("ALTER TABLE user_data ADD COLUMN title TEXT DEFAULT ''")
        except aiosqlite.OperationalError:
            pass

        try:
            await self.conn.execute("ALTER TABLE user_data ADD COLUMN aquarium_slots INTEGER DEFAULT 5")
        except aiosqlite.OperationalError:
            pass

        try:
            await self.conn.execute("ALTER TABLE user_data ADD COLUMN username TEXT DEFAULT ''")
        except aiosqlite.OperationalError:
            pass

        # 통 (bucket) 마이그레이션 로직
        try:
            # bucket 테이블이 존재하는지 확인
            await self.conn.execute("SELECT 1 FROM bucket LIMIT 1")
            
            # 버킷에 있는 물고기를 인벤토리로 이동시키며 is_locked = 1 로 설정
            await self.conn.execute('''
                INSERT INTO inventory (user_id, item_name, amount, is_locked)
                SELECT user_id, item_name, amount, 1 FROM bucket
                ON CONFLICT(user_id, item_name) DO UPDATE SET 
                    amount = inventory.amount + excluded.amount, 
                    is_locked = 1
            ''')
            
            # 마이그레이션 완료 후 버킷 테이블 삭제
            await self.conn.execute("DROP TABLE bucket")
            print("✅ 마이그레이션 성공: 통(bucket) 데이터가 inventory로 안전하게 병합되었으며 테이블이 제거되었습니다.")
        except aiosqlite.OperationalError:
            # bucket 테이블이 없으면 이미 마이그레이션 완료된 것
            pass

        await self.conn.commit()

    async def execute(self, query, params=()):
        return await self.conn.execute(query, params)

    async def executemany(self, query, params):
        return await self.conn.executemany(query, params)

    async def commit(self):
        await self.conn.commit()

    async def close(self):
        if self.conn:
            await self.conn.close()

    async def get_user_data(self, user_id):
        async with self.conn.execute("SELECT coins, rod_tier, rating FROM user_data WHERE user_id=?", (user_id,)) as cursor:
            res = await cursor.fetchone()
        
        if not res:
            await self.conn.execute("INSERT INTO user_data (user_id) VALUES (?)", (user_id,))
            await self.conn.commit()
            return (0, 1, 1000) 
            
        return res

db = DBManager()
