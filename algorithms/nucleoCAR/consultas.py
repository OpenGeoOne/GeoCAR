# -*- coding: utf-8 -*-
"""
Consultas externas usadas pela pré-análise: CAR vizinhos (SICAR) e parcelas certificadas (SIGEF).

As ferramentas do grupo 3 chamam garantirVizinhosCAR / garantirParcelasSigef: se a camada ainda não foi
consultada no projeto, a consulta é feita pela extensão da ATI; se já foi (mesmo sem resultado), reaproveita.
"""

import json
import os
from datetime import date

from qgis.PyQt.QtCore import QDate, QDateTime, QMetaType
from qgis.core import (QgsCoordinateReferenceSystem, QgsCoordinateTransform, QgsFeature, QgsFeatureRequest, QgsField,
                       QgsGeometry, QgsProcessingContext, QgsProject, QgsVectorLayer)

from .processingCAR import camadaFixa, garantirCamadaFixa, substituirFeicoes

ARQUIVO_FONTES = os.path.join(os.path.dirname(__file__), 'fontes_restricoes.json')
NOME_VIZINHOS = 'CAR_Vizinhos_SICAR'
NOME_SIGEF = 'Parcelas_SIGEF'
NOME_RESTRICOES = 'Restricoes_Territoriais'
MARGEM_RESTRICOES_M = 2000.0
PROPRIEDADE_CONSULTA = 'geocar/consulta'   # data da última consulta, guardada na camada (salva no projeto)
MARGEM_VIZINHOS_M = 1000.0
MARGEM_SIGEF_M = 500.0


def _camadaDoResultado(contexto, saida):
    """Camada de saída de um algoritmo filho (o processing.run pode devolver o id ou a própria camada)."""
    if not saida:
        return None
    identificador = saida.id() if hasattr(saida, 'id') else saida
    camada = contexto.takeResultLayer(identificador)
    return camada if camada is not None else (saida if hasattr(saida, 'id') else None)


def marcarConsulta(camada):
    """Registra na camada a data da consulta (assim uma consulta sem resultado não é refeita a cada análise)."""
    if camada is not None:
        camada.setCustomProperty(PROPRIEDADE_CONSULTA, date.today().isoformat())


def jaConsultada(camada):
    return camada is not None and (camada.featureCount() > 0 or bool(camada.customProperty(PROPRIEDADE_CONSULTA)))


def extensaoDaAti(camadaAti, margem_m):
    """Extensão da ATI em SIRGAS 2000 (graus), com a margem convertida aproximadamente."""
    crsGeo = QgsCoordinateReferenceSystem('EPSG:4674')
    extensao = QgsCoordinateTransform(camadaAti.crs(), crsGeo, QgsProject.instance()).transformBoundingBox(
        camadaAti.extent())
    extensao.grow(margem_m / 111000.0)
    return extensao


def _texto(valor):
    if valor is None or (hasattr(valor, 'isNull') and valor.isNull()):
        return ''
    if isinstance(valor, (QDateTime, QDate)):
        return valor.toString('dd/MM/yyyy')
    texto = str(valor).strip()
    return '' if texto in ('NULL', 'None') else texto


CAMPOS_SIGEF = ('parcela', 'codigo_imovel', 'nome_area', 'matricula', 'situacao', 'aprovacao', 'fonte', 'consulta')


