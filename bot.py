import asyncio
import logging
import json
import sys
import os
from datetime import datetime, timedelta

from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import Command, StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import ReplyKeyboardMarkup, KeyboardButton, InlineKeyboardMarkup, InlineKeyboardButton, ReplyKeyboardRemove
from aiogram.utils.keyboard import InlineKeyboardBuilder
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger

import config
from database import Database
from states import AdminStates, UserStates

# Настройка логирования
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler('bot.log', encoding='utf-8', mode='a')
    ]
)
logger = logging.getLogger(__name__)

# Глобальные переменные
bot = None
storage = None
dp = None
db = Database()
scheduler = AsyncIOScheduler()

# ==================== ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ ====================
def format_time_left(expiry_date_str: str) -> str:
    """Форматирует оставшееся время подписки в читаемый вид"""
    try:
        if not expiry_date_str:
            return "не активна"
            
        expiry_date = datetime.fromisoformat(expiry_date_str)
        now = datetime.now()
        
        # Бессрочная подписка
        if expiry_date.year == 2099:
            return "∞ (навсегда)"
        
        time_left = expiry_date - now
        
        if time_left.total_seconds() <= 0:
            return "истекла"
        
        days = time_left.days
        hours = time_left.seconds // 3600
        minutes = (time_left.seconds % 3600) // 60
        
        if days > 0:
            return f"{days} д. {hours} ч."
        elif hours > 0:
            return f"{hours} ч. {minutes} мин."
        else:
            return f"{minutes} мин."
    except Exception as e:
        logger.error(f"Ошибка форматирования времени: {e}")
        return "ошибка"

def format_balance(amount: float) -> str:
    """Форматирует сумму баланса"""
    return f"{amount:.2f} руб."

def format_price(amount: float) -> str:
    """Форматирует цену"""
    return f"{amount:.0f} руб."

        # ==================== КЛАВИАТУРЫ ====================
def get_main_keyboard(user_id: int = None) -> ReplyKeyboardMarkup:
            """Главное меню для всех пользователей"""
    keyboard = [
                        [KeyboardButton(text="👤 Профиль"), KeyboardButton(text="📦 Паки")],
                        [KeyboardButton(text="ℹ️ Подписка")]
    ]
    
    if user_id and user_id in config.ADMIN_IDS:
        keyboard.append([KeyboardButton(text="⚙️ Админ-панель")])
    
    return ReplyKeyboardMarkup(keyboard=keyboard, resize_keyboard=True)

def get_profile_keyboard() -> InlineKeyboardMarkup:
    """Клавиатура для раздела профиля"""
    return InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text="⬅️ Назад", callback_data="menu_back"),
        InlineKeyboardButton(text="💳 Пополнить", callback_data="deposit")
    ]])

def get_back_keyboard() -> InlineKeyboardMarkup:
    """Клавиатура с кнопкой Назад"""
    return InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text="⬅️ Назад", callback_data="menu_back")
    ]])

def get_admin_keyboard() -> ReplyKeyboardMarkup:
    """Клавиатура админ-панели"""
            return ReplyKeyboardMarkup(
                keyboard=[
                    [KeyboardButton(text="📊 Информация"), KeyboardButton(text="📢 Рассылка")],
            [KeyboardButton(text="➕ Добавить пак"), KeyboardButton(text="✏️ Управление паками")],
            [KeyboardButton(text="ℹ️ Подписка (глобальная)"), KeyboardButton(text="👥 Управление пользователями")],
            [KeyboardButton(text="📈 Статистика"), KeyboardButton(text="🧹 Очистить статистику")],
            [KeyboardButton(text="⬅️ В главное меню")]
                ],
                resize_keyboard=True
            )

def get_duration_keyboard(pack_id: int = None, is_global: bool = False) -> InlineKeyboardMarkup:
    """Клавиатура выбора длительности подписки"""
            if is_global:
                callback_prefix = "global_duration"
        back_callback = "back_to_subscription"
            else:
                callback_prefix = f"duration_{pack_id}"
        back_callback = f"pack_{pack_id}"
    
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="5 дней", callback_data=f"{callback_prefix}_5"),
            InlineKeyboardButton(text="10 дней", callback_data=f"{callback_prefix}_10")
        ],
        [
            InlineKeyboardButton(text="15 дней", callback_data=f"{callback_prefix}_15"),
            InlineKeyboardButton(text="30 дней", callback_data=f"{callback_prefix}_30")
        ],
        [
            InlineKeyboardButton(text="Навсегда", callback_data=f"{callback_prefix}_forever"),
            InlineKeyboardButton(text="⬅️ Назад", callback_data=back_callback)
        ]
    ])

def get_packs_keyboard(packs: list) -> InlineKeyboardMarkup:
    """Клавиатура списка паков"""
            builder = InlineKeyboardBuilder()
            for pack in packs:
        pack_id, name, description, prices, channel_id, created_at, is_active = pack
                builder.button(text=name, callback_data=f"pack_{pack_id}")
            builder.button(text="⬅️ Назад", callback_data="menu_back")
            builder.adjust(1)
            return builder.as_markup()

def get_pack_detail_keyboard(pack_id: int) -> InlineKeyboardMarkup:
    """Клавиатура деталей пака"""
    return InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text="🛒 Купить", callback_data=f"buy_{pack_id}"),
        InlineKeyboardButton(text="⬅️ Назад", callback_data="back_to_packs")
    ]])

def get_subscription_keyboard() -> InlineKeyboardMarkup:
    """Клавиатура для раздела подписки"""
    return InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text="🛒 Купить подписку", callback_data="buy_global_subscription"),
        InlineKeyboardButton(text="⬅️ Назад", callback_data="menu_back")
    ]])

def get_confirmation_keyboard(confirm_data: str = "confirm", cancel_data: str = "cancel") -> InlineKeyboardMarkup:
    """Универсальная клавиатура подтверждения"""
    return InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text="✅ Подтвердить", callback_data=confirm_data),
        InlineKeyboardButton(text="❌ Отменить", callback_data=cancel_data)
    ]])

def get_admin_management_keyboard() -> InlineKeyboardMarkup:
    """Клавиатура управления пользователями"""
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="💵 Пополнить баланс", callback_data="admin_deposit"),
            InlineKeyboardButton(text="➖ Списать средства", callback_data="admin_withdraw")
        ],
        [
            InlineKeyboardButton(text="👀 Просмотр профиля", callback_data="admin_view_profile"),
            InlineKeyboardButton(text="📊 Статистика пользователя", callback_data="admin_user_stats")
        ],
        [
            InlineKeyboardButton(text="⬅️ Назад", callback_data="admin_back")
        ]
    ])

