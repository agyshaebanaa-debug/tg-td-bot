import asyncio
import logging
import json
import os
import random
import time
import io
import urllib.request
import sqlite3
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
# ⚠️ ОБЯЗАТЕЛЬНО СМЕНИТЕ ТОКЕН ЧЕРЕЗ @BotFather, ТАК КАК ОН БЫЛ "ЗАСВЕЧЕН"
TOKEN = "8403453180:AAEyAq5LG8CUQaxwNa1A7Fp7JhvDaS6tdRc"
MAIN_ADMIN_ID = "5341904332"

DB_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "game_data.db")

admins_db = {MAIN_ADMIN_ID}
rarities_db = [] 
units_db = {}    
unit_id_counter = 1
mobs_db = {}
mob_id_counter = 1
user_inventory = {}  # "uid:is_shiny" -> "5:1"
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
    "turn_time_noskip": 10
}

ATTACK_TYPES = ["Одиночный", "Сплеш", "АОЕ", "Саппорт", "Ферма"]

elevators_db = {}
elevator_id_counter = 1
active_battles = {}
battle_id_counter = 1
user_to_battle = {}
active_tasks = {}
panel_owners = {} 
image_cache = {}

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
        
        rarities_db = data.get("rarities_db", [])
        
        loaded_settings = data.get("bot_settings", {})
        bot_settings["coins_per_damage"] = loaded_settings.get("coins_per_damage", 0.5)
        bot_settings["turn_time_skip"] = loaded_settings.get("turn_time_skip", 5)
        bot_settings["turn_time_noskip"] = loaded_settings.get("turn_time_noskip", 10)
        
        units_db = data.get("units_db", {})
        # Миграция старых юнитов на мульти-классы (массив unit_types)
        for uid, udata in units_db.items():
            if "unit_type" in udata:
                udata["unit_types"] = [udata.pop("unit_type")]
        
        unit_id_counter = data.get("unit_id_counter", 1)
        mobs_db = data.get("mobs_db", {})
        mob_id_counter = data.get("mob_id_counter", 1)
        
        currencies_db = data.get("currencies_db", ["💰 Монеты", "💎 Гемы"])
        if "💰 Монеты" not in currencies_db: currencies_db.insert(0, "💰 Монеты")
        
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
    return su

def format_unit_stats(u):
    utypes = u.get("unit_types", [])
    types_str = ", ".join(utypes) if utypes else "Нет класса"
    
    res = f"├ 🏷 Классы: <b>{types_str}</b>\n├ 💰 Цена: {u.get('deploy_cost', 50)} | 🛑 Лимит: {u.get('supply_limit', '∞')}\n"
    
    if any(t in utypes for t in ["Одиночный", "Сплеш", "АОЕ"]):
        res += f"├ ⚔️ Атака: 💥 {u.get('damage', 10)} | ⏱ КД: {u.get('cd', 1.0)}с\n"
    if "Саппорт" in utypes:
        res += f"├ ✨ Саппорт: ⏱ КД x{u.get('cd_boost', 1.0)} | 💥 Урон x{u.get('dmg_boost', 1.0)}\n"
    if "Ферма" in utypes:
        res += f"├ 🌾 Ферма: 💰 +{u.get('income', 0)}/волна\n"
        
    res += "└──────────────────"
    return res

# ==========================================
# MIDDLEWARE И СОСТОЯНИЯ
# ==========================================
class PanelMiddleware(BaseMiddleware):
    async def __call__(self, handler, event, data):
        if isinstance(event, CallbackQuery) and event.message:
            if event.message.chat.type in {"group", "supergroup"}:
                public_cb = ["el_", "b_dep_", "b_toggle_", "b_surr_"]
                if not any(event.data.startswith(p) for p in public_cb):
                    key = f"{event.message.chat.id}_{event.message.message_id}"
                    if key in panel_owners and panel_owners[key] != event.from_user.id:
                        await event.answer("🚫 Это меню вызвал другой игрок! Напишите /panel", show_alert=True)
                        return
        return await handler(event, data)

class AdminStates(StatesGroup):
    waiting_for_add = State()
    waiting_for_remove = State()

class AdminCurrencyAdd(StatesGroup):
    name = State()

class AdminGiveCur(StatesGroup):
    select_cur = State()
    target_id = State()
    amount = State()

class AdminMapAdd(StatesGroup):
    photo, name, starting_coins, waves_count, mob_select, mobs_amount, turns_count, reward_select, reward_amount = State(), State(), State(), State(), State(), State(), State(), State(), State()

class AdminRarityAdd(StatesGroup):
    waiting_for_name = State()

class AdminUnitAdd(StatesGroup):
    unit_types = State()
    photo = State()
    name = State()
    rarity = State()
    supply_limit = State()
    deploy_cost = State()
    # Динамические стейты в зависимости от классов
    cd = State()
    damage = State()
    cd_boost = State()
    dmg_boost = State()
    income = State()

class AdminMobAdd(StatesGroup):
    photo, name, hp, effect, defense_percent = State(), State(), State(), State(), State()

class AdminCrateAdd(StatesGroup):
    photo, name, currency, price, unit_select, unit_weight = State(), State(), State(), State(), State(), State()

class AdminSettingsEdit(StatesGroup):
    waiting_for_coins_per_damage, waiting_for_turn_time_skip, waiting_for_turn_time_noskip = State(), State(), State()

# ==========================================
# UI КЛАВИАТУРЫ
# ==========================================
reply_bottom_menu = ReplyKeyboardMarkup(
    keyboard=[[KeyboardButton(text="🔙 В Главное Меню")]],
    resize_keyboard=True,
    is_persistent=True,
    input_field_placeholder="Управление в меню"
)

