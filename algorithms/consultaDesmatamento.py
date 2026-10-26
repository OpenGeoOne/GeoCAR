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
# Consulta o desmatamento anual do PRODES (INPE) na área do imóvel
# consultaDesmatamento.py

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

from .nucleoCAR.consultas import MARGEM_PRODES_M, extensaoDaAti, marcarConsulta
from .nucleoCAR.desmatamento import ANTES, NOME_PRODES, consultarProdes
from .nucleoCAR.processingCAR import (avisoLegal, camadaFixa, camadaPadrao, garantirCamadaFixa, projetoSalvo,
                                      rodapeAjuda, substituirFeicoes)


class ConsultaDesmatamentoCAR(QgsProcessingAlgorithm):
    """Desmatamento anual do PRODES em torno da ATI, com a data de detecção."""

    INPUT_ATI = 'INPUT_ATI'
    MARGEM = 'MARGEM'
    OUTPUT = 'OUTPUT'

    def initAlgorithm(self, config=None):
        self.addParameter(QgsProcessingParameterVectorLayer(
            self.INPUT_ATI, self.tr('Área Total do Imóvel (ATI)'), [Qgis.ProcessingSourceType.VectorPolygon],
            defaultValue=camadaPadrao('ati') or 'ATI'))
        self.addParameter(QgsProcessingParameterNumber(
            self.MARGEM, self.tr('Margem em torno da ATI (m)'), type=Qgis.ProcessingNumberParameterType.Double,
            minValue=0.0, maxValue=10000.0, defaultValue=MARGEM_PRODES_M))
        if camadaFixa(NOME_PRODES) is not None or projetoSalvo():
            self.addParameter(QgsProcessingParameterFeatureSink(
                self.OUTPUT, self.tr(f'Desmatamento — cópia opcional (o resultado já vai para a camada {NOME_PRODES})'),
                createByDefault=False, optional=True))
        else:
            self.addParameter(QgsProcessingParameterFeatureSink(self.OUTPUT, self.tr('Desmatamento (PRODES)')))

    def processAlgorithm(self, parameters, context, feedback):
        camadaAti = self.parameterAsVectorLayer(parameters, self.INPUT_ATI, context)
        if camadaAti is None or camadaAti.featureCount() == 0:
            raise QgsProcessingException(self.tr('A camada ATI está vazia ou não foi informada.'))
        margem = self.parameterAsDouble(parameters, self.MARGEM, context)

        memoria = consultarProdes(extensaoDaAti(camadaAti, margem), feedback)
        if memoria is None:
            raise QgsProcessingException(self.tr('Serviço do PRODES (TerraBrasilis/INPE) indisponível no momento. '
                                                 'Tente mais tarde.'))
        apos = [f for f in memoria.getFeatures() if f['periodo'] != ANTES]
        if apos:
            anos = sorted({f['ano'] for f in apos if f['ano']})
            feedback.pushWarning(self.tr(f'{len(apos)} desmatamento(s) depois de 22/07/2008 ou a confirmar na área '
                                         f'consultada (anos: {", ".join(str(a) for a in anos)}). A pré-análise (3c) '
                                         f'cruza com a ATI, a área consolidada, a APP e a Reserva Legal.'))

        fixa = garantirCamadaFixa(NOME_PRODES, context.project())
        if fixa is not None:
            total = substituirFeicoes(fixa, memoria)
            marcarConsulta(fixa)
            feedback.pushInfo(self.tr(f'{NOME_PRODES}: {total} polígono(s) gravado(s) na camada do projeto '
                                      '(a consulta anterior foi apagada).'))

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
        if camadaFixa(NOME_PRODES) is not None or projetoSalvo():
            return super().flags() | Qgis.ProcessingAlgorithmFlag.NoThreading
        return super().flags()

    def name(self):
        return 'consultadesmatamentocar'

    def displayName(self):
        return self.tr('e. Consulta desmatamento (PRODES/INPE)')

    def group(self):
        return self.tr('1. 🔍 Consultas')

    def groupId(self):
        return 'consultas'

    def tr(self, string):
        return QCoreApplication.translate('Processing', string)

    def createInstance(self):
        return ConsultaDesmatamentoCAR()

    def tags(self):
        return ('GeoOne,GeoCAR,PRODES,INPE,TerraBrasilis,desmatamento,supressão,2008,área consolidada,'
                'embargo').split(',')

    def icon(self):
        return QIcon(os.path.join(os.path.dirname(os.path.dirname(__file__)), 'images/geocar.png'))

    def shortHelpString(self):
        txt = """Consulta o <b>desmatamento anual do PRODES</b> (INPE, portal TerraBrasilis), nos seis biomas, na área da ATI: ano, data da imagem que detectou o desmatamento e se ele é <b>anterior ou posterior a 22/07/2008</b>, o marco do Código Florestal.

O resultado vai para a camada <b>Desmatamento_PRODES</b> (grupo <b>Areas_Vizinhas</b>, no <b>Pre-Analise/PreAnalise.gpkg</b>), apagando a consulta anterior. A ferramenta <b>3c</b> cruza o desmatamento posterior a 2008 com a ATI, a área consolidada, a APP e a Reserva Legal. Não precisa rodar antes da 3c: se ainda não foi consultado, a 3c consulta sozinha.

Por que importa: área desmatada depois de 22/07/2008 <b>não é área consolidada</b> (Lei 12.651/2012, art. 3º, IV), não tem as regras da escadinha (art. 61-A) e, em APP ou Reserva Legal, deve ser recomposta (arts. 7º e 17).

<b>Limites:</b> o PRODES usa imagens Landsat (30 m) e mapeia desmatamentos a partir de cerca de 1 ha. A ausência de polígono não prova que não houve supressão: confira com imagens históricas. Desmatamentos detectados em 2008 ficam <b>a confirmar</b>, pois podem ser anteriores ou posteriores a 22/07/2008.
""" + avisoLegal()
        return txt + rodapeAjuda()
