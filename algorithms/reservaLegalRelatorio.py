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
# Estima a Reserva Legal e gera o relatório HTML completo da pré-análise do CAR
# reservaLegalRelatorio.py

__author__ = 'Prof Cazaroli e Leandro França'
__date__ = '2026-10-23'
__copyright__ = '(C) 2026 by Prof Cazaroli e Leandro França'

import os
from datetime import datetime

from qgis.PyQt.QtCore import QCoreApplication
from qgis.PyQt.QtGui import QIcon
from qgis.core import (
    Qgis,
    QgsProcessingAlgorithm,
    QgsProcessingException,
    QgsProcessingParameterBoolean,
    QgsProcessingOutputNumber,
    QgsProcessingParameterEnum,
    QgsProcessingParameterField,
    QgsProcessingParameterFileDestination,
    QgsProcessingParameterMultipleLayers,
    QgsProcessingParameterNumber,
    QgsProcessingParameterString,
    QgsProcessingParameterVectorLayer,
    QgsVectorLayer,
)

from .nucleoCAR import analise
from .nucleoCAR.processingCAR import (OPCOES_RL, VALORES_RL, avisoLegal, camadaFixa, camadaPadrao,
                                      camadasPadrao, destinoPadrao, garantirCamadaFixa, gravarECarregarResultado,
                                      limparCamada, projetoSalvo, resolverModuloFiscal, rodapeAjuda,
                                      substituirFeicoes)
from .nucleoCAR.sobreposicao import LARGURA_DIVISA_PADRAO, PERC_DIVISA_PADRAO