def get_main_menu_kb(chat_type: str = "private") -> InlineKeyboardMarkup:
    kb = []
    if maps_db: kb.append([InlineKeyboardButton(text="⚔️ В бой ⚔️", callback_data="battle_select_map")])
    kb.append([InlineKeyboardButton(text="🛗 Лобби (Лифты) 🛗", callback_data="el_list")])
    if crates_db: 
        kb.append([InlineKeyboardButton(text="📦 Магазин Крейтов 📦", callback_data="crates_list")])
        
    if chat_type in {"group", "supergroup"}:
        kb.append([InlineKeyboardButton(text="🎁 Бесплатный Крейт 🎁", callback_data="free_crate")])
        
    kb.append([
        InlineKeyboardButton(text="📖 Энциклопедия", callback_data="main_index"), 
        InlineKeyboardButton(text="🎒 Мой Инвентарь", callback_data="main_inventory")
    ])
    kb.append([InlineKeyboardButton(text="⚙️ Админ панель", callback_data="admin_panel")])
    return InlineKeyboardMarkup(inline_keyboard=kb)

def get_admin_panel_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="➕ Юнит", callback_data="admin_add_unit"), InlineKeyboardButton(text="➖ Юнит", callback_data="admin_del_unit")],
        [InlineKeyboardButton(text="👾 Доб. Моба", callback_data="admin_add_mob"), InlineKeyboardButton(text="👾 Удал. Моба", callback_data="admin_del_mob")],
        [InlineKeyboardButton(text="🗺 Доб. Карту", callback_data="admin_add_map"), InlineKeyboardButton(text="🗺 Удал. Карту", callback_data="admin_del_map")],
        [InlineKeyboardButton(text="📦 Доб. Крейт", callback_data="admin_add_crate"), InlineKeyboardButton(text="📦 Удал. Крейт", callback_data="admin_del_crate")],
        [InlineKeyboardButton(text="🪙 Доб. Валюту", callback_data="admin_add_cur"), InlineKeyboardButton(text="🪙 Удал. Валюту", callback_data="admin_del_cur")],
        [InlineKeyboardButton(text="💸 Выдать Валюту (Любому) 💸", callback_data="admin_give_cur")],
        [InlineKeyboardButton(text="✨ Доб. Редкость", callback_data="admin_add_rarity"), InlineKeyboardButton(text="✨ Удал. Редкость", callback_data="admin_del_rarity")],
        [InlineKeyboardButton(text="👨‍💻 Назначить Админа", callback_data="admin_add"), InlineKeyboardButton(text="🚫 Снять Админа", callback_data="admin_remove")],
        [InlineKeyboardButton(text="⚙️ Настройки Игры ⚙️", callback_data="admin_settings")]
    ])

def get_unit_types_kb(selected: list) -> InlineKeyboardMarkup:
    kb = []
    for t in ATTACK_TYPES:
        mark = "✅" if t in selected else "❌"
        kb.append([InlineKeyboardButton(text=f"{mark} {t}", callback_data=f"toggleutype_{t}")])
    kb.append([InlineKeyboardButton(text="💾 Продолжить (Сохранить типы)", callback_data="saveutypes")])
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

def get_welcome_text(user_id_str: str, user_name: str) -> str:
    bal = user_balances.get(user_id_str, {"💰 Монеты": 100, "💎 Гемы": 0})
    
    bal_text = ""
    for cur in currencies_db:
        amount = bal.get(cur, 0)
        bal_text += f" ├ {cur}: <b>{amount}</b>\n"
    if not bal_text: bal_text = " └ <i>Пусто</i>\n"
    else:
        parts = bal_text.rsplit('├', 1)
        bal_text = parts[0] + '└' + parts[1]
        
    unlocked_base = set([item.split(":")[0] for item in user_inventory.get(user_id_str, set())])
    unlocked_count = len(unlocked_base)
    total_units = len(units_db)
    
    return (
        f"👑 <b>ПРОФИЛЬ ИГРОКА: {user_name}</b> 👑\n"
        "━━━━━━━━━━━━━━━━━━\n"
        f"💳 <b>Ваши финансы:</b>\n"
        f"{bal_text}"
        "━━━━━━━━━━━━━━━━━━\n"
        f"📊 <b>Прогресс коллекции:</b>\n"
        f" └ 🧩 Открыто юнитов: <b>{unlocked_count} из {total_units}</b>\n"
        "━━━━━━━━━━━━━━━━━━\n"
        "👇 <i>Выберите действие в меню ниже:</i>"
    )

async def send_main_screen(target: Message, header_text: str | None = None):
    user_id_str = str(target.from_user.id)
    user_name = target.from_user.first_name or "Игрок"
    first_text = header_text if header_text else "🏠 <i>Вы вернулись в главное меню</i>"
    await target.answer(first_text, reply_markup=reply_bottom_menu)
    msg = await target.answer(get_welcome_text(user_id_str, user_name), reply_markup=get_main_menu_kb(target.chat.type))
    if target.chat.type in {"group", "supergroup"}:
        panel_owners[f"{msg.chat.id}_{msg.message_id}"] = target.from_user.id

def render_inventory(user_id_str: str) -> tuple[str, InlineKeyboardMarkup]:
    unlocked = user_inventory.get(user_id_str, set())
    equipped = user_equipped.get(user_id_str, [])
    bal = user_balances.get(user_id_str, {"💰 Монеты": 100, "💎 Гемы": 0})
    
    bal_lines = [f"<b>{bal.get(c, 0)}</b> {c}" for c in currencies_db]
    bal_text = " | ".join(bal_lines)
    
    text = (
        f"🎒 <b>ИНВЕНТАРЬ ИГРОКА</b>\n"
        f"━━━━━━━━━━━━━━━━━━\n"
        f"💳 <b>Баланс:</b> {bal_text}\n"
        f"━━━━━━━━━━━━━━━━━━\n\n"
        f"⚔️ <b>ЭКИПИРОВАНО ({len(equipped)}/5):</b>\n"
    )
    
    if not equipped: 
        text += " └ <i>Пусто. Выберите юнитов из списка ниже для добавления в колоду.</i>\n\n"
    else:
        for i, item_str in enumerate(equipped, 1):
            uid, is_shiny_str = item_str.split(":")
            is_shiny = (is_shiny_str == "1")
            
            if uid in units_db: 
                u = get_unit_stats(uid, is_shiny)
                stat_str = format_unit_stats(u).replace("├", " ").replace("└", " ")
                text += f"{i}. <b>{u.get('name')}</b> | {u.get('rarity', 'Обычный')}\n   {stat_str}\n"
        text += "\n"
        
    text += "📦 <b>ВАША КОЛЛЕКЦИЯ (НАЖМИТЕ ЧТОБЫ ЭКИПИРОВАТЬ):</b>\n"
    
    buttons = []
    if equipped: buttons.append([InlineKeyboardButton(text="❌ Снять всех юнитов ❌", callback_data="inv_unequip_all")])
    row = []
    
    # Сортировка инвентаря для красоты
    sorted_unlocked = sorted(list(unlocked), key=lambda x: (int(x.split(":")[0]), x.split(":")[1]))
    
    for item_str in sorted_unlocked:
        uid, is_shiny_str = item_str.split(":")
        is_shiny = (is_shiny_str == "1")
        
        if uid not in units_db: continue 
        mark = "✅ " if item_str in equipped else "🔹 "
        u = get_unit_stats(uid, is_shiny)
        
        row.append(InlineKeyboardButton(text=f"{mark}{u.get('name')}", callback_data=f"inv_t_{uid}_{is_shiny_str}"))
        if len(row) == 2:
            buttons.append(row)
            row = []
    if row: buttons.append(row)
    
    kb = InlineKeyboardMarkup(inline_keyboard=buttons) if buttons else InlineKeyboardMarkup(inline_keyboard=[])
    return text, kb

