# -*- coding: utf-8 -*-
"""
Conferência antes de gerar os arquivos para o CAR (grupo 5).

Só avisa, não impede a exportação. Confere:
- ATI presente e com geometria válida (e sem vértices duplicados, muito próximos ou agulhas);
- Sede (nas RAIZ que têm a camada) com ponto e dentro da ATI;
- camadas da RAIZ em edição com alterações não salvas;
- pendências da última pré-análise (grupo 3) e se as camadas mudaram depois dela.
"""

import glob
import hashlib
import os
from datetime import datetime

from qgis.core import QgsCoordinateTransform, QgsGeometry, QgsMapLayer, QgsProject

from .processingCAR import PASTA_RESULTADOS, camadaFixa, camadaPadrao

IMPEDE = 'Resolver antes de enviar'
ATENCAO = 'Conferir'


def _nomes(itens, maximo=4):
    itens = sorted(set(itens))
    return ', '.join(itens[:maximo]) + (f' e mais {len(itens) - maximo}' if len(itens) > maximo else '')


def conferir(projeto=None):
    """Lista de (nível, texto) com o que conferir antes do envio."""
    from ..utilsExportacao import camadasParaExportar
    from .correcoes import srcDaAti
    from .validacao import vertices_duplicados, vertices_suspeitos

    projeto = projeto or QgsProject.instance()
    itens = []
    camadas = camadasParaExportar()

    # 1. ATI
    nomeAti = camadaPadrao('ati')
    ati = next((c for c in projeto.mapLayersByName(nomeAti or 'ATI') if c.type() == QgsMapLayer.VectorLayer), None)
    perimetro = None
    if ati is None or ati.featureCount() == 0:
        itens.append((IMPEDE, 'A camada da Área Total do Imóvel (ATI) está vazia ou não foi encontrada.'))
    else:
        geometrias = [f.geometry() for f in ati.getFeatures() if f.hasGeometry()]
        invalidas = sum(1 for g in geometrias if not g.isGeosValid())
        if invalidas:
            itens.append((IMPEDE, f'{ati.name()}: {invalidas} geometria(s) inválida(s). Use a 4b (Corrigir geometria '
                                  f'da ATI).'))
        src = srcDaAti(ati)
        paraUtm = QgsCoordinateTransform(ati.crs(), src, projeto)
        duplicados = suspeitos = 0
        for g in geometrias:
            utm = QgsGeometry(g)
            utm.transform(paraUtm)
            duplicados += len(vertices_duplicados(utm))
            suspeitos += len(vertices_suspeitos(utm))
        if duplicados:
            itens.append((IMPEDE, f'{ati.name()}: {duplicados} vértice(s) duplicado(s). Use a 4b (Corrigir geometria '
                                  f'da ATI).'))
        if suspeitos:
            itens.append((ATENCAO, f'{ati.name()}: {suspeitos} vértice(s) muito próximo(s) ou em agulha. Use a 4b '
                                   f'(Corrigir geometria da ATI).'))
        perimetro = QgsGeometry.unaryUnion([g.makeValid() for g in geometrias])

    # 2. Sede (só nas RAIZ que têm a camada)
    for sede in [c for c in camadas if c.name().lower() == 'sede']:
        if sede.featureCount() == 0:
            itens.append((ATENCAO, 'A camada Sede está vazia: informe a localização da sede do imóvel.'))
        elif perimetro is not None and not perimetro.isEmpty():
            paraAti = QgsCoordinateTransform(sede.crs(), ati.crs(), projeto)
            fora = 0
            for f in sede.getFeatures():
                g = QgsGeometry(f.geometry())
                g.transform(paraAti)
                fora += int(not perimetro.intersects(g))
            if fora:
                itens.append((IMPEDE, f'{fora} ponto(s) da Sede fora da ATI.'))

    # 3. Edições não salvas
    emEdicao = [c.name() for c in camadas if c.isEditable() and c.isModified()]
    if emEdicao:
        itens.append((ATENCAO, f'Camada(s) em edição com alterações não salvas: {_nomes(emEdicao)}. O arquivo sai com '
                               f'o que está na tela, mas o projeto não: salve (ou descarte) as edições antes.'))

    # 4. Pendências da última pré-análise
    def contar(nome, campo=None, valores=()):
        camada = camadaFixa(nome, projeto)
        if camada is None:
            return 0, []
        if campo is None:
            return camada.featureCount(), [str(f['tipo']) for f in camada.getFeatures()
                                           if camada.fields().indexFromName('tipo') >= 0]
        lista = [f for f in camada.getFeatures() if str(f[campo]) in valores]
        return len(lista), []

    # Os problemas de vértice e de validade da ATI já foram conferidos acima, na camada atual
    jaConferidos = {'Vértices duplicados', 'Vértices muito próximos', 'Agulha', 'Geometria inválida'}
    _n, tipos = contar('Problemas_Validacao')
    tipos = [x for x in tipos if x not in jaConferidos]
    n = len(tipos)
    if n:
        itens.append((IMPEDE, f'Pré-análise: {n} problema(s) geométrico(s) ({_nomes(tipos)}). Veja Problemas_Validacao '
                              f'e o grupo 4.'))
    n, _ = contar('Inconsistencias', 'gravidade', ('Erro',))
    if n:
        itens.append((IMPEDE, f'Pré-análise: {n} erro(s) de consistência entre camadas (fora da ATI ou sobreposição '
                              f'entre camadas). Veja Inconsistencias e o grupo 4.'))
    n, _ = contar('Sobreposicoes', 'classe', ('Sobreposição relevante',))
    if n:
        itens.append((ATENCAO, f'Pré-análise: {n} sobreposição(ões) relevante(s) com imóveis vizinhos ou áreas '
                               f'protegidas. O SICAR aceita, mas o cadastro fica com pendência na análise.'))
    n, _ = contar('Divergencias_SIGEF', 'tipo', ('Parcela de terceiro dentro da ATI',))
    if n:
        itens.append((ATENCAO, f'Pré-análise: a ATI avança sobre {n} parcela(s) certificada(s) de terceiros no SIGEF.'))

    # 5. Reserva Legal declarada?
    from .processingCAR import CANDIDATOS
    reservas = [c for c in camadas if c.name() in CANDIDATOS['reservas']]
    if reservas and not any(c.featureCount() for c in reservas):
        itens.append((ATENCAO, 'Nenhuma Reserva Legal declarada (camadas de RL vazias). Se o imóvel exige RL, a 4f '
                               '(Rascunho de Reserva Legal) desenha uma proposta.'))

    # 6. Pré-análise feita? Atualizada? (assinatura do conteúdo das camadas gravada pela 3c)
    pasta = os.path.join(projeto.homePath(), PASTA_RESULTADOS)
    relatorios = glob.glob(os.path.join(pasta, 'GeoCAR_Resultados_Pre-Analise_*.pdf')) + \
        glob.glob(os.path.join(pasta, 'GeoCAR_Resultados_Pre-Analise_*.html'))
    if not relatorios:
        itens.append((ATENCAO, 'A pré-análise (grupo 3) ainda não foi feita neste projeto: rode a 3c antes de enviar.'))
    else:
        gravada = lerAssinatura(projeto)
        if gravada is not None and gravada[1] != assinatura(camadas):
            itens.append((ATENCAO, f'As camadas foram alteradas depois da última pré-análise ({gravada[0]}): rode a '
                                   f'3c de novo para confirmar as pendências acima.'))
    return itens


