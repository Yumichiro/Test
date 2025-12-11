import json
import logging
import os
import traceback
from datetime import datetime, timedelta, timezone
from io import BytesIO
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

from telegram import Update
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    ContextTypes,
    filters,
)
from telegram.error import TelegramError
from apscheduler.schedulers.asyncio import AsyncIOScheduler

# 🔑 Токен бота
TOKEN = "7858833917:AAH3BSCm4tAIj6YP82TbCUSDVS-moR_XlR8"

# 🧾 Белый список ID (кому доступны /promote и /demote)
WHITELIST = [666580112, 1131995068]

# 🧠 Файлы для сохранения
CACHE_FILE = "user_cache.json"
USED_NAME_FILE = "used_name.json"
ACTIVITY_FILE = "activity.json"

# 🧠 Данные
user_cache = {}
used_name = {}
activity_data = {}

# 🔧 Логирование
logging.basicConfig(format="%(asctime)s - %(levelname)s - %(message)s", level=logging.INFO)
logger = logging.getLogger(__name__)

# ==========================
# 💾 Файлы
# ==========================
def ensure_files():
    for f in [CACHE_FILE, USED_NAME_FILE, ACTIVITY_FILE]:
        if not os.path.exists(f):
            with open(f, "w", encoding="utf-8") as file:
                json.dump({}, file)
            logger.info(f"📂 Создан пустой {f}")

def load_cache():
    global user_cache
    try:
        with open(CACHE_FILE, "r", encoding="utf-8") as f:
            user_cache = json.load(f)
        logger.info(f"📂 Загружено пользователей: {len(user_cache)}")
    except Exception as e:
        logger.error(f"⚠️ Ошибка при загрузке кэша: {e}")
        user_cache = {}

def save_cache():
    try:
        with open(CACHE_FILE, "w", encoding="utf-8") as f:
            json.dump(user_cache, f, ensure_ascii=False, indent=2)
        logger.info("💾 Кэш сохранён.")
    except Exception as e:
        logger.error(f"⚠️ Ошибка при сохранении кэша: {e}")

def load_used_name():
    global used_name
    try:
        with open(USED_NAME_FILE, "r", encoding="utf-8") as f:
            used_name = json.load(f)
        logger.info(f"📂 Загружено пользователей, использовавших /name: {len(used_name)}")
    except Exception as e:
        logger.error(f"⚠️ Ошибка при загрузке used_name: {e}")
        used_name = {}

def save_used_name():
    try:
        with open(USED_NAME_FILE, "w", encoding="utf-8") as f:
            json.dump(used_name, f, ensure_ascii=False, indent=2)
        logger.info("💾 Список использовавших /name сохранён.")
    except Exception as e:
        logger.error(f"⚠️ Ошибка при сохранении used_name: {e}")

def load_activity():
    global activity_data
    try:
        with open(ACTIVITY_FILE, "r", encoding="utf-8") as f:
            activity_data = json.load(f)
        logger.info(f"📂 Загружены данные активности (чатов: {len(activity_data)})")
    except Exception as e:
        logger.error(f"⚠️ Ошибка при загрузке activity: {e}")
        activity_data = {}

def save_activity():
    try:
        with open(ACTIVITY_FILE, "w", encoding="utf-8") as f:
            json.dump(activity_data, f, ensure_ascii=False, indent=2)
        logger.info("💾 activity сохранён.")
    except Exception as e:
        logger.error(f"⚠️ Ошибка сохранения activity: {e}")