def parcelasSigef(extensao, feedback):
    """Parcelas certificadas (imóveis privados) do SIGEF na extensão, numa camada de memória; None se indisponível."""
    with open(ARQUIVO_FONTES, encoding='utf-8') as arquivo:
        definicao = json.load(arquivo).get('sigef')
    if not definicao:
        return None
    servico = QgsVectorLayer(f"crs='EPSG:4674' url='{definicao['url']}'", 'sigef', 'arcgisfeatureserver')
    if not servico.isValid():
        feedback.reportError('SIGEF: serviço indisponível no momento.', fatalError=False)
        return None
    memoria = QgsVectorLayer('MultiPolygon?crs=EPSG:4674', NOME_SIGEF, 'memory')
    memoria.dataProvider().addAttributes([QgsField(n, QMetaType.Type.QString) for n in CAMPOS_SIGEF])
    memoria.updateFields()
    crsGeo = QgsCoordinateReferenceSystem('EPSG:4674')
    paraServico = QgsCoordinateTransform(crsGeo, servico.crs(), QgsProject.instance())
    paraGeo = QgsCoordinateTransform(servico.crs(), crsGeo, QgsProject.instance())
    areaBusca = QgsGeometry.fromRect(extensao)
    nomes = servico.fields().names()
    valor = lambda f, n: _texto(f[n]) if n in nomes else ''
    hoje = date.today().strftime('%d/%m/%Y')
    pedido = QgsFeatureRequest().setFilterRect(paraServico.transformBoundingBox(extensao))
    pedido.setFeedback(feedback)
    novas = []
    for feicao in servico.getFeatures(pedido):
        geometria = QgsGeometry(feicao.geometry())
        if geometria.isNull():
            continue
        geometria.transform(paraGeo)
        if not geometria.intersects(areaBusca):
            continue
        geometria.convertToMultiType()
        nova = QgsFeature(memoria.fields())
        nova.setGeometry(geometria)
        nova.setAttributes([valor(feicao, 'parcela_co'), valor(feicao, 'codigo_imo'), valor(feicao, 'nome_area'),
                            valor(feicao, 'registro_m'),
                            ' — '.join(v for v in (valor(feicao, 'status'), valor(feicao, 'situacao_i')) if v),
                            valor(feicao, 'data_aprov'), definicao['fonte'], hoje])
        novas.append(nova)
    memoria.dataProvider().addFeatures(novas)
    feedback.pushInfo(f'SIGEF: {len(novas)} parcela(s) certificada(s)')
    return memoria


def garantirParcelasSigef(context, feedback, camadaAti):
    """
    Camada de parcelas certificadas do SIGEF para a análise. Ainda não consultada no projeto: consulta pela
    extensão da ATI e grava na camada fixa Parcelas_SIGEF (projeto salvo) ou devolve a camada de memória.
    """
    projeto = context.project() or QgsProject.instance()
    fixa = garantirCamadaFixa(NOME_SIGEF, projeto)
    if jaConsultada(fixa):
        return fixa
    feedback.pushInfo('Vizinhos com SIGEF ainda não consultados: consultando as parcelas certificadas pela ATI...')
    memoria = parcelasSigef(extensaoDaAti(camadaAti, MARGEM_SIGEF_M), feedback)
    if memoria is None:
        return fixa
    if fixa is None:
        return memoria
    substituirFeicoes(fixa, memoria)
    marcarConsulta(fixa)
    return fixa


def garantirVizinhosCAR(context, feedback, camadaAti):
    """
    Camada de CARs vizinhos para a análise. Ainda não consultada no projeto: faz a Consulta CAR pela extensão
    da ATI (grava na camada fixa CAR_Vizinhos_SICAR, ou devolve a camada temporária se o projeto não está salvo).
    """
    import processing   # importado aqui: o módulo é carregado pelo provider antes do Processing estar pronto

    projeto = context.project() or QgsProject.instance()
    fixa = camadaFixa(NOME_VIZINHOS, projeto)
    if jaConsultada(fixa):
        return fixa
    if fixa is None:
        existentes = [c for c in projeto.mapLayersByName(NOME_VIZINHOS) if c.featureCount() > 0]
        if existentes:
            return existentes[0]
    feedback.pushInfo('Vizinhos com CAR ainda não consultados: fazendo a Consulta CAR pela extensão da ATI...')
    extensao = extensaoDaAti(camadaAti, MARGEM_VIZINHOS_M)
    filho = QgsProcessingContext()
    filho.setProject(projeto)
    try:
        resultado = processing.run('GeoCAR:baixarcar', {
            'EXTENT': f'{extensao.xMinimum()},{extensao.xMaximum()},{extensao.yMinimum()},{extensao.yMaximum()} '
                      f'[EPSG:4674]',
            'WFS': 0, 'GEOONE': False, 'OUTPUT': 'TEMPORARY_OUTPUT'}, context=filho, feedback=feedback)
    except Exception as erro:   # serviço fora do ar: a análise segue sem os vizinhos
        feedback.reportError(f'Consulta CAR não concluída: {erro}', fatalError=False)
        return fixa
    fixa = camadaFixa(NOME_VIZINHOS, projeto)
    if fixa is not None:
        marcarConsulta(fixa)
        return fixa
    camada = _camadaDoResultado(filho, resultado.get('OUTPUT'))
    if camada is not None:
        camada.setName(NOME_VIZINHOS)
    return camada


