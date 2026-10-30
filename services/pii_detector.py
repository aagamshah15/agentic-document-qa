"""
PII Detection Service for Squad B (Profiling, Quality & Security).

Scans column names and sample text values using regex and heuristic patterns
for sensitive personally identifiable information (PII) and credentials:
- Email addresses
- Social Security Numbers (SSNs)
- Credit card numbers
- Phone numbers
- Raw passwords / API tokens / secrets
- IP addresses

Returns List[AnomalyReport] with severity levels (critical, warning, info).
"""

import re
import ipaddress
from typing import List, Any, Optional, Dict, Union
from core.db_models import AnomalyReport, ColumnProfile

# =====================================================================
# Regex Patterns for Sensitive PII & Credentials
# =====================================================================

EMAIL_REGEX = re.compile(
    r'^[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+$'
)
EMAIL_SEARCH_REGEX = re.compile(
    r'\b[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+\b'
)

# US SSN: 3 digits - 2 digits - 4 digits (excluding impossible area/group numbers)
SSN_STRICT_REGEX = re.compile(
    r'^(?!000|666)\d{3}-(?!00)\d{2}-(?!0000)\d{4}$'
)
SSN_GENERAL_REGEX = re.compile(
    r'^\d{3}-\d{2}-\d{4}$'
)

# Standard Credit Cards: Visa (4), MC (51-55, 2221-2720), Amex (34/37), Discover (6011/65)
CREDIT_CARD_REGEX = re.compile(
    r'^(?:4[0-9]{12}(?:[0-9]{3})?|5[1-5][0-9]{14}|2(?:22[1-9]|2[3-9][0-9]|[3-6][0-9]{2}|7[01][0-9]|720)[0-9]{12}|3[47][0-9]{13}|3(?:0[0-5]|[68][0-9])[0-9]{11}|6(?:011|5[0-9]{2})[0-9]{12})$'
)
CREDIT_CARD_FORMATTED_REGEX = re.compile(
    r'^\d{4}[ -]\d{4}[ -]\d{4}[ -]\d{4}$'
)

# Phone: US & International formats
PHONE_REGEX = re.compile(
    r'^(\+?\d{1,3}[-.\s]?)?(\(?\d{3}\)?[-.\s]?)?\d{3}[-.\s]?\d{4}$'
)

# Security Credentials & API Tokens
JWT_REGEX = re.compile(
    r'^eyJ[A-Za-z0-9_-]{10,}\.eyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}$'
)
AWS_KEY_REGEX = re.compile(r'^AKIA[0-9A-Z]{16}$')
GITHUB_TOKEN_REGEX = re.compile(r'^(?:ghp|gho|ghu|ghs|ghr)_[A-Za-z0-9_]{36,255}$')
SLACK_TOKEN_REGEX = re.compile(r'^xox[baprs]-[0-9A-Za-z-]{10,48}$')
GENERIC_API_KEY_REGEX = re.compile(r'^(?:sk_live_[0-9a-zA-Z]{24}|key-[0-9a-zA-Z]{32})$')
PRIVATE_KEY_REGEX = re.compile(r'-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----')

# Column Name Heuristic Patterns
EMAIL_COL_RE = re.compile(r'(email|e_mail|mail_addr|user_email|contact_email)', re.I)
SSN_COL_RE = re.compile(r'(ssn|social_?security|soc_?sec|national_?id|tax_?id|sin)', re.I)
CC_COL_RE = re.compile(r'(credit_?card|card_?num|pan|cc_?num|card_?number|cvv|cvc)', re.I)
PHONE_COL_RE = re.compile(r'(phone|telephone|mobile|cell_?phone|tel_?num|contact_?num)', re.I)
SECRET_COL_RE = re.compile(r'(password|passwd|pwd|secret|api_?key|access_?token|auth_?token|private_?key|bearer_?token|client_?secret)', re.I)
IP_COL_RE = re.compile(r'(ip_?address|client_?ip|remote_?ip|ipv4|ipv6|host_?ip)', re.I)


# =====================================================================
# Validation Helper Functions
# =====================================================================

def is_luhn_valid(number_str: str) -> bool:
    """Validate digits against Luhn checksum (standard for payment cards)."""
    digits = [int(c) for c in number_str if c.isdigit()]
    if len(digits) < 13 or len(digits) > 19:
        return False
    checksum = 0
    reverse_digits = digits[::-1]
    for i, d in enumerate(reverse_digits):
        if i % 2 == 1:
            d *= 2
            if d > 9:
                d -= 9
        checksum += d
    return checksum % 10 == 0


