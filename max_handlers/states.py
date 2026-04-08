from maxapi.context import State, StatesGroup


class TarotState(StatesGroup):
    waiting_question = State()
