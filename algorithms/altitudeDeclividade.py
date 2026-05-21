# -*- coding: utf-8 -*-

"""
/***************************************************************************
 GeoCAR
                                 A QGIS plugin
Cadastro Ambiental Rural (CAR)
                              -------------------
        begin                : 2026-05-20
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

__author__ = 'Prof Cazaroli e Leandro França'
__date__ = '2026-05-20'
__copyright__ = '(C) 2026 by Prof Cazaroli e Leandro França'

from qgis.PyQt.QtCore import QCoreApplication
from qgis.PyQt.QtGui import QIcon, QColor
from qgis.core import (
    QgsCoordinateReferenceSystem,
    QgsFillSymbol,
    QgsLinePatternFillSymbolLayer,
    QgsProcessing,
    QgsProcessingAlgorithm,
    QgsProcessingException,
    QgsProcessingMultiStepFeedback,
    QgsProcessingOutputLayerDefinition,
    QgsProcessingParameterCrs,
    QgsProcessingParameterFeatureSink,
    QgsProcessingParameterRasterLayer,
    QgsProcessingUtils,
    QgsSingleSymbolRenderer
)
from qgis import processing
import os


class AltitudeDeclividadeAPPUsoRestrito(QgsProcessingAlgorithm):
    """
    Gera três camadas vetoriais a partir de um MDE:
    1) APP - Área acima de 1800 m
    2) APP - Declividade acima de 45°
    3) Uso restrito - Declividade entre 25° e 45°
    """

    INPUT_DEM = 'INPUT_DEM'
    CRS = 'CRS'
    OUTPUT_ALTITUDE_1800 = 'OUTPUT_ALTITUDE_1800'
    OUTPUT_SLOPE_45 = 'OUTPUT_SLOPE_45'
    OUTPUT_SLOPE_25_45 = 'OUTPUT_SLOPE_25_45'

    def initAlgorithm(self, config=None):

        self.addParameter(
            QgsProcessingParameterRasterLayer(
                self.INPUT_DEM,
                self.tr('MDE / MDT'),
                defaultValue=None
            )
        )

        self.addParameter(
            QgsProcessingParameterCrs(
                self.CRS,
                self.tr('SRC projetado'),
                defaultValue='ProjectCrs'
            )
        )

        self.addParameter(
            QgsProcessingParameterFeatureSink(
                self.OUTPUT_ALTITUDE_1800,
                self.tr('APP - Área acima de 1800 m'),
                type=QgsProcessing.TypeVectorPolygon,
                createByDefault=True,
                defaultValue=None
            )
        )

        self.addParameter(
            QgsProcessingParameterFeatureSink(
                self.OUTPUT_SLOPE_45,
                self.tr('APP - Declividade acima de 45°'),
                type=QgsProcessing.TypeVectorPolygon,
                createByDefault=True,
                defaultValue=None
            )
        )

        self.addParameter(
            QgsProcessingParameterFeatureSink(
                self.OUTPUT_SLOPE_25_45,
                self.tr('Uso restrito - Declividade entre 25° e 45°'),
                type=QgsProcessing.TypeVectorPolygon,
                createByDefault=True,
                defaultValue=None
            )
        )

    def _check_projected_crs(self, crs: QgsCoordinateReferenceSystem):
        """Verifica se o SRC informado é válido e projetado."""
        if not crs or not crs.isValid():
            raise QgsProcessingException(
                self.tr('SRC inválido. Selecione um SRC projetado, preferencialmente UTM.')
            )

        if crs.isGeographic():
            raise QgsProcessingException(
                self.tr(
                    f'O SRC escolhido ({crs.authid()}) não é projetado.\n'
                    'Para cálculo de declividade e análise altimétrica, utilize um SRC projetado em metros, como UTM/SIRGAS 2000.'
                )
            )

    def _check_lftools_installed(self):
        """Verifica se o algoritmo de Limiarização Binária do LFTools está disponível."""
        try:
            processing.algorithmHelp('lftools:binarythresholding')
        except Exception:
            raise QgsProcessingException(
                self.tr(
                    'O plugin LFTools não foi encontrado no Processing. '
                    'Instale/ative o LFTools e reinicie o QGIS. '
                    '(Algoritmo esperado: lftools:binarythresholding)'
                )
            )

    def _make_output_definition(self, parameters, output_key, context, destination_name):
        """Cria/ajusta QgsProcessingOutputLayerDefinition para controlar o nome da camada."""
        out_param = parameters[output_key]

        if not isinstance(out_param, QgsProcessingOutputLayerDefinition):
            output_def = QgsProcessingOutputLayerDefinition(out_param, context.project())
        else:
            output_def = out_param

        output_def.destinationName = destination_name
        return output_def

    def _binary_raster_to_vector(self, binary_raster, output_definition, context, feedback, prefix):
        """Poligoniza raster binário, extrai DN = 1 e grava o resultado final."""

        polygonized = processing.run(
            'gdal:polygonize',
            {
                'BAND': 1,
                'EIGHT_CONNECTEDNESS': False,
                'EXTRA': '',
                'FIELD': 'DN',
                'INPUT': binary_raster,
                'OUTPUT': QgsProcessing.TEMPORARY_OUTPUT
            },
            context=context,
            feedback=feedback,
            is_child_algorithm=True
        )

        if feedback.isCanceled():
            return None

        extracted = processing.run(
            'native:extractbyattribute',
            {
                'FIELD': 'DN',
                'INPUT': polygonized['OUTPUT'],
                'OPERATOR': 0,
                'VALUE': '1',
                'OUTPUT': output_definition
            },
            context=context,
            feedback=feedback,
            is_child_algorithm=True
        )

        return extracted['OUTPUT']

    def processAlgorithm(self, parameters, context, model_feedback):

        feedback = QgsProcessingMultiStepFeedback(8, model_feedback)
        results = {}

        self._check_lftools_installed()

        dem_layer = self.parameterAsRasterLayer(parameters, self.INPUT_DEM, context)
        if dem_layer is None:
            raise QgsProcessingException(self.invalidSourceError(parameters, self.INPUT_DEM))

        if not dem_layer.crs().isValid():
            raise QgsProcessingException(self.tr('O MDE/MDT de entrada não possui SRC válido.'))

        target_crs = self.parameterAsCrs(parameters, self.CRS, context)
        self._check_projected_crs(target_crs)

        dem_source = dem_layer.dataProvider().dataSourceUri()

        feedback.pushInfo(self.tr('Reprojetando o MDE/MDT para o SRC projetado selecionado...'))

        reproj = processing.run(
            'gdal:warpreproject',
            {
                'INPUT': dem_source,
                'SOURCE_CRS': dem_layer.crs(),
                'TARGET_CRS': target_crs,
                'RESAMPLING': 1,
                'NODATA': None,
                'TARGET_RESOLUTION': None,
                'OPTIONS': '',
                'DATA_TYPE': 0,
                'TARGET_EXTENT': None,
                'TARGET_EXTENT_CRS': None,
                'MULTITHREADING': True,
                'EXTRA': '',
                'OUTPUT': QgsProcessing.TEMPORARY_OUTPUT
            },
            context=context,
            feedback=feedback,
            is_child_algorithm=True
        )
        dem_projected = reproj['OUTPUT']

        feedback.setCurrentStep(1)
        if feedback.isCanceled():
            return {}

        feedback.pushInfo(self.tr('Calculando declividade em graus...'))

        slope = processing.run(
            'gdal:slope',
            {
                'INPUT': dem_projected,
                'BAND': 1,
                'SCALE': 1.0,
                'AS_PERCENT': False,
                'COMPUTE_EDGES': True,
                'ZEVENBERGEN': False,
                'OPTIONS': '',
                'EXTRA': '',
                'OUTPUT': QgsProcessing.TEMPORARY_OUTPUT
            },
            context=context,
            feedback=feedback,
            is_child_algorithm=True
        )
        slope_degrees = slope['OUTPUT']

        feedback.setCurrentStep(2)
        if feedback.isCanceled():
            return {}

        feedback.pushInfo(self.tr('Classificando APP por altitude acima de 1800 m...'))

        altitude_bin = processing.run(
            'lftools:binarythresholding',
            {
                'METHOD': 3,
                'OPEN': False,
                'RasterIN': dem_projected,
                'SAMPLES': None,
                'VALUES': '1800,6000',
                'RasterOUT': QgsProcessing.TEMPORARY_OUTPUT
            },
            context=context,
            feedback=feedback,
            is_child_algorithm=True
        )

        feedback.setCurrentStep(3)
        if feedback.isCanceled():
            return {}

        feedback.pushInfo(self.tr('Classificando APP por declividade acima de 45°...'))

        slope_45_bin = processing.run(
            'lftools:binarythresholding',
            {
                'METHOD': 3,
                'OPEN': False,
                'RasterIN': slope_degrees,
                'SAMPLES': None,
                'VALUES': '45,90',
                'RasterOUT': QgsProcessing.TEMPORARY_OUTPUT
            },
            context=context,
            feedback=feedback,
            is_child_algorithm=True
        )

        feedback.setCurrentStep(4)
        if feedback.isCanceled():
            return {}

        feedback.pushInfo(self.tr('Classificando uso restrito por declividade entre 25° e 45°...'))

        slope_25_45_bin = processing.run(
            'lftools:binarythresholding',
            {
                'METHOD': 3,
                'OPEN': False,
                'RasterIN': slope_degrees,
                'SAMPLES': None,
                'VALUES': '25,45',
                'RasterOUT': QgsProcessing.TEMPORARY_OUTPUT
            },
            context=context,
            feedback=feedback,
            is_child_algorithm=True
        )

        feedback.setCurrentStep(5)
        if feedback.isCanceled():
            return {}

        out_alt = self._make_output_definition(
            parameters,
            self.OUTPUT_ALTITUDE_1800,
            context,
            'APP_Altitude_Acima_1800m'
        )
        results[self.OUTPUT_ALTITUDE_1800] = self._binary_raster_to_vector(
            altitude_bin['RasterOUT'], out_alt, context, feedback, 'altitude_1800'
        )

        feedback.setCurrentStep(6)
        if feedback.isCanceled():
            return {}

        out_slope_45 = self._make_output_definition(
            parameters,
            self.OUTPUT_SLOPE_45,
            context,
            'APP_Declividade_Acima_45'
        )
        results[self.OUTPUT_SLOPE_45] = self._binary_raster_to_vector(
            slope_45_bin['RasterOUT'], out_slope_45, context, feedback, 'slope_45'
        )

        feedback.setCurrentStep(7)
        if feedback.isCanceled():
            return {}

        out_slope_25_45 = self._make_output_definition(
            parameters,
            self.OUTPUT_SLOPE_25_45,
            context,
            'Uso_Restrito_Declividade_25_45'
        )
        results[self.OUTPUT_SLOPE_25_45] = self._binary_raster_to_vector(
            slope_25_45_bin['RasterOUT'], out_slope_25_45, context, feedback, 'slope_25_45'
        )

        self.output_altitude_id = results[self.OUTPUT_ALTITUDE_1800]
        self.output_slope_45_id = results[self.OUTPUT_SLOPE_45]
        self.output_slope_25_45_id = results[self.OUTPUT_SLOPE_25_45]

        feedback.pushInfo(self.tr('Processamento finalizado com sucesso!'))
        feedback.pushInfo(self.tr('GeoCAR - GeoOne'))

        return results

    def name(self):
        return 'AltitudeDeclividadeAPPUsoRestrito'.lower()

    def displayName(self):
        return self.tr('2. APP altitude, declividade e uso restrito')

    def group(self):
        return self.tr(self.groupId())

    def groupId(self):
        return ''

    def tr(self, string):
        return QCoreApplication.translate('Processing', string)

    def createInstance(self):
        return AltitudeDeclividadeAPPUsoRestrito()

    def tags(self):
        return 'GeoOne,GeoCAR,GeoRural,ambiental,APP,SiCAR,slope,declividade,inclinação,rampa,altura,altitude,elevação,MDE,MDT,Código Florestal,uso restrito'.split(',')

    def icon(self):
        return QIcon(os.path.join(os.path.dirname(os.path.dirname(__file__)), 'images/geocar.png'))

    def shortHelpString(self):
        txt = """Identifica automaticamente três classes ambientais relacionadas ao Código Florestal a partir de um Modelo Digital de Elevação/Terreno (MDE/MDT):

