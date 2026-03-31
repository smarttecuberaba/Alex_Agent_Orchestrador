"""Tools de busca no catálogo — chamadas pela IA via function calling."""

from uuid import UUID

from agente_2w.db import catalogo_repo


def buscar_pneus(
    largura: int | None = None,
    perfil: int | None = None,
    aro: int | None = None,
    medida_texto: str | None = None,
    marca_modelo: str | None = None,
) -> dict:
    """Busca pneus no catálogo por dimensões, texto de medida ou marca/modelo.

    Parâmetros (todos opcionais, mas pelo menos um deve ser informado):
        largura: largura em mm (ex: 100, 110, 120)
        perfil: altura do perfil (ex: 80, 90)
        aro: diâmetro do aro em polegadas (ex: 17, 18)
        medida_texto: trecho da medida (ex: "100/80", "110/80-18")
        marca_modelo: nome da marca ou modelo (ex: "Pirelli", "Pilot Street")

    Retorna dict com lista de pneus encontrados e quantidade.
    """
    resultados: list[dict] = []

    if marca_modelo:
        resultados = catalogo_repo.buscar_pneus_por_marca_modelo(marca_modelo)
    elif medida_texto:
        resultados = catalogo_repo.buscar_pneus_por_medida_texto(medida_texto)
    else:
        resultados = catalogo_repo.buscar_pneus_por_dimensoes(
            largura=largura, perfil=perfil, aro=aro,
        )

    return {
        "quantidade": len(resultados),
        "pneus": resultados,
    }


def buscar_pneus_por_moto(termo_moto: str) -> dict:
    """Busca pneus compatíveis com uma moto pelo nome/modelo.

    Parâmetros:
        termo_moto: nome ou modelo da moto (ex: "CG 160", "Biz 125", "Factor 150")

    Retorna dict com pneus compatíveis agrupados por moto encontrada.
    """
    compatibilidades = catalogo_repo.buscar_compatibilidade_por_moto_texto(termo_moto)

    return {
        "quantidade": len(compatibilidades),
        "compatibilidades": compatibilidades,
    }


def buscar_detalhes_pneu(pneu_id: str) -> dict:
    """Busca detalhes completos de um pneu específico pelo ID.

    Parâmetros:
        pneu_id: UUID do pneu

    Retorna dict com dados do pneu ou mensagem de não encontrado.
    """
    pneu = catalogo_repo.buscar_pneu_por_id(UUID(pneu_id))
    if pneu is None:
        return {"encontrado": False, "mensagem": "Pneu não encontrado."}

    estoque = catalogo_repo.buscar_estoque_por_pneu(UUID(pneu_id))

    return {
        "encontrado": True,
        "pneu": pneu.model_dump(mode="json"),
        "estoque": estoque.model_dump(mode="json") if estoque else None,
    }
