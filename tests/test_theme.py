from photo_fit_picker.theme import PALETTES, STYLESHEET, _render


def test_theme_palettes_render_every_token() -> None:
    for colors in PALETTES.values():
        rendered = _render(STYLESHEET, colors)
        assert "@" not in rendered
        assert not any(f"{value}_" in rendered for value in colors.values())
        assert "#08090a" not in rendered


def test_dark_palette_keeps_surfaces_visibly_separated() -> None:
    dark = PALETTES["dark"]
    assert dark["workspace"] != dark["sidebar"]
    assert dark["workspace"] != dark["surface"]
    assert dark["surface"] != dark["surface_raised"]
