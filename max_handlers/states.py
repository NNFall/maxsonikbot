from maxapi.context import State, StatesGroup


class DreamState(StatesGroup):
    waiting_dream = State()


class TarotState(StatesGroup):
    waiting_question = State()
