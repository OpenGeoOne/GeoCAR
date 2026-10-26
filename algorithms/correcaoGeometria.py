# -*- coding: utf-8 -*-

"""
/***************************************************************************
 GeoCAR
                                 A QGIS plugin
Cadastro Ambiental Rural (CAR)
                              -------------------
        begin                : 2026-10-26
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
# Ferramentas de correção (grupo 4): geometria da ATI, recorte pela ATI, sobreposições entre camadas
# e lascas sem cobertura
# correcaoGeometria.py

__author__ = 'Prof Cazaroli e Leandro França'
__date__ = '2026-10-26'
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
    QgsProcessingParameterBoolean,
    QgsProcessingParameterEnum,
    QgsProcessingParameterMultipleLayers,
    QgsProcessingParameterNumber,
    QgsProcessingParameterVectorLayer,
    QgsVectorLayer,
)

from .nucleoCAR.correcoes import (AREA_MINIMA_M2, Conversor, ajustarTipo, contarVertices, editar, finalizar,
                                  prioridadeCobertura, prioridadeReserva, srcDaAti, toleranciaNaCamada, uniaoAti,
                                  uniaoUtm)
from .nucleoCAR.processingCAR import avisoLegal, camadaPadrao, camadasPadrao, rodapeAjuda
from .nucleoCAR.registro_correcoes import entrada, registrar
from .nucleoCAR.validacao import (AGULHA, ANGULO_AGULHA_GRAUS, TOLERANCIA_PROXIMO_M, TOLERANCIA_VERTICE_M,
                                  vertices_suspeitos)

GRUPO = '4. 🔧 Correções'
GRUPO_ID = 'correcoes'
AVISO_EDICAO = ('<b>Segurança:</b> as correções ficam no <b>modo de edição</b> das camadas, sem salvar. Confira no mapa '
                'e salve ou descarte as edições (Ctrl+Z desfaz). Marque <b>Salvar as alterações</b> para gravar direto. '
                'Depois, rode a pré-análise de novo para confirmar que a pendência sumiu.<br><br>'
                'Cada correção fica registrada, e o relatório <b>Pre-Analise/GeoCAR_Correcoes_Pre-Analise_&lt;data&gt;.pdf</b> '
                'é refeito com o fundamento legal (Lei 12.651/2012 e Decreto 7.830/2012).')
LIMITE_REPETICOES = 10000   # trava de segurança na remoção vértice a vértice


class _BaseCorrecao(QgsProcessingAlgorithm):
    """Partes comuns às ferramentas de correção."""

    SALVAR = 'SALVAR'

    def parametroSalvar(self):
        self.addParameter(QgsProcessingParameterBoolean(
            self.SALVAR, self.tr('Salvar as alterações (desmarcado: ficam em edição para conferir)'),
            defaultValue=False))

    def camadaAti(self, parameters, context, chave='INPUT_ATI'):
        camada = self.parameterAsVectorLayer(parameters, chave, context)
        if camada is None or camada.featureCount() == 0:
            raise QgsProcessingException(self.tr('A camada ATI está vazia ou não foi informada.'))
        return camada

    def listaDeCamadas(self, parameters, chave, context, excluir=None):
        return [c for c in self.parameterAsLayerList(parameters, chave, context)
                if isinstance(c, QgsVectorLayer) and (excluir is None or c.id() != excluir.id())]

    def registrarCorrecoes(self, entradas, salvar, feedback, context):
        registrar(entradas, salvar, feedback, context.project())

    def avisarEdicao(self, camada, alterou, salvar, feedback):
        if alterou and not salvar:
            feedback.pushWarning(self.tr(f'{camada.name()} está em edição: confira e salve (ou descarte) as alterações.'))

    def flags(self):
        # Edita camadas do projeto: precisa da thread principal
        return super().flags() | Qgis.ProcessingAlgorithmFlag.NoThreading

    def group(self):
        return self.tr(GRUPO)

    def groupId(self):
        return GRUPO_ID

    def tr(self, string):
        return QCoreApplication.translate('Processing', string)

    def icon(self):
        return QIcon(os.path.join(os.path.dirname(os.path.dirname(__file__)), 'images/vetor.png'))


class CorrigirGeometriaAtiCAR(_BaseCorrecao):
    """Vértices duplicados, vértices muito próximos, agulhas, geometria inválida e partes sobrepostas da ATI."""

    INPUT_ATI = 'INPUT_ATI'
    TOLERANCIA = 'TOLERANCIA'
    PROXIMOS = 'PROXIMOS'
    ANGULO = 'ANGULO'
    OUTPUT_N = 'OUTPUT_N'

    def initAlgorithm(self, config=None):
        self.addParameter(QgsProcessingParameterVectorLayer(
            self.INPUT_ATI, self.tr('Área Total do Imóvel (ATI)'), [Qgis.ProcessingSourceType.VectorPolygon],
            defaultValue=camadaPadrao('ati') or 'ATI'))
        self.addParameter(QgsProcessingParameterNumber(
            self.TOLERANCIA, self.tr('Tolerância para vértices duplicados (m)'),
            type=Qgis.ProcessingNumberParameterType.Double, minValue=0.0, maxValue=1.0,
            defaultValue=TOLERANCIA_VERTICE_M))
        self.addParameter(QgsProcessingParameterNumber(
            self.PROXIMOS, self.tr('Distância mínima entre vértices seguidos (m)'),
            type=Qgis.ProcessingNumberParameterType.Double, minValue=0.0, maxValue=1.0,
            defaultValue=TOLERANCIA_PROXIMO_M))
        self.addParameter(QgsProcessingParameterNumber(
            self.ANGULO, self.tr('Ângulo máximo de uma agulha (graus)'),
            type=Qgis.ProcessingNumberParameterType.Double, minValue=0.0, maxValue=10.0,
            defaultValue=ANGULO_AGULHA_GRAUS))
        self.parametroSalvar()
        self.addOutput(QgsProcessingOutputNumber(self.OUTPUT_N, self.tr('Feições corrigidas')))

    def processAlgorithm(self, parameters, context, feedback):
        camada = self.camadaAti(parameters, context)
        tolerancia = toleranciaNaCamada(camada, self.parameterAsDouble(parameters, self.TOLERANCIA, context))
        proximos = self.parameterAsDouble(parameters, self.PROXIMOS, context)
        angulo = self.parameterAsDouble(parameters, self.ANGULO, context)
        src = srcDaAti(camada)
        conversor = Conversor(camada, src)
        salvar = self.parameterAsBool(parameters, self.SALVAR, context)
        ligou = editar(camada)
        corrigidas = set()
        entradas = []
        ferramenta = '4b'

        # 1. Vértices e validade, feição por feição
        for feicao in camada.getFeatures():
            if not feicao.hasGeometry():
                continue
            geometria = QgsGeometry(feicao.geometry())
            antes = contarVertices(geometria)
            geometria.removeDuplicateNodes(tolerancia)
            duplicados = antes - contarVertices(geometria)
            agulhas = proximosRemovidos = 0
            for _ in range(LIMITE_REPETICOES):
                suspeitos = vertices_suspeitos(conversor.paraUtm(geometria), proximos, angulo)
                if not suspeitos or not geometria.deleteVertex(suspeitos[0][0]):
                    break
                if suspeitos[0][1] == AGULHA:
                    agulhas += 1
                else:
                    proximosRemovidos += 1
            invalida = not geometria.isGeosValid()
            if invalida:
                motivos = '; '.join(e.what() for e in geometria.validateGeometry())
                geometria = geometria.makeValid()
            if not (duplicados or agulhas or proximosRemovidos or invalida):
                continue
            geometria = ajustarTipo(geometria, camada)
            if geometria.isEmpty() or not camada.changeGeometry(feicao.id(), geometria):
                feedback.reportError(self.tr(f'Feição {feicao.id()}: não foi possível corrigir.'), fatalError=False)
                continue
            corrigidas.add(feicao.id())
            for n, texto, tipo in ((duplicados, 'vértice(s) duplicado(s) removido(s)', 'vertice_duplicado'),
                                   (proximosRemovidos, f'vértice(s) a menos de {proximos * 100:g} cm do vizinho '
                                                       f'removido(s)', 'vertice_proximo'),
                                   (agulhas, 'agulha(s) removida(s)', 'agulha')):
                if n:
                    feedback.pushInfo(self.tr(f'Feição {feicao.id()}: {n} {texto}.'))
                    entradas.append(entrada(ferramenta, camada.name(), feicao.id(), tipo, texto, n, 'vértice(s)'))
            if invalida:
                feedback.pushInfo(self.tr(f'Feição {feicao.id()}: geometria inválida corrigida ({motivos}).'))
                entradas.append(entrada(ferramenta, camada.name(), feicao.id(), 'geometria_invalida',
                                        f'geometria inválida corrigida ({motivos})'))

        # 2. Partes da ATI sobrepostas: dissolve na feição de menor id
        mantidas = []   # [fid, geometria na camada, geometria no UTM]
        for feicao in sorted(camada.getFeatures(), key=lambda f: f.id()):
            if not feicao.hasGeometry():
                continue
            geometria = QgsGeometry(feicao.geometry())
            utm = conversor.paraUtm(geometria).makeValid()
            destino = next((m for m in mantidas if m[2].intersection(utm).area() >= AREA_MINIMA_M2), None)
            if destino is None:
                mantidas.append([feicao.id(), geometria, utm])
                continue
            area = destino[2].intersection(utm).area()
            destino[1] = destino[1].combine(geometria).makeValid()
            destino[2] = destino[2].combine(utm)
            camada.changeGeometry(destino[0], ajustarTipo(destino[1], camada))
            camada.deleteFeature(feicao.id())
            corrigidas.update((destino[0], feicao.id()))
            feedback.pushInfo(self.tr(f'Feições {destino[0]} e {feicao.id()} se sobrepunham ({area:.1f} m²): '
                                      f'unidas na feição {destino[0]}.'))
            entradas.append(entrada(ferramenta, camada.name(), f'{destino[0]} e {feicao.id()}', 'partes_ati',
                                    f'feições sobrepostas unidas na feição {destino[0]}', area, 'm²'))

        finalizar(camada, ligou, bool(corrigidas), salvar)
        self.avisarEdicao(camada, bool(corrigidas), salvar, feedback)
        self.registrarCorrecoes(entradas, salvar, feedback, context)
        if not corrigidas:
            feedback.pushInfo(self.tr('Nenhuma correção necessária.'))
        return {self.OUTPUT_N: len(corrigidas)}

    def name(self):
        return 'corrigirgeometriaaticar'

    def displayName(self):
        return self.tr('b. Corrigir geometria da ATI')

    def createInstance(self):
        return CorrigirGeometriaAtiCAR()

    def shortHelpString(self):
        txt = f"""Corrige os problemas geométricos da ATI apontados em <b>Problemas_Validacao</b>:
• <b>vértices duplicados</b> em sequência (até 1 mm): mantém um deles
• <b>vértices muito próximos</b> (menos de 5 cm um do outro): apaga o segundo
• <b>agulhas</b>: pontas finas, com ângulo menor que 1°, em que o limite vai e volta; apaga o vértice da ponta
• <b>geometria inválida</b> (autointerseção, anel cruzado), mantendo só as partes poligonais
• <b>partes da ATI sobrepostas</b>: une as feições numa só

Não muda o desenho da ATI além do necessário: apagar um vértice não move os demais.

{AVISO_EDICAO}
""" + avisoLegal()
        return txt + rodapeAjuda()


class RecortarPelaAtiCAR(_BaseCorrecao):
    """Recorta as camadas declaradas no limite da ATI."""

    INPUT_ATI = 'INPUT_ATI'
    INPUT_CAMADAS = 'INPUT_CAMADAS'
    OUTPUT_HA = 'OUTPUT_HA'

    def initAlgorithm(self, config=None):
        poligono = Qgis.ProcessingSourceType.VectorPolygon
        self.addParameter(QgsProcessingParameterVectorLayer(
            self.INPUT_ATI, self.tr('Área Total do Imóvel (ATI)'), [poligono], defaultValue=camadaPadrao('ati') or 'ATI'))
        padrao = []
        for chave in ('vegetacao', 'coberturas', 'reservas', 'servidoes'):
            padrao += [n for n in camadasPadrao(chave) if n not in padrao]
        self.addParameter(QgsProcessingParameterMultipleLayers(
            self.INPUT_CAMADAS, self.tr('Camadas a recortar (vegetação, consolidada, pousio, Reserva Legal, servidão...)'),
            layerType=poligono, defaultValue=padrao or None))
        self.parametroSalvar()
        self.addOutput(QgsProcessingOutputNumber(self.OUTPUT_HA, self.tr('Área removida fora da ATI (ha)')))

    def processAlgorithm(self, parameters, context, feedback):
        camadaAti = self.camadaAti(parameters, context)
        camadas = self.listaDeCamadas(parameters, self.INPUT_CAMADAS, context, camadaAti)
        src = srcDaAti(camadaAti)
        ati = uniaoAti(camadaAti, src)
        salvar = self.parameterAsBool(parameters, self.SALVAR, context)
        totalHa = 0.0
        entradas = []
        for camada in camadas:
            conversor = Conversor(camada, src)
            ligou = editar(camada)
            alterou = False
            for feicao in camada.getFeatures():
                if not feicao.hasGeometry():
                    continue
                geometria = conversor.paraUtm(feicao.geometry()).makeValid()
                fora = geometria.difference(ati)
                if fora.isEmpty() or fora.area() < AREA_MINIMA_M2:
                    continue
                dentro = geometria.intersection(ati)
                totalHa += fora.area() / 10000.0
                if dentro.isEmpty() or dentro.area() < AREA_MINIMA_M2:
                    camada.deleteFeature(feicao.id())
                    feedback.pushInfo(self.tr(f'{camada.name()}, feição {feicao.id()}: inteira fora da ATI '
                                              f'({fora.area() / 10000.0:.4f} ha) — excluída.'))
                    entradas.append(entrada('4c', camada.name(), feicao.id(), 'fora_ati',
                                            'feição inteira fora da ATI excluída', fora.area(), 'm²'))
                else:
                    camada.changeGeometry(feicao.id(), ajustarTipo(conversor.paraCamada(dentro), camada))
                    feedback.pushInfo(self.tr(f'{camada.name()}, feição {feicao.id()}: {fora.area() / 10000.0:.4f} ha '
                                              f'fora da ATI recortados.'))
                    entradas.append(entrada('4c', camada.name(), feicao.id(), 'fora_ati',
                                            'parte fora da ATI recortada', fora.area(), 'm²'))
                alterou = True
            finalizar(camada, ligou, alterou, salvar)
            self.avisarEdicao(camada, alterou, salvar, feedback)
        self.registrarCorrecoes(entradas, salvar, feedback, context)
        if totalHa == 0:
            feedback.pushInfo(self.tr('Nenhuma feição passa da ATI.'))
        return {self.OUTPUT_HA: round(totalHa, 4)}

    def name(self):
        return 'recortarpelaaticar'

    def displayName(self):
        return self.tr('c. Recortar camadas pela ATI')

    def createInstance(self):
        return RecortarPelaAtiCAR()

    def shortHelpString(self):
        txt = f"""Recorta no limite da ATI as camadas declaradas (vegetação nativa, área consolidada, pousio, Reserva Legal, servidão...), corrigindo a inconsistência <b>Fora da ATI</b>.

