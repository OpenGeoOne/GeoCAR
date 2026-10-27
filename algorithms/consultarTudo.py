# -*- coding: utf-8 -*-

"""
/***************************************************************************
 GeoCAR
                                 A QGIS plugin
Cadastro Ambiental Rural (CAR)
                              -------------------
        begin                : 2026-10-27
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
# Faz todas as consultas do grupo 1 de uma vez pela ATI
# consultarTudo.py

__author__ = 'Prof Cazaroli e Leandro França'
__date__ = '2026-10-27'
__copyright__ = '(C) 2026 by Prof Cazaroli e Leandro França'

import os

from qgis.PyQt.QtCore import QCoreApplication
from qgis.PyQt.QtGui import QIcon
from qgis.core import (
    Qgis,
    QgsGeometry,
    QgsProcessingAlgorithm,
    QgsProcessingException,
    QgsProcessingMultiStepFeedback,
    QgsProcessingParameterBoolean,
    QgsProcessingParameterRasterLayer,
    QgsProcessingParameterVectorLayer,
    QgsProject,
)

from .nucleoCAR.consultas import (NOME_RESTRICOES, NOME_SIGEF, NOME_VIZINHOS, garantirParcelasSigef, garantirProdes,
                                  garantirRestricoes, garantirVizinhosCAR)
from .nucleoCAR.desmatamento import NOME_PRODES
from .nucleoCAR.processingCAR import GRUPO_APOIO, avisoLegal, camadaPadrao, grupoPorCaminho, rodapeAjuda


class ConsultarTudoCAR(QgsProcessingAlgorithm):
    """Consultas do grupo 1 em sequência pela ATI: CAR, SIGEF, restrições, PRODES (e relevo, se houver MDT)."""

    INPUT_ATI = 'INPUT_ATI'
    CAR = 'CAR'
    SIGEF = 'SIGEF'
    RESTRICOES = 'RESTRICOES'
    PRODES = 'PRODES'
    INPUT_DEM = 'INPUT_DEM'

    def initAlgorithm(self, config=None):
        self.addParameter(QgsProcessingParameterVectorLayer(
            self.INPUT_ATI, self.tr('Área Total do Imóvel (ATI)'), [Qgis.ProcessingSourceType.VectorPolygon],
            defaultValue=camadaPadrao('ati') or 'ATI'))
        for chave, rotulo in ((self.CAR, 'b. Consulta CAR (imóveis vizinhos no SICAR)'),
                              (self.SIGEF, 'c. Consulta SIGEF (parcelas certificadas)'),
                              (self.RESTRICOES, 'e. Consulta de restrições (UC, TI, assentamentos, embargos)'),
                              (self.PRODES, 'f. Consulta desmatamento (PRODES/INPE)')):
            self.addParameter(QgsProcessingParameterBoolean(chave, self.tr(rotulo), defaultValue=True))
        self.addParameter(QgsProcessingParameterRasterLayer(
            self.INPUT_DEM, self.tr('d. MDT para APP de altitude e declividade (opcional)'), optional=True))

    def processAlgorithm(self, parameters, context, feedback):
        camadaAti = self.parameterAsVectorLayer(parameters, self.INPUT_ATI, context)
        if camadaAti is None or camadaAti.featureCount() == 0:
            raise QgsProcessingException(self.tr('A camada ATI está vazia ou não foi informada.'))
        mdt = self.parameterAsRasterLayer(parameters, self.INPUT_DEM, context)

        etapas = [(self.CAR, NOME_VIZINHOS, garantirVizinhosCAR),
                  (self.SIGEF, NOME_SIGEF, garantirParcelasSigef),
                  (self.RESTRICOES, NOME_RESTRICOES, garantirRestricoes),
                  (self.PRODES, NOME_PRODES, garantirProdes)]
        etapas = [e for e in etapas if self.parameterAsBoolean(parameters, e[0], context)]
        total = len(etapas) + (1 if mdt is not None else 0)
        if total == 0:
            raise QgsProcessingException(self.tr('Marque ao menos uma consulta (ou informe o MDT).'))
        passos = QgsProcessingMultiStepFeedback(total, feedback)

        resumo = []
        for i, (_, nome, funcao) in enumerate(etapas):
            passos.setCurrentStep(i)
            if feedback.isCanceled():
                break
            feedback.pushInfo('')
            feedback.pushInfo(self.tr(f'— {nome} —'))
            try:
                camada = funcao(context, passos, camadaAti, forcar=True)
            except Exception as erro:
                camada = None
                feedback.reportError(self.tr(f'{nome}: falhou ({erro}).'))
            if camada is None:
                resumo.append(f'{nome}: não consultado (serviço indisponível?)')
            else:
                resumo.append(f'{nome}: {camada.featureCount()} feição(ões)')

        if mdt is not None and not feedback.isCanceled():
            passos.setCurrentStep(len(etapas))
            feedback.pushInfo('')
            feedback.pushInfo(self.tr('— Relevo: APP de altitude, declividade e uso restrito —'))
            resumo += self._relevo(mdt, camadaAti, context, passos)

        feedback.pushInfo('')
        feedback.pushInfo(self.tr('Resumo das consultas:'))
        for linha in resumo:
            feedback.pushInfo('  • ' + linha)
        feedback.pushInfo(self.tr('As camadas ficam no grupo Pré-Análise (GeoCAR) › Consultas. '
                                  'Rode a pré-análise (3c) para cruzar tudo com o imóvel.'))
        feedback.pushInfo(self.tr('GeoCAR - GeoOne'))
        return {}

    def _relevo(self, mdt, camadaAti, context, feedback):
        import processing
        from .nucleoCAR.utils import src_utm_sirgas
        geometrias = [f.geometry() for f in camadaAti.getFeatures() if f.hasGeometry()]
        src = src_utm_sirgas(QgsGeometry.unaryUnion(geometrias), camadaAti.crs())
        saidas = {'OUTPUT_ALTITUDE_1800': 'APP_Altitude_1800m',
                  'OUTPUT_SLOPE_45': 'APP_Declividade_45graus',
                  'OUTPUT_SLOPE_25_45': 'Uso_Restrito_Declividade_25a45graus'}
        try:
            resultado = processing.run('GeoCAR:altitudedeclividadeappusorestrito', dict(
                INPUT_DEM=mdt, CRS=src, **{k: 'TEMPORARY_OUTPUT' for k in saidas}),
                context=context, feedback=feedback, is_child_algorithm=True)
        except Exception as erro:
            feedback.reportError(self.tr(f'Relevo: falhou ({erro}).'))
            return ['Relevo: não calculado']
        projeto = context.project() or QgsProject.instance()
        grupo = grupoPorCaminho(projeto.layerTreeRoot(), GRUPO_APOIO)
        resumo = []
        for chave, nome in saidas.items():
            camada = context.takeResultLayer(resultado.get(chave)) if resultado.get(chave) else None
            if camada is None:
                continue
            for antiga in projeto.mapLayersByName(nome):
                projeto.removeMapLayer(antiga.id())
            camada.setName(nome)
            projeto.addMapLayer(camada, False)
            grupo.addLayer(camada)
            resumo.append(f'{nome}: {camada.featureCount()} feição(ões) (temporária)')
        return resumo

    def flags(self):
        # Grava nas camadas fixas do projeto: precisa da thread principal
        return super().flags() | Qgis.ProcessingAlgorithmFlag.NoThreading

    def name(self):
        return 'consultartudocar'

    def displayName(self):
        return self.tr('a. Consultar tudo')

    def group(self):
        return self.tr('1. 🔍 Consultas')

    def groupId(self):
        return 'consultas'

    def tr(self, string):
        return QCoreApplication.translate('Processing', string)

    def createInstance(self):
        return ConsultarTudoCAR()

    def tags(self):
        return ('GeoOne,GeoCAR,consultar tudo,SICAR,SIGEF,INCRA,restrições,UC,terra indígena,embargo,PRODES,'
                'desmatamento,MDT,declividade,altitude').split(',')

    def icon(self):
        return QIcon(os.path.join(os.path.dirname(os.path.dirname(__file__)), 'images/geocar.png'))

    def shortHelpString(self):
        txt = """Faz <b>todas as consultas do grupo 1 de uma vez</b>, pela extensão da ATI, e grava cada resultado na sua camada do grupo <b>Pré-Análise (GeoCAR) › Consultas</b> (no <b>Pre-Analise/PreAnalise.gpkg</b>):

