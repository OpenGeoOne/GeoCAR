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
# Consulta as parcelas certificadas no SIGEF (INCRA) em torno da ATI
# consultaSIGEF.py

__author__ = 'Prof Cazaroli e Leandro França'
__date__ = '2026-10-26'
__copyright__ = '(C) 2026 by Prof Cazaroli e Leandro França'

import os

from qgis.PyQt.QtCore import QCoreApplication
from qgis.PyQt.QtGui import QIcon
from qgis.core import (
    Qgis,
    QgsFeature,
    QgsFeatureSink,
    QgsProcessingAlgorithm,
    QgsProcessingException,
    QgsProcessingParameterFeatureSink,
    QgsProcessingParameterNumber,
    QgsProcessingParameterVectorLayer,
    QgsWkbTypes,
)

from .nucleoCAR.consultas import (MARGEM_SIGEF_M, NOME_SIGEF, extensaoDaAti, marcarConsulta, parcelasSigef)
from .nucleoCAR.processingCAR import (avisoLegal, camadaFixa, camadaPadrao, garantirCamadaFixa, projetoSalvo,
                                      rodapeAjuda, substituirFeicoes)


class ConsultaSigefCAR(QgsProcessingAlgorithm):
    """Parcelas certificadas no SIGEF em torno da ATI."""

    INPUT_ATI = 'INPUT_ATI'
    MARGEM = 'MARGEM'
    OUTPUT = 'OUTPUT'

    def initAlgorithm(self, config=None):
        self.addParameter(QgsProcessingParameterVectorLayer(
            self.INPUT_ATI, self.tr('Área Total do Imóvel (ATI)'), [Qgis.ProcessingSourceType.VectorPolygon],
            defaultValue=camadaPadrao('ati') or 'ATI'))
        self.addParameter(QgsProcessingParameterNumber(
            self.MARGEM, self.tr('Margem em torno da ATI (m)'), type=Qgis.ProcessingNumberParameterType.Double,
            minValue=0.0, maxValue=20000.0, defaultValue=MARGEM_SIGEF_M))
        if camadaFixa(NOME_SIGEF) is not None or projetoSalvo():
            self.addParameter(QgsProcessingParameterFeatureSink(
                self.OUTPUT, self.tr(f'Parcelas certificadas — cópia opcional (o resultado já vai para a camada {NOME_SIGEF})'),
                createByDefault=False, optional=True))
        else:
            self.addParameter(QgsProcessingParameterFeatureSink(self.OUTPUT, self.tr('Parcelas certificadas')))

    def processAlgorithm(self, parameters, context, feedback):
        camadaAti = self.parameterAsVectorLayer(parameters, self.INPUT_ATI, context)
        if camadaAti is None or camadaAti.featureCount() == 0:
            raise QgsProcessingException(self.tr('A camada ATI está vazia ou não foi informada.'))
        margem = self.parameterAsDouble(parameters, self.MARGEM, context)

        memoria = parcelasSigef(extensaoDaAti(camadaAti, margem), feedback)
        if memoria is None:
            raise QgsProcessingException(self.tr('Serviço do SIGEF indisponível no momento. Tente mais tarde.'))

        fixa = garantirCamadaFixa(NOME_SIGEF, context.project())
        if fixa is not None:
            total = substituirFeicoes(fixa, memoria)
            marcarConsulta(fixa)
            feedback.pushInfo(self.tr(f'{NOME_SIGEF}: {total} parcela(s) gravada(s) na camada do projeto '
                                      '(as anteriores foram apagadas).'))

        resultados = {}
        if parameters.get(self.OUTPUT) is not None or fixa is None:
            sink, destId = self.parameterAsSink(parameters, self.OUTPUT, context, memoria.fields(),
                                                QgsWkbTypes.MultiPolygon, memoria.crs())
            if sink is None:
                raise QgsProcessingException(self.invalidSinkError(parameters, self.OUTPUT))
            for feicao in memoria.getFeatures():
                sink.addFeature(QgsFeature(feicao), QgsFeatureSink.FastInsert)
            resultados[self.OUTPUT] = destId
        feedback.pushInfo(self.tr('GeoCAR - GeoOne'))
        return resultados

    def flags(self):
        # Grava na camada fixa do projeto: precisa da thread principal
        if camadaFixa(NOME_SIGEF) is not None or projetoSalvo():
            return super().flags() | Qgis.ProcessingAlgorithmFlag.NoThreading
        return super().flags()

    def name(self):
        return 'consultasigefcar'

    def displayName(self):
        return self.tr('b. Consulta SIGEF (INCRA)')

    def group(self):
        return self.tr('1. 🔍 Consultas')

    def groupId(self):
        return 'consultas'

    def tr(self, string):
        return QCoreApplication.translate('Processing', string)

    def createInstance(self):
        return ConsultaSigefCAR()

    def tags(self):
        return ('GeoOne,GeoCAR,GeoRural,INCRA,SIGEF,certificação,georreferenciamento,parcela,matrícula,'
                'vizinhos,titularidade').split(',')

    def icon(self):
        return QIcon(os.path.join(os.path.dirname(os.path.dirname(__file__)), 'images/geoincra.png'))

    def shortHelpString(self):
        txt = """Consulta as <b>parcelas certificadas no SIGEF</b> (INCRA) que tocam a ATI e as dos <b>imóveis vizinhos</b>, na margem informada (padrão de 1 km, a mesma da Consulta CAR automática): código do imóvel, nome, matrícula, situação e data de aprovação.

O resultado vai para a camada <b>Parcelas_SIGEF</b> (grupo <b>Areas_Vizinhas</b>, no <b>Pre-Analise/PreAnalise.gpkg</b>), apagando a consulta anterior. A ferramenta <b>3c</b> compara essas parcelas com a ATI: parcela de terceiro dentro da ATI, várias matrículas reunidas, área sem certificação.

Não precisa rodar antes da 3c: se as parcelas ainda não foram consultadas, a 3c faz a consulta sozinha.

A base é a publicada pelo IBAMA a partir do SIGEF; o endereço fica em <b>nucleoCAR/fontes_restricoes.json</b>.
""" + avisoLegal()
        return txt + rodapeAjuda()
