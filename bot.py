import asyncio
import logging
import aiohttp
from datetime import datetime
from aiogram import Bot, Dispatcher, F
from aiogram.types import Message, ReplyKeyboardMarkup, KeyboardButton, ReplyKeyboardRemove
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage

# ==============================
# НАСТРОЙКИ - ЗАПОЛНИ СВОИ ДАННЫЕ
# ==============================
BOT_TOKEN = "8823108260:AAFUiFvspXvrsiuw0OuLuEajCxALXogshX0"
GROUP_CHAT_ID = -1003987828582  # Вставь ID своей группы
ROAPP_API_KEY = "16c119cfb495407bac606bd8055bc11e"
ROAPP_API_URL = "https://api.roapp.io/v2"

ROAPP_WAREHOUSE_ID = 3096824
MANAGERS = ["Лёша", "Тимур"]
DELIVERY_OPTIONS = ["Самовывоз", "Новая Почта"]
# ==============================

logging.basicConfig(level=logging.INFO)

async def get_stock(product_ids: list) -> dict:
    if not product_ids:
        return {}
    headers = {"Authorization": f"Bearer {ROAPP_API_KEY}"}
    params = [("ids[]", pid) for pid in product_ids]
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(
                f"https://api.roapp.io/warehouse/goods/{ROAPP_WAREHOUSE_ID}",
                headers=headers, params=params
            ) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    items = data if isinstance(data, list) else data.get("data", [])
                    return {p["id"]: p.get("residue", 0) for p in items}
                else:
                    logging.error(f"Stock API error: {resp.status}")
    except Exception as e:
        logging.error(f"Get stock error: {e}")
    return {}

async def search_products_api(query: str, limit: int = 15):
    headers = {"Authorization": f"Bearer {ROAPP_API_KEY}"}
    params = {"q": query}
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(
                f"{ROAPP_API_URL}/catalog/products", headers=headers, params=params
            ) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    items = data.get("data", [])[:limit]
                    product_ids = [p["id"] for p in items]
                    stock = await get_stock(product_ids)
                    results = []
                    for p in items:
                        pid = p.get("id")
                        results.append({
                            "article": p.get("code", p.get("sku", "")),
                            "name": p.get("title", ""),
                            "price": 0,
                            "stock": stock.get(pid, 0)
                        })
                    return results
                else:
                    logging.error(f"Catalog API error: {resp.status}")
                    return []
    except Exception as e:
        logging.error(f"Search API error: {e}")
        return []

def short_name(name: str, max_len: int = 120) -> str:
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
    item_select = State()
    item_quantity = State()
    item_price = State()
    comment = State()
    confirm = State()

order_counter = {"value": 1}

CANCEL_BTN = "🚫 Отменить заказ"
DELETE_BTN = "↩️ Удалить последний товар"
DONE_BTN = "✅ Готово"

def make_keyboard(options: list, cancel: bool = True) -> ReplyKeyboardMarkup:
    buttons = [[KeyboardButton(text=opt)] for opt in options]
    if cancel:
        buttons.append([KeyboardButton(text=CANCEL_BTN)])
    return ReplyKeyboardMarkup(keyboard=buttons, resize_keyboard=True, one_time_keyboard=True)

def items_keyboard() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text=DONE_BTN)],
            [KeyboardButton(text=DELETE_BTN)],
            [KeyboardButton(text=CANCEL_BTN)],
        ],
        resize_keyboard=True
    )

def cancel_kb() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[[KeyboardButton(text=CANCEL_BTN)]],
        resize_keyboard=True
    )

async def cancel_order(message: Message, state: FSMContext):
    await state.clear()
    kb = ReplyKeyboardMarkup(
        keyboard=[[KeyboardButton(text="🆕 Создать заказ")]],
        resize_keyboard=True
    )
    await message.answer("🚫 Заказ отменён. Начни заново.", reply_markup=kb)

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher(storage=MemoryStorage())

# ── /cancel ──────────────────────────────────────────
@dp.message(Command("cancel"))
async def cmd_cancel(message: Message, state: FSMContext):
    await cancel_order(message, state)

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
    if message.text == CANCEL_BTN:
        await cancel_order(message, state); return
    if message.text not in MANAGERS:
        await message.answer("Выбери из списка:", reply_markup=make_keyboard(MANAGERS))
        return
    await state.update_data(manager=message.text, items=[])
    await state.set_state(OrderForm.client_name)
    await message.answer("Введи имя клиента:", reply_markup=cancel_kb())

# ── Имя клиента ───────────────────────────────────────
@dp.message(OrderForm.client_name)
async def set_client_name(message: Message, state: FSMContext):
    if message.text == CANCEL_BTN:
        await cancel_order(message, state); return
    await state.update_data(client_name=message.text.strip())
    await state.set_state(OrderForm.client_phone)
    await message.answer("Введи телефон клиента:", reply_markup=cancel_kb())

