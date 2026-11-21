"""Jornal do dia: junta as notícias dos canais (RSS), resume com IA e gera o PDF."""
import datetime
import email.utils
import html
import os
import re
import urllib.request
import xml.etree.ElementTree as ET

import conversor
import ia

DIAS = ["segunda-feira", "terça-feira", "quarta-feira", "quinta-feira", "sexta-feira",
        "sábado", "domingo"]
MESES = ["janeiro", "fevereiro", "março", "abril", "maio", "junho", "julho", "agosto",
         "setembro", "outubro", "novembro", "dezembro"]
PASTA_KINDLE = "Noticias"          # subpasta de documents no Kindle


def data_extenso(d):
    return "%s, %d de %s de %d" % (DIAS[d.weekday()], d.day, MESES[d.month - 1], d.year)


def _texto(el):
    if el is None:
        return ""
    t = "".join(el.itertext()) if len(el) else (el.text or "")
    t = re.sub(r"<[^>]+>", " ", html.unescape(t))
    return re.sub(r"\s+", " ", html.unescape(t)).strip()


def _data(txt):
    txt = (txt or "").strip()
    if not txt:
        return None
    try:
        d = email.utils.parsedate_to_datetime(txt)
    except (TypeError, ValueError):
        try:
            d = datetime.datetime.fromisoformat(txt.replace("Z", "+00:00"))
        except ValueError:
            return None
    if d.tzinfo is None:
        d = d.replace(tzinfo=datetime.timezone.utc)
    return d


def _filho(el, *nomes):
    for filho in el:
        local = filho.tag.rsplit("}", 1)[-1]
        if local in nomes:
            return filho
    return None


def ler_feed(dados, fonte):
    raiz = ET.fromstring(dados)
    itens = []
    for el in raiz.iter():
        local = el.tag.rsplit("}", 1)[-1]
        if local not in ("item", "entry"):
            continue
        titulo = _texto(_filho(el, "title"))
        if not titulo:
            continue
        resumo = _texto(_filho(el, "description", "summary", "content", "encoded"))
        data = _data(_texto(_filho(el, "pubDate", "published", "updated", "date")))
        itens.append({"fonte": fonte, "titulo": titulo, "resumo": resumo[:600], "data": data})
    return itens


def baixar(url, timeout=25):
    req = urllib.request.Request(url, headers={
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) KindleEnvia/1.0",
        "Accept": "application/rss+xml, application/atom+xml, application/xml, text/xml, */*"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read()


def coletar(fontes, por_fonte=6, horas=30, aviso=None):
    """Devolve ({fonte: [itens]}, [erros])."""
    agora = datetime.datetime.now(datetime.timezone.utc)
    resultado, erros = {}, []
    for nome, url, ligado in fontes:
        if not ligado:
            continue
        if aviso:
            aviso("Buscando %s..." % nome)
        try:
            itens = ler_feed(baixar(url), nome)
        except Exception as e:  # noqa: BLE001 - um canal com problema não para os outros
            erros.append("%s: %s" % (nome, getattr(e, "reason", e)))
            continue
        recentes = [i for i in itens if not i["data"] or agora - i["data"] < datetime.timedelta(hours=horas)]
        recentes.sort(key=lambda i: i["data"] or agora, reverse=True)
        if recentes:
            resultado[nome] = recentes[:por_fonte]
    return resultado, erros


def _manchetes_md(por_fonte):
    linhas = []
    for fonte, itens in por_fonte.items():
        linhas.append("## " + fonte)
        for i in itens:
            resumo = i["resumo"]
            if resumo and resumo.lower() != i["titulo"].lower():
                if len(resumo) > 260:
                    resumo = resumo[:260].rsplit(" ", 1)[0] + "…"
                linhas.append("- **%s** %s" % (i["titulo"], resumo))
            else:
                linhas.append("- **%s**" % i["titulo"])
        linhas.append("")
    return "\n".join(linhas)


def montar(cfg, ia_cfg=None, aviso=None):
    """Monta o Markdown do jornal. Devolve (markdown, erros)."""
    n = cfg["noticias"]
    por_fonte, erros = coletar(n["fontes"], int(n.get("por_fonte", 6)), aviso=aviso)
    if not por_fonte:
        raise conversor.ConversaoErro("Nenhum canal de notícias respondeu.\n" + "\n".join(erros))
    partes = []
    if n.get("resumo_ia"):
        if aviso:
            aviso("Pedindo o resumo à IA...")
        entrada = "\n\n".join(
            "Fonte: %s\n%s" % (f, "\n".join("- %s: %s" % (i["titulo"], i["resumo"][:300]) for i in itens))
            for f, itens in por_fonte.items())
        try:
            partes.append(ia.resumir_noticias(entrada, ia_cfg))
        except ia.IAErro as e:
            erros.append("Resumo com IA: %s" % e)
    partes.append("# Manchetes por fonte" if partes else "")
    partes.append(_manchetes_md(por_fonte))
    return "\n\n".join(p for p in partes if p), erros, list(por_fonte)


def gerar(cfg, pasta_saida, ia_cfg=None, aviso=None, hoje=None, formato="azw3"):
    """Monta o Jornal do dia. Devolve (caminho, erros)."""
    formato = conversor.formato_real(formato)
    hoje = hoje or datetime.date.today()
    markdown, erros, fontes = montar(cfg, ia_cfg, aviso)
    titulo = "Jornal do dia - %s" % hoje.strftime("%d/%m/%Y")
    if formato == "pdf":
        capa = ("<div class='capa'><div class='pequeno'>%s</div><h1 style='font-size:46px'>Jornal do dia</h1>"
                "<hr><p class='pequeno'>Fontes: %s</p></div><div class='quebra'></div>"
                % (html.escape(data_extenso(hoje)), html.escape(", ".join(fontes))))
    else:
        capa = ("<div class='capa'><h1 class='primeiro'>Jornal do dia</h1><p>%s</p><hr>"
                "<p class='pequeno'>Fontes: %s</p></div>"
                % (html.escape(data_extenso(hoje)), html.escape(", ".join(fontes))))
        # no livro, cada parte (resumo, manchetes) começa numa página nova e entra no sumário
        markdown = re.sub(r"^## Destaques do dia", "# Destaques do dia", markdown, count=1, flags=re.M)
    pasta = os.path.join(pasta_saida, PASTA_KINDLE)
    os.makedirs(pasta, exist_ok=True)
    destino = os.path.join(pasta, "Noticias %s%s" % (hoje.isoformat(), conversor.EXT[formato]))
    if os.path.exists(destino):
        os.remove(destino)
    if aviso:
        aviso("Montando o jornal (%s)..." % formato.upper())
    conversor.html_para_livro(capa + conversor.markdown_para_html(markdown), destino, titulo, formato)
    return destino, erros
