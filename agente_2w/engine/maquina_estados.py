from agente_2w.enums.enums import EtapaFluxo

TRANSICOES_PERMITIDAS: dict[EtapaFluxo, list[EtapaFluxo]] = {
    EtapaFluxo.identificacao: [
        EtapaFluxo.busca,
    ],
    EtapaFluxo.busca: [
        EtapaFluxo.oferta,
        EtapaFluxo.identificacao,
    ],
    EtapaFluxo.oferta: [
        EtapaFluxo.confirmacao_item,
        EtapaFluxo.busca,
    ],
    EtapaFluxo.confirmacao_item: [
        EtapaFluxo.entrega_pagamento,
        EtapaFluxo.oferta,
    ],
    EtapaFluxo.entrega_pagamento: [
        EtapaFluxo.fechamento,
        EtapaFluxo.confirmacao_item,
    ],
    EtapaFluxo.fechamento: [],
}


def transicao_permitida(atual: EtapaFluxo, destino: EtapaFluxo) -> bool:
    return destino in TRANSICOES_PERMITIDAS.get(atual, [])


def motivo_bloqueio(atual: EtapaFluxo, destino: EtapaFluxo) -> str:
    return (
        f"transicao de {atual.value} para {destino.value} nao e permitida "
        f"no fluxo V1"
    )


def proximas_etapas(atual: EtapaFluxo) -> list[EtapaFluxo]:
    return TRANSICOES_PERMITIDAS.get(atual, [])


def e_etapa_terminal(etapa: EtapaFluxo) -> bool:
    return len(TRANSICOES_PERMITIDAS.get(etapa, [])) == 0
