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
# Valida a geometria da ATI e verifica sobreposições com camadas de restrição
# validacaoSobreposicoes.py

__author__ = 'Prof Cazaroli e Leandro França'
__date__ = '2026-10-23'
__copyright__ = '(C) 2026 by Prof Cazaroli e Leandro França'

import os

from qgis.PyQt.QtCore import QCoreApplication
from qgis.PyQt.QtGui import QIcon
from qgis.core import (
    Qgis,
    QgsGeometry,
    QgsProcessingAlgorithm,
    QgsProcessingException,
    QgsProcessingOutputNumber,
    QgsProcessingParameterBoolean,
    QgsProcessingParameterFeatureSink,
    QgsProcessingParameterMultipleLayers,
    QgsProcessingParameterNumber,
    QgsProcessingParameterVectorLayer,
    QgsVectorLayer,
)

from .nucleoCAR.processingCAR import (adicionarSaida, avisoLegal, camadaPadrao, camadasPadrao, gravarResultado,
                                      rodapeAjuda)
from .nucleoCAR.sobreposicao import (CLASSE_DIVISA, CLASSE_RELEVANTE, LARGURA_DIVISA_PADRAO, PERC_DIVISA_PADRAO,
                                     analisar_sobreposicoes)
from .nucleoCAR.utils import (adicionar_feicao, area_ha, criar_camada_memoria,
                              src_utm_sirgas, uniao)
from .nucleoCAR.validacao import validar_perimetro, verificar_extrapolacao


