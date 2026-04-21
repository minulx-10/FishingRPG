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
