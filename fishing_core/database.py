import contextlib
from typing import Any

import aiosqlite

from .logger import logger


class DBManager:
    """데이터베이스 관리를 담당하는 클래스입니다. aiosqlite를 사용하여 비동기적으로 작동합니다."""

    def __init__(self) -> None:
        self.conn: aiosqlite.Connection | None = None

    async def init_db(self) -> None:
        """데이터베이스 연결을 초기화하고 필요한 테이블들을 생성합니다."""
        self.conn = await aiosqlite.connect('fishing_rpg.db')

        # 기본 테이블 생성
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
                amount INTEGER DEFAULT 1,
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

        # [NEW] 어종 정보 테이블 (JSON 대체용)
        await self.conn.execute('''
            CREATE TABLE IF NOT EXISTS fish_info (
                item_name TEXT PRIMARY KEY,
                grade TEXT,
                price INTEGER,
                prob REAL,
                element TEXT,
                power INTEGER DEFAULT 0,
                description TEXT
            )
        ''')

        # [NEW] 레시피 정보 테이블 (JSON 대체용)
        await self.conn.execute('''
            CREATE TABLE IF NOT EXISTS recipes (
                result_item TEXT PRIMARY KEY,
                ingredients TEXT, -- JSON string
                stamina_boost INTEGER DEFAULT 0
            )
        ''')

        await self.conn.execute('CREATE INDEX IF NOT EXISTS idx_active_buffs_end_time ON active_buffs (user_id, end_time)')

        # 마이그레이션 테이블 생성
        await self.conn.execute('''
            CREATE TABLE IF NOT EXISTS migrations (
                version INTEGER PRIMARY KEY,
                applied_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        ''')

        # 마이그레이션 리스트 (버전, 쿼리)
        migrations = [
            (1, "ALTER TABLE user_data ADD COLUMN last_daily TEXT DEFAULT ''"),
            (2, "ALTER TABLE user_data ADD COLUMN boat_tier INTEGER DEFAULT 1"),
            (3, "ALTER TABLE user_data ADD COLUMN quest_date TEXT DEFAULT ''"),
            (4, "ALTER TABLE user_data ADD COLUMN quest_item TEXT DEFAULT ''"),
            (5, "ALTER TABLE user_data ADD COLUMN quest_amount INTEGER DEFAULT 0"),
            (6, "ALTER TABLE user_data ADD COLUMN quest_reward INTEGER DEFAULT 0"),
            (7, "ALTER TABLE user_data ADD COLUMN quest_is_cleared INTEGER DEFAULT 0"),
            (8, "ALTER TABLE inventory ADD COLUMN is_locked INTEGER DEFAULT 0"),
            (9, "ALTER TABLE user_data ADD COLUMN stamina INTEGER DEFAULT 150"),
            (10, "ALTER TABLE user_data ADD COLUMN max_stamina INTEGER DEFAULT 150"),
            (11, "ALTER TABLE user_data ADD COLUMN peace_mode INTEGER DEFAULT 0"),
            (12, "ALTER TABLE user_data ADD COLUMN title TEXT DEFAULT ''"),
            (13, "ALTER TABLE user_data ADD COLUMN aquarium_slots INTEGER DEFAULT 5"),
            (14, "ALTER TABLE user_data ADD COLUMN username TEXT DEFAULT ''"),
            (15, "ALTER TABLE user_data ADD COLUMN peace_cooldown TEXT DEFAULT ''"),
            (16, "ALTER TABLE user_data ADD COLUMN last_free_rest TEXT DEFAULT ''"),
            (17, "ALTER TABLE user_data ADD COLUMN pvp_shield_count INTEGER DEFAULT 3"),
            (18, "ALTER TABLE user_data ADD COLUMN pvp_shield_date TEXT DEFAULT ''"),
            (19, "ALTER TABLE user_data ADD COLUMN pvp_last_target INTEGER DEFAULT 0"),
            (20, "ALTER TABLE user_data ADD COLUMN pvp_consecutive_count INTEGER DEFAULT 0"),
            (21, "ALTER TABLE user_data ADD COLUMN dex_rewards TEXT DEFAULT '{}'"),
            (22, "ALTER TABLE user_data ADD COLUMN upgrade_pity INTEGER DEFAULT 0"),
            (23, "ALTER TABLE user_data ADD COLUMN last_active TEXT DEFAULT ''"),
            (24, "ALTER TABLE user_data ADD COLUMN guard_fish TEXT DEFAULT ''"),
            (25, "ALTER TABLE aquarium ADD COLUMN amount INTEGER DEFAULT 1"),
            (26, "ALTER TABLE user_data ADD COLUMN last_farm_harvest TEXT DEFAULT ''"),
            (27, "ALTER TABLE user_data ADD COLUMN merchant_purchase_state TEXT DEFAULT '{}'"),
            (28, "ALTER TABLE user_data ADD COLUMN last_prayer_date TEXT DEFAULT ''"),
            (29, "ALTER TABLE user_data ADD COLUMN current_region TEXT DEFAULT '연안'"),
            (30, "ALTER TABLE user_data ADD COLUMN claimed_collections TEXT DEFAULT '{}'"),
        ]

        # 현재 버전 확인
        async with self.conn.execute("SELECT MAX(version) FROM migrations") as cursor:
            row = await cursor.fetchone()
            current_version = row[0] if row and row[0] is not None else 0

        for version, query in migrations:
            if version > current_version:
                try:
                    await self.conn.execute(query)
                    await self.conn.execute("INSERT INTO migrations (version) VALUES (?)", (version,))
                    logger.info(f"🚀 DB 마이그레이션 적용 완료: 버전 {version}")
                except aiosqlite.OperationalError as e:
                    if "duplicate column name" in str(e).lower():
                        await self.conn.execute("INSERT OR IGNORE INTO migrations (version) VALUES (?)", (version,))
                    else:
                        logger.error(f"❌ 마이그레이션 실패 (버전 {version}): {e}")

        # 통 (bucket) 마이그레이션 로직
        with contextlib.suppress(aiosqlite.OperationalError):
            await self.conn.execute("SELECT 1 FROM bucket LIMIT 1")
            await self.conn.execute('''
                INSERT INTO inventory (user_id, item_name, amount, is_locked)
                SELECT user_id, item_name, amount, 1 FROM bucket
                WHERE 1
                ON CONFLICT(user_id, item_name) DO UPDATE SET
                    amount = inventory.amount + excluded.amount,
                    is_locked = 1
            ''')
            await self.conn.execute("DROP TABLE bucket")
            logger.info("✅ 마이그레이션 성공: 통(bucket) 데이터가 inventory로 안전하게 병합되었습니다.")

        await self.conn.commit()

    async def execute(self, query: str, params: tuple[Any, ...] | list[Any] = ()) -> aiosqlite.Cursor | None:
        """쿼리를 실행합니다."""
        if not self.conn:
            return None
        return await self.conn.execute(query, params)

    async def executemany(self, query: str, params: list[tuple[Any, ...]]) -> aiosqlite.Cursor | None:
        """여러 쿼리를 한 번에 실행합니다."""
        if not self.conn:
            return None
        return await self.conn.executemany(query, params)

    async def commit(self) -> None:
        """변경 사항을 저장합니다."""
        if self.conn:
            await self.conn.commit()

    async def close(self) -> None:
        """연결을 종료합니다."""
        if self.conn:
            await self.conn.close()

    async def get_user_data(self, user_id: int) -> tuple[int, int, int]:
        """유저의 기본 정보(코인, 낚싯대 티어, 레이팅)를 가져옵니다."""
        if not self.conn:
            return (0, 1, 1000)

        async with self.conn.execute("SELECT coins, rod_tier, rating FROM user_data WHERE user_id=?", (user_id,)) as cursor:
            res = await cursor.fetchone()

        if not res:
            await self.conn.execute("INSERT INTO user_data (user_id, stamina, max_stamina) VALUES (?, 150, 150)", (user_id,))
            await self.conn.commit()
            return (0, 1, 1000)

        return res

    async def get_user_title(self, user_id: int) -> str:
        """유저의 칭호를 가져옵니다."""
        if not self.conn:
            return ""

        async with self.conn.execute("SELECT title FROM user_data WHERE user_id=?", (user_id,)) as cursor:
            res = await cursor.fetchone()
        return res[0] if res and res[0] else ""

db = DBManager()
