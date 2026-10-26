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
# Consulta, em serviços oficiais, as áreas protegidas e restrições em torno do imóvel
# consultaRestricoes.py

__author__ = 'Prof Cazaroli e Leandro França'
__date__ = '2026-10-23'
__copyright__ = '(C) 2026 by Prof Cazaroli e Leandro França'

import json
import os
import re
from datetime import date

from qgis.PyQt.QtCore import QCoreApplication, QDate, QDateTime
from qgis.PyQt.QtGui import QIcon
from qgis.core import (
    Qgis,
    QgsBlockingNetworkRequest,
    QgsCoordinateReferenceSystem,
    QgsCoordinateTransform,
    QgsFeature,
    QgsFeatureRequest,
    QgsFeatureSink,
    QgsFields,
    QgsField,
    QgsGeometry,
    QgsProcessingAlgorithm,
    QgsProcessingException,
    QgsProcessingParameterEnum,
    QgsProcessingParameterFeatureSink,
    QgsProcessingParameterNumber,
    QgsProcessingParameterVectorLayer,
    QgsProject,
    QgsVectorLayer,
    QgsWkbTypes,
)
from qgis.PyQt.QtCore import QMetaType, QUrl
from qgis.PyQt.QtNetwork import QNetworkRequest

from .nucleoCAR.processingCAR import PosProcessamentoCopiaFixa, avisoLegal, camadaPadrao, rodapeAjuda

NOME_RESTRICOES = 'Restricoes_Territoriais'
GRUPO_RESTRICOES = 'Areas_Vizinhas'
ARQUIVO_FONTES = os.path.join(os.path.dirname(__file__), 'nucleoCAR', 'fontes_restricoes.json')


def carregarFontes():
    """Fontes oficiais definidas em nucleoCAR/fontes_restricoes.json (endereços editáveis sem mexer no código)."""
    with open(ARQUIVO_FONTES, encoding='utf-8') as arquivo:
        return json.load(arquivo)['fontes']


def camposRestricoes():
    campos = QgsFields()
    for nome in ('tipo', 'nome', 'codigo', 'situacao', 'data', 'fonte', 'consulta'):
        campos.append(QgsField(nome, QMetaType.Type.QString))
    return campos


def _texto(valor):
    """Valor de atributo como texto (datas no padrão brasileiro)."""
    if valor is None or (hasattr(valor, 'isNull') and valor.isNull()):
        return ''
    if isinstance(valor, (QDateTime, QDate)):
        return valor.toString('dd/MM/yyyy')
    texto = str(valor).strip()
    return '' if texto in ('NULL', 'None') else texto


def _valor(feicao, nomesCampos, candidatos):
    """Primeiro campo candidato preenchido."""
    for nome in candidatos:
        if nome in nomesCampos:
            texto = _texto(feicao[nome])
            if texto:
                return texto
    return ''


def _camadaCnuc(url, prefixo, feedback):
    """Camada mais recente do CNUC no WFS do MMA (as versões são publicadas com nomes por data), ou None."""
    pedido = QgsBlockingNetworkRequest()
    semErro = getattr(getattr(QgsBlockingNetworkRequest, 'ErrorCode', QgsBlockingNetworkRequest), 'NoError')
    if pedido.get(QNetworkRequest(QUrl(url + '?service=WFS&request=GetCapabilities'))) != semErro:
        return None
    texto = bytes(pedido.reply().content()).decode('utf-8', 'ignore')
    nomes = sorted(set(re.findall(r'<Name>(' + re.escape(prefixo) + r'[^<]+)</Name>', texto)))

    def data(nome):
        # cnuc_2026_03, cnuc_04_2024, cnuc_26_07_31 -> (ano, mês); versões "_atualizado" por último
        numeros = [int(n) for n in re.findall(r'\d+', nome)]
        ano = next((n for n in numeros if n > 1999), None)
        if ano is None and numeros:
            ano = 2000 + numeros[0]
        mes = next((n for n in numeros if 1 <= n <= 12 and n != ano), 0)
        return ('_atualizado' not in nome, ano or 0, mes)

    for nome in sorted(nomes, key=data, reverse=True):
        camada = QgsVectorLayer(f"pagingEnabled='true' restrictToRequestBBOX='1' srsname='EPSG:4674' "
                                f"typename='{nome}' url='{url}' version='auto'", nome, 'WFS')
        if camada.isValid() and 'nome_uc' in camada.fields().names():
            feedback.pushInfo(f'CNUC: camada {nome}')
            return camada
    return None


