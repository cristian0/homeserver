"""LAN/VPN-only MCP server for the coach: ``python -m app.mcp_server``.

A separate process next to the Flask app, on the same ``DATA_DIR``. Every
HTTP request needs ``Authorization: Bearer <token>`` (token in
``DATA_DIR/mcp-token``); the tools are the functions of ``coach_tools``, each
call on its own sqlite connection, closed when the tool returns. No Flask
request context is used here.
"""

import logging
import os
from pathlib import Path
import secrets

from mcp.server.mcpserver import MCPServer
from mcp.shared.exceptions import MCPError
from mcp_types.jsonrpc import INVALID_PARAMS
from pydantic import ValidationError
import uvicorn

from . import coach_tools
from .db import ensure_token_file, open_connection
from .workflow import utc_now_iso


logger = logging.getLogger(__name__)

SERVER_NAME = "coach-ginnastica"
DEFAULT_PORT = 8765
UNAUTHORIZED = b"Non autorizzato.\n"
ARGUMENT_ERROR = "Errore: strumento o argomenti non validi."
DATES_PARAMETERS = "da, a (testo AAAA-MM-GG, facoltativi)"
PLAN_PARAMETER = "scheda (testo, obbligatorio: la scheda JSON v1)"
# Fixed per-tool hints: Claude Desktop drops unknown argument names, so the coach needs the right ones.
TOOL_PARAMETERS = {
    "stato_attuale": "nessuno",
    "elenco_sessioni": DATES_PARAMETERS,
    "dettaglio_sessione": "id_sessione (testo, obbligatorio, es. sessione-023, da elenco_sessioni)",
    "diario": DATES_PARAMETERS,
    "valida_scheda": PLAN_PARAMETER,
    "proponi_scheda": PLAN_PARAMETER,
    "proponi_non_eseguita": "id_sessione (testo, obbligatorio: l'id della sessione corrente, da stato_attuale)",
}
INSTRUCTIONS = (
    "Strumenti dell'app Coach ginnastica, raggiungibile solo in LAN o VPN. Chiama stato_attuale "
    "all'inizio di ogni conversazione. Le schede si propongono con proponi_scheda, la sessione "
    "corrente mai iniziata si propone come non eseguita con proponi_non_eseguita: l'utente "
    "conferma sempre nell'app; nessuno strumento scrive sessioni, feedback o diario."
)
DATE_HINT = "Date facoltative nel formato AAAA-MM-GG (data locale italiana); vuote = nessun limite."
TOOL_DESCRIPTIONS = {
    "stato_attuale": (
        "Stato dal vivo per il coach, da chiamare all'inizio di ogni conversazione: sessione corrente "
        "e cosa manca, giorni dall'ultima sessione conclusa, ultime sessioni concluse, diario "
        "dall'ultima sessione, proposta in attesa. Stesso testo di 'Copia stato per il coach'."
    ),
    "elenco_sessioni": (
        "Elenco compatto delle sessioni (una riga ciascuna, con id) in un intervallo di date. "
        "Usalo per domande sullo storico e per trovare l'id da passare a dettaglio_sessione. " + DATE_HINT
    ),
    "dettaglio_sessione": (
        "Tutto ciò che è registrato su una sessione: scheda, esercizi completati e saltati, feedback "
        "immediato e del mattino, tempi e riepilogo salvato. Richiede l'id da elenco_sessioni."
    ),
    "diario": "Note del diario dell'utente in un intervallo di date. " + DATE_HINT,
    "valida_scheda": (
        "Controlla una scheda JSON v1 (testo, anche in un blocco ```json) senza salvare nulla: errori di "
        "schema oppure, se lo schema è valido, i problemi di stato che bloccherebbero l'importazione "
        "(sequenza, sostituzione). Usalo prima di mostrare o proporre una scheda."
    ),
    "proponi_scheda": (
        "Valida una scheda JSON v1 (testo, anche in un blocco ```json) e la salva come proposta in "
        "attesa, sostituendo un'eventuale proposta precedente. Non importa la scheda: l'utente la "
        "conferma o la scarta dall'app, pagina Oggi."
    ),
    "proponi_non_eseguita": (
        "Propone di segnare come non eseguita la sessione corrente, solo se mai iniziata (nessuna "
        "spunta attiva, nessun feedback). L'utente conferma o scarta dall'app, pagina Oggi. La "
        "proposta sostituisce un'eventuale proposta in attesa; sessioni e storico restano invariati. "
        "Se hai già la scheda che la sostituisce, usa proponi_scheda."
    ),
}
TOOL_NAMES = tuple(TOOL_DESCRIPTIONS)


def _call_shape(params):
    """Tool name plus argument names and types of a tools/call, never the values."""
    params = dict(params) if hasattr(params, "keys") else {}
    arguments = params.get("arguments")
    if isinstance(arguments, dict):
        shape = ",".join(f"{key}:{type(value).__name__}" for key, value in sorted(arguments.items()))
    else:
        shape = type(arguments).__name__
    return params.get("name"), shape


