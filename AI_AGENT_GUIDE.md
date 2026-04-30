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

### ⚠️ 중첩 트랜잭션 주의 (Nested Transactions)
`cannot start a transaction within a transaction` 에러를 방지하기 위해 중첩된 `async with db.transaction():` 호출에 유의해야 합니다. 상점 대량 구매나 레이드 전투 등 여러 서비스 계층을 넘나들며 복잡한 쓰기 작업이 발생하는 경우, 상위 계층에서 하나의 트랜잭션으로 묶고 `SAVEPOINT` 등 안전한 방식을 통해 원자성과 데이터 무결성을 보장해야 합니다.

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

- **작업 완료 후 자동 푸시(Push)**: 코드를 수정하거나 문서를 업데이트하는 등 모든 작업이 완료되면, 사용자가 명시적으로 지시하지 않더라도 **반드시 깃허브(GitHub)에 커밋 및 푸시(git add, commit, push)**를 진행하십시오.
- **커밋 컨벤션**: 변경 사항을 깃허브에 푸시할 때는 아래와 같은 관례를 따릅니다:
  - `feat: 새로운 기능 추가`
  - `fix: 버그 수정`
  - `refactor: 리팩토링 (기능 변화 없음)`
  - `docs: 문서 수정`
- **에러 핸들링**: 모든 명령어 처리부에는 적절한 예외 처리를 추가하여, 에러 발생 시 `ephemeral=True` 옵션으로 유저에게 피드백이 전달되도록 하십시오.
- **테스트**: 코드를 수정한 후에는 가급적 관련된 명령어들을 시뮬레이션하거나 로직을 점검하여 순환 참조(Circular Import)가 발생하지 않는지 확인하십시오. (`Cog -> Service -> DB` 방향을 지향)

*작업을 시작하기 전, 이 가이드라인을 완벽히 숙지했음을 기반으로 코드를 작성해 주십시오.*

---

## 7. ⚖️ 게임 경제 및 밸런스 설계 원칙

새로운 기능을 추가하거나 기존 시스템을 변경할 때는 다음의 밸런스 원칙을 엄격하게 준수해야 합니다.

- **제로섬(Zero-Sum) 또는 인플레이션 방어**: PvP 레이팅, 재화 생산 시스템 등에서 무한히 재화/점수가 복사(창조)되는 로직을 피하십시오.
  - *예시*: PvP 레이팅은 승자가 얻는 점수만큼 패자가 잃거나(ELO 기반), 총합이 일정하게 유지되어야 합니다.
- **복리 이자 효과(Compounding Interest) 금지**: 매일 '보유 금액의 N%' 비율로 코인이나 아이템을 지급하는 스킬/효과를 절대 도입하지 마십시오. 이는 하이퍼 인플레이션을 유발합니다. 대신 '고정 금액 지급' 방식으로 설계하십시오.
- **성장 곡선의 완만화(Polynomial vs Exponential)**: 강화 비용이나 필요 경험치 공식을 설계할 때 기하급수적(Exponential) 스케일링(`1.3^n`)은 후반부 밸런스 붕괴를 초래합니다. 상한선(Cap)이 존재하는 완만한 지수 함수나 다항식(`n^2 * base_cost`)을 권장합니다.
- **아이템 간 가성비(ROI) 점검**: 상위 아이템/기능이 하위 아이템의 존재 가치를 완전히 소멸시키지 않도록, 비용 효율(가성비)과 쿨타임 등을 신중하게 설정하십시오. (예: 저렴한 전체 스태미나 회복과 비싼 고정량 회복 아이템의 밸런스 조절)
- **대량 거래 어뷰징 방지(Slippage)**: 상점에서 아이템을 대량으로 판매/구매할 때 시세 차익을 악용하는 것을 막기 위해, 시장 슬립피지(Slippage) 시스템이나 대량 거래 패널티를 도입하여 경제 안정성을 보장하십시오.

---

## 8. 🎯 개발 및 유지보수 작업 우선순위 원칙

에이전트가 코드를 수정하거나 새로운 기능을 개발할 때는 다음의 우선순위를 정해서 수행하십시오.

