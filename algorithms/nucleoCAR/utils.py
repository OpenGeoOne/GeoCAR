# -*- coding: utf-8 -*-
"""
Funções utilitárias do CAR Pré-Análise.

- Compatibilidade entre QGIS 3.x (Qt5) e QGIS 4.x (Qt6)
- Escolha automática de SRC métrico (SIRGAS 2000 / UTM)
- Transformação de geometrias e criação de camadas de memória
"""

from qgis.core import (
    Qgis,
    QgsCoordinateReferenceSystem,
    QgsCoordinateTransform,
    QgsFeature,
    QgsFeatureRequest,
    QgsGeometry,
    QgsPointXY,
    QgsProject,
    QgsVectorLayer,
    QgsWkbTypes,
)

SRC_GEOGRAFICO_SIRGAS = "EPSG:4674"


# ---------------------------------------------------------------------------
# Compatibilidade Qt5 / Qt6
# ---------------------------------------------------------------------------
def enum_compat(classe, escopo, nome):
    """
    Retorna um valor de enum funcionando com enums com escopo (Qt6/QGIS 4)
    e sem escopo (Qt5/QGIS 3).

    Exemplo: enum_compat(Qt, "CursorShape", "WaitCursor")
    """
    alvo = getattr(classe, escopo, classe)
    return getattr(alvo, nome)


def tipo_geometria(camada):
    """Retorna 'ponto', 'linha', 'poligono' ou None para uma camada vetorial."""
    gt = camada.geometryType()
    try:
        mapa = {
            Qgis.GeometryType.Point: "ponto",
            Qgis.GeometryType.Line: "linha",
            Qgis.GeometryType.Polygon: "poligono",
        }
    except AttributeError:
        mapa = {
            QgsWkbTypes.PointGeometry: "ponto",
            QgsWkbTypes.LineGeometry: "linha",
            QgsWkbTypes.PolygonGeometry: "poligono",
        }
    return mapa.get(gt)


# ---------------------------------------------------------------------------
# SRC e transformações
# ---------------------------------------------------------------------------
def src_utm_sirgas(geometria, src_origem):
    """
    Define o SRC SIRGAS 2000 / UTM do fuso que contém o centróide da geometria.

    Hemisfério Sul: EPSG 31960 + fuso (18S = 31978 ... 25S = 31985)
    Hemisfério Norte: EPSG 31954 + fuso (18N = 31972 ... 22N = 31976)
    """
    centro = geometria.centroid().asPoint()
    if not src_origem.isGeographic():
        transf = QgsCoordinateTransform(
            src_origem,
            QgsCoordinateReferenceSystem(SRC_GEOGRAFICO_SIRGAS),
            QgsProject.instance(),
        )
        centro = transf.transform(QgsPointXY(centro))

    lon, lat = centro.x(), centro.y()
    fuso = int((lon + 180.0) / 6.0) + 1
    epsg = 31960 + fuso if lat < 0 else 31954 + fuso
    src = QgsCoordinateReferenceSystem(f"EPSG:{epsg}")
    if not src.isValid():
        raise ValueError(f"Não foi possível definir o SRC UTM (EPSG:{epsg}).")
    return src


def transformar(geometria, src_origem, src_destino):
    """Retorna uma cópia da geometria transformada para o SRC de destino."""
    g = QgsGeometry(geometria)
    if src_origem != src_destino:
        transf = QgsCoordinateTransform(src_origem, src_destino, QgsProject.instance())
        g.transform(transf)
    return g


def feicoes_no_src(camada, src_destino, retangulo_destino=None):
    """
    Gera tuplas (id_feicao, atributos_dict, geometria_no_src_destino).

    Se 'retangulo_destino' for informado (no SRC de destino), filtra
    espacialmente as feições para acelerar o processamento.
    """
    requisicao = QgsFeatureRequest()
    if retangulo_destino is not None:
        transf_inv = QgsCoordinateTransform(src_destino, camada.crs(), QgsProject.instance())
        requisicao.setFilterRect(transf_inv.transformBoundingBox(retangulo_destino))

    nomes = [c.name() for c in camada.fields()]
    for f in camada.getFeatures(requisicao):
        if not f.hasGeometry() or f.geometry().isEmpty():
            continue
        atributos = {n: f[n] for n in nomes}
        yield f.id(), atributos, transformar(f.geometry(), camada.crs(), src_destino)


