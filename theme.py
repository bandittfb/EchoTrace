"""Dark theme and branding constants for Banditt-Tek EchoTrace."""

APP_NAME = "Banditt-Tek EchoTrace"
APP_SUBTITLE = "AI-Enhanced Audio & Video Transcription"
APP_VERSION = "1.0.0"

# Colours
BG_DARK = "#1A1A2E"
BG_PANEL = "#16213E"
BG_INPUT = "#0F3460"
BG_HIGHLIGHT = "#E94560"  # accent red
TEXT_PRIMARY = "#EAEAEA"
TEXT_SECONDARY = "#8892A0"
TEXT_TIMESTAMP = "#53A8B6"
TEXT_SPEAKER = "#5CB8FF"
ACCENT = "#E94560"
ACCENT_HOVER = "#FF6B81"
BORDER = "#2A2A4A"
PROGRESS_BG = "#0F3460"
PROGRESS_FILL = "#E94560"
SEGMENT_HIGHLIGHT = "#2A1A3E"  # subtle purple for current segment

STYLESHEET = f"""
QMainWindow, QWidget {{
    background-color: {BG_DARK};
    color: {TEXT_PRIMARY};
    font-family: 'Segoe UI', 'Arial', sans-serif;
}}

QLabel {{
    color: {TEXT_PRIMARY};
    background: transparent;
}}

QLabel#title {{
    font-size: 24px;
    font-weight: bold;
    color: {TEXT_PRIMARY};
}}

QLabel#subtitle {{
    font-size: 13px;
    color: {TEXT_SECONDARY};
}}

QLabel#hint {{
    font-size: 10px;
    color: {TEXT_SECONDARY};
}}

QLabel#fileLabel {{
    font-size: 13px;
    font-weight: bold;
    color: {TEXT_PRIMARY};
}}

QLabel#dropzone {{
    border: 3px dashed {TEXT_SECONDARY};
    border-radius: 16px;
    font-size: 16px;
    color: {TEXT_SECONDARY};
    background: {BG_PANEL};
    min-height: 200px;
    padding: 20px;
}}

QLabel#dropzone[dragOver="true"] {{
    border-color: {ACCENT};
    background: #1A2A4E;
}}

QPushButton {{
    background-color: {BG_INPUT};
    color: {TEXT_PRIMARY};
    border: 1px solid {BORDER};
    border-radius: 6px;
    padding: 6px 14px;
    font-size: 12px;
    font-weight: 500;
}}

QPushButton:hover {{
    background-color: {ACCENT};
    border-color: {ACCENT};
}}

QPushButton:pressed {{
    background-color: {ACCENT_HOVER};
}}

QPushButton:checked {{
    background-color: {ACCENT};
    border-color: {ACCENT};
}}

QPushButton#exportBtn {{
    background-color: {BG_INPUT};
    border: 1px solid {BORDER};
    padding: 6px 12px;
}}

QPushButton#exportBtn:hover {{
    background-color: {ACCENT};
}}

QPushButton#playBtn {{
    font-size: 13px;
    font-weight: bold;
    padding: 8px 16px;
    background-color: {ACCENT};
    border: none;
}}

QPushButton#playBtn:hover {{
    background-color: {ACCENT_HOVER};
}}

QComboBox {{
    background-color: {BG_INPUT};
    color: {TEXT_PRIMARY};
    border: 1px solid {BORDER};
    border-radius: 6px;
    padding: 4px 8px;
}}

QComboBox::drop-down {{
    border: none;
}}

QComboBox QAbstractItemView {{
    background-color: {BG_PANEL};
    color: {TEXT_PRIMARY};
    selection-background-color: {ACCENT};
}}

QProgressBar {{
    background-color: {PROGRESS_BG};
    border: 1px solid {BORDER};
    border-radius: 8px;
    height: 22px;
    text-align: center;
    color: {TEXT_PRIMARY};
    font-size: 11px;
    font-weight: bold;
}}

QProgressBar::chunk {{
    background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
        stop:0 {ACCENT}, stop:1 #FF6B81);
    border-radius: 7px;
}}

QPlainTextEdit {{
    background-color: {BG_PANEL};
    color: {TEXT_PRIMARY};
    border: 1px solid {BORDER};
    border-radius: 8px;
    padding: 8px;
    selection-background-color: {ACCENT};
    font-family: 'Consolas', 'Courier New', monospace;
    font-size: 12px;
    line-height: 1.5;
}}

QSlider::groove:horizontal {{
    height: 6px;
    background: {BG_INPUT};
    border-radius: 3px;
}}

QSlider::handle:horizontal {{
    background: {ACCENT};
    width: 14px;
    height: 14px;
    margin: -4px 0;
    border-radius: 7px;
}}

QSlider::sub-page:horizontal {{
    background: {ACCENT};
    border-radius: 3px;
}}

QMenuBar {{
    background-color: {BG_PANEL};
    color: {TEXT_PRIMARY};
    border-bottom: 1px solid {BORDER};
}}

QMenuBar::item:selected {{
    background-color: {ACCENT};
}}

QMenu {{
    background-color: {BG_PANEL};
    color: {TEXT_PRIMARY};
    border: 1px solid {BORDER};
}}

QMenu::item:selected {{
    background-color: {ACCENT};
}}

QMessageBox {{
    background-color: {BG_DARK};
    color: {TEXT_PRIMARY};
}}
"""
