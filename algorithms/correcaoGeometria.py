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
# Ferramentas de correção (grupo 4): geometria da ATI, recorte pela ATI e lascas sem cobertura
# correcaoGeometria.py

__author__ = 'Prof Cazaroli e Leandro França'
__date__ = '2026-10-26'
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
    QgsProcessingParameterMultipleLayers,
    QgsProcessingParameterNumber,
    QgsProcessingParameterVectorLayer,
    QgsVectorLayer,
)

from .nucleoCAR.correcoes import (AREA_MINIMA_M2, Conversor, ajustarTipo, contarVertices, editar, finalizar,
                                  srcDaAti, toleranciaNaCamada, uniaoAti)
from .nucleoCAR.processingCAR import avisoLegal, camadaPadrao, camadasPadrao, rodapeAjuda

GRUPO = '4. 🔧 Correções'
GRUPO_ID = 'correcoes'
AVISO_EDICAO = ('<b>Segurança:</b> as correções ficam no <b>modo de edição</b> das camadas, sem salvar. Confira no mapa '
                'e salve ou descarte as edições (Ctrl+Z desfaz). Marque <b>Salvar as alterações</b> para gravar direto. '
                'Depois, rode a pré-análise de novo para confirmar que a pendência sumiu.')


class _BaseCorrecao(QgsProcessingAlgorithm):
    """Partes comuns às ferramentas de correção."""

    SALVAR = 'SALVAR'

    def parametroSalvar(self):
        self.addParameter(QgsProcessingParameterBoolean(
            self.SALVAR, self.tr('Salvar as alterações (desmarcado: ficam em edição para conferir)'),
            defaultValue=False))

    def flags(self):
        # Edita camadas do projeto: precisa da thread principal
        return super().flags() | Qgis.ProcessingAlgorithmFlag.NoThreading

    def group(self):
        return self.tr(GRUPO)

    def groupId(self):
        return GRUPO_ID

    def tr(self, string):
        return QCoreApplication.translate('Processing', string)

    def icon(self):
        return QIcon(os.path.join(os.path.dirname(os.path.dirname(__file__)), 'images/vetor.png'))


class CorrigirGeometriaAtiCAR(_BaseCorrecao):
    """Remove vértices duplicados e corrige geometrias inválidas da ATI."""

    INPUT_ATI = 'INPUT_ATI'
    TOLERANCIA = 'TOLERANCIA'
    OUTPUT_N = 'OUTPUT_N'

    def initAlgorithm(self, config=None):
        self.addParameter(QgsProcessingParameterVectorLayer(
            self.INPUT_ATI, self.tr('Área Total do Imóvel (ATI)'), [Qgis.ProcessingSourceType.VectorPolygon],
            defaultValue=camadaPadrao('ati') or 'ATI'))
        self.addParameter(QgsProcessingParameterNumber(
            self.TOLERANCIA, self.tr('Tolerância para vértices duplicados (m)'),
            type=Qgis.ProcessingNumberParameterType.Double, minValue=0.0, maxValue=1.0, defaultValue=0.001))
        self.parametroSalvar()
        self.addOutput(QgsProcessingOutputNumber(self.OUTPUT_N, self.tr('Feições corrigidas')))

    def processAlgorithm(self, parameters, context, feedback):
        camada = self.parameterAsVectorLayer(parameters, self.INPUT_ATI, context)
        if camada is None or camada.featureCount() == 0:
            raise QgsProcessingException(self.tr('A camada ATI está vazia ou não foi informada.'))
        tolerancia = toleranciaNaCamada(camada, self.parameterAsDouble(parameters, self.TOLERANCIA, context))
        ligou = editar(camada)
        corrigidas = 0
        for feicao in camada.getFeatures():
            if not feicao.hasGeometry():
                continue
            geometria = QgsGeometry(feicao.geometry())
            antes = contarVertices(geometria)
            geometria.removeDuplicateNodes(tolerancia)
            removidos = antes - contarVertices(geometria)
            invalida = not geometria.isGeosValid()
            if invalida:
                motivos = '; '.join(e.what() for e in geometria.validateGeometry())
                geometria = geometria.makeValid()
            if not removidos and not invalida:
                continue
            geometria = ajustarTipo(geometria, camada)
            if geometria.isEmpty() or not camada.changeGeometry(feicao.id(), geometria):
                feedback.reportError(self.tr(f'Feição {feicao.id()}: não foi possível corrigir.'), fatalError=False)
                continue
            corrigidas += 1
            if removidos:
                feedback.pushInfo(self.tr(f'Feição {feicao.id()}: {removidos} vértice(s) duplicado(s) removido(s).'))
            if invalida:
                feedback.pushInfo(self.tr(f'Feição {feicao.id()}: geometria inválida corrigida ({motivos}).'))
        salvar = self.parameterAsBool(parameters, self.SALVAR, context)
        finalizar(camada, ligou, corrigidas > 0, salvar)
        if corrigidas and not salvar:
            feedback.pushWarning(self.tr(f'{camada.name()} está em edição: confira e salve (ou descarte) as alterações.'))
        if not corrigidas:
            feedback.pushInfo(self.tr('Nenhuma correção necessária.'))
        return {self.OUTPUT_N: corrigidas}

    def name(self):
        return 'corrigirgeometriaaticar'

    def displayName(self):
        return self.tr('a. Corrigir geometria da ATI')

    def createInstance(self):
        return CorrigirGeometriaAtiCAR()

    def shortHelpString(self):
        txt = f"""Corrige os problemas geométricos da ATI apontados em <b>Problemas_Validacao</b>:
• remove <b>vértices duplicados</b> em sequência (dentro da tolerância, padrão de 1 mm), mantendo um deles
• corrige <b>geometrias inválidas</b> (autointerseção, anel cruzado), mantendo só as partes poligonais

Não muda o desenho da ATI além do necessário: um vértice duplicado sai sem mover os demais.

{AVISO_EDICAO}
""" + avisoLegal()
        return txt + rodapeAjuda()


