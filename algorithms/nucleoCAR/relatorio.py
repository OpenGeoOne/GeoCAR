# -*- coding: utf-8 -*-
"""Geração do relatório da pré-análise do CAR em HTML ou PDF."""

from html import escape

CSS = """
body { font-family: Segoe UI, Arial, sans-serif; margin: 32px; color: #1f2933; max-width: 960px; }
h1 { color: #2e7d32; border-bottom: 3px solid #2e7d32; padding-bottom: 6px; }
h2 { color: #1b5e20; margin-top: 32px; }
table { border-collapse: collapse; width: 100%; margin: 8px 0 16px; font-size: 14px; }
th, td { border: 1px solid #cfd8dc; padding: 6px 8px; text-align: left; }
th { background: #e8f5e9; }
td.num { text-align: right; font-variant-numeric: tabular-nums; }
.ok { color: #2e7d32; font-weight: 600; }
.alerta { color: #c62828; font-weight: 600; }
.aviso { background: #fff8e1; border-left: 4px solid #f9a825; padding: 8px 12px; margin: 6px 0; }
.nota { font-size: 12px; color: #607d8b; margin-top: 40px; border-top: 1px solid #cfd8dc;
        padding-top: 8px; }
"""

# Versão compacta do CSS para o PDF (o QTextDocument não herda o tamanho da fonte da tabela para as células)
CSS_PDF = """
body { font-family: Arial, sans-serif; font-size: 8pt; color: #1f2933; }
p { font-size: 8pt; margin: 2px 0; }
h1 { font-size: 15pt; color: #2e7d32; margin: 0 0 2px 0; }
h2 { font-size: 11pt; color: #1b5e20; margin: 10px 0 3px 0; }
th, td { font-size: 7.5pt; border: 1px solid #cfd8dc; padding: 1px 3px; text-align: left; }
th { background: #e8f5e9; }
td.num { text-align: right; }
.ok { color: #2e7d32; font-weight: 600; }
.alerta { color: #c62828; font-weight: 600; }
.aviso { font-size: 7.5pt; background: #fff8e1; margin: 2px 0; }
.nota { font-size: 7pt; color: #607d8b; margin-top: 12px; }
"""


def _n(valor, casas=4):
    """Formata número no padrão brasileiro."""
    if valor is None:
        return "-"
    txt = f"{valor:,.{casas}f}"
    return txt.replace(",", "X").replace(".", ",").replace("X", ".")


def _tabela(cabecalho, linhas, colunas_num=()):
    """Monta uma tabela HTML. colunas_num: índices alinhados à direita."""
    # Atributos de tabela garantem as bordas também na impressão em PDF (QTextDocument)
    html = ['<table border="1" cellspacing="0" cellpadding="4" width="100%"><tr>'] + [f"<th>{escape(c)}</th>" for c in cabecalho] + ["</tr>"]
    for linha in linhas:
        html.append("<tr>")
        for i, valor in enumerate(linha):
            classe = ' class="num"' if i in colunas_num else ""
            html.append(f"<td{classe}>{escape(str(valor))}</td>")
        html.append("</tr>")
    html.append("</table>")
    return "".join(html)


