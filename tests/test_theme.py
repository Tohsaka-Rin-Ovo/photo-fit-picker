from photo_fit_picker.theme import (
    PALETTES,
    STYLESHEET,
    THEME_STYLESHEETS,
    _render,
    is_dark_theme,
    normalize_theme,
)


def test_theme_palettes_render_every_token() -> None:
    for mode, colors in PALETTES.items():
        rendered = _render(STYLESHEET, colors)
        rendered += _render(THEME_STYLESHEETS.get(mode, ""), colors)
        assert "@" not in rendered
        assert not any(f"{value}_" in rendered for value in colors.values())
        assert "#08090a" not in rendered


def test_dark_palette_keeps_surfaces_visibly_separated() -> None:
    dark = PALETTES["dark"]
    assert dark["workspace"] != dark["sidebar"]
    assert dark["workspace"] != dark["surface"]
    assert dark["surface"] != dark["surface_raised"]


def test_kook_theme_uses_expected_accent_and_dark_appearance() -> None:
    assert PALETTES["kook"]["accent"] == "#7acc35"
    assert is_dark_theme("kook") is True
    assert "border-left: 4px solid @accent" in THEME_STYLESHEETS["kook"]


def test_theme_normalization_preserves_legacy_values() -> None:
    assert normalize_theme("graphite") == "light"
    assert normalize_theme("black") == "dark"
    assert normalize_theme("unknown") == "light"
