"""OnlyOffice integration helpers for Odysseus.

Handles JWT signing, signature verification, and configuration generation for
the OnlyOffice Document Server editor.
"""

import os
import logging
from typing import Dict, Any, Optional

logger = logging.getLogger(__name__)


def get_onlyoffice_url() -> Optional[str]:
    """Return the ONLYOFFICE_URL configured in the environment."""
    url = os.getenv("ONLYOFFICE_URL")
    if not url:
        return None
    return url.rstrip("/")


def is_onlyoffice_enabled() -> bool:
    """Return True if OnlyOffice is configured and enabled."""
    return bool(get_onlyoffice_url())


def get_onlyoffice_secret() -> str:
    """Return the ONLYOFFICE_JWT_SECRET used to sign and verify payloads."""
    return os.getenv("ONLYOFFICE_JWT_SECRET") or ""


def sign_payload(payload: Dict[str, Any]) -> str:
    """Sign a payload using PyJWT and the ONLYOFFICE_JWT_SECRET if configured.

    If secret is not set, returns empty string.
    """
    secret = get_onlyoffice_secret()
    if not secret:
        return ""
    try:
        import jwt
        # OnlyOffice uses HS256 by default
        return jwt.encode(payload, secret, algorithm="HS256")
    except Exception as e:
        logger.error("Failed to sign OnlyOffice payload: %s", e)
        return ""


def decode_token(token: str) -> Optional[Dict[str, Any]]:
    """Decode and verify an OnlyOffice JWT token.

    Returns the payload if valid, otherwise None.
    """
    secret = get_onlyoffice_secret()
    if not secret:
        # If secret is unset, we cannot verify. Returns payload if jwt works without verification
        try:
            import jwt
            return jwt.decode(token, options={"verify_signature": False})
        except Exception:
            return None
    try:
        import jwt
        return jwt.decode(token, secret, algorithms=["HS256"])
    except Exception as e:
        logger.warning("Failed to decode OnlyOffice token: %s", e)
        return None


def get_document_type(filename: str) -> str:
    """Determine OnlyOffice documentType based on file extension."""
    _, ext = os.path.splitext(filename.lower())
    ext = ext.lstrip(".")
    if ext in ["docx", "doc", "odt", "rtf", "txt", "epub", "md"]:
        return "word"
    elif ext in ["pptx", "ppt", "odp"]:
        return "slide"
    elif ext in ["xlsx", "xls", "ods", "csv"]:
        return "cell"
    return "word"


def build_onlyoffice_config(
    doc_id: str,
    filename: str,
    download_url: str,
    callback_url: str,
    user_id: str,
    user_name: str,
    version_key: str,
    can_edit: bool = True
) -> Dict[str, Any]:
    """Generate configuration dictionary for the OnlyOffice iframe editor.

    Automatically wraps and appends 'token' if JWT secret is configured.
    """
    file_ext = os.path.splitext(filename)[1].lstrip(".").lower() or "docx"
    doc_type = get_document_type(filename)

    config: Dict[str, Any] = {
        "documentType": doc_type,
        "document": {
            "fileType": file_ext,
            "key": version_key,
            "title": filename,
            "url": download_url,
            "permissions": {
                "edit": can_edit,
                "download": True,
                "print": True,
                "fillForms": True,
            }
        },
        "editorConfig": {
            "callbackUrl": callback_url,
            "mode": "edit" if can_edit else "view",
            "lang": "en",
            "user": {
                "id": user_id,
                "name": user_name
            },
            "customization": {
                "forcesave": True, # request forcesave on close
                "chat": False, # disable onlyoffice internal chat
                "commentAuthorOnly": False,
                "help": False,
            }
        }
    }

    # If secret is set, sign the config and add 'token' property
    secret = get_onlyoffice_secret()
    if secret:
        token = sign_payload(config)
        if token:
            config["token"] = token

    return config


import re

_OFFICE_FRONT_MATTER_RE = re.compile(
    r'<!--\s*onlyoffice_source\s+upload_id="(?P<upload_id>[^"]+)"(?:\s+filename="(?P<filename>[^"]+)")?\s*-->'
)


def find_office_source(content: str) -> Optional[tuple[str, str]]:
    """Return (upload_id, filename) if content is an OnlyOffice-backed doc, else None."""
    if not content:
        return None
    m = _OFFICE_FRONT_MATTER_RE.search(content)
    if m:
        upload_id = m.group("upload_id")
        filename = m.group("filename") or "document.docx"
        from src.upload_handler import is_valid_upload_id
        if is_valid_upload_id(upload_id):
            return upload_id, filename
    return None

