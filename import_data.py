"""Import a v1 watchlist or v2 archive into an already migrated database."""

import argparse
import json
from pathlib import Path

from dotenv import load_dotenv
from fastapi import HTTPException
from pydantic import ValidationError
from sqlalchemy.exc import SQLAlchemyError

from app.config import database_url
from app.database import lock_library, make_engine, make_sessions
from app.schemas import ImportRequest
from app.services.import_export import apply_import, plan_import


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("file", type=Path)
    parser.add_argument("--preview", action="store_true")
    parser.add_argument("--mode", choices=("merge", "update", "replace"), default="merge")
    parser.add_argument("--confirm-replace", action="store_true")
    args = parser.parse_args()
    load_dotenv()
    engine = make_engine(database_url())
    try:
        if args.file.stat().st_size > 16 * 1024 * 1024:
            parser.exit(1, "Архив превышает 16 МиБ.\n")
        raw = json.loads(args.file.read_text(encoding="utf-8-sig"))
        archive = {"items": raw} if isinstance(raw, list) else raw
        payload = ImportRequest.model_validate(
            {
                **{k: v for k, v in archive.items() if k in {"version", "items", "events"}},
                "mode": args.mode,
                "confirm": args.confirm_replace,
            }
        )
        with make_sessions(engine)() as db:
            if not args.preview:
                lock_library(db)
            plan = plan_import(db, payload)
            result = plan.summary() if args.preview else apply_import(db, payload, plan)
            print(json.dumps(result, ensure_ascii=False, indent=2))
    except HTTPException as exc:
        parser.exit(1, json.dumps(exc.detail, ensure_ascii=False) + "\n")
    except (AttributeError, OSError, ValueError, ValidationError, SQLAlchemyError):
        parser.exit(1, "Импорт отменён. Проверьте файл и состояние базы.\n")
    finally:
        engine.dispose()


if __name__ == "__main__":
    main()