def completarVizinhos(context, feedback, camadaAti, camadas):
    """
    Lista de restrições com os CARs vizinhos garantidos: consulta quando a camada CAR_Vizinhos_SICAR está na
    lista (ou nem existe no projeto) e ainda não foi consultada. Se o usuário tirou a camada da lista, respeita.
    """
    projeto = context.project() or QgsProject.instance()
    nomes = [c.name() for c in camadas]
    if NOME_VIZINHOS in nomes or not projeto.mapLayersByName(NOME_VIZINHOS):
        camada = garantirVizinhosCAR(context, feedback, camadaAti)
        if camada is not None:
            camadas = [c for c in camadas if c.name() != NOME_VIZINHOS] + [camada]
    return camadas


def completarSigef(context, feedback, camadaAti, camada):
    """Camada de parcelas do SIGEF para a 3c: consulta quando é a camada fixa ainda não consultada, ou não existe."""
    projeto = context.project() or QgsProject.instance()
    if camada is None and not projeto.mapLayersByName(NOME_SIGEF):
        return garantirParcelasSigef(context, feedback, camadaAti)
    if camada is not None and camada.name() == NOME_SIGEF and not jaConsultada(camada):
        return garantirParcelasSigef(context, feedback, camadaAti)
    return camada


def garantirRestricoes(context, feedback, camadaAti):
    """
    Restrições oficiais (UC, TI, assentamentos, embargos, terras públicas). Ainda não consultadas no projeto:
    faz a consulta de restrições (1d) pela ATI e grava na camada fixa Restricoes_Territoriais.
    """
    import processing

    projeto = context.project() or QgsProject.instance()
    fixa = garantirCamadaFixa(NOME_RESTRICOES, projeto)
    if jaConsultada(fixa):
        return fixa
    feedback.pushInfo('Restrições oficiais ainda não consultadas: fazendo a consulta de restrições pela ATI '
                      '(pode levar cerca de 1 minuto)...')
    filho = QgsProcessingContext()
    filho.setProject(projeto)
    try:
        resultado = processing.run('GeoCAR:consultarestricoescar', {
            'INPUT_ATI': camadaAti, 'MARGEM': MARGEM_RESTRICOES_M, 'OUTPUT': 'TEMPORARY_OUTPUT'},
            context=filho, feedback=feedback)
    except Exception as erro:
        feedback.reportError(f'Consulta de restrições não concluída: {erro}', fatalError=False)
        return fixa
    camada = _camadaDoResultado(filho, resultado.get('OUTPUT'))
    if camada is None:
        return fixa
    if fixa is None:
        camada.setName(NOME_RESTRICOES)
        return camada
    substituirFeicoes(fixa, camada)
    marcarConsulta(fixa)
    return fixa


def completarRestricoes(context, feedback, camadaAti, camadas):
    """Lista de restrições com as restrições oficiais garantidas (mesma regra dos CARs vizinhos)."""
    projeto = context.project() or QgsProject.instance()
    nomes = [c.name() for c in camadas]
    if NOME_RESTRICOES in nomes or not projeto.mapLayersByName(NOME_RESTRICOES):
        camada = garantirRestricoes(context, feedback, camadaAti)
        if camada is not None:
            camadas = [c for c in camadas if c.name() != NOME_RESTRICOES] + [camada]
    return camadas