• <b>APP - Área acima de 1800 m</b>  
• <b>APP - Declividade acima de 45°</b>  
• <b>Uso restrito - Declividade entre 25° e 45°</b>

A ferramenta reprojeta o MDE/MDT para o SRC projetado selecionado, calcula a declividade em graus, classifica os limiares ambientais e converte os resultados em camadas vetoriais.

<b>Parâmetros principais:</b>
• MDE / MDT – raster altimétrico de entrada  
• SRC projetado – sistema de coordenadas em metros, preferencialmente UTM

<b>Resultados:</b>
São geradas três camadas vetoriais:
• <b>APP - Área acima de 1800 m</b>  
• <b>APP - Declividade acima de 45°</b>  
• <b>Uso restrito - Declividade entre 25° e 45°</b>

<b>Observação:</b>
Utilize um MDE/MDT consistente, com altitude em metros e SRC projetado adequado à área de estudo.
"""

        footer = '''<div>
                      <div align="center">
                      <a target="_blank" rel="noopener noreferrer" href="https://geoone.com.br/pvcar/"><img title="Inscreva-se no curso de CAR" style="width: 100%; height: auto;" src="'''+ os.path.join(os.path.dirname(os.path.dirname(__file__)), 'images/CAR_GeoOne.jpg') +'''"></a>
                      </div>
                      <div align="right">
                      <p align="right">
                      <a href="https://geoone.com.br/pvcar/"><span style="font-weight: bold;">Conheça o curso de Cadastro Ambiental Rural (CAR)</span></a>
                      </p>
                      <p align="right">
                      <a href="https://portal.geoone.com.br/m/lessons/car?classId=6080"><span style="font-weight: bold;">Acesse a aula sobre esta ferramenta no curso de CAR da GeoOne</span></a>
                      </p>
                      <a target="_blank" rel="noopener noreferrer" href="https://geoone.com.br/"><img title="GeoOne" width="280"  src="'''+ os.path.join(os.path.dirname(os.path.dirname(__file__)), 'images/GeoOne.png') +'''"></a>
                      <p><i>"Mapeamento automatizado, fácil e direto ao ponto é na GeoOne!"</i></p>
                      </div>
                    </div>'''
        return txt + footer

    def postProcessAlgorithm(self, context, feedback):

        def aplicar_hachura(layer_id, cor_hex, angle=45, distance=2.0, width=0.5):
            layer = QgsProcessingUtils.mapLayerFromString(layer_id, context)
            if not layer:
                return

            hachura = QgsLinePatternFillSymbolLayer()
            hachura.setColor(QColor(cor_hex))
            hachura.setLineAngle(angle)
            hachura.setDistance(distance)
            hachura.setLineWidth(width)

            symbol = QgsFillSymbol.createSimple({
                'color': '0,0,0,0',
                'outline_color': cor_hex,
                'outline_width': '0.4'
            })
            symbol.appendSymbolLayer(hachura)

            layer.setRenderer(QgsSingleSymbolRenderer(symbol))
            layer.triggerRepaint()

        aplicar_hachura(self.output_altitude_id, "#00ffeb")
        aplicar_hachura(self.output_slope_45_id, "#44a0e6")
        aplicar_hachura(self.output_slope_25_45_id, "#ffb000")

        return {}