# ---------------------------------------------------------------------------
# Geometria
# ---------------------------------------------------------------------------
def uniao(geometrias):
    """União de uma lista de geometrias; retorna geometria vazia se a lista for vazia."""
    validas = [g for g in geometrias if g is not None and not g.isEmpty()]
    if not validas:
        return QgsGeometry()
    if len(validas) == 1:
        return QgsGeometry(validas[0])
    return QgsGeometry.unaryUnion(validas)


def area_ha(geometria):
    """Área em hectares (a geometria deve estar em SRC métrico)."""
    if geometria is None or geometria.isEmpty():
        return 0.0
    return geometria.area() / 10000.0


def recortar(geometria, mascara):
    """Interseção segura entre duas geometrias."""
    if geometria is None or mascara is None or geometria.isEmpty() or mascara.isEmpty():
        return QgsGeometry()
    return geometria.intersection(mascara)


def subtrair(geometria, outra):
    """Diferença segura entre duas geometrias."""
    if geometria is None or geometria.isEmpty():
        return QgsGeometry()
    if outra is None or outra.isEmpty():
        return QgsGeometry(geometria)
    return geometria.difference(outra)


# ---------------------------------------------------------------------------
# Camadas de memória
# ---------------------------------------------------------------------------
def criar_camada_memoria(nome, tipo, src, campos):
    """
    Cria uma camada de memória.

    tipo: 'Point', 'LineString', 'Polygon', 'MultiPolygon'...
    campos: lista de tuplas (nome_campo, 'string' | 'double' | 'integer')
    """
    definicao_campos = "".join(f"&field={n}:{t}" for n, t in campos)
    uri = f"{tipo}?crs={src.authid()}{definicao_campos}"
    camada = QgsVectorLayer(uri, nome, "memory")
    if not camada.isValid():
        raise RuntimeError(f"Falha ao criar a camada de memória '{nome}'.")
    return camada


def extrair_poligonos(geometria):
    """
    Mantém apenas as partes poligonais de uma geometria (interseções podem
    gerar GeometryCollection com linhas e pontos) e converte para multiparte.
    """
    if geometria is None or geometria.isEmpty():
        return QgsGeometry()
    if tipo_geometria_geom(geometria) == "poligono" and not _eh_colecao(geometria):
        g = QgsGeometry(geometria)
        g.convertToMultiType()
        return g
    partes = [p for p in geometria.asGeometryCollection()
              if tipo_geometria_geom(p) == "poligono"]
    g = uniao(partes)
    if not g.isEmpty():
        g.convertToMultiType()
    return g


def tipo_geometria_geom(geometria):
    """Igual a tipo_geometria(), mas para um objeto QgsGeometry."""
    gt = geometria.type()
    try:
        mapa = {
            Qgis.GeometryType.Point: "ponto",
            Qgis.GeometryType.Line: "linha",
            Qgis.GeometryType.Polygon: "poligono",
        }
    except AttributeError:
        mapa = {
            QgsWkbTypes.PointGeometry: "ponto",
            QgsWkbTypes.LineGeometry: "linha",
            QgsWkbTypes.PolygonGeometry: "poligono",
        }
    return mapa.get(gt)


def _eh_colecao(geometria):
    """True se a geometria for uma GeometryCollection genérica."""
    nome = QgsWkbTypes.displayString(geometria.wkbType()).lower()
    return "geometrycollection" in nome


def adicionar_feicao(camada, geometria, valores):
    """Adiciona uma feição com geometria e lista de valores à camada de memória."""
    if geometria is None or geometria.isEmpty():
        return
    if tipo_geometria(camada) == "poligono":
        geometria = extrair_poligonos(geometria)
        if geometria.isEmpty():
            return
    feicao = QgsFeature(camada.fields())
    feicao.setGeometry(geometria)
    feicao.setAttributes(list(valores))
    camada.dataProvider().addFeatures([feicao])
    camada.updateExtents()