def is_valid_ip(val_str: str) -> bool:
    """Validate IPv4 or IPv6 address."""
    s = val_str.strip()
    if not s or len(s) < 7:
        return False
    try:
        ipaddress.ip_address(s)
        return True
    except ValueError:
        return False


def is_valid_email(val_str: str) -> bool:
    """Check if value is a valid email string."""
    s = val_str.strip()
    return bool(EMAIL_REGEX.match(s) or EMAIL_SEARCH_REGEX.search(s))


def is_valid_ssn(val_str: str, col_name_matches: bool = False) -> bool:
    """Check if value looks like a US SSN."""
    s = val_str.strip()
    if SSN_STRICT_REGEX.match(s):
        return True
    # If column name specifically indicates SSN, also match general format or unhyphenated 9 digits
    if col_name_matches:
        if SSN_GENERAL_REGEX.match(s) or re.match(r'^\d{9}$', s):
            return True
    return False


def is_valid_credit_card(val_str: str, col_name_matches: bool = False) -> bool:
    """Check if value is formatted as or passes credit card validation."""
    s = val_str.strip()
    cleaned = re.sub(r'[\s-]', '', s)
    if not cleaned.isdigit() or len(cleaned) < 13 or len(cleaned) > 19:
        return False
    if CREDIT_CARD_REGEX.match(cleaned) or CREDIT_CARD_FORMATTED_REGEX.match(s):
        return True
    if is_luhn_valid(cleaned):
        return True
    if col_name_matches and 13 <= len(cleaned) <= 19:
        return True
    return False


def is_valid_phone(val_str: str, col_name_matches: bool = False) -> bool:
    """Check if value is formatted like a phone number."""
    s = val_str.strip()
    if PHONE_REGEX.match(s):
        return True
    if col_name_matches:
        cleaned = re.sub(r'[\s+().-]', '', s)
        if cleaned.isdigit() and 7 <= len(cleaned) <= 15:
            return True
    return False


def is_secret_token_or_credential(val_str: str, col_name_matches: bool = False) -> bool:
    """Check if value looks like an API key, bearer token, secret, or raw password."""
    s = val_str.strip()
    if not s:
        return False
    if (
        JWT_REGEX.match(s)
        or AWS_KEY_REGEX.match(s)
        or GITHUB_TOKEN_REGEX.match(s)
        or SLACK_TOKEN_REGEX.match(s)
        or GENERIC_API_KEY_REGEX.match(s)
        or PRIVATE_KEY_REGEX.search(s)
    ):
        return True
    # If the column specifically indicates secret/password and it's plaintext
    if col_name_matches:
        # Exclude hashed passwords starting with bcrypt/argon2 markers if desired,
        # but storing raw password columns is still a severe risk
        return True
    return False


# =====================================================================
# Core PII Scanning Functions
# =====================================================================