# ==========================
# 💾 Слежение за сообщениями
# ==========================
async def cache_user(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    chat = update.effective_chat
    if not user or not chat:
        return

    # Добавляем в кэш по username (если есть)
    if user.username:
        uname = user.username.lower()
        if user_cache.get(uname) != user.id:
            user_cache[uname] = user.id
            save_cache()
            logger.info(f"🧠 Добавлен в кэш: @{user.username} → {user.id}")

    # Подсчёт активности
    chat_id = str(chat.id)
    uid = str(user.id)
    activity_data.setdefault(chat_id, {})
    activity_data[chat_id].setdefault(uid, {"score": 0, "history": [], "base_score": 0})
    activity_data[chat_id][uid]["score"] = int(activity_data[chat_id][uid].get("score", 0)) + 1
    save_activity()

# ==========================
# 🔍 Определение ID пользователя
# ==========================
async def resolve_user_id(update: Update, context: ContextTypes.DEFAULT_TYPE, arg: str, chat_id: int):
    if update.message.reply_to_message:
        user = update.message.reply_to_message.from_user
        logger.info(f"🎯 Выбран из reply: {user.id} (@{user.username or 'нет'})")
        return user.id

    if arg.isdigit():
        user_id = int(arg)
        logger.info(f"🎯 Используем user_id: {user_id}")
        return user_id

    if arg.startswith("@"):
        username = arg[1:].lower()
        logger.info(f"🔍 Поиск по username: @{username}")

        if username in user_cache:
            logger.info(f"✅ Найден в кэше: @{username} → {user_cache[username]}")
            return user_cache[username]

        try:
            target_chat = await context.bot.get_chat(f"@{username}")
            logger.info(f"✅ Найден через API: {target_chat.id} ({target_chat.full_name})")
            user_cache[username] = target_chat.id
            save_cache()
            return target_chat.id
        except TelegramError as e:
            logger.warning(f"⚠️ Не удалось найти @{username}: {e}")

        await update.message.reply_text(
            f"❌ Не удалось найти пользователя @{username}. "
            f"Попросите его написать сообщение в чат, чтобы бот его запомнил."
        )
        return None

    await update.message.reply_text("❌ Укажите: user_id, @username или ответьте на сообщение.")
    return None

# ==========================
# 📈 /promote
# ==========================
async def promote(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.message.chat_id
    user = update.effective_user

    if user.id not in WHITELIST:
        await update.message.reply_text("🚫 У вас нет доступа к этой команде!")
        return

    if not context.args and not update.message.reply_to_message:
        await update.message.reply_text("Использование: /promote <user_id|@username> или ответьте на сообщение.")
        return

    target_arg = context.args[0] if context.args else None
    target_id = await resolve_user_id(update, context, target_arg, chat_id)
    if not target_id:
        return

    try:
        caller_member = await context.bot.get_chat_member(chat_id, user.id)
        bot_member = await context.bot.get_chat_member(chat_id, context.bot.id)
    except TelegramError as e:
        await update.message.reply_text("❌ Ошибка проверки прав.")
        logger.error(f"Ошибка get_chat_member: {e}")
        return

    if caller_member.status not in ("creator", "administrator"):
        await update.message.reply_text("⚠️ Только администраторы и создатель могут повышать.")
        return
    elif caller_member.status == "administrator" and not getattr(caller_member, "can_promote_members", False):
        await update.message.reply_text("⚠️ У вас нет права назначать администраторов.")
        return

    if bot_member.status != "administrator" or not getattr(bot_member, "can_promote_members", False):
        await update.message.reply_text("⚠️ У бота нет прав назначать администраторов!")
        return

    try:
        await context.bot.promote_chat_member(
            chat_id=chat_id,
            user_id=target_id,
            can_manage_chat=False,
            can_delete_messages=False,
            can_invite_users=False,
            can_restrict_members=False,
            can_pin_messages=False,
            can_promote_members=False,
            can_manage_video_chats=True,
            can_manage_topics=False,
            is_anonymous=False,
        )

        try:
            target_user = await context.bot.get_chat(target_id)
            name = f"@{target_user.username}" if target_user.username else f"ID {target_id}"
        except Exception:
            name = f"ID {target_id}"

        await update.message.reply_text(f"✅ Пользователь {name} назначен администратором без прав.")
    except TelegramError as e:
        logger.error(f"Ошибка при повышении: {e}")
        await update.message.reply_text(f"❌ Ошибка: {e}")

# ==========================
# 📉 /demote
# ==========================
async def demote(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.message.chat_id
    user = update.effective_user

    if user.id not in WHITELIST:
        await update.message.reply_text("🚫 У вас нет доступа к этой команде!")
        return

    if not context.args and not update.message.reply_to_message:
        await update.message.reply_text("Использование: /demote <user_id|@username> или ответьте на сообщение.")
        return

    target_arg = context.args[0] if context.args else None
    target_id = await resolve_user_id(update, context, target_arg, chat_id)
    if not target_id:
        return

    try:
        caller_member = await context.bot.get_chat_member(chat_id, user.id)
        bot_member = await context.bot.get_chat_member(chat_id, context.bot.id)
        target_member = await context.bot.get_chat_member(chat_id, target_id)
    except TelegramError as e:
        await update.message.reply_text("❌ Ошибка получения данных.")
        logger.error(f"Ошибка: {e}")
        return

    if caller_member.status not in ("creator", "administrator"):
        await update.message.reply_text("⚠️ Только администраторы и создатель могут понижать.")
        return
    elif caller_member.status == "administrator" and not getattr(caller_member, "can_promote_members", False):
        await update.message.reply_text("⚠️ У вас нет права изменять администраторов.")
        return

    if bot_member.status != "administrator" or not getattr(bot_member, "can_promote_members", False):
        await update.message.reply_text("⚠️ У бота нет прав изменять администраторов!")
        return

    if target_member.status not in ("administrator", "creator"):
        await update.message.reply_text("❌ Этот пользователь не является администратором.")
        return
    if target_member.status == "creator":
        await update.message.reply_text("❌ Нельзя снять создателя чата!")
        return

    try:
        await context.bot.promote_chat_member(
            chat_id=chat_id,
            user_id=target_id,
            can_manage_chat=False,
            can_delete_messages=False,
            can_invite_users=False,
            can_restrict_members=False,
            can_pin_messages=False,
            can_promote_members=False,
            can_manage_video_chats=False,
            can_manage_topics=False,
            is_anonymous=False,
        )

        try:
            target_user = await context.bot.get_chat(target_id)
            name = f"@{target_user.username}" if target_user.username else f"ID {target_id}"
        except Exception:
            name = f"ID {target_id}"

        await update.message.reply_text(f"✅ С пользователя {name} снят статус администратора.")
    except TelegramError as e:
        logger.error(f"Ошибка при понижении: {e}")
        await update.message.reply_text(f"❌ Ошибка: {e}")

# ==========================
# 📝 /name — изменить свой титул (только один раз)
# ==========================
async def set_name(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = str(update.message.chat_id)
    user_id = str(update.effective_user.id)
    user = update.effective_user

    if user_id in used_name.get(chat_id, []):
        await update.message.reply_text("❌ Вы уже использовали эту команду и больше не можете менять титул.")
        return

    if not context.args:
        await update.message.reply_text("Использование: /name <новый титул>")
        return

    new_title = " ".join(context.args).strip()
    if not new_title:
        await update.message.reply_text("❌ Укажите новый титул")
        return

    try:
        member = await context.bot.get_chat_member(chat_id, user.id)
    except TelegramError as e:
        await update.message.reply_text("❌ Ошибка получения данных о вас")
        logger.error(f"Ошибка get_chat_member: {e}")
        return

    if member.status != "administrator":
        await update.message.reply_text("⚠️ Только администраторы могут менять свой титул.")
        return

    try:
        await context.bot.set_chat_administrator_custom_title(
            chat_id=chat_id,
            user_id=user.id,
            custom_title=new_title
        )
        used_name.setdefault(chat_id, []).append(user_id)
        save_used_name()
        await update.message.reply_text(f"✅ Ваш титул обновлён на: {new_title}")
    except TelegramError as e:
        logger.error(f"Ошибка установки титула: {e}")
        await update.message.reply_text(f"❌ Не удалось изменить титул: {e}")

# ==========================
# ⏳ Ежедневный snapshot и еженедельный decay
# ==========================
async def daily_snapshot():
    """
    Делаем ежедневный снимок активности.
    Добавляем текущее значение очков в историю каждого пользователя.
    """
    for chat_id, users in activity_data.items():
        if chat_id == 'last_daily':
            continue
        for uid, info in users.items():
            score = int(info.get("score", 0))
            history = info.get("history", [])
            history.append(score)
            # Сохраняем только последние 7 записей
            info["history"] = history[-7:]
    save_activity()
    logger.info("📊 Ежедневный снимок активности сохранён.")

async def weekly_decay():
    for chat_id, users in activity_data.items():
        if chat_id == 'last_daily':
            continue
        for uid, info in users.items():
            score = int(info.get("score", 0))
            loss = max(5, int(score * 0.2))
            info["score"] = max(0, score - loss)
            info["base_score"] = info["score"]
    save_activity()
    logger.info("📉 Еженедельное снижение очков выполнено.")

async def daily_job(now=None):
    if now is None:
        now = datetime.now(timezone(timedelta(hours=3)))
    if now.weekday() == 0:  # Monday
        await weekly_decay()
    await daily_snapshot()
    activity_data['last_daily'] = now.isoformat()
    save_activity()

# ==========================
# 📊 /chart
# ==========================
async def cmd_chart(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat = update.effective_chat
    user = update.effective_user
    if not chat or not user:
        return

    chat_id = str(chat.id)
    uid = str(user.id)
    if chat_id not in activity_data or uid not in activity_data[chat_id]:
        await update.message.reply_text("Нет данных по вашей активности. Начните писать сообщения.")
        return

    info = activity_data[chat_id][uid]
    history = info.get("history", [])
    current_score = int(info.get("score", 0))
    points = history + [current_score]
    points = [0] + points
    points = points[-10:]

    today = datetime.now(timezone(timedelta(hours=3)))
    dates = [(today - timedelta(days=len(points)-i-1)).strftime("%d.%m") for i in range(len(points))]

    messages_day = points[-1] - points[-2] if len(points) >= 2 else points[-1]
    messages_day = max(0, messages_day)

    base_score = info.get("base_score", 0)
    messages_week = max(0, current_score - base_score)

    fig, ax = plt.subplots(figsize=(10, 4))
    ax.set_facecolor("#030d3a")
    plt.grid(True, color="gray", linestyle="--", alpha=0.3)
    plt.plot(points, color="#10e0a3", linewidth=2.5, marker='o')
    plt.fill_between(range(len(points)), points, 0, color="#10e0a3", alpha=0.1)
    plt.axhline(y=100, color="red", linestyle="--", linewidth=1.5)
    plt.title("Ваша активность", color="white", fontsize=14)
    plt.ylabel("Сообщения", color="white")
    plt.xticks(ticks=range(len(points)), labels=dates, rotation=45, color="white", fontsize=8)
    plt.yticks(color="white", fontsize=8)
    plt.ylim(bottom=0)
    for i, v in enumerate(points):
        plt.annotate(str(v), (i, v), textcoords="offset points", xytext=(0, 6),
                     ha='center', fontsize=8, color="white")

    buf = BytesIO()
    plt.savefig(buf, format='png', bbox_inches='tight', facecolor="#030d3a")
    plt.close()
    buf.seek(0)

    caption = (f"Количество сообщений за день: {messages_day}\n"
               f"Количество сообщений за неделю: {messages_week}")
    await update.message.reply_photo(photo=buf, caption=caption)

# ==========================
# 📸 /snapshot — manual daily snapshot
# ==========================
async def manual_snapshot(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    if user.id not in WHITELIST:
        await update.message.reply_text("🚫 У вас нет доступа к этой команде!")
        return

    await daily_snapshot()
    await update.message.reply_text("📊 Ручной ежедневный снимок активности выполнен.")

# ==========================
# 📉 /weekly — manual weekly decay
# ==========================
async def manual_weekly_decay(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    if user.id not in WHITELIST:
        await update.message.reply_text("🚫 У вас нет доступа к этой команде!")
        return

    await weekly_decay()
    await update.message.reply_text("📉 Ручное еженедельное снижение очков выполнено.")

# ==========================
# ⚠️ Ошибки
# ==========================
async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE):
    error_text = "".join(traceback.format_exception(type(context.error), context.error, context.error.__traceback__))
    user_info = ""
    chat_info = ""
    if update:
        if hasattr(update, "effective_user") and update.effective_user:
            u = update.effective_user
            user_info = f"\n👤 Пользователь: @{u.username or u.first_name} ({u.id})"
        if hasattr(update, "effective_chat") and update.effective_chat:
            c = update.effective_chat
            chat_info = f"\n💬 Чат: {c.title or c.id}"
    full_message = f"⚠️ Ошибка в боте!{chat_info}{user_info}\n\n{error_text}"
    logger.error(full_message)
    try:
        await context.bot.send_message(chat_id=WHITELIST[0], text=full_message[:3900])
    except Exception:
        pass

# ==========================
# 🚀 Запуск бота
# ==========================
async def main():
    ensure_files()
    load_cache()
    load_used_name()
    load_activity()

    # Catch up on missed daily jobs
    last_daily_str = activity_data.get('last_daily')
    if last_daily_str:
        try:
            last_daily = datetime.fromisoformat(last_daily_str)
        except ValueError:
            last_daily = None
    else:
        last_daily = None

    current_now = datetime.now(timezone(timedelta(hours=3)))

    if last_daily is not None:
        next_expected = last_daily + timedelta(days=1)
        next_expected = next_expected.replace(hour=0, minute=0, second=0, microsecond=0)
        while next_expected < current_now:
            logger.info(f"🕒 Performing missed daily_job for {next_expected}")
            await daily_job(now=next_expected)
            next_expected = next_expected + timedelta(days=1)

    app = Application.builder().token(TOKEN).build()

    async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
        await update.message.reply_text("Привет! Я бот для администрирования и учёта активности.")

    async def cmd_myid(update: Update, context: ContextTypes.DEFAULT_TYPE):
        await update.message.reply_text(f"Твой user_id: {update.effective_user.id}")

    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("myid", cmd_myid))
    app.add_handler(CommandHandler("promote", promote))
    app.add_handler(CommandHandler("demote", demote))
    app.add_handler(CommandHandler("name", set_name))
    app.add_handler(CommandHandler("chart", cmd_chart))
    app.add_handler(CommandHandler("snapshot", manual_snapshot))
    app.add_handler(CommandHandler("weekly", manual_weekly_decay))
    app.add_handler(MessageHandler(filters.ALL & (~filters.COMMAND), cache_user))
    app.add_error_handler(error_handler)

    scheduler = AsyncIOScheduler(timezone="Europe/Moscow")
    scheduler.add_job(daily_job, "cron", hour=0, minute=0)
    scheduler.start()
    logger.info("🕒 Планировщик запущен")

    async with app:
        await app.start()
        await app.updater.start_polling(drop_pending_updates=True)
        # Держим цикл запущенным бесконечно
        await asyncio.Event().wait()

if __name__ == "__main__":
    import asyncio
    asyncio.run(main())