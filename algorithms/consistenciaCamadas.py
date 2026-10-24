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
# Verifica a consistência entre as camadas declaradas no CAR (coberturas, Reserva Legal e servidões)
# consistenciaCamadas.py

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
    QgsProcessingParameterMultipleLayers,
    QgsProcessingParameterVectorLayer,
    QgsVectorLayer,
)

from .nucleoCAR.consistencia import ERRO, verificar_consistencia
from .nucleoCAR.processingCAR import (adicionarSaida, avisoLegal, camadaPadrao, camadasPadrao, gravarResultado,
                                      rodapeAjuda)
from .nucleoCAR.utils import adicionar_feicao, area_ha, criar_camada_memoria, src_utm_sirgas, uniao
from .nucleoCAR.validacao import validar_perimetro


def camadaInconsistencias(itens, src):
    """Camada de memória com os itens da verificação de consistência."""
    camada = criar_camada_memoria('Inconsistências', 'MultiPolygon', src,
                                  [('gravidade', 'string'), ('tipo', 'string'), ('camadas', 'string'),
                                   ('area_ha', 'double'), ('descricao', 'string')])
    for item in itens:
        adicionar_feicao(camada, item['geometria'],
                         [item['gravidade'], item['tipo'], item['camadas'], round(item['area_ha'], 4),
                          item['descricao']])
    return camada