def conferirAntesDeExportar(feedback, projeto=None):
    """Mostra a conferência no registro da ferramenta. Retorna o número de itens que impedem o envio."""
    try:
        itens = conferir(projeto)
    except Exception as erro:   # a conferência nunca deve impedir a exportação
        feedback.pushWarning(f'Conferência antes do envio não concluída: {erro}')
        return 0
    feedback.pushInfo('===== Conferência antes do envio ao CAR =====')
    if not itens:
        feedback.pushInfo('✔ Nenhum problema encontrado.')
        return 0
    for nivel in (IMPEDE, ATENCAO):
        for n, texto in itens:
            if n == nivel:
                feedback.pushWarning(f'⚠ {nivel}: {texto}')
    impedem = sum(1 for n, _t in itens if n == IMPEDE)
    feedback.pushWarning(f'{impedem} item(ns) a resolver antes de enviar e {len(itens) - impedem} a conferir. '
                         f'Os arquivos serão gerados assim mesmo.')
    feedback.pushInfo('')
    return impedem


TABELA_CONTROLE = 'Controle_Pre_Analise'


def assinatura(camadas):
    """Resumo (MD5) do conteúdo das camadas da RAIZ: geometrias e atributos, inclusive edições não salvas."""
    resumo = hashlib.md5()
    for camada in sorted(camadas, key=lambda c: c.name()):
        resumo.update(camada.name().encode('utf-8'))
        linhas = []
        for f in camada.getFeatures():
            g = f.geometry()
            linhas.append(hashlib.md5((bytes(g.asWkb()) if g and not g.isNull() else b'')
                                      + repr(f.attributes()).encode('utf-8')).hexdigest())
        resumo.update(''.join(sorted(linhas)).encode('ascii'))
    return resumo.hexdigest()


