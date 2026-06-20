import asyncio
import logging
import json
import os
import random
import time
import io
import urllib.request
import sqlite3
import uuid
from aiogram import Bot, Dispatcher, F, BaseMiddleware
from aiogram.types import (
    Message, 
    CallbackQuery, 
    ReplyKeyboardMarkup, 
    KeyboardButton,
    InlineKeyboardMarkup,
    InlineKeyboardButton,
    InputMediaPhoto,
    BufferedInputFile,
    BotCommand
)
from aiogram.filters import CommandStart, Command, StateFilter
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.exceptions import TelegramBadRequest

# ==========================================
# НАСТРОЙКА PIL (ДЛЯ ОТРИСОВКИ БОЯ)
# ==========================================
try:
    from PIL import Image, ImageDraw, ImageFont
    HAS_PIL = True
except ImportError:
    logging.warning("Библиотека Pillow не найдена! Установите её: pip install Pillow")
    HAS_PIL = False

FONT_FILE = "bot_font.ttf"
FONT_URL = "https://github.com/googlefonts/roboto/raw/main/src/hinted/Roboto-Bold.ttf"

if HAS_PIL and not os.path.exists(FONT_FILE):
    try:
        urllib.request.urlretrieve(FONT_URL, FONT_FILE)
    except Exception as e:
        logging.error(f"Не удалось скачать шрифт: {e}")

# ==========================================
# 1. КОНФИГУРАЦИЯ БОТА И БД
# ==========================================
# ⚠️ ОБЯЗАТЕЛЬНО СМЕНИТЕ ТОКЕН В ПРОДАКШЕНЕ
TOKEN = "8403453180:AAEyAq5LG8CUQaxwNa1A7Fp7JhvDaS6tdRc"
MAIN_ADMIN_ID = "5341904332"

DB_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "game_data.db")

admins_db = {MAIN_ADMIN_ID}
rarities_db = ["Обычная", "Редкая", "Эпическая", "Легендарная"] 
units_db = {}    
unit_id_counter = 1
mobs_db = {}
mob_id_counter = 1
user_inventory = {}  
user_equipped = {}   
user_balances = {} 
user_free_crate_times = {} 
currencies_db = ["💰 Монеты", "💎 Гемы"] 
maps_db = {}       
map_id_counter = 1
crates_db = {}     
crate_id_counter = 1

bot_settings = {
    "coins_per_damage": 0.5,
    "turn_time_skip": 5,
    "turn_time_noskip": 10,
    "free_crate_cooldown": 3600 * 4 # 4 часа
}

ATTACK_TYPES = ["Одиночный", "Сплеш", "АОЕ", "Саппорт", "Ферма", "Замедление"]

active_battles = {}
battle_id_counter = 1
user_to_battle = {}
active_tasks = {}
panel_owners = {} 
image_cache = {}
lobbies = {} # Упрощенная система каток вместо elevators

# ==========================================
# 2. СИСТЕМА SQLITE
# ==========================================
def init_db():
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute("CREATE TABLE IF NOT EXISTS storage (key TEXT PRIMARY KEY, data TEXT)")
    conn.commit()
    conn.close()

def db_get(key, default=None):
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute("SELECT data FROM storage WHERE key=?", (key,))
    row = c.fetchone()
    conn.close()
    return json.loads(row[0]) if row else default

def db_set(key, data):
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute("INSERT OR REPLACE INTO storage (key, data) VALUES (?, ?)", (key, json.dumps(data, ensure_ascii=False)))
    conn.commit()
    conn.close()

def load_data():
    global admins_db, rarities_db, units_db, unit_id_counter, user_inventory, user_equipped
    global mobs_db, mob_id_counter, currencies_db, maps_db, map_id_counter
    global user_balances, crates_db, crate_id_counter, user_free_crate_times, bot_settings
    
    init_db()
    data = db_get("full_state", {})
    if not data: return
        
    try:
        admins_db = set(data.get("admins_db", [MAIN_ADMIN_ID]))
        if MAIN_ADMIN_ID not in admins_db: admins_db.add(MAIN_ADMIN_ID)
        rarities_db = data.get("rarities_db", ["Обычная", "Редкая"])
        
        loaded_settings = data.get("bot_settings", {})
        bot_settings.update(loaded_settings)
        
        units_db = data.get("units_db", {})
        unit_id_counter = data.get("unit_id_counter", 1)
        mobs_db = data.get("mobs_db", {})
        mob_id_counter = data.get("mob_id_counter", 1)
        currencies_db = data.get("currencies_db", ["💰 Монеты", "💎 Гемы"])
        maps_db = data.get("maps_db", {})
        map_id_counter = data.get("map_id_counter", 1)
        crates_db = data.get("crates_db", {})
        crate_id_counter = data.get("crate_id_counter", 1)
        
        user_inventory = {str(k): set(v) for k, v in data.get("user_inventory", {}).items()}
        user_equipped = {str(k): list(v) for k, v in data.get("user_equipped", {}).items()}
        user_balances = data.get("user_balances", {})
        user_free_crate_times = {str(k): float(v) for k, v in data.get("user_free_crate_times", {}).items()}
    except Exception as e:
        logging.error(f"⚠️ Ошибка загрузки из SQLite: {e}")

def save_data():
    data = {
        "admins_db": list(admins_db),
        "rarities_db": rarities_db,
        "units_db": units_db,
        "unit_id_counter": unit_id_counter,
        "mobs_db": mobs_db,
        "mob_id_counter": mob_id_counter,
        "currencies_db": currencies_db,
        "maps_db": maps_db,
        "map_id_counter": map_id_counter,
        "crates_db": crates_db,
        "crate_id_counter": crate_id_counter,
        "user_inventory": {str(k): list(v) for k, v in user_inventory.items()},
        "user_equipped": {str(k): list(v) for k, v in user_equipped.items()},
        "user_balances": user_balances,
        "user_free_crate_times": user_free_crate_times,
        "bot_settings": bot_settings
    }
    db_set("full_state", data)

