# -*- coding: utf-8 -*-
# Funções de apoio comuns aos algoritmos 8, 9 e 10 (pré-análise do CAR) do GeoCAR
# processingCAR.py

import os

from qgis.PyQt.QtCore import QMetaType, QTimer
from qgis.core import (QgsCategorizedSymbolRenderer, QgsCoordinateTransform, QgsFeature, QgsFeatureSink,
                       QgsFillSymbol, QgsGeometry, QgsLayerTreeGroup, QgsMapLayer, QgsProcessingContext,
                       QgsProcessingException, QgsProcessingLayerPostProcessorInterface,
                       QgsProcessingParameterFeatureSink, QgsProcessingUtils, QgsProject, QgsProviderRegistry,
                       QgsField, QgsMarkerSymbol, QgsRendererCategory, QgsSingleSymbolRenderer,
                       QgsVectorFileWriter, QgsVectorLayer, QgsWkbTypes)

from .utils import adicionar_feicao, area_ha, criar_camada_memoria

PASTA_IMAGENS = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), 'images')

OPCOES_RL = [
    '20% — Demais regiões / campos gerais na Amazônia Legal',
    '35% — Cerrado na Amazônia Legal',
    '80% — Floresta na Amazônia Legal',
]
VALORES_RL = [20.0, 35.0, 80.0]

# Resultados da pré-análise na estrutura RAIZ
PASTA_RESULTADOS = 'Pre-Analise'
GRUPO_RESULTADOS = 'Resultados da Pré-Análise'
GRUPO_RESULTADOS_FIXO = GRUPO_RESULTADOS

# Camadas fixas da estrutura RAIZ (vazias no modelo) ficam neste GeoPackage, na pasta Pre-Analise
# do projeto, fora do GeoCAR*.gpkg
ARQUIVO_FIXO = 'PreAnalise.gpkg'

# Nomes de camada usados nas 5 RAIZ, para preencher as entradas automaticamente
CANDIDATOS = {
    'ati': ['Area_Imovel', 'Area_Total_Imovel', 'ATI', 'ATP'],
    'vegetacao': ['Vegetacao_Nativa', 'Remanescente_Vegetacao_Nativa', 'AVN'],
    'consolidada': ['Area_Consolidada', 'AREA_CONSOLIDADA', 'AC'],
    'hidrografia': ['Rio_Menor_10m_30m', 'Curso_Agua_Natural_Perene_ou_Intermitente_Largura_inf_10m'],
    'rios_poligono': ['RIO_MENOR_10', 'RIO_ATE_10',
                      'Rio_10_50m_50m', 'Rio_50_200m_100m', 'Rio_200_600m_200m', 'Rio_Maior_600m_500m',
                      'RIO_10_A_50', 'RIO_50_A_200', 'RIO_200_A_600', 'RIO_ACIMA_600',
                      'Curso_Agua_Natural_Perene_ou_Intermitente_Largura_10_a_50m',
                      'Curso_Agua_Natural_Perene_ou_Intermitente_Largura_51_a_200m',
                      'Curso_Agua_Natural_Perene_ou_Intermitente_Largura_201_a_600m',
                      'Curso_Agua_Natural_Perene_ou_Intermitente_Largura_sup_600m'],
    'nascentes': ['Nascente_50m', 'NASCENTE', 'Nascente_ou_Olho_de_Agua_Perene'],
    'lagos': ['Lago_Lagoa_Natural_50m', 'LAGO_LAGOA_NATURAL', 'LAGOA_NATURAL', 'Lago_ou_Lagoa_Natural'],
    'restricoes': ['CAR_Vizinhos_SICAR'],
}
TIPOS_GEOMETRIA = {'ponto': QgsWkbTypes.PointGeometry, 'linha': QgsWkbTypes.LineGeometry,
                   'poligono': QgsWkbTypes.PolygonGeometry}


def camadasPadrao(chave, tipo='poligono'):
    """Nomes das camadas do projeto atual que correspondem à chave (na ordem de CANDIDATOS)."""
    projeto = QgsProject.instance()
    nomes = []
    for nome in CANDIDATOS[chave]:
        for camada in projeto.mapLayersByName(nome):
            if (camada.type() == QgsMapLayer.VectorLayer
                    and QgsWkbTypes.geometryType(camada.wkbType()) == TIPOS_GEOMETRIA[tipo]
                    and nome not in nomes):
                nomes.append(nome)
    return nomes


def camadaPadrao(chave, tipo='poligono'):
    """Primeira camada do projeto atual que corresponde à chave, ou None."""
    nomes = camadasPadrao(chave, tipo)
    return nomes[0] if nomes else None


# Estrutura fixa: grupo -> camadas; camada -> (geometria, campos)
_S, _D, _I, _DT = QMetaType.Type.QString, QMetaType.Type.Double, QMetaType.Type.Int, QMetaType.Type.QDateTime
CAMPOS_SICAR = [('cod_imovel', _S), ('status_imovel', _S), ('dat_criacao', _DT), ('data_atualizacao', _DT),
                ('area', _D), ('condicao', _S), ('uf', _S), ('municipio', _S), ('cod_municipio_ibge', _I),
                ('m_fiscal', _D), ('tipo_imovel', _S)]
CAMADAS_FIXAS = {
    'CAR_Vizinhos_SICAR': ('MultiPolygon', CAMPOS_SICAR),
    'Area_Consolidada': ('MultiPolygon', [('observacao', _S)]),
    '3a_problemas': ('Point', [('feicao', _S), ('tipo', _S), ('descricao', _S)]),
    '3a_sobreposicoes': ('MultiPolygon', [('camada', _S), ('identific', _S), ('classe', _S), ('area_ha', _D),
                                          ('perc', _D), ('larg_med', _D)]),
    '3b_APP_integral': ('MultiPolygon', [('area_ha', _D)]),
    '3b_faixa_escadinha': ('MultiPolygon', [('area_ha', _D)]),
    '3b_APP_recompor_consolidada': ('MultiPolygon', [('area_ha', _D)]),
    '3b_uso_consolidado_em_APP': ('MultiPolygon', [('area_ha', _D)]),
    '3b_APP_fora_consolidada': ('MultiPolygon', [('area_ha', _D)]),
}
GRUPOS_FIXOS = [
    ('Areas_Vizinhas', ['CAR_Vizinhos_SICAR']),
    ('Apoio à Pré-Análise', ['Area_Consolidada']),
    (GRUPO_RESULTADOS_FIXO, ['3a_problemas', '3a_sobreposicoes', '3b_APP_integral', '3b_faixa_escadinha',
                             '3b_APP_recompor_consolidada', '3b_uso_consolidado_em_APP', '3b_APP_fora_consolidada']),
]
ESTILOS_FIXOS = {
    'CAR_Vizinhos_SICAR': {'color': '0,0,0,0', 'outline_color': '255,255,0', 'outline_width': '0.6'},
    'Area_Consolidada': {'color': '230,200,120,110', 'outline_color': '180,140,60', 'outline_width': '0.4'},
    '3b_APP_integral': {'color': '0,160,255,90', 'outline_color': '0,100,200', 'outline_width': '0.4'},
    '3b_faixa_escadinha': {'color': '0,90,200,120', 'outline_color': '0,60,160', 'outline_width': '0.4'},
    '3b_APP_recompor_consolidada': {'color': '255,120,0,130', 'outline_color': '200,80,0', 'outline_width': '0.4'},
    '3b_uso_consolidado_em_APP': {'color': '255,230,0,120', 'outline_color': '200,170,0', 'outline_width': '0.4'},
    '3b_APP_fora_consolidada': {'color': '0,200,200,100', 'outline_color': '0,140,140', 'outline_width': '0.4'},
}


def projetoSalvo(projeto=None):
    """True se o projeto já foi salvo (tem pasta para o PreAnalise.gpkg)."""
    return bool((projeto or QgsProject.instance()).homePath())


