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
    """Запускает мини-сервер, необходимый Render для мониторинга активности (health check)."""
    port = int(os.getenv("PORT", 8080))
    app = web.Application()
    app.router.add_get("/", handle_ping)
    app.router.add_get("/health", handle_ping)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "0.0.0.0", port)
    logger.info("Веб-сервер запущен на порту %s", port)
    await site.start()


# ---------------- КЛАВИАТУРЫ ----------------


def get_sub_keyboard() -> InlineKeyboardMarkup:
    """Клавиатура проверки обязательной подписки на канал."""
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="📢 Подписаться на канал",
                    url=CHANNEL_URL,
                )
            ],
            [
                InlineKeyboardButton(
                    text="✅ Я подписался",
                    callback_data="check_sub",
                )
            ],
        ]
    )


def get_main_menu_keyboard() -> InlineKeyboardMarkup:
    """Главное меню."""
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="💎 ПОДПИСКА", callback_data="menu_subscription")],
            [InlineKeyboardButton(text="🔑 МОЙ ДОСТУП", callback_data="menu_access")],
            [InlineKeyboardButton(text="👥 Реферальная система", callback_data="menu_referrals")],
            [InlineKeyboardButton(text="🤝 Сотрудничество", callback_data="menu_collab")],
            [InlineKeyboardButton(text="🛠 Поддержка", callback_data="menu_support")],
        ]
    )


def get_subscription_keyboard() -> InlineKeyboardMarkup:
    """Клавиатура оформления доступа (Xrocket 8.5 USDT и назад)."""
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="Оплатить Xrocket - 8.5 USDT", callback_data="pay_xrocket_invoice")],
            [InlineKeyboardButton(text="⬅️ ГЛАВНОЕ МЕНЮ", callback_data="back_to_main")],
        ]
    )


def get_invoice_keyboard(pay_url: str, invoice_id: str) -> InlineKeyboardMarkup:
    """Клавиатура с кнопкой оплаты и кнопкой проверки."""
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="🚀 Перейти к оплате 8.5 USDT", url=pay_url)],
            [InlineKeyboardButton(text="🔄 Проверить оплату", callback_data=f"check_inv_{invoice_id}")],
            [InlineKeyboardButton(text="⬅️ ГЛАВНОЕ МЕНЮ", callback_data="back_to_main")],
        ]
    )


def get_back_keyboard() -> InlineKeyboardMarkup:
    """Кнопка возврата в главное меню."""
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="⬅️ ГЛАВНОЕ МЕНЮ", callback_data="back_to_main")]
        ]
    )


def get_user_contact_button(user_id: int, username: str | None) -> InlineKeyboardMarkup:
    """Кнопка для быстрого перехода к диалогу с пользователем."""
    if username:
        return InlineKeyboardMarkup(
            inline_keyboard=[
                [InlineKeyboardButton(text="💬 Написать пользователю", url=f"https://t.me/{username}")]
            ]
        )
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="💬 Профиль пользователя", url=f"tg://user?id={user_id}")]
        ]
    )


# ---------------- ТЕКСТЫ ----------------


def get_main_menu_text() -> str:
    return (
        "<b>Scam Offers</b>\n"
        "───────────────────────────\n"
        "Управление доступом и рабочими инструментами.\n\n"
        "Выберите раздел."
    )


def get_subscription_text() -> str:
    return (
        "<b>ОФОРМЛЕНИЕ ДОСТУПА</b>\n"
        "───────────────────────────\n"
        "Срок: 30 дней\n\n"
        "Цена: 8.5 USDT\n\n"
        "Выберите способ оплаты."
    )


# ---------------- ПРОВЕРКА ПОДПИСКИ ----------------


