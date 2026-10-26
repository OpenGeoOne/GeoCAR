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
# Rascunho de Reserva Legal sobre a vegetação nativa (grupo 4)
# propostaReservaLegal.py

__author__ = 'Prof Cazaroli e Leandro França'
__date__ = '2026-10-26'
__copyright__ = '(C) 2026 by Prof Cazaroli e Leandro França'

import os

from qgis.PyQt.QtCore import QCoreApplication, QMetaType
from qgis.PyQt.QtGui import QIcon
from qgis.core import (
    Qgis,
    QgsFeature,
    QgsFeatureSink,
    QgsField,
    QgsGeometry,
    QgsProcessingAlgorithm,
    QgsProcessingException,
    QgsProcessingOutputNumber,
    QgsProcessingParameterBoolean,
    QgsProcessingParameterEnum,
    QgsProcessingParameterFeatureSink,
    QgsProcessingParameterMultipleLayers,
    QgsProcessingParameterVectorLayer,
    QgsVectorLayer,
    QgsWkbTypes,
)

from .nucleoCAR.correcoes import Conversor, srcDaAti, uniaoAti, uniaoUtm
from .nucleoCAR.processingCAR import (avisoLegal, camadaFixa, camadaPadrao, camadasPadrao, garantirCamadaFixa,
                                      limparCamada, projetoSalvo, rodapeAjuda, substituirFeicoes)
from .nucleoCAR.proposta_rl import propor_rl
from .nucleoCAR.reserva_legal import OPCOES_PERCENTUAL

NOME_RASCUNHO = 'RL_Rascunho'
NOME_APP = 'APP_Integral'


