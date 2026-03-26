import contextvars
import re
import sqlite3
from contextlib import contextmanager
from dataclasses import dataclass


DEFAULT_TENANT_ID = "tenant-default"
DEFAULT_TENANT_NAME = "Default Tenant"
PLAN_OPTIONS = ("starter", "pro", "enterprise")
TENANT_STATUS_OPTIONS = ("active", "suspended", "deleted")
TENANT_SCOPED_TABLES = {
    "api_keys",
    "audit_log",
    "carrier_invoices",
    "contract_rates",
    "customs_declarations",
    "customer_invoices",
    "dock_appointments",
    "docks",
    "edi_partners",
    "drivers",
    "duty_logs",
    "edi_transactions",
    "freight_claims",
    "intake_documents",
    "load_shipments",
    "loadboard_posts",
    "loads",
    "location_geocodes",
    "pod_records",
    "portal_tokens",
    "quotes",
    "shipment_events",
    "shipments",
    "tender_responses",
    "tenders",
    "tenants",
    "tms_carriers",
    "tms_documents",
    "tms_integrations",
    "tms_lanes",
    "tms_settings",
    "tracking_driver_tokens",
    "tracking_pings",
    "vehicles",
}
_TENANTABLE_SQL_PREFIXES = ("SELECT", "INSERT", "UPDATE", "DELETE")
_SQL_KEYWORDS = {
    "ALL",
    "AND",
    "AS",
    "BY",
    "CASE",
    "CROSS",
    "DELETE",
    "DISTINCT",
    "ELSE",
    "END",
    "FROM",
    "FULL",
    "GROUP",
    "HAVING",
    "INNER",
    "INSERT",
    "INTO",
    "JOIN",
    "LEFT",
    "LIMIT",
    "OFFSET",
    "ON",
    "OR",
    "ORDER",
    "OUTER",
    "RETURNING",
    "RIGHT",
    "SELECT",
    "SET",
    "UNION",
    "UPDATE",
    "VALUES",
    "WHEN",
    "WHERE",
    "WINDOW",
}

_current_tenant = contextvars.ContextVar("tms_current_tenant", default=DEFAULT_TENANT_ID)
_current_actor = contextvars.ContextVar("tms_audit_actor", default="system")
_current_ip = contextvars.ContextVar("tms_audit_ip", default="")
_scope_disabled = contextvars.ContextVar("tms_scope_disabled", default=False)


@dataclass(frozen=True)
class SqlToken:
    text: str
    upper: str
    start: int
    end: int
    depth: int


def normalize_tenant_id(value, fallback=DEFAULT_TENANT_ID):
    raw_value = (value or "").strip().lower()
    clean_value = re.sub(r"[^a-z0-9]+", "-", raw_value).strip("-")
    return clean_value or fallback


def get_current_tenant():
    return normalize_tenant_id(_current_tenant.get())


def get_current_actor():
    actor = (_current_actor.get() or "").strip()
    return actor or "system"


def get_current_ip():
    return (_current_ip.get() or "").strip()


def is_scope_disabled():
    return bool(_scope_disabled.get())


@contextmanager
def tenant_context(*, tenant_id=None, actor=None, ip=None, disable_scope=None):
    tokens = []
    if tenant_id is not None:
        tokens.append((_current_tenant, _current_tenant.set(normalize_tenant_id(tenant_id))))
    if actor is not None:
        tokens.append((_current_actor, _current_actor.set((actor or "").strip() or "system")))
    if ip is not None:
        tokens.append((_current_ip, _current_ip.set((ip or "").strip())))
    if disable_scope is not None:
        tokens.append((_scope_disabled, _scope_disabled.set(bool(disable_scope))))
    try:
        yield
    finally:
        for var, token in reversed(tokens):
            var.reset(token)


@contextmanager
def disabled_tenant_scope():
    with tenant_context(disable_scope=True):
        yield


class TenantAwareConnection(sqlite3.Connection):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.create_function("current_tenant", 0, get_current_tenant)
        self.create_function("current_audit_actor", 0, get_current_actor)
        self.create_function("current_audit_ip", 0, get_current_ip)
        self.create_function("tenant_scope_disabled", 0, lambda: 1 if is_scope_disabled() else 0)

    def cursor(self, factory=None):
        return super().cursor(factory or TenantAwareCursor)

    def execute(self, sql, parameters=(), /):
        return self.cursor().execute(sql, parameters)

    def executemany(self, sql, seq_of_parameters, /):
        return self.cursor().executemany(sql, seq_of_parameters)


