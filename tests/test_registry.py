"""Tests for the plugin registry."""

from neo4j_ingest.registry import Registry


class TestRegistry:
    def test_register_and_get(self):
        reg = Registry("test")

        @reg.register("mykey")
        def my_fn():
            return 42

        assert reg.get("mykey") is my_fn
        assert reg.get("mykey")() == 42

    def test_get_missing_returns_none(self):
        reg = Registry("test")
        assert reg.get("nonexistent") is None

    def test_contains(self):
        reg = Registry("test")

        @reg.register("a")
        def fn():
            pass

        assert "a" in reg
        assert "b" not in reg

    def test_keys(self):
        reg = Registry("test")

        @reg.register("x")
        def fn1():
            pass

        @reg.register("y")
        def fn2():
            pass

        assert set(reg.keys()) == {"x", "y"}

    def test_overwrite_warns(self, caplog):
        import logging

        reg = Registry("test")

        @reg.register("dup")
        def fn1():
            return 1

        with caplog.at_level(logging.WARNING):
            @reg.register("dup")
            def fn2():
                return 2

        assert reg.get("dup")() == 2
        assert "overwriting" in caplog.text
