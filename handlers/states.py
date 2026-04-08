from aiogram.fsm.state import StatesGroup, State


class EffectState(StatesGroup):
    waiting_photo = State()


class CustomState(StatesGroup):
    waiting_photo_text = State()
    waiting_duration = State()


class PhotoEffectState(StatesGroup):
    waiting_photo = State()


class PhotoCustomState(StatesGroup):
    waiting_photo_text = State()


class PhotoTextState(StatesGroup):
    waiting_prompt = State()


class ConcatState(StatesGroup):
    waiting_video1 = State()
    waiting_video2 = State()


class CutState(StatesGroup):
    waiting_video = State()
    waiting_timecodes = State()


class AdminAddEffectState(StatesGroup):
    waiting_type = State()
    waiting_name = State()
    waiting_prompt = State()
    waiting_demo = State()


class TarotState(StatesGroup):
    waiting_question = State()
