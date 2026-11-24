#!/bin/sh
set -eu

image=${1:?Provide the tag of the built Watch Tracker image}
container=$(docker run --detach --rm --env APP_ENV=local --env APP_DISABLE_AUTH=1 \
    --publish 127.0.0.1::8000 "$image" sh -c \
    'alembic upgrade head && exec uvicorn app.main:app --host 0.0.0.0 --port 8000 --no-access-log')
trap 'docker stop "$container" >/dev/null' EXIT
address=$(docker port "$container" 8000/tcp)
curl --fail --silent --retry 10 --retry-all-errors --retry-delay 1 "http://$address/api/health"
test "$(docker exec "$container" id -u)" = 10001
docker exec "$container" python -c 'from zoneinfo import ZoneInfo; [ZoneInfo(name) for name in ("UTC", "Europe/Moscow", "Europe/Stockholm", "Asia/Tokyo", "America/New_York")]'
for zone in UTC Europe/Moscow Europe/Stockholm Asia/Tokyo America/New_York; do
    curl --fail --silent --output /dev/null --get --data-urlencode "tz=$zone" \
        "http://$address/api/statistics"
done
