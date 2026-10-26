# -*- coding: utf-8 -*-
"""Geração do relatório da pré-análise do CAR em HTML ou PDF."""

from html import escape

CSS = """
body { font-family: Segoe UI, Arial, sans-serif; margin: 32px; color: #1f2933; max-width: 960px; }
h1 { color: #2e7d32; border-bottom: 3px solid #2e7d32; padding-bottom: 6px; }
h2 { color: #1b5e20; margin-top: 32px; }
h3 { color: #1b5e20; margin: 16px 0 4px; }
li { margin: 3px 0; }
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
h3 { font-size: 9pt; color: #1b5e20; margin: 6px 0 1px 0; }
ul { margin: 0 0 2px 0; } li { font-size: 8pt; margin: 1px 0; }
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


def _plano_acao(r):
    """
    "O que corrigir": as pendências da análise, em ordem de prioridade, montadas a partir dos resultados.
    Retorna o HTML da seção.
    """
    h = lambda v: _n(v, 2)
    bloqueia, ajustes, recompor, atencao = [], [], [], []

    # Validação geométrica
    if r["problemas"]:
        tipos = sorted({x["tipo"] for x in r["problemas"]})
        bloqueia.append(f"Corrigir {len(r['problemas'])} problema(s) geométrico(s): {', '.join(tipos)} "
                        f"(camada Problemas_Validacao).")

    # Sobreposições
    relevantes = [s for s in r["sobreposicoes"] if s["classe"] == "Sobreposição relevante"]
    divisas = [s for s in r["sobreposicoes"] if s["classe"] == "Ajuste de divisa"]
    apas = [s for s in r["sobreposicoes"] if s["classe"].startswith("Informativa")]
    for s in relevantes:
        ident = s["identificador"] or f"fid {s['feicao']}"
        if ":" in ident:   # restrição oficial (UC, Terra Indígena, assentamento, embargo, floresta pública)
            bloqueia.append(f"Sobreposição de {h(s['area_ha'])} ha ({h(s['percentual'])}% do imóvel) com {ident}: "
                            f"verificar a restrição no órgão responsável, pois pode impedir ou condicionar o uso.")
        else:
            bloqueia.append(f"Sobreposição de {h(s['area_ha'])} ha ({h(s['percentual'])}% do imóvel) com {s['camada']} "
                            f"{ident}: conferir matrícula, escritura, SIGEF e CCIR dos dois imóveis. Se o outro cadastro "
                            f"estiver errado, o titular dele precisa retificar ou cancelar; se o erro for desta ATI, "
                            f"retificá-la.")
    if divisas:
        larguras = [s["largura_m"] for s in divisas]
        ajustes.append(f"{len(divisas)} faixa(s) de ajuste de divisa, {h(sum(s['area_ha'] for s in divisas))} ha, "
                       f"com largura média de {_n(min(larguras), 1)} a {_n(max(larguras), 1)} m: vale o limite mais "
                       f"preciso. Mantenha a ATI se ela vier de levantamento georreferenciado ou do SIGEF; se foi "
                       f"digitalizada sobre imagem, encoste no limite do vizinho.")

    # Consistência entre camadas
    for i in r.get("consistencia") or []:
        texto = f"{i['tipo']} ({i['camadas']}): {h(i['area_ha'])} ha."
        if i["gravidade"] == "Erro":
            bloqueia.append(texto + " Corrigir as camadas declaradas.")
        elif i["tipo"].startswith("Reserva Legal sem vegetação"):
            recompor.append(f"Reserva Legal sem vegetação nativa: {h(i['area_ha'])} ha a recompor (PRA).")
        elif i["tipo"].startswith("Área sem cobertura"):
            ajustes.append(f"{h(i['area_ha'])} ha da ATI sem cobertura do solo declarada: classificar essas áreas em "
                           f"vegetação nativa, área consolidada ou pousio.")
        else:
            ajustes.append(texto)

    # Reserva Legal
    rl = r["rl"]
    declarada = rl.get("declarada_ha")
    if declarada is not None and declarada < rl["exigida_ha"] - 0.0001:
        suficiente = rl["vegetacao_fora_app_ha"] >= rl["exigida_ha"]
        base = (f"há {h(rl['vegetacao_fora_app_ha'])} ha de vegetação nativa fora de APP, suficientes para desenhar "
                f"toda a RL sobre vegetação" if suficiente else
                f"há só {h(rl['vegetacao_fora_app_ha'])} ha de vegetação nativa fora de APP")
        if declarada <= 0.0001:
            bloqueia.append(f"Reserva Legal não declarada: a exigida é de {h(rl['exigida_ha'])} ha "
                            f"({_n(rl['percentual'], 0)}%); {base}.")
        else:
            bloqueia.append(f"Reserva Legal declarada ({h(declarada)} ha) menor que a exigida "
                            f"({h(rl['exigida_ha'])} ha); {base}.")
    if rl["deficit_com_app_ha"] > 0.0001:
        if r["n_modulos"] <= 4:
            recompor.append(f"Déficit de RL de {h(rl['deficit_com_app_ha'])} ha, mas o imóvel tinha até 4 MF em "
                            f"22/07/2008: pelo art. 67, a RL pode ficar com a vegetação existente naquela data.")
        else:
            recompor.append(f"Déficit de RL de {h(rl['deficit_com_app_ha'])} ha: recompor, regenerar ou compensar "
                            f"(art. 66), pelo PRA.")

    # APP hídrica
    a = r["app"]
    if a["integral_ha"] > 0:
        if a["tem_consolidada"] and a["recompor_ha"] > 0.0001:
            recompor.append(f"Recompor {h(a['recompor_ha'])} ha da faixa da escadinha (art. 61-A) dentro da área "
                            f"consolidada, pela adesão ao PRA.")
        if a["tem_vegetacao"]:
            onde = "fora da área consolidada" if a["tem_consolidada"] else ""
            if a["fora_sem_vegetacao_ha"] > 0.0001:
                recompor.append(f"Recompor {h(a['fora_sem_vegetacao_ha'])} ha de APP {onde} sem vegetação nativa "
                                f"(faixa integral do art. 4º).".replace("  ", " "))
            recompor.append(f"Total de APP a recompor de fato: {h(a['recompor_real_ha'])} ha; o restante dos "
                            f"{h(a['recompor_total_ha'])} ha a preservar ou recompor já tem vegetação.")
        else:
            recompor.append("Vegetação nativa não informada: não foi possível separar a APP que já está vegetada.")
        if a["tem_consolidada"] and a["limite_61b_ha"] is not None:
            excede = a["recompor_total_ha"] > a["limite_61b_ha"]
            recompor.append(f"Teto do art. 61-B: {h(a['limite_61b_ha'])} ha — "
                            + ("a recomposição fica limitada a esse teto." if excede else "dentro do limite."))
        if a["tem_consolidada"] and a["liberada_ha"] > 0.0001:
            recompor.append(f"Uso consolidado em APP ({h(a['liberada_ha'])} ha) pode continuar (art. 61-A), com "
                            f"práticas de conservação do solo e da água.")
        if not a["tem_consolidada"]:
            recompor.append("Área consolidada não informada: a APP foi calculada no cenário integral. Se houver uso "
                            "anterior a 22/07/2008, informe a camada e refaça a análise.")
    for aviso in a["avisos"]:
        if "largura" in aviso:
            recompor.append(f"Conferir em campo a largura dos cursos d'água: {aviso}")
    if r.get("modulo_automatico"):
        recompor.append(f"Conferir na tabela do INCRA o módulo fiscal ({h(r['modulo_fiscal_ha'])} ha), obtido dos "
                        f"CARs vizinhos.")

    # Comparação com o SIGEF (titularidade)
    sg = r.get("sigef")
    if sg is not None:
        doImovel = [x for x in sg["parcelas"] if x["classe"] == "Parcela do imóvel"]
        for x in sg["parcelas"]:
            ref = ", ".join(v for v in (x["nome"], f"matrícula {x['matricula']}" if x["matricula"] else "",
                                        f"código {x['codigo']}" if x["codigo"] else "") if v)
            if x["classe"] == "Parcela de terceiro dentro da ATI":
                bloqueia.append(f"A ATI avança {h(x['area_na_ati_ha'])} ha sobre a parcela certificada no SIGEF ({ref}), "
                                f"que é de outro imóvel: retificar a ATI ou comprovar a titularidade.")
        divisas_sigef = [x for x in sg["parcelas"] if x["classe"] == "Ajuste de divisa com parcela certificada"]
        if divisas_sigef:
            ajustes.append(f"{len(divisas_sigef)} faixa(s) estreita(s) entre a ATI e parcelas certificadas no SIGEF "
                           f"({h(sum(x['area_na_ati_ha'] for x in divisas_sigef))} ha): ajustar a ATI ao limite "
                           f"certificado, que é o mais preciso.")
        if not doImovel:
            recompor.append("Nenhuma parcela certificada no SIGEF coincide com a ATI: conferir se o imóvel já foi "
                            "georreferenciado e certificado (obrigatório em desmembramentos e transferências, "
                            "conforme o tamanho do imóvel).")
        else:
            if len(sg["matriculas"]) > 1:
                recompor.append(f"A ATI reúne {len(sg['matriculas'])} parcelas certificadas "
                                f"({', '.join(sg['matriculas'])}): conferir se todas são do mesmo titular, "
                                f"condição para um único CAR.")
            if sg["sem_certificacao_ha"] > 0.01 * r["area_imovel_ha"]:
                recompor.append(f"{h(sg['sem_certificacao_ha'])} ha da ATI sem parcela certificada no SIGEF: "
                                f"posse sem título ou georreferenciamento pendente; conferir os documentos dessa área.")
            if sg["fora_ati_ha"] > 0.01 * r["area_imovel_ha"]:
                recompor.append(f"As parcelas certificadas do imóvel têm {h(sg['fora_ati_ha'])} ha fora da ATI: a ATI "
                                f"está menor que o imóvel certificado; conferir se deve seguir o perímetro do SIGEF.")

    # Atenção
    if apas:
        nomes = "; ".join(s["identificador"].split(":", 1)[-1].strip() for s in apas)
        atencao.append(f"Imóvel em Área de Proteção Ambiental ({nomes}): não impede o CAR; conferir o zoneamento e o "
                       f"plano de manejo antes de mudanças de uso.")
    vistas = set()
    for p in r.get("restricoes_proximas") or []:
        chave = (p["tipo"], p["nome"])
        if chave in vistas:
            continue
        vistas.add(chave)
        nota = " (provável zona de amortecimento; pesa em licenciamento)" if p["tipo"].startswith("Unidade") else ""
        atencao.append(f"{p['tipo']} a {_n(p['distancia_m'] / 1000.0, 1)} km: {p['nome']}{nota}. Não toca o imóvel.")

    # Documentos a reunir, conforme as pendências encontradas
    documentos = ["Documento de propriedade ou posse do imóvel e CPF/CNPJ do proprietário ou possuidor; "
                  "procuração, se o cadastro for feito por terceiro."]
    if any(":" not in (s["identificador"] or "") for s in relevantes) or (sg and any(
            x["classe"] == "Parcela de terceiro dentro da ATI" for x in sg["parcelas"])):
        documentos.append("Certidão de inteiro teor atualizada da matrícula, memorial descritivo e certificação do "
                          "SIGEF, CCIR e contrato de compra e venda ou formal de partilha, se houve venda ou herança.")
    if any(":" in (s["identificador"] or "") for s in relevantes):
        documentos.append("Declaração ou certidão do órgão responsável pela área sobreposta (ICMBio ou órgão "
                          "estadual, FUNAI, INCRA, SFB) sobre a situação do imóvel.")
    if sg is not None and len(sg["matriculas"]) > 1:
        documentos.append("Certidões de todas as matrículas reunidas na ATI, comprovando o mesmo titular.")
    if sg is not None and (not [x for x in sg["parcelas"] if x["classe"] == "Parcela do imóvel"]
                           or sg["sem_certificacao_ha"] > 0.01 * r["area_imovel_ha"]):
        documentos.append("Título ou documento de posse da área sem certificação e, se já houver, ART e memorial do "
                          "georreferenciamento.")
    if a["tem_consolidada"]:
        documentos.append("Comprovação do uso anterior a 22/07/2008 na área consolidada: imagens de satélite da época, "
                          "declarações de ITR antigas, notas fiscais de produção, financiamentos rurais.")
    tipos_rl = rl.get("tipos_declarados") or []
    if "averbada" in tipos_rl:
        documentos.append("Certidão da matrícula com a averbação da Reserva Legal.")
    if "outro_imovel" in tipos_rl:
        documentos.append("Instrumento que vincula a Reserva Legal em outro imóvel (servidão ambiental, CRA, "
                          "condomínio ou termo do órgão ambiental).")
    if rl["deficit_com_app_ha"] > 0.0001 and r["n_modulos"] > 4:
        documentos.append("Proposta de recomposição, regeneração ou compensação da Reserva Legal para o PRA.")
    if any("mbargo" in (p["tipo"] or "") for p in r.get("restricoes_proximas") or []) or \
            any("Embargo" in (s["identificador"] or "") for s in r["sobreposicoes"]):
        documentos.append("Certidão negativa de embargos do IBAMA (e do ICMBio), consultada pelo CPF/CNPJ do "
                          "proprietário — o plugin não guarda dados pessoais dos embargos.")

    # HTML
    partes = ["<h2>O que corrigir</h2>"]
    if bloqueia:
        partes.append(f"<p class='alerta'>{len(bloqueia)} pendência(s) a resolver antes do envio ao CAR.</p>")
    else:
        partes.append("<p class='ok'>Nenhuma pendência impede o envio ao CAR.</p>")
    for titulo, itens in (("Resolver antes de enviar", bloqueia), ("Ajustes pequenos", ajustes),
                          ("Recompor e conferir", recompor), ("Ficar atento", atencao)):
        if itens:
            partes.append(f"<h3>{titulo}</h3><ul>" + "".join(f"<li>{escape(i)}</li>" for i in itens) + "</ul>")
    partes.append("<h3>Documentos a reunir</h3><ul>" + "".join(f"<li>{escape(d)}</li>" for d in documentos) + "</ul>")
    return "".join(partes)


def gerar_relatorio_html(r, caminho):
    """Gera o relatório a partir do resumo da análise: PDF se o caminho terminar em .pdf, senão HTML."""
    partes = [
        "<!doctype html><html lang='pt-BR'><head><meta charset='utf-8'>",
        f"<title>GeoCAR — Resultados da Pré-Análise</title><style>{CSS}</style></head><body>",
        "<h1>GeoCAR — Resultados da Pré-Análise</h1>",
        f"<p>Gerado em {escape(r['data'])} — camada <b>{escape(r['camada_perimetro'])}</b></p>",
    ]

    # Plano de correções: o resumo do que fazer, antes dos detalhes
    partes.append(_plano_acao(r))

    # Dados do imóvel
    # Os detalhes começam em nova página: a primeira fica com o resumo do que corrigir
    partes.append("<h2 style='page-break-before: always'>1. Dados do imóvel</h2>")
    identificacao = [[rotulo, valor] for rotulo, valor in (r.get("identificacao") or {}).items() if valor]
    partes.append(_tabela(["Item", "Valor"], identificacao + [
        ["Área do imóvel (ha)", _n(r["area_imovel_ha"])],
        ["Área considerada em 22/07/2008 (ha)", _n(r["area_2008_ha"])],
        ["Módulo fiscal do município (ha)" + (" — obtido dos CARs vizinhos; confira na tabela do INCRA"
                                              if r.get("modulo_automatico") else ""), _n(r["modulo_fiscal_ha"], 2)],
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
        divisas = [s for s in r["sobreposicoes"] if s["classe"] == "Ajuste de divisa"]
        informativas = [s for s in r["sobreposicoes"] if s["classe"].startswith("Informativa")]
        if relevantes:
            partes.append(f"<p class='alerta'>Sobreposição relevante: {_n(sum(s['area_ha'] for s in relevantes))} ha "
                          f"em {len(relevantes)} feição(ões) — a resolver antes do envio (com CAR vizinho: verificar matrícula, "
                          f"posse, CAR duplicado ou desmembramento; com UC, Terra Indígena, assentamento, embargo "
                          f"ou floresta pública: verificar a restrição no órgão responsável).</p>")
        else:
            partes.append("<p class='ok'>Nenhuma sobreposição relevante.</p>")
        if divisas:
            partes.append(f"<p>Ajuste de divisa: {_n(sum(s['area_ha'] for s in divisas))} ha em {len(divisas)} "
                          f"feição(ões) — faixas estreitas ao longo do limite, típicas de digitalização "
                          f"sobre imagens diferentes.</p>")
        if informativas:
            partes.append(f"<p>Informativa: imóvel em {len(informativas)} Área(s) de Proteção Ambiental (APA) — "
                          f"a APA admite propriedade privada; observar as regras do plano de manejo.</p>")
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

    # Consistência entre camadas
    if r.get("consistencia_verificada") or r.get("consistencia"):
        partes.append("<h2>6. Consistência entre camadas</h2>")
        itens = r.get("consistencia") or []
        erros = [i for i in itens if i["gravidade"] == "Erro"]
        if not itens:
            partes.append("<p class='ok'>Nenhuma inconsistência entre as camadas declaradas.</p>")
        else:
            if erros:
                partes.append(f"<p class='alerta'>{len(erros)} erro(s) entre as camadas — corrigir antes da "
                              f"importação no SICAR.</p>")
            partes.append(_tabela(["Gravidade", "Tipo", "Camadas", "Área (ha)"],
                                  [[i["gravidade"], i["tipo"], i["camadas"], _n(i["area_ha"])] for i in itens],
                                  colunas_num=(3,)))

    # Comparação com o SIGEF
    sg = r.get("sigef")
    if sg is not None:
        partes.append("<h2>7. Comparação com o SIGEF</h2>")
        if not sg["parcelas"]:
            partes.append("<p class='alerta'>Nenhuma parcela certificada no SIGEF toca a ATI.</p>")
        else:
            partes.append(_tabela(
                ["Parcela", "Matrícula", "Classe", "Área da parcela (ha)", "Na ATI (ha)", "% da parcela na ATI"],
                [[x["nome"] or x["codigo"], x["matricula"], x["classe"], _n(x["area_parcela_ha"]),
                  _n(x["area_na_ati_ha"]), _n(x["perc_parcela"], 1)] for x in sg["parcelas"]],
                colunas_num=(3, 4, 5)))
        partes.append(f"<p>ATI sem parcela certificada: {_n(sg['sem_certificacao_ha'])} ha · "
                      f"parcelas do imóvel fora da ATI: {_n(sg['fora_ati_ha'])} ha.</p>")
        if sg.get("vizinhas"):
            partes.append("<p><b>Imóveis certificados vizinhos</b> (não tocam a ATI):</p>")
            partes.append(_tabela(
                ["Imóvel", "Matrícula", "Código", "Área (ha)", "Distância da ATI (m)"],
                [[v["nome"], v["matricula"], v["codigo"], _n(v["area_parcela_ha"]), _n(v["distancia_m"], 0)]
                 for v in sg["vizinhas"]], colunas_num=(3, 4)))

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


def _evitarTabelasQuebradas(documento, alturaPagina):
    """
    Se uma tabela cair entre duas páginas, começa nova página no título da seção (h2) dela,
    para manter título e tabela juntos. Repete até não haver tabela quebrada (máx. 10 vezes).
    """
    from qgis.PyQt.QtGui import QTextCursor, QTextFormat, QTextTable

    sempreAntes = getattr(getattr(QTextFormat, 'PageBreakFlag', QTextFormat), 'PageBreak_AlwaysBefore')
    for _ in range(10):
        layout = documento.documentLayout()
        alterou = False
        for quadro in documento.rootFrame().childFrames():
            if not isinstance(quadro, QTextTable):
                continue
            retangulo = layout.frameBoundingRect(quadro)
            if retangulo.height() >= alturaPagina:
                continue   # maior que uma página: não há como evitar
            # Título (h2) da seção da tabela
            bloco = documento.findBlock(quadro.firstPosition()).previous()
            while bloco.isValid() and bloco.blockFormat().headingLevel() != 2:
                bloco = bloco.previous()
            if not bloco.isValid() or bloco.blockFormat().pageBreakPolicy() & sempreAntes:
                continue
            paginaTitulo = int(layout.blockBoundingRect(bloco).top() // alturaPagina)
            paginaInicio = int(retangulo.top() // alturaPagina)
            paginaFim = int((retangulo.bottom() - 1) // alturaPagina)
            # Tabela inteira na mesma página do seu título: nada a fazer
            if paginaTitulo == paginaInicio == paginaFim:
                continue
            cursor = QTextCursor(bloco)
            formato = bloco.blockFormat()
            formato.setPageBreakPolicy(sempreAntes)
            cursor.setBlockFormat(formato)
            alterou = True
            break
        if not alterou:
            return


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
    impressora.setDocName("GeoCAR — Resultados da Pré-Análise")

    # No PDF usa o CSS compacto, para as tabelas caberem inteiras na página
    html = html.replace(CSS, CSS_PDF, 1)

    documento = QTextDocument()
    documento.setHtml(html)
    areaUtil = impressora.pageLayout().paintRectPixels(impressora.resolution())
    documento.setPageSize(QSizeF(areaUtil.width(), areaUtil.height()))
    _evitarTabelasQuebradas(documento, areaUtil.height())
    imprimir = getattr(documento, "print", None) or getattr(documento, "print_")   # Qt6 / Qt5
    imprimir(impressora)
    return caminho
