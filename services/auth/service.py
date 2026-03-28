"""
auth/service.py — Re-exports auth business logic from root modules.
Other services call these functions; routes.py uses them for HTTP endpoints.
"""
import sys, os
_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if _root not in sys.path:
    sys.path.insert(0, _root)

from auth import (
    register_user, login_user, setup_mfa, enable_mfa, disable_mfa,
    verify_mfa, request_password_reset, reset_password,
    set_session, clear_session, validate_session_token,
    change_password, list_users, set_user_role,
    check_mfa_enforced, is_user_mfa_enabled, is_admin, is_internal, is_customer, current_user,
)
from oauth import (
    google_enabled, microsoft_enabled,
    get_google_auth_url, handle_google_callback,
    get_microsoft_auth_url, handle_microsoft_callback,
    oauth_login_or_register,
)
from permissions import (
    feature_required, get_user_permissions, check_permission,
    set_permission, bulk_set_permissions, initialize_defaults,
    revoke_all, save_template, list_templates, FEATURES, ACTIONS,
)
from api_auth import (
    create_api_key, validate_api_key, revoke_api_key, list_api_keys,
)