A parte de fora é removida; a feição que estiver inteira fora da ATI é excluída. A lista de camadas já vem preenchida com as camadas da RAIZ — confira, pois os nomes variam entre os estados.

{AVISO_EDICAO}
""" + avisoLegal()
        return txt + rodapeAjuda()


class ResolverSobreposicoesCAR(_BaseCorrecao):
    """Tira as sobreposições entre coberturas do solo, entre Reservas Legais e da servidão sobre a RL."""

    INPUT_ATI = 'INPUT_ATI'
    INPUT_COBERTURAS = 'INPUT_COBERTURAS'
    PRIORIDADE = 'PRIORIDADE'
    INPUT_RESERVAS = 'INPUT_RESERVAS'
    INPUT_SERVIDOES = 'INPUT_SERVIDOES'
    OUTPUT_HA = 'OUTPUT_HA'

    PRIORIDADES = ['Vegetação nativa > área consolidada > pousio',
                   'Área consolidada > vegetação nativa > pousio']

    def initAlgorithm(self, config=None):
        poligono = Qgis.ProcessingSourceType.VectorPolygon
        self.addParameter(QgsProcessingParameterVectorLayer(
            self.INPUT_ATI, self.tr('Área Total do Imóvel (ATI)'), [poligono], defaultValue=camadaPadrao('ati') or 'ATI'))
        padrao = []
        for chave in ('vegetacao', 'coberturas'):
            padrao += [n for n in camadasPadrao(chave) if n not in padrao]
        self.addParameter(QgsProcessingParameterMultipleLayers(
            self.INPUT_COBERTURAS, self.tr('Camadas de cobertura do solo'),
            layerType=poligono, optional=True, defaultValue=padrao or None))
        self.addParameter(QgsProcessingParameterEnum(
            self.PRIORIDADE, self.tr('Na sobreposição entre coberturas, prevalece'),
            options=[self.tr(p) for p in self.PRIORIDADES], defaultValue=0))
        self.addParameter(QgsProcessingParameterMultipleLayers(
            self.INPUT_RESERVAS, self.tr('Reserva Legal (proposta, averbada, aprovada...)'),
            layerType=poligono, optional=True, defaultValue=camadasPadrao('reservas') or None))
        self.addParameter(QgsProcessingParameterMultipleLayers(
            self.INPUT_SERVIDOES, self.tr('Servidão administrativa (sai de dentro da Reserva Legal)'),
            layerType=poligono, optional=True, defaultValue=camadasPadrao('servidoes') or None))
        self.parametroSalvar()
        self.addOutput(QgsProcessingOutputNumber(self.OUTPUT_HA, self.tr('Área sobreposta removida (ha)')))

    def _subtrairEmOrdem(self, camadas, src, ocupado, motivo, salvar, feedback, entradas, tipo, servidao=None):
        """
        Em cada camada (na ordem de prioridade), tira das feições o que já está ocupado pelas anteriores
        (e pela geometria inicial). Retorna a área removida, em m².
        """
        removido = 0.0
        for camada in camadas:
            conversor = Conversor(camada, src)
            originais, mudancas, feicoes = [], [], {}
            for feicao in camada.getFeatures():
                if not feicao.hasGeometry():
                    continue
                geometria = conversor.paraUtm(feicao.geometry()).makeValid()
                originais.append(geometria)
                feicoes[feicao.id()] = geometria
                if ocupado.isEmpty() or not geometria.boundingBox().intersects(ocupado.boundingBox()):
                    continue
                comum = geometria.intersection(ocupado)
                if comum.isEmpty() or comum.area() < AREA_MINIMA_M2:
                    continue
                mudancas.append((feicao.id(), geometria.difference(ocupado), comum.area()))
            if mudancas:
                ligou = editar(camada)
                for fid, resto, area in mudancas:
                    removido += area
                    self._anotar(entradas, camada, fid, area, tipo, servidao, conversor, feicoes)
                    if resto.isEmpty() or resto.area() < AREA_MINIMA_M2:
                        camada.deleteFeature(fid)
                        feedback.pushInfo(self.tr(f'{camada.name()}, feição {fid}: inteira sobre {motivo} — excluída.'))
                    else:
                        camada.changeGeometry(fid, ajustarTipo(conversor.paraCamada(resto), camada))
                        feedback.pushInfo(self.tr(f'{camada.name()}, feição {fid}: {area:.1f} m² sobre {motivo} '
                                                  f'removidos.'))
                finalizar(camada, ligou, True, salvar)
                self.avisarEdicao(camada, True, salvar, feedback)
            if originais:
                ocupado = QgsGeometry.unaryUnion([ocupado] + originais) if not ocupado.isEmpty() \
                    else QgsGeometry.unaryUnion(originais)
        return removido

    @staticmethod
    def _anotar(entradas, camada, fid, area, tipo, servidao, _conversor, feicoes):
        """Registra a correção; na RL, separa a parte sobre servidão da parte sobre outra RL."""
        if tipo == 'sobreposicao_rl' and servidao is not None and not servidao.isEmpty():
            sobreServidao = feicoes[fid].intersection(servidao)
            areaServidao = 0.0 if sobreServidao.isEmpty() else sobreServidao.area()
            if areaServidao >= AREA_MINIMA_M2:
                entradas.append(entrada('4d', camada.name(), fid, 'servidao_rl',
                                        'parte sobre servidão administrativa retirada da RL', areaServidao, 'm²'))
            area -= areaServidao
            if area < AREA_MINIMA_M2:
                return
            detalhe = 'parte sobre RL de maior prioridade retirada'
        else:
            detalhe = 'parte sobre cobertura de maior prioridade retirada'
        entradas.append(entrada('4d', camada.name(), fid, tipo, detalhe, area, 'm²'))

    def processAlgorithm(self, parameters, context, feedback):
        camadaAti = self.camadaAti(parameters, context)
        coberturas = self.listaDeCamadas(parameters, self.INPUT_COBERTURAS, context, camadaAti)
        reservas = self.listaDeCamadas(parameters, self.INPUT_RESERVAS, context, camadaAti)
        servidoes = self.listaDeCamadas(parameters, self.INPUT_SERVIDOES, context, camadaAti)
        if not coberturas and not reservas:
            raise QgsProcessingException(self.tr('Informe as camadas de cobertura do solo ou de Reserva Legal.'))
        consolidadaPrimeiro = self.parameterAsEnum(parameters, self.PRIORIDADE, context) == 1
        salvar = self.parameterAsBool(parameters, self.SALVAR, context)
        src = srcDaAti(camadaAti)

        # Ordem estável: em empate, vale a ordem da lista
        coberturas = sorted(coberturas, key=lambda c: prioridadeCobertura(c.name(), consolidadaPrimeiro))
        reservas = sorted(reservas, key=lambda c: prioridadeReserva(c.name()))
        if coberturas:
            feedback.pushInfo(self.tr('Coberturas, da que prevalece para a que cede: '
                                      + ' > '.join(c.name() for c in coberturas)))
        if reservas:
            feedback.pushInfo(self.tr('Reservas Legais, da que prevalece para a que cede: '
                                      + ' > '.join(c.name() for c in reservas)))

        entradas = []
        servidao = uniaoUtm(servidoes, src)
        removido = self._subtrairEmOrdem(coberturas, src, QgsGeometry(), 'cobertura de maior prioridade',
                                         salvar, feedback, entradas, 'sobreposicao_cobertura')
        removido += self._subtrairEmOrdem(reservas, src, QgsGeometry(servidao),
                                          'servidão administrativa ou Reserva Legal de maior prioridade',
                                          salvar, feedback, entradas, 'sobreposicao_rl', servidao)
        self.registrarCorrecoes(entradas, salvar, feedback, context)
        if not removido:
            feedback.pushInfo(self.tr('Nenhuma sobreposição entre as camadas.'))
        return {self.OUTPUT_HA: round(removido / 10000.0, 4)}

    def name(self):
        return 'resolversobreposicoescar'

    def displayName(self):
        return self.tr('d. Resolver sobreposições entre camadas')

    def createInstance(self):
        return ResolverSobreposicoesCAR()

    def shortHelpString(self):
        txt = f"""Tira as sobreposições entre as camadas declaradas apontadas em <b>Inconsistencias</b>, que o SICAR não aceita:
