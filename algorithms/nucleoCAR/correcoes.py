# -*- coding: utf-8 -*-
"""
Funções das ferramentas de correção (grupo 4).

As correções são feitas no modo de edição das camadas, sem salvar: o usuário confere no mapa e salva ou
descarta (Ctrl+Z funciona). Os cálculos de área usam o SIRGAS 2000 / UTM do imóvel.
"""

from qgis.core import QgsCoordinateTransform, QgsGeometry, QgsProject, QgsWkbTypes

from .utils import src_utm_sirgas

AREA_MINIMA_M2 = 1.0   # abaixo disso é ruído numérico


def apenasPoligonos(geometria):
    """Só as partes poligonais (o makeValid pode devolver linhas ou pontos soltos)."""
    if geometria is None or geometria.isEmpty():
        return QgsGeometry()
    if QgsWkbTypes.geometryType(geometria.wkbType()) == QgsWkbTypes.PolygonGeometry \
            and QgsWkbTypes.flatType(geometria.wkbType()) in (QgsWkbTypes.Polygon, QgsWkbTypes.MultiPolygon):
        return geometria
    partes = [p for p in geometria.asGeometryCollection()
              if QgsWkbTypes.geometryType(p.wkbType()) == QgsWkbTypes.PolygonGeometry and not p.isEmpty()]
    return QgsGeometry.unaryUnion(partes) if partes else QgsGeometry()


def ajustarTipo(geometria, camada):
    """Geometria no tipo da camada (simples ou multi)."""
    geometria = apenasPoligonos(geometria)
    if geometria.isEmpty():
        return geometria
    if QgsWkbTypes.isMultiType(camada.wkbType()):
        geometria.convertToMultiType()
    elif geometria.isMultipart():
        partes = geometria.asGeometryCollection()
        if len(partes) == 1:
            geometria = partes[0]
    return geometria


def editar(camada):
    """Liga o modo de edição, se ainda não estiver ligado. Retorna True se ligou agora."""
    if camada.isEditable():
        return False
    return camada.startEditing()


def finalizar(camada, ligouAgora, alterou, salvar):
    """Salva (se pedido) ou deixa em edição para revisão; sem alteração, desliga a edição que ligou."""
    if salvar and alterou:
        camada.commitChanges()
    elif ligouAgora and not alterou:
        camada.rollBack()
    camada.triggerRepaint()


def srcDaAti(camadaAti):
    """SRC métrico (UTM SIRGAS 2000) do imóvel."""
    geometrias = [f.geometry() for f in camadaAti.getFeatures() if f.hasGeometry()]
    return src_utm_sirgas(QgsGeometry.unaryUnion(geometrias), camadaAti.crs())


class Conversor:
    """Ida e volta entre o SRC de uma camada e o UTM do imóvel."""

    def __init__(self, camada, src):
        projeto = QgsProject.instance()
        self.ida = QgsCoordinateTransform(camada.crs(), src, projeto)
        self.volta = QgsCoordinateTransform(src, camada.crs(), projeto)

    def paraUtm(self, geometria):
        g = QgsGeometry(geometria)
        g.transform(self.ida)
        return g

    def paraCamada(self, geometria):
        g = QgsGeometry(geometria)
        g.transform(self.volta)
        return g


def uniaoAti(camadaAti, src):
    conversor = Conversor(camadaAti, src)
    return QgsGeometry.unaryUnion([conversor.paraUtm(f.geometry()).makeValid()
                                   for f in camadaAti.getFeatures() if f.hasGeometry()])


def toleranciaNaCamada(camada, metros):
    """Tolerância em unidades da camada (graus quando o SRC é geográfico)."""
    return metros / 111320.0 if camada.crs().isGeographic() else metros


def contarVertices(geometria):
    return sum(1 for _ in geometria.vertices())


def prioridadeCobertura(nome, consolidadaPrimeiro=False):
    """Ordem de prevalência na sobreposição entre coberturas do solo (menor = prevalece)."""
    n = nome.lower()
    vegetacao, consolidada = (1, 0) if consolidadaPrimeiro else (0, 1)
    if 'vegeta' in n or n == 'avn':
        return vegetacao
    if 'consolid' in n or n == 'ac':
        return consolidada
    if 'pousio' in n:
        return 2
    return 3


def prioridadeReserva(nome):
    """Ordem de prevalência entre Reservas Legais: averbada > aprovada > demais > proposta."""
    n = nome.lower()
    if 'proposta' in n or 'restauracao' in n:
        return 3
    if 'averbada' in n and 'nao' not in n:
        return 0
    if 'aprovada' in n:
        return 1
    return 2


def uniaoUtm(camadas, src):
    """União das feições das camadas no UTM do imóvel (geometria vazia se não houver)."""
    geometrias = []
    for camada in camadas:
        conversor = Conversor(camada, src)
        geometrias += [conversor.paraUtm(f.geometry()).makeValid() for f in camada.getFeatures() if f.hasGeometry()]
    return QgsGeometry.unaryUnion(geometrias) if geometrias else QgsGeometry()
