from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.auth import router as auth_router
from app.api.course_files import router as course_files_router
from app.api.datasets import router as datasets_router
from app.api.training import router as training_router
from app.api.users import router as users_router
from app.core import settings
from app.core.db import init_db
from app.core.pool import close_pool

app = FastAPI(title="DataDNA API")

# allow_credentials is needed so the browser sends the refresh cookie. Origins must be listed
# explicitly (no "*") for that to work. Set CORS_ORIGINS in .env to change them.
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins(),
    allow_credentials=True,
    allow_methods=["GET", "POST", "PATCH", "PUT", "DELETE", "OPTIONS"],
    allow_headers=["Authorization", "Content-Type"],
)


@app.middleware("http")
async def never_cache_account_data(request, call_next):
    """Tokens, temporary passwords and user lists must not be kept by browsers or proxies."""
    response = await call_next(request)
    if request.url.path.startswith(("/auth", "/users")):
        response.headers["Cache-Control"] = "no-store"
        response.headers["Pragma"] = "no-cache"
    return response


@app.on_event("startup")
def startup():
    settings.startup_checks()  # stops the app with a clear message if JWT_SECRET etc. are wrong
    init_db()


@app.on_event("shutdown")
def shutdown():
    close_pool()


@app.get("/health")
def health():
    return {"status": "ok", "service": "datadna-api"}


app.include_router(auth_router)
app.include_router(users_router)
app.include_router(course_files_router)
app.include_router(datasets_router)
app.include_router(training_router)
