import asyncio
import datetime
import html
import logging
import os
import sys
from aiohttp import web

from aiogram import Bot, Dispatcher, F
from aiogram.enums import ChatMemberStatus
from aiogram.filters import CommandObject, CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import (
    CallbackQuery,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Message,
)

from config import ADMIN_ID, ADMIN_USERNAME, BOT_TOKEN, CHANNEL_ID, CHANNEL_URL
import database as db
import xrocket_pay

# Настройка логирования
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
)
logger = logging.getLogger(__name__)

dp = Dispatcher()


class Form(StatesGroup):
    waiting_for_support_message = State()
    waiting_for_collab_application = State()


# ---------------- ВЕБ-СЕРВЕР ДЛЯ RENDER.COM ----------------


async def handle_ping(request):
    return web.Response(text="Bot is running!")


async def start_web_server():
    """Фоновый HTTP-сервер для поддержания статуса на Render.com."""
    port = int(os.getenv("PORT", 8080))
    app = web.Application()
    app.router.add_get("/", handle_ping)
    app.router.add_get("/health", handle_ping)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "0.0.0.0", port)
    logger.info("Веб-сервер запущен на порту %s", port)
    await site.start()


# ---------------- КЛАВИАТУРЫ (LUXURY / VIP GOLD) ----------------


def get_sub_keyboard() -> InlineKeyboardMarkup:
    """Клавиатура проверки обязательного членства в канале."""
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="✨ Вступить в закрытый канал",
                    url=CHANNEL_URL,
                )
            ],
            [
                InlineKeyboardButton(
                    text="👑 Подтвердить подписку",
                    callback_data="check_sub",
                )
            ],
        ]
    )


def get_main_menu_keyboard() -> InlineKeyboardMarkup:
    """Главная панель управления (VIP стиль)."""
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="💎 Оформить VIP-доступ", callback_data="menu_subscription")],
            [InlineKeyboardButton(text="⚜️ Мой статус и доступ", callback_data="menu_access")],
            [InlineKeyboardButton(text="👥 Партнёрская сеть", callback_data="menu_referrals")],
            [InlineKeyboardButton(text="🤝 Медиа & Коллаборация", callback_data="menu_collab")],
            [InlineKeyboardButton(text="💬 Персональная поддержка", callback_data="menu_support")],
        ]
    )


def get_subscription_keyboard() -> InlineKeyboardMarkup:
    """Клавиатура оформления доступа."""
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="⚡ Оплатить через xRocket (8.5 USDT)", callback_data="pay_xrocket_invoice")],
            [InlineKeyboardButton(text="« Назад в главное меню", callback_data="back_to_main")],
        ]
    )


def get_invoice_keyboard(pay_url: str, invoice_id: str) -> InlineKeyboardMarkup:
    """Клавиатура сгенерированного инвойса."""
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="🚀 Перейти к оплате 8.5 USDT", url=pay_url)],
            [InlineKeyboardButton(text="🔄 Проверить статус платежа", callback_data=f"check_inv_{invoice_id}")],
            [InlineKeyboardButton(text="« Отмена и назад", callback_data="back_to_main")],
        ]
    )


def get_back_keyboard() -> InlineKeyboardMarkup:
    """Кнопка возврата в меню."""
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="« Назад в главное меню", callback_data="back_to_main")]
        ]
    )


def get_user_contact_button(user_id: int, username: str | None) -> InlineKeyboardMarkup:
    """Кнопка быстрого перехода к профилю для администратора."""
    if username:
        return InlineKeyboardMarkup(
            inline_keyboard=[
                [InlineKeyboardButton(text="💬 Открыть диалог с клиентом", url=f"https://t.me/{username}")]
            ]
        )
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="💬 Профиль клиента", url=f"tg://user?id={user_id}")]
        ]
    )


# ---------------- ТЕКСТЫ (LUXURY / VIP GOLD) ----------------