class TenantAwareCursor(sqlite3.Cursor):
    def execute(self, sql, parameters=(), /):
        rewritten = rewrite_sql(sql)
        return super().execute(rewritten, parameters)

    def executemany(self, sql, seq_of_parameters, /):
        rewritten = rewrite_sql(sql)
        return super().executemany(rewritten, seq_of_parameters)


def rewrite_sql(sql):
    if not isinstance(sql, str):
        return sql
    if is_scope_disabled():
        return sql

    trimmed = sql.lstrip()
    if not trimmed:
        return sql

    prefix = trimmed.split(None, 1)[0].upper()
    if prefix not in _TENANTABLE_SQL_PREFIXES:
        return sql

    sql = _rewrite_parenthesized_subqueries(sql)
    tokens = _tokenize_sql(sql)
    if not tokens:
        return sql

    prefix = tokens[0].upper
    if prefix == "SELECT":
        return _rewrite_select(sql, tokens)
    if prefix == "UPDATE":
        return _rewrite_update(sql, tokens)
    if prefix == "DELETE":
        return _rewrite_delete(sql, tokens)
    if prefix == "INSERT":
        return _rewrite_insert(sql, tokens)
    return sql


def _rewrite_parenthesized_subqueries(sql):
    result = []
    index = 0
    while index < len(sql):
        char = sql[index]
        if char in ("'", '"'):
            end = _consume_quoted(sql, index)
            result.append(sql[index:end])
            index = end
            continue
        if sql.startswith("--", index):
            end = sql.find("\n", index)
            if end == -1:
                end = len(sql)
            result.append(sql[index:end])
            index = end
            continue
        if sql.startswith("/*", index):
            end = sql.find("*/", index + 2)
            if end == -1:
                end = len(sql)
            else:
                end += 2
            result.append(sql[index:end])
            index = end
            continue
        if char == "(":
            close_index = _find_matching_paren(sql, index)
            if close_index == -1:
                result.append(char)
                index += 1
                continue
            inner = sql[index + 1:close_index]
            rewritten_inner = inner
            if _starts_with_rewritable_statement(inner):
                rewritten_inner = rewrite_sql(inner)
            else:
                rewritten_inner = _rewrite_parenthesized_subqueries(inner)
            result.append(f"({rewritten_inner})")
            index = close_index + 1
            continue
        result.append(char)
        index += 1
    return "".join(result)


def _starts_with_rewritable_statement(sql):
    trimmed = sql.lstrip()
    if not trimmed:
        return False
    prefix = trimmed.split(None, 1)[0].upper()
    return prefix in _TENANTABLE_SQL_PREFIXES


def _tokenize_sql(sql):
    tokens = []
    index = 0
    depth = 0
    while index < len(sql):
        char = sql[index]
        if char.isspace():
            index += 1
            continue
        if sql.startswith("--", index):
            end = sql.find("\n", index)
            index = len(sql) if end == -1 else end
            continue
        if sql.startswith("/*", index):
            end = sql.find("*/", index + 2)
            index = len(sql) if end == -1 else end + 2
            continue
        if char in ("'", '"'):
            start = index
            index = _consume_quoted(sql, index)
            text = sql[start:index]
            tokens.append(SqlToken(text=text, upper=text.upper(), start=start, end=index, depth=depth))
            continue
        if char == "(":
            tokens.append(SqlToken(text=char, upper=char, start=index, end=index + 1, depth=depth))
            depth += 1
            index += 1
            continue
        if char == ")":
            depth = max(0, depth - 1)
            tokens.append(SqlToken(text=char, upper=char, start=index, end=index + 1, depth=depth))
            index += 1
            continue
        if char in ",;":
            tokens.append(SqlToken(text=char, upper=char, start=index, end=index + 1, depth=depth))
            index += 1
            continue
        start = index
        while index < len(sql):
            current = sql[index]
            if current.isspace() or current in "',;()":
                break
            if sql.startswith("--", index) or sql.startswith("/*", index):
                break
            index += 1
        text = sql[start:index]
        tokens.append(SqlToken(text=text, upper=text.upper(), start=start, end=index, depth=depth))
    return tokens