def _argument_error(name):
    """Fixed hint naming the tool's parameters; the caller's values are never quoted."""
    if name in TOOL_PARAMETERS:
        text = f"Errore: argomenti non validi per {name}. Parametri: {TOOL_PARAMETERS[name]}."
    elif name is None:
        text = ARGUMENT_ERROR
    else:
        text = f"Errore: strumento sconosciuto. Strumenti disponibili: {', '.join(TOOL_NAMES)}."
    return {"content": [{"type": "text", "text": text}], "isError": True}


async def _fixed_argument_errors(ctx, call_next):
    """SDK errors (unknown tool, wrong arguments) quote the caller's values: answer a fixed text."""
    if ctx.method != "tools/call":
        return await call_next(ctx)
    name, shape = _call_shape(ctx.params)
    known = name if name in TOOL_PARAMETERS else None
    try:
        result = await call_next(ctx)
    except ValidationError:
        logger.warning("tools/call rejected tool=%s arguments=%s", known, shape)
        raise MCPError(code=INVALID_PARAMS, message=ARGUMENT_ERROR) from None
    # The chain hands back the wire form (a dict) or a model, depending on the layer.
    is_error = result.get("isError") if isinstance(result, dict) else getattr(result, "is_error", False)
    if is_error:
        logger.warning("tools/call rejected tool=%s arguments=%s", known, shape)
        return _argument_error(name if isinstance(name, str) else None)
    return result


def create_server(database_path):
    server = MCPServer(SERVER_NAME, instructions=INSTRUCTIONS, log_level="WARNING", middleware=[_fixed_argument_errors])

    def run(tool, *arguments):
        try:
            connection = open_connection(database_path)
        except Exception as error:
            logger.error("tool=%s exception=%s", tool.__name__, type(error).__name__)
            return coach_tools.UNAVAILABLE
        try:
            return tool(connection, *arguments, utc_now_iso())
        finally:
            connection.close()

    def stato_attuale() -> str:
        return run(coach_tools.stato_attuale)

    def elenco_sessioni(da: str | None = None, a: str | None = None) -> str:
        return run(coach_tools.elenco_sessioni, da, a)

    def dettaglio_sessione(id_sessione: str) -> str:
        return run(coach_tools.dettaglio_sessione, id_sessione)

    def diario(da: str | None = None, a: str | None = None) -> str:
        return run(coach_tools.diario, da, a)

    def valida_scheda(scheda: str) -> str:
        return run(coach_tools.valida_scheda, scheda)

    def proponi_scheda(scheda: str) -> str:
        return run(coach_tools.proponi_scheda, scheda)

    def proponi_non_eseguita(id_sessione: str) -> str:
        return run(coach_tools.proponi_non_eseguita, id_sessione)

    for function in (
        stato_attuale, elenco_sessioni, dettaglio_sessione, diario, valida_scheda, proponi_scheda,
        proponi_non_eseguita,
    ):
        server.add_tool(
            function, name=function.__name__, description=TOOL_DESCRIPTIONS[function.__name__],
            structured_output=False,
        )
    return server


class BearerTokenMiddleware:
    """ASGI gate, fail closed: only ``lifespan`` passes without the exact bearer token.

    HTTP gets 401 and a fixed body, a websocket is closed before accept, any
    other scope type is dropped.
    """

    def __init__(self, app, token):
        self.app = app
        self.expected = f"Bearer {token}".encode("ascii")

    async def __call__(self, scope, receive, send):
        if scope["type"] == "lifespan" or self._authorized(scope):
            await self.app(scope, receive, send)
            return
        if scope["type"] == "websocket":
            await send({"type": "websocket.close", "code": 1008})
        elif scope["type"] == "http":
            await send({
                "type": "http.response.start", "status": 401,
                "headers": [
                    (b"content-type", b"text/plain; charset=utf-8"),
                    (b"content-length", str(len(UNAUTHORIZED)).encode("ascii")),
                    (b"www-authenticate", b"Bearer"),
                ],
            })
            await send({"type": "http.response.body", "body": UNAUTHORIZED})

    def _authorized(self, scope):
        values = [value for name, value in scope.get("headers", ()) if name.lower() == b"authorization"]
        return len(values) == 1 and secrets.compare_digest(values[0], self.expected)


def build_asgi_app(database_path, token):
    """Streamable HTTP on ``/mcp`` (stateless, JSON responses) behind the token gate."""
    # host="0.0.0.0": the SDK's localhost-only Host check would refuse LAN clients;
    # access is limited by the network (LAN/VPN) and the token.
    inner = create_server(database_path).streamable_http_app(
        streamable_http_path="/mcp", stateless_http=True, json_response=True, host="0.0.0.0",
    )
    return BearerTokenMiddleware(inner, token)


def main():
    data_dir = Path(os.environ.get("DATA_DIR", "/app/data"))
    token = ensure_token_file(data_dir / "mcp-token")
    port = int(os.environ.get("COACH_MCP_PORT", DEFAULT_PORT))
    app = build_asgi_app(data_dir / "coach.db", token)
    uvicorn.run(app, host="0.0.0.0", port=port, access_log=False, log_level="warning")


if __name__ == "__main__":
    main()