def estiloFixo(camada):
    """Estilo padrão das camadas fixas."""
    nome = camada.name()
    if nome == '3a_problemas':
        camada.setRenderer(QgsSingleSymbolRenderer(QgsMarkerSymbol.createSimple(
            {'name': 'circle', 'color': '255,0,0', 'size': '3'})))
    elif nome in ESTILOS_FIXOS:
        camada.setRenderer(QgsSingleSymbolRenderer(QgsFillSymbol.createSimple(ESTILOS_FIXOS[nome])))
    aplicarEstilo(camada)


def criarEstruturaFixa(projeto):
    """
    Cria no projeto (salvo) o Pre-Analise/PreAnalise.gpkg com as camadas fixas que faltam e os grupos
    Areas_Vizinhas, Apoio à Pré-Análise e Resultados da Pré-Análise, abaixo dos grupos existentes.
    A Area_Consolidada só é criada se o projeto ainda não tiver camada de área consolidada.
    """
    if not projetoSalvo(projeto):
        return False
    pasta = os.path.join(projeto.homePath(), PASTA_RESULTADOS)
    os.makedirs(pasta, exist_ok=True)
    gpkg = os.path.join(pasta, ARQUIVO_FIXO)
    temConsolidada = any(projeto.mapLayersByName(n) for n in CANDIDATOS['consolidada'])
    raiz = projeto.layerTreeRoot()
    for nomeGrupo, nomes in GRUPOS_FIXOS:
        faltam = [n for n in nomes if camadaFixa(n, projeto) is None
                  and not (n == 'Area_Consolidada' and temConsolidada)]
        if not faltam:
            continue
        grupo = next((g for g in raiz.findGroups(True) if g.name().lower() == nomeGrupo.lower()), None)
        if grupo is None:
            indices = [i for i, filho in enumerate(raiz.children()) if isinstance(filho, QgsLayerTreeGroup)]
            grupo = raiz.insertGroup(indices[-1] + 1 if indices else 0, nomeGrupo)
        for nome in faltam:
            geometria, campos = CAMADAS_FIXAS[nome]
            memoria = QgsVectorLayer(f'{geometria}?crs=EPSG:4674', nome, 'memory')
            memoria.dataProvider().addAttributes([QgsField(n, tipo) for n, tipo in campos])
            memoria.updateFields()
            opcoes = QgsVectorFileWriter.SaveVectorOptions()
            opcoes.driverName = 'GPKG'
            opcoes.layerName = nome
            opcoes.fileEncoding = 'UTF-8'
            acao = QgsVectorFileWriter.ActionOnExistingFile
            opcoes.actionOnExistingFile = acao.CreateOrOverwriteLayer if os.path.exists(gpkg) else acao.CreateOrOverwriteFile
            resultado = QgsVectorFileWriter.writeAsVectorFormatV3(memoria, gpkg, projeto.transformContext(), opcoes)
            if resultado[0] != getattr(getattr(QgsVectorFileWriter, 'WriterError', QgsVectorFileWriter), 'NoError'):
                raise QgsProcessingException(f'Erro ao criar a camada {nome} em {gpkg}: {resultado[1]}')
            camada = QgsVectorLayer(f'{gpkg}|layername={nome}', nome, 'ogr')
            estiloFixo(camada)
            projeto.addMapLayer(camada, False)
            no = grupo.addLayer(camada)
            no.setCustomProperty('showFeatureCount', 1)
    return True


def garantirCamadaFixa(nome, projeto=None):
    """Camada fixa da RAIZ; num projeto salvo sem ela, cria a estrutura fixa antes. None se não salvo."""
    projeto = projeto or QgsProject.instance()
    camada = camadaFixa(nome, projeto)
    if camada is None and criarEstruturaFixa(projeto):
        camada = camadaFixa(nome, projeto)
    return camada


