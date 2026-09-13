from __future__ import annotations

import re
from typing import Mapping

from PySide6.QtGui import QColor, QPalette
from PySide6.QtWidgets import QApplication


PALETTES: dict[str, dict[str, str]] = {
    "dark": {
        "canvas": "#1b1c1f",
        "workspace": "#202125",
        "sidebar": "#27282c",
        "surface": "#292a2f",
        "surface_raised": "#303136",
        "surface_hover": "#37383e",
        "surface_pressed": "#404148",
        "border": "#3a3b41",
        "border_strong": "#505159",
        "text": "#f2f2f4",
        "text_secondary": "#b3b4bb",
        "text_muted": "#85868e",
        "disabled": "#686970",
        "accent": "#0a84ff",
        "accent_hover": "#3198ff",
        "accent_pressed": "#0874df",
        "accent_soft": "#183b5e",
        "accent_text": "#d6eaff",
        "green": "#43c982",
        "green_soft": "#1f4432",
        "red": "#ff696f",
        "red_soft": "#512b30",
        "amber": "#ffd16a",
        "amber_soft": "#594719",
        "image": "#111214",
        "overlay": "rgba(24, 25, 28, 224)",
        "scroll": "#55565e",
    },
    "light": {
        "canvas": "#f2f2f4",
        "workspace": "#f7f7f8",
        "sidebar": "#e9e9ec",
        "surface": "#ffffff",
        "surface_raised": "#ffffff",
        "surface_hover": "#e2e2e6",
        "surface_pressed": "#d7d7dc",
        "border": "#d4d4d9",
        "border_strong": "#b9bac1",
        "text": "#202124",
        "text_secondary": "#55565d",
        "text_muted": "#777880",
        "disabled": "#a4a5ab",
        "accent": "#007aff",
        "accent_hover": "#006ee6",
        "accent_pressed": "#0062cc",
        "accent_soft": "#dcecff",
        "accent_text": "#15558f",
        "green": "#228754",
        "green_soft": "#def2e7",
        "red": "#c6424d",
        "red_soft": "#f8e0e2",
        "amber": "#8a6412",
        "amber_soft": "#fff0c7",
        "image": "#151619",
        "overlay": "rgba(27, 28, 31, 224)",
        "scroll": "#b6b7bd",
    },
}


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
    font-size: 12px;
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
    font-size: 22px;
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
    background: @surface;
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
    color: @text_secondary;
    background: @surface_raised;
    border: 1px solid @border;
    border-radius: 6px;
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
    min-height: 38px;
    padding-left: 10px;
    text-align: left;
}
#settingsButton:checked, #settingsNavButton:checked {
    color: @text;
    background: @surface_pressed;
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
#viewModeButton {
    min-width: 34px;
    max-width: 34px;
    min-height: 32px;
    max-height: 32px;
    padding: 0;
    background: @surface_raised;
    border: 1px solid @border;
}
#viewSizeSlider {
    min-height: 24px;
}
#photoCard {
    background: @surface;
    border: 1px solid @border;
    border-radius: 7px;
}
#photoCard:hover {
    background: @surface_raised;
    border-color: @border_strong;
}
#photoCard[selected="true"] {
    background: @surface_raised;
    border: 2px solid @accent;
}
#photoCard[reviewStatus="kept"] {
    background: @green_soft;
    border: 2px solid @green;
}
#photoCard[reviewStatus="kept"][selected="true"] {
    border: 2px solid @accent;
}
#photoCard[reviewStatus="rejected"] {
    background: @surface;
    border-color: @border;
}
#photoCard[reviewStatus="trashed"] {
    background: @surface;
    border: 1px dashed @border_strong;
}
#photoCard[feedback="true"] {
    border: 2px solid @accent;
}
#previewFrame {
    background: @image;
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
    color: @amber;
    background: @amber_soft;
    border-radius: 5px;
    font-size: 11px;
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
    min-height: 48px;
    max-height: 48px;
    background: @accent_soft;
    border: 1px solid @accent;
    border-radius: 7px;
}
#batchCount {
    min-width: 88px;
    color: @accent_text;
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
    font-size: 23px;
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
    background: @surface;
    border: 1px solid @border;
    border-radius: 8px;
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
    background: @sidebar;
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
QDialog#photoViewer #viewerImage {
    color: @text_muted;
    background: @image;
    border: 1px solid @border;
    border-radius: 6px;
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


def apply_unified_theme(app: QApplication, mode: str) -> None:
    mode = "dark" if mode == "dark" else "light"
    colors = PALETTES[mode]
    app.setStyle("Fusion")
    app.setPalette(_qt_palette(colors))
    app.setStyleSheet(_render(STYLESHEET, colors))
