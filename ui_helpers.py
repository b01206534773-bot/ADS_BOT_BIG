"""
ui_helpers.py — نظام رسالة البانر المتحركة
الفكرة: كل تحديث يحذف الرسالة القديمة ويبعت جديدة في آخر المحادثة.
دوال:
  send_ui         — بعت بانر جديد (أول استخدام)
  update_ui       — احذف القديمة + ابعت جديدة في الأسفل
  update_ui_call  — نفس update_ui لكن بياخد CallbackQuery مباشرةً
  reply_ui        — للـ message handlers (احذف + جديدة)
  clear_keep      — امسح الـ FSM مع الحفاظ على ui_msg_id
"""
from pathlib import Path
from aiogram import Bot
from aiogram.types import FSInputFile, CallbackQuery
from aiogram.fsm.context import FSMContext

BANNER_PATH = Path('attached_assets/paner_1784079200586.webp')
_file_id: str | None = None   # cache بعد أول رفع


async def send_ui(
    bot: Bot,
    chat_id: int,
    text: str,
    keyboard=None,
    state: FSMContext = None,
) -> int:
    """بعت رسالة بانر جديدة وحفظ message_id في state."""
    global _file_id
    photo = _file_id if _file_id else FSInputFile(BANNER_PATH)
    msg = await bot.send_photo(
        chat_id=chat_id,
        photo=photo,
        caption=text[:1020],
        reply_markup=keyboard,
        parse_mode='HTML',
    )
    if not _file_id and msg.photo:
        _file_id = msg.photo[-1].file_id
    if state:
        await state.update_data(ui_msg_id=msg.message_id, active_msg_id=msg.message_id)
    return msg.message_id


async def update_ui(
    bot: Bot,
    state: FSMContext,
    chat_id: int,
    text: str,
    keyboard=None,
    old_msg_id: int = None,
) -> int:
    """احذف الرسالة القديمة وابعت جديدة في أسفل المحادثة."""
    if old_msg_id is None:
        data = await state.get_data()
        old_msg_id = data.get('ui_msg_id')
    if old_msg_id:
        try:
            await bot.delete_message(chat_id=chat_id, message_id=old_msg_id)
        except Exception:
            pass
    return await send_ui(bot, chat_id, text, keyboard, state)


async def update_ui_call(
    call: CallbackQuery,
    state: FSMContext,
    text: str,
    keyboard=None,
) -> int:
    """مساعد للـ callbacks — يحذف رسالة call.message ويبعت جديدة."""
    return await update_ui(
        call.bot,
        state,
        call.message.chat.id,
        text,
        keyboard,
        old_msg_id=call.message.message_id,
    )


async def reply_ui(
    bot: Bot,
    state: FSMContext,
    chat_id: int,
    text: str,
    keyboard=None,
) -> int:
    """للـ message handlers — احذف البانر القديم وابعت جديد في الأسفل."""
    return await update_ui(bot, state, chat_id, text, keyboard)


async def clear_keep(state: FSMContext):
    """امسح الـ FSM مع الحفاظ على ui_msg_id و active_msg_id."""
    data = await state.get_data()
    ui  = data.get('ui_msg_id')
    act = data.get('active_msg_id')
    await state.clear()
    patch = {}
    if ui:
        patch['ui_msg_id'] = ui
    if act:
        patch['active_msg_id'] = act
    if patch:
        await state.update_data(**patch)