def get_pack_management_keyboard() -> InlineKeyboardMarkup:
    """Клавиатура управления паками"""
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="✏️ Редактировать пак", callback_data="admin_edit_pack"),
            InlineKeyboardButton(text="🚫 Деактивировать пак", callback_data="admin_deactivate_pack")
        ],
        [
            InlineKeyboardButton(text="⬅️ Назад", callback_data="admin_back")
        ]
    ])

# ==================== СИСТЕМНЫЕ ФУНКЦИИ ====================
        async def check_subscription(user_id: int) -> bool:
    """Проверяет подписку пользователя на канал"""
            try:
                logger.info(f"Проверка подписки для пользователя {user_id}")
                chat_member = await bot.get_chat_member(chat_id=config.PRIVATE_CHANNEL_ID, user_id=user_id)
                is_subscribed = chat_member.status in ['member', 'administrator', 'creator']
                logger.info(f"Пользователь {user_id} подписан: {is_subscribed}")
                return is_subscribed
            except Exception as e:
                logger.error(f"Ошибка при проверке подписки для {user_id}: {e}")
                return False

async def update_user_activity(user_id: int):
    """Обновляет активность пользователя"""
    try:
        await db.update_user_activity(user_id)
    except Exception as e:
        logger.error(f"Ошибка обновления активности пользователя {user_id}: {e}")

async def check_expired_subscriptions():
    """Проверяет и деактивирует истекшие подписки"""
    try:
        logger.info("Проверка истекших подписки...")
        
        # Проверяем истекшие подписки на паки
        expired_packs = await db.get_expired_subscriptions()
        for subscription in expired_packs:
            user_pack_id, user_id, pack_id, purchase_date, expiry_date, amount, status, pack_name, channel_id, username = subscription
            await db.deactivate_expired_subscription(user_pack_id)
            logger.info(f"Деактивирована подписка {user_pack_id} пользователя {user_id} на пак {pack_name}")
            
            try:
                # Уведомляем пользователя
                await bot.send_message(
                    user_id,
                    f"⚠️ Ваша подписка на пак '{pack_name}' истекла. Доступ к каналу закрыт."
                )
            except Exception as e:
                logger.error(f"Не удалось уведомить пользователя {user_id}: {e}")
        
        # Проверяем истекшие глобальные подписки
        expired_global = await db.get_expired_global_subscriptions()
        for user_data in expired_global:
            user_id, username, subscription_until = user_data
            await db.deactivate_global_subscription(user_id)
            logger.info(f"Деактивирована глобальная подписка пользователя {user_id}")
            
            try:
                # Уведомляем пользователя
                await bot.send_message(
                    user_id,
                    "⚠️ Ваша глобальная подписка истекла. Доступ ко всем пакам закрыт."
                )
            except Exception as e:
                logger.error(f"Не удалось уведомить пользователя {user_id}: {e}")
                
    except Exception as e:
        logger.error(f"Ошибка при проверке истекших подписок: {e}")

async def send_subscription_reminders():
    """Отправляет напоминания об истекающих подписках"""
    try:
        logger.info("Отправка напоминаний о подписках...")
        # Здесь можно добавить логику отправки напоминаний
        # за 24 часа до окончания подписки
    except Exception as e:
        logger.error(f"Ошибка при отправке напоминаний: {e}")

# Обработчики будут зарегистрированы в main()

