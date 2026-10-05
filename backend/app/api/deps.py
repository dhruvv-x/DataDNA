"""
Shared FastAPI dependencies (S3): database connection and the logged-in user.

get_db gives each request one pooled connection and NEVER commits on its own.
A handler that changes data must call db.commit() itself. If it just returns or raises,
everything it did is rolled back. This is deliberate: a failed login must save its
"wrong password" counter and then still answer 401, so those handlers commit first.
"""
from fastapi import Depends, HTTPException
from fastapi.security import OAuth2PasswordBearer

from app.core import security
from app.core.pool import get_pool
from app.core.scope import CurrentUser

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="auth/login")


def get_db():
    try:
        pool = get_pool()
        cm = pool.connection()
        conn = cm.__enter__()
    except Exception as exc:  # pool timeout, database down, ...
        raise HTTPException(status_code=503, detail="Database is not available.") from exc
    try:
        yield conn
    finally:
        try:
            conn.rollback()
        finally:
            cm.__exit__(None, None, None)


def _unauthorized() -> HTTPException:
    return HTTPException(
        status_code=401,
        detail="Not authenticated.",
        headers={"WWW-Authenticate": "Bearer"},
    )


def current_user_any(token: str = Depends(oauth2_scheme), db=Depends(get_db)) -> CurrentUser:
    """The logged-in user, even if they still must change a temporary password."""
    try:
        claims = security.decode_access_token(token)
    except security.TokenError:
        raise _unauthorized()
    # The role and active flag come from the database on every request, never from the token.
    row = db.execute(
        """
        SELECT id, email, full_name, role, department_id, is_active,
               must_change_password, password_changed_at
        FROM users WHERE id = %s
        """,
        (claims["sub"],),
    ).fetchone()
    if row is None or not row["is_active"]:
        raise _unauthorized()
    if security.password_version(row["password_changed_at"]) != claims["pv"]:
        raise _unauthorized()  # password was changed or reset after this token was issued
    return CurrentUser(
        id=row["id"],
        email=row["email"],
        full_name=row["full_name"],
        role=row["role"],
        department_id=row["department_id"],
        must_change_password=row["must_change_password"],
    )


def current_user(user: CurrentUser = Depends(current_user_any)) -> CurrentUser:
    """The logged-in user. Blocked until a temporary password has been changed."""
    if user.must_change_password:
        raise HTTPException(status_code=403, detail="Password change required.")
    return user
