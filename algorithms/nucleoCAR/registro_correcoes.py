# -*- coding: utf-8 -*-
"""
Registro das correções do grupo 4 e relatório em PDF com a fundamentação legal.

Cada ferramenta de correção grava o que fez na tabela Registro_Correcoes do Pre-Analise/PreAnalise.gpkg e
o relatório Pre-Analise/GeoCAR_Correcoes_<data>.pdf é refeito com todo o histórico, agrupado por tipo de
correção, com o fundamento legal de cada uma.

Legislação: Lei nº 12.651, de 25 de maio de 2012 (Código Florestal), e Decreto nº 7.830, de 17 de outubro de
2012 (SICAR e CAR).
"""

import os
from datetime import date, datetime
from html import escape

from qgis.PyQt.QtCore import QMetaType
from uuid import uuid4

from qgis.core import (Qgis, QgsFeature, QgsField, QgsMessageLog, QgsProject, QgsVectorFileWriter,
                       QgsVectorLayer)

from .processingCAR import ARQUIVO_FIXO, PASTA_RESULTADOS, projetoSalvo

TABELA = 'Registro_Correcoes'
CAMPOS = [('data_hora', QMetaType.Type.QString), ('ferramenta', QMetaType.Type.QString),
          ('camada', QMetaType.Type.QString), ('feicao', QMetaType.Type.QString),
          ('tipo', QMetaType.Type.QString), ('detalhe', QMetaType.Type.QString),
          ('quantidade', QMetaType.Type.Double), ('unidade', QMetaType.Type.QString),
          ('gravacao', QMetaType.Type.QString), ('lote', QMetaType.Type.QString)]

LEI = "Lei nº 12.651/2012"
DECRETO = "Decreto nº 7.830/2012"

# Art. 29, § 1º, III da Lei e art. 5º do Decreto: base de toda a parte geométrica do CAR
_BASE_PLANTA = (f"{LEI}, art. 29, § 1º, III: a inscrição no CAR exige a identificação do imóvel por meio de planta e "
                f"memorial descritivo, com as coordenadas geográficas do perímetro, informando a localização dos "
                f"remanescentes de vegetação nativa, das Áreas de Preservação Permanente, das Áreas de Uso Restrito, "
                f"das áreas consolidadas e, se existente, da Reserva Legal. {DECRETO}, art. 5º: o CAR contempla a "
                f"planta georreferenciada do perímetro do imóvel, com a localização dessas áreas.")