# ==================== ЗАПУСК БОТА ====================
async def main():
    """Основная функция запуска бота"""
    global bot, storage, dp
    
    logger.info("=== ЗАПУСК БОТА ===")
    
    try:
        # Инициализация базы данных
        logger.info("Инициализация базы данных...")
        await db.create_tables()
        logger.info("База данных инициализирована")
        
        # Инициализация бота
        logger.info("Инициализация бота...")
        bot = Bot(token=config.BOT_TOKEN)
        storage = MemoryStorage()
        dp = Dispatcher(storage=storage)
        
        # Проверка токена бота
        logger.info("Проверка токена бота...")
        bot_info = await bot.get_me()
        logger.info(f"Бот успешно инициализирован: @{bot_info.username} (ID: {bot_info.id})")
        
        # ==================== РЕГИСТРАЦИЯ ОБРАБОТЧИКОВ ====================
        @dp.message(Command("start"))
        async def cmd_start(message: types.Message):
            """Обработчик команды /start"""
            user_id = message.from_user.id
            username = message.from_user.full_name
            
            await update_user_activity(user_id)
            logger.info(f"Команда /start от пользователя {user_id} ({username})")
            
            try:
                await db.add_user(user_id, username)
                logger.info(f"Пользователь {user_id} добавлен в БД")

                if not await check_subscription(user_id):
                    # Пользователь не подписан
                    keyboard = InlineKeyboardMarkup(inline_keyboard=[[
                        InlineKeyboardButton(
                            text="✅ Подписаться на канал", 
                            url="https://t.me/+7kpMpaDvyc8zNjVi"
                        ),
                    ], [
                        InlineKeyboardButton(text="🔄 Проверить подписку", callback_data="check_subscription")
                    ]])
                    
                    await message.answer(
                        "📢 Для использования бота необходимо подписаться на наш приватный канал.\n\n"
                        "После подписки нажмите кнопку 'Проверить подписку'.",
                        reply_markup=keyboard
                    )
                    logger.info(f"Пользователь {user_id} не подписан, отправлено предложение подписки")
                else:
                    # Пользователь подписан - показываем главное меню
                    await message.answer(
                        "👋 Добро пожаловать! Выберите действие:",
                        reply_markup=get_main_keyboard(user_id)
                    )
                    logger.info(f"Пользователь {user_id} подписан, показано главное меню")
                    
            except Exception as e:
                logger.error(f"Ошибка в обработчике /start для пользователя {user_id}: {e}")
                await message.answer("❌ Произошла ошибка. Попробуйте позже.")

        @dp.callback_query(F.data == "check_subscription")
        async def check_subscription_callback(callback: types.CallbackQuery):
            """Обработчик проверки подписки"""
            user_id = callback.from_user.id
            await update_user_activity(user_id)
            logger.info(f"Проверка подписки (callback) для пользователя {user_id}")
            
            try:
                if await check_subscription(user_id):
                    await callback.message.edit_text("✅ Спасибо за подписку! Добро пожаловать!")
                    await callback.message.answer(
                        "Выберите действие:",
                        reply_markup=get_main_keyboard(user_id)
                    )
                    logger.info(f"Пользователь {user_id} успешно прошел проверку подписки")
                else:
                    await callback.answer(
                        "❌ Вы еще не подписались на канал. Пожалуйста, подпишитесь и нажмите снова.", 
                        show_alert=True
                    )
                    logger.info(f"Пользователь {user_id} не прошел проверку подписки")
            except Exception as e:
                logger.error(f"Ошибка в callback проверки подписки для пользователя {user_id}: {e}")
                await callback.answer("❌ Ошибка проверки подписки", show_alert=True)

        @dp.message(F.text == "👤 Профиль")
        async def profile_handler(message: types.Message):
            """Обработчик раздела Профиль"""
            user_id = message.from_user.id
            await update_user_activity(user_id)
            logger.info(f"Запрос профиля от пользователя {user_id}")
            
            try:
                user_data = await db.get_user(user_id)
                
                if user_data:
                    user_id_db, username, balance, global_subscription_until, registered_at, last_activity = user_data
                    
                    # Получаем активные подписки на паки
                    user_packs = await db.get_user_packs(user_id)
                    subscriptions_text = ""
                    
                    if user_packs:
                        for pack in user_packs:
                            user_pack_id, user_id_db, pack_id, purchase_date, expiry_date, amount, status, pack_name, description, channel_id = pack
                            time_left = format_time_left(expiry_date)
                            subscriptions_text += f"\n📦 {pack_name}: осталось {time_left}"
                    else:
                        subscriptions_text = "\n❌ Активных подписок на паки нет"
                    
                    # Проверяем глобальную подписку
                    global_sub_text = ""
                    if global_subscription_until:
                        global_time_left = format_time_left(global_subscription_until)
                        if global_time_left != "истекла":
                            global_sub_text = f"\n🌟 Глобальная подписка: осталось {global_time_left}"
                        else:
                            global_sub_text = f"\n🌟 Глобальная подписка: {global_time_left}"
                    else:
                        global_sub_text = "\n🌟 Глобальная подписка: не активна"
                    
                    # Формируем текст профиля
                    profile_text = f"""
👤 **Ваш профиль**

🆔 ID: `{user_id_db}`
💰 Баланс: {format_balance(balance)}
📅 Зарегистрирован: {registered_at[:10] if registered_at else 'Неизвестно'}
{global_sub_text}
💎 **Подписки на паки:**{subscriptions_text}
                    """
                    await message.answer(profile_text.strip(), parse_mode="Markdown", reply_markup=get_profile_keyboard())
                    logger.info(f"Профиль пользователя {user_id} отправлен")
                else:
                    await message.answer("❌ Пользователь не найден в системе")
                    logger.warning(f"Пользователь {user_id} не найден в БД")
                    
            except Exception as e:
                logger.error(f"Ошибка получения профиля для пользователя {user_id}: {e}")
                await message.answer("❌ Ошибка загрузки профиля. Попробуйте позже.")

        @dp.message(F.text == "📦 Паки")
        async def packs_handler(message: types.Message):
            """Обработчик раздела Паки"""
            user_id = message.from_user.id
            await update_user_activity(user_id)
            logger.info(f"Запрос списка паков от пользователя {user_id}")
            
            try:
                packs = await db.get_packs()
                if not packs:
                    await message.answer(
                        "📦 На данный момент паков нет в продаже.", 
                        reply_markup=get_back_keyboard()
                    )
                    logger.info(f"Пользователь {user_id} запросил паки, но паков нет")
                    return
                
                await message.answer(
                    "📦 Выберите пак:", 
                    reply_markup=get_packs_keyboard(packs)
                )
                logger.info(f"Список паков отправлен пользователю {user_id}")
                
            except Exception as e:
                logger.error(f"Ошибка получения паков для пользователя {user_id}: {e}")
                await message.answer("❌ Ошибка загрузки паков. Попробуйте позже.")

        @dp.message(F.text == "ℹ️ Подписка")
        async def subscription_handler(message: types.Message):
            """Обработчик раздела Подписка"""
            user_id = message.from_user.id
            await update_user_activity(user_id)
            logger.info(f"Запрос информации о подписке от пользователя {user_id}")
            
            try:
                settings = await db.get_global_subscription_settings()
                if not settings:
                    await message.answer(
                        "ℹ️ Информация о глобальной подписке пока не настроена.", 
                        reply_markup=get_back_keyboard()
                    )
                    logger.info(f"Пользователь {user_id} запросил подписку, но настройки не заданы")
                    return
                
                id, description, prices_json, updated_at = settings
                prices = json.loads(prices_json)
                
                text = f"ℹ️ **Глобальная подписка**\n\n{description}\n\n"
                text += "🌟 **Доступ ко всем пакам!**\n\n"
                text += "💳 **Цены:**\n"
                
                for duration, price in prices.items():
                    text += f"• {duration}: {format_price(price)}\n"
                
                # Добавляем информацию о текущем статусе подписки
                    user_data = await db.get_user(user_id)
                    if user_data:
                    user_id_db, username, balance, global_subscription_until, registered_at, last_activity = user_data
                    if global_subscription_until:
                        time_left = format_time_left(global_subscription_until)
                        if time_left != "истекла":
                            text += f"\n✅ **Ваш статус:** активна ({time_left})"
                        else:
                            text += f"\n❌ **Ваш статус:** {time_left}"
                    else:
                        text += f"\n❌ **Ваш статус:** не активна"
                
                await message.answer(text, parse_mode="Markdown", reply_markup=get_subscription_keyboard())
                logger.info(f"Информация о подписке отправлена пользователю {user_id}")
                
                                except Exception as e:
                logger.error(f"Ошибка получения информации о подписке для пользователя {user_id}: {e}")
                await message.answer("❌ Ошибка загрузки информации о подписке. Попробуйте позже.")

        # ==================== ОБРАБОТЧИКИ ПАКОВ ====================
        @dp.callback_query(F.data.startswith("pack_"))
        async def pack_detail_handler(callback: types.CallbackQuery):
            """Обработчик деталей пака"""
            user_id = callback.from_user.id
            await update_user_activity(user_id)
            
            try:
                pack_id = int(callback.data.split("_")[1])
                logger.info(f"Пользователь {user_id} запросил детали пака {pack_id}")
                
                pack = await db.get_pack(pack_id)
                if pack:
                    pack_id, name, description, prices_json, channel_id, created_at, is_active = pack
                    prices = json.loads(prices_json)
                    
                    text = f"📦 **{name}**\n\n{description}\n\n"
                    text += "💳 **Цены:**\n"
                    
                    for duration, price in prices.items():
                        text += f"• {duration}: {format_price(price)}\n"
                    
                    await callback.message.edit_text(
                        text, 
                        parse_mode="Markdown", 
                        reply_markup=get_pack_detail_keyboard(pack_id)
                    )
                    logger.info(f"Детали пака {pack_id} отправлены пользователю {user_id}")
                else:
                    await callback.answer("❌ Пак не найден", show_alert=True)
                    logger.warning(f"Пак {pack_id} не найден для пользователя {user_id}")
                    
            except Exception as e:
                logger.error(f"Ошибка получения деталей пака для пользователя {user_id}: {e}")
                await callback.answer("❌ Ошибка загрузки пака", show_alert=True)

        @dp.callback_query(F.data.startswith("buy_"))
        async def buy_pack_handler(callback: types.CallbackQuery):
            """Обработчик начала покупки"""
            user_id = callback.from_user.id
            await update_user_activity(user_id)
            
            try:
            data = callback.data.split("_")
            if data[1] == "global":
                    logger.info(f"Пользователь {user_id} начал покупку глобальной подписки")
                    await buy_global_subscription_handler(callback)
            else:
                pack_id = int(data[1])
                logger.info(f"Пользователь {user_id} начал покупку пака {pack_id}")
                    await callback.message.edit_text(
                        "⏳ Выберите длительность подписки:", 
                        reply_markup=get_duration_keyboard(pack_id)
                    )
            except Exception as e:
                logger.error(f"Ошибка начала покупки для пользователя {user_id}: {e}")
                await callback.answer("❌ Ошибка обработки запроса", show_alert=True)

        @dp.callback_query(F.data.startswith("duration_"))
        async def duration_handler(callback: types.CallbackQuery):
            """Обработчик выбора длительности подписки на пак"""
            user_id = callback.from_user.id
            await update_user_activity(user_id)
            
            try:
            data = callback.data.split("_")
            pack_id = int(data[1])
            duration_key = data[2]
            
            logger.info(f"Пользователь {user_id} выбрал длительность {duration_key} для пака {pack_id}")
            
                pack = await db.get_pack(pack_id)
                if pack:
                    pack_id, name, description, prices_json, channel_id, created_at, is_active = pack
                    prices = json.loads(prices_json)
                    
                    duration_text = duration_key if duration_key != "forever" else "навсегда"
                    price = prices.get(duration_text, 0)
                    
                    text = f"🛒 **Подтверждение покупки**\n\n"
                    text += f"📦 Пак: {name}\n"
                    text += f"⏳ Длительность: {duration_text}\n"
                    text += f"💰 Стоимость: {format_price(price)}\n\n"
                    text += "Для оплаты нажмите кнопку ниже:"
                    
                    keyboard = InlineKeyboardMarkup(inline_keyboard=[
                        [InlineKeyboardButton(text="💳 Оплатить", callback_data=f"pay_{pack_id}_{duration_key}")],
                        [InlineKeyboardButton(text="⬅️ Назад", callback_data=f"pack_{pack_id}")]
                    ])
                    
                    await callback.message.edit_text(text, parse_mode="Markdown", reply_markup=keyboard)
                    logger.info(f"Подтверждение покупки пака {pack_id} отправлено пользователю {user_id}")
                    
            except Exception as e:
                logger.error(f"Ошибка обработки длительности для пользователя {user_id}: {e}")
                await callback.answer("❌ Ошибка обработки запроса", show_alert=True)

        @dp.callback_query(F.data.startswith("pay_"))
        async def payment_handler(callback: types.CallbackQuery):
            """Обработчик оплаты пака"""
            user_id = callback.from_user.id
            await update_user_activity(user_id)
            
            try:
            data = callback.data.split("_")
            pack_id = int(data[1])
            duration_key = data[2]
            
            logger.info(f"Пользователь {user_id} оплачивает пак {pack_id} на {duration_key}")
            
                pack = await db.get_pack(pack_id)
                if pack:
                    pack_id, name, description, prices_json, channel_id, created_at, is_active = pack
                    prices = json.loads(prices_json)
                    
                    duration_text = duration_key if duration_key != "forever" else "навсегда"
                    price = prices.get(duration_text, 0)
                    duration_days = config.SUBSCRIPTION_DURATIONS.get(duration_text, 0)
                    
                    user_data = await db.get_user(user_id)
                    if user_data:
                        user_id_db, username, balance, subscription_until, registered_at, last_activity = user_data
                        
                        if balance >= price:
                            # Списание средств
                            await db.update_balance(user_id, -price)
                            await db.add_user_pack(user_id, pack_id, duration_days, price)
                            await db.add_transaction(
                                user_id, 
                                'purchase', 
                                price, 
                                f"Пак {name} на {duration_text}"
                            )
                            
                            # Создание инвайт-ссылки
                            try:
                                invite_link = await bot.create_chat_invite_link(
                                    chat_id=channel_id,
                                    member_limit=1,
                                    creates_join_request=False
                                )
                                
                                success_text = f"""
✅ **Покупка успешно завершена!**

📦 Пак: {name}
⏳ Длительность: {duration_text}
💰 Стоимость: {format_price(price)}

🔗 **Ссылка для доступа:**
{invite_link.invite_link}

⚠️ Ссылка одноразовая! Никому не передавайте её.
"""
                                await callback.message.edit_text(success_text, parse_mode="Markdown")
                                logger.info(f"Пользователь {user_id} успешно купил пак {pack_id}, ссылка создана")
                                
                            except Exception as e:
                                logger.error(f"Ошибка создания инвайт-ссылки для пользователя {user_id}: {e}")
                                await callback.message.edit_text(
                                    "✅ Покупка завершена, но возникла ошибка при создании ссылки. Свяжитесь с администратором."
                                )
                        else:
                            await callback.answer("❌ Недостаточно средств на балансе", show_alert=True)
                            logger.info(f"Пользователь {user_id} пытался купить пак {pack_id}, но недостаточно средств")
                            
            except Exception as e:
                logger.error(f"Ошибка обработки платежа для пользователя {user_id}: {e}")
                await callback.answer("❌ Ошибка обработки платежа", show_alert=True)

        # ==================== ОБРАБОТЧИКИ ГЛОБАЛЬНОЙ ПОДПИСКИ ====================
        async def buy_global_subscription_handler(callback: types.CallbackQuery):
            """Обработчик покупки глобальной подписки"""
            user_id = callback.from_user.id
            await update_user_activity(user_id)
            
            try:
                settings = await db.get_global_subscription_settings()
                if not settings:
                    await callback.answer("❌ Настройки подписки не найдены", show_alert=True)
                    return
                
                await callback.message.edit_text(
                    "⏳ Выберите длительность глобальной подписки:", 
                    reply_markup=get_duration_keyboard(is_global=True)
                )
                logger.info(f"Пользователь {user_id} выбрал покупку глобальной подписки")
                
            except Exception as e:
                logger.error(f"Ошибка при покупке глобальной подписки пользователем {user_id}: {e}")
                await callback.answer("❌ Ошибка загрузки подписки", show_alert=True)

        @dp.callback_query(F.data.startswith("global_duration_"))
        async def global_duration_handler(callback: types.CallbackQuery):
            """Обработчик выбора длительности глобальной подписки"""
            user_id = callback.from_user.id
            await update_user_activity(user_id)
            
            try:
                data = callback.data.split("_")
                duration_key = data[2]
                
                logger.info(f"Пользователь {user_id} выбрал длительность {duration_key} для глобальной подписки")
                
                settings = await db.get_global_subscription_settings()
                if settings:
                    id, description, prices_json, updated_at = settings
                    prices = json.loads(prices_json)
                    
                    duration_text = duration_key if duration_key != "forever" else "навсегда"
                    price = prices.get(duration_text, 0)
                    duration_days = config.SUBSCRIPTION_DURATIONS.get(duration_text, 0)
                    
                    user_data = await db.get_user(user_id)
                    if user_data:
                        user_id_db, username, balance, subscription_until, registered_at, last_activity = user_data
                        
                        if balance >= price:
                            # Списание средств и активация глобальной подписки
                            await db.update_balance(user_id, -price)
                            await db.add_global_subscription(user_id, duration_days, price)
                            await db.add_transaction(
                                user_id, 
                                'purchase', 
                                price, 
                                f"Глобальная подписка на {duration_text}"
                            )
                            
                            # Получаем все паки для создания ссылок
                            packs = await db.get_packs()
                            links_text = "🔗 **Ссылки для доступа ко всем пакам:**\n\n"
                            
                            successful_links = 0
                            for pack in packs:
                                pack_id, name, description, prices_json, channel_id, created_at, is_active = pack
                                try:
                                    invite_link = await bot.create_chat_invite_link(
                                        chat_id=channel_id,
                                        member_limit=1
                                    )
                                    links_text += f"📦 {name}: {invite_link.invite_link}\n\n"
                                    successful_links += 1
                                except Exception as e:
                                    logger.error(f"Ошибка создания ссылки для пака {name}: {e}")
                                    links_text += f"📦 {name}: ❌ Ошибка создания ссылки\n\n"
                            
                            success_text = f"""
✅ **Глобальная подписка успешно активирована!**

🌟 Подписка: Глобальный доступ
⏳ Длительность: {duration_text}
💰 Стоимость: {format_price(price)}

{links_text}
✅ Успешно создано ссылок: {successful_links}/{len(packs)}
⚠️ Ссылки одноразовые! Никому не передавайте их.
                            """
                            await callback.message.edit_text(success_text, parse_mode="Markdown")
                            logger.info(f"Пользователь {user_id} успешно купил глобальную подписку")
                            
                        else:
                            await callback.answer("❌ Недостаточно средств на балансе", show_alert=True)
                            logger.info(f"Пользователь {user_id} пытался купить глобальную подписку, но недостаточно средств")
                            
            except Exception as e:
                logger.error(f"Ошибка обработки глобальной подписки для пользователя {user_id}: {e}")
                await callback.answer("❌ Ошибка обработки подписки", show_alert=True)

        @dp.callback_query(F.data == "menu_back")
        async def menu_back_callback(callback: types.CallbackQuery):
            """Обработчик кнопки Назад в главное меню"""
            user_id = callback.from_user.id
            await update_user_activity(user_id)
            
            await callback.message.edit_text("Главное меню:")
            await callback.message.answer(
                "👋 Добро пожаловать! Выберите действие:", 
                reply_markup=get_main_keyboard(user_id)
            )
            logger.info(f"Пользователь {user_id} нажал 'Назад' в главное меню")

        @dp.callback_query(F.data == "back_to_packs")
        async def back_to_packs_callback(callback: types.CallbackQuery):
            """Обработчик кнопки Назад к списку паков"""
            user_id = callback.from_user.id
            await update_user_activity(user_id)
            
            try:
                packs = await db.get_packs()
                if packs:
                    await callback.message.edit_text(
                        "📦 Выберите пак:", 
                        reply_markup=get_packs_keyboard(packs)
                    )
                else:
                    await callback.message.edit_text(
                        "📦 На данный момент паков нет в продаже.", 
                        reply_markup=get_back_keyboard()
                    )
                logger.info(f"Пользователь {user_id} вернулся к списку паков")
                
            except Exception as e:
                logger.error(f"Ошибка возврата к пакам для пользователя {user_id}: {e}")
                await callback.answer("❌ Ошибка загрузки", show_alert=True)

        @dp.callback_query(F.data == "back_to_subscription")
        async def back_to_subscription_callback(callback: types.CallbackQuery):
            """Обработчик кнопки Назад к информации о подписке"""
            user_id = callback.from_user.id
            await update_user_activity(user_id)
            
            try:
                settings = await db.get_global_subscription_settings()
                if settings:
                    id, description, prices_json, updated_at = settings
                    prices = json.loads(prices_json)
                    
                    text = f"ℹ️ **Глобальная подписка**\n\n{description}\n\n"
                    text += "🌟 **Доступ ко всем пакам!**\n\n"
                    text += "💳 **Цены:**\n"
                    
                    for duration, price in prices.items():
                        text += f"• {duration}: {format_price(price)}\n"
                    
                    await callback.message.edit_text(
                        text, 
                        parse_mode="Markdown", 
                        reply_markup=get_subscription_keyboard()
                    )
                    logger.info(f"Пользователь {user_id} вернулся к информации о подписке")
                    
            except Exception as e:
                logger.error(f"Ошибка возврата к подписке для пользователя {user_id}: {e}")
                await callback.answer("❌ Ошибка загрузки", show_alert=True)

        # ==================== ОБРАБОТЧИКИ АДМИН-ПАНЕЛИ ====================
        @dp.message(F.text == "⚙️ Админ-панель")
        async def admin_panel_handler(message: types.Message):
            """Обработчик входа в админ-панель"""
            user_id = message.from_user.id
            await update_user_activity(user_id)
            
            if user_id in config.ADMIN_IDS:
                await message.answer(
                    "👋 Добро пожаловать в админ-панель!", 
                    reply_markup=get_admin_keyboard()
                )
                logger.info(f"Админ {user_id} вошел в админ-панель")
            else:
                await message.answer("❌ У вас нет доступа к админ-панели.")
                logger.warning(f"Пользователь {user_id} попытался войти в админ-панель без прав")

        @dp.message(F.text == "⬅️ В главное меню")
        async def back_to_main_menu(message: types.Message):
            """Обработчик возврата в главное меню"""
            user_id = message.from_user.id
            await update_user_activity(user_id)
            
            await message.answer(
                "👋 Добро пожаловать! Выберите действие:", 
                reply_markup=get_main_keyboard(user_id)
            )
            logger.info(f"Пользователь {user_id} вернулся в главное меню")

        @dp.message(F.text == "📊 Информация")
        async def admin_info_handler(message: types.Message):
            """Обработчик информации о боте"""
            if message.from_user.id not in config.ADMIN_IDS:
                await message.answer("❌ У вас нет доступа к этой команде.")
                return
            
            await update_user_activity(message.from_user.id)
            
            try:
                user_count = await db.get_user_count()
                active_users = await db.get_active_users_count(7)
                total_packs = len(await db.get_packs())
                
                info_text = f"""
📊 **Статистика бота**

👥 Всего пользователей: {user_count}
🟢 Активных (7 дней): {active_users}
📦 Активных паков: {total_packs}
🆔 Ваш ID: {message.from_user.id}
                """
                await message.answer(info_text.strip(), parse_mode="Markdown")
                logger.info(f"Админ {message.from_user.id} запросил информацию о боте")
                
            except Exception as e:
                logger.error(f"Ошибка получения информации для админа {message.from_user.id}: {e}")
                await message.answer("❌ Ошибка получения информации")

        @dp.message(F.text == "📈 Статистика")
        async def admin_stats_handler(message: types.Message):
            """Обработчик статистики продаж"""
            if message.from_user.id not in config.ADMIN_IDS:
                await message.answer("❌ У вас нет доступа к этой команде.")
                return
            
            await update_user_activity(message.from_user.id)
            
            try:
                # Статистика за разные периоды
                day_stats = await db.get_transactions_stats(1)
                week_stats = await db.get_transactions_stats(7)
                month_stats = await db.get_transactions_stats(30)
                total_stats = await db.get_transactions_stats()
                
                day_count, day_amount = day_stats or (0, 0)
                week_count, week_amount = week_stats or (0, 0)
                month_count, month_amount = month_stats or (0, 0)
                total_count, total_amount = total_stats or (0, 0)
                
                # Детальная статистика
                detailed_stats = await db.get_detailed_stats(30)
                if detailed_stats:
                    total_sales, total_income, avg_sale, unique_buyers = detailed_stats
                else:
                    total_sales = total_income = avg_sale = unique_buyers = 0
                
                # Топ покупателей
                top_buyers = await db.get_top_buyers(5)
                
                stats_text = f"""
📈 **Статистика продаж**

📊 **За сегодня:**
   • Продаж: {day_count}
   • Сумма: {format_balance(day_amount or 0)}

📊 **За неделю:**
   • Продаж: {week_count}
   • Сумма: {format_balance(week_amount or 0)}

📊 **За месяц:**
   • Продаж: {month_count}
   • Сумма: {format_balance(month_amount or 0)}

📊 **Всего:**
   • Продаж: {total_count}
   • Сумма: {format_balance(total_amount or 0)}

📋 **Детальная статистика (30 дней):**
   • Всего продаж: {total_sales}
   • Общий доход: {format_balance(total_income or 0)}
   • Средний чек: {format_balance(avg_sale or 0)}
   • Уникальных покупателей: {unique_buyers}
                """
                
                # Добавляем топ покупателей если они есть
                if top_buyers:
                    stats_text += "\n🏆 **Топ покупателей:**\n"
                    for i, (user_id, username, total_spent) in enumerate(top_buyers, 1):
                        stats_text += f"   {i}. {username or 'Без имени'} ({user_id}): {format_balance(total_spent or 0)}\n"
                
                await message.answer(stats_text.strip(), parse_mode="Markdown")
                logger.info(f"Админ {message.from_user.id} запросил статистику")
                
            except Exception as e:
                logger.error(f"Ошибка получения статистики для админа {message.from_user.id}: {e}")
                await message.answer("❌ Ошибка получения статистики")

        @dp.message(F.text == "✏️ Управление паками")
        async def admin_pack_management_handler(message: types.Message):
            """Обработчик управления паками"""
            if message.from_user.id not in config.ADMIN_IDS:
                await message.answer("❌ У вас нет доступа к этой команде.")
                return
            
            await update_user_activity(message.from_user.id)
            
            try:
                packs = await db.get_packs()
                if not packs:
                    await message.answer("📦 Паки не найдены. Добавьте первый пак!")
                    return
                
                text = "📦 **Управление паками**\n\nВыберите пак для редактирования:"
                await message.answer(text, reply_markup=get_pack_management_keyboard(packs), parse_mode="Markdown")
                logger.info(f"Админ {message.from_user.id} открыл управление паками")
                
            except Exception as e:
                logger.error(f"Ошибка управления паками для админа {message.from_user.id}: {e}")
                await message.answer("❌ Ошибка загрузки паков")

        @dp.message(F.text == "➕ Добавить пак")
        async def admin_add_pack_handler(message: types.Message):
            """Обработчик добавления пака"""
            if message.from_user.id not in config.ADMIN_IDS:
                await message.answer("❌ У вас нет доступа к этой команде.")
                return
            
            await update_user_activity(message.from_user.id)
            
            await message.answer(
                "📝 **Добавление нового пака**\n\n"
                "Отправьте информацию о паке в следующем формате:\n\n"
                "**Название пака**\n"
                "**Описание пака**\n"
                "**ID канала** (например: -1001234567890)\n"
                "**Цены** (в формате: 1день:100, 7дней:500, 30дней:1500, forever:5000)",
                parse_mode="Markdown"
            )
            
            # Устанавливаем состояние для добавления пака
            await AdminStates.adding_pack.set()
            logger.info(f"Админ {message.from_user.id} начал добавление пака")

        @dp.message(F.text == "ℹ️ Подписка (глобальная)")
        async def admin_global_subscription_handler(message: types.Message):
            """Обработчик управления глобальной подпиской"""
            if message.from_user.id not in config.ADMIN_IDS:
                await message.answer("❌ У вас нет доступа к этой команде.")
                return
            
            await update_user_activity(message.from_user.id)
            
            try:
                settings = await db.get_global_subscription_settings()
                if settings:
                    id, description, prices_json, updated_at = settings
                    prices = json.loads(prices_json)
                    
                    text = f"ℹ️ **Управление глобальной подпиской**\n\n"
                    text += f"**Описание:** {description}\n\n"
                    text += "**Цены:**\n"
                    
                    for duration, price in prices.items():
                        text += f"• {duration}: {format_price(price)}\n"
                    
                    text += f"\n**Обновлено:** {updated_at}"
                    
                    await message.answer(
                        text, 
                        parse_mode="Markdown",
                        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                            [InlineKeyboardButton(text="✏️ Редактировать", callback_data="admin_edit_global_subscription")],
                            [InlineKeyboardButton(text="⬅️ Назад", callback_data="admin_back")]
                        ])
                    )
                else:
                    await message.answer(
                        "ℹ️ **Глобальная подписка не настроена**\n\n"
                        "Нажмите кнопку ниже для настройки:",
                        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                            [InlineKeyboardButton(text="⚙️ Настроить", callback_data="admin_setup_global_subscription")],
                            [InlineKeyboardButton(text="⬅️ Назад", callback_data="admin_back")]
                        ]),
                        parse_mode="Markdown"
                    )
                
                logger.info(f"Админ {message.from_user.id} открыл управление глобальной подпиской")
                
            except Exception as e:
                logger.error(f"Ошибка управления глобальной подпиской для админа {message.from_user.id}: {e}")
                await message.answer("❌ Ошибка загрузки настроек подписки")

        @dp.message(F.text == "📢 Рассылка")
        async def admin_broadcast_handler(message: types.Message):
            """Обработчик рассылки"""
            if message.from_user.id not in config.ADMIN_IDS:
                await message.answer("❌ У вас нет доступа к этой команде.")
                return
            
            await update_user_activity(message.from_user.id)
            
            await message.answer(
                "📢 **Рассылка сообщений**\n\n"
                "Отправьте сообщение, которое нужно разослать всем пользователям:",
                reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                    [InlineKeyboardButton(text="❌ Отмена", callback_data="admin_back")]
                ]),
                parse_mode="Markdown"
            )
            
            # Устанавливаем состояние для рассылки
            await AdminStates.broadcasting.set()
            logger.info(f"Админ {message.from_user.id} начал рассылку")

        # ==================== ОБРАБОТЧИКИ СОСТОЯНИЙ FSM ====================
        @dp.message(AdminStates.adding_pack)
        async def process_add_pack(message: types.Message, state: FSMContext):
            """Обработчик добавления пака"""
            if message.from_user.id not in config.ADMIN_IDS:
                await message.answer("❌ У вас нет доступа к этой команде.")
                return
            
            await update_user_activity(message.from_user.id)
            
            try:
                lines = message.text.strip().split('\n')
                if len(lines) < 4:
                    await message.answer(
                        "❌ Неверный формат. Отправьте информацию в следующем формате:\n\n"
                        "**Название пака**\n"
                        "**Описание пака**\n"
                        "**ID канала**\n"
                        "**Цены** (1день:100, 7дней:500, 30дней:1500, forever:5000)",
                        parse_mode="Markdown"
                    )
                    return
                
                name = lines[0].strip()
                description = lines[1].strip()
                channel_id = lines[2].strip()
                
                # Парсим цены
                prices_str = lines[3].strip()
                prices = {}
                for price_item in prices_str.split(','):
                    if ':' in price_item:
                        duration, price = price_item.strip().split(':')
                        try:
                            prices[duration.strip()] = float(price.strip())
                        except ValueError:
                            await message.answer("❌ Неверный формат цены. Используйте числа.")
                            return
                
                # Добавляем пак в базу
                await db.add_pack(name, description, json.dumps(prices), channel_id)
                
                await message.answer(
                    f"✅ **Пак успешно добавлен!**\n\n"
                    f"**Название:** {name}\n"
                    f"**Описание:** {description}\n"
                    f"**Канал:** {channel_id}\n"
                    f"**Цены:** {prices_str}",
                    parse_mode="Markdown",
                    reply_markup=get_admin_keyboard()
                )
                
                await state.finish()
                logger.info(f"Админ {message.from_user.id} добавил пак: {name}")
                
            except Exception as e:
                logger.error(f"Ошибка добавления пака админом {message.from_user.id}: {e}")
                await message.answer("❌ Ошибка добавления пака")
                await state.finish()

        @dp.message(AdminStates.broadcasting)
        async def process_broadcast(message: types.Message, state: FSMContext):
            """Обработчик рассылки сообщений"""
            if message.from_user.id not in config.ADMIN_IDS:
                await message.answer("❌ У вас нет доступа к этой команде.")
                return
            
            await update_user_activity(message.from_user.id)
            
            try:
                # Получаем всех пользователей
                users = await db.get_all_users()
                sent_count = 0
                failed_count = 0
                
                await message.answer("📢 Начинаю рассылку...")
                
                for user_id, username, balance, global_subscription_until, registered_at, last_activity in users:
                    try:
                        await bot.send_message(user_id, message.text)
                        sent_count += 1
                        
                        # Небольшая задержка чтобы не превысить лимиты API
                        await asyncio.sleep(0.05)
                        
                    except Exception as e:
                        failed_count += 1
                        logger.warning(f"Не удалось отправить сообщение пользователю {user_id}: {e}")
                
                await message.answer(
                    f"✅ **Рассылка завершена!**\n\n"
                    f"📤 Отправлено: {sent_count}\n"
                    f"❌ Ошибок: {failed_count}\n"
                    f"👥 Всего пользователей: {len(users)}",
                    reply_markup=get_admin_keyboard(),
                    parse_mode="Markdown"
                )
                
                await state.finish()
                logger.info(f"Админ {message.from_user.id} завершил рассылку: {sent_count}/{len(users)}")
                
            except Exception as e:
                logger.error(f"Ошибка рассылки админом {message.from_user.id}: {e}")
                await message.answer("❌ Ошибка рассылки")
                await state.finish()

        # ==================== CALLBACK ОБРАБОТЧИКИ ====================
        @dp.callback_query(F.data == "admin_back")
        async def admin_back_callback(callback: types.CallbackQuery):
            """Обработчик кнопки Назад в админ-панели"""
            user_id = callback.from_user.id
            await update_user_activity(user_id)
            
            if user_id in config.ADMIN_IDS:
                await callback.message.edit_text(
                    "👋 Добро пожаловать в админ-панель!",
                    reply_markup=get_admin_keyboard()
                )
                logger.info(f"Админ {user_id} вернулся в админ-панель")
            else:
                await callback.answer("❌ У вас нет доступа")

        @dp.callback_query(F.data.startswith("admin_edit_pack_"))
        async def admin_edit_pack_callback(callback: types.CallbackQuery):
            """Обработчик редактирования пака"""
            user_id = callback.from_user.id
            await update_user_activity(user_id)
            
            if user_id not in config.ADMIN_IDS:
                await callback.answer("❌ У вас нет доступа")
                return
            
            try:
                pack_id = int(callback.data.split("_")[-1])
                pack = await db.get_pack(pack_id)
                
                if pack:
                    pack_id, name, description, prices_json, channel_id, created_at, is_active = pack
                    prices = json.loads(prices_json)
                    
                    status = "✅ Активен" if is_active else "❌ Неактивен"
                    prices_text = ", ".join([f"{duration}: {format_price(price)}" for duration, price in prices.items()])
                    
                    text = f"""📦 **Редактирование пака**

**Название:** {name}
**Описание:** {description}
**Канал:** {channel_id}
**Цены:** {prices_text}
**Статус:** {status}
**Создан:** {created_at}"""
                    
                    keyboard = InlineKeyboardMarkup(inline_keyboard=[
                        [InlineKeyboardButton(text="🔄 Активировать/Деактивировать", callback_data=f"admin_toggle_pack_{pack_id}")],
                        [InlineKeyboardButton(text="🗑️ Удалить", callback_data=f"admin_delete_pack_{pack_id}")],
                        [InlineKeyboardButton(text="⬅️ Назад", callback_data="admin_back")]
                    ])
                    
                    await callback.message.edit_text(text, reply_markup=keyboard, parse_mode="Markdown")
                    logger.info(f"Админ {user_id} редактирует пак {pack_id}")
                else:
                    await callback.answer("❌ Пак не найден", show_alert=True)
                    
            except Exception as e:
                logger.error(f"Ошибка редактирования пака для админа {user_id}: {e}")
                await callback.answer("❌ Ошибка загрузки пака", show_alert=True)

        @dp.callback_query(F.data.startswith("admin_toggle_pack_"))
        async def admin_toggle_pack_callback(callback: types.CallbackQuery):
            """Обработчик активации/деактивации пака"""
            user_id = callback.from_user.id
            await update_user_activity(user_id)
            
            if user_id not in config.ADMIN_IDS:
                await callback.answer("❌ У вас нет доступа")
                return
            
            try:
                pack_id = int(callback.data.split("_")[-1])
                pack = await db.get_pack(pack_id)
                
                if pack:
                    pack_id, name, description, prices_json, channel_id, created_at, is_active = pack
                    new_status = not is_active
                    
                    await db.update_pack(pack_id, name, description, prices_json, channel_id, new_status)
                    
                    status_text = "активирован" if new_status else "деактивирован"
                    await callback.answer(f"✅ Пак {status_text}", show_alert=True)
                    logger.info(f"Админ {user_id} {status_text} пак {pack_id}")
                else:
                    await callback.answer("❌ Пак не найден", show_alert=True)
                    
            except Exception as e:
                logger.error(f"Ошибка переключения статуса пака для админа {user_id}: {e}")
                await callback.answer("❌ Ошибка обновления", show_alert=True)

        @dp.callback_query(F.data.startswith("admin_delete_pack_"))
        async def admin_delete_pack_callback(callback: types.CallbackQuery):
            """Обработчик удаления пака"""
            user_id = callback.from_user.id
            await update_user_activity(user_id)
            
            if user_id not in config.ADMIN_IDS:
                await callback.answer("❌ У вас нет доступа")
                return
            
            try:
                pack_id = int(callback.data.split("_")[-1])
                
                # Показываем подтверждение
                keyboard = InlineKeyboardMarkup(inline_keyboard=[
                    [InlineKeyboardButton(text="✅ Да, удалить", callback_data=f"admin_confirm_delete_pack_{pack_id}")],
                    [InlineKeyboardButton(text="❌ Отмена", callback_data=f"admin_edit_pack_{pack_id}")]
                ])
                
                await callback.message.edit_text(
                    "⚠️ **Подтверждение удаления**\n\n"
                    "Вы уверены, что хотите удалить этот пак?\n"
                    "Это действие нельзя отменить!",
                    reply_markup=keyboard,
                    parse_mode="Markdown"
                )
                    
            except Exception as e:
                logger.error(f"Ошибка удаления пака для админа {user_id}: {e}")
                await callback.answer("❌ Ошибка удаления", show_alert=True)

        @dp.callback_query(F.data.startswith("admin_confirm_delete_pack_"))
        async def admin_confirm_delete_pack_callback(callback: types.CallbackQuery):
            """Обработчик подтверждения удаления пака"""
            user_id = callback.from_user.id
            await update_user_activity(user_id)
            
            if user_id not in config.ADMIN_IDS:
                await callback.answer("❌ У вас нет доступа")
                return
            
            try:
                pack_id = int(callback.data.split("_")[-1])
                await db.delete_pack(pack_id)
                
                await callback.message.edit_text(
                    "✅ **Пак успешно удален!**",
                    reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                        [InlineKeyboardButton(text="⬅️ В админ-панель", callback_data="admin_back")]
                    ]),
                    parse_mode="Markdown"
                )
                
                logger.info(f"Админ {user_id} удалил пак {pack_id}")
                    
            except Exception as e:
                logger.error(f"Ошибка удаления пака для админа {user_id}: {e}")
                await callback.answer("❌ Ошибка удаления", show_alert=True)

        # ==================== НАСТРОЙКА ПЛАНИРОВЩИКА ====================
        # Проверка истекших подписок каждый час
        scheduler.add_job(
            check_expired_subscriptions,
            trigger=CronTrigger(hour="*"),
            id="check_expired_subscriptions",
            replace_existing=True
        )
        
        # Отправка напоминаний каждый день в 12:00
        scheduler.add_job(
            send_subscription_reminders,
            trigger=CronTrigger(hour=12, minute=0),
            id="send_subscription_reminders",
            replace_existing=True
        )
        
        # Обновление ежедневной статистики каждый день в 23:59
        scheduler.add_job(
            db.update_daily_stats,
            trigger=CronTrigger(hour=23, minute=59),
            id="update_daily_stats",
            replace_existing=True
        )
        
        scheduler.start()
        logger.info("Планировщик задач запущен")
        
        # Запуск бота
        logger.info("Запуск polling...")
        await dp.start_polling(bot)
        
    except Exception as e:
        logger.critical(f"КРИТИЧЕСКАЯ ОШИБКА ПРИ ЗАПУСКЕ БОТА: {e}", exc_info=True)
        print(f"Критическая ошибка: {e}")
        print("Подробности в файле bot.log")
    finally:
        # Остановка планировщика при завершении
        scheduler.shutdown()
        logger.info("Бот остановлен")

if __name__ == '__main__':
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("Бот остановлен пользователем")
        print("Бот остановлен")
    except Exception as e:
        logger.critical(f"НЕОБРАБОТАННОЕ ИСКЛЮЧЕНИЕ: {e}", exc_info=True)
        print(f"Необработанное исключение: {e}")
