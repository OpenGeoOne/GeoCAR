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
# Calcula a APP hídrica integral (art. 4º) e a faixa da "escadinha" (art. 61-A) dentro da ATI
# appHidrica.py

__author__ = 'Prof Cazaroli e Leandro França'
__date__ = '2026-10-23'
__copyright__ = '(C) 2026 by Prof Cazaroli e Leandro França'

import os

from qgis.PyQt.QtCore import QCoreApplication
from qgis.PyQt.QtGui import QIcon
from qgis.core import (
    Qgis,
    QgsGeometry,
    QgsProcessingAlgorithm,
    QgsProcessingException,
    QgsProcessingOutputNumber,
    QgsProcessingParameterFeatureSink,
    QgsProcessingParameterField,
    QgsProcessingParameterMultipleLayers,
    QgsProcessingParameterNumber,
    QgsProcessingParameterVectorLayer,
)

from .nucleoCAR import app as moduloApp
from .nucleoCAR.processingCAR import (adicionarSaida, avisoLegal, camadaPadrao, camadaPoligonoArea,
                                      camadasPadrao, gravarResultado, rodapeAjuda)
from .nucleoCAR.utils import area_ha, feicoes_no_src, src_utm_sirgas, uniao
from .nucleoCAR.validacao import verificar_extrapolacao