def get_main_menu_text(safe_name: str, user_id: int, is_active: bool) -> str:
    status_label = "🟢 VIP АКТИВЕН" if is_active else "🔴 ДОСТУП ОГРАНИЧЕН"
    return (
        "👑 <b>SCAM OFFERS | PRIVATE CLUB</b>\n"
        "◈ ━━━━━━━━━━━━━━━━━━━━ ◈\n"
        "<i>Премиальная инфраструктура и закрытые офферы</i>\n\n"
        f"👤 <b>Клиент:</b> {safe_name}\n"
        f"🆔 <b>ID:</b> <code>{user_id}</code>\n"
        f"⚡ <b>Статус:</b> <b>{status_label}</b>\n\n"
        "Выберите раздел для управления:"
    )


def get_subscription_text() -> str:
    return (
        "⚜️ <b>ПРИОБРЕТЕНИЕ КЛУБНОГО ДОСТУПА</b> ⚜️\n"
        "◈ ━━━━━━━━━━━━━━━━━━━━ ◈\n\n"
        "✦ <b>Тариф:</b> <code>FULL VIP ACCESS</code>\n"
        "✦ <b>Срок действия:</b> <code>30 календарных дней</code>\n"
        "✦ <b>Стоимость:</b> <code>8.5 USDT</code>\n\n"
        "<b>В членство включено:</b>\n"
        "▸ Полный доступ к приватным офферам\n"
        "▸ Приоритетные рабочие инструменты\n"
        "▸ Прямой контакт с консьерж-сервисом 24/7\n\n"
        "<i>Нажмите кнопку ниже для моментальной оплаты через xRocket Pay:</i>"
    )


# ---------------- ПРОВЕРКА ПОДПИСКИ ----------------


async def is_subscribed(bot: Bot, user_id: int) -> bool:
    """Проверка наличия членства в канале."""
    try:
        member = await bot.get_chat_member(chat_id=CHANNEL_ID, user_id=user_id)
        return member.status in {
            ChatMemberStatus.MEMBER,
            ChatMemberStatus.ADMINISTRATOR,
            ChatMemberStatus.CREATOR,
            ChatMemberStatus.RESTRICTED,
        }
    except Exception as e:
        logger.error("Ошибка при проверке подписки для user_id %s: %s", user_id, e)
        return False


def check_user_active_sub(user_id: int) -> bool:
    """Проверяет, активна ли VIP-подписка в локальной БД."""
    user_data = db.get_user(user_id)
    if not user_data:
        return False
    sub_expires_at = user_data.get("sub_expires_at", 0)
    now = int(datetime.datetime.now().timestamp())
    return sub_expires_at > now


# ---------------- ХЕНДЛЕРЫ ----------------


@dp.message(CommandStart())
async def cmd_start(message: Message, command: CommandObject, bot: Bot, state: FSMContext):
    await state.clear()
    user = message.from_user
    if not user:
        return

    referrer_id = None
    if command.args and command.args.isdigit():
        referrer_id = int(command.args)

    db.register_user(
        user_id=user.id,
        username=user.username,
        first_name=user.first_name,
        referrer_id=referrer_id,
    )

    safe_name = html.escape(user.first_name)

    if await is_subscribed(bot, user.id):
        is_active = check_user_active_sub(user.id)
        await message.answer(
            get_main_menu_text(safe_name, user.id, is_active),
            reply_markup=get_main_menu_keyboard(),
            parse_mode="HTML",
        )
    else:
        await message.answer(
            "⚜️ <b>ДОБРО ПОЖАЛОВАТЬ В PRIVATE CLUB</b> ⚜️\n"
            "◈ ━━━━━━━━━━━━━━━━━━━━ ◈\n\n"
            f"Приветствуем вас, <b>{safe_name}</b>.\n\n"
            "Для входа в закрытую инфраструктуру и доступа к инструментам подтвердите членство в нашем официальном канале:\n"
            f"✦ <a href=\"{CHANNEL_URL}\"><b>Официальный канал: NFT OFFERS</b></a>\n\n"
            "<i>После подписки нажмите кнопку подтверждения ниже:</i>",
            reply_markup=get_sub_keyboard(),
            parse_mode="HTML",
            disable_web_page_preview=True,
        )


