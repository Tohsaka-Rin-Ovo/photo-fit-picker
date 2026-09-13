from photo_fit_picker.ui import (
    _clamped_thumbnail_size,
    _normalized_view_mode,
    _photo_grid_columns,
)


def test_view_preferences_are_normalized() -> None:
    assert _normalized_view_mode("compact") == "compact"
    assert _normalized_view_mode("unexpected") == "large"
    assert _clamped_thumbnail_size("80") == 120
    assert _clamped_thumbnail_size(999) == 320
    assert _clamped_thumbnail_size("invalid") == 268


def test_grid_columns_follow_view_mode_and_available_width() -> None:
    assert _photo_grid_columns(900, "compact", 168) == 4
    assert _photo_grid_columns(900, "large", 268) == 3
    assert _photo_grid_columns(900, "list", 136) == 1
    assert _photo_grid_columns(40, "compact", 168) == 1
