"""
Loads the project's .env file (datadna/.env) into the process environment, once.

Values already set in the real environment always win over the file.
Importing this module is enough; there is nothing to call.
"""
from pathlib import Path

from dotenv import load_dotenv

ENV_FILE = Path(__file__).resolve().parents[3] / ".env"
load_dotenv(ENV_FILE, override=False)
