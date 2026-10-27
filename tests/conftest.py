import os
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
# the app runs as `python src/main.py`, so its modules import each other from src/
sys.path.insert(0, os.path.join(ROOT, "src"))

# src/main.py creates the Api and the data dirs at import time. Give it a harmless context so
# that importing it offline neither reads ~/supervisely.env/local.env nor touches a real server.
# Contract tests build their own Api from ~/supervisely.env and swap it in.
os.environ.setdefault("ENV", "production")
os.environ.setdefault("SERVER_ADDRESS", "http://fake.supervisely.local")
os.environ.setdefault("API_TOKEN", "x" * 128)
os.environ.setdefault("SLY_APP_DATA_DIR", tempfile.mkdtemp(prefix="download-images-tests-"))