def camadaFixa(nome, projeto=None):
    """Camada fixa da RAIZ com esse nome, gravada no PreAnalise.gpkg do projeto, ou None."""
    projeto = projeto or QgsProject.instance()
    for camada in projeto.mapLayersByName(nome):
        if camada.type() == QgsMapLayer.VectorLayer and camada.providerType() == 'ogr':
            caminho = _arquivo(camada.source())
            if caminho and os.path.basename(caminho).lower() == ARQUIVO_FIXO.lower():
                return camada
    return None


def limparCamada(camada):
    """Apaga todas as feições da camada (direto no provedor, sem modo de edição)."""
    provedor = camada.dataProvider()
    if not provedor.truncate():
        provedor.deleteFeatures(list(camada.allFeatureIds()))


def substituirFeicoes(destino, origem):
    """
    Apaga as feições da camada fixa e grava as da origem: campos pelo nome, geometria
    reprojetada para o SRC do destino e convertida para multi quando necessário.
    Retorna o número de feições gravadas.
    """
    limparCamada(destino)
    transformacao = QgsCoordinateTransform(origem.crs(), destino.crs(), QgsProject.instance())
    campos = destino.fields()
    multi = QgsWkbTypes.isMultiType(destino.wkbType())
    novas = []
    for feicao in origem.getFeatures():
        nova = QgsFeature(campos)
        geometria = QgsGeometry(feicao.geometry())
        if not geometria.isNull():
            geometria.transform(transformacao)
            if multi:
                geometria.convertToMultiType()
        nova.setGeometry(geometria)
        for campo in origem.fields():
            indice = campos.indexFromName(campo.name())
            if indice >= 0 and campo.name().lower() != 'fid':
                nova.setAttribute(indice, feicao[campo.name()])
        novas.append(nova)
    if novas and not destino.dataProvider().addFeatures(novas)[0]:
        raise QgsProcessingException(f'Erro ao gravar na camada {destino.name()}.')
    destino.updateExtents()
    destino.triggerRepaint()
    return len(novas)


def adicionarSaida(algoritmo, chave, rotulo, nomeCamada, tipo):
    """
    Cria o parâmetro de saída. Com a camada fixa no projeto, a saída é opcional e vem desligada
    (o resultado já vai para a camada fixa); sem ela, grava por padrão em Pre-Analise/<nomeCamada>.gpkg.
    """
    if camadaFixa(nomeCamada) is not None or projetoSalvo():
        algoritmo.addParameter(QgsProcessingParameterFeatureSink(
            chave, algoritmo.tr(f'{rotulo} — cópia opcional (o resultado já vai para a camada {nomeCamada})'),
            type=tipo, createByDefault=False, optional=True))
    else:
        # Projeto ainda não salvo: sem pasta para o PreAnalise.gpkg, o resultado sai em camada temporária
        algoritmo.addParameter(QgsProcessingParameterFeatureSink(
            chave, algoritmo.tr(rotulo), type=tipo, createByDefault=True, optional=True))


def gravarResultado(algoritmo, parameters, chave, context, feedback, camadaMemoria, nomeCamada):
    """
    Grava o resultado na camada fixa da RAIZ (apagando as feições anteriores), se existir,
    e no parâmetro de saída, se ele foi pedido. Retorna o id da saída ou None.
    """
    fixa = garantirCamadaFixa(nomeCamada, context.project())
    if fixa is not None:
        total = substituirFeicoes(fixa, camadaMemoria)
        feedback.pushInfo(f'{nomeCamada}: {total} feição(ões) gravada(s) na camada do projeto '
                          f'(as anteriores foram apagadas).')
    if parameters.get(chave) is None:
        return None
    # Com camada fixa, a cópia não recebe o mesmo nome nem vai para o grupo, para não confundir
    return gravarCamadaNoSink(algoritmo, parameters, chave, context, camadaMemoria,
                              None if fixa is not None else nomeCamada)


# Referências aos pós-processadores (o Processing não guarda a referência Python)
_posProcessadores = {}


def destinoPadrao(nomeArquivo, pasta=PASTA_RESULTADOS):
    """Caminho padrão de saída na pasta do projeto, ou None se o projeto ainda não foi salvo."""
    pastaProjeto = QgsProject.instance().homePath()
    return os.path.join(pastaProjeto, pasta, nomeArquivo) if pastaProjeto else None


def _arquivo(fonte, provedor='ogr'):
    """Caminho absoluto normalizado do arquivo de uma fonte OGR, ou None."""
    caminho = QgsProviderRegistry.instance().decodeUri(provedor, fonte).get('path')
    return os.path.normcase(os.path.abspath(caminho)) if caminho else None


def prepararDestino(destino, projeto=None):
    """
    Antes de gravar em arquivo: cria a pasta e tira do projeto as camadas que leem esse arquivo
    (resultado anterior), para que possa ser sobrescrito também no Windows.
    """
    if not destino or destino.startswith(('memory:', 'postgres:', 'TEMPORARY_OUTPUT')):
        return
    caminho = _arquivo(destino[4:] if destino.startswith('ogr:') else destino)
    if not caminho or not os.path.splitext(caminho)[1]:
        return
    os.makedirs(os.path.dirname(caminho), exist_ok=True)
    projeto = projeto or QgsProject.instance()
    for camada in list(projeto.mapLayers().values()):
        if camada.providerType() == 'ogr' and _arquivo(camada.source()) == caminho:
            projeto.removeMapLayer(camada.id())


class PosProcessamentoGrupo(QgsProcessingLayerPostProcessorInterface):
    """Renomeia a camada de resultado e a coloca no grupo indicado."""

    def __init__(self, nomeCamada, nomeGrupo):
        super().__init__()
        self.nomeCamada = nomeCamada
        self.nomeGrupo = nomeGrupo

    def postProcessLayer(self, layer, context, feedback):
        if self.nomeCamada:
            layer.setName(self.nomeCamada)
        aplicarEstilo(layer)
        projeto = context.project() or QgsProject.instance()
        idCamada = layer.id()
        # Depois que o Processing termina de inserir a camada na árvore
        QTimer.singleShot(0, lambda: moverParaGrupo(projeto, idCamada, self.nomeGrupo))


def aplicarEstilo(camada):
    """Sobreposições coloridas por classe: relevante em vermelho, ajuste de divisa em laranja."""
    if camada.fields().indexFromName('classe') < 0 or camada.fields().indexFromName('larg_med') < 0:
        return
    categorias = [
        QgsRendererCategory('Sobreposição relevante', QgsFillSymbol.createSimple(
            {'color': '255,0,0,140', 'outline_color': '180,0,0', 'outline_width': '0.6'}), 'Sobreposição relevante'),
        QgsRendererCategory('Ajuste de divisa', QgsFillSymbol.createSimple(
            {'color': '255,165,0,160', 'outline_color': '255,140,0', 'outline_width': '0.4'}), 'Ajuste de divisa'),
    ]
    camada.setRenderer(QgsCategorizedSymbolRenderer('classe', categorias))


def definirPosProcessamento(context, destId, nomeCamada, nomeGrupo):
    """Associa o pós-processamento (nome e grupo) à camada que será carregada no fim do algoritmo."""
    if context.willLoadLayerOnCompletion(destId):
        pos = PosProcessamentoGrupo(nomeCamada, nomeGrupo)
        _posProcessadores[destId] = pos
        context.layerToLoadOnCompletionDetails(destId).setPostProcessor(pos)