class ReservaLegalRelatorioCAR(QgsProcessingAlgorithm):
    """Pré-análise completa e relatório em PDF ou HTML (validação, sobreposições, APP e Reserva Legal)."""

    INPUT_ATI = 'INPUT_ATI'
    MODULO_FISCAL = 'MODULO_FISCAL'
    AREA_2008 = 'AREA_2008'
    PERCENTUAL_RL = 'PERCENTUAL_RL'
    INPUT_VEGETACAO = 'INPUT_VEGETACAO'
    INPUT_CONSOLIDADA = 'INPUT_CONSOLIDADA'
    INPUT_HIDROGRAFIA = 'INPUT_HIDROGRAFIA'
    CAMPO_LARGURA = 'CAMPO_LARGURA'
    LARGURA_PADRAO = 'LARGURA_PADRAO'
    INPUT_NASCENTES = 'INPUT_NASCENTES'
    INPUT_LAGOS = 'INPUT_LAGOS'
    INPUT_RIOS_POLIGONO = 'INPUT_RIOS_POLIGONO'
    INPUT_RESTRICOES = 'INPUT_RESTRICOES'
    LARGURA_DIVISA = 'LARGURA_DIVISA'
    PERC_DIVISA = 'PERC_DIVISA'
    OUTPUT_HTML = 'OUTPUT_HTML'
    GERAR_CAMADAS = 'GERAR_CAMADAS'
    INPUT_COBERTURAS = 'INPUT_COBERTURAS'
    INPUT_RESERVAS = 'INPUT_RESERVAS'
    INPUT_SERVIDOES = 'INPUT_SERVIDOES'
    INPUT_SIGEF = 'INPUT_SIGEF'
    AUTO_CONSULTAS = 'AUTO_CONSULTAS'
    IMOVEL = 'IMOVEL'
    MUNICIPIO_UF = 'MUNICIPIO_UF'
    PROPRIETARIO = 'PROPRIETARIO'
    RESPONSAVEL = 'RESPONSAVEL'

    # Identificação do trabalho no topo do relatório: parâmetro -> rótulo
    IDENTIFICACAO = [
        (IMOVEL, 'Imóvel'),
        (MUNICIPIO_UF, 'Município/UF'),
        (PROPRIETARIO, 'Proprietário/possuidor'),
        (RESPONSAVEL, 'Responsável técnico (CREA/CFT)'),
    ]

    # Camadas da análise -> nomes dos resultados da 3a e da 3b (o perímetro em UTM não é gravado)
    CAMADAS_RESULTADO = {
        'Problemas de validação': 'Problemas_Validacao',
        'Sobreposições': 'Sobreposicoes',
        'APP integral (art. 4º)': 'APP_Integral',
        'Faixa escadinha (art. 61-A)': 'Faixa_Escadinha',
        'APP a recompor em área consolidada': 'APP_Recompor_Consolidada',
        'Uso consolidado mantido em APP': 'Uso_Consolidado_em_APP',
        'APP fora de área consolidada': 'APP_Fora_Consolidada',
        'Inconsistências': 'Inconsistencias',
        'Divergências SIGEF': 'Divergencias_SIGEF',
    }

    OUTPUT_RL_EXIGIDA = 'OUTPUT_RL_EXIGIDA'
    OUTPUT_VEGETACAO = 'OUTPUT_VEGETACAO'
    OUTPUT_DEFICIT_COM_APP = 'OUTPUT_DEFICIT_COM_APP'
    OUTPUT_DEFICIT_SEM_APP = 'OUTPUT_DEFICIT_SEM_APP'

    def initAlgorithm(self, config=None):
        poligono = Qgis.ProcessingSourceType.VectorPolygon
        decimal = Qgis.ProcessingNumberParameterType.Double

        self.addParameter(QgsProcessingParameterVectorLayer(
            self.INPUT_ATI, self.tr('Área Total do Imóvel (ATI)'), [poligono],
            defaultValue=camadaPadrao('ati') or 'ATI'))
        for chave, rotulo in self.IDENTIFICACAO:
            self.addParameter(QgsProcessingParameterString(
                chave, self.tr(f'{rotulo} — no relatório (opcional)'), optional=True))
        self.addParameter(QgsProcessingParameterNumber(
            self.MODULO_FISCAL, self.tr('Módulo fiscal do município (ha) — 0 = automático pelos CARs vizinhos'),
            type=decimal, minValue=0.0, defaultValue=0.0))
        self.addParameter(QgsProcessingParameterNumber(
            self.AREA_2008, self.tr('Área do imóvel em 22/07/2008 (ha) — 0 = usar a área da ATI'),
            type=decimal, minValue=0.0, defaultValue=0.0))
        self.addParameter(QgsProcessingParameterEnum(
            self.PERCENTUAL_RL, self.tr('Percentual de Reserva Legal (art. 12)'),
            options=OPCOES_RL, defaultValue=0))
        self.addParameter(QgsProcessingParameterVectorLayer(
            self.INPUT_VEGETACAO, self.tr('Vegetação nativa'), [poligono], optional=True,
            defaultValue=camadaPadrao('vegetacao')))
        self.addParameter(QgsProcessingParameterVectorLayer(
            self.INPUT_CONSOLIDADA, self.tr('Área rural consolidada até 22/07/2008'), [poligono],
            optional=True, defaultValue=camadaPadrao('consolidada')))
        self.addParameter(QgsProcessingParameterVectorLayer(
            self.INPUT_HIDROGRAFIA, self.tr("Cursos d'água — eixo (linhas)"),
            [Qgis.ProcessingSourceType.VectorLine], optional=True,
            defaultValue=camadaPadrao('hidrografia', 'linha')))
        self.addParameter(QgsProcessingParameterField(
            self.CAMPO_LARGURA, self.tr("Campo com a largura do curso d'água (m)"),
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
            self.INPUT_NASCENTES, self.tr("Nascentes e olhos d'água (pontos)"),
            [Qgis.ProcessingSourceType.VectorPoint], optional=True,
            defaultValue=camadaPadrao('nascentes', 'ponto')))
        self.addParameter(QgsProcessingParameterVectorLayer(
            self.INPUT_LAGOS, self.tr('Lagos e lagoas naturais (polígonos)'), [poligono],
            optional=True, defaultValue=camadaPadrao('lagos')))
        self.addParameter(QgsProcessingParameterMultipleLayers(
            self.INPUT_RESTRICOES, self.tr('Camadas de restrição (sobreposição)'),
            layerType=poligono, optional=True, defaultValue=camadasPadrao('restricoes') or None))
        self.addParameter(QgsProcessingParameterNumber(
            self.LARGURA_DIVISA, self.tr('Ajuste de divisa: largura média máxima da faixa (m)'),
            type=Qgis.ProcessingNumberParameterType.Double, minValue=0.0, defaultValue=LARGURA_DIVISA_PADRAO))
        self.addParameter(QgsProcessingParameterNumber(
            self.PERC_DIVISA, self.tr('Ajuste de divisa: área máxima (% do imóvel)'),
            type=Qgis.ProcessingNumberParameterType.Double, minValue=0.0, maxValue=100.0,
            defaultValue=PERC_DIVISA_PADRAO))
        # Consistência entre camadas (mesma verificação da ferramenta d), em parâmetros avançados
        for chave, rotulo, candidatos in (
                (self.INPUT_COBERTURAS, 'Consistência: outras coberturas do solo (área consolidada, pousio...)', 'coberturas'),
                (self.INPUT_RESERVAS, 'Consistência: Reserva Legal', 'reservas'),
                (self.INPUT_SERVIDOES, 'Consistência: servidão administrativa (polígonos)', 'servidoes')):
            parametro = QgsProcessingParameterMultipleLayers(
                chave, self.tr(rotulo), layerType=poligono, optional=True,
                defaultValue=camadasPadrao(candidatos) or None)
            parametro.setFlags(parametro.flags() | Qgis.ProcessingParameterFlag.Advanced)
            self.addParameter(parametro)
        parametro = QgsProcessingParameterVectorLayer(
            self.INPUT_SIGEF, self.tr('Parcelas certificadas no SIGEF (comparação com a ATI)'), [poligono],
            optional=True, defaultValue=camadaPadrao('sigef'))
        parametro.setFlags(parametro.flags() | Qgis.ProcessingParameterFlag.Advanced)
        self.addParameter(parametro)
        self.addParameter(QgsProcessingParameterFileDestination(
            self.OUTPUT_HTML, self.tr('Relatório de pré-análise (PDF ou HTML)'),
            fileFilter='PDF (*.pdf);;HTML (*.html)',
            # Data no nome: cada dia de trabalho fica com o seu relatório
            defaultValue=destinoPadrao(f"GeoCAR_Resultados_Pre-Analise_{datetime.now().strftime('%Y-%m-%d')}.pdf")))
        self.addParameter(QgsProcessingParameterBoolean(
            self.AUTO_CONSULTAS, self.tr('Fazer as consultas que faltarem (vizinhos com CAR e com SIGEF, restrições oficiais)'), defaultValue=True))
        self.addParameter(QgsProcessingParameterBoolean(
            self.GERAR_CAMADAS,
            self.tr('Gerar também as camadas de resultado (as mesmas das ferramentas a e b)'),
            # Marcada quando a RAIZ tem as camadas fixas de resultado
            defaultValue=camadaFixa('Sobreposicoes') is not None or projetoSalvo()))

        self.addOutput(QgsProcessingOutputNumber(self.OUTPUT_RL_EXIGIDA, self.tr('RL exigida (ha)')))
        self.addOutput(QgsProcessingOutputNumber(self.OUTPUT_VEGETACAO, self.tr('Vegetação nativa (ha)')))
        self.addOutput(QgsProcessingOutputNumber(self.OUTPUT_DEFICIT_COM_APP,
                                                 self.tr('Déficit de RL com cômputo da APP (ha)')))
        self.addOutput(QgsProcessingOutputNumber(self.OUTPUT_DEFICIT_SEM_APP,
                                                 self.tr('Déficit de RL sem cômputo da APP (ha)')))

    def processAlgorithm(self, parameters, context, feedback):
        camadaAti = self.parameterAsVectorLayer(parameters, self.INPUT_ATI, context)
        if camadaAti is None or camadaAti.featureCount() == 0:
            raise QgsProcessingException(self.tr('A camada ATI está vazia ou não foi informada.'))

        caminhoHtml = self.parameterAsFileOutput(parameters, self.OUTPUT_HTML, context)
        indiceRl = self.parameterAsEnum(parameters, self.PERCENTUAL_RL, context)

        # Restrições e parcelas do SIGEF; as consultas que faltarem são feitas agora (vizinhos com CAR e com SIGEF,
        # restrições oficiais)
        restricoes = [c for c in self.parameterAsLayerList(parameters, self.INPUT_RESTRICOES, context)
                      if isinstance(c, QgsVectorLayer)]
        camadaSigef = self.parameterAsVectorLayer(parameters, self.INPUT_SIGEF, context)
        if self.parameterAsBool(parameters, self.AUTO_CONSULTAS, context):
            from .nucleoCAR.consultas import completarRestricoes, completarSigef, completarVizinhos
            restricoes = completarVizinhos(context, feedback, camadaAti, restricoes)
            restricoes = completarRestricoes(context, feedback, camadaAti, restricoes)
            camadaSigef = completarSigef(context, feedback, camadaAti, camadaSigef)
        self._camadasConsultadas = restricoes + [camadaSigef]   # mantém vivas as camadas temporárias

        parametrosAnalise = {
            'perimetro': camadaAti,
            'modulo_fiscal_ha': resolverModuloFiscal(
                self.parameterAsDouble(parameters, self.MODULO_FISCAL, context), camadaAti,
                restricoes, feedback, context.project()),
            'area_2008_ha': self.parameterAsDouble(parameters, self.AREA_2008, context),
            'pct_rl': VALORES_RL[indiceRl],
            'vegetacao': self.parameterAsVectorLayer(parameters, self.INPUT_VEGETACAO, context),
            'consolidada': self.parameterAsVectorLayer(parameters, self.INPUT_CONSOLIDADA, context),
            'hidrografia': self.parameterAsVectorLayer(parameters, self.INPUT_HIDROGRAFIA, context),
            'campo_largura': self.parameterAsString(parameters, self.CAMPO_LARGURA, context) or None,
            'largura_padrao': self.parameterAsDouble(parameters, self.LARGURA_PADRAO, context),
            'nascentes': self.parameterAsVectorLayer(parameters, self.INPUT_NASCENTES, context),
            'lagos': self.parameterAsVectorLayer(parameters, self.INPUT_LAGOS, context),
            'rios_poligono': [c for c in self.parameterAsLayerList(parameters, self.INPUT_RIOS_POLIGONO, context)
                              if c is not None and c.type() == 0],
            'restricoes': restricoes,
            'largura_divisa': self.parameterAsDouble(parameters, self.LARGURA_DIVISA, context),
            'perc_divisa': self.parameterAsDouble(parameters, self.PERC_DIVISA, context),
            'modulo_automatico': self.parameterAsDouble(parameters, self.MODULO_FISCAL, context) <= 0,
            'coberturas': [c for c in self.parameterAsLayerList(parameters, self.INPUT_COBERTURAS, context)
                           if isinstance(c, QgsVectorLayer)],
            'reservas': [c for c in self.parameterAsLayerList(parameters, self.INPUT_RESERVAS, context)
                         if isinstance(c, QgsVectorLayer)],
            'servidoes': [c for c in self.parameterAsLayerList(parameters, self.INPUT_SERVIDOES, context)
                          if isinstance(c, QgsVectorLayer)],
            'sigef': [c for c in [camadaSigef] if c is not None],
            'caminho_relatorio': caminhoHtml,
            'identificacao': {rotulo: self.parameterAsString(parameters, chave, context).strip()
                              for chave, rotulo in self.IDENTIFICACAO},
        }

        feedback.pushInfo(self.tr('Executando a pré-análise completa (validação, sobreposições, APP e RL)...'))
        try:
            resultado = analise.executar(parametrosAnalise)
        except ValueError as erro:
            raise QgsProcessingException(str(erro))

        resumo = resultado['resumo']

        # Camadas de resultado em Pre-Analise/, carregadas no grupo Resultados da Pré-Análise
        if self.parameterAsBool(parameters, self.GERAR_CAMADAS, context):
            porNome = {self.CAMADAS_RESULTADO[c.name()]: c for c in resultado['camadas']
                       if c.name() in self.CAMADAS_RESULTADO}
            for nome in self.CAMADAS_RESULTADO.values():
                fixa = garantirCamadaFixa(nome, context.project())
                camada = porNome.get(nome)
                if fixa is not None:
                    # Camada fixa da RAIZ: apaga as feições anteriores (também quando o resultado é vazio)
                    total = substituirFeicoes(fixa, camada) if camada is not None else 0
                    if camada is None:
                        limparCamada(fixa)
                        fixa.triggerRepaint()
                    feedback.pushInfo(self.tr(f'{nome}: {total} feição(ões) gravada(s) na camada do projeto.'))
                elif camada is not None:
                    caminho = gravarECarregarResultado(context, camada, nome)
                    feedback.pushInfo(self.tr(f'Camada gravada: {caminho}'))
        rl = resumo['rl']
        feedback.pushInfo(self.tr(f"Área: {resumo['area_imovel_ha']:.4f} ha | "
                                  f"Módulos fiscais: {resumo['n_modulos']:.2f}"))
        feedback.pushInfo(self.tr(f"RL exigida ({rl['percentual']:g}%): {rl['exigida_ha']:.4f} ha | "
                                  f"Vegetação nativa: {rl['vegetacao_ha']:.4f} ha"))
        feedback.pushInfo(self.tr(f"Déficit com cômputo da APP: {rl['deficit_com_app_ha']:.4f} ha | "
                                  f"sem cômputo: {rl['deficit_sem_app_ha']:.4f} ha"))
        for aviso in resumo['app']['avisos']:
            feedback.pushWarning(aviso)
        for observacao in rl['observacoes']:
            feedback.pushWarning(observacao)
        feedback.pushInfo(self.tr(f'Relatório gravado em: {caminhoHtml}'))
        feedback.pushInfo(self.tr('GeoCAR - GeoOne'))

        return {
            self.OUTPUT_HTML: caminhoHtml,
            self.OUTPUT_RL_EXIGIDA: round(rl['exigida_ha'], 4),
            self.OUTPUT_VEGETACAO: round(rl['vegetacao_ha'], 4),
            self.OUTPUT_DEFICIT_COM_APP: round(rl['deficit_com_app_ha'], 4),
            self.OUTPUT_DEFICIT_SEM_APP: round(rl['deficit_sem_app_ha'], 4),
        }

    def flags(self):
        # A geração do PDF usa QTextDocument/QPrinter, que devem rodar na thread principal
        return super().flags() | Qgis.ProcessingAlgorithmFlag.NoThreading

    def name(self):
        return 'reservalegalrelatoriocar'

    def displayName(self):
        return self.tr('c. Pré-análise completa e relatório')

    def group(self):
        return self.tr('3. ✅ Pré-análise do CAR')

    def groupId(self):
        return 'preanalise'

    def tr(self, string):
        return QCoreApplication.translate('Processing', string)

    def createInstance(self):
        return ReservaLegalRelatorioCAR()

    def tags(self):
        return ('GeoOne,GeoCAR,GeoRural,ambiental,SiCAR,reserva legal,RL,déficit,compensação,'
                'relatório,pré-análise,Código Florestal,art. 67,art. 15').split(',')

    def icon(self):
        return QIcon(os.path.join(os.path.dirname(os.path.dirname(__file__)), 'images/qualidade.png'))

    def shortHelpString(self):
        txt = """Executa <b>de uma vez</b> a pré-análise completa do CAR e gera um <b>relatório em PDF ou HTML</b> (escolha pela extensão do arquivo de saída):
• validação geométrica da ATI e sobreposições (relevante, ajuste de divisa ou informativa/APA)
• consistência entre camadas (coberturas do solo, Reserva Legal e servidões — parâmetros avançados)
• APP hídrica integral, faixa da escadinha e teto do art. 61-B
• Reserva Legal
• comparação com as parcelas certificadas no SIGEF (camada Parcelas_SIGEF, da ferramenta 1c): parcela de terceiro dentro da ATI, várias matrículas, área sem certificação — parâmetro avançado

A <b>primeira página</b> do relatório é o resumo <b>O que corrigir</b>, montado a partir dos resultados: o que resolver antes de enviar, ajustes pequenos, o que recompor e conferir, restrições próximas para ficar atento e os <b>documentos a reunir</b> para cada pendência.

A opção <b>Gerar também as camadas de resultado</b> preenche as mesmas camadas das ferramentas <b>a</b>, <b>b</b> e <b>d</b>. Ela já vem marcada e grava nas camadas do grupo <b>Resultados da Pré-Análise</b>, no <b>Pre-Analise/PreAnalise.gpkg</b> do projeto (criado na primeira execução, se ainda não existir), apagando os resultados anteriores. O relatório fica na pasta <b>Pre-Analise/</b>. As entradas já vêm preenchidas com as camadas da RAIZ. <b>Consultas:</b> se os vizinhos com CAR, as parcelas do SIGEF ou as restrições oficiais ainda não foram consultados no projeto, a ferramenta faz as consultas sozinha antes da análise (só na primeira vez; depois reaproveita).

<b>Reserva Legal:</b>
• RL exigida pelo percentual do art. 12 (20%, 35% ou 80%)
• vegetação nativa existente na ATI
• déficit <b>com</b> e <b>sem</b> o cômputo da APP na RL (art. 15)
• alerta do <b>art. 67</b> para imóveis de até 4 módulos fiscais em 22/07/2008

As áreas calculadas ficam disponíveis como saídas numéricas, para uso em modelos do Processing.
""" + avisoLegal()
        return txt + rodapeAjuda()
