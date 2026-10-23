# -*- coding: utf-8 -*-
"""
Módulo fiscal do município obtido dos imóveis vizinhos do SICAR.

Cada imóvel do SICAR traz a área (ha) e o número de módulos fiscais (m_fiscal); a razão
área / m_fiscal é o tamanho do módulo fiscal do município. Usa-se a mediana dos imóveis do
mesmo município do imóvel analisado (o município do vizinho mais próximo do centro da ATI).
"""

from statistics import median

from qgis.core import QgsCoordinateTransform, QgsGeometry, QgsProject


def _indiceCampo(camada, nome):
    """Índice do campo pelo nome completo ou truncado em 10 caracteres (shapefile), ou -1."""
    for i, campo in enumerate(camada.fields()):
        nomeCampo = campo.name().lower()
        if nomeCampo == nome or (len(nomeCampo) == 10 and nome.startswith(nomeCampo)):
            return i
    return -1


def camadaTemCamposSicar(camada):
    """True se a camada tem os campos do SICAR necessários (area, m_fiscal, cod_municipio_ibge)."""
    return all(_indiceCampo(camada, n) >= 0 for n in ('area', 'm_fiscal', 'cod_municipio_ibge'))


def moduloFiscalPelosVizinhos(camadas, perimetro, srcTrabalho):
    """
    Retorna (modulo_ha, cod_municipio, n_imoveis) ou None se não houver dados.
    perimetro: geometria da ATI no srcTrabalho.
    """
    centro = perimetro.centroid()
    amostras = []   # (distância ao centro da ATI, município, área/m_fiscal)
    for camada in camadas:
        if camada is None or not camadaTemCamposSicar(camada):
            continue
        iArea, iModulos, iMunicipio = (_indiceCampo(camada, n) for n in ('area', 'm_fiscal', 'cod_municipio_ibge'))
        transformacao = QgsCoordinateTransform(camada.crs(), srcTrabalho, QgsProject.instance())
        for feicao in camada.getFeatures():
            try:
                area, modulos = float(feicao[iArea]), float(feicao[iModulos])
            except (TypeError, ValueError):
                continue
            if area <= 0 or modulos <= 0 or feicao[iMunicipio] in (None, ''):
                continue
            geometria = QgsGeometry(feicao.geometry())
            if geometria.isNull():
                continue
            geometria.transform(transformacao)
            amostras.append((geometria.distance(centro), str(feicao[iMunicipio]), area / modulos))
    if not amostras:
        return None
    municipio = min(amostras)[1]
    razoes = [r for _d, m, r in amostras if m == municipio]
    valor = median(razoes)
    # Os módulos fiscais são números redondos (5 a 110 ha); a razão traz o arredondamento do SICAR
    valor = round(valor) if abs(valor - round(valor)) < 0.2 else round(valor, 1)
    return valor, municipio, len(razoes)
