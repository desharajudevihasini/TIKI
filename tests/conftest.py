import pytest
from app import store

@pytest.fixture(autouse=True)
def clear_transient_camera_grant():
    store.set_setting("pending_camera", None)
    yield
    store.set_setting("pending_camera", None)