class ValidacaoSobreposicoesCAR(QgsProcessingAlgorithm):
    """Validação geométrica da ATI e sobreposição com camadas de restrição."""

    INPUT_ATI = 'INPUT_ATI'
    INPUT_RESTRICOES = 'INPUT_RESTRICOES'
    INPUT_VEGETACAO = 'INPUT_VEGETACAO'
    INPUT_CONSOLIDADA = 'INPUT_CONSOLIDADA'
    LARGURA_DIVISA = 'LARGURA_DIVISA'
    AUTO_CONSULTAS = 'AUTO_CONSULTAS'
    PERC_DIVISA = 'PERC_DIVISA'
    OUTPUT_PROBLEMAS = 'OUTPUT_PROBLEMAS'
    OUTPUT_SOBREPOSICOES = 'OUTPUT_SOBREPOSICOES'
    OUTPUT_N_PROBLEMAS = 'OUTPUT_N_PROBLEMAS'
    OUTPUT_AREA_SOBREPOSTA = 'OUTPUT_AREA_SOBREPOSTA'
    OUTPUT_AREA_RELEVANTE = 'OUTPUT_AREA_RELEVANTE'

    def initAlgorithm(self, config=None):
        poligono = Qgis.ProcessingSourceType.VectorPolygon

        self.addParameter(QgsProcessingParameterVectorLayer(
            self.INPUT_ATI, self.tr('Área Total do Imóvel (ATI)'), [poligono],
            defaultValue=camadaPadrao('ati') or 'ATI'))

        self.addParameter(QgsProcessingParameterMultipleLayers(
            self.INPUT_RESTRICOES,
            self.tr('Camadas de restrição (CARs vizinhos, SIGEF, UC, TI, assentamentos, embargos)'),
            layerType=poligono, optional=True, defaultValue=camadasPadrao('restricoes') or None))

        self.addParameter(QgsProcessingParameterVectorLayer(
            self.INPUT_VEGETACAO, self.tr('Vegetação nativa (opcional)'), [poligono], optional=True,
            defaultValue=camadaPadrao('vegetacao')))

        self.addParameter(QgsProcessingParameterVectorLayer(
            self.INPUT_CONSOLIDADA, self.tr('Área rural consolidada (opcional)'), [poligono],
            optional=True, defaultValue=camadaPadrao('consolidada')))

        self.addParameter(QgsProcessingParameterNumber(
            self.LARGURA_DIVISA, self.tr('Ajuste de divisa: largura média máxima da faixa (m)'),
            type=Qgis.ProcessingNumberParameterType.Double, minValue=0.0, defaultValue=LARGURA_DIVISA_PADRAO))
        self.addParameter(QgsProcessingParameterNumber(
            self.PERC_DIVISA, self.tr('Ajuste de divisa: área máxima (% do imóvel)'),
            type=Qgis.ProcessingNumberParameterType.Double, minValue=0.0, maxValue=100.0,
            defaultValue=PERC_DIVISA_PADRAO))

        self.addParameter(QgsProcessingParameterBoolean(
            self.AUTO_CONSULTAS, self.tr('Fazer as consultas que faltarem (vizinhos com CAR e restrições oficiais)'), defaultValue=True))
        adicionarSaida(self, self.OUTPUT_PROBLEMAS, 'Problemas de validação', 'Problemas_Validacao',
                       Qgis.ProcessingSourceType.VectorPoint)
        adicionarSaida(self, self.OUTPUT_SOBREPOSICOES, 'Sobreposições', 'Sobreposicoes', poligono)

        self.addOutput(QgsProcessingOutputNumber(self.OUTPUT_N_PROBLEMAS,
                                                 self.tr('Número de problemas')))
        self.addOutput(QgsProcessingOutputNumber(self.OUTPUT_AREA_SOBREPOSTA,
                                                 self.tr('Área sobreposta total (ha)')))
        self.addOutput(QgsProcessingOutputNumber(self.OUTPUT_AREA_RELEVANTE,
                                                 self.tr('Área em sobreposição relevante (ha)')))

    def processAlgorithm(self, parameters, context, feedback):
        camadaAti = self.parameterAsVectorLayer(parameters, self.INPUT_ATI, context)
        if camadaAti is None or camadaAti.featureCount() == 0:
            raise QgsProcessingException(self.tr('A camada ATI está vazia ou não foi informada.'))

        camadasRestricao = [c for c in self.parameterAsLayerList(parameters, self.INPUT_RESTRICOES, context)
                            if isinstance(c, QgsVectorLayer)]
        if self.parameterAsBool(parameters, self.AUTO_CONSULTAS, context):
            from .nucleoCAR.consultas import completarRestricoes, completarVizinhos
            camadasRestricao = completarVizinhos(context, feedback, camadaAti, camadasRestricao)
            camadasRestricao = completarRestricoes(context, feedback, camadaAti, camadasRestricao)
        camadaVegetacao = self.parameterAsVectorLayer(parameters, self.INPUT_VEGETACAO, context)
        camadaConsolidada = self.parameterAsVectorLayer(parameters, self.INPUT_CONSOLIDADA, context)

        # SRC de trabalho: SIRGAS 2000 / UTM do fuso do imóvel
        geomReferencia = QgsGeometry.unaryUnion(
            [f.geometry().makeValid() for f in camadaAti.getFeatures() if f.hasGeometry()])
        srcTrabalho = src_utm_sirgas(geomReferencia, camadaAti.crs())
        feedback.pushInfo(self.tr(f'SRC de cálculo: {srcTrabalho.authid()} — {srcTrabalho.description()}'))

        # 1. Validação geométrica
        feedback.pushInfo(self.tr('Validando a geometria da ATI...'))
        problemas, parcelas = validar_perimetro(camadaAti, srcTrabalho)
        perimetro = uniao([g.makeValid() for _fid, g in parcelas])
        areaImovel = area_ha(perimetro)

        for camada, tema in ((camadaVegetacao, 'Vegetação nativa'), (camadaConsolidada, 'Área consolidada')):
            if camada is not None:
                _geom, problema = verificar_extrapolacao(camada, tema, perimetro, srcTrabalho)
                if problema:
                    problemas.append(problema)
        if feedback.isCanceled():
            return {}

        # 2. Sobreposições
        feedback.pushInfo(self.tr(f'Cruzando a ATI com {len(camadasRestricao)} camada(s) de restrição...'))
        larguraDivisa = self.parameterAsDouble(parameters, self.LARGURA_DIVISA, context)
        percDivisa = self.parameterAsDouble(parameters, self.PERC_DIVISA, context)
        sobreposicoes = analisar_sobreposicoes(perimetro, areaImovel, camadasRestricao, srcTrabalho,
                                               larguraDivisa, percDivisa)

        # 3. Saídas
        camadaProblemas = criar_camada_memoria('Problemas', 'Point', srcTrabalho,
                                               [('feicao', 'string'), ('tipo', 'string'),
                                                ('descricao', 'string')])
        for problema in problemas:
            adicionar_feicao(camadaProblemas, QgsGeometry.fromPointXY(problema['ponto']),
                             [str(problema['feicao']), problema['tipo'], problema['descricao']])

        camadaSobreposicoes = criar_camada_memoria('Sobreposicoes', 'MultiPolygon', srcTrabalho,
                                                   [('camada', 'string'), ('identific', 'string'),
                                                    ('classe', 'string'), ('area_ha', 'double'),
                                                    ('perc', 'double'), ('larg_med', 'double')])
        for item in sobreposicoes:
            adicionar_feicao(camadaSobreposicoes, item['geometria'],
                             [item['camada'], item['identificador'], item['classe'],
                              round(item['area_ha'], 4), round(item['percentual'], 2),
                              round(item['largura_m'], 2)])

        idProblemas = gravarResultado(self, parameters, self.OUTPUT_PROBLEMAS, context, feedback,
                                      camadaProblemas, 'Problemas_Validacao')
        idSobreposicoes = gravarResultado(self, parameters, self.OUTPUT_SOBREPOSICOES, context, feedback,
                                          camadaSobreposicoes, 'Sobreposicoes')

        # Resumo no log
        areaSobreposta = sum(item['area_ha'] for item in sobreposicoes)
        relevantes = [item for item in sobreposicoes if item['classe'] == CLASSE_RELEVANTE]
        areaRelevante = sum(item['area_ha'] for item in relevantes)
        feedback.pushInfo(self.tr(f'Área da ATI: {areaImovel:.4f} ha em {len(parcelas)} feição(ões).'))
        for problema in problemas:
            feedback.reportError(f"[{problema['tipo']}] {problema['descricao']}", fatalError=False)
        for item in sobreposicoes:
            texto = (f"{item['classe']} com {item['camada']} {item['identificador']}: "
                     f"{item['area_ha']:.4f} ha ({item['percentual']:.2f}%; largura média {item['largura_m']:.1f} m)")
            if item['classe'] == CLASSE_RELEVANTE:
                feedback.pushWarning(texto)
            else:
                feedback.pushInfo(texto)
        if sobreposicoes:
            divisas = [item for item in sobreposicoes if item['classe'] == CLASSE_DIVISA]
            informativas = len(sobreposicoes) - len(relevantes) - len(divisas)
            feedback.pushInfo(self.tr(f'Sobreposição relevante: {areaRelevante:.4f} ha em {len(relevantes)} feição(ões) | '
                                      f'Ajuste de divisa: {sum(i["area_ha"] for i in divisas):.4f} ha em '
                                      f'{len(divisas)} feição(ões)' + (f' | Informativa (APA): {informativas}'
                                                                      if informativas else '')))
        if not problemas and not sobreposicoes:
            feedback.pushInfo(self.tr('Nenhum problema geométrico ou sobreposição encontrado.'))
        feedback.pushInfo(self.tr('GeoCAR - GeoOne'))

        resultados = {chave: valor for chave, valor in ((self.OUTPUT_PROBLEMAS, idProblemas),
                                                         (self.OUTPUT_SOBREPOSICOES, idSobreposicoes)) if valor}
        return dict(resultados, **{
            self.OUTPUT_N_PROBLEMAS: len(problemas),
            self.OUTPUT_AREA_SOBREPOSTA: round(areaSobreposta, 4),
            self.OUTPUT_AREA_RELEVANTE: round(areaRelevante, 4),
        })

    def flags(self):
        # Grava nas camadas fixas do projeto: precisa rodar na thread principal
        return super().flags() | Qgis.ProcessingAlgorithmFlag.NoThreading

    def name(self):
        return 'validacaosobreposicoescar'

    def displayName(self):
        return self.tr('a. Validação e sobreposições')

    def group(self):
        return self.tr('3. ✅ Pré-análise do CAR')

    def groupId(self):
        return 'preanalise'

    def tr(self, string):
        return QCoreApplication.translate('Processing', string)

    def createInstance(self):
        return ValidacaoSobreposicoesCAR()

    def tags(self):
        return ('GeoOne,GeoCAR,GeoRural,ambiental,SiCAR,validação,topologia,geometria inválida,'
                'sobreposição,vizinho,SIGEF,UC,terra indígena,embargo,pré-análise').split(',')

    def icon(self):
        return QIcon(os.path.join(os.path.dirname(os.path.dirname(__file__)), 'images/qualidade.png'))

    def shortHelpString(self):
        txt = """Faz a <b>pré-análise geométrica</b> da Área Total do Imóvel (ATI) antes do envio ou da retificação do CAR.

<b>Validação da ATI:</b>
• geometrias inválidas (GEOS)
• vértices consecutivos duplicados
• imóvel multiparte
• sobreposição entre as feições da própria ATI
• vegetação nativa ou área consolidada fora da ATI

<b>Sobreposições:</b> cruza a ATI com as camadas de restrição escolhidas (por exemplo, o resultado da ferramenta <b>Consulta CAR</b>, parcelas SIGEF, UCs, Terras Indígenas, assentamentos e embargos) e informa a área e o percentual do imóvel atingido.

<b>Classificação das sobreposições:</b>
• <b>Ajuste de divisa</b> — faixa estreita ao longo do limite (largura média = 2·área/perímetro até o valor informado, padrão 15 m) e pequena (até o % do imóvel informado, padrão 2%). É típica de limites digitalizados sobre imagens diferentes.
• <b>Sobreposição relevante</b> — demais casos: conflito de área (CAR duplicado, matrícula-mãe e desmembramentos, posse e propriedade declaradas em CARs diferentes).

Os cálculos são feitos em <b>SIRGAS 2000 / UTM</b> do fuso do imóvel, escolhido automaticamente.
<b>Resultados:</b> vão para as camadas do grupo <b>Pré-Análise (GeoCAR) › Resultados</b>, no <b>Pre-Analise/PreAnalise.gpkg</b> do projeto (criado na primeira execução, se ainda não existir), apagando os anteriores; as saídas desta tela são cópias opcionais. Com o projeto ainda não salvo, os resultados saem em camadas temporárias. As entradas já vêm preenchidas com as camadas da RAIZ. <b>Consultas:</b> se os vizinhos com CAR ou as restrições oficiais ainda não foram consultados no projeto, a ferramenta faz as consultas sozinha (só na primeira vez).
""" + avisoLegal()
        return txt + rodapeAjuda()