class PropostaReservaLegalCAR(QgsProcessingAlgorithm):
    """Rascunho de Reserva Legal sobre a vegetação nativa, contínuo com a APP e a RL declarada."""

    INPUT_ATI = 'INPUT_ATI'
    PERCENTUAL = 'PERCENTUAL'
    INPUT_VEGETACAO = 'INPUT_VEGETACAO'
    INPUT_APP = 'INPUT_APP'
    INPUT_RESERVAS = 'INPUT_RESERVAS'
    INPUT_SERVIDOES = 'INPUT_SERVIDOES'
    COMPUTAR_APP = 'COMPUTAR_APP'
    OUTPUT = 'OUTPUT'
    OUTPUT_PROPOSTA = 'OUTPUT_PROPOSTA'
    OUTPUT_DEFICIT = 'OUTPUT_DEFICIT'

    def initAlgorithm(self, config=None):
        poligono = Qgis.ProcessingSourceType.VectorPolygon
        self.addParameter(QgsProcessingParameterVectorLayer(
            self.INPUT_ATI, self.tr('Área Total do Imóvel (ATI)'), [poligono], defaultValue=camadaPadrao('ati') or 'ATI'))
        self.addParameter(QgsProcessingParameterEnum(
            self.PERCENTUAL, self.tr('Percentual de Reserva Legal (art. 12)'),
            options=[self.tr(rotulo) for _v, rotulo in OPCOES_PERCENTUAL], defaultValue=0))
        self.addParameter(QgsProcessingParameterVectorLayer(
            self.INPUT_VEGETACAO, self.tr('Vegetação nativa'), [poligono], defaultValue=camadaPadrao('vegetacao')))
        self.addParameter(QgsProcessingParameterVectorLayer(
            self.INPUT_APP, self.tr('APP (camada APP_Integral, gerada pela pré-análise)'), [poligono], optional=True,
            defaultValue=NOME_APP if camadaFixa(NOME_APP) is not None else None))
        self.addParameter(QgsProcessingParameterMultipleLayers(
            self.INPUT_RESERVAS, self.tr('Reserva Legal já declarada (descontada da exigida)'),
            layerType=poligono, optional=True, defaultValue=camadasPadrao('reservas') or None))
        self.addParameter(QgsProcessingParameterMultipleLayers(
            self.INPUT_SERVIDOES, self.tr('Servidão administrativa (fica fora da RL)'),
            layerType=poligono, optional=True, defaultValue=camadasPadrao('servidoes') or None))
        self.addParameter(QgsProcessingParameterBoolean(
            self.COMPUTAR_APP, self.tr('Se faltar vegetação fora de APP, completar com APP vegetada (art. 15)'),
            defaultValue=True))
        if camadaFixa(NOME_RASCUNHO) is not None or projetoSalvo():
            self.addParameter(QgsProcessingParameterFeatureSink(
                self.OUTPUT, self.tr(f'Rascunho — cópia opcional (o resultado já vai para a camada {NOME_RASCUNHO})'),
                createByDefault=False, optional=True))
        else:
            self.addParameter(QgsProcessingParameterFeatureSink(self.OUTPUT, self.tr('Rascunho de Reserva Legal')))
        self.addOutput(QgsProcessingOutputNumber(self.OUTPUT_PROPOSTA, self.tr('Área proposta (ha)')))
        self.addOutput(QgsProcessingOutputNumber(self.OUTPUT_DEFICIT, self.tr('Déficit sem vegetação (ha)')))

    def processAlgorithm(self, parameters, context, feedback):
        camadaAti = self.parameterAsVectorLayer(parameters, self.INPUT_ATI, context)
        if camadaAti is None or camadaAti.featureCount() == 0:
            raise QgsProcessingException(self.tr('A camada ATI está vazia ou não foi informada.'))
        vegetacao = self.parameterAsVectorLayer(parameters, self.INPUT_VEGETACAO, context)
        if vegetacao is None:
            raise QgsProcessingException(self.tr('Informe a camada de vegetação nativa.'))
        camadaApp = self.parameterAsVectorLayer(parameters, self.INPUT_APP, context)

        def lista(chave):
            return [c for c in self.parameterAsLayerList(parameters, chave, context)
                    if isinstance(c, QgsVectorLayer) and c.id() != camadaAti.id()]

        percentual = OPCOES_PERCENTUAL[self.parameterAsEnum(parameters, self.PERCENTUAL, context)][0]
        src = srcDaAti(camadaAti)
        ati = uniaoAti(camadaAti, src)
        res = propor_rl(ati, percentual, uniaoUtm([vegetacao], src),
                        app=uniaoUtm([camadaApp], src) if camadaApp is not None else None,
                        reserva_declarada=uniaoUtm(lista(self.INPUT_RESERVAS), src),
                        servidao=uniaoUtm(lista(self.INPUT_SERVIDOES), src),
                        computar_app=self.parameterAsBool(parameters, self.COMPUTAR_APP, context))

        feedback.pushInfo(self.tr(f'RL exigida ({percentual:g}%): {res["exigida_ha"]:.4f} ha | já declarada: '
                                  f'{res["declarada_ha"]:.4f} ha | a propor: {res["falta_ha"]:.4f} ha'))
        for origem, geometria in res['partes']:
            feedback.pushInfo(self.tr(f'{origem}: {geometria.area() / 1e4:.4f} ha'))
        for aviso in res['avisos']:
            feedback.pushWarning(self.tr(aviso))

        # Camada de memória no SRC da ATI
        memoria = QgsVectorLayer(f'MultiPolygon?crs={camadaAti.crs().authid()}', NOME_RASCUNHO, 'memory')
        memoria.dataProvider().addAttributes([QgsField('origem', QMetaType.Type.QString),
                                              QgsField('area_ha', QMetaType.Type.Double)])
        memoria.updateFields()
        conversor = Conversor(camadaAti, src)
        novas = []
        for origem, geometria in res['partes']:
            nova = QgsFeature(memoria.fields())
            g = conversor.paraCamada(geometria)
            g.convertToMultiType()
            nova.setGeometry(g)
            nova.setAttributes([origem, round(geometria.area() / 1e4, 4)])
            novas.append(nova)
        memoria.dataProvider().addFeatures(novas)

        fixa = garantirCamadaFixa(NOME_RASCUNHO, context.project())
        if fixa is not None:
            if novas:
                substituirFeicoes(fixa, memoria)
            else:
                limparCamada(fixa)
                fixa.triggerRepaint()
            feedback.pushInfo(self.tr(f'{NOME_RASCUNHO}: {len(novas)} feição(ões) gravada(s) (o rascunho anterior '
                                      'foi apagado).'))

        resultados = {self.OUTPUT_PROPOSTA: round(res['proposta_ha'], 4),
                      self.OUTPUT_DEFICIT: round(res['deficit_ha'], 4)}
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
        return super().flags() | Qgis.ProcessingAlgorithmFlag.NoThreading

    def name(self):
        return 'propostareservalegalcar'

    def displayName(self):
        return self.tr('e. Rascunho de Reserva Legal')

    def group(self):
        return self.tr('4. 🔧 Correções')

    def groupId(self):
        return 'correcoes'

    def tr(self, string):
        return QCoreApplication.translate('Processing', string)

    def createInstance(self):
        return PropostaReservaLegalCAR()

    def tags(self):
        return 'GeoOne,GeoCAR,Reserva Legal,RL,proposta,rascunho,vegetação nativa,APP,art. 12,art. 15'.split(',')

    def icon(self):
        return QIcon(os.path.join(os.path.dirname(os.path.dirname(__file__)), 'images/vetor.png'))

    def shortHelpString(self):
        txt = """Desenha um <b>rascunho de Reserva Legal</b> quando a RL não foi declarada ou é menor que a exigida.

• Meta: o percentual do art. 12 sobre a ATI, menos a RL já declarada
• Usa primeiro a <b>vegetação nativa fora de APP</b>, fora da servidão administrativa
• Se houver mais vegetação que o necessário, a RL cresce a partir da APP e da RL já declarada (sem elas, a partir da divisa), para ficar contínua e formar corredor com a APP e com os vizinhos
• Se faltar, completa com <b>APP vegetada</b> (art. 15), se a opção estiver marcada
• O que nem a vegetação cobre aparece como déficit: recompor, regenerar ou compensar (art. 66); art. 67 para imóveis de até 4 módulos fiscais

O resultado vai para a camada <b>RL_Rascunho</b> (grupo <b>Apoio à Pré-Análise</b>), com a origem de cada parte. Rode depois da pré-análise do grupo 3, que gera a <b>APP_Integral</b>.

<b>É um ponto de partida:</b> a localização da RL é escolha do proprietário, aprovada pelo órgão ambiental (art. 14), que considera plano de bacia, zoneamento, corredores e áreas frágeis. Ajuste o desenho e copie para a camada de RL proposta da RAIZ.
""" + avisoLegal()
        return txt + rodapeAjuda()