@dp.callback_query(F.data == "check_sub")
async def callback_check_sub(callback: CallbackQuery, bot: Bot):
    user = callback.from_user
    if not user or not callback.message:
        return

    safe_name = html.escape(user.first_name)

    if await is_subscribed(bot, user.id):
        await callback.answer("✨ Членство успешно подтверждено!", show_alert=False)
        is_active = check_user_active_sub(user.id)
        if isinstance(callback.message, Message):
            await callback.message.edit_text(
                get_main_menu_text(safe_name, user.id, is_active),
                reply_markup=get_main_menu_keyboard(),
                parse_mode="HTML",
            )
    else:
        await callback.answer(
            "❌ Вы ещё не подписались на канал!\n\nПожалуйста, перейдите по ссылке и вступите в канал.",
            show_alert=True,
        )


@dp.callback_query(F.data == "back_to_main")
async def callback_back_to_main(callback: CallbackQuery, state: FSMContext):
    await state.clear()
    user = callback.from_user
    safe_name = html.escape(user.first_name) if user else "Клиент"
    user_id = user.id if user else 0
    is_active = check_user_active_sub(user_id)

    if callback.message and isinstance(callback.message, Message):
        await callback.message.edit_text(
            get_main_menu_text(safe_name, user_id, is_active),
            reply_markup=get_main_menu_keyboard(),
            parse_mode="HTML",
        )
    await callback.answer()


@dp.callback_query(F.data == "menu_subscription")
async def callback_subscription(callback: CallbackQuery, state: FSMContext):
    await state.clear()
    if callback.message and isinstance(callback.message, Message):
        await callback.message.edit_text(
            get_subscription_text(),
            reply_markup=get_subscription_keyboard(),
            parse_mode="HTML",
        )
    await callback.answer()


@dp.callback_query(F.data == "menu_access")
async def callback_access(callback: CallbackQuery, state: FSMContext):
    await state.clear()
    user = callback.from_user
    user_data = db.get_user(user.id) if user else None
    sub_expires_at = user_data.get("sub_expires_at", 0) if user_data else 0
    now = int(datetime.datetime.now().timestamp())

    if sub_expires_at > now:
        expires_date = datetime.datetime.fromtimestamp(sub_expires_at).strftime("%d.%m.%Y в %H:%M")
        days_left = max(1, int((sub_expires_at - now) / 86400))
        text = (
            "⚜️ <b>ВАШ КЛУБНЫЙ СТАТУС</b> ⚜️\n"
            "◈ ━━━━━━━━━━━━━━━━━━━━ ◈\n\n"
            "Статус: 🟢 <b>VIP АКТИВЕН</b>\n"
            f"✦ <b>Срок действия:</b> до <code>{expires_date}</code>\n"
            f"✦ <b>Осталось дней:</b> <code>{days_left} дн.</code>\n\n"
            "<i>Все приватные офферы и инструменты доступны в полном объёме.</i>"
        )
    else:
        text = (
            "⚜️ <b>ВАШ КЛУБНЫЙ СТАТУС</b> ⚜️\n"
            "◈ ━━━━━━━━━━━━━━━━━━━━ ◈\n\n"
            "Статус: 🔴 <b>ДОСТУП НЕ АКТИВИРОВАН</b>\n\n"
            "<i>У вас пока нет активного членства. Нажмите «Оформить VIP-доступ» в главном меню для разблокировки платформы.</i>"
        )

    if callback.message and isinstance(callback.message, Message):
        await callback.message.edit_text(
            text,
            reply_markup=get_back_keyboard(),
            parse_mode="HTML",
        )
    await callback.answer()


