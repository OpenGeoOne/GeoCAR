# -*- coding: utf-8 -*-
"""
Validação topológica do perímetro do imóvel e das camadas internas.

Verifica:
- geometrias nulas, vazias ou inválidas (GEOS)
- vértices duplicados consecutivos
- vértices muito próximos (menos de 5 cm) e agulhas (pontas finas em que o limite vai e volta)
- imóvel multiparte (várias parcelas)
- sobreposição entre parcelas do próprio imóvel
- camadas internas (vegetação, área consolidada) extrapolando o perímetro
"""

import math

from qgis.core import QgsPointXY

from .utils import area_ha, feicoes_no_src, recortar, subtrair, uniao

TOLERANCIA_VERTICE_M = 0.001   # 1 mm
AREA_MINIMA_SOBREPOSICAO_HA = 0.0001  # 1 m², abaixo disso é ruído numérico
TOLERANCIA_PROXIMO_M = 0.05    # vértices a menos de 5 cm um do outro: ruído de digitalização
ANGULO_AGULHA_GRAUS = 1.0      # ângulo interno abaixo disso: ponta fina (agulha)
VERTICE_MUITO_PROXIMO = "Vértices muito próximos"
AGULHA = "Agulha"


def vertices_duplicados(geometria, tolerancia=TOLERANCIA_VERTICE_M):
    """Vértices consecutivos coincidentes (dentro da tolerância, em metros): lista dos pontos onde ocorrem."""
    pontos = []
    anterior = None
    for vertice in geometria.vertices():
        if anterior is not None and vertice.distance(anterior) < tolerancia:
            pontos.append(QgsPointXY(vertice.x(), vertice.y()))
        anterior = vertice
    return pontos


def grupos_duplicados(pontos, tolerancia=TOLERANCIA_VERTICE_M):
    """Junta os vértices repetidos no mesmo local: lista de (ponto, quantas cópias a mais)."""
    grupos = []
    for ponto in pontos:
        if grupos and grupos[-1][0].distance(ponto) < tolerancia:
            grupos[-1][1] += 1
        else:
            grupos.append([ponto, 1])
    return [(p, n) for p, n in grupos]


def _angulo(a, p, b):
    """Ângulo em p (graus, 0 a 180) entre os segmentos p-a e p-b."""
    ux, uy, wx, wy = a.x() - p.x(), a.y() - p.y(), b.x() - p.x(), b.y() - p.y()
    return math.degrees(math.atan2(abs(ux * wy - uy * wx), ux * wx + uy * wy))


def vertices_suspeitos(geometria, tolerancia_proximo=TOLERANCIA_PROXIMO_M, angulo_agulha=ANGULO_AGULHA_GRAUS):
    """
    Vértices a apagar, com a geometria num SRC métrico: lista de (número do vértice, tipo, ponto, valor).
    - Vértices muito próximos: o segundo de dois vértices seguidos a menos da tolerância (valor = distância em m).
      Os duplicados (menos de 1 mm) ficam de fora, pois têm checagem própria.
    - Agulha: vértice com ângulo interno menor que o limite (valor = ângulo em graus).
    Anéis com menos de 4 vértices não são avaliados (apagar um vértice desfaria o polígono).
    """
    aneis = {}
    for n, vertice in enumerate(geometria.vertices()):
        _ok, vid = geometria.vertexIdFromVertexNr(n)
        aneis.setdefault((vid.part, vid.ring), []).append((n, vertice))
    saida = []
    for lista in aneis.values():
        if len(lista) > 1 and lista[0][1].distance(lista[-1][1]) < 1e-9:
            lista = lista[:-1]   # o último repete o primeiro (anel fechado)
        m = len(lista)
        if m < 4:
            continue
        for k in range(m):
            n, p = lista[k]
            nProximo, b = lista[(k + 1) % m]
            _nAnterior, a = lista[k - 1]
            distancia = p.distance(b)
            if TOLERANCIA_VERTICE_M <= distancia < tolerancia_proximo:
                saida.append((nProximo if (k + 1) % m else n, VERTICE_MUITO_PROXIMO,
                              QgsPointXY(p.x(), p.y()), distancia))
            if p.distance(a) < tolerancia_proximo or distancia < tolerancia_proximo:
                continue
            angulo = _angulo(a, p, b)
            if angulo < angulo_agulha:
                saida.append((n, AGULHA, QgsPointXY(p.x(), p.y()), angulo))
    return saida


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

        # Um ponto em cada local com vértice repetido, para achar no mapa
        for ponto, copias in grupos_duplicados(pontosDuplicados):
            problemas.append({
                "feicao": fid,
                "tipo": "Vértices duplicados",
                "descricao": (f"{copias + 1} vértices no mesmo lugar, em sequência: apague "
                              f"{'um deles' if copias == 1 else f'{copias} deles'}."),
                "ponto": ponto,
            })

        # Vértices muito próximos e agulhas
        for _n, tipo, ponto, valor in vertices_suspeitos(geom):
            descricao = (f"Ponta fina de {valor:.2f}° (o limite vai e volta): apague o vértice da ponta."
                         if tipo == AGULHA else
                         f"2 vértices a {valor * 100:.1f} cm um do outro: apague um deles.")
            problemas.append({"feicao": fid, "tipo": tipo, "descricao": descricao, "ponto": ponto})

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
