from utils.privacy import extract_user_message_text


def test_extract_from_wrapped_string():
    content = """Conversation info (untrusted metadata):
```json
{"a": 1}
```

Sender (untrusted metadata):
```json
{"b": 2}
```

[priv] actual message
"""
    assert extract_user_message_text(content) == "[priv] actual message"


def test_extract_from_list_content():
    content = [
        {
            "type": "text",
            "text": "Conversation info (untrusted metadata):\n```json\n{}\n```",
        },
        {
            "type": "input_text",
            "text": "Sender (untrusted metadata):\n```json\n{}\n```",
        },
        {"type": "text", "text": "real user text"},
    ]
    assert extract_user_message_text(content) == "real user text"


def test_passthrough_when_no_metadata():
    content = "plain user text"
    assert extract_user_message_text(content) == "plain user text"


def test_fallback_on_malformed_block():
    content = "Conversation info (untrusted metadata):\n```json\n{bad\nplain fallback"
    assert extract_user_message_text(content) == content
