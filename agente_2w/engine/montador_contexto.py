from uuid import UUID
from datetime import datetime, timezone

from agente_2w.db import sessao_repo, mensagem_repo, contexto_repo, item_provisorio_repo, cliente_repo, pedido_repo, catalogo_repo
from agente_2w.engine.pendencias import acoes_permitidas, pendencias_da_etapa
from agente_2w.enums.enums import StatusSessao, StatusItemProvisorio
from agente_2w.constantes import ChaveContexto
from agente_2w.schemas.contexto_executavel import (
    ContextoExecutavel,
    SessaoContexto,
    ClienteContexto,
    BloqueioAtivo,
    MensagemRecente,
    FatoAtivo,
    ItemProvisorioContexto,
    ItemUltimoPedidoContexto,
    UltimoPedidoContexto,
    Pendencia,
    ResumoOperacional,
    Metadados,
)


def montar_contexto(sessao_id: UUID) -> ContextoExecutavel:
    sessao = sessao_repo.buscar_sessao_por_id(sessao_id)
    if sessao is None:
        raise ValueError(f"sessao {sessao_id} nao encontrada")

    # Sessao
    sessao_ctx = SessaoContexto(
        sessao_id=str(sessao.id),
        canal=sessao.canal,
        contato_externo=sessao.contato_externo,
        etapa_atual=sessao.etapa_atual,
        status_sessao=sessao.status_sessao,
        ultima_interacao_em=sessao.ultima_interacao_em,
    )

    # Cliente
    cliente_ctx = ClienteContexto()
    if sessao.cliente_id:
        cliente = cliente_repo.buscar_cliente_por_id(sessao.cliente_id)
        if cliente:
            # Ultimo pedido confirmado (excluindo a sessao atual)
            ultimo_pedido_ctx = None
            ultimo_pedido = pedido_repo.buscar_ultimo_pedido_confirmado(
                cliente.id, excluir_sessao_id=sessao_id
            )
            if ultimo_pedido:
                itens_pedido = pedido_repo.listar_itens_pedido(ultimo_pedido.id)
                itens_ctx = []
                for item in itens_pedido:
                    pneu = catalogo_repo.buscar_pneu_por_id(item.pneu_id)
                    nome_pneu = pneu.descricao_comercial if pneu else str(item.pneu_id)
                    itens_ctx.append(ItemUltimoPedidoContexto(
                        pneu_nome=nome_pneu,
                        posicao=item.posicao.value if item.posicao else None,
                        quantidade=item.quantidade,
                        preco_unitario=item.preco_unitario,
                    ))
                ultimo_pedido_ctx = UltimoPedidoContexto(
                    data=ultimo_pedido.criado_em,
                    valor_total=ultimo_pedido.valor_total,
                    forma_pagamento=ultimo_pedido.forma_pagamento.value,
                    tipo_entrega=ultimo_pedido.tipo_entrega.value,
                    itens=itens_ctx,
                )

            cliente_ctx = ClienteContexto(
                cliente_id=str(cliente.id),
                nome=cliente.nome,
                telefone=cliente.telefone,
                resolvido=True,
                segmento=cliente.segmento,
                total_pedidos=cliente.total_pedidos,
                valor_total_gasto=cliente.valor_total_gasto,
                ultima_compra_em=cliente.ultima_compra_em,
                municipio=cliente.municipio,
                bairro=cliente.bairro,
                ultimo_pedido=ultimo_pedido_ctx,
            )

    # Bloqueios
    bloqueios: list[BloqueioAtivo] = []
    if sessao.status_sessao == StatusSessao.bloqueada and sessao.codigo_motivo:
        bloqueios.append(BloqueioAtivo(
            codigo_motivo=sessao.codigo_motivo,
            mensagem_motivo=sessao.mensagem_motivo or "",
            campo_relacionado=sessao.campo_relacionado,
            acao_bloqueada=sessao.acao_bloqueada or "",
        ))

    # Mensagens recentes
    mensagens_db = mensagem_repo.listar_mensagens_por_sessao(sessao_id, limite=20)
    mensagens_recentes = [
        MensagemRecente(
            mensagem_id=str(m.id),
            direcao=m.direcao.value,
            remetente=m.remetente.value,
            conteudo_texto=m.conteudo_texto,
            criado_em=m.criado_em,
        )
        for m in mensagens_db
    ]

    # Fatos ativos
    fatos_db = contexto_repo.listar_fatos_ativos(sessao_id)
    fatos_ativos = [
        FatoAtivo(
            chave=f.chave,
            valor=f.valor_texto if f.valor_texto else f.valor_json,
            tipo_de_verdade=f.tipo_de_verdade,
            nivel_confirmacao=f.nivel_confirmacao,
            fonte=f.fonte,
            mensagem_chat_id=str(f.mensagem_chat_id) if f.mensagem_chat_id else None,
            item_provisorio_id=str(f.item_provisorio_id) if f.item_provisorio_id else None,
            coletado_em=f.coletado_em,
        )
        for f in fatos_db
    ]

    # Itens provisorios
    itens_db = item_provisorio_repo.listar_itens_ativos_por_sessao(sessao_id)
    itens_provisorios = [
        ItemProvisorioContexto(
            item_provisorio_id=str(item.id),
            pneu_id=str(item.pneu_id) if item.pneu_id else None,
            descricao_contextual=item.observacao or f"item {item.status_item.value}",
            posicao=item.posicao.value if item.posicao else None,
            quantidade=item.quantidade,
            status_item=item.status_item,
            preco_unitario_sugerido=item.preco_unitario_sugerido,
            cliente_confirmou=item.cliente_confirmou_em is not None,
            validado_backend=item.validado_backend_em is not None,
        )
        for item in itens_db
    ]

    # Pendencias
    pendencias_etapa = pendencias_da_etapa(sessao.etapa_atual)
    pendencias = [
        Pendencia(
            codigo=p["codigo"],
            descricao=p["descricao"],
            campo_relacionado=p.get("campo_relacionado"),
            obrigatoria_para=p["obrigatoria_para"],
        )
        for p in pendencias_etapa
    ]

    # Acoes permitidas
    acoes = acoes_permitidas(sessao.etapa_atual)

    # Resumo operacional
    tem_item_validado = any(
        item.status_item in (StatusItemProvisorio.validado, StatusItemProvisorio.selecionado_cliente)
        and item.pneu_id is not None
        for item in itens_db
    )

    chaves_ativas = {f.chave for f in fatos_db}
    tem_entrega = ChaveContexto.TIPO_ENTREGA in chaves_ativas
    tem_pagamento = ChaveContexto.FORMA_PAGAMENTO in chaves_ativas

    resumo = ResumoOperacional(
        tem_item_validado=tem_item_validado,
        tem_entrega_definida=tem_entrega,
        tem_pagamento_definido=tem_pagamento,
        pode_avancar_etapa=tem_item_validado and sessao.status_sessao != StatusSessao.bloqueada,
    )

    return ContextoExecutavel(
        sessao=sessao_ctx,
        cliente=cliente_ctx,
        bloqueios_ativos=bloqueios,
        mensagens_recentes=mensagens_recentes,
        fatos_ativos=fatos_ativos,
        resultados_busca_atuais=[],
        itens_provisorios=itens_provisorios,
        pendencias=pendencias,
        acoes_permitidas=acoes,
        resumo_operacional=resumo,
        metadados=Metadados(
            gerado_em=datetime.now(timezone.utc),
            versao_contexto="v1",
        ),
    )
