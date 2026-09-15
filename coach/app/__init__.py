from pathlib import Path
import sqlite3
from datetime import datetime, timezone
from uuid import uuid4

from flask import Flask, jsonify, render_template, request
from flask_wtf import CSRFProtect
from flask_wtf.csrf import CSRFError
from werkzeug.exceptions import HTTPException

from .db import close_db, get_db, init_database, ensure_secret_file, seed_initial_session


def _utc_now_iso():
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def create_app(test_config=None):
    app = Flask(__name__)
    repository_root = Path(app.root_path).parent
    default_data_dir = Path("/app/data")
    app.config.from_mapping(
        DATA_DIR=default_data_dir,
        DATABASE_PATH=default_data_dir / "coach.db",
        SECRET_PATH=default_data_dir / "app-secret",
        SEED_PATH=repository_root / "seed" / "scheda-iniziale-app-v1.json",
        MAX_CONTENT_LENGTH=131072,
        SESSION_COOKIE_HTTPONLY=True,
        SESSION_COOKIE_SAMESITE="Strict",
        SESSION_COOKIE_SECURE=False,
    )
    if test_config is not None:
        app.config.from_mapping(test_config)

    Path(app.config["DATA_DIR"]).mkdir(parents=True, exist_ok=True)
    app.config["SECRET_KEY"] = ensure_secret_file(app.config["SECRET_PATH"])

    CSRFProtect(app)
    app.teardown_appcontext(close_db)

    from .routes import main
    app.register_blueprint(main)

    @app.errorhandler(CSRFError)
    def csrf_error(_error):
        message = "La richiesta non può essere verificata. Ricarica la pagina e riprova."
        wants_json = request.is_json or (
            request.accept_mimetypes["application/json"]
            > request.accept_mimetypes["text/html"]
        )
        if wants_json:
            return jsonify(error=message), 400
        return render_template("error.html", error_message=message, status=400), 400

    error_messages = {
        400: "La richiesta non è valida. Controlla i dati e riprova.",
        404: "La pagina richiesta non è stata trovata.",
        409: "L'operazione non è consentita nello stato attuale.",
        413: "La richiesta è troppo grande. Riduci il testo e riprova.",
        500: "Si è verificato un errore interno. Riprova più tardi.",
        503: "I dati non sono disponibili al momento. Riprova più tardi.",
    }

    def error_page(error):
        status = error.code
        return render_template("error.html", status=status, error_message=error_messages[status]), status

    for status in (400, 404, 409, 413, 500):
        app.register_error_handler(status, error_page)

    def server_error(error, status):
        request_id = uuid4().hex
        # Never pass the exception object or traceback to the logger.
        app.logger.error("exception=%s path=%s request_id=%s", type(error).__name__, request.path, request_id)
        return render_template("error.html", status=status, error_message=error_messages[status], request_id=request_id), status

    @app.errorhandler(sqlite3.DatabaseError)
    def database_error(error):
        return server_error(error, 503)

    @app.errorhandler(Exception)
    def unexpected_error(error):
        if isinstance(error, HTTPException):
            return error
        # Handle before Flask's default traceback logging can expose submitted data.
        return server_error(error, 500)

    with app.app_context():
        init_database()
        if app.config["SEED_PATH"] is not None:
            seed_initial_session(get_db(), app.config["SEED_PATH"], _utc_now_iso())

    @app.get("/healthz")
    def healthz():
        try:
            get_db().execute("SELECT 1").fetchone()
        except sqlite3.Error:
            return jsonify(status="error"), 503
        return jsonify(status="ok")

    return app
