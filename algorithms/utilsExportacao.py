# -*- coding: utf-8 -*-
# Funções comuns às ferramentas de exportação (ZIP, SHP e KML) do GeoCAR
# utilsExportacao.py

import os
import re

from qgis.core import QgsMapLayer, QgsProject, QgsProviderRegistry, QgsVectorFileWriter

# Constante de sucesso compatível com QGIS 3 e QGIS 4
try:
    SEM_ERRO = QgsVectorFileWriter.WriterError.NoError
except AttributeError:
    SEM_ERRO = QgsVectorFileWriter.NoError

# Camadas de referência que não devem ser exportadas para o CAR:
# "Geo" isolado ou seguido de palavra iniciada em maiúscula (GeoOne, GeoCAR, GeoRural),
# "CAR" e "INCRA" como palavras inteiras. Assim, nomes como "Geologia" ou "CARGA" não são ignorados.
PADRAO_REFERENCIA = re.compile(r'(?<![A-Za-z])(Geo[A-Z][A-Za-z]*|Geo|CAR|INCRA)(?![A-Za-z])')


def camadaDeReferencia(nomeCamada):
    """Retorna True se a camada for de referência (GeoOne, CAR, INCRA) e deve ser ignorada."""
    return PADRAO_REFERENCIA.search(nomeCamada) is not None


def exportarCamada(camada, caminhoArquivo, nomeDriver):
    """
    Exporta a camada com QgsVectorFileWriter.writeAsVectorFormatV3, em UTF-8 e no SRC da camada.
    Retorna a tupla (erro, mensagem), no mesmo formato usado antes com writeAsVectorFormat.
    """
    opcoes = QgsVectorFileWriter.SaveVectorOptions()
    opcoes.driverName = nomeDriver
    opcoes.fileEncoding = 'UTF-8'
    resultado = QgsVectorFileWriter.writeAsVectorFormatV3(
        camada, caminhoArquivo, QgsProject.instance().transformContext(), opcoes)
    return resultado[0], resultado[1]


# Camadas auxiliares da RAIZ que nunca vão para o CAR
CAMADAS_AUXILIARES = ('linha_auxiliar',)


def _arquivoDaCamada(camada):
    """Caminho absoluto do arquivo de dados da camada vetorial (GeoPackage ou Shapefile), ou None."""
    if camada.type() != QgsMapLayer.VectorLayer or camada.providerType() != 'ogr':
        return None
    caminho = QgsProviderRegistry.instance().decodeUri('ogr', camada.source()).get('path')
    return os.path.normcase(os.path.abspath(caminho)) if caminho else None


def fontesDaRaiz(projeto):
    """
    Locais de dados da estrutura RAIZ do projeto, independentemente dos nomes dos grupos:
    • RAIZ em GeoPackage (Federal, BA, MS, MT): os arquivos GeoCAR*.gpkg;
    • RAIZ em Shapefile (GO): a pasta da camada ATI.
    Retorna um conjunto vazio quando a estrutura não é reconhecida.
    """
    fontes = set()
    for camada in projeto.mapLayers().values():
        caminho = _arquivoDaCamada(camada)
        if caminho:
            nome = os.path.basename(caminho).lower()
            if nome.startswith('geocar') and nome.endswith('.gpkg'):
                fontes.add(caminho)
    if not fontes:
        for camada in projeto.mapLayersByName('ATI'):
            caminho = _arquivoDaCamada(camada)
            if caminho:
                fontes.add(os.path.dirname(caminho))
    return fontes


def camadasParaExportar(feedback=None):
    """
    Camadas vetoriais do projeto que pertencem à estrutura RAIZ.
    Ficam de fora camadas temporárias, a Consulta CAR, camadas de apoio e resultados da pré-análise,
    seja qual for o nome delas ou do grupo em que estão.
    """
    projeto = QgsProject.instance()
    fontes = fontesDaRaiz(projeto)
    vetoriais = [c for c in projeto.mapLayers().values() if c.type() == QgsMapLayer.VectorLayer]

    if not fontes:
        if feedback:
            feedback.pushWarning('Estrutura RAIZ não reconhecida (GeoCAR*.gpkg ou camada ATI em Shapefile): '
                                 'serão consideradas todas as camadas vetoriais do projeto.')
        return vetoriais

    exportar, ignoradas = [], []
    for camada in vetoriais:
        caminho = _arquivoDaCamada(camada)
        daRaiz = caminho is not None and (caminho in fontes or os.path.dirname(caminho) in fontes)
        if daRaiz and camada.name().lower() not in CAMADAS_AUXILIARES:
            exportar.append(camada)
        elif camada.featureCount() > 0:
            ignoradas.append(camada.name())
    if feedback and ignoradas:
        feedback.pushInfo('Camadas fora da estrutura RAIZ (não exportadas): ' + ', '.join(sorted(ignoradas)))
    return exportar
