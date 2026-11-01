import os
from pathlib import Path
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[1]
load_dotenv(ROOT / '.env')
DATA = Path(os.getenv('TIKI_DATA_DIR', str(ROOT / 'data'))).expanduser()
DATA.mkdir(parents=True, exist_ok=True)
PHOTO_DIR = DATA / 'photos'
PHOTO_DIR.mkdir(parents=True, exist_ok=True)
DB_PATH = DATA / 'tiki.sqlite3'
ESP_URL = os.getenv('TIKI_ESP_URL', 'http://192.168.0.115').rstrip('/')
GEMINI_API_KEY = os.getenv('GEMINI_API_KEY', '').strip()
AI_MODEL = os.getenv('TIKI_AI_MODEL', 'auto').strip()
MAC_TTS = os.getenv('TIKI_MAC_TTS', '1') == '1'
DEMO_MODE = os.getenv('TIKI_DEMO_MODE', '0') == '1' or not GEMINI_API_KEY
