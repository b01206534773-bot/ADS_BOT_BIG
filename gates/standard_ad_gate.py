from aiogram.types import CallbackQuery, Message
from aiogram.fsm.context import FSMContext
from keyboards import (
    back_home, proxy_selection_keyboard, back_to_proxy,
    objective_selection_keyboard, confirm_keyboard,
    activate_or_back_keyboard, post_selection_keyboard
)
from states import AdObjectives, GateConstants, AdGateStates
from gates.base_gate import BaseGate
from services.facebook_api import (
    run_standard_ad, run_standard_ad_then_pause, fetch_page_posts
)
from ui_helpers import reply_ui, clear_keep


def _result_text(result: dict, gate_name: str) -> str:
    paused = result.get('paused', False)
    status = "⏸ <b>تم النشر ثم الإيقاف بنجاح!</b>" if paused else "🟢 <b>الإعلان يعمل الآن!</b>"
    return (
        f"✅ <b>تم تشغيل {gate_name} بنجاح!</b>\n\n"
        "━━━━━━━━━━━━━━━━━━━━\n"
        f"📊 <b>Campaign ID:</b> <code>{result.get('campaign_id', 'N/A')}</code>\n"
        f"📦 <b>Ad Set ID:</b>  <code>{result.get('ad_set_id', 'N/A')}</code>\n"
        f"🎨 <b>Creative ID:</b> <code>{result.get('creative_id', 'N/A')}</code>\n"
        f"📌 <b>Ad ID:</b>      <code>{result.get('ad_id', 'N/A')}</code>\n\n"
        f"{status}"
    )