def gerar_relatorio_html(r, caminho):
    """Gera o relatório a partir do resumo da análise: PDF se o caminho terminar em .pdf, senão HTML."""
    partes = [
        "<!doctype html><html lang='pt-BR'><head><meta charset='utf-8'>",
        f"<title>Pré-análise do CAR</title><style>{CSS}</style></head><body>",
        "<h1>Pré-análise do CAR</h1>",
        f"<p>Gerado em {escape(r['data'])} — camada <b>{escape(r['camada_perimetro'])}</b></p>",
    ]

    # Dados do imóvel
    partes.append("<h2>1. Dados do imóvel</h2>")
    partes.append(_tabela(["Item", "Valor"], [
        ["Área do imóvel (ha)", _n(r["area_imovel_ha"])],
        ["Área considerada em 22/07/2008 (ha)", _n(r["area_2008_ha"])],
        ["Módulo fiscal do município (ha)", _n(r["modulo_fiscal_ha"], 2)],
        ["Número de módulos fiscais", _n(r["n_modulos"], 2)],
        ["Parcelas na camada", r["n_parcelas"]],
        ["SRC de cálculo", r["src"]],
    ], colunas_num=(1,)))

    # Validação
    partes.append("<h2>2. Validação geométrica</h2>")
    if r["problemas"]:
        partes.append(f"<p class='alerta'>{len(r['problemas'])} problema(s) encontrado(s).</p>")
        partes.append(_tabela(["Feição", "Tipo", "Descrição"],
                              [[x["feicao"], x["tipo"], x["descricao"]] for x in r["problemas"]]))
    else:
        partes.append("<p class='ok'>Nenhum problema geométrico encontrado.</p>")

    # Sobreposições
    partes.append("<h2>3. Sobreposições</h2>")
    if r["sobreposicoes"]:
        largura_divisa, perc_divisa = r.get("criterio_divisa", (15.0, 2.0))
        relevantes = [s for s in r["sobreposicoes"] if s["classe"] == "Sobreposição relevante"]
        divisas = [s for s in r["sobreposicoes"] if s["classe"] != "Sobreposição relevante"]
        if relevantes:
            partes.append(f"<p class='alerta'>Sobreposição relevante: {_n(sum(s['area_ha'] for s in relevantes))} ha "
                          f"em {len(relevantes)} feição(ões) — conflito de área a resolver antes do envio "
                          f"(verificar matrícula, posse, CAR duplicado ou desmembramento).</p>")
        else:
            partes.append("<p class='ok'>Nenhuma sobreposição relevante.</p>")
        if divisas:
            partes.append(f"<p>Ajuste de divisa: {_n(sum(s['area_ha'] for s in divisas))} ha em {len(divisas)} "
                          f"feição(ões) — faixas estreitas ao longo do limite, típicas de digitalização "
                          f"sobre imagens diferentes.</p>")
        partes.append(_tabela(
            ["Camada", "Identificador", "Classe", "Área (ha)", "% do imóvel", "Larg. média (m)"],
            [[s["camada"], s["identificador"] or f"fid {s['feicao']}", s["classe"],
              _n(s["area_ha"]), _n(s["percentual"], 2), _n(s["largura_m"], 1)] for s in r["sobreposicoes"]],
            colunas_num=(3, 4, 5)))
        partes.append(f"<p>Critério: ajuste de divisa quando a largura média (2·área/perímetro) é de até "
                      f"{_n(largura_divisa, 1)} m e a área é de até {_n(perc_divisa, 1)}% do imóvel.</p>")
    else:
        partes.append("<p class='ok'>Nenhuma sobreposição com as camadas de restrição "
                      "selecionadas.</p>")

    # APP
    a = r["app"]
    partes.append("<h2>4. Áreas de Preservação Permanente (hídricas)</h2>")
    for aviso in a["avisos"]:
        if aviso.startswith("Área consolidada não informada"):
            # Destaque: o usuário pode ter esquecido a camada
            partes.append(f"<div class='aviso'><b class='alerta'>{escape(aviso)}</b></div>")
        else:
            partes.append(f"<div class='aviso'>{escape(aviso)}</div>")
    if a["detalhes"]:
        agrupados = {}
        for d in a["detalhes"]:
            chave = (d["tipo"], d["faixa_integral"], d["faixa_consolidada"])
            agrupados[chave] = agrupados.get(chave, 0) + 1
        partes.append(_tabela(
            ["Feição", "Qtde", "Faixa integral art. 4º (m)", "Faixa escadinha art. 61-A (m)"],
            [[tipo, qtde, _n(fi, 1), _n(fc, 1)] for (tipo, fi, fc), qtde in agrupados.items()],
            colunas_num=(1, 2, 3)))

    linhas_app = [
        ["APP integral (art. 4º)", _n(a["integral_ha"])],
        ["Faixa da escadinha (art. 61-A)", _n(a["faixa_consolidada_ha"])],
    ]
    if a["tem_consolidada"]:
        linhas_app += [
            ["Área rural consolidada informada", _n(a["consolidada_ha"])],
            ["APP a recompor dentro da área consolidada", _n(a["recompor_ha"])],
            ["Uso consolidado que pode ser mantido em APP", _n(a["liberada_ha"])],
            ["Total de APP a preservar/recompor", _n(a["recompor_total_ha"])],
        ]
    else:
        linhas_app.append(["Total de APP a preservar (toda a APP integral)", _n(a["recompor_total_ha"])])
    partes.append(_tabela(["Tema", "Área (ha)"], linhas_app, colunas_num=(1,)))

    if a["limite_61b_ha"] is not None and not a["tem_consolidada"]:
        partes.append("<p>Limite do art. 61-B: não se aplica — área consolidada não informada.</p>")
    elif a["limite_61b_ha"] is not None:
        excede = a["recompor_total_ha"] > a["limite_61b_ha"]
        classe = "alerta" if excede else "ok"
        texto = ("excede o limite — a recomposição fica limitada ao teto legal"
                 if excede else "dentro do limite")
        partes.append(f"<p>Limite do art. 61-B: {_n(a['limite_61b_ha'])} ha — "
                      f"<span class='{classe}'>{texto}</span>.</p>")

    # Reserva Legal
    rl = r["rl"]
    partes.append("<h2>5. Reserva Legal</h2>")
    partes.append(_tabela(["Item", "Área (ha)"], [
        [f"RL exigida ({_n(rl['percentual'], 0)}%)", _n(rl["exigida_ha"])],
        ["Vegetação nativa no imóvel", _n(rl["vegetacao_ha"])],
        ["Vegetação nativa fora de APP", _n(rl["vegetacao_fora_app_ha"])],
        ["Déficit com cômputo da APP (art. 15)", _n(rl["deficit_com_app_ha"])],
        ["Déficit sem cômputo da APP", _n(rl["deficit_sem_app_ha"])],
    ], colunas_num=(1,)))
    for obs in rl["observacoes"]:
        partes.append(f"<div class='aviso'>{escape(obs)}</div>")

    partes.append(
        "<p class='nota'>Pré-análise técnica automatizada, de caráter indicativo. Não substitui "
        "a análise do órgão ambiental competente nem a verificação da legislação estadual, que "
        "pode ser mais restritiva. A faixa da escadinha (art. 61-A) aplica-se somente a áreas "
        "rurais consolidadas até 22/07/2008, devidamente comprovadas.</p>")
    partes.append("</body></html>")
    html = "".join(partes)

    if caminho.lower().endswith(".pdf"):
        return _salvar_pdf(html, caminho)
    with open(caminho, "w", encoding="utf-8") as arq:
        arq.write(html)
    return caminho


