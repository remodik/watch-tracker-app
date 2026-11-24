import os
import subprocess
import sys
from tempfile import TemporaryDirectory

import uvicorn

with TemporaryDirectory(prefix="watch-browser-") as directory:
    os.environ.update(
        APP_ENV="local",
        APP_DISABLE_AUTH="0",
        APP_TOKEN="browser-only-token",
        APP_ORIGIN="http://127.0.0.1:8773",
        DATABASE_URL=f"sqlite:///{directory}/browser.db",
        DATABASE_URL_DIRECT="",
        ANILIST_ENABLED="0",
        TMDB_READ_TOKEN="",
    )
    subprocess.run([sys.executable, "-m", "alembic", "upgrade", "head"], check=True)
    uvicorn.run("app.main:app", host="127.0.0.1", port=8773, access_log=False, log_level="warning")