# ==========================================
# 3. ЛОГИКА ЮНИТОВ И СТАТИСТИКИ
# ==========================================
def get_unit_stats(uid: str, is_shiny: bool = False) -> dict | None:
    u = units_db.get(str(uid))
    if not u: return None
    if not is_shiny: return u
    
    su = u.copy()
    su["name"] = f"✨ {su.get('name', f'Юнит №{uid}')} ✨"
    if "damage" in su: su["damage"] = round(su["damage"] * 1.25, 2)
    if "income" in su: su["income"] = int(su["income"] * 1.10)
    if "cd_boost" in su: su["cd_boost"] = round(su["cd_boost"] * 0.90, 2)
    if "dmg_boost" in su: su["dmg_boost"] = round(su["dmg_boost"] * 1.10, 2)
    if "deploy_cost" in su: su["deploy_cost"] = int(su["deploy_cost"] * 1.20)
    if "slow_percent" in su: su["slow_percent"] = min(90, int(su["slow_percent"] * 1.2)) # Кап замедления 90%
    return su

def format_unit_stats(u):
    utypes = u.get("unit_types", [])
    types_str = ", ".join(utypes) if utypes else "Нет класса"
    
    res = f"├ 🏷 Классы: <b>{types_str}</b>\n├ 💰 Цена: {u.get('deploy_cost', 50)} | 🛑 Лимит: {u.get('supply_limit', '∞')}\n"
    
    if any(t in utypes for t in ["Одиночный", "Сплеш", "АОЕ", "Замедление"]):
        res += f"├ ⚔️ Атака: 💥 {u.get('damage', 10)} | ⏱ КД: {u.get('cd', 1.0)}с\n"
    if "Саппорт" in utypes:
        res += f"├ ✨ Саппорт: ⏱ КД x{u.get('cd_boost', 1.0)} | 💥 Урон x{u.get('dmg_boost', 1.0)}\n"
    if "Ферма" in utypes:
        res += f"├ 🌾 Ферма: 💰 +{u.get('income', 0)}/волна\n"
    if "Замедление" in utypes:
        res += f"├ ❄️ Замедление: {u.get('slow_percent', 20)}% на {u.get('slow_duration', 5)}с (КД: {u.get('slow_cooldown', 15)}с)\n"
        
    res += "└──────────────────"
    return res

# ==========================================
# MIDDLEWARE И СОСТОЯНИЯ
# ==========================================
class PanelMiddleware(BaseMiddleware):
    async def __call__(self, handler, event, data):
        if isinstance(event, CallbackQuery) and event.message:
            if event.message.chat.type in {"group", "supergroup"}:
                public_cb = ["lobby_", "b_dep_", "b_toggle_", "b_surr_", "free_crate"]
                if not any(event.data.startswith(p) for p in public_cb):
                    key = f"{event.message.chat.id}_{event.message.message_id}"
                    if key in panel_owners and panel_owners[key] != event.from_user.id:
                        await event.answer("🚫 Это меню вызвал другой игрок! Напишите /panel", show_alert=True)
                        return
        return await handler(event, data)

class AdminGiveCur(StatesGroup):
    select_cur, target_id, amount = State(), State(), State()

class AdminMapAdd(StatesGroup):
    photo, name, waves_count = State(), State(), State()

class AdminUnitAdd(StatesGroup):
    unit_types, photo, name, rarity, supply_limit, deploy_cost = State(), State(), State(), State(), State(), State()
    cd, damage, cd_boost, dmg_boost, income = State(), State(), State(), State(), State()
    slow_percent, slow_duration, slow_cooldown = State(), State(), State()

class AdminMobAdd(StatesGroup):
    photo, name, hp, defense_percent = State(), State(), State(), State()

# ==========================================
# UI КЛАВИАТУРЫ
# ==========================================
reply_bottom_menu = ReplyKeyboardMarkup(
    keyboard=[[KeyboardButton(text="🔙 В Главное Меню")]],
    resize_keyboard=True, is_persistent=True
)

def get_main_menu_kb(chat_type: str = "private") -> InlineKeyboardMarkup:
    kb = []
    if maps_db: kb.append([InlineKeyboardButton(text="⚔️ В бой ⚔️", callback_data="battle_select_map")])
    if crates_db: kb.append([InlineKeyboardButton(text="📦 Магазин Крейтов 📦", callback_data="crates_list")])
    if chat_type in {"group", "supergroup"}: kb.append([InlineKeyboardButton(text="🎁 Бесплатный Крейт 🎁", callback_data="free_crate")])
    kb.append([InlineKeyboardButton(text="📖 Энциклопедия", callback_data="main_index"), InlineKeyboardButton(text="🎒 Инвентарь", callback_data="main_inventory")])
    kb.append([InlineKeyboardButton(text="⚙️ Админ панель", callback_data="admin_panel")])
    return InlineKeyboardMarkup(inline_keyboard=kb)

def get_admin_panel_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="➕ Юнит", callback_data="admin_add_unit"), InlineKeyboardButton(text="➖ Юнит", callback_data="admin_del_unit")],
        [InlineKeyboardButton(text="👾 Доб. Моба", callback_data="admin_add_mob"), InlineKeyboardButton(text="🗺 Доб. Карту", callback_data="admin_add_map")],
        [InlineKeyboardButton(text="💸 Выдать Валюту (Любому) 💸", callback_data="admin_give_cur")]
    ])

def get_unit_types_kb(selected: list) -> InlineKeyboardMarkup:
    kb = [[InlineKeyboardButton(text=f"{'✅' if t in selected else '❌'} {t}", callback_data=f"toggleutype_{t}")] for t in ATTACK_TYPES]
    kb.append([InlineKeyboardButton(text="💾 Продолжить", callback_data="saveutypes")])
    return InlineKeyboardMarkup(inline_keyboard=kb)

