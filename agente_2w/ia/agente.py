"""Agente IA — chamada ao OpenAI com function calling e contexto."""

import json
import logging

from openai import OpenAI, RateLimitError, APITimeoutError, APIConnectionError
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type

from agente_2w.config import OPENAI_API_KEY, OPENAI_MODEL

logger = logging.getLogger(__name__)

OPENAI_TIMEOUT = 30  # segundos
from agente_2w.ia.prompt_sistema import SYSTEM_PROMPT
from agente_2w.schemas.contexto_executavel import ContextoExecutavel
from agente_2w.tools.busca_catalogo import (
    buscar_pneus,
    buscar_pneus_por_moto,
    buscar_detalhes_pneu,
)
from agente_2w.tools.consulta_estoque import consultar_estoque
from agente_2w.tools.resolve_cliente import resolver_cliente

_client = OpenAI(api_key=OPENAI_API_KEY, timeout=OPENAI_TIMEOUT)

# ---------- Definição das tools para function calling ----------

TOOLS_SCHEMA = [
    {
        "type": "function",
        "function": {
            "name": "buscar_pneus",
            "description": "Busca pneus no catálogo por dimensões, texto de medida ou marca/modelo.",
            "parameters": {
                "type": "object",
                "properties": {
                    "largura": {"type": "integer", "description": "Largura em mm (ex: 100, 110)"},
                    "perfil": {"type": "integer", "description": "Altura do perfil (ex: 80, 90)"},
                    "aro": {"type": "integer", "description": "Diâmetro do aro em polegadas (ex: 17, 18)"},
                    "medida_texto": {"type": "string", "description": "Trecho da medida (ex: '100/80', '110/80-18')"},
                    "marca_modelo": {"type": "string", "description": "Nome da marca ou modelo (ex: 'Pirelli', 'Pilot Street')"},
                },
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "buscar_pneus_por_moto",
            "description": "Busca pneus compatíveis com uma moto pelo nome/modelo.",
            "parameters": {
                "type": "object",
                "properties": {
                    "termo_moto": {"type": "string", "description": "Nome ou modelo da moto (ex: 'CG 160', 'Biz 125')"},
                },
                "required": ["termo_moto"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "buscar_detalhes_pneu",
            "description": "Busca detalhes completos de um pneu específico pelo UUID.",
            "parameters": {
                "type": "object",
                "properties": {
                    "pneu_id": {"type": "string", "description": "UUID do pneu"},
                },
                "required": ["pneu_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "consultar_estoque",
            "description": "Consulta disponibilidade e preço de um pneu específico pelo UUID.",
            "parameters": {
                "type": "object",
                "properties": {
                    "pneu_id": {"type": "string", "description": "UUID do pneu"},
                },
                "required": ["pneu_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "resolver_cliente",
            "description": "Busca um cliente pelo telefone. Se não existir, cria um novo.",
            "parameters": {
                "type": "object",
                "properties": {
                    "telefone": {"type": "string", "description": "Telefone do cliente (ex: '11999998888')"},
                    "nome": {"type": "string", "description": "Nome do cliente (opcional)"},
                },
                "required": ["telefone"],
            },
        },
    },
]

# ---------- Mapa de dispatch das tools ----------

_TOOL_DISPATCH: dict = {
    "buscar_pneus": buscar_pneus,
    "buscar_pneus_por_moto": buscar_pneus_por_moto,
    "buscar_detalhes_pneu": buscar_detalhes_pneu,
    "consultar_estoque": consultar_estoque,
    "resolver_cliente": resolver_cliente,
}

MAX_TOOL_ROUNDS = 5

_RETRY_EXCEPTIONS = (RateLimitError, APITimeoutError, APIConnectionError)


@retry(
    retry=retry_if_exception_type(_RETRY_EXCEPTIONS),
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=1, min=2, max=30),
    before_sleep=lambda retry_state: logger.warning(
        "OpenAI retry %d apos %s: %s",
        retry_state.attempt_number,
        type(retry_state.outcome.exception()).__name__,
        retry_state.outcome.exception(),
    ),
    reraise=True,
)
def _chamar_openai(messages: list, tools=None) -> object:
    """Chamada OpenAI com retry automatico para rate limit e timeout."""
    kwargs = {
        "model": OPENAI_MODEL,
        "messages": messages,
        "temperature": 0.3,
        "response_format": {"type": "json_object"},
    }
    if tools:
        kwargs["tools"] = tools
        kwargs["tool_choice"] = "auto"
    return _client.chat.completions.create(**kwargs)


def _executar_tool(nome: str, argumentos: dict) -> str:
    """Executa uma tool pelo nome e retorna o resultado serializado."""
    fn = _TOOL_DISPATCH.get(nome)
    if fn is None:
        return json.dumps({"erro": f"Tool '{nome}' não encontrada."})
    resultado = fn(**argumentos)
    return json.dumps(resultado, ensure_ascii=False, default=str)


# ---------- Extração de pneu_ids dos resultados de tools ----------

_TOOLS_COM_PNEU = {"buscar_pneus", "buscar_pneus_por_moto", "buscar_detalhes_pneu", "consultar_estoque"}


def _extrair_pneus_de_resultado(resultado_json: str) -> list[dict]:
    """Extrai pneu_ids dos resultados de tools de busca.

    Suporta todas as estruturas de retorno das tools:
    - buscar_pneus: {"pneus": [{"pneu_id": ...}]}
    - buscar_pneus_por_moto: {"compatibilidades": [{"pneu_id": ...}]}
    - consultar_estoque: {"pneu": {"id": ...}, "preco_venda": ...}
    - buscar_detalhes_pneu: {"pneu": {"id": ...}}

    Retorna lista de dicts com pneu_id, posicao e preco_venda quando disponiveis.
    """
    try:
        data = json.loads(resultado_json)
    except (json.JSONDecodeError, TypeError):
        return []

    pneus: list[dict] = []
    vistos: set = set()

    def _adicionar(pid: str, posicao=None, preco=None) -> None:
        if pid and pid not in vistos:
            vistos.add(pid)
            pneus.append({"pneu_id": pid, "posicao": posicao, "preco_venda": preco})

    def _extrair_item(item: dict, preco_contexto=None) -> None:
        pid = item.get("pneu_id")
        if pid:
            _adicionar(
                str(pid),
                posicao=item.get("posicao") or item.get("pneu_tipo"),
                preco=item.get("preco_venda") or preco_contexto,
            )

    if isinstance(data, list):
        for item in data:
            if isinstance(item, dict):
                _extrair_item(item)
    elif isinstance(data, dict):
        # Sub-listas: "pneus" (buscar_pneus) e "compatibilidades" (buscar_pneus_por_moto)
        for key in ("pneus", "compatibilidades"):
            sub = data.get(key)
            if isinstance(sub, list):
                for item in sub:
                    if isinstance(item, dict):
                        _extrair_item(item)

        # Nivel raiz: pneu_id direto
        _extrair_item(data)

        # Sub-dict "pneu" (consultar_estoque, buscar_detalhes_pneu):
        # essas tools retornam pneu["id"] em vez de pneu_id no topo
        pneu_sub = data.get("pneu")
        if isinstance(pneu_sub, dict):
            pid = pneu_sub.get("id")
            if pid:
                _adicionar(
                    str(pid),
                    posicao=pneu_sub.get("tipo") or data.get("posicao"),
                    preco=data.get("preco_venda"),
                )

    return pneus


def chamar_agente(
    contexto: ContextoExecutavel,
    mensagem_usuario: str,
) -> tuple[str, list[dict]]:
    """Envia mensagem do usuário + contexto para o modelo e processa tool calls.

    Retorna tupla:
        - texto bruto da resposta final do modelo (JSON do EnvelopeIA)
        - lista de pneus encontrados pelas tools (pneu_id, posicao, preco_venda)
    """
    contexto_json = contexto.model_dump_json(indent=None)

    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {
            "role": "system",
            "content": f"CONTEXTO ATUAL DA SESSÃO (JSON):\n{contexto_json}",
        },
        {"role": "user", "content": mensagem_usuario},
    ]

    pneus_encontrados: list[dict] = []

    for round_num in range(MAX_TOOL_ROUNDS):
        response = _chamar_openai(messages, tools=TOOLS_SCHEMA)
        choice = response.choices[0]

        # Se não tem tool calls, retornar a resposta final
        if choice.finish_reason != "tool_calls" or not choice.message.tool_calls:
            return choice.message.content or "", pneus_encontrados

        # Processar cada tool call
        messages.append(choice.message)

        for tool_call in choice.message.tool_calls:
            args = json.loads(tool_call.function.arguments)
            logger.debug("Tool call: %s(%s)", tool_call.function.name, args)
            resultado = _executar_tool(tool_call.function.name, args)
            messages.append({
                "role": "tool",
                "tool_call_id": tool_call.id,
                "content": resultado,
            })

            # Coletar pneu_ids de tools de busca
            if tool_call.function.name in _TOOLS_COM_PNEU:
                novos = _extrair_pneus_de_resultado(resultado)
                pneus_encontrados.extend(novos)

    # Se esgotou os rounds, fazer uma última chamada sem tools
    logger.warning("Esgotou %d rounds de tool calls, chamando sem tools", MAX_TOOL_ROUNDS)
    response = _chamar_openai(messages)
    return response.choices[0].message.content or "", pneus_encontrados
