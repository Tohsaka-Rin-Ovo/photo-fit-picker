from __future__ import annotations

import re
from typing import Mapping

from PySide6.QtGui import QColor, QPalette
from PySide6.QtWidgets import QApplication


PALETTES: dict[str, dict[str, str]] = {
    "dark": {
        "canvas": "#17191c",
        "workspace": "#17191c",
        "sidebar": "#1d2024",
        "surface": "#202327",
        "surface_raised": "#292d31",
        "surface_hover": "#30353a",
        "surface_pressed": "#383d44",
        "border": "#34383e",
        "border_strong": "#444950",
        "text": "#eef0f3",
        "text_secondary": "#c2c7cf",
        "text_muted": "#a5abb3",
        "disabled": "#7f858d",
        "accent": "#5a9cff",
        "accent_hover": "#70a9ff",
        "accent_pressed": "#438cff",
        "accent_soft": "#253a57",
        "accent_text": "#a9ccff",
        "green": "#65cf98",
        "green_soft": "#274438",
        "red": "#ff7373",
        "red_soft": "#492c30",
        "amber": "#ffd166",
        "amber_soft": "#493d24",
        "image": "#111315",
        "overlay": "rgba(17, 19, 21, 220)",
        "scroll": "#555c65",
    },
    "light": {
        "canvas": "#f7f8fa",
        "workspace": "#f7f8fa",
        "sidebar": "#eef1f4",
        "surface": "#ffffff",
        "surface_raised": "#ffffff",
        "surface_hover": "#f0f2f5",
        "surface_pressed": "#e6e9ee",
        "border": "#dfe3e8",
        "border_strong": "#cdd3da",
        "text": "#202124",
        "text_secondary": "#505761",
        "text_muted": "#717780",
        "disabled": "#969ca5",
        "accent": "#1677ff",
        "accent_hover": "#0f6ee8",
        "accent_pressed": "#075bc2",
        "accent_soft": "#e9f2ff",
        "accent_text": "#075bc2",
        "green": "#1e8e5a",
        "green_soft": "#e7f6ee",
        "red": "#d83b3b",
        "red_soft": "#fff0f0",
        "amber": "#9a6a12",
        "amber_soft": "#fff4d4",
        "image": "#151619",
        "overlay": "rgba(27, 35, 45, 212)",
        "scroll": "#b8c0ca",
    },
    "kook": {
        "canvas": "#1c1f1d",
        "workspace": "#1c1f1d",
        "sidebar": "#202420",
        "surface": "#252925",
        "surface_raised": "#2d322d",
        "surface_hover": "#30352f",
        "surface_pressed": "#394038",
        "border": "#383e37",
        "border_strong": "#4a5248",
        "text": "#f1f3f0",
        "text_secondary": "#cdd3c9",
        "text_muted": "#adb4aa",
        "disabled": "#838b80",
        "accent": "#7acc35",
        "accent_hover": "#8ad545",
        "accent_pressed": "#67b52c",
        "accent_soft": "#304423",
        "accent_text": "#a5e66e",
        "green": "#8bda52",
        "green_soft": "#304423",
        "red": "#ff7770",
        "red_soft": "#4b302f",
        "amber": "#f3c85c",
        "amber_soft": "#4b4022",
        "image": "#111315",
        "overlay": "rgba(17, 19, 21, 220)",
        "scroll": "#66864f",
    },
}

THEME_ALIASES = {"graphite": "light", "black": "dark"}
DARK_THEMES = {"dark", "kook"}


def normalize_theme(mode: object) -> str:
    normalized = THEME_ALIASES.get(str(mode), str(mode))
    return normalized if normalized in PALETTES else "light"


def is_dark_theme(mode: object) -> bool:
    return normalize_theme(mode) in DARK_THEMES


def theme_colors(mode: object) -> Mapping[str, str]:
    return PALETTES[normalize_theme(mode)]


def _render(template: str, colors: Mapping[str, str]) -> str:
    return re.sub(
        r"@([a-z_]+)",
        lambda match: colors[match.group(1)],
        template,
    )