# Tipo: (seção, o que foi feito, fundamento legal)
TIPOS = {
    'vertice_duplicado': (
        "Geometria da ATI",
        "Vértices duplicados em sequência foram removidos, mantendo um deles.",
        _BASE_PLANTA),
    'vertice_proximo': (
        "Geometria da ATI",
        "Vértices a menos de 5 cm do vértice vizinho foram removidos (ruído de digitalização).",
        _BASE_PLANTA),
    'agulha': (
        "Geometria da ATI",
        "Agulhas (pontas com ângulo menor que 1°, em que o limite vai e volta) tiveram o vértice da ponta removido.",
        _BASE_PLANTA),
    'geometria_invalida': (
        "Geometria da ATI",
        "Geometria inválida (autointerseção, anel cruzado) foi corrigida, mantendo as partes poligonais.",
        _BASE_PLANTA),
    'partes_ati': (
        "Geometria da ATI",
        "Feições da ATI sobrepostas foram unidas numa só, para a mesma área não ser contada duas vezes.",
        _BASE_PLANTA),
    'fora_ati': (
        "Camadas fora da ATI",
        "As partes das camadas declaradas que passavam do perímetro do imóvel foram recortadas; feições inteiramente "
        "fora da ATI foram excluídas.",
        _BASE_PLANTA + " As áreas declaradas no CAR são áreas do próprio imóvel, contidas no seu perímetro."),
    'sobreposicao_cobertura': (
        "Sobreposição entre coberturas do solo",
        "A mesma área estava declarada em duas coberturas do solo. Ficou na cobertura de maior prioridade "
        "(padrão: vegetação nativa > área consolidada > pousio) e saiu da outra. A ordem de prioridade é critério "
        "técnico, ajustável na ferramenta: deve refletir a situação real do terreno.",
        f"{LEI}, art. 3º, IV (área rural consolidada: ocupação antrópica preexistente a 22/07/2008) e XXIV (pousio: "
        f"interrupção temporária de atividades por no máximo 5 anos); {DECRETO}, art. 2º, IV (remanescente de "
        f"vegetação nativa). São classes distintas: cada porção do imóvel tem uma só cobertura declarada."),
    'servidao_rl': (
        "Servidão administrativa sobre Reserva Legal",
        "A parte da Reserva Legal sobre área de servidão administrativa foi retirada da RL.",
        f"{LEI}, art. 12, §§ 6º a 8º: não se exige Reserva Legal nas áreas de abastecimento público de água e "
        f"tratamento de esgoto, de geração e transmissão de energia elétrica e de rodovias e ferrovias. A área "
        f"ocupada pela servidão não compõe a RL."),
    'sobreposicao_rl': (
        "Sobreposição entre Reservas Legais",
        "A mesma área estava em duas camadas de Reserva Legal. Prevaleceu a averbada, depois a aprovada; a "
        "proposta cedeu a parte sobreposta.",
        f"{LEI}, art. 18: a RL é registrada no CAR, vedada a alteração de sua destinação; art. 30: a RL averbada na "
        f"matrícula, com perímetro e localização identificados, dispensa nova informação ao órgão ambiental. A RL "
        f"já averbada ou aprovada não é redesenhada pela proposta."),
    'lasca': (
        "Lascas sem cobertura do solo",
        "Pequenas áreas da ATI sem nenhuma cobertura declarada (lascas de digitalização) foram juntadas à cobertura "
        "vizinha com a maior divisa em comum. Áreas maiores que o limite da ferramenta não foram preenchidas.",
        _BASE_PLANTA + " Toda a área do imóvel deve estar classificada."),
    'rascunho_rl': (
        "Rascunho de Reserva Legal",
        "Foi desenhado um rascunho da Reserva Legal que falta, sobre vegetação nativa, contínuo com a APP e com a "
        "RL já declarada (camada RL_Rascunho). É ponto de partida: a localização é escolha do proprietário, "
        "aprovada pelo órgão ambiental.",
        f"{LEI}, art. 12 (percentuais mínimos de RL); art. 14 (a localização considera o plano de bacia "
        f"hidrográfica, o Zoneamento Ecológico-Econômico, a formação de corredores ecológicos com outra RL, APP, "
        f"Unidade de Conservação ou outra área protegida, as áreas de maior importância para a biodiversidade e as "
        f"de maior fragilidade ambiental; § 1º: o órgão estadual aprova a localização após a inclusão no CAR); "
        f"art. 15 (cômputo da APP na RL, desde que não implique conversão de novas áreas para uso alternativo do "
        f"solo, a APP esteja conservada ou em recuperação e o imóvel esteja inscrito no CAR)."),
    'deficit_rl': (
        "Rascunho de Reserva Legal",
        "Parte da Reserva Legal exigida não tem vegetação nativa disponível no imóvel.",
        f"{LEI}, art. 66: a regularização do déficit se faz por recomposição, regeneração natural ou compensação; "
        f"art. 67: no imóvel com até 4 módulos fiscais em 22/07/2008, a RL é constituída pela vegetação nativa "
        f"existente naquela data, vedadas novas conversões para uso alternativo do solo."),
}
ORDEM_SECOES = []
for _tipo, (_secao, _f, _l) in TIPOS.items():
    if _secao not in ORDEM_SECOES:
        ORDEM_SECOES.append(_secao)

# Registro em memória quando o projeto não está salvo (não há onde gravar)
_registroTemporario = []
# Camadas com correções em edição: id da camada -> {'camada', 'lotes', 'slots'}
_vigiadas = {}

GRAVACAO_SALVA = 'salva'
GRAVACAO_EDICAO = 'em edição (conferir e salvar)'


def entrada(ferramenta, camada, feicao, tipo, detalhe, quantidade=None, unidade=''):
    return {'ferramenta': ferramenta, 'camada': camada, 'feicao': str(feicao), 'tipo': tipo, 'detalhe': detalhe,
            'quantidade': quantidade, 'unidade': unidade}


def _caminhoGpkg(projeto):
    return os.path.join(projeto.homePath(), PASTA_RESULTADOS, ARQUIVO_FIXO)


def _caminhoPdf(projeto):
    return os.path.join(projeto.homePath(), PASTA_RESULTADOS,
                        f'GeoCAR_Correcoes_Pre-Analise_{date.today().isoformat()}.pdf')


