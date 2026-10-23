# -*- coding: utf-8 -*-
# Funções de apoio comuns aos algoritmos 8, 9 e 10 (pré-análise do CAR) do GeoCAR
# processingCAR.py

import os

from qgis.PyQt.QtCore import QTimer
from qgis.core import (QgsFeature, QgsFeatureSink, QgsLayerTreeGroup, QgsProcessingException,
                       QgsProcessingLayerPostProcessorInterface, QgsProject, QgsProviderRegistry)

from .utils import adicionar_feicao, area_ha, criar_camada_memoria

PASTA_IMAGENS = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), 'images')

OPCOES_RL = [
    '20% — Demais regiões / campos gerais na Amazônia Legal',
    '35% — Cerrado na Amazônia Legal',
    '80% — Floresta na Amazônia Legal',
]
VALORES_RL = [20.0, 35.0, 80.0]

# Resultados da pré-análise na estrutura RAIZ
PASTA_RESULTADOS = 'Pre-Analise'
GRUPO_RESULTADOS = 'Resultados da Pré-Análise'

# Referências aos pós-processadores (o Processing não guarda a referência Python)
_posProcessadores = {}


def destinoPadrao(nomeArquivo, pasta=PASTA_RESULTADOS):
    """Caminho padrão de saída na pasta do projeto, ou None se o projeto ainda não foi salvo."""
    pastaProjeto = QgsProject.instance().homePath()
    return os.path.join(pastaProjeto, pasta, nomeArquivo) if pastaProjeto else None


def _arquivo(fonte, provedor='ogr'):
    """Caminho absoluto normalizado do arquivo de uma fonte OGR, ou None."""
    caminho = QgsProviderRegistry.instance().decodeUri(provedor, fonte).get('path')
    return os.path.normcase(os.path.abspath(caminho)) if caminho else None


def prepararDestino(destino, projeto=None):
    """
    Antes de gravar em arquivo: cria a pasta e tira do projeto as camadas que leem esse arquivo
    (resultado anterior), para que possa ser sobrescrito também no Windows.
    """
    if not destino or destino.startswith(('memory:', 'postgres:', 'TEMPORARY_OUTPUT')):
        return
    caminho = _arquivo(destino[4:] if destino.startswith('ogr:') else destino)
    if not caminho or not os.path.splitext(caminho)[1]:
        return
    os.makedirs(os.path.dirname(caminho), exist_ok=True)
    projeto = projeto or QgsProject.instance()
    for camada in list(projeto.mapLayers().values()):
        if camada.providerType() == 'ogr' and _arquivo(camada.source()) == caminho:
            projeto.removeMapLayer(camada.id())


class PosProcessamentoGrupo(QgsProcessingLayerPostProcessorInterface):
    """Renomeia a camada de resultado e a coloca no grupo indicado."""

    def __init__(self, nomeCamada, nomeGrupo):
        super().__init__()
        self.nomeCamada = nomeCamada
        self.nomeGrupo = nomeGrupo

    def postProcessLayer(self, layer, context, feedback):
        if self.nomeCamada:
            layer.setName(self.nomeCamada)
        projeto = context.project() or QgsProject.instance()
        idCamada = layer.id()
        # Depois que o Processing termina de inserir a camada na árvore
        QTimer.singleShot(0, lambda: moverParaGrupo(projeto, idCamada, self.nomeGrupo))


def definirPosProcessamento(context, destId, nomeCamada, nomeGrupo):
    """Associa o pós-processamento (nome e grupo) à camada que será carregada no fim do algoritmo."""
    if context.willLoadLayerOnCompletion(destId):
        pos = PosProcessamentoGrupo(nomeCamada, nomeGrupo)
        _posProcessadores[destId] = pos
        context.layerToLoadOnCompletionDetails(destId).setPostProcessor(pos)