• <b>b. Consulta CAR</b>: imóveis vizinhos no SICAR (CAR_Vizinhos_SICAR), 1 km em volta da ATI;
• <b>c. Consulta SIGEF</b>: parcelas certificadas pelo INCRA (Parcelas_SIGEF), 1 km em volta;
• <b>e. Consulta de restrições</b>: UC, terras indígenas, assentamentos e embargos (Restricoes_Territoriais), 2 km em volta;
• <b>f. Consulta desmatamento</b>: PRODES/INPE (Desmatamento_PRODES), 500 m em volta;
• <b>d. APP de altitude e declividade</b>: só se você informar o <b>MDT</b>. As camadas saem temporárias no grupo Apoio.

Cada consulta <b>refaz</b> a anterior, mesmo que já tenha sido feita. Se um serviço estiver fora do ar, a camada antiga é mantida e as outras consultas continuam.

Não é obrigatório rodar antes da pré-análise: a <b>3c</b> faz sozinha as consultas que ainda não foram feitas. Use esta ferramenta para começar um imóvel novo ou para <b>atualizar</b> tudo (por exemplo, depois de mudar a ATI ou quando os dados oficiais forem atualizados). Para ajustar a margem ou outras opções, use a ferramenta individual (b a f).
""" + avisoLegal()
        return txt + rodapeAjuda()
