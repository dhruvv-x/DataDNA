from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.auth import router as auth_router
from app.api.course_files import router as course_files_router
from app.api.master import router as master_router
from app.api.rules import router as rules_router
from app.api.scores import router as scores_router
from app.api.submissions import router as submissions_router
from app.api.users import router as users_router
from app.core import scheduler, settings
from app.core.pool import close_pool

app = FastAPI(title="Faculty Compliance & Trust Engine API")

# allow_credentials is needed so the browser sends the refresh cookie. Origins must be listed
# explicitly (no "*") for that to work. Set CORS_ORIGINS in .env to change them.
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins(),
    allow_credentials=True,
    allow_methods=["GET", "POST", "PATCH", "PUT", "DELETE", "OPTIONS"],
    allow_headers=["Authorization", "Content-Type"],
    expose_headers=["Content-Disposition", "X-File-SHA256"],
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
    settings.startup_checks()  # stops the app with a clear message if JWT_SECRET, STORAGE_DIR etc. are wrong
    scheduler.start()          # automatic deadline check (RULES_SWEEP_MINUTES, 0 = off)


@app.on_event("shutdown")
def shutdown():
    scheduler.stop()
    close_pool()


@app.get("/health")
def health():
    return {"status": "ok", "service": "compliance-api"}


app.include_router(auth_router)
app.include_router(users_router)
app.include_router(master_router)
app.include_router(course_files_router)
app.include_router(submissions_router)
app.include_router(rules_router)
app.include_router(scores_router)