class ConsistenciaCamadasCAR(QgsProcessingAlgorithm):
    """Consistência entre as camadas do CAR: coberturas do solo, Reserva Legal e servidões."""

    INPUT_ATI = 'INPUT_ATI'
    INPUT_VEGETACAO = 'INPUT_VEGETACAO'
    INPUT_COBERTURAS = 'INPUT_COBERTURAS'
    INPUT_RESERVAS = 'INPUT_RESERVAS'
    INPUT_SERVIDOES = 'INPUT_SERVIDOES'
    OUTPUT_INCONSISTENCIAS = 'OUTPUT_INCONSISTENCIAS'
    OUTPUT_N_ERROS = 'OUTPUT_N_ERROS'
    OUTPUT_N_AVISOS = 'OUTPUT_N_AVISOS'

    def initAlgorithm(self, config=None):
        poligono = Qgis.ProcessingSourceType.VectorPolygon

        self.addParameter(QgsProcessingParameterVectorLayer(
            self.INPUT_ATI, self.tr('Área Total do Imóvel (ATI)'), [poligono],
            defaultValue=camadaPadrao('ati') or 'ATI'))
        self.addParameter(QgsProcessingParameterVectorLayer(
            self.INPUT_VEGETACAO, self.tr('Vegetação nativa'), [poligono], optional=True,
            defaultValue=camadaPadrao('vegetacao')))
        self.addParameter(QgsProcessingParameterMultipleLayers(
            self.INPUT_COBERTURAS, self.tr('Outras coberturas do solo (área consolidada, pousio...)'),
            layerType=poligono, optional=True, defaultValue=camadasPadrao('coberturas') or None))
        self.addParameter(QgsProcessingParameterMultipleLayers(
            self.INPUT_RESERVAS, self.tr('Reserva Legal (proposta, averbada, aprovada...)'),
            layerType=poligono, optional=True, defaultValue=camadasPadrao('reservas') or None))
        self.addParameter(QgsProcessingParameterMultipleLayers(
            self.INPUT_SERVIDOES, self.tr('Servidão administrativa (polígonos)'),
            layerType=poligono, optional=True, defaultValue=camadasPadrao('servidoes') or None))

        adicionarSaida(self, self.OUTPUT_INCONSISTENCIAS, 'Inconsistências', 'Inconsistencias', poligono)

        self.addOutput(QgsProcessingOutputNumber(self.OUTPUT_N_ERROS, self.tr('Número de erros')))
        self.addOutput(QgsProcessingOutputNumber(self.OUTPUT_N_AVISOS, self.tr('Número de avisos')))

    def processAlgorithm(self, parameters, context, feedback):
        camadaAti = self.parameterAsVectorLayer(parameters, self.INPUT_ATI, context)
        if camadaAti is None or camadaAti.featureCount() == 0:
            raise QgsProcessingException(self.tr('A camada ATI está vazia ou não foi informada.'))

        def lista(chave):
            return [c for c in self.parameterAsLayerList(parameters, chave, context)
                    if isinstance(c, QgsVectorLayer) and c.id() != camadaAti.id()]

        vegetacao = self.parameterAsVectorLayer(parameters, self.INPUT_VEGETACAO, context)
        coberturas, reservas, servidoes = (lista(self.INPUT_COBERTURAS), lista(self.INPUT_RESERVAS),
                                           lista(self.INPUT_SERVIDOES))

        geomReferencia = QgsGeometry.unaryUnion(
            [f.geometry().makeValid() for f in camadaAti.getFeatures() if f.hasGeometry()])
        srcTrabalho = src_utm_sirgas(geomReferencia, camadaAti.crs())
        _problemas, parcelas = validar_perimetro(camadaAti, srcTrabalho)
        perimetro = uniao([g.makeValid() for _fid, g in parcelas])
        feedback.pushInfo(self.tr(f'SRC de cálculo: {srcTrabalho.authid()} | ATI: {area_ha(perimetro):.4f} ha'))
        feedback.pushInfo(self.tr(f'Coberturas: {len(coberturas) + (vegetacao is not None)} | '
                                  f'Reserva Legal: {len(reservas)} | Servidões: {len(servidoes)} camada(s)'))

        itens = verificar_consistencia(perimetro, srcTrabalho, vegetacao, coberturas, reservas, servidoes)
        for item in itens:
            texto = f"[{item['gravidade']}] {item['tipo']} — {item['camadas']}: {item['area_ha']:.4f} ha"
            if item['gravidade'] == ERRO:
                feedback.reportError(texto, fatalError=False)
            else:
                feedback.pushWarning(texto)
        erros = sum(1 for i in itens if i['gravidade'] == ERRO)
        if not itens:
            feedback.pushInfo(self.tr('Nenhuma inconsistência entre as camadas.'))

        idSaida = gravarResultado(self, parameters, self.OUTPUT_INCONSISTENCIAS, context, feedback,
                                  camadaInconsistencias(itens, srcTrabalho), 'Inconsistencias')
        feedback.pushInfo(self.tr('GeoCAR - GeoOne'))
        resultados = {self.OUTPUT_N_ERROS: erros, self.OUTPUT_N_AVISOS: len(itens) - erros}
        if idSaida:
            resultados[self.OUTPUT_INCONSISTENCIAS] = idSaida
        return resultados

    def flags(self):
        # Grava nas camadas fixas do projeto: precisa rodar na thread principal
        return super().flags() | Qgis.ProcessingAlgorithmFlag.NoThreading

    def name(self):
        return 'consistenciacamadascar'

    def displayName(self):
        return self.tr('d. Consistência entre camadas')

    def group(self):
        return self.tr('3. ✅ Pré-análise do CAR')

    def groupId(self):
        return 'preanalise'

    def tr(self, string):
        return QCoreApplication.translate('Processing', string)

    def createInstance(self):
        return ConsistenciaCamadasCAR()

    def tags(self):
        return ('GeoOne,GeoCAR,GeoRural,ambiental,SiCAR,consistência,topologia,sobreposição,cobertura do solo,'
                'Reserva Legal,servidão,pré-análise').split(',')

    def icon(self):
        return QIcon(os.path.join(os.path.dirname(os.path.dirname(__file__)), 'images/qualidade.png'))

    def shortHelpString(self):
        txt = """Verifica a <b>consistência entre as camadas</b> declaradas no CAR, antes da importação no SICAR.

<b>Erros</b> (costumam impedir ou pendenciar a inscrição):
• feições fora da ATI
• sobreposição entre coberturas do solo (vegetação nativa, área consolidada, pousio...)
• sobreposição entre camadas de Reserva Legal
• servidão administrativa sobre Reserva Legal

<b>Avisos:</b>
• trecho de Reserva Legal sem vegetação nativa (a recompor)
• área da ATI sem cobertura do solo declarada

<b>Resultados:</b> vão para a camada <b>Inconsistencias</b> do grupo <b>Resultados da Pré-Análise</b>, no <b>Pre-Analise/PreAnalise.gpkg</b> do projeto (criado na primeira execução, se ainda não existir), apagando os anteriores. As entradas já vêm preenchidas com as camadas da RAIZ; confira as listas, pois os nomes variam entre os estados.

Os cálculos são feitos em <b>SIRGAS 2000 / UTM</b> do fuso do imóvel, escolhido automaticamente.
""" + avisoLegal()
        return txt + rodapeAjuda()