def moverParaGrupo(projeto, idCamada, nomeGrupo):
    """
    Move a camada para o grupo (criado abaixo do último grupo da raiz, se não existir) e
    remove do grupo a camada temporária anterior com o mesmo nome (consulta ou análise refeita).
    """
    camada = projeto.mapLayer(idCamada)
    if camada is None:
        return
    raiz = projeto.layerTreeRoot()
    grupo = next((g for g in raiz.findGroups(True) if g.name().lower() == nomeGrupo.lower()), None)
    if grupo is None:
        indices = [i for i, filho in enumerate(raiz.children()) if isinstance(filho, QgsLayerTreeGroup)]
        grupo = raiz.insertGroup(indices[-1] + 1 if indices else 0, nomeGrupo)

    # Resultado temporário anterior com o mesmo nome (os gravados em arquivo já saem em prepararDestino)
    for no in list(grupo.findLayers()):
        anterior = no.layer()
        if (no.layerId() != idCamada and anterior is not None and anterior.name() == camada.name()
                and anterior.providerType() == 'memory'):
            projeto.removeMapLayer(no.layerId())

    no = raiz.findLayer(idCamada)
    if no is None:
        grupo.addLayer(camada)
    elif no.parent() is not grupo:
        grupo.addChildNode(no.clone())
        no.parent().removeChildNode(no)
    # Contagem de feições no painel de camadas, como nas camadas da RAIZ
    no = raiz.findLayer(idCamada)
    if no is not None:
        no.setCustomProperty('showFeatureCount', 1)


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


def gravarCamadaNoSink(algoritmo, parameters, chave, context, camadaMemoria, nomeCamada=None,
                       nomeGrupo=GRUPO_RESULTADOS):
    """
    Copia as feições de uma camada de memória para o sink de saída do algoritmo.
    Com nomeCamada, a camada carregada recebe esse nome e vai para o grupo nomeGrupo.
    """
    prepararDestino(algoritmo.parameterAsOutputLayer(parameters, chave, context), context.project())
    (sink, destId) = algoritmo.parameterAsSink(
        parameters, chave, context,
        camadaMemoria.fields(), camadaMemoria.wkbType(), camadaMemoria.crs()
    )
    if sink is None:
        raise QgsProcessingException(algoritmo.invalidSinkError(parameters, chave))
    for feicao in camadaMemoria.getFeatures():
        sink.addFeature(QgsFeature(feicao), QgsFeatureSink.FastInsert)
    if nomeCamada:
        definirPosProcessamento(context, destId, nomeCamada, nomeGrupo)
    return destId


def gravarECarregarResultado(context, camadaMemoria, nomeCamada, nomeGrupo=GRUPO_RESULTADOS):
    """
    Grava a camada de memória em Pre-Analise/<nomeCamada>.gpkg (ou em arquivo temporário, se o projeto
    não estiver salvo) e agenda o carregamento no grupo de resultados ao fim do algoritmo.
    Retorna o caminho gravado.
    """
    caminho = destinoPadrao(nomeCamada + '.gpkg') or QgsProcessingUtils.generateTempFilename(nomeCamada + '.gpkg')
    prepararDestino(caminho, context.project())
    opcoes = QgsVectorFileWriter.SaveVectorOptions()
    opcoes.driverName = 'GPKG'
    opcoes.fileEncoding = 'UTF-8'
    opcoes.layerName = nomeCamada
    resultado = QgsVectorFileWriter.writeAsVectorFormatV3(
        camadaMemoria, caminho, context.transformContext(), opcoes)
    semErro = getattr(getattr(QgsVectorFileWriter, 'WriterError', QgsVectorFileWriter), 'NoError')
    if resultado[0] != semErro:
        raise QgsProcessingException(f'Erro ao gravar {caminho}: {resultado[1]}')

    detalhes = QgsProcessingContext.LayerDetails(nomeCamada, context.project() or QgsProject.instance(), nomeCamada)
    pos = PosProcessamentoGrupo(nomeCamada, nomeGrupo)
    _posProcessadores[caminho] = pos
    detalhes.setPostProcessor(pos)
    context.addLayerToLoadOnCompletion(caminho, detalhes)
    return caminho


def camadaPoligonoArea(nome, src, geometria):
    """Cria camada de memória (MultiPolygon) com uma feição e o campo area_ha."""
    camada = criar_camada_memoria(nome, 'MultiPolygon', src, [('area_ha', 'double')])
    if geometria is not None and not geometria.isEmpty():
        adicionar_feicao(camada, geometria, [round(area_ha(geometria), 4)])
    return camada