def _abrirServico(definicao, feedback):
    """Abre o serviço (wfs_cnuc, wfs ou arcgis) e devolve a camada, ou None se estiver indisponível."""
    servico = definicao['servico']
    if servico == 'wfs_cnuc':
        return _camadaCnuc(definicao['url'], definicao.get('prefixo', 'MMA:cnuc_'), feedback)
    if servico == 'wfs':
        camada = QgsVectorLayer(f"pagingEnabled='true' restrictToRequestBBOX='1' srsname='EPSG:4674' "
                                f"typename='{definicao['camada']}' url='{definicao['url']}' version='auto'",
                                definicao['camada'], 'WFS')
    else:
        camada = QgsVectorLayer(f"crs='EPSG:4674' url='{definicao['url']}'", 'restricao', 'arcgisfeatureserver')
    return camada if camada.isValid() else None


def abrirFonte(fonte, feedback):
    """Lista de (camada, definição) da fonte: o serviço principal ou, se falhar, as alternativas."""
    camada = _abrirServico(fonte, feedback)
    if camada is not None:
        return [(camada, fonte)]
    abertas = []
    for alternativa in fonte.get('alternativas', []):
        camada = _abrirServico(alternativa, feedback)
        if camada is not None:
            abertas.append((camada, alternativa))
    if abertas:
        feedback.pushWarning(f"{fonte['tipo']}: serviço principal indisponível, usando a base alternativa.")
    return abertas


