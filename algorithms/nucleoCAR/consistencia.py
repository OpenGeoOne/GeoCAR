# -*- coding: utf-8 -*-
"""
Consistência entre as camadas declaradas no CAR.

Verifica, no SRC de trabalho (UTM):
- feições fora da ATI;
- sobreposição entre camadas de cobertura do solo (vegetação nativa, área consolidada, pousio...);
- sobreposição entre camadas de Reserva Legal;
- servidão administrativa sobre Reserva Legal;
- Reserva Legal sem vegetação nativa (a recompor) — aviso;
- área da ATI sem cobertura do solo declarada — aviso.
"""

from itertools import combinations

from .utils import area_ha, feicoes_no_src, recortar, subtrair, uniao

AREA_MINIMA_HA = 0.0001  # 1 m²

ERRO = "Erro"
AVISO = "Aviso"


def _uniaoCamada(camada, src):
    """União das geometrias válidas da camada no SRC de trabalho, ou None se vazia."""
    geometrias = [g.makeValid() for _fid, _atrib, g in feicoes_no_src(camada, src)
                  if g is not None and not g.isEmpty()]
    if not geometrias:
        return None
    geometria = uniao(geometrias)
    return None if geometria is None or geometria.isEmpty() else geometria


def _registrar(itens, gravidade, tipo, camadas, geometria, descricao):
    """Acrescenta o item se a área for significativa."""
    if geometria is None or geometria.isEmpty():
        return
    area = area_ha(geometria)
    if area <= AREA_MINIMA_HA:
        return
    itens.append({"gravidade": gravidade, "tipo": tipo, "camadas": camadas,
                  "area_ha": area, "descricao": descricao, "geometria": geometria})


def verificar_consistencia(perimetro, src, vegetacao=None, coberturas=(), reservas=(), servidoes=()):
    """
    perimetro: geometria da ATI no SRC de trabalho.
    vegetacao: camada de vegetação nativa (ou None).
    coberturas, reservas, servidoes: listas de camadas poligonais.

    Retorna lista de dicts {gravidade, tipo, camadas, area_ha, descricao, geometria},
    com os erros primeiro e, dentro de cada gravidade, da maior para a menor área.
    """
    itens = []
    grupos = {"cobertura": [], "reserva": [], "servidao": []}
    vistos = set()
    for chave, camadas in (("cobertura", [vegetacao] + list(coberturas)), ("reserva", reservas),
                           ("servidao", servidoes)):
        for camada in camadas:
            if camada is None or camada.id() in vistos:
                continue
            vistos.add(camada.id())
            geometria = _uniaoCamada(camada, src)
            if geometria is not None:
                grupos[chave].append((camada.name(), geometria))

    # 1. Feições fora da ATI
    for chave in grupos:
        for nome, geometria in grupos[chave]:
            _registrar(itens, ERRO, "Fora da ATI", nome, subtrair(geometria, perimetro),
                       "Parte da camada está fora da Área Total do Imóvel.")

    # 2. Sobreposição entre coberturas do solo e entre Reservas Legais
    for chave, tipo in (("cobertura", "Sobreposição entre coberturas do solo"),
                        ("reserva", "Sobreposição entre Reservas Legais")):
        for (nomeA, geomA), (nomeB, geomB) in combinations(grupos[chave], 2):
            _registrar(itens, ERRO, tipo, f"{nomeA} × {nomeB}", recortar(geomA, geomB),
                       "A mesma área foi declarada em duas camadas que não podem se sobrepor.")

    reserva = uniao([g for _n, g in grupos["reserva"]]) if grupos["reserva"] else None

    # 3. Servidão administrativa sobre Reserva Legal
    if reserva is not None:
        for nome, geometria in grupos["servidao"]:
            _registrar(itens, ERRO, "Servidão administrativa sobre Reserva Legal", nome,
                       recortar(geometria, reserva),
                       "A Reserva Legal não pode ser proposta sobre área de servidão administrativa.")

    # 4. Reserva Legal sem vegetação nativa (a recompor)
    if reserva is not None and vegetacao is not None:
        geomVegetacao = next((g for n, g in grupos["cobertura"] if n == vegetacao.name()), None)
        semVegetacao = subtrair(recortar(reserva, perimetro), geomVegetacao) if geomVegetacao is not None \
            else recortar(reserva, perimetro)
        _registrar(itens, AVISO, "Reserva Legal sem vegetação nativa", "Reserva Legal", semVegetacao,
                   "Trecho da Reserva Legal sem vegetação nativa: deve ser recomposto (PRA).")

    # 5. Área da ATI sem cobertura do solo declarada
    if grupos["cobertura"]:
        declarada = uniao([g for _n, g in grupos["cobertura"]] + [g for _n, g in grupos["servidao"]])
        _registrar(itens, AVISO, "Área sem cobertura do solo declarada", "ATI", subtrair(perimetro, declarada),
                   "Parte da ATI não foi classificada em nenhuma camada de cobertura do solo ou servidão.")

    itens.sort(key=lambda i: (i["gravidade"] != ERRO, -i["area_ha"]))
    return itens
