import os
import sys
from pathlib import Path

# settings are read at import time; give tests a private data dir and a known token
os.environ.setdefault("RC_DEV", "1")
os.environ.setdefault("RC_WORKER_TOKEN", "test-token-0123456789")
os.environ.setdefault("RC_DATA_DIR", "/tmp/rc-pytest")
os.environ.setdefault("RC_DISPLAY_BASE", "150")
os.environ.setdefault("RC_STUN_URL", "")
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
