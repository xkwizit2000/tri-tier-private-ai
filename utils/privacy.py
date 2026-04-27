from typing import Any

def extract_user_message_text(content) -> str:
    """Extract the actual user message text from content that may include OpenClaw metadata wrapper.
    
    OpenClaw wraps user messages with metadata like:
    Conversation info (untrusted metadata):
    ```json
    {...}
    ```
    
    Sender (untrusted metadata):
    ```json
    {...}
    ```
    
    The actual user message comes AFTER these metadata blocks.
    """
    if isinstance(content, str):
        text = content
    elif isinstance(content, list):
        # Extract text from list parts
        text_parts = []
        for part in content:
            if isinstance(part, dict) and part.get("type") in ("text", "input_text"):
                text_parts.append(part.get("text", ""))
            elif isinstance(part, str):
                text_parts.append(part)
        text = '\n'.join(text_parts)
    else:
        text = str(content)
    
    # Strategy: Find all metadata blocks and extract what comes after them
    # Metadata blocks are marked by headers like "Conversation info (untrusted metadata):" or "Sender (untrusted metadata):"
    # followed by ```json ... ```
    
    # OpenClaw prepends untrusted metadata before the actual user text.
    # Strip known wrapper blocks so privacy detection only sees the real message.

    metadata_headers = [
        'Conversation info (untrusted metadata):',
        'Sender (untrusted metadata):',
    ]
    
    # Find the position after all metadata blocks
    remaining_text = text
    for header in metadata_headers:
        if header in remaining_text:
            # Find the header and skip past the JSON block
            idx = remaining_text.find(header)
            if idx >= 0:
                # Find the ```json marker after the header
                json_start = remaining_text.find('```', idx)
                if json_start >= 0:
                    # Find the closing ```
                    json_end = remaining_text.find('```', json_start + 3)
                    if json_end >= 0:
                        remaining_text = remaining_text[json_end + 3:].lstrip()
    
    # After removing all metadata blocks, remaining_text should be the user message
    if remaining_text.strip():
        return remaining_text.strip()
    
    # Fallback: return original text
    return text

def _extract_user_message_text(content: Any) -> str:
    """Backward-compatible alias for older imports and tests."""
    return extract_user_message_text(content)