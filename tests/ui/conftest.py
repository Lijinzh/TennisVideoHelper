import pytest

import tennis_video_helper.ui.main_window as gui_module


@pytest.fixture(autouse=True)
def default_desktop_language_is_chinese():
    """Keep UI tests deterministic without overwriting the user's saved language."""

    settings = gui_module._application_settings()
    previous = settings.value(gui_module.LANGUAGE_SETTINGS_KEY, None)
    settings.setValue(gui_module.LANGUAGE_SETTINGS_KEY, "zh_CN")
    settings.sync()
    gui_module.set_language("zh_CN")
    yield
    gui_module.set_language("zh_CN")
    if previous is None:
        settings.remove(gui_module.LANGUAGE_SETTINGS_KEY)
    else:
        settings.setValue(gui_module.LANGUAGE_SETTINGS_KEY, previous)
    settings.sync()