@dp.callback_query(F.data == "menu_referrals")
async def callback_referrals(callback: CallbackQuery, bot: Bot, state: FSMContext):
    await state.clear()
    user_id = callback.from_user.id
    bot_info = await bot.get_me()
    bot_username = bot_info.username or "scmnft_bot"

    ref_link = f"https://t.me/{bot_username}?start={user_id}"
    invited_count, has_buyer = db.get_referral_stats(user_id)

    buyer_status = "🟢 Есть покупка (VIP получен)" if has_buyer else "🔴 Пока нет покупок"

    text = (
        "👥 <b>ПАРТНЁРСКАЯ ПРОГРАММА VIP</b> 👥\n"
        "◈ ━━━━━━━━━━━━━━━━━━━━ ◈\n\n"
        "<i>Пригласите 3-х партнёров. Как только один из них активирует VIP-доступ — вы получите полный доступ бесплатно!</i>\n\n"
        "🔗 <b>Ваша реферальная ссылка:</b>\n"
        f"<code>{ref_link}</code>\n\n"
        "📊 <b>Ваша статистика:</b>\n"
        f"▸ Приглашено партнёров: <b>{invited_count} / 3</b>\n"
        f"▸ Статус покупки: <b>{buyer_status}</b>"
    )

    if callback.message and isinstance(callback.message, Message):
        await callback.message.edit_text(
            text,
            reply_markup=get_back_keyboard(),
            parse_mode="HTML",
            disable_web_page_preview=True,
        )
    await callback.answer()


@dp.callback_query(F.data == "menu_collab")
async def callback_collab(callback: CallbackQuery, state: FSMContext):
    await state.set_state(Form.waiting_for_collab_application)
    text = (
        "🤝 <b>МЕДИА-ПАРТНЁРСТВО & TIKTOK</b> 🤝\n"
        "◈ ━━━━━━━━━━━━━━━━━━━━ ◈\n\n"
        "<i>Публикуйте видео о нашем клубе в TikTok и получайте бесплатное продление VIP-доступа!</i>\n\n"
        "✦ <b>Награда:</b> <code>2 000 просмотров = 1 месяц подписки</code>\n\n"
        "<b>Анкета для подачи заявки:</b>\n"
        "1. Ваш ник в Telegram:\n"
        "2. Ссылка на TikTok аккаунт:\n"
        "3. Количество видео в сутки:\n\n"
        "<i>Отправьте готовую анкету ответным сообщением в этот чат:</i>"
    )

    if callback.message and isinstance(callback.message, Message):
        await callback.message.edit_text(
            text,
            reply_markup=get_back_keyboard(),
            parse_mode="HTML",
        )
    await callback.answer()


@dp.callback_query(F.data == "menu_support")
async def callback_support(callback: CallbackQuery, state: FSMContext):
    await state.set_state(Form.waiting_for_support_message)
    text = (
        "💬 <b>ПЕРСОНАЛЬНЫЙ КОНСЬЕРЖ-СЕРВИС</b> 💬\n"
        "◈ ━━━━━━━━━━━━━━━━━━━━ ◈\n\n"
        "Возник вопрос, предложение или нужна помощь с доступом?\n\n"
        "<i>Напишите ваше сообщение прямо в этот чат, и персональный менеджер ответит вам в кратчайшие сроки.</i>"
    )

    if callback.message and isinstance(callback.message, Message):
        await callback.message.edit_text(
            text,
            reply_markup=get_back_keyboard(),
            parse_mode="HTML",
        )
    await callback.answer()


# ---------------- ОПЛАТА XROCKET ----------------


@dp.callback_query(F.data == "pay_xrocket_invoice")
async def callback_pay_xrocket_invoice(callback: CallbackQuery, bot: Bot):
    user = callback.from_user
    safe_name = html.escape(user.first_name)
    user_handle = f"@{user.username}" if user.username else f"ID: {user.id}"

    # Создаём счёт через xRocket Pay API
    invoice = await xrocket_pay.create_invoice(amount="8.5", currency="USDT")

    if invoice:
        inv_id, pay_link = invoice

        if ADMIN_ID:
            try:
                await bot.send_message(
                    chat_id=ADMIN_ID,
                    text=(
                        "💳 <b>СФОРМИРОВАН НОВЫЙ СЧЁТ НА ОПЛАТУ</b>\n"
                        "◈ ━━━━━━━━━━━━━━━━━━━━ ◈\n"
                        f"<b>Клиент:</b> {safe_name} ({user_handle})\n"
                        f"<b>ID:</b> <code>{user.id}</code>\n"
                        f"<b>Сумма:</b> 8.5 USDT\n"
                        f"<b>Инвойс:</b> <code>#{inv_id}</code>\n"
                        f"<b>Ссылка:</b> {pay_link}"
                    ),
                    reply_markup=get_user_contact_button(user.id, user.username),
                    parse_mode="HTML",
                )
            except Exception as e:
                logger.error("Ошибка при отправке уведомления админу: %s", e)

        text = (
            "💳 <b>СЧЁТ НА ОПЛАТУ ЧЛЕНСТВА</b>\n"
            "◈ ━━━━━━━━━━━━━━━━━━━━ ◈\n\n"
            "✦ <b>Тариф:</b> <code>VIP Подписка (30 дней)</code>\n"
            "✦ <b>К оплате:</b> <code>8.5 USDT</code>\n"
            f"✦ <b>Счёт ID:</b> <code>#{inv_id}</code>\n\n"
            "<i>Платёж безопасно проводится через систему xRocket Pay. "
            "После совершения транзакции нажмите кнопку проверки ниже:</i>"
        )

        if callback.message and isinstance(callback.message, Message):
            await callback.message.edit_text(
                text,
                reply_markup=get_invoice_keyboard(pay_url=pay_link, invoice_id=inv_id),
                parse_mode="HTML",
            )
        await callback.answer()
    else:
        await callback.answer(
            "Не удалось сформировать счёт. Обратитесь к менеджеру @hetero777.",
            show_alert=True,
        )


@dp.callback_query(F.data.startswith("check_inv_"))
async def callback_check_invoice(callback: CallbackQuery, bot: Bot):
    user = callback.from_user
    invoice_id = callback.data.replace("check_inv_", "").strip()

    is_paid = await xrocket_pay.check_invoice_paid(invoice_id)

    if is_paid:
        db.activate_subscription(user.id, days=30)
        await callback.answer("✨ Оплата успешно подтверждена!", show_alert=True)

        if ADMIN_ID:
            try:
                await bot.send_message(
                    chat_id=ADMIN_ID,
                    text=(
                        "🎉 <b>ПОЛУЧЕНА ОПЛАТА VIP-ДОСТУПА!</b>\n"
                        "◈ ━━━━━━━━━━━━━━━━━━━━ ◈\n"
                        f"<b>Клиент:</b> {html.escape(user.first_name)} (@{user.username})\n"
                        f"<b>ID:</b> <code>{user.id}</code>\n"
                        f"<b>Сумма:</b> 8.5 USDT\n"
                        f"<b>Счёт:</b> <code>#{invoice_id}</code>"
                    ),
                    reply_markup=get_user_contact_button(user.id, user.username),
                    parse_mode="HTML",
                )
            except Exception as e:
                logger.error("Ошибка уведомления админа: %s", e)

        if callback.message and isinstance(callback.message, Message):
            await callback.message.edit_text(
                "👑 <b>ПОЗДРАВЛЯЕМ! ОПЛАТА УСПЕШНО ПРИНЯТА.</b>\n"
                "◈ ━━━━━━━━━━━━━━━━━━━━ ◈\n\n"
                "Ваш клубный VIP-доступ активирован на <b>30 дней</b>.\n"
                "Добро пожаловать в закрытую часть сервиса!",
                reply_markup=get_back_keyboard(),
                parse_mode="HTML",
            )
    else:
        await callback.answer(
            "⏳ Транзакция ещё не подтверждена сетью.\nЕсли вы только что перевели средства, подождите 10-15 секунд и нажмите кнопку снова.",
            show_alert=True,
        )


