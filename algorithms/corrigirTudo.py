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
# Roda as correções do grupo 4 de uma vez, na ordem certa
# corrigirTudo.py

__author__ = 'Prof Cazaroli e Leandro França'
__date__ = '2026-10-26'
__copyright__ = '(C) 2026 by Prof Cazaroli e Leandro França'

import os

from qgis.PyQt.QtCore import QCoreApplication
from qgis.PyQt.QtGui import QIcon
from qgis.core import (
    Qgis,
    QgsProcessingAlgorithm,
    QgsProcessingException,
    QgsProcessingMultiStepFeedback,
    QgsProcessingParameterBoolean,
    QgsProcessingParameterEnum,
    QgsProcessingParameterMultipleLayers,
    QgsProcessingParameterNumber,
    QgsProcessingParameterVectorLayer,
    QgsVectorLayer,
)

from .nucleoCAR.processingCAR import avisoLegal, camadaPadrao, camadasPadrao, rodapeAjuda


class CorrigirTudoCAR(QgsProcessingAlgorithm):
    """Correções do grupo 4 em sequência: geometria da ATI, recorte, sobreposições, lascas (e rascunho de RL)."""

    INPUT_ATI = 'INPUT_ATI'
    INPUT_COBERTURAS = 'INPUT_COBERTURAS'
    INPUT_RESERVAS = 'INPUT_RESERVAS'
    INPUT_SERVIDOES = 'INPUT_SERVIDOES'
    GEOMETRIA = 'GEOMETRIA'
    RECORTAR = 'RECORTAR'
    SOBREPOSICOES = 'SOBREPOSICOES'
    LASCAS = 'LASCAS'
    RASCUNHO_RL = 'RASCUNHO_RL'
    PRIORIDADE = 'PRIORIDADE'
    AREA_MAXIMA = 'AREA_MAXIMA'
    SALVAR = 'SALVAR'
    REFAZER_PREANALISE = 'REFAZER_PREANALISE'
    LIMPAR_HISTORICO = 'LIMPAR_HISTORICO'

    PRIORIDADES = ['Vegetação nativa > área consolidada > pousio',
                   'Área consolidada > vegetação nativa > pousio']

    def initAlgorithm(self, config=None):
        poligono = Qgis.ProcessingSourceType.VectorPolygon
        self.addParameter(QgsProcessingParameterVectorLayer(
            self.INPUT_ATI, self.tr('Área Total do Imóvel (ATI)'), [poligono], defaultValue=camadaPadrao('ati') or 'ATI'))
        coberturas = []
        for chave in ('vegetacao', 'coberturas'):
            coberturas += [n for n in camadasPadrao(chave) if n not in coberturas]
        self.addParameter(QgsProcessingParameterMultipleLayers(
            self.INPUT_COBERTURAS, self.tr('Camadas de cobertura do solo (vegetação nativa, área consolidada, pousio...)'),
            layerType=poligono, optional=True, defaultValue=coberturas or None))
        self.addParameter(QgsProcessingParameterMultipleLayers(
            self.INPUT_RESERVAS, self.tr('Reserva Legal (proposta, averbada, aprovada...)'),
            layerType=poligono, optional=True, defaultValue=camadasPadrao('reservas') or None))
        self.addParameter(QgsProcessingParameterMultipleLayers(
            self.INPUT_SERVIDOES, self.tr('Servidão administrativa (polígonos)'),
            layerType=poligono, optional=True, defaultValue=camadasPadrao('servidoes') or None))

        for chave, rotulo, padrao in (
                (self.GEOMETRIA, 'b. Corrigir geometria da ATI', True),
                (self.RECORTAR, 'c. Recortar camadas pela ATI', True),
                (self.SOBREPOSICOES, 'd. Resolver sobreposições entre camadas', True),
                (self.LASCAS, 'e. Preencher lascas sem cobertura', True),
                (self.RASCUNHO_RL, 'f. Rascunho de Reserva Legal (proposta, não correção)', False)):
            self.addParameter(QgsProcessingParameterBoolean(chave, self.tr(rotulo), defaultValue=padrao))

        self.addParameter(QgsProcessingParameterEnum(
            self.PRIORIDADE, self.tr('Na sobreposição entre coberturas, prevalece'),
            options=[self.tr(p) for p in self.PRIORIDADES], defaultValue=0))
        self.addParameter(QgsProcessingParameterNumber(
            self.AREA_MAXIMA, self.tr('Área máxima de cada lasca a preencher (m²)'),
            type=Qgis.ProcessingNumberParameterType.Double, minValue=1.0, defaultValue=500.0))
        self.addParameter(QgsProcessingParameterBoolean(
            self.SALVAR, self.tr('Salvar as alterações (desmarcado: ficam em edição para conferir)'),
            defaultValue=False))
        self.addParameter(QgsProcessingParameterBoolean(
            self.REFAZER_PREANALISE, self.tr('No fim, refazer a pré-análise (3c) para conferir as pendências'),
            defaultValue=True))
        self.addParameter(QgsProcessingParameterBoolean(
            self.LIMPAR_HISTORICO, self.tr('Começar histórico novo (apaga o registro das correções anteriores)'),
            defaultValue=False))

    def processAlgorithm(self, parameters, context, feedback):
        import processing   # importado aqui: o provider carrega antes do Processing estar pronto

        camadaAti = self.parameterAsVectorLayer(parameters, self.INPUT_ATI, context)
        if camadaAti is None or camadaAti.featureCount() == 0:
            raise QgsProcessingException(self.tr('A camada ATI está vazia ou não foi informada.'))

        def lista(chave):
            return [c for c in self.parameterAsLayerList(parameters, chave, context)
                    if isinstance(c, QgsVectorLayer) and c.id() != camadaAti.id()]

        coberturas, reservas, servidoes = (lista(self.INPUT_COBERTURAS), lista(self.INPUT_RESERVAS),
                                           lista(self.INPUT_SERVIDOES))
        salvar = self.parameterAsBool(parameters, self.SALVAR, context)
        comum = {'INPUT_ATI': camadaAti, 'SALVAR': salvar}
        recortar = coberturas + [c for c in reservas + servidoes if c not in coberturas]

        etapas = []
        if self.parameterAsBool(parameters, self.GEOMETRIA, context):
            etapas.append(('b. Corrigir geometria da ATI', 'GeoCAR:corrigirgeometriaaticar', dict(comum)))
        if self.parameterAsBool(parameters, self.RECORTAR, context):
            if recortar:
                etapas.append(('c. Recortar camadas pela ATI', 'GeoCAR:recortarpelaaticar',
                               dict(comum, INPUT_CAMADAS=recortar)))
            else:
                feedback.pushWarning(self.tr('c. Recortar: nenhuma camada informada.'))
        if self.parameterAsBool(parameters, self.SOBREPOSICOES, context):
            if coberturas or reservas:
                etapas.append(('d. Resolver sobreposições entre camadas', 'GeoCAR:resolversobreposicoescar',
                               dict(comum, INPUT_COBERTURAS=coberturas, INPUT_RESERVAS=reservas,
                                    INPUT_SERVIDOES=servidoes,
                                    PRIORIDADE=self.parameterAsEnum(parameters, self.PRIORIDADE, context))))
            else:
                feedback.pushWarning(self.tr('d. Sobreposições: nenhuma camada de cobertura ou RL informada.'))
        if self.parameterAsBool(parameters, self.LASCAS, context):
            if coberturas:
                etapas.append(('e. Preencher lascas sem cobertura', 'GeoCAR:preencherlascascar',
                               dict(comum, INPUT_COBERTURAS=coberturas, INPUT_SERVIDOES=servidoes,
                                    AREA_MAXIMA=self.parameterAsDouble(parameters, self.AREA_MAXIMA, context))))
            else:
                feedback.pushWarning(self.tr('e. Lascas: nenhuma camada de cobertura informada.'))
        if self.parameterAsBool(parameters, self.RASCUNHO_RL, context):
            vegetacao = next((c for c in coberturas if 'vegeta' in c.name().lower() or c.name().lower() == 'avn'),
                             None)
            if vegetacao is None:
                feedback.pushWarning(self.tr('f. Rascunho de RL: camada de vegetação nativa não encontrada.'))
            else:
                etapas.append(('f. Rascunho de Reserva Legal', 'GeoCAR:propostareservalegalcar',
                               {'INPUT_ATI': camadaAti, 'INPUT_VEGETACAO': vegetacao, 'INPUT_RESERVAS': reservas,
                                'INPUT_SERVIDOES': servidoes}))
        refazer = self.parameterAsBool(parameters, self.REFAZER_PREANALISE, context)
        if refazer:
            etapas.append(('Pré-análise de conferência (3c)', 'GeoCAR:reservalegalrelatoriocar',
                           {'INPUT_ATI': camadaAti}))
        if not etapas:
            raise QgsProcessingException(self.tr('Nenhuma etapa marcada.'))

        if self.parameterAsBool(parameters, self.LIMPAR_HISTORICO, context):
            from .nucleoCAR.registro_correcoes import limparHistorico
            apagadas = limparHistorico(context.project())
            feedback.pushInfo(self.tr(f'Histórico de correções apagado ({apagadas} registro(s)).'))

        passos = QgsProcessingMultiStepFeedback(len(etapas), feedback)
        resultados = {}
        for i, (titulo, algoritmo, parametros) in enumerate(etapas):
            if feedback.isCanceled():
                break
            passos.setCurrentStep(i)
            feedback.pushInfo('')
            feedback.pushInfo(self.tr(f'===== {titulo} ====='))
            try:
                resultado = processing.run(algoritmo, parametros, context=context, feedback=passos,
                                           is_child_algorithm=True)
            except QgsProcessingException as erro:
                feedback.reportError(self.tr(f'{titulo}: {erro}'), fatalError=False)
                continue
            resultados[titulo] = {k: v for k, v in resultado.items() if isinstance(v, (int, float, str))}
        feedback.pushInfo('')
        feedback.pushInfo(self.tr('Correções registradas em Pre-Analise/GeoCAR_Correcoes_Pre-Analise_<data>.pdf.'))
        if not salvar:
            feedback.pushWarning(self.tr('As camadas corrigidas estão em edição: confira no mapa e salve '
                                         '(ou descarte) as alterações.'))
        return {}

    def flags(self):
        # As etapas editam camadas do projeto: precisa da thread principal
        return super().flags() | Qgis.ProcessingAlgorithmFlag.NoThreading

    def name(self):
        return 'corrigirtudocar'

    def displayName(self):
        return self.tr('a. Corrigir tudo')

    def group(self):
        return self.tr('4. 🔧 Correções')

    def groupId(self):
        return 'correcoes'

    def tr(self, string):
        return QCoreApplication.translate('Processing', string)

    def createInstance(self):
        return CorrigirTudoCAR()

    def tags(self):
        return 'GeoOne,GeoCAR,correção,corrigir,ATI,sobreposição,lasca,geometria,Reserva Legal'.split(',')

    def icon(self):
        return QIcon(os.path.join(os.path.dirname(os.path.dirname(__file__)), 'images/vetor.png'))

    def shortHelpString(self):
        txt = """Roda de uma vez as correções do grupo 4, <b>na ordem certa</b>:
<b>b.</b> geometria da ATI (define o limite) → <b>c.</b> recorte das camadas pela ATI → <b>d.</b> sobreposições entre camadas → <b>e.</b> lascas sem cobertura (medidas já sem sobreposição).

O <b>f. Rascunho de Reserva Legal</b> vem desmarcado: não corrige erro, propõe onde a RL fica, o que é escolha do proprietário.

Use as ferramentas separadas (b a f) para corrigir só um tipo de erro ou ajustar parâmetros finos, como as tolerâncias de vértice.

<b>Segurança:</b> as correções ficam no <b>modo de edição</b>, sem salvar; confira no mapa e salve ou descarte (Ctrl+Z desfaz). Marque <b>Salvar as alterações</b> para gravar direto.

Cada correção fica registrada no <b>Pre-Analise/GeoCAR_Correcoes_Pre-Analise_&lt;data&gt;.pdf</b>, com o fundamento legal. No fim, a pré-análise (3c) é refeita para conferir se as pendências sumiram.

O registro acompanha as camadas: ao <b>salvar</b> a edição, a correção passa a "salva" no relatório; ao <b>descartar</b>, ela sai do relatório. Marque <b>Começar histórico novo</b> só quando o projeto foi reaproveitado de outro imóvel.
""" + avisoLegal()
        return txt + rodapeAjuda()