async def is_subscribed(bot: Bot, user_id: int) -> bool:
    """Проверка наличия подписки на канал."""
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

    if await is_subscribed(bot, user.id):
        await message.answer(
            get_main_menu_text(),
            reply_markup=get_main_menu_keyboard(),
            parse_mode="HTML",
        )
    else:
        safe_name = html.escape(user.first_name)
        await message.answer(
            f"👋 Привет, <b>{safe_name}</b>!\n\n"
            "⚠️ Для использования бота необходимо подписаться на наш канал:\n"
            f"👉 <a href=\"{CHANNEL_URL}\">Нажмите сюда, чтобы подписаться</a>\n\n"
            "После подписки нажмите кнопку <b>«✅ Я подписался»</b> ниже.",
            reply_markup=get_sub_keyboard(),
            parse_mode="HTML",
            disable_web_page_preview=True,
        )


@dp.callback_query(F.data == "check_sub")
async def callback_check_sub(callback: CallbackQuery, bot: Bot):
    user = callback.from_user
    if not user or not callback.message:
        return

    if await is_subscribed(bot, user.id):
        await callback.answer("✅ Подписка подтверждена!", show_alert=False)
        if isinstance(callback.message, Message):
            await callback.message.edit_text(
                get_main_menu_text(),
                reply_markup=get_main_menu_keyboard(),
                parse_mode="HTML",
            )
    else:
        await callback.answer(
            "❌ Вы ещё не подписались на канал!\n\nПожалуйста, перейдите в канал и нажмите «Подписаться».",
            show_alert=True,
        )


