# -*- coding: utf-8 -*-

"""
/***************************************************************************
 GeoCAR
                                 A QGIS plugin
Cadastro Ambiental Rural (CAR)
 Generated by Plugin Builder: http://g-sherman.github.io/Qgis-Plugin-Builder/
                              -------------------
        begin                : 2024-11-25
        copyright            : (C) 2024 by Prof Cazaroli e Leandro França
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

__author__ = 'Prof Cazaroli e Leandro França'
__date__ = '2024-11-25'
__copyright__ = '(C) 2024 by Prof Cazaroli e Leandro França'

from qgis.PyQt.QtCore import QCoreApplication, QVariant
from qgis.core import *
import os
from qgis.PyQt.QtGui import QIcon
from GeoCAR.images.Imgs import *


class BaixarCAR(QgsProcessingAlgorithm):

    INPUT = 'INPUT'
    OUTPUT = 'OUTPUT'
    EXTENT = 'EXTENT'
    WFS = 'WFS'

    mapping = { 0: 'Imóveis do Sicar',
               # 1: 'Nova camada',
            }

    layer_name = {    0: 'sicar_imoveis_xx',
                     # 1: 'nova_camada',
            }

    links = {     mapping[0]: 'https://geoserver.car.gov.br/geoserver/sicar/wfs',
                  # mapping[1]: 'http://geserver.geoone',
            }

    def initAlgorithm(self, config):

        self.addParameter(
            QgsProcessingParameterExtent(
                self.EXTENT,
                self.tr('Retângulo de Extensão')
            )
        )

        self.addParameter(
            QgsProcessingParameterEnum(
                self.WFS,
                self.tr('Camada'),
                options = self.links.keys(),
                defaultValue= 0
            )
        )

        self.addParameter(
            QgsProcessingParameterFeatureSink(
                self.OUTPUT,
                self.tr('Resultado da consulta')
            )
        )

    def processAlgorithm(self, parameters, context, feedback):

        extensao = self.parameterAsExtent(
        parameters,
        self.EXTENT,
        context
        )
        if not extensao:
            raise QgsProcessingException(self.invalidSourceError(parameters, self.EXTENT))

        crsSrc = QgsCoordinateReferenceSystem(QgsProject().instance().crs())
        crsDest = QgsCoordinateReferenceSystem('EPSG:4674')
        proj2geo = QgsCoordinateTransform(crsSrc, crsDest, QgsProject.instance())
        extensao = proj2geo.transform(extensao)

        option = self.parameterAsEnum(parameters, self.WFS, context)
        layer = self.mapping[option]
        name = self.layer_name[option]
        link = self.links[layer]

        path = os.path.dirname(__file__) + "/shp" + "/BR_UF_2020.shp"
        estado = QgsVectorLayer(path, "BR_UF_2020", "ogr")

        uris = list()
        for feat in estado.getFeatures():
             if feat.geometry().intersects(extensao):

                 uri_default= """pagingEnabled='true' preferCoordinatesForWfsT11='false' restrictToRequestBBOX='1' srsname='EPSG:4674' typename='name_' url='link' version='auto'"""
                 uri_default = uri_default.replace('name_',name)
                 uri_default = uri_default.replace('link',link)
                 uri_default = uri_default.replace('xx',feat['SIGLA_UF'].lower())
                 uris.append(uri_default)

        source = QgsVectorLayer(uris[0], "my wfs layer", "WFS")
        (sink, dest_id) = self.parameterAsSink(
            parameters,
            self.OUTPUT,
            context,
            source.fields(),
            source.wkbType(),
            source.sourceCrs()
        )
        if sink is None:
            raise QgsProcessingException(self.invalidSinkError(parameters, self.OUTPUT))

        for uri in uris:
            vlayer = QgsVectorLayer(uri, "wfs_layer", "WFS")

            request = QgsFeatureRequest().setFilterRect(extensao)

            for current, feature in enumerate(vlayer.getFeatures(request)):
                # Stop the algorithm if cancel button has been clicked
                if feedback.isCanceled():
                    break

                # Add a feature in the sink
                sink.addFeature(feature, QgsFeatureSink.FastInsert)

        global renamer
        renamer = Renamer(layer)
        context.layerToLoadOnCompletionDetails(dest_id).setPostProcessor(renamer)

        return {self.OUTPUT: dest_id}

    def name(self):
        return 'baixarcar'

    def displayName(self):
        return self.tr('Consulta CAR')

    def group(self):
        return self.tr(self.groupId())

    def groupId(self):
        return ''

    def tr(self, string):
        return QCoreApplication.translate('Processing', string)

    def createInstance(self):
        return BaixarCAR()

    def icon(self):
        return QIcon(os.path.join(os.path.dirname(os.path.dirname(__file__)), 'images/geocar.png'))

    def shortHelpString(self):
        txt = 'Baixa camadas do CAR a partir de uma extensão (retângulo).'

        footer = '''<div>
                      <div align="center">
                      <img style="width: 100%; height: auto;" src="data:image/jpg;base64,'''+ CAR_GeoOne +'''
                      </div>
                      <div align="right">
                      <p align="right">
                      <a href="https://geoone.com.br/pvcar2/"><span style="font-weight: bold;">Conheça o curso de Cadastro Ambiental Rural (CAR)</span></a>
                      </p>
                      <p align="right">
                      <a href="https://portal.geoone.com.br/m/lessons/car"><span style="font-weight: bold;">Acesse seu curso na GeoOne</span></a>
                      </p>
                      <a target="_blank" rel="noopener noreferrer" href="https://geoone.com.br/"><img title="GeoOne" src="data:image/png;base64,'''+ GeoOne +'''"></a>
                      <p><i>"Mapeamento automatizado, fácil e direto ao ponto é na GeoOne!"</i></p>
                      </div>
                    </div>'''
        return txt + footer

class Renamer (QgsProcessingLayerPostProcessorInterface):
    def __init__(self, layer_name):
        self.name = layer_name
        super().__init__()

    def postProcessLayer(self, layer, context, feedback):
        layer.setName(self.name)