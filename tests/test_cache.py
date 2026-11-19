from ask_olist import cache, config


def test_key_depends_on_model_prompt_version_and_input():
    base = cache.make_key("m", "v1", "q")
    assert base == cache.make_key("m", "v1", "q")
    assert base != cache.make_key("m2", "v1", "q")
    assert base != cache.make_key("m", "v2", "q")   # new prompt version = new key
    assert base != cache.make_key("m", "v1", "q2")


def test_put_then_get(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "CACHE_DIR", tmp_path)
    assert cache.get("t", "abc") is None
    cache.put("t", "abc", {"x": 1})
    assert cache.get("t", "abc") == {"x": 1}