# ── Телефон ───────────────────────────────────────────
@dp.message(OrderForm.client_phone)
async def set_client_phone(message: Message, state: FSMContext):
    if message.text == CANCEL_BTN:
        await cancel_order(message, state); return
    await state.update_data(client_phone=message.text.strip())
    await state.set_state(OrderForm.delivery)
    await message.answer("Метод доставки:", reply_markup=make_keyboard(DELIVERY_OPTIONS))

# ── Доставка ──────────────────────────────────────────
@dp.message(OrderForm.delivery)
async def set_delivery(message: Message, state: FSMContext):
    if message.text == CANCEL_BTN:
        await cancel_order(message, state); return
    if message.text not in DELIVERY_OPTIONS:
        await message.answer("Выбери из списка:", reply_markup=make_keyboard(DELIVERY_OPTIONS))
        return
    await state.update_data(delivery=message.text)
    if message.text == "Новая Почта":
        await state.set_state(OrderForm.nova_poshta)
        await message.answer("Введи номер отделения НП:", reply_markup=cancel_kb())
    else:
        await state.set_state(OrderForm.adding_items)
        await message.answer(
            "Отлично! Введи название или артикул для поиска:",
            reply_markup=items_keyboard()
        )

# ── Отделение НП ─────────────────────────────────────
@dp.message(OrderForm.nova_poshta)
async def set_nova_poshta(message: Message, state: FSMContext):
    if message.text == CANCEL_BTN:
        await cancel_order(message, state); return
    await state.update_data(nova_poshta=message.text.strip())
    await state.set_state(OrderForm.adding_items)
    await message.answer("Введи название или артикул для поиска:", reply_markup=items_keyboard())

# ── Поиск товара ─────────────────────────────────────
@dp.message(OrderForm.adding_items)
async def search_item(message: Message, state: FSMContext):
    text = message.text.strip()

    if text == CANCEL_BTN:
        await cancel_order(message, state); return

    if text == DELETE_BTN:
        data = await state.get_data()
        items = data.get("items", [])
        if not items:
            await message.answer("Список товаров пуст.", reply_markup=items_keyboard())
            return
        removed = items.pop()
        await state.update_data(items=items)
        total = sum(i["price"] * i.get("quantity", 1) for i in items)
        await message.answer(
            f"↩️ Удалён: {short_name(removed['name'], 50)}\n\n"
            f"Товаров в заказе: <b>{len(items)}</b> | Сумма: <b>{total:.0f} грн</b>\n\n"
            f"Введи следующий товар или нажми <b>Готово</b>:",
            parse_mode="HTML", reply_markup=items_keyboard()
        )
        return

    if text == DONE_BTN or text.lower() == "готово":
        await show_order_summary(message, state)
        return

    await message.answer("🔍 Ищу...", reply_markup=items_keyboard())
    results = await search_products_api(text)

    if not results:
        await message.answer(
            "Ничего не найдено. Попробуй другой запрос.\n\nИли нажми <b>Готово</b> чтобы завершить заказ.",
            parse_mode="HTML", reply_markup=items_keyboard()
        )
        return

    lines = [f"Найдено товаров: <b>{len(results)}</b>\n"]
    for i, p in enumerate(results, 1):
        stock = p.get("stock", 0)
        stock_str = f"🟩 {stock} шт" if stock > 0 else "❌ Нет на складе"
        lines.append(f"<b>{i}.</b> {short_name(p['name'])}")
        lines.append(f"   {stock_str} | Арт: {p['article']}")
        lines.append("")

    lines.append("👉 Введи <b>номер</b> товара или уточни запрос:")

    await state.update_data(search_results=results)
    await state.set_state(OrderForm.item_select)
    await message.answer("\n".join(lines), parse_mode="HTML")

# ── Выбор товара ─────────────────────────────────────
@dp.message(OrderForm.item_select)
async def select_item(message: Message, state: FSMContext):
    text = message.text.strip()

    if text == CANCEL_BTN:
        await cancel_order(message, state); return

    if text == DONE_BTN or text.lower() == "готово":
        await show_order_summary(message, state)
        return

    data = await state.get_data()
    results = data.get("search_results", [])

    if text.isdigit():
        idx = int(text) - 1
        if 0 <= idx < len(results):
            selected = results[idx]
            await state.update_data(selected_item=selected)
            await state.set_state(OrderForm.item_quantity)
            stock = selected.get("stock", 0)
            stock_str = f"🟩 На складе: {stock} шт" if stock > 0 else "❌ Нет на складе"
            await message.answer(
                f"✅ Выбран:\n<b>{selected['name']}</b>\n"
                f"Арт: {selected['article']}\n{stock_str}\n\n"
                f"Введи количество (шт):",
                parse_mode="HTML", reply_markup=cancel_kb()
            )
            return
        else:
            await message.answer(f"Введи число от 1 до {len(results)}:")
            return

    # Новый поиск
    await state.set_state(OrderForm.adding_items)
    await search_item(message, state)

