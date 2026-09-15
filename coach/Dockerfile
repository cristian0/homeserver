FROM python:3.13-slim

ARG APP_UID=1000
ARG APP_GID=1000

RUN if ! [ "${APP_UID}" -gt 0 ] 2>/dev/null; then echo "APP_UID must be a positive integer" >&2; exit 1; fi; \
    if ! [ "${APP_GID}" -gt 0 ] 2>/dev/null; then echo "APP_GID must be a positive integer" >&2; exit 1; fi; \
    groupadd --gid "${APP_GID}" --non-unique app \
    && useradd --uid "${APP_UID}" --gid app --create-home --non-unique app

WORKDIR /app

COPY requirements.txt ./
RUN python -m pip install --no-cache-dir -r requirements.txt

COPY app ./app
COPY seed ./seed
COPY wsgi.py ./

RUN mkdir /app/data && chown app:app /app/data

USER app

EXPOSE 8080

CMD ["gunicorn", "--workers", "1", "--threads", "2", "--bind", "0.0.0.0:8080", "--timeout", "30", "--access-logfile", "/dev/null", "wsgi:app"]
