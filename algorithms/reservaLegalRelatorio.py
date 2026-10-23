# -*- coding: utf-8 -*-

"""
/***************************************************************************
 GeoCAR
                                 A QGIS plugin
Cadastro Ambiental Rural (CAR)
                              -------------------
        begin                : 2026-10-23
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
# Estima a Reserva Legal e gera o relatório HTML completo da pré-análise do CAR
# reservaLegalRelatorio.py

__author__ = 'Prof Cazaroli e Leandro França'
__date__ = '2026-10-23'
__copyright__ = '(C) 2026 by Prof Cazaroli e Leandro França'

import os

from qgis.PyQt.QtCore import QCoreApplication
from qgis.PyQt.QtGui import QIcon
from qgis.core import (
    Qgis,
    QgsProcessingAlgorithm,
    QgsProcessingException,
    QgsProcessingOutputNumber,
    QgsProcessingParameterEnum,
    QgsProcessingParameterField,
    QgsProcessingParameterFileDestination,
    QgsProcessingParameterMultipleLayers,
    QgsProcessingParameterNumber,
    QgsProcessingParameterVectorLayer,
    QgsVectorLayer,
)

from .nucleoCAR import analise
from .nucleoCAR.processingCAR import OPCOES_RL, VALORES_RL, avisoLegal, rodapeAjuda


class ReservaLegalRelatorioCAR(QgsProcessingAlgorithm):
    """Reserva Legal e relatório HTML consolidado (validação, sobreposições, APP e RL)."""

    INPUT_ATI = 'INPUT_ATI'
    MODULO_FISCAL = 'MODULO_FISCAL'
    AREA_2008 = 'AREA_2008'
    PERCENTUAL_RL = 'PERCENTUAL_RL'
    INPUT_VEGETACAO = 'INPUT_VEGETACAO'
    INPUT_CONSOLIDADA = 'INPUT_CONSOLIDADA'
    INPUT_HIDROGRAFIA = 'INPUT_HIDROGRAFIA'
    CAMPO_LARGURA = 'CAMPO_LARGURA'
    LARGURA_PADRAO = 'LARGURA_PADRAO'
    INPUT_NASCENTES = 'INPUT_NASCENTES'
    INPUT_LAGOS = 'INPUT_LAGOS'
    INPUT_RESTRICOES = 'INPUT_RESTRICOES'
    OUTPUT_HTML = 'OUTPUT_HTML'

    OUTPUT_RL_EXIGIDA = 'OUTPUT_RL_EXIGIDA'
    OUTPUT_VEGETACAO = 'OUTPUT_VEGETACAO'
    OUTPUT_DEFICIT_COM_APP = 'OUTPUT_DEFICIT_COM_APP'
    OUTPUT_DEFICIT_SEM_APP = 'OUTPUT_DEFICIT_SEM_APP'

    def initAlgorithm(self, config=None):
        poligono = Qgis.ProcessingSourceType.VectorPolygon
        decimal = Qgis.ProcessingNumberParameterType.Double

        self.addParameter(QgsProcessingParameterVectorLayer(
            self.INPUT_ATI, self.tr('Área Total do Imóvel (ATI)'), [poligono], defaultValue='ATI'))
        self.addParameter(QgsProcessingParameterNumber(
            self.MODULO_FISCAL, self.tr('Módulo fiscal do município (ha)'), type=decimal,
            minValue=0.01, defaultValue=20.0))
        self.addParameter(QgsProcessingParameterNumber(
            self.AREA_2008, self.tr('Área do imóvel em 22/07/2008 (ha) — 0 = usar a área da ATI'),
            type=decimal, minValue=0.0, defaultValue=0.0))
        self.addParameter(QgsProcessingParameterEnum(
            self.PERCENTUAL_RL, self.tr('Percentual de Reserva Legal (art. 12)'),
            options=OPCOES_RL, defaultValue=0))
        self.addParameter(QgsProcessingParameterVectorLayer(
            self.INPUT_VEGETACAO, self.tr('Vegetação nativa'), [poligono], optional=True))
        self.addParameter(QgsProcessingParameterVectorLayer(
            self.INPUT_CONSOLIDADA, self.tr('Área rural consolidada até 22/07/2008'), [poligono],
            optional=True))
        self.addParameter(QgsProcessingParameterVectorLayer(
            self.INPUT_HIDROGRAFIA, self.tr("Cursos d'água — eixo (linhas)"),
            [Qgis.ProcessingSourceType.VectorLine], optional=True))
        self.addParameter(QgsProcessingParameterField(
            self.CAMPO_LARGURA, self.tr("Campo com a largura do curso d'água (m)"),
            parentLayerParameterName=self.INPUT_HIDROGRAFIA,
            type=Qgis.ProcessingFieldParameterDataType.Numeric, optional=True))
        self.addParameter(QgsProcessingParameterNumber(
            self.LARGURA_PADRAO, self.tr('Largura padrão quando não houver dado (m)'),
            type=decimal, minValue=0.1, defaultValue=5.0))
        self.addParameter(QgsProcessingParameterVectorLayer(
            self.INPUT_NASCENTES, self.tr("Nascentes e olhos d'água (pontos)"),
            [Qgis.ProcessingSourceType.VectorPoint], optional=True))
        self.addParameter(QgsProcessingParameterVectorLayer(
            self.INPUT_LAGOS, self.tr('Lagos e lagoas naturais (polígonos)'), [poligono],
            optional=True))
        self.addParameter(QgsProcessingParameterMultipleLayers(
            self.INPUT_RESTRICOES, self.tr('Camadas de restrição (sobreposição)'),
            layerType=poligono, optional=True))
        self.addParameter(QgsProcessingParameterFileDestination(
            self.OUTPUT_HTML, self.tr('Relatório de pré-análise'),
            fileFilter='HTML (*.html)'))

        self.addOutput(QgsProcessingOutputNumber(self.OUTPUT_RL_EXIGIDA, self.tr('RL exigida (ha)')))
        self.addOutput(QgsProcessingOutputNumber(self.OUTPUT_VEGETACAO, self.tr('Vegetação nativa (ha)')))
        self.addOutput(QgsProcessingOutputNumber(self.OUTPUT_DEFICIT_COM_APP,
                                                 self.tr('Déficit de RL com cômputo da APP (ha)')))
        self.addOutput(QgsProcessingOutputNumber(self.OUTPUT_DEFICIT_SEM_APP,
                                                 self.tr('Déficit de RL sem cômputo da APP (ha)')))

    def processAlgorithm(self, parameters, context, feedback):
        camadaAti = self.parameterAsVectorLayer(parameters, self.INPUT_ATI, context)
        if camadaAti is None or camadaAti.featureCount() == 0:
            raise QgsProcessingException(self.tr('A camada ATI está vazia ou não foi informada.'))

        caminhoHtml = self.parameterAsFileOutput(parameters, self.OUTPUT_HTML, context)
        indiceRl = self.parameterAsEnum(parameters, self.PERCENTUAL_RL, context)

        parametrosAnalise = {
            'perimetro': camadaAti,
            'modulo_fiscal_ha': self.parameterAsDouble(parameters, self.MODULO_FISCAL, context),
            'area_2008_ha': self.parameterAsDouble(parameters, self.AREA_2008, context),
            'pct_rl': VALORES_RL[indiceRl],
            'vegetacao': self.parameterAsVectorLayer(parameters, self.INPUT_VEGETACAO, context),
            'consolidada': self.parameterAsVectorLayer(parameters, self.INPUT_CONSOLIDADA, context),
            'hidrografia': self.parameterAsVectorLayer(parameters, self.INPUT_HIDROGRAFIA, context),
            'campo_largura': self.parameterAsString(parameters, self.CAMPO_LARGURA, context) or None,
            'largura_padrao': self.parameterAsDouble(parameters, self.LARGURA_PADRAO, context),
            'nascentes': self.parameterAsVectorLayer(parameters, self.INPUT_NASCENTES, context),
            'lagos': self.parameterAsVectorLayer(parameters, self.INPUT_LAGOS, context),
            'restricoes': [c for c in self.parameterAsLayerList(parameters, self.INPUT_RESTRICOES, context)
                           if isinstance(c, QgsVectorLayer)],
            'caminho_relatorio': caminhoHtml,
        }

        feedback.pushInfo(self.tr('Executando a pré-análise completa (validação, sobreposições, APP e RL)...'))
        try:
            resultado = analise.executar(parametrosAnalise)
        except ValueError as erro:
            raise QgsProcessingException(str(erro))

        resumo = resultado['resumo']
        rl = resumo['rl']
        feedback.pushInfo(self.tr(f"Área: {resumo['area_imovel_ha']:.4f} ha | "
                                  f"Módulos fiscais: {resumo['n_modulos']:.2f}"))
        feedback.pushInfo(self.tr(f"RL exigida ({rl['percentual']:g}%): {rl['exigida_ha']:.4f} ha | "
                                  f"Vegetação nativa: {rl['vegetacao_ha']:.4f} ha"))
        feedback.pushInfo(self.tr(f"Déficit com cômputo da APP: {rl['deficit_com_app_ha']:.4f} ha | "
                                  f"sem cômputo: {rl['deficit_sem_app_ha']:.4f} ha"))
        for observacao in rl['observacoes']:
            feedback.pushWarning(observacao)
        feedback.pushInfo(self.tr(f'Relatório gravado em: {caminhoHtml}'))
        feedback.pushInfo(self.tr('GeoCAR - GeoOne'))

        return {
            self.OUTPUT_HTML: caminhoHtml,
            self.OUTPUT_RL_EXIGIDA: round(rl['exigida_ha'], 4),
            self.OUTPUT_VEGETACAO: round(rl['vegetacao_ha'], 4),
            self.OUTPUT_DEFICIT_COM_APP: round(rl['deficit_com_app_ha'], 4),
            self.OUTPUT_DEFICIT_SEM_APP: round(rl['deficit_sem_app_ha'], 4),
        }

    def name(self):
        return 'reservalegalrelatoriocar'

    def displayName(self):
        return self.tr('c. Reserva Legal e relatório de pré-análise')

    def group(self):
        return self.tr('3. ✅ Pré-análise do CAR')

    def groupId(self):
        return 'preanalise'

    def tr(self, string):
        return QCoreApplication.translate('Processing', string)

    def createInstance(self):
        return ReservaLegalRelatorioCAR()

    def tags(self):
        return ('GeoOne,GeoCAR,GeoRural,ambiental,SiCAR,reserva legal,RL,déficit,compensação,'
                'relatório,pré-análise,Código Florestal,art. 67,art. 15').split(',')

    def icon(self):
        return QIcon(os.path.join(os.path.dirname(os.path.dirname(__file__)), 'images/qualidade.png'))

    def shortHelpString(self):
        txt = """Executa a <b>pré-análise completa do CAR</b> e gera um <b>relatório HTML</b>.

<b>Reserva Legal:</b>
• RL exigida pelo percentual do art. 12 (20%, 35% ou 80%)
• vegetação nativa existente na ATI
• déficit <b>com</b> e <b>sem</b> o cômputo da APP na RL (art. 15)
• alerta do <b>art. 67</b> para imóveis de até 4 módulos fiscais em 22/07/2008

<b>O relatório também reúne:</b> validação geométrica da ATI, sobreposições, APP hídrica integral, faixa da escadinha e teto do art. 61-B — as mesmas análises das ferramentas <b>Validação e sobreposições</b> e <b>APP hídrica e escadinha</b>.

As áreas calculadas ficam disponíveis como saídas numéricas, para uso em modelos do Processing.
""" + avisoLegal()
        return txt + rodapeAjuda()
