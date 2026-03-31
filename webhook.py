"""Servidor webhook para integração Chatwoot <-> Agente 2W Pneus.

Recebe mensagens via webhook do Chatwoot (WhatsApp/Baileys) e responde
usando a API do Chatwoot. Gerencia sessões por contato (telefone).
"""

import hashlib
import hmac
import logging
import os
import re
from collections import OrderedDict
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from threading import Lock
from uuid import UUID

import httpx
from fastapi import FastAPI, Request, HTTPException, BackgroundTasks

from agente_2w.config import SUPABASE_URL, OPENAI_MODEL
from agente_2w.db import sessao_repo
from agente_2w.enums.enums import EtapaFluxo, StatusSessao
from agente_2w.schemas.sessao_chat import SessaoChatCreate
from agente_2w.engine.orquestrador import processar_turno

# ---------------------------------------------------------------------------
# Configuração
# ---------------------------------------------------------------------------

logging.basicConfig(
    level=os.getenv("LOG_LEVEL", "INFO").upper(),
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger("webhook")

CHATWOOT_BASE_URL = os.environ["CHATWOOT_BASE_URL"]       # ex: https://chatwoot.smarttecsolutions.com.br
CHATWOOT_API_TOKEN = os.environ["CHATWOOT_API_TOKEN"]      # Bot agent token
CHATWOOT_ACCOUNT_ID = os.environ["CHATWOOT_ACCOUNT_ID"]    # ID numérico da conta
CHATWOOT_INBOX_ID = os.getenv("CHATWOOT_INBOX_ID")         # Filtrar inbox (opcional)
CHATWOOT_WEBHOOK_SECRET = os.getenv("CHATWOOT_WEBHOOK_SECRET", "")  # Para validar assinatura

# ---------------------------------------------------------------------------
# Cache de deduplicação thread-safe (LRU)
# ---------------------------------------------------------------------------

_MAX_CACHE = 5000
_cache_lock = Lock()
_mensagens_processadas: OrderedDict[str, bool] = OrderedDict()

# Lock por telefone para evitar criação duplicada de sessões
_sessao_locks: dict[str, Lock] = {}
_sessao_locks_lock = Lock()

# ---------------------------------------------------------------------------
# HTTP client para Chatwoot API
# ---------------------------------------------------------------------------

_http: httpx.AsyncClient | None = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    global _http
    _http = httpx.AsyncClient(timeout=30.0)
    logger.info("Agente 2W Pneus webhook iniciado")
    logger.info("  Chatwoot: %s", CHATWOOT_BASE_URL)
    logger.info("  Supabase: %s...", SUPABASE_URL[:40])
    logger.info("  Modelo:   %s", OPENAI_MODEL)
    yield
    await _http.aclose()
    logger.info("Webhook encerrado")


app = FastAPI(title="Agente 2W Pneus - Webhook", lifespan=lifespan)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _normalizar_telefone(raw: str) -> str:
    """Extrai apenas dígitos do telefone. Garante formato 55XXXXXXXXXXX."""
    digitos = re.sub(r"\D", "", raw or "")
    if digitos and not digitos.startswith("55"):
        digitos = "55" + digitos
    return digitos


def _verificar_assinatura(payload: bytes, signature: str) -> bool:
    """Valida HMAC-SHA256 do webhook (se secret configurado)."""
    if not CHATWOOT_WEBHOOK_SECRET:
        return True
    expected = hmac.new(
        CHATWOOT_WEBHOOK_SECRET.encode(), payload, hashlib.sha256
    ).hexdigest()
    return hmac.compare_digest(expected, signature)


def _mensagem_ja_processada(message_id: str) -> bool:
    """Verifica e registra message_id de forma thread-safe (LRU)."""
    if not message_id:
        return False
    with _cache_lock:
        if message_id in _mensagens_processadas:
            return True
        _mensagens_processadas[message_id] = True
        while len(_mensagens_processadas) > _MAX_CACHE:
            _mensagens_processadas.popitem(last=False)
    return False


def _lock_para_telefone(telefone: str) -> Lock:
    """Retorna um Lock exclusivo por telefone (evita sessão duplicada)."""
    with _sessao_locks_lock:
        if telefone not in _sessao_locks:
            _sessao_locks[telefone] = Lock()
        return _sessao_locks[telefone]


def _obter_ou_criar_sessao(telefone: str, canal: str = "whatsapp") -> UUID:
    """Busca sessão ativa pelo telefone ou cria uma nova (thread-safe)."""
    lock = _lock_para_telefone(telefone)
    with lock:
        sessao = sessao_repo.buscar_sessao_ativa_por_contato(telefone)
        if sessao:
            logger.debug("Sessao existente: %s (etapa=%s)", sessao.id, sessao.etapa_atual.value)
            return sessao.id

        sessao = sessao_repo.criar_sessao(SessaoChatCreate(
            canal=canal,
            contato_externo=telefone,
            etapa_atual=EtapaFluxo.identificacao,
            status_sessao=StatusSessao.ativa,
        ))
        logger.info("Nova sessao criada: %s para %s", sessao.id, telefone)
        return sessao.id


async def _enviar_resposta_chatwoot(conversation_id: int, texto: str) -> None:
    """Envia mensagem de resposta via API do Chatwoot."""
    url = (
        f"{CHATWOOT_BASE_URL}/api/v1/accounts/{CHATWOOT_ACCOUNT_ID}"
        f"/conversations/{conversation_id}/messages"
    )
    headers = {"api_access_token": CHATWOOT_API_TOKEN}
    payload = {
        "content": texto,
        "message_type": "outgoing",
        "private": False,
    }

    try:
        resp = await _http.post(url, json=payload, headers=headers)
        resp.raise_for_status()
        logger.info("Resposta enviada para conversa %s (%d chars)", conversation_id, len(texto))
    except httpx.HTTPStatusError as e:
        logger.error(
            "Erro ao enviar para Chatwoot: %s - %s",
            e.response.status_code, e.response.text,
        )
    except Exception as e:
        logger.error("Erro de conexao com Chatwoot: %s", e)


def _processar_mensagem_sync(
    telefone: str,
    texto: str,
    message_id_externo: str | None = None,
) -> str:
    """Processa a mensagem no orquestrador (sincrono - roda em thread)."""
    sessao_id = _obter_ou_criar_sessao(telefone)
    resposta = processar_turno(
        sessao_id,
        texto,
        criado_em=datetime.now(timezone.utc),
        message_id_externo=message_id_externo,
    )
    return resposta


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@app.get("/health")
async def health():
    """Health check com validação de conectividade Supabase."""
    try:
        from agente_2w.db.client import supabase
        supabase.table("sessao_chat").select("id").limit(1).execute()
        return {"status": "ok", "service": "agente-2w-pneus"}
    except Exception as e:
        logger.error("Health check falhou: %s", e)
        raise HTTPException(status_code=503, detail="Supabase indisponivel")


@app.post("/webhook/chatwoot")
async def chatwoot_webhook(request: Request, background_tasks: BackgroundTasks):
    """Recebe webhooks do Chatwoot (evento message_created)."""

    # Validar assinatura se configurada
    body = await request.body()
    signature = request.headers.get("x-chatwoot-signature", "")
    if CHATWOOT_WEBHOOK_SECRET and not _verificar_assinatura(body, signature):
        logger.warning("Assinatura invalida no webhook")
        raise HTTPException(status_code=401, detail="Assinatura invalida")

    data = await request.json()

    # Só processar evento message_created
    event = data.get("event")
    if event != "message_created":
        return {"status": "ignored", "event": event}

    # Só processar mensagens incoming (do cliente)
    message_type = data.get("message_type")
    if message_type != "incoming":
        return {"status": "ignored", "reason": "not_incoming"}

    # Ignorar mensagens privadas (notas internas)
    if data.get("private", False):
        return {"status": "ignored", "reason": "private"}

    # Extrair dados
    content = (data.get("content") or "").strip()
    if not content:
        return {"status": "ignored", "reason": "empty_content"}

    conversation = data.get("conversation", {})
    conversation_id = conversation.get("id")
    inbox_id = conversation.get("inbox_id")

    # Gerar message_id robusto
    raw_id = data.get("id")
    message_id = str(raw_id) if raw_id else f"cw_{conversation_id}_{datetime.now(timezone.utc).timestamp()}"

    # Filtrar por inbox se configurado
    if CHATWOOT_INBOX_ID and str(inbox_id) != str(CHATWOOT_INBOX_ID):
        return {"status": "ignored", "reason": "wrong_inbox"}

    # Extrair telefone do contato
    sender = data.get("sender", {})
    telefone_raw = (
        sender.get("phone_number")
        or conversation.get("meta", {}).get("sender", {}).get("phone_number")
        or conversation.get("contact", {}).get("phone_number")
        or ""
    )
    telefone = _normalizar_telefone(telefone_raw)

    if not telefone:
        # Fallback: usar conversation_id como identificador
        telefone = f"chatwoot_{conversation_id}"
        logger.warning("Telefone nao encontrado, usando fallback: %s", telefone)

    # Deduplicação thread-safe
    if _mensagem_ja_processada(message_id):
        return {"status": "ignored", "reason": "duplicate"}

    logger.info(
        "Mensagem recebida: conversa=%s, telefone=%s, msg_id=%s, texto='%s'",
        conversation_id, telefone, message_id, content[:80],
    )

    # Processar em background para responder 200 rápido ao Chatwoot
    async def _processar_e_responder():
        import asyncio
        try:
            resposta = await asyncio.to_thread(
                _processar_mensagem_sync, telefone, content, message_id
            )
            await _enviar_resposta_chatwoot(conversation_id, resposta)
        except Exception as e:
            logger.error("Erro ao processar mensagem: %s", e, exc_info=True)
            await _enviar_resposta_chatwoot(
                conversation_id,
                "Desculpe, tive um problema ao processar sua mensagem. Pode repetir?",
            )

    background_tasks.add_task(_processar_e_responder)

    return {"status": "processing", "message_id": message_id}
