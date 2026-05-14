import asyncio
import logging
import csv
from datetime import datetime
from aiogram import Bot, Dispatcher, F
from aiogram.types import Message, CallbackQuery, ReplyKeyboardMarkup, KeyboardButton, ReplyKeyboardRemove
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage

# ==============================
# НАСТРОЙКИ - ЗАПОЛНИ СВОИ ДАННЫЕ
# ==============================
BOT_TOKEN = "8677859917:AAFhsXDuwRzspzIYjr4wJ0tajKyHsJXPWYM"
GROUP_CHAT_ID = -1003987828582  # Вставь ID своей группы

MANAGERS = ["Лёша", "Тимур"]
DELIVERY_OPTIONS = ["Самовывоз", "Новая Почта"]
# ==============================

logging.basicConfig(level=logging.INFO)

# Загрузка товаров из CSV
def load_products():
    products = []
    with open("products.csv", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            products.append({
                "article": row["article"],
                "name": row["name"],
                "price": float(row["price"]) if row["price"] else 0
            })
    return products

PRODUCTS = load_products()

def search_products(query: str, limit: int = 15):
    """Поиск товаров по подстроке (нечувствительно к регистру)"""
    query = query.lower().strip()
    results = []
    for p in PRODUCTS:
        if all(word in p["name"].lower() for word in query.split()) or query in p["article"].lower():
            results.append(p)
        if len(results) >= limit:
            break
    return results

def short_name(name: str, max_len: int = 55) -> str:
    """Сокращённое название для отображения в списке"""
    if len(name) <= max_len:
        return name
    return name[:max_len] + "..."

# FSM состояния
class OrderForm(StatesGroup):
    manager = State()
    client_name = State()
    client_phone = State()
    delivery = State()
    nova_poshta = State()
    adding_items = State()
    item_search = State()
    item_select = State()
    item_quantity = State()
    item_price = State()
    confirm = State()

order_counter = {"value": 1}

def make_keyboard(options: list) -> ReplyKeyboardMarkup:
    buttons = [[KeyboardButton(text=opt)] for opt in options]
    return ReplyKeyboardMarkup(keyboard=buttons, resize_keyboard=True, one_time_keyboard=True)

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher(storage=MemoryStorage())

# ── /start ──────────────────────────────────────────
@dp.message(Command("start"))
async def cmd_start(message: Message, state: FSMContext):
    await state.clear()
    kb = ReplyKeyboardMarkup(
        keyboard=[[KeyboardButton(text="🆕 Создать заказ")]],
        resize_keyboard=True
    )
    await message.answer("Привет! Нажми кнопку чтобы создать заказ.", reply_markup=kb)

# ── Создать заказ ────────────────────────────────────
@dp.message(F.text == "🆕 Создать заказ")
async def start_order(message: Message, state: FSMContext):
    await state.set_state(OrderForm.manager)
    await message.answer("Кто оформляет заказ?", reply_markup=make_keyboard(MANAGERS))

# ── Менеджер ─────────────────────────────────────────
@dp.message(OrderForm.manager)
async def set_manager(message: Message, state: FSMContext):
    if message.text not in MANAGERS:
        await message.answer("Выбери из списка:", reply_markup=make_keyboard(MANAGERS))
        return
    await state.update_data(manager=message.text, items=[])
    await state.set_state(OrderForm.client_name)
    await message.answer("Введи имя клиента:", reply_markup=ReplyKeyboardRemove())

# ── Имя клиента ───────────────────────────────────────
@dp.message(OrderForm.client_name)
async def set_client_name(message: Message, state: FSMContext):
    await state.update_data(client_name=message.text.strip())
    await state.set_state(OrderForm.client_phone)
    await message.answer("Введи телефон клиента:")

# ── Телефон ───────────────────────────────────────────
@dp.message(OrderForm.client_phone)
async def set_client_phone(message: Message, state: FSMContext):
    await state.update_data(client_phone=message.text.strip())
    await state.set_state(OrderForm.delivery)
    await message.answer("Метод доставки:", reply_markup=make_keyboard(DELIVERY_OPTIONS))

# ── Доставка ──────────────────────────────────────────
@dp.message(OrderForm.delivery)
async def set_delivery(message: Message, state: FSMContext):
    if message.text not in DELIVERY_OPTIONS:
        await message.answer("Выбери из списка:", reply_markup=make_keyboard(DELIVERY_OPTIONS))
        return
    await state.update_data(delivery=message.text)
    if message.text == "Новая Почта":
        await state.set_state(OrderForm.nova_poshta)
        await message.answer("Введи номер отделения НП:", reply_markup=ReplyKeyboardRemove())
    else:
        await state.set_state(OrderForm.adding_items)
        await message.answer(
            "Отлично! Теперь добавляй товары.\n\nВведи название или артикул для поиска:",
            reply_markup=ReplyKeyboardRemove()
        )

# ── Отделение НП ─────────────────────────────────────
@dp.message(OrderForm.nova_poshta)
async def set_nova_poshta(message: Message, state: FSMContext):
    await state.update_data(nova_poshta=message.text.strip())
    await state.set_state(OrderForm.adding_items)
    await message.answer("Введи название или артикул для поиска:")

# ── Поиск товара ─────────────────────────────────────
@dp.message(OrderForm.adding_items)
async def search_item(message: Message, state: FSMContext):
    text = message.text.strip()

    # Команды
    if text.lower() in ["готово", "✅ готово"]:
        await show_order_summary(message, state)
        return

    results = search_products(text)

    if not results:
        await message.answer(
            "Ничего не найдено. Попробуй другой запрос.\n\nИли напиши <b>готово</b> чтобы завершить заказ.",
            parse_mode="HTML"
        )
        return

    # Формируем нумерованный список
    lines = ["Найдено товаров: <b>{}</b>\n".format(len(results))]
    for i, p in enumerate(results, 1):
        price_str = f" — {p['price']:.0f} грн" if p['price'] > 0 else ""
        lines.append(f"<b>{i}.</b> {short_name(p['name'], 120)}{price_str}")
        lines.append("")  # пустая строка между товарами

    lines.append("\n👉 Введи <b>номер</b> товара или уточни запрос:")
    lines.append("Или напиши <b>готово</b> чтобы завершить заказ.")

    await state.update_data(search_results=results)
    await state.set_state(OrderForm.item_select)
    await message.answer("\n".join(lines), parse_mode="HTML")

# ── Выбор товара ─────────────────────────────────────
@dp.message(OrderForm.item_select)
async def select_item(message: Message, state: FSMContext):
    text = message.text.strip()

    if text.lower() in ["готово", "✅ готово"]:
        await show_order_summary(message, state)
        return

    data = await state.get_data()
    results = data.get("search_results", [])

    # Если ввели число - выбираем товар
    if text.isdigit():
        idx = int(text) - 1
        if 0 <= idx < len(results):
            selected = results[idx]
            await state.update_data(selected_item=selected)
            await state.set_state(OrderForm.item_quantity)
            await message.answer(
                f"✅ Выбран:\n<b>{selected['name']}</b>\n"
                f"Арт: {selected['article']}\n\n"
                f"Введи количество (шт):",
                parse_mode="HTML"
            )
            return
        else:
            await message.answer(f"Введи число от 1 до {len(results)}:")
            return

    # Иначе - новый поиск
    await state.set_state(OrderForm.adding_items)
    await search_item(message, state)

# ── Количество товара ─────────────────────────────────
@dp.message(OrderForm.item_quantity)
async def set_item_quantity(message: Message, state: FSMContext):
    text = message.text.strip()
    if not text.isdigit() or int(text) < 1:
        await message.answer("Введи целое число, например: 2")
        return
    quantity = int(text)
    data = await state.get_data()
    selected = data["selected_item"]
    await state.update_data(item_quantity=quantity)
    await state.set_state(OrderForm.item_price)
    price_hint = f"\n(В базе: {selected['price']:.0f} грн)" if selected['price'] > 0 else ""
    await message.answer(
        f"Количество: <b>{quantity} шт</b>{price_hint}\n\n"
        f"Введи цену продажи за 1 шт (грн):",
        parse_mode="HTML"
    )

# ── Цена товара ───────────────────────────────────────
@dp.message(OrderForm.item_price)
async def set_item_price(message: Message, state: FSMContext):
    text = message.text.strip().replace(",", ".")
    try:
        price = float(text)
    except ValueError:
        await message.answer("Введи числом, например: 1500")
        return

    data = await state.get_data()
    selected = data["selected_item"]
    quantity = data.get("item_quantity", 1)
    items = data.get("items", [])
    items.append({
        "name": selected["name"],
        "article": selected["article"],
        "price": price,
        "quantity": quantity
    })
    await state.update_data(items=items, search_results=[])
    await state.set_state(OrderForm.adding_items)

    total = sum(i["price"] * i.get("quantity", 1) for i in items)
    await message.answer(
        f"✅ Добавлено: {short_name(selected['name'], 40)}\n"
        f"<b>{quantity} шт × {price:.0f} грн = {quantity * price:.0f} грн</b>\n\n"
        f"Товаров в заказе: {len(items)} | Сумма: <b>{total:.0f} грн</b>\n\n"
        f"Введи следующий товар или напиши <b>готово</b>:",
        parse_mode="HTML"
    )

# ── Итог заказа ───────────────────────────────────────
async def show_order_summary(message: Message, state: FSMContext):
    data = await state.get_data()
    items = data.get("items", [])

    if not items:
        await message.answer("Ты не добавил ни одного товара. Введи название для поиска:")
        await state.set_state(OrderForm.adding_items)
        return

    total = sum(i["price"] * i.get("quantity", 1) for i in items)
    delivery = data.get("delivery", "")
    np_branch = data.get("nova_poshta", "")
    delivery_str = f"Новая Почта, отд. {np_branch}" if delivery == "Новая Почта" else "Самовывоз"

    lines = [
        "📋 <b>Проверь заказ:</b>\n",
        f"👤 Менеджер: {data.get('manager')}",
        f"🙍 Клиент: {data.get('client_name')}",
        f"📞 Телефон: {data.get('client_phone')}",
        f"🚚 Доставка: {delivery_str}",
        "\n<b>Товары:</b>"
    ]
    for i, item in enumerate(items, 1):
        qty = item.get("quantity", 1)
        lines.append(f"{i}. {short_name(item['name'], 45)}")
        lines.append(f"   {qty} шт × {item['price']:.0f} грн = {qty * item['price']:.0f} грн")

    lines.append(f"\n💰 <b>Итого: {total:.0f} грн</b>")

    await state.set_state(OrderForm.confirm)
    await message.answer(
        "\n".join(lines),
        parse_mode="HTML",
        reply_markup=make_keyboard(["✅ Подтвердить", "❌ Отменить"])
    )

# ── Подтверждение ─────────────────────────────────────
@dp.message(OrderForm.confirm)
async def confirm_order(message: Message, state: FSMContext):
    if message.text == "❌ Отменить":
        await state.clear()
        kb = ReplyKeyboardMarkup(
            keyboard=[[KeyboardButton(text="🆕 Создать заказ")]],
            resize_keyboard=True
        )
        await message.answer("Заказ отменён.", reply_markup=kb)
        return

    if message.text != "✅ Подтвердить":
        await message.answer("Нажми кнопку:", reply_markup=make_keyboard(["✅ Подтвердить", "❌ Отменить"]))
        return

    data = await state.get_data()
    items = data.get("items", [])
    total = sum(i["price"] * i.get("quantity", 1) for i in items)
    delivery = data.get("delivery", "")
    np_branch = data.get("nova_poshta", "")
    delivery_str = f"Новая Почта, отд. {np_branch}" if delivery == "Новая Почта" else "Самовывоз"
    now = datetime.now().strftime("%d.%m.%Y %H:%M")
    order_num = order_counter["value"]
    order_counter["value"] += 1

    # Сообщение в группу
    lines = [
        f"🆕 <b>Новый заказ #{order_num:04d}</b>",
        f"📅 {now}",
        f"👤 Менеджер: {data.get('manager')}",
        f"",
        f"🙍 Клиент: {data.get('client_name')}",
        f"📞 Телефон: {data.get('client_phone')}",
        f"🚚 Доставка: {delivery_str}",
        f"",
        f"<b>Товары:</b>"
    ]
    for i, item in enumerate(items, 1):
        qty = item.get("quantity", 1)
        lines.append(f"{i}. {item['name']}")
        lines.append(f"   Арт: {item['article']} | {qty} шт × {item['price']:.0f} грн = {qty * item['price']:.0f} грн")

    lines.append(f"")
    lines.append(f"💰 <b>Итого: {total:.0f} грн</b>")

    group_message = "\n".join(lines)

    try:
        await bot.send_message(GROUP_CHAT_ID, group_message, parse_mode="HTML")
        await message.answer(
            f"✅ Заказ #{order_num:04d} отправлен!",
            reply_markup=ReplyKeyboardMarkup(
                keyboard=[[KeyboardButton(text="🆕 Создать заказ")]],
                resize_keyboard=True
            )
        )
    except Exception as e:
        await message.answer(f"Ошибка отправки в группу: {e}")

    await state.clear()

# ── Запуск ────────────────────────────────────────────
async def main():
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