def moverParaGrupo(projeto, idCamada, nomeGrupo):
    """
    Move a camada para o grupo (criado abaixo do último grupo da raiz, se não existir) e
    remove do grupo a camada temporária anterior com o mesmo nome (consulta ou análise refeita).
    """
    camada = projeto.mapLayer(idCamada)
    if camada is None:
        return
    raiz = projeto.layerTreeRoot()
    grupo = next((g for g in raiz.findGroups(True) if g.name().lower() == nomeGrupo.lower()), None)
    if grupo is None:
        indices = [i for i, filho in enumerate(raiz.children()) if isinstance(filho, QgsLayerTreeGroup)]
        grupo = raiz.insertGroup(indices[-1] + 1 if indices else 0, nomeGrupo)

    # Resultado temporário anterior com o mesmo nome (os gravados em arquivo já saem em prepararDestino)
    for no in list(grupo.findLayers()):
        anterior = no.layer()
        if (no.layerId() != idCamada and anterior is not None and anterior.name() == camada.name()
                and anterior.providerType() == 'memory'):
            projeto.removeMapLayer(no.layerId())

    no = raiz.findLayer(idCamada)
    if no is None:
        grupo.addLayer(camada)
    elif no.parent() is not grupo:
        grupo.addChildNode(no.clone())
        no.parent().removeChildNode(no)


def rodapeAjuda():
    """Rodapé padrão do GeoCAR para o shortHelpString."""
    return '''<div>
                      <div align="center">
                      <a target="_blank" rel="noopener noreferrer" href="https://geoone.com.br/pvcar/"><img title="Inscreva-se no curso de CAR" style="width: 100%; height: auto;" src="''' + os.path.join(PASTA_IMAGENS, 'CAR_GeoOne.jpg') + '''"></a>
                      </div>
                      <div align="right">
                      <p align="right">
                      <a href="https://geoone.com.br/pvcar/"><span style="font-weight: bold;">Conheça o curso de Cadastro Ambiental Rural (CAR)</span></a>
                      </p>
                      <a target="_blank" rel="noopener noreferrer" href="https://geoone.com.br/"><img title="GeoOne" width="280"  src="''' + os.path.join(PASTA_IMAGENS, 'GeoOne.png') + '''"></a>
                      <p><i>"Mapeamento automatizado, fácil e direto ao ponto é na GeoOne!"</i></p>
                      </div>
                    </div>'''


def avisoLegal():
    """Texto curto de responsabilidade técnica exibido na ajuda."""
    return ('<p><b>Atenção:</b> pré-análise técnica de caráter indicativo. Não substitui a análise '
            'do órgão ambiental nem a verificação da legislação estadual, que pode ser mais restritiva.</p>')


def gravarCamadaNoSink(algoritmo, parameters, chave, context, camadaMemoria, nomeCamada=None,
                       nomeGrupo=GRUPO_RESULTADOS):
    """
    Copia as feições de uma camada de memória para o sink de saída do algoritmo.
    Com nomeCamada, a camada carregada recebe esse nome e vai para o grupo nomeGrupo.
    """
    prepararDestino(algoritmo.parameterAsOutputLayer(parameters, chave, context), context.project())
    (sink, destId) = algoritmo.parameterAsSink(
        parameters, chave, context,
        camadaMemoria.fields(), camadaMemoria.wkbType(), camadaMemoria.crs()
    )
    if sink is None:
        raise QgsProcessingException(algoritmo.invalidSinkError(parameters, chave))
    for feicao in camadaMemoria.getFeatures():
        sink.addFeature(QgsFeature(feicao), QgsFeatureSink.FastInsert)
    if nomeCamada:
        definirPosProcessamento(context, destId, nomeCamada, nomeGrupo)
    return destId


def camadaPoligonoArea(nome, src, geometria):
    """Cria camada de memória (MultiPolygon) com uma feição e o campo area_ha."""
    camada = criar_camada_memoria(nome, 'MultiPolygon', src, [('area_ha', 'double')])
    if geometria is not None and not geometria.isEmpty():
        adicionar_feicao(camada, geometria, [round(area_ha(geometria), 4)])
    return camada
