# -*- coding: utf-8 -*-

"""
/***************************************************************************
 GeoCAR
                                 A QGIS plugin
Cadastro Ambiental Rural (CAR)
                              -------------------
        begin                : 2026-10-26
        copyright            : (C) 2026 by Prof Cazaroli e Leandro França
        email                : contato@geoone.com.br
 ***************************************************************************/

/***************************************************************************
 *                                                                         *
 *   This program is free software; you can redistribute it and/or modify  *
 *   it under the terms of the GNU General Public License as published by  *
 *   the Free Software Foundation; either version 2 of the License, or     *
 *   (at your option) any later version.                                   *
 *                                                                         *
 ***************************************************************************/
"""
# Mapa do imóvel em PDF, para entregar ao cliente
# mapaImovel.py

__author__ = 'Prof Cazaroli e Leandro França'
__date__ = '2026-10-26'
__copyright__ = '(C) 2026 by Prof Cazaroli e Leandro França'

import os
from datetime import date

from qgis.PyQt.QtCore import QCoreApplication
from qgis.PyQt.QtGui import QIcon
from qgis.core import (
    Qgis,
    QgsMapLayer,
    QgsProcessingAlgorithm,
    QgsProcessingException,
    QgsProcessingParameterBoolean,
    QgsProcessingParameterFileDestination,
    QgsProcessingParameterMultipleLayers,
    QgsProcessingParameterRasterLayer,
    QgsProcessingParameterString,
    QgsProcessingParameterVectorLayer,
    QgsProject,
    QgsVectorLayer,
)

from .nucleoCAR.processingCAR import (PASTA_RESULTADOS, avisoLegal, camadaFixa, camadaPadrao, camadasPadrao,
                                      projetoSalvo, rodapeAjuda)


def _camadasPadrao():
    """Camadas da RAIZ com feições (sem relevo e uso restrito), coberturas, APP calculada e RL (ou o rascunho)."""
    from .nucleoCAR.quadro_areas import classificar_camada
    from .utilsExportacao import camadasParaExportar
    projeto = QgsProject.instance()
    nomeAti = camadaPadrao('ati')
    nomes = [c.name() for c in camadasParaExportar()
             if c.featureCount() > 0 and c.name() != nomeAti and not classificar_camada(c.name())]
    for nome in camadasPadrao('coberturas') + ['APP_Integral']:
        if nome not in nomes and any(c.featureCount() for c in projeto.mapLayersByName(nome)):
            nomes.append(nome)
    temRl = any(c.featureCount() for n in camadasPadrao('reservas') for c in projeto.mapLayersByName(n))
    if not temRl and camadaFixa('RL_Rascunho') is not None and camadaFixa('RL_Rascunho').featureCount():
        nomes.append('RL_Rascunho')
    return nomes


def _fundoPadrao():
    for camada in QgsProject.instance().mapLayers().values():
        if camada.type() == QgsMapLayer.RasterLayer and camada.providerType() in ('wms', 'xyz', 'arcgismapserver'):
            return camada.name()
    return None


class MapaImovelCAR(QgsProcessingAlgorithm):
    """Prancha A4 com o imóvel, as camadas declaradas, legenda, quadro de áreas, escala e norte."""

    INPUT_ATI = 'INPUT_ATI'
    INPUT_CAMADAS = 'INPUT_CAMADAS'
    INPUT_FUNDO = 'INPUT_FUNDO'
    MANTER_LAYOUT = 'MANTER_LAYOUT'
    OUTPUT = 'OUTPUT'
    IDENTIFICACAO = [('IMOVEL', 'Imóvel'), ('MUNICIPIO_UF', 'Município/UF'),
                     ('PROPRIETARIO', 'Proprietário/possuidor'), ('RESPONSAVEL', 'Responsável técnico (CREA/CFT)')]

    def initAlgorithm(self, config=None):
        poligono = Qgis.ProcessingSourceType.VectorPolygon
        self.addParameter(QgsProcessingParameterVectorLayer(
            self.INPUT_ATI, self.tr('Área Total do Imóvel (ATI)'), [poligono], defaultValue=camadaPadrao('ati') or 'ATI'))
        self.addParameter(QgsProcessingParameterMultipleLayers(
            self.INPUT_CAMADAS, self.tr('Camadas do mapa (já vem com as camadas preenchidas da RAIZ)'),
            layerType=Qgis.ProcessingSourceType.Vector, optional=True, defaultValue=_camadasPadrao() or None))
        self.addParameter(QgsProcessingParameterRasterLayer(
            self.INPUT_FUNDO, self.tr('Imagem de fundo (opcional)'), optional=True, defaultValue=_fundoPadrao()))
        for chave, rotulo in self.IDENTIFICACAO:
            self.addParameter(QgsProcessingParameterString(chave, self.tr(rotulo), optional=True))
        self.addParameter(QgsProcessingParameterBoolean(
            self.MANTER_LAYOUT, self.tr('Deixar o layout no projeto, para ajustes (Projeto > Layouts)'),
            defaultValue=True))
        padrao = None
        if projetoSalvo():
            padrao = os.path.join(QgsProject.instance().homePath(), PASTA_RESULTADOS,
                                  f'GeoCAR_Mapa_do_Imovel_{date.today().isoformat()}.pdf')
        self.addParameter(QgsProcessingParameterFileDestination(
            self.OUTPUT, self.tr('Mapa do imóvel (PDF)'), 'PDF (*.pdf)', defaultValue=padrao))

    def processAlgorithm(self, parameters, context, feedback):
        from .nucleoCAR.correcoes import srcDaAti
        from .nucleoCAR.mapa_imovel import NOME_LAYOUT, gerar_mapa

        camadaAti = self.parameterAsVectorLayer(parameters, self.INPUT_ATI, context)
        if camadaAti is None or camadaAti.featureCount() == 0:
            raise QgsProcessingException(self.tr('A camada ATI está vazia ou não foi informada.'))
        camadas = [c for c in self.parameterAsLayerList(parameters, self.INPUT_CAMADAS, context)
                   if isinstance(c, QgsVectorLayer) and c.id() != camadaAti.id() and c.featureCount() > 0]
        fundo = self.parameterAsRasterLayer(parameters, self.INPUT_FUNDO, context)
        identificacao = [(rotulo, self.parameterAsString(parameters, chave, context).strip())
                         for chave, rotulo in self.IDENTIFICACAO]
        caminho = self.parameterAsFileOutput(parameters, self.OUTPUT, context)
        os.makedirs(os.path.dirname(caminho) or '.', exist_ok=True)
        feedback.pushInfo(self.tr(f'Camadas no mapa: {", ".join(c.name() for c in camadas) or "só a ATI"}'))
        if fundo is not None:
            feedback.pushInfo(self.tr(f'Imagem de fundo: {fundo.name()} (precisa de internet se for serviço online)'))
        try:
            gerar_mapa(context.project() or QgsProject.instance(), camadaAti, camadas, fundo, identificacao, caminho,
                       srcDaAti(camadaAti), self.parameterAsBool(parameters, self.MANTER_LAYOUT, context))
        except RuntimeError as erro:
            raise QgsProcessingException(str(erro))
        feedback.pushInfo(self.tr(f'Mapa gravado em: {caminho}'))
        if self.parameterAsBool(parameters, self.MANTER_LAYOUT, context):
            feedback.pushInfo(self.tr(f'Layout "{NOME_LAYOUT}" disponível em Projeto > Layouts para ajustes.'))
        return {self.OUTPUT: caminho}

    def flags(self):
        # Monta layout no projeto: precisa da thread principal
        return super().flags() | Qgis.ProcessingAlgorithmFlag.NoThreading

    def name(self):
        return 'mapaimovelcar'

    def displayName(self):
        return self.tr('e. Mapa do imóvel (PDF)')

    def group(self):
        return self.tr('5. 📤 Gerar arquivos para o CAR')

    def groupId(self):
        return 'gerararquivoscar'

    def tr(self, string):
        return QCoreApplication.translate('Processing', string)

    def createInstance(self):
        return MapaImovelCAR()

    def tags(self):
        return 'GeoOne,GeoCAR,mapa,prancha,layout,PDF,cliente,imóvel'.split(',')

    def icon(self):
        return QIcon(os.path.join(os.path.dirname(os.path.dirname(__file__)), 'images/geocar2.png'))

    def shortHelpString(self):
        txt = """Gera o <b>mapa do imóvel</b> em PDF (A4 paisagem), para entregar ao cliente ou anexar ao processo: ATI e camadas declaradas sobre a imagem de fundo, grade em coordenadas UTM, legenda, quadro de áreas dentro da ATI, escala, norte e identificação.

A lista de camadas já vem com as camadas preenchidas da RAIZ (sem as de relevo e uso restrito, que podem ser acrescentadas), a área consolidada, a APP calculada pela pré-análise e a Reserva Legal (ou o rascunho, se a RL não foi declarada). As cores são as da RAIZ.

O mapa fica em <b>Pre-Analise/GeoCAR_Mapa_do_Imovel_&lt;data&gt;.pdf</b> e o layout fica no projeto (<b>Projeto &gt; Layouts &gt; GeoCAR - Mapa do imóvel</b>) para ajustes finos, como mudar a legenda ou acrescentar o logotipo.

Mapa ilustrativo: não substitui memorial descritivo nem levantamento georreferenciado.
""" + avisoLegal()
        return txt + rodapeAjuda()
