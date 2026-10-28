"""Read-only API над mart.*; подключение: `app.include_router(app.api.router)`."""

from app.api.routes import router

__all__ = ["router"]
