# -*- coding: utf-8 -*-
"""
Mapa do imóvel em PDF (prancha A4 paisagem), montado como layout do QGIS.

Mapa com a ATI e as camadas declaradas sobre a imagem de fundo, grade em coordenadas UTM, legenda, quadro de
áreas, escala, norte e identificação. O layout fica no projeto (Projeto > Layouts) para ajustes finos.
"""

import math
import os
from datetime import datetime

from qgis.PyQt.QtCore import QPointF, QRectF
from qgis.PyQt.QtGui import QColor, QFont
from qgis.core import (QgsCoordinateTransform, QgsDistanceArea, QgsGeometry, QgsLayerTree, QgsLayoutExporter, QgsLayoutItemLabel,
                       QgsLayoutItemLegend, QgsLayoutItemMap, QgsLayoutItemMapGrid, QgsLayoutItemPicture,
                       QgsLayoutItemScaleBar, QgsLayoutMeasurement, QgsLayoutPoint, QgsLayoutSize,
                       QgsLegendStyle, QgsMapLayer, QgsPrintLayout, QgsRectangle, QgsTextFormat, QgsUnitTypes,
                       QgsWkbTypes)

NOME_LAYOUT = 'GeoCAR - Mapa do imóvel'
SETA_NORTE = ':/images/north_arrows/layout_default_north_arrow.svg'
LARGURA, ALTURA, MARGEM = 297.0, 210.0, 8.0
MAPA_LARGURA = 192.0
PAINEL_X = MARGEM + MAPA_LARGURA + 5.0
PAINEL_L = LARGURA - PAINEL_X - MARGEM


def _texto(tamanho, negrito=False, cor='#1f2933'):
    fonte = QFont('Arial')
    fonte.setBold(negrito)
    formato = QgsTextFormat()
    formato.setFont(fonte)
    formato.setSize(tamanho)
    formato.setSizeUnit(QgsUnitTypes.RenderPoints)
    formato.setColor(QColor(cor))
    return formato


def _rotulo(layout, texto, x, y, largura, altura, tamanho=8, negrito=False, html=False, cor='#1f2933'):
    item = QgsLayoutItemLabel(layout)
    item.setText(texto)
    if html:
        item.setMode(QgsLayoutItemLabel.ModeHtml)
    item.setTextFormat(_texto(tamanho, negrito, cor))
    item.attemptMove(QgsLayoutPoint(x, y))
    item.attemptResize(QgsLayoutSize(largura, altura))
    layout.addLayoutItem(item)
    return item


def _intervalo(comprimento):
    """Intervalo 'redondo' da grade para cerca de 4 linhas."""
    bruto = comprimento / 4.0
    base = 10 ** math.floor(math.log10(bruto))
    for fator in (1, 2, 2.5, 5, 10):
        if base * fator >= bruto:
            return base * fator
    return base * 10


def _medidor(crs, projeto):
    """Área elipsoidal, como o campo 'area' das RAIZ (elipsoide do projeto)."""
    medidor = QgsDistanceArea()
    medidor.setSourceCrs(crs, projeto.transformContext())
    medidor.setEllipsoid(projeto.ellipsoid() if projeto.ellipsoid() not in ('', 'NONE') else 'EPSG:7019')
    return medidor


def _area_na_ati(camada, ati, crsAti, projeto):
    """Área elipsoidal (ha) da camada poligonal dentro da ATI."""
    if camada.geometryType() != QgsWkbTypes.PolygonGeometry:
        return None
    transformacao = QgsCoordinateTransform(camada.crs(), crsAti, projeto)
    geometrias = []
    for f in camada.getFeatures():
        if f.hasGeometry():
            g = QgsGeometry(f.geometry())
            g.transform(transformacao)
            geometrias.append(g.makeValid())
    if not geometrias:
        return None
    return _medidor(crsAti, projeto).measureArea(QgsGeometry.unaryUnion(geometrias).intersection(ati)) / 1e4


def _ha(valor):
    return f'{valor:,.4f}'.replace(',', 'X').replace('.', ',').replace('X', '.')


