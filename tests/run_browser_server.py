import os
import shutil
import subprocess
import sys
from contextlib import asynccontextmanager
from pathlib import Path
from tempfile import TemporaryDirectory

import uvicorn
from starlette.responses import JSONResponse

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
    from app.main import STATIC, app, create_app

    static_b = Path(directory) / "release-b"
    shutil.copytree(STATIC, static_b)
    html = static_b / "index.html"
    html.write_text(html.read_text().replace('id="boot"', 'id="boot-b"'))
    script = static_b / "js" / "app.js"
    script.write_text(
        script.read_text().replace('"#boot"', '"#boot-b"')
        + '\ndocument.documentElement.dataset.testRelease = "b";\n'
    )
    updated = create_app(static_dir=static_b)
    current = app

    @asynccontextmanager
    async def release_lifespan(_app):
        async with updated.router.lifespan_context(updated), original_lifespan(app):
            yield

    original_lifespan = app.router.lifespan_context
    app.router.lifespan_context = release_lifespan

    async def service(scope, receive, send):
        global current
        if scope["type"] == "lifespan":
            await app(scope, receive, send)
        elif scope["method"] == "POST" and scope["path"] in {
            "/_test/release-a",
            "/_test/release-b",
        }:
            current = updated if scope["path"].endswith("-b") else app
            await JSONResponse({"ok": True})(scope, receive, send)
        else:
            await current(scope, receive, send)

    uvicorn.run(service, host="127.0.0.1", port=8773, access_log=False, log_level="warning")
