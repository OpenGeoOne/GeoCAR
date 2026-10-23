# -*- coding: utf-8 -*-
"""
Sobreposição do perímetro do imóvel com camadas de restrição.

Exemplos de camadas: CARs vizinhos (base pública do SICAR), parcelas SIGEF,
Unidades de Conservação, Terras Indígenas, assentamentos, embargos.
"""

from .utils import area_ha, feicoes_no_src, recortar

AREA_MINIMA_HA = 0.0001  # 1 m²

# Classificação das sobreposições
CLASSE_DIVISA = "Ajuste de divisa"
CLASSE_RELEVANTE = "Sobreposição relevante"
LARGURA_DIVISA_PADRAO = 15.0   # m — largura média máxima de uma lasca de divisa
PERC_DIVISA_PADRAO = 2.0       # % — fração máxima do imóvel para ser tratada como ajuste de divisa


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


def largura_media(geom):
    """Largura média da faixa (m): 2·A/P, exata para faixas estreitas e longas."""
    perimetro = geom.length()
    return 2.0 * geom.area() / perimetro if perimetro > 0 else 0.0


def classificar(largura_m, percentual, largura_divisa=LARGURA_DIVISA_PADRAO, perc_divisa=PERC_DIVISA_PADRAO):
    """Ajuste de divisa: faixa estreita (largura média <= limite) E pequena (% do imóvel <= limite)."""
    if largura_m <= largura_divisa and percentual <= perc_divisa:
        return CLASSE_DIVISA
    return CLASSE_RELEVANTE


def analisar_sobreposicoes(perimetro, area_imovel_ha, camadas, src_trabalho,
                           largura_divisa=LARGURA_DIVISA_PADRAO, perc_divisa=PERC_DIVISA_PADRAO):
    """
    Cruza o perímetro com cada camada de restrição.

    Cada sobreposição é classificada em "Ajuste de divisa" (lasca estreita ao longo do limite,
    típica de digitalização sobre imagens diferentes) ou "Sobreposição relevante" (conflito de área).

    Retorna lista de dicts:
    {camada, feicao, identificador, area_ha, percentual, largura_m, classe, geometria}
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
            percentual = (area / area_imovel_ha * 100.0) if area_imovel_ha else 0.0
            largura = largura_media(inter)
            resultados.append({
                "camada": camada.name(),
                "feicao": fid,
                "identificador": _identificador(atributos),
                "area_ha": area,
                "percentual": percentual,
                "largura_m": largura,
                "classe": classificar(largura, percentual, largura_divisa, perc_divisa),
                "geometria": inter,
            })

    # Relevantes primeiro; dentro de cada classe, da maior para a menor área
    resultados.sort(key=lambda r: (r["classe"] != CLASSE_RELEVANTE, -r["area_ha"]))
    return resultados
