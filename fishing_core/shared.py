import json
import datetime
import random

kst = datetime.timezone(datetime.timedelta(hours=9))
SUPER_ADMIN_IDS = [
    771274777443696650,  
    861106310439632896,  
    1478295213389774920,
    673900043912085536
]

def load_fish_data():
    try:
        with open('fish_data.json', 'r', encoding='utf-8') as f:
            return json.load(f)
    except FileNotFoundError:
        print("❌ 오류: fish_data.json 파일이 없습니다! 봇이 종료됩니다.")
        exit()

def load_recipes():
    try:
        with open('recipes.json', 'r', encoding='utf-8') as f:
            return json.load(f)
    except FileNotFoundError:
        return {}

def load_special_fish_data():
    try:
        with open('special_fish.json', 'r', encoding='utf-8') as f:
            return json.load(f)
    except FileNotFoundError:
        return {}

FISH_DATA = load_fish_data()
FISH_DATA.update(load_special_fish_data())

MARKET_PRICES = {fish: data["price"] for fish, data in FISH_DATA.items() if "price" in data}
RECIPES = load_recipes()

WEATHER_TYPES = ["☀️ 맑음", "☁️ 흐림", "🌧️ 비", "🌩️ 폭풍우", "🌫️ 안개"]
# 문자열 대신 딕셔너리로 상태를 담아 모듈간 참조 유지
env_state = {
    "CURRENT_WEATHER": "☀️ 맑음"
}

def reload_data():
    """데이터 동기화: 기존 참조를 유지한 채 데이터만 덮어씌움"""
    new_fish = load_fish_data()
    new_fish.update(load_special_fish_data())
    
    FISH_DATA.clear()
    FISH_DATA.update(new_fish)

    MARKET_PRICES.clear()
    MARKET_PRICES.update({fish: data["price"] for fish, data in FISH_DATA.items() if "price" in data})

    new_recipes = load_recipes()
    RECIPES.clear()
    RECIPES.update(new_recipes)

def update_weather_randomly():
    """날씨 업데이트: 맑음(40%), 흐림(25%), 비(20%), 폭풍우(5%), 안개(10%) 확률"""
    env_state["CURRENT_WEATHER"] = random.choices(WEATHER_TYPES, weights=[40, 25, 20, 5, 10], k=1)[0]
    return env_state["CURRENT_WEATHER"]

def get_element_multiplier(atk_elem, def_elem):
    if atk_elem == "무속성" or def_elem == "무속성": return 1.0
    if atk_elem == "표층" and def_elem == "심해": return 1.5
    if atk_elem == "심해" and def_elem == "암초": return 1.5
    if atk_elem == "암초" and def_elem == "표층": return 1.5
    if atk_elem == def_elem: return 1.0
    return 0.8 