def _tabela(projeto, criar=False):
    caminho = _caminhoGpkg(projeto)
    camada = QgsVectorLayer(f'{caminho}|layername={TABELA}', TABELA, 'ogr') if os.path.exists(caminho) else None
    if (camada is None or not camada.isValid()) and criar:
        memoria = QgsVectorLayer('None', TABELA, 'memory')
        memoria.dataProvider().addAttributes([QgsField(n, t) for n, t in CAMPOS])
        memoria.updateFields()
        os.makedirs(os.path.dirname(caminho), exist_ok=True)
        opcoes = QgsVectorFileWriter.SaveVectorOptions()
        opcoes.driverName = 'GPKG'
        opcoes.layerName = TABELA
        opcoes.fileEncoding = 'UTF-8'
        opcoes.actionOnExistingFile = (QgsVectorFileWriter.ActionOnExistingFile.CreateOrOverwriteLayer
                                       if os.path.exists(caminho)
                                       else QgsVectorFileWriter.ActionOnExistingFile.CreateOrOverwriteFile)
        QgsVectorFileWriter.writeAsVectorFormatV3(memoria, caminho, projeto.transformContext(), opcoes)
        camada = QgsVectorLayer(f'{caminho}|layername={TABELA}', TABELA, 'ogr')
    if camada is None or not camada.isValid():
        return None
    # Tabelas criadas antes do campo 'lote'
    faltam = [QgsField(n, t) for n, t in CAMPOS if camada.fields().indexFromName(n) < 0]
    if faltam:
        camada.dataProvider().addAttributes(faltam)
        camada.updateFields()
    return camada


def registrar(entradas, salvo, feedback, projeto=None, contexto=None):
    """
    Grava as entradas no registro e refaz o relatório das correções. 'salvo': se as alterações foram gravadas
    ou ficaram em edição; em edição, o registro acompanha a camada: ao salvar, a correção passa a "salva"; ao
    descartar, sai do registro. Retorna o caminho do PDF (ou None, com o projeto não salvo).
    """
    projeto = projeto or QgsProject.instance()
    if not entradas:
        return None
    agora = datetime.now().strftime('%d/%m/%Y %H:%M')
    lote = uuid4().hex[:12]
    linhas = [dict(e, data_hora=agora, gravacao=GRAVACAO_SALVA if salvo else GRAVACAO_EDICAO, lote=lote)
              for e in entradas]
    if not salvo:
        _vigiar(projeto, lote, {e['camada'] for e in entradas})
    if not projetoSalvo(projeto):
        _registroTemporario.extend(linhas)
        feedback.pushInfo('Projeto não salvo: o registro das correções fica só nesta sessão (sem PDF).')
        return None
    tabela = _tabela(projeto, criar=True)
    if tabela is None:
        feedback.reportError('Não foi possível gravar o registro das correções.', fatalError=False)
        return None
    novas = []
    for linha in _registroTemporario + linhas:
        f = QgsFeature(tabela.fields())
        for nome, _t in CAMPOS:
            f.setAttribute(nome, linha.get(nome))
        novas.append(f)
    tabela.dataProvider().addFeatures(novas)
    _registroTemporario.clear()
    caminho = gerarRelatorio(projeto)
    if caminho:
        feedback.pushInfo(f'Relatório das correções: {caminho}')
    return caminho


def _vigiar(projeto, lote, nomes):
    """Liga a camada em edição ao registro: salvar confirma a correção, descartar a remove."""
    for nome in nomes:
        for camada in projeto.mapLayersByName(nome):
            if not isinstance(camada, QgsVectorLayer) or not camada.isEditable():
                continue
            info = _vigiadas.get(camada.id())
            if info is None:
                aoSalvar = lambda c=camada: _finalizar(c, True)
                aoDescartar = lambda c=camada: _finalizar(c, False)
                camada.afterCommitChanges.connect(aoSalvar)
                camada.afterRollBack.connect(aoDescartar)
                info = {'camada': camada, 'lotes': set(), 'slots': (aoSalvar, aoDescartar)}
                _vigiadas[camada.id()] = info
            info['lotes'].add(lote)


def _desligar(camada):
    info = _vigiadas.pop(camada.id(), None)
    if info is not None:
        aoSalvar, aoDescartar = info['slots']
        for sinal, slot in ((camada.afterCommitChanges, aoSalvar), (camada.afterRollBack, aoDescartar)):
            try:
                sinal.disconnect(slot)
            except (TypeError, RuntimeError):
                pass
    return info