def _salvar_pdf(html, caminho):
    """Converte o HTML do relatório em PDF (A4) com QTextDocument e QPrinter, sem dependências externas."""
    from qgis.PyQt.QtCore import QMarginsF, QSizeF
    from qgis.PyQt.QtGui import QPageLayout, QPageSize, QTextDocument
    from qgis.PyQt.QtPrintSupport import QPrinter

    from .utils import enum_compat

    # ScreenResolution mantém as medidas em px do CSS proporcionais (o texto continua vetorial no PDF)
    impressora = QPrinter(enum_compat(QPrinter, "PrinterMode", "ScreenResolution"))
    impressora.setOutputFormat(enum_compat(QPrinter, "OutputFormat", "PdfFormat"))
    impressora.setOutputFileName(caminho)
    # QPageLayout funciona igual no Qt5 e no Qt6 (setPageMargins mudou de assinatura)
    impressora.setPageLayout(QPageLayout(
        QPageSize(enum_compat(QPageSize, "PageSizeId", "A4")),
        enum_compat(QPageLayout, "Orientation", "Portrait"),
        QMarginsF(15, 15, 15, 15),
        enum_compat(QPageLayout, "Unit", "Millimeter")))
    impressora.setDocName("Pré-análise do CAR")

    # No PDF usa o CSS compacto, para as tabelas caberem inteiras na página
    html = html.replace(CSS, CSS_PDF, 1)

    documento = QTextDocument()
    documento.setHtml(html)
    areaUtil = impressora.pageLayout().paintRectPixels(impressora.resolution())
    documento.setPageSize(QSizeF(areaUtil.width(), areaUtil.height()))
    imprimir = getattr(documento, "print", None) or getattr(documento, "print_")   # Qt6 / Qt5
    imprimir(impressora)
    return caminho