# ==========================================
# ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ
# ==========================================
def extract_user_identifier(message: Message) -> str | None:
    if message.forward_origin and message.forward_origin.type == "user": return str(message.forward_origin.sender_user.id)
    if message.text and not message.text.startswith("/"): return message.text.strip()
    return None

def init_user_balance(user_id_str: str):
    if user_id_str not in user_balances:
        user_balances[user_id_str] = {"💰 Монеты": 100, "💎 Гемы": 0}
        save_data()

async def send_main_screen(target: Message, header_text: str | None = None):
    user_id_str = str(target.from_user.id)
    init_user_balance(user_id_str)
    bal = user_balances[user_id_str]
    bal_text = "".join(f" ├ {cur}: <b>{bal.get(cur, 0)}</b>\n" for cur in currencies_db)
    
    text = (f"👑 <b>ПРОФИЛЬ: {target.from_user.first_name or 'Игрок'}</b>\n━━━━━━━━━━━━━━━━━━\n"
            f"💳 <b>Ваши финансы:</b>\n{bal_text}━━━━━━━━━━━━━━━━━━\n"
            f"📊 <b>Коллекция:</b> {len(set(i.split(':')[0] for i in user_inventory.get(user_id_str, set())))} / {len(units_db)}\n"
            "━━━━━━━━━━━━━━━━━━\n👇 <i>Выберите действие:</i>")
    
    await target.answer(header_text or "🏠 <i>Главное меню</i>", reply_markup=reply_bottom_menu)
    msg = await target.answer(text, reply_markup=get_main_menu_kb(target.chat.type))
    if target.chat.type in {"group", "supergroup"}: panel_owners[f"{msg.chat.id}_{msg.message_id}"] = target.from_user.id

