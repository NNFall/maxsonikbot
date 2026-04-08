from .admin import router as admin_router
from .payments import router as payments_router
from .start import router as start_router
from .tarot import router as tarot_router

all_routers = [
    start_router,
    tarot_router,
    payments_router,
    admin_router,
]
