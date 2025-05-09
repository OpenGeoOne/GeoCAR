# -*- coding: utf-8 -*-

"""
/***************************************************************************
 GeoCAR
                                 A QGIS plugin
 Cadastro Ambiental Rural
 Generated by Plugin Builder: http://g-sherman.github.io/Qgis-Plugin-Builder/
                              -------------------
        begin                : 2025-04-30
        copyright            : (C) 2025 by Prof Cazaroli e Leandro França
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
__date__ = '2025-04-30'
__copyright__ = '(C) 2025 by Prof Cazaroli e Leandro França'

__revision__ = '$Format:%H$'

from qgis.PyQt.QtCore import QCoreApplication
from qgis.core import (QgsProject,
                        QgsMapLayer,
                        QgsVectorFileWriter,
                        QgsProcessingException,
                        QgsProcessingAlgorithm,
                        QgsProcessingParameterFolderDestination,
                        QgsProcessingParameterVectorLayer,
                        QgsCoordinateReferenceSystem,
                        QgsWkbTypes,
                        QgsProcessing,
                        QgsFeatureRequest)
from qgis.PyQt.QtGui import QIcon
from qgis import processing
import os
from geocar.images.Imgs import *

class preparaCAR_KML(QgsProcessingAlgorithm):
    OUTPUT_FOLDER = 'OUTPUT_FOLDER'

    def tr(self, string):
        return QCoreApplication.translate('Processing', string)

    def createInstance(self):
        return preparaCAR_KML()

    def name(self):
        return 'preparaCAR_KML'

    def displayName(self):
        return self.tr('Gera Arquivo(s) KML')

    def group(self):
        return self.tr(self.groupId())

    def groupId(self):
        return ''

    def icon(self):
        return QIcon(os.path.join(os.path.dirname(os.path.dirname(__file__)), 'images/geocar.png'))

    def shortHelpString(self):
        txt = "Exporta camadas do QGIS no formato KML para o CAR."

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

    def initAlgorithm(self, config=None):
        # Define the folder destination parameter
        self.addParameter(
            QgsProcessingParameterFolderDestination(
                self.OUTPUT_FOLDER,
                'Pasta para gravar arquivo KML'
            )
        )

    def processAlgorithm(self, parameters, context, feedback):
        output_folder = self.parameterAsString(parameters, self.OUTPUT_FOLDER, context)

        # Defina o diretório de exportação
        caminho = output_folder

        # Itera sobre as camadas vetoriais no projeto
        for c in QgsProject.instance().mapLayers().values():
            if c.type() == QgsMapLayer.VectorLayer:  # Verifica se é uma camada vetorial
                if c.featureCount() > 0:  # Verifica se a camada tem feições
                    if "Geo" in c.name() or "CAR" in c.name() or "INCRA" in c.name(): # não pega Camadas fora dos 5 Grupos
                        continue
                    # Define o caminho+nome do Shapefile
                    camArq = os.path.join(caminho, c.name())

                    # Exporta a camada para Shapefile
                    error = QgsVectorFileWriter.writeAsVectorFormat(
                        c, camArq + ".shp", "UTF-8", c.crs(), "ESRI Shapefile"
                    )

                    if error[0] == QgsVectorFileWriter.NoError:
                        # Lista de extensões associadas ao Shapefile
                        extensoes = [".shp", ".shx", ".dbf", ".prj", ".cpg"]

                        # Caminhos completos para os arquivos gerados
                        shapefile_files = [
                            camArq + ext for ext in extensoes if os.path.exists(camArq + ext)
                        ]

                        # Exporta para KML
                        nomeKML = os.path.join(caminho, c.name() + ".kml")

                        # Reprojeta para WGS84 caso seja necessário
                        if c.crs().authid() != 'EPSG:4326':
                            params_reproj = {
                                'INPUT': c,
                                'TARGET_CRS': 'EPSG:4326',
                                'OUTPUT': 'TEMPORARY_OUTPUT'
                            }
                            c = processing.run('native:reprojectlayer', params_reproj, context=context)['OUTPUT']

                        error = QgsVectorFileWriter.writeAsVectorFormat(
                            c,
                            nomeKML,
                            'UTF-8',
                            c.crs(),
                            'KML'
                        )

                        if error[0] == QgsVectorFileWriter.NoError:
                            feedback.pushInfo(self.tr(f'Exportado: {nomeKML}'))
                        else:
                            feedback.reportError(self.tr(f'Erro ao exportar {nomeKML}'))

                        # Apaga os arquivos Shapefile após compactar
                        for f in shapefile_files:
                            try:
                                os.remove(f)
                            except OSError as e:
                                feedback.pushInfo(f"Erro ao remover {f} {e}")
                    else:
                        feedback.pushInfo(f"Erro ao exportar a camada {c.name()}: {error[0]}")

        feedback.pushInfo(f"Observe os arquivos KML na pasta: {output_folder}")

        return {}
