# -*- coding: utf-8 -*-
"""
Validação topológica do perímetro do imóvel e das camadas internas.

Verifica:
- geometrias nulas, vazias ou inválidas (GEOS)
- vértices duplicados consecutivos
- imóvel multiparte (várias parcelas)
- sobreposição entre parcelas do próprio imóvel
- camadas internas (vegetação, área consolidada) extrapolando o perímetro
"""

from qgis.core import QgsPointXY

from .utils import area_ha, feicoes_no_src, recortar, subtrair, uniao

TOLERANCIA_VERTICE_M = 0.001   # 1 mm
AREA_MINIMA_SOBREPOSICAO_HA = 0.0001  # 1 m², abaixo disso é ruído numérico


def vertices_duplicados(geometria, tolerancia=TOLERANCIA_VERTICE_M):
    """Vértices consecutivos coincidentes (dentro da tolerância, em metros): lista dos pontos onde ocorrem."""
    pontos = []
    anterior = None
    for vertice in geometria.vertices():
        if anterior is not None and vertice.distance(anterior) < tolerancia:
            pontos.append(QgsPointXY(vertice.x(), vertice.y()))
        anterior = vertice
    return pontos


def contar_vertices_duplicados(geometria, tolerancia=TOLERANCIA_VERTICE_M):
    """Conta vértices consecutivos coincidentes (dentro da tolerância, em metros)."""
    return len(vertices_duplicados(geometria, tolerancia))


def validar_perimetro(camada, src_trabalho):
    """
    Valida as feições da camada de perímetro.

    Retorna (problemas, geometrias), onde:
    - problemas: lista de dicts {feicao, tipo, descricao, ponto}
    - geometrias: lista de (id_feicao, geometria no SRC de trabalho)
    """
    problemas = []
    geometrias = []

    for fid, _atrib, geom in feicoes_no_src(camada, src_trabalho):
        geometrias.append((fid, geom))

        # Vértices duplicados (checagem própria, com tolerância métrica)
        pontosDuplicados = vertices_duplicados(geom)
        duplicados = len(pontosDuplicados)

        # Validade GEOS — se já houver vértice duplicado, descarta o aviso equivalente
        # do GEOS ("duplicate"/"duplicados") para não repetir o mesmo problema
        for erro in geom.validateGeometry():
            if duplicados and "duplic" in erro.what().lower():
                continue
            ponto = erro.where() if erro.hasWhere() else geom.centroid().asPoint()
            problemas.append({
                "feicao": fid,
                "tipo": "Geometria inválida",
                "descricao": erro.what(),
                "ponto": ponto,
            })

        # Um ponto em cada vértice duplicado, para achar o local no mapa
        for ponto in pontosDuplicados:
            problemas.append({
                "feicao": fid,
                "tipo": "Vértices duplicados",
                "descricao": f"Vértice repetido em sequência ({duplicados} na feição): apague um deles.",
                "ponto": ponto,
            })

        # Multiparte
        if geom.isMultipart():
            n_partes = len(geom.asGeometryCollection())
            if n_partes > 1:
                problemas.append({
                    "feicao": fid,
                    "tipo": "Imóvel multiparte",
                    "descricao": (f"{n_partes} partes. Confirme se as parcelas pertencem ao mesmo "
                                  "imóvel (ex.: divididas por estrada ou rio)."),
                    "ponto": geom.centroid().asPoint(),
                })

    # Sobreposição entre parcelas do próprio imóvel
    for i in range(len(geometrias)):
        for j in range(i + 1, len(geometrias)):
            fid_a, ga = geometrias[i]
            fid_b, gb = geometrias[j]
            if not ga.boundingBox().intersects(gb.boundingBox()):
                continue
            inter = recortar(ga, gb)
            if area_ha(inter) > AREA_MINIMA_SOBREPOSICAO_HA:
                problemas.append({
                    "feicao": f"{fid_a} × {fid_b}",
                    "tipo": "Sobreposição entre parcelas",
                    "descricao": f"{area_ha(inter):.4f} ha sobrepostos.",
                    "ponto": inter.centroid().asPoint(),
                })

    if not geometrias:
        raise ValueError("A camada de perímetro não possui geometrias válidas.")

    return problemas, geometrias


def verificar_extrapolacao(camada, nome_tema, perimetro, src_trabalho):
    """
    Verifica se uma camada interna ultrapassa o perímetro do imóvel.

    Retorna (geometria_unida_recortada, problema_ou_None).
    """
    if camada is None:
        return None, None

    geoms = [g for _fid, _a, g in feicoes_no_src(camada, src_trabalho, perimetro.boundingBox())]
    total = uniao([g.makeValid() for g in geoms])
    if total.isEmpty():
        return total, None

    fora = subtrair(total, perimetro)
    problema = None
    area_fora = area_ha(fora)
    if area_fora > AREA_MINIMA_SOBREPOSICAO_HA:
        problema = {
            "feicao": "-",
            "tipo": f"{nome_tema} fora do perímetro",
            "descricao": f"{area_fora:.4f} ha de '{nome_tema}' estão fora do perímetro do imóvel.",
            "ponto": fora.centroid().asPoint(),
        }
    return recortar(total, perimetro), problema
