# 🤖 낚시 RPG AI 에이전트 작업 가이드라인

이 문서는 낚시 RPG(Fishing RPG) 봇의 코드베이스에서 작업하는 AI 에이전트를 위한 핵심 지침서입니다. 코드를 수정하거나 기능을 추가하기 전에 **반드시 이 문서를 끝까지 읽고** 명시된 아키텍처 패턴, 파일 규칙, 데이터베이스 접근 원칙을 준수하여 런타임 에러와 데이터 손실을 방지하십시오.

---

## 1. 프로젝트 구조 및 파일 역할

로직을 수정하기 전에 해당 기능이 어느 계층에 속하는지 파악하십시오:

- **`fishing_cogs/`**: 디스코드 봇 명령어(`Cog` 클래스)가 위치합니다. **여기에는 비즈니스 로직을 최소화하십시오.** 복잡한 계산이나 확률 로직은 `services/`로 위임합니다.
- **`fishing_core/services/`**: 핵심 비즈니스 로직(예: `FishingService`, `AchievementService`)이 위치합니다. 새로운 게임 시스템은 상태를 가지지 않는(stateless) 클래스 메서드 형태로 이곳에 추가하십시오.
- **`fishing_core/database.py`**: 비동기 데이터베이스 통신을 담당하는 중앙 매니저(`DBManager`)입니다. **절대로 이 파일을 우회하여 `sqlite3`나 `aiosqlite`를 직접 열지 마십시오.**
- **`fishing_core/views_v2.py`**: 디스코드 UI 컴포넌트(버튼, 선택 메뉴, 모달)가 위치합니다. 기존 `views.py`가 아닌 **`v2`** 버전을 표준으로 사용합니다.
- **`fishing_core/utils.py`**: 도우미 함수, 자동완성(Autocomplete) 로직, UI 일관성을 위한 `EmbedFactory` 등이 포함되어 있습니다.
- **`fishing_core/shared.py`**: 글로벌 상태 변수(`env_state`), 시간대 설정(`kst`), 정적 게임 데이터(`FISH_DATA`) 등이 포함되어 있습니다.

---

## 2. 🚨 데이터베이스 트랜잭션 규칙 (매우 중요)

이 프로젝트는 중첩 트랜잭션을 안전하게 처리하기 위해 래핑된 커스텀 `DBManager`를 사용합니다. 이를 제대로 지키지 않으면 `cannot start a transaction within a transaction` 에러나 치명적인 데이터 손실이 발생합니다.

### ✅ DO: `async with db.transaction():` 사용하기
여러 개의 쿼리가 실행되거나, 읽은 후 쓰기(Read-then-Write) 작업이 발생하는 모든 로직은 반드시 트랜잭션 컨텍스트 매니저로 감싸야 합니다.

```python
from fishing_core.database import db

# 올바른 트랜잭션 처리 예시
async with db.transaction():
    # 1. 읽기
    async with db.conn.execute("SELECT stamina FROM user_data WHERE user_id=?", (user_id,)) as cursor:
        stamina = (await cursor.fetchone())[0]
        
    if stamina < cost:
        raise ValueError("행동력이 부족합니다.")
        
    # 2. 쓰기
    await db.execute("UPDATE user_data SET stamina = stamina - ? WHERE user_id=?", (cost, user_id))
    await db.modify_inventory(user_id, "아이템이름", 1)
```

### ❌ DON'T: `await db.commit()` 직접 호출 금지
`db.transaction()` 블록은 에러가 없으면 자동으로 커밋하고, 예외 발생 시 자동으로 롤백합니다. **비즈니스 로직 내부에서 명시적으로 커밋을 호출하면 트랜잭션의 원자성이 깨지고 격리 수준 오류가 발생합니다.**

### 💡 권장: 제공되는 헬퍼 함수 사용
인벤토리 수정 시 직접 UPDATE 쿼리를 짜지 말고 다음 함수를 적극 활용하십시오:
`await db.modify_inventory(user_id, item_name, amount)`

---

## 3. 정적 데이터 (JSON 파일) 관리

물고기 정보(`fish_data.json`), 도감(`collections.json`), 레시피(`recipes.json`) 등은 JSON 형태의 정적 파일로 관리됩니다.

- 봇 구동 시 `fishing_core/shared.py`에서 해당 JSON 파일들을 메모리로 불러와 딕셔너리로 캐싱합니다.
- 게임 중 데이터를 읽어올 때는 파일을 직접 열지 말고, `from fishing_core.shared import FISH_DATA`와 같이 임포트하여 사용하십시오.
- JSON 데이터를 수정(Write)해야 하는 로직은 가급적 지양하고, 동적인 데이터는 반드시 SQLite 데이터베이스(`user_data`, `inventory` 등)를 이용하십시오.

---

## 4. 디스코드 UI 및 Embed 표준화

유저에게 보여지는 모든 텍스트 포맷과 Embed 메시지는 프로젝트의 일관성을 유지해야 합니다.

- **Embed 생성**: `fishing_core.utils`의 `EmbedFactory`를 사용하십시오.
- **사용 가능한 스타일**: `info`, `warning`, `error`, `success`

```python
from fishing_core.utils import EmbedFactory

embed = EmbedFactory.build(title="🎣 낚시 결과", description="성공적으로 낚았습니다!", style="success")
embed.add_field(name="획득", value="전설의 물고기")
await interaction.response.send_message(embed=embed)
```

- **UI 상호작용 지연 (Defer)**: DB 처리가 오래 걸릴 것으로 예상되는 작업(ex. 상점 구매, 대규모 쿼리) 전에는 반드시 `await interaction.response.defer(ephemeral=True/False)`를 호출하여 타임아웃 에러(3초 제한)를 방지하십시오.

---

## 5. 관심사의 분리 (Service 계층 적극 활용)

- `fishing_cogs/` 내부에 위치한 명령어 함수 안에 수백 줄에 달하는 계산 로직이나 조건문을 넣지 마십시오.
- 새로운 시스템(전투, 강화, 크래프팅 등)을 추가할 때는 `fishing_core/services/`에 관련 서비스 클래스를 만들고, Cog에서는 그 메서드만 호출하도록 설계해야 합니다.
- **예시 참조**: `fishing_core/services/fishing_service.py`의 `FishingService.calculate_fish_probabilities()`를 확인해 보세요.

---

## 6. Git 및 배포 가이드

- **에러 핸들링**: 모든 명령어 처리부에는 적절한 예외 처리를 추가하여, 에러 발생 시 `ephemeral=True` 옵션으로 유저에게 피드백이 전달되도록 하십시오.
- **테스트**: 코드를 수정한 후에는 가급적 관련된 명령어들을 시뮬레이션하거나 로직을 점검하여 순환 참조(Circular Import)가 발생하지 않는지 확인하십시오. (`Cog -> Service -> DB` 방향을 지향)
- **커밋 컨벤션**: 변경 사항을 깃허브에 푸시할 때는 아래와 같은 관례를 따릅니다:
  - `feat: 새로운 기능 추가`
  - `fix: 버그 수정`
  - `refactor: 리팩토링 (기능 변화 없음)`
  - `docs: 문서 수정`

*작업을 시작하기 전, 이 가이드라인을 완벽히 숙지했음을 기반으로 코드를 작성해 주십시오.*
