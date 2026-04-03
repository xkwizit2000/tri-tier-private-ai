"""
router_hook.py — Tri-Tier Keyword Router
========================================
Intercepts every prompt before it reaches a model.
If sensitive keywords are detected → routes to local Ollama.
All other prompts → Together AI cloud reasoning.

Sensitive keywords are intentionally broad. Add/remove as needed.
"""

import logging

logger = logging.getLogger(__name__)

# ----------------------------------------------------------------
# PRIVATE KEYWORD LIST
# Prompts containing any of these route to local-private (Ollama)
# Together AI never sees this content
# ----------------------------------------------------------------
PRIVATE_KEYWORDS = {
    # Financial / tax
    "tax", "taxes", "irs", "w2", "w-2", "1099", "ein", "tin",
    "deduction", "filing", "refund", "audit", "revenue",
    "invoice", "payroll", "ledger", "balance sheet", "p&l",
    "profit and loss", "financial statement", "net worth",

    # Identity / PII
    "ssn", "social security", "passport", "driver's license",
    "date of birth", "dob", "address", "home address",

    # Sensitive markers
    "private", "confidential", "classified", "internal only",
    "do not share", "proprietary",

    # File / document handling
    "file", "document", "upload", "attachment", "pdf",
    "spreadsheet", "contract", "agreement", "nda",

    # Medical
    "medical", "diagnosis", "prescription", "hipaa",
    "health record", "patient",

    # Legal
    "attorney", "lawsuit", "litigation", "settlement",
    "legal advice", "privileged",

    # Credentials
    "password", "api key", "secret", "token", "credential",
}


async def async_pre_call_hook(user_api_key_dict, cache, data, call_type):
    """
    LiteLLM pre-call hook — runs before every model request.
    Inspects message content and overrides model routing if
    sensitive keywords are detected.
    """
    messages = data.get("messages", [])

    # Flatten all message content to a single lowercase string
    full_text = ""
    for m in messages:
        content = m.get("content", "")
        if isinstance(content, str):
            full_text += content.lower() + " "
        elif isinstance(content, list):
            # Handle multi-part messages (e.g. with images)
            for part in content:
                if isinstance(part, dict) and part.get("type") == "text":
                    full_text += part.get("text", "").lower() + " "

    # Check for sensitive keyword match
    matched = [kw for kw in PRIVATE_KEYWORDS if kw in full_text]

    if matched:
        logger.info(
            f"[PrivacyRouter] Sensitive keywords detected: {matched[:3]}{'...' if len(matched) > 3 else ''}. "
            f"Routing to local-private (Ollama)."
        )
        data["model"] = "local-private"
    else:
        logger.info(
            "[PrivacyRouter] No sensitive keywords. "
            "Routing to cloud-reasoning (Together AI)."
        )
        data.setdefault("model", "cloud-reasoning")

    return data

