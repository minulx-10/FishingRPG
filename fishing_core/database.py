import contextlib
import json
from typing import Any

import aiosqlite

from .logger import logger


class DBManager:
    """데이터베이스 관리를 담당하는 클래스입니다. aiosqlite를 사용하여 비동기적으로 작동합니다."""

    def __init__(self) -> None:
        self.conn: aiosqlite.Connection | None = None

    async def init_db(self) -> None:
        """데이터베이스 연결을 초기화하고 마이그레이션을 수행합니다."""
        self.conn = await aiosqlite.connect('fishing_rpg.db')

        # 1. 시스템 테이블 생성 (마이그레이션 관리용)
        await self.conn.execute('''
            CREATE TABLE IF NOT EXISTS server_state (
                key TEXT PRIMARY KEY,
                value TEXT
            )
        ''')
        await self.conn.execute('''
            CREATE TABLE IF NOT EXISTS migrations (
                version INTEGER PRIMARY KEY,
                applied_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        ''')

        # 2. 마이그레이션 리스트 (기본 테이블 생성 및 변경 사항)
        # v1 ~ v31은 이전 히스토리 유지, v32부터 신규 기능 추가
        migrations = [
            # --- [기초 스키마] ---
            (1, "CREATE TABLE IF NOT EXISTS user_data (user_id INTEGER PRIMARY KEY, coins INTEGER DEFAULT 0, rod_tier INTEGER DEFAULT 1, rating INTEGER DEFAULT 1000)"),
            (2, "CREATE TABLE IF NOT EXISTS inventory (user_id INTEGER, item_name TEXT, amount INTEGER DEFAULT 0, PRIMARY KEY (user_id, item_name))"),
            (3, "CREATE TABLE IF NOT EXISTS active_buffs (user_id INTEGER, buff_type TEXT, end_time TEXT, PRIMARY KEY (user_id, buff_type))"),
            (4, "CREATE TABLE IF NOT EXISTS fish_dex (user_id INTEGER, item_name TEXT, PRIMARY KEY (user_id, item_name))"),
            (5, "CREATE TABLE IF NOT EXISTS aquarium (user_id INTEGER, item_name TEXT, amount INTEGER DEFAULT 1, PRIMARY KEY (user_id, item_name))"),
            (6, "CREATE TABLE IF NOT EXISTS market_sales (item_name TEXT PRIMARY KEY, amount_sold INTEGER DEFAULT 0)"),
            (7, "CREATE TABLE IF NOT EXISTS fish_records (user_id INTEGER, item_name TEXT, max_size REAL DEFAULT 0.0, PRIMARY KEY (user_id, item_name))"),
            (8, "CREATE TABLE IF NOT EXISTS fish_info (item_name TEXT PRIMARY KEY, grade TEXT, price INTEGER, prob REAL, element TEXT, power INTEGER DEFAULT 0, description TEXT)"),
            (9, "CREATE TABLE IF NOT EXISTS recipe_info (recipe_name TEXT PRIMARY KEY, ingredients TEXT, result_item TEXT, buff_type TEXT, duration INTEGER)"),
            
            # --- [컬럼 추가 히스토리 (v10~v31 요약)] ---
            (10, "ALTER TABLE user_data ADD COLUMN last_daily TEXT DEFAULT ''"),
            (11, "ALTER TABLE user_data ADD COLUMN boat_tier INTEGER DEFAULT 1"),
            (12, "ALTER TABLE user_data ADD COLUMN stamina INTEGER DEFAULT 150"),
            (13, "ALTER TABLE user_data ADD COLUMN max_stamina INTEGER DEFAULT 150"),
            (14, "ALTER TABLE user_data ADD COLUMN title TEXT DEFAULT ''"),
            (15, "ALTER TABLE inventory ADD COLUMN is_locked INTEGER DEFAULT 0"),
            (16, "ALTER TABLE user_data ADD COLUMN current_region TEXT DEFAULT '연안'"),
            (17, "ALTER TABLE user_data ADD COLUMN upgrade_pity INTEGER DEFAULT 0"),
            (18, "ALTER TABLE user_data ADD COLUMN merchant_purchase_state TEXT DEFAULT '{}'"),
            (19, "ALTER TABLE user_data ADD COLUMN claimed_collections TEXT DEFAULT '{}'"),
            (20, "ALTER TABLE user_data ADD COLUMN pvp_shield_count INTEGER DEFAULT 3"),
            (21, "ALTER TABLE user_data ADD COLUMN last_prayer_date TEXT DEFAULT ''"),
            
            # --- [감사 로그 시스템] ---
            (31, '''
                CREATE TABLE IF NOT EXISTS audit_logs (
                    log_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id INTEGER,
                    action_type TEXT,
                    details TEXT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            '''),

            # --- [Phase 4: 업적 시스템] ---
            (32, '''
                CREATE TABLE IF NOT EXISTS user_achievements (
                    user_id INTEGER,
                    achievement_id TEXT,
                    progress INTEGER DEFAULT 0,
                    is_completed INTEGER DEFAULT 0,
                    completed_at TEXT,
                    PRIMARY KEY (user_id, achievement_id)
                )
            '''),
        ]

        # 3. 마이그레이션 실행
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
                    # 이미 존재하는 컬럼/테이블 에러는 무시하고 버전만 기록
                    if "duplicate" in str(e).lower() or "already exists" in str(e).lower():
                        await self.conn.execute("INSERT OR IGNORE INTO migrations (version) VALUES (?)", (version,))
                    else:
                        logger.error(f"❌ 마이그레이션 실패 (버전 {version}): {e}")

        await self.conn.commit()

    async def log_action(self, user_id: int, action_type: str, details: str):
        """중요 액션을 감사 로그에 기록합니다."""
        if not self.conn: return
        await self.conn.execute(
            "INSERT INTO audit_logs (user_id, action_type, details) VALUES (?, ?, ?)",
            (user_id, action_type, details)
        )
        await self.conn.commit()

    async def commit(self) -> None:
        """변경 사항을 저장합니다."""
        if self.conn:
            await self.conn.commit()

    async def execute(self, query: str, params: tuple[Any, ...] | list[Any] = ()) -> aiosqlite.Cursor | None:
        """쿼리를 실행합니다."""
        if not self.conn: return None
        return await self.conn.execute(query, params)

    async def executemany(self, query: str, params: list[tuple[Any, ...]]) -> aiosqlite.Cursor | None:
        """여러 쿼리를 한 번에 실행합니다."""
        if not self.conn: return None
        return await self.conn.executemany(query, params)

    async def close(self) -> None:
        """연결을 종료합니다."""
        if self.conn:
            await self.conn.close()

    async def get_user_data(self, user_id: int) -> tuple[int, int, int]:
        """유저의 기본 정보(코인, 낚싯대 티어, 레이팅)를 가져옵니다."""
        if not self.conn: return (0, 1, 1000)
        async with self.conn.execute("SELECT coins, rod_tier, rating FROM user_data WHERE user_id=?", (user_id,)) as cursor:
            res = await cursor.fetchone()
            if not res:
                await self.conn.execute("INSERT INTO user_data (user_id, coins, rod_tier, rating, max_stamina, stamina) VALUES (?, 0, 1, 1000, 100, 100)", (user_id,))
                await self.conn.commit()
                return (0, 1, 1000)
            return res

    async def get_user_title(self, user_id: int) -> str:
        """유저의 현재 칭호를 가져옵니다."""
        if not self.conn: return ""
        async with self.conn.execute("SELECT title FROM user_data WHERE user_id=?", (user_id,)) as cursor:
            row = await cursor.fetchone()
            return row[0] if row else ""

db = DBManager()