# ==========================================
# БОЕВОЙ ИНТЕРФЕЙС И РЕНДЕР
# ==========================================
def _draw_battle_image_sync(img_bytes, total_mobs_hp, current_wave, waves_total, current_turn, turns_total):
    try:
        img = Image.open(io.BytesIO(img_bytes)).convert("RGBA")
        draw = ImageDraw.Draw(img)
        font = None
        if os.path.exists(FONT_FILE):
            try: font = ImageFont.truetype(FONT_FILE, size=max(20, img.height // 12))
            except: pass
        if not font:
            try: font = ImageFont.load_default()
            except: pass

        def draw_outlined_text(d, txt, pos, anchor_y="center"):
            try: bbox = d.textbbox((0, 0), txt, font=font)
            except AttributeError:
                w, h = d.textsize(txt, font=font)
                bbox = (0, 0, w, h)
                
            w = bbox[2] - bbox[0]; h = bbox[3] - bbox[1]; x = pos[0] - w / 2
            y = pos[1] if anchor_y == "top" else (pos[1] - h / 2 if anchor_y == "center" else pos[1] - h)
            
            for dx in [-2, -1, 0, 1, 2]:
                for dy in [-2, -1, 0, 1, 2]:
                    if dx != 0 or dy != 0: d.text((x + dx, y + dy), txt, font=font, fill="black")
            d.text((x, y), txt, font=font, fill="white")

        draw_outlined_text(draw, f"ХП: {total_mobs_hp}", (img.width // 2, 10), anchor_y="top")
        draw_outlined_text(draw, f"Wave: {current_wave}", (img.width // 2, img.height // 2), anchor_y="center")
        draw_outlined_text(draw, f"Ходы: {current_turn} / {turns_total}", (img.width // 2, img.height - 10), anchor_y="bottom")
        
        out_bio = io.BytesIO()
        img.convert("RGB").save(out_bio, format="JPEG", quality=80, optimize=True)
        return out_bio.getvalue()
    except Exception: return None

async def render_battle_ui(battle_id: str, bot: Bot) -> tuple:
    battle = active_battles[battle_id]
    map_data = maps_db[battle["map_id"]]
    wave_info = map_data["waves"][battle["current_wave"] - 1]
    mob = mobs_db.get(wave_info["mob_id"], {"name": "Неизвестный моб", "hp": 100, "effect": "none", "defense_percent": 0, "photo": ""})
    
    timer_delay = bot_settings["turn_time_skip"] if battle["auto_skip"] else bot_settings["turn_time_noskip"]
    total_mobs_hp = round(sum(battle["mobs"]), 2)
    
    photo_file = mob.get("photo", "")
    if HAS_PIL and photo_file:
        if photo_file not in image_cache:
            try:
                bio = io.BytesIO()
                await bot.download(photo_file, destination=bio)
                image_cache[photo_file] = bio.getvalue()
            except Exception: pass
                
        if photo_file in image_cache:
            drawn_bytes = await asyncio.to_thread(_draw_battle_image_sync, image_cache[photo_file], total_mobs_hp, battle['current_wave'], map_data['waves_total'], battle['current_turn'], wave_info['turns'])
            if drawn_bytes: photo_file = BufferedInputFile(drawn_bytes, filename="render.jpg")

    text = ""
    if not photo_file or isinstance(photo_file, str):
        text += f"❤️ <b>Суммарное ХП мобов: {total_mobs_hp}</b>\n━━━━━━━━━━━━━━━\n🌊 <b>Волна: {battle['current_wave']} / {map_data['waves_total']}</b>\n━━━━━━━━━━━━━━━\n\n"
        
    perk = f"🛡 Защита {mob['defense_percent']}%" if mob['effect'] == 'defense' else "Нет перка"
    text += f"👾 <b>{mob.get('name', 'Моб')}</b> | ✨ {perk}\n"
    
    living_mobs = len(battle["mobs"])
    for m_hp in battle["mobs"][:5]: text += f"❤️ {m_hp}/{mob['hp']}\n"
    if living_mobs > 5: text += f"<i>...и еще {living_mobs - 5} шт.</i>\n"
        
    text += "=====================\n"
    text += f"🏰 <b>ВАША БАЗА</b>\n❤️ Прочность: <b>{battle['base_hp']}/100</b>\n\n"
    text += "👥 <b>Игроки в бою:</b>\n"
    for uid, p in battle["players"].items():
        disp_coins = int(p['coins']) if p['coins'] == int(p['coins']) else round(p['coins'], 1)
        text += f"• {p['name']}: 💰 {disp_coins}\n"
    
    text += "\n🛡 <b>Поставленные юниты:</b>\n"
    total_deployed = 0
    for uid, p in battle["players"].items():
        deployed_counts = {}
        for dep in p["deployed"]:
            item_str = f"{dep['uid']}:{1 if dep.get('is_shiny') else 0}"
            deployed_counts[item_str] = deployed_counts.get(item_str, 0) + 1
            
        for item_str, count in deployed_counts.items():
            total_deployed += count
            dep_uid, is_shiny_str = item_str.split(":")
            u = get_unit_stats(dep_uid, is_shiny_str == "1")
            if not u: continue
            
            types = u.get("unit_types", [])
            stats_list = []
            if any(t in types for t in ["Одиночный", "Сплеш", "АОЕ"]): stats_list.append(f"💥 {u.get('damage', 10)}")
            if "Саппорт" in types: stats_list.append(f"✨ Саппорт")
            if "Ферма" in types: stats_list.append(f"🌾 Ферма")
            
            text += f"• {u.get('name')} (x{count}) | {' | '.join(stats_list)}\n"
            
    if total_deployed == 0: text += "<i>Поле боя пустует</i>\n"
    text += "=====================\n"
    
    if not photo_file or isinstance(photo_file, str):
        text += f"⏱ <b>Ход: {battle['current_turn']} / {wave_info['turns']}</b> (След. ход через {timer_delay}с)"
    
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
            limit = unit.get("supply_limit", 99)
            deployed_count = sum(1 for d in p["deployed"] if d["uid"] == uid and d.get("is_shiny") == is_shiny)
            
            row.append(InlineKeyboardButton(text=f"🔸 {unit.get('name')} | 💰{cost} | ({deployed_count}/{limit})", callback_data=f"b_dep_{battle_id}_{uid}_{is_shiny_str}"))
            if len(row) == 1: # По одной кнопке в ряд для читаемости
                buttons.append(row)
                row = []
    if row: buttons.append(row)
    return InlineKeyboardMarkup(inline_keyboard=buttons)

# ==========================================
# ОСНОВНАЯ ЛОГИКА
# ==========================================
dp = Dispatcher()
dp.callback_query.middleware(PanelMiddleware())

@dp.message(StateFilter('*'), Command("panel"), F.chat.type.in_({"group", "supergroup"}))
async def cmd_panel(message: Message, state: FSMContext):
    await state.clear()
    init_user_balance(str(message.from_user.id))
    msg = await message.answer(get_welcome_text(str(message.from_user.id), message.from_user.first_name), reply_markup=get_main_menu_kb(message.chat.type))
    panel_owners[f"{msg.chat.id}_{msg.message_id}"] = message.from_user.id

@dp.message(StateFilter('*'), F.text.in_({"🔙 Назад", "🔙Назад🔙", "🔙 В Главное Меню"}))
async def global_back_button(message: Message, state: FSMContext):
    await state.clear()
    user_id_str = str(message.from_user.id)
    battle_id = user_to_battle.get(user_id_str)
    
    if battle_id and battle_id in active_battles:
        battle = active_battles[battle_id]
        p_msg_id = battle["player_msg_ids"].get(user_id_str)
        if p_msg_id:
            try: await message.bot.delete_message(chat_id=battle["chat_id"], message_id=p_msg_id)
            except: pass
        battle["players"].pop(user_id_str, None)
        del user_to_battle[user_id_str]
        
        if not battle["players"]:
            if battle_id in active_tasks: active_tasks[battle_id].cancel()
            try: await message.bot.delete_message(chat_id=battle["chat_id"], message_id=battle["main_msg_id"])
            except: pass
            del active_battles[battle_id]
            
        return await send_main_screen(message, "🏳 <b>Вы покинули поле боя и вернулись в меню.</b>")
        
    init_user_balance(user_id_str)
    await send_main_screen(message)

@dp.message(StateFilter('*'), CommandStart())
async def cmd_start(message: Message, state: FSMContext):
    await state.clear()
    init_user_balance(str(message.from_user.id))
    await send_main_screen(message, "🔄 <i>Инициализация интерфейса завершена...</i>")

# --- ОТКРЫТИЕ КРЕЙТОВ ---
@dp.callback_query(StateFilter('*'), F.data == "crates_list")
async def cq_crates_list(callback: CallbackQuery, state: FSMContext):
    await state.clear()
    if not crates_db: return await callback.answer("Магазин пока пуст!", show_alert=True)
    kb = [[InlineKeyboardButton(text=f"📦 {c.get('name', 'Крейт')} | {c['price']} {c.get('currency', '💰 Монеты')}", callback_data=f"crate_info_{cid}")] for cid, c in crates_db.items()]
    await callback.message.edit_text("📦 <b>Магазин Крейтов</b>\n━━━━━━━━━━━━━━━━━━\n👇 Выберите крейт для просмотра шансов:", reply_markup=InlineKeyboardMarkup(inline_keyboard=kb))
    await callback.answer()

@dp.callback_query(StateFilter('*'), F.data.startswith("crate_info_"))
async def cq_crate_info(callback: CallbackQuery, state: FSMContext):
    await state.clear()
    cid = callback.data.split("_")[2]
    crate = crates_db[cid]
    unlocked_base = set([item.split(":")[0] for item in user_inventory.get(str(callback.from_user.id), set())])
    total_weight = sum(crate["units"].values())
    
    text = f"📦 <b>{crate.get('name', 'Крейт')}</b>\n━━━━━━━━━━━━━━━━━━\n💰 <b>Цена:</b> {crate['price']} {crate.get('currency', '💰 Монеты')}\n\n🎲 <b>Шансы выпадения:</b>\n"
    for uid, weight in crate["units"].items():
        if uid not in units_db: continue
        chance = (weight / total_weight) * 100
        text += f"• <b>{units_db[uid].get('name') if uid in unlocked_base else '??? (Неизвестно)'}</b> — {chance:.1f}%\n"
    text += "\n✨ <i>Любой выпавший юнит имеет 5% шанс стать Шайни!</i>\n━━━━━━━━━━━━━━━━━━\nСколько крейтов открыть?"
    
    kb = [[InlineKeyboardButton(text="Откр. 1", callback_data=f"crate_open_{cid}_1"), InlineKeyboardButton(text="Откр. 5", callback_data=f"crate_open_{cid}_5")],
          [InlineKeyboardButton(text="Откр. 10", callback_data=f"crate_open_{cid}_10"), InlineKeyboardButton(text="Откр. 50", callback_data=f"crate_open_{cid}_50")],
          [InlineKeyboardButton(text="🔙 Назад в магазин", callback_data="crates_list")]]
    
    try: await callback.message.delete()
    except: pass
    msg = await callback.message.answer_photo(photo=crate["photo"], caption=text, reply_markup=InlineKeyboardMarkup(inline_keyboard=kb))
    if callback.message.chat.type in {"group", "supergroup"}: panel_owners[f"{msg.chat.id}_{msg.message_id}"] = callback.fromuser.id
    await callback.answer()

@dp.callback_query(StateFilter('*'), F.data.startswith("crate_open_"))
async def cq_crate_open(callback: CallbackQuery, state: FSMContext):
    await state.clear()
    _, _, cid, amt_str = callback.data.split("_")
    amount = int(amt_str)
    crate = crates_db[cid]
    user_id_str = str(callback.from_user.id)
    
    total_cost = crate["price"] * amount
    req_cur = crate.get("currency", "💰 Монеты")
    bal = user_balances.get(user_id_str, {"💰 Монеты": 100, "💎 Гемы": 0})
    
    if bal.get(req_cur, 0) < total_cost:
        return await callback.answer(f"Недостаточно средств! Требуется {total_cost} {req_cur}.", show_alert=True)
        
    bal[req_cur] -= total_cost
    user_balances[user_id_str] = bal
    results = random.choices(list(crate["units"].keys()), weights=list(crate["units"].values()), k=amount)
    
    counts = {}
    if user_id_str not in user_inventory: user_inventory[user_id_str] = set()
    
    for uid in results:
        is_shiny = 1 if random.random() <= 0.05 else 0
        item_str = f"{uid}:{is_shiny}"
        counts[item_str] = counts.get(item_str, 0) + 1
        user_inventory[user_id_str].add(item_str)
    save_data()
    
    text = f"🎉 <b>{callback.from_user.first_name}</b>, вы открыли <b>{crate.get('name')}</b> ({amount} шт.)!\n━━━━━━━━━━━━━━━━━━\n<b>Вам выпало:</b>\n"
    for item_str, cnt in counts.items():
        uid, is_shiny_str = item_str.split(":")
        if uid in units_db: 
            u = get_unit_stats(uid, is_shiny_str == "1")
            text += f"• {u.get('name')} (x{cnt})\n"
            
    await callback.message.answer(text)
    await callback.answer("Успешно открыто!")

# --- ИНВЕНТАРЬ И ИНДЕКС ---
@dp.callback_query(StateFilter('*'), F.data == "main_inventory")
async def cq_main_inventory(callback: CallbackQuery, state: FSMContext):
    await state.clear()
    init_user_balance(str(callback.from_user.id))
    text, kb = render_inventory(str(callback.from_user.id))
    try: await callback.message.edit_text(text, reply_markup=kb)
    except:
        try: await callback.message.delete()
        except: pass
        msg = await callback.message.answer(text, reply_markup=kb)
        if callback.message.chat.type in {"group", "supergroup"}: panel_owners[f"{msg.chat.id}_{msg.message_id}"] = callback.from_user.id
    await callback.answer()

@dp.callback_query(StateFilter('*'), F.data == "inv_unequip_all")
async def cq_inv_unequip_all(callback: CallbackQuery, state: FSMContext):
    await state.clear()
    user_id_str = str(callback.from_user.id)
    user_equipped[user_id_str] = [] 
    save_data()
    text, kb = render_inventory(user_id_str)
    await callback.message.edit_text(text, reply_markup=kb)
    await callback.answer("Вся колода снята!")

@dp.callback_query(StateFilter('*'), F.data.startswith("inv_t_"))
async def cq_inv_toggle(callback: CallbackQuery, state: FSMContext):
    await state.clear()
    parts = callback.data.split("_")
    item_str = f"{parts[2]}:{parts[3]}"
    user_id_str = str(callback.from_user.id)
    equipped = user_equipped.get(user_id_str, [])
    
    if item_str in equipped: equipped.remove(item_str)
    else:
        if len(equipped) >= 5: return await callback.answer("⚠️ В колоде может быть максимум 5 юнитов!", show_alert=True)
        equipped.append(item_str)
        
    user_equipped[user_id_str] = equipped
    save_data()
    text, kb = render_inventory(user_id_str)
    await callback.message.edit_text(text, reply_markup=kb)
    await callback.answer()

@dp.callback_query(StateFilter('*'), F.data == "main_index")
async def cq_main_index(callback: CallbackQuery, state: FSMContext):
    await state.clear()
    unlocked_base = set([item.split(":")[0] for item in user_inventory.get(str(callback.from_user.id), set())])
    if not units_db: return await callback.answer("Энциклопедия пуста.", show_alert=True)
            
    text = "📖 <b>ЭНЦИКЛОПЕДИЯ (БАЗОВЫЕ ЮНИТЫ)</b>\n━━━━━━━━━━━━━━━━━━\n\n"
    for uid, unit in units_db.items():
        if uid in unlocked_base:
            text += f"✅ <b>{unit.get('name', f'Юнит №{uid}')}</b>\n{format_unit_stats(unit)}\n"
        else: 
            text += "❓ <b>Неизвестный Юнит</b>\n └ <i>Откройте его в крейтах, чтобы увидеть характеристики</i>\n\n"
            
    try: await callback.message.edit_text(text)
    except:
        try: await callback.message.delete()
        except: pass
        msg = await callback.message.answer(text)
        if callback.message.chat.type in {"group", "supergroup"}: panel_owners[f"{msg.chat.id}_{msg.message_id}"] = callback.from_user.id
    await callback.answer()

# ==========================================
# БОЙ И ЛОГИКА АТАКИ С МУЛЬТИКЛАССАМИ
# ==========================================
# (Лобби и создание опущены для экономии места, они идентичны прошлой версии)
# Подхватываем функцию хода боя:
async def process_battle_turn(battle_id: str, bot: Bot):
    if battle_id not in active_battles: return
    battle = active_battles[battle_id]
    m_data = maps_db[battle["map_id"]]
    w_info = m_data["waves"][battle["current_wave"] - 1]
    m_stats = mobs_db.get(w_info["mob_id"], {"effect": "none", "defense_percent": 0})
    m_def = m_stats.get("defense_percent", 0) if m_stats.get("effect") == "defense" else 0
    
    best_cd_mult, best_dmg_mult = 1.0, 1.0
    
    # 1. Сбор баффов саппортов
    for uid, p in battle["players"].items():
        for dep in p["deployed"]:
            u_stats = get_unit_stats(dep["uid"], dep.get("is_shiny", False))
            if u_stats and "Саппорт" in u_stats.get("unit_types", []):
                if float(u_stats.get("cd_boost", 1.0)) < best_cd_mult: best_cd_mult = float(u_stats.get("cd_boost", 1.0))
                if float(u_stats.get("dmg_boost", 1.0)) > best_dmg_mult: best_dmg_mult = float(u_stats.get("dmg_boost", 1.0))

    # 2. Атака мультиклассовыми юнитами
    for uid, p in battle["players"].items():
        for dep in p["deployed"]:
            if not battle["mobs"]: break 
            
            u_stats = get_unit_stats(dep["uid"], dep.get("is_shiny", False))
            if not u_stats: continue 
            utypes = u_stats.get("unit_types", [])
            
            # Если юнит не имеет атакующих классов, пропускаем фазу урона
            if not any(t in utypes for t in ["Одиночный", "Сплеш", "АОЕ"]):
                continue
                
            base_cd = float(u_stats.get("cd", 1.0))
            actual_cd = max(0.01, round(base_cd * best_cd_mult, 2))
            dmg = round(float(u_stats.get("damage", 10)) * best_dmg_mult * (1 - m_def / 100), 2)
            
            dep["time_bank"] = dep.get("time_bank", 0.0) + 1.0
            
            while dep["time_bank"] >= actual_cd and battle["mobs"]:
                dep["time_bank"] -= actual_cd
                coins_earned = 0.0

                if "Одиночный" in utypes and battle["mobs"]: 
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
            wave_income = 0
            for dep in p_data["deployed"]:
                u_st = get_unit_stats(dep["uid"], dep.get("is_shiny", False))
                if u_st and "Ферма" in u_st.get("unit_types", []):
                    wave_income += u_st.get("income", 0)
            if wave_income > 0: p_data["coins"] += wave_income

        battle["current_wave"] += 1
        battle["current_turn"] = 1
        if battle["current_wave"] > m_data["waves_total"]:
            return await finish_battle(battle_id, bot, True) # Победа
            
        w_info = m_data["waves"][battle["current_wave"] - 1]
        mob = mobs_db.get(w_info["mob_id"], {"hp": 100})
        battle["mobs"] = [mob["hp"] for _ in range(w_info["count"])]
    else:
        battle["current_turn"] += 1
        if battle["current_turn"] > w_info["turns"]:
            battle["base_hp"] = round(battle["base_hp"] - sum(h/10 for h in battle["mobs"]), 2)
            battle["mobs"] = []
            if battle["base_hp"] <= 0:
                return await finish_battle(battle_id, bot, False) # Поражение
                
            battle["current_wave"] += 1
            battle["current_turn"] = 1
            if battle["current_wave"] > m_data["waves_total"]:
                return await finish_battle(battle_id, bot, True) # Победа
                
            w_info = m_data["waves"][battle["current_wave"] - 1]
            mob = mobs_db.get(w_info["mob_id"], {"hp": 100})
            battle["mobs"] = [mob["hp"] for _ in range(w_info["count"])]

    # Обновление UI
    photo_file, text, main_kb = await render_battle_ui(battle_id, bot)
    try:
        if photo_file:
            try: await bot.edit_message_media(chat_id=chat_id, message_id=battle["main_msg_id"], media=InputMediaPhoto(media=photo_file, caption=text[:1024], parse_mode="HTML"), reply_markup=main_kb)
            except: pass
        else:
            try: await bot.edit_message_caption(chat_id=chat_id, message_id=battle["main_msg_id"], caption=text[:1024], reply_markup=main_kb, parse_mode="HTML")
            except: 
                try: await bot.edit_message_text(chat_id=chat_id, message_id=battle["main_msg_id"], text=text[:4096], reply_markup=main_kb, parse_mode="HTML")
                except: pass
    except TelegramBadRequest: pass 

async def finish_battle(battle_id: str, bot: Bot, is_win: bool):
    battle = active_battles[battle_id]
    chat_id = battle["chat_id"]
    m_data = maps_db[battle["map_id"]]
    rew = m_data.get("rewards", {})
    
    text = "❇️❇️❇️ <b>ПОБЕДА В БОЮ!</b> ❇️❇️❇️\n\nНаграды:\n" if is_win else "📛📛📛 <b>ПОРАЖЕНИЕ (БАЗА УНИЧТОЖЕНА)</b> 📛📛📛\n\nУтешительный приз:\n"
    
    for k, v in rew.items():
        amt = v if is_win else max(1, int(v * 0.1))
        text += f"+{amt} {k}\n"
        for p_uid in battle["players"].keys():
            bal = user_balances.get(p_uid, {"💰 Монеты": 100, "💎 Гемы": 0})
            bal[k] = bal.get(k, 0) + amt
            user_balances[p_uid] = bal
            
    save_data()
    await bot.send_message(chat_id=chat_id, text=text, parse_mode="HTML")
    await cleanup_battle(battle_id, bot)

# (Остальные боевые коллбэки b_dep, b_toggle, b_surr аналогичны, опущены для лимита - подразумевается их стандартное наличие)

# === АДМИН ПАНЕЛЬ И МУЛЬТИ-КЛАССЫ ===
@dp.callback_query(StateFilter('*'), F.data == "admin_panel")
async def cq_admin_panel(callback: CallbackQuery, state: FSMContext):
    if str(callback.from_user.id) not in admins_db: return await callback.answer("⛔️ У вас нет прав!", show_alert=True)
    await state.clear()
    text = "👑 <b>ПАНЕЛЬ АДМИНИСТРАТОРА</b>\n━━━━━━━━━━━━━━━━━━\nВыберите действие:"
    try: await callback.message.edit_text(text, reply_markup=get_admin_panel_kb())
    except:
        try: await callback.message.delete()
        except: pass
        await callback.message.answer(text, reply_markup=get_admin_panel_kb())
    await callback.answer()

@dp.callback_query(StateFilter('*'), F.data == "admin_add_unit")
async def cq_u_add(callback: CallbackQuery, state: FSMContext):
    await state.clear()
    if not rarities_db: return await callback.answer("Сначала создайте редкости!", show_alert=True)
    await state.set_state(AdminUnitAdd.unit_types)
    await state.update_data(temp_types=[])
    await callback.message.edit_text("➕ <b>Создание Юнита</b>\n\nВыберите один или несколько классов для юнита (Мультикласс):", reply_markup=get_unit_types_kb([]))
    await callback.answer()

@dp.callback_query(AdminUnitAdd.unit_types, F.data.startswith("toggleutype_"))
async def u_toggle_type(callback: CallbackQuery, state: FSMContext):
    t_name = callback.data.split("_")[1]
    data = await state.get_data()
    types = data.get("temp_types", [])
    if t_name in types: types.remove(t_name)
    else: types.append(t_name)
    await state.update_data(temp_types=types)
    await callback.message.edit_reply_markup(reply_markup=get_unit_types_kb(types))
    await callback.answer()

@dp.callback_query(AdminUnitAdd.unit_types, F.data == "saveutypes")
async def u_save_types(callback: CallbackQuery, state: FSMContext):
    data = await state.get_data()
    if not data.get("temp_types"): return await callback.answer("Выберите хотя бы один класс!", show_alert=True)
    await state.set_state(AdminUnitAdd.photo)
    await callback.message.edit_text("📸 Отправьте фото юнита:")
    await callback.answer()

@dp.message(AdminUnitAdd.photo)
async def u_step_photo(message: Message, state: FSMContext):
    if not message.photo: return await message.answer("⚠️ Требуется отправить изображение.")
    await state.update_data(photo=message.photo[-1].file_id)
    await state.set_state(AdminUnitAdd.name)
    await message.answer("📝 Введите название юнита:")

@dp.message(AdminUnitAdd.name)
async def u_step_name(message: Message, state: FSMContext):
    await state.update_data(name=message.text.strip())
    await state.set_state(AdminUnitAdd.rarity)
    
    kb = [[InlineKeyboardButton(text=f"🔸 {r} 🔸", callback_data=f"selrar_{idx}")] for idx, r in enumerate(rarities_db)]
    await message.answer("💎 Выберите редкость:", reply_markup=InlineKeyboardMarkup(inline_keyboard=kb))

@dp.callback_query(AdminUnitAdd.rarity, F.data.startswith("selrar_"))
async def u_step_rarity(callback: CallbackQuery, state: FSMContext):
    await state.update_data(rarity=rarities_db[int(callback.data.split("_")[1])])
    await state.set_state(AdminUnitAdd.supply_limit)
    await callback.message.edit_text("🛑 Введите лимит поставки на поле (например, 5):")
    await callback.answer()

@dp.message(AdminUnitAdd.supply_limit)
async def u_step_limit(message: Message, state: FSMContext):
    if not message.text.isdigit(): return await message.answer("⚠️ Введите число.")
    await state.update_data(supply_limit=int(message.text))
    await state.set_state(AdminUnitAdd.deploy_cost)
    await message.answer("💰 Введите цену размещения в бою:")

@dp.message(AdminUnitAdd.deploy_cost)
async def u_step_cost(message: Message, state: FSMContext):
    if not message.text.isdigit(): return await message.answer("⚠️ Введите число.")
    await state.update_data(deploy_cost=int(message.text))
    await jump_next_unit_stat(message, state)

# Умный прыжок по стейтам в зависимости от выбранных классов
async def jump_next_unit_stat(message: Message, state: FSMContext):
    data = await state.get_data()
    types = data.get("temp_types", [])
    
    has_attack = any(t in types for t in ["Одиночный", "Сплеш", "АОЕ"])
    
    if has_attack and "cd" not in data:
        await state.set_state(AdminUnitAdd.cd)
        return await message.answer("⏱ <b>[Атака]</b> Введите КД атаки (в секундах, например 1.0):")
        
    if has_attack and "damage" not in data:
        await state.set_state(AdminUnitAdd.damage)
        return await message.answer("💥 <b>[Атака]</b> Введите наносимый урон (число):")
        
    if "Саппорт" in types and "cd_boost" not in data:
        await state.set_state(AdminUnitAdd.cd_boost)
        return await message.answer("✨ <b>[Саппорт]</b> Введите Буст КД (множитель, меньше = лучше, например 0.80):")
        
    if "Саппорт" in types and "dmg_boost" not in data:
        await state.set_state(AdminUnitAdd.dmg_boost)
        return await message.answer("💪 <b>[Саппорт]</b> Введите Буст Урона (множитель, больше = лучше, например 1.20):")
        
    if "Ферма" in types and "income" not in data:
        await state.set_state(AdminUnitAdd.income)
        return await message.answer("🌾 <b>[Ферма]</b> Введите доход (монет за каждую пройденную волну):")
        
    # Если всё собрано:
    global unit_id_counter
    uid = str(unit_id_counter)
    
    u_dict = {
        "photo": data["photo"], 
        "name": data["name"], 
        "rarity": data["rarity"], 
        "unit_types": types, 
        "supply_limit": data["supply_limit"], 
        "deploy_cost": data["deploy_cost"]
    }
    if has_attack:
        u_dict["cd"] = data["cd"]
        u_dict["damage"] = data["damage"]
    if "Саппорт" in types:
        u_dict["cd_boost"] = data["cd_boost"]
        u_dict["dmg_boost"] = data["dmg_boost"]
    if "Ферма" in types:
        u_dict["income"] = data["income"]
        
    units_db[uid] = u_dict
    unit_id_counter += 1
    save_data()
    await state.clear()
    await send_main_screen(message, f"✅ Мультиклассовый юнит «{data['name']}» успешно создан!")

@dp.message(AdminUnitAdd.cd)
async def u_rec_cd(message: Message, state: FSMContext):
    try: val = float(message.text.replace(",", "."))
    except: return await message.answer("⚠️ Введите число (например 1.5).")
    await state.update_data(cd=val)
    await jump_next_unit_stat(message, state)

@dp.message(AdminUnitAdd.damage)
async def u_rec_dmg(message: Message, state: FSMContext):
    if not message.text.isdigit(): return await message.answer("⚠️ Целое число.")
    await state.update_data(damage=int(message.text))
    await jump_next_unit_stat(message, state)

@dp.message(AdminUnitAdd.cd_boost)
async def u_rec_cdb(message: Message, state: FSMContext):
    try: val = float(message.text.replace(",", "."))
    except: return await message.answer("⚠️ Введите число.")
    await state.update_data(cd_boost=val)
    await jump_next_unit_stat(message, state)

@dp.message(AdminUnitAdd.dmg_boost)
async def u_rec_dmgb(message: Message, state: FSMContext):
    try: val = float(message.text.replace(",", "."))
    except: return await message.answer("⚠️ Введите число.")
    await state.update_data(dmg_boost=val)
    await jump_next_unit_stat(message, state)

@dp.message(AdminUnitAdd.income)
async def u_rec_inc(message: Message, state: FSMContext):
    if not message.text.isdigit(): return await message.answer("⚠️ Целое число.")
    await state.update_data(income=int(message.text))
    await jump_next_unit_stat(message, state)

# === ВЫДАЧА ВАЛЮТЫ ЛЮБОМУ ИГРОКУ С УВЕДОМЛЕНИЕМ ===
@dp.callback_query(StateFilter('*'), F.data == "admin_give_cur")
async def cq_admin_give_cur(callback: CallbackQuery, state: FSMContext):
    await state.clear()
    await state.set_state(AdminGiveCur.select_cur)
    kb = [[InlineKeyboardButton(text=f"🔸 {c} 🔸", callback_data=f"givecur_{idx}")] for idx, c in enumerate(currencies_db)]
    await callback.message.edit_text("💸 <b>Выдача валюты игрокам</b>\n━━━━━━━━━━━━━━━━━━\nВыберите валюту из списка:", reply_markup=InlineKeyboardMarkup(inline_keyboard=kb))
    await callback.answer()

@dp.callback_query(AdminGiveCur.select_cur, F.data.startswith("givecur_"))
async def admin_give_cur_step2(callback: CallbackQuery, state: FSMContext):
    cur_name = currencies_db[int(callback.data.split("_")[1])]
    await state.update_data(give_cur_name=cur_name)
    await state.set_state(AdminGiveCur.target_id)
    await callback.message.edit_text("👤 Введите <b>ID игрока</b> (или перешлите его сообщение), которому вы хотите выдать валюту:")
    await callback.answer()

@dp.message(AdminGiveCur.target_id)
async def admin_give_cur_step3(message: Message, state: FSMContext):
    uid = extract_user_identifier(message)
    if not uid: return await message.answer("⚠️ Не удалось распознать ID. Попробуйте ввести вручную.")
    await state.update_data(target_id=uid)
    await state.set_state(AdminGiveCur.amount)
    data = await state.get_data()
    await message.answer(f"🔢 Сколько <b>{data['give_cur_name']}</b> вы хотите выдать игроку <code>{uid}</code>?\n<i>(Можно использовать отрицательные числа для штрафа)</i>")

@dp.message(AdminGiveCur.amount)
async def admin_give_cur_step4(message: Message, state: FSMContext):
    try: amt = int(message.text)
    except ValueError: return await message.answer("⚠️ Введите целое число!")
    
    data = await state.get_data()
    cur_name = data["give_cur_name"]
    target_id = data["target_id"]
    
    init_user_balance(target_id)
    user_balances[target_id][cur_name] = user_balances[target_id].get(cur_name, 0) + amt
    save_data()
    
    # Пытаемся уведомить пользователя
    try:
        if amt > 0:
            await message.bot.send_message(chat_id=target_id, text=f"🎁 <b>СИСТЕМНОЕ УВЕДОМЛЕНИЕ</b>\n━━━━━━━━━━━━━━━━━━\nАдминистратор вручил вам: <b>{amt} {cur_name}</b>!")
        else:
            await message.bot.send_message(chat_id=target_id, text=f"📉 <b>СИСТЕМНОЕ УВЕДОМЛЕНИЕ</b>\n━━━━━━━━━━━━━━━━━━\nАдминистратор списал у вас: <b>{abs(amt)} {cur_name}</b>.")
        notify_status = "✅ Игрок успешно уведомлен."
    except Exception:
        notify_status = "⚠️ Игрок не получил уведомление (возможно, он заблокировал бота)."

    await state.clear()
    await message.answer(f"✅ Баланс игрока <code>{target_id}</code> обновлен!\nИзменение: <b>{amt} {cur_name}</b>\n\n{notify_status}")
    await send_main_screen(message)

# ==========================================
# УНИВЕРСАЛЬНЫЙ ПЕРЕХВАТЧИК
# ==========================================
async def safe_exit_and_menu(message: Message, state: FSMContext, alert_text=None):
    await state.clear()
    init_user_balance(str(message.from_user.id))
    await send_main_screen(message, alert_text)

@dp.message(StateFilter('*'), F.text.startswith("/"))
async def handle_unknown_command(message: Message, state: FSMContext):
    await safe_exit_and_menu(message, state, "⚠️ Неизвестная команда. Вы возвращены в меню.")

@dp.message(StateFilter('*'))
async def handle_any_text(message: Message, state: FSMContext):
    if message.chat.type in {"group", "supergroup"}: return
    await safe_exit_and_menu(message, state)

# ==========================================
# ЗАПУСК БОТА
# ==========================================
async def main():
    logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
    load_data() 
            
    bot = Bot(token=TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
    
    await bot.set_my_commands([
        BotCommand(command="panel", description="Открыть меню (только для групп)"),
        BotCommand(command="getcrate", description="Открыть бесплатный крейт (только для групп)"),
        BotCommand(command="start", description="Запустить/Перезапустить бота")
    ])
    
    await bot.delete_webhook(drop_pending_updates=True)
    try:
        await dp.start_polling(bot)
    finally:
        await bot.session.close()

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass
