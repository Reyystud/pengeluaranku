def test_backend_app_importable() -> None:
    import app

    assert app.__doc__