# ==========================================
# БОЕВОЙ ИНТЕРФЕЙС И РЕНДЕР
# ==========================================
def _draw_battle_image_sync(img_bytes, total_mobs_hp, current_wave, waves_total, current_turn, turns_total, slow_active):
    try:
        img = Image.open(io.BytesIO(img_bytes)).convert("RGBA")
        draw = ImageDraw.Draw(img)
        font = ImageFont.truetype(FONT_FILE, size=max(20, img.height // 12)) if os.path.exists(FONT_FILE) else ImageFont.load_default()

        def draw_outlined_text(d, txt, pos, anchor_y="center", color="white"):
            try: bbox = d.textbbox((0, 0), txt, font=font)
            except AttributeError:
                w, h = d.textsize(txt, font=font)
                bbox = (0, 0, w, h)
            w = bbox[2] - bbox[0]; h = bbox[3] - bbox[1]; x = pos[0] - w / 2
            y = pos[1] if anchor_y == "top" else (pos[1] - h / 2 if anchor_y == "center" else pos[1] - h)
            for dx in [-2, -1, 0, 1, 2]:
                for dy in [-2, -1, 0, 1, 2]:
                    if dx != 0 or dy != 0: d.text((x + dx, y + dy), txt, font=font, fill="black")
            d.text((x, y), txt, font=font, fill=color)

        draw_outlined_text(draw, f"ХП Вольны: {total_mobs_hp}", (img.width // 2, 10), anchor_y="top")
        draw_outlined_text(draw, f"Волна: {current_wave}/{waves_total}", (img.width // 2, img.height // 2), anchor_y="center")
        if slow_active: draw_outlined_text(draw, "❄️ ЗАМЕДЛЕНИЕ ❄️", (img.width // 2, img.height // 2 + 40), color="cyan")
        draw_outlined_text(draw, f"Ход: {current_turn} / {turns_total}", (img.width // 2, img.height - 10), anchor_y="bottom")
        
        out_bio = io.BytesIO()
        img.convert("RGB").save(out_bio, format="JPEG", quality=80, optimize=True)
        return out_bio.getvalue()
    except Exception: return None

async def render_battle_ui(battle_id: str, bot: Bot) -> tuple:
    battle = active_battles[battle_id]
    map_data = maps_db[battle["map_id"]]
    wave_info = map_data["waves"][battle["current_wave"] - 1]
    mob = mobs_db.get(wave_info["mob_id"], {"name": "Моб", "hp": 100, "defense_percent": 0, "photo": ""})
    
    total_mobs_hp = round(sum(battle["mobs"]), 2)
    slow_active = battle.get("wave_slow_duration", 0) > 0
    
    photo_file = mob.get("photo", "")
    if HAS_PIL and photo_file:
        if photo_file not in image_cache:
            try:
                bio = io.BytesIO()
                await bot.download(photo_file, destination=bio)
                image_cache[photo_file] = bio.getvalue()
            except Exception: pass
                
        if photo_file in image_cache:
            drawn_bytes = await asyncio.to_thread(_draw_battle_image_sync, image_cache[photo_file], total_mobs_hp, battle['current_wave'], map_data['waves_total'], battle['current_turn'], wave_info['turns'], slow_active)
            if drawn_bytes: photo_file = BufferedInputFile(drawn_bytes, filename="render.jpg")

    text = f"❤️ <b>Суммарное ХП: {total_mobs_hp}</b>\n🌊 <b>Волна: {battle['current_wave']} / {map_data['waves_total']}</b>\n\n"
    if slow_active: text += f"❄️ <b>ВОЛНА ЗАМЕДЛЕНА НА {battle.get('wave_slow', 0)}%</b> ({battle['wave_slow_duration']}с)\n"
    
    text += f"👾 <b>{mob.get('name', 'Моб')}</b> | 🛡 Защита {mob.get('defense_percent', 0)}%\n"
    for m_hp in battle["mobs"][:5]: text += f"❤️ {m_hp}/{mob['hp']}\n"
    if len(battle["mobs"]) > 5: text += f"<i>...и еще {len(battle['mobs']) - 5} шт.</i>\n"
        
    text += f"\n🏰 <b>БАЗА: {battle['base_hp']}/100</b>\n"
    for uid, p in battle["players"].items():
        text += f"• {p['name']}: 💰 {int(p['coins'])}\n"
    
    text += "\n🛡 <b>Юниты:</b>\n"
    total_dep = sum(len(p["deployed"]) for p in battle["players"].values())
    if total_dep == 0: text += "<i>Пусто</i>\n"
    else: text += f"<i>На поле {total_dep} юнитов (Атакуют...)</i>\n"
    
    timer_delay = bot_settings["turn_time_skip"] if battle["auto_skip"] else bot_settings["turn_time_noskip"]
    text += f"\n⏱ <b>Ход: {battle['current_turn']} / {wave_info['turns']}</b> (След. ход через {timer_delay}с)"
    
    skip_status = "🟢 Вкл" if battle["auto_skip"] else "🔴 Выкл"
    buttons = [[
        InlineKeyboardButton(text=f"⏩ Авто-скип ({skip_status})", callback_data=f"b_toggle_{battle_id}"),
        InlineKeyboardButton(text="🏳 Сдаться", callback_data=f"b_surr_{battle_id}")
    ]]
    return photo_file, text, InlineKeyboardMarkup(inline_keyboard=buttons)

def get_player_kb(battle_id: str, user_id_str: str) -> InlineKeyboardMarkup:
    battle = active_battles[battle_id]
    p = battle["players"][user_id_str]
    buttons, row = [], []
    
    for item_str in user_equipped.get(user_id_str, []):
        uid, is_shiny_str = item_str.split(":")
        is_shiny = (is_shiny_str == "1")
        if uid in units_db:
            unit = get_unit_stats(uid, is_shiny)
            cost = unit.get("deploy_cost", 50)
            row.append(InlineKeyboardButton(text=f"🔸 {unit.get('name')} | 💰{cost}", callback_data=f"b_dep_{battle_id}_{uid}_{is_shiny_str}"))
            if len(row) == 1: 
                buttons.append(row)
                row = []
    if row: buttons.append(row)
    return InlineKeyboardMarkup(inline_keyboard=buttons)

# ==========================================
# БОЙ И ЛОГИКА АТАКИ С МУЛЬТИКЛАССАМИ
# ==========================================
async def process_battle_turn(battle_id: str, bot: Bot):
    if battle_id not in active_battles: return
    battle = active_battles[battle_id]
    m_data = maps_db[battle["map_id"]]
    w_info = m_data["waves"][battle["current_wave"] - 1]
    m_stats = mobs_db.get(w_info["mob_id"], {"defense_percent": 0})
    m_def = m_stats.get("defense_percent", 0)
    
    best_cd_mult, best_dmg_mult = 1.0, 1.0
    
    # 1. Сбор баффов саппортов и активация Замедления
    for uid, p in battle["players"].items():
        for dep in p["deployed"]:
            u_stats = get_unit_stats(dep["uid"], dep.get("is_shiny", False))
            if not u_stats: continue
            
            utypes = u_stats.get("unit_types", [])
            if "Саппорт" in utypes:
                if float(u_stats.get("cd_boost", 1.0)) < best_cd_mult: best_cd_mult = float(u_stats.get("cd_boost", 1.0))
                if float(u_stats.get("dmg_boost", 1.0)) > best_dmg_mult: best_dmg_mult = float(u_stats.get("dmg_boost", 1.0))
                
            if "Замедление" in utypes:
                dep["slow_cd_timer"] = max(0, dep.get("slow_cd_timer", float(u_stats.get("slow_cooldown", 15))) - 1.0)
                if dep["slow_cd_timer"] <= 0 and battle["mobs"]:
                    battle["wave_slow"] = float(u_stats.get("slow_percent", 20))
                    battle["wave_slow_duration"] = float(u_stats.get("slow_duration", 5))
                    dep["slow_cd_timer"] = float(u_stats.get("slow_cooldown", 15))

    # Высчитываем бонус времени от замедления (Юниты получают больше времени на атаки в этот ход)
    effective_time_step = 1.0
    if battle.get("wave_slow_duration", 0) > 0:
        effective_time_step *= (1 + battle.get("wave_slow", 0) / 100.0)
        battle["wave_slow_duration"] -= 1.0

    # 2. Атака мультиклассовыми юнитами
    for uid, p in battle["players"].items():
        for dep in p["deployed"]:
            if not battle["mobs"]: break 
            
            u_stats = get_unit_stats(dep["uid"], dep.get("is_shiny", False))
            if not u_stats: continue 
            utypes = u_stats.get("unit_types", [])
            
            if not any(t in utypes for t in ["Одиночный", "Сплеш", "АОЕ", "Замедление"]):
                continue
                
            base_cd = float(u_stats.get("cd", 1.0))
            actual_cd = max(0.01, round(base_cd * best_cd_mult, 2))
            dmg = round(float(u_stats.get("damage", 10)) * best_dmg_mult * (1 - m_def / 100), 2)
            
            dep["time_bank"] = dep.get("time_bank", 0.0) + effective_time_step
            
            while dep["time_bank"] >= actual_cd and battle["mobs"]:
                dep["time_bank"] -= actual_cd
                coins_earned = 0.0

                if ("Одиночный" in utypes or "Замедление" in utypes) and battle["mobs"]: 
                    actual_dmg_done = min(battle["mobs"][0], dmg)
                    coins_earned += actual_dmg_done * bot_settings["coins_per_damage"]
                    battle["mobs"][0] = round(battle["mobs"][0] - dmg, 2)
                    if battle["mobs"][0] <= 0: battle["mobs"].pop(0)
                    
                if "Сплеш" in utypes and battle["mobs"]:
                    for i in range(min(5, len(battle["mobs"]))):
                        actual_dmg_done = min(battle["mobs"][i], dmg)
                        coins_earned += actual_dmg_done * bot_settings["coins_per_damage"]
                        battle["mobs"][i] = round(battle["mobs"][i] - dmg, 2)
                    battle["mobs"] = [h for h in battle["mobs"] if h > 0]
                    
                if "АОЕ" in utypes and battle["mobs"]:
                    for i in range(len(battle["mobs"]))[:10]:
                        actual_dmg_done = min(battle["mobs"][i], dmg)
                        coins_earned += actual_dmg_done * bot_settings["coins_per_damage"]
                        battle["mobs"][i] = round(battle["mobs"][i] - dmg, 2)
                    battle["mobs"] = [h for h in battle["mobs"] if h > 0]
                
                p["coins"] += coins_earned

    chat_id = battle["chat_id"]

    # 3. Фермы и завершение волны
    if not battle["mobs"]:
        for p_uid, p_data in battle["players"].items():
            wave_income = sum(get_unit_stats(d["uid"], d.get("is_shiny")).get("income", 0) for d in p_data["deployed"] if "Ферма" in get_unit_stats(d["uid"], d.get("is_shiny")).get("unit_types", []))
            p_data["coins"] += wave_income

        battle["current_wave"] += 1
        battle["current_turn"] = 1
        battle["wave_slow_duration"] = 0 # Сброс замедления
        
        if battle["current_wave"] > m_data["waves_total"]:
            return await finish_battle(battle_id, bot, True) 
            
        w_info = m_data["waves"][battle["current_wave"] - 1]
        mob = mobs_db.get(w_info["mob_id"], {"hp": 100})
        battle["mobs"] = [mob["hp"] for _ in range(w_info["count"])]
    else:
        battle["current_turn"] += 1
        if battle["current_turn"] > w_info["turns"]:
            battle["base_hp"] = round(battle["base_hp"] - sum(h/10 for h in battle["mobs"]), 2)
            battle["mobs"] = []
            battle["wave_slow_duration"] = 0
            
            if battle["base_hp"] <= 0: return await finish_battle(battle_id, bot, False)
                
            battle["current_wave"] += 1
            battle["current_turn"] = 1
            if battle["current_wave"] > m_data["waves_total"]:
                return await finish_battle(battle_id, bot, True)
                
            w_info = m_data["waves"][battle["current_wave"] - 1]
            mob = mobs_db.get(w_info["mob_id"], {"hp": 100})
            battle["mobs"] = [mob["hp"] for _ in range(w_info["count"])]

    # Обновление UI
    photo_file, text, main_kb = await render_battle_ui(battle_id, bot)
    try:
        if photo_file:
            await bot.edit_message_media(chat_id=chat_id, message_id=battle["main_msg_id"], media=InputMediaPhoto(media=photo_file, caption=text[:1024], parse_mode="HTML"), reply_markup=main_kb)
        else:
            await bot.edit_message_caption(chat_id=chat_id, message_id=battle["main_msg_id"], caption=text[:1024], reply_markup=main_kb, parse_mode="HTML")
    except Exception: pass 

async def battle_loop(battle_id: str, bot: Bot):
    while battle_id in active_battles:
        battle = active_battles[battle_id]
        delay = bot_settings["turn_time_skip"] if battle.get("auto_skip") else bot_settings["turn_time_noskip"]
        await asyncio.sleep(delay)
        await process_battle_turn(battle_id, bot)

async def finish_battle(battle_id: str, bot: Bot, is_win: bool):
    if battle_id not in active_battles: return
    battle = active_battles[battle_id]
    chat_id = battle["chat_id"]
    m_data = maps_db[battle["map_id"]]
    rew = m_data.get("rewards", {"💰 Монеты": 50})
    
    text = "❇️ <b>ПОБЕДА!</b>\n\nНаграды:\n" if is_win else "📛 <b>ПОРАЖЕНИЕ</b>\n\nУтешительный приз:\n"
    
    for k, v in rew.items():
        amt = v if is_win else max(1, int(v * 0.1))
        text += f"+{amt} {k}\n"
        for p_uid in battle["players"].keys():
            bal = user_balances.get(p_uid, {"💰 Монеты": 100, "💎 Гемы": 0})
            bal[k] = bal.get(k, 0) + amt
            user_balances[p_uid] = bal
            
    save_data()
    try: await bot.send_message(chat_id=chat_id, text=text, parse_mode="HTML")
    except: pass
    
    for uid, p_msg in battle["player_msg_ids"].items():
        try: await bot.delete_message(chat_id=chat_id, message_id=p_msg)
        except: pass
        if uid in user_to_battle: del user_to_battle[uid]
        
    try: await bot.delete_message(chat_id=chat_id, message_id=battle["main_msg_id"])
    except: pass
    
    del active_battles[battle_id]
    if battle_id in active_tasks:
        active_tasks[battle_id].cancel()
        del active_tasks[battle_id]

# ==========================================
# ОСНОВНЫЕ ОБРАБОТЧИКИ И ЛОББИ (Создание каток)
# ==========================================
dp = Dispatcher()
dp.callback_query.middleware(PanelMiddleware())

@dp.message(StateFilter('*'), Command("panel"), F.chat.type.in_({"group", "supergroup"}))
async def cmd_panel(message: Message, state: FSMContext):
    await state.clear()
    await send_main_screen(message)

@dp.message(StateFilter('*'), F.text.in_({"🔙 Назад", "🔙 В Главное Меню"}))
async def global_back_button(message: Message, state: FSMContext):
    await state.clear()
    user_id_str = str(message.from_user.id)
    if user_id_str in user_to_battle:
        await message.answer("⚠️ Вы не можете выйти в меню, пока находитесь в бою. Нажмите '🏳 Сдаться' под интерфейсом боя.")
        return
    await send_main_screen(message)

@dp.message(StateFilter('*'), CommandStart())
async def cmd_start(message: Message, state: FSMContext):
    await state.clear()
    await send_main_screen(message, "🔄 <i>Инициализация интерфейса завершена...</i>")

@dp.callback_query(F.data == "free_crate")
async def cq_free_crate(callback: CallbackQuery):
    user_id_str = str(callback.from_user.id)
    last_time = user_free_crate_times.get(user_id_str, 0)
    current_time = time.time()
    
    if current_time - last_time < bot_settings["free_crate_cooldown"]:
        rem = int(bot_settings["free_crate_cooldown"] - (current_time - last_time))
        return await callback.answer(f"Подождите еще {rem // 3600}ч {(rem % 3600) // 60}м!", show_alert=True)
        
    user_free_crate_times[user_id_str] = current_time
    init_user_balance(user_id_str)
    user_balances[user_id_str]["💰 Монеты"] += 100
    save_data()
    await callback.answer("🎁 Вы получили 100 💰 Монет!", show_alert=True)

# --- НОВАЯ СИСТЕМА ЛОББИ ---
@dp.callback_query(F.data == "battle_select_map")
async def cq_battle_select_map(callback: CallbackQuery):
    if not maps_db: return await callback.answer("Карт пока нет!", show_alert=True)
    kb = [[InlineKeyboardButton(text=f"🗺 {m['name']} (Волн: {m['waves_total']})", callback_data=f"lobby_create_{mid}")] for mid, m in maps_db.items()]
    kb.append([InlineKeyboardButton(text="🔙 Назад", callback_data="main_menu")])
    await callback.message.edit_text("🗺 <b>Выберите карту для создания лобби:</b>", reply_markup=InlineKeyboardMarkup(inline_keyboard=kb))

@dp.callback_query(F.data.startswith("lobby_create_"))
async def cq_lobby_create(callback: CallbackQuery):
    mid = callback.data.split("_")[2]
    lobby_id = str(uuid.uuid4())[:8]
    lobbies[lobby_id] = {
        "map_id": mid,
        "host": str(callback.from_user.id),
        "players": {str(callback.from_user.id): callback.from_user.first_name}
    }
    await update_lobby_ui(callback.message, lobby_id)

async def update_lobby_ui(message: Message, lobby_id: str):
    lobby = lobbies.get(lobby_id)
    if not lobby: return
    
    m = maps_db[lobby["map_id"]]
    text = f"⚔️ <b>ЛОББИ: {m['name']}</b>\n━━━━━━━━━━━━━━━━━━\n👥 <b>Игроки:</b>\n"
    for uid, name in lobby["players"].items():
        text += f" • {name} {'👑 (Хост)' if uid == lobby['host'] else ''}\n"
        
    kb = [
        [InlineKeyboardButton(text="➕ Присоединиться", callback_data=f"lobby_join_{lobby_id}"), InlineKeyboardButton(text="➖ Покинуть", callback_data=f"lobby_leave_{lobby_id}")],
        [InlineKeyboardButton(text="🚀 НАЧАТЬ ИГРУ (Хост) 🚀", callback_data=f"lobby_start_{lobby_id}")]
    ]
    try: await message.edit_text(text, reply_markup=InlineKeyboardMarkup(inline_keyboard=kb))
    except: pass

@dp.callback_query(F.data.startswith("lobby_join_"))
async def cq_lobby_join(callback: CallbackQuery):
    lobby_id = callback.data.split("_")[2]
    uid = str(callback.from_user.id)
    if lobby_id not in lobbies: return await callback.answer("Лобби больше не существует", show_alert=True)
    if uid in user_to_battle: return await callback.answer("Вы уже в бою!", show_alert=True)
    if not user_equipped.get(uid): return await callback.answer("Экипируйте юнитов в инвентаре!", show_alert=True)
    
    lobbies[lobby_id]["players"][uid] = callback.from_user.first_name
    await update_lobby_ui(callback.message, lobby_id)
    await callback.answer()

@dp.callback_query(F.data.startswith("lobby_leave_"))
async def cq_lobby_leave(callback: CallbackQuery):
    lobby_id = callback.data.split("_")[2]
    uid = str(callback.from_user.id)
    if lobby_id in lobbies and uid in lobbies[lobby_id]["players"]:
        if lobbies[lobby_id]["host"] == uid:
            del lobbies[lobby_id]
            return await callback.message.edit_text("🛑 Лобби распущено хостом.")
        del lobbies[lobby_id]["players"][uid]
        await update_lobby_ui(callback.message, lobby_id)
    await callback.answer()

@dp.callback_query(F.data.startswith("lobby_start_"))
async def cq_lobby_start(callback: CallbackQuery):
    lobby_id = callback.data.split("_")[2]
    uid = str(callback.from_user.id)
    if lobby_id not in lobbies or lobbies[lobby_id]["host"] != uid: return await callback.answer("Только хост может начать игру!", show_alert=True)
    
    lobby = lobbies.pop(lobby_id)
    global battle_id_counter
    bid = str(battle_id_counter)
    battle_id_counter += 1
    
    m_data = maps_db[lobby["map_id"]]
    battle = {
        "chat_id": callback.message.chat.id, "map_id": lobby["map_id"],
        "base_hp": 100, "current_wave": 1, "current_turn": 1,
        "auto_skip": False, "wave_slow": 0, "wave_slow_duration": 0,
        "players": {}, "player_msg_ids": {}
    }
    
    w_info = m_data["waves"][0]
    mob = mobs_db.get(w_info["mob_id"], {"hp": 100})
    battle["mobs"] = [mob["hp"] for _ in range(w_info["count"])]
    
    for pid, pname in lobby["players"].items():
        battle["players"][pid] = {"name": pname, "coins": m_data.get("starting_coins", 200), "deployed": []}
        user_to_battle[pid] = bid
        
    active_battles[bid] = battle
    await callback.message.delete()
    
    photo, text, kb = await render_battle_ui(bid, callback.bot)
    if photo:
        msg = await callback.message.answer_photo(photo=photo, caption=text, reply_markup=kb, parse_mode="HTML")
    else:
        msg = await callback.message.answer(text, reply_markup=kb, parse_mode="HTML")
        
    battle["main_msg_id"] = msg.message_id
    
    for pid in battle["players"]:
        try:
            pmsg = await callback.message.answer(f"🎮 Пульт управления игрока {battle['players'][pid]['name']}:", reply_markup=get_player_kb(bid, pid))
            battle["player_msg_ids"][pid] = pmsg.message_id
        except: pass
        
    active_tasks[bid] = asyncio.create_task(battle_loop(bid, callback.bot))
    await callback.answer()

# --- КНОПКИ В БОЮ ---
@dp.callback_query(F.data.startswith("b_toggle_"))
async def cq_b_toggle(callback: CallbackQuery):
    bid = callback.data.split("_")[2]
    if bid in active_battles:
        active_battles[bid]["auto_skip"] = not active_battles[bid]["auto_skip"]
        _, text, kb = await render_battle_ui(bid, callback.bot)
        try: await callback.message.edit_caption(caption=text[:1024], reply_markup=kb, parse_mode="HTML")
        except: pass
    await callback.answer()

@dp.callback_query(F.data.startswith("b_surr_"))
async def cq_b_surr(callback: CallbackQuery):
    bid = callback.data.split("_")[2]
    if bid in active_battles: await finish_battle(bid, callback.bot, False)
    await callback.answer("Вы сдались!")

@dp.callback_query(F.data.startswith("b_dep_"))
async def cq_b_dep(callback: CallbackQuery):
    _, _, bid, uid, is_shiny_str = callback.data.split("_")
    pid = str(callback.from_user.id)
    if bid not in active_battles or pid not in active_battles[bid]["players"]: return await callback.answer("Бой завершен", show_alert=True)
    
    u_stats = get_unit_stats(uid, is_shiny_str == "1")
    cost = u_stats.get("deploy_cost", 50)
    p_data = active_battles[bid]["players"][pid]
    
    if p_data["coins"] < cost: return await callback.answer(f"Не хватает монет! Нужно {cost}", show_alert=True)
    limit = u_stats.get("supply_limit", 99)
    current_count = sum(1 for d in p_data["deployed"] if d["uid"] == uid and str(d.get("is_shiny", 0)) == is_shiny_str)
    if current_count >= limit: return await callback.answer("Лимит юнитов этого типа!", show_alert=True)
    
    p_data["coins"] -= cost
    p_data["deployed"].append({"uid": uid, "is_shiny": (is_shiny_str == "1"), "time_bank": 0.0, "slow_cd_timer": float(u_stats.get("slow_cooldown", 15))})
    
    try: await callback.message.edit_reply_markup(reply_markup=get_player_kb(bid, pid))
    except: pass
    await callback.answer(f"{u_stats.get('name')} размещен!")

# ==========================================
# АДМИН ПАНЕЛЬ (КРАТКАЯ ВЕРСИЯ С ДОП. КНОПКАМИ)
# ==========================================
@dp.callback_query(F.data == "admin_panel")
async def cq_admin_panel(callback: CallbackQuery, state: FSMContext):
    if str(callback.from_user.id) not in admins_db: return await callback.answer("⛔️ У вас нет прав!", show_alert=True)
    await state.clear()
    await callback.message.edit_text("👑 <b>ПАНЕЛЬ АДМИНА</b>", reply_markup=get_admin_panel_kb())

@dp.callback_query(F.data == "admin_add_unit")
async def cq_u_add(callback: CallbackQuery, state: FSMContext):
    await state.clear()
    await state.set_state(AdminUnitAdd.unit_types)
    await state.update_data(temp_types=[])
    await callback.message.edit_text("➕ <b>Создание Юнита</b>\nВыберите классы (вкл. Замедление):", reply_markup=get_unit_types_kb([]))

@dp.callback_query(AdminUnitAdd.unit_types, F.data.startswith("toggleutype_"))
async def u_toggle_type(callback: CallbackQuery, state: FSMContext):
    t_name = callback.data.split("_")[1]
    data = await state.get_data()
    types = data.get("temp_types", [])
    if t_name in types: types.remove(t_name)
    else: types.append(t_name)
    await state.update_data(temp_types=types)
    await callback.message.edit_reply_markup(reply_markup=get_unit_types_kb(types))

@dp.callback_query(AdminUnitAdd.unit_types, F.data == "saveutypes")
async def u_save_types(callback: CallbackQuery, state: FSMContext):
    data = await state.get_data()
    if not data.get("temp_types"): return await callback.answer("Выберите класс!", show_alert=True)
    await state.set_state(AdminUnitAdd.photo)
    await callback.message.edit_text("📸 Отправьте фото (любое):")

@dp.message(AdminUnitAdd.photo)
async def u_step_photo(message: Message, state: FSMContext):
    if not message.photo: return await message.answer("Фото!")
    await state.update_data(photo=message.photo[-1].file_id)
    await state.set_state(AdminUnitAdd.name)
    await message.answer("📝 Название юнита:")

@dp.message(AdminUnitAdd.name)
async def u_step_name(message: Message, state: FSMContext):
    await state.update_data(name=message.text.strip())
    await state.set_state(AdminUnitAdd.supply_limit)
    await message.answer("🛑 Лимит на поле (число):")

@dp.message(AdminUnitAdd.supply_limit)
async def u_step_limit(message: Message, state: FSMContext):
    await state.update_data(supply_limit=int(message.text))
    await state.set_state(AdminUnitAdd.deploy_cost)
    await message.answer("💰 Цена спавна:")

@dp.message(AdminUnitAdd.deploy_cost)
async def u_step_cost(message: Message, state: FSMContext):
    await state.update_data(deploy_cost=int(message.text))
    await jump_next_unit_stat(message, state)

async def jump_next_unit_stat(message: Message, state: FSMContext):
    data = await state.get_data()
    types = data.get("temp_types", [])
    has_attack = any(t in types for t in ["Одиночный", "Сплеш", "АОЕ", "Замедление"])
    
    if "Замедление" in types and "slow_percent" not in data:
        await state.set_state(AdminUnitAdd.slow_percent)
        return await message.answer("❄️ <b>[Замедление]</b> % замедления (напр. 20):")
    if "Замедление" in types and "slow_duration" not in data:
        await state.set_state(AdminUnitAdd.slow_duration)
        return await message.answer("❄️ <b>[Замедление]</b> Длительность в секундах (напр. 5):")
    if "Замедление" in types and "slow_cooldown" not in data:
        await state.set_state(AdminUnitAdd.slow_cooldown)
        return await message.answer("❄️ <b>[Замедление]</b> КД способности (напр. 15):")

    if has_attack and "cd" not in data:
        await state.set_state(AdminUnitAdd.cd)
        return await message.answer("⏱ <b>[Атака]</b> КД атаки (напр. 1.0):")
    if has_attack and "damage" not in data:
        await state.set_state(AdminUnitAdd.damage)
        return await message.answer("💥 <b>[Атака]</b> Урон:")
        
    if "Саппорт" in types and "cd_boost" not in data:
        await state.set_state(AdminUnitAdd.cd_boost)
        return await message.answer("✨ <b>[Саппорт]</b> Буст КД (напр 0.8):")
    if "Саппорт" in types and "dmg_boost" not in data:
        await state.set_state(AdminUnitAdd.dmg_boost)
        return await message.answer("💪 <b>[Саппорт]</b> Буст Урона (напр 1.2):")
        
    if "Ферма" in types and "income" not in data:
        await state.set_state(AdminUnitAdd.income)
        return await message.answer("🌾 <b>[Ферма]</b> Доход за волну:")
        
    global unit_id_counter
    uid = str(unit_id_counter)
    u_dict = {"photo": data["photo"], "name": data["name"], "unit_types": types, "supply_limit": data["supply_limit"], "deploy_cost": data["deploy_cost"]}
    
    if has_attack: u_dict["cd"], u_dict["damage"] = data["cd"], data["damage"]
    if "Саппорт" in types: u_dict["cd_boost"], u_dict["dmg_boost"] = data["cd_boost"], data["dmg_boost"]
    if "Ферма" in types: u_dict["income"] = data["income"]
    if "Замедление" in types: u_dict["slow_percent"], u_dict["slow_duration"], u_dict["slow_cooldown"] = data["slow_percent"], data["slow_duration"], data["slow_cooldown"]
        
    units_db[uid] = u_dict
    unit_id_counter += 1
    save_data()
    await state.clear()
    await send_main_screen(message, f"✅ Юнит создан!")

# Обработчики ввода статов
@dp.message(StateFilter(AdminUnitAdd.slow_percent, AdminUnitAdd.slow_duration, AdminUnitAdd.slow_cooldown, AdminUnitAdd.cd, AdminUnitAdd.damage, AdminUnitAdd.cd_boost, AdminUnitAdd.dmg_boost, AdminUnitAdd.income))
async def u_rec_stats(message: Message, state: FSMContext):
    val = float(message.text.replace(",", ".")) if "." in message.text or "," in message.text else int(message.text)
    curr_state = await state.get_state()
    state_name = curr_state.split(":")[-1]
    await state.update_data({state_name: val})
    await jump_next_unit_stat(message, state)

# Быстрое создание Карты (Автогенерация волн)
@dp.callback_query(F.data == "admin_add_map")
async def cq_m_add(callback: CallbackQuery, state: FSMContext):
    if not mobs_db: return await callback.answer("Сначала создайте мобов!", show_alert=True)
    await state.set_state(AdminMapAdd.photo)
    await callback.message.edit_text("📸 Отправьте фото Карты:")

@dp.message(AdminMapAdd.photo)
async def m_step_photo(message: Message, state: FSMContext):
    await state.update_data(photo=message.photo[-1].file_id)
    await state.set_state(AdminMapAdd.name)
    await message.answer("📝 Название Карты:")

@dp.message(AdminMapAdd.name)
async def m_step_name(message: Message, state: FSMContext):
    await state.update_data(name=message.text)
    await state.set_state(AdminMapAdd.waves_count)
    await message.answer("🌊 Количество волн (сгенерируются автоматически):")

@dp.message(AdminMapAdd.waves_count)
async def m_step_waves(message: Message, state: FSMContext):
    data = await state.get_data()
    waves_total = int(message.text)
    
    waves = []
    mob_ids = list(mobs_db.keys())
    for i in range(waves_total):
        waves.append({
            "mob_id": random.choice(mob_ids),
            "count": 5 + i * 2,
            "turns": 10 + i
        })
        
    global map_id_counter
    maps_db[str(map_id_counter)] = {
        "photo": data["photo"], "name": data["name"],
        "starting_coins": 200, "waves_total": waves_total,
        "waves": waves, "rewards": {"💰 Монеты": 100 + waves_total * 10}
    }
    map_id_counter += 1
    save_data()
    await state.clear()
    await send_main_screen(message, "✅ Карта успешно сгенерирована!")

# ==========================================
# ЗАПУСК БОТА
# ==========================================
async def main():
    logging.basicConfig(level=logging.INFO)
    load_data() 
    bot = Bot(token=TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
    await bot.set_my_commands([
        BotCommand(command="panel", description="Открыть меню (только для групп)"),
        BotCommand(command="start", description="Запустить/Перезапустить бота")
    ])
    await bot.delete_webhook(drop_pending_updates=True)
    try: await dp.start_polling(bot)
    finally: await bot.session.close()

if __name__ == "__main__":
    try: asyncio.run(main())
    except KeyboardInterrupt: pass
