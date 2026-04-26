import router_hook

def _req(content):
    return {
        "model": "cloud-simple",
        "messages": [{"role": "user", "content": content}],
        "metadata": {"chat_id": "test-chat"},
        "tools": [{"type": "function", "function": {"name": "x"}}],
        "max_completion_tokens": 128,
    }

def test_private_routes_local_and_strips_prefix(monkeypatch):
    monkeypatch.setattr(router_hook, "LOCAL_MEMORY_ENABLED", False)
    out = router_hook._route(_req("[priv] secret"))
    assert out["model"] == "local-private"
    assert out["messages"][0]["role"] == "system"
    assert out["messages"][1]["role"] == "user"
    assert out["messages"][1]["content"] == "secret"
    assert "tools" not in out
    assert "max_completion_tokens" not in out
    assert out["max_tokens"] == 512

def test_non_private_simple_route(monkeypatch):
    monkeypatch.setattr(router_hook, "classify_complexity", lambda _: "simple")
    out = router_hook._route(_req("hello"))
    assert out["model"] == "cloud-simple"

def test_non_private_complex_route(monkeypatch):
    monkeypatch.setattr(router_hook, "classify_complexity", lambda _: "complex")
    out = router_hook._route(_req("deep architecture question"))
    assert out["model"] == "cloud-complex"