# ── Количество товара ─────────────────────────────────
@dp.message(OrderForm.item_quantity)
async def set_item_quantity(message: Message, state: FSMContext):
    text = message.text.strip()
    if text == CANCEL_BTN:
        await cancel_order(message, state); return
    if not text.isdigit() or int(text) < 1:
        await message.answer("Введи целое число, например: 2")
        return
    quantity = int(text)
    await state.update_data(item_quantity=quantity)
    await state.set_state(OrderForm.item_price)
    await message.answer(
        f"Количество: <b>{quantity} шт</b>\n\nВведи цену продажи за 1 шт (грн):",
        parse_mode="HTML", reply_markup=cancel_kb()
    )

# ── Цена товара ───────────────────────────────────────
@dp.message(OrderForm.item_price)
async def set_item_price(message: Message, state: FSMContext):
    if message.text.strip() == CANCEL_BTN:
        await cancel_order(message, state); return
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
        f"✅ Добавлено: {short_name(selected['name'], 50)}\n"
        f"<b>{quantity} шт × {price:.0f} грн = {quantity * price:.0f} грн</b>\n\n"
        f"Товаров в заказе: {len(items)} | Сумма: <b>{total:.0f} грн</b>\n\n"
        f"Введи следующий товар или нажми <b>Готово</b>:",
        parse_mode="HTML", reply_markup=items_keyboard()
    )

# ── Комментарий ───────────────────────────────────────
async def ask_comment(message: Message, state: FSMContext):
    await state.set_state(OrderForm.comment)
    kb = ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="➡️ Без комментария")],
            [KeyboardButton(text=CANCEL_BTN)]
        ],
        resize_keyboard=True
    )
    await message.answer(
        "💬 Добавь комментарий или нажми <b>Без комментария</b>:",
        parse_mode="HTML", reply_markup=kb
    )

@dp.message(OrderForm.comment)
async def set_comment(message: Message, state: FSMContext):
    if message.text == CANCEL_BTN:
        await cancel_order(message, state); return
    comment = "" if message.text == "➡️ Без комментария" else message.text.strip()
    await state.update_data(comment=comment)
    await show_order_summary(message, state)

# ── Итог заказа ───────────────────────────────────────
async def show_order_summary(message: Message, state: FSMContext):
    data = await state.get_data()
    items = data.get("items", [])

    if not items:
        await message.answer(
            "Ты не добавил ни одного товара. Введи название для поиска:",
            reply_markup=items_keyboard()
        )
        await state.set_state(OrderForm.adding_items)
        return

    if "comment" not in data:
        await ask_comment(message, state)
        return

    total = sum(i["price"] * i.get("quantity", 1) for i in items)
    delivery = data.get("delivery", "")
    np_branch = data.get("nova_poshta", "")
    delivery_str = f"Новая Почта, отд. {np_branch}" if delivery == "Новая Почта" else "Самовывоз"
    comment = data.get("comment", "")

    lines = [
        "📋 <b>Проверь заказ:</b>\n",
        f"👤 Менеджер: {data.get('manager')}",
        f"🙍 Клиент: {data.get('client_name')}",
        f"📞 Телефон: {data.get('client_phone')}",
        f"🚚 Доставка: {delivery_str}",
    ]
    if comment:
        lines.append(f"💬 Комментарий: {comment}")
    lines.append("\n<b>Товары:</b>")
    for i, item in enumerate(items, 1):
        qty = item.get("quantity", 1)
        lines.append(f"{i}. {short_name(item['name'], 50)}")
        lines.append(f"   {qty} шт × {item['price']:.0f} грн = {qty * item['price']:.0f} грн")
    lines.append(f"\n💰 <b>Итого: {total:.0f} грн</b>")

    await state.set_state(OrderForm.confirm)
    await message.answer(
        "\n".join(lines), parse_mode="HTML",
        reply_markup=make_keyboard(["✅ Подтвердить", "❌ Отменить"], cancel=False)
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
        await message.answer(
            "Нажми кнопку:",
            reply_markup=make_keyboard(["✅ Подтвердить", "❌ Отменить"], cancel=False)
        )
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
    comment = data.get("comment", "")

    lines = [
        f"🆕 <b>Новый заказ #{order_num:04d}</b>",
        f"📅 {now}",
        f"👤 Менеджер: {data.get('manager')}",
        "",
        f"🙍 Клиент: {data.get('client_name')}",
        f"📞 Телефон: {data.get('client_phone')}",
        f"🚚 Доставка: {delivery_str}",
    ]
    if comment:
        lines.append(f"💬 {comment}")
    lines.append("")
    lines.append("<b>Товары:</b>")
    for i, item in enumerate(items, 1):
        qty = item.get("quantity", 1)
        lines.append(f"{i}. {item['name']}")
        lines.append(f"   Арт: {item['article']} | {qty} шт × {item['price']:.0f} грн = {qty * item['price']:.0f} грн")
    lines.append("")
    lines.append(f"💰 <b>Итого: {total:.0f} грн</b>")

    try:
        await bot.send_message(GROUP_CHAT_ID, "\n".join(lines), parse_mode="HTML")
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
    logging.info(f"✅ Бот запущен. Склад ID: {ROAPP_WAREHOUSE_ID}")
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
