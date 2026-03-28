import base64
import io
import secrets
from datetime import datetime, timezone
from functools import wraps

import pyotp
import qrcode
import qrcode.image.svg
from flask import abort, current_app, g, redirect, request, session, url_for


ROLE_LABELS = {
    "admin": "Admin",
    "dispatcher": "Dispatcher",
    "viewer": "Viewer",
}


def generate_csrf_token():
    token = session.get("csrf_token")
    if not token:
        token = secrets.token_urlsafe(32)
        session["csrf_token"] = token
    return token


def validate_csrf_token():
    form_token = request.form.get("csrf_token", "")
    session_token = session.get("csrf_token", "")
    if not session_token or not secrets.compare_digest(form_token, session_token):
        abort(400, description="Invalid CSRF token.")


def generate_totp_secret():
    return pyotp.random_base32()


def build_totp_uri(email, secret):
    issuer = current_app.config["TMS_OTP_ISSUER"]
    return pyotp.TOTP(secret).provisioning_uri(name=email, issuer_name=issuer)


def build_totp_qr_data_uri(uri):
    image = qrcode.make(uri, image_factory=qrcode.image.svg.SvgImage)
    buffer = io.BytesIO()
    image.save(buffer)
    encoded = base64.b64encode(buffer.getvalue()).decode("ascii")
    return f"data:image/svg+xml;base64,{encoded}"


def verify_totp_code(secret, code):
    if not secret or not code:
        return False
    token = code.replace(" ", "")
    return pyotp.TOTP(secret).verify(token, valid_window=1)


def complete_login(user, tenant=None):
    user_row = dict(user)
    session.clear()
    session["user_id"] = user_row["id"]
    session["tenant_id"] = user_row.get("tenant_id") or (tenant or {}).get("tenant_id")
    session["tenant_name"] = (tenant or {}).get("company_name", "")
    session["user_role"] = user_row["role"]
    session["user_email"] = user_row["email"]
    session["user_name"] = user_row["full_name"]
    session["session_last_activity_at"] = datetime.now(timezone.utc).isoformat()


def clear_login_state():
    session.clear()


def login_required(view_func):
    @wraps(view_func)
    def wrapped(*args, **kwargs):
        if not getattr(g, "current_user", None):
            return redirect(url_for("login"))
        return view_func(*args, **kwargs)

    return wrapped


def roles_required(*allowed_roles):
    def decorator(view_func):
        @wraps(view_func)
        def wrapped(*args, **kwargs):
            if not getattr(g, "current_user", None):
                return redirect(url_for("login"))
            if g.current_user["role"] not in allowed_roles:
                readable_roles = ", ".join(ROLE_LABELS[role] for role in allowed_roles)
                abort(403, description=f"{readable_roles} access required.")
            return view_func(*args, **kwargs)

        return wrapped

    return decorator


def require_allowed_host():
    allowed_hosts = current_app.config["ALLOWED_HOSTS"]
    if not allowed_hosts:
        return
    request_host = request.host.split(":", 1)[0].lower()
    if request_host not in allowed_hosts:
        abort(400, description="Host header is not allowed.")