class RecortarPelaAtiCAR(_BaseCorrecao):
    """Recorta as camadas declaradas no limite da ATI."""

    INPUT_ATI = 'INPUT_ATI'
    INPUT_CAMADAS = 'INPUT_CAMADAS'
    OUTPUT_HA = 'OUTPUT_HA'

    def initAlgorithm(self, config=None):
        poligono = Qgis.ProcessingSourceType.VectorPolygon
        self.addParameter(QgsProcessingParameterVectorLayer(
            self.INPUT_ATI, self.tr('Área Total do Imóvel (ATI)'), [poligono], defaultValue=camadaPadrao('ati') or 'ATI'))
        padrao = []
        for chave in ('vegetacao', 'coberturas', 'reservas', 'servidoes'):
            padrao += [n for n in camadasPadrao(chave) if n not in padrao]
        self.addParameter(QgsProcessingParameterMultipleLayers(
            self.INPUT_CAMADAS, self.tr('Camadas a recortar (vegetação, consolidada, pousio, Reserva Legal, servidão...)'),
            layerType=poligono, defaultValue=padrao or None))
        self.parametroSalvar()
        self.addOutput(QgsProcessingOutputNumber(self.OUTPUT_HA, self.tr('Área removida fora da ATI (ha)')))

    def processAlgorithm(self, parameters, context, feedback):
        camadaAti = self.parameterAsVectorLayer(parameters, self.INPUT_ATI, context)
        if camadaAti is None or camadaAti.featureCount() == 0:
            raise QgsProcessingException(self.tr('A camada ATI está vazia ou não foi informada.'))
        camadas = [c for c in self.parameterAsLayerList(parameters, self.INPUT_CAMADAS, context)
                   if isinstance(c, QgsVectorLayer) and c.id() != camadaAti.id()]
        src = srcDaAti(camadaAti)
        ati = uniaoAti(camadaAti, src)
        salvar = self.parameterAsBool(parameters, self.SALVAR, context)
        totalHa = 0.0
        for camada in camadas:
            conversor = Conversor(camada, src)
            ligou = editar(camada)
            alterou = False
            for feicao in camada.getFeatures():
                if not feicao.hasGeometry():
                    continue
                geometria = conversor.paraUtm(feicao.geometry()).makeValid()
                fora = geometria.difference(ati)
                if fora.isEmpty() or fora.area() < AREA_MINIMA_M2:
                    continue
                dentro = geometria.intersection(ati)
                totalHa += fora.area() / 10000.0
                if dentro.isEmpty() or dentro.area() < AREA_MINIMA_M2:
                    camada.deleteFeature(feicao.id())
                    feedback.pushInfo(self.tr(f'{camada.name()}, feição {feicao.id()}: inteira fora da ATI '
                                              f'({fora.area() / 10000.0:.4f} ha) — excluída.'))
                else:
                    camada.changeGeometry(feicao.id(), ajustarTipo(conversor.paraCamada(dentro), camada))
                    feedback.pushInfo(self.tr(f'{camada.name()}, feição {feicao.id()}: {fora.area() / 10000.0:.4f} ha '
                                              f'fora da ATI recortados.'))
                alterou = True
            finalizar(camada, ligou, alterou, salvar)
            if alterou and not salvar:
                feedback.pushWarning(self.tr(f'{camada.name()} está em edição: confira e salve (ou descarte).'))
        if totalHa == 0:
            feedback.pushInfo(self.tr('Nenhuma feição passa da ATI.'))
        return {self.OUTPUT_HA: round(totalHa, 4)}

    def name(self):
        return 'recortarpelaaticar'

    def displayName(self):
        return self.tr('b. Recortar camadas pela ATI')

    def createInstance(self):
        return RecortarPelaAtiCAR()

    def shortHelpString(self):
        txt = f"""Recorta no limite da ATI as camadas declaradas (vegetação nativa, área consolidada, pousio, Reserva Legal, servidão...), corrigindo a inconsistência <b>Fora da ATI</b>.

A parte de fora é removida; a feição que estiver inteira fora da ATI é excluída. A lista de camadas já vem preenchida com as camadas da RAIZ — confira, pois os nomes variam entre os estados.

{AVISO_EDICAO}
""" + avisoLegal()
        return txt + rodapeAjuda()