@dp.callback_query(F.data == "back_to_main")
async def callback_back_to_main(callback: CallbackQuery, state: FSMContext):
    await state.clear()
    if callback.message and isinstance(callback.message, Message):
        await callback.message.edit_text(
            get_main_menu_text(),
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
    user_data = db.get_user(callback.from_user.id)
    sub_expires_at = user_data.get("sub_expires_at", 0) if user_data else 0
    now = int(datetime.datetime.now().timestamp())

    if sub_expires_at > now:
        expires_date = datetime.datetime.fromtimestamp(sub_expires_at).strftime("%d.%m.%Y")
        text = (
            f"✅ <b>Ваш доступ активен!</b>\n\n"
            f"⏳ Срок действия: до <b>{expires_date}</b>"
        )
    else:
        text = (
            "❌ Активной подписки нет.\n"
            "Нажмите «ПОДПИСКА» в главном меню."
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

    buyer_status = "✅ Есть покупка" if has_buyer else "❌ Пока нет купивших"

    text = (
        "👥 <b>Реферальная система</b>\n"
        "───────────────────────────\n"
        "Пригласи 3-х друзей и один из них должен купить подписку чтобы ты получил бесплатный доступ!\n\n"
        f"🔗 Ваша ссылка:\n"
        f"<code>{ref_link}</code>\n\n"
        f"👥 Приглашено друзей: <b>{invited_count} / 3</b>\n"
        f"💳 Покупка от реферала: {buyer_status}"
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
        "Рекламируй бота в TikTok и получай подписку в боте!\n\n"
        "2000 просмотров - 1 подписка\n\n"
        "Чтобы сотрудничать подай заявку по форме ниже\n\n"
        "Юзернейм тг:\n"
        "Ссылка на тик ток:\n"
        "Сколько видео в день готовы публиковать:"
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
        "🛠 <b>Техническая поддержка</b>\n"
        "───────────────────────────\n"
        "Напишите ваше сообщение или вопрос в ответном сообщении,\n"
        "и администратор ответит вам."
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

    invoice = await xrocket_pay.create_invoice(amount="8.5", currency="USDT")

    if invoice:
        inv_id, pay_link = invoice

        if ADMIN_ID:
            try:
                await bot.send_message(
                    chat_id=ADMIN_ID,
                    text=(
                        "💳 <b>Создан новый счёт на оплату!</b>\n\n"
                        f"<b>Пользователь:</b> {safe_name} ({user_handle})\n"
                        f"<b>ID:</b> <code>{user.id}</code>\n"
                        f"<b>Сумма:</b> 8.5 USDT\n"
                        f"<b>ID счёта:</b> <code>{inv_id}</code>\n"
                        f"<b>Ссылка:</b> {pay_link}"
                    ),
                    reply_markup=get_user_contact_button(user.id, user.username),
                    parse_mode="HTML",
                )
            except Exception as e:
                logger.error("Ошибка при отправке уведомления админу: %s", e)

        text = (
            "💳 <b>Оформление подписки через xRocket</b>\n"
            "───────────────────────────\n"
            "<b>Срок:</b> 30 дней\n"
            "<b>Сумма к оплате:</b> 8.5 USDT\n\n"
            "Нажмите кнопку <b>«🚀 Перейти к оплате»</b> ниже для оплаты в боте xRocket.\n"
            "После совершения платежа нажмите кнопку <b>«🔄 Проверить оплату»</b>."
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
            "Не удалось создать счёт автоматически. Обратитесь к администратору @hetero777.",
            show_alert=True,
        )


@dp.callback_query(F.data.startswith("check_inv_"))
async def callback_check_invoice(callback: CallbackQuery, bot: Bot):
    user = callback.from_user
    invoice_id = callback.data.replace("check_inv_", "").strip()

    is_paid = await xrocket_pay.check_invoice_paid(invoice_id)

    if is_paid:
        db.activate_subscription(user.id, days=30)
        await callback.answer("✅ Оплата успешно подтверждена!", show_alert=True)

        if ADMIN_ID:
            try:
                await bot.send_message(
                    chat_id=ADMIN_ID,
                    text=(
                        "🎉 <b>Подписка успешно оплачена!</b>\n\n"
                        f"<b>Пользователь:</b> {html.escape(user.first_name)} (@{user.username})\n"
                        f"<b>ID:</b> <code>{user.id}</code>\n"
                        f"<b>Сумма:</b> 8.5 USDT\n"
                        f"<b>ID счёта:</b> <code>{invoice_id}</code>"
                    ),
                    reply_markup=get_user_contact_button(user.id, user.username),
                    parse_mode="HTML",
                )
            except Exception as e:
                logger.error("Ошибка уведомления админа об оплате: %s", e)

        if callback.message and isinstance(callback.message, Message):
            await callback.message.edit_text(
                "🎉 <b>Поздравляем! Оплата успешно прошла.</b>\n\n"
                "Ваш доступ активирован на <b>30 дней</b>.",
                reply_markup=get_back_keyboard(),
                parse_mode="HTML",
            )
    else:
        await callback.answer(
            "⏳ Оплата ещё не поступила.\nЕсли вы только что оплатили, подождите несколько секунд и проверьте снова.",
            show_alert=True,
        )


# ---------------- ОБРАБОТКА ТЕКСТОВЫХ СООБЩЕНИЙ ----------------


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
                    "🛠 <b>Новое обращение в техподдержку!</b>\n\n"
                    f"<b>От:</b> {safe_name} ({user_handle})\n"
                    f"<b>ID:</b> <code>{user.id}</code>\n\n"
                    f"<b>Сообщение:</b>\n{user_text}"
                ),
                reply_markup=get_user_contact_button(user.id, user.username),
                parse_mode="HTML",
            )
        except Exception as e:
            logger.error("Не удалось отправить сообщение админу: %s", e)

    await state.clear()
    await message.answer(
        "✅ Ваше сообщение отправлено в поддержку! Ожидайте ответа администратора.",
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
                    "🤝 <b>Новая заявка на сотрудничество!</b>\n\n"
                    f"<b>От:</b> {safe_name} ({user_handle})\n"
                    f"<b>ID:</b> <code>{user.id}</code>\n\n"
                    f"<b>Анкета:</b>\n{user_text}"
                ),
                reply_markup=get_user_contact_button(user.id, user.username),
                parse_mode="HTML",
            )
        except Exception as e:
            logger.error("Не удалось отправить заявку админу: %s", e)

    await state.clear()
    await message.answer(
        "✅ Ваша заявка на сотрудничество принята! Мы скоро свяжемся с вами.",
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

    # Запускаем встроенный веб-сервер для Render.com
    await start_web_server()

    try:
        await bot.delete_webhook(drop_pending_updates=True)
        await dp.start_polling(bot)
    finally:
        await bot.session.close()


if __name__ == "__main__":
    asyncio.run(main())