# ---------------- ОБРАБОТКА ВХОДЯЩИХ СООБЩЕНИЙ ----------------


@dp.message(Form.waiting_for_support_message)
async def process_support_msg(message: Message, bot: Bot, state: FSMContext):
    user = message.from_user
    if not user:
        return

    safe_name = html.escape(user.first_name)
    user_handle = f"@{user.username}" if user.username else "без юзернейма"
    user_text = html.escape(message.text or "(медиа / вложение)")

    if ADMIN_ID:
        try:
            await bot.send_message(
                chat_id=ADMIN_ID,
                text=(
                    "💬 <b>НОВОЕ ОБРАЩЕНИЕ В КОНСЬЕРЖ-СЕРВИС</b>\n"
                    "◈ ━━━━━━━━━━━━━━━━━━━━ ◈\n"
                    f"<b>Клиент:</b> {safe_name} ({user_handle})\n"
                    f"<b>ID:</b> <code>{user.id}</code>\n\n"
                    f"<b>Сообщение:</b>\n{user_text}"
                ),
                reply_markup=get_user_contact_button(user.id, user.username),
                parse_mode="HTML",
            )
        except Exception as e:
            logger.error("Не удалось переслать сообщение админу: %s", e)

    await state.clear()
    await message.answer(
        "✨ Ваше обращение передано персональному менеджеру! Ожидайте ответа.",
        reply_markup=get_back_keyboard(),
        parse_mode="HTML",
    )


@dp.message(Form.waiting_for_collab_application)
async def process_collab_msg(message: Message, bot: Bot, state: FSMContext):
    user = message.from_user
    if not user:
        return

    safe_name = html.escape(user.first_name)
    user_handle = f"@{user.username}" if user.username else "без юзернейма"
    user_text = html.escape(message.text or "(медиа / вложение)")

    if ADMIN_ID:
        try:
            await bot.send_message(
                chat_id=ADMIN_ID,
                text=(
                    "🤝 <b>НОВАЯ ЗАЯВКА НА МЕДИА-СОТРУДНИЧЕСТВО</b>\n"
                    "◈ ━━━━━━━━━━━━━━━━━━━━ ◈\n"
                    f"<b>От:</b> {safe_name} ({user_handle})\n"
                    f"<b>ID:</b> <code>{user.id}</code>\n\n"
                    f"<b>Анкета:</b>\n{user_text}"
                ),
                reply_markup=get_user_contact_button(user.id, user.username),
                parse_mode="HTML",
            )
        except Exception as e:
            logger.error("Не удалось переслать заявку админу: %s", e)

    await state.clear()
    await message.answer(
        "✨ Ваша анкета принята на рассмотрение! Менеджер свяжется с вами в ближайшее время.",
        reply_markup=get_back_keyboard(),
        parse_mode="HTML",
    )


async def main():
    if not BOT_TOKEN:
        logger.critical("Токен бота не найден! Укажите BOT_TOKEN в файле .env")
        return

    db.init_db()
    bot = Bot(token=BOT_TOKEN)
    logger.info("Бот запускается... Администратор: ID %s (%s)", ADMIN_ID, ADMIN_USERNAME)

    # Веб-сервер для поддержания статуса на Render.com
    await start_web_server()

    try:
        await bot.delete_webhook(drop_pending_updates=True)
        await dp.start_polling(bot)
    finally:
        await bot.session.close()


if __name__ == "__main__":
    asyncio.run(main())
