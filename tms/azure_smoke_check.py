import argparse
import re
import sys
from urllib.parse import urljoin, urlparse

import requests


def _assert(condition, message):
    if not condition:
        raise AssertionError(message)


def _get_csrf_token(html_text):
    match = re.search(r'name="csrf_token"\s+value="([^"]+)"', html_text)
    return match.group(1) if match else ""


def _request(session, method, base_url, path, **kwargs):
    return session.request(method, urljoin(base_url.rstrip("/") + "/", path.lstrip("/")), timeout=20, **kwargs)


def _assert_security_headers(response, *, expect_hsts):
    headers = response.headers
    _assert(headers.get("X-Frame-Options") == "DENY", "missing X-Frame-Options=DENY")
    _assert(headers.get("X-Content-Type-Options") == "nosniff", "missing X-Content-Type-Options=nosniff")
    _assert(
        headers.get("Referrer-Policy") == "strict-origin-when-cross-origin",
        "missing Referrer-Policy=strict-origin-when-cross-origin",
    )
    _assert("Content-Security-Policy" in headers, "missing Content-Security-Policy header")
    csp = headers.get("Content-Security-Policy", "")
    _assert("frame-ancestors 'none'" in csp, "Content-Security-Policy missing frame-ancestors 'none'")
    _assert("form-action 'self'" in csp, "Content-Security-Policy missing form-action 'self'")
    if expect_hsts:
        _assert(
            "Strict-Transport-Security" in headers,
            "missing Strict-Transport-Security header on HTTPS deployment",
        )


def run_smoke_check(base_url):
    session = requests.Session()
    results = []
    parsed = urlparse(base_url)
    expect_hsts = parsed.scheme == "https"

    health = _request(session, "GET", base_url, "/health")
    _assert(health.status_code == 200, f"/health expected 200, got {health.status_code}")
    payload = health.json()
    _assert(payload.get("status") == "ok", "/health did not return status=ok")
    _assert_security_headers(health, expect_hsts=expect_hsts)
    results.append("health ok")

    static_asset = _request(session, "GET", base_url, "/static/bootstrap.min.css")
    _assert(static_asset.status_code == 200, f"/static/bootstrap.min.css expected 200, got {static_asset.status_code}")
    results.append("static assets ok")

    login = _request(session, "GET", base_url, "/login")
    _assert(login.status_code == 200, f"/login expected 200, got {login.status_code}")
    login_csrf = _get_csrf_token(login.text)
    _assert(login_csrf, "/login did not include csrf token")
    _assert_security_headers(login, expect_hsts=expect_hsts)
    results.append("login csrf ok")

    portal_login = _request(session, "GET", base_url, "/portal/login")
    _assert(portal_login.status_code == 200, f"/portal/login expected 200, got {portal_login.status_code}")
    portal_csrf = _get_csrf_token(portal_login.text)
    _assert(portal_csrf, "/portal/login did not include csrf token")
    _assert_security_headers(portal_login, expect_hsts=expect_hsts)
    results.append("portal csrf ok")

    tracking_ping = _request(
        session,
        "POST",
        base_url,
        "/tms/track/ping",
        data={"shipment_ref": "TEST", "lat": "1", "lng": "1"},
    )
    _assert(tracking_ping.status_code == 403, f"/tms/track/ping expected 403 without token, got {tracking_ping.status_code}")
    results.append("tracking write locked")

    public_tracking = _request(session, "GET", base_url, "/track/TMS-DEMO-003", allow_redirects=False)
    _assert(public_tracking.status_code == 403, f"/track/<ref> expected 403 without signed token, got {public_tracking.status_code}")
    results.append("public tracking locked")

    unauth_api_docs = _request(session, "GET", base_url, "/tms/api-docs", allow_redirects=False)
    _assert(unauth_api_docs.status_code in {301, 302}, f"/tms/api-docs expected redirect, got {unauth_api_docs.status_code}")
    _assert("/login" in unauth_api_docs.headers.get("Location", ""), "/tms/api-docs did not redirect to /login")
    results.append("auth gate ok")

    tracking_search = _request(session, "GET", base_url, "/tms/track", allow_redirects=False)
    _assert(tracking_search.status_code in {301, 302}, f"/tms/track expected redirect, got {tracking_search.status_code}")
    _assert("/login" in tracking_search.headers.get("Location", ""), "/tms/track did not redirect to /login")
    results.append("tracking search gated")

    bad_portal_post = _request(
        requests.Session(),
        "POST",
        base_url,
        "/portal/login",
        data={"access_code": "000000"},
        allow_redirects=False,
    )
    _assert(bad_portal_post.status_code == 400, f"/portal/login without csrf expected 400, got {bad_portal_post.status_code}")
    results.append("portal csrf enforced")

    portal_logout_get = _request(session, "GET", base_url, "/portal/logout", allow_redirects=False)
    _assert(portal_logout_get.status_code == 405, f"/portal/logout GET expected 405, got {portal_logout_get.status_code}")
    results.append("portal logout locked")

    office_logout_get = _request(session, "GET", base_url, "/logout", allow_redirects=False)
    _assert(office_logout_get.status_code == 405, f"/logout GET expected 405, got {office_logout_get.status_code}")
    results.append("office logout locked")

    bad_logout_post = _request(
        requests.Session(),
        "POST",
        base_url,
        "/logout",
        data={},
        allow_redirects=False,
    )
    _assert(bad_logout_post.status_code == 400, f"/logout without csrf expected 400, got {bad_logout_post.status_code}")
    results.append("office logout csrf enforced")

    _assert(parsed.scheme == "https", "base url must be https")
    results.append("https url")

    return results


def main():
    parser = argparse.ArgumentParser(description="Run Azure smoke checks against the hardened TMS deployment.")
    parser.add_argument("base_url", help="HTTPS base URL, for example https://your-app.azurewebsites.net")
    args = parser.parse_args()

    try:
        results = run_smoke_check(args.base_url)
    except Exception as exc:
        print(f"FAIL: {exc}")
        return 1

    for item in results:
        print(f"OK: {item}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
