# -*- coding: utf-8 -*-
"""
Sobreposição do perímetro do imóvel com camadas de restrição.

Exemplos de camadas: CARs vizinhos (base pública do SICAR), parcelas SIGEF,
Unidades de Conservação, Terras Indígenas, assentamentos, embargos.
"""

from .utils import area_ha, feicoes_no_src, recortar

AREA_MINIMA_HA = 0.0001  # 1 m²


def _identificador(atributos):
    """Tenta montar um identificador legível a partir de campos comuns."""
    candidatos = ("cod_imovel", "codigo", "cod_car", "nome", "nome_uc", "terrai_nom",
                  "parcela_co", "codigo_imo", "id")
    chaves = {k.lower(): k for k in atributos}
    for c in candidatos:
        if c in chaves:
            valor = atributos[chaves[c]]
            if valor not in (None, ""):
                return str(valor)
    return ""


def analisar_sobreposicoes(perimetro, area_imovel_ha, camadas, src_trabalho):
    """
    Cruza o perímetro com cada camada de restrição.

    Retorna lista de dicts:
    {camada, feicao, identificador, area_ha, percentual, geometria}
    """
    resultados = []
    retangulo = perimetro.boundingBox()

    for camada in camadas:
        for fid, atributos, geom in feicoes_no_src(camada, src_trabalho, retangulo):
            if not geom.boundingBox().intersects(retangulo):
                continue
            inter = recortar(perimetro, geom.makeValid())
            area = area_ha(inter)
            if area <= AREA_MINIMA_HA:
                continue
            resultados.append({
                "camada": camada.name(),
                "feicao": fid,
                "identificador": _identificador(atributos),
                "area_ha": area,
                "percentual": (area / area_imovel_ha * 100.0) if area_imovel_ha else 0.0,
                "geometria": inter,
            })

    resultados.sort(key=lambda r: r["area_ha"], reverse=True)
    return resultados
