from flask import Flask
from flask_sqlalchemy import SQLAlchemy
import os

# Load .env file if present (keys kept out of git). Optional — the app runs without it.
env_path = os.path.join(os.path.abspath(os.path.dirname(os.path.dirname(__file__))), '.env')
if os.path.exists(env_path):
    with open(env_path) as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith('#') and '=' in line:
                key, val = line.split('=', 1)
                os.environ.setdefault(key.strip(), val.strip())

app = Flask(__name__)

# Configuration.
base_dir = os.path.abspath(os.path.dirname(__name__))
# Shares the SQLite database of the sibling detectfake_rlvr app (this app only adds its own
# table; db.create_all() below leaves every existing table untouched). Override the location
# with DETECTFAKE_DB_PATH, e.g. when the apps are deployed in different directories.
_repo_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
database_path = os.environ.get('DETECTFAKE_DB_PATH') or os.path.join(
    os.path.dirname(_repo_root), 'detectfake_rlvr', 'webapp', 'detectfakesv3.db')
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///' + database_path

# Persistent secret key for session signing (stable across restarts).
secret_key_path = os.path.join(base_dir, 'webapp', '.secret_key')
if os.path.exists(secret_key_path):
    with open(secret_key_path, 'rb') as f:
        app.secret_key = f.read()
else:
    app.secret_key = os.urandom(24)
    with open(secret_key_path, 'wb') as f:
        f.write(app.secret_key)

# Initialize SQLAlchemy
db = SQLAlchemy(app)

from . import text_routes

# Create any missing tables (idempotent — leaves existing tables untouched).
with app.app_context():
    db.create_all()
