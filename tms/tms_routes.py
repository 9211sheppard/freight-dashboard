from datetime import date, datetime
import csv
import hashlib
import json
import os
import re
import secrets
import time
from functools import wraps
from datetime import timedelta
from math import ceil

from flask import Blueprint, Response, abort, current_app, flash, g, jsonify, make_response, redirect, render_template, request, session, send_from_directory, url_for
import io
from rate_limiter import RateLimiter
from itsdangerous import BadData, URLSafeTimedSerializer
from werkzeug.utils import secure_filename

from . import edi as edi_module, freight_audit
from .notifications import (
    ensure_notification_scheduler,
    get_imap_config,
    get_notification_log,
    get_smtp_config,
    notify_invoice_generated,
    notify_pod_received,
    notify_shipment_created,
    notify_shipment_status_change,
    smtp_configured,
)
from .rate_reply_parser import get_gap_report, get_parse_log, process_pending_replies
from .tms_db import get_email_settings, save_email_settings
from .load_board import (get_all_providers as lb_get_providers, post_load as lb_post_load,
                          delete_posting as lb_delete_posting, get_active_postings,
                          get_board_settings, save_board_settings)
from .cold_chain import (
    configure_shipment,
    get_cold_chain_dashboard,
    get_excursions as get_cold_chain_excursions,
    get_readings as get_cold_chain_readings,
    get_shipment_config,
    ingest_reading,
)
from .accounting import (get_all_providers as acct_get_providers, push_invoice,
                          pull_payments, test_connection as acct_test,
                          get_accounting_settings, save_accounting_settings,
                          get_sync_log)
from .hos import (
    DUTY_STATUS_CHOICES as HOS_DUTY_STATUS_CHOICES,
    MAX_CYCLE_HOURS_8DAY,
    MAX_DRIVING_HOURS,
    MAX_ON_DUTY_HOURS,
    REQUIRED_OFF_HOURS,
    add_log_entry as add_hos_log_entry,
    get_driver_logs as get_hos_driver_logs,
    get_driver_summary as get_hos_driver_summary,
    get_hos_dashboard,
)
from .forecasting import get_forecast_dashboard, get_lane_forecast
from .spot_quotes import (
    award_quote as award_spot_quote,
    blast_carriers as blast_spot_quote_carriers,
    create_quote as create_spot_quote,
    get_quote_detail as get_spot_quote_detail,
    get_quotes as get_spot_quotes,
)
from .tms_db import (
    CARBON_FRAMEWORK_LABEL,
    CARBON_MODE_LABELS,
    CLAIM_STATUSES,
    CLAIM_TYPES,
    CUSTOMS_STATUSES,
    HS_CODE_HINTS,
    INCOTERMS,
    check_compliance_flags,
    estimate_duty,
    get_customs_dashboard_context,
    get_customs_record,
    upsert_customs_record,
    DOCK_APPOINTMENT_STATUSES,
    DOCK_APPOINTMENT_TYPES,
    DOCK_TYPES,
    DRIVER_STATUS_OPTIONS,
    DUTY_STATUS_OPTIONS,
    EDI_PARTNER_DIRECTIONS,
    EDI_PARTNER_FORMATS,
    EQUIPMENT_TYPES,
    LOAD_STATUSES,
    POD_UPLOAD_DIR,
    VEHICLE_STATUS_OPTIONS,
    add_load_stop,
    add_shipment_to_load,
    approve_stop_deviation,
    backfill_shipment_co2,
    convert_load_to_ftl,
    create_ltl_load,
    get_all_loads_context,
    get_load_builder_context,
    get_load_messages,
    release_load_to_accounting,
    remove_shipment_from_load,
    reorder_load_stops,
    send_load_message,
    build_dock_calendar,
    calculate_shipment_co2_details,
    create_api_key,
    create_edi_transaction,
    create_customer_shipment,
    create_freight_claim,
    create_intake_document,
    create_tenant,
    create_portal_quote_request,
    create_portal_shipment_request,
    create_shipment_from_intake,
    create_load,
    delete_carrier,
    delete_contract_rate,
    delete_driver,
    delete_edi_partner,
    delete_vehicle,
    find_best_contract_rate,
    find_recent_edi_partner_for_shipment,
    find_shipment_by_ref,
    generate_ref,
    get_api_key,
    get_carrier,
    get_carrier_with_history,
    get_edi_partner,
    get_edi_transaction,
    get_contract_rate,
    get_control_tower_context,
    get_customer_shipment_snapshot,
    get_dock,
    get_dock_appointment,
    get_db,
    get_intake_document,
    get_driver,
    get_driver_checkin_context,
    get_driver_with_history,
    get_freight_claim,
    get_load_snapshot,
    get_or_create_dock_booking_token,
    get_or_create_pod_token,
    get_portal_dashboard_context,
    get_portal_quote_request,
    get_portal_shipment_snapshot,
    get_portal_token,
    get_or_create_tracking_driver_token,
    get_pod_record,
    get_setup_state,
    get_shipment_snapshot,
    get_tenant,
    get_driver_tracking_context,
    get_tracking_page_context,
    get_vehicle,
    get_vehicle_with_history,
    import_carriers_from_contacts_db,
    init_tms_db,
    list_audit_log,
    list_api_keys,
    list_available_dock_slots,
    list_available_load_shipments,
    list_carriers,
    list_contract_rates,
    list_dock_appointments,
    list_docks,
    list_drivers,
    list_documents,
    list_edi_partners,
    list_edi_transactions,
    list_intake_documents,
    list_freight_claim_filter_carriers,
    list_freight_claims,
    list_loads,
    list_portal_quote_requests,
    list_tenants,
    list_vehicles,
    list_customer_shipments,
    list_shipment_refs,
    lookup_api_rate,
    revoke_api_key,
    resolve_portal_login,
    refresh_customer_invoice_statuses,
    refresh_carrier_safety,
    refresh_shipment_carbon,
    quote_portal_quote_request,
    save_carrier,
    save_contract_rate,
    save_dock,
    save_dock_appointment,
    save_driver,
    save_edi_partner,
    save_document_record,
    save_duty_log,
    save_pod_record,
    save_tracking_ping,
    save_setup,
    save_vehicle,
    normalize_carbon_mode,
    submit_driver_checkin,
    touch_tracking_driver_token,
    touch_api_key_last_used,
    respond_to_freight_claim,
    _distance_km,
    _lookup_location_coordinates,
    update_intake_document,
    update_dock_appointment_status,
    update_freight_claim,
    update_load_status,
    update_tenant_status,
    add_shipment_leg,
    get_shipment_legs,
    update_leg_status,
    delete_shipment_leg,
    reorder_shipment_legs,
    LEG_MODES,
    LEG_STATUSES,
    STOP_TYPES,
    ROUTE_STATUSES,
    create_route_plan,
    get_route_plan,
    get_all_route_plans,
    add_route_stop,
    reorder_stops,
    delete_route_stop,
    update_stop_status,
    assign_driver_to_route,
    LTL_STATUSES,
    LTL_EQUIPMENT_TYPES,
    ltl_get_all,
    ltl_get,
    ltl_create,
    ltl_add_shipment,
    ltl_remove_shipment,
    ltl_convert_to_ftl,
    ltl_fill_stats,
    send_message_to_driver,
    get_driver_messages,
    driver_reply,
    get_unread_message_count,
    save_pod_submission,
    get_pod_submissions,
    route_pod_to_billing,
    get_billing_queue,
    mark_billed,
    pod_image_to_pdf,
    PIPELINE_STAGES,
    SERVICE_TYPES,
    EQUIPMENT_TYPES_ORDER,
    submit_customer_order,
    get_all_customer_orders,
    get_pipeline_counts,
    get_pipeline_orders,
    advance_order_stage,
    get_customer_order,
)
from .carrier_scorecard import (get_all_scorecards, log_carrier_performance,
                                 get_best_carrier_for_lane, get_carrier_history,
                                 get_scorecard_stats)
from .rate_matrix import (get_all_matrices, get_matrix, create_matrix,
                          add_rate_entry, lookup_rate, delete_rate_entry)
from .scenarios import get_saved_scenarios, run_scenario, save_scenario
from .tenanting import DEFAULT_TENANT_ID, disabled_tenant_scope, tenant_context
from .auto_invoice import (get_all_invoices, get_invoice, create_auto_invoice,
                            mark_invoice_sent, mark_invoice_paid, get_invoice_stats)
from .fuel_surcharge import (get_fsc_history, get_fsc_brackets, log_doe_price,
                              get_current_fsc_pct, calculate_fsc_for_shipment,
                              get_latest_doe_price)
from .ifta import (add_fuel_purchase, add_mileage_log, get_quarterly_summary,
                   get_all_quarters, get_fuel_purchases, get_mileage_logs,
                   get_current_quarter, FUEL_TYPES)
from .tms_intake import INTAKE_FIELD_ORDER, extract_intake_payload
from .dg_hazmat import (init_dg_db, search_un, get_un, create_declaration,
                         validate_declaration, get_declarations, get_dg_dashboard, HAZMAT_CLASSES)
from .dvir import (create_dvir, certify_dvir, get_dvir_reports, get_fleet_health_dashboard,
                   create_maintenance_schedule, get_work_orders, close_work_order,
                   get_maintenance_due, INSPECTION_ITEMS, MAINTENANCE_TYPES)
from .workflow_engine import (get_workflow_dashboard, create_rule, toggle_rule, delete_rule,
                               fire_trigger, run_scheduled_checks, TRIGGERS, CONDITIONS, ACTIONS)
from .white_label import get_branding, save_branding, get_css_vars
from .tms_ocr import DOCUMENT_TYPE_CHOICES, extract_document_payload
from .doc_ocr import process_ocr_upload, get_ocr_job, mark_ocr_applied, get_ocr_history
from .load_matcher import get_match_suggestions, auto_assign_driver, get_load_board_summary
from .eld import get_eld_connections, sync_eld_provider, ELD_PROVIDERS
from .market_rates import get_market_rate_estimate, compare_to_market, BASE_REGION_RATES
from .ai_insights import get_ai_dashboard, predict_eta, score_lane, get_late_risk, get_top_lanes, score_carrier
from .benchmarking import benchmark_lane, get_benchmark_dashboard, get_carrier_rate_comparison
from .live_map import (get_live_shipments, get_shipment_trail, get_map_summary,
                       get_geofences, create_geofence, delete_geofence,
                       get_geofence_events, ingest_ping)
from .driver_pay import (get_pay_structure, save_pay_structure, calculate_settlement,
                         create_settlement, approve_settlement, mark_paid,
                         get_settlements, get_settlement)
from .accessorials import (get_accessorial_dashboard, add_charge, get_charges,
                            get_charges_summary, approve_charge, delete_charge,
                            get_all_pending_charges, start_detention_timer,
                            stop_detention_timer, get_active_timers, ACCESSORIAL_TYPES)
from .wms import (
    create_pick as create_wms_pick,
    create_receipt as create_wms_receipt,
    get_inventory_by_location as get_wms_inventory_by_location,
    get_inventory_by_sku as get_wms_inventory_by_sku,
    get_location_utilization as get_wms_location_utilization,
    get_pick as get_wms_pick,
    get_receipt as get_wms_receipt,
    get_wms_dashboard,
    list_inventory as list_wms_inventory,
    list_locations as list_wms_locations,
    list_picks as list_wms_picks,
    list_receipts as list_wms_receipts,
    pick_line as update_wms_pick_line,
    receive_line as update_wms_receipt_line,
)
from .marketplace import (
    add_review as marketplace_add_review,
    get_carrier_profile,
    get_featured_carriers,
    get_marketplace_equipment_options,
    get_marketplace_state_options,
    request_connection as marketplace_request_connection,
    search_carriers,
)
from .soc2 import (get_audit_log, get_security_incidents, get_privacy_requests,
                   submit_privacy_request, get_soc2_summary, run_health_check,
                   audit, record_login_attempt, is_ip_locked)
from .subscriptions import (get_all_saas_tenants, get_saas_tenant, get_all_plans,
                             get_platform_revenue_summary, create_saas_tenant,
                             add_tenant_addon, remove_tenant_addon, suspend_saas_tenant,
                             activate_saas_tenant, get_tenant_addons, tenant_has_addon,
                             get_tenant_monthly_total)
from .global_trade import (
    get_compliance_history,
    get_trade_settings,
    run_compliance_check,
    search_hs_codes,
)
try:
    from .tms_docs import generate_awb, generate_bol, generate_customer_invoice, generate_invoice, generate_packing_list, generate_pod
    _tms_docs_error = None
except Exception as exc:
    generate_awb = None
    generate_bol = None
    generate_customer_invoice = None
    generate_invoice = None
    generate_packing_list = None
    generate_pod = None
    _tms_docs_error = exc

SUPPORTED_TRANSACTION_TYPES = edi_module.SUPPORTED_TRANSACTION_TYPES
detect_edi_format = edi_module.detect_edi_format
get_edi_inbox_path = edi_module.get_edi_inbox_path
generate_204 = getattr(edi_module, "generate_204", None)
generate_214 = getattr(edi_module, "generate_214", None)
generate_215 = getattr(edi_module, "generate_215", None)
generate_856 = getattr(edi_module, "generate_856", None)
generate_990 = getattr(edi_module, "generate_990", None)
generate_997 = getattr(edi_module, "generate_997", None)
generate_iftsta = getattr(edi_module, "generate_iftsta", None)
process_inbound_edi_payload = edi_module.process_inbound_edi_payload
start_edi_inbox_watcher = edi_module.start_edi_inbox_watcher


def _auto_start_edi_inbox_watcher():
    enabled = os.getenv("TMS_ENABLE_EDI_WATCHER", "").strip().lower()
    if enabled in {"1", "true", "yes", "on"}:
        start_edi_inbox_watcher()


_auto_start_edi_inbox_watcher()

tms = Blueprint("tms", __name__, url_prefix="/tms", template_folder="../templates")
portal = Blueprint("portal", __name__, url_prefix="/portal", template_folder="../templates")
public = Blueprint("public", __name__, template_folder="../templates")

LEGACY_PUBLIC_TMS_ENDPOINTS = {
    "tms.capture_pod",
    "tms.carrier_dock_booking",
    "tms.cold_chain_reading",
    "tms.customer_track",
    "tms.customer_track_search",
    "tms.driver_checkin",
    "tms.driver_message_reply",
    "tms.driver_tracking_page",
    "tms.fuel_surcharge_calc",
    "tms.order_submit",
    "tms.pod_photo",
    "tms.pod_submission",
    "tms.pricing_page",
    "tms.privacy_request_submit",
    "tms.respond_to_tender",
    "tms.tracking_ping",
}


def _truthy(value, default=False):
    if value is None:
        return default
    return str(value).strip().lower() in {"1", "true", "yes", "on"}


def _legacy_runtime_config(name, env_name):
    try:
        configured = current_app.config.get(name)
    except RuntimeError:
        configured = None
    if configured is not None:
        return configured
    return os.getenv(env_name)


def _legacy_production_mode():
    env_value = _legacy_runtime_config("TMS_ENV", "TMS_ENV") or "development"
    return str(env_value).strip().lower() == "production"


def _legacy_route_auth_enabled():
    configured = _legacy_runtime_config("TMS_ENFORCE_ROUTE_AUTH", "TMS_ENFORCE_ROUTE_AUTH")
    return _truthy(configured, default=True)


def _allow_request_tenant_override():
    configured = _legacy_runtime_config(
        "TMS_ALLOW_REQUEST_TENANT_OVERRIDE",
        "TMS_ALLOW_REQUEST_TENANT_OVERRIDE",
    )
    return _truthy(configured, default=not _legacy_production_mode())


def _allow_request_actor_override():
    configured = _legacy_runtime_config(
        "TMS_ALLOW_REQUEST_ACTOR_OVERRIDE",
        "TMS_ALLOW_REQUEST_ACTOR_OVERRIDE",
    )
    return _truthy(configured, default=not _legacy_production_mode())


def _legacy_session_authenticated():
    return bool(
        session.get("logged_in")
        or _normalize_text(session.get("user_email"))
        or _normalize_text(session.get("user_id"))
    )


def _legacy_login_required_response():
    if request.accept_mimetypes.accept_html and "login" in current_app.view_functions:
        next_url = request.full_path if request.query_string else request.path
        return redirect(url_for("login", next=next_url))
    return jsonify(ok=False, error="authentication_required"), 401


def _enforce_legacy_tms_auth():
    if not _legacy_route_auth_enabled():
        return None
    if request.blueprint != "tms":
        return None
    if request.path.startswith("/api/v1/"):
        return None
    if request.endpoint in LEGACY_PUBLIC_TMS_ENDPOINTS:
        return None
    if request.endpoint == "static" or request.path.startswith("/static/"):
        return None
    if _legacy_session_authenticated():
        return None
    return _legacy_login_required_response()


def tms_login_required(f):
    """Route guard for legacy TMS views when blueprint-level auth enforcement is enabled."""
    @wraps(f)
    def decorated(*args, **kwargs):
        auth_response = _enforce_legacy_tms_auth()
        if auth_response is not None:
            return auth_response
        return f(*args, **kwargs)
    return decorated


def tms_roles_required(*allowed_roles):
    normalized_roles = {
        str(role or "").strip().lower()
        for role in allowed_roles
        if str(role or "").strip()
    }

    def decorator(f):
        @wraps(f)
        def decorated(*args, **kwargs):
            if not _legacy_session_authenticated():
                return _legacy_login_required_response()
            current_role = _normalize_text(session.get("user_role")).lower()
            if normalized_roles and current_role not in normalized_roles:
                abort(403)
            return f(*args, **kwargs)

        return decorated

    return decorator


QUOTE_STATUS_STYLES = {
    "Accepted": "success",
    "Pending": "warning",
    "Expired": "danger",
    "Rejected": "secondary",
}

QUOTE_RATE_LABELS = {
    "rate_20ft": "20ft",
    "rate_40ft": "40ft",
    "rate_40hc": "40HC",
}

TENDER_STATUS_STYLES = {
    "Open": "warning",
    "Awarded": "success",
    "Expired": "secondary",
}

TENDER_RESPONSE_STATUS_STYLES = {
    "Pending": "secondary",
    "Submitted": "info",
    "Awarded": "success",
    "Not Awarded": "dark",
    "Expired": "secondary",
}


def _request_ip_address():
    return request.remote_addr or ""


def _request_actor():
    values = [
        session.get("user_email"),
        session.get("user_id"),
    ]
    if _allow_request_actor_override():
        values.extend(
            [
                request.headers.get("X-User-Id"),
                request.headers.get("X-Actor"),
            ]
        )
    for value in values:
        actor = _normalize_text(value)
        if actor:
            return actor
    return "system"


def _resolve_request_tenant():
    candidates = [session.get("tms_tenant_id")]
    if _allow_request_tenant_override():
        candidates = [
            request.headers.get("X-Tenant-ID"),
            request.args.get("tenant_id"),
            *candidates,
        ]
    for candidate in candidates:
        clean_candidate = _normalize_text(candidate)
        if clean_candidate:
            tenant = get_tenant(clean_candidate)
            if tenant and tenant.get("status") != "deleted":
                session["tms_tenant_id"] = tenant["tenant_id"]
                return tenant["tenant_id"]
    session.setdefault("tms_tenant_id", DEFAULT_TENANT_ID)
    return session.get("tms_tenant_id", DEFAULT_TENANT_ID)


def _enter_tenant_request_context():
    init_tms_db()
    tenant_id = _resolve_request_tenant()
    actor = _request_actor()
    ip_address = _request_ip_address()
    g.tms_tenant_id = tenant_id
    g.tenant_context = tenant_context(tenant_id=tenant_id, actor=actor, ip=ip_address)
    g.tenant_context.__enter__()


def _exit_tenant_request_context(_error=None):
    context_manager = g.pop("tenant_context", None)
    if context_manager:
        context_manager.__exit__(None, None, None)


@tms.before_request
def _load_tms_request_context():
    _enter_tenant_request_context()
    ensure_notification_scheduler()
    return _enforce_legacy_tms_auth()


@portal.before_request
def _load_portal_request_context():
    _enter_tenant_request_context()
    ensure_notification_scheduler()


@tms.teardown_request
def _teardown_tms_request_context(error=None):
    _exit_tenant_request_context(error)


@portal.teardown_request
def _teardown_portal_request_context(error=None):
    _exit_tenant_request_context(error)

LOAD_STATUS_STYLES = {
    "Planning": "secondary",
    "Dispatched": "primary",
    "In Transit": "warning",
    "Delivered": "success",
}

LOADBOARD_POST_STATUS_STYLES = {
    "Active": "success",
    "Closed": "secondary",
}

RATE_SHOP_SOURCE_PRIORITY = {
    "Contract": 0,
    "Market": 1,
    "Spot": 2,
}

INVOICE_STATUS_STYLES = {
    "Draft": "secondary",
    "Sent": "primary",
    "Paid": "success",
    "Overdue": "danger",
}

INVOICE_PAYMENT_TERMS = [
    "NET30",
    "NET15",
    "NET60",
    "DUE ON RECEIPT",
    "PREPAID",
]

CARRIER_INVOICE_STATUS_STYLES = {
    "Pending": "warning",
    "Approved": "success",
    "Disputed": "danger",
    "Paid": "primary",
}

CARRIER_INVOICE_STATUS_TRANSITIONS = {
    "Pending": {"Approved", "Disputed"},
    "Approved": {"Disputed", "Paid"},
    "Disputed": {"Approved"},
    "Paid": set(),
}

CARRIER_INVOICE_VARIANCE_THRESHOLD = 5.0
CLAIM_STATUS_STYLES = {
    "Filed": "secondary",
    "Under Review": "warning",
    "Approved": "success",
    "Paid": "primary",
    "Denied": "danger",
}
CLAIM_CLOSED_STATUSES = {"Paid", "Denied"}

SHIPMENT_STATUSES = {"Draft", "Active", "Booked", "In Transit", "Delivered", "Cancelled"}
SHIPMENT_STATUS_STYLES = {
    "Draft": "secondary",
    "Active": "primary",
    "Booked": "info",
    "In Transit": "warning",
    "Delivered": "success",
    "Cancelled": "danger",
}
INTAKE_STATUS_STYLES = {
    "processed": "warning",
    "reviewed": "info",
    "shipment_created": "success",
}
INTAKE_FIELD_SPECS = [
    {"key": "shipper", "label": "Shipper", "type": "text"},
    {"key": "consignee", "label": "Consignee", "type": "text"},
    {"key": "origin", "label": "Origin", "type": "text"},
    {"key": "destination", "label": "Destination", "type": "text"},
    {"key": "cargo_description", "label": "Cargo Description", "type": "text"},
    {"key": "weight", "label": "Weight", "type": "text"},
    {"key": "containers", "label": "Containers", "type": "text"},
    {"key": "etd", "label": "ETD", "type": "date"},
    {"key": "eta", "label": "ETA", "type": "date"},
    {"key": "incoterm", "label": "Incoterm", "type": "text"},
    {"key": "currency", "label": "Currency", "type": "text"},
    {"key": "rate", "label": "Rate", "type": "text"},
]
DISPATCH_COLUMNS = (
    {"id": "unassigned", "label": "Unassigned", "status": "Draft"},
    {"id": "tendered", "label": "Tendered", "status": "Active"},
    {"id": "confirmed", "label": "Confirmed", "status": "Booked"},
    {"id": "in_transit", "label": "In Transit", "status": "In Transit"},
    {"id": "delivered", "label": "Delivered", "status": "Delivered"},
)
DISPATCH_COLUMN_STATUS_MAP = {column["id"]: column["status"] for column in DISPATCH_COLUMNS}
DISPATCH_STATUS_COLUMN_MAP = {
    "Draft": "unassigned",
    "Active": "tendered",
    "Booked": "confirmed",
    "In Transit": "in_transit",
    "Delivered": "delivered",
}
API_PERMISSION_OPTIONS = [
    {
        "value": "shipments.read",
        "label": "Shipments Read",
        "description": "List customer shipments and view shipment details.",
    },
    {
        "value": "shipments.write",
        "label": "Shipments Write",
        "description": "Create new customer shipments.",
    },
    {
        "value": "tracking.read",
        "label": "Tracking Read",
        "description": "Read public tracking payloads for customer shipments.",
    },
    {
        "value": "rates.read",
        "label": "Rates Read",
        "description": "Query sandbox lane rate lookups.",
    },
]
VALID_API_PERMISSIONS = {option["value"] for option in API_PERMISSION_OPTIONS}
API_ROUTE_DEFINITIONS = []
API_RATE_LIMITER = RateLimiter(max_requests=100, window_seconds=60)
LOADBOARD_INTEREST_RATE_LIMITER = RateLimiter(max_requests=5, window_seconds=300)
ORDER_SUBMIT_RATE_LIMITER = RateLimiter(max_requests=5, window_seconds=600)
PUBLIC_TRACKING_TOKEN_MAX_AGE_SECONDS = 60 * 60 * 24 * 30
PUBLIC_TRACKING_TOKEN_SALT = "customer-tracking-link"
COLD_CHAIN_INGEST_TOKEN_MAX_AGE_SECONDS = 60 * 60 * 24 * 30
COLD_CHAIN_INGEST_TOKEN_SALT = "cold-chain-ingest"


def _load_shipment(conn, ref):
    return conn.execute("SELECT * FROM shipments WHERE shipment_ref=?", (ref,)).fetchone()


def _safe_url_for(endpoint, **values):
    if endpoint not in current_app.view_functions:
        return ""
    return url_for(endpoint, **values)


def _normalize_text(value):
    if value is None:
        return ""
    if isinstance(value, str):
        return value.strip()
    return str(value).strip()


def _public_tracking_serializer():
    secret_key = current_app.config.get("SECRET_KEY") or current_app.secret_key
    return URLSafeTimedSerializer(secret_key, salt=PUBLIC_TRACKING_TOKEN_SALT)


def _create_public_tracking_token(ref):
    clean_ref = _normalize_text(ref).upper()
    if not clean_ref:
        raise ValueError("Shipment reference is required.")
    return _public_tracking_serializer().dumps(clean_ref)


def _public_tracking_token_is_valid(ref, token):
    clean_ref = _normalize_text(ref).upper()
    clean_token = _normalize_text(token)
    if not clean_ref or not clean_token:
        return False
    try:
        max_age = int(
            current_app.config.get(
                "PUBLIC_TRACKING_TOKEN_MAX_AGE_SECONDS",
                PUBLIC_TRACKING_TOKEN_MAX_AGE_SECONDS,
            )
        )
    except (TypeError, ValueError):
        max_age = PUBLIC_TRACKING_TOKEN_MAX_AGE_SECONDS
    try:
        signed_ref = _public_tracking_serializer().loads(clean_token, max_age=max_age)
    except BadData:
        return False
    return secrets.compare_digest(str(signed_ref), clean_ref)


def build_public_tracking_url(ref, external=False):
    clean_ref = _normalize_text(ref).upper()
    if not clean_ref:
        return ""
    values = {
        "ref": clean_ref,
        "token": _create_public_tracking_token(clean_ref),
    }
    if external:
        values["_external"] = True
    return url_for("public_tracking", **values)


def _cold_chain_ingest_serializer():
    secret_key = current_app.config.get("SECRET_KEY") or current_app.secret_key
    return URLSafeTimedSerializer(secret_key, salt=COLD_CHAIN_INGEST_TOKEN_SALT)


def _create_cold_chain_ingest_token(shipment_ref, provider, sensor_id):
    clean_ref = _normalize_text(shipment_ref)
    clean_provider = _normalize_text(provider)
    clean_sensor_id = _normalize_text(sensor_id)
    if not clean_ref or not clean_provider or not clean_sensor_id:
        raise ValueError("Shipment reference, provider, and sensor ID are required.")
    return _cold_chain_ingest_serializer().dumps(
        {
            "shipment_ref": clean_ref,
            "provider": clean_provider,
            "sensor_id": clean_sensor_id,
        }
    )


def _cold_chain_ingest_token_is_valid(token, shipment_ref, provider, sensor_id):
    clean_token = _normalize_text(token)
    clean_ref = _normalize_text(shipment_ref)
    clean_provider = _normalize_text(provider)
    clean_sensor_id = _normalize_text(sensor_id)
    if not clean_token or not clean_ref or not clean_provider or not clean_sensor_id:
        return False
    try:
        max_age = int(
            current_app.config.get(
                "COLD_CHAIN_INGEST_TOKEN_MAX_AGE_SECONDS",
                COLD_CHAIN_INGEST_TOKEN_MAX_AGE_SECONDS,
            )
        )
    except (TypeError, ValueError):
        max_age = COLD_CHAIN_INGEST_TOKEN_MAX_AGE_SECONDS
    try:
        signed_payload = _cold_chain_ingest_serializer().loads(clean_token, max_age=max_age)
    except BadData:
        return False
    if not isinstance(signed_payload, dict):
        return False
    return (
        secrets.compare_digest(str(signed_payload.get("shipment_ref", "")), clean_ref)
        and secrets.compare_digest(str(signed_payload.get("provider", "")), clean_provider)
        and secrets.compare_digest(str(signed_payload.get("sensor_id", "")), clean_sensor_id)
    )


SCENARIO_INPUT_FIELDS = {
    "carrier_switch": ("lane", "current_rate", "new_rate", "annual_volume"),
    "route_change": ("current_miles", "new_miles", "fuel_rate", "driver_rate_per_mile"),
    "mode_shift": ("current_mode", "new_mode", "weight_lbs", "distance"),
    "volume_commitment": ("committed_volume", "spot_volume", "contract_rate", "spot_rate"),
}


def _scenario_form_defaults(overrides=None):
    values = {
        "lane": "",
        "current_rate": "",
        "new_rate": "",
        "annual_volume": "",
        "current_miles": "",
        "new_miles": "",
        "fuel_rate": "",
        "driver_rate_per_mile": "",
        "current_mode": "TL",
        "new_mode": "Rail",
        "weight_lbs": "",
        "distance": "",
        "committed_volume": "",
        "spot_volume": "",
        "contract_rate": "",
        "spot_rate": "",
    }
    if overrides:
        for key, value in overrides.items():
            if key in values and value is not None:
                values[key] = value
    return values


def _scenario_inputs_from_source(scenario_type, source):
    fields = SCENARIO_INPUT_FIELDS.get(_normalize_text(scenario_type))
    if not fields:
        raise ValueError("Scenario type is invalid.")
    return {field: source.get(field, "") for field in fields}


def _render_scenarios_page(
    *,
    active_type="carrier_switch",
    current_inputs=None,
    result=None,
    form_error=None,
    status_code=200,
    selected_saved_id=None,
    save_name="",
):
    saved_scenarios = get_saved_scenarios()
    selected_saved = None
    if selected_saved_id:
        selected_saved = next((item for item in saved_scenarios if item["id"] == selected_saved_id), None)
        if not selected_saved:
            flash("Saved scenario not found.", "warning")

    if selected_saved and result is None:
        result = selected_saved.get("results") or None
    if selected_saved and current_inputs is None:
        current_inputs = selected_saved.get("inputs") or None
    if selected_saved and not save_name:
        save_name = selected_saved.get("name", "")
    if selected_saved and not active_type:
        active_type = selected_saved.get("scenario_type") or "carrier_switch"

    active_type = active_type or "carrier_switch"
    current_inputs = _scenario_form_defaults(current_inputs)
    if not save_name and result:
        save_name = result.get("name_suggestion", "")

    return (
        render_template(
            "tms/scenarios.html",
            active_type=active_type,
            current_inputs=current_inputs,
            result=result,
            form_error=form_error,
            save_name=save_name,
            saved_scenarios=saved_scenarios,
            selected_saved=selected_saved,
        ),
        status_code,
    )


def _claims_upload_dir():
    upload_dir = current_app.config.get("TMS_CLAIMS_UPLOAD_DIR")
    if not upload_dir:
        upload_dir = os.path.join(current_app.root_path, "static", "uploads", "claims")
    os.makedirs(upload_dir, exist_ok=True)
    return upload_dir


def _claim_form_defaults(values=None):
    values = values or {}
    return {
        "shipment_ref": _normalize_text(values.get("shipment_ref")),
        "claim_type": _normalize_text(values.get("claim_type")) or CLAIM_TYPES[0],
        "description": _normalize_text(values.get("description")),
        "claimed_amount": _normalize_text(values.get("claimed_amount")),
        "currency": _normalize_text(values.get("currency")) or "USD",
    }


def _claim_response_form_defaults(claim=None):
    claim = claim or {}
    counter_offer = claim.get("counter_offer")
    return {
        "carrier_notes": _normalize_text(claim.get("carrier_notes")),
        "counter_offer": "" if counter_offer is None else f"{float(counter_offer):.2f}",
    }


def _claim_update_form_defaults(claim=None):
    claim = claim or {}
    settlement_amount = claim.get("settlement_amount")
    return {
        "status": _normalize_text(claim.get("status")) or CLAIM_STATUSES[0],
        "settlement_amount": "" if settlement_amount is None else f"{float(settlement_amount):.2f}",
    }


def _save_claim_evidence(upload, shipment_ref):
    if not upload or not getattr(upload, "filename", ""):
        raise ValueError("Evidence photo is required.")

    mimetype = _normalize_text(getattr(upload, "mimetype", "")).lower()
    if not mimetype.startswith("image/"):
        raise ValueError("Evidence must be an image upload.")

    safe_name = secure_filename(upload.filename or "")
    _, extension = os.path.splitext(safe_name)
    extension = extension.lower() or ".png"
    safe_ref = secure_filename(_normalize_text(shipment_ref)) or "shipment"
    stored_name = f"claim-{safe_ref}-{secrets.token_hex(8)}{extension}"
    upload_path = os.path.join(_claims_upload_dir(), stored_name)
    upload.save(upload_path)
    return stored_name


def _claim_evidence_fs_path(stored_name):
    clean_name = os.path.basename(_normalize_text(stored_name))
    if not clean_name:
        return ""
    return os.path.join(_claims_upload_dir(), clean_name)


def _pod_datetime_input_value(value):
    parsed = None
    raw = _normalize_text(value)
    if raw:
        candidate = raw[:-1] + "+00:00" if raw.endswith("Z") else raw
        try:
            parsed = datetime.fromisoformat(candidate)
        except ValueError:
            parsed = None
    if parsed is None:
        parsed = datetime.now().astimezone().replace(second=0, microsecond=0)
    elif parsed.tzinfo is not None:
        parsed = parsed.astimezone()
    return parsed.replace(second=0, microsecond=0).strftime("%Y-%m-%dT%H:%M")


def _pod_form_defaults(shipment, pod_record=None, overrides=None):
    pod_record = pod_record or {}
    values = {
        "recipient_name": _normalize_text(pod_record.get("recipient_name")) or _normalize_text((shipment or {}).get("consignee_name")),
        "delivered_at": _pod_datetime_input_value(pod_record.get("delivered_at")),
        "notes": _normalize_text(pod_record.get("notes")),
        "signature_data": _normalize_text(pod_record.get("signature_data")),
    }
    if overrides:
        values.update({key: value for key, value in overrides.items() if value is not None})
    return values


def _save_pod_photo(upload, shipment_ref, existing_path=""):
    if not upload or not getattr(upload, "filename", ""):
        return _normalize_text(existing_path)

    mimetype = _normalize_text(getattr(upload, "mimetype", "")).lower()
    if mimetype and not mimetype.startswith("image/"):
        raise ValueError("Delivery photo must be an image upload.")

    safe_name = secure_filename(upload.filename or "")
    _, extension = os.path.splitext(safe_name)
    extension = extension.lower() or ".jpg"
    safe_ref = secure_filename(_normalize_text(shipment_ref)) or "shipment"
    os.makedirs(POD_UPLOAD_DIR, exist_ok=True)
    stored_path = os.path.join(POD_UPLOAD_DIR, f"{safe_ref}-pod-photo{extension}")
    upload.save(stored_path)

    previous_path = _normalize_text(existing_path)
    if previous_path and previous_path != stored_path and os.path.exists(previous_path):
        try:
            os.remove(previous_path)
        except OSError:
            pass
    return stored_path


def _load_pod_access_context(ref, token):
    snapshot = get_shipment_snapshot(ref)
    if not snapshot:
        return None

    pod_token = get_or_create_pod_token(ref)
    if not secrets.compare_digest(pod_token, _normalize_text(token)):
        return None

    shipment = snapshot["shipment"]
    pod_record = get_pod_record(ref)
    return {
        "shipment": shipment,
        "pod_record": pod_record,
        "pod_token": pod_token,
        "pod_photo_url": _safe_url_for("tms.pod_photo", ref=shipment["shipment_ref"], token=pod_token),
        "pod_capture_url": _safe_url_for(
            "tms.capture_pod",
            ref=shipment["shipment_ref"],
            token=pod_token,
            _external=True,
        ),
    }


def _build_claim_view_model(claim):
    if not claim:
        return None

    claim_view = dict(claim)
    claim_view["status_class"] = CLAIM_STATUS_STYLES.get(claim_view["status"], "secondary")
    claim_view["claimed_amount_display"] = f"{float(claim_view['claimed_amount'] or 0):,.2f}"
    claim_view["settlement_amount_display"] = (
        f"{float(claim_view['settlement_amount']):,.2f}"
        if claim_view.get("settlement_amount") is not None
        else ""
    )
    claim_view["counter_offer_display"] = (
        f"{float(claim_view['counter_offer']):,.2f}"
        if claim_view.get("counter_offer") is not None
        else ""
    )
    claim_view["carrier_response_link"] = (
        url_for(
            "tms.respond_to_claim",
            claim_id=claim_view["id"],
            token=claim_view["response_token"],
            _external=True,
        )
        if claim_view.get("response_token")
        else ""
    )
    claim_view["evidence_url"] = (
        url_for("tms.claim_evidence", filename=claim_view["evidence_path"])
        if claim_view.get("evidence_path")
        else ""
    )
    claim_view["has_carrier_response"] = bool(
        claim_view.get("carrier_notes") or claim_view.get("counter_offer") is not None
    )
    claim_view["is_closed"] = claim_view["status"] in CLAIM_CLOSED_STATUSES
    return claim_view


def _claims_board_context(*, status="", carrier_id="", claim_type="", shipment_ref="", selected_claim_id=None):
    filtered_claims = [
        _build_claim_view_model(claim)
        for claim in list_freight_claims(
            status=status,
            carrier_id=carrier_id,
            claim_type=claim_type,
            shipment_ref=shipment_ref,
        )
    ]
    all_claims = [_build_claim_view_model(claim) for claim in list_freight_claims()]
    selected_claim = None
    if selected_claim_id:
        selected_claim = next(
            (claim for claim in filtered_claims if claim["id"] == selected_claim_id),
            None,
        )
    if selected_claim is None and filtered_claims:
        selected_claim = filtered_claims[0]

    return {
        "claims": filtered_claims,
        "claim_stats": {
            "total": len(all_claims),
            "filed": sum(1 for claim in all_claims if claim["status"] == "Filed"),
            "under_review": sum(1 for claim in all_claims if claim["status"] == "Under Review"),
            "approved": sum(1 for claim in all_claims if claim["status"] == "Approved"),
            "paid": sum(1 for claim in all_claims if claim["status"] == "Paid"),
            "denied": sum(1 for claim in all_claims if claim["status"] == "Denied"),
        },
        "selected_claim": selected_claim,
        "claim_filters": {
            "status": _normalize_text(status),
            "carrier_id": _normalize_text(carrier_id),
            "claim_type": _normalize_text(claim_type),
            "shipment_ref": _normalize_text(shipment_ref),
        },
        "claim_filter_carriers": list_freight_claim_filter_carriers(),
        "claim_types": CLAIM_TYPES,
        "claim_statuses": CLAIM_STATUSES,
        "claim_status_styles": CLAIM_STATUS_STYLES,
        "shipment_refs": list_shipment_refs(),
    }


def _normalize_optional_iso_date(raw_value):
    value = _normalize_text(raw_value)
    if not value:
        return ""
    try:
        date.fromisoformat(value)
    except ValueError:
        return ""
    return value


def _parse_dispatch_date(raw_value):
    value = _normalize_text(raw_value)
    if not value:
        return None
    try:
        return date.fromisoformat(value[:10])
    except ValueError:
        try:
            return datetime.fromisoformat(value.replace("Z", "+00:00")).date()
        except ValueError:
            return None


def _format_dispatch_date(raw_value):
    value = _parse_dispatch_date(raw_value)
    if not value:
        return "-"
    return value.strftime("%b %d")


def _dispatch_column_for_status(status):
    return DISPATCH_STATUS_COLUMN_MAP.get(_normalize_text(status), "unassigned")


def _dispatch_health(shipment):
    status = _normalize_text((shipment or {}).get("status"))
    if status == "Delivered":
        return {"tone": "on-time", "label": "On time"}

    eta_date = _parse_dispatch_date((shipment or {}).get("eta"))
    if not eta_date:
        return {"tone": "at-risk", "label": "ETA pending"}

    days_until_eta = (eta_date - date.today()).days
    if days_until_eta < 0:
        return {"tone": "late", "label": "Late"}
    if days_until_eta <= 1:
        return {"tone": "at-risk", "label": "At risk"}
    return {"tone": "on-time", "label": "On time"}


def _get_dispatch_board_context():
    init_tms_db()
    carrier_filter = _normalize_text(request.args.get("carrier"))
    mode_filter = _normalize_text(request.args.get("mode"))
    date_from = _normalize_optional_iso_date(request.args.get("date_from"))
    date_to = _normalize_optional_iso_date(request.args.get("date_to"))

    if date_from and date_to and date_from > date_to:
        date_from, date_to = date_to, date_from

    conn = get_db()
    try:
        carriers = conn.execute(
            """
            SELECT id, name
            FROM tms_carriers
            WHERE active = 1
            ORDER BY name COLLATE NOCASE ASC
            """
        ).fetchall()
        carrier_names = [
            row["carrier_name"]
            for row in conn.execute(
                """
                SELECT DISTINCT carrier_name
                FROM shipments
                WHERE COALESCE(TRIM(carrier_name), '') <> ''
                ORDER BY carrier_name COLLATE NOCASE ASC
                """
            ).fetchall()
        ]
        modes = [
            row["mode"]
            for row in conn.execute(
                """
                SELECT DISTINCT mode
                FROM shipments
                WHERE COALESCE(TRIM(mode), '') <> ''
                ORDER BY mode COLLATE NOCASE ASC
                """
            ).fetchall()
        ]

        query = """
            SELECT s.*
            FROM shipments s
            WHERE COALESCE(s.status, 'Draft') <> 'Cancelled'
        """
        params = []
        if carrier_filter == "__unassigned__":
            query += " AND COALESCE(TRIM(s.carrier_name), '') = ''"
        elif carrier_filter:
            query += " AND COALESCE(s.carrier_name, '') = ?"
            params.append(carrier_filter)

        if mode_filter:
            query += " AND LOWER(COALESCE(s.mode, '')) = LOWER(?)"
            params.append(mode_filter)

        if date_from:
            query += " AND date(COALESCE(s.eta, s.etd, s.created_at)) >= date(?)"
            params.append(date_from)

        if date_to:
            query += " AND date(COALESCE(s.etd, s.eta, s.created_at)) <= date(?)"
            params.append(date_to)

        query += """
            ORDER BY
                CASE COALESCE(s.status, 'Draft')
                    WHEN 'Draft' THEN 0
                    WHEN 'Active' THEN 1
                    WHEN 'Booked' THEN 2
                    WHEN 'In Transit' THEN 3
                    WHEN 'Delivered' THEN 4
                    ELSE 0
                END,
                date(COALESCE(s.eta, s.etd, s.created_at)) ASC,
                datetime(COALESCE(s.updated_at, s.created_at)) DESC,
                s.id DESC
        """

        rows = conn.execute(query, params).fetchall()
    finally:
        conn.close()

    dispatch_columns = []
    shipments_by_column = {
        column["id"]: {
            "id": column["id"],
            "label": column["label"],
            "status": column["status"],
            "shipments": [],
        }
        for column in DISPATCH_COLUMNS
    }

    for row in rows:
        shipment = dict(row)
        column_id = _dispatch_column_for_status(shipment.get("status"))
        shipment["dispatch_column_id"] = column_id
        shipment["dispatch_health"] = _dispatch_health(shipment)
        shipment["dispatch_etd"] = _format_dispatch_date(shipment.get("etd"))
        shipment["dispatch_eta"] = _format_dispatch_date(shipment.get("eta"))
        shipment["dispatch_carrier"] = shipment.get("carrier_name") or "Unassigned"
        shipment["dispatch_origin"] = shipment.get("origin_port") or "Origin TBD"
        shipment["dispatch_destination"] = shipment.get("destination_port") or "Destination TBD"
        shipment["dispatch_cargo"] = shipment.get("cargo_description") or "Cargo pending"
        shipment["dispatch_mode"] = shipment.get("mode") or "Mode TBD"
        shipments_by_column[column_id]["shipments"].append(shipment)

    for column in DISPATCH_COLUMNS:
        dispatch_columns.append(shipments_by_column[column["id"]])

    filter_carriers = sorted(
        {
            name
            for name in (
                carrier_names + [carrier["name"] for carrier in carriers if carrier["name"]]
            )
            if name
        },
        key=str.lower,
    )

    return {
        "dispatch_columns": dispatch_columns,
        "carriers": carriers,
        "carrier_filters": filter_carriers,
        "mode_filters": modes,
        "filters": {
            "carrier": carrier_filter,
            "mode": mode_filter,
            "date_from": date_from,
            "date_to": date_to,
        },
        "dispatch_status_map": DISPATCH_COLUMN_STATUS_MAP,
        "auto_refresh_seconds": 60,
    }


def _invoice_number(invoice_or_id):
    invoice_id = invoice_or_id
    if isinstance(invoice_or_id, dict):
        invoice_id = invoice_or_id.get("id")
    elif hasattr(invoice_or_id, "keys") and "id" in invoice_or_id.keys():
        invoice_id = invoice_or_id["id"]
    return f"CINV-{int(invoice_id or 0):05d}"


def _parse_invoice_status(raw_value):
    status = _normalize_text(raw_value) or "Draft"
    if status not in INVOICE_STATUS_STYLES:
        raise ValueError("Invoice status is invalid.")
    return status


def _parse_invoice_amount(raw_value):
    return _parse_quote_amount(raw_value, "Amount")


def _parse_invoice_component_amount(raw_value, label):
    value = _normalize_text(raw_value)
    if not value:
        return 0.0
    try:
        amount = round(float(value), 2)
    except ValueError as exc:
        raise ValueError(f"{label} must be a valid number.") from exc
    if amount < 0:
        raise ValueError(f"{label} cannot be negative.")
    return amount


def _normalize_invoice_payment_terms(raw_value):
    value = _normalize_text(raw_value)
    if not value:
        return "NET30"
    normalized = re.sub(r"\s+", " ", value).strip().upper()
    return {
        "NET30": "NET30",
        "NET15": "NET15",
        "NET60": "NET60",
        "DUEONRECEIPT": "DUE ON RECEIPT",
        "PREPAID": "PREPAID",
    }.get(normalized.replace(" ", ""), normalized)


def _parse_invoice_payment_terms(raw_value):
    normalized = _normalize_invoice_payment_terms(raw_value)
    if normalized not in INVOICE_PAYMENT_TERMS:
        raise ValueError("Payment terms are invalid.")
    return normalized


def _parse_exchange_rate(raw_value):
    value = _normalize_text(raw_value) or "1"
    try:
        exchange_rate = round(float(value), 6)
    except ValueError as exc:
        raise ValueError("Exchange rate must be a valid number.") from exc
    if exchange_rate <= 0:
        raise ValueError("Exchange rate must be greater than 0.")
    return exchange_rate


def _parse_invoice_due_date(raw_value):
    value = _normalize_text(raw_value)
    if not value:
        raise ValueError("Due date is required.")
    try:
        return date.fromisoformat(value)
    except ValueError as exc:
        raise ValueError("Due date must be a valid date.") from exc


def _parse_invoice_date(raw_value):
    value = _normalize_text(raw_value)
    if not value:
        raise ValueError("Invoice date is required.")
    try:
        return date.fromisoformat(value)
    except ValueError as exc:
        raise ValueError("Invoice date must be a valid date.") from exc


def _shipment_customer_defaults(shipment):
    shipment = shipment or {}
    freight_charge = shipment.get("freight_rate")
    payment_terms = _normalize_invoice_payment_terms(shipment.get("payment_terms"))
    if payment_terms not in INVOICE_PAYMENT_TERMS:
        payment_terms = "NET30"
    return {
        "shipment_ref": shipment.get("shipment_ref", ""),
        "customer_name": shipment.get("shipper_name") or shipment.get("consignee_name") or "",
        "amount": f"{float(freight_charge or 0):.2f}" if freight_charge is not None else "",
        "currency": shipment.get("currency") or "USD",
        "exchange_rate": "1.0000",
        "status": "Draft",
        "freight_charge": f"{float(freight_charge or 0):.2f}" if freight_charge is not None else "",
        "fuel_surcharge": "0.00",
        "accessorial_total": "0.00",
        "tax_amount": "0.00",
        "discount": "0.00",
        "payment_terms": payment_terms,
        "remit_to": "",
        "invoice_date": date.today().isoformat(),
        "po_reference": shipment.get("po_number") or "",
        "due_date": (date.today() + timedelta(days=30)).isoformat(),
    }


def _invoice_form_defaults(shipment=None, invoice=None):
    defaults = _shipment_customer_defaults(shipment)
    if invoice:
        freight_charge = invoice["freight_charge"]
        if freight_charge is None and invoice["amount"] is not None:
            freight_charge = invoice["amount"]
        invoice_payment_terms = _normalize_invoice_payment_terms(invoice["payment_terms"])
        if invoice_payment_terms not in INVOICE_PAYMENT_TERMS:
            invoice_payment_terms = "NET30"
        defaults.update(
            {
                "invoice_id": str(invoice["id"]),
                "shipment_ref": invoice["shipment_ref"],
                "customer_name": invoice["customer_name"] or "",
                "amount": f"{float(invoice['amount'] or 0):.2f}",
                "currency": invoice["currency"] or defaults["currency"],
                "exchange_rate": f"{float(invoice['exchange_rate'] or 1):.4f}",
                "status": invoice["status"] or "Draft",
                "freight_charge": f"{float(freight_charge or 0):.2f}" if freight_charge is not None else "",
                "fuel_surcharge": f"{float(invoice['fuel_surcharge'] or 0):.2f}",
                "accessorial_total": f"{float(invoice['accessorial_total'] or 0):.2f}",
                "tax_amount": f"{float(invoice['tax_amount'] or 0):.2f}",
                "discount": f"{float(invoice['discount'] or 0):.2f}",
                "payment_terms": invoice_payment_terms,
                "remit_to": invoice["remit_to"] or "",
                "invoice_date": invoice["invoice_date"] or _invoice_date_value(invoice),
                "po_reference": invoice["po_reference"] or "",
                "due_date": invoice["due_date"] or defaults["due_date"],
            }
        )
    return defaults


def _hydrate_invoice_row(row):
    invoice = dict(row)
    invoice["invoice_number"] = _invoice_number(invoice)
    invoice["status_class"] = INVOICE_STATUS_STYLES.get(invoice["status"], "secondary")
    invoice["amount_display"] = f"{float(invoice['amount'] or 0):,.2f}"
    invoice["exchange_rate_display"] = f"{float(invoice['exchange_rate'] or 1):,.4f}"
    invoice["route_label"] = f"{invoice.get('origin_port') or '-'} -> {invoice.get('destination_port') or '-'}"
    invoice["can_mark_sent"] = invoice["status"] in {"Draft", "Overdue"}
    invoice["can_mark_paid"] = invoice["status"] in {"Sent", "Overdue"}
    invoice["can_mark_draft"] = invoice["status"] in {"Sent", "Overdue"}
    invoice["is_open"] = invoice["status"] in {"Sent", "Overdue"}
    return invoice


def _load_customer_invoice(conn, invoice_id):
    return conn.execute(
        """
        SELECT ci.*, s.shipper_name, s.shipper_address, s.consignee_name, s.consignee_address,
               s.origin_port, s.destination_port, s.cargo_description, s.containers,
               s.weight_kg, s.volume_cbm, s.etd, s.eta
        FROM customer_invoices ci
        LEFT JOIN shipments s ON s.shipment_ref = ci.shipment_ref
        WHERE ci.id = ?
        """,
        (invoice_id,),
    ).fetchone()


def _list_customer_invoices(conn):
    refresh_customer_invoice_statuses(conn)
    rows = conn.execute(
        """
        SELECT ci.*, s.shipper_name, s.shipper_address, s.consignee_name, s.consignee_address,
               s.origin_port, s.destination_port, s.cargo_description, s.containers,
               s.weight_kg, s.volume_cbm, s.etd, s.eta
        FROM customer_invoices ci
        LEFT JOIN shipments s ON s.shipment_ref = ci.shipment_ref
        ORDER BY
            CASE ci.status
                WHEN 'Overdue' THEN 0
                WHEN 'Sent' THEN 1
                WHEN 'Draft' THEN 2
                WHEN 'Paid' THEN 3
                ELSE 4
            END,
            date(ci.due_date) ASC,
            ci.id DESC
        """
    ).fetchall()
    return [_hydrate_invoice_row(row) for row in rows]


def _log_invoice_event(conn, shipment_ref, event_type, description):
    shipment = conn.execute(
        "SELECT id FROM shipments WHERE shipment_ref = ?",
        (shipment_ref,),
    ).fetchone()
    if not shipment:
        return
    conn.execute(
        "INSERT INTO shipment_events (shipment_id, event_type, description) VALUES (?,?,?)",
        (shipment["id"], event_type, description),
    )


def _invoice_date_value(invoice):
    return _normalize_text(invoice.get("invoice_date")) or _normalize_text(invoice.get("created_at"))[:10] or date.today().isoformat()


def _invoice_description(invoice):
    cargo_description = _normalize_text(invoice.get("cargo_description"))
    if cargo_description:
        return cargo_description
    return f"Freight services for {invoice.get('shipment_ref', 'shipment')}"


def _csv_download_response(filename, fieldnames, rows):
    buffer = io.StringIO()
    writer = csv.DictWriter(buffer, fieldnames=fieldnames)
    writer.writeheader()
    for row in rows:
        writer.writerow(row)
    return Response(
        buffer.getvalue(),
        mimetype="text/csv",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


def _shipment_reporting_date(shipment):
    etd_value = _normalize_text(shipment.get("etd"))
    if etd_value:
        try:
            return date.fromisoformat(etd_value)
        except ValueError:
            pass

    created_at_value = _normalize_text(shipment.get("created_at"))
    if not created_at_value:
        return None
    try:
        return datetime.fromisoformat(created_at_value.replace("Z", "+00:00")).date()
    except ValueError:
        return None


def _recent_month_buckets(month_count=6):
    today = date.today()
    current_index = today.year * 12 + today.month - 1
    buckets = []
    for offset in range(month_count - 1, -1, -1):
        bucket_index = current_index - offset
        year = bucket_index // 12
        month = bucket_index % 12 + 1
        bucket_date = date(year, month, 1)
        buckets.append(
            {
                "key": bucket_date.strftime("%Y-%m"),
                "label": bucket_date.strftime("%b %Y"),
            }
        )
    return buckets


def _load_esg_shipments(conn):
    shipments = []
    for row in conn.execute(
        """
        SELECT *
        FROM shipments
        ORDER BY date(COALESCE(NULLIF(etd, ''), created_at)) DESC, id DESC
        """
    ).fetchall():
        shipment = dict(row)
        shipment["reporting_date"] = _shipment_reporting_date(shipment)
        shipment["carbon_mode"] = normalize_carbon_mode(shipment.get("mode"))
        shipment["carbon_mode_label"] = CARBON_MODE_LABELS.get(shipment["carbon_mode"], "Unmapped")
        shipment["lane_label"] = f"{shipment.get('origin_port') or '-'} -> {shipment.get('destination_port') or '-'}"
        shipment["is_operational"] = shipment.get("status") not in {"Draft", "Cancelled"}
        shipments.append(shipment)
    return shipments


def _build_esg_dashboard_context(conn):
    shipments = _load_esg_shipments(conn)
    eligible_shipments = [
        shipment for shipment in shipments if shipment["is_operational"] and shipment.get("co2_kg") is not None
    ]

    today = date.today()
    total_month = 0.0
    total_year = 0.0
    by_mode_totals = {mode: 0.0 for mode in ("ocean", "air", "road", "rail")}
    carrier_totals = {}
    lane_totals = {}
    trend_totals = {bucket["key"]: 0.0 for bucket in _recent_month_buckets()}

    for shipment in eligible_shipments:
        shipment_date = shipment.get("reporting_date")
        co2_kg = float(shipment.get("co2_kg") or 0)
        if shipment_date and shipment_date.year == today.year:
            total_year += co2_kg
            if shipment_date.month == today.month:
                total_month += co2_kg
            month_key = shipment_date.strftime("%Y-%m")
            if month_key in trend_totals:
                trend_totals[month_key] += co2_kg

        mode_key = shipment.get("carbon_mode")
        if mode_key in by_mode_totals:
            by_mode_totals[mode_key] += co2_kg

        carrier_name = shipment.get("carrier_name") or "Unassigned"
        carrier_entry = carrier_totals.setdefault(carrier_name, {"name": carrier_name, "co2_kg": 0.0, "shipments": 0})
        carrier_entry["co2_kg"] += co2_kg
        carrier_entry["shipments"] += 1

        lane_label = shipment["lane_label"]
        lane_entry = lane_totals.setdefault(lane_label, {"lane": lane_label, "co2_kg": 0.0, "shipments": 0})
        lane_entry["co2_kg"] += co2_kg
        lane_entry["shipments"] += 1

    usd_scope_shipments = [
        shipment
        for shipment in eligible_shipments
        if (shipment.get("currency") or "USD").upper() == "USD" and float(shipment.get("freight_rate") or 0) > 0
    ]
    usd_spend = round(sum(float(shipment.get("freight_rate") or 0) for shipment in usd_scope_shipments), 2)
    usd_scope_co2 = round(sum(float(shipment.get("co2_kg") or 0) for shipment in usd_scope_shipments), 2)
    carbon_intensity = round(usd_scope_co2 / usd_spend, 4) if usd_spend > 0 else None
    excluded_spend_shipments = len(
        [
            shipment
            for shipment in eligible_shipments
            if (shipment.get("currency") or "USD").upper() != "USD" or float(shipment.get("freight_rate") or 0) <= 0
        ]
    )

    month_buckets = _recent_month_buckets()
    top_carriers = sorted(carrier_totals.values(), key=lambda item: (-item["co2_kg"], item["name"]))[:10]
    top_lanes = sorted(lane_totals.values(), key=lambda item: (-item["co2_kg"], item["lane"]))[:10]

    for row in top_carriers:
        row["co2_kg"] = round(row["co2_kg"], 2)
    for row in top_lanes:
        row["co2_kg"] = round(row["co2_kg"], 2)

    by_mode_labels = [CARBON_MODE_LABELS[mode] for mode in ("ocean", "air", "road", "rail")]
    by_mode_values = [round(by_mode_totals[mode], 2) for mode in ("ocean", "air", "road", "rail")]
    trend_labels = [bucket["label"] for bucket in month_buckets]
    trend_values = [round(trend_totals[bucket["key"]], 2) for bucket in month_buckets]

    return {
        "framework_label": CARBON_FRAMEWORK_LABEL,
        "summary": {
            "month_co2_kg": round(total_month, 2),
            "year_co2_kg": round(total_year, 2),
            "carbon_intensity_kg_per_usd": carbon_intensity,
            "usd_spend": usd_spend,
            "usd_scope_co2_kg": usd_scope_co2,
            "eligible_shipments": len(eligible_shipments),
            "calculated_shipments": len(eligible_shipments),
            "unresolved_shipments": sum(
                1
                for shipment in shipments
                if shipment["is_operational"] and shipment.get("co2_kg") is None
            ),
            "excluded_spend_shipments": excluded_spend_shipments,
        },
        "top_carriers": top_carriers,
        "top_lanes": top_lanes,
        "chart_data": {
            "by_mode": {
                "labels": by_mode_labels,
                "values": by_mode_values,
            },
            "trend": {
                "labels": trend_labels,
                "values": trend_values,
            },
        },
    }


def _build_esg_export_rows(conn):
    rows = []
    last_checked = datetime.utcnow().replace(microsecond=0).isoformat() + "Z"
    for shipment in _load_esg_shipments(conn):
        details = calculate_shipment_co2_details(shipment, conn=conn)
        rows.append(
            {
                "shipment_ref": shipment.get("shipment_ref") or "",
                "status": shipment.get("status") or "",
                "shipment_date": shipment["reporting_date"].isoformat() if shipment.get("reporting_date") else "",
                "origin_port": shipment.get("origin_port") or "",
                "destination_port": shipment.get("destination_port") or "",
                "lane": shipment["lane_label"],
                "carrier_name": shipment.get("carrier_name") or "",
                "mode": shipment.get("mode") or "",
                "esg_mode": details.get("mode_label") or "",
                "weight_kg": shipment.get("weight_kg") or 0,
                "distance_km": details.get("distance_km") or "",
                "emission_factor_kg_per_tonne_km": details.get("emission_factor_kg_per_tonne_km") or "",
                "co2_kg": details.get("co2_kg") or "",
                "freight_rate": shipment.get("freight_rate") or 0,
                "currency": shipment.get("currency") or "USD",
                "carbon_intensity_kg_per_usd": details.get("carbon_intensity_kg_per_usd") or "",
                "framework_label": details.get("framework_label") or CARBON_FRAMEWORK_LABEL,
                "calculation_status": details.get("calculation_status") or "",
                "origin_source_url": details.get("origin_source_url") or "",
                "destination_source_url": details.get("destination_source_url") or "",
                "last_checked": last_checked,
            }
        )
    return rows


def _portal_brand_settings():
    return get_setup_state()["settings"]


def _portal_session_token():
    active_token = _normalize_text(session.get("portal_token")).upper()
    if not active_token:
        return None

    portal_token = get_portal_token(active_token)
    if not portal_token:
        session.pop("portal_token", None)
        return None

    session["portal_token"] = portal_token["token"]
    return portal_token


def _portal_quote_form_defaults(overrides=None):
    values = {
        "origin": "",
        "destination": "",
        "cargo_description": "",
        "weight_kg": "",
        "volume_cbm": "",
        "equipment_type": "dry_van",
        "pickup_date": date.today().isoformat(),
        "delivery_date": "",
        "notes": "",
    }
    if overrides:
        values.update({key: value for key, value in overrides.items() if value is not None})
    return values


def _portal_equipment_options():
    return [
        {
            "value": value,
            "label": (meta or {}).get("label") or value.replace("_", " ").title(),
            "group": (meta or {}).get("group") or "Other",
        }
        for value, meta in EQUIPMENT_TYPES.items()
    ]


def _send_portal_quote_email(portal_request, dispatcher_note=""):
    customer_email = _normalize_text((portal_request or {}).get("customer_email"))
    if not customer_email:
        return False, "Customer email is missing for this portal token."

    try:
        from .email_engine import EmailEngine

        engine = EmailEngine()
        providers = engine.list_provider_configs()
        if not providers:
            return False, "No email provider is configured."

        settings = _portal_brand_settings()
        company_name = settings.get("company_name", "Customer Portal")
        portal_login_url = url_for("portal.portal_login", _external=True)
        quoted_rate_display = (portal_request or {}).get("quoted_rate_display") or "$0.00"
        note_text = _normalize_text(dispatcher_note) or "No additional notes were included."
        subject = f"Your quote is ready: {(portal_request or {}).get('reference', 'Portal Request')}"
        body = (
            f"Hello {(portal_request or {}).get('customer_name', 'Customer')},\n\n"
            f"Your quote request {(portal_request or {}).get('reference', '')} is now ready.\n"
            f"Route: {(portal_request or {}).get('route_label', '')}\n"
            f"Quoted rate: {quoted_rate_display}\n"
            f"Equipment: {(portal_request or {}).get('equipment_label') or '-'}\n\n"
            f"Dispatcher notes:\n{note_text}\n\n"
            f"Log in to the portal to review your quote:\n{portal_login_url}\n\n"
            f"Regards,\n{company_name}"
        )
        result = engine.send_message(
            to_addresses=[customer_email],
            subject=subject,
            text_body=body,
            html_body=f'<pre style="font-family:Arial;font-size:14px;white-space:pre-wrap">{body}</pre>',
        )
        if result.get("ok"):
            return True, ""
        return False, result.get("error", "Unknown email error.")
    except Exception as exc:
        return False, str(exc)


def _portal_request_defaults(portal_token=None, overrides=None):
    portal_token = portal_token or {}
    values = {
        "shipper_name": portal_token.get("customer_name", ""),
        "shipper_address": "",
        "consignee_name": "",
        "consignee_address": "",
        "origin_port": "",
        "destination_port": "",
        "mode": "FTL",
        "etd": "",
        "eta": "",
        "cargo_description": "",
        "containers": "",
        "weight_kg": "",
        "volume_cbm": "",
        "currency": "USD",
        "incoterm": "FOB",
        "notes": "",
        "selected_ref": "",
    }
    if overrides:
        values.update({key: value for key, value in overrides.items() if value is not None})
    return values


def _runtime_base_url():
    configured = _legacy_runtime_config("BASE_URL", "BASE_URL")
    clean_configured = _normalize_text(configured)
    if clean_configured:
        return str(configured).rstrip("/")
    return request.url_root.rstrip("/")


def _build_document_response(shipment, company, ref, document_type):
    generators = {
        "bol": (generate_bol, "BOL"),
        "invoice": (generate_invoice, "Invoice"),
        "packing-list": (generate_packing_list, "PackingList"),
        "awb": (generate_awb, "AWB"),
    }
    generator, filename_prefix = generators[document_type]
    if generator is None:
        return f"Document generation unavailable: {_tms_docs_error}", 503

    pdf = generator(shipment, company)
    return Response(
        pdf,
        mimetype="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="{filename_prefix}-{ref}.pdf"'},
    )


def _build_pod_document_response(shipment, pod_record, company, ref):
    if generate_pod is None:
        return f"Document generation unavailable: {_tms_docs_error}", 503

    pdf = generate_pod(shipment, pod_record, company)
    return Response(
        pdf,
        mimetype="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="POD-{ref}.pdf"'},
    )


def _render_portal_dashboard(token, *, selected_ref=None, form_values=None, form_error=None, status_code=200):
    context = get_portal_dashboard_context(token, selected_ref=selected_ref)
    if not context:
        session.pop("portal_token", None)
        flash("Portal access was not found.", "danger")
        return redirect(url_for("portal.portal_login"))

    session["portal_token"] = context["portal_token"]["token"]
    defaults = _portal_request_defaults(
        context["portal_token"],
        {"selected_ref": context["selected_shipment"]["shipment_ref"] if context["selected_shipment"] else ""},
    )
    if form_values:
        defaults.update(form_values)
    public_tracking_url = ""
    if context["selected_shipment"]:
        public_tracking_url = build_public_tracking_url(
            context["selected_shipment"]["shipment_ref"]
        )

    return (
        render_template(
            "tms/portal_dashboard.html",
            documents_enabled=all(
                generator is not None
                for generator in (generate_bol, generate_invoice, generate_packing_list)
            ),
            form_error=form_error,
            form_values=defaults,
            public_tracking_url=public_tracking_url,
            **context,
        ),
        status_code,
    )


def _parse_quote_amount(raw_value, label):
    value = (raw_value or "").strip()
    if not value:
        return None
    try:
        parsed = round(float(value), 2)
    except ValueError as exc:
        raise ValueError(f"{label} must be a valid number.") from exc
    if parsed <= 0:
        raise ValueError(f"{label} must be greater than 0.")
    return parsed


def _get_or_create_carrier(conn, carrier_name):
    clean_name = (carrier_name or "").strip()
    if not clean_name:
        raise ValueError("Carrier is required.")

    existing = conn.execute(
        "SELECT id, name FROM tms_carriers WHERE lower(name)=lower(?) LIMIT 1",
        (clean_name,),
    ).fetchone()
    if existing:
        return existing["id"], existing["name"]

    cursor = conn.execute(
        "INSERT INTO tms_carriers (name, active, updated_at) VALUES (?, 1, CURRENT_TIMESTAMP)",
        (clean_name,),
    )
    return cursor.lastrowid, clean_name


def _quote_rate_priority(containers):
    container_text = (containers or "").upper().replace(" ", "")
    if "40HC" in container_text or "40HQ" in container_text or "HC" in container_text:
        return ("rate_40hc", "rate_40ft", "rate_20ft")
    if "40" in container_text:
        return ("rate_40ft", "rate_40hc", "rate_20ft")
    if "20" in container_text:
        return ("rate_20ft", "rate_40ft", "rate_40hc")
    return ("rate_20ft", "rate_40ft", "rate_40hc")


def _resolve_quote_rate(shipment, quote):
    for field_name in _quote_rate_priority(shipment["containers"]):
        value = quote[field_name]
        if value is not None:
            return field_name, round(float(value), 2)
    return None, None


def _parse_decimal_value(raw_value, default=0.0):
    value = _normalize_text(raw_value)
    if not value:
        return default
    try:
        return round(float(value), 2)
    except ValueError:
        return default


def _shipment_lookup_date(raw_value):
    value = _normalize_text(raw_value)
    if not value:
        return date.today().isoformat()
    return value


def _build_shipment_rate_context(conn, form):
    contract_rate = find_best_contract_rate(
        origin=form.get("origin_port", ""),
        destination=form.get("destination_port", ""),
        mode=form.get("mode", ""),
        containers=form.get("containers", ""),
        reference_date=_shipment_lookup_date(form.get("etd")),
        conn=conn,
    )
    if contract_rate:
        return {
            "freight_rate": contract_rate["matched_rate"] or 0,
            "currency": contract_rate["currency"],
            "contract_rate_id": contract_rate["id"],
            "contract_rate": contract_rate,
        }
    return {
        "freight_rate": _parse_decimal_value(form.get("freight_rate")),
        "currency": (_normalize_text(form.get("currency")) or "USD").upper(),
        "contract_rate_id": None,
        "contract_rate": None,
    }


def _rate_form_defaults(source=None):
    source = source or {}
    return {
        "id": source.get("id", ""),
        "origin": source.get("origin", ""),
        "destination": source.get("destination", ""),
        "mode": source.get("mode", ""),
        "rate_20ft": "" if source.get("rate_20ft") is None else source.get("rate_20ft"),
        "rate_40ft": "" if source.get("rate_40ft") is None else source.get("rate_40ft"),
        "rate_40hc": "" if source.get("rate_40hc") is None else source.get("rate_40hc"),
        "currency": source.get("currency", "USD"),
        "valid_from": source.get("valid_from", ""),
        "valid_to": source.get("valid_to", ""),
    }


def _render_rates_page(selected_rate_id=None, form_values=None, form_mode=None, form_error=None, status_code=200):
    search_query = request.args.get("q", "")
    rates = list_contract_rates(search_query=search_query)
    selected_rate = get_contract_rate(selected_rate_id) if selected_rate_id else None
    current_mode = form_mode or ("edit" if selected_rate else "new")
    if current_mode == "edit" and not form_values and selected_rate:
        form_values = _rate_form_defaults(selected_rate)
    if not form_values:
        form_values = _rate_form_defaults()

    stats = {
        "total": len(rates),
        "active": sum(1 for row in rates if row["status_label"] == "Active"),
        "future": sum(1 for row in rates if row["status_label"] == "Future"),
        "expired": sum(1 for row in rates if row["status_label"] == "Expired"),
    }
    return (
        render_template(
            "tms/rates.html",
            rates=rates,
            selected_rate=selected_rate,
            form_mode=current_mode,
            form_values=form_values,
            form_error=form_error,
            stats=stats,
            today=date.today().isoformat(),
            search_query=search_query,
        ),
        status_code,
    )


def _serialize_contract_rate(rate):
    return {
        "contract_rate_id": rate["id"],
        "origin": rate["origin"],
        "destination": rate["destination"],
        "mode": rate["mode"],
        "currency": rate["currency"],
        "rate": rate["matched_rate"],
        "rate_field": rate["matched_rate_field"],
        "rate_label": rate["matched_rate_label"],
        "rate_20ft": rate["rate_20ft"],
        "rate_40ft": rate["rate_40ft"],
        "rate_40hc": rate["rate_40hc"],
        "valid_from": rate["valid_from"],
        "valid_to": rate["valid_to"],
    }


def _loadboard_location_region(location_value):
    parts = [part.strip() for part in _normalize_text(location_value).split(",") if part.strip()]
    if not parts:
        return ""
    return parts[-1]


def _loadboard_equipment_label(shipment):
    return _normalize_text(shipment.get("containers")) or _normalize_text(shipment.get("mode")) or "Unspecified"


def _rate_shop_weight_factor(raw_weight):
    try:
        weight = float(raw_weight or 0)
    except (TypeError, ValueError):
        return 1.0
    if weight <= 0:
        return 1.0
    return max(0.92, min(1.08, 1.0 + ((weight - 12000.0) / 100000.0)))


def _demo_variance(seed_text):
    digest = hashlib.sha256(seed_text.encode("utf-8")).hexdigest()
    scale = int(digest[:8], 16) / 0xFFFFFFFF
    return (scale * 0.30) - 0.15


def _estimate_rate_shop_transit_days(origin, destination, mode, lane=None):
    lane = lane or {}
    lane_days = lane.get("avg_transit_days")
    try:
        lane_days = int(lane_days or 0)
    except (TypeError, ValueError):
        lane_days = 0
    if lane_days > 0:
        return lane_days

    mode_key = _normalize_text(mode).lower()
    minimum_days = {
        "air": 1,
        "expedited": 1,
        "ftl": 2,
        "ltl": 3,
        "rail": 4,
        "intermodal": 4,
        "ocean": 12,
        "drayage": 1,
    }
    speed_by_mode = {
        "air": 3200,
        "expedited": 1400,
        "ftl": 900,
        "ltl": 700,
        "rail": 550,
        "intermodal": 550,
        "ocean": 450,
        "drayage": 240,
    }
    fallback_days = {
        "air": 1,
        "expedited": 1,
        "ftl": 2,
        "ltl": 4,
        "rail": 5,
        "intermodal": 5,
        "ocean": 18,
        "drayage": 1,
    }

    origin_coords = _lookup_location_coordinates(origin)
    destination_coords = _lookup_location_coordinates(destination)
    distance_km = _distance_km(origin_coords, destination_coords)
    if distance_km:
        speed = speed_by_mode.get(mode_key, 750)
        minimum = minimum_days.get(mode_key, 2)
        return max(minimum, ceil(distance_km / speed))
    return fallback_days.get(mode_key, 3)


def _rate_shop_form_defaults(source=None):
    source = source or {}
    return {
        "origin": _normalize_text(source.get("origin")),
        "destination": _normalize_text(source.get("destination")),
        "mode": _normalize_text(source.get("mode")),
        "weight": _normalize_text(source.get("weight")),
        "equipment_type": _normalize_text(source.get("equipment_type") or source.get("containers")),
        "date": _normalize_text(source.get("date")) or date.today().isoformat(),
    }


def _build_rate_shop_results(form_values):
    search_requested = any(_normalize_text(value) for value in form_values.values())
    required_fields = ("origin", "destination", "mode")
    missing_fields = [field for field in required_fields if not _normalize_text(form_values.get(field))]
    if missing_fields:
        return [], None, ("Enter origin, destination, and mode to shop rates." if search_requested else None)

    lookup_date = date.fromisoformat(_shipment_lookup_date(form_values.get("date") or date.today().isoformat())[:10])
    lookup_payload = lookup_api_rate(
        form_values["origin"],
        form_values["destination"],
        form_values["mode"],
        containers=form_values.get("equipment_type", ""),
        reference_date=lookup_date.isoformat(),
    )

    if not lookup_payload:
        return [], None, "No contract or historical market benchmark is available for this lane yet."

    lane = lookup_payload.get("lane") or {}
    transit_days = _estimate_rate_shop_transit_days(
        form_values["origin"],
        form_values["destination"],
        form_values["mode"],
        lane=lane,
    )
    history = lookup_payload.get("history") or {}
    contract_rate = lookup_payload.get("contract_rate") or {}
    base_rate = contract_rate.get("matched_rate") or history.get("rate_average")
    currency = contract_rate.get("currency") or history.get("currency") or "USD"
    weight_factor = _rate_shop_weight_factor(form_values.get("weight"))

    conn = get_db()
    try:
        carrier_rows = conn.execute(
            """
            SELECT id, name
            FROM tms_carriers
            WHERE active = 1
            ORDER BY name COLLATE NOCASE ASC, id ASC
            LIMIT 4
            """
        ).fetchall()
    finally:
        conn.close()

    results = []
    if contract_rate:
        results.append(
            {
                "carrier": "Contract benchmark",
                "carrier_id": None,
                "rate": round(float(contract_rate["matched_rate"]), 2),
                "transit_days": transit_days,
                "mode": form_values["mode"],
                "source": "Contract",
                "currency": contract_rate.get("currency") or currency,
                "detail": f"{contract_rate.get('matched_rate_label', 'Best')} contract through {contract_rate.get('valid_to', '-')}",
                "rate_field": contract_rate.get("matched_rate_label", ""),
            }
        )

    if history:
        results.append(
            {
                "carrier": "Market average",
                "carrier_id": None,
                "rate": round(float(history["rate_average"]), 2),
                "transit_days": transit_days,
                "mode": form_values["mode"],
                "source": "Market",
                "currency": history.get("currency") or currency,
                "detail": f"{int(history.get('sample_size') or 0)} historical shipment(s), low {float(history.get('rate_low') or 0):,.2f}, high {float(history.get('rate_high') or 0):,.2f}",
                "rate_field": "Historical avg",
            }
        )

    if base_rate:
        for carrier_row in carrier_rows:
            carrier = dict(carrier_row)
            variance = _demo_variance(
                "|".join(
                    [
                        form_values["origin"].lower(),
                        form_values["destination"].lower(),
                        form_values["mode"].lower(),
                        form_values.get("equipment_type", "").lower(),
                        lookup_date.isoformat(),
                        str(carrier["id"]),
                    ]
                )
            )
            simulated_rate = round(float(base_rate) * weight_factor * (1 + variance), 2)
            results.append(
                {
                    "carrier": carrier["name"],
                    "carrier_id": carrier["id"],
                    "rate": simulated_rate,
                    "transit_days": max(1, transit_days + (-1 if variance < -0.08 else 1 if variance > 0.08 else 0)),
                    "mode": form_values["mode"],
                    "source": "Spot",
                    "currency": currency,
                    "detail": f"Demo spot quote at {variance * 100:+.1f}% vs baseline",
                    "rate_field": "Spot demo",
                }
            )

    # ── Live carrier rates from connected integrations ─────────────────────────
    try:
        from tms.carrier_clients import get_all_live_rates
        origin_zip = form_values.get("origin", "").split()[-1] if form_values.get("origin") else ""
        dest_zip = form_values.get("destination", "").split()[-1] if form_values.get("destination") else ""
        weight_lbs = float(form_values.get("weight") or 0) * 2.20462
        if origin_zip.isdigit() and dest_zip.isdigit() and weight_lbs > 0:
            live = get_all_live_rates(origin_zip, dest_zip, weight_lbs)
            for lr in live:
                results.append({
                    "carrier": lr["carrier"],
                    "carrier_id": None,
                    "rate": round(float(lr["rate"]), 2),
                    "transit_days": lr.get("transit_days") or transit_days,
                    "mode": form_values["mode"],
                    "source": "Live",
                    "currency": lr.get("currency", "USD"),
                    "detail": f"Live rate · {lr.get('service','')}",
                    "rate_field": "Live API",
                })
    except Exception as _live_err:
        log.debug("Live rate fetch skipped: %s", _live_err)

    results.sort(
        key=lambda row: (
            float(row["rate"]),
            RATE_SHOP_SOURCE_PRIORITY.get(row["source"], 99),
            row["carrier"].lower(),
        )
    )
    for index, row in enumerate(results, start=1):
        row["rank"] = index
        prefill_params = {
            "origin": form_values["origin"],
            "destination": form_values["destination"],
            "mode": form_values["mode"],
            "weight_kg": form_values.get("weight"),
            "equipment_type": form_values.get("equipment_type"),
            "date": lookup_date.isoformat(),
            "freight_rate": f"{float(row['rate']):.2f}",
            "currency": row["currency"],
            "rate_source": row["source"],
            "selected_rate_label": row["carrier"],
            "transit_days": row["transit_days"],
        }
        if row["source"] == "Spot":
            prefill_params["carrier_id"] = row.get("carrier_id")
            prefill_params["carrier_name"] = row["carrier"]
        row["prefill_url"] = url_for(
            "tms.new_shipment",
            **{key: value for key, value in prefill_params.items() if value not in (None, "")},
        )

    return results, lookup_payload, None


def _default_loadboard_expiry(raw_etd):
    try:
        etd_date = date.fromisoformat(_shipment_lookup_date(raw_etd)[:10])
    except ValueError:
        etd_date = date.today()
    etd_expiry = datetime(etd_date.year, etd_date.month, etd_date.day, 23, 59) + timedelta(days=1)
    minimum_expiry = datetime.now().replace(second=0, microsecond=0) + timedelta(days=2)
    return max(etd_expiry, minimum_expiry)


def _sync_loadboard_posts(conn):
    eligible_rows = conn.execute(
        """
        SELECT s.shipment_ref, s.etd
        FROM shipments s
        LEFT JOIN load_shipments ls ON ls.shipment_ref = s.shipment_ref
        WHERE ls.shipment_ref IS NULL
          AND COALESCE(s.carrier_id, 0) = 0
          AND TRIM(COALESCE(s.carrier_name, '')) = ''
          AND s.status NOT IN ('Delivered', 'Cancelled')
        """
    ).fetchall()

    active_refs = []
    for row in eligible_rows:
        active_refs.append(row["shipment_ref"])
        expires_at = _default_loadboard_expiry(row["etd"]).strftime("%Y-%m-%d %H:%M:%S")
        existing_post = conn.execute(
            "SELECT shipment_ref FROM loadboard_posts WHERE shipment_ref = ?",
            (row["shipment_ref"],),
        ).fetchone()
        if existing_post:
            conn.execute(
                """
                UPDATE loadboard_posts
                SET expires_at = ?, status = 'Active'
                WHERE shipment_ref = ?
                """,
                (expires_at, row["shipment_ref"]),
            )
        else:
            conn.execute(
                """
                INSERT INTO loadboard_posts (shipment_ref, posted_at, expires_at, status, views)
                VALUES (?, CURRENT_TIMESTAMP, ?, 'Active', 0)
                """,
                (row["shipment_ref"], expires_at),
            )

    if active_refs:
        placeholders = ",".join("?" for _ in active_refs)
        conn.execute(
            f"""
            UPDATE loadboard_posts
            SET status = 'Closed'
            WHERE shipment_ref NOT IN ({placeholders})
            """,
            active_refs,
        )
    else:
        conn.execute("UPDATE loadboard_posts SET status = 'Closed'")


def _loadboard_filters(source=None):
    source = source or {}
    raw_date = _normalize_text(source.get("date"))
    if raw_date:
        raw_date = date.fromisoformat(_shipment_lookup_date(raw_date)[:10]).isoformat()
    return {
        "origin_region": _normalize_text(source.get("origin_region")),
        "equipment_type": _normalize_text(source.get("equipment_type")),
        "date": raw_date,
    }


def _get_loadboard_listing_context(*, public_board=False, filters=None):
    init_tms_db()
    filters = filters or _loadboard_filters()
    conn = get_db()
    try:
        _refresh_expired_tenders(conn)
        _sync_loadboard_posts(conn)
        rows = conn.execute(
            """
            SELECT
                s.id AS shipment_id,
                s.shipment_ref,
                s.origin_port,
                s.destination_port,
                s.mode,
                s.containers,
                s.weight_kg,
                s.freight_rate,
                s.currency,
                s.etd,
                p.posted_at,
                p.expires_at,
                p.status AS post_status,
                p.views,
                (
                    SELECT COUNT(*)
                    FROM tenders t
                    WHERE t.shipment_id = s.id AND t.status = 'Open'
                ) AS open_tenders,
                (
                    SELECT COUNT(*)
                    FROM tender_responses tr
                    JOIN tenders t ON t.id = tr.tender_id
                    WHERE t.shipment_id = s.id AND t.status = 'Open'
                ) AS interest_count
            FROM loadboard_posts p
            JOIN shipments s ON s.shipment_ref = p.shipment_ref
            WHERE p.status = 'Active'
            ORDER BY COALESCE(NULLIF(s.etd, ''), '9999-12-31') ASC, p.posted_at DESC, s.shipment_ref ASC
            """
        ).fetchall()

        load_rows = []
        origin_regions = set()
        equipment_types = set()
        for row in rows:
            shipment = dict(row)
            shipment["origin_region"] = _loadboard_location_region(shipment.get("origin_port"))
            shipment["equipment_label"] = _loadboard_equipment_label(shipment)
            shipment["date_value"] = _normalize_text(shipment.get("etd"))[:10]
            shipment["rate_offered_display"] = (
                f"{float(shipment['freight_rate']):,.2f} {shipment.get('currency') or 'USD'}"
                if shipment.get("freight_rate") is not None
                else "Rate pending"
            )
            shipment["posted_at_display"] = _format_tender_datetime(shipment.get("posted_at"))
            shipment["expires_at_display"] = _format_tender_datetime(shipment.get("expires_at"))
            shipment["post_status_class"] = LOADBOARD_POST_STATUS_STYLES.get(shipment["post_status"], "secondary")
            shipment["weight_display"] = f"{float(shipment.get('weight_kg') or 0):,.0f} kg"
            origin_regions.add(shipment["origin_region"])
            equipment_types.add(shipment["equipment_label"])

            if filters["origin_region"] and shipment["origin_region"].lower() != filters["origin_region"].lower():
                continue
            if filters["equipment_type"] and shipment["equipment_label"].lower() != filters["equipment_type"].lower():
                continue
            if filters["date"] and shipment["date_value"] != filters["date"]:
                continue
            load_rows.append(shipment)

        if public_board and load_rows:
            placeholders = ",".join("?" for _ in load_rows)
            conn.execute(
                f"UPDATE loadboard_posts SET views = views + 1 WHERE shipment_ref IN ({placeholders})",
                [row["shipment_ref"] for row in load_rows],
            )
            for shipment in load_rows:
                shipment["views"] = int(shipment.get("views") or 0) + 1

        conn.commit()
    finally:
        conn.close()

    stats = {
        "available": len(load_rows),
        "open_tenders": sum(int(row.get("open_tenders") or 0) for row in load_rows),
        "interest": sum(int(row.get("interest_count") or 0) for row in load_rows),
        "views": sum(int(row.get("views") or 0) for row in load_rows),
    }

    return {
        "public_board": public_board,
        "loadboard_rows": load_rows,
        "loadboard_filters": filters,
        "loadboard_stats": stats,
        "origin_region_options": sorted(option for option in origin_regions if option),
        "equipment_type_options": sorted(option for option in equipment_types if option),
        "public_loadboard_url": url_for("public.public_loadboard", _external=True),
    }


def _ensure_loadboard_interest_carrier(conn, *, name, contact_email="", contact_phone="", country=""):
    clean_name = _normalize_text(name)
    if not clean_name:
        raise ValueError("Carrier name is required.")

    carrier = conn.execute(
        "SELECT * FROM tms_carriers WHERE LOWER(name) = LOWER(?) LIMIT 1",
        (clean_name,),
    ).fetchone()
    if carrier:
        updates = {
            "country": _normalize_text(country) or carrier["country"],
            "contact_email": _normalize_text(contact_email) or carrier["contact_email"],
            "contact_phone": _normalize_text(contact_phone) or carrier["contact_phone"],
        }
        conn.execute(
            """
            UPDATE tms_carriers
            SET country = ?, contact_email = ?, contact_phone = ?, active = 1, updated_at = CURRENT_TIMESTAMP
            WHERE id = ?
            """,
            (
                updates["country"],
                updates["contact_email"],
                updates["contact_phone"],
                carrier["id"],
            ),
        )
        return conn.execute("SELECT * FROM tms_carriers WHERE id = ?", (carrier["id"],)).fetchone()

    cursor = conn.execute(
        """
        INSERT INTO tms_carriers (name, country, contact_email, contact_phone, active, updated_at)
        VALUES (?, ?, ?, ?, 1, CURRENT_TIMESTAMP)
        """,
        (
            clean_name,
            _normalize_text(country),
            _normalize_text(contact_email),
            _normalize_text(contact_phone),
        ),
    )
    return conn.execute("SELECT * FROM tms_carriers WHERE id = ?", (cursor.lastrowid,)).fetchone()


def _create_loadboard_interest_tender(conn, shipment_ref, *, carrier_name, contact_email="", contact_phone="", country=""):
    _refresh_expired_tenders(conn)
    _sync_loadboard_posts(conn)

    shipment = conn.execute(
        """
        SELECT s.*
        FROM shipments s
        JOIN loadboard_posts p ON p.shipment_ref = s.shipment_ref
        WHERE s.shipment_ref = ?
          AND p.status = 'Active'
          AND COALESCE(s.carrier_id, 0) = 0
          AND TRIM(COALESCE(s.carrier_name, '')) = ''
        """,
        (_normalize_text(shipment_ref),),
    ).fetchone()
    if not shipment:
        raise ValueError("That load is no longer available.")

    carrier = _ensure_loadboard_interest_carrier(
        conn,
        name=carrier_name,
        contact_email=contact_email,
        contact_phone=contact_phone,
        country=country,
    )

    tender = conn.execute(
        """
        SELECT *
        FROM tenders
        WHERE shipment_id = ?
          AND status = 'Open'
          AND datetime(deadline_at) > CURRENT_TIMESTAMP
        ORDER BY datetime(deadline_at) DESC, id DESC
        LIMIT 1
        """,
        (shipment["id"],),
    ).fetchone()
    if not tender:
        deadline = datetime.now().replace(minute=0, second=0, microsecond=0) + timedelta(days=2)
        cursor = conn.execute(
            """
            INSERT INTO tenders (shipment_id, deadline_at, notes, status, updated_at)
            VALUES (?, ?, ?, 'Open', CURRENT_TIMESTAMP)
            """,
            (
                shipment["id"],
                deadline.strftime("%Y-%m-%d %H:%M:%S"),
                "Created from load board carrier interest.",
            ),
        )
        tender_id = cursor.lastrowid
        conn.execute(
            "INSERT INTO shipment_events (shipment_id, event_type, description) VALUES (?,?,?)",
            (
                shipment["id"],
                "Tender Sent",
                f"Load board tender opened with deadline {deadline.strftime('%Y-%m-%d %H:%M')}",
            ),
        )
    else:
        tender_id = tender["id"]

    response = conn.execute(
        """
        SELECT *
        FROM tender_responses
        WHERE tender_id = ? AND carrier_id = ?
        ORDER BY id DESC
        LIMIT 1
        """,
        (tender_id, carrier["id"]),
    ).fetchone()
    if response:
        token = response["token"]
    else:
        token = _generate_tender_token(conn)
        conn.execute(
            """
            INSERT INTO tender_responses
                (tender_id, carrier_id, token, response_status, updated_at)
            VALUES (?, ?, ?, 'Pending', CURRENT_TIMESTAMP)
            """,
            (tender_id, carrier["id"], token),
        )

    conn.execute(
        "INSERT INTO shipment_events (shipment_id, event_type, description) VALUES (?,?,?)",
        (
            shipment["id"],
            "Load Board Interest",
            f"{carrier['name']} expressed interest from the load board.",
        ),
    )
    return token


def _refresh_expired_quotes(conn, shipment_id):
    conn.execute(
        """
        UPDATE quotes
        SET status = 'Expired'
        WHERE shipment_id = ?
          AND status = 'Pending'
          AND valid_until IS NOT NULL
          AND date(valid_until) < date(?)
        """,
        (shipment_id, date.today().isoformat()),
    )


def _get_quote_for_shipment(conn, shipment_id, quote_id):
    return conn.execute(
        """
        SELECT q.*, COALESCE(tc.name, '') AS carrier_name
        FROM quotes q
        LEFT JOIN tms_carriers tc ON tc.id = q.carrier_id
        WHERE q.id = ? AND q.shipment_id = ?
        """,
        (quote_id, shipment_id),
    ).fetchone()


def _create_shipment_quote(conn, shipment):
    valid_until_raw = (request.form.get("valid_until") or "").strip()
    if not valid_until_raw:
        raise ValueError("Validity date is required.")

    try:
        valid_until = date.fromisoformat(valid_until_raw)
    except ValueError as exc:
        raise ValueError("Validity date must be a valid date.") from exc

    rate_20ft = _parse_quote_amount(request.form.get("rate_20ft"), "20ft rate")
    rate_40ft = _parse_quote_amount(request.form.get("rate_40ft"), "40ft rate")
    rate_40hc = _parse_quote_amount(request.form.get("rate_40hc"), "40HC rate")
    if all(rate is None for rate in (rate_20ft, rate_40ft, rate_40hc)):
        raise ValueError("Enter at least one quote rate.")

    carrier_id, carrier_name = _get_or_create_carrier(conn, request.form.get("carrier_name"))
    status = "Expired" if valid_until < date.today() else "Pending"
    notes = (request.form.get("notes") or "").strip()

    conn.execute(
        """
        INSERT INTO quotes
            (shipment_id, carrier_id, rate_20ft, rate_40ft, rate_40hc, valid_until, status, notes)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            shipment["id"],
            carrier_id,
            rate_20ft,
            rate_40ft,
            rate_40hc,
            valid_until.isoformat(),
            status,
            notes,
        ),
    )
    conn.execute(
        "INSERT INTO shipment_events (shipment_id, event_type, description) VALUES (?,?,?)",
        (
            shipment["id"],
            "Quote Added",
            f"{carrier_name} quote added with validity through {valid_until.isoformat()}",
        ),
    )


def _accept_shipment_quote(conn, shipment, quote):
    if quote["status"] == "Expired":
        raise ValueError("Expired quotes cannot be accepted.")

    rate_field, rate_value = _resolve_quote_rate(shipment, quote)
    if rate_value is None:
        raise ValueError("This quote does not contain a usable rate for the shipment.")

    carrier_name = quote["carrier_name"] or shipment["carrier_name"] or "Carrier"
    conn.execute(
        """
        UPDATE quotes
        SET status = 'Rejected'
        WHERE shipment_id = ? AND id <> ? AND status IN ('Pending', 'Accepted')
        """,
        (shipment["id"], quote["id"]),
    )
    conn.execute("UPDATE quotes SET status='Accepted' WHERE id=?", (quote["id"],))
    conn.execute(
        """
        UPDATE shipments
        SET carrier_id = ?, carrier_name = ?, freight_rate = ?, contract_rate_id = NULL, updated_at = CURRENT_TIMESTAMP
        WHERE id = ?
        """,
        (quote["carrier_id"], carrier_name, rate_value, shipment["id"]),
    )
    conn.execute(
        "INSERT INTO shipment_events (shipment_id, event_type, description) VALUES (?,?,?)",
        (
            shipment["id"],
            "Quote Accepted",
            f"{carrier_name} accepted at {rate_value:,.2f} based on the {QUOTE_RATE_LABELS[rate_field]} rate",
        ),
    )


def _reject_shipment_quote(conn, shipment, quote):
    if quote["status"] == "Accepted":
        raise ValueError("Accepted quotes cannot be rejected. Accept another quote instead.")
    if quote["status"] == "Rejected":
        return

    carrier_name = quote["carrier_name"] or "Carrier"
    conn.execute("UPDATE quotes SET status='Rejected' WHERE id=?", (quote["id"],))
    conn.execute(
        "INSERT INTO shipment_events (shipment_id, event_type, description) VALUES (?,?,?)",
        (
            shipment["id"],
            "Quote Rejected",
            f"{carrier_name} quote rejected",
        ),
    )


def _build_quote_rows(shipment, raw_quotes):
    today = date.today()
    quotes = []
    for row in raw_quotes:
        quote = dict(row)
        rate_field, rate_value = _resolve_quote_rate(shipment, row)
        valid_until = None
        if row["valid_until"]:
            try:
                valid_until = date.fromisoformat(row["valid_until"])
            except ValueError:
                valid_until = None

        if valid_until is None:
            expiry_label = "No expiry"
            expiry_class = "secondary"
        elif valid_until < today:
            days_expired = (today - valid_until).days
            expiry_label = f"Expired {days_expired}d ago"
            expiry_class = "danger"
        elif valid_until == today:
            expiry_label = "Expires today"
            expiry_class = "warning"
        else:
            days_left = (valid_until - today).days
            expiry_label = f"{days_left}d left"
            expiry_class = "success" if days_left > 2 else "warning"

        quote["status_class"] = QUOTE_STATUS_STYLES.get(quote["status"], "secondary")
        quote["expiry_label"] = expiry_label
        quote["expiry_class"] = expiry_class
        quote["applied_rate"] = rate_value
        quote["applied_rate_label"] = QUOTE_RATE_LABELS.get(rate_field, "")
        quote["can_accept"] = quote["status"] not in {"Accepted", "Expired", "Rejected"}
        quote["can_reject"] = quote["status"] not in {"Accepted", "Rejected"}
        quotes.append(quote)
    return quotes


def _edi_sender_id(raw_value):
    token = re.sub(r"[^A-Za-z0-9]", "", raw_value or "").upper()
    return token[:15] or "TMSCLIENT"


def _load_edi_generation_shipment(conn, ref):
    return conn.execute(
        """
        SELECT s.*, COALESCE(tc.scac, '') AS carrier_scac
        FROM shipments s
        LEFT JOIN tms_carriers tc ON tc.id = s.carrier_id
        WHERE s.shipment_ref = ?
        """,
        (ref,),
    ).fetchone()


def _resolve_edi_partner_for_shipment(conn, shipment_ref, preferred_format="X12"):
    format_order = [preferred_format] + [item for item in EDI_PARTNER_FORMATS if item != preferred_format]
    for edi_format in format_order:
        partner = find_recent_edi_partner_for_shipment(conn, shipment_ref, edi_format=edi_format)
        if partner:
            return partner
    return None


def _edi_receiver_id(shipment, partner=None):
    if partner and partner.get("isa_id"):
        return partner["isa_id"]
    return shipment.get("carrier_scac") or _edi_sender_id(shipment.get("carrier_name", ""))


def _record_edi_outbound_204(conn, shipment_row, settings):
    shipment = dict(shipment_row)
    if generate_204 is None:
        raise ValueError("EDI 204 generation is unavailable in this environment.")
    partner = _resolve_edi_partner_for_shipment(conn, shipment["shipment_ref"], preferred_format="X12")
    raw_edi = generate_204(
        shipment,
        sender_id=_edi_sender_id(settings.get("company_name", "")),
        receiver_id=_edi_receiver_id(shipment, partner),
    )
    create_edi_transaction(
        conn,
        "outbound",
        "204",
        raw_edi,
        {
            "type": "204",
            "shipment_ref": shipment["shipment_ref"],
            "carrier_scac": shipment.get("carrier_scac", ""),
            "generated_at": datetime.utcnow().isoformat(timespec="seconds"),
        },
        shipment_ref=shipment["shipment_ref"],
        status="generated",
        edi_format="X12",
        partner_id=partner["id"] if partner else None,
    )
    conn.execute(
        """
        INSERT INTO shipment_events (shipment_id, event_type, description, created_by)
        VALUES (?, 'EDI 204', ?, 'system')
        """,
        (shipment["id"], "Outbound 204 generated for carrier tender."),
    )
    return raw_edi


def _record_edi_outbound_997(conn, inbound_record):
    parsed_payload = inbound_record.get("parsed_data") or {}
    if generate_997 is None:
        raise ValueError("EDI 997 generation is unavailable in this environment.")
    raw_edi = generate_997(parsed_payload)
    create_edi_transaction(
        conn,
        "outbound",
        "997",
        raw_edi,
        {
            "type": "997",
            "acknowledges_transaction_id": inbound_record["id"],
            "acknowledges_type": inbound_record.get("type", ""),
            "shipment_ref": inbound_record.get("shipment_ref", ""),
            "generated_at": datetime.utcnow().isoformat(timespec="seconds"),
        },
        shipment_ref=inbound_record.get("shipment_ref", ""),
        status="generated",
        edi_format="X12",
        partner_id=inbound_record.get("partner_id"),
    )
    return raw_edi


def _record_edi_status_notice(conn, shipment_row, settings, *, event=None):
    shipment = dict(shipment_row)
    partner = _resolve_edi_partner_for_shipment(conn, shipment["shipment_ref"], preferred_format="X12")
    if partner and partner.get("format") == "EDIFACT":
        if generate_iftsta is None:
            raise ValueError("EDIFACT IFTSTA generation is unavailable in this environment.")
        raw_edi = generate_iftsta(
            shipment,
            sender_id=_edi_sender_id(settings.get("company_name", "")),
            receiver_id=partner.get("isa_id", ""),
            event=event,
        )
        transaction_type = "IFTSTA"
        edi_format = "EDIFACT"
        event_type = "EDIFACT IFTSTA"
        description = "Outbound EDIFACT IFTSTA generated for shipment status update."
    else:
        if generate_214 is None:
            raise ValueError("EDI 214 generation is unavailable in this environment.")
        partner = partner or _resolve_edi_partner_for_shipment(conn, shipment["shipment_ref"], preferred_format="X12")
        raw_edi = generate_214(
            shipment,
            sender_id=_edi_sender_id(settings.get("company_name", "")),
            receiver_id=_edi_receiver_id(shipment, partner),
            event=event,
        )
        transaction_type = "214"
        edi_format = "X12"
        event_type = "EDI 214"
        description = "Outbound 214 generated for shipment status update."

    create_edi_transaction(
        conn,
        "outbound",
        transaction_type,
        raw_edi,
        {
            "type": transaction_type,
            "shipment_ref": shipment["shipment_ref"],
            "status": event.get("status") if event else shipment.get("status"),
            "generated_at": datetime.utcnow().isoformat(timespec="seconds"),
        },
        shipment_ref=shipment["shipment_ref"],
        status="generated",
        edi_format=edi_format,
        partner_id=partner["id"] if partner else None,
    )
    conn.execute(
        """
        INSERT INTO shipment_events (shipment_id, event_type, description, created_by)
        VALUES (?, ?, ?, 'system')
        """,
        (shipment["id"], event_type, description),
    )
    return raw_edi


def _parse_carrier_invoice_amount(raw_value):
    return _parse_quote_amount(raw_value, "Invoice amount")


def _parse_currency_code(raw_value):
    currency = _normalize_text(raw_value).upper()
    if not currency:
        raise ValueError("Currency is required.")
    if not re.fullmatch(r"[A-Z]{3}", currency):
        raise ValueError("Currency must be a 3-letter code such as USD or CAD.")
    return currency


def _calculate_carrier_invoice_variance(amount, baseline_amount):
    try:
        baseline = float(baseline_amount)
    except (TypeError, ValueError):
        return None
    if baseline <= 0:
        return None
    return round(((float(amount) - baseline) / baseline) * 100, 2)


def _is_carrier_invoice_flagged(variance_pct):
    if variance_pct is None:
        return False
    return abs(float(variance_pct)) > CARRIER_INVOICE_VARIANCE_THRESHOLD


def _carrier_invoice_form_defaults(source=None):
    source = source or {}
    return {
        "carrier_name": source.get("carrier_name", ""),
        "shipment_ref": source.get("shipment_ref", ""),
        "invoice_no": source.get("invoice_no", ""),
        "amount": source.get("amount", ""),
        "currency": source.get("currency", "USD"),
        "notes": source.get("notes", ""),
    }


def _find_single_reference_match(candidates, text):
    matches = []
    seen = set()
    for candidate in candidates:
        value = _normalize_text(candidate)
        key = value.lower()
        if not value or key in seen:
            continue
        if re.search(rf"(?<!\w){re.escape(value)}(?!\w)", text, re.IGNORECASE):
            matches.append(value)
            seen.add(key)
    return matches[0] if len(matches) == 1 else None


def _find_single_name_match(candidates, text):
    haystack = text.lower()
    matches = []
    seen = set()
    for candidate in candidates:
        value = _normalize_text(candidate)
        key = value.lower()
        if not value or key in seen:
            continue
        if key in haystack:
            matches.append(value)
            seen.add(key)
    return matches[0] if len(matches) == 1 else None


def _currency_from_symbol(symbol):
    return {
        "€": "EUR",
        "£": "GBP",
    }.get(symbol)


def _extract_carrier_invoice_pdf_fields(conn, upload):
    filename = _normalize_text(getattr(upload, "filename", ""))
    if not filename:
        return {}, []
    if not filename.lower().endswith(".pdf"):
        raise ValueError("Invoice upload must be a PDF file.")

    shipment_refs = [
        row["shipment_ref"]
        for row in conn.execute(
            "SELECT shipment_ref FROM shipments WHERE shipment_ref IS NOT NULL AND TRIM(shipment_ref) != ''"
        ).fetchall()
    ]
    carrier_names = [
        row["name"]
        for row in conn.execute(
            """
            SELECT name FROM tms_carriers WHERE name IS NOT NULL AND TRIM(name) != ''
            UNION
            SELECT DISTINCT carrier_name AS name
            FROM shipments
            WHERE carrier_name IS NOT NULL AND TRIM(carrier_name) != ''
            """
        ).fetchall()
    ]

    try:
        payload = extract_document_payload(upload, known_shipment_refs=shipment_refs)
    except ValueError as exc:
        return {}, [str(exc)]

    text = _normalize_text(payload.get("text_excerpt", ""))
    if not text:
        return {}, ["No readable text was found in the PDF. Enter the invoice fields manually."]

    fields = {}
    shipment_ref = _normalize_text(payload.get("fields", {}).get("shipment_ref")) or _find_single_reference_match(
        shipment_refs, text
    )
    if shipment_ref:
        fields["shipment_ref"] = shipment_ref

    carrier_name = _find_single_name_match(carrier_names, text)
    if carrier_name:
        fields["carrier_name"] = carrier_name

    invoice_match = re.search(
        r"(?:invoice\s*(?:no\.?|number|#)|inv\s*#)\s*[:#-]?\s*([A-Za-z0-9/-]+)",
        text,
        re.IGNORECASE,
    )
    if invoice_match:
        fields["invoice_no"] = invoice_match.group(1).strip()

    extracted_amount = payload.get("fields", {}).get("amount")
    if extracted_amount is not None:
        try:
            fields["amount"] = round(float(extracted_amount), 2)
        except (TypeError, ValueError):
            pass

    amount_match = re.search(
        r"(?:invoice\s*total|amount\s*due|total\s*due|balance\s*due)\s*[:#-]?\s*(?:(USD|CAD|EUR|GBP)\s*)?([€£$])?\s*([0-9][0-9,]*(?:\.\d{2})?)",
        text,
        re.IGNORECASE,
    )
    if amount_match:
        if "amount" not in fields:
            fields["amount"] = round(float(amount_match.group(3).replace(",", "")), 2)
        currency_code = (amount_match.group(1) or "").upper() or _currency_from_symbol(amount_match.group(2) or "")
        if currency_code:
            fields["currency"] = currency_code

    notices = list(payload.get("warnings", []))
    if not fields:
        notices.append("PDF scanned but no invoice fields could be extracted.")
    else:
        missing = [
            label
            for key, label in (
                ("carrier_name", "carrier"),
                ("shipment_ref", "shipment reference"),
                ("invoice_no", "invoice number"),
                ("amount", "amount"),
                ("currency", "currency"),
            )
            if key not in fields
        ]
        if missing:
            notices.append(f"PDF scanned. Complete the remaining fields manually: {', '.join(missing)}.")
        else:
            notices.append("PDF scanned and all core invoice fields were extracted.")
    return fields, notices


def _append_carrier_invoice_note(existing_notes, status, note_text):
    note_text = _normalize_text(note_text)
    existing_notes = _normalize_text(existing_notes)
    if not note_text:
        return existing_notes
    entry = f"[{datetime.now().strftime('%Y-%m-%d %H:%M')}] {status}: {note_text}"
    if not existing_notes:
        return entry
    return f"{existing_notes}\n{entry}"


def _load_carrier_invoice(conn, invoice_id):
    return conn.execute(
        "SELECT * FROM carrier_invoices WHERE id = ?",
        (invoice_id,),
    ).fetchone()


def _hydrate_carrier_invoice_row(row):
    invoice = dict(row)
    variance_pct = invoice.get("variance_pct")
    invoice["status_class"] = CARRIER_INVOICE_STATUS_STYLES.get(invoice["status"], "secondary")
    invoice["flagged"] = _is_carrier_invoice_flagged(variance_pct)
    invoice["amount_display"] = f"{float(invoice['amount'] or 0):,.2f}"
    contracted_rate = invoice.get("contracted_rate")
    invoice["contracted_rate_display"] = (
        f"{float(contracted_rate):,.2f}" if contracted_rate is not None else "-"
    )
    invoice["matched"] = bool(invoice.get("matched_shipment_id"))
    invoice["route_label"] = f"{invoice.get('origin_port') or '-'} -> {invoice.get('destination_port') or '-'}"
    invoice["variance_display"] = "No baseline"
    invoice["variance_class"] = "secondary"
    if variance_pct is not None:
        invoice["variance_display"] = f"{float(variance_pct):+.2f}%"
        if invoice["flagged"]:
            invoice["variance_class"] = "danger"
        elif float(variance_pct) > 0:
            invoice["variance_class"] = "warning"
        else:
            invoice["variance_class"] = "success"
    invoice["can_approve"] = invoice["status"] in {"Pending", "Disputed"}
    invoice["can_dispute"] = invoice["status"] in {"Pending", "Approved"}
    invoice["can_pay"] = invoice["status"] == "Approved"
    return invoice


def _list_carrier_invoice_rows(conn, status_filter=""):
    params = []
    where_sql = ""
    if status_filter:
        where_sql = "WHERE ci.status = ?"
        params.append(status_filter)

    rows = conn.execute(
        f"""
        SELECT
            ci.*,
            s.id AS matched_shipment_id,
            s.freight_rate AS contracted_rate,
            s.origin_port,
            s.destination_port
        FROM carrier_invoices ci
        LEFT JOIN shipments s ON s.shipment_ref = ci.shipment_ref
        {where_sql}
        ORDER BY
            CASE ci.status
                WHEN 'Pending' THEN 0
                WHEN 'Disputed' THEN 1
                WHEN 'Approved' THEN 2
                WHEN 'Paid' THEN 3
                ELSE 4
            END,
            ci.created_at DESC
        """,
        params,
    ).fetchall()
    return [_hydrate_carrier_invoice_row(row) for row in rows]


def _carrier_invoice_summary(conn):
    return {
        "total": conn.execute("SELECT COUNT(*) FROM carrier_invoices").fetchone()[0],
        "pending": conn.execute("SELECT COUNT(*) FROM carrier_invoices WHERE status = 'Pending'").fetchone()[0],
        "flagged": conn.execute(
            "SELECT COUNT(*) FROM carrier_invoices WHERE variance_pct IS NOT NULL AND ABS(variance_pct) > ?",
            (CARRIER_INVOICE_VARIANCE_THRESHOLD,),
        ).fetchone()[0],
        "approved_count": conn.execute(
            "SELECT COUNT(*) FROM carrier_invoices WHERE status IN ('Approved', 'Paid')"
        ).fetchone()[0],
        "approved_total": conn.execute(
            "SELECT COALESCE(SUM(amount), 0) FROM carrier_invoices WHERE status IN ('Approved', 'Paid')"
        ).fetchone()[0],
    }


def _parse_tender_deadline(raw_value):
    value = (raw_value or "").strip()
    if not value:
        raise ValueError("Tender deadline is required.")
    try:
        deadline = datetime.fromisoformat(value.replace("T", " "))
    except ValueError as exc:
        raise ValueError("Tender deadline must be a valid date and time.") from exc

    deadline = deadline.replace(second=0, microsecond=0)
    if deadline <= datetime.now():
        raise ValueError("Tender deadline must be in the future.")
    return deadline


def _parse_tender_datetime(raw_value):
    value = (raw_value or "").strip()
    if not value:
        return None
    for candidate in (value, value.replace("T", " ")):
        try:
            return datetime.fromisoformat(candidate)
        except ValueError:
            continue
    return None


def _format_tender_datetime(raw_value):
    parsed = _parse_tender_datetime(raw_value)
    if not parsed:
        return raw_value or "-"
    return parsed.strftime("%Y-%m-%d %H:%M")


def _build_deadline_meta(deadline_at):
    parsed = _parse_tender_datetime(deadline_at)
    if not parsed:
        return {
            "display": deadline_at or "-",
            "label": "Deadline unavailable",
            "badge_class": "secondary",
            "is_expired": False,
        }

    now = datetime.now()
    display = parsed.strftime("%Y-%m-%d %H:%M")
    if parsed <= now:
        elapsed_hours = int((now - parsed).total_seconds() // 3600)
        if elapsed_hours < 1:
            label = "Expired"
        elif elapsed_hours < 24:
            label = f"Expired {elapsed_hours}h ago"
        else:
            label = f"Expired {(now.date() - parsed.date()).days}d ago"
        return {
            "display": display,
            "label": label,
            "badge_class": "danger",
            "is_expired": True,
        }

    hours_left = int(max(1, (parsed - now).total_seconds() // 3600))
    if hours_left < 24:
        label = f"{hours_left}h left"
        badge_class = "warning"
    else:
        label = f"{max(1, hours_left // 24)}d left"
        badge_class = "success"
    return {
        "display": display,
        "label": label,
        "badge_class": badge_class,
        "is_expired": False,
    }


def _default_tender_deadline_value():
    return (datetime.now().replace(minute=0, second=0, microsecond=0) + timedelta(days=1)).strftime("%Y-%m-%dT%H:%M")


def _parse_tender_carrier_ids(raw_values):
    carrier_ids = []
    for raw_value in raw_values:
        value = (raw_value or "").strip()
        if not value:
            continue
        if not value.isdigit():
            raise ValueError("Select valid carriers for the tender.")
        carrier_id = int(value)
        if carrier_id not in carrier_ids:
            carrier_ids.append(carrier_id)
    if not carrier_ids:
        raise ValueError("Select at least one carrier.")
    return carrier_ids


def _generate_tender_token(conn):
    while True:
        token = secrets.token_urlsafe(24)
        exists = conn.execute(
            "SELECT 1 FROM tender_responses WHERE token = ? LIMIT 1",
            (token,),
        ).fetchone()
        if not exists:
            return token


def _parse_transit_days(raw_value):
    value = (raw_value or "").strip()
    if not value:
        raise ValueError("Transit days is required.")
    try:
        parsed = int(value)
    except ValueError as exc:
        raise ValueError("Transit days must be a whole number.") from exc
    if parsed <= 0:
        raise ValueError("Transit days must be greater than 0.")
    return parsed


def _refresh_expired_tenders(conn):
    now_value = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    conn.execute(
        """
        UPDATE tenders
        SET status = 'Expired', updated_at = CURRENT_TIMESTAMP
        WHERE status = 'Open'
          AND datetime(deadline_at) < datetime(?)
        """,
        (now_value,),
    )
    conn.execute(
        """
        UPDATE tender_responses
        SET response_status = 'Expired', updated_at = CURRENT_TIMESTAMP
        WHERE response_status = 'Pending'
          AND tender_id IN (
              SELECT id
              FROM tenders
              WHERE status = 'Expired'
          )
        """
    )


def _build_tender_rows(conn, *, shipment_id=None):
    params = []
    shipment_filter = ""
    if shipment_id is not None:
        shipment_filter = "WHERE t.shipment_id = ?"
        params.append(shipment_id)

    raw_tenders = conn.execute(
        f"""
        SELECT
            t.*,
            s.shipment_ref,
            s.origin_port,
            s.destination_port,
            s.containers,
            s.carrier_name AS shipment_carrier_name,
            s.freight_rate AS shipment_freight_rate,
            s.currency
        FROM tenders t
        JOIN shipments s ON s.id = t.shipment_id
        {shipment_filter}
        ORDER BY
            CASE t.status
                WHEN 'Open' THEN 0
                WHEN 'Awarded' THEN 1
                WHEN 'Expired' THEN 2
                ELSE 3
            END,
            datetime(t.deadline_at) ASC,
            t.created_at DESC
        """,
        params,
    ).fetchall()
    if not raw_tenders:
        return []

    tenders = []
    tender_lookup = {}
    for row in raw_tenders:
        tender = dict(row)
        deadline_meta = _build_deadline_meta(tender["deadline_at"])
        tender["status_class"] = TENDER_STATUS_STYLES.get(tender["status"], "secondary")
        tender["deadline_display"] = deadline_meta["display"]
        tender["deadline_label"] = deadline_meta["label"]
        tender["deadline_class"] = deadline_meta["badge_class"]
        tender["responses"] = []
        tender["submitted_count"] = 0
        tender["pending_count"] = 0
        tender["awarded_count"] = 0
        tender["best_rate"] = None
        tender["best_carrier_name"] = ""
        tender["awarded_response"] = None
        tenders.append(tender)
        tender_lookup[tender["id"]] = tender

    placeholders = ",".join("?" for _ in tender_lookup)
    raw_responses = conn.execute(
        f"""
        SELECT tr.*, COALESCE(tc.name, '') AS carrier_name
        FROM tender_responses tr
        LEFT JOIN tms_carriers tc ON tc.id = tr.carrier_id
        WHERE tr.tender_id IN ({placeholders})
        ORDER BY
            CASE tr.response_status
                WHEN 'Awarded' THEN 0
                WHEN 'Submitted' THEN 1
                WHEN 'Pending' THEN 2
                WHEN 'Expired' THEN 3
                ELSE 4
            END,
            COALESCE(tr.submitted_at, tr.created_at) ASC,
            tr.id ASC
        """,
        list(tender_lookup),
    ).fetchall()

    for row in raw_responses:
        response = dict(row)
        tender = tender_lookup[response["tender_id"]]
        rate_field, rate_value = _resolve_quote_rate(tender, response)
        response["response_status_class"] = TENDER_RESPONSE_STATUS_STYLES.get(response["response_status"], "secondary")
        response["applied_rate"] = rate_value
        response["applied_rate_label"] = QUOTE_RATE_LABELS.get(rate_field, "")
        response["submitted_at_display"] = _format_tender_datetime(response["submitted_at"] or response["updated_at"] or response["created_at"])
        response["response_link"] = url_for("tms.respond_to_tender", token=response["token"], _external=True)
        response["can_award"] = tender["status"] == "Open" and response["response_status"] == "Submitted" and rate_value is not None
        tender["responses"].append(response)

        if response["response_status"] in {"Submitted", "Awarded"}:
            tender["submitted_count"] += 1
        if response["response_status"] == "Pending":
            tender["pending_count"] += 1
        if response["response_status"] == "Awarded":
            tender["awarded_count"] += 1

        if response["response_status"] in {"Submitted", "Awarded"} and rate_value is not None:
            if tender["best_rate"] is None or rate_value < tender["best_rate"]:
                tender["best_rate"] = rate_value
                tender["best_carrier_name"] = response["carrier_name"] or ""

        if tender.get("awarded_response_id") == response["id"]:
            tender["awarded_response"] = response

    return tenders


def _load_tender_response(conn, token):
    return conn.execute(
        """
        SELECT
            tr.*,
            t.shipment_id,
            t.deadline_at,
            t.notes AS tender_notes,
            t.status AS tender_status,
            t.awarded_response_id,
            s.shipment_ref,
            s.origin_port,
            s.destination_port,
            s.containers,
            s.cargo_description,
            s.etd,
            s.eta,
            s.currency,
            COALESCE(tc.name, '') AS carrier_name
        FROM tender_responses tr
        JOIN tenders t ON t.id = tr.tender_id
        JOIN shipments s ON s.id = t.shipment_id
        LEFT JOIN tms_carriers tc ON tc.id = tr.carrier_id
        WHERE tr.token = ?
        """,
        (token,),
    ).fetchone()


def _build_tender_response_context(response_row):
    response = dict(response_row)
    deadline_meta = _build_deadline_meta(response["deadline_at"])
    rate_field, rate_value = _resolve_quote_rate(response, response)
    response["deadline_display"] = deadline_meta["display"]
    response["deadline_label"] = deadline_meta["label"]
    response["deadline_class"] = deadline_meta["badge_class"]
    response["response_status_class"] = TENDER_RESPONSE_STATUS_STYLES.get(response["response_status"], "secondary")
    response["submitted_at_display"] = _format_tender_datetime(response["submitted_at"] or response["updated_at"] or response["created_at"])
    response["applied_rate"] = rate_value
    response["applied_rate_label"] = QUOTE_RATE_LABELS.get(rate_field, "")
    response["is_awarded"] = response.get("awarded_response_id") == response["id"]
    response["is_closed"] = response["tender_status"] != "Open" or deadline_meta["is_expired"]
    return response


def _get_shipment_view_context(ref):
    snapshot = get_tracking_page_context(ref)
    if not snapshot:
        return None

    conn = get_db()
    try:
        _refresh_expired_tenders(conn)
        conn.commit()
        tender_carriers = conn.execute(
            "SELECT id, name FROM tms_carriers WHERE active = 1 ORDER BY name COLLATE NOCASE ASC"
        ).fetchall()
        shipment_tenders = _build_tender_rows(conn, shipment_id=snapshot["shipment"]["id"])
    finally:
        conn.close()

    driver_tracking_token = get_or_create_tracking_driver_token(
        ref,
        snapshot["shipment"].get("carrier_id"),
    )
    dock_appointment = get_dock_appointment(shipment_ref=ref)
    dock_booking_token = get_or_create_dock_booking_token(ref)
    pod_record = get_pod_record(ref)
    pod_token = get_or_create_pod_token(ref)
    pod_capture_url = (
        url_for("tms.capture_pod", ref=ref, token=pod_token, _external=True)
        if "tms.capture_pod" in current_app.view_functions
        else ""
    )
    pod_photo_url = (
        url_for("tms.pod_photo", ref=ref, token=pod_token)
        if pod_record and pod_record.get("photo_available") and "tms.pod_photo" in current_app.view_functions
        else ""
    )

    # Predictive ETA
    predicted_eta = None
    try:
        from predictive_eta import get_predicted_eta
        ship = snapshot["shipment"]
        predicted_eta = get_predicted_eta(
            carrier=ship.get("carrier_name") or "",
            origin=ship.get("origin_port") or "",
            destination=ship.get("destination_port") or "",
            scheduled_eta=ship.get("eta") or "",
        )
    except Exception:
        pass

    return {
        "shipment": snapshot["shipment"],
        "sc": SHIPMENT_STATUS_STYLES,
        "events": snapshot["events"],
        "tracking": snapshot["tracking"],
        "tracking_map": snapshot["tracking_map"],
        "tracking_pings": snapshot["tracking_pings"],
        "predicted_eta": predicted_eta,
        "pod_record": pod_record,
        "pod_token": pod_token,
        "pod_capture_url": pod_capture_url,
        "pod_photo_url": pod_photo_url,
        "documents_enabled": all(
            generator is not None
            for generator in (generate_bol, generate_invoice, generate_packing_list)
        ),
        "tracking_url": build_public_tracking_url(ref, external=True),
        "driver_tracking_token": driver_tracking_token,
        "driver_tracking_url": url_for("tms.driver_tracking_page", token=driver_tracking_token, _external=True),
        "driver_checkin_url": url_for(
            "tms.driver_checkin",
            token=snapshot["shipment"]["driver_checkin_token"],
            _external=True,
        )
        if snapshot["shipment"].get("driver_checkin_token")
        else "",
        "dock_appointment": dock_appointment,
        "dock_booking_url": url_for("tms.carrier_dock_booking", token=dock_booking_token, _external=True),
        "tender_carriers": tender_carriers,
        "shipment_tenders": shipment_tenders,
        "default_tender_deadline": _default_tender_deadline_value(),
        "shipment_claims": [_build_claim_view_model(claim) for claim in list_freight_claims(shipment_ref=ref)],
        "claim_status_styles": CLAIM_STATUS_STYLES,
    }


def _get_load_board_context(selected_load_ref=None, *, form_values=None, form_error=None):
    init_tms_db()
    loads = list_loads()
    available_shipments = list_available_load_shipments()
    conn = get_db()
    try:
        carriers = conn.execute(
            "SELECT id, name FROM tms_carriers WHERE active = 1 ORDER BY name COLLATE NOCASE ASC"
        ).fetchall()
    finally:
        conn.close()

    selected_load = None
    if selected_load_ref:
        selected_load = get_load_snapshot(selected_load_ref)

    form_values = form_values or {}
    normalized_form_values = {
        "carrier_id": (form_values.get("carrier_id") or "").strip(),
        "status": (form_values.get("status") or LOAD_STATUSES[0]).strip() or LOAD_STATUSES[0],
        "shipment_refs": [ref for ref in form_values.get("shipment_refs", []) if ref],
    }

    stats = {
        "total": len(loads),
        "planning": sum(1 for load in loads if load["status"] == "Planning"),
        "in_transit": sum(1 for load in loads if load["status"] == "In Transit"),
        "assigned_shipments": sum(load["shipment_count"] for load in loads),
        "available_shipments": len(available_shipments),
    }

    return {
        "loads": loads,
        "selected_load": selected_load,
        "available_shipments": available_shipments,
        "available_shipments_json": available_shipments,
        "load_carriers": carriers,
        "load_status_styles": LOAD_STATUS_STYLES,
        "load_statuses": LOAD_STATUSES,
        "load_stats": stats,
        "load_form_values": normalized_form_values,
        "load_form_error": form_error,
    }


def _document_review_from_form():
    warnings = [warning.strip() for warning in request.form.getlist("warning") if warning.strip()]
    return {
        "filename": _normalize_text(request.form.get("filename")) or "document",
        "doc_type": _normalize_text(request.form.get("doc_type")) or "Unknown",
        "extraction_method": _normalize_text(request.form.get("extraction_method")) or "manual-review",
        "warnings": warnings,
        "text_excerpt": _normalize_text(request.form.get("text_excerpt")),
        "fields": {
            "shipment_ref": _normalize_text(request.form.get("shipment_ref")),
            "shipper": _normalize_text(request.form.get("shipper")),
            "consignee": _normalize_text(request.form.get("consignee")),
            "origin": _normalize_text(request.form.get("origin")),
            "destination": _normalize_text(request.form.get("destination")),
            "amount": _normalize_text(request.form.get("amount")),
            "dates": _normalize_text(request.form.get("dates")),
        },
    }


def _blank_intake_field():
    return {"value": "", "confidence": 0, "source": ""}


def _hydrate_intake_review(intake_record):
    payload = dict((intake_record or {}).get("extracted_json") or {})
    fields = {}
    existing_fields = payload.get("fields") or {}
    for key in INTAKE_FIELD_ORDER:
        field = existing_fields.get(key) or {}
        if isinstance(field, dict):
            fields[key] = {
                "value": _normalize_text(field.get("value")),
                "confidence": int(field.get("confidence") or 0),
                "source": _normalize_text(field.get("source")),
            }
        else:
            fields[key] = _blank_intake_field()
            fields[key]["value"] = _normalize_text(field)
    payload["fields"] = fields
    payload["warnings"] = [_normalize_text(warning) for warning in payload.get("warnings", []) if _normalize_text(warning)]
    payload["source_name"] = _normalize_text(payload.get("source_name")) or (intake_record or {}).get("source_name") or "Email text"
    payload["source_kind"] = _normalize_text(payload.get("source_kind")) or (intake_record or {}).get("source_kind") or "email_text"
    payload["text_excerpt"] = _normalize_text(payload.get("text_excerpt")) or (intake_record or {}).get("text_excerpt") or ""
    payload["reviewed_at"] = _normalize_text(payload.get("reviewed_at"))
    return payload


def _intake_confidence_from_fields(fields):
    scores = [int(field.get("confidence") or 0) for field in (fields or {}).values() if _normalize_text(field.get("value"))]
    return int(round(sum(scores) / len(scores))) if scores else 0


def _reviewed_intake_payload(intake_record):
    payload = _hydrate_intake_review(intake_record)
    reviewed_fields = {}
    for key in INTAKE_FIELD_ORDER:
        original = payload["fields"].get(key) or _blank_intake_field()
        reviewed_fields[key] = {
            "value": _normalize_text(request.form.get(key)),
            "confidence": int(original.get("confidence") or 0),
            "source": _normalize_text(original.get("source")),
        }
    payload["fields"] = reviewed_fields
    payload["reviewed_at"] = datetime.utcnow().isoformat(timespec="seconds")
    return payload, _intake_confidence_from_fields(reviewed_fields)


def _parse_intake_date(value, label):
    raw_value = _normalize_text(value)
    if not raw_value:
        return ""

    for fmt in ("%Y-%m-%d", "%Y/%m/%d", "%b %d, %Y", "%B %d, %Y", "%d %b %Y", "%d %B %Y"):
        try:
            return datetime.strptime(raw_value, fmt).date().isoformat()
        except ValueError:
            continue

    if "/" in raw_value:
        first, second, year = raw_value.split("/")
        try:
            first_number = int(first)
            second_number = int(second)
        except ValueError as exc:
            raise ValueError(f"{label} must be a valid date.") from exc
        if first_number > 12:
            fmt = "%d/%m/%Y" if len(year) == 4 else "%d/%m/%y"
        elif second_number > 12:
            fmt = "%m/%d/%Y" if len(year) == 4 else "%m/%d/%y"
        else:
            raise ValueError(f"{label} is ambiguous. Use YYYY-MM-DD.")
        try:
            return datetime.strptime(raw_value, fmt).date().isoformat()
        except ValueError as exc:
            raise ValueError(f"{label} must be a valid date.") from exc

    raise ValueError(f"{label} must be a valid date.")


def _parse_intake_weight_to_kg(value):
    raw_value = _normalize_text(value)
    if not raw_value:
        return ""
    match = re.search(
        r"(?P<amount>\d[\d,]*(?:\.\d+)?)\s*(?P<unit>kg|kgs|kilograms?|lb|lbs|pounds?|mt|metric tons?|tonnes?)?\b",
        raw_value,
        re.IGNORECASE,
    )
    if not match:
        raise ValueError("Weight must be a number or include KG, LB, or MT units.")

    amount = float(match.group("amount").replace(",", ""))
    unit = (match.group("unit") or "kg").lower()
    if unit in {"kg", "kgs", "kilogram", "kilograms"}:
        return round(amount, 2)
    if unit in {"lb", "lbs", "pound", "pounds"}:
        return round(amount * 0.45359237, 2)
    if unit in {"mt", "metric ton", "metric tons", "tonne", "tonnes"}:
        return round(amount * 1000, 2)
    raise ValueError("Weight units must be KG, LB, or MT.")


def _parse_intake_rate_value(value):
    raw_value = _normalize_text(value)
    if not raw_value:
        return ""
    match = re.search(r"(\d[\d,]*(?:\.\d{1,2})?)", raw_value)
    if not match:
        raise ValueError("Rate must contain a valid amount.")
    return round(float(match.group(1).replace(",", "")), 2)


def _build_shipment_payload_from_intake(review_payload, intake_id):
    fields = review_payload.get("fields") or {}
    source_name = _normalize_text(review_payload.get("source_name")) or f"intake-{intake_id}"
    return {
        "status": "Draft",
        "customer_name": _normalize_text(fields.get("shipper", {}).get("value")),
        "shipper_name": _normalize_text(fields.get("shipper", {}).get("value")),
        "shipper_address": "",
        "consignee_name": _normalize_text(fields.get("consignee", {}).get("value")),
        "consignee_address": "",
        "carrier_name": "",
        "origin_port": _normalize_text(fields.get("origin", {}).get("value")),
        "destination_port": _normalize_text(fields.get("destination", {}).get("value")),
        "mode": "",
        "etd": _parse_intake_date(fields.get("etd", {}).get("value"), "ETD") if _normalize_text(fields.get("etd", {}).get("value")) else "",
        "eta": _parse_intake_date(fields.get("eta", {}).get("value"), "ETA") if _normalize_text(fields.get("eta", {}).get("value")) else "",
        "cargo_description": _normalize_text(fields.get("cargo_description", {}).get("value")),
        "containers": _normalize_text(fields.get("containers", {}).get("value")),
        "weight_kg": _parse_intake_weight_to_kg(fields.get("weight", {}).get("value")) if _normalize_text(fields.get("weight", {}).get("value")) else "",
        "volume_cbm": "",
        "freight_rate": _parse_intake_rate_value(fields.get("rate", {}).get("value")) if _normalize_text(fields.get("rate", {}).get("value")) else "",
        "currency": _normalize_text(fields.get("currency", {}).get("value")).upper(),
        "incoterm": _normalize_text(fields.get("incoterm", {}).get("value")).upper(),
        "notes": f"Source: {source_name}",
    }


def _carrier_form_defaults(row=None):
    row = dict(row) if row else {}
    return {
        "id": row.get("id"),
        "name": row.get("name", ""),
        "scac": row.get("scac", "") or "",
        "dot_number": row.get("dot_number", "") or "",
        "mc_number": row.get("mc_number", "") or "",
        "contact_name": row.get("contact_name", "") or "",
        "country": row.get("country", "") or "",
        "contact_email": row.get("contact_email", "") or "",
        "contact_phone": row.get("contact_phone", "") or "",
        "address": row.get("address", "") or "",
        "city": row.get("city", "") or "",
        "state_province": row.get("state_province", "") or "",
        "postal_code": row.get("postal_code", "") or "",
        "equipment_types": row.get("equipment_types", "") or "",
        "service_areas": row.get("service_areas", "") or "",
        "insurance_company": row.get("insurance_company", "") or "",
        "insurance_policy": row.get("insurance_policy", "") or "",
        "cargo_insurance_amount": row.get("cargo_insurance_amount", "") or "",
        "liability_amount": row.get("liability_amount", "") or "",
        "payment_terms": row.get("payment_terms", "NET30") or "NET30",
        "active": 1 if row.get("active", 1) else 0,
    }


def _carrier_return_args():
    query = (request.values.get("q") or "").strip()
    page = request.values.get("page", type=int) or 1
    return {"q": query, "page": max(page, 1)}


def _carrier_page_numbers(page, page_count):
    start = max(1, page - 2)
    end = min(page_count, page + 2)
    return list(range(start, end + 1))


def _render_carriers_page(selected_carrier_id=None, form_mode=None, form_carrier=None):
    page = request.values.get("page", type=int) or 1
    search_query = (request.values.get("q") or "").strip()
    carrier_listing = list_carriers(page=page, page_size=25, search_query=search_query)

    selected_carrier = None
    shipment_history = []
    carrier_stats = {
        "shipments": 0,
        "delivered": 0,
        "active": 0,
        "revenue": 0,
    }

    if selected_carrier_id is None and carrier_listing["rows"]:
        selected_carrier_id = carrier_listing["rows"][0]["id"]

    if selected_carrier_id:
        selected_carrier, shipment_history, carrier_stats = get_carrier_with_history(selected_carrier_id)

    if form_mode == "edit" and not form_carrier and selected_carrier:
        form_carrier = _carrier_form_defaults(selected_carrier)
    elif form_mode == "new" and not form_carrier:
        form_carrier = _carrier_form_defaults()

    return render_template(
        "tms/carriers.html",
        carriers=carrier_listing["rows"],
        carrier_listing=carrier_listing,
        page_numbers=_carrier_page_numbers(carrier_listing["page"], carrier_listing["page_count"]),
        selected_carrier=selected_carrier,
        shipment_history=shipment_history,
        carrier_stats=carrier_stats,
        form_mode=form_mode,
        form_carrier=form_carrier,
        return_args={"q": search_query, "page": carrier_listing["page"]},
    )


def _driver_form_defaults(row=None):
    row = dict(row) if row else {}
    return {
        "id": row.get("id"),
        "name": row.get("name", "") or "",
        "license_number": row.get("license_number", "") or "",
        "phone": row.get("phone", "") or "",
        "country": row.get("country", "") or "",
        "cdl_class": row.get("cdl_class", "") or "",
        "cdl_expiry": row.get("cdl_expiry", "") or "",
        "medical_card_expiry": row.get("medical_card_expiry", "") or "",
        "drug_test_date": row.get("drug_test_date", "") or "",
        "hire_date": row.get("hire_date", "") or "",
        "emergency_contact_name": row.get("emergency_contact_name", "") or "",
        "emergency_contact_phone": row.get("emergency_contact_phone", "") or "",
        "hazmat_endorsement": 1 if row.get("hazmat_endorsement") else 0,
        "twic_card": 1 if row.get("twic_card") else 0,
        "license_state": row.get("license_state", "") or "",
        "email": row.get("email", "") or "",
        "status": row.get("status", "Active") or "Active",
    }


def _vehicle_form_defaults(row=None):
    row = dict(row) if row else {}
    return {
        "id": row.get("id"),
        "truck_number": row.get("truck_number", "") or "",
        "vin": row.get("vin", "") or "",
        "license_plate": row.get("license_plate", "") or "",
        "year": row.get("year", "") or "",
        "make": row.get("make", "") or "",
        "model": row.get("model", "") or "",
        "vehicle_type": row.get("vehicle_type", "") or "",
        "capacity_weight": row.get("capacity_weight", "") or "",
        "capacity_cbm": row.get("capacity_cbm", "") or "",
        "country": row.get("country", "") or "",
        "registration_expiry": row.get("registration_expiry", "") or "",
        "insurance_expiry": row.get("insurance_expiry", "") or "",
        "insurance_carrier": row.get("insurance_carrier", "") or "",
        "odometer": row.get("odometer", "") or "",
        "last_inspection_date": row.get("last_inspection_date", "") or "",
        "next_inspection_due": row.get("next_inspection_due", "") or "",
        "status": row.get("status", "Active") or "Active",
    }


def _parse_optional_id(raw_value, label):
    clean_value = _normalize_text(raw_value)
    if not clean_value:
        return None
    if not clean_value.isdigit():
        raise ValueError(f"{label} selection is invalid.")
    return int(clean_value)


def _load_assignment_options():
    conn = get_db()
    try:
        carriers = conn.execute(
            "SELECT id, name FROM tms_carriers WHERE active = 1 ORDER BY name COLLATE NOCASE ASC"
        ).fetchall()
    finally:
        conn.close()
    return carriers, list_drivers(), list_vehicles()


def _resolve_carrier_selection(carrier_id_value, carrier_name_value=""):
    carrier_id = _parse_optional_id(carrier_id_value, "Carrier")
    if not carrier_id:
        return None, _normalize_text(carrier_name_value)

    carrier = get_carrier(carrier_id)
    if not carrier:
        raise ValueError("Selected carrier was not found.")
    return carrier_id, carrier["name"]


def _render_drivers_page(selected_driver_id=None, form_mode=None, form_driver=None):
    drivers = list_drivers()
    selected_driver = None
    driver_shipments = []
    duty_logs = []
    driver_stats = {
        "shipments": 0,
        "active_shipments": 0,
        "driving_hours": 0.0,
        "alerts": 0,
    }

    if selected_driver_id is None and drivers:
        selected_driver_id = drivers[0]["id"]

    if selected_driver_id:
        selected_driver, driver_shipments, duty_logs, driver_stats = get_driver_with_history(selected_driver_id)

    if form_mode == "edit" and not form_driver and selected_driver:
        form_driver = _driver_form_defaults(selected_driver)
    elif form_mode == "new" and not form_driver:
        form_driver = _driver_form_defaults()

    return render_template(
        "tms/drivers.html",
        drivers=drivers,
        selected_driver=selected_driver,
        driver_shipments=driver_shipments,
        duty_logs=duty_logs,
        driver_stats=driver_stats,
        form_mode=form_mode,
        form_driver=form_driver,
        driver_statuses=DRIVER_STATUS_OPTIONS,
        duty_statuses=DUTY_STATUS_OPTIONS,
        duty_form_defaults={
            "duty_status": "Driving",
            "start_time": datetime.now().replace(minute=0, second=0, microsecond=0).strftime("%Y-%m-%dT%H:%M"),
            "end_time": "",
            "location": selected_driver["last_location"] if selected_driver else "",
            "notes": "",
        },
        checkin_url=url_for("tms.driver_checkin", token=selected_driver["checkin_token"], _external=True)
        if selected_driver
        else "",
        now_date=date.today().isoformat(),
    )


def _render_fleet_page(selected_vehicle_id=None, form_mode=None, form_vehicle=None):
    vehicles = list_vehicles()
    selected_vehicle = None
    vehicle_shipments = []
    vehicle_stats = {
        "shipments": 0,
        "active_shipments": 0,
        "total_weight": 0.0,
        "total_cbm": 0.0,
    }

    if selected_vehicle_id is None and vehicles:
        selected_vehicle_id = vehicles[0]["id"]

    if selected_vehicle_id:
        selected_vehicle, vehicle_shipments, vehicle_stats = get_vehicle_with_history(selected_vehicle_id)

    if form_mode == "edit" and not form_vehicle and selected_vehicle:
        form_vehicle = _vehicle_form_defaults(selected_vehicle)
    elif form_mode == "new" and not form_vehicle:
        form_vehicle = _vehicle_form_defaults()

    return render_template(
        "tms/fleet.html",
        vehicles=vehicles,
        selected_vehicle=selected_vehicle,
        vehicle_shipments=vehicle_shipments,
        vehicle_stats=vehicle_stats,
        form_mode=form_mode,
        form_vehicle=form_vehicle,
        vehicle_statuses=VEHICLE_STATUS_OPTIONS,
        now_date=date.today().isoformat(),
    )


def _format_datetime_local_input(value):
    raw = _normalize_text(value)
    if not raw:
        return ""
    for candidate in (raw, raw.replace("T", " ")):
        try:
            parsed = datetime.fromisoformat(candidate)
            return parsed.replace(second=0, microsecond=0).strftime("%Y-%m-%dT%H:%M")
        except ValueError:
            continue
    return ""


def _dock_form_defaults(row=None):
    row = dict(row) if row else {}
    return {
        "id": row.get("id"),
        "name": row.get("name", "") or "",
        "dock_type": row.get("dock_type", "both") or "both",
        "location": row.get("location", "") or "",
        "default_duration_minutes": row.get("default_duration_minutes", 60) or 60,
        "active": 1 if row.get("active", 1) else 0,
    }


def _dock_appointment_form_defaults(source=None):
    source = dict(source) if source else {}
    next_slot = (datetime.now().replace(minute=0, second=0, microsecond=0) + timedelta(hours=1)).strftime(
        "%Y-%m-%dT%H:%M"
    )
    return {
        "shipment_ref": source.get("shipment_ref", "") or "",
        "dock_id": str(source.get("dock_id", "") or ""),
        "appointment_type": source.get("appointment_type", "inbound") or "inbound",
        "scheduled_start": _format_datetime_local_input(source.get("scheduled_start")) or next_slot,
        "notes": source.get("notes", "") or "",
        "contact_name": source.get("contact_name", "") or "",
        "contact_email": source.get("contact_email", "") or "",
    }


def _load_dock_shipment_options():
    conn = get_db()
    try:
        rows = conn.execute(
            """
            SELECT
                s.shipment_ref,
                s.status,
                COALESCE(s.shipper_name, '') AS shipper_name,
                COALESCE(s.consignee_name, '') AS consignee_name,
                COALESCE(s.carrier_name, '') AS carrier_name,
                COALESCE(s.origin_port, '') AS origin_port,
                COALESCE(s.destination_port, '') AS destination_port,
                da.status AS appointment_status,
                da.scheduled_start,
                da.booking_token,
                d.name AS dock_name
            FROM shipments s
            LEFT JOIN dock_appointments da
              ON UPPER(COALESCE(da.shipment_ref, '')) = UPPER(COALESCE(s.shipment_ref, ''))
            LEFT JOIN docks d ON d.id = da.dock_id
            WHERE s.status != 'Cancelled'
            ORDER BY
                CASE s.status
                    WHEN 'Booked' THEN 0
                    WHEN 'Active' THEN 1
                    WHEN 'Draft' THEN 2
                    WHEN 'In Transit' THEN 3
                    WHEN 'Delivered' THEN 4
                    ELSE 5
                END,
                COALESCE(NULLIF(s.etd, ''), '9999-12-31') ASC,
                s.created_at DESC
            """
        ).fetchall()
    finally:
        conn.close()

    shipment_options = []
    for row in rows:
        shipment = dict(row)
        route_label = " -> ".join(
            part
            for part in (
                shipment.get("origin_port"),
                shipment.get("destination_port"),
            )
            if part
        )
        party_label = " / ".join(
            part
            for part in (
                shipment.get("shipper_name"),
                shipment.get("consignee_name"),
            )
            if part
        )
        shipment["display_label"] = " | ".join(
            part
            for part in (
                shipment["shipment_ref"],
                route_label,
                party_label,
            )
            if part
        )
        shipment_options.append(shipment)
    return shipment_options


def _coerce_dock_week_start(value):
    raw = _normalize_text(value)
    if raw:
        try:
            requested = date.fromisoformat(raw)
        except ValueError:
            requested = date.today()
    else:
        requested = date.today()
    return requested - timedelta(days=requested.weekday())


def _render_docks_page(selected_dock_id=None, selected_shipment_ref="", dock_form=None, appointment_form=None):
    docks = list_docks(active_only=False)
    selected_dock = None
    if selected_dock_id:
        selected_dock = get_dock(selected_dock_id)

    if dock_form is None:
        dock_form = _dock_form_defaults(selected_dock if selected_dock_id else None)

    shipment_options = _load_dock_shipment_options()
    selected_shipment_ref = _normalize_text(
        selected_shipment_ref
        or (appointment_form or {}).get("shipment_ref")
        or request.values.get("shipment_ref")
    )
    selected_shipment = next(
        (shipment for shipment in shipment_options if shipment["shipment_ref"] == selected_shipment_ref),
        None,
    )
    selected_appointment = (
        get_dock_appointment(shipment_ref=selected_shipment_ref)
        if selected_shipment_ref
        else None
    )
    if appointment_form is None:
        appointment_form = _dock_appointment_form_defaults(selected_appointment or {"shipment_ref": selected_shipment_ref})

    selected_booking_url = ""
    if selected_shipment_ref:
        try:
            selected_booking_url = url_for(
                "tms.carrier_dock_booking",
                token=get_or_create_dock_booking_token(selected_shipment_ref),
                _external=True,
            )
        except LookupError:
            selected_booking_url = ""

    appointments = list_dock_appointments(
        start=date.today() - timedelta(days=1),
        end=date.today() + timedelta(days=14),
        include_unscheduled=False,
    )

    stats = {
        "dock_count": len(docks),
        "active_docks": sum(1 for dock in docks if dock["active"]),
        "scheduled": sum(1 for appointment in appointments if appointment["status"] == "Scheduled"),
        "in_progress": sum(1 for appointment in appointments if appointment["status"] in {"Checked-In", "Loading"}),
    }

    return render_template(
        "tms/docks.html",
        docks=docks,
        selected_dock=selected_dock,
        dock_form=dock_form,
        dock_types=DOCK_TYPES,
        shipment_options=shipment_options,
        selected_shipment=selected_shipment,
        selected_appointment=selected_appointment,
        appointment_form=appointment_form,
        appointment_types=DOCK_APPOINTMENT_TYPES,
        appointment_statuses=DOCK_APPOINTMENT_STATUSES,
        appointments=appointments,
        selected_booking_url=selected_booking_url,
        stats=stats,
    )


def _mask_api_key(raw_key):
    key_text = _normalize_text(raw_key)
    if len(key_text) <= 12:
        return key_text
    return f"{key_text[:8]}...{key_text[-4:]}"


def _coerce_optional_number(value, label):
    raw_value = _normalize_text(value)
    if raw_value == "":
        return 0
    try:
        parsed = round(float(raw_value), 2)
    except ValueError as exc:
        raise ValueError(f"{label} must be a valid number.") from exc
    if parsed < 0:
        raise ValueError(f"{label} cannot be negative.")
    return parsed


def _coerce_iso_datetime(value, label):
    raw_value = _normalize_text(value)
    if not raw_value:
        return ""

    candidate = raw_value[:-1] + "+00:00" if raw_value.endswith("Z") else raw_value
    try:
        datetime.fromisoformat(candidate)
        return raw_value
    except ValueError:
        try:
            date.fromisoformat(raw_value)
            return raw_value
        except ValueError as exc:
            raise ValueError(f"{label} must be an ISO date or datetime.") from exc


def _parse_api_shipment_payload(payload, customer_name):
    if not isinstance(payload, dict):
        raise ValueError("Request body must be a JSON object.")

    status = _normalize_text(payload.get("status")) or "Draft"
    if status not in SHIPMENT_STATUSES:
        allowed = ", ".join(sorted(SHIPMENT_STATUSES))
        raise ValueError(f"Status must be one of: {allowed}.")

    cleaned_payload = {
        "status": status,
        "shipper_name": _normalize_text(payload.get("shipper_name")) or customer_name,
        "shipper_address": _normalize_text(payload.get("shipper_address")),
        "consignee_name": _normalize_text(payload.get("consignee_name")),
        "consignee_address": _normalize_text(payload.get("consignee_address")),
        "carrier_name": _normalize_text(payload.get("carrier_name")),
        "origin_port": _normalize_text(payload.get("origin_port")),
        "destination_port": _normalize_text(payload.get("destination_port")),
        "mode": _normalize_text(payload.get("mode")),
        "etd": _coerce_iso_datetime(payload.get("etd"), "ETD"),
        "eta": _coerce_iso_datetime(payload.get("eta"), "ETA"),
        "cargo_description": _normalize_text(payload.get("cargo_description")),
        "containers": _normalize_text(payload.get("containers")),
        "weight_kg": _coerce_optional_number(payload.get("weight_kg"), "Weight (kg)"),
        "volume_cbm": _coerce_optional_number(payload.get("volume_cbm"), "Volume (cbm)"),
        "freight_rate": _coerce_optional_number(payload.get("freight_rate"), "Freight rate"),
        "currency": _normalize_text(payload.get("currency")) or "USD",
        "incoterm": _normalize_text(payload.get("incoterm")) or "FOB",
        "notes": _normalize_text(payload.get("notes")),
    }

    for field_name, label in [
        ("consignee_name", "Consignee name"),
        ("origin_port", "Origin"),
        ("destination_port", "Destination"),
        ("cargo_description", "Cargo description"),
    ]:
        if not cleaned_payload[field_name]:
            raise ValueError(f"{label} is required.")

    return cleaned_payload


def _shipment_list_item(shipment):
    return {
        "shipment_ref": shipment.get("shipment_ref"),
        "customer_name": shipment.get("customer_name") or shipment.get("shipper_name"),
        "status": shipment.get("status"),
        "shipper_name": shipment.get("shipper_name"),
        "consignee_name": shipment.get("consignee_name"),
        "origin_port": shipment.get("origin_port"),
        "destination_port": shipment.get("destination_port"),
        "mode": shipment.get("mode"),
        "etd": shipment.get("etd"),
        "eta": shipment.get("eta"),
        "cargo_description": shipment.get("cargo_description"),
        "freight_rate": shipment.get("freight_rate"),
        "currency": shipment.get("currency"),
        "updated_at": shipment.get("updated_at"),
    }


def _tracking_payload_from_context(context):
    latest_event = context["tracking"].get("latest_event") or {}
    return {
        "shipment_ref": context["shipment"].get("shipment_ref"),
        "status": context["shipment"].get("status"),
        "route_label": context["tracking"].get("route_label"),
        "eta_summary": context["tracking"].get("eta_summary"),
        "progress_percent": context["tracking"].get("progress_percent"),
        "event_count": context["tracking"].get("event_count"),
        "current_location": context["tracking"].get("current_location"),
        "last_updated": context["shipment"].get("last_updated_display"),
        "latest_event": {
            "event_type": latest_event.get("event_type"),
            "description": latest_event.get("description"),
            "location": latest_event.get("location"),
            "event_date": latest_event.get("event_date"),
            "event_date_display": latest_event.get("event_date_display"),
        },
        "events": [
            {
                "event_type": event.get("event_type"),
                "description": event.get("description"),
                "location": event.get("location"),
                "event_date": event.get("event_date"),
                "event_date_display": event.get("event_date_display"),
            }
            for event in context["events"]
        ],
    }


def _attach_api_headers(response, include_authenticate=False):
    for header_name, header_value in getattr(g, "api_rate_limit_headers", {}).items():
        response.headers[header_name] = str(header_value)
    if include_authenticate:
        response.headers["WWW-Authenticate"] = 'Bearer realm="tms-api"'
    return response


def _api_response(payload, status=200):
    response = make_response(jsonify(payload), status)
    return _attach_api_headers(response)


def _api_error(status, code, message, *, include_authenticate=False, extra=None):
    body = {
        "error": {
            "code": code,
            "message": message,
        }
    }
    if extra:
        body["error"].update(extra)
    response = make_response(jsonify(body), status)
    return _attach_api_headers(response, include_authenticate=include_authenticate)


def _extract_bearer_token():
    auth_header = request.headers.get("Authorization", "")
    if not auth_header:
        return ""
    parts = auth_header.split(None, 1)
    if len(parts) != 2 or parts[0].lower() != "bearer":
        return ""
    return _normalize_text(parts[1])


def require_api_key(*required_permissions):
    def decorator(view_func):
        @wraps(view_func)
        def wrapped(*args, **kwargs):
            token = _extract_bearer_token()
            if not token:
                return _api_error(
                    401,
                    "missing_bearer_token",
                    "Send Authorization: Bearer <api_key>.",
                    include_authenticate=True,
                )

            api_key = get_api_key(token)
            if not api_key:
                return _api_error(
                    401,
                    "invalid_api_key",
                    "The provided API key is invalid or has been revoked.",
                    include_authenticate=True,
                )

            permissions = set(api_key["permissions"])
            if "*" not in permissions and any(permission not in permissions for permission in required_permissions):
                return _api_error(403, "insufficient_permissions", "This API key does not allow that action.")

            if not API_RATE_LIMITER.allow(token):
                g.api_rate_limit_headers = {
                    "X-RateLimit-Limit": API_RATE_LIMITER.max_requests,
                    "X-RateLimit-Remaining": 0,
                    "Retry-After": API_RATE_LIMITER.window_seconds,
                }
                return _api_error(
                    429,
                    "rate_limit_exceeded",
                    "Rate limit exceeded. Try again in 60 seconds.",
                    extra={"limit": API_RATE_LIMITER.max_requests, "window_seconds": API_RATE_LIMITER.window_seconds},
                )

            touch_api_key_last_used(token)
            g.api_key = api_key
            g.api_permissions = permissions
            g.api_rate_limit_headers = {
                "X-RateLimit-Limit": API_RATE_LIMITER.max_requests,
                "X-RateLimit-Remaining": API_RATE_LIMITER.remaining(token),
            }
            return _attach_api_headers(make_response(view_func(*args, **kwargs)))

        return wrapped

    return decorator


def api_endpoint(rule, *, methods=("GET",), summary="", description="", permissions=(), query_params=None, body_fields=None):
    def decorator(view_func):
        API_ROUTE_DEFINITIONS.append(
            {
                "rule": rule,
                "methods": tuple(methods),
                "endpoint": f"tms_api_{view_func.__name__}",
                "view_func": view_func,
                "summary": summary,
                "description": description,
                "permissions": list(permissions),
                "query_params": list(query_params or []),
                "body_fields": list(body_fields or []),
            }
        )
        return view_func

    return decorator


@tms.record_once
def _register_external_api_routes(setup_state):
    for route_definition in API_ROUTE_DEFINITIONS:
        setup_state.app.add_url_rule(
            route_definition["rule"],
            endpoint=route_definition["endpoint"],
            view_func=route_definition["view_func"],
            methods=list(route_definition["methods"]),
        )


@tms.route("/api-keys", methods=["GET", "POST"])
@tms_roles_required("admin")
def api_keys():
    init_tms_db()
    generated_api_key = None
    status_code = 200
    customer_name = ""
    selected_permissions = [option["value"] for option in API_PERMISSION_OPTIONS]

    if request.method == "POST":
        action = _normalize_text(request.form.get("action")).lower() or "generate"
        customer_name = _normalize_text(request.form.get("customer_name"))
        selected_permissions = [
            permission
            for permission in request.form.getlist("permissions")
            if permission in VALID_API_PERMISSIONS
        ]
        try:
            if action == "generate":
                generated_api_key = create_api_key(customer_name, selected_permissions)
                flash(f"API key created for {generated_api_key['customer_name']}.", "success")
                customer_name = ""
                selected_permissions = [option["value"] for option in API_PERMISSION_OPTIONS]
            elif action == "revoke":
                revoked_key = revoke_api_key(request.form.get("key"))
                flash(f"API key revoked for {revoked_key['customer_name']}.", "warning")
            else:
                raise ValueError("Unknown API key action.")
        except ValueError as exc:
            flash(str(exc), "danger")
            status_code = 400

    api_keys_rows = []
    for row in list_api_keys():
        record = dict(row)
        record["masked_key"] = record.get("key_hint") or _mask_api_key(record["key"])
        api_keys_rows.append(record)

    return (
        render_template(
            "tms/api_keys.html",
            api_keys=api_keys_rows,
            generated_api_key=generated_api_key,
            permission_options=API_PERMISSION_OPTIONS,
            customer_name=customer_name,
            selected_permissions=set(selected_permissions),
        ),
        status_code,
    )


@tms.route("/api-docs")
def api_docs():
    api_routes = []
    for route_definition in API_ROUTE_DEFINITIONS:
        route_item = dict(route_definition)
        route_item["methods_label"] = ", ".join(route_definition["methods"])
        route_item["path_example"] = route_definition["rule"]
        if route_definition["query_params"]:
            sample_pairs = [
                f"{item['name']}={item.get('example', item['name'].upper())}"
                for item in route_definition["query_params"]
            ]
            route_item["path_example"] = f"{route_definition['rule']}?{'&'.join(sample_pairs)}"
        api_routes.append(route_item)

    return render_template(
        "tms/api_docs.html",
        api_routes=api_routes,
        api_base_url=_runtime_base_url(),
        permission_options=API_PERMISSION_OPTIONS,
    )


@api_endpoint(
    "/api/v1/shipments",
    methods=("GET",),
    summary="List shipments for the API key customer",
    description="Returns the shipments that belong to the customer attached to the bearer token.",
    permissions=("shipments.read",),
)
@require_api_key("shipments.read")
def api_v1_list_shipments():
    shipments = list_customer_shipments(g.api_key["customer_name"])
    return _api_response(
        {
            "customer_name": g.api_key["customer_name"],
            "count": len(shipments),
            "shipments": [_shipment_list_item(shipment) for shipment in shipments],
        }
    )


@api_endpoint(
    "/api/v1/shipments",
    methods=("POST",),
    summary="Create a shipment",
    description="Creates a new shipment owned by the API key customer.",
    permissions=("shipments.write",),
    body_fields=[
        {"name": "consignee_name", "required": True},
        {"name": "origin_port", "required": True},
        {"name": "destination_port", "required": True},
        {"name": "cargo_description", "required": True},
        {"name": "status", "required": False},
        {"name": "etd", "required": False},
        {"name": "eta", "required": False},
    ],
)
@require_api_key("shipments.write")
def api_v1_create_shipment():
    try:
        payload = _parse_api_shipment_payload(request.get_json(silent=True), g.api_key["customer_name"])
        snapshot = create_customer_shipment(g.api_key["customer_name"], payload)
    except ValueError as exc:
        return _api_error(400, "invalid_request", str(exc))

    return _api_response(
        {
            "message": "Shipment created.",
            "shipment": snapshot["shipment"],
            "events": snapshot["events"],
        },
        status=201,
    )


@api_endpoint(
    "/api/v1/shipments/<ref>",
    methods=("GET",),
    summary="Get shipment detail",
    description="Returns shipment detail and shipment events for a customer shipment reference.",
    permissions=("shipments.read",),
)
@require_api_key("shipments.read")
def api_v1_get_shipment(ref):
    snapshot = get_customer_shipment_snapshot(g.api_key["customer_name"], ref)
    if not snapshot:
        return _api_error(404, "not_found", "Shipment not found.")

    tracking_context = get_tracking_page_context(ref)
    return _api_response(
        {
            "shipment": snapshot["shipment"],
            "events": snapshot["events"],
            "tracking": _tracking_payload_from_context(tracking_context) if tracking_context else None,
        }
    )


@api_endpoint(
    "/api/v1/track/<ref>",
    methods=("GET",),
    summary="Get public tracking data",
    description="Returns the public tracking view payload for a customer shipment reference.",
    permissions=("tracking.read",),
)
@require_api_key("tracking.read")
def api_v1_track_shipment(ref):
    snapshot = get_customer_shipment_snapshot(g.api_key["customer_name"], ref)
    if not snapshot:
        return _api_error(404, "not_found", "Shipment not found.")

    tracking_context = get_tracking_page_context(ref)
    if not tracking_context:
        return _api_error(404, "not_found", "Tracking data not found.")
    return _api_response(_tracking_payload_from_context(tracking_context))


@api_endpoint(
    "/api/v1/rates/lookup",
    methods=("GET",),
    summary="Lookup rates by lane",
    description="Returns sandbox rate guidance using contract rates when available and shipment history otherwise.",
    permissions=("rates.read",),
    query_params=[
        {"name": "origin", "required": True, "example": "Chicago, IL"},
        {"name": "destination", "required": True, "example": "Dallas, TX"},
        {"name": "mode", "required": False, "example": "FTL"},
        {"name": "containers", "required": False, "example": "53' Reefer"},
    ],
)
@require_api_key("rates.read")
def api_v1_lookup_rates():
    origin = request.args.get("origin")
    destination = request.args.get("destination")
    mode = request.args.get("mode", "")
    containers = request.args.get("containers", "")
    try:
        lookup = lookup_api_rate(origin, destination, mode=mode, containers=containers)
    except ValueError as exc:
        return _api_error(400, "invalid_request", str(exc))

    if not lookup:
        return _api_error(404, "not_found", "No rate data found for that lane.")
    return _api_response(lookup)


@portal.route("/login", methods=["GET", "POST"])
def portal_login():
    settings = _portal_brand_settings()
    active_token = session.get("portal_token")
    if request.method == "GET" and active_token:
        active_context = get_portal_dashboard_context(active_token)
        if active_context:
            return redirect(
                url_for("portal.portal_dashboard", token=active_context["portal_token"]["token"])
            )
        session.pop("portal_token", None)

    if request.method == "POST":
        access_code = _normalize_text(request.form.get("access_code"))
        request_ip = _request_ip_address()
        if is_ip_locked(request_ip):
            return (
                render_template(
                    "tms/portal_login.html",
                    access_code=access_code,
                    login_error="Too many login attempts. Try again later.",
                    settings=settings,
                ),
                423,
            )
        portal_token = resolve_portal_login(access_code)
        if portal_token:
            record_login_attempt(request_ip, access_code, True)
            session["portal_token"] = portal_token["token"]
            return redirect(url_for("portal.portal_dashboard", token=portal_token["token"]))
        record_login_attempt(request_ip, access_code, False)
        return (
            render_template(
                "tms/portal_login.html",
                access_code=access_code,
                login_error="Enter a valid portal token or 6-digit PIN.",
                settings=settings,
            ),
            401,
        )

    return render_template(
        "tms/portal_login.html",
        access_code="",
        login_error=None,
        settings=settings,
    )


@portal.route("/logout", methods=["GET", "POST"])
def portal_logout():
    if request.method == "GET" and current_app.config.get("TMS_ENFORCE_CSRF"):
        abort(405)
    session.pop("portal_token", None)
    return redirect(url_for("portal.portal_login"))


@portal.route("/book", methods=["GET"])
def portal_book():
    portal_token = _portal_session_token()
    if not portal_token:
        flash("Please sign in to the customer portal.", "warning")
        return redirect(url_for("portal.portal_login"))

    return render_template(
        "tms/portal_book.html",
        equipment_options=_portal_equipment_options(),
        form_error=None,
        form_values=_portal_quote_form_defaults(),
        portal_token=portal_token,
        settings=_portal_brand_settings(),
    )


@portal.route("/book/submit", methods=["POST"])
def portal_book_submit():
    portal_token = _portal_session_token()
    if not portal_token:
        flash("Please sign in to the customer portal.", "warning")
        return redirect(url_for("portal.portal_login"))

    form_values = _portal_quote_form_defaults(request.form.to_dict())
    try:
        request_id = create_portal_quote_request(portal_token["token"], request.form)
    except ValueError as exc:
        return (
            render_template(
                "tms/portal_book.html",
                equipment_options=_portal_equipment_options(),
                form_error=str(exc),
                form_values=form_values,
                portal_token=portal_token,
                settings=_portal_brand_settings(),
            ),
            400,
        )

    return redirect(url_for("portal.portal_book_confirm", request_id=request_id))


@portal.route("/book/confirm", methods=["GET"])
def portal_book_confirm():
    portal_token = _portal_session_token()
    if not portal_token:
        flash("Please sign in to the customer portal.", "warning")
        return redirect(url_for("portal.portal_login"))

    request_id = request.args.get("request_id", type=int)
    quote_request = get_portal_quote_request(request_id, portal_token=portal_token["token"])
    if not quote_request:
        flash("Quote request confirmation was not found.", "warning")
        return redirect(url_for("portal.portal_book"))

    return render_template(
        "tms/portal_book_confirm.html",
        portal_token=portal_token,
        quote_request=quote_request,
        settings=_portal_brand_settings(),
    )


@portal.route("/quotes", methods=["GET"])
def portal_quotes():
    portal_token = _portal_session_token()
    if not portal_token:
        flash("Please sign in to the customer portal.", "warning")
        return redirect(url_for("portal.portal_login"))

    quote_requests = list_portal_quote_requests(portal_token["token"])
    return render_template(
        "tms/portal_quotes.html",
        portal_token=portal_token,
        quote_requests=quote_requests,
        settings=_portal_brand_settings(),
    )


@portal.route("/<token>/", methods=["GET", "POST"])
def portal_dashboard(token):
    normalized_token = _normalize_text(token).upper()
    selected_ref = request.values.get("selected_ref") or request.args.get("ref")

    if request.method == "POST":
        form_values = request.form.to_dict()
        try:
            new_ref = create_portal_shipment_request(normalized_token, form_values)
        except ValueError as exc:
            return _render_portal_dashboard(
                normalized_token,
                selected_ref=selected_ref,
                form_values=form_values,
                form_error=str(exc),
                status_code=400,
            )
        flash(f"Shipment request {new_ref} submitted.", "success")
        return redirect(url_for("portal.portal_dashboard", token=normalized_token, ref=new_ref))

    return _render_portal_dashboard(normalized_token, selected_ref=selected_ref)


@tms.route("/portal-bookings", methods=["GET"])
@tms_login_required
def portal_bookings_page():
    quote_requests = list_portal_quote_requests()
    pending_requests = [item for item in quote_requests if item["status"] == "pending"]
    history_requests = [item for item in quote_requests if item["status"] != "pending"]
    quote_counts = {
        "total": len(quote_requests),
        "pending": sum(1 for item in quote_requests if item["status"] == "pending"),
        "quoted": sum(1 for item in quote_requests if item["status"] == "quoted"),
        "booked": sum(1 for item in quote_requests if item["status"] == "booked"),
        "cancelled": sum(1 for item in quote_requests if item["status"] == "cancelled"),
    }
    return render_template(
        "tms/portal_bookings.html",
        history_requests=history_requests,
        pending_requests=pending_requests,
        quote_counts=quote_counts,
        quote_requests=quote_requests,
    )


@tms.route("/portal-bookings/<int:request_id>/quote", methods=["POST"])
@tms_login_required
def portal_bookings_quote(request_id):
    dispatcher_note = _normalize_text(request.form.get("quote_notes"))
    try:
        portal_request = quote_portal_quote_request(
            request_id,
            request.form.get("quoted_rate"),
            quoted_by=_request_actor() or "dispatcher",
            notes=dispatcher_note,
        )
    except ValueError as exc:
        flash(str(exc), "danger")
        return redirect(url_for("tms.portal_bookings_page"))

    email_sent, email_message = _send_portal_quote_email(portal_request, dispatcher_note=dispatcher_note)
    if email_sent:
        flash(
            f"Quote {portal_request['reference']} saved and emailed to {portal_request.get('customer_email')}.",
            "success",
        )
    else:
        flash(
            f"Quote {portal_request['reference']} saved, but email was not sent: {email_message}",
            "warning",
        )
    return redirect(url_for("tms.portal_bookings_page"))


@portal.route("/<token>/shipments/<ref>/bol.pdf")
def portal_download_bol(token, ref):
    snapshot = get_portal_shipment_snapshot(token, ref)
    if not snapshot:
        return "Shipment not found", 404
    return _build_document_response(
        snapshot["shipment"],
        snapshot["settings"].get("company_name", "My Freight Co"),
        ref,
        "bol",
    )


@portal.route("/<token>/shipments/<ref>/invoice.pdf")
def portal_download_invoice(token, ref):
    snapshot = get_portal_shipment_snapshot(token, ref)
    if not snapshot:
        return "Shipment not found", 404
    return _build_document_response(
        snapshot["shipment"],
        snapshot["settings"].get("company_name", "My Freight Co"),
        ref,
        "invoice",
    )


@portal.route("/<token>/shipments/<ref>/packing-list.pdf")
def portal_download_packing_list(token, ref):
    snapshot = get_portal_shipment_snapshot(token, ref)
    if not snapshot:
        return "Shipment not found", 404
    return _build_document_response(
        snapshot["shipment"],
        snapshot["settings"].get("company_name", "My Freight Co"),
        ref,
        "packing-list",
    )


@tms.route("/setup", methods=["GET", "POST"])
@tms_roles_required("admin")
def setup_wizard():
    init_tms_db()
    if request.method == "POST":
        try:
            state = save_setup(
                company_name=request.form.get("company_name", ""),
                primary_color=request.form.get("primary_color", ""),
                logo_file=request.files.get("logo"),
            )
        except ValueError as exc:
            return jsonify({"ok": False, "error": str(exc)}), 400
        except Exception as exc:
            return jsonify({"ok": False, "error": str(exc)}), 500

        return jsonify(
            {
                "ok": True,
                "message": "Sandbox setup saved.",
                "brand": {
                    "company_name": state["settings"].get("company_name", ""),
                    "primary_color": state["settings"].get("primary_color", ""),
                    "setup_complete": state["settings"].get("setup_complete", "0"),
                },
                "counts": state["counts"],
            }
        )

    return render_template("tms_onboarding.html", setup=get_setup_state())


@tms.route("/")
def dashboard():
    if not get_setup_state()["setup_complete"]:
        return redirect(url_for("tms.setup_wizard"))

    init_tms_db()
    conn = get_db()
    c = conn.cursor()
    shipments = c.execute(
        """
        SELECT s.*, d.name AS driver_name, v.truck_number AS vehicle_truck_number
        FROM shipments s
        LEFT JOIN drivers d ON d.id = s.driver_id
        LEFT JOIN vehicles v ON v.id = s.vehicle_id
        ORDER BY s.created_at DESC
        """
    ).fetchall()
    stats = {
        "total": c.execute("SELECT COUNT(*) FROM shipments").fetchone()[0],
        "active": c.execute("SELECT COUNT(*) FROM shipments WHERE status='Active'").fetchone()[0],
        "in_transit": c.execute("SELECT COUNT(*) FROM shipments WHERE status='In Transit'").fetchone()[0],
        "delivered": c.execute("SELECT COUNT(*) FROM shipments WHERE status='Delivered'").fetchone()[0],
        "loads": c.execute("SELECT COUNT(*) FROM loads").fetchone()[0],
        "drivers": c.execute("SELECT COUNT(*) FROM drivers").fetchone()[0],
        "fleet": c.execute("SELECT COUNT(*) FROM vehicles").fetchone()[0],
        "revenue": c.execute("SELECT COALESCE(SUM(freight_rate),0) FROM shipments WHERE status!='Draft'").fetchone()[0],
    }
    settings = dict(c.execute("SELECT key, value FROM tms_settings").fetchall())
    conn.close()
    return render_template(
        "tms/dashboard.html",
        shipments=shipments,
        stats=stats,
        settings=settings,
        current_tenant=get_tenant(g.get("tms_tenant_id")),
    )


@tms.route("/admin/tenants", methods=["GET", "POST"])
@tms_roles_required("admin")
def admin_tenants():
    form_values = {
        "company_name": "",
        "plan": "starter",
        "max_users": "5",
        "data_region": "ca-central",
        "session_timeout_minutes": "30",
        "allowed_ip_cidrs": "",
        "saml_entity_id": "",
        "saml_sso_url": "",
        "saml_metadata_url": "",
        "saml_x509_cert": "",
    }
    status_code = 200

    if request.method == "POST":
        action = _normalize_text(request.form.get("action")).lower()
        target_tenant_id = _normalize_text(request.form.get("tenant_id"))
        form_values.update(
            {
                "company_name": request.form.get("company_name", ""),
                "plan": request.form.get("plan", "starter"),
                "max_users": request.form.get("max_users", "5"),
                "data_region": request.form.get("data_region", "ca-central"),
                "session_timeout_minutes": request.form.get("session_timeout_minutes", "30"),
                "allowed_ip_cidrs": request.form.get("allowed_ip_cidrs", ""),
                "saml_entity_id": request.form.get("saml_entity_id", ""),
                "saml_sso_url": request.form.get("saml_sso_url", ""),
                "saml_metadata_url": request.form.get("saml_metadata_url", ""),
                "saml_x509_cert": request.form.get("saml_x509_cert", ""),
            }
        )

        try:
            if action == "create":
                tenant = create_tenant(
                    company_name=form_values["company_name"],
                    plan=form_values["plan"],
                    max_users=form_values["max_users"],
                    data_region=form_values["data_region"],
                    session_timeout_minutes=form_values["session_timeout_minutes"],
                    allowed_ip_cidrs=form_values["allowed_ip_cidrs"],
                    saml_entity_id=form_values["saml_entity_id"],
                    saml_sso_url=form_values["saml_sso_url"],
                    saml_x509_cert=form_values["saml_x509_cert"],
                    saml_metadata_url=form_values["saml_metadata_url"],
                )
                session["tms_tenant_id"] = tenant["tenant_id"]
                flash(f"Tenant {tenant['company_name']} created.", "success")
                return redirect(url_for("tms.admin_tenants"))
            if action == "switch":
                tenant = get_tenant(target_tenant_id)
                if not tenant or tenant.get("status") == "deleted":
                    raise ValueError("Tenant was not found.")
                session["tms_tenant_id"] = tenant["tenant_id"]
                flash(f"Switched to {tenant['company_name']}.", "success")
                return redirect(url_for("tms.admin_tenants"))
            if action == "suspend":
                tenant = update_tenant_status(target_tenant_id, "suspended")
                flash(f"Tenant {tenant['company_name']} suspended.", "warning")
                return redirect(url_for("tms.admin_tenants"))
            if action == "activate":
                tenant = update_tenant_status(target_tenant_id, "active")
                flash(f"Tenant {tenant['company_name']} reactivated.", "success")
                return redirect(url_for("tms.admin_tenants"))
            if action == "delete":
                tenant = update_tenant_status(target_tenant_id, "deleted")
                if session.get("tms_tenant_id") == tenant["tenant_id"]:
                    session["tms_tenant_id"] = DEFAULT_TENANT_ID
                flash(f"Tenant {tenant['company_name']} marked deleted.", "danger")
                return redirect(url_for("tms.admin_tenants"))
            raise ValueError("Unknown tenant action.")
        except ValueError as exc:
            flash(str(exc), "danger")
            status_code = 400

    return (
        render_template(
            "tms/admin_tenants.html",
            tenants=list_tenants(include_deleted=True),
            current_tenant_id=session.get("tms_tenant_id", DEFAULT_TENANT_ID),
            form_values=form_values,
            tenant_plans=("starter", "pro", "enterprise"),
        ),
        status_code,
    )


@tms.route("/admin/audit")
@tms_roles_required("admin")
def admin_audit():
    filters = {
        "tenant_id": _normalize_text(request.args.get("tenant_id")),
        "user_id": _normalize_text(request.args.get("user_id")),
        "action": _normalize_text(request.args.get("action")).upper(),
        "start_date": _normalize_text(request.args.get("start_date")),
        "end_date": _normalize_text(request.args.get("end_date")),
    }
    audit_events = list_audit_log(
        tenant_id=filters["tenant_id"] or None,
        user_id=filters["user_id"],
        action=filters["action"],
        start_date=filters["start_date"],
        end_date=filters["end_date"],
        include_all=True,
        limit=1000,
    )
    user_options = sorted({event["user_id"] for event in audit_events if event.get("user_id")})
    return render_template(
        "tms/admin_audit.html",
        audit_events=audit_events,
        filters=filters,
        tenants=list_tenants(include_deleted=True),
        user_options=user_options,
        action_options=("INSERT", "UPDATE", "DELETE"),
    )


@tms.route("/admin/audit/export")
@tms_roles_required("admin")
def admin_audit_export():
    filters = {
        "tenant_id": _normalize_text(request.args.get("tenant_id")),
        "user_id": _normalize_text(request.args.get("user_id")),
        "action": _normalize_text(request.args.get("action")).upper(),
        "start_date": _normalize_text(request.args.get("start_date")),
        "end_date": _normalize_text(request.args.get("end_date")),
    }
    audit_events = list_audit_log(
        tenant_id=filters["tenant_id"] or None,
        user_id=filters["user_id"],
        action=filters["action"],
        start_date=filters["start_date"],
        end_date=filters["end_date"],
        include_all=True,
        limit=5000,
    )
    output = io.StringIO()
    writer = csv.DictWriter(
        output,
        fieldnames=("id", "tenant_id", "user_id", "action", "table_name", "record_id", "ip", "created_at", "changes_json"),
    )
    writer.writeheader()
    for event in audit_events:
        writer.writerow(
            {
                "id": event.get("id"),
                "tenant_id": event.get("tenant_id"),
                "user_id": event.get("user_id"),
                "action": event.get("action"),
                "table_name": event.get("table_name"),
                "record_id": event.get("record_id"),
                "ip": event.get("ip"),
                "created_at": event.get("created_at"),
                "changes_json": json.dumps(event.get("changes") or {}, sort_keys=True),
            }
        )
    response = make_response(output.getvalue())
    response.headers["Content-Type"] = "text/csv; charset=utf-8"
    response.headers["Content-Disposition"] = "attachment; filename=tms-audit-export.csv"
    return response


@tms.route("/control-tower")
def control_tower():
    return render_template("tms/control_tower.html", control_tower=get_control_tower_context())


@tms.route("/control-tower/data")
def control_tower_data():
    return jsonify(get_control_tower_context())


@tms.route("/edi")
@tms_roles_required("admin", "dispatcher")
def edi_transactions_page():
    init_tms_db()
    conn = get_db()
    try:
        stats = {
            "total": conn.execute("SELECT COUNT(*) FROM edi_transactions").fetchone()[0],
            "inbound": conn.execute("SELECT COUNT(*) FROM edi_transactions WHERE direction = 'inbound'").fetchone()[0],
            "outbound": conn.execute("SELECT COUNT(*) FROM edi_transactions WHERE direction = 'outbound'").fetchone()[0],
            "partners": conn.execute("SELECT COUNT(*) FROM edi_partners").fetchone()[0],
            "failed": conn.execute(
                "SELECT COUNT(*) FROM edi_transactions WHERE status IN ('failed', 'parse_error')"
            ).fetchone()[0],
        }
        settings = dict(conn.execute("SELECT key, value FROM tms_settings").fetchall())
        recent_shipments = conn.execute(
            """
            SELECT s.shipment_ref, s.status, s.origin_port, s.destination_port, s.carrier_name,
                   COALESCE(tc.scac, '') AS carrier_scac
            FROM shipments s
            LEFT JOIN tms_carriers tc ON tc.id = s.carrier_id
            ORDER BY COALESCE(s.updated_at, s.created_at) DESC, s.id DESC
            LIMIT 50
            """
        ).fetchall()
    finally:
        conn.close()

    transactions = list_edi_transactions(limit=120)
    for transaction in transactions:
        transaction["pretty_json"] = json.dumps(transaction.get("parsed_data") or {}, indent=2, sort_keys=True)
        transaction["raw_preview"] = transaction.get("raw", "").strip()

    return render_template(
        "tms/edi.html",
        transactions=transactions,
        stats=stats,
        settings=settings,
        inbox_path=get_edi_inbox_path(),
        recent_shipments=recent_shipments,
        supported_types=sorted(SUPPORTED_TRANSACTION_TYPES),
    )


@tms.route("/edi/upload", methods=["POST"])
@tms_roles_required("admin", "dispatcher")
def edi_upload():
    upload = request.files.get("edi_file")
    if not upload or not getattr(upload, "filename", ""):
        flash("Choose an EDI file to upload.", "danger")
        return redirect(url_for("tms.edi_transactions_page"))

    raw_edi = edi_module._decode_edi_bytes(upload.read())
    try:
        try:
            summary = process_inbound_edi_payload(raw_edi, filename=upload.filename)
        except ValueError as exc:
            flash(f"EDI upload could not be parsed: {exc}", "danger")
            return redirect(url_for("tms.edi_transactions_page"))
    except Exception as exc:
        flash(f"EDI upload failed: {exc}", "danger")
        return redirect(url_for("tms.edi_transactions_page"))

    if summary["processed"]:
        logged = summary.get("logged", 0)
        flash(
            f"Processed {summary['processed']} {summary.get('format', 'EDI')} transaction(s): {summary['created']} created, {summary['updated']} updated, {logged} logged, {summary['acked']} 997 acknowledgement(s) generated.",
            "success",
        )
    if summary["failed"]:
        flash(f"{summary['failed']} transaction(s) were logged as failed.", "warning")
    return redirect(url_for("tms.edi_transactions_page"))


@tms.route("/edi/partners", methods=["GET", "POST"])
@tms_roles_required("admin", "dispatcher")
def edi_partners_page():
    init_tms_db()
    selected_partner_id = request.args.get("partner_id", type=int)
    selected_partner = get_edi_partner(selected_partner_id) if selected_partner_id else None
    form_values = {
        "partner_id": str(selected_partner["id"]) if selected_partner else "",
        "name": selected_partner["name"] if selected_partner else "",
        "isa_id": selected_partner["isa_id"] if selected_partner else "",
        "format": selected_partner["format"] if selected_partner else EDI_PARTNER_FORMATS[0],
        "direction": selected_partner["direction"] if selected_partner else EDI_PARTNER_DIRECTIONS[0],
    }

    if request.method == "POST":
        form_values = {
            "partner_id": (request.form.get("partner_id") or "").strip(),
            "name": (request.form.get("name") or "").strip(),
            "isa_id": (request.form.get("isa_id") or "").strip(),
            "format": (request.form.get("format") or EDI_PARTNER_FORMATS[0]).strip(),
            "direction": (request.form.get("direction") or EDI_PARTNER_DIRECTIONS[0]).strip(),
        }
        try:
            saved = save_edi_partner(
                form_values["name"],
                form_values["isa_id"],
                edi_format=form_values["format"],
                direction=form_values["direction"],
                partner_id=form_values["partner_id"] or None,
            )
            flash(f"EDI partner {saved['name']} saved.", "success")
            return redirect(url_for("tms.edi_partners_page", partner_id=saved["id"]))
        except ValueError as exc:
            flash(str(exc), "danger")

    return render_template(
        "tms/edi_partners.html",
        partners=list_edi_partners(),
        selected_partner=selected_partner,
        form_values=form_values,
        format_options=EDI_PARTNER_FORMATS,
        direction_options=EDI_PARTNER_DIRECTIONS,
        inbox_path=get_edi_inbox_path(),
    )


@tms.route("/edi/partners/<int:partner_id>/delete", methods=["POST"])
@tms_roles_required("admin", "dispatcher")
def edi_delete_partner(partner_id):
    delete_edi_partner(partner_id)
    flash("EDI partner deleted.", "success")
    return redirect(url_for("tms.edi_partners_page"))


@tms.route("/edi/shipments/<ref>/204", methods=["POST"])
def edi_generate_load_tender(ref):
    init_tms_db()
    conn = get_db()
    try:
        shipment_row = _load_edi_generation_shipment(conn, ref)
        if not shipment_row:
            flash("Shipment not found.", "danger")
            return redirect(url_for("tms.shipments"))

        settings = dict(conn.execute("SELECT key, value FROM tms_settings").fetchall())
        try:
            raw_edi = _record_edi_outbound_204(conn, shipment_row, settings)
        except ValueError as exc:
            conn.rollback()
            flash(str(exc), "danger")
            return redirect(request.referrer or url_for("tms.view_shipment", ref=ref))

        conn.commit()
    finally:
        conn.close()

    filename = f"{ref}-204.edi"
    return Response(
        raw_edi,
        mimetype="text/plain",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@tms.route("/edi/<int:transaction_id>/997", methods=["POST"])
def edi_generate_functional_ack(transaction_id):
    inbound_record = get_edi_transaction(transaction_id)
    if not inbound_record:
        flash("EDI transaction not found.", "danger")
        return redirect(url_for("tms.edi_transactions_page"))
    if inbound_record.get("direction") != "inbound":
        flash("Only inbound transactions can generate a 997 acknowledgement.", "warning")
        return redirect(url_for("tms.edi_transactions_page"))

    init_tms_db()
    conn = get_db()
    try:
        raw_edi = _record_edi_outbound_997(conn, inbound_record)
        conn.commit()
    finally:
        conn.close()

    filename = f"ack-{transaction_id}-997.edi"
    return Response(
        raw_edi,
        mimetype="text/plain",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@tms.route("/edi/<int:transaction_id>/download")
def download_edi_transaction(transaction_id):
    transaction = get_edi_transaction(transaction_id)
    if not transaction:
        return "EDI transaction not found.", 404

    filename = f"{transaction['direction']}-{transaction['type']}-{transaction_id}.edi"
    return Response(
        transaction.get("raw", ""),
        mimetype="text/plain",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@tms.route("/carriers")
def carriers():
    carrier_id = request.args.get("carrier_id", type=int)
    return _render_carriers_page(selected_carrier_id=carrier_id)


@tms.route("/carriers/new", methods=["GET", "POST"])
def new_carrier():
    if request.method == "POST":
        return_args = _carrier_return_args()
        form_values = _carrier_form_defaults(request.form)
        try:
            carrier_id = save_carrier(
                name=request.form.get("name", ""),
                scac=request.form.get("scac", ""),
                dot_number=request.form.get("dot_number", ""),
                mc_number=request.form.get("mc_number", ""),
                contact_name=request.form.get("contact_name", ""),
                country=request.form.get("country", ""),
                contact_email=request.form.get("contact_email", ""),
                contact_phone=request.form.get("contact_phone", ""),
                address=request.form.get("address", ""),
                city=request.form.get("city", ""),
                state_province=request.form.get("state_province", ""),
                postal_code=request.form.get("postal_code", ""),
                equipment_types=request.form.get("equipment_types", ""),
                service_areas=request.form.get("service_areas", ""),
                insurance_company=request.form.get("insurance_company", ""),
                insurance_policy=request.form.get("insurance_policy", ""),
                cargo_insurance_amount=request.form.get("cargo_insurance_amount", ""),
                liability_amount=request.form.get("liability_amount", ""),
                payment_terms=request.form.get("payment_terms", "NET30"),
                active=request.form.get("active", "0"),
            )
        except ValueError as exc:
            flash(str(exc), "danger")
            return _render_carriers_page(form_mode="new", form_carrier=form_values)

        flash("Carrier created.", "success")
        return redirect(url_for("tms.view_carrier", carrier_id=carrier_id, **return_args))

    return _render_carriers_page(form_mode="new")


@tms.route("/carriers/import", methods=["POST"])
def import_carriers():
    return_args = _carrier_return_args()
    try:
        summary = import_carriers_from_contacts_db()
    except (FileNotFoundError, ValueError) as exc:
        flash(str(exc), "danger")
    except Exception as exc:
        flash(f"Carrier import failed: {exc}", "danger")
    else:
        flash(
            f"Imported {summary['inserted']:,} carriers and refreshed {summary['updated']:,} existing records from {summary['source_total']:,} unique companies.",
            "success",
        )
    return redirect(url_for("tms.carriers", **return_args))


@tms.route("/carriers/<int:carrier_id>")
def view_carrier(carrier_id):
    carrier = get_carrier(carrier_id)
    if not carrier:
        flash("Carrier not found.", "danger")
        return redirect(url_for("tms.carriers"))
    return _render_carriers_page(selected_carrier_id=carrier_id)


@tms.route("/carriers/<int:carrier_id>/edit", methods=["GET", "POST"])
def edit_carrier(carrier_id):
    carrier = get_carrier(carrier_id)
    if not carrier:
        flash("Carrier not found.", "danger")
        return redirect(url_for("tms.carriers"))

    if request.method == "POST":
        return_args = _carrier_return_args()
        form_values = _carrier_form_defaults(request.form)
        form_values["id"] = carrier_id
        try:
            save_carrier(
                carrier_id=carrier_id,
                name=request.form.get("name", ""),
                scac=request.form.get("scac", ""),
                dot_number=request.form.get("dot_number", ""),
                mc_number=request.form.get("mc_number", ""),
                contact_name=request.form.get("contact_name", ""),
                country=request.form.get("country", ""),
                contact_email=request.form.get("contact_email", ""),
                contact_phone=request.form.get("contact_phone", ""),
                address=request.form.get("address", ""),
                city=request.form.get("city", ""),
                state_province=request.form.get("state_province", ""),
                postal_code=request.form.get("postal_code", ""),
                equipment_types=request.form.get("equipment_types", ""),
                service_areas=request.form.get("service_areas", ""),
                insurance_company=request.form.get("insurance_company", ""),
                insurance_policy=request.form.get("insurance_policy", ""),
                cargo_insurance_amount=request.form.get("cargo_insurance_amount", ""),
                liability_amount=request.form.get("liability_amount", ""),
                payment_terms=request.form.get("payment_terms", "NET30"),
                active=request.form.get("active", "0"),
            )
        except ValueError as exc:
            flash(str(exc), "danger")
            return _render_carriers_page(
                selected_carrier_id=carrier_id,
                form_mode="edit",
                form_carrier=form_values,
            )

        flash("Carrier updated.", "success")
        return redirect(url_for("tms.view_carrier", carrier_id=carrier_id, **return_args))

    return _render_carriers_page(selected_carrier_id=carrier_id, form_mode="edit")


@tms.route("/carriers/<int:carrier_id>/safety-refresh", methods=["POST"])
def refresh_carrier_safety_route(carrier_id):
    return_args = _carrier_return_args()
    try:
        carrier = refresh_carrier_safety(carrier_id)
    except (LookupError, ValueError) as exc:
        flash(str(exc), "warning")
    except Exception as exc:
        flash(f"FMCSA refresh failed: {exc}", "danger")
    else:
        flash(
            f"FMCSA safety refreshed for {carrier['name']}.",
            "success",
        )
    return redirect(url_for("tms.view_carrier", carrier_id=carrier_id, **return_args))


@tms.route("/carriers/<int:carrier_id>/delete", methods=["POST"])
def remove_carrier(carrier_id):
    return_args = _carrier_return_args()
    try:
        carrier_name = delete_carrier(carrier_id)
    except ValueError as exc:
        flash(str(exc), "danger")
    else:
        flash(f"{carrier_name} deleted.", "warning")
    return redirect(url_for("tms.carriers", **return_args))


@tms.route("/drivers")
def drivers():
    driver_id = request.args.get("driver_id", type=int)
    return _render_drivers_page(selected_driver_id=driver_id)


@tms.route("/drivers/new", methods=["GET", "POST"])
def new_driver():
    if request.method == "POST":
        form_values = _driver_form_defaults(request.form)
        try:
            driver_id = save_driver(
                name=request.form.get("name", ""),
                license_number=request.form.get("license_number", ""),
                phone=request.form.get("phone", ""),
                country=request.form.get("country", ""),
                cdl_class=request.form.get("cdl_class", ""),
                cdl_expiry=request.form.get("cdl_expiry", ""),
                medical_card_expiry=request.form.get("medical_card_expiry", ""),
                drug_test_date=request.form.get("drug_test_date", ""),
                hire_date=request.form.get("hire_date", ""),
                emergency_contact_name=request.form.get("emergency_contact_name", ""),
                emergency_contact_phone=request.form.get("emergency_contact_phone", ""),
                hazmat_endorsement=request.form.get("hazmat_endorsement", 0),
                twic_card=request.form.get("twic_card", 0),
                license_state=request.form.get("license_state", ""),
                email=request.form.get("email", ""),
                status=request.form.get("status", "Active"),
            )
        except ValueError as exc:
            flash(str(exc), "danger")
            return _render_drivers_page(form_mode="new", form_driver=form_values)

        flash("Driver created.", "success")
        return redirect(url_for("tms.drivers", driver_id=driver_id))

    return _render_drivers_page(form_mode="new")


@tms.route("/drivers/<int:driver_id>/edit", methods=["GET", "POST"])
def edit_driver(driver_id):
    driver = get_driver(driver_id)
    if not driver:
        flash("Driver not found.", "danger")
        return redirect(url_for("tms.drivers"))

    if request.method == "POST":
        form_values = _driver_form_defaults(request.form)
        form_values["id"] = driver_id
        try:
            save_driver(
                driver_id=driver_id,
                name=request.form.get("name", ""),
                license_number=request.form.get("license_number", ""),
                phone=request.form.get("phone", ""),
                country=request.form.get("country", ""),
                cdl_class=request.form.get("cdl_class", ""),
                cdl_expiry=request.form.get("cdl_expiry", ""),
                medical_card_expiry=request.form.get("medical_card_expiry", ""),
                drug_test_date=request.form.get("drug_test_date", ""),
                hire_date=request.form.get("hire_date", ""),
                emergency_contact_name=request.form.get("emergency_contact_name", ""),
                emergency_contact_phone=request.form.get("emergency_contact_phone", ""),
                hazmat_endorsement=request.form.get("hazmat_endorsement", 0),
                twic_card=request.form.get("twic_card", 0),
                license_state=request.form.get("license_state", ""),
                email=request.form.get("email", ""),
                status=request.form.get("status", "Active"),
            )
        except ValueError as exc:
            flash(str(exc), "danger")
            return _render_drivers_page(
                selected_driver_id=driver_id,
                form_mode="edit",
                form_driver=form_values,
            )

        flash("Driver updated.", "success")
        return redirect(url_for("tms.drivers", driver_id=driver_id))

    return _render_drivers_page(selected_driver_id=driver_id, form_mode="edit")


@tms.route("/drivers/<int:driver_id>/delete", methods=["POST"])
def remove_driver(driver_id):
    try:
        driver_name = delete_driver(driver_id)
    except ValueError as exc:
        flash(str(exc), "danger")
    else:
        flash(f"{driver_name} deleted.", "warning")
    return redirect(url_for("tms.drivers"))


@tms.route("/drivers/<int:driver_id>/duty-log", methods=["POST"])
def add_driver_duty_log(driver_id):
    try:
        save_duty_log(
            driver_id=driver_id,
            shipment_id=_parse_optional_id(request.form.get("shipment_id"), "Shipment"),
            duty_status=request.form.get("duty_status", "Driving"),
            start_time=request.form.get("start_time", ""),
            end_time=request.form.get("end_time", ""),
            location=request.form.get("location", ""),
            notes=request.form.get("notes", ""),
        )
    except ValueError as exc:
        flash(str(exc), "danger")
    else:
        flash("Duty log saved.", "success")
    return redirect(url_for("tms.drivers", driver_id=driver_id))


@tms.route("/hos")
def hos_dashboard_page():
    dashboard = get_hos_dashboard()
    violations = [row for row in dashboard if row["has_violation"]]
    at_risk_count = sum(
        1
        for row in dashboard
        if any(
            pct >= 80
            for pct in (row["driving_pct"], row["on_duty_pct"], row["cycle_pct"])
        )
    )
    cycle_average = round(
        sum(row["cycle_hours_8day"] for row in dashboard) / len(dashboard),
        1,
    ) if dashboard else 0.0
    return render_template(
        "tms/hos.html",
        dashboard=dashboard,
        violation_count=len(violations),
        at_risk_count=at_risk_count,
        cycle_average=cycle_average,
        max_driving_hours=MAX_DRIVING_HOURS,
        max_on_duty_hours=MAX_ON_DUTY_HOURS,
        required_off_hours=REQUIRED_OFF_HOURS,
        max_cycle_hours_8day=MAX_CYCLE_HOURS_8DAY,
    )


@tms.route("/hos/<int:driver_id>")
def hos_detail_page(driver_id):
    try:
        summary = get_hos_driver_summary(driver_id)
        logs = get_hos_driver_logs(driver_id, days=7)
    except ValueError as exc:
        flash(str(exc), "danger")
        return redirect(url_for("tms.hos_dashboard_page"))

    form_end = datetime.now().replace(second=0, microsecond=0)
    form_start = form_end - timedelta(hours=1)
    latest_location = logs[0]["location"] if logs else ""
    return render_template(
        "tms/hos_detail.html",
        summary=summary,
        logs=logs,
        duty_status_choices=HOS_DUTY_STATUS_CHOICES,
        form_defaults={
            "duty_status": "driving",
            "start_time": form_start.strftime("%Y-%m-%dT%H:%M"),
            "end_time": form_end.strftime("%Y-%m-%dT%H:%M"),
            "location": latest_location,
            "notes": "",
        },
        max_driving_hours=MAX_DRIVING_HOURS,
        max_on_duty_hours=MAX_ON_DUTY_HOURS,
        required_off_hours=REQUIRED_OFF_HOURS,
        max_cycle_hours_8day=MAX_CYCLE_HOURS_8DAY,
    )


@tms.route("/hos/<int:driver_id>/log", methods=["POST"])
def hos_add_log(driver_id):
    try:
        add_hos_log_entry(
            driver_id=driver_id,
            duty_status=request.form.get("duty_status", "driving"),
            start_time=request.form.get("start_time", ""),
            end_time=request.form.get("end_time", ""),
            location=request.form.get("location", ""),
            notes=request.form.get("notes", ""),
        )
    except ValueError as exc:
        flash(str(exc), "danger")
    else:
        flash("HOS log saved.", "success")
    return redirect(url_for("tms.hos_detail_page", driver_id=driver_id))


@tms.route("/fleet")
def fleet():
    vehicle_id = request.args.get("vehicle_id", type=int)
    return _render_fleet_page(selected_vehicle_id=vehicle_id)


@tms.route("/fleet/new", methods=["GET", "POST"])
def new_vehicle():
    if request.method == "POST":
        form_values = _vehicle_form_defaults(request.form)
        try:
            vehicle_id = save_vehicle(
                truck_number=request.form.get("truck_number", ""),
                vin=request.form.get("vin", ""),
                license_plate=request.form.get("license_plate", ""),
                year=request.form.get("year", ""),
                make=request.form.get("make", ""),
                model=request.form.get("model", ""),
                vehicle_type=request.form.get("vehicle_type", ""),
                capacity_weight=request.form.get("capacity_weight", ""),
                capacity_cbm=request.form.get("capacity_cbm", ""),
                country=request.form.get("country", ""),
                registration_expiry=request.form.get("registration_expiry", ""),
                insurance_expiry=request.form.get("insurance_expiry", ""),
                insurance_carrier=request.form.get("insurance_carrier", ""),
                odometer=request.form.get("odometer", ""),
                last_inspection_date=request.form.get("last_inspection_date", ""),
                next_inspection_due=request.form.get("next_inspection_due", ""),
                status=request.form.get("status", "Active"),
            )
        except ValueError as exc:
            flash(str(exc), "danger")
            return _render_fleet_page(form_mode="new", form_vehicle=form_values)

        flash("Vehicle created.", "success")
        return redirect(url_for("tms.fleet", vehicle_id=vehicle_id))

    return _render_fleet_page(form_mode="new")


@tms.route("/fleet/<int:vehicle_id>/edit", methods=["GET", "POST"])
def edit_vehicle(vehicle_id):
    vehicle = get_vehicle(vehicle_id)
    if not vehicle:
        flash("Vehicle not found.", "danger")
        return redirect(url_for("tms.fleet"))

    if request.method == "POST":
        form_values = _vehicle_form_defaults(request.form)
        form_values["id"] = vehicle_id
        try:
            save_vehicle(
                vehicle_id=vehicle_id,
                truck_number=request.form.get("truck_number", ""),
                vin=request.form.get("vin", ""),
                license_plate=request.form.get("license_plate", ""),
                year=request.form.get("year", ""),
                make=request.form.get("make", ""),
                model=request.form.get("model", ""),
                vehicle_type=request.form.get("vehicle_type", ""),
                capacity_weight=request.form.get("capacity_weight", ""),
                capacity_cbm=request.form.get("capacity_cbm", ""),
                country=request.form.get("country", ""),
                registration_expiry=request.form.get("registration_expiry", ""),
                insurance_expiry=request.form.get("insurance_expiry", ""),
                insurance_carrier=request.form.get("insurance_carrier", ""),
                odometer=request.form.get("odometer", ""),
                last_inspection_date=request.form.get("last_inspection_date", ""),
                next_inspection_due=request.form.get("next_inspection_due", ""),
                status=request.form.get("status", "Active"),
            )
        except ValueError as exc:
            flash(str(exc), "danger")
            return _render_fleet_page(
                selected_vehicle_id=vehicle_id,
                form_mode="edit",
                form_vehicle=form_values,
            )

        flash("Vehicle updated.", "success")
        return redirect(url_for("tms.fleet", vehicle_id=vehicle_id))

    return _render_fleet_page(selected_vehicle_id=vehicle_id, form_mode="edit")


@tms.route("/fleet/<int:vehicle_id>/delete", methods=["POST"])
def remove_vehicle(vehicle_id):
    try:
        truck_number = delete_vehicle(vehicle_id)
    except ValueError as exc:
        flash(str(exc), "danger")
    else:
        flash(f"{truck_number} deleted.", "warning")
    return redirect(url_for("tms.fleet"))


@tms.route("/docks", methods=["GET", "POST"])
def docks():
    selected_dock_id = request.values.get("dock_id", type=int)
    selected_shipment_ref = _normalize_text(request.values.get("shipment_ref"))

    if request.method == "POST":
        action = (_normalize_text(request.form.get("action")) or "save_appointment").lower()

        if action == "save_dock":
            dock_form = {
                **_dock_form_defaults(request.form),
                "id": request.form.get("record_id", type=int),
                "name": _normalize_text(request.form.get("name")),
                "dock_type": _normalize_text(request.form.get("dock_type")).lower() or "both",
                "location": _normalize_text(request.form.get("location")),
                "default_duration_minutes": _normalize_text(request.form.get("default_duration_minutes")) or "60",
                "active": 1 if request.form.get("active") in {"1", "true", "on", "yes"} else 0,
            }
            try:
                saved_dock = save_dock(
                    dock_id=request.form.get("record_id"),
                    name=request.form.get("name", ""),
                    dock_type=request.form.get("dock_type", "both"),
                    location=request.form.get("location", ""),
                    default_duration_minutes=request.form.get("default_duration_minutes", "60"),
                    active=request.form.get("active", "0"),
                )
            except ValueError as exc:
                flash(str(exc), "danger")
                return _render_docks_page(
                    selected_dock_id=request.form.get("record_id", type=int) or selected_dock_id,
                    selected_shipment_ref=selected_shipment_ref,
                    dock_form=dock_form,
                ), 400

            flash(
                "Dock updated." if request.form.get("record_id") else "Dock created.",
                "success",
            )
            redirect_args = {"dock_id": saved_dock["id"]}
            if selected_shipment_ref:
                redirect_args["shipment_ref"] = selected_shipment_ref
            return redirect(url_for("tms.docks", **redirect_args))

        if action == "save_appointment":
            appointment_form = {
                **_dock_appointment_form_defaults(request.form),
                "shipment_ref": _normalize_text(request.form.get("shipment_ref")),
                "dock_id": _normalize_text(request.form.get("dock_id")),
                "appointment_type": _normalize_text(request.form.get("appointment_type")).lower() or "inbound",
                "scheduled_start": _normalize_text(request.form.get("scheduled_start")),
                "notes": _normalize_text(request.form.get("notes")),
                "contact_name": _normalize_text(request.form.get("contact_name")),
                "contact_email": _normalize_text(request.form.get("contact_email")),
            }
            selected_shipment_ref = appointment_form["shipment_ref"]
            selected_dock_id = request.form.get("dock_id", type=int) or selected_dock_id
            try:
                appointment = save_dock_appointment(
                    shipment_ref=appointment_form["shipment_ref"],
                    dock_id=appointment_form["dock_id"],
                    scheduled_start=appointment_form["scheduled_start"],
                    appointment_type=appointment_form["appointment_type"],
                    notes=appointment_form["notes"],
                    contact_name=appointment_form["contact_name"],
                    contact_email=appointment_form["contact_email"],
                    booked_by="dispatch",
                )
            except ValueError as exc:
                flash(str(exc), "danger")
                return _render_docks_page(
                    selected_dock_id=selected_dock_id,
                    selected_shipment_ref=selected_shipment_ref,
                    appointment_form=appointment_form,
                ), 400

            flash(
                f"Shipment {appointment['shipment_ref']} scheduled at {appointment['dock_name']} "
                f"for {appointment['scheduled_start_display']}.",
                "success",
            )
            return redirect(
                url_for(
                    "tms.docks",
                    dock_id=appointment["dock_id"],
                    shipment_ref=appointment["shipment_ref"],
                )
            )

        flash("Unknown dock action.", "danger")
        return redirect(url_for("tms.docks"))

    return _render_docks_page(
        selected_dock_id=selected_dock_id,
        selected_shipment_ref=selected_shipment_ref,
    )


@tms.route("/docks/appointments/<int:appointment_id>/status", methods=["POST"])
def dock_appointment_status(appointment_id):
    selected_shipment_ref = _normalize_text(request.form.get("shipment_ref"))
    try:
        appointment = update_dock_appointment_status(appointment_id, request.form.get("status"))
    except ValueError as exc:
        flash(str(exc), "danger")
        return redirect(request.referrer or url_for("tms.docks"))

    flash(
        f"Dock appointment for {appointment['shipment_ref']} marked {appointment['status']}.",
        "success",
    )
    redirect_args = {}
    if appointment.get("dock_id"):
        redirect_args["dock_id"] = appointment["dock_id"]
    if selected_shipment_ref or appointment.get("shipment_ref"):
        redirect_args["shipment_ref"] = selected_shipment_ref or appointment["shipment_ref"]
    return redirect(request.referrer or url_for("tms.docks", **redirect_args))


@tms.route("/docks/calendar")
def dock_calendar():
    week_start = _coerce_dock_week_start(request.args.get("start"))
    calendar_context = build_dock_calendar(start_date=week_start, days=7)
    return render_template(
        "tms/dock_calendar.html",
        **calendar_context,
        prev_start=(week_start - timedelta(days=7)).isoformat(),
        next_start=(week_start + timedelta(days=7)).isoformat(),
    )


@tms.route("/docks/book/<token>", methods=["GET", "POST"])
def carrier_dock_booking(token):
    appointment = get_dock_appointment(token=token)
    if not appointment or not appointment.get("shipment_ref"):
        return (
            render_template(
                "tms/dock_booking.html",
                appointment=None,
                availability=[],
                appointment_types=DOCK_APPOINTMENT_TYPES,
                form_values={},
                form_error="This booking link is invalid or no longer available.",
            ),
            404,
        )

    form_values = {
        "appointment_type": _normalize_text(
            request.form.get("appointment_type") if request.method == "POST" else appointment.get("appointment_type")
        ).lower() or "inbound",
        "slot": _normalize_text(request.form.get("slot")),
        "contact_name": _normalize_text(request.form.get("contact_name") or appointment.get("contact_name")),
        "contact_email": _normalize_text(request.form.get("contact_email") or appointment.get("contact_email")),
        "notes": _normalize_text(request.form.get("notes") or appointment.get("notes")),
    }
    form_error = None

    if request.method == "POST":
        action = (_normalize_text(request.form.get("action")) or "book").lower()
        slot_value = form_values["slot"]
        if action == "refresh":
            slot_value = ""
        elif "|" not in slot_value:
            form_error = "Select an available dock slot."
        else:
            dock_id_value, start_value = slot_value.split("|", 1)
            try:
                save_dock_appointment(
                    appointment_id=appointment["id"],
                    shipment_ref=appointment["shipment_ref"],
                    dock_id=dock_id_value,
                    scheduled_start=start_value,
                    appointment_type=form_values["appointment_type"],
                    notes=form_values["notes"],
                    contact_name=form_values["contact_name"],
                    contact_email=form_values["contact_email"],
                    booked_by="carrier",
                )
            except ValueError as exc:
                form_error = str(exc)
            else:
                flash("Dock appointment booked.", "success")
                return redirect(url_for("tms.carrier_dock_booking", token=token))

    appointment = get_dock_appointment(token=token)
    availability = list_available_dock_slots(
        appointment_type=form_values["appointment_type"],
        exclude_appointment_id=appointment["id"],
    )
    return render_template(
        "tms/dock_booking.html",
        appointment=appointment,
        availability=availability,
        appointment_types=DOCK_APPOINTMENT_TYPES,
        form_values=form_values,
        form_error=form_error,
    )


@tms.route("/driver/<token>", methods=["GET", "POST"])
def driver_checkin(token):
    context = get_driver_checkin_context(token)
    if not context:
        return (
            render_template(
                "tms/driver_checkin.html",
                driver=None,
                shipment=None,
                duty_logs=[],
                driver_statuses=DRIVER_STATUS_OPTIONS,
                duty_statuses=DUTY_STATUS_OPTIONS,
                form_values={},
                form_error="This driver check-in link is invalid or expired.",
                saved=False,
            ),
            404,
        )

    form_values = {
        "status": context["driver"].get("status", "Active"),
        "location": context["driver"].get("last_location", ""),
        "issue": "",
        "duty_status": "Driving",
        "duty_start": "",
        "duty_end": "",
    }
    form_error = None
    status_code = 200

    if request.method == "POST":
        form_values = {
            "status": request.form.get("status", context["driver"].get("status", "Active")),
            "location": _normalize_text(request.form.get("location")),
            "issue": _normalize_text(request.form.get("issue")),
            "duty_status": request.form.get("duty_status", "Driving"),
            "duty_start": _normalize_text(request.form.get("duty_start")),
            "duty_end": _normalize_text(request.form.get("duty_end")),
        }
        try:
            submit_driver_checkin(
                token,
                status=form_values["status"],
                location=form_values["location"],
                issue=form_values["issue"],
                duty_status=form_values["duty_status"],
                duty_start=form_values["duty_start"],
                duty_end=form_values["duty_end"],
            )
            return redirect(url_for("tms.driver_checkin", token=token, saved=1))
        except ValueError as exc:
            form_error = str(exc)
            status_code = 400
            context = get_driver_checkin_context(token) or context

    return (
        render_template(
            "tms/driver_checkin.html",
            driver=context["driver"],
            shipment=context["shipment"],
            duty_logs=context["duty_logs"],
            driver_statuses=DRIVER_STATUS_OPTIONS,
            duty_statuses=DUTY_STATUS_OPTIONS,
            form_values=form_values,
            form_error=form_error,
            saved=request.args.get("saved") == "1",
        ),
        status_code,
    )


@tms.route("/rates", methods=["GET", "POST"])
def contract_rates():
    selected_rate_id = request.args.get("rate_id", type=int)

    if request.method == "POST":
        raw_rate_id = _normalize_text(request.form.get("rate_id"))
        rate_id = int(raw_rate_id) if raw_rate_id.isdigit() else None
        form_values = _rate_form_defaults(request.form)

        try:
            saved_rate = save_contract_rate(
                rate_id=rate_id,
                origin=request.form.get("origin", ""),
                destination=request.form.get("destination", ""),
                mode=request.form.get("mode", ""),
                rate_20ft=request.form.get("rate_20ft", ""),
                rate_40ft=request.form.get("rate_40ft", ""),
                rate_40hc=request.form.get("rate_40hc", ""),
                currency=request.form.get("currency", "USD"),
                valid_from=request.form.get("valid_from", ""),
                valid_to=request.form.get("valid_to", ""),
            )
        except ValueError as exc:
            return _render_rates_page(
                selected_rate_id=rate_id or selected_rate_id,
                form_values=form_values,
                form_mode="edit" if rate_id else "new",
                form_error=str(exc),
                status_code=400,
            )

        flash("Contract rate updated." if rate_id else "Contract rate created.", "success")
        return redirect(url_for("tms.contract_rates", rate_id=saved_rate["id"]))

    return _render_rates_page(selected_rate_id=selected_rate_id)


@tms.route("/rates/upload", methods=["POST"])
def upload_contract_rates():
    upload = request.files.get("tariff_file")
    if not upload or not _normalize_text(upload.filename):
        flash("Choose a tariff CSV file to upload.", "danger")
        return redirect(url_for("tms.contract_rates"))

    try:
        payload = upload.read().decode("utf-8-sig")
    except UnicodeDecodeError:
        flash("Tariff CSV must be UTF-8 encoded.", "danger")
        return redirect(url_for("tms.contract_rates"))

    reader = csv.DictReader(io.StringIO(payload))
    required_columns = {
        "origin",
        "destination",
        "mode",
        "rate_20ft",
        "rate_40ft",
        "rate_40hc",
        "currency",
        "valid_from",
        "valid_to",
    }
    headers = {(_normalize_text(name) or "") for name in (reader.fieldnames or [])}
    if not required_columns.issubset(headers):
        missing = ", ".join(sorted(required_columns - headers))
        flash(f"Tariff CSV is missing required columns: {missing}", "danger")
        return redirect(url_for("tms.contract_rates"))

    conn = get_db()
    imported = 0
    try:
        for row_number, row in enumerate(reader, start=2):
            normalized_row = {(_normalize_text(key) or ""): value for key, value in row.items()}
            if not any(_normalize_text(value) for value in normalized_row.values()):
                continue
            try:
                save_contract_rate(
                    origin=normalized_row.get("origin", ""),
                    destination=normalized_row.get("destination", ""),
                    mode=normalized_row.get("mode", ""),
                    rate_20ft=normalized_row.get("rate_20ft", ""),
                    rate_40ft=normalized_row.get("rate_40ft", ""),
                    rate_40hc=normalized_row.get("rate_40hc", ""),
                    currency=normalized_row.get("currency", "USD"),
                    valid_from=normalized_row.get("valid_from", ""),
                    valid_to=normalized_row.get("valid_to", ""),
                    conn=conn,
                )
            except ValueError as exc:
                conn.rollback()
                flash(f"Tariff upload failed on row {row_number}: {exc}", "danger")
                return redirect(url_for("tms.contract_rates"))
            imported += 1

        conn.commit()
    finally:
        conn.close()

    flash(f"Imported {imported} contract rate rows.", "success")
    return redirect(url_for("tms.contract_rates"))


@tms.route("/rates/<int:rate_id>/delete", methods=["POST"])
def remove_contract_rate(rate_id):
    try:
        deleted_rate = delete_contract_rate(rate_id)
    except ValueError as exc:
        flash(str(exc), "danger")
    else:
        flash(
            f"Deleted contract rate for {deleted_rate['origin']} -> {deleted_rate['destination']} ({deleted_rate['mode']}).",
            "warning",
        )
    return redirect(url_for("tms.contract_rates"))


@tms.route("/rates/lookup")
def contract_rate_lookup():
    origin = request.args.get("origin", "")
    destination = request.args.get("destination", "")
    mode = request.args.get("mode", "")
    containers = request.args.get("containers", "")
    if not _normalize_text(origin) or not _normalize_text(destination) or not _normalize_text(mode):
        return jsonify({"ok": False, "error": "origin, destination, and mode are required."}), 400

    try:
        contract_rate = find_best_contract_rate(
            origin=origin,
            destination=destination,
            mode=mode,
            containers=containers,
            reference_date=request.args.get("date") or date.today().isoformat(),
        )
    except ValueError as exc:
        return jsonify({"ok": False, "error": str(exc)}), 400

    if not contract_rate:
        return jsonify({"ok": False, "error": "No matching contract rate found."}), 404

    return jsonify({"ok": True, **_serialize_contract_rate(contract_rate)})


@tms.route("/rates/shop")
def rate_shop():
    form_values = _rate_shop_form_defaults(request.args)
    form_error = None
    status_code = 200
    try:
        results, lookup_payload, form_error = _build_rate_shop_results(form_values)
    except ValueError as exc:
        results = []
        lookup_payload = None
        form_error = str(exc)
        status_code = 400

    return (
        render_template(
            "tms/rate_shop.html",
            form_values=form_values,
            rate_results=results,
            rate_benchmark=lookup_payload,
            form_error=form_error,
        ),
        status_code,
    )


@tms.route("/intake", methods=["GET", "POST"])
def intake():
    status_code = 200

    if request.method == "POST":
        action = (_normalize_text(request.form.get("action")) or "extract").lower()

        if action == "extract":
            try:
                extracted_payload, raw_text = extract_intake_payload(
                    email_text=request.form.get("email_text", ""),
                    uploaded_file=request.files.get("document"),
                )
                intake_record = create_intake_document(
                    raw_text=raw_text,
                    extracted_payload=extracted_payload,
                    confidence=extracted_payload["confidence"],
                    status="processed",
                )
                flash("Order intake extracted. Review the fields below before creating the shipment.", "success")
                return redirect(url_for("tms.intake", intake_id=intake_record["id"]))
            except ValueError as exc:
                flash(str(exc), "danger")
                status_code = 400

        elif action in {"save_review", "create_shipment"}:
            intake_id = request.form.get("intake_id", type=int)
            intake_record = get_intake_document(intake_id)
            if not intake_record:
                flash("Intake record not found.", "danger")
                return redirect(url_for("tms.intake"))

            try:
                review_payload, confidence = _reviewed_intake_payload(intake_record)
                update_intake_document(
                    intake_id,
                    extracted_payload=review_payload,
                    confidence=confidence,
                    status="reviewed",
                )

                if action == "save_review":
                    flash("Intake review saved.", "success")
                    return redirect(url_for("tms.intake", intake_id=intake_id))

                shipment_payload = _build_shipment_payload_from_intake(review_payload, intake_id)
                result = create_shipment_from_intake(intake_id, shipment_payload)
                snapshot = result["shipment"]
                shipment_ref = snapshot["shipment"]["shipment_ref"]
                if result.get("created", True):
                    try:
                        notify_shipment_created(shipment_ref)
                    except Exception:
                        pass
                    flash(f"Shipment {shipment_ref} created from intake #{intake_id}.", "success")
                else:
                    flash(f"Intake #{intake_id} is already linked to shipment {shipment_ref}.", "info")
                return redirect(url_for("tms.view_shipment", ref=shipment_ref))
            except (LookupError, ValueError) as exc:
                flash(str(exc), "danger")
                status_code = 400

        else:
            flash("Unknown intake action.", "danger")
            status_code = 400

    selected_intake_id = request.args.get("intake_id", type=int)
    if request.method == "POST" and request.form.get("intake_id"):
        selected_intake_id = request.form.get("intake_id", type=int)
    selected_intake = get_intake_document(selected_intake_id)
    review_payload = _hydrate_intake_review(selected_intake) if selected_intake else None
    recent_intakes = list_intake_documents(limit=25)

    return (
        render_template(
            "tms/intake.html",
            selected_intake=selected_intake,
            review_payload=review_payload,
            recent_intakes=recent_intakes,
            intake_field_specs=INTAKE_FIELD_SPECS,
            intake_status_styles=INTAKE_STATUS_STYLES,
        ),
        status_code,
    )


@tms.route("/documents", methods=["GET", "POST"])
def documents():
    default_shipment_ref = _normalize_text(
        request.args.get("shipment_ref") or request.form.get("default_shipment_ref")
    )
    review = None
    matched_shipment = None
    status_code = 200

    if request.method == "POST":
        action = (_normalize_text(request.form.get("action")) or "upload").lower()
        if action == "upload":
            uploaded_file = request.files.get("document")
            if not uploaded_file or not getattr(uploaded_file, "filename", ""):
                flash("Choose a document to upload.", "danger")
                status_code = 400
            else:
                try:
                    review = extract_document_payload(
                        uploaded_file,
                        known_shipment_refs=list_shipment_refs(),
                        preferred_shipment_ref=default_shipment_ref,
                    )
                    matched_shipment = find_shipment_by_ref(review["fields"].get("shipment_ref"))
                except Exception as exc:
                    flash(str(exc), "danger")
                    status_code = 400
        elif action == "save":
            review = _document_review_from_form()
            if review["doc_type"] not in DOCUMENT_TYPE_CHOICES:
                review["doc_type"] = "Unknown"
            matched_shipment = find_shipment_by_ref(review["fields"].get("shipment_ref"))
            try:
                save_result = save_document_record(
                    filename=review["filename"],
                    doc_type=review["doc_type"],
                    extracted_payload=review,
                    shipment_ref=review["fields"].get("shipment_ref", ""),
                    apply_to_shipment=request.form.get("apply_to_shipment") in {"1", "true", "on", "yes"},
                )
                if save_result["shipment"]:
                    flash(
                        f"Document saved and linked to {save_result['shipment']['shipment_ref']}.",
                        "success",
                    )
                    return redirect(url_for("tms.view_shipment", ref=save_result["shipment"]["shipment_ref"]))
                flash("Document saved.", "success")
                return redirect(url_for("tms.documents"))
            except Exception as exc:
                flash(str(exc), "danger")
                status_code = 400
        else:
            flash("Unknown document action.", "danger")
            status_code = 400

    recent_documents = list_documents(limit=25)
    return (
        render_template(
            "tms/documents.html",
            review=review,
            matched_shipment=matched_shipment,
            recent_documents=recent_documents,
            doc_type_choices=DOCUMENT_TYPE_CHOICES,
            default_shipment_ref=default_shipment_ref,
        ),
        status_code,
    )


@tms.route("/loads")
def loads():
    loads_list = get_all_loads_context()
    load_stats = {
        "total": len(loads_list),
        "planning": sum(1 for l in loads_list if l["status"] == "Planning"),
        "in_transit": sum(1 for l in loads_list if l["status"] in ("Dispatched", "In Transit")),
        "delivered": sum(1 for l in loads_list if l["status"] == "Delivered"),
        "assigned_shipments": sum(l.get("shipment_count", 0) for l in loads_list),
    }
    # Drivers for the new load modal
    try:
        db_conn = get_db()
        drivers = [dict(d) for d in db_conn.execute(
            "SELECT id, name FROM drivers ORDER BY name"
        ).fetchall()]
        db_conn.close()
    except Exception:
        drivers = []
    # Stub legacy template variables so the old template sections don't crash
    _load_form_values = {"carrier_id": "", "status": LOAD_STATUSES[0], "shipment_refs": []}
    return render_template(
        "tms/loads.html",
        loads=loads_list,
        load_stats=load_stats,
        equipment_types=EQUIPMENT_TYPES,
        drivers=drivers,
        load_form_error=None,
        load_form_values=_load_form_values,
        load_statuses=LOAD_STATUSES,
        load_carriers=[],
        available_shipments=[],
        available_shipments_json=[],
        selected_load=None,
    )


@tms.route("/loads/new", methods=["POST"])
def loads_new():
    equipment = request.form.get("equipment_type", "dry_van")
    trailer = request.form.get("trailer_number", "")
    driver_id = request.form.get("driver_id") or None
    notes = request.form.get("notes", "")
    load_id = create_ltl_load(equipment, trailer, driver_id, notes)
    return redirect(url_for("tms.load_builder", load_id=load_id))


@tms.route("/loads/builder/<int:load_id>")
def load_builder(load_id):
    ctx = get_load_builder_context(load_id)
    if not ctx:
        flash("Load not found", "error")
        return redirect(url_for("tms.loads"))
    return render_template("tms/load_builder.html", load=ctx, equipment_types=EQUIPMENT_TYPES)


@tms.route("/loads/builder/<int:load_id>/add-shipment", methods=["POST"])
def load_add_shipment(load_id):
    ref = request.form.get("shipment_ref", "").strip()
    ok, msg = add_shipment_to_load(load_id, ref)
    return jsonify(ok=ok, message=msg)


@tms.route("/loads/builder/<int:load_id>/remove-shipment", methods=["POST"])
def load_remove_shipment(load_id):
    ref = request.form.get("shipment_ref", "").strip()
    remove_shipment_from_load(load_id, ref)
    return jsonify(ok=True)


@tms.route("/loads/builder/<int:load_id>/add-stop", methods=["POST"])
def load_add_stop(load_id):
    add_load_stop(
        load_id,
        request.form.get("stop_type", "pickup"),
        request.form.get("company_name", ""),
        request.form.get("address", ""),
        request.form.get("city", ""),
        request.form.get("state", ""),
        request.form.get("zip", ""),
        request.form.get("shipment_ref", ""),
        request.form.get("scheduled_time", ""),
        request.form.get("notes", ""),
    )
    return jsonify(ok=True)


@tms.route("/loads/builder/<int:load_id>/reorder-stops", methods=["POST"])
def load_reorder_stops(load_id):
    data = request.get_json(silent=True) or {}
    reorder_load_stops(load_id, data.get("order", []))
    return jsonify(ok=True)


@tms.route("/loads/builder/<int:load_id>/convert-ftl", methods=["POST"])
def load_convert_ftl(load_id):
    ref = convert_load_to_ftl(load_id)
    return jsonify(ok=True, load_ref=ref)


@tms.route("/loads/builder/<int:load_id>/message", methods=["POST"])
def load_send_message(load_id):
    data = request.get_json(silent=True) or {}
    send_load_message(load_id, data.get("sender", "dispatcher"), data.get("message", ""))
    return jsonify(ok=True)


@tms.route("/loads/builder/<int:load_id>/messages")
def load_get_messages(load_id):
    return jsonify(messages=get_load_messages(load_id))


@tms.route("/loads/builder/<int:load_id>/approve-deviation/<int:stop_id>", methods=["POST"])
def load_approve_deviation(load_id, stop_id):
    approve_stop_deviation(stop_id)
    return jsonify(ok=True)


@tms.route("/loads/builder/<int:load_id>/release-accounting", methods=["POST"])
def load_release_accounting(load_id):
    release_load_to_accounting(load_id)
    return jsonify(ok=True)


@tms.route("/loads/<load_ref>")
def view_load(load_ref):
    context = _get_load_board_context(selected_load_ref=load_ref)
    if load_ref and not context["selected_load"]:
        flash("Load not found.", "danger")
        return redirect(url_for("tms.loads"))
    return render_template("tms/loads.html", **context)


@tms.route("/loads/<load_ref>/status", methods=["POST"])
def set_load_status(load_ref):
    try:
        load = update_load_status(load_ref, request.form.get("status"))
    except ValueError as exc:
        flash(str(exc), "danger")
        return redirect(url_for("tms.view_load", load_ref=load_ref))

    flash(f"Load {load['load_ref']} updated to {load['status']}.", "success")
    return redirect(url_for("tms.view_load", load_ref=load["load_ref"]))


@tms.route("/loadboard")
def loadboard():
    form_error = None
    status_code = 200
    try:
        filters = _loadboard_filters(request.args)
    except ValueError as exc:
        filters = _loadboard_filters()
        form_error = str(exc)
        status_code = 400

    context = _get_loadboard_listing_context(public_board=False, filters=filters)
    return render_template("tms/loadboard.html", form_error=form_error, **context), status_code


@public.route("/loadboard")
def public_loadboard():
    form_error = None
    status_code = 200
    try:
        filters = _loadboard_filters(request.args)
    except ValueError as exc:
        filters = _loadboard_filters()
        form_error = str(exc)
        status_code = 400

    context = _get_loadboard_listing_context(public_board=True, filters=filters)
    return render_template("tms/loadboard.html", form_error=form_error, **context), status_code


@public.route("/loadboard/interest", methods=["POST"])
def loadboard_interest():
    next_url = _normalize_text(request.form.get("next")) or url_for("public.public_loadboard")
    if not next_url.startswith("/loadboard") and not next_url.startswith("/tms/loadboard"):
        next_url = url_for("public.public_loadboard")
    rate_limit_key = f"loadboard-interest:{_request_ip_address() or 'unknown'}"
    if not LOADBOARD_INTEREST_RATE_LIMITER.allow(rate_limit_key):
        flash("Too many interest submissions. Try again in a few minutes.", "danger")
        return redirect(next_url)

    conn = get_db()
    try:
        token = _create_loadboard_interest_tender(
            conn,
            request.form.get("shipment_ref", ""),
            carrier_name=request.form.get("carrier_name", ""),
            contact_email=request.form.get("contact_email", ""),
            contact_phone=request.form.get("contact_phone", ""),
            country=request.form.get("country", ""),
        )
        conn.commit()
    except ValueError as exc:
        conn.rollback()
        flash(str(exc), "danger")
        return redirect(next_url)
    finally:
        conn.close()

    flash("Interest received. Finish the tender response below.", "success")
    return redirect(url_for("tms.respond_to_tender", token=token))


@tms.route("/dispatch")
def dispatch_board():
    return render_template("tms/dispatch.html", **_get_dispatch_board_context())


@tms.route("/shipments")
def shipments():
    status_filter = request.args.get("status", "")
    init_tms_db()
    conn = get_db()
    c = conn.cursor()
    query = """
        SELECT
            s.*,
            d.name AS driver_name,
            v.truck_number AS vehicle_truck_number,
            l.load_ref,
            l.status AS load_status
        FROM shipments s
        LEFT JOIN drivers d ON d.id = s.driver_id
        LEFT JOIN vehicles v ON v.id = s.vehicle_id
        LEFT JOIN load_shipments ls ON ls.shipment_ref = s.shipment_ref
        LEFT JOIN loads l ON l.id = ls.load_id
    """
    params = []
    if status_filter:
        query += " WHERE s.status = ?"
        params.append(status_filter)
    query += " ORDER BY s.created_at DESC"
    rows = c.execute(query, params).fetchall()
    conn.close()
    return render_template("tms/shipments.html", shipments=rows, status_filter=status_filter)


@tms.route("/claims/evidence/<path:filename>")
def claim_evidence(filename):
    return send_from_directory(_claims_upload_dir(), os.path.basename(filename))


@tms.route("/claims")
def claims_board():
    status_filter = _normalize_text(request.args.get("status"))
    carrier_filter = _normalize_text(request.args.get("carrier_id"))
    claim_type_filter = _normalize_text(request.args.get("claim_type"))
    shipment_ref_filter = _normalize_text(request.args.get("shipment_ref"))
    selected_claim_id = request.args.get("claim_id", type=int)

    try:
        context = _claims_board_context(
            status=status_filter,
            carrier_id=carrier_filter,
            claim_type=claim_type_filter,
            shipment_ref=shipment_ref_filter,
            selected_claim_id=selected_claim_id,
        )
    except ValueError as exc:
        flash(str(exc), "danger")
        return redirect(url_for("tms.claims_board"))

    return render_template(
        "tms/claims.html",
        page_mode="list",
        claim_form_values=_claim_form_defaults({"shipment_ref": shipment_ref_filter}),
        claim_form_error=None,
        claim_update_form_values=_claim_update_form_defaults(context["selected_claim"]),
        claim_update_form_error=None,
        claim_response_form_values=_claim_response_form_defaults(),
        claim_response_form_error=None,
        submitted=False,
        **context,
    )


@tms.route("/claims/new", methods=["GET", "POST"])
def new_claim():
    form_values = _claim_form_defaults(request.form if request.method == "POST" else request.args)
    form_error = None
    status_code = 200
    linked_shipment = find_shipment_by_ref(form_values["shipment_ref"]) if form_values["shipment_ref"] else None

    if request.method == "POST":
        evidence_name = ""
        try:
            evidence_name = _save_claim_evidence(request.files.get("evidence"), form_values["shipment_ref"])
            claim = create_freight_claim(
                shipment_ref=form_values["shipment_ref"],
                claim_type=form_values["claim_type"],
                description=form_values["description"],
                claimed_amount=form_values["claimed_amount"],
                currency=form_values["currency"],
                evidence_path=evidence_name,
            )
            flash(f"Claim #{claim['id']} filed for shipment {claim['shipment_ref']}.", "success")
            return redirect(url_for("tms.claims_board", claim_id=claim["id"]))
        except ValueError as exc:
            if evidence_name:
                evidence_path = _claim_evidence_fs_path(evidence_name)
                if evidence_path and os.path.exists(evidence_path):
                    os.remove(evidence_path)
            form_error = str(exc)
            status_code = 400
            linked_shipment = find_shipment_by_ref(form_values["shipment_ref"]) if form_values["shipment_ref"] else None

    return (
        render_template(
            "tms/claims.html",
            page_mode="new",
            claim_form_values=form_values,
            claim_form_error=form_error,
            claim_update_form_values=_claim_update_form_defaults(),
            claim_update_form_error=None,
            claim_response_form_values=_claim_response_form_defaults(),
            claim_response_form_error=None,
            linked_shipment=linked_shipment,
            recent_claims=[
                _build_claim_view_model(claim)
                for claim in list_freight_claims(shipment_ref=form_values["shipment_ref"])
            ]
            if form_values["shipment_ref"]
            else [],
            claim_types=CLAIM_TYPES,
            claim_statuses=CLAIM_STATUSES,
            claim_status_styles=CLAIM_STATUS_STYLES,
            claim_filter_carriers=list_freight_claim_filter_carriers(),
            shipment_refs=list_shipment_refs(),
            claims=[],
            claim_stats={"total": 0, "filed": 0, "under_review": 0, "approved": 0, "paid": 0, "denied": 0},
            selected_claim=None,
            claim_filters={"status": "", "carrier_id": "", "claim_type": "", "shipment_ref": ""},
            submitted=False,
        ),
        status_code,
    )


@tms.route("/claims/<int:claim_id>/status", methods=["POST"])
def update_claim_status(claim_id):
    redirect_args = {
        "claim_id": claim_id,
        "status": _normalize_text(request.form.get("filter_status")),
        "carrier_id": _normalize_text(request.form.get("filter_carrier_id")),
        "claim_type": _normalize_text(request.form.get("filter_claim_type")),
        "shipment_ref": _normalize_text(request.form.get("filter_shipment_ref")),
    }
    redirect_args = {key: value for key, value in redirect_args.items() if value not in {"", None}}

    try:
        claim = update_freight_claim(
            claim_id,
            status=request.form.get("status"),
            settlement_amount=request.form.get("settlement_amount"),
        )
        flash(f"Claim #{claim['id']} updated to {claim['status']}.", "success")
    except ValueError as exc:
        flash(str(exc), "danger")

    return redirect(url_for("tms.claims_board", **redirect_args))


@tms.route("/claims/<int:claim_id>/respond/<token>", methods=["GET", "POST"])
def respond_to_claim(claim_id, token):
    form_error = None
    status_code = 200
    submitted = request.args.get("submitted") == "1"
    claim = get_freight_claim(claim_id, response_token=token)
    if not claim:
        return (
            render_template(
                "tms/claims.html",
                page_mode="respond",
                claim=None,
                submitted=False,
                claim_response_form_values=_claim_response_form_defaults(),
                claim_response_form_error="This claim response link is invalid or expired.",
                claim_form_values=_claim_form_defaults(),
                claim_form_error=None,
                claim_update_form_values=_claim_update_form_defaults(),
                claim_update_form_error=None,
                claim_types=CLAIM_TYPES,
                claim_statuses=CLAIM_STATUSES,
                claim_status_styles=CLAIM_STATUS_STYLES,
                claim_filter_carriers=[],
                shipment_refs=[],
                claims=[],
                claim_stats={"total": 0, "filed": 0, "under_review": 0, "approved": 0, "paid": 0, "denied": 0},
                selected_claim=None,
                claim_filters={"status": "", "carrier_id": "", "claim_type": "", "shipment_ref": ""},
            ),
            404,
        )

    if request.method == "POST":
        try:
            claim = respond_to_freight_claim(
                claim_id,
                response_token=token,
                carrier_notes=request.form.get("carrier_notes"),
                counter_offer=request.form.get("counter_offer"),
            )
            flash("Carrier response submitted.", "success")
            return redirect(url_for("tms.respond_to_claim", claim_id=claim_id, token=token, submitted=1))
        except ValueError as exc:
            form_error = str(exc)
            status_code = 400
            claim = get_freight_claim(claim_id, response_token=token)

    claim_view = _build_claim_view_model(claim)
    form_values = _claim_response_form_defaults(claim_view)
    if request.method == "POST":
        form_values = {
            "carrier_notes": _normalize_text(request.form.get("carrier_notes")),
            "counter_offer": _normalize_text(request.form.get("counter_offer")),
        }

    return (
        render_template(
            "tms/claims.html",
            page_mode="respond",
            claim=claim_view,
            submitted=submitted,
            claim_response_form_values=form_values,
            claim_response_form_error=form_error,
            claim_form_values=_claim_form_defaults(),
            claim_form_error=None,
            claim_update_form_values=_claim_update_form_defaults(claim_view),
            claim_update_form_error=None,
            claim_types=CLAIM_TYPES,
            claim_statuses=CLAIM_STATUSES,
            claim_status_styles=CLAIM_STATUS_STYLES,
            claim_filter_carriers=[],
            shipment_refs=[],
            claims=[],
            claim_stats={"total": 0, "filed": 0, "under_review": 0, "approved": 0, "paid": 0, "denied": 0},
            selected_claim=None,
            claim_filters={"status": "", "carrier_id": "", "claim_type": "", "shipment_ref": ""},
        ),
        status_code,
    )


@tms.route("/audit", methods=["GET", "POST"])
def audit():
    requested_status = _normalize_text(request.args.get("status"))
    status_filter = requested_status if requested_status in CARRIER_INVOICE_STATUS_STYLES else ""
    form_values = _carrier_invoice_form_defaults(
        {"shipment_ref": _normalize_text(request.args.get("shipment_ref"))}
    )
    form_error = None
    pdf_notices = []
    status_code = 200

    init_tms_db()
    conn = get_db()
    try:
        if request.method == "POST":
            action = (_normalize_text(request.form.get("action")) or "create").lower()
            posted_filter = _normalize_text(request.form.get("status_filter"))
            status_filter = posted_filter if posted_filter in CARRIER_INVOICE_STATUS_STYLES else ""
            redirect_args = {"status": status_filter} if status_filter else {}

            if action == "create":
                form_values = _carrier_invoice_form_defaults(request.form)
                try:
                    parsed_fields, pdf_notices = _extract_carrier_invoice_pdf_fields(
                        conn, request.files.get("invoice_pdf")
                    )

                    if not form_values["carrier_name"] and parsed_fields.get("carrier_name"):
                        form_values["carrier_name"] = parsed_fields["carrier_name"]
                    if not form_values["shipment_ref"] and parsed_fields.get("shipment_ref"):
                        form_values["shipment_ref"] = parsed_fields["shipment_ref"]
                    if not form_values["invoice_no"] and parsed_fields.get("invoice_no"):
                        form_values["invoice_no"] = parsed_fields["invoice_no"]
                    if not _normalize_text(form_values["amount"]) and parsed_fields.get("amount") is not None:
                        form_values["amount"] = f"{float(parsed_fields['amount']):.2f}"
                    if not _normalize_text(request.form.get("currency")) and parsed_fields.get("currency"):
                        form_values["currency"] = parsed_fields["currency"]

                    carrier_name = _normalize_text(form_values["carrier_name"])
                    shipment_ref = _normalize_text(form_values["shipment_ref"])
                    invoice_no = _normalize_text(form_values["invoice_no"])
                    amount = _parse_carrier_invoice_amount(form_values["amount"])
                    currency = _parse_currency_code(form_values["currency"])
                    notes = _normalize_text(form_values["notes"])

                    if not carrier_name:
                        raise ValueError("Carrier is required.")
                    if not shipment_ref:
                        raise ValueError("Shipment reference is required.")
                    if not invoice_no:
                        raise ValueError("Invoice number is required.")
                    if amount is None:
                        raise ValueError("Invoice amount is required.")

                    shipment = _load_shipment(conn, shipment_ref)
                    if not shipment:
                        raise ValueError("Shipment reference was not found.")

                    duplicate = conn.execute(
                        """
                        SELECT id
                        FROM carrier_invoices
                        WHERE lower(invoice_no) = lower(?)
                          AND lower(carrier_name) = lower(?)
                        LIMIT 1
                        """,
                        (invoice_no, carrier_name),
                    ).fetchone()
                    if duplicate:
                        raise ValueError("This carrier invoice already exists for that carrier.")

                    variance_pct = _calculate_carrier_invoice_variance(amount, shipment["freight_rate"])
                    conn.execute(
                        """
                        INSERT INTO carrier_invoices
                            (shipment_ref, carrier_name, invoice_no, amount, currency, status, variance_pct, notes)
                        VALUES (?, ?, ?, ?, ?, 'Pending', ?, ?)
                        """,
                        (
                            shipment_ref,
                            carrier_name,
                            invoice_no,
                            amount,
                            currency,
                            variance_pct,
                            notes,
                        ),
                    )
                    conn.execute(
                        "INSERT INTO shipment_events (shipment_id, event_type, description) VALUES (?,?,?)",
                        (
                            shipment["id"],
                            "Carrier Invoice Logged",
                            f"Invoice {invoice_no} logged at {amount:,.2f} {currency}",
                        ),
                    )
                    conn.commit()

                    for notice in pdf_notices:
                        flash(notice, "info")
                    flash(f"Carrier invoice {invoice_no} matched to shipment {shipment_ref}.", "success")
                    if _is_carrier_invoice_flagged(variance_pct):
                        flash(
                            f"Invoice {invoice_no} was flagged at {variance_pct:+.2f}% variance.",
                            "warning",
                        )
                    return redirect(url_for("tms.audit", status="Pending"))
                except ValueError as exc:
                    conn.rollback()
                    form_error = str(exc)
                    status_code = 400

            elif action == "update_status":
                try:
                    invoice_id_raw = _normalize_text(request.form.get("invoice_id"))
                    if not invoice_id_raw.isdigit():
                        raise ValueError("Select a valid invoice.")

                    target_status = _normalize_text(request.form.get("status"))
                    if target_status not in CARRIER_INVOICE_STATUS_STYLES:
                        raise ValueError("Select a valid payment status.")

                    invoice = _load_carrier_invoice(conn, int(invoice_id_raw))
                    if not invoice:
                        raise ValueError("Carrier invoice not found.")

                    current_status = invoice["status"] or "Pending"
                    allowed_statuses = CARRIER_INVOICE_STATUS_TRANSITIONS.get(current_status, set())
                    if target_status != current_status and target_status not in allowed_statuses:
                        raise ValueError(f"Cannot move a {current_status.lower()} invoice to {target_status.lower()}.")

                    updated_notes = _append_carrier_invoice_note(
                        invoice["notes"],
                        target_status,
                        request.form.get("notes"),
                    )
                    conn.execute(
                        """
                        UPDATE carrier_invoices
                        SET status = ?, notes = ?
                        WHERE id = ?
                        """,
                        (target_status, updated_notes, invoice["id"]),
                    )

                    shipment = _load_shipment(conn, invoice["shipment_ref"])
                    if shipment:
                        conn.execute(
                            "INSERT INTO shipment_events (shipment_id, event_type, description) VALUES (?,?,?)",
                            (
                                shipment["id"],
                                "Carrier Invoice Updated",
                                f"Invoice {invoice['invoice_no']} marked {target_status.lower()}",
                            ),
                        )
                    conn.commit()
                    flash(
                        f"Carrier invoice {invoice['invoice_no']} marked {target_status.lower()}.",
                        "warning" if target_status == "Disputed" else "success",
                    )
                except ValueError as exc:
                    conn.rollback()
                    flash(str(exc), "danger")
                return redirect(url_for("tms.audit", **redirect_args))

            else:
                flash("Unknown audit action.", "danger")
                return redirect(url_for("tms.audit", **redirect_args))

        invoice_rows = _list_carrier_invoice_rows(conn, status_filter=status_filter)
        carriers = conn.execute(
            "SELECT name FROM tms_carriers WHERE active = 1 ORDER BY name COLLATE NOCASE ASC"
        ).fetchall()
        shipment_refs = conn.execute(
            "SELECT shipment_ref FROM shipments ORDER BY created_at DESC"
        ).fetchall()
        summary = _carrier_invoice_summary(conn)

        return (
            render_template(
                "tms/audit.html",
                invoices=invoice_rows,
                carriers=carriers,
                shipment_refs=shipment_refs,
                summary=summary,
                status_filter=status_filter,
                form_values=form_values,
                form_error=form_error,
                pdf_notices=pdf_notices,
                variance_threshold=CARRIER_INVOICE_VARIANCE_THRESHOLD,
                audit_status_styles=CARRIER_INVOICE_STATUS_STYLES,
            ),
            status_code,
        )
    finally:
        conn.close()


@tms.route("/freight-audit")
def freight_audit_page():
    init_tms_db()
    return render_template(
        "tms/freight_audit.html",
        audit_queue=freight_audit.get_audit_queue(),
        summary=freight_audit.get_audit_summary(),
    )


@tms.route("/freight-audit/run", methods=["POST"])
def freight_audit_run():
    init_tms_db()
    freight_audit.run_audit()
    flash("Audit complete", "success")
    return redirect(url_for("tms.freight_audit_page"))


@tms.route("/freight-audit/approve/<int:id>", methods=["POST"])
def freight_audit_approve(id):
    init_tms_db()
    if freight_audit.approve_item(id):
        flash("Audit item approved.", "success")
    else:
        flash("Audit item not found.", "danger")
    return redirect(url_for("tms.freight_audit_page"))


@tms.route("/freight-audit/dispute/<int:id>", methods=["POST"])
def freight_audit_dispute(id):
    init_tms_db()
    if freight_audit.dispute_item(id, request.form["notes"]):
        flash("Audit item disputed.", "warning")
    else:
        flash("Audit item not found.", "danger")
    return redirect(url_for("tms.freight_audit_page"))


@tms.route("/shipments/new", methods=["GET", "POST"])
def new_shipment():
    carriers, drivers, vehicles = _load_assignment_options()
    if request.method == "POST":
        conn = get_db()
        try:
            c = conn.cursor()
            ref = generate_ref()
            carrier_id, carrier_name = _resolve_carrier_selection(
                request.form.get("carrier_id"),
                request.form.get("carrier_name", ""),
            )
            driver_id = _parse_optional_id(request.form.get("driver_id"), "Driver")
            vehicle_id = _parse_optional_id(request.form.get("vehicle_id"), "Vehicle")

            driver = get_driver(driver_id, conn=conn) if driver_id else None
            vehicle = get_vehicle(vehicle_id, conn=conn) if vehicle_id else None
            if driver_id and not driver:
                raise ValueError("Selected driver was not found.")
            if vehicle_id and not vehicle:
                raise ValueError("Selected vehicle was not found.")

            rate_context = _build_shipment_rate_context(conn, request.form)
            shipment_values = (
                ref,
                request.form.get("status", "Draft"),
                request.form.get("customer_name") or request.form.get("shipper_name"),
                request.form.get("shipper_name"),
                request.form.get("shipper_address"),
                request.form.get("consignee_name"),
                request.form.get("consignee_address"),
                carrier_name,
                carrier_id,
                request.form.get("origin_port"),
                request.form.get("destination_port"),
                request.form.get("mode"),
                request.form.get("etd"),
                request.form.get("eta"),
                request.form.get("cargo_description"),
                request.form.get("containers"),
                request.form.get("weight_kg") or 0,
                request.form.get("volume_cbm") or 0,
                rate_context["freight_rate"],
                rate_context["currency"],
                request.form.get("incoterm", "FOB"),
                request.form.get("notes"),
                rate_context["contract_rate_id"],
                driver_id,
                vehicle_id,
                request.form.get("po_number", ""),
                request.form.get("pro_number", ""),
                request.form.get("bol_number", ""),
                request.form.get("pickup_number", ""),
                request.form.get("delivery_number", ""),
                request.form.get("seal_number", ""),
                request.form.get("trailer_number", ""),
                request.form.get("pickup_appt", ""),
                request.form.get("delivery_appt", ""),
                request.form.get("shipper_contact_name", ""),
                request.form.get("shipper_contact_phone", ""),
                request.form.get("consignee_contact_name", ""),
                request.form.get("consignee_contact_phone", ""),
                1 if request.form.get("hazmat") else 0,
                1 if request.form.get("temp_required") else 0,
                request.form.get("temp_min_f") or None,
                request.form.get("temp_max_f") or None,
                request.form.get("pieces") or 0,
                request.form.get("pallets") or 0,
                request.form.get("special_instructions", ""),
                request.form.get("payment_terms", "NET30"),
            )
            shipment_placeholders = ",".join("?" for _ in shipment_values)
            c.execute(
                f"""
                INSERT INTO shipments
                    (shipment_ref, status, customer_name, shipper_name, shipper_address, consignee_name, consignee_address,
                     carrier_name, carrier_id, origin_port, destination_port, mode, etd, eta, cargo_description, containers,
                     weight_kg, volume_cbm, freight_rate, currency, incoterm, notes, contract_rate_id, driver_id, vehicle_id,
                     po_number, pro_number, bol_number,
                     pickup_number, delivery_number, seal_number, trailer_number,
                     pickup_appt, delivery_appt,
                     shipper_contact_name, shipper_contact_phone,
                     consignee_contact_name, consignee_contact_phone,
                     hazmat, temp_required, temp_min_f, temp_max_f,
                     pieces, pallets, special_instructions, payment_terms)
                VALUES ({shipment_placeholders})
                """,
                shipment_values,
            )
            shipment_id = c.lastrowid
            refresh_shipment_carbon(conn, shipment_id=shipment_id)
            c.execute(
                "INSERT INTO shipment_events (shipment_id, event_type, description) VALUES (?,?,?)",
                (shipment_id, "Created", f"Shipment {ref} created"),
            )
            if driver or vehicle:
                assignment_parts = []
                if driver:
                    assignment_parts.append(f"driver {driver['name']}")
                if vehicle:
                    assignment_parts.append(f"vehicle {vehicle['truck_number']}")
                c.execute(
                    "INSERT INTO shipment_events (shipment_id, event_type, description) VALUES (?,?,?)",
                    (
                        shipment_id,
                        "Assignment",
                        f"Assigned {' and '.join(assignment_parts)}.",
                    ),
                )
            if rate_context["contract_rate"]:
                c.execute(
                    "INSERT INTO shipment_events (shipment_id, event_type, description) VALUES (?,?,?)",
                    (
                        shipment_id,
                        "Contract Rate Matched",
                        f"Auto-rated at {rate_context['freight_rate']:,.2f} {rate_context['currency']} using the {rate_context['contract_rate']['matched_rate_label']} contract rate.",
                    ),
                )
            conn.commit()
        except ValueError as exc:
            conn.rollback()
            flash(str(exc), "danger")
            conn.close()
            return render_template(
                "tms/new_shipment.html",
                carriers=carriers,
                drivers=drivers,
                vehicles=vehicles,
                form_values=request.form,
            ), 400
        conn.close()
        try:
            audit('CREATE', 'shipment', ref, new_value={'ref': ref, 'status': request.form.get('status', 'Draft')})
        except Exception:
            pass
        try:
            notify_shipment_created(ref)
        except Exception:
            pass
        flash(f"Shipment {ref} created successfully.", "success")
        return redirect(url_for("tms.view_shipment", ref=ref))

    prefill_values = {
        "status": _normalize_text(request.args.get("status")) or "Draft",
        "customer_name": _normalize_text(request.args.get("customer_name")),
        "shipper_name": _normalize_text(request.args.get("shipper_name")),
        "shipper_address": _normalize_text(request.args.get("shipper_address")),
        "consignee_name": _normalize_text(request.args.get("consignee_name")),
        "consignee_address": _normalize_text(request.args.get("consignee_address")),
        "origin_port": _normalize_text(request.args.get("origin")) or _normalize_text(request.args.get("origin_port")),
        "destination_port": _normalize_text(request.args.get("destination")) or _normalize_text(request.args.get("destination_port")),
        "mode": _normalize_text(request.args.get("mode")),
        "etd": _normalize_text(request.args.get("date")) or _normalize_text(request.args.get("etd")),
        "eta": _normalize_text(request.args.get("eta")),
        "cargo_description": _normalize_text(request.args.get("cargo_description")),
        "containers": _normalize_text(request.args.get("equipment_type") or request.args.get("containers")),
        "weight_kg": _normalize_text(request.args.get("weight_kg") or request.args.get("weight")),
        "volume_cbm": _normalize_text(request.args.get("volume_cbm")),
        "freight_rate": _normalize_text(request.args.get("freight_rate")),
        "currency": _normalize_text(request.args.get("currency")) or "USD",
        "incoterm": _normalize_text(request.args.get("incoterm")) or "FOB",
        "notes": _normalize_text(request.args.get("notes")),
        "carrier_id": _normalize_text(request.args.get("carrier_id")),
        "carrier_name": _normalize_text(request.args.get("carrier_name")),
        "rate_source": _normalize_text(request.args.get("rate_source")),
        "selected_rate_label": _normalize_text(request.args.get("selected_rate_label")),
        "selected_transit_days": _normalize_text(request.args.get("transit_days")),
    }
    return render_template(
        "tms/new_shipment.html",
        carriers=carriers,
        drivers=drivers,
        vehicles=vehicles,
        form_values=prefill_values,
    )


@tms.route("/pod/<ref>/<token>", methods=["GET", "POST"])
def capture_pod(ref, token):
    context = _load_pod_access_context(ref, token)
    if not context:
        return (
            render_template(
                "tms/pod_capture.html",
                shipment=None,
                pod_record=None,
                pod_photo_url="",
                pod_capture_url="",
                form_values={},
                form_error="Invalid or expired POD link.",
                saved=False,
            ),
            404,
        )

    shipment = context["shipment"]
    pod_record = context["pod_record"]
    form_error = None
    saved = request.args.get("saved") == "1"
    form_values = _pod_form_defaults(shipment, pod_record)

    if request.method == "POST":
        was_delivered = _normalize_text(shipment.get("status")) == "Delivered"
        had_pod_record = bool(pod_record)
        form_values = _pod_form_defaults(shipment, pod_record, request.form.to_dict())
        try:
            if not _normalize_text(request.form.get("signature_data")):
                raise ValueError("Signature is required.")
            if not _normalize_text(request.form.get("recipient_name")):
                raise ValueError("Recipient name is required.")
            if not _normalize_text(request.form.get("delivered_at")):
                raise ValueError("Delivery timestamp is required.")
            photo_upload = request.files.get("photo")
            if not (photo_upload and getattr(photo_upload, "filename", "")) and not (pod_record and pod_record.get("photo_path")):
                raise ValueError("Delivery photo is required.")
            photo_path = _save_pod_photo(photo_upload, shipment["shipment_ref"], (pod_record or {}).get("photo_path", ""))
            save_pod_record(
                shipment_ref=shipment["shipment_ref"],
                recipient_name=request.form.get("recipient_name", ""),
                signature_data=request.form.get("signature_data", ""),
                photo_path=photo_path,
                delivered_at=request.form.get("delivered_at", ""),
                notes=request.form.get("notes", ""),
            )
        except (LookupError, ValueError) as exc:
            form_error = str(exc)
            saved = False
        else:
            if not was_delivered:
                try:
                    notify_shipment_status_change(shipment["shipment_ref"], "Delivered")
                except Exception:
                    pass
            if not had_pod_record:
                try:
                    notify_pod_received(shipment["shipment_ref"])
                except Exception:
                    pass
            return redirect(url_for("tms.capture_pod", ref=ref, token=token, saved=1))

    pod_record = get_pod_record(ref) or pod_record
    pod_photo_url = url_for("tms.pod_photo", ref=ref, token=token) if pod_record and pod_record.get("photo_available") else ""
    return render_template(
        "tms/pod_capture.html",
        shipment=shipment,
        pod_record=pod_record,
        pod_photo_url=pod_photo_url,
        pod_capture_url=context["pod_capture_url"],
        form_values=form_values,
        form_error=form_error,
        saved=saved,
    )


@tms.route("/shipments/<ref>/pod/photo/<token>")
def pod_photo(ref, token):
    context = _load_pod_access_context(ref, token)
    if not context or not context["pod_record"] or not context["pod_record"].get("photo_available"):
        return "POD photo not found.", 404

    photo_path = context["pod_record"]["photo_path"]
    return send_from_directory(os.path.dirname(photo_path), os.path.basename(photo_path))


@tms.route("/shipments/<ref>")
def view_shipment(ref):
    context = _get_shipment_view_context(ref)
    if not context:
        flash("Shipment not found.", "danger")
        return redirect(url_for("tms.shipments"))
    context["contract_rate"] = context["shipment"].get("matched_contract_rate")
    context["tender_form_error"] = None
    context["tender_form_values"] = {
        "carrier_ids": [],
        "deadline_at": context["default_tender_deadline"],
        "notes": "",
    }
    context["legs"] = get_shipment_legs(ref)
    context["leg_modes"] = LEG_MODES
    context["leg_statuses"] = LEG_STATUSES
    return render_template("tms/view_shipment.html", **context)


@tms.route("/shipments/<ref>/legs", methods=["POST"])
def shipment_add_leg(ref):
    data = request.get_json(silent=True) or request.form.to_dict()
    existing = get_shipment_legs(ref)
    leg_num = len(existing) + 1
    add_shipment_leg(
        ref, leg_num,
        data.get("mode", "Truck"),
        data.get("carrier_name", ""),
        data.get("origin", ""),
        data.get("destination", ""),
        data.get("etd", ""),
        data.get("eta", ""),
        data.get("container_ref", ""),
        data.get("notes", ""),
    )
    return jsonify(ok=True)


@tms.route("/shipments/<ref>/legs/<int:leg_id>/status", methods=["POST"])
def shipment_update_leg_status(ref, leg_id):
    data = request.get_json(silent=True) or {}
    update_leg_status(leg_id, data.get("status", "Planned"))
    return jsonify(ok=True)


@tms.route("/shipments/<ref>/legs/<int:leg_id>", methods=["DELETE"])
def shipment_delete_leg(ref, leg_id):
    delete_shipment_leg(leg_id)
    return jsonify(ok=True)


@tms.route("/shipments/<ref>/legs/reorder", methods=["POST"])
def shipment_reorder_legs(ref):
    data = request.get_json(silent=True) or {}
    reorder_shipment_legs(ref, data.get("order", []))
    return jsonify(ok=True)


@tms.route("/track/ping", methods=["POST"])
def tracking_ping():
    payload = request.get_json(silent=True)
    if not isinstance(payload, dict):
        payload = request.form.to_dict()

    tracking_token = (
        payload.get("tracking_token")
        or payload.get("token")
        or request.headers.get("X-Tracking-Token")
    )
    tracking_context = get_driver_tracking_context(tracking_token) if tracking_token else None
    if not tracking_context:
        return jsonify({"ok": False, "error": "A valid driver tracking token is required."}), 403

    try:
        ping = save_tracking_ping(
            carrier_id=tracking_context["shipment"].get("carrier_id"),
            shipment_ref=tracking_context["shipment"]["shipment_ref"],
            lat=payload.get("lat"),
            lng=payload.get("lng"),
            speed=payload.get("speed"),
            timestamp=payload.get("timestamp"),
        )
        touch_tracking_driver_token(tracking_context["token"])
    except LookupError as exc:
        return jsonify({"ok": False, "error": str(exc)}), 404
    except ValueError as exc:
        return jsonify({"ok": False, "error": str(exc)}), 400

    tracking_page_context = get_tracking_page_context(ping["shipment_ref"])
    return jsonify(
        {
            "ok": True,
            "ping": ping,
            "tracking": {
                "eta_display": tracking_page_context["tracking"]["eta_display"],
                "eta_summary": tracking_page_context["tracking"]["eta_summary"],
                "last_ping_display": tracking_page_context["tracking"]["last_ping_display"],
                "gps_ping_count": tracking_page_context["tracking"]["gps_ping_count"],
            },
            "tracking_url": build_public_tracking_url(ping["shipment_ref"], external=True),
        }
    )


@tms.route("/track/driver/<token>", methods=["GET", "POST"])
def driver_tracking_page(token):
    context = get_driver_tracking_context(token)
    if not context:
        return render_template(
            "tms/driver_tracking.html",
            shipment=None,
            latest_ping=None,
            settings={},
            token=token,
            form_values={},
            form_error="This driver tracking link is invalid or expired.",
            public_tracking_url=None,
        ), 404

    form_values = {
        "lat": "",
        "lng": "",
        "speed": "",
        "timestamp": "",
    }
    form_error = None

    if request.method == "POST":
        form_values = {
            "lat": (request.form.get("lat") or "").strip(),
            "lng": (request.form.get("lng") or "").strip(),
            "speed": (request.form.get("speed") or "").strip(),
            "timestamp": (request.form.get("timestamp") or "").strip(),
        }
        try:
            save_tracking_ping(
                carrier_id=context["shipment"].get("carrier_id"),
                shipment_ref=context["shipment"]["shipment_ref"],
                lat=form_values["lat"],
                lng=form_values["lng"],
                speed=form_values["speed"],
                timestamp=form_values["timestamp"],
            )
            touch_tracking_driver_token(token)
            return redirect(url_for("tms.driver_tracking_page", token=token, saved=1))
        except (LookupError, ValueError) as exc:
            form_error = str(exc)

    if request.args.get("saved") == "1":
        flash("Location submitted.", "success")

    context = get_driver_tracking_context(token)
    return render_template(
        "tms/driver_tracking.html",
        shipment=context["shipment"],
        latest_ping=context["latest_ping"],
        settings=context["settings"],
        token=token,
        form_values=form_values,
        form_error=form_error,
        public_tracking_url=build_public_tracking_url(context["shipment"]["shipment_ref"], external=True),
    )


@tms.route("/shipments/<ref>/tender", methods=["POST"])
def create_tender(ref):
    form_values = {
        "carrier_ids": request.form.getlist("carrier_ids"),
        "deadline_at": (request.form.get("deadline_at") or "").strip(),
        "notes": (request.form.get("notes") or "").strip(),
    }

    conn = get_db()
    try:
        shipment = _load_shipment(conn, ref)
        if not shipment:
            flash("Shipment not found.", "danger")
            return redirect(url_for("tms.shipments"))

        _refresh_expired_tenders(conn)
        conn.commit()

        try:
            carrier_ids = _parse_tender_carrier_ids(form_values["carrier_ids"])
            deadline = _parse_tender_deadline(form_values["deadline_at"])
            placeholders = ",".join("?" for _ in carrier_ids)
            carriers = conn.execute(
                f"""
                SELECT id, name
                FROM tms_carriers
                WHERE active = 1
                  AND id IN ({placeholders})
                ORDER BY name COLLATE NOCASE ASC
                """,
                carrier_ids,
            ).fetchall()
            if len(carriers) != len(carrier_ids):
                raise ValueError("One or more selected carriers are unavailable.")

            cursor = conn.execute(
                """
                INSERT INTO tenders (shipment_id, deadline_at, notes, status, updated_at)
                VALUES (?, ?, ?, 'Open', CURRENT_TIMESTAMP)
                """,
                (
                    shipment["id"],
                    deadline.strftime("%Y-%m-%d %H:%M:%S"),
                    form_values["notes"],
                ),
            )
            tender_id = cursor.lastrowid

            for carrier in carriers:
                conn.execute(
                    """
                    INSERT INTO tender_responses
                        (tender_id, carrier_id, token, response_status, updated_at)
                    VALUES (?, ?, ?, 'Pending', CURRENT_TIMESTAMP)
                    """,
                    (tender_id, carrier["id"], _generate_tender_token(conn)),
                )

            conn.execute(
                "INSERT INTO shipment_events (shipment_id, event_type, description) VALUES (?,?,?)",
                (
                    shipment["id"],
                    "Tender Sent",
                    f"Tender sent to {len(carriers)} carriers with deadline {deadline.strftime('%Y-%m-%d %H:%M')}",
                ),
            )
            conn.commit()
            flash(f"Tender created for {len(carriers)} carriers.", "success")
            return redirect(url_for("tms.view_shipment", ref=ref))
        except ValueError as exc:
            conn.rollback()
            context = _get_shipment_view_context(ref)
            if not context:
                flash("Shipment not found.", "danger")
                return redirect(url_for("tms.shipments"))
            context["contract_rate"] = context["shipment"].get("matched_contract_rate")
            context["tender_form_error"] = str(exc)
            context["tender_form_values"] = {
                "carrier_ids": form_values["carrier_ids"],
                "deadline_at": form_values["deadline_at"] or context["default_tender_deadline"],
                "notes": form_values["notes"],
            }
            return render_template("tms/view_shipment.html", **context), 400
    finally:
        conn.close()


@tms.route("/tender/<token>/respond", methods=["GET", "POST"])
def respond_to_tender(token):
    form_error = None
    submitted = request.args.get("submitted") == "1"
    status_code = 200

    conn = get_db()
    try:
        _refresh_expired_tenders(conn)
        conn.commit()
        response_row = _load_tender_response(conn, token)
        if not response_row:
            flash("Tender link not found.", "danger")
            return redirect(url_for("tms.tenders_board"))

        if request.method == "POST":
            try:
                response = _build_tender_response_context(response_row)
                if response["is_closed"]:
                    raise ValueError("This tender is closed and can no longer accept responses.")

                rate_20ft = _parse_quote_amount(request.form.get("rate_20ft"), "20ft rate")
                rate_40ft = _parse_quote_amount(request.form.get("rate_40ft"), "40ft rate")
                rate_40hc = _parse_quote_amount(request.form.get("rate_40hc"), "40HC rate")
                if all(rate is None for rate in (rate_20ft, rate_40ft, rate_40hc)):
                    raise ValueError("Enter at least one rate.")

                transit_days = _parse_transit_days(request.form.get("transit_days"))
                notes = (request.form.get("notes") or "").strip()
                previously_submitted = response_row["response_status"] == "Submitted"

                conn.execute(
                    """
                    UPDATE tender_responses
                    SET rate_20ft = ?, rate_40ft = ?, rate_40hc = ?, transit_days = ?,
                        notes = ?, response_status = 'Submitted', submitted_at = CURRENT_TIMESTAMP,
                        updated_at = CURRENT_TIMESTAMP
                    WHERE id = ?
                    """,
                    (
                        rate_20ft,
                        rate_40ft,
                        rate_40hc,
                        transit_days,
                        notes,
                        response_row["id"],
                    ),
                )
                if not previously_submitted:
                    conn.execute(
                        "INSERT INTO shipment_events (shipment_id, event_type, description) VALUES (?,?,?)",
                        (
                            response_row["shipment_id"],
                            "Tender Response",
                            f"{response_row['carrier_name'] or 'Carrier'} submitted a tender response",
                        ),
                    )
                conn.commit()
                return redirect(url_for("tms.respond_to_tender", token=token, submitted=1))
            except ValueError as exc:
                conn.rollback()
                form_error = str(exc)
                status_code = 400

        response_row = _load_tender_response(conn, token)
        if not response_row:
            flash("Tender link not found.", "danger")
            return redirect(url_for("tms.tenders_board"))

        response = _build_tender_response_context(response_row)
        form_values = {
            "rate_20ft": "" if response["rate_20ft"] is None else response["rate_20ft"],
            "rate_40ft": "" if response["rate_40ft"] is None else response["rate_40ft"],
            "rate_40hc": "" if response["rate_40hc"] is None else response["rate_40hc"],
            "transit_days": "" if response["transit_days"] is None else response["transit_days"],
            "notes": response["notes"] or "",
        }
        if request.method == "POST":
            form_values = {
                "rate_20ft": (request.form.get("rate_20ft") or "").strip(),
                "rate_40ft": (request.form.get("rate_40ft") or "").strip(),
                "rate_40hc": (request.form.get("rate_40hc") or "").strip(),
                "transit_days": (request.form.get("transit_days") or "").strip(),
                "notes": (request.form.get("notes") or "").strip(),
            }

        return (
            render_template(
                "tms/tender_respond.html",
                tender_response=response,
                form_error=form_error,
                form_values=form_values,
                submitted=submitted,
            ),
            status_code,
        )
    finally:
        conn.close()


@tms.route("/spot-quotes")
def spot_quotes_board():
    quotes = get_spot_quotes()
    open_quotes = [quote for quote in quotes if quote["status"] == "open"]
    quote_stats = {
        "open": sum(1 for quote in quotes if quote["status"] == "open"),
        "awarded": sum(1 for quote in quotes if quote["status"] == "awarded"),
        "cancelled": sum(1 for quote in quotes if quote["status"] == "cancelled"),
        "responses": sum(int(quote.get("response_count") or 0) for quote in quotes),
    }
    return render_template(
        "tms/spot_quotes.html",
        quotes=open_quotes,
        quote_stats=quote_stats,
        today=date.today().isoformat(),
    )


@tms.route("/spot-quotes/create", methods=["POST"])
def create_spot_quote_route():
    try:
        quote_id = create_spot_quote(request.form)
    except ValueError as exc:
        flash(str(exc), "danger")
        return redirect(url_for("tms.spot_quotes_board"))

    flash("Spot quote created.", "success")
    return redirect(url_for("tms.spot_quote_detail_page", quote_id=quote_id))


@tms.route("/spot-quotes/<int:quote_id>")
def spot_quote_detail_page(quote_id):
    try:
        detail = get_spot_quote_detail(quote_id)
    except ValueError:
        detail = None
    if not detail:
        flash("Spot quote not found.", "danger")
        return redirect(url_for("tms.spot_quotes_board"))

    return render_template(
        "tms/spot_quote_detail.html",
        quote=detail["quote"],
        responses=detail["responses"],
        awarded_response=detail["awarded_response"],
    )


@tms.route("/spot-quotes/<int:quote_id>/blast", methods=["POST"])
def blast_spot_quote_route(quote_id):
    raw_emails = _normalize_text(request.form.get("carrier_emails"))
    carrier_emails = [email for email in re.split(r"[\s,;]+", raw_emails) if email]

    try:
        summary = blast_spot_quote_carriers(quote_id, carrier_emails)
    except (LookupError, ValueError) as exc:
        flash(str(exc), "danger")
    else:
        if summary["sent"] > 0:
            flash(f"Spot quote emailed to {summary['sent']} carrier(s).", "success")
            if summary["sent"] < summary["attempted"]:
                flash(
                    f"{summary['attempted'] - summary['sent']} carrier email(s) were skipped or failed.",
                    "warning",
                )
        else:
            flash("No carrier email was sent. Check SMTP or notification settings.", "warning")

    return redirect(url_for("tms.spot_quote_detail_page", quote_id=quote_id))


@tms.route("/spot-quotes/<int:quote_id>/award/<int:response_id>", methods=["POST"])
def award_spot_quote_route(quote_id, response_id):
    try:
        result = award_spot_quote(quote_id, response_id)
    except (LookupError, ValueError) as exc:
        flash(str(exc), "danger")
    else:
        flash(
            f"Spot quote {result['quote']['ref']} awarded to {result['response']['carrier_name']}.",
            "success",
        )

    return redirect(url_for("tms.spot_quote_detail_page", quote_id=quote_id))


@tms.route("/tenders")
def tenders_board():
    conn = get_db()
    try:
        _refresh_expired_tenders(conn)
        conn.commit()
        tenders = _build_tender_rows(conn)
    finally:
        conn.close()

    active_tenders = [tender for tender in tenders if tender["status"] == "Open"]
    closed_tenders = [tender for tender in tenders if tender["status"] != "Open"]
    tender_stats = {
        "open": len(active_tenders),
        "awarded": sum(1 for tender in tenders if tender["status"] == "Awarded"),
        "expired": sum(1 for tender in tenders if tender["status"] == "Expired"),
        "responses": sum(len(tender["responses"]) for tender in tenders),
    }
    return render_template(
        "tms/tenders.html",
        active_tenders=active_tenders,
        closed_tenders=closed_tenders,
        tender_stats=tender_stats,
    )


@tms.route("/tenders/<int:tender_id>/award", methods=["POST"])
def award_tender(tender_id):
    response_id_raw = (request.form.get("response_id") or "").strip()
    if not response_id_raw.isdigit():
        flash("Select a valid tender response.", "danger")
        return redirect(url_for("tms.tenders_board"))

    conn = get_db()
    try:
        _refresh_expired_tenders(conn)
        conn.commit()
        tender = conn.execute(
            """
            SELECT
                t.*,
                s.shipment_ref,
                s.containers
            FROM tenders t
            JOIN shipments s ON s.id = t.shipment_id
            WHERE t.id = ?
            """,
            (tender_id,),
        ).fetchone()
        if not tender:
            flash("Tender not found.", "danger")
            return redirect(url_for("tms.tenders_board"))
        if tender["status"] != "Open":
            flash("Only open tenders can be awarded.", "danger")
            return redirect(url_for("tms.tenders_board"))

        response = conn.execute(
            """
            SELECT tr.*, COALESCE(tc.name, '') AS carrier_name
            FROM tender_responses tr
            LEFT JOIN tms_carriers tc ON tc.id = tr.carrier_id
            WHERE tr.id = ? AND tr.tender_id = ?
            """,
            (int(response_id_raw), tender_id),
        ).fetchone()
        if not response:
            flash("Tender response not found.", "danger")
            return redirect(url_for("tms.tenders_board"))
        if response["response_status"] != "Submitted":
            flash("Only submitted responses can be awarded.", "danger")
            return redirect(url_for("tms.tenders_board"))

        rate_field, rate_value = _resolve_quote_rate(tender, response)
        if rate_value is None:
            flash("The selected response does not include a usable rate.", "danger")
            return redirect(url_for("tms.tenders_board"))

        conn.execute(
            """
            UPDATE tender_responses
            SET response_status = 'Not Awarded', updated_at = CURRENT_TIMESTAMP
            WHERE tender_id = ? AND id <> ? AND response_status IN ('Pending', 'Submitted', 'Expired', 'Not Awarded')
            """,
            (tender_id, response["id"]),
        )
        conn.execute(
            """
            UPDATE tender_responses
            SET response_status = 'Awarded', awarded_at = CURRENT_TIMESTAMP, updated_at = CURRENT_TIMESTAMP
            WHERE id = ?
            """,
            (response["id"],),
        )
        conn.execute(
            """
            UPDATE tenders
            SET status = 'Awarded', awarded_response_id = ?, updated_at = CURRENT_TIMESTAMP
            WHERE id = ?
            """,
            (response["id"], tender_id),
        )
        conn.execute(
            """
            UPDATE shipments
            SET carrier_id = ?, carrier_name = ?, freight_rate = ?, updated_at = CURRENT_TIMESTAMP
            WHERE id = ?
            """,
            (response["carrier_id"], response["carrier_name"], rate_value, tender["shipment_id"]),
        )
        conn.execute(
            "INSERT INTO shipment_events (shipment_id, event_type, description) VALUES (?,?,?)",
            (
                tender["shipment_id"],
                "Tender Awarded",
                f"{response['carrier_name'] or 'Carrier'} awarded at {rate_value:,.2f} using the {QUOTE_RATE_LABELS[rate_field]} rate",
            ),
        )
        conn.commit()
        flash("Tender awarded and shipment updated.", "success")
        return redirect(url_for("tms.tenders_board"))
    finally:
        conn.close()


@tms.route("/shipments/<ref>/quotes", methods=["GET", "POST"])
def shipment_quotes(ref):
    conn = get_db()
    form_error = None
    form_values = {}
    status_code = 200

    try:
        shipment = _load_shipment(conn, ref)
        if not shipment:
            flash("Shipment not found.", "danger")
            return redirect(url_for("tms.shipments"))

        _refresh_expired_quotes(conn, shipment["id"])
        conn.commit()

        if request.method == "POST":
            action = (request.form.get("action") or "create").strip().lower()
            form_values = request.form.to_dict()
            try:
                if action == "create":
                    _create_shipment_quote(conn, shipment)
                elif action in {"accept", "reject"}:
                    quote_id_raw = (request.form.get("quote_id") or "").strip()
                    if not quote_id_raw.isdigit():
                        raise ValueError("Select a valid quote.")

                    quote = _get_quote_for_shipment(conn, shipment["id"], int(quote_id_raw))
                    if not quote:
                        raise ValueError("Quote not found for this shipment.")

                    if action == "accept":
                        _accept_shipment_quote(conn, shipment, quote)
                    else:
                        _reject_shipment_quote(conn, shipment, quote)
                else:
                    raise ValueError("Unknown quote action.")

                conn.commit()
                return redirect(url_for("tms.shipment_quotes", ref=ref))
            except ValueError as exc:
                conn.rollback()
                form_error = str(exc)
                status_code = 400
                _refresh_expired_quotes(conn, shipment["id"])
                conn.commit()

        shipment = _load_shipment(conn, ref)
        carriers = conn.execute(
            "SELECT id, name FROM tms_carriers WHERE active = 1 ORDER BY name"
        ).fetchall()
        raw_quotes = conn.execute(
            """
            SELECT q.*, COALESCE(tc.name, '') AS carrier_name
            FROM quotes q
            LEFT JOIN tms_carriers tc ON tc.id = q.carrier_id
            WHERE q.shipment_id = ?
            ORDER BY
                CASE q.status
                    WHEN 'Accepted' THEN 0
                    WHEN 'Pending' THEN 1
                    WHEN 'Expired' THEN 2
                    WHEN 'Rejected' THEN 3
                    ELSE 4
                END,
                date(q.valid_until) ASC,
                q.created_at DESC
            """,
            (shipment["id"],),
        ).fetchall()

        quotes = _build_quote_rows(shipment, raw_quotes)
        best_rates = {}
        for field_name in QUOTE_RATE_LABELS:
            values = [quote[field_name] for quote in quotes if quote[field_name] is not None and quote["status"] != "Rejected"]
            best_rates[field_name] = min(values) if values else None

        accepted_quote = next((quote for quote in quotes if quote["status"] == "Accepted"), None)
        quote_counts = {
            "total": len(quotes),
            "pending": sum(1 for quote in quotes if quote["status"] == "Pending"),
            "accepted": sum(1 for quote in quotes if quote["status"] == "Accepted"),
            "expired": sum(1 for quote in quotes if quote["status"] == "Expired"),
        }
        lane_label = f"{shipment['origin_port'] or '-'} -> {shipment['destination_port'] or '-'}"

        return (
            render_template(
                "tms/quotes.html",
                shipment=shipment,
                lane_label=lane_label,
                carriers=carriers,
                quotes=quotes,
                best_rates=best_rates,
                quote_counts=quote_counts,
                accepted_quote=accepted_quote,
                form_error=form_error,
                form_values=form_values,
                today=date.today().isoformat(),
            ),
            status_code,
        )
    finally:
        conn.close()


@tms.route("/shipments/<ref>/edit", methods=["GET", "POST"])
def edit_shipment(ref):
    carriers, drivers, vehicles = _load_assignment_options()
    conn = get_db()
    c = conn.cursor()
    shipment = c.execute("SELECT * FROM shipments WHERE shipment_ref=?", (ref,)).fetchone()
    if not shipment:
        conn.close()
        flash("Shipment not found.", "danger")
        return redirect(url_for("tms.shipments"))

    if request.method == "POST":
        status_notice_error = None
        status_changed = False
        new_status = ""
        try:
            previous_status = shipment["status"]
            rate_context = _build_shipment_rate_context(conn, request.form)
            carrier_id, carrier_name = _resolve_carrier_selection(
                request.form.get("carrier_id"),
                request.form.get("carrier_name", ""),
            )
            driver_id = _parse_optional_id(request.form.get("driver_id"), "Driver")
            vehicle_id = _parse_optional_id(request.form.get("vehicle_id"), "Vehicle")

            driver = get_driver(driver_id, conn=conn) if driver_id else None
            vehicle = get_vehicle(vehicle_id, conn=conn) if vehicle_id else None
            if driver_id and not driver:
                raise ValueError("Selected driver was not found.")
            if vehicle_id and not vehicle:
                raise ValueError("Selected vehicle was not found.")

            c.execute(
                """
                UPDATE shipments SET
                    status=?, customer_name=?, shipper_name=?, shipper_address=?, consignee_name=?, consignee_address=?,
                    carrier_name=?, carrier_id=?, origin_port=?, destination_port=?, mode=?, etd=?, eta=?,
                    cargo_description=?, containers=?, weight_kg=?, volume_cbm=?,
                    freight_rate=?, currency=?, incoterm=?, notes=?, contract_rate_id=?, driver_id=?, vehicle_id=?,
                    po_number=?, pro_number=?, bol_number=?, pickup_number=?, delivery_number=?,
                    trailer_number=?, seal_number=?, pickup_appt=?, delivery_appt=?,
                    shipper_contact_name=?, shipper_contact_phone=?,
                    consignee_contact_name=?, consignee_contact_phone=?,
                    hazmat=?, temp_required=?, temp_min_f=?, temp_max_f=?,
                    pieces=?, pallets=?, payment_terms=?, special_instructions=?,
                    updated_at=CURRENT_TIMESTAMP
                WHERE shipment_ref=?
                """,
                (
                    request.form.get("status"),
                    request.form.get("customer_name") or request.form.get("shipper_name"),
                    request.form.get("shipper_name"),
                    request.form.get("shipper_address"),
                    request.form.get("consignee_name"),
                    request.form.get("consignee_address"),
                    carrier_name,
                    carrier_id,
                    request.form.get("origin_port"),
                    request.form.get("destination_port"),
                    request.form.get("mode"),
                    request.form.get("etd"),
                    request.form.get("eta"),
                    request.form.get("cargo_description"),
                    request.form.get("containers"),
                    request.form.get("weight_kg") or 0,
                    request.form.get("volume_cbm") or 0,
                    rate_context["freight_rate"],
                    rate_context["currency"],
                    request.form.get("incoterm", "FOB"),
                    request.form.get("notes"),
                    rate_context["contract_rate_id"],
                    driver_id,
                    vehicle_id,
                    request.form.get("po_number"),
                    request.form.get("pro_number"),
                    request.form.get("bol_number"),
                    request.form.get("pickup_number"),
                    request.form.get("delivery_number"),
                    request.form.get("trailer_number"),
                    request.form.get("seal_number"),
                    request.form.get("pickup_appt"),
                    request.form.get("delivery_appt"),
                    request.form.get("shipper_contact_name"),
                    request.form.get("shipper_contact_phone"),
                    request.form.get("consignee_contact_name"),
                    request.form.get("consignee_contact_phone"),
                    1 if request.form.get("hazmat") else 0,
                    1 if request.form.get("temp_required") else 0,
                    request.form.get("temp_min_f") or None,
                    request.form.get("temp_max_f") or None,
                    request.form.get("pieces") or None,
                    request.form.get("pallets") or None,
                    request.form.get("payment_terms"),
                    request.form.get("special_instructions"),
                    ref,
                ),
            )
            refresh_shipment_carbon(conn, shipment_ref=ref)
            c.execute(
                "INSERT INTO shipment_events (shipment_id, event_type, description) VALUES (?,?,?)",
                (shipment["id"], "Updated", f"Shipment updated to status: {request.form.get('status')}"),
            )
            if driver or vehicle:
                assignment_parts = []
                if driver:
                    assignment_parts.append(f"driver {driver['name']}")
                if vehicle:
                    assignment_parts.append(f"vehicle {vehicle['truck_number']}")
                c.execute(
                    "INSERT INTO shipment_events (shipment_id, event_type, description) VALUES (?,?,?)",
                    (
                        shipment["id"],
                        "Assignment",
                        f"Assigned {' and '.join(assignment_parts)}.",
                    ),
                )
            if rate_context["contract_rate"]:
                c.execute(
                    "INSERT INTO shipment_events (shipment_id, event_type, description) VALUES (?,?,?)",
                    (
                        shipment["id"],
                        "Contract Rate Matched",
                        f"Shipment re-rated at {rate_context['freight_rate']:,.2f} {rate_context['currency']} using the {rate_context['contract_rate']['matched_rate_label']} contract rate.",
                    ),
                )
            new_status = request.form.get("status")
            status_changed = bool(
                _normalize_text(new_status)
                and _normalize_text(new_status) != _normalize_text(previous_status)
            )
            if status_changed:
                refreshed_shipment = _load_edi_generation_shipment(conn, ref)
                settings = dict(conn.execute("SELECT key, value FROM tms_settings").fetchall())
                try:
                    _record_edi_status_notice(
                        conn,
                        refreshed_shipment,
                        settings,
                        event={
                            "status": new_status,
                            "description": f"Status changed to {new_status}",
                            "location": request.form.get("destination_port") if new_status == "Delivered" else request.form.get("origin_port"),
                        },
                    )
                except ValueError as exc:
                    status_notice_error = str(exc)
            conn.commit()
        except ValueError as exc:
            conn.rollback()
            flash(str(exc), "danger")
            form_shipment = dict(shipment)
            form_shipment.update(request.form.to_dict())
            conn.close()
            return render_template(
                "tms/edit_shipment.html",
                shipment=form_shipment,
                carriers=carriers,
                drivers=drivers,
                vehicles=vehicles,
            ), 400
        conn.close()
        if status_changed:
            try:
                notify_shipment_status_change(ref, new_status)
            except Exception:
                pass
        if status_notice_error:
            flash(status_notice_error, "warning")
        flash("Shipment updated.", "success")
        return redirect(url_for("tms.view_shipment", ref=ref))
    conn.close()
    return render_template(
        "tms/edit_shipment.html",
        shipment=shipment,
        carriers=carriers,
        drivers=drivers,
        vehicles=vehicles,
    )


@tms.route("/shipments/<ref>/status", methods=["POST"])
def update_status(ref):
    payload = request.get_json(silent=True)
    if not isinstance(payload, dict):
        payload = request.form.to_dict()

    new_status = _normalize_text(payload.get("status"))
    if new_status not in SHIPMENT_STATUSES:
        allowed = ", ".join(sorted(SHIPMENT_STATUSES))
        return jsonify({"ok": False, "error": f"Status must be one of: {allowed}."}), 400

    conn = get_db()
    status_notice_error = None
    shipment = None
    old_status = ""
    status_changed = False
    try:
        c = conn.cursor()
        shipment = c.execute("SELECT id, status FROM shipments WHERE shipment_ref=?", (ref,)).fetchone()
        if not shipment:
            return jsonify({"ok": False, "error": "Shipment not found."}), 404

        c.execute(
            "UPDATE shipments SET status=?, updated_at=CURRENT_TIMESTAMP WHERE shipment_ref=?",
            (new_status, ref),
        )
        c.execute(
            "INSERT INTO shipment_events (shipment_id, event_type, description) VALUES (?,?,?)",
            (shipment["id"], "Status Change", f"Status changed to {new_status}"),
        )
        old_status = shipment["status"]
        status_changed = _normalize_text(new_status) != _normalize_text(old_status)
        if status_changed:
            refreshed_shipment = _load_edi_generation_shipment(conn, ref)
            settings = dict(conn.execute("SELECT key, value FROM tms_settings").fetchall())
            try:
                _record_edi_status_notice(
                    conn,
                    refreshed_shipment,
                    settings,
                    event={
                        "status": new_status,
                        "description": f"Status changed to {new_status}",
                        "location": payload.get("location") or (
                            refreshed_shipment["destination_port"] if new_status == "Delivered" else refreshed_shipment["origin_port"]
                        ),
                    },
                )
            except ValueError as exc:
                status_notice_error = str(exc)
        conn.commit()
    finally:
        conn.close()
    if status_changed:
        try:
            notify_shipment_status_change(ref, new_status)
        except Exception:
            pass
        try:
            fire_trigger('shipment_status_changed', {
                'shipment_ref': ref, 'status': new_status,
                'old_status': old_status,
            })
            if new_status == 'Delivered':
                fire_trigger('pod_received', {'shipment_ref': ref, 'status': new_status})
        except Exception:
            pass
    try:
        audit('UPDATE', 'shipment', ref,
              old_value={'status': old_status},
              new_value={'status': new_status})
    except Exception:
        pass
    response_payload = {"ok": True, "status": new_status}
    if status_notice_error:
        response_payload["warning"] = status_notice_error
    return jsonify(response_payload)


@tms.route("/shipments/<ref>/carrier", methods=["POST"])
def update_carrier(ref):
    payload = request.get_json(silent=True)
    if not isinstance(payload, dict):
        payload = request.form.to_dict()

    try:
        carrier_id, carrier_name = _resolve_carrier_selection(
            payload.get("carrier_id"),
            payload.get("carrier_name", ""),
        )
    except ValueError as exc:
        return jsonify({"ok": False, "error": str(exc)}), 400

    conn = get_db()
    try:
        shipment = conn.execute(
            "SELECT id, carrier_id, carrier_name FROM shipments WHERE shipment_ref=?",
            (ref,),
        ).fetchone()
        if not shipment:
            return jsonify({"ok": False, "error": "Shipment not found."}), 404

        conn.execute(
            """
            UPDATE shipments
            SET carrier_id=?, carrier_name=?, updated_at=CURRENT_TIMESTAMP
            WHERE shipment_ref=?
            """,
            (carrier_id, carrier_name, ref),
        )
        description = (
            f"Carrier assigned to {carrier_name}."
            if carrier_name
            else "Carrier assignment cleared."
        )
        conn.execute(
            "INSERT INTO shipment_events (shipment_id, event_type, description) VALUES (?,?,?)",
            (shipment["id"], "Carrier Update", description),
        )
        conn.commit()
    finally:
        conn.close()

    return jsonify(
        {
            "ok": True,
            "carrier_id": carrier_id,
            "carrier_name": carrier_name or "",
        }
    )


@tms.route("/shipments/<ref>/event", methods=["POST"])
def add_event(ref):
    conn = get_db()
    c = conn.cursor()
    shipment = c.execute("SELECT id FROM shipments WHERE shipment_ref=?", (ref,)).fetchone()
    c.execute(
        "INSERT INTO shipment_events (shipment_id, event_type, description, location) VALUES (?,?,?,?)",
        (
            shipment["id"],
            request.form.get("event_type"),
            request.form.get("description"),
            request.form.get("location"),
        ),
    )
    conn.commit()
    conn.close()
    flash("Event added.", "success")
    return redirect(url_for("tms.view_shipment", ref=ref))


@tms.route("/api/shipments")
def api_shipments():
    init_tms_db()
    conn = get_db()
    rows = conn.execute(
        """
        SELECT s.*, l.load_ref, l.status AS load_status
        FROM shipments s
        LEFT JOIN load_shipments ls ON ls.shipment_ref = s.shipment_ref
        LEFT JOIN loads l ON l.id = ls.load_id
        ORDER BY s.created_at DESC
        """
    ).fetchall()
    conn.close()
    return jsonify([dict(r) for r in rows])


@tms.route("/shipments/<ref>/delete", methods=["POST"])
def delete_shipment(ref):
    conn = get_db()
    c = conn.cursor()
    c.execute("DELETE FROM tender_responses WHERE tender_id IN (SELECT id FROM tenders WHERE shipment_id=(SELECT id FROM shipments WHERE shipment_ref=?))", (ref,))
    c.execute("DELETE FROM tenders WHERE shipment_id=(SELECT id FROM shipments WHERE shipment_ref=?)", (ref,))
    c.execute("DELETE FROM shipment_events WHERE shipment_id=(SELECT id FROM shipments WHERE shipment_ref=?)", (ref,))
    c.execute("DELETE FROM shipments WHERE shipment_ref=?", (ref,))
    conn.commit()
    conn.close()
    flash(f"Shipment {ref} deleted.", "warning")
    return redirect(url_for("tms.shipments"))


# ── Document Downloads ────────────────────────────────────────────────────────
def _get_shipment_and_company(ref):
    conn = get_db()
    shipment = conn.execute("SELECT * FROM shipments WHERE shipment_ref=?", (ref,)).fetchone()
    settings = dict(conn.execute("SELECT key,value FROM tms_settings").fetchall())
    conn.close()
    return dict(shipment) if shipment else None, settings.get('company_name', 'My Freight Co')

@tms.route("/shipments/<ref>/bol.pdf")
def download_bol(ref):
    shipment, company = _get_shipment_and_company(ref)
    if not shipment:
        return "Shipment not found", 404
    return _build_document_response(shipment, company, ref, "bol")

@tms.route("/shipments/<ref>/invoice.pdf")
def download_invoice(ref):
    shipment, company = _get_shipment_and_company(ref)
    if not shipment:
        return "Shipment not found", 404
    return _build_document_response(shipment, company, ref, "invoice")

@tms.route("/shipments/<ref>/packing-list.pdf")
def download_packing_list(ref):
    shipment, company = _get_shipment_and_company(ref)
    if not shipment:
        return "Shipment not found", 404
    return _build_document_response(shipment, company, ref, "packing-list")


@tms.route("/shipments/<ref>/awb.pdf")
def download_awb(ref):
    shipment, company = _get_shipment_and_company(ref)
    if not shipment:
        return "Shipment not found", 404
    return _build_document_response(shipment, company, ref, "awb")


@tms.route("/shipments/<ref>/pod.pdf")
def download_pod(ref):
    shipment, company = _get_shipment_and_company(ref)
    if not shipment:
        return "Shipment not found", 404
    pod_record = get_pod_record(ref)
    if not pod_record:
        return "POD not found", 404
    return _build_pod_document_response(shipment, pod_record, company, ref)


@tms.route("/shipments/<ref>/label")
def shipment_label(ref):
    """Generate a printable shipping label for the shipment."""
    shipment, company = _get_shipment_and_company(ref)
    if not shipment:
        return "Shipment not found", 404

    # Try to get a live carrier label first
    label_url = None
    label_error = None
    try:
        from tms.carrier_clients import is_connected, get_credentials
        carrier_name = (shipment.get("carrier_name") or "").lower()
        # Map common carrier names to integration keys
        carrier_key_map = {
            "ups": "ups", "fedex": "fedex", "dhl": "dhl",
            "easypost": "easypost", "aftership": "aftership",
        }
        matched_key = next((v for k, v in carrier_key_map.items() if k in carrier_name), None)
        if matched_key and is_connected(matched_key):
            creds = get_credentials(matched_key)
            if matched_key == "easypost" and creds.get("api_key"):
                import requests as req
                # Create EasyPost shipment for label
                ep_resp = req.post(
                    "https://api.easypost.com/v2/shipments",
                    auth=(creds["api_key"], ""),
                    json={
                        "shipment": {
                            "to_address": {"name": shipment.get("consignee_name", "Consignee"),
                                           "street1": shipment.get("consignee_address", ""),
                                           "city": shipment.get("destination_port", ""),
                                           "country": "US"},
                            "from_address": {"name": shipment.get("shipper_name", "Shipper"),
                                             "street1": shipment.get("shipper_address", ""),
                                             "city": shipment.get("origin_port", ""),
                                             "country": "US"},
                            "parcel": {"weight": max(float(shipment.get("weight_kg") or 1) * 2.20462, 1)},
                        }
                    },
                    timeout=10,
                )
                if ep_resp.ok:
                    ep_data = ep_resp.json()
                    rates = ep_data.get("shipment", {}).get("rates", [])
                    if rates:
                        buy_resp = req.post(
                            f"https://api.easypost.com/v2/shipments/{ep_data['shipment']['id']}/buy",
                            auth=(creds["api_key"], ""),
                            json={"rate": {"id": rates[0]["id"]}},
                            timeout=10,
                        )
                        if buy_resp.ok:
                            label_url = buy_resp.json().get("shipment", {}).get("postage_label", {}).get("label_url")
    except Exception as _label_err:
        label_error = str(_label_err)

    if label_url:
        return redirect(label_url)

    # Fall back to in-app printable label
    label_html = render_template(
        "tms/label.html",
        shipment=shipment,
        company=company,
        label_error=label_error,
        now=datetime.utcnow().strftime("%Y-%m-%d %H:%M UTC"),
    )
    return label_html


@tms.route("/invoices", methods=["GET", "POST"])
def invoices():
    init_tms_db()
    conn = get_db()
    form_error = None
    status_code = 200
    common_currencies = ["USD", "CAD", "EUR", "GBP", "MXN", "CNY", "JPY", "AUD"]

    try:
        refresh_customer_invoice_statuses(conn)
        conn.commit()
        selected_shipment_ref = _normalize_text(request.args.get("shipment_ref"))
        selected_invoice_id = request.args.get("invoice_id", type=int)

        selected_shipment = _load_shipment(conn, selected_shipment_ref) if selected_shipment_ref else None
        selected_invoice = _load_customer_invoice(conn, selected_invoice_id) if selected_invoice_id else None
        form_values = _invoice_form_defaults(
            shipment=dict(selected_shipment) if selected_shipment else None,
            invoice=dict(selected_invoice) if selected_invoice else None,
        )

        if request.method == "POST":
            action = (_normalize_text(request.form.get("action")) or "save").lower()

            try:
                if action == "save":
                    form_values = request.form.to_dict()
                    invoice_id = request.form.get("invoice_id", type=int)
                    shipment_ref = _normalize_text(request.form.get("shipment_ref"))
                    shipment = _load_shipment(conn, shipment_ref)
                    if not shipment:
                        raise ValueError("Select a valid shipment.")

                    customer_name = _normalize_text(request.form.get("customer_name"))
                    if not customer_name:
                        raise ValueError("Customer name is required.")

                    amount_fallback = _normalize_text(request.form.get("amount"))
                    line_item_fields = [
                        _normalize_text(request.form.get("freight_charge")),
                        _normalize_text(request.form.get("fuel_surcharge")),
                        _normalize_text(request.form.get("accessorial_total")),
                        _normalize_text(request.form.get("tax_amount")),
                        _normalize_text(request.form.get("discount")),
                    ]
                    if amount_fallback and not any(line_item_fields):
                        form_values["freight_charge"] = amount_fallback

                    freight_charge = _parse_invoice_component_amount(
                        form_values.get("freight_charge"),
                        "Freight charge",
                    )
                    fuel_surcharge = _parse_invoice_component_amount(
                        request.form.get("fuel_surcharge"),
                        "Fuel surcharge",
                    )
                    accessorial_total = _parse_invoice_component_amount(
                        request.form.get("accessorial_total"),
                        "Accessorial total",
                    )
                    tax_amount = _parse_invoice_component_amount(
                        request.form.get("tax_amount"),
                        "Tax amount",
                    )
                    discount = _parse_invoice_component_amount(
                        request.form.get("discount"),
                        "Discount",
                    )
                    payment_terms = _parse_invoice_payment_terms(request.form.get("payment_terms"))
                    remit_to = _normalize_text(request.form.get("remit_to"))
                    invoice_date = _parse_invoice_date(
                        _normalize_text(request.form.get("invoice_date")) or date.today().isoformat()
                    )
                    po_reference = _normalize_text(request.form.get("po_reference"))
                    amount = round(
                        freight_charge
                        + fuel_surcharge
                        + accessorial_total
                        + tax_amount
                        - discount,
                        2,
                    )
                    if amount < 0:
                        raise ValueError("Invoice total cannot be negative.")
                    currency = (_normalize_text(request.form.get("currency")) or "USD").upper()
                    exchange_rate = _parse_exchange_rate(request.form.get("exchange_rate"))
                    due_date = _parse_invoice_due_date(request.form.get("due_date"))
                    requested_status = _parse_invoice_status(request.form.get("status"))
                    existing_invoice = _load_customer_invoice(conn, invoice_id) if invoice_id else None
                    if invoice_id and not existing_invoice:
                        raise ValueError("Invoice not found.")

                    paid_at = None
                    if requested_status == "Paid":
                        paid_at = (
                            existing_invoice["paid_at"]
                            if existing_invoice and existing_invoice["paid_at"]
                            else datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S")
                        )

                    if invoice_id:
                        conn.execute(
                            """
                            UPDATE customer_invoices
                            SET shipment_ref = ?, customer_name = ?, amount = ?, currency = ?,
                                exchange_rate = ?, status = ?, due_date = ?, paid_at = ?,
                                freight_charge = ?, fuel_surcharge = ?, accessorial_total = ?,
                                tax_amount = ?, discount = ?, payment_terms = ?, remit_to = ?,
                                invoice_date = ?, po_reference = ?,
                                updated_at = CURRENT_TIMESTAMP
                            WHERE id = ?
                            """,
                            (
                                shipment_ref,
                                customer_name,
                                amount,
                                currency,
                                exchange_rate,
                                requested_status,
                                due_date.isoformat(),
                                paid_at,
                                freight_charge,
                                fuel_surcharge,
                                accessorial_total,
                                tax_amount,
                                discount,
                                payment_terms,
                                remit_to,
                                invoice_date.isoformat(),
                                po_reference,
                                invoice_id,
                            ),
                        )
                    else:
                        cursor = conn.execute(
                            """
                            INSERT INTO customer_invoices
                                (
                                    shipment_ref, customer_name, amount, currency, exchange_rate,
                                    status, due_date, paid_at, freight_charge, fuel_surcharge,
                                    accessorial_total, tax_amount, discount, payment_terms,
                                    remit_to, invoice_date, po_reference
                                )
                            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                            """,
                            (
                                shipment_ref,
                                customer_name,
                                amount,
                                currency,
                                exchange_rate,
                                requested_status,
                                due_date.isoformat(),
                                paid_at,
                                freight_charge,
                                fuel_surcharge,
                                accessorial_total,
                                tax_amount,
                                discount,
                                payment_terms,
                                remit_to,
                                invoice_date.isoformat(),
                                po_reference,
                            ),
                        )
                        invoice_id = cursor.lastrowid

                    refresh_customer_invoice_statuses(conn)
                    saved_invoice = _load_customer_invoice(conn, invoice_id)
                    invoice_label = _invoice_number(saved_invoice)
                    _log_invoice_event(
                        conn,
                        shipment_ref,
                        "Customer Invoice",
                        f"{invoice_label} saved for {customer_name} with status {saved_invoice['status']}.",
                    )
                    conn.commit()
                    if not existing_invoice:
                        try:
                            notify_invoice_generated(invoice_id=invoice_id, shipment_ref=shipment_ref)
                        except Exception:
                            pass
                    flash(f"{invoice_label} saved.", "success")
                    return redirect(url_for("tms.invoices", invoice_id=invoice_id))

                if action == "set_status":
                    invoice_id = request.form.get("invoice_id", type=int)
                    status_value = _parse_invoice_status(request.form.get("status"))
                    invoice = _load_customer_invoice(conn, invoice_id)
                    if not invoice:
                        raise ValueError("Invoice not found.")

                    paid_at = invoice["paid_at"]
                    if status_value == "Paid":
                        paid_at = paid_at or datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S")
                    else:
                        paid_at = None

                    conn.execute(
                        """
                        UPDATE customer_invoices
                        SET status = ?, paid_at = ?, updated_at = CURRENT_TIMESTAMP
                        WHERE id = ?
                        """,
                        (status_value, paid_at, invoice_id),
                    )
                    refresh_customer_invoice_statuses(conn)
                    updated_invoice = _load_customer_invoice(conn, invoice_id)
                    _log_invoice_event(
                        conn,
                        updated_invoice["shipment_ref"],
                        "Invoice Status",
                        f"{_invoice_number(updated_invoice)} moved to {updated_invoice['status']}.",
                    )
                    conn.commit()
                    flash(f"{_invoice_number(updated_invoice)} updated to {updated_invoice['status']}.", "success")
                    return redirect(url_for("tms.invoices"))

                if action == "delete":
                    invoice_id = request.form.get("invoice_id", type=int)
                    invoice = _load_customer_invoice(conn, invoice_id)
                    if not invoice:
                        raise ValueError("Invoice not found.")
                    conn.execute("DELETE FROM customer_invoices WHERE id = ?", (invoice_id,))
                    _log_invoice_event(
                        conn,
                        invoice["shipment_ref"],
                        "Customer Invoice",
                        f"{_invoice_number(invoice)} deleted.",
                    )
                    conn.commit()
                    flash(f"{_invoice_number(invoice)} deleted.", "warning")
                    return redirect(url_for("tms.invoices"))

                raise ValueError("Unknown invoice action.")
            except ValueError as exc:
                conn.rollback()
                form_error = str(exc)
                status_code = 400

        invoice_rows = _list_customer_invoices(conn)
        conn.commit()

        shipment_rows = conn.execute(
            """
            SELECT shipment_ref, shipper_name, consignee_name, freight_rate, currency, created_at
            FROM shipments
            ORDER BY created_at DESC, shipment_ref DESC
            """
        ).fetchall()
        shipments = [dict(row) for row in shipment_rows]
        invoice_by_shipment = {invoice["shipment_ref"]: invoice for invoice in invoice_rows}
        settings = dict(conn.execute("SELECT key, value FROM tms_settings").fetchall())
        stats = {
            "total": len(invoice_rows),
            "open": sum(1 for invoice in invoice_rows if invoice["status"] in {"Sent", "Overdue"}),
            "paid": sum(1 for invoice in invoice_rows if invoice["status"] == "Paid"),
            "outstanding_amount": sum(
                float(invoice["amount"] or 0)
                for invoice in invoice_rows
                if invoice["status"] in {"Sent", "Overdue"}
            ),
        }

        return (
            render_template(
                "tms/invoices.html",
                invoices=invoice_rows,
                shipments=shipments,
                invoice_by_shipment=invoice_by_shipment,
                stats=stats,
                settings=settings,
                form_values=form_values,
                form_error=form_error,
                selected_invoice_id=selected_invoice_id,
                common_currencies=common_currencies,
            ),
            status_code,
        )
    finally:
        conn.close()


@tms.route("/invoices/<int:invoice_id>/pdf")
def customer_invoice_pdf(invoice_id):
    init_tms_db()
    conn = get_db()
    try:
        refresh_customer_invoice_statuses(conn)
        invoice = _load_customer_invoice(conn, invoice_id)
        settings = dict(conn.execute("SELECT key, value FROM tms_settings").fetchall())
        conn.commit()
    finally:
        conn.close()

    if not invoice:
        return "Invoice not found", 404
    if generate_customer_invoice is None:
        return f"Document generation unavailable: {_tms_docs_error}", 503

    invoice_payload = dict(invoice)
    pdf = generate_customer_invoice(invoice_payload, invoice_payload, settings.get("company_name", "My Freight Co"))
    return Response(
        pdf,
        mimetype="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="{_invoice_number(invoice_payload)}.pdf"'},
    )


@tms.route("/invoices/export/quickbooks")
def export_invoices_quickbooks():
    init_tms_db()
    conn = get_db()
    try:
        invoice_rows = _list_customer_invoices(conn)
        conn.commit()
    finally:
        conn.close()

    export_rows = []
    for invoice in invoice_rows:
        if invoice["status"] == "Draft":
            continue
        export_rows.append(
            {
                "Invoice No": invoice["invoice_number"],
                "Customer": invoice["customer_name"],
                "Invoice Date": _invoice_date_value(invoice),
                "Due Date": invoice["due_date"] or "",
                "Item Description": _invoice_description(invoice),
                "Item Amount": f"{float(invoice['amount'] or 0):.2f}",
                "Currency": invoice["currency"] or "USD",
                "Exchange Rate": f"{float(invoice['exchange_rate'] or 1):.4f}",
                "Shipment Ref": invoice["shipment_ref"],
                "Status": invoice["status"],
            }
        )

    fieldnames = [
        "Invoice No",
        "Customer",
        "Invoice Date",
        "Due Date",
        "Item Description",
        "Item Amount",
        "Currency",
        "Exchange Rate",
        "Shipment Ref",
        "Status",
    ]
    return _csv_download_response("quickbooks_invoices.csv", fieldnames, export_rows)


@tms.route("/invoices/export/xero")
def export_invoices_xero():
    init_tms_db()
    conn = get_db()
    try:
        invoice_rows = _list_customer_invoices(conn)
        conn.commit()
    finally:
        conn.close()

    export_rows = []
    for invoice in invoice_rows:
        if invoice["status"] == "Draft":
            continue
        export_rows.append(
            {
                "Type": "ACCREC",
                "ContactName": invoice["customer_name"],
                "InvoiceNumber": invoice["invoice_number"],
                "InvoiceDate": _invoice_date_value(invoice),
                "DueDate": invoice["due_date"] or "",
                "Description": _invoice_description(invoice),
                "Quantity": "1",
                "UnitAmount": f"{float(invoice['amount'] or 0):.2f}",
                "Currency": invoice["currency"] or "USD",
                "Reference": invoice["shipment_ref"],
                "Status": invoice["status"],
                "ExchangeRate": f"{float(invoice['exchange_rate'] or 1):.4f}",
            }
        )

    fieldnames = [
        "Type",
        "ContactName",
        "InvoiceNumber",
        "InvoiceDate",
        "DueDate",
        "Description",
        "Quantity",
        "UnitAmount",
        "Currency",
        "Reference",
        "Status",
        "ExchangeRate",
    ]
    return _csv_download_response("xero_invoices.csv", fieldnames, export_rows)


@tms.route("/esg")
def esg_dashboard():
    init_tms_db()
    conn = get_db()
    try:
        backfill_shipment_co2(conn=conn, only_missing=True)
        conn.commit()
        context = _build_esg_dashboard_context(conn)
    finally:
        conn.close()
    return render_template("tms/esg.html", **context)


@tms.route("/esg/export.csv")
def esg_export():
    init_tms_db()
    conn = get_db()
    try:
        backfill_shipment_co2(conn=conn, only_missing=True)
        export_rows = _build_esg_export_rows(conn)
        conn.commit()
    finally:
        conn.close()

    fieldnames = [
        "shipment_ref",
        "status",
        "shipment_date",
        "origin_port",
        "destination_port",
        "lane",
        "carrier_name",
        "mode",
        "esg_mode",
        "weight_kg",
        "distance_km",
        "emission_factor_kg_per_tonne_km",
        "co2_kg",
        "freight_rate",
        "currency",
        "carbon_intensity_kg_per_usd",
        "framework_label",
        "calculation_status",
        "origin_source_url",
        "destination_source_url",
        "last_checked",
    ]
    return _csv_download_response("esg_export.csv", fieldnames, export_rows)


# ── Reporting ─────────────────────────────────────────────────────────────────
@tms.route("/reports")
def reports():
    conn = get_db()
    c = conn.cursor()

    # Revenue by currency
    revenue_by_currency = c.execute("""
        SELECT currency, SUM(freight_rate) as total, COUNT(*) as count
        FROM shipments WHERE status NOT IN ('Draft','Cancelled')
        GROUP BY currency ORDER BY total DESC
    """).fetchall()

    # Top lanes (origin → destination)
    top_lanes = c.execute("""
        SELECT origin_port, destination_port, COUNT(*) as shipments,
               SUM(freight_rate) as revenue, AVG(freight_rate) as avg_rate,
               currency
        FROM shipments WHERE status NOT IN ('Draft','Cancelled')
        GROUP BY origin_port, destination_port
        ORDER BY shipments DESC LIMIT 10
    """).fetchall()

    # Carrier performance
    carrier_stats = c.execute("""
        SELECT carrier_name, COUNT(*) as total,
               SUM(CASE WHEN status='Delivered' THEN 1 ELSE 0 END) as delivered,
               SUM(CASE WHEN status='In Transit' THEN 1 ELSE 0 END) as in_transit,
               SUM(freight_rate) as revenue
        FROM shipments WHERE carrier_name IS NOT NULL AND carrier_name != ''
        GROUP BY carrier_name ORDER BY total DESC LIMIT 10
    """).fetchall()

    # Status breakdown
    status_breakdown = c.execute("""
        SELECT status, COUNT(*) as count, SUM(freight_rate) as revenue
        FROM shipments GROUP BY status ORDER BY count DESC
    """).fetchall()

    # Monthly volume (last 6 months)
    monthly = c.execute("""
        SELECT strftime('%Y-%m', created_at) as month,
               COUNT(*) as shipments, SUM(freight_rate) as revenue
        FROM shipments
        WHERE created_at >= date('now', '-6 months')
        GROUP BY month ORDER BY month
    """).fetchall()

    # Summary stats
    stats = {
        'total_shipments': c.execute("SELECT COUNT(*) FROM shipments").fetchone()[0],
        'total_revenue':   c.execute("SELECT COALESCE(SUM(freight_rate),0) FROM shipments WHERE status NOT IN ('Draft','Cancelled')").fetchone()[0],
        'delivered':       c.execute("SELECT COUNT(*) FROM shipments WHERE status='Delivered'").fetchone()[0],
        'in_transit':      c.execute("SELECT COUNT(*) FROM shipments WHERE status='In Transit'").fetchone()[0],
        'active_lanes':    c.execute("SELECT COUNT(DISTINCT origin_port||destination_port) FROM shipments").fetchone()[0],
        'carriers_used':   c.execute("SELECT COUNT(DISTINCT carrier_name) FROM shipments WHERE carrier_name!=''").fetchone()[0],
    }
    conn.close()
    return render_template('tms/reports.html',
        stats=stats, revenue_by_currency=revenue_by_currency,
        top_lanes=top_lanes, carrier_stats=carrier_stats,
        status_breakdown=status_breakdown, monthly=monthly)

# -- Integrations — replaced by Smart Connect hub below (lines appended at end) --

# -- Forecasting ----------------------------------------------------------------
@tms.route('/forecasting')
def forecasting():
    return render_template('tms/forecasting.html', **get_forecast_dashboard())


@tms.route('/forecasting/lane')
def forecasting_lane():
    origin = (request.args.get('origin') or '').strip()
    destination = (request.args.get('dest') or '').strip()
    if not origin and not destination:
        return render_template('tms/forecasting.html', **get_forecast_dashboard())
    return render_template('tms/forecasting.html', **get_lane_forecast(origin, destination))


# -- Analytics -----------------------------------------------------------------
@tms.route('/analytics')
def analytics():
    period = request.args.get('period', '30')
    try: days = int(period)
    except: days = 30
    period_labels = {'7':'Last 7 Days','30':'Last 30 Days','90':'Last 90 Days','365':'Last Year'}
    conn = get_db()
    c = conn.cursor()

    # KPI stats
    total    = c.execute(f"SELECT COUNT(*) FROM shipments WHERE created_at >= date('now','-{days} days')").fetchone()[0]
    prev     = c.execute(f"SELECT COUNT(*) FROM shipments WHERE created_at >= date('now','-{days*2} days') AND created_at < date('now','-{days} days')").fetchone()[0]
    delivered= c.execute(f"SELECT COUNT(*) FROM shipments WHERE status='Delivered' AND created_at >= date('now','-{days} days')").fetchone()[0]
    in_trans = c.execute(f"SELECT COUNT(*) FROM shipments WHERE status='In Transit' AND created_at >= date('now','-{days} days')").fetchone()[0]
    lanes    = c.execute(f"SELECT COUNT(DISTINCT origin_port||destination_port) FROM shipments WHERE created_at >= date('now','-{days} days')").fetchone()[0]
    carriers = c.execute(f"SELECT COUNT(DISTINCT carrier_name) FROM shipments WHERE carrier_name!='' AND created_at >= date('now','-{days} days')").fetchone()[0]
    rev_rows = c.execute(f"SELECT currency, COALESCE(SUM(freight_rate),0) as total FROM shipments WHERE status NOT IN ('Draft','Cancelled') AND created_at >= date('now','-{days} days') GROUP BY currency").fetchall()
    rev_str  = ', '.join(f"{r['currency']} {r['total']:,.0f}" for r in rev_rows) if rev_rows else '�'

    # Volume over time
    volume_data = [dict(r) for r in c.execute(f"SELECT date(created_at) as date, COUNT(*) as count FROM shipments WHERE created_at >= date('now','-{days} days') GROUP BY date(created_at) ORDER BY date").fetchall()]

    # Status breakdown
    status_data = [dict(r) for r in c.execute("SELECT status, COUNT(*) as count FROM shipments GROUP BY status ORDER BY count DESC").fetchall()]

    # Top lanes
    lanes_data = [{'lane': f"{r['origin_port']} ? {r['destination_port']}", 'count': r['count']} for r in c.execute(f"SELECT origin_port, destination_port, COUNT(*) as count FROM shipments WHERE created_at >= date('now','-{days} days') GROUP BY origin_port,destination_port ORDER BY count DESC LIMIT 8").fetchall()]

    # Currency data
    currency_data = [dict(r) for r in c.execute(f"SELECT currency, COALESCE(SUM(freight_rate),0) as total FROM shipments WHERE status NOT IN ('Draft','Cancelled') AND created_at >= date('now','-{days} days') GROUP BY currency ORDER BY total DESC").fetchall()]

    # Carrier performance
    carriers_raw = c.execute(f"SELECT carrier_name, COUNT(*) as total, SUM(CASE WHEN status='Delivered' THEN 1 ELSE 0 END) as delivered, COALESCE(SUM(freight_rate),0) as revenue, currency FROM shipments WHERE carrier_name!='' AND created_at >= date('now','-{days} days') GROUP BY carrier_name ORDER BY total DESC LIMIT 10").fetchall()
    carriers_list = []
    for r in carriers_raw:
        row = dict(r)
        row['revenue_str'] = f"{row.get('currency','USD')} {row['revenue']:,.0f}"
        carriers_list.append(row)

    conn.close()
    stats = {'total': total, 'prev_total': prev, 'delivered': delivered, 'in_transit': in_trans,
             'lanes': lanes, 'carriers': carriers, 'revenue_str': rev_str}
    return render_template('tms/analytics.html', stats=stats, period=period,
        period_label=period_labels.get(period,'Last 30 Days'),
        volume_data=volume_data, status_data=status_data,
        lanes_data=lanes_data, currency_data=currency_data,
        carriers=carriers_list)

# ── Email from Shipment ───────────────────────────────────────────────────────
@tms.route('/shipments/<ref>/email', methods=['GET','POST'])
def shipment_email(ref):
    conn = get_db()
    shipment = conn.execute('SELECT * FROM shipments WHERE shipment_ref=?', (ref,)).fetchone()
    settings = dict(conn.execute('SELECT key,value FROM tms_settings').fetchall())
    conn.close()
    if not shipment:
        flash('Shipment not found.','danger')
        return redirect(url_for('tms.shipments'))
    s = dict(shipment)
    company = settings.get('company_name','My Freight Co')

    TEMPLATES = {
        'booking': {
            'subject': f'Booking Confirmation - {ref}',
            'body': f'''Dear {s.get('consignee_name','Valued Customer')},

We are pleased to confirm your booking with {company}.

Shipment Reference: {ref}
Origin: {s.get('origin_port','')}
Destination: {s.get('destination_port','')}
Carrier: {s.get('carrier_name','')}
ETD: {s.get('etd','')}
ETA: {s.get('eta','')}
Cargo: {s.get('cargo_description','')}

You can track your shipment live at: {build_public_tracking_url(ref, external=True)}

Please do not hesitate to contact us with any questions.

Best regards,
{company}'''
        },
        'rate_request': {
            'subject': 'Rate Request - ' + s.get('origin_port','') + ' to ' + s.get('destination_port',''),
            'body': f'''Dear {s.get('carrier_name','Carrier')},

We are requesting a freight rate for the following shipment:

Reference: {ref}
Origin: {s.get('origin_port','')}
Destination: {s.get('destination_port','')}
Cargo: {s.get('cargo_description','')}
Weight: {s.get('weight_kg','')} KG
Volume: {s.get('volume_cbm','')} CBM
Containers: {s.get('containers','')}
ETD: {s.get('etd','')}

Please provide your best rate at your earliest convenience.

Best regards,
{company}'''
        },
        'delivery': {
            'subject': f'Delivery Notification - {ref}',
            'body': f'''Dear {s.get('consignee_name','Valued Customer')},

We are pleased to inform you that your shipment has been delivered.

Shipment Reference: {ref}
Origin: {s.get('origin_port','')}
Destination: {s.get('destination_port','')}
Carrier: {s.get('carrier_name','')}

Thank you for your business.

Best regards,
{company}'''
        },
        'custom': {'subject': f'Re: Shipment {ref}', 'body': ''}
    }

    if request.method == 'POST':
        to_email  = request.form.get('to_email','').strip()
        subject   = request.form.get('subject','').strip()
        body      = request.form.get('body','').strip()
        if not to_email or not subject or not body:
            flash('To, Subject and Body are required.','danger')
            return render_template('tms/shipment_email.html', shipment=s, ref=ref, templates=TEMPLATES, company=company, tracking_url=build_public_tracking_url(ref, external=True))
        try:
            from .email_engine import EmailEngine
            engine = EmailEngine()
            providers = engine.list_provider_configs()
            if not providers:
                flash('No email provider configured. Set up email in TMS settings first.','warning')
                return render_template('tms/shipment_email.html', shipment=s, ref=ref, templates=TEMPLATES, company=company, tracking_url=build_public_tracking_url(ref, external=True))
            result = engine.send_message(to_addresses=[to_email], subject=subject, text_body=body, html_body=f'<pre style="font-family:Arial;font-size:14px;white-space:pre-wrap">{body}</pre>')
            if result.get('ok'):
                # Log event
                conn2 = get_db()
                conn2.execute('INSERT INTO shipment_events (shipment_id,event_type,description,created_at) VALUES ((SELECT id FROM shipments WHERE shipment_ref=?),?,?,?)',
                    (ref, 'Email Sent', f'Email sent to {to_email}: {subject}', datetime.utcnow().isoformat()))
                conn2.commit(); conn2.close()
                flash(f'Email sent to {to_email}.','success')
                return redirect(url_for('tms.view_shipment', ref=ref))
            else:
                flash(f'Send failed: {result.get("error","Unknown error")}','danger')
        except Exception as e:
            flash(f'Email error: {str(e)}','danger')
    return render_template('tms/shipment_email.html', shipment=s, ref=ref, templates=TEMPLATES, company=company, tracking_url=build_public_tracking_url(ref, external=True))


# ── Legacy Fleet Management ───────────────────────────────────────────────────
@tms.route('/fleet-legacy', methods=['GET', 'POST'])
def fleet_legacy():
    conn = get_db()
    if request.method == 'POST':
        action = request.form.get('action')
        if action == 'add_vehicle':
            conn.execute(
                'INSERT INTO vehicles (truck_number,vehicle_type,capacity_weight,capacity_cbm,country,status,vin,license_plate,year,make,model,registration_expiry,insurance_expiry,insurance_carrier,odometer,last_inspection_date,next_inspection_due) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)',
                (request.form.get('truck_number'), request.form.get('vehicle_type','Truck'),
                 request.form.get('capacity_weight',0), request.form.get('capacity_cbm',0),
                 request.form.get('country',''), request.form.get('status','Active'),
                 request.form.get('vin',''), request.form.get('license_plate',''),
                 request.form.get('year',''), request.form.get('make',''),
                 request.form.get('model',''), request.form.get('registration_expiry',''),
                 request.form.get('insurance_expiry',''), request.form.get('insurance_carrier',''),
                 request.form.get('odometer',''), request.form.get('last_inspection_date',''),
                 request.form.get('next_inspection_due',''))
            )
            conn.commit(); flash('Vehicle added.','success')
        elif action == 'delete_vehicle':
            conn.execute('DELETE FROM vehicles WHERE id=?', (request.form.get('vehicle_id'),))
            conn.commit(); flash('Vehicle removed.','warning')
    vehicles = conn.execute('SELECT * FROM vehicles ORDER BY truck_number').fetchall()
    conn.close()
    return render_template('tms/fleet.html', vehicles=vehicles)

@tms.route('/drivers-legacy', methods=['GET', 'POST'])
def drivers_legacy():
    conn = get_db()
    if request.method == 'POST':
        action = request.form.get('action')
        if action == 'add':
            conn.execute(
                'INSERT INTO drivers (name,license_number,phone,country,status,cdl_class,cdl_expiry,medical_card_expiry,drug_test_date,hire_date,emergency_contact_name,emergency_contact_phone,hazmat_endorsement,twic_card,license_state,email) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)',
                (request.form.get('name'), request.form.get('license_number',''),
                 request.form.get('phone',''), request.form.get('country',''),
                 request.form.get('status','Active'), request.form.get('cdl_class',''),
                 request.form.get('cdl_expiry',''), request.form.get('medical_card_expiry',''),
                 request.form.get('drug_test_date',''), request.form.get('hire_date',''),
                 request.form.get('emergency_contact_name',''), request.form.get('emergency_contact_phone',''),
                 request.form.get('hazmat_endorsement', 0), request.form.get('twic_card', 0),
                 request.form.get('license_state',''), request.form.get('email','')))
            conn.commit(); flash('Driver added.','success')
        elif action == 'delete':
            conn.execute('DELETE FROM drivers WHERE id=?', (request.form.get('driver_id'),))
            conn.commit(); flash('Driver removed.','warning')
    drivers_list = conn.execute('SELECT * FROM drivers ORDER BY name').fetchall()
    conn.close()
    return render_template('tms/drivers.html', drivers=drivers_list)


# ── Legacy EDI ────────────────────────────────────────────────────────────────
@tms.route('/edi-legacy', methods=['GET', 'POST'])
def edi_view_legacy():
    conn = get_db()
    if request.method == 'POST' and 'edi_file' in request.files:
        f = request.files['edi_file']
        raw = f.read().decode('utf-8', errors='replace')
        try:
            from .edi import parse_edi, detect_type
            parsed = parse_edi(raw)
            doc_type = detect_type(raw)
        except Exception as e:
            parsed = {}; doc_type = 'Unknown'
        import json as _json
        conn.execute('INSERT INTO edi_transactions (direction,type,raw,parsed_json,status) VALUES (?,?,?,?,?)',
            ('inbound', doc_type, raw, _json.dumps(parsed), 'received'))
        conn.commit()
        flash(f'EDI file parsed as {doc_type}.', 'success')
    transactions = conn.execute('SELECT * FROM edi_transactions ORDER BY created_at DESC LIMIT 100').fetchall()
    conn.close()
    return render_template('tms/edi.html', transactions=transactions)


# ── Customs & Compliance ──────────────────────────────────────────────────────
@tms.route('/compliance', methods=['GET', 'POST'])
def compliance():
    conn = get_db()
    if request.method == 'POST':
        ref = request.form.get('shipment_ref')
        conn.execute('''INSERT INTO customs_declarations
            (shipment_ref,hs_code,country_of_origin,declared_value,currency,export_license_required,dps_status,screened_at,status,notes)
            VALUES (?,?,?,?,?,?,?,CURRENT_TIMESTAMP,?,?)
            ON CONFLICT(shipment_ref) DO UPDATE SET
            hs_code=excluded.hs_code, country_of_origin=excluded.country_of_origin,
            declared_value=excluded.declared_value, currency=excluded.currency,
            export_license_required=excluded.export_license_required,
            dps_status=excluded.dps_status, screened_at=excluded.screened_at,
            status=excluded.status, notes=excluded.notes''',
            (ref, request.form.get('hs_code',''), request.form.get('country_of_origin',''),
             float(request.form.get('declared_value') or 0), request.form.get('currency','USD'),
             1 if request.form.get('export_license_required') else 0,
             'clear', request.form.get('status','pending'), request.form.get('notes','')))
        conn.commit(); flash('Customs declaration saved.','success')
    pending = conn.execute('''SELECT s.shipment_ref, s.origin_port, s.destination_port,
        s.shipper_name, s.consignee_name, s.cargo_description, c.status as customs_status,
        c.hs_code, c.dps_status
        FROM shipments s LEFT JOIN customs_declarations c ON s.shipment_ref=c.shipment_ref
        ORDER BY s.created_at DESC''').fetchall()
    conn.close()
    return render_template('tms/compliance.html', shipments=pending)



# ── Network Optimization ──────────────────────────────────────────────────────
@tms.route('/network-optimization')
def network_optimization():
    """Analyzes lanes and recommends optimal carrier/mode combos."""
    import collections, datetime as _dt
    conn = get_db()
    
    # Analyze all delivered shipments in past 6 months
    cutoff = (_dt.date.today() - _dt.timedelta(days=180)).isoformat()
    rows = conn.execute(
        """SELECT origin_port, destination_port, mode, carrier_name,
           freight_rate, currency, weight_kg, etd, eta,
           JULIANDAY(eta) - JULIANDAY(etd) as transit_actual
           FROM shipments
           WHERE status='Delivered' AND etd >= ? AND freight_rate > 0
           ORDER BY etd DESC""",
        (cutoff,)).fetchall()
    
    # Lane analysis
    lanes = collections.defaultdict(lambda: {
        'count':0, 'total_cost':0, 'total_transit':0,
        'carriers': collections.Counter(), 'modes': collections.Counter()
    })
    for r in rows:
        key = (r['origin_port'] or '', r['destination_port'] or '')
        if not key[0] or not key[1]: continue
        d = lanes[key]
        d['count'] += 1
        d['total_cost'] += r['freight_rate'] or 0
        d['total_transit'] += r['transit_actual'] or 0
        d['carriers'][r['carrier_name'] or 'Unknown'] += 1
        d['modes'][r['mode'] or 'ocean'] += 1
    
    # Build recommendations
    lane_data = []
    for (orig, dest), d in lanes.items():
        if d['count'] < 2: continue
        avg_cost = round(d['total_cost'] / d['count'], 0)
        avg_transit = round(d['total_transit'] / d['count'], 1)
        top_carrier = d['carriers'].most_common(1)[0][0] if d['carriers'] else 'N/A'
        top_mode = d['modes'].most_common(1)[0][0] if d['modes'] else 'ocean'
        # Check contract rates for potential savings
        contract = conn.execute(
            """SELECT cr.*, tc.name as cname FROM contract_rates cr
               JOIN tms_carriers tc ON tc.id=cr.carrier_id
               WHERE cr.origin=? AND cr.destination=? AND cr.mode=?
               AND cr.valid_to >= ?""",
            (orig, dest, top_mode, _dt.date.today().isoformat())).fetchone()
        contract_rate = contract['rate_20ft'] if contract else None
        savings = round(avg_cost - contract_rate, 0) if contract_rate and contract_rate < avg_cost else 0
        lane_data.append({
            'origin': orig, 'destination': dest,
            'shipments': d['count'],
            'avg_cost': avg_cost, 'avg_transit': avg_transit,
            'top_carrier': top_carrier, 'top_mode': top_mode,
            'contract_rate': contract_rate, 'savings': savings,
            'recommendation': (
                f'Switch to contract: save /shipment' if savings > 0
                else 'On optimal contract' if contract_rate
                else 'No contract — request quote to lock in rate'
            )
        })
    
    lane_data.sort(key=lambda x: -(x['savings'] or 0))
    
    # Overall stats
    total_spend = sum(r['freight_rate'] or 0 for r in rows)
    total_savings_potential = sum(d['savings'] for d in lane_data)
    
    conn.close()
    return render_template('tms/network_optimization.html',
        lanes=lane_data,
        total_spend=total_spend,
        total_savings_potential=total_savings_potential,
        shipment_count=len(rows))



# ── Global Trade Management ────────────────────────────────────────────────────
def _trade_flash_message(result):
    status = result.get("status", "review")
    tariff = result.get("tariff_rate") or {}
    flags = result.get("flags") or []
    if status == "clear":
        duty_rate = tariff.get("duty_rate_pct")
        if duty_rate is None:
            return "Compliance check clear."
        return f"Compliance check clear. Duty rate on file: {duty_rate:g}%."
    if flags:
        return f"Compliance check {status}. {flags[0].get('message', '')}".strip()
    return f"Compliance check {status}."


@tms.route('/trade')
def global_trade():
    return render_template(
        'tms/global_trade.html',
        recent_checks=get_compliance_history(),
        trade_settings=get_trade_settings(),
        highlighted_ref=(request.args.get('shipment_ref') or '').strip(),
    )


@tms.route('/trade/check', methods=['POST'])
def trade_check():
    shipment_ref = (request.form.get('shipment_ref') or '').strip()
    hs_code = (request.form.get('hs_code') or '').strip()
    origin = (request.form.get('origin_country') or '').strip()
    dest = (request.form.get('dest_country') or '').strip()

    if not shipment_ref or not hs_code or not origin or not dest:
        flash('Shipment reference, HS code, origin country, and destination country are required.', 'danger')
        return redirect(url_for('tms.global_trade'))

    result = run_compliance_check(shipment_ref, hs_code, origin, dest)
    flash(
        _trade_flash_message(result),
        {'clear': 'success', 'review': 'warning', 'blocked': 'danger'}.get(result['status'], 'info'),
    )
    return redirect(url_for('tms.global_trade', shipment_ref=result['shipment_ref']))


@tms.route('/trade/hs-search')
def trade_hs_search():
    return jsonify(search_hs_codes(request.args.get('q', '')))



# ── Yard Management ────────────────────────────────────────────────────────────
@tms.route('/yard', methods=['GET','POST'])
def yard_management():
    """Yard management: track trailers, containers, and chassis in the yard."""
    conn = get_db()
    if request.method == 'POST':
        action = request.form.get('action','checkin')
        if action == 'checkin':
            conn.execute(
                """INSERT INTO yard_units
                (unit_type, unit_number, carrier_name, shipment_ref,
                 location, status, driver_name, notes)
                VALUES (?,?,?,?,?,?,?,?)""",
                (request.form.get('unit_type','trailer'),
                 request.form.get('unit_number',''),
                 request.form.get('carrier_name',''),
                 request.form.get('shipment_ref',''),
                 request.form.get('location',''),
                 'in_yard',
                 request.form.get('driver_name',''),
                 request.form.get('notes','')))
            conn.commit()
            flash(f"Unit {request.form.get('unit_number','')} checked in.", 'success')
        elif action == 'checkout':
            unit_id = request.form.get('unit_id')
            conn.execute(
                """UPDATE yard_units SET status='departed',
                   departed_at=CURRENT_TIMESTAMP WHERE id=?""", (unit_id,))
            conn.commit()
            flash('Unit checked out.', 'success')
        elif action == 'move':
            unit_id = request.form.get('unit_id')
            conn.execute('UPDATE yard_units SET location=? WHERE id=?',
                (request.form.get('new_location'), unit_id))
            conn.commit()
            flash('Unit moved.', 'success')
        conn.close()
        return redirect(url_for('tms.yard_management'))
    
    units = conn.execute(
        """SELECT * FROM yard_units WHERE status='in_yard'
           ORDER BY arrived_at DESC""").fetchall()
    recent_departed = conn.execute(
        """SELECT * FROM yard_units WHERE status='departed'
           ORDER BY departed_at DESC LIMIT 20""").fetchall()
    stats = {
        'total_in_yard': len(units),
        'trailers': sum(1 for u in units if u['unit_type']=='trailer'),
        'containers': sum(1 for u in units if u['unit_type']=='container'),
        'chassis': sum(1 for u in units if u['unit_type']=='chassis'),
    }
    conn.close()
    return render_template('tms/yard.html', units=units,
        recent_departed=recent_departed, stats=stats)


# ══════════════════════════════════════════════════════════════════════════════
#  INTEGRATION HUB — Smart Connect
# ══════════════════════════════════════════════════════════════════════════════
@tms.route('/integrations')
@tms_roles_required("admin")
def integrations():
    from tms.tms_integrations import CATEGORY_LABELS, CATEGORY_ORDER, INTEGRATIONS
    from collections import OrderedDict
    conn = get_db()
    rows = conn.execute("SELECT integration_key, status, last_tested, last_error FROM integration_connections").fetchall()
    conn.close()
    connected = {r['integration_key']: dict(r) for r in rows}
    grouped = OrderedDict()
    for cat in CATEGORY_ORDER:
        grouped[cat] = []
    for key, data in INTEGRATIONS.items():
        cat = data.get('category', 'Other')
        if cat not in grouped:
            grouped[cat] = []
        item = dict(data)
        item['key'] = key
        conn_data = connected.get(key)
        item['connected'] = conn_data is not None and conn_data['status'] == 'connected'
        item['conn_data'] = conn_data
        grouped[cat].append(item)
    grouped = {k: v for k, v in grouped.items() if v}
    total = len(INTEGRATIONS)
    total_connected = sum(1 for v in connected.values() if v['status'] == 'connected')
    return render_template('tms/integrations.html',
        grouped=grouped, total=total, total_connected=total_connected,
        integrations=INTEGRATIONS, category_labels=CATEGORY_LABELS)


@tms.route('/integrations/settings', methods=['GET', 'POST'])
@tms_roles_required("admin")
def integrations_settings():
    from tms.tms_integrations import (
        CATEGORY_LABELS,
        SETTINGS_CATEGORY_ORDER,
        get_integration_settings,
        get_settings_providers,
        save_integration_settings,
    )

    saved = False
    if request.method == 'POST':
        save_integration_settings(request.form.to_dict())
        saved = True

    providers = get_settings_providers()
    settings = get_integration_settings()
    sections = []
    for category in SETTINGS_CATEGORY_ORDER:
        section_providers = [provider for provider in providers if provider.get('category') == category]
        if section_providers:
            sections.append({
                'key': category,
                'label': CATEGORY_LABELS.get(category, category),
                'providers': section_providers,
            })

    return render_template(
        'tms/integrations_settings.html',
        sections=sections,
        settings=settings,
        saved=saved,
    )


@tms.route('/integrations/connect', methods=['POST'])
@tms_roles_required("admin")
def integrations_connect():
    from tms.tms_integrations import INTEGRATIONS, encrypt_key
    import json as _json
    key = request.form.get('integration_key', '')
    if key not in INTEGRATIONS:
        flash('Unknown integration.', 'danger')
        return redirect(url_for('tms.integrations'))
    integ = INTEGRATIONS[key]
    fields = integ.get('fields', [])
    plain = {f['key']: request.form.get(f['key'], '') for f in fields}
    encrypted = {k: encrypt_key(v) for k, v in plain.items() if v}
    conn = get_db()
    conn.execute(
        """INSERT INTO integration_connections (integration_key, encrypted_fields, status, updated_at)
           VALUES (?, ?, 'connected', CURRENT_TIMESTAMP)
           ON CONFLICT(tenant_id, integration_key) DO UPDATE SET
               encrypted_fields=excluded.encrypted_fields,
               status='connected', last_error='', updated_at=CURRENT_TIMESTAMP""",
        (key, _json.dumps(encrypted)))
    conn.commit()
    conn.close()
    flash(f"{integ['name']} connected.", 'success')
    return redirect(url_for('tms.integrations'))


@tms.route('/integrations/disconnect', methods=['POST'])
@tms_roles_required("admin")
def integrations_disconnect():
    from tms.tms_integrations import INTEGRATIONS
    key = request.form.get('integration_key', '')
    conn = get_db()
    conn.execute("DELETE FROM integration_connections WHERE integration_key=?", (key,))
    conn.commit()
    conn.close()
    name = INTEGRATIONS.get(key, {}).get('name', key)
    flash(f"{name} disconnected.", 'info')
    return redirect(url_for('tms.integrations'))


@tms.route('/integrations/test/<key>', methods=['POST'])
@tms_roles_required("admin")
def integrations_test(key):
    from tms.carrier_clients import test_integration
    result = test_integration(key)
    return jsonify(**result)


# ══════════════════════════════════════════════════════════════════════════════
#  TMS MASTER — Internal Community Load Board
# ══════════════════════════════════════════════════════════════════════════════
@tms.route('/network', methods=['GET', 'POST'])
def flash_network():
    conn = get_db()
    if request.method == 'POST':
        ptype = request.form.get('post_type', 'load')
        company = request.form.get('company_name', 'My Company')
        if ptype == 'load':
            conn.execute(
                """INSERT INTO network_loads
                   (posted_by, company_name, origin_city, origin_country,
                    dest_city, dest_country, cargo_type, weight_kg, volume_cbm,
                    ready_date, equipment_type, rate_usd, rate_type, mode, notes)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (request.form.get('posted_by',''),
                 company,
                 request.form.get('origin_city',''),
                 request.form.get('origin_country',''),
                 request.form.get('dest_city',''),
                 request.form.get('dest_country',''),
                 request.form.get('cargo_type',''),
                 float(request.form.get('weight_kg') or 0),
                 float(request.form.get('volume_cbm') or 0),
                 request.form.get('ready_date',''),
                 request.form.get('equipment_type','any'),
                 float(request.form.get('rate_usd') or 0),
                 request.form.get('rate_type','negotiable'),
                 request.form.get('mode','any'),
                 request.form.get('notes','')))
            flash('Load posted to TMS Master.', 'success')
        elif ptype == 'capacity':
            conn.execute(
                """INSERT INTO network_capacity
                   (posted_by, company_name, origin_city, origin_country,
                    dest_city, dest_country, equipment_type, available_date,
                    capacity_kg, capacity_cbm, mode, rate_usd, rate_type, notes)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (request.form.get('posted_by',''),
                 company,
                 request.form.get('origin_city',''),
                 request.form.get('origin_country',''),
                 request.form.get('dest_city',''),
                 request.form.get('dest_country',''),
                 request.form.get('equipment_type',''),
                 request.form.get('available_date',''),
                 float(request.form.get('capacity_kg') or 0),
                 float(request.form.get('capacity_cbm') or 0),
                 request.form.get('mode','road'),
                 float(request.form.get('rate_usd') or 0),
                 request.form.get('rate_type','negotiable'),
                 request.form.get('notes','')))
            flash('Capacity posted to TMS Master.', 'success')
        conn.commit()
        conn.close()
        return redirect(url_for('tms.flash_network'))

    origin = request.args.get('origin','')
    dest   = request.args.get('dest','')
    mode   = request.args.get('mode','')
    lq = "SELECT * FROM network_loads WHERE status='open'"
    cq = "SELECT * FROM network_capacity WHERE status='available'"
    load_params = []
    capacity_params = []
    for val, cols in [(origin, 'origin_city,origin_country'), (dest, 'dest_city,dest_country')]:
        if val:
            c1, c2 = cols.split(',')
            clause = f" AND ({c1} LIKE ? OR {c2} LIKE ?)"
            pattern = f"%{val}%"
            lq += clause
            cq += clause
            load_params.extend([pattern, pattern])
            capacity_params.extend([pattern, pattern])
    if mode:
        lq += " AND mode=?"
        cq += " AND mode=?"
        load_params.append(mode)
        capacity_params.append(mode)
    loads = conn.execute(lq + " ORDER BY created_at DESC LIMIT 50", load_params).fetchall()
    capacity = conn.execute(cq + " ORDER BY created_at DESC LIMIT 50", capacity_params).fetchall()
    stats = {
        'total_loads':    conn.execute("SELECT COUNT(*) FROM network_loads WHERE status='open'").fetchone()[0],
        'total_capacity': conn.execute("SELECT COUNT(*) FROM network_capacity WHERE status='available'").fetchone()[0],
        'countries':      conn.execute("SELECT COUNT(DISTINCT origin_country) FROM network_loads WHERE origin_country!=''").fetchone()[0],
    }
    conn.close()
    return render_template('tms/network.html',
        loads=loads, capacity=capacity, stats=stats,
        filter_origin=origin, filter_dest=dest, filter_mode=mode)


@tms.route('/network/close', methods=['POST'])
def network_close_post():
    ptype   = request.form.get('post_type', 'load')
    post_id = request.form.get('post_id')
    conn = get_db()
    if ptype == 'load':
        conn.execute("UPDATE network_loads SET status='closed' WHERE id=?", (post_id,))
    else:
        conn.execute("UPDATE network_capacity SET status='closed' WHERE id=?", (post_id,))
    conn.commit()
    conn.close()
    flash('Post closed.', 'info')
    return redirect(url_for('tms.flash_network'))


# ── Customs & Compliance ─────────────────────────────────────────────────────

@tms.route('/customs')
def customs():
    ctx = get_customs_dashboard_context()
    return render_template(
        "tms/customs.html",
        records=ctx["records"],
        stats=ctx["stats"],
        customs_statuses=CUSTOMS_STATUSES,
    )


@tms.route('/shipments/<ref>/customs', methods=['GET', 'POST'])
def shipment_customs(ref):
    shipment = find_shipment_by_ref(ref)
    if not shipment:
        return "Not found", 404
    if request.method == 'POST':
        data = request.form.to_dict()
        if data.get("hs_code") and data.get("declared_value") and data.get("origin_country") and data.get("destination_country"):
            try:
                pct, amt = estimate_duty(
                    data["hs_code"],
                    data["origin_country"],
                    data["destination_country"],
                    float(data.get("declared_value", 0)),
                )
                data["estimated_duty_pct"] = pct
                data["estimated_duty_amount"] = amt
            except (ValueError, TypeError):
                pass
        upsert_customs_record(ref, data)
        flash("Customs record saved.", "success")
        return redirect(url_for('tms.shipment_customs', ref=ref))
    record = get_customs_record(ref)
    flags = {}
    if record and record.get("origin_country") and record.get("destination_country"):
        flags = check_compliance_flags(
            record["origin_country"],
            record["destination_country"],
            record.get("hs_code", ""),
        )
    return render_template(
        "tms/shipment_customs.html",
        shipment=dict(shipment),
        record=record,
        flags=flags,
        incoterms=INCOTERMS,
        customs_statuses=CUSTOMS_STATUSES,
        hs_hints=HS_CODE_HINTS,
    )


@tms.route('/shipments/<ref>/customs/check', methods=['POST'])
def customs_compliance_check(ref):
    data = request.get_json(silent=True) or {}
    flags = check_compliance_flags(
        data.get("origin", ""),
        data.get("destination", ""),
        data.get("hs_code", ""),
    )
    try:
        pct, amt = estimate_duty(
            data.get("hs_code", ""),
            data.get("origin", ""),
            data.get("destination", ""),
            float(data.get("value", 0)),
        )
    except (ValueError, TypeError):
        pct, amt = 0.0, 0.0
    return jsonify(flags=flags, duty_pct=pct, duty_amount=amt)


# ── Route Planner ──────────────────────────────────────────────────────────────

@tms.route("/routes")
def route_plans():
    init_tms_db()
    plans = get_all_route_plans()
    return render_template("tms/route_plans.html", plans=plans)


@tms.route("/routes/new", methods=["POST"])
def route_new():
    data = request.get_json(silent=True) or request.form.to_dict()
    ref = create_route_plan(
        shipment_ref=data.get("shipment_ref", ""),
        load_number=data.get("load_number", ""),
        driver_id=data.get("driver_id") or None,
        notes=data.get("notes", ""),
    )
    return jsonify(ok=True, route_ref=ref)


@tms.route("/routes/<route_ref>")
def route_detail(route_ref):
    init_tms_db()
    plan, stops = get_route_plan(route_ref)
    if not plan:
        return "Route not found", 404
    conn = get_db()
    try:
        drivers = [
            dict(r)
            for r in conn.execute(
                "SELECT id, name FROM drivers WHERE status='Active' ORDER BY name"
            ).fetchall()
        ]
    finally:
        conn.close()
    pickups = [s for s in stops if s["stop_type"] == "Pickup"]
    drops = [s for s in stops if s["stop_type"] == "Drop"]
    return render_template(
        "tms/route_detail.html",
        plan=plan,
        stops=stops,
        drivers=drivers,
        pickups=pickups,
        drops=drops,
        stop_types=STOP_TYPES,
        route_statuses=ROUTE_STATUSES,
    )


@tms.route("/routes/<route_ref>/stops", methods=["POST"])
def route_add_stop(route_ref):
    data = request.get_json(silent=True) or request.form.to_dict()
    stop_num, stop_id = add_route_stop(route_ref, data)
    return jsonify(ok=True, stop_number=stop_num, stop_id=stop_id)


@tms.route("/routes/<route_ref>/stops/<int:stop_id>", methods=["DELETE"])
def route_delete_stop(route_ref, stop_id):
    delete_route_stop(route_ref, stop_id)
    return jsonify(ok=True)


@tms.route("/routes/<route_ref>/reorder", methods=["POST"])
def route_reorder(route_ref):
    data = request.get_json(silent=True) or {}
    ordered = data.get("order", [])
    reorder_stops(route_ref, ordered)
    return jsonify(ok=True)


@tms.route("/routes/<route_ref>/stops/<int:stop_id>/status", methods=["POST"])
def route_stop_status(route_ref, stop_id):
    data = request.get_json(silent=True) or {}
    update_stop_status(route_ref, stop_id, data.get("status", ""))
    return jsonify(ok=True)


@tms.route("/routes/<route_ref>/assign", methods=["POST"])
def route_assign(route_ref):
    data = request.get_json(silent=True) or {}
    assign_driver_to_route(route_ref, data.get("driver_id"))
    return jsonify(ok=True)


@tms.route("/scenarios")
def scenarios_page():
    return _render_scenarios_page(selected_saved_id=request.args.get("scenario_id", type=int))


@tms.route("/scenarios/run", methods=["POST"])
def scenarios_run():
    scenario_type = _normalize_text(request.form.get("scenario_type"))
    try:
        current_inputs = _scenario_inputs_from_source(scenario_type, request.form)
        result = run_scenario(scenario_type, current_inputs)
    except ValueError as exc:
        current_inputs = _scenario_form_defaults()
        try:
            current_inputs = _scenario_form_defaults(_scenario_inputs_from_source(scenario_type, request.form))
        except ValueError:
            scenario_type = "carrier_switch"
        return _render_scenarios_page(
            active_type=scenario_type,
            current_inputs=current_inputs,
            form_error=str(exc),
            status_code=400,
        )

    return _render_scenarios_page(
        active_type=scenario_type,
        current_inputs=result.get("inputs"),
        result=result,
        save_name=result.get("name_suggestion", ""),
    )


@tms.route("/scenarios/save", methods=["POST"])
def scenarios_save_route():
    scenario_type = _normalize_text(request.form.get("scenario_type"))
    save_name = _normalize_text(request.form.get("name"))
    current_inputs = None
    result = None

    try:
        inputs_json = _normalize_text(request.form.get("inputs_json"))
        results_json = _normalize_text(request.form.get("results_json"))
        if not inputs_json or not results_json:
            raise ValueError("Run a scenario before saving it.")

        current_inputs = json.loads(inputs_json)
        result = json.loads(results_json)
        saved = save_scenario(save_name, scenario_type, current_inputs, result)
    except json.JSONDecodeError:
        return _render_scenarios_page(
            active_type=scenario_type or "carrier_switch",
            form_error="Scenario payload is invalid. Run the scenario again before saving.",
            status_code=400,
            save_name=save_name,
        )
    except ValueError as exc:
        return _render_scenarios_page(
            active_type=scenario_type or "carrier_switch",
            current_inputs=current_inputs,
            result=result,
            form_error=str(exc),
            status_code=400,
            save_name=save_name,
        )

    flash("Scenario saved.", "success")
    return redirect(url_for("tms.scenarios_page", scenario_id=saved["id"]))


# ---------------------------------------------------------------------------
# LTL Load Builder routes
# ---------------------------------------------------------------------------

@tms.route('/ltl')
def ltl_loads():
    loads = ltl_get_all()
    return render_template("tms/ltl_loads.html", loads=loads, ltl_statuses=LTL_STATUSES)


@tms.route('/ltl/new', methods=['GET', 'POST'])
def ltl_new():
    if request.method == 'POST':
        load_number = ltl_create(request.form.to_dict())
        return redirect(url_for('tms.ltl_detail', load_number=load_number))
    return render_template("tms/ltl_new.html", equipment_types=LTL_EQUIPMENT_TYPES)


@tms.route('/ltl/<load_number>')
def ltl_detail(load_number):
    load, shipments = ltl_get(load_number)
    if not load:
        return "Load not found", 404
    weight_pct, pallet_pct, lbs_to_ftl = ltl_fill_stats(load)
    conn = get_db()
    try:
        existing_refs = [s["shipment_ref"] for s in shipments]
        placeholders = ",".join("?" * len(existing_refs)) if existing_refs else "'__none__'"
        query = (
            f"SELECT shipment_ref, cargo_description, origin_port, destination_port "
            f"FROM shipments WHERE shipment_ref NOT IN ({placeholders}) "
            f"AND status NOT IN ('Delivered','Cancelled') "
            f"ORDER BY shipment_ref DESC LIMIT 50"
        )
        available = [dict(r) for r in conn.execute(query, existing_refs).fetchall()]
    finally:
        conn.close()
    return render_template(
        "tms/ltl_detail.html",
        load=load,
        shipments=shipments,
        weight_pct=weight_pct,
        pallet_pct=pallet_pct,
        lbs_to_ftl=lbs_to_ftl,
        available=available,
        equipment_types=LTL_EQUIPMENT_TYPES,
    )


@tms.route('/ltl/<load_number>/add', methods=['POST'])
def ltl_add_shipment_route(load_number):
    data = request.get_json(silent=True) or request.form.to_dict()
    ok, msg = ltl_add_shipment(
        load_number,
        data.get("shipment_ref", ""),
        float(data.get("weight_lbs", 0) or 0),
        int(data.get("pallets", 0) or 0),
        data.get("pickup_address", ""),
        data.get("delivery_address", ""),
    )
    return jsonify(ok=ok, message=msg)


@tms.route('/ltl/<load_number>/remove/<ref>', methods=['POST'])
def ltl_remove_shipment_route(load_number, ref):
    ok = ltl_remove_shipment(load_number, ref)
    return jsonify(ok=ok)


@tms.route('/ltl/<load_number>/convert', methods=['POST'])
def ltl_convert_route(load_number):
    ok, result = ltl_convert_to_ftl(load_number)
    return jsonify(ok=ok, ftl_ref=result if ok else None, message=result if not ok else "Converted")


# ---------------------------------------------------------------------------
# Driver Direct Messaging
# ---------------------------------------------------------------------------

@tms.route("/drivers/<int:driver_id>/messages")
def driver_messages(driver_id):
    conn = get_db()
    try:
        driver = conn.execute("SELECT * FROM drivers WHERE id=?", (driver_id,)).fetchone()
    finally:
        conn.close()
    if not driver:
        return "Driver not found", 404
    messages = get_driver_messages(driver_id)
    return render_template("tms/driver_messages.html", driver=dict(driver), messages=messages)


@tms.route("/drivers/<int:driver_id>/messages/send", methods=["POST"])
def driver_send_message(driver_id):
    data = request.get_json(silent=True) or request.form.to_dict()
    send_message_to_driver(driver_id, data.get("message", ""), data.get("shipment_ref", ""))
    return jsonify(ok=True)


@tms.route("/drivers/<int:driver_id>/messages/reply", methods=["POST"])
def driver_message_reply(driver_id):
    """Public endpoint — drivers reply via link, no login required."""
    data = request.get_json(silent=True) or request.form.to_dict()
    driver_token = (
        data.get("driver_token")
        or data.get("token")
        or request.headers.get("X-Driver-Token")
    )
    driver_context = get_driver_checkin_context(driver_token) if driver_token else None
    if not driver_context or int(driver_context["driver"]["id"]) != int(driver_id):
        return jsonify(ok=False, error="A valid driver token is required."), 403
    driver_reply(driver_id, data.get("message", ""), data.get("shipment_ref", ""))
    return jsonify(ok=True)


# ---------------------------------------------------------------------------
# POD Submission (mobile-friendly public endpoint)
# ---------------------------------------------------------------------------

@tms.route("/shipments/<ref>/pod-submit", methods=["GET", "POST"])
def pod_submission(ref):
    """Legacy POD route. Anonymous access now requires the shipment POD token."""
    shipment = find_shipment_by_ref(ref)
    if not shipment:
        return "Shipment not found", 404

    token = _normalize_text(request.values.get("token"))
    if token:
        return capture_pod(ref, token)

    if session.get("logged_in"):
        return redirect(url_for("tms.capture_pod", ref=ref, token=get_or_create_pod_token(ref)))

    return "A valid POD link is required.", 403


@tms.route("/pods")
def pod_dashboard():
    pods = get_pod_submissions()
    return render_template("tms/pod_dashboard.html", pods=pods)


@tms.route("/pods/<int:pod_id>/release", methods=["POST"])
def pod_release_to_billing(pod_id):
    conn = get_db()
    try:
        pod = conn.execute("SELECT * FROM pod_submissions WHERE id=?", (pod_id,)).fetchone()
    finally:
        conn.close()
    if not pod:
        return jsonify(ok=False, message="Not found")
    route_pod_to_billing(pod_id, pod["shipment_ref"], notes="Manually released by dispatcher")
    return jsonify(ok=True)


# ---------------------------------------------------------------------------
# Billing Queue
# ---------------------------------------------------------------------------

@tms.route("/billing-queue")
def billing_queue_view():
    items = get_billing_queue()
    return render_template("tms/billing_queue.html", items=items)


@tms.route("/billing-queue/<ref>/mark-billed", methods=["POST"])
def billing_mark_billed(ref):
    mark_billed(ref)
    return jsonify(ok=True)


# ---------------------------------------------------------------------------
# Warehouse Management System (WMS)
# ---------------------------------------------------------------------------

def _parse_wms_float(value, label, *, minimum=0.0):
    raw_value = (value or "").strip()
    if raw_value == "":
        number = 0.0
    else:
        try:
            number = float(raw_value)
        except (TypeError, ValueError) as exc:
            raise ValueError(f"{label} must be a number.") from exc
    if number < minimum:
        comparator = "greater than zero" if minimum > 0 else "zero or greater"
        raise ValueError(f"{label} must be {comparator}.")
    return number


def _parse_receipt_form_lines(form):
    skus = form.getlist("line_sku")
    expected_qtys = form.getlist("line_expected_qty")
    location_codes = form.getlist("line_location_code")
    notes = form.getlist("line_notes")
    row_count = max(len(skus), len(expected_qtys), len(location_codes), len(notes), 0)
    lines = []

    for index in range(row_count):
        sku = _normalize_text(skus[index] if index < len(skus) else "")
        expected_raw = expected_qtys[index] if index < len(expected_qtys) else ""
        location_code = _normalize_text(location_codes[index] if index < len(location_codes) else "")
        note = _normalize_text(notes[index] if index < len(notes) else "")

        if not any((sku, _normalize_text(expected_raw), location_code, note)):
            continue
        if not sku:
            raise ValueError(f"Receipt line {index + 1} is missing a SKU.")

        lines.append(
            {
                "sku": sku,
                "expected_qty": _parse_wms_float(expected_raw, f"Receipt line {index + 1} expected quantity", minimum=0.000001),
                "location_code": location_code,
                "notes": note,
            }
        )

    if not lines:
        raise ValueError("Add at least one receipt line.")
    return lines


def _parse_pick_form_lines(form):
    skus = form.getlist("line_sku")
    quantities = form.getlist("line_quantity")
    location_codes = form.getlist("line_location_code")
    row_count = max(len(skus), len(quantities), len(location_codes), 0)
    lines = []

    for index in range(row_count):
        sku = _normalize_text(skus[index] if index < len(skus) else "")
        quantity_raw = quantities[index] if index < len(quantities) else ""
        location_code = _normalize_text(location_codes[index] if index < len(location_codes) else "")

        if not any((sku, _normalize_text(quantity_raw), location_code)):
            continue
        if not sku:
            raise ValueError(f"Pick line {index + 1} is missing a SKU.")

        lines.append(
            {
                "sku": sku,
                "quantity": _parse_wms_float(quantity_raw, f"Pick line {index + 1} quantity", minimum=0.000001),
                "location_code": location_code,
            }
        )

    if not lines:
        raise ValueError("Add at least one pick line.")
    return lines


@tms.route("/wms")
@tms_login_required
def wms_dashboard_page():
    return render_template("tms/wms.html", dashboard=get_wms_dashboard())


@tms.route("/wms/inventory")
@tms_login_required
def wms_inventory_page():
    inventory = list_wms_inventory()
    selected_sku = _normalize_text(request.args.get("sku"))
    selected_location = _normalize_text(request.args.get("location_code"))
    sku_inventory = get_wms_inventory_by_sku(selected_sku) if selected_sku else []
    location_inventory = get_wms_inventory_by_location(selected_location) if selected_location else []
    inventory_stats = {
        "row_count": len(inventory),
        "sku_count": len({row["sku"] for row in inventory}),
        "location_count": len({row["location_code"] for row in inventory if row.get("location_code")}),
        "total_quantity": round(sum(float(row.get("quantity") or 0) for row in inventory), 2),
    }
    return render_template(
        "tms/wms_inventory.html",
        inventory=inventory,
        inventory_stats=inventory_stats,
        selected_sku=selected_sku,
        selected_location=selected_location,
        sku_inventory=sku_inventory,
        location_inventory=location_inventory,
    )


@tms.route("/wms/receipts")
@tms_login_required
def wms_receipts_page():
    return render_template(
        "tms/wms_receipts.html",
        receipts=list_wms_receipts(),
        selected_receipt=None,
    )


@tms.route("/wms/receipts/create", methods=["POST"])
@tms_login_required
def wms_receipt_create():
    try:
        receipt = create_wms_receipt(
            request.form.get("shipment_ref", ""),
            request.form.get("supplier", ""),
            request.form.get("po_number", ""),
            _parse_receipt_form_lines(request.form),
        )
    except ValueError as exc:
        flash(str(exc), "danger")
        return redirect(url_for("tms.wms_receipts_page"))

    flash(f"Receipt {receipt['receipt_ref']} created.", "success")
    return redirect(url_for("tms.wms_receipt_detail", id=receipt["id"]))


@tms.route("/wms/receipts/<int:id>")
@tms_login_required
def wms_receipt_detail(id):
    receipt = get_wms_receipt(id)
    if not receipt:
        flash("Receipt not found.", "danger")
        return redirect(url_for("tms.wms_receipts_page"))
    return render_template(
        "tms/wms_receipts.html",
        receipts=list_wms_receipts(),
        selected_receipt=receipt,
    )


@tms.route("/wms/receipts/<int:id>/receive", methods=["POST"])
@tms_login_required
def wms_receipt_receive(id):
    receipt = get_wms_receipt(id)
    if not receipt:
        flash("Receipt not found.", "danger")
        return redirect(url_for("tms.wms_receipts_page"))

    try:
        receipt_line_id = int(request.form.get("receipt_line_id", "0"))
    except ValueError:
        flash("Receipt line is invalid.", "danger")
        return redirect(url_for("tms.wms_receipt_detail", id=id))

    if receipt_line_id not in {line["id"] for line in receipt["lines"]}:
        flash("Receipt line does not belong to this receipt.", "danger")
        return redirect(url_for("tms.wms_receipt_detail", id=id))

    try:
        update_wms_receipt_line(
            receipt_line_id,
            _parse_wms_float(request.form.get("qty"), "Received quantity", minimum=0.0),
            request.form.get("location_code", ""),
        )
    except ValueError as exc:
        flash(str(exc), "danger")
    else:
        flash("Receipt line updated.", "success")

    return redirect(url_for("tms.wms_receipt_detail", id=id))


@tms.route("/wms/picks")
@tms_login_required
def wms_picks_page():
    return render_template(
        "tms/wms_picks.html",
        picks=list_wms_picks(),
        selected_pick=None,
    )


@tms.route("/wms/picks/create", methods=["POST"])
@tms_login_required
def wms_pick_create():
    try:
        pick = create_wms_pick(
            request.form.get("shipment_ref", ""),
            _parse_pick_form_lines(request.form),
        )
    except ValueError as exc:
        flash(str(exc), "danger")
        return redirect(url_for("tms.wms_picks_page"))

    flash(f"Pick {pick['pick_ref']} created.", "success")
    return redirect(url_for("tms.wms_pick_detail", id=pick["id"]))


@tms.route("/wms/picks/<int:id>")
@tms_login_required
def wms_pick_detail(id):
    pick = get_wms_pick(id)
    if not pick:
        flash("Pick not found.", "danger")
        return redirect(url_for("tms.wms_picks_page"))
    return render_template(
        "tms/wms_picks.html",
        picks=list_wms_picks(),
        selected_pick=pick,
    )


@tms.route("/wms/picks/<int:id>/pick", methods=["POST"])
@tms_login_required
def wms_pick_line_update(id):
    pick = get_wms_pick(id)
    if not pick:
        flash("Pick not found.", "danger")
        return redirect(url_for("tms.wms_picks_page"))

    try:
        pick_line_id = int(request.form.get("pick_line_id", "0"))
    except ValueError:
        flash("Pick line is invalid.", "danger")
        return redirect(url_for("tms.wms_pick_detail", id=id))

    if pick_line_id not in {line["id"] for line in pick["lines"]}:
        flash("Pick line does not belong to this pick.", "danger")
        return redirect(url_for("tms.wms_pick_detail", id=id))

    try:
        update_wms_pick_line(
            pick_line_id,
            _parse_wms_float(request.form.get("picked_qty"), "Picked quantity", minimum=0.0),
        )
    except ValueError as exc:
        flash(str(exc), "danger")
    else:
        flash("Pick line updated.", "success")

    return redirect(url_for("tms.wms_pick_detail", id=id))


@tms.route("/wms/locations")
@tms_login_required
def wms_locations_page():
    return render_template(
        "tms/wms_locations.html",
        locations=list_wms_locations(),
        utilization=get_wms_location_utilization(),
    )


# ---------------------------------------------------------------------------
# Customer Order Intake & Pipeline
# ---------------------------------------------------------------------------

@tms.route('/orders')
def customer_orders():
    pipeline = get_pipeline_orders()
    counts = get_pipeline_counts()
    return render_template("tms/customer_orders.html",
        pipeline=pipeline, counts=counts,
        stages=PIPELINE_STAGES)


@tms.route('/orders/submit', methods=['GET', 'POST'])
def order_submit():
    """Public endpoint — customers submit load requests."""
    if request.method == 'POST':
        rate_limit_key = f"order-submit:{_request_ip_address() or 'unknown'}"
        if not ORDER_SUBMIT_RATE_LIMITER.allow(rate_limit_key):
            return render_template(
                "tms/order_submit.html",
                service_types=SERVICE_TYPES,
                equipment_types=EQUIPMENT_TYPES_ORDER,
                error_message="Too many order submissions. Try again in a few minutes.",
            ), 429
        order_ref = submit_customer_order(request.form.to_dict())
        conn = get_db()
        try:
            order = conn.execute(
                "SELECT shipment_ref FROM customer_orders WHERE order_ref = ?",
                (order_ref,),
            ).fetchone()
        finally:
            conn.close()
        if order and _normalize_text(order["shipment_ref"]):
            try:
                notify_shipment_created(order["shipment_ref"], request.form.get("customer_email", ""))
            except Exception:
                pass
        return render_template("tms/order_success.html", order_ref=order_ref)
    return render_template("tms/order_submit.html",
        service_types=SERVICE_TYPES,
        equipment_types=EQUIPMENT_TYPES_ORDER)


@tms.route('/orders/<order_ref>/advance', methods=['POST'])
def order_advance(order_ref):
    data = request.get_json(silent=True) or {}
    new_stage = data.get("stage", "")
    if new_stage not in PIPELINE_STAGES:
        return jsonify(ok=False, error="Invalid stage"), 400
    advance_order_stage(order_ref, new_stage)
    return jsonify(ok=True)


@tms.route('/orders/<order_ref>')
def order_detail(order_ref):
    order = get_customer_order(order_ref)
    if not order:
        return "Order not found", 404
    return render_template("tms/order_detail.html", order=order, stages=PIPELINE_STAGES)


# ── Auto Invoices ─────────────────────────────────────────────────
@tms.route('/auto-invoices')
@tms_login_required
def auto_invoices():
    invoices = get_all_invoices()
    stats = get_invoice_stats()
    return render_template("tms/auto_invoices.html", invoices=invoices, stats=stats)

@tms.route('/auto-invoices/<invoice_number>')
@tms_login_required
def auto_invoice_detail(invoice_number):
    inv = get_invoice(invoice_number)
    if not inv:
        return "Not found", 404
    return render_template("tms/auto_invoice_detail.html", inv=inv)

@tms.route('/auto-invoices/create', methods=['POST'])
@tms_login_required
def auto_invoice_create():
    data = request.form.to_dict()
    existing_invoice = next(
        (invoice for invoice in get_all_invoices() if invoice.get("shipment_ref") == data.get("shipment_ref", "")),
        None,
    )
    fsc = calculate_fsc_for_shipment(float(data.get('base_rate', 0)))
    inv_num = create_auto_invoice(
        shipment_ref=data.get('shipment_ref', ''),
        customer_name=data.get('customer_name', ''),
        customer_email=data.get('customer_email', ''),
        base_rate=float(data.get('base_rate', 0)),
        fuel_surcharge_pct=fsc['fsc_pct'],
        payment_terms=data.get('payment_terms', 'Net 30')
    )
    try:
        audit('CREATE', 'invoice', inv_num, new_value={'invoice_number': inv_num, 'shipment_ref': data.get('shipment_ref', '')})
    except Exception:
        pass
    if not existing_invoice:
        try:
            invoice = get_invoice(inv_num) or {}
            notify_invoice_generated(
                invoice_number=inv_num,
                shipment_ref=data.get("shipment_ref", ""),
                customer_email=data.get("customer_email", ""),
                amount=invoice.get("total", 0),
                currency=invoice.get("currency", "USD"),
                customer_name=invoice.get("customer_name", "") or data.get("customer_name", ""),
                due_date=invoice.get("due_date", ""),
            )
        except Exception:
            pass
    return jsonify(ok=True, invoice_number=inv_num)

@tms.route('/auto-invoices/<invoice_number>/sent', methods=['POST'])
@tms_login_required
def auto_invoice_mark_sent(invoice_number):
    mark_invoice_sent(invoice_number)
    return jsonify(ok=True)

@tms.route('/auto-invoices/<invoice_number>/paid', methods=['POST'])
@tms_login_required
def auto_invoice_mark_paid(invoice_number):
    mark_invoice_paid(invoice_number)
    return jsonify(ok=True)


# ── Fuel Surcharge ────────────────────────────────────────────────
@tms.route('/fuel-surcharge')
@tms_login_required
def fuel_surcharge():
    latest = get_latest_doe_price()
    history = get_fsc_history()
    brackets = get_fsc_brackets()
    return render_template("tms/fuel_surcharge.html",
        latest=latest, history=history, brackets=brackets)

@tms.route('/fuel-surcharge/update', methods=['POST'])
@tms_login_required
def fuel_surcharge_update():
    data = request.form.to_dict()
    pct = log_doe_price(float(data.get('doe_price', 0)), data.get('effective_date'), data.get('notes', ''))
    return jsonify(ok=True, fsc_pct=pct)

@tms.route('/fuel-surcharge/calculate', methods=['GET'])
def fuel_surcharge_calc():
    base = float(request.args.get('base_rate', 0))
    doe = request.args.get('doe_price')
    result = calculate_fsc_for_shipment(base, float(doe) if doe else None)
    return jsonify(result)


# ── Carrier Scorecard ─────────────────────────────────────────────────────────

@tms.route('/carrier-scorecard')
@tms_login_required
def carrier_scorecard():
    scorecards = get_all_scorecards()
    stats = get_scorecard_stats()
    return render_template("tms/carrier_scorecard.html", scorecards=scorecards, stats=stats)


@tms.route('/carrier-scorecard/log', methods=['POST'])
@tms_login_required
def carrier_log_performance():
    log_carrier_performance(request.form.to_dict())
    return redirect(url_for('tms.carrier_scorecard'))


@tms.route('/carrier-scorecard/best-lane', methods=['GET'])
@tms_login_required
def carrier_best_lane():
    origin = request.args.get('origin', '')
    dest = request.args.get('dest', '')
    carriers = get_best_carrier_for_lane(origin, dest)
    return jsonify(carriers=carriers)


@tms.route('/carrier-scorecard/<path:carrier_name>')
@tms_login_required
def carrier_scorecard_detail(carrier_name):
    history = get_carrier_history(carrier_name)
    scorecards = get_all_scorecards()
    card = next((s for s in scorecards if s['carrier_name'] == carrier_name), None)
    return render_template("tms/carrier_scorecard_detail.html",
        carrier_name=carrier_name, card=card, history=history)


# ── IFTA Reporting ────────────────────────────────────────────────────────────

@tms.route('/ifta')
@tms_login_required
def ifta_dashboard():
    quarter = request.args.get('quarter') or get_current_quarter()
    quarters = get_all_quarters()
    summary = get_quarterly_summary(quarter)
    purchases = get_fuel_purchases(quarter)
    mileage = get_mileage_logs(quarter)
    return render_template("tms/ifta.html",
        quarter=quarter, quarters=quarters,
        summary=summary, purchases=purchases, mileage=mileage,
        fuel_types=FUEL_TYPES)


@tms.route('/ifta/fuel', methods=['POST'])
@tms_login_required
def ifta_add_fuel():
    add_fuel_purchase(request.form.to_dict())
    return redirect(url_for('tms.ifta_dashboard'))


@tms.route('/ifta/mileage', methods=['POST'])
@tms_login_required
def ifta_add_mileage():
    add_mileage_log(request.form.to_dict())
    return redirect(url_for('tms.ifta_dashboard'))


# ── Customer Tracking Portal (Public) ─────────────────────────────────────────

@tms.route('/track/<ref>')
def customer_track(ref):
    """Public customer tracking page."""
    if not session.get("logged_in") and not _public_tracking_token_is_valid(ref, request.args.get("token")):
        return "A valid tracking link is required.", 403
    tracking_context = get_tracking_page_context(ref)
    if not tracking_context:
        return render_template("tms/track_not_found.html", ref=ref)
    return render_template("tms/tracking.html", **tracking_context)


@tms.route('/track')
def customer_track_search():
    """Public tracking search page."""
    if not session.get("logged_in"):
        if "login" in current_app.view_functions:
            next_url = request.full_path if request.query_string else request.path
            return redirect(url_for("login", next=next_url))
        return "Authentication required.", 403
    ref = request.args.get('ref', '').strip().upper()
    if ref:
        return redirect(build_public_tracking_url(ref))
    return render_template("tms/customer_track_search.html")


# ── Rate Matrix Builder ────────────────────────────────────────────────────────

@tms.route('/rate-matrix')
@tms_login_required
def rate_matrix():
    matrices = get_all_matrices()
    return render_template("tms/rate_matrix.html", matrices=matrices)


@tms.route('/rate-matrix/new', methods=['POST'])
@tms_login_required
def rate_matrix_new():
    data = request.form.to_dict()
    matrix_id = create_matrix(
        data.get("matrix_name", "New Matrix"),
        data.get("service_type", "LTL"),
        data.get("equipment_type", "Dry Van"),
        data.get("effective_date", ""),
        data.get("expiry_date", ""),
        data.get("notes", "")
    )
    return redirect(url_for('tms.rate_matrix_detail', matrix_id=matrix_id))


@tms.route('/rate-matrix/<int:matrix_id>')
@tms_login_required
def rate_matrix_detail(matrix_id):
    matrix, entries = get_matrix(matrix_id)
    if not matrix:
        return "Not found", 404
    return render_template("tms/rate_matrix_detail.html", matrix=matrix, entries=entries)


@tms.route('/rate-matrix/<int:matrix_id>/entries', methods=['POST'])
@tms_login_required
def rate_matrix_add_entry(matrix_id):
    add_rate_entry(matrix_id, request.form.to_dict())
    return redirect(url_for('tms.rate_matrix_detail', matrix_id=matrix_id))


@tms.route('/rate-matrix/entries/<int:entry_id>', methods=['DELETE'])
@tms_login_required
def rate_matrix_delete_entry(entry_id):
    delete_rate_entry(entry_id)
    return jsonify(ok=True)


@tms.route('/rate-matrix/lookup')
@tms_login_required
def rate_matrix_lookup():
    origin = request.args.get('origin', '')
    dest = request.args.get('dest', '')
    weight = float(request.args.get('weight', 0))
    service = request.args.get('service', 'LTL')
    result = lookup_rate(origin, dest, weight, service)
    return jsonify(result)


# ── Notifications ─────────────────────────────────────────────────
@tms.route('/notifications')
@tms_login_required
def notification_log():
    logs = get_notification_log()
    smtp_ok = smtp_configured()
    return render_template("tms/notification_log.html", logs=logs, smtp_ok=smtp_ok)


# ── Document OCR ────────────────────────────────────────────────────────────

@tms.route('/ocr')
@tms_login_required
def ocr_dashboard():
    history = get_ocr_history()
    return render_template("tms/ocr.html", history=history)


@tms.route('/ocr/upload', methods=['POST'])
@tms_login_required
def ocr_upload():
    if 'document' not in request.files:
        return jsonify(ok=False, message="No file provided")
    f = request.files['document']
    if not f or not f.filename:
        return jsonify(ok=False, message="Empty file")
    upload_dir = os.path.join(os.path.dirname(__file__), '..', 'static', 'ocr_uploads')
    os.makedirs(upload_dir, exist_ok=True)
    original_name = secure_filename(f.filename)
    if not original_name:
        return jsonify(ok=False, message="Invalid filename")
    safe_name = f"ocr_{int(time.time())}_{original_name}"
    path = os.path.join(upload_dir, safe_name)
    f.save(path)
    result = process_ocr_upload(path, original_name)
    return jsonify(ok=True, **result)


@tms.route('/ocr/<int:job_id>/apply', methods=['POST'])
@tms_login_required
def ocr_apply(job_id):
    data = request.get_json(silent=True) or {}
    mark_ocr_applied(job_id, data.get('shipment_ref', ''))
    return jsonify(ok=True)


# ── AI Load Matching ────────────────────────────────────────────────────────

@tms.route('/load-matching')
@tms_login_required
def load_matching():
    suggestions = get_match_suggestions()
    summary = get_load_board_summary()
    return render_template("tms/load_matching.html", suggestions=suggestions, summary=summary)


@tms.route('/load-matching/<ref>')
@tms_login_required
def load_matching_detail(ref):
    suggestions = get_match_suggestions(ref)
    result = suggestions[0] if suggestions else None
    return render_template("tms/load_matching_detail.html", result=result, ref=ref)


@tms.route('/load-matching/<ref>/assign', methods=['POST'])
@tms_login_required
def load_matching_assign(ref):
    data = request.get_json(silent=True) or {}
    ok = auto_assign_driver(ref, data.get('driver_id'))
    return jsonify(ok=ok)


# ── Driver PWA ───────────────────────────────────────────────────────────────

@tms.route('/driver-app')
def driver_app():
    """Driver PWA hub — public, mobile-optimized."""
    driver_id = request.args.get('driver_id')
    shipment_ref = request.args.get('ref', '')
    tab = request.args.get('tab', 'home')
    flash_message = request.args.get('msg', '')
    flash_type = request.args.get('msg_type', 'success')
    active_pod_url = ""

    import sqlite3
    conn = get_db()
    conn.row_factory = sqlite3.Row
    try:
        driver = conn.execute("SELECT * FROM drivers WHERE id=?", (driver_id,)).fetchone() if driver_id else None
        # Active load: ref from URL or most recent assigned to driver
        active_load = None
        if shipment_ref:
            active_load = conn.execute(
                "SELECT * FROM shipments WHERE shipment_ref=?", (shipment_ref,)
            ).fetchone()
        elif driver_id:
            active_load = conn.execute(
                "SELECT * FROM shipments WHERE driver_id=? AND status NOT IN ('Delivered','Cancelled') "
                "ORDER BY etd DESC LIMIT 1", (driver_id,)
            ).fetchone()
        # All loads for this driver (loads tab)
        loads = []
        if driver_id:
            rows = conn.execute(
                "SELECT * FROM shipments WHERE driver_id=? ORDER BY etd DESC LIMIT 50", (driver_id,)
            ).fetchall()
            loads = [dict(r) for r in rows]
        if active_load:
            active_pod_url = url_for(
                "tms.capture_pod",
                ref=active_load["shipment_ref"],
                token=get_or_create_pod_token(active_load["shipment_ref"]),
            )
    finally:
        conn.close()

    return render_template("tms/driver_app.html",
        driver=dict(driver) if driver else None,
        active_load=dict(active_load) if active_load else None,
        loads=loads,
        driver_id=driver_id,
        shipment_ref=shipment_ref,
        tab=tab,
        flash_message=flash_message,
        flash_type=flash_type,
        active_pod_url=active_pod_url,
        status_saved=False,
        status_error=None,
    )


@tms.route('/driver-app/status', methods=['POST'])
def driver_app_status():
    """Driver submits a load status update from the PWA."""
    driver_id = request.form.get('driver_id', '').strip()
    shipment_ref = request.form.get('shipment_ref', '').strip()
    new_status = request.form.get('new_status', '').strip()
    location = request.form.get('location', '').strip()
    notes = request.form.get('notes', '').strip()

    if not shipment_ref or not new_status:
        return redirect(url_for('tms.driver_app', tab='status', driver_id=driver_id,
                                ref=shipment_ref, msg='Missing shipment or status.', msg_type='error'))
    try:
        import sqlite3
        conn = get_db()
        conn.row_factory = sqlite3.Row
        try:
            # Map driver status terms to TMS shipment statuses
            status_map = {
                'Picked Up': 'Picked Up', 'In Transit': 'In Transit',
                'At Delivery': 'At Delivery Location', 'Delivered': 'Delivered',
                'Delayed': 'Delayed', 'Issue': 'Exception',
            }
            tms_status = status_map.get(new_status, new_status)
            conn.execute(
                "UPDATE shipments SET status=?, updated_at=CURRENT_TIMESTAMP WHERE shipment_ref=?",
                (tms_status, shipment_ref)
            )
            # Log event
            shipment_row = conn.execute(
                "SELECT id FROM shipments WHERE shipment_ref=?", (shipment_ref,)
            ).fetchone()
            if shipment_row:
                desc = f"Driver update: {new_status}"
                if location:
                    desc += f" — {location}"
                if notes:
                    desc += f". {notes}"
                conn.execute(
                    "INSERT INTO shipment_events (shipment_id, event_type, description) VALUES (?,?,?)",
                    (shipment_row['id'], 'Driver Update', desc)
                )
            # Update driver location
            if driver_id and location:
                conn.execute(
                    "UPDATE drivers SET last_location=?, updated_at=CURRENT_TIMESTAMP WHERE id=?",
                    (location, driver_id)
                )
            conn.commit()
        finally:
            conn.close()
        # Notify dispatch
        try:
            notify_shipment_status_change(shipment_ref, tms_status)
        except Exception:
            pass
        return redirect(url_for('tms.driver_app', tab='status', driver_id=driver_id,
                                ref=shipment_ref, msg=f'{new_status} recorded.', msg_type='success'))
    except Exception as exc:
        return redirect(url_for('tms.driver_app', tab='status', driver_id=driver_id,
                                ref=shipment_ref, msg=str(exc), msg_type='error'))


# ── ELD / HOS Integration ────────────────────────────────────────────────────

@tms.route('/eld')
@tms_login_required
def eld_dashboard():
    connections = get_eld_connections()
    return render_template("tms/eld.html", connections=connections, providers=ELD_PROVIDERS)


@tms.route('/eld/sync/<provider>', methods=['POST'])
@tms_login_required
def eld_sync(provider):
    result = sync_eld_provider(provider)
    return jsonify(**result)


# ── Market Rate Benchmark ────────────────────────────────────────────────────

_STATE_NAMES = {
    "CA": "California", "TX": "Texas", "IL": "Illinois", "FL": "Florida",
    "NY": "New York", "OH": "Ohio", "GA": "Georgia", "WA": "Washington",
}

@tms.route('/market-rates')
@tms_login_required
def market_rates():
    import os as _os
    dat_configured = bool(_os.environ.get('DAT_API_KEY', ''))
    # Build common lanes list from BASE_REGION_RATES
    common_lanes = []
    seen = set()
    for (orig, dest), rate in BASE_REGION_RATES.items():
        if (orig, dest) in seen:
            continue
        seen.add((orig, dest))
        reverse = BASE_REGION_RATES.get((dest, orig))
        common_lanes.append({
            "origin": orig,
            "dest": dest,
            "origin_name": _STATE_NAMES.get(orig, orig),
            "dest_name": _STATE_NAMES.get(dest, dest),
            "rate": rate,
            "reverse_rate": reverse,
        })
    # Sort by origin then dest
    common_lanes.sort(key=lambda x: (x["origin"], x["dest"]))
    return render_template("tms/market_rates.html",
        dat_configured=dat_configured,
        common_lanes=common_lanes)


@tms.route('/market-rates/lookup')
@tms_login_required
def market_rate_lookup():
    origin = request.args.get('origin', '')
    dest = request.args.get('dest', '')
    equipment = request.args.get('equipment', 'Dry Van')
    miles = float(request.args.get('miles', 0) or 0)
    your_rate = float(request.args.get('your_rate', 0) or 0)
    result = get_market_rate_estimate(origin, dest, equipment, miles)
    if your_rate:
        result['comparison'] = compare_to_market(your_rate, result['rate_per_mile'])
    return jsonify(result)


# Marketplace

@tms.route('/marketplace')
@tms_login_required
def marketplace_index():
    q = (request.args.get('q') or '').strip()
    equipment_type = (request.args.get('equipment_type') or '').strip()
    origin_state = (request.args.get('origin_state') or '').strip().upper()
    dest_state = (request.args.get('dest_state') or '').strip().upper()

    carriers = search_carriers(
        equipment_type=equipment_type or None,
        origin_state=origin_state or None,
        dest_state=dest_state or None,
    )
    if q:
        search_value = q.lower()
        carriers = [
            carrier for carrier in carriers
            if search_value in (carrier.get('company_name', '') or '').lower()
            or search_value in (carrier.get('contact_name', '') or '').lower()
            or search_value in (carrier.get('contact_email', '') or '').lower()
            or search_value in (carrier.get('equipment_types', '') or '').lower()
            or search_value in (carrier.get('lanes_served', '') or '').lower()
        ]

    return render_template(
        "tms/marketplace.html",
        carriers=carriers,
        featured_carriers=get_featured_carriers(),
        equipment_options=get_marketplace_equipment_options(),
        state_options=get_marketplace_state_options(),
        filters={
            "q": q,
            "equipment_type": equipment_type,
            "origin_state": origin_state,
            "dest_state": dest_state,
        },
        search_active=bool(q or equipment_type or origin_state or dest_state),
    )


@tms.route('/marketplace/<int:carrier_id>')
@tms_login_required
def marketplace_carrier_detail(carrier_id):
    profile = get_carrier_profile(carrier_id)
    if not profile:
        flash("Carrier profile not found.", "danger")
        return redirect(url_for('tms.marketplace_index'))

    return render_template(
        "tms/marketplace_carrier.html",
        carrier=profile["carrier"],
        reviews=profile["reviews"],
        connection_status=profile["connection_status"],
        rating_breakdown=profile["rating_breakdown"],
    )


@tms.route('/marketplace/<int:carrier_id>/connect', methods=['POST'])
@tms_login_required
def marketplace_connect(carrier_id):
    next_url = request.form.get('next') or url_for('tms.marketplace_carrier_detail', carrier_id=carrier_id)
    if not next_url.startswith('/') or next_url.startswith('//'):
        next_url = url_for('tms.marketplace_carrier_detail', carrier_id=carrier_id)
    try:
        connection = marketplace_request_connection(carrier_id)
    except ValueError as exc:
        flash(str(exc), "danger")
        return redirect(next_url)

    if connection["status"] == "blocked":
        flash("This carrier connection is currently blocked.", "warning")
    else:
        flash("Connection request submitted.", "success")
    return redirect(next_url)


@tms.route('/marketplace/<int:carrier_id>/review', methods=['POST'])
@tms_login_required
def marketplace_review(carrier_id):
    next_url = request.form.get('next') or url_for('tms.marketplace_carrier_detail', carrier_id=carrier_id)
    if not next_url.startswith('/') or next_url.startswith('//'):
        next_url = url_for('tms.marketplace_carrier_detail', carrier_id=carrier_id)
    shipment_ref = request.form.get('shipment_ref', '')
    review_text = request.form.get('review_text', '')
    rating_raw = request.form.get('rating', '')
    try:
        marketplace_add_review(carrier_id, shipment_ref, int(rating_raw), review_text)
    except (TypeError, ValueError) as exc:
        flash(str(exc) if str(exc) else "Select a rating between 1 and 5.", "danger")
        return redirect(next_url)

    flash("Review added to the carrier profile.", "success")
    return redirect(next_url)


# ── SOC 2 / Compliance ────────────────────────────────────────────────────────

@tms.route('/compliance')
@tms_login_required
def soc2_dashboard():
    summary = get_soc2_summary()
    incidents = get_security_incidents()
    health = run_health_check()
    return render_template("tms/soc2_dashboard.html",
        summary=summary, incidents=incidents, health=health)

@tms.route('/compliance/audit-log')
@tms_login_required
def audit_log_view():
    user = request.args.get('user', '')
    resource = request.args.get('resource', '')
    action_filter = request.args.get('action', '')
    export = request.args.get('export', '')

    logs = get_audit_log(
        limit=200,
        user=user or None,
        resource_type=resource or None,
        action=action_filter or None
    )

    if export == 'csv':
        import io, csv as csv_mod
        output = io.StringIO()
        writer = csv_mod.writer(output)
        writer.writerow(['Timestamp', 'User ID', 'User Email', 'Action', 'Resource Type',
                         'Resource ID', 'Result', 'IP Address', 'Old Value', 'New Value'])
        for log in logs:
            writer.writerow([
                log.get('event_time', ''),
                log.get('user_id', ''),
                log.get('user_email', ''),
                log.get('action', ''),
                log.get('resource_type', ''),
                log.get('resource_id', ''),
                log.get('result', ''),
                log.get('ip_address', ''),
                log.get('old_value', ''),
                log.get('new_value', ''),
            ])
        resp = make_response(output.getvalue())
        resp.headers['Content-Type'] = 'text/csv'
        resp.headers['Content-Disposition'] = 'attachment; filename=audit_log.csv'
        return resp

    return render_template("tms/audit_log.html", logs=logs,
                           user=user, resource=resource, action=action_filter)

@tms.route('/compliance/privacy')
@tms_login_required
def privacy_requests_view():
    from datetime import datetime as _dt
    requests_list = get_privacy_requests()
    return render_template("tms/privacy_requests.html", requests=requests_list,
                           now_iso=_dt.now().isoformat())

@tms.route('/compliance/privacy/submit', methods=['POST'])
def privacy_request_submit():
    """Public endpoint — anyone can submit a data request."""
    data = request.form.to_dict()
    submit_privacy_request(
        data.get('request_type', 'access'),
        data.get('name', ''),
        data.get('email', ''),
        data.get('notes', '')
    )
    return jsonify(ok=True, message="Request received. We will respond within 30 days.")

@tms.route('/compliance/health')
@tms_login_required
def health_check_view():
    health = run_health_check()
    return jsonify(health)


# ── Admin Panel ────────────────────────────────────────────────────────────────

@tms.route('/admin')
@tms_roles_required("admin")
def admin_dashboard():
    summary = get_platform_revenue_summary()
    tenants = get_all_saas_tenants()
    return render_template("tms/admin_dashboard.html", summary=summary, tenants=tenants)

@tms.route('/admin/tenants/<tenant_id>')
@tms_roles_required("admin")
def admin_tenant_detail(tenant_id):
    tenant = get_saas_tenant(tenant_id)
    if not tenant:
        return "Not found", 404
    plans = get_all_plans()
    return render_template("tms/admin_tenant_detail.html", tenant=tenant, plans=plans)

@tms.route('/admin/tenants/new', methods=['POST'])
@tms_roles_required("admin")
def admin_tenant_new():
    data = request.form.to_dict()
    tid = create_saas_tenant(
        data.get('company_name', ''),
        data.get('owner_email', ''),
        data.get('owner_name', ''),
        data.get('phone', ''),
        int(data.get('trial_days', 14))
    )
    return jsonify(ok=True, tenant_id=tid)

@tms.route('/admin/tenants/<tenant_id>/addons/<plan_key>', methods=['POST'])
@tms_roles_required("admin")
def admin_addon_add(tenant_id, plan_key):
    add_tenant_addon(tenant_id, plan_key)
    return jsonify(ok=True)

@tms.route('/admin/tenants/<tenant_id>/addons/<plan_key>', methods=['DELETE'])
@tms_roles_required("admin")
def admin_addon_remove(tenant_id, plan_key):
    ok = remove_tenant_addon(tenant_id, plan_key)
    return jsonify(ok=ok)

@tms.route('/admin/tenants/<tenant_id>/suspend', methods=['POST'])
@tms_roles_required("admin")
def admin_tenant_suspend(tenant_id):
    suspend_saas_tenant(tenant_id)
    return jsonify(ok=True)

@tms.route('/admin/tenants/<tenant_id>/activate', methods=['POST'])
@tms_roles_required("admin")
def admin_tenant_activate(tenant_id):
    activate_saas_tenant(tenant_id)
    return jsonify(ok=True)


# ── Pricing page (public) ──────────────────────────────────────────────────────

@tms.route('/pricing')
def pricing_page():
    plans = get_all_plans()
    base = next((p for p in plans if p['is_base']), None)
    addons = [p for p in plans if p['is_addon']]
    categories = {}
    for p in addons:
        cat = p['category']
        if cat not in categories:
            categories[cat] = []
        categories[cat].append(p)
    return render_template("tms/pricing.html", base=base, categories=categories)


# ── Tenant self-service billing ────────────────────────────────────────────────

@tms.route('/settings/billing')
@tms_roles_required("admin")
def tenant_billing():
    tenant_id = session.get('tenant_id', 'default')
    plans = get_all_plans()
    active_addons = get_tenant_addons(tenant_id)
    active_keys = {a['plan_key'] for a in active_addons}
    monthly_total = get_tenant_monthly_total(tenant_id)
    return render_template("tms/tenant_billing.html",
        plans=plans, active_addons=active_addons,
        active_keys=active_keys, monthly_total=monthly_total)

@tms.route('/settings/billing/addons/<plan_key>', methods=['POST'])
@tms_roles_required("admin")
def tenant_addon_toggle(plan_key):
    tenant_id = session.get('tenant_id', 'default')
    action = request.get_json(silent=True) or {}
    if action.get('action') == 'add':
        add_tenant_addon(tenant_id, plan_key)
    else:
        remove_tenant_addon(tenant_id, plan_key)
    total = get_tenant_monthly_total(tenant_id)
    return jsonify(ok=True, monthly_total=total)


# ── Email Settings ─────────────────────────────────────────────────────────────

@tms.route('/settings/email', methods=['GET', 'POST'])
@tms_roles_required("admin")
def email_settings():
    saved = False
    error = None
    if request.method == 'POST':
        try:
            save_email_settings(request.form.to_dict())
            saved = True
        except Exception as exc:
            error = str(exc)
    cfg = get_email_settings()
    imap_ok = bool(cfg.get('imap_host') and cfg.get('imap_user'))
    smtp_ok = bool(cfg.get('smtp_host') and (cfg.get('smtp_user') or cfg.get('smtp_from')))
    return render_template(
        'tms/email_settings.html',
        cfg=cfg,
        saved=saved,
        error=error,
        smtp_ok=smtp_ok,
        imap_ok=imap_ok,
    )


@tms.route('/settings/email/test', methods=['POST'])
@tms_roles_required("admin")
def email_settings_test():
    """Quick SMTP connectivity test — tries to open a connection."""
    import smtplib, ssl as _ssl
    cfg = get_smtp_config()
    if not cfg['host']:
        return jsonify(ok=False, message='No SMTP host configured.')
    try:
        port = cfg['port']
        if cfg['use_ssl']:
            ctx = _ssl.create_default_context()
            with smtplib.SMTP_SSL(cfg['host'], port, context=ctx, timeout=8):
                pass
        else:
            with smtplib.SMTP(cfg['host'], port, timeout=8) as s:
                if cfg['use_tls']:
                    s.starttls()
                if cfg['user'] and cfg['password']:
                    s.login(cfg['user'], cfg['password'])
        return jsonify(ok=True, message=f"Connected to {cfg['host']}:{port} successfully.")
    except Exception as exc:
        return jsonify(ok=False, message=str(exc))


# ── Rate Gaps ──────────────────────────────────────────────────────────────────

@tms.route('/rate-gaps')
@tms_login_required
def rate_gaps():
    report = get_gap_report()
    parse_log = get_parse_log(limit=50)
    return render_template('tms/rate_gaps.html', report=report, parse_log=parse_log)


@tms.route('/rate-gaps/process', methods=['POST'])
@tms_login_required
def rate_gaps_process():
    """Manually trigger reply parsing."""
    results = process_pending_replies()
    applied = sum(1 for r in results if r['parse_status'] == 'applied')
    return jsonify(ok=True, processed=len(results), applied=applied)


# ── Load Board ─────────────────────────────────────────────────────────────────

@tms.route('/load-board')
@tms_login_required
def load_board():
    providers = lb_get_providers()
    postings = get_active_postings()
    from .tms_db import get_db
    import sqlite3
    conn = get_db()
    conn.row_factory = sqlite3.Row
    try:
        shipments = conn.execute(
            "SELECT shipment_ref, origin_port, destination_port FROM shipments "
            "WHERE status NOT IN ('Delivered','Cancelled') ORDER BY created_at DESC LIMIT 100"
        ).fetchall()
    finally:
        conn.close()
    return render_template('tms/load_board.html',
        providers=providers, postings=postings,
        shipments=[dict(s) for s in shipments],
        post_results=None)

@tms.route('/load-board/post', methods=['POST'])
@tms_login_required
def load_board_post():
    shipment_ref = request.form.get('shipment_ref', '').strip()
    boards = request.form.getlist('boards')
    results = lb_post_load(shipment_ref, boards) if shipment_ref and boards else {}
    providers = lb_get_providers()
    postings = get_active_postings()
    from .tms_db import get_db
    import sqlite3
    conn = get_db()
    conn.row_factory = sqlite3.Row
    try:
        shipments = conn.execute(
            "SELECT shipment_ref, origin_port, destination_port FROM shipments "
            "WHERE status NOT IN ('Delivered','Cancelled') ORDER BY created_at DESC LIMIT 100"
        ).fetchall()
    finally:
        conn.close()
    return render_template('tms/load_board.html',
        providers=providers, postings=postings,
        shipments=[dict(s) for s in shipments],
        post_results=results)

@tms.route('/load-board/delete/<int:posting_id>', methods=['POST'])
@tms_login_required
def load_board_delete(posting_id):
    lb_delete_posting(posting_id)
    return redirect(url_for('tms.load_board'))

@tms.route('/load-board/settings', methods=['GET', 'POST'])
@tms_login_required
def load_board_settings():
    saved = False
    if request.method == 'POST':
        save_board_settings(request.form.to_dict())
        saved = True
    providers = lb_get_providers()
    settings = get_board_settings()
    return render_template('tms/load_board_settings.html',
        providers=providers, settings=settings, saved=saved)


# -- Cold Chain ---------------------------------------------------------------

@tms.route('/cold-chain')
@tms_login_required
def cold_chain():
    return render_template('tms/cold_chain.html', **get_cold_chain_dashboard())


@tms.route('/cold-chain/<ref>')
@tms_login_required
def cold_chain_detail(ref):
    try:
        hours = int(request.args.get('hours', 72) or 72)
    except ValueError:
        hours = 72

    readings = get_cold_chain_readings(ref, hours=max(1, min(hours, 24 * 14)))
    config = get_shipment_config(ref) or {}
    latest_reading = readings[-1] if readings else None
    excursions = get_cold_chain_excursions(ref)

    latest_temp = latest_reading.get('temperature_c') if latest_reading else None
    gauge_values = [reading['temperature_c'] for reading in readings if reading.get('temperature_c') is not None]
    if config.get('min_temp_c') is not None:
        gauge_values.append(config['min_temp_c'])
    if config.get('max_temp_c') is not None:
        gauge_values.append(config['max_temp_c'])

    if gauge_values:
        gauge_min = min(gauge_values)
        gauge_max = max(gauge_values)
        if gauge_min == gauge_max:
            gauge_min -= 1
            gauge_max += 1
    else:
        gauge_min = -10
        gauge_max = 10

    if latest_temp is None:
        gauge_pct = 0
    else:
        gauge_pct = ((latest_temp - gauge_min) / (gauge_max - gauge_min)) * 100
        gauge_pct = max(0, min(100, gauge_pct))

    current_status_class = 'secondary'
    current_status_label = 'Awaiting readings'
    if latest_reading:
        current_status_class = latest_reading.get('status_class', 'secondary')
        current_status_label = latest_reading.get('status_label', 'Awaiting readings')

    ingest_token = ""
    config_provider = config.get("provider") or (latest_reading.get("provider") if latest_reading else "")
    config_sensor_id = config.get("sensor_id") or (latest_reading.get("sensor_id") if latest_reading else "")
    if config_provider and config_sensor_id:
        try:
            ingest_token = _create_cold_chain_ingest_token(ref, config_provider, config_sensor_id)
        except ValueError:
            ingest_token = ""

    return render_template(
        'tms/cold_chain_detail.html',
        shipment_ref=ref,
        config=config,
        readings=readings,
        latest_reading=latest_reading,
        current_temp_display=(latest_reading.get('temperature_display') or 'No data') if latest_reading else 'No data',
        current_humidity_display=(latest_reading.get('humidity_display') or '-') if latest_reading else '-',
        current_location_display=(latest_reading.get('location_display') or 'Unspecified') if latest_reading else 'Unspecified',
        current_provider_name=(latest_reading.get('provider_name') or config.get('provider_name') or 'Unassigned') if latest_reading else (config.get('provider_name') or 'Unassigned'),
        current_sensor_id=(latest_reading.get('sensor_id') or config.get('sensor_id') or 'Unassigned') if latest_reading else (config.get('sensor_id') or 'Unassigned'),
        current_status_class=current_status_class,
        current_status_label=current_status_label,
        gauge_pct=round(gauge_pct, 1),
        gauge_min=round(gauge_min, 1),
        gauge_max=round(gauge_max, 1),
        range_label=config.get('range_label', 'No thresholds configured'),
        hours=hours,
        excursion_count=len(excursions),
        ingest_token=ingest_token,
        ingest_endpoint=url_for('tms.cold_chain_reading'),
    )


@tms.route('/cold-chain/<ref>/config', methods=['POST'])
@tms_login_required
def cold_chain_config(ref):
    try:
        configure_shipment(
            shipment_ref=ref,
            min_temp=request.form.get('min_temp_c'),
            max_temp=request.form.get('max_temp_c'),
            min_humidity=request.form.get('min_humidity'),
            max_humidity=request.form.get('max_humidity'),
            alert_email=request.form.get('alert_email'),
            provider=request.form.get('provider'),
            sensor_id=request.form.get('sensor_id'),
        )
        flash(f'Cold chain monitoring saved for {ref}.', 'success')
    except ValueError as exc:
        flash(str(exc), 'danger')
    return redirect(url_for('tms.cold_chain_detail', ref=ref))


@tms.route('/cold-chain/reading', methods=['POST'])
def cold_chain_reading():
    payload = request.get_json(silent=True)
    if not isinstance(payload, dict):
        return jsonify({'ok': False, 'error': 'JSON body is required.'}), 400

    shipment_ref = _normalize_text(payload.get('shipment_ref'))
    sensor_id = _normalize_text(payload.get('sensor_id'))
    provider = _normalize_text(payload.get('provider'))
    ingest_token = (
        _normalize_text(payload.get('ingest_token'))
        or _normalize_text(request.headers.get('X-Cold-Chain-Token'))
    )
    config = get_shipment_config(shipment_ref) or {}
    expected_provider = _normalize_text(config.get('provider'))
    expected_sensor_id = _normalize_text(config.get('sensor_id'))
    if (
        not expected_provider
        or not expected_sensor_id
        or provider != expected_provider
        or sensor_id != expected_sensor_id
        or not _cold_chain_ingest_token_is_valid(ingest_token, shipment_ref, provider, sensor_id)
    ):
        return jsonify({'ok': False, 'error': 'A valid cold chain ingest token is required.'}), 403

    try:
        reading = ingest_reading(
            shipment_ref=shipment_ref,
            sensor_id=sensor_id,
            provider=provider,
            temp_c=payload.get('temperature_c', payload.get('temp_c')),
            humidity=payload.get('humidity_pct', payload.get('humidity')),
            lat=payload.get('lat'),
            lon=payload.get('lon'),
            location=payload.get('location_label', payload.get('location')),
        )
    except ValueError as exc:
        return jsonify({'ok': False, 'error': str(exc)}), 400

    return jsonify({'ok': True, 'reading': reading, 'alert_triggered': bool(reading.get('alert_triggered'))}), 201


# ── Accounting ─────────────────────────────────────────────────────────────────

@tms.route('/accounting')
@tms_login_required
def accounting():
    from .auto_invoice import get_all_invoices
    providers = acct_get_providers()
    invoices = get_all_invoices()
    sync_log = get_sync_log(limit=50)
    return render_template('tms/accounting.html',
        providers=providers, invoices=invoices,
        sync_log=sync_log, push_result=None)

@tms.route('/accounting/push', methods=['POST'])
@tms_login_required
def accounting_push():
    invoice_id = request.form.get('invoice_id', '').strip()
    provider_key = request.form.get('provider_key', '').strip()
    result = push_invoice(invoice_id, provider_key) if invoice_id and provider_key else \
        {'ok': False, 'error': 'Missing invoice or provider'}
    from .auto_invoice import get_all_invoices
    providers = acct_get_providers()
    invoices = get_all_invoices()
    sync_log = get_sync_log(limit=50)
    push_result = {
        'ok': result.get('ok'),
        'message': f"Pushed to {provider_key} — external ID: {result.get('external_id') or 'n/a'}"
            if result.get('ok') else result.get('error', 'Failed')
    }
    return render_template('tms/accounting.html',
        providers=providers, invoices=invoices,
        sync_log=sync_log, push_result=push_result)

@tms.route('/accounting/test/<provider_key>', methods=['POST'])
@tms_login_required
def accounting_test(provider_key):
    result = acct_test(provider_key)
    return jsonify(ok=result['ok'], message=result['message'])

@tms.route('/accounting/settings', methods=['GET', 'POST'])
@tms_login_required
def accounting_settings():
    saved = False
    if request.method == 'POST':
        save_accounting_settings(request.form.to_dict())
        saved = True
    providers = acct_get_providers()
    settings = get_accounting_settings()
    return render_template('tms/accounting_settings.html',
        providers=providers, settings=settings, saved=saved)


# ── AI Insights ─────────────────────────────────────────────────────────────────

@tms.route('/ai-insights')
@tms_login_required
def ai_insights():
    data = get_ai_dashboard()
    return render_template('tms/ai_insights.html', **data)


@tms.route('/ai-insights/predict-eta')
@tms_login_required
def ai_predict_eta():
    origin = request.args.get('origin', '')
    destination = request.args.get('destination', '')
    etd = request.args.get('etd', '')
    carrier = request.args.get('carrier', '') or None
    if not (origin and destination and etd):
        return jsonify(error='origin, destination, etd required'), 400
    return jsonify(predict_eta(origin, destination, etd, carrier))


@tms.route('/ai-insights/lane-score')
@tms_login_required
def ai_lane_score():
    origin = request.args.get('origin', '')
    destination = request.args.get('destination', '')
    if not (origin and destination):
        return jsonify(error='origin and destination required'), 400
    return jsonify(score_lane(origin, destination))


@tms.route('/ai-insights/shipment-risk/<int:shipment_id>')
@tms_login_required
def ai_shipment_risk(shipment_id):
    return jsonify(get_late_risk(shipment_id))


# ── Benchmarking ──────────────────────────────────────────────────────────────

@tms.route('/benchmarking')
@tms_login_required
def benchmarking():
    from .tms_db import get_db as _get_db
    data = get_benchmark_dashboard()
    carriers = _get_db().execute(
        "SELECT id, name FROM tms_carriers WHERE active=1 ORDER BY name"
    ).fetchall()
    return render_template('tms/benchmarking.html', **data, carriers=carriers)


@tms.route('/benchmarking/lane')
@tms_login_required
def benchmarking_lane():
    origin = request.args.get('origin', '')
    destination = request.args.get('destination', '')
    if not (origin and destination):
        return jsonify(error='origin and destination required'), 400
    return jsonify(benchmark_lane(origin, destination))


@tms.route('/benchmarking/carrier/<int:carrier_id>')
@tms_login_required
def benchmarking_carrier(carrier_id):
    data = get_carrier_rate_comparison(carrier_id)
    return render_template('tms/benchmarking_carrier.html', **data)


# ── Live Map ──────────────────────────────────────────────────────────────────

@tms.route('/live-map')
@tms_login_required
def live_map():
    shipments = get_live_shipments()
    summary   = get_map_summary()
    geofences = get_geofences()
    events    = get_geofence_events(20)
    return render_template('tms/live_map.html',
        shipments=shipments, summary=summary,
        geofences=geofences, events=events)

@tms.route('/live-map/data')
@tms_login_required
def live_map_data():
    return jsonify(shipments=get_live_shipments(), summary=get_map_summary())

@tms.route('/live-map/trail/<ref>')
@tms_login_required
def live_map_trail(ref):
    hours = int(request.args.get('hours', 24))
    return jsonify(trail=get_shipment_trail(ref, hours))

@tms.route('/live-map/ping', methods=['POST'])
@tms_login_required
def live_map_ping():
    d = request.get_json() or request.form
    ref = d.get('shipment_ref', '')
    try:
        lat, lon = float(d.get('lat')), float(d.get('lon'))
    except (TypeError, ValueError):
        return jsonify(error='lat/lon required'), 400
    triggered = ingest_ping(ref, lat, lon,
        speed_mph=d.get('speed_mph'), heading=d.get('heading'),
        location_label=d.get('location_label'))
    return jsonify(ok=True, geofence_events=triggered)

@tms.route('/live-map/geofence', methods=['POST'])
@tms_login_required
def live_map_geofence_create():
    f = request.form
    gid = create_geofence(
        f.get('name',''), float(f.get('lat',0)), float(f.get('lon',0)),
        float(f.get('radius_miles', 0.5)), f.get('fence_type','poi'),
        f.get('shipment_ref') or None,
        f.get('alert_entry') == 'on', f.get('alert_exit') == 'on'
    )
    return redirect(url_for('tms.live_map'))

@tms.route('/live-map/geofence/<int:fence_id>/delete', methods=['POST'])
@tms_login_required
def live_map_geofence_delete(fence_id):
    delete_geofence(fence_id)
    return redirect(url_for('tms.live_map'))


# ── Driver Pay & Settlement ───────────────────────────────────────────────────

@tms.route('/driver-pay')
@tms_login_required
def driver_pay():
    from .tms_db import get_db as _gdb
    drivers = _gdb().execute(
        "SELECT id, name FROM drivers WHERE status='Active' ORDER BY name"
    ).fetchall()
    settlements = get_settlements()
    pending = [s for s in settlements if s['status'] == 'pending']
    paid_mtd = sum(s.get('net_pay') or 0 for s in settlements if s['status'] == 'paid')
    total_pending = sum(s.get('net_pay') or 0 for s in pending)
    return render_template('tms/driver_pay.html',
        drivers=drivers, settlements=settlements, pending=pending,
        total_pending=total_pending, pending_count=len(pending), paid_mtd=paid_mtd)

@tms.route('/driver-pay/<int:driver_id>/structure', methods=['GET', 'POST'])
@tms_login_required
def driver_pay_structure(driver_id):
    from .tms_db import get_db as _gdb
    driver = _gdb().execute("SELECT * FROM drivers WHERE id=?", (driver_id,)).fetchone()
    if not driver:
        return redirect(url_for('tms.driver_pay'))
    if request.method == 'POST':
        save_pay_structure(driver_id, request.form.to_dict())
        flash('Pay structure saved.', 'success')
        return redirect(url_for('tms.driver_pay'))
    structure = get_pay_structure(driver_id)
    return render_template('tms/driver_pay_structure.html',
        driver=driver, structure=structure)

@tms.route('/driver-pay/<int:driver_id>/calculate', methods=['POST'])
@tms_login_required
def driver_pay_calculate(driver_id):
    start = request.form.get('period_start', '')
    end   = request.form.get('period_end', '')
    notes = request.form.get('notes', '')
    result = create_settlement(driver_id, start, end, notes)
    if 'error' in result:
        flash(result['error'], 'danger')
        return redirect(url_for('tms.driver_pay'))
    flash(f"Settlement {result['settlement_ref']} created — ${result['net_pay']:,.2f} net pay.", 'success')
    return redirect(url_for('tms.driver_pay'))

@tms.route('/driver-pay/settlement/<int:settlement_id>')
@tms_login_required
def driver_pay_settlement(settlement_id):
    s = get_settlement(settlement_id)
    if not s:
        return redirect(url_for('tms.driver_pay'))
    return render_template('tms/driver_settlement.html', settlement=s)

@tms.route('/driver-pay/settlement/<int:settlement_id>/approve', methods=['POST'])
@tms_login_required
def driver_pay_approve(settlement_id):
    approve_settlement(settlement_id, session.get('username', 'dispatcher'))
    flash('Settlement approved.', 'success')
    return redirect(url_for('tms.driver_pay_settlement', settlement_id=settlement_id))

@tms.route('/driver-pay/settlement/<int:settlement_id>/paid', methods=['POST'])
@tms_login_required
def driver_pay_mark_paid(settlement_id):
    mark_paid(settlement_id)
    flash('Settlement marked as paid.', 'success')
    return redirect(url_for('tms.driver_pay'))


# ── Accessorials ──────────────────────────────────────────────────────────────

@tms.route('/accessorials')
@tms_login_required
def accessorials():
    data = get_accessorial_dashboard()
    return render_template('tms/accessorials.html', **data)

@tms.route('/accessorials/charge/<ref>', methods=['POST'])
@tms_login_required
def accessorials_add_charge(ref):
    f = request.form
    add_charge(ref, f.get('charge_type','custom'),
               float(f.get('rate', 0)), float(f.get('quantity', 1)),
               f.get('description'), f.get('billable_to','customer'), f.get('notes'))
    flash('Charge added.', 'success')
    return redirect(request.referrer or url_for('tms.accessorials'))

@tms.route('/accessorials/charge/<int:charge_id>/approve', methods=['POST'])
@tms_login_required
def accessorials_approve(charge_id):
    approve_charge(charge_id, session.get('username', 'dispatcher'))
    return redirect(url_for('tms.accessorials'))

@tms.route('/accessorials/charge/<int:charge_id>/delete', methods=['POST'])
@tms_login_required
def accessorials_delete(charge_id):
    delete_charge(charge_id)
    return redirect(url_for('tms.accessorials'))

@tms.route('/accessorials/detention/start', methods=['POST'])
@tms_login_required
def accessorials_detention_start():
    f = request.form
    tid = start_detention_timer(
        f.get('shipment_ref',''), f.get('location_type','delivery'),
        float(f.get('free_hours', 2.0)), float(f.get('rate_per_hour', 75.0))
    )
    flash(f'Detention timer started (ID #{tid}).', 'success')
    return redirect(url_for('tms.accessorials'))

@tms.route('/accessorials/detention/<int:timer_id>/stop', methods=['POST'])
@tms_login_required
def accessorials_detention_stop(timer_id):
    result = stop_detention_timer(timer_id)
    if result and result['charge_created']:
        flash(f"Detention stopped — ${result['amount']:,.2f} charge created ({result['billable_hours']:.1f} hrs).", 'success')
    else:
        flash('Detention stopped — within free time, no charge.', 'info')
    return redirect(url_for('tms.accessorials'))

@tms.route('/accessorials/charge/new', methods=['POST'])
@tms_login_required
def accessorials_add_charge_new():
    f = request.form
    add_charge(f.get('shipment_ref',''), f.get('charge_type','custom'),
               float(f.get('amount', 0)), float(f.get('quantity', 1)),
               f.get('charge_type','').replace('_',' ').title(), 'customer', f.get('notes',''))
    flash('Charge added.', 'success')
    return redirect(url_for('tms.accessorials'))

@tms.route('/accessorials/<ref>')
@tms_login_required
def accessorials_shipment(ref):
    summary = get_charges_summary(ref)
    return render_template('tms/accessorials_shipment.html',
        shipment_ref=ref, **summary, accessorial_types=ACCESSORIAL_TYPES)


# ── DG / Hazmat ───────────────────────────────────────────────────────────────

@tms.route('/hazmat')
@tms_login_required
def hazmat():
    init_dg_db()
    data = get_dg_dashboard()
    return render_template('tms/hazmat.html', **data)

@tms.route('/hazmat/search')
@tms_login_required
def hazmat_search():
    q = request.args.get('q', '')
    return jsonify(search_un(q) if q else [])

@tms.route('/hazmat/declaration/new', methods=['GET', 'POST'])
@tms_login_required
def hazmat_new_declaration():
    if request.method == 'POST':
        f = request.form
        ref = create_declaration(
            f.get('shipment_ref',''), f.get('un_number',''),
            float(f.get('quantity',0)), f.get('unit','kg'),
            f.get('transport_mode','road'), f.get('inner_pkg',''), f.get('outer_pkg',''),
            f.get('shipper',''), f.get('consignee',''),
            f.get('emergency_contact',''), f.get('emergency_phone',''),
            session.get('username','dispatcher')
        )
        flash(f'DG Declaration {ref} created.', 'success')
        return redirect(url_for('tms.hazmat'))
    from .tms_db import get_db as _gdb
    shipments = _gdb().execute("SELECT shipment_ref FROM shipments WHERE status NOT IN ('Delivered','Cancelled') ORDER BY created_at DESC LIMIT 100").fetchall()
    return render_template('tms/hazmat_new.html', shipments=shipments, hazmat_classes=HAZMAT_CLASSES)

@tms.route('/hazmat/declaration/<int:decl_id>/validate', methods=['POST'])
@tms_login_required
def hazmat_validate(decl_id):
    result = validate_declaration(decl_id)
    flash(('Valid declaration.' if result['valid'] else 'Validation failed: ' + '; '.join(result['notes'])),
          'success' if result['valid'] else 'danger')
    return redirect(url_for('tms.hazmat'))


# ── DVIR / Fleet Maintenance ──────────────────────────────────────────────────

@tms.route('/fleet-health')
@tms_login_required
def fleet_health():
    from datetime import date
    data = get_fleet_health_dashboard()
    return render_template('tms/fleet_health.html', **data, now_date=date.today().isoformat())

@tms.route('/fleet-health/dvir/new', methods=['GET', 'POST'])
@tms_login_required
def fleet_health_dvir_new():
    from .tms_db import get_db as _gdb
    if request.method == 'POST':
        f = request.form
        defects = json.loads(f.get('defects_json', '[]'))
        ref = create_dvir(
            int(f.get('vehicle_id',0)), int(f.get('driver_id',0)),
            f.get('inspection_type','pre_trip'),
            float(f.get('odometer',0)) if f.get('odometer') else None,
            f.get('location',''), defects
        )
        flash(f'DVIR {ref} submitted.', 'success')
        return redirect(url_for('tms.fleet_health'))
    db = _gdb()
    vehicles = db.execute("SELECT id, truck_number FROM vehicles ORDER BY truck_number").fetchall()
    drivers = db.execute("SELECT id, name FROM drivers WHERE status='Active' ORDER BY name").fetchall()
    return render_template('tms/dvir_new.html', vehicles=vehicles, drivers=drivers,
                           inspection_items=INSPECTION_ITEMS)

@tms.route('/fleet-health/dvir/<int:report_id>/certify', methods=['POST'])
@tms_login_required
def fleet_health_certify(report_id):
    f = request.form
    certify_dvir(report_id, f.get('mechanic_signature',''), f.get('notes',''),
                 f.get('certified_safe') == 'on')
    flash('DVIR certified.', 'success')
    return redirect(url_for('tms.fleet_health'))

@tms.route('/fleet-health/maintenance/new', methods=['POST'])
@tms_login_required
def fleet_health_maint_new():
    f = request.form
    create_maintenance_schedule(
        int(f.get('vehicle_id',0)), f.get('maintenance_type',''),
        float(f.get('interval_miles',0)) if f.get('interval_miles') else None,
        int(f.get('interval_days',0)) if f.get('interval_days') else None,
        f.get('last_done') or None, float(f.get('last_odometer',0)) if f.get('last_odometer') else None,
        f.get('vendor','')
    )
    flash('Maintenance schedule added.', 'success')
    return redirect(url_for('tms.fleet_health'))

@tms.route('/fleet-health/work-order/<int:wo_id>/close', methods=['POST'])
@tms_login_required
def fleet_health_wo_close(wo_id):
    f = request.form
    close_work_order(wo_id, float(f.get('cost',0)), float(f.get('parts_cost',0)),
                     float(f.get('labor_cost',0)), f.get('notes',''))
    flash('Work order closed.', 'success')
    return redirect(url_for('tms.fleet_health'))


# ── Workflow Automation ───────────────────────────────────────────────────────

@tms.route('/workflows')
@tms_login_required
def workflows():
    data = get_workflow_dashboard()
    return render_template('tms/workflows.html', **data)

@tms.route('/workflows/create', methods=['POST'])
@tms_login_required
def workflows_create():
    f = request.form
    # Build conditions from individual form fields
    cond_type = f.get('cond_type', 'always')
    cond_value = f.get('cond_value', '')
    conditions = [{'type': cond_type, 'value': cond_value}] if cond_type != 'always' else []
    # Build action from form fields
    atype = f.get('action_type', '')
    param_map = {'to_email': f.get('action_param1',''), 'subject': f.get('action_param2',''),
                 'body': f.get('action_param3',''), 'new_status': f.get('action_param1',''),
                 'task_title': f.get('action_param1',''), 'assigned_to': f.get('action_param2',''),
                 'event_description': f.get('action_param1',''), 'webhook_url': f.get('action_param1','')}
    actions = [{'type': atype, 'params': param_map}] if atype else []
    create_rule(f.get('name',''), f.get('trigger',''), conditions, actions,
                session.get('username','dispatcher'))
    flash('Workflow rule created.', 'success')
    return redirect(url_for('tms.workflows'))

@tms.route('/workflows/<int:rule_id>/toggle', methods=['POST'])
@tms_login_required
def workflows_toggle(rule_id):
    active = request.form.get('active') == '1'
    toggle_rule(rule_id, active)
    return redirect(url_for('tms.workflows'))

@tms.route('/workflows/<int:rule_id>/delete', methods=['POST'])
@tms_login_required
def workflows_delete(rule_id):
    delete_rule(rule_id)
    flash('Rule deleted.', 'success')
    return redirect(url_for('tms.workflows'))


# ── White-Label / Branding ────────────────────────────────────────────────────

@tms.route('/settings/branding', methods=['GET', 'POST'])
@tms_login_required
def settings_branding():
    tenant_id = session.get('tenant_id', 'default')
    if request.method == 'POST':
        save_branding(tenant_id, request.form.to_dict())
        flash('Branding saved.', 'success')
    branding = get_branding(tenant_id)
    tenant_list = get_all_tenant_brandings()
    return render_template('tms/settings_branding.html', branding=branding, tenant_list=tenant_list)

@tms.route('/brand.css')
def brand_css():
    tenant_id = 'default'
    css = get_css_vars(tenant_id)
    return css, 200, {'Content-Type': 'text/css'}
