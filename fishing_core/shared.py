import json
import os
import random
from datetime import timedelta, timezone

import aiofiles

from fishing_core.logger import logger

kst = timezone(timedelta(hours=9))
SUPER_ADMIN_IDS = [
    771274777443696650,
    861106310439632896,
    1478295213389774920,
    673900043912085536,
]

ADMIN_LOG_CHANNEL_ID = int(os.getenv("ADMIN_LOG_CHANNEL_ID", "0"))

# 전역 데이터 컨테이너
FISH_DATA: dict[str, any] = {}
MARKET_PRICES: dict[str, int] = {}
RECIPES: dict[str, any] = {}


async def load_json_async(file_path: str) -> dict[str, any]:
    """파일을 비동기적으로 읽어서 JSON으로 반환합니다."""
    try:
        async with aiofiles.open(file_path, encoding='utf-8') as f:
            content = await f.read()
            return json.loads(content)
    except FileNotFoundError:
        logger.warning(f"파일을 찾을 수 없습니다: {file_path}")
        return {}
    except Exception as e:
        logger.error(f"JSON 로드 중 오류 발생 ({file_path}): {e}")
        return {}

async def init_shared_data():
    """봇 시작 시 데이터를 초기화합니다."""
    # 1. 어종 데이터 로드
    base_fish = await load_json_async('fish_data.json')
    if not base_fish:
        logger.critical("기본 어종 데이터(fish_data.json) 로드 실패!")
    
    special_fish = await load_json_async('special_fish.json')
    
    FISH_DATA.clear()
    FISH_DATA.update(base_fish)
    FISH_DATA.update(special_fish)
    
    # 2. 시세 데이터 초기화
    MARKET_PRICES.clear()
    MARKET_PRICES.update({fish: data["price"] for fish, data in FISH_DATA.items() if "price" in data})
    
    # 3. 레시피 데이터 로드
    recipes = await load_json_async('recipes.json')
    RECIPES.clear()
    RECIPES.update(recipes)
    
    logger.info("비동기 데이터 초기화 완료")

async def reload_data_async():
    """데이터를 비동기적으로 다시 로드합니다."""
    await init_shared_data()
    logger.info("데이터 리로드(비동기) 완료")

WEATHER_TYPES = ["☀️ 맑음", "☁️ 흐림", "🌧️ 비", "🌩️ 폭풍우", "🌫️ 안개"]
# 문자열 대신 딕셔너리로 상태를 담아 모듈간 참조 유지
env_state = {
    "CURRENT_WEATHER": "☀️ 맑음"
}

def update_weather_randomly():
    """날씨 업데이트: 맑음(40%), 흐림(25%), 비(20%), 폭풍우(5%), 안개(10%) 확률"""
    new_weather = random.choices(WEATHER_TYPES, weights=[40, 25, 20, 5, 10], k=1)[0]
    env_state["CURRENT_WEATHER"] = new_weather
    logger.info(f"날씨가 변경되었습니다: {new_weather}")
    return new_weather

def get_element_multiplier(atk_elem, def_elem):
    if atk_elem == "무속성" or def_elem == "무속성":
        return 1.0
    if atk_elem == "표층" and def_elem == "심해":
        return 1.5
    if atk_elem == "심해" and def_elem == "암초":
        return 1.5
    if atk_elem == "암초" and def_elem == "표층":
        return 1.5
    if atk_elem == def_elem:
        return 1.0
    return 0.8