def _finalizar(camada, salva):
    """Camada salva ou descartada: atualiza o registro das correções dela e refaz o PDF."""
    info = _desligar(camada)
    if info is None:
        return
    try:
        nome, lotes = camada.name(), info['lotes']
        doLote = lambda lote, nomeCamada: lote in lotes and nomeCamada == nome
        if salva:
            for linha in _registroTemporario:
                if doLote(linha.get('lote'), linha.get('camada')):
                    linha['gravacao'] = GRAVACAO_SALVA
        else:
            _registroTemporario[:] = [l for l in _registroTemporario if not doLote(l.get('lote'), l.get('camada'))]
        projeto = QgsProject.instance()
        if not projetoSalvo(projeto):
            return
        tabela = _tabela(projeto)
        if tabela is None:
            return
        alvo = [f.id() for f in tabela.getFeatures()
                if doLote(f['lote'], f['camada']) and f['gravacao'] != GRAVACAO_SALVA]
        if not alvo:
            return
        if salva:
            indice = tabela.fields().indexFromName('gravacao')
            tabela.dataProvider().changeAttributeValues({fid: {indice: GRAVACAO_SALVA} for fid in alvo})
            acao = 'confirmada(s): a camada foi salva'
        else:
            tabela.dataProvider().deleteFeatures(alvo)
            acao = 'retirada(s) do registro: as edições foram descartadas'
        if lerRegistro(projeto):
            gerarRelatorio(projeto)
        elif os.path.exists(_caminhoPdf(projeto)):
            os.remove(_caminhoPdf(projeto))
        QgsMessageLog.logMessage(f'{nome}: {len(alvo)} correção(ões) {acao}. Relatório das correções atualizado.',
                                 'GeoCAR', Qgis.MessageLevel.Info)
    except Exception as erro:   # o registro nunca deve atrapalhar o salvar/descartar da camada
        QgsMessageLog.logMessage(f'Registro das correções: {erro}', 'GeoCAR', Qgis.MessageLevel.Warning)


def limparHistorico(projeto=None):
    """Apaga o histórico de correções do projeto e o relatório do dia. Retorna quantas linhas apagou."""
    projeto = projeto or QgsProject.instance()
    _registroTemporario.clear()
    tabela = _tabela(projeto)
    total = 0
    if tabela is not None:
        ids = [f.id() for f in tabela.getFeatures()]
        total = len(ids)
        if ids:
            tabela.dataProvider().deleteFeatures(ids)
    if projetoSalvo(projeto) and os.path.exists(_caminhoPdf(projeto)):
        os.remove(_caminhoPdf(projeto))
    return total


def lerRegistro(projeto=None):
    projeto = projeto or QgsProject.instance()
    tabela = _tabela(projeto)
    if tabela is None:
        return []
    registros = []
    for f in tabela.getFeatures():
        registro = {n: f[n] for n, _t in CAMPOS}
        registro = {k: ('' if v is None or str(v) == 'NULL' else v) for k, v in registro.items()}
        registros.append(registro)
    return registros


def _quantidade(r):
    q = r.get('quantidade')
    if q in ('', None):
        return ''
    try:
        q = float(q)
    except (TypeError, ValueError):
        return str(q)
    casas = 4 if r.get('unidade') == 'ha' else (1 if r.get('unidade') == 'm²' else 0)
    texto = f'{q:,.{casas}f}'.replace(',', 'X').replace('.', ',').replace('X', '.')
    return f"{texto} {r.get('unidade') or ''}".strip()


def _agrupar(itens):
    """Junta numa linha as correções iguais da mesma execução e feição (ex.: várias lascas na mesma feição)."""
    grupos = {}
    for r in itens:
        chave = (r['data_hora'], r['camada'], r['feicao'], r['tipo'], r['detalhe'], r['unidade'], r['gravacao'])
        if chave not in grupos:
            grupos[chave] = dict(r, n=0, quantidade=0.0 if r.get('quantidade') not in ('', None) else '')
        g = grupos[chave]
        g['n'] += 1
        if g['quantidade'] != '':
            g['quantidade'] += float(r['quantidade'] or 0)
    saida = []
    for g in grupos.values():
        if g['n'] > 1:
            g = dict(g, detalhe=f"{g['n']}× {g['detalhe']}")
        saida.append(g)
    return saida