class PreencherLascasCAR(_BaseCorrecao):
    """Junta as lascas da ATI sem cobertura declarada à cobertura vizinha."""

    INPUT_ATI = 'INPUT_ATI'
    INPUT_COBERTURAS = 'INPUT_COBERTURAS'
    INPUT_SERVIDOES = 'INPUT_SERVIDOES'
    AREA_MAXIMA = 'AREA_MAXIMA'
    OUTPUT_HA = 'OUTPUT_HA'

    def initAlgorithm(self, config=None):
        poligono = Qgis.ProcessingSourceType.VectorPolygon
        self.addParameter(QgsProcessingParameterVectorLayer(
            self.INPUT_ATI, self.tr('Área Total do Imóvel (ATI)'), [poligono], defaultValue=camadaPadrao('ati') or 'ATI'))
        padrao = []
        for chave in ('vegetacao', 'coberturas'):
            padrao += [n for n in camadasPadrao(chave) if n not in padrao]
        self.addParameter(QgsProcessingParameterMultipleLayers(
            self.INPUT_COBERTURAS, self.tr('Camadas de cobertura do solo (recebem as lascas)'),
            layerType=poligono, defaultValue=padrao or None))
        self.addParameter(QgsProcessingParameterMultipleLayers(
            self.INPUT_SERVIDOES, self.tr('Servidão administrativa (área ocupada, não recebe lascas)'),
            layerType=poligono, optional=True, defaultValue=camadasPadrao('servidoes') or None))
        self.addParameter(QgsProcessingParameterNumber(
            self.AREA_MAXIMA, self.tr('Área máxima de cada lasca a preencher (m²)'),
            type=Qgis.ProcessingNumberParameterType.Double, minValue=1.0, defaultValue=500.0))
        self.parametroSalvar()
        self.addOutput(QgsProcessingOutputNumber(self.OUTPUT_HA, self.tr('Área preenchida (ha)')))

    def processAlgorithm(self, parameters, context, feedback):
        camadaAti = self.parameterAsVectorLayer(parameters, self.INPUT_ATI, context)
        if camadaAti is None or camadaAti.featureCount() == 0:
            raise QgsProcessingException(self.tr('A camada ATI está vazia ou não foi informada.'))
        coberturas = [c for c in self.parameterAsLayerList(parameters, self.INPUT_COBERTURAS, context)
                      if isinstance(c, QgsVectorLayer) and c.id() != camadaAti.id()]
        servidoes = [c for c in self.parameterAsLayerList(parameters, self.INPUT_SERVIDOES, context)
                     if isinstance(c, QgsVectorLayer)]
        if not coberturas:
            raise QgsProcessingException(self.tr('Informe ao menos uma camada de cobertura do solo.'))
        areaMaxima = self.parameterAsDouble(parameters, self.AREA_MAXIMA, context)
        src = srcDaAti(camadaAti)
        ati = uniaoAti(camadaAti, src)

        # Feições de cobertura no UTM: (camada, id, geometria)
        feicoes, ocupado = [], []
        for camada in coberturas:
            conversor = Conversor(camada, src)
            for f in camada.getFeatures():
                if f.hasGeometry():
                    g = conversor.paraUtm(f.geometry()).makeValid()
                    feicoes.append([camada, f.id(), g])
                    ocupado.append(g)
        for camada in servidoes:
            conversor = Conversor(camada, src)
            ocupado += [conversor.paraUtm(f.geometry()).makeValid() for f in camada.getFeatures() if f.hasGeometry()]
        semCobertura = ati.difference(QgsGeometry.unaryUnion(ocupado)) if ocupado else QgsGeometry(ati)
        lascas = [p for p in semCobertura.asGeometryCollection()
                  if not p.isEmpty() and p.area() >= AREA_MINIMA_M2] if not semCobertura.isEmpty() else []

        preenchidaHa, grandes, alteradas = 0.0, [], {}
        for lasca in lascas:
            if lasca.area() > areaMaxima:
                grandes.append(lasca.area())
                continue
            # Vizinha com a maior divisa em comum
            borda = lasca.buffer(0.05, 4)
            melhor, maior = None, 0.0
            for item in feicoes:
                comum = item[2].intersection(borda)
                comprimento = comum.area() if not comum.isEmpty() else 0.0
                if comprimento > maior:
                    melhor, maior = item, comprimento
            if melhor is None:
                grandes.append(lasca.area())
                continue
            melhor[2] = melhor[2].combine(lasca).makeValid()
            alteradas[(melhor[0].id(), melhor[1])] = melhor
            preenchidaHa += lasca.area() / 10000.0
            feedback.pushInfo(self.tr(f'Lasca de {lasca.area():.1f} m² juntada a {melhor[0].name()} (feição {melhor[1]}).'))

        salvar = self.parameterAsBool(parameters, self.SALVAR, context)
        porCamada = {}
        for camada, fid, geometria in alteradas.values():
            porCamada.setdefault(camada.id(), [camada, []])[1].append((fid, geometria))
        for camada, lista in porCamada.values():
            conversor = Conversor(camada, src)
            ligou = editar(camada)
            for fid, geometria in lista:
                camada.changeGeometry(fid, ajustarTipo(conversor.paraCamada(geometria), camada))
            finalizar(camada, ligou, True, salvar)
            if not salvar:
                feedback.pushWarning(self.tr(f'{camada.name()} está em edição: confira e salve (ou descarte).'))
        if grandes:
            feedback.pushWarning(self.tr(
                f'{len(grandes)} área(s) sem cobertura maiores que {areaMaxima:g} m² ({sum(grandes) / 10000.0:.4f} ha) '
                f'não foram preenchidas: classifique-as manualmente.'))
        if not lascas:
            feedback.pushInfo(self.tr('Nenhuma área sem cobertura dentro da ATI.'))
        return {self.OUTPUT_HA: round(preenchidaHa, 4)}

    def name(self):
        return 'preencherlascascar'

    def displayName(self):
        return self.tr('c. Preencher lascas sem cobertura')

    def createInstance(self):
        return PreencherLascasCAR()

    def shortHelpString(self):
        txt = f"""Junta à cobertura vizinha as <b>lascas</b> da ATI sem nenhuma cobertura do solo declarada — o aviso <b>Área sem cobertura do solo declarada</b> da pré-análise.

Cada lasca até a área máxima (padrão de 500 m²) vai para a feição de cobertura com a maior divisa em comum com ela. Áreas maiores não são preenchidas: são uso de verdade e precisam ser classificadas manualmente. A servidão administrativa conta como área ocupada.

{AVISO_EDICAO}
""" + avisoLegal()
        return txt + rodapeAjuda()