class AppHidricaCAR(QgsProcessingAlgorithm):
    """APP de cursos d'água, nascentes e lagos: integral e em área rural consolidada."""

    INPUT_ATI = 'INPUT_ATI'
    INPUT_HIDROGRAFIA = 'INPUT_HIDROGRAFIA'
    CAMPO_LARGURA = 'CAMPO_LARGURA'
    LARGURA_PADRAO = 'LARGURA_PADRAO'
    INPUT_NASCENTES = 'INPUT_NASCENTES'
    INPUT_LAGOS = 'INPUT_LAGOS'
    INPUT_RIOS_POLIGONO = 'INPUT_RIOS_POLIGONO'
    INPUT_CONSOLIDADA = 'INPUT_CONSOLIDADA'
    MODULO_FISCAL = 'MODULO_FISCAL'
    AREA_2008 = 'AREA_2008'

    OUTPUT_APP_INTEGRAL = 'OUTPUT_APP_INTEGRAL'
    OUTPUT_FAIXA_ESCADINHA = 'OUTPUT_FAIXA_ESCADINHA'
    OUTPUT_APP_RECOMPOR = 'OUTPUT_APP_RECOMPOR'
    OUTPUT_USO_CONSOLIDADO = 'OUTPUT_USO_CONSOLIDADO'
    OUTPUT_APP_FORA_CONSOLIDADA = 'OUTPUT_APP_FORA_CONSOLIDADA'

    OUTPUT_N_MODULOS = 'OUTPUT_N_MODULOS'
    OUTPUT_AREA_INTEGRAL = 'OUTPUT_AREA_INTEGRAL'
    OUTPUT_AREA_RECOMPOR = 'OUTPUT_AREA_RECOMPOR'
    OUTPUT_LIMITE_61B = 'OUTPUT_LIMITE_61B'

    SAIDAS = [
        (OUTPUT_APP_INTEGRAL, 'APP integral (art. 4º)'),
        (OUTPUT_FAIXA_ESCADINHA, 'Faixa da escadinha (art. 61-A)'),
        (OUTPUT_APP_RECOMPOR, 'APP a recompor em área consolidada'),
        (OUTPUT_USO_CONSOLIDADO, 'Uso consolidado mantido em APP'),
        (OUTPUT_APP_FORA_CONSOLIDADA, 'APP fora de área consolidada'),
    ]
    # Nome da camada e do arquivo em Pre-Analise/
    NOMES_SAIDAS = {
        OUTPUT_APP_INTEGRAL: '3b_APP_integral',
        OUTPUT_FAIXA_ESCADINHA: '3b_faixa_escadinha',
        OUTPUT_APP_RECOMPOR: '3b_APP_recompor_consolidada',
        OUTPUT_USO_CONSOLIDADO: '3b_uso_consolidado_em_APP',
        OUTPUT_APP_FORA_CONSOLIDADA: '3b_APP_fora_consolidada',
    }

    def initAlgorithm(self, config=None):
        poligono = Qgis.ProcessingSourceType.VectorPolygon
        decimal = Qgis.ProcessingNumberParameterType.Double

        self.addParameter(QgsProcessingParameterVectorLayer(
            self.INPUT_ATI, self.tr('Área Total do Imóvel (ATI)'), [poligono],
            defaultValue=camadaPadrao('ati') or 'ATI'))

        self.addParameter(QgsProcessingParameterNumber(
            self.MODULO_FISCAL, self.tr('Módulo fiscal do município (ha)'), type=decimal,
            minValue=0.01, defaultValue=20.0))

        self.addParameter(QgsProcessingParameterNumber(
            self.AREA_2008, self.tr('Área do imóvel em 22/07/2008 (ha) — 0 = usar a área da ATI'),
            type=decimal, minValue=0.0, defaultValue=0.0))

        self.addParameter(QgsProcessingParameterVectorLayer(
            self.INPUT_HIDROGRAFIA, self.tr("Cursos d'água — eixo (linhas)"),
            [Qgis.ProcessingSourceType.VectorLine], optional=True,
            defaultValue=camadaPadrao('hidrografia', 'linha')))

        self.addParameter(QgsProcessingParameterField(
            self.CAMPO_LARGURA, self.tr('Campo com a largura do curso d\'água (m)'),
            parentLayerParameterName=self.INPUT_HIDROGRAFIA,
            type=Qgis.ProcessingFieldParameterDataType.Numeric, optional=True))

        self.addParameter(QgsProcessingParameterNumber(
            self.LARGURA_PADRAO, self.tr('Largura padrão quando não houver dado (m)'),
            type=decimal, minValue=0.1, defaultValue=5.0))

        self.addParameter(QgsProcessingParameterMultipleLayers(
            self.INPUT_RIOS_POLIGONO,
            self.tr("Rios — leito em polígono (ex.: Rio_10_50m_50m)"),
            layerType=poligono, optional=True, defaultValue=camadasPadrao('rios_poligono') or None))

        self.addParameter(QgsProcessingParameterVectorLayer(
            self.INPUT_NASCENTES, self.tr('Nascentes e olhos d\'água (pontos)'),
            [Qgis.ProcessingSourceType.VectorPoint], optional=True,
            defaultValue=camadaPadrao('nascentes', 'ponto')))

        self.addParameter(QgsProcessingParameterVectorLayer(
            self.INPUT_LAGOS, self.tr('Lagos e lagoas naturais (polígonos)'), [poligono],
            optional=True, defaultValue=camadaPadrao('lagos')))

        self.addParameter(QgsProcessingParameterVectorLayer(
            self.INPUT_CONSOLIDADA, self.tr('Área rural consolidada até 22/07/2008 (opcional)'),
            [poligono], optional=True, defaultValue=camadaPadrao('consolidada')))

        for chave, rotulo in self.SAIDAS:
            adicionarSaida(self, chave, rotulo, self.NOMES_SAIDAS[chave], poligono)

        self.addOutput(QgsProcessingOutputNumber(self.OUTPUT_N_MODULOS, self.tr('Número de módulos fiscais')))
        self.addOutput(QgsProcessingOutputNumber(self.OUTPUT_AREA_INTEGRAL, self.tr('APP integral (ha)')))
        self.addOutput(QgsProcessingOutputNumber(self.OUTPUT_AREA_RECOMPOR,
                                                 self.tr('APP a preservar/recompor (ha)')))
        self.addOutput(QgsProcessingOutputNumber(self.OUTPUT_LIMITE_61B,
                                                 self.tr('Limite do art. 61-B (ha)')))

    def processAlgorithm(self, parameters, context, feedback):
        camadaAti = self.parameterAsVectorLayer(parameters, self.INPUT_ATI, context)
        if camadaAti is None or camadaAti.featureCount() == 0:
            raise QgsProcessingException(self.tr('A camada ATI está vazia ou não foi informada.'))

        moduloFiscal = self.parameterAsDouble(parameters, self.MODULO_FISCAL, context)
        area2008 = self.parameterAsDouble(parameters, self.AREA_2008, context)
        camadaHidro = self.parameterAsVectorLayer(parameters, self.INPUT_HIDROGRAFIA, context)
        campoLargura = self.parameterAsString(parameters, self.CAMPO_LARGURA, context) or None
        larguraPadrao = self.parameterAsDouble(parameters, self.LARGURA_PADRAO, context)
        camadaNascentes = self.parameterAsVectorLayer(parameters, self.INPUT_NASCENTES, context)
        camadaLagos = self.parameterAsVectorLayer(parameters, self.INPUT_LAGOS, context)
        camadasRiosPoligono = [c for c in self.parameterAsLayerList(parameters, self.INPUT_RIOS_POLIGONO, context)
                               if c is not None and c.type() == 0]
        camadaConsolidada = self.parameterAsVectorLayer(parameters, self.INPUT_CONSOLIDADA, context)

        if camadaHidro is None and camadaNascentes is None and camadaLagos is None and not camadasRiosPoligono:
            raise QgsProcessingException(
                self.tr('Informe ao menos uma camada de hidrografia, nascentes ou lagos.'))

        # SRC de trabalho e perímetro do imóvel
        geomReferencia = QgsGeometry.unaryUnion(
            [f.geometry().makeValid() for f in camadaAti.getFeatures() if f.hasGeometry()])
        srcTrabalho = src_utm_sirgas(geomReferencia, camadaAti.crs())
        perimetro = uniao([g.makeValid() for _fid, _a, g in feicoes_no_src(camadaAti, srcTrabalho)])
        areaImovel = area_ha(perimetro)
        if area2008 <= 0:
            area2008 = areaImovel
        nModulos = area2008 / moduloFiscal
        feedback.pushInfo(self.tr(f'SRC de cálculo: {srcTrabalho.authid()}'))
        feedback.pushInfo(self.tr(f'Área: {areaImovel:.4f} ha | Módulos fiscais em 2008: {nModulos:.2f}'))

        consolidada = None
        if camadaConsolidada is not None:
            consolidada, problema = verificar_extrapolacao(camadaConsolidada, 'Área consolidada',
                                                           perimetro, srcTrabalho)
            if problema:
                feedback.pushWarning(problema['descricao'])

        # Cálculo das APPs
        feedback.pushInfo(self.tr('Calculando APP integral e faixa da escadinha...'))
        resultado = moduloApp.calcular_app(
            perimetro, srcTrabalho, nModulos,
            hidrografia=camadaHidro, campo_largura=campoLargura, largura_padrao=larguraPadrao,
            nascentes=camadaNascentes, lagos=camadaLagos, consolidada=consolidada,
            rios_poligono=camadasRiosPoligono)

        for aviso in resultado['avisos']:
            feedback.pushWarning(aviso)
        for detalhe in resultado['detalhes']:
            feedback.pushInfo(f"{detalhe['tipo']}: integral {detalhe['faixa_integral']:g} m | "
                              f"escadinha {detalhe['faixa_consolidada']:g} m")

        temConsolidada = consolidada is not None and not consolidada.isEmpty()
        if temConsolidada:
            areaRecompor = area_ha(resultado['app_recompor'])
            if resultado['app_nao_consolidada'] is not None:
                areaRecompor += area_ha(resultado['app_nao_consolidada'])
        else:
            # Sem área consolidada a escadinha não se aplica: toda a APP integral deve ser preservada
            areaRecompor = area_ha(resultado['app_integral'])
        limite61b = moduloApp.limite_61b(nModulos, areaImovel)

        # Gravação das saídas
        geometrias = {
            self.OUTPUT_APP_INTEGRAL: ('APP_Integral', resultado['app_integral']),
            self.OUTPUT_FAIXA_ESCADINHA: ('APP_Faixa_Escadinha', resultado['faixa_consolidada']),
            self.OUTPUT_APP_RECOMPOR: ('APP_Recompor_Consolidada',
                                       resultado['app_recompor'] if temConsolidada else None),
            self.OUTPUT_USO_CONSOLIDADO: ('Uso_Consolidado_em_APP', resultado['consolidada_liberada']),
            self.OUTPUT_APP_FORA_CONSOLIDADA: ('APP_Fora_Consolidada', resultado['app_nao_consolidada']),
        }
        resultados = {}
        for chave, (nome, geom) in geometrias.items():
            idSaida = gravarResultado(self, parameters, chave, context, feedback,
                                      camadaPoligonoArea(nome, srcTrabalho, geom), self.NOMES_SAIDAS[chave])
            if idSaida:
                resultados[chave] = idSaida

        feedback.pushInfo(self.tr(f'APP integral: {area_ha(resultado["app_integral"]):.4f} ha'))
        feedback.pushInfo(self.tr(f'APP a preservar/recompor: {areaRecompor:.4f} ha'))
        if limite61b is not None and not temConsolidada:
            feedback.pushInfo(self.tr('Limite do art. 61-B não se aplica: área consolidada não informada.'))
            limite61b = None
        if limite61b is not None:
            if areaRecompor > limite61b:
                feedback.pushWarning(self.tr(f'Excede o limite do art. 61-B ({limite61b:.4f} ha): '
                                             'a recomposição fica limitada a esse teto.'))
            else:
                feedback.pushInfo(self.tr(f'Dentro do limite do art. 61-B ({limite61b:.4f} ha).'))
        feedback.pushInfo(self.tr('GeoCAR - GeoOne'))

        resultados.update({
            self.OUTPUT_N_MODULOS: round(nModulos, 4),
            self.OUTPUT_AREA_INTEGRAL: round(area_ha(resultado['app_integral']), 4),
            self.OUTPUT_AREA_RECOMPOR: round(areaRecompor, 4),
            self.OUTPUT_LIMITE_61B: round(limite61b, 4) if limite61b is not None else -1,
        })
        return resultados

    def flags(self):
        # Grava nas camadas fixas do projeto: precisa rodar na thread principal
        return super().flags() | Qgis.ProcessingAlgorithmFlag.NoThreading

    def name(self):
        return 'apphidricacar'

    def displayName(self):
        return self.tr('b. APP hídrica e escadinha')

    def group(self):
        return self.tr('3. ✅ Pré-análise do CAR')

    def groupId(self):
        return 'preanalise'

    def tr(self, string):
        return QCoreApplication.translate('Processing', string)

    def createInstance(self):
        return AppHidricaCAR()

    def tags(self):
        return ('GeoOne,GeoCAR,GeoRural,ambiental,APP,SiCAR,rio,nascente,lago,escadinha,'
                'área consolidada,61-A,61-B,Código Florestal,módulo fiscal').split(',')

    def icon(self):
        return QIcon(os.path.join(os.path.dirname(os.path.dirname(__file__)), 'images/qualidade.png'))

    def shortHelpString(self):
        txt = """Calcula as <b>Áreas de Preservação Permanente hídricas</b> dentro da ATI.

<b>APP integral (art. 4º da Lei 12.651/2012):</b>
• cursos d'água: 30 m (&lt;10 m), 50 m (10–50 m), 100 m (50–200 m), 200 m (200–600 m), 500 m (&gt;600 m)
• rios de 10 m ou mais em polígono (leito): largura estimada por 2 × área / perímetro
• nascentes: raio de 50 m
• lagos e lagoas naturais: 50 m (até 20 ha) ou 100 m

<b>Faixa da escadinha (art. 61-A), em área rural consolidada:</b>
• rios: 5 m (até 1 MF), 8 m (1–2 MF), 15 m (2–4 MF), 20 m (4–10 MF e rio até 10 m), demais casos metade da largura, entre 30 e 100 m
• nascentes: 15 m | lagos: 5, 8, 15 ou 30 m

Com a camada de <b>área consolidada</b>, separa o que deve ser recomposto do uso que pode ser mantido e verifica o <b>teto do art. 61-B</b> (10% até 2 MF; 20% de 2 a 4 MF).

A hidrografia linear é tratada como eixo: a faixa é medida da borda do leito regular (largura/2). Complementa a ferramenta <b>APP altitude, declividade e uso restrito</b>.
<b>Estrutura RAIZ:</b> se o projeto tem as camadas fixas do <b>PreAnalise.gpkg</b>, os resultados vão direto para as camadas do grupo <b>Resultados da Pré-Análise</b>, apagando os anteriores; as saídas desta tela viram cópias opcionais. As entradas já vêm preenchidas com as camadas da RAIZ.
""" + avisoLegal()
        return txt + rodapeAjuda()