def scan_column_for_pii(
    table_name: str,
    column_name: str,
    sample_values: List[Any],
    data_type: Optional[str] = None
) -> List[AnomalyReport]:
    """
    Scans a single column's name and sample values for sensitive PII.
    
    Returns:
        List[AnomalyReport] with severity in ("critical", "warning", "info")
    """
    reports: List[AnomalyReport] = []
    str_samples = [str(v) for v in sample_values if v is not None and str(v).strip() != ""]

    col_lower = column_name.lower()
    col_has_email = bool(EMAIL_COL_RE.search(col_lower))
    col_has_ssn = bool(SSN_COL_RE.search(col_lower))
    col_has_cc = bool(CC_COL_RE.search(col_lower))
    col_has_phone = bool(PHONE_COL_RE.search(col_lower))
    col_has_secret = bool(SECRET_COL_RE.search(col_lower))
    col_has_ip = bool(IP_COL_RE.search(col_lower))

    # 1. Email Detection (Severity: warning)
    email_matches = sum(1 for v in str_samples if is_valid_email(v))
    if email_matches > 0 or (col_has_email and len(str_samples) > 0):
        match_desc = f" ({email_matches} sample matches)" if email_matches else " based on column name"
        reports.append(AnomalyReport(
            category="pii_risk",
            severity="warning",
            table=table_name,
            column=column_name,
            description=f"Column '{column_name}' contains sensitive email addresses{match_desc}.",
            suggested_action="Apply data masking or pseudonymization (e.g. SHA-256 or redact) for GDPR/CCPA compliance."
        ))

    # 2. Social Security Number (SSN) Detection (Severity: critical)
    ssn_matches = sum(1 for v in str_samples if is_valid_ssn(v, col_has_ssn))
    if ssn_matches > 0 or (col_has_ssn and len(str_samples) > 0):
        match_desc = f" ({ssn_matches} sample matches)" if ssn_matches else " based on column name"
        reports.append(AnomalyReport(
            category="pii_risk",
            severity="critical",
            table=table_name,
            column=column_name,
            description=f"Column '{column_name}' contains potential Social Security Numbers (SSNs){match_desc}.",
            suggested_action="Critical PII exposure: encrypt at rest with KMS, tokenize, or redact SSN values immediately."
        ))

    # 3. Credit Card Number Detection (Severity: critical)
    cc_matches = sum(1 for v in str_samples if is_valid_credit_card(v, col_has_cc))
    if cc_matches > 0 or (col_has_cc and len(str_samples) > 0):
        match_desc = f" ({cc_matches} sample matches)" if cc_matches else " based on column name"
        reports.append(AnomalyReport(
            category="pii_risk",
            severity="critical",
            table=table_name,
            column=column_name,
            description=f"Column '{column_name}' contains potential Credit Card Numbers{match_desc}.",
            suggested_action="PCI-DSS violation risk: tokenize, redact, or retain only the last 4 digits."
        ))

    # 4. Phone Number Detection (Severity: warning)
    phone_matches = sum(1 for v in str_samples if is_valid_phone(v, col_has_phone))
    if phone_matches > 0 or (col_has_phone and len(str_samples) > 0):
        match_desc = f" ({phone_matches} sample matches)" if phone_matches else " based on column name"
        reports.append(AnomalyReport(
            category="pii_risk",
            severity="warning",
            table=table_name,
            column=column_name,
            description=f"Column '{column_name}' contains phone numbers{match_desc}.",
            suggested_action="Mask phone numbers or restrict access with role-based column-level security."
        ))

    # 5. Raw Passwords / API Tokens / Secrets Detection (Severity: critical)
    secret_matches = sum(1 for v in str_samples if is_secret_token_or_credential(v, col_has_secret))
    if secret_matches > 0 or (col_has_secret and len(str_samples) > 0):
        match_desc = f" ({secret_matches} sample matches)" if secret_matches else " based on column name"
        reports.append(AnomalyReport(
            category="pii_risk",
            severity="critical",
            table=table_name,
            column=column_name,
            description=f"Column '{column_name}' contains plaintext credentials, passwords, or secret tokens{match_desc}.",
            suggested_action="Security violation: never store raw credentials in database. Hash with bcrypt/Argon2 or use a secret vault."
        ))

    # 6. IP Address Detection (Severity: info)
    ip_matches = sum(1 for v in str_samples if is_valid_ip(v))
    if ip_matches > 0 or (col_has_ip and len(str_samples) > 0):
        match_desc = f" ({ip_matches} sample matches)" if ip_matches else " based on column name"
        reports.append(AnomalyReport(
            category="pii_risk",
            severity="info",
            table=table_name,
            column=column_name,
            description=f"Column '{column_name}' contains IP addresses{match_desc}.",
            suggested_action="Consider truncating or hashing the final octet for privacy-preserving network telemetry."
        ))

    return reports


def scan_table_for_pii(
    table_name: str,
    columns_profile: Union[List[ColumnProfile], Dict[str, List[Any]]]
) -> List[AnomalyReport]:
    """
    Scans an entire table's column profiles or column samples dictionary for PII anomalies.
    """
    reports: List[AnomalyReport] = []

    if isinstance(columns_profile, dict):
        for col_name, samples in columns_profile.items():
            reports.extend(scan_column_for_pii(table_name, col_name, samples))
    else:
        for col in columns_profile:
            reports.extend(scan_column_for_pii(table_name, col.name, col.sample_values, col.data_type))

    return reports


# Convenience aliases for callers across squads
detect_pii = scan_column_for_pii
detect_table_pii = scan_table_for_pii


class PIIDetector:
    @classmethod
    def detect_pii_in_column(cls, column_name: str, sample_values: List[Any], table_name: str = "") -> Dict[str, Any]:
        reports = scan_column_for_pii(table_name, column_name, sample_values)
        if reports:
            rep = reports[0]
            entity = "pii"
            if "contains sensitive " in rep.description:
                entity = rep.description.split("contains sensitive ")[-1].split(" ")[0].rstrip(".")
            return {
                "has_pii": True,
                "detected_entity": entity,
                "confidence": 0.95 if rep.severity == "critical" else 0.85,
                "reports": reports,
            }
        return {"has_pii": False}
