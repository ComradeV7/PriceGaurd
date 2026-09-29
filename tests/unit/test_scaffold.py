"""Scaffold smoke tests."""


def test_scaffold_imports() -> None:
    """The package is importable."""
    import priceguard

    assert priceguard.__version__ == "0.1.0"
