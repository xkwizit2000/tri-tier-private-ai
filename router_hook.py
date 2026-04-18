import logging
from litellm.integrations.custom_logger import CustomLogger

print("[PrivacyRouter] MODULE LOADED")
logger = logging.getLogger(__name__)

PRIVATE_KEYWORDS = {
    "tax", "taxes", "irs", "w2", "1099", "ein", "tin",
    "deduction", "filing", "refund", "audit", "invoice",
    "payroll", "ledger", "ssn", "social security", "passport",
    "date of birth", "home address", "private", "confidential",
    "classified", "proprietary", "file", "document", "upload",
    "pdf", "contract", "agreement", "nda", "medical", "diagnosis",
    "prescription", "hipaa", "health record", "patient",
    "attorney", "lawsuit", "settlement", "password", "secret",
    "credential",
}

class PrivacyRouter(CustomLogger):

    def __init__(self):
        super().__init__()
        print("[PrivacyRouter] INSTANCE CREATED")

    async def async_pre_call_hook(self, user_api_key_dict, cache, data, call_type):
        print(f"[PrivacyRouter] HOOK CALLED model={data.get('model')}")
        messages = data.get("messages", [])
        full_text = ""
        for m in messages:
            content = m.get("content", "")
            if isinstance(content, str):
                full_text += content.lower() + " "

        matched = [kw for kw in PRIVATE_KEYWORDS if kw in full_text]

        if matched:
            print(f"[PrivacyRouter] SENSITIVE {matched[:2]} -> local-private")
            data["model"] = "local-private"
        else:
            print(f"[PrivacyRouter] CLEAN -> cloud-reasoning")
            data.setdefault("model", "cloud-reasoning")

        return data

proxy_handler_instance = PrivacyRouter()
print(f"[PrivacyRouter] INSTANCE READY: {proxy_handler_instance}")