class StandardAdGate(BaseGate):
    def __init__(self):
        super().__init__('standard_ad', '🟢 إعلان رابط بوست', 'standard_ad')

    async def enter(self, call: CallbackQuery, state: FSMContext, config: dict):
        await state.update_data(gate_id=self.gate_id, gate_type=self.gate_type, gate_name=self.gate_name)
        await state.set_state(AdGateStates.waiting_proxy)
        await call.message.edit_caption(
            caption=(
                f"🚪 <b>{self.gate_name}</b>\n\n"
                "━━━━━━━━━━━━━━━━━━━━\n"
                "📋 <b>خطوات العمل:</b>\n"
                "1️⃣ البروكسي\n2️⃣ الكوكيز\n3️⃣ Account ID\n"
                "4️⃣ Page ID\n5️⃣ اختيار البوست\n"
                "6️⃣ الهدف + الأوديانس\n7️⃣ الميزانية والأيام\n8️⃣ مراجعة وتشغيل\n\n"
                "━━━━━━━━━━━━━━━━━━━━\n"
                "🔽 <b>الخطوة 1:</b> اختر البروكسي"
            ),
            reply_markup=proxy_selection_keyboard()
        )

    async def handle_proxy_auto(self, call: CallbackQuery, state: FSMContext, proxy: str = None):
        if not proxy:
            await call.answer("⚠️ لا توجد بروكسيات متاحة في القائمة", show_alert=True)
            return
        await state.update_data(proxy=proxy)
        await state.set_state(AdGateStates.waiting_cookies)
        await call.message.edit_caption(
            caption=(
                "✅ <b>البروكسي:</b> تم اختيار بروكسي من البوت تلقائياً\n\n"
                "━━━━━━━━━━━━━━━━━━━━\n"
                "🔽 <b>الخطوة 2:</b> أرسل كوكيز فيسبوك\n\n"
                "📌 افتح فيسبوك في المتصفح وانسخ الكوكيز من Developer Tools"
            ),
            reply_markup=back_to_proxy()
        )

    async def handle_proxy_skip(self, call: CallbackQuery, state: FSMContext):
        await state.update_data(proxy=None)
        await state.set_state(AdGateStates.waiting_cookies)
        await call.message.edit_caption(
            caption=(
                "✅ <b>تم تخطي البروكسي</b>\n\n"
                "━━━━━━━━━━━━━━━━━━━━\n"
                "🔽 <b>الخطوة 2:</b> أرسل كوكيز فيسبوك"
            ),
            reply_markup=back_to_proxy()
        )

    async def handle_proxy_custom(self, message: Message, state: FSMContext):
        is_valid, error = self.validate_proxy(message.text)
        if not is_valid:
            await reply_ui(message.bot, state, message.chat.id, error, back_home())
            return
        proxy = message.text.strip() if message.text.strip().lower() != 'skip' else None
        await state.update_data(proxy=proxy)
        await state.set_state(AdGateStates.waiting_cookies)
        await reply_ui(
            message.bot, state, message.chat.id,
            f"✅ <b>البروكسي:</b> {proxy or 'بدون'}\n\n"
            "━━━━━━━━━━━━━━━━━━━━\n"
            "🔽 <b>الخطوة 2:</b> أرسل كوكيز فيسبوك",
            back_to_proxy()
        )

    async def handle_proxy_back(self, call: CallbackQuery, state: FSMContext):
        await state.set_state(AdGateStates.waiting_proxy)
        await call.message.edit_caption(
            caption="🔽 <b>اختر البروكسي</b>",
            reply_markup=proxy_selection_keyboard()
        )

    async def handle_cookies(self, message: Message, state: FSMContext):
        is_valid, error = self.validate_cookies(message.text)
        if not is_valid:
            await reply_ui(message.bot, state, message.chat.id, error, back_home())
            return
        await state.update_data(cookies=message.text.strip())
        await state.set_state(AdGateStates.waiting_ad_account_id)
        await reply_ui(
            message.bot, state, message.chat.id,
            "✅ <b>تم حفظ الكوكيز</b>\n\n"
            "━━━━━━━━━━━━━━━━━━━━\n"
            "🔽 <b>الخطوة 3:</b> أدخل Ad Account ID\n"
            "(أرقام فقط - مثال: 1234567890123)",
            back_home()
        )

    async def handle_ad_account_id(self, message: Message, state: FSMContext):
        is_valid, result = self.validate_ad_account_id(message.text)
        if not is_valid:
            await reply_ui(message.bot, state, message.chat.id, result, back_home())
            return
        await state.update_data(ad_account_id=result)
        await state.set_state(AdGateStates.waiting_page_id)
        await reply_ui(
            message.bot, state, message.chat.id,
            f"✅ <b>Account ID:</b> {result}\n\n"
            "━━━━━━━━━━━━━━━━━━━━\n"
            "🔽 <b>الخطوة 4:</b> أدخل Page ID\n"
            "(معرف صفحتك على فيسبوك - أرقام فقط)",
            back_home()
        )

    async def handle_page_id(self, message: Message, state: FSMContext):
        is_valid, result = self.validate_page_id(message.text)
        if not is_valid:
            await reply_ui(message.bot, state, message.chat.id, result, back_home())
            return
        await state.update_data(page_id=result)
        await state.set_state(AdGateStates.waiting_post_select)

        await reply_ui(
            message.bot, state, message.chat.id,
            f"✅ <b>Page ID:</b> {result}\n\n⏳ جاري جلب بوستات الصفحة..."
        )
        try:
            data = await state.get_data()
            resp  = await fetch_page_posts(data['cookies'], result, data.get('proxy'))
            posts = resp.get('posts', [])
            if posts:
                await reply_ui(
                    message.bot, state, message.chat.id,
                    f"✅ <b>Page ID:</b> {result}\n\n"
                    "━━━━━━━━━━━━━━━━━━━━\n"
                    f"🔽 <b>الخطوة 5:</b> اختر البوست ({len(posts)} بوست)",
                    post_selection_keyboard(posts)
                )
                await state.update_data(fetched_posts=posts)
            else:
                await reply_ui(
                    message.bot, state, message.chat.id,
                    f"✅ <b>Page ID:</b> {result}\n\n"
                    "━━━━━━━━━━━━━━━━━━━━\n"
                    "⚠️ لم يُعثر على بوستات — أدخل رابط البوست أو معرفه يدوياً:",
                    back_home()
                )
                await state.set_state(AdGateStates.waiting_post_link)
        except Exception:
            await reply_ui(
                message.bot, state, message.chat.id,
                f"✅ <b>Page ID:</b> {result}\n\n"
                "━━━━━━━━━━━━━━━━━━━━\n"
                "🔽 <b>الخطوة 5:</b> أرسل رابط البوست أو معرفه (Post ID)\n\n"
                "📌 مثال: https://facebook.com/page/posts/123456\n"
                "📌 أو: 123456789012345",
                back_home()
            )
            await state.set_state(AdGateStates.waiting_post_link)

    async def handle_post_select(self, call: CallbackQuery, state: FSMContext):
        post_id = call.data.split(':', 1)[1]
        if post_id == 'manual':
            await state.set_state(AdGateStates.waiting_post_link)
            await call.message.edit_caption(
                caption=(
                    "✏️ <b>إدخال يدوي</b>\n\n"
                    "🔽 أرسل رابط البوست أو معرفه (Post ID):\n\n"
                    "📌 مثال: https://facebook.com/page/posts/123456\n"
                    "📌 أو: 123456789012345"
                ),
                reply_markup=back_home()
            )
            await call.answer()
            return

        data = await state.get_data()
        posts = data.get('fetched_posts', [])
        chosen = next((p for p in posts if p.get('id') == post_id), None)
        preview = ''
        if chosen:
            txt = chosen.get('message') or chosen.get('story') or ''
            preview = f"\n📝 {txt[:80]}..." if txt else ''

        await state.update_data(post_id=post_id, post_link=f"https://facebook.com/posts/{post_id}")
        await state.set_state(AdGateStates.waiting_objective)
        await call.message.edit_caption(
            caption=(
                f"✅ <b>Post ID:</b> <code>{post_id}</code>{preview}\n\n"
                "━━━━━━━━━━━━━━━━━━━━\n"
                "🔽 <b>الخطوة 6:</b> اختر هدف الإعلان"
            ),
            reply_markup=objective_selection_keyboard()
        )
        await call.answer()

    async def handle_post_link(self, message: Message, state: FSMContext):
        text = message.text.strip()
        is_valid, error = self.validate_post_link(text)
        if not is_valid:
            await reply_ui(message.bot, state, message.chat.id, error, back_home())
            return
        post_id = self.extract_post_id(text)
        link = text if 'facebook.com' in text else f"https://facebook.com/posts/{post_id}"
        await state.update_data(post_link=link, post_id=post_id)
        await state.set_state(AdGateStates.waiting_objective)
        await reply_ui(
            message.bot, state, message.chat.id,
            f"✅ <b>Post ID:</b> <code>{post_id}</code>\n\n"
            "━━━━━━━━━━━━━━━━━━━━\n"
            "🔽 <b>الخطوة 6:</b> اختر هدف الإعلان",
            objective_selection_keyboard()
        )

    async def handle_objective(self, call: CallbackQuery, state: FSMContext):
        objective = call.data.split(':', 1)[1]
        await state.update_data(objective=objective)
        await state.set_state(AdGateStates.waiting_audience_id)
        await call.message.edit_caption(
            caption=(
                f"✅ <b>الهدف:</b> {AdObjectives.get_display_name(objective)}\n\n"
                "━━━━━━━━━━━━━━━━━━━━\n"
                "🔽 <b>الخطوة 7:</b> أدخل Audience ID\n"
                "(اختياري — اكتب skip للتخطي)"
            ),
            reply_markup=back_home()
        )
        await call.answer()

    async def handle_audience_id(self, message: Message, state: FSMContext):
        is_valid, result = self.validate_audience_id(message.text)
        if not is_valid:
            await reply_ui(message.bot, state, message.chat.id, result, back_home())
            return
        await state.update_data(audience_id=result)
        await state.set_state(AdGateStates.waiting_daily_budget)
        await reply_ui(
            message.bot, state, message.chat.id,
            f"✅ <b>Audience ID:</b> {result or 'افتراضي'}\n\n"
            "━━━━━━━━━━━━━━━━━━━━\n"
            f"🔽 <b>الخطوة 8:</b> أدخل الميزانية اليومية (USD)\n"
            f"(الافتراضي: {GateConstants.DEFAULT_BUDGET}$ — اكتب skip للتخطي)",
            back_home()
        )

    async def handle_daily_budget(self, message: Message, state: FSMContext):
        is_valid, result = self.validate_budget(message.text)
        if not is_valid:
            await reply_ui(message.bot, state, message.chat.id, result, back_home())
            return
        await state.update_data(daily_budget=result)
        await state.set_state(AdGateStates.waiting_days)
        await reply_ui(
            message.bot, state, message.chat.id,
            f"✅ <b>الميزانية:</b> {result}$\n\n"
            "━━━━━━━━━━━━━━━━━━━━\n"
            f"🔽 <b>الخطوة 9:</b> أدخل عدد الأيام\n"
            f"(الافتراضي: {GateConstants.DEFAULT_DAYS} — اكتب skip للتخطي)",
            back_home()
        )

    async def handle_days(self, message: Message, state: FSMContext):
        is_valid, result = self.validate_days(message.text)
        if not is_valid:
            await reply_ui(message.bot, state, message.chat.id, result, back_home())
            return
        await state.update_data(days=result)
        await state.set_state(AdGateStates.waiting_confirm)
        data = await state.get_data()
        await reply_ui(message.bot, state, message.chat.id, self.format_summary(data), confirm_keyboard())

    async def handle_confirm(self, call: CallbackQuery, state: FSMContext):
        if call.data == 'confirm:yes':
            await state.set_state(AdGateStates.waiting_activate)
            await call.message.edit_caption(
                caption=(
                    "🚀 <b>جاهز للتشغيل!</b>\n\n"
                    "━━━━━━━━━━━━━━━━━━━━\n"
                    "اختر طريقة النشر:"
                ),
                reply_markup=activate_or_back_keyboard()
            )
        else:
            await clear_keep(state)
            await call.message.edit_caption(caption="❌ <b>تم إلغاء العملية</b>", reply_markup=back_home())
        await call.answer()

    async def handle_activate(self, call: CallbackQuery, state: FSMContext):
        data   = await state.get_data()
        action = call.data

        if action not in ('activate:run', 'activate:run_pause'):
            await clear_keep(state)
            await call.message.edit_caption(caption="🏠 <b>تم الإلغاء</b>", reply_markup=back_home())
            await call.answer()
            return

        pause = action == 'activate:run_pause'
        label = "⏸ نشر ثم إيقاف" if pause else "🟢 نشر نشط"

        await call.message.edit_caption(
            caption=(
                f"⏳ <b>جاري إنشاء الإعلان... ({label})</b>\n\n"
                "🔄 الخطوة 1/4: إنشاء الحملة\nيرجى الانتظار..."
            )
        )
        try:
            fn     = run_standard_ad_then_pause if pause else run_standard_ad
            result = await fn(data)
            if result['success']:
                await call.message.edit_caption(
                    caption=_result_text(result, self.gate_name),
                    reply_markup=back_home()
                )
            else:
                await call.message.edit_caption(
                    caption=(
                        f"❌ <b>فشل في خطوة: {result.get('step', '?')}</b>\n\n"
                        f"🔴 {result.get('error', 'خطأ غير معروف')}"
                    ),
                    reply_markup=back_home()
                )
        except Exception as e:
            await call.message.edit_caption(caption=f"❌ <b>خطأ:</b>\n{e}", reply_markup=back_home())
        await call.answer()
