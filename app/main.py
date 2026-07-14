from uuid import uuid4

from fastapi import FastAPI
from fastapi import Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.config import Settings
from app.errors import AppError


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or Settings()
    app = FastAPI()
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=False,
        allow_methods=["POST", "GET", "OPTIONS"],
        allow_headers=["Authorization", "Content-Type"],
    )

    @app.middleware("http")
    async def assign_request_id(request: Request, call_next):
        request.state.request_id = str(uuid4())
        return await call_next(request)

    @app.exception_handler(AppError)
    async def handle_app_error(request: Request, exc: AppError) -> JSONResponse:
        return JSONResponse(
            status_code=exc.status_code,
            content={
                "error": {
                    "code": exc.code,
                    "message": exc.message,
                    "request_id": request.state.request_id,
                }
            },
        )

    @app.get("/health")
    async def health() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/ready")
    async def ready():
        required_settings = {
            "SUPABASE_URL": settings.supabase_url,
            "SUPABASE_ANON_KEY": settings.supabase_anon_key,
            "GROQ_API_KEY": settings.groq_api_key,
        }
        missing = [name for name, value in required_settings.items() if not value]
        if missing:
            return JSONResponse(
                status_code=503,
                content={"status": "not_ready", "missing": missing},
            )
        return {"status": "ready"}

    return app


app = create_app()
