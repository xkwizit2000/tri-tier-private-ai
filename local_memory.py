"""
Local Memory Module for [priv] Conversations

Stores and retrieves private conversation history in isolated local storage.
Never touches cloud services or cloud-tier context.
"""

import json
import os
from datetime import datetime
from typing import List, Dict, Optional

MEMORY_PATH = "/app/data/local_memory.json"
MAX_MESSAGES = 50  # Keep last 50 messages per chat for context
DEFAULT_LIMIT = 10  # Load last 10 messages for context injection


def _load_memory() -> Dict:
    """Load existing memory file or return empty dict."""
    if os.path.exists(MEMORY_PATH):
        try:
            with open(MEMORY_PATH, 'r') as f:
                return json.load(f)
        except (json.JSONDecodeError, IOError) as e:
            print(f"[LocalMemory] Warning: Could not load memory file: {e}")
            return {}
    return {}


def _save_memory(data: Dict) -> bool:
    """Save memory to file. Returns True on success."""
    try:
        with open(MEMORY_PATH, 'w') as f:
            json.dump(data, f, indent=2, default=str)
        return True
    except IOError as e:
        print(f"[LocalMemory] Error saving memory: {e}")
        return False


def store_message(chat_id: str, role: str, content: str) -> bool:
    """
    Store a [priv] message in local memory.
    
    Args:
        chat_id: Unique identifier for the chat (e.g., telegram:7296068402)
        role: 'user' or 'assistant'
        content: The message content
    
    Returns:
        True on success, False on failure
    """
    memory = _load_memory()
    
    # Initialize chat if not exists
    if chat_id not in memory:
        memory[chat_id] = {
            "messages": [],
            "last_accessed": datetime.utcnow().isoformat()
        }
    
    # Add new message
    message_entry = {
        "timestamp": datetime.utcnow().isoformat(),
        "role": role,
        "content": content
    }
    
    memory[chat_id]["messages"].append(message_entry)
    memory[chat_id]["last_accessed"] = datetime.utcnow().isoformat()
    
    # Trim to MAX_MESSAGES if needed
    if len(memory[chat_id]["messages"]) > MAX_MESSAGES:
        # Keep only the last MAX_MESSAGES
        memory[chat_id]["messages"] = memory[chat_id]["messages"][-MAX_MESSAGES:]
    
    return _save_memory(memory)


def load_context(chat_id: str, limit: int = DEFAULT_LIMIT) -> str:
    """
    Load prior [priv] context for a chat.
    
    Args:
        chat_id: Unique identifier for the chat
        limit: Number of recent messages to load
    
    Returns:
        Formatted context string for injection into prompt, or empty string if no history
   """ 
    memory = _load_memory()
    
    if chat_id not in memory or not memory[chat_id].get("messages"):
        return "" 
    
    messages = memory[chat_id]["messages"][-limit:]
    
    if not messages:
        return ""
    
    # Format as conversation context
    context_lines = []
    for msg in messages:
        role_label = "User" if msg["role"] == "user" else "Assistant"
        context_lines.append(f"{role_label}: {msg['content']}")
    
    return "\n".join(context_lines)


def get_chat_history(chat_id: str) -> List[Dict]:
    """
    Get full message history for a chat (for debugging/audit).
    
    Args:
        chat_id: Unique identifier for the chat
    
    Returns:
        List of message dictionaries, or empty list if no history
    """
    memory = _load_memory()
    
    if chat_id not in memory:
        return []
    
    return memory[chat_id].get("messages", [])


def clear_chat(chat_id: str) -> bool:
    """
    Clear all memory for a specific chat.
    
    Args:
        chat_id: Unique identifier for the chat
    
    Returns:
        True on success, False on failure
    """
    memory = _load_memory()
    
    if chat_id in memory:
        del memory[chat_id]
        return _save_memory(memory)
    
    return True


def list_chats() -> List[str]:
    """
    List all chat IDs with stored memory.
    
    Returns:
        List of chat_id strings
    """
    memory = _load_memory()
    return list(memory.keys())


# Test function
if __name__ == "__main__":
    print("[LocalMemory] Module loaded successfully")
    print(f"[LocalMemory] Memory path: {MEMORY_PATH}")
    print(f"[LocalMemory] Max messages per chat: {MAX_MESSAGES}")
    print(f"[LocalMemory] Default context limit: {DEFAULT_LIMIT}")