def gerarRelatorio(projeto=None):
    """Refaz o PDF das correções com todo o histórico do registro. Retorna o caminho."""
    from .relatorio import CSS, _salvar_pdf

    projeto = projeto or QgsProject.instance()
    registros = lerRegistro(projeto)
    if not registros:
        return None
    caminho = _caminhoPdf(projeto)
    porSecao = {}
    for r in registros:
        secao = TIPOS.get(r['tipo'], ('Outras correções', '', ''))[0]
        porSecao.setdefault(secao, []).append(r)

    p = [f"<html><head><meta charset='utf-8'><style>{CSS}</style></head><body>",
         "<h1>GeoCAR — Correções da Pré-Análise</h1>",
         f"<p>Projeto: <b>{escape(projeto.baseName() or '')}</b> | Relatório gerado em "
         f"{datetime.now().strftime('%d/%m/%Y %H:%M')} | {len(registros)} correção(ões) registrada(s)</p>",
         "<p>Registro das correções feitas pelas ferramentas do grupo <b>4. Correções</b> do GeoCAR, com o "
         "fundamento legal de cada uma. Base: Lei nº 12.651, de 25 de maio de 2012 (Código Florestal), e Decreto "
         "nº 7.830, de 17 de outubro de 2012 (Sistema de Cadastro Ambiental Rural).</p>",
         "<h2>Resumo</h2><table border='1' cellspacing='0' cellpadding='4' width='100%'><tr><th>Correção</th><th>Registros</th><th>Ferramenta</th></tr>"]
    for secao in ORDEM_SECOES + [s for s in porSecao if s not in ORDEM_SECOES]:
        if secao in porSecao:
            itens = porSecao[secao]
            ferramentas = ', '.join(sorted({r['ferramenta'] for r in itens}))
            p.append(f"<tr><td>{escape(secao)}</td><td class='num'>{len(itens)}</td><td>{escape(ferramentas)}</td></tr>")
    p.append("</table>")

    numero = 0
    for secao in ORDEM_SECOES + [s for s in porSecao if s not in ORDEM_SECOES]:
        if secao not in porSecao:
            continue
        numero += 1
        itens = porSecao[secao]
        p.append(f"<h2>{numero}. {escape(secao)}</h2>")
        tipos = []
        for r in itens:
            if r['tipo'] not in tipos:
                tipos.append(r['tipo'])
        fundamentos = []
        for tipo in tipos:
            _s, feito, lei = TIPOS.get(tipo, ('', '', ''))
            if feito:
                p.append(f"<p><b>O que foi feito:</b> {escape(feito)}</p>")
            if lei and lei not in fundamentos:
                fundamentos.append(lei)
        for lei in fundamentos:
            p.append(f"<p class='aviso'><b>Fundamento legal:</b> {escape(lei)}</p>")
        p.append("<table border='1' cellspacing='0' cellpadding='4' width='100%'><tr><th>Data</th><th>Camada</th><th>Feição</th><th>Correção</th><th>Quantidade</th>"
                 "<th>Gravação</th></tr>")
        for r in _agrupar(itens):
            p.append(f"<tr><td>{escape(str(r['data_hora']))}</td><td>{escape(str(r['camada']))}</td>"
                     f"<td>{escape(str(r['feicao']))}</td><td>{escape(str(r['detalhe']))}</td>"
                     f"<td class='num'>{escape(_quantidade(r))}</td><td>{escape(str(r['gravacao']))}</td></tr>")
        p.append("</table>")

    p.append("<h2>Observações</h2><ul>"
             "<li>Correções marcadas como <b>em edição</b> ainda não foram salvas na camada: ao salvar, passam a "
             "<b>salva</b>; ao descartar, saem deste relatório.</li>"
             "<li>Depois das correções, rode de novo a pré-análise (grupo 3) para confirmar que as pendências "
             "sumiram.</li>"
             "<li>Sobreposições com imóveis vizinhos, Unidades de Conservação, Terras Indígenas, assentamentos e "
             "embargos não são corrigidas automaticamente: dependem de documentos e do órgão responsável.</li>"
             "<li>Este relatório registra correções técnicas da geometria. Não substitui a análise do órgão ambiental "
             "competente nem a responsabilidade técnica do profissional pela inscrição no CAR.</li></ul>")
    p.append("<p class='nota'>GeoCAR — GeoOne</p></body></html>")
    _salvar_pdf("".join(p), caminho, "GeoCAR — Correções da Pré-Análise")
    return caminho