1. **1순위 (경제 시스템 및 치명적 버그)**: 코인/재화가 비정상적으로 복사되거나 경제를 파괴할 수 있는 밸런스 문제, 트랜잭션 충돌 등 시스템의 근간을 흔드는 버그를 가장 먼저 해결하십시오.
2. **2순위 (경쟁 시스템 및 어뷰징 방지)**: PvP 레이팅 인플레이션, 시장 시세 조작(슬립피지 부재) 등 유저 간의 공정성을 해치는 메커니즘을 수정하십시오.
3. **3순위 (콘텐츠 및 세부 로직)**: 특수 물고기의 패시브 스킬 구현, UI/UX 개선, 텍스트 수정 등은 핵심 시스템이 안정화된 이후 마지막 단계로 진행하십시오.
4. **4순위 (신규 유저 온보딩 및 리텐션)**: 진입 장벽을 낮추고 초반 몰입도를 높이는 튜토리얼 설계 및 점진적 시스템 해금을 통해 신규 유저 경험(NUX)을 지속적으로 개선하십시오.

---

## 9. 🛠️ 코드 스타일 및 품질 (Code Quality)

- **파이썬 내장 함수/타입 섀도잉(Shadowing) 방지**: 변수명이나 파라미터 이름으로 파이썬 내장 키워드(`id`, `type`, `list`, `dict`, `max`, `min` 등)를 절대 사용하지 마십시오. (예: `id` 대신 `user_id` 혹은 `item_id`, `type` 대신 `item_type` 등으로 구체적으로 명명)
- **순환 참조(Circular Import) 방지**: `views_v2.py`와 같은 UI 계층이나 서비스 계층 간 상호 참조 시 순환 참조가 흔히 발생합니다. 타입 힌팅을 위한 임포트는 `from typing import TYPE_CHECKING` 패턴을 활용하고, 실행 시점에 필요한 경우에만 메서드/함수 내부에서 지연 임포트(Lazy Import)를 사용하십시오.
- **타입 힌트 의무화**: 가독성과 유지보수성 향상 및 런타임 에러 사전 방지를 위해 함수와 클래스, 메서드에 적절한 타입 힌트(Type Hints)를 적극적으로 적용하십시오.

---

## 10. 🔒 보안, 설정 및 성능 최적화

- **환경 변수(.env) 활용**: 봇 토큰, 환경 설정값, API 키 등 민감한 정보는 코드 내에 절대 하드코딩하지 말고 환경 변수로 분리하여 관리해야 합니다.
- **캐싱(Caching)을 통한 성능 최적화**: 매번 DB를 조회할 필요가 없는 정적/준정적 데이터는 캐싱 시스템을 도입하거나 `fishing_core/shared.py`의 글로벌 메모리 공간을 활용하여 병목 현상을 방지하십시오.
- **안전한 서비스 분리**: 다른 봇(예: 학교 봇 등)과 함께 운영되는 환경인 경우, 크로스 서비스 간 간섭이 발생하지 않도록 모듈화하고 독립적인 데이터/환경 변수 컨텍스트를 유지하십시오.

---

## 11. 🧹 코드 품질 및 린팅 (Linting)

에이전트는 코드를 작성하고 푸시하기 전에 반드시 코드 스타일과 잠재적 에러를 점검해야 합니다.

- **Ruff 사용**: 이 프로젝트는 `ruff`를 사용하여 코드 스타일을 유지하고 린팅을 수행합니다. 
- **체크 및 수정**: 작업을 완료한 후 푸시하기 전, 반드시 다음 명령어를 실행하여 오류가 없는지 확인하십시오:
  ```powershell
  ruff check .
  ```
- **자동 수정**: `ruff check --fix .` 명령어를 통해 자동으로 수정 가능한 항목들을 처리할 수 있습니다. 
- **린트 에러 무시 금지**: 린트 에러가 발생한 채로 푸시하면 배포 파이프라인에서 오류가 발생할 수 있습니다. 반드시 에러를 해결한 후 푸시하십시오.
- **삼항 연산자 활용 (SIM108)**: 단순한 `if-else` 블록은 `new_price = A if condition else B`와 같은 삼항 연산자를 사용하여 코드를 간결하게 유지하십시오.