def _tabelaControle(projeto, criar=False):
    from qgis.PyQt.QtCore import QMetaType
    from qgis.core import QgsField, QgsVectorFileWriter, QgsVectorLayer
    from .processingCAR import ARQUIVO_FIXO
    caminho = os.path.join(projeto.homePath(), PASTA_RESULTADOS, ARQUIVO_FIXO)
    uri = f'{caminho}|layername={TABELA_CONTROLE}'
    camada = QgsVectorLayer(uri, TABELA_CONTROLE, 'ogr') if os.path.exists(caminho) else None
    if (camada is None or not camada.isValid()) and criar and os.path.exists(caminho):
        memoria = QgsVectorLayer('None', TABELA_CONTROLE, 'memory')
        memoria.dataProvider().addAttributes([QgsField('data_hora', QMetaType.Type.QString),
                                              QgsField('assinatura', QMetaType.Type.QString)])
        memoria.updateFields()
        opcoes = QgsVectorFileWriter.SaveVectorOptions()
        opcoes.driverName = 'GPKG'
        opcoes.layerName = TABELA_CONTROLE
        opcoes.actionOnExistingFile = QgsVectorFileWriter.ActionOnExistingFile.CreateOrOverwriteLayer
        QgsVectorFileWriter.writeAsVectorFormatV3(memoria, caminho, projeto.transformContext(), opcoes)
        camada = QgsVectorLayer(uri, TABELA_CONTROLE, 'ogr')
    return camada if camada is not None and camada.isValid() else None


def gravarAssinatura(projeto=None):
    """Chamada ao fim da pré-análise (3c): guarda a assinatura das camadas analisadas."""
    from qgis.core import QgsFeature
    from ..utilsExportacao import camadasParaExportar
    projeto = projeto or QgsProject.instance()
    tabela = _tabelaControle(projeto, criar=True)
    if tabela is None:
        return
    tabela.dataProvider().deleteFeatures([f.id() for f in tabela.getFeatures()])
    f = QgsFeature(tabela.fields())
    f.setAttribute('data_hora', datetime.now().strftime('%d/%m/%Y %H:%M'))
    f.setAttribute('assinatura', assinatura(camadasParaExportar()))
    tabela.dataProvider().addFeatures([f])


def lerAssinatura(projeto=None):
    """(data_hora, assinatura) da última pré-análise, ou None."""
    tabela = _tabelaControle(projeto or QgsProject.instance())
    f = next(tabela.getFeatures(), None) if tabela is not None else None
    return (f['data_hora'], f['assinatura']) if f is not None else None