def _consume_quoted(sql, index):
    quote = sql[index]
    index += 1
    while index < len(sql):
        if sql[index] == quote:
            index += 1
            if index < len(sql) and sql[index] == quote:
                index += 1
                continue
            break
        index += 1
    return index


def _find_matching_paren(sql, open_index):
    depth = 0
    index = open_index
    while index < len(sql):
        char = sql[index]
        if char in ("'", '"'):
            index = _consume_quoted(sql, index)
            continue
        if sql.startswith("--", index):
            end = sql.find("\n", index)
            index = len(sql) if end == -1 else end
            continue
        if sql.startswith("/*", index):
            end = sql.find("*/", index + 2)
            index = len(sql) if end == -1 else end + 2
            continue
        if char == "(":
            depth += 1
        elif char == ")":
            depth -= 1
            if depth == 0:
                return index
        index += 1
    return -1


def _next_token(tokens, start_index):
    for index in range(start_index, len(tokens)):
        token = tokens[index]
        if token.text:
            return index, token
    return None, None


def _normalize_identifier(identifier):
    token = identifier.strip()
    if "." in token:
        token = token.split(".")[-1]
    return token.strip('"[]`').lower()


def _is_keyword(token):
    return token.upper in _SQL_KEYWORDS


def _find_tail_start(tokens, keywords):
    tail_positions = [token.start for token in tokens if token.depth == 0 and token.upper in keywords]
    return min(tail_positions) if tail_positions else len(tokens[-1].text) + tokens[-1].start


def _inject_condition(sql, tokens, condition, tail_keywords):
    tail_positions = [token.start for token in tokens if token.depth == 0 and token.upper in tail_keywords]
    insert_pos = min(tail_positions) if tail_positions else len(sql)
    has_where = any(token.depth == 0 and token.upper == "WHERE" for token in tokens)
    if has_where:
        return f"{sql[:insert_pos].rstrip()} AND {condition}{sql[insert_pos:]}"
    return f"{sql[:insert_pos].rstrip()} WHERE {condition}{sql[insert_pos:]}"


def _join_condition(alias, allow_null=False):
    if allow_null:
        return f"({alias}.tenant_id = current_tenant() OR {alias}.tenant_id IS NULL)"
    return f"{alias}.tenant_id = current_tenant()"


def _rewrite_select(sql, tokens):
    refs = []
    index = 0
    while index < len(tokens):
        token = tokens[index]
        if token.depth != 0:
            index += 1
            continue
        if token.upper not in {"FROM", "JOIN"}:
            index += 1
            continue

        next_index, table_token = _next_token(tokens, index + 1)
        if not table_token or table_token.text == "(":
            index += 1
            continue

        table_name = _normalize_identifier(table_token.text)
        if table_name not in TENANT_SCOPED_TABLES:
            index = next_index + 1
            continue

        alias = table_name
        allow_null = False
        if token.upper == "JOIN":
            prev_index = index - 1
            while prev_index >= 0 and tokens[prev_index].depth != 0:
                prev_index -= 1
            if prev_index >= 0 and tokens[prev_index].upper == "LEFT":
                allow_null = True

        alias_index, alias_token = _next_token(tokens, next_index + 1)
        if alias_token and alias_token.depth == 0:
            if alias_token.upper == "AS":
                alias_index, alias_token = _next_token(tokens, alias_index + 1)
            if alias_token and alias_token.depth == 0 and not _is_keyword(alias_token) and alias_token.text not in {",", ")", "("}:
                alias = alias_token.text

        refs.append((alias, allow_null))
        index = next_index + 1

    if not refs:
        return sql

    conditions = []
    seen = set()
    for alias, allow_null in refs:
        if alias in seen:
            continue
        seen.add(alias)
        conditions.append(_join_condition(alias, allow_null=allow_null))

    if not conditions:
        return sql

    return _inject_condition(sql, tokens, " AND ".join(conditions), {"GROUP", "HAVING", "ORDER", "LIMIT", "OFFSET", "WINDOW", "UNION"})