def _qt_palette(colors: Mapping[str, str]) -> QPalette:
    palette = QPalette()
    roles = {
        QPalette.ColorRole.Window: "workspace",
        QPalette.ColorRole.WindowText: "text",
        QPalette.ColorRole.Base: "surface",
        QPalette.ColorRole.AlternateBase: "surface_hover",
        QPalette.ColorRole.ToolTipBase: "surface_raised",
        QPalette.ColorRole.ToolTipText: "text",
        QPalette.ColorRole.Text: "text",
        QPalette.ColorRole.Button: "surface_raised",
        QPalette.ColorRole.ButtonText: "text",
        QPalette.ColorRole.BrightText: "red",
        QPalette.ColorRole.Highlight: "accent",
        QPalette.ColorRole.HighlightedText: "#ffffff",
        QPalette.ColorRole.PlaceholderText: "text_muted",
    }
    for role, name in roles.items():
        palette.setColor(role, QColor(colors.get(name, name)))
    palette.setColor(
        QPalette.ColorGroup.Disabled,
        QPalette.ColorRole.WindowText,
        QColor(colors["disabled"]),
    )
    palette.setColor(
        QPalette.ColorGroup.Disabled,
        QPalette.ColorRole.Text,
        QColor(colors["disabled"]),
    )
    palette.setColor(
        QPalette.ColorGroup.Disabled,
        QPalette.ColorRole.ButtonText,
        QColor(colors["disabled"]),
    )
    return palette