def gerar_mapa(projeto, camadaAti, camadas, fundo, identificacao, caminho, src, manterLayout=True):
    """
    Monta o layout e exporta o PDF. camadas: camadas vetoriais a mostrar (a ATI entra sempre, por cima);
    fundo: camada raster de fundo (ou None); identificacao: lista de (rótulo, valor).
    Retorna o caminho do PDF.
    """
    gerente = projeto.layoutManager()
    antigo = gerente.layoutByName(NOME_LAYOUT)
    if antigo is not None:
        gerente.removeLayout(antigo)
    layout = QgsPrintLayout(projeto)
    layout.initializeDefaults()
    layout.setName(NOME_LAYOUT)
    pagina = layout.pageCollection().page(0)
    pagina.setPageSize(QgsLayoutSize(LARGURA, ALTURA))

    # Ordem de desenho: a da árvore de camadas do projeto; ATI por cima, fundo por baixo
    ordem = [c for c in projeto.layerTreeRoot().layerOrder() if c in camadas and c.id() != camadaAti.id()]
    mostrar = [camadaAti] + ordem + ([fundo] if fundo is not None else [])

    # Mapa
    alturaMapa = ALTURA - 2 * MARGEM - 8.0
    mapa = QgsLayoutItemMap(layout)
    mapa.attemptMove(QgsLayoutPoint(MARGEM + 6.0, MARGEM + 4.0))
    mapa.attemptResize(QgsLayoutSize(MAPA_LARGURA - 8.0, alturaMapa - 4.0))
    mapa.setCrs(src)
    mapa.setLayers(mostrar)
    mapa.setKeepLayerSet(True)
    mapa.setFrameEnabled(True)
    extensao = QgsCoordinateTransform(camadaAti.crs(), src, projeto).transformBoundingBox(camadaAti.extent())
    extensao.scale(1.15)
    razao = (MAPA_LARGURA - 8.0) / (alturaMapa - 4.0)
    if extensao.width() / extensao.height() < razao:
        extensao = QgsRectangle.fromCenterAndSize(extensao.center(), extensao.height() * razao, extensao.height())
    else:
        extensao = QgsRectangle.fromCenterAndSize(extensao.center(), extensao.width(), extensao.width() / razao)
    mapa.setExtent(extensao)
    escala = mapa.scale()
    for passo in (500, 1000, 2000, 2500, 5000, 10000, 25000, 50000, 100000):
        if escala <= passo * 10:
            mapa.setScale(math.ceil(escala / passo) * passo)
            break
    layout.addLayoutItem(mapa)

    # Grade UTM
    grade = QgsLayoutItemMapGrid('Grade UTM', mapa)
    grade.setCrs(src)
    intervalo = _intervalo(mapa.extent().width())
    grade.setIntervalX(intervalo)
    grade.setIntervalY(intervalo)
    grade.setStyle(QgsLayoutItemMapGrid.Cross)
    grade.setCrossLength(2.0)
    grade.setAnnotationEnabled(True)
    grade.setAnnotationPrecision(0)
    grade.setAnnotationTextFormat(_texto(5.5))
    for lado in (QgsLayoutItemMapGrid.Left, QgsLayoutItemMapGrid.Right):
        grade.setAnnotationDirection(QgsLayoutItemMapGrid.Vertical, lado)
    for lado in (QgsLayoutItemMapGrid.Left, QgsLayoutItemMapGrid.Right, QgsLayoutItemMapGrid.Top,
                 QgsLayoutItemMapGrid.Bottom):
        grade.setAnnotationPosition(QgsLayoutItemMapGrid.OutsideMapFrame, lado)
    grade.setFrameStyle(QgsLayoutItemMapGrid.Zebra)
    grade.setFrameWidth(1.2)
    mapa.grids().addGrid(grade)
    mapa.updateBoundingRect()

    # Painel da direita
    y = MARGEM
    _rotulo(layout, 'MAPA DO IMÓVEL RURAL', PAINEL_X, y, PAINEL_L, 7, 12, True, cor='#1b5e20')
    y += 8
    nomeImovel = dict(identificacao).get('Imóvel') or camadaAti.name()
    _rotulo(layout, nomeImovel, PAINEL_X, y, PAINEL_L, 6, 9, True)
    y += 7
    linhas = [f'<b>{r}:</b> {v}' for r, v in identificacao if v and r != 'Imóvel']
    ati = QgsGeometry.unaryUnion([QgsGeometry(f.geometry()).makeValid() for f in camadaAti.getFeatures()
                                  if f.hasGeometry()])
    linhas.append(f'<b>Área total do imóvel:</b> {_ha(_medidor(camadaAti.crs(), projeto).measureArea(ati) / 1e4)} ha')
    altura = 4.0 * len(linhas) + 2
    _rotulo(layout, '<br>'.join(linhas), PAINEL_X, y, PAINEL_L, altura, 7, html=True)
    y += altura + 2

    # Quadro de áreas das camadas poligonais (dentro da ATI)
    areas = []
    for camada in ordem:
        a = _area_na_ati(camada, ati, camadaAti.crs(), projeto)
        if a is not None and a >= 0.0001:
            areas.append(f'{camada.name().replace("_", " ")}: {_ha(a)} ha')
    if areas:
        altura = 3.4 * len(areas) + 5
        _rotulo(layout, '<b>Quadro de áreas (dentro da ATI, área elipsoidal)</b><br>' + '<br>'.join(areas), PAINEL_X, y, PAINEL_L,
                altura, 6.5, html=True)
        y += altura + 2

    # Legenda (só as camadas do mapa, sem o fundo)
    legenda = QgsLayoutItemLegend(layout)
    legenda.setTitle('Legenda')
    legenda.setLinkedMap(mapa)
    legenda.setAutoUpdateModel(False)
    raiz = QgsLayerTree()
    for camada in [camadaAti] + ordem:
        raiz.addLayer(camada).setName(camada.name().replace('_', ' '))
    legenda.model().setRootGroup(raiz)
    for estilo, tamanho, negrito in ((QgsLegendStyle.Title, 9, True), (QgsLegendStyle.Group, 7, True),
                                     (QgsLegendStyle.Subgroup, 7, True), (QgsLegendStyle.SymbolLabel, 6.5, False)):
        legenda.rstyle(estilo).setTextFormat(_texto(tamanho, negrito))
    legenda.setSymbolWidth(5)
    legenda.setSymbolHeight(3)
    legenda.attemptMove(QgsLayoutPoint(PAINEL_X, y))
    legenda.setResizeToContents(True)
    layout.addLayoutItem(legenda)
    legenda.adjustBoxSize()
    y += legenda.rect().height() + 3

    # Norte e escala, no pé do painel
    norte = QgsLayoutItemPicture(layout)
    norte.setPicturePath(SETA_NORTE)
    norte.setLinkedMap(mapa)
    norte.setNorthMode(QgsLayoutItemPicture.GridNorth)
    norte.attemptMove(QgsLayoutPoint(PAINEL_X, ALTURA - MARGEM - 34))
    norte.attemptResize(QgsLayoutSize(10, 14))
    layout.addLayoutItem(norte)

    barra = QgsLayoutItemScaleBar(layout)
    barra.setStyle('Single Box')
    barra.setLinkedMap(mapa)
    barra.setUnits(QgsUnitTypes.DistanceMeters)
    barra.setUnitLabel('m')
    barra.setNumberOfSegments(2)
    barra.setNumberOfSegmentsLeft(0)
    barra.setUnitsPerSegment(_intervalo(mapa.extent().width() * 0.6) / 2)
    barra.setTextFormat(_texto(6))
    barra.attemptMove(QgsLayoutPoint(PAINEL_X + 13, ALTURA - MARGEM - 30))
    layout.addLayoutItem(barra)
    barra.update()

    rodape = (f'Escala 1:{mapa.scale():,.0f}'.replace(',', '.') + f'  ·  {src.description()} ({src.authid()})'
              + f'  ·  Gerado pelo GeoCAR em {datetime.now().strftime("%d/%m/%Y")}'
              + (f'  ·  Imagem de fundo: {fundo.name()}' if fundo is not None else '')
              + '<br>Mapa ilustrativo do cadastro ambiental, sem valor de memorial descritivo nem de levantamento '
                'georreferenciado.')
    _rotulo(layout, rodape, PAINEL_X, ALTURA - MARGEM - 14, PAINEL_L, 14, 5.5, html=True, cor='#455a64')

    gerente.addLayout(layout)
    exportador = QgsLayoutExporter(layout)
    configuracao = QgsLayoutExporter.PdfExportSettings()
    configuracao.dpi = 200
    configuracao.rasterizeWholeImage = False
    resultado = exportador.exportToPdf(caminho, configuracao)
    if not manterLayout:
        gerente.removeLayout(layout)
    if resultado != QgsLayoutExporter.Success:
        raise RuntimeError(f'Falha ao exportar o mapa (código {resultado}).')
    return caminho
