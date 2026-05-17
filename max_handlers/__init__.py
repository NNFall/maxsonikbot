from .admin import router as admin_router
from .dream import router as dream_router
from .payments import router as payments_router
from .start import router as start_router

all_routers = [
    start_router,
    payments_router,
    admin_router,
    dream_router,
]
