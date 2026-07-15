"""
ui_helpers.py — نظام رسالة البانر الثابتة
- send_ui    : يبعت صورة البانر مع نص وأزرار (أول مرة)
- reply_ui   : يعدّل caption الرسالة الموجودة أو يبعت جديدة
- clear_keep : يمسح الـ state مع الحفاظ على ui_msg_id
"""
from pathlib import Path
from aiogram import Bot
from aiogram.types import FSInputFile
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


async def reply_ui(
    bot: Bot,
    state: FSMContext,
    chat_id: int,
    text: str,
    keyboard=None,
) -> int:
    """عدّل caption الرسالة الموجودة، أو ابعت جديدة لو مفيش."""
    data = await state.get_data()
    msg_id = data.get('ui_msg_id')
    if msg_id:
        try:
            await bot.edit_message_caption(
                chat_id=chat_id,
                message_id=msg_id,
                caption=text[:1020],
                reply_markup=keyboard,
                parse_mode='HTML',
            )
            return msg_id
        except Exception:
            pass
    return await send_ui(bot, chat_id, text, keyboard, state)


async def clear_keep(state: FSMContext):
    """امسح الـ state مع الحفاظ على ui_msg_id و active_msg_id."""
    data = await state.get_data()
    ui   = data.get('ui_msg_id')
    act  = data.get('active_msg_id')
    await state.clear()
    patch = {}
    if ui:
        patch['ui_msg_id'] = ui
    if act:
        patch['active_msg_id'] = act
    if patch:
        await state.update_data(**patch)
