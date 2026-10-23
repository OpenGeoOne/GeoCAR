# -*- coding: utf-8 -*-
# Funções comuns às ferramentas de exportação (ZIP, SHP e KML) do GeoCAR
# utilsExportacao.py

import re

from qgis.core import QgsProject, QgsVectorFileWriter

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
