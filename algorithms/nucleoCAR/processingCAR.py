# -*- coding: utf-8 -*-
# Funções de apoio comuns aos algoritmos 8, 9 e 10 (pré-análise do CAR) do GeoCAR
# processingCAR.py

import os

from qgis.core import QgsFeature, QgsFeatureSink, QgsProcessingException

from .utils import adicionar_feicao, area_ha, criar_camada_memoria

PASTA_IMAGENS = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), 'images')

OPCOES_RL = [
    '20% — Demais regiões / campos gerais na Amazônia Legal',
    '35% — Cerrado na Amazônia Legal',
    '80% — Floresta na Amazônia Legal',
]
VALORES_RL = [20.0, 35.0, 80.0]


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


def gravarCamadaNoSink(algoritmo, parameters, chave, context, camadaMemoria):
    """Copia as feições de uma camada de memória para o sink de saída do algoritmo."""
    (sink, destId) = algoritmo.parameterAsSink(
        parameters, chave, context,
        camadaMemoria.fields(), camadaMemoria.wkbType(), camadaMemoria.crs()
    )
    if sink is None:
        raise QgsProcessingException(algoritmo.invalidSinkError(parameters, chave))
    for feicao in camadaMemoria.getFeatures():
        sink.addFeature(QgsFeature(feicao), QgsFeatureSink.FastInsert)
    return destId


def camadaPoligonoArea(nome, src, geometria):
    """Cria camada de memória (MultiPolygon) com uma feição e o campo area_ha."""
    camada = criar_camada_memoria(nome, 'MultiPolygon', src, [('area_ha', 'double')])
    if geometria is not None and not geometria.isEmpty():
        adicionar_feicao(camada, geometria, [round(area_ha(geometria), 4)])
    return camada
