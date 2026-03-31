from agente_2w.schemas.envelope_ia import EnvelopeIA
from agente_2w.schemas.contexto_executavel import ContextoExecutavel
from agente_2w.engine.pendencias import acoes_permitidas
from agente_2w.engine.maquina_estados import transicao_permitida


def validar_envelope(
    envelope: EnvelopeIA,
    contexto: ContextoExecutavel,
) -> list[str]:
    """
    Retorna lista de erros. Lista vazia = envelope valido.
    """
    erros: list[str] = []

    # 1. Acoes sugeridas devem estar dentro das permitidas
    # Quando ha uma transicao valida, permite acoes da etapa atual OU da proposta
    permitidas = set(acoes_permitidas(contexto.sessao.etapa_atual))
    etapa_proposta = envelope.etapa_atual
    if (
        etapa_proposta != contexto.sessao.etapa_atual
        and transicao_permitida(contexto.sessao.etapa_atual, etapa_proposta)
    ):
        permitidas |= set(acoes_permitidas(etapa_proposta))

    for acao in envelope.acoes_sugeridas:
        if acao not in permitidas:
            erros.append(
                f"acao '{acao}' nao e permitida na etapa "
                f"{contexto.sessao.etapa_atual.value}"
            )

    # 2. Etapa do envelope deve ser igual ou transicao valida
    if envelope.etapa_atual != contexto.sessao.etapa_atual:
        if not transicao_permitida(contexto.sessao.etapa_atual, envelope.etapa_atual):
            erros.append(
                f"transicao de {contexto.sessao.etapa_atual.value} para "
                f"{envelope.etapa_atual.value} nao e permitida"
            )

    # 3. Fatos observados nao devem conter chaves vazias
    for fato in envelope.fatos_observados:
        if not fato.chave or not fato.chave.strip():
            erros.append("fato observado com chave vazia")
        if fato.valor is None:
            erros.append(f"fato observado '{fato.chave}' com valor nulo")

    # 4. Fatos inferidos devem ter justificativa
    for fato in envelope.fatos_inferidos:
        if not fato.justificativa or not fato.justificativa.strip():
            erros.append(
                f"fato inferido '{fato.chave}' sem justificativa"
            )

    # 5. Mudancas de itens nao devem promover sem validacao
    ids_itens = {ip.item_provisorio_id for ip in contexto.itens_provisorios}
    # pneu_ids dos itens — modelo as vezes confunde pneu_id com item_provisorio_id
    pneu_ids_de_itens = {ip.pneu_id for ip in contexto.itens_provisorios if ip.pneu_id}
    for mudanca in envelope.mudancas_itens:
        if mudanca.item_provisorio_id and mudanca.item_provisorio_id not in ids_itens:
            # Tolerancia: se o ID e um pneu_id de algum item, o orquestrador vai auto-corrigir
            if mudanca.item_provisorio_id not in pneu_ids_de_itens:
                erros.append(
                    f"mudanca referencia item_provisorio_id "
                    f"'{mudanca.item_provisorio_id}' que nao existe no contexto"
                )
        # Bloquear IA de setar status=promovido (exclusivo do promotor)
        if mudanca.acao == "atualizar" and mudanca.dados:
            if isinstance(mudanca.dados, dict) and mudanca.dados.get("status_item") == "promovido":
                erros.append(
                    "mudanca_itens nao pode definir status_item=promovido "
                    "(exclusivo do promotor)"
                )

    # 6. Confianca deve ser enum valido (Pydantic ja garante, mas dupla checagem)
    if envelope.confianca not in ("alta", "media", "baixa"):
        erros.append(f"confianca '{envelope.confianca}' invalida")

    # 7. Mensagem para o cliente nao pode ser vazia
    if not envelope.mensagem_cliente or not envelope.mensagem_cliente.strip():
        erros.append("mensagem_cliente vazia")

    return erros