def _rewrite_update(sql, tokens):
    table_index, table_token = _next_token(tokens, 1)
    if not table_token:
        return sql
    table_name = _normalize_identifier(table_token.text)
    if table_name not in TENANT_SCOPED_TABLES:
        return sql
    alias = table_name
    alias_index, alias_token = _next_token(tokens, table_index + 1)
    if alias_token and alias_token.depth == 0:
        if alias_token.upper == "AS":
            alias_index, alias_token = _next_token(tokens, alias_index + 1)
        if alias_token and alias_token.depth == 0 and not _is_keyword(alias_token):
            alias = alias_token.text
    condition = _join_condition(alias)
    return _inject_condition(sql, tokens, condition, {"ORDER", "LIMIT", "RETURNING"})


def _rewrite_delete(sql, tokens):
    from_index = next((idx for idx, token in enumerate(tokens) if token.depth == 0 and token.upper == "FROM"), None)
    if from_index is None:
        return sql
    table_index, table_token = _next_token(tokens, from_index + 1)
    if not table_token:
        return sql
    table_name = _normalize_identifier(table_token.text)
    if table_name not in TENANT_SCOPED_TABLES:
        return sql
    condition = _join_condition(table_name)
    return _inject_condition(sql, tokens, condition, {"ORDER", "LIMIT", "RETURNING"})


def _rewrite_insert(sql, tokens):
    into_index = next((idx for idx, token in enumerate(tokens) if token.depth == 0 and token.upper == "INTO"), None)
    if into_index is None:
        return sql

    table_index, table_token = _next_token(tokens, into_index + 1)
    if not table_token:
        return sql
    table_name = _normalize_identifier(table_token.text)
    if table_name not in TENANT_SCOPED_TABLES:
        return sql

    open_index, open_token = _next_token(tokens, table_index + 1)
    if not open_token or open_token.text != "(" or open_token.depth != 0:
        return sql

    close_pos = _find_matching_paren(sql, open_token.start)
    if close_pos == -1:
        return sql

    column_list = sql[open_token.start + 1:close_pos]
    if any(_normalize_identifier(part) == "tenant_id" for part in column_list.split(",")):
        return sql

    rewritten = f"{sql[:close_pos].rstrip()}, tenant_id{sql[close_pos:]}"
    offset = len(rewritten) - len(sql)
    tail = rewritten[close_pos + offset + 1:]
    tail_tokens = _tokenize_sql(tail)
    first_keyword = next((token for token in tail_tokens if token.depth == 0 and token.upper in {"VALUES", "SELECT"}), None)
    if not first_keyword:
        return rewritten

    if first_keyword.upper == "VALUES":
        return _inject_current_tenant_into_values(rewritten, close_pos + offset + 1 + first_keyword.end)
    return _inject_current_tenant_into_select(rewritten, close_pos + offset + 1 + first_keyword.start)


def _inject_current_tenant_into_values(sql, start_pos):
    close_positions = []
    index = start_pos
    depth = 0
    tuple_start = None
    while index < len(sql):
        char = sql[index]
        if char in ("'", '"'):
            index = _consume_quoted(sql, index)
            continue
        if sql.startswith("--", index):
            end = sql.find("\n", index)
            index = len(sql) if end == -1 else end
            continue
        if sql.startswith("/*", index):
            end = sql.find("*/", index + 2)
            index = len(sql) if end == -1 else end + 2
            continue
        if char == "(":
            if depth == 0:
                tuple_start = index
            depth += 1
        elif char == ")":
            depth -= 1
            if depth == 0 and tuple_start is not None:
                close_positions.append(index)
        index += 1

    rewritten = sql
    for close_pos in reversed(close_positions):
        rewritten = f"{rewritten[:close_pos].rstrip()}, current_tenant(){rewritten[close_pos:]}"
    return rewritten


def _inject_current_tenant_into_select(sql, select_pos):
    tail = sql[select_pos:]
    tokens = _tokenize_sql(tail)
    from_token = next((token for token in tokens if token.depth == 0 and token.upper == "FROM"), None)
    if not from_token:
        return f"{sql.rstrip()}, current_tenant() AS tenant_id"
    insert_pos = select_pos + from_token.start
    return f"{sql[:insert_pos].rstrip()}, current_tenant() AS tenant_id {sql[insert_pos:]}"
