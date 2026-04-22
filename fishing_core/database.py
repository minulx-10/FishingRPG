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
            CREATE TABLE IF NOT EXISTS active_buffs (
                user_id INTEGER,
                buff_type TEXT,
                end_time TEXT,
                PRIMARY KEY (user_id, buff_type)
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
        await self.conn.execute('''
            CREATE TABLE IF NOT EXISTS fish_records (
                user_id INTEGER,
                item_name TEXT,
                max_size REAL DEFAULT 0.0,
                PRIMARY KEY (user_id, item_name)
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
            await self.conn.execute("ALTER TABLE user_data ADD COLUMN stamina INTEGER DEFAULT 150")
            await self.conn.execute("ALTER TABLE user_data ADD COLUMN max_stamina INTEGER DEFAULT 150")
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

        # Phase 1: 평화모드 쿨타임 (ISO 형식 타임스탬프)
        try:
            await self.conn.execute("ALTER TABLE user_data ADD COLUMN peace_cooldown TEXT DEFAULT ''")
        except aiosqlite.OperationalError:
            pass

        # Phase 1: 일일 무료 휴식 날짜
        try:
            await self.conn.execute("ALTER TABLE user_data ADD COLUMN last_free_rest TEXT DEFAULT ''")
        except aiosqlite.OperationalError:
            pass

        # Phase 1: PvP 보호막 (하루 약탈당하는 횟수 제한)
        try:
            await self.conn.execute("ALTER TABLE user_data ADD COLUMN pvp_shield_count INTEGER DEFAULT 3")
            await self.conn.execute("ALTER TABLE user_data ADD COLUMN pvp_shield_date TEXT DEFAULT ''")
        except aiosqlite.OperationalError:
            pass

        # Phase 3: PvP 연속 약탈 패널티 (동일 유저 공격 시 수익 감소)
        try:
            await self.conn.execute("ALTER TABLE user_data ADD COLUMN pvp_last_target INTEGER DEFAULT 0")
            await self.conn.execute("ALTER TABLE user_data ADD COLUMN pvp_consecutive_count INTEGER DEFAULT 0")
        except aiosqlite.OperationalError:
            pass

        # Phase 3: 도감 보상 수령 현황 (JSON 형식)
        try:
            await self.conn.execute("ALTER TABLE user_data ADD COLUMN dex_rewards TEXT DEFAULT '{}'")
        except aiosqlite.OperationalError:
            pass

        # Phase 4: 강화 천장(Pity) 시스템
        try:
            await self.conn.execute("ALTER TABLE user_data ADD COLUMN upgrade_pity INTEGER DEFAULT 0")
        except aiosqlite.OperationalError:
            pass

        # Phase 4: 마지막 활동 시간 (오프라인 보호용)
        try:
            await self.conn.execute("ALTER TABLE user_data ADD COLUMN last_active TEXT DEFAULT ''")
        except aiosqlite.OperationalError:
            pass

        # Phase 4: 호위 어종 (오프라인 방어용)
        try:
            await self.conn.execute("ALTER TABLE user_data ADD COLUMN guard_fish TEXT DEFAULT ''")
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
                WHERE 1
                ON CONFLICT(user_id, item_name) DO UPDATE SET 
                    amount = inventory.amount + excluded.amount, 
                    is_locked = 1
            ''')
            
            # 마이그레이션 완료 후 버킷 테이블 삭제
            await self.conn.execute("DROP TABLE bucket")
            print("✅ 마이그레이션 성공: 통(bucket) 데이터가 inventory로 안전하게 병합되었으며 테이블이 제거되었습니다.")
        except aiosqlite.OperationalError:
            # bucket 테이블이 없거나 이미 마이그레이션 완료된 경우
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
            await self.conn.execute("INSERT INTO user_data (user_id, stamina, max_stamina) VALUES (?, 150, 150)", (user_id,))
            await self.conn.commit()
            return (0, 1, 1000) 
            
        return res

    async def get_user_title(self, user_id):
        async with self.conn.execute("SELECT title FROM user_data WHERE user_id=?", (user_id,)) as cursor:
            res = await cursor.fetchone()
        return res[0] if res and res[0] else ""

db = DBManager()
