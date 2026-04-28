import asyncio
import contextlib
import contextvars
from typing import Any

import aiosqlite

from .logger import logger

# 트랜잭션 중첩 상태를 추적하기 위한 ContextVar
_transaction_depth: contextvars.ContextVar[int] = contextvars.ContextVar("_transaction_depth", default=0)

class DBManager:
    """데이터베이스 관리를 담당하는 클래스입니다. aiosqlite를 사용하여 비동기적으로 작동합니다."""

    def __init__(self) -> None:
        self.conn: aiosqlite.Connection | None = None
        self._lock = asyncio.Lock()

    @contextlib.asynccontextmanager
    async def transaction(self):
        """
        트랜잭션을 관리하는 컨텍스트 매니저입니다.
        중첩된 트랜잭션 호출 시 SAVEPOINT를 사용하여 처리하거나, 
        동일 태스크 내에서는 락을 건너뛰고 최상위에서만 BEGIN/COMMIT을 수행합니다.
        """
        if not self.conn:
            yield
            return

        depth = _transaction_depth.get()
        token = _transaction_depth.set(depth + 1)

        try:
            if depth == 0:
                # 최상위 트랜잭션: 락 획득 및 BEGIN
                async with self._lock:
                    await self.conn.execute("BEGIN TRANSACTION")
                    try:
                        yield
                        await self.conn.commit()
                    except Exception as e:
                        await self.conn.rollback()
                        logger.error(f"⚠️ 트랜잭션 오류로 롤백됨: {e}")
                        raise
            else:
                # 중첩된 트랜잭션: 별도의 락 없이 SAVEPOINT 사용 (또는 그냥 yield)
                # 여기서는 안전하게 SAVEPOINT를 사용하여 중첩 롤백이 가능하게 합니다.
                sp_name = f"sp_{depth}"
                await self.conn.execute(f"SAVEPOINT {sp_name}")
                try:
                    yield
                    await self.conn.execute(f"RELEASE SAVEPOINT {sp_name}")
                except Exception as e:
                    await self.conn.execute(f"ROLLBACK TO SAVEPOINT {sp_name}")
                    logger.warning(f"⚠️ 중첩 트랜잭션({sp_name}) 롤백됨: {e}")
                    raise
        finally:
            _transaction_depth.reset(token)

    async def init_db(self) -> None:
        """데이터베이스 연결을 초기화하고 마이그레이션을 수행합니다."""
        # isolation_level=None으로 설정하여 트랜잭션을 수동으로 완벽하게 제어합니다.
        # (기본값은 ""이며, 이는 DML 실행 시 자동으로 트랜잭션을 시작하여 'cannot start a transaction...' 에러를 유발할 수 있음)
        self.conn = await aiosqlite.connect('fishing_rpg.db', isolation_level=None)

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
        migrations = [
            (1, "CREATE TABLE IF NOT EXISTS user_data (user_id INTEGER PRIMARY KEY, coins INTEGER DEFAULT 0, rod_tier INTEGER DEFAULT 1, rating INTEGER DEFAULT 1000)"),
            (2, "CREATE TABLE IF NOT EXISTS inventory (user_id INTEGER, item_name TEXT, amount INTEGER DEFAULT 0, PRIMARY KEY (user_id, item_name))"),
            (3, "CREATE TABLE IF NOT EXISTS active_buffs (user_id INTEGER, buff_type TEXT, end_time TEXT, PRIMARY KEY (user_id, buff_type))"),
            (4, "CREATE TABLE IF NOT EXISTS fish_dex (user_id INTEGER, item_name TEXT, PRIMARY KEY (user_id, item_name))"),
            (5, "CREATE TABLE IF NOT EXISTS aquarium (user_id INTEGER, item_name TEXT, amount INTEGER DEFAULT 1, PRIMARY KEY (user_id, item_name))"),
            (6, "CREATE TABLE IF NOT EXISTS market_sales (item_name TEXT PRIMARY KEY, amount_sold INTEGER DEFAULT 0)"),
            (7, "CREATE TABLE IF NOT EXISTS fish_records (user_id INTEGER, item_name TEXT, max_size REAL DEFAULT 0.0, PRIMARY KEY (user_id, item_name))"),
            (8, "CREATE TABLE IF NOT EXISTS fish_info (item_name TEXT PRIMARY KEY, grade TEXT, price INTEGER, prob REAL, element TEXT, power INTEGER DEFAULT 0, description TEXT)"),
            (9, "CREATE TABLE IF NOT EXISTS recipe_info (recipe_name TEXT PRIMARY KEY, ingredients TEXT, result_item TEXT, buff_type TEXT, duration INTEGER)"),
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
            (31, "CREATE TABLE IF NOT EXISTS audit_logs (log_id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER, action_type TEXT, details TEXT, created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)"),
            (32, "CREATE TABLE IF NOT EXISTS user_achievements (user_id INTEGER, achievement_id TEXT, progress INTEGER DEFAULT 0, is_completed INTEGER DEFAULT 0, completed_at TEXT, PRIMARY KEY (user_id, achievement_id))"),
            (33, "ALTER TABLE user_data ADD COLUMN last_active TEXT DEFAULT ''"),
            (34, "ALTER TABLE user_data ADD COLUMN quest_date TEXT DEFAULT ''"),
            (35, "ALTER TABLE user_data ADD COLUMN quest_item TEXT DEFAULT ''"),
            (36, "ALTER TABLE user_data ADD COLUMN quest_amount INTEGER DEFAULT 0"),
            (37, "ALTER TABLE user_data ADD COLUMN quest_reward INTEGER DEFAULT 0"),
            (38, "ALTER TABLE user_data ADD COLUMN quest_is_cleared INTEGER DEFAULT 0"),
            (39, "ALTER TABLE user_data ADD COLUMN last_farm_harvest TEXT DEFAULT ''"),
            (40, "ALTER TABLE user_data ADD COLUMN dex_rewards TEXT DEFAULT '{}'"),
            (41, "ALTER TABLE user_data ADD COLUMN aquarium_slots INTEGER DEFAULT 5"),
            (42, "ALTER TABLE user_data ADD COLUMN peace_mode INTEGER DEFAULT 0"),
            (43, "ALTER TABLE user_data ADD COLUMN peace_cooldown TEXT DEFAULT ''"),
            (44, "ALTER TABLE user_data ADD COLUMN guard_fish TEXT DEFAULT ''"),
            (45, "ALTER TABLE user_data ADD COLUMN last_free_rest TEXT DEFAULT ''"),
            (46, "ALTER TABLE user_data ADD COLUMN pvp_shield_date TEXT DEFAULT ''"),
            (47, "ALTER TABLE user_data ADD COLUMN username TEXT DEFAULT ''"),
            (48, "CREATE TABLE IF NOT EXISTS admin_sessions (token TEXT PRIMARY KEY, created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)"),
            (49, "CREATE TABLE IF NOT EXISTS market_prices (item_name TEXT PRIMARY KEY, current_price INTEGER DEFAULT 0)"),
            (50, "CREATE TABLE IF NOT EXISTS stats_history (id INTEGER PRIMARY KEY AUTOINCREMENT, recorded_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP, total_users INTEGER, total_coins INTEGER, avg_fish_price INTEGER)"),
            (51, "ALTER TABLE user_data ADD COLUMN visited_regions TEXT DEFAULT '[]'"),
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
                    if "duplicate" in str(e).lower() or "already exists" in str(e).lower():
                        await self.conn.execute("INSERT OR IGNORE INTO migrations (version) VALUES (?)", (version,))
                    else:
                        logger.error(f"❌ 마이그레이션 실패 (버전 {version}): {e}")

        await self.conn.commit()

    async def log_action(self, user_id: int, action_type: str, details: str):
        """중요 액션을 감사 로그에 기록합니다."""
        if not self.conn: return
        # 외부에서 트랜잭션 중일 수 있으므로 commit()을 호출하지 않거나 수동 제어
        await self.conn.execute(
            "INSERT INTO audit_logs (user_id, action_type, details) VALUES (?, ?, ?)",
            (user_id, action_type, details)
        )
        # 트랜잭션 외부인 경우에만 커밋 (isolation_level=None 이므로 수동 커밋 필요)
        if _transaction_depth.get() == 0:
            await self.conn.commit()

    async def commit(self) -> None:
        """변경 사항을 저장합니다."""
        if self.conn:
            await self.conn.commit()

    async def execute(self, query: str, params: tuple[Any, ...] | list[Any] = ()) -> aiosqlite.Cursor | None:
        """쿼리를 실행합니다."""
        if not self.conn: return None
        res = await self.conn.execute(query, params)
        if _transaction_depth.get() == 0:
            await self.conn.commit()
        return res

    async def executemany(self, query: str, params: list[tuple[Any, ...]]) -> aiosqlite.Cursor | None:
        """여러 쿼리를 한 번에 실행합니다."""
        if not self.conn: return None
        res = await self.conn.executemany(query, params)
        if _transaction_depth.get() == 0:
            await self.conn.commit()
        return res

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
                # isolation_level=None이므로 트랜잭션 처리가 중요함
                async with self.transaction():
                    await self.conn.execute("INSERT INTO user_data (user_id, coins, rod_tier, rating, max_stamina, stamina) VALUES (?, 0, 1, 1000, 150, 150)", (user_id,))
                return (0, 1, 1000)
            return res

    async def get_user_title(self, user_id: int) -> str:
        """유저의 현재 칭호를 가져옵니다."""
        if not self.conn: return ""
        async with self.conn.execute("SELECT title FROM user_data WHERE user_id=?", (user_id,)) as cursor:
            row = await cursor.fetchone()
            return row[0] if row else ""

    async def get_full_user_data(self, user_id: int) -> dict[str, Any]:
        """유저의 모든 주요 정보를 딕셔너리 형태로 가져옵니다."""
        if not self.conn: return {}
        
        # 유저가 없으면 생성
        await self.get_user_data(user_id)
        
        query = "SELECT coins, rod_tier, rating, boat_tier, stamina, max_stamina, current_region, title FROM user_data WHERE user_id=?"
        async with self.conn.execute(query, (user_id,)) as cursor:
            row = await cursor.fetchone()
            if not row: return {}
            
            return {
                "coins": row[0],
                "rod_tier": row[1],
                "rating": row[2],
                "boat_tier": row[3],
                "stamina": row[4],
                "max_stamina": row[5],
                "region": row[6],
                "title": row[7]
            }

    async def modify_inventory(self, user_id: int, item_name: str, amount: int) -> bool:
        """인벤토리 아이템 수량을 변경합니다. (음수 가능)"""
        if not self.conn: return False
        
        # isolation_level=None 대응: 내부 작업이므로 상위 트랜잭션이 없을 경우 자동 커밋되도록 설계됨 (execute/executemany 참고)
        if amount > 0:
            await self.execute(
                "INSERT INTO inventory (user_id, item_name, amount) VALUES (?, ?, ?) "
                "ON CONFLICT(user_id, item_name) DO UPDATE SET amount = amount + ?",
                (user_id, item_name, amount, amount)
            )
        elif amount < 0:
            # 수량 확인 후 차감
            async with self.conn.execute("SELECT amount FROM inventory WHERE user_id=? AND item_name=?", (user_id, item_name)) as cursor:
                row = await cursor.fetchone()
                if not row or row[0] < abs(amount):
                    return False
                
                await self.execute(
                    "UPDATE inventory SET amount = amount + ? WHERE user_id=? AND item_name=?",
                    (amount, user_id, item_name)
                )
                # 0개 이하면 삭제
                await self.execute("DELETE FROM inventory WHERE user_id=? AND item_name=? AND amount <= 0", (user_id, item_name))
        
        return True

db = DBManager()