• <b>entre coberturas do solo</b>: a mesma área como vegetação nativa e área consolidada, por exemplo. Prevalece a vegetação nativa (situação atual), depois a área consolidada e o pousio; a ordem pode ser invertida no parâmetro
• <b>servidão administrativa sobre Reserva Legal</b>: a RL não pode ficar sobre a servidão, então a servidão é recortada da RL
• <b>entre Reservas Legais</b>: prevalece a averbada, depois a aprovada; a proposta cede

A camada que prevalece não muda; a outra perde só a parte sobreposta.

{AVISO_EDICAO}
""" + avisoLegal()
        return txt + rodapeAjuda()


class PreencherLascasCAR(_BaseCorrecao):
    """Junta as lascas da ATI sem cobertura declarada à cobertura vizinha."""

    INPUT_ATI = 'INPUT_ATI'
    INPUT_COBERTURAS = 'INPUT_COBERTURAS'
    INPUT_SERVIDOES = 'INPUT_SERVIDOES'
    AREA_MAXIMA = 'AREA_MAXIMA'
    OUTPUT_HA = 'OUTPUT_HA'

    def initAlgorithm(self, config=None):
        poligono = Qgis.ProcessingSourceType.VectorPolygon
        self.addParameter(QgsProcessingParameterVectorLayer(
            self.INPUT_ATI, self.tr('Área Total do Imóvel (ATI)'), [poligono], defaultValue=camadaPadrao('ati') or 'ATI'))
        padrao = []
        for chave in ('vegetacao', 'coberturas'):
            padrao += [n for n in camadasPadrao(chave) if n not in padrao]
        self.addParameter(QgsProcessingParameterMultipleLayers(
            self.INPUT_COBERTURAS, self.tr('Camadas de cobertura do solo (recebem as lascas)'),
            layerType=poligono, defaultValue=padrao or None))
        self.addParameter(QgsProcessingParameterMultipleLayers(
            self.INPUT_SERVIDOES, self.tr('Servidão administrativa (área ocupada, não recebe lascas)'),
            layerType=poligono, optional=True, defaultValue=camadasPadrao('servidoes') or None))
        self.addParameter(QgsProcessingParameterNumber(
            self.AREA_MAXIMA, self.tr('Área máxima de cada lasca a preencher (m²)'),
            type=Qgis.ProcessingNumberParameterType.Double, minValue=1.0, defaultValue=500.0))
        self.parametroSalvar()
        self.addOutput(QgsProcessingOutputNumber(self.OUTPUT_HA, self.tr('Área preenchida (ha)')))

    def processAlgorithm(self, parameters, context, feedback):
        camadaAti = self.camadaAti(parameters, context)
        coberturas = self.listaDeCamadas(parameters, self.INPUT_COBERTURAS, context, camadaAti)
        servidoes = self.listaDeCamadas(parameters, self.INPUT_SERVIDOES, context)
        if not coberturas:
            raise QgsProcessingException(self.tr('Informe ao menos uma camada de cobertura do solo.'))
        areaMaxima = self.parameterAsDouble(parameters, self.AREA_MAXIMA, context)
        src = srcDaAti(camadaAti)
        ati = uniaoAti(camadaAti, src)

        # Feições de cobertura no UTM: [camada, id, geometria]
        feicoes, ocupado = [], []
        for camada in coberturas:
            conversor = Conversor(camada, src)
            for f in camada.getFeatures():
                if f.hasGeometry():
                    g = conversor.paraUtm(f.geometry()).makeValid()
                    feicoes.append([camada, f.id(), g])
                    ocupado.append(g)
        servidao = uniaoUtm(servidoes, src)
        if not servidao.isEmpty():
            ocupado.append(servidao)
        semCobertura = ati.difference(QgsGeometry.unaryUnion(ocupado)) if ocupado else QgsGeometry(ati)
        lascas = [p for p in semCobertura.asGeometryCollection()
                  if not p.isEmpty() and p.area() >= AREA_MINIMA_M2] if not semCobertura.isEmpty() else []

        preenchidaHa, grandes, alteradas, entradas = 0.0, [], {}, []
        for lasca in lascas:
            if lasca.area() > areaMaxima:
                grandes.append(lasca.area())
                continue
            # Vizinha com a maior divisa em comum (área de contato com uma borda de 5 cm em volta da lasca)
            borda = lasca.buffer(0.05, 4)
            melhor, maior = None, 0.0
            for item in feicoes:
                comum = item[2].intersection(borda)
                contato = comum.area() if not comum.isEmpty() else 0.0
                if contato > maior:
                    melhor, maior = item, contato
            if melhor is None:
                grandes.append(lasca.area())
                continue
            melhor[2] = melhor[2].combine(lasca).makeValid()
            alteradas[(melhor[0].id(), melhor[1])] = melhor
            preenchidaHa += lasca.area() / 10000.0
            feedback.pushInfo(self.tr(f'Lasca de {lasca.area():.1f} m² juntada a {melhor[0].name()} (feição {melhor[1]}).'))
            entradas.append(entrada('4e', melhor[0].name(), melhor[1], 'lasca', 'lasca sem cobertura juntada à feição',
                                    lasca.area(), 'm²'))

        salvar = self.parameterAsBool(parameters, self.SALVAR, context)
        porCamada = {}
        for camada, fid, geometria in alteradas.values():
            porCamada.setdefault(camada.id(), [camada, []])[1].append((fid, geometria))
        for camada, lista in porCamada.values():
            conversor = Conversor(camada, src)
            ligou = editar(camada)
            for fid, geometria in lista:
                camada.changeGeometry(fid, ajustarTipo(conversor.paraCamada(geometria), camada))
            finalizar(camada, ligou, True, salvar)
            self.avisarEdicao(camada, True, salvar, feedback)
        self.registrarCorrecoes(entradas, salvar, feedback, context)
        if grandes:
            feedback.pushWarning(self.tr(
                f'{len(grandes)} área(s) sem cobertura maiores que {areaMaxima:g} m² ({sum(grandes) / 10000.0:.4f} ha) '
                f'não foram preenchidas: classifique-as manualmente.'))
        if not lascas:
            feedback.pushInfo(self.tr('Nenhuma área sem cobertura dentro da ATI.'))
        return {self.OUTPUT_HA: round(preenchidaHa, 4)}

    def name(self):
        return 'preencherlascascar'

    def displayName(self):
        return self.tr('e. Preencher lascas sem cobertura')

    def createInstance(self):
        return PreencherLascasCAR()

    def shortHelpString(self):
        txt = f"""Junta à cobertura vizinha as <b>lascas</b> da ATI sem nenhuma cobertura do solo declarada — o aviso <b>Área sem cobertura do solo declarada</b> da pré-análise.

Cada lasca até a área máxima (padrão de 500 m²) vai para a feição de cobertura com a maior divisa em comum com ela. Áreas maiores não são preenchidas: são uso de verdade e precisam ser classificadas manualmente. A servidão administrativa conta como área ocupada.

Rode depois da <b>d. Resolver sobreposições entre camadas</b>, para as lascas serem medidas já sem sobreposição.

{AVISO_EDICAO}
""" + avisoLegal()
        return txt + rodapeAjuda()