STYLESHEET = r"""
QWidget {
    color: @text;
    font-family: Inter, "Noto Sans SC", "PingFang SC", "Segoe UI", sans-serif;
    font-size: 13px;
}
QMainWindow, #rootStack, #appRoot, #emptyState, #reviewWorkspace,
#photo_grid_host, #settingsView, #settingsPages, #settingsPage,
#organizationView, #organizationDetail {
    background: @workspace;
}
QScrollArea, QScrollArea > QWidget > QWidget {
    background: transparent;
}
#sidebar, #settingsSidebar, #organizationSidebar {
    background: @sidebar;
    border: 0;
    border-right: 1px solid @border;
}
#appMark {
    background: @surface_raised;
    border: 1px solid @border;
    border-radius: 7px;
}
#appTitle {
    color: @text;
    font-size: 18px;
    font-weight: 600;
}
#sourceLabel, #photoDetails, #photoSecondaryDetails, #groupMeta, #emptyHint,
#summaryLabel, #resumeDetail, #viewerInfo, #settingsSectionHint,
#settingsRowHint, #settingsPath, #organizationSummary, #organizationGroupMeta,
#viewerReason, #viewerMetadataLabel {
    color: @text_muted;
}
#sourceLabel, #photoSecondaryDetails, #resumeDetail, #settingsSectionHint,
#settingsRowHint, #organizationSummary, #organizationGroupMeta,
#viewerMetadataLabel, #viewerMetadataValue, #viewerReason {
    font-size: 11px;
}
#sectionTitle {
    color: @text_muted;
    font-size: 11px;
    font-weight: 600;
}
#progressCount, #settingsValue {
    color: @accent;
    font-size: 11px;
    font-weight: 600;
}
#emptyIcon {
    margin-bottom: 8px;
}
#emptyTitle {
    margin-top: 8px;
    color: @text;
    font-size: 28px;
    font-weight: 600;
}
#emptyHint {
    margin-bottom: 14px;
}
#groupTitle {
    color: @text;
    font-size: 18px;
    font-weight: 600;
}
#analysisView {
    background: @workspace;
}
#analysisPanel {
    background: @surface_raised;
    border: 1px solid @border;
    border-radius: 8px;
}
#analysisTitle {
    color: @text;
    font-size: 20px;
    font-weight: 600;
}
#analysisDetail {
    min-height: 36px;
    color: @text_muted;
}
#analysisCount {
    min-width: 58px;
    color: @text_secondary;
    font-size: 12px;
}
#analysisProgress {
    min-height: 7px;
    max-height: 7px;
}
#analysisPanelCancel {
    min-height: 32px;
}

QPushButton, QComboBox, QSpinBox, QToolButton, QLineEdit {
    min-height: 34px;
    padding: 0 11px;
    color: @text;
    background: @surface_raised;
    border: 1px solid @border;
    border-radius: 7px;
}
QPushButton:hover, QToolButton:hover {
    color: @text;
    background: @surface_hover;
    border-color: @border_strong;
}
QPushButton:pressed, QToolButton:pressed {
    background: @surface_pressed;
}
QPushButton:focus, QToolButton:focus, QComboBox:focus, QSpinBox:focus,
QLineEdit:focus {
    border: 1px solid @accent;
}
QPushButton:disabled, QToolButton:disabled, QComboBox:disabled,
QSpinBox:disabled {
    color: @disabled;
    background: @surface;
    border-color: @border;
}
QToolButton {
    min-width: 34px;
    padding: 0;
}
#primaryButton, #emptyPrimaryButton {
    color: #ffffff;
    background: @accent;
    border-color: @accent;
    font-weight: 600;
}
#primaryButton:hover, #emptyPrimaryButton:hover {
    color: #ffffff;
    background: @accent_hover;
    border-color: @accent_hover;
}
#primaryButton:pressed, #emptyPrimaryButton:pressed {
    background: @accent_pressed;
    border-color: @accent_pressed;
}
#primaryButton:disabled, #emptyPrimaryButton:disabled {
    color: @disabled;
    background: @surface_hover;
    border-color: @surface_hover;
}
#emptyPrimaryButton, #emptySecondaryButton {
    min-width: 178px;
    min-height: 40px;
}
#emptySecondaryButton {
    background: @surface_raised;
}
#headerIconButton, #toolbarIconButton, #batchIconButton,
#quietButton, #disclosureButton, #sidebarButton, #settingsButton,
#sidebarUtilityButton, #settingsBackButton, #settingsNavButton {
    color: @text_secondary;
    background: transparent;
    border-color: transparent;
}
#headerIconButton, #toolbarIconButton, #batchIconButton {
    min-width: 34px;
    max-width: 34px;
    min-height: 34px;
    max-height: 34px;
}
#headerIconButton:hover, #toolbarIconButton:hover, #batchIconButton:hover,
#quietButton:hover, #disclosureButton:hover, #sidebarButton:hover,
#settingsButton:hover, #sidebarUtilityButton:hover, #settingsBackButton:hover,
#settingsNavButton:hover {
    color: @text;
    background: @surface_hover;
    border-color: transparent;
}
#sidebarButton, #settingsButton, #sidebarUtilityButton, #settingsBackButton,
#settingsNavButton {
    min-height: 39px;
    padding-left: 10px;
    text-align: left;
    border-radius: 7px;
}
#settingsButton:checked, #settingsNavButton:checked {
    color: @text;
    background: @surface_raised;
    border: 1px solid @border;
}
#quietButton {
    min-height: 32px;
    color: @text_muted;
}
#disclosureButton {
    min-width: 0;
    padding-left: 4px;
    text-align: left;
}
#analysisCancelButton {
    min-width: 24px;
    max-width: 24px;
    min-height: 22px;
    max-height: 22px;
    padding: 0;
    background: transparent;
    border-color: transparent;
}
#trashButton:hover, #batchBar #trashButton:hover {
    background: @red_soft;
    border-color: @red;
}

QComboBox, QSpinBox {
    selection-color: #ffffff;
    selection-background-color: @accent;
}
QComboBox::drop-down, QSpinBox::up-button, QSpinBox::down-button {
    width: 25px;
    border: 0;
}
QComboBox QAbstractItemView {
    padding: 4px;
    color: @text;
    background: @surface_raised;
    selection-color: @text;
    selection-background-color: @surface_hover;
    border: 1px solid @border_strong;
    border-radius: 6px;
    outline: none;
}
QListWidget {
    padding: 2px;
    color: @text_secondary;
    background: transparent;
    border: 0;
    outline: none;
}
QListWidget::item {
    min-height: 36px;
    padding: 0 8px;
    border-radius: 5px;
}
QListWidget::item:hover {
    color: @text;
    background: @surface_hover;
}
QListWidget::item:selected {
    color: @text;
    background: @surface_pressed;
}

#reviewToolbar {
    background: transparent;
    border: 0;
}
#viewControls {
    min-height: 34px;
    max-height: 34px;
    background: transparent;
    border: 0;
}
#viewModeButton, #sortModeButton {
    min-width: 34px;
    max-width: 34px;
    min-height: 32px;
    max-height: 32px;
    padding: 0;
    background: @surface_hover;
    border: 1px solid @border;
    border-radius: 7px;
}
#viewSizeSlider {
    min-height: 24px;
}
#cardLoadingProgress {
    min-height: 5px;
    max-height: 5px;
}
#photoCard {
    background: transparent;
    border: 1px solid transparent;
    border-radius: 7px;
}
#photoCard:hover {
    background: @surface_raised;
    border-color: @border;
}
#photoCard[selected="true"] {
    background: @accent_soft;
    border: 1px solid @accent;
}
#photoCard[reviewStatus="kept"] {
    background: @green_soft;
    border: 1px solid @green;
}
#photoCard[reviewStatus="kept"][selected="true"] {
    border: 1px solid @accent;
}
#photoCard[reviewStatus="rejected"] {
    background: transparent;
    border-color: @border;
}
#photoCard[reviewStatus="trashed"] {
    background: transparent;
    border: 1px dashed @border_strong;
}
#photoCard[feedback="true"] {
    border: 1px solid @accent;
}
#previewFrame {
    background: @surface_hover;
    border-top-left-radius: 6px;
    border-top-right-radius: 6px;
}
#previewFrame[viewMode="list"] {
    border-top-right-radius: 0;
    border-bottom-left-radius: 6px;
}
#photoCaption {
    background: transparent;
}
#photoName {
    color: @text;
    font-weight: 600;
}
#recommendBadge {
    color: #ffffff;
    background: @accent;
    border-radius: 5px;
    font-size: 10px;
    font-weight: 700;
}
#portraitBadge {
    color: #ffffff;
    background: @overlay;
    border-radius: 5px;
    font-size: 10px;
    font-weight: 700;
}
#cardActions {
    background: @overlay;
    border: 1px solid @border_strong;
    border-radius: 7px;
}
#photoStatus {
    min-width: 48px;
    padding: 0 6px;
    color: @text_muted;
    background: @surface_hover;
    border-radius: 4px;
    font-size: 11px;
}
#photoStatus[reviewStatus="kept"] {
    color: @green;
    background: @green_soft;
    font-weight: 600;
}
#photoStatus[reviewStatus="rejected"] {
    color: @text_secondary;
    background: @surface_hover;
}
#photoStatus[reviewStatus="moved"] {
    color: @accent_text;
    background: @accent_soft;
}
#photoStatus[reviewStatus="trashed"] {
    color: @red;
    background: @red_soft;
}
#photoCard #keepButton, #photoCard #rejectButton {
    min-width: 30px;
    max-width: 30px;
    min-height: 30px;
    max-height: 30px;
    padding: 0;
    background: transparent;
    border-color: transparent;
    border-radius: 5px;
}
#photoCard #keepButton:hover, #photoCard #rejectButton:hover {
    background: @surface_pressed;
}
#keepButton:checked {
    background: @green;
    border-color: @green;
}
#rejectButton:checked {
    background: @red;
    border-color: @red;
}
#batchBar {
    min-height: 56px;
    max-height: 56px;
    background: @surface_raised;
    border: 1px solid @border_strong;
    border-radius: 8px;
}
#batchCount {
    min-width: 88px;
    color: @text;
    font-weight: 600;
}

QSlider::groove:horizontal {
    height: 4px;
    background: @surface_pressed;
    border-radius: 2px;
}
QSlider::sub-page:horizontal {
    background: @accent;
    border-radius: 2px;
}
QSlider::handle:horizontal {
    width: 16px;
    height: 16px;
    margin: -6px 0;
    background: @surface_raised;
    border: 2px solid @accent;
    border-radius: 8px;
}
QProgressBar {
    height: 8px;
    color: @text_secondary;
    background: @surface_pressed;
    border: 0;
    border-radius: 4px;
    text-align: center;
}
QProgressBar::chunk {
    background: @accent;
    border-radius: 4px;
}
#reviewProgress {
    min-height: 5px;
    max-height: 5px;
}
QScrollBar:vertical {
    width: 10px;
    margin: 2px;
    background: transparent;
}
QScrollBar::handle:vertical {
    min-height: 28px;
    background: @scroll;
    border-radius: 4px;
}
QScrollBar::handle:vertical:hover {
    background: @border_strong;
}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {
    height: 0;
}
QScrollBar:horizontal {
    height: 10px;
    margin: 2px;
    background: transparent;
}
QScrollBar::handle:horizontal {
    min-width: 28px;
    background: @scroll;
    border-radius: 4px;
}
QScrollBar::handle:horizontal:hover {
    background: @border_strong;
}
QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal {
    width: 0;
}
QMenu {
    padding: 5px;
    color: @text;
    background: @surface_raised;
    border: 1px solid @border_strong;
    border-radius: 7px;
}
QMenu::item {
    min-width: 136px;
    min-height: 30px;
    padding: 0 12px;
    border-radius: 5px;
}
QMenu::item:selected {
    background: @surface_hover;
}

#settingsTitle {
    min-height: 42px;
    padding: 8px 9px 4px 9px;
    color: @text;
    font-size: 22px;
    font-weight: 600;
}
#settingsVersion {
    padding: 0 9px;
    color: @disabled;
    font-size: 11px;
}
#settingsSectionTitle {
    margin-top: 2px;
    color: @text;
    font-size: 26px;
    font-weight: 600;
}
#settingsSectionHint {
    margin-bottom: 4px;
}
#settingsRowTitle {
    color: @text;
    font-weight: 500;
}
#settingsGroup {
    background: transparent;
    border: 0;
    border-radius: 0;
}
#settingsDivider, #viewerDivider {
    max-height: 1px;
    background: @border;
    border: 0;
}
#settingsActionButton {
    min-height: 32px;
    max-height: 32px;
    padding: 0 11px;
}

#organizationHeader {
    min-height: 54px;
    background: @sidebar;
    border-bottom: 1px solid @border;
}
#organizationTitle {
    color: @text;
    font-size: 16px;
    font-weight: 600;
}
#organizationSafety {
    padding: 5px 9px;
    color: @green;
    background: @green_soft;
    border-radius: 5px;
    font-size: 11px;
}
#organizationNameEdit {
    min-height: 40px;
    padding: 0 11px;
    color: @text;
    background: @surface;
    font-size: 15px;
}
#organizationPhotoList {
    padding: 4px;
    background: @surface;
    border: 1px solid @border;
    border-radius: 7px;
}
#organizationPhotoList::item {
    padding: 5px 8px;
    border-bottom: 1px solid @border;
}
#organizationPhotoList::item:selected {
    background: @accent_soft;
}
QSplitter::handle {
    width: 1px;
    background: @border;
}
QStatusBar {
    min-height: 22px;
    color: @text_muted;
    background: @workspace;
    border-top: 1px solid @border;
}
QToolTip {
    padding: 6px 8px;
    color: @text;
    background: @surface_raised;
    border: 1px solid @border_strong;
}
QMessageBox {
    background: @workspace;
}
QMessageBox QLabel {
    color: @text;
}
QMessageBox QPushButton {
    min-width: 88px;
}
QMessageBox #destructiveButton {
    color: #ffffff;
    background: @red;
    border-color: @red;
}

QDialog#photoViewer {
    background: @workspace;
}
QDialog#photoViewer #viewerImageScroll,
QDialog#photoViewer #viewerImageScroll > QWidget > QWidget {
    background: @image;
    border: 1px solid @border;
    border-radius: 6px;
}
QDialog#photoViewer #viewerImage {
    color: @text_muted;
    background: @image;
    border: 0;
}
QDialog#photoViewer #viewerZoomLabel {
    color: @text_muted;
    font-size: 12px;
}
QDialog#photoViewer #viewerZoomButton {
    min-width: 32px;
    max-width: 32px;
    min-height: 32px;
    max-height: 32px;
    padding: 0;
}
QDialog#photoViewer #viewerInspectorScroll,
QDialog#photoViewer #viewerInspector {
    background: @surface;
}
QDialog#photoViewer #viewerInspector {
    border: 1px solid @border;
    border-radius: 7px;
}
QDialog#photoViewer #viewerSectionTitle {
    color: @text;
    font-size: 14px;
    font-weight: 600;
}
QDialog#photoViewer #viewerMetadataValue,
QDialog#photoViewer #viewerQuality {
    color: @text_secondary;
}
QDialog#photoViewer QPushButton, QDialog#photoViewer QToolButton {
    color: @text_secondary;
    background: @surface_raised;
    border-color: @border;
}
QDialog#photoViewer QPushButton:hover, QDialog#photoViewer QToolButton:hover {
    color: @text;
    background: @surface_hover;
    border-color: @border_strong;
}
QDialog#photoViewer #primaryButton {
    color: #ffffff;
    background: @accent;
    border-color: @accent;
}
"""


THEME_STYLESHEETS = {
    "kook": r"""
#settingsNavButton:checked, #settingsButton:checked {
    color: @accent_text;
    background: @accent_soft;
}
#analysisPanel {
    border-left: 4px solid @accent;
}
#batchBar {
    border-left: 4px solid @accent;
}
QListWidget::item:selected, #organizationPhotoList::item:selected {
    color: @text;
    background: @accent_soft;
}
QScrollBar::handle:vertical, QScrollBar::handle:horizontal {
    background: @scroll;
}
QScrollBar::handle:vertical:hover, QScrollBar::handle:horizontal:hover {
    background: @accent;
}
""",
}


def apply_unified_theme(app: QApplication, mode: str) -> None:
    mode = normalize_theme(mode)
    colors = PALETTES[mode]
    stylesheet = _render(STYLESHEET, colors)
    if mode in THEME_STYLESHEETS:
        stylesheet += _render(THEME_STYLESHEETS[mode], colors)
    app.setStyle("Fusion")
    app.setPalette(_qt_palette(colors))
    app.setStyleSheet(stylesheet)
