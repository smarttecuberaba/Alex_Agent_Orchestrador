from agente_2w.enums.enums import EtapaFluxo
from agente_2w.constantes import ChaveContexto

ACOES_POR_ETAPA: dict[EtapaFluxo, list[str]] = {
    EtapaFluxo.identificacao: [
        "pedir_clarificacao_moto",
        "pedir_clarificacao_medida",
        "pedir_clarificacao_posicao",
        "buscar_por_moto",
        "buscar_por_medida",
        "registrar_fato_observado",
        "registrar_opcoes_encontradas",
        "responder_incerteza_segura",
    ],
    EtapaFluxo.busca: [
        "buscar_por_moto",
        "buscar_por_medida",
        "buscar_medida_proxima",
        "pedir_clarificacao_moto",
        "pedir_clarificacao_medida",
        "registrar_opcoes_encontradas",
        "responder_incerteza_segura",
    ],
    EtapaFluxo.oferta: [
        "apresentar_opcoes",
        "explicar_falta",
        "pedir_escolha_cliente",
        "responder_incerteza_segura",
    ],
    EtapaFluxo.confirmacao_item: [
        "confirmar_item",
        "registrar_quantidade",
        "registrar_posicao",
        "rejeitar_item",
        "responder_incerteza_segura",
    ],
    EtapaFluxo.entrega_pagamento: [
        "perguntar_tipo_entrega",
        "perguntar_endereco",
        "perguntar_forma_pagamento",
        "registrar_entrega",
        "registrar_pagamento",
        "responder_incerteza_segura",
    ],
    EtapaFluxo.fechamento: [
        "revisar_pedido",
        "converter_em_pedido",
        "responder_incerteza_segura",
    ],
}


def acoes_permitidas(etapa: EtapaFluxo) -> list[str]:
    return ACOES_POR_ETAPA.get(etapa, ["responder_incerteza_segura"])


PENDENCIAS_POR_ETAPA: dict[EtapaFluxo, list[dict]] = {
    EtapaFluxo.identificacao: [
        {
            "codigo": "moto_ou_medida",
            "descricao": "cliente precisa informar moto ou medida do pneu",
            "campo_relacionado": "moto_modelo_informado",
            "obrigatoria_para": "busca",
        },
    ],
    EtapaFluxo.busca: [
        {
            "codigo": "resultado_busca",
            "descricao": "busca precisa retornar pelo menos uma opcao real",
            "campo_relacionado": "resultados_busca",
            "obrigatoria_para": "oferta",
        },
    ],
    EtapaFluxo.oferta: [
        {
            "codigo": "escolha_cliente",
            "descricao": "cliente precisa escolher um pneu",
            "campo_relacionado": "pneu_confirmado",
            "obrigatoria_para": "confirmacao_item",
        },
    ],
    EtapaFluxo.confirmacao_item: [
        {
            "codigo": "item_validado",
            "descricao": "item provisorio precisa estar validado com pneu real",
            "campo_relacionado": "item_provisorio",
            "obrigatoria_para": "entrega_pagamento",
        },
    ],
    EtapaFluxo.entrega_pagamento: [
        {
            "codigo": ChaveContexto.TIPO_ENTREGA,
            "descricao": "tipo de entrega precisa estar definido",
            "campo_relacionado": ChaveContexto.TIPO_ENTREGA,
            "obrigatoria_para": "fechamento",
        },
        {
            "codigo": ChaveContexto.FORMA_PAGAMENTO,
            "descricao": "forma de pagamento precisa estar definida",
            "campo_relacionado": ChaveContexto.FORMA_PAGAMENTO,
            "obrigatoria_para": "fechamento",
        },
    ],
    EtapaFluxo.fechamento: [
        {
            "codigo": "pedido_pronto",
            "descricao": "todos os requisitos precisam estar validados para criar pedido",
            "campo_relacionado": "pedido",
            "obrigatoria_para": "fechamento",
        },
    ],
}


def pendencias_da_etapa(etapa: EtapaFluxo) -> list[dict]:
    return PENDENCIAS_POR_ETAPA.get(etapa, [])