class ConsultaRestricoesCAR(QgsProcessingAlgorithm):
    """Consulta áreas protegidas e restrições oficiais em torno do imóvel."""

    INPUT_ATI = 'INPUT_ATI'
    MARGEM = 'MARGEM'
    FONTES = 'FONTES'
    OUTPUT = 'OUTPUT'

    def initAlgorithm(self, config=None):
        self.addParameter(QgsProcessingParameterVectorLayer(
            self.INPUT_ATI, self.tr('Área Total do Imóvel (ATI)'), [Qgis.ProcessingSourceType.VectorPolygon],
            defaultValue=camadaPadrao('ati') or 'ATI'))
        self.addParameter(QgsProcessingParameterNumber(
            self.MARGEM, self.tr('Margem em torno da ATI (m)'), type=Qgis.ProcessingNumberParameterType.Double,
            minValue=0.0, maxValue=50000.0, defaultValue=2000.0))
        self.addParameter(QgsProcessingParameterEnum(
            self.FONTES, self.tr('Restrições a consultar'), options=[f['tipo'] for f in carregarFontes()],
            allowMultiple=True, defaultValue=list(range(len(carregarFontes())))))
        self.addParameter(QgsProcessingParameterFeatureSink(
            self.OUTPUT, self.tr('Restrições encontradas')))

    def processAlgorithm(self, parameters, context, feedback):
        camadaAti = self.parameterAsVectorLayer(parameters, self.INPUT_ATI, context)
        if camadaAti is None or camadaAti.featureCount() == 0:
            raise QgsProcessingException(self.tr('A camada ATI está vazia ou não foi informada.'))
        margem = self.parameterAsDouble(parameters, self.MARGEM, context)
        fontes = carregarFontes()
        escolhidas = [fontes[i] for i in self.parameterAsEnums(parameters, self.FONTES, context)]
        hoje = date.today().strftime('%d/%m/%Y')

        # Retângulo de busca em SIRGAS 2000 (graus), com a margem convertida aproximadamente
        crsGeo = QgsCoordinateReferenceSystem('EPSG:4674')
        transformacao = QgsCoordinateTransform(camadaAti.crs(), crsGeo, QgsProject.instance())
        extensao = transformacao.transformBoundingBox(camadaAti.extent())
        extensao.grow(margem / 111000.0)
        areaBusca = QgsGeometry.fromRect(extensao)

        campos = camposRestricoes()
        (sink, destId) = self.parameterAsSink(parameters, self.OUTPUT, context, campos,
                                              QgsWkbTypes.MultiPolygon, crsGeo)
        if sink is None:
            raise QgsProcessingException(self.invalidSinkError(parameters, self.OUTPUT))

        total = 0
        for passo, fonte in enumerate(escolhidas):
            if feedback.isCanceled():
                break
            feedback.setProgress(100.0 * passo / max(len(escolhidas), 1))
            feedback.pushInfo(self.tr(f"Consultando: {fonte['tipo']}..."))
            abertas = abrirFonte(fonte, feedback)
            if not abertas:
                feedback.reportError(self.tr(f"{fonte['tipo']}: serviço indisponível no momento — "
                                             "consulta seguiu com as demais fontes."), fatalError=False)
                continue
            encontradas = 0
            for camada, info in abertas:
                nomesCampos = camada.fields().names()
                campos_ = info['campos']
                paraCamada = QgsCoordinateTransform(crsGeo, camada.crs(), QgsProject.instance())
                paraGeo = QgsCoordinateTransform(camada.crs(), crsGeo, QgsProject.instance())
                pedido = QgsFeatureRequest().setFilterRect(paraCamada.transformBoundingBox(extensao))
                pedido.setFeedback(feedback)
                for feicao in camada.getFeatures(pedido):
                    if feedback.isCanceled():
                        break
                    geometria = QgsGeometry(feicao.geometry())
                    if geometria.isNull() or QgsWkbTypes.geometryType(geometria.wkbType()) != QgsWkbTypes.PolygonGeometry:
                        continue
                    geometria.transform(paraGeo)
                    if not geometria.intersects(areaBusca):
                        continue
                    geometria.convertToMultiType()
                    nova = QgsFeature(campos)
                    nova.setGeometry(geometria)
                    situacao = ' — '.join(v for v in (_valor(feicao, nomesCampos, [c]) for c in campos_['situacao']) if v)
                    nova.setAttributes([fonte['tipo'], _valor(feicao, nomesCampos, campos_['nome']),
                                        _valor(feicao, nomesCampos, campos_['codigo']), situacao,
                                        _valor(feicao, nomesCampos, campos_['data']), info['fonte'], hoje])
                    sink.addFeature(nova, QgsFeatureSink.FastInsert)
                    encontradas += 1
            feedback.pushInfo(self.tr(f"{fonte['tipo']}: {encontradas} área(s)"))
            total += encontradas

        feedback.pushInfo(self.tr(f'Total: {total} área(s) de restrição na ATI e na margem de {margem:g} m.'))

        feedback.pushInfo(self.tr('GeoCAR - GeoOne'))

        # No fim, a camada vai para a camada fixa Restricoes_Territoriais (PreAnalise.gpkg), apagando a anterior
        if context.willLoadLayerOnCompletion(destId):
            global posRestricoes
            posRestricoes = PosProcessamentoCopiaFixa(NOME_RESTRICOES, GRUPO_RESTRICOES)
            context.layerToLoadOnCompletionDetails(destId).setPostProcessor(posRestricoes)
        return {self.OUTPUT: destId}

    def name(self):
        return 'consultarestricoescar'

    def displayName(self):
        return self.tr('d. Consulta de restrições (UC, TI, assentamentos, embargos)')

    def group(self):
        return self.tr('1. 🔍 Consultas')

    def groupId(self):
        return 'consultas'

    def tr(self, string):
        return QCoreApplication.translate('Processing', string)

    def createInstance(self):
        return ConsultaRestricoesCAR()

    def tags(self):
        return ('GeoOne,GeoCAR,GeoRural,ambiental,SiCAR,restrição,unidade de conservação,UC,CNUC,terra indígena,'
                'FUNAI,assentamento,INCRA,embargo,IBAMA,ICMBio,floresta pública,SFB,sobreposição').split(',')

    def icon(self):
        return QIcon(os.path.join(os.path.dirname(os.path.dirname(__file__)), 'images/geocar.png'))

    def shortHelpString(self):
        txt = """Consulta, em <b>serviços oficiais</b>, as áreas protegidas e restrições que tocam a ATI ou estão na margem informada:
• <b>Unidades de Conservação</b> federais, estaduais e municipais — CNUC/MMA
• <b>Terras Indígenas</b> — FUNAI (base publicada pelo IBAMA)
• <b>Assentamentos</b> — INCRA
• <b>Embargos</b> do IBAMA e do ICMBio
• <b>Florestas Públicas</b>, <b>terras públicas não destinadas</b> e <b>áreas militares</b> — Serviço Florestal Brasileiro
• <b>Glebas públicas federais</b> — SIGEF público (INCRA)


O resultado vai para a camada <b>Restricoes_Territoriais</b> (grupo <b>Areas_Vizinhas</b>, no <b>Pre-Analise/PreAnalise.gpkg</b>), apagando a consulta anterior, e entra automaticamente como camada de restrição nas ferramentas <b>3a</b> e <b>3c</b>.

<b>Atenção:</b> sobreposição com APA (Área de Proteção Ambiental) não impede o CAR — a APA admite propriedade privada. Já UC de proteção integral, Terra Indígena, assentamento, embargo e floresta pública exigem análise. Os nomes e CPF/CNPJ dos embargados não são copiados.

Os serviços são de terceiros e podem ficar fora do ar ou mudar de endereço: a ferramenta avisa, segue com as demais fontes e, quando há, usa uma base alternativa. Os endereços ficam no arquivo <b>nucleoCAR/fontes_restricoes.json</b> do plugin. Cada área traz a fonte e a data da consulta. Se um serviço falhar, a camada baixada manualmente pode ser usada como restrição nas ferramentas 3a e 3c.
""" + avisoLegal()
        return txt + rodapeAjuda()
