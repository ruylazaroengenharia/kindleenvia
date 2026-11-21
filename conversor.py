"""
Converte arquivos para ler bem no Kindle 4 (tela de 600x800, 16 tons de cinza).

Formato de saída (escolhido na aba Kindle):
- AZW3 (padrão) ou MOBI, gerados pelo Calibre (ebook-convert): o texto se ajusta
  à tela, dá para mudar a letra, o dicionário funciona e as páginas viram rápido.
  Imagens e diagramas viram páginas de tela cheia dentro do livro.
- PDF: páginas no tamanho exato da tela (não precisa de Calibre; texto usa o Edge).

- Imagens (JPG, PNG...): cinza, giradas se forem deitadas, ajustadas à tela.
- PDF de entrada: original, "ampliar" (corta as margens), "metades" (divide a
  página em duas, para ler com o Kindle deitado) ou "texto" (Calibre refaz o texto).
- Mermaid (.mmd) e SVG: desenhados pelo Edge/Chrome em modo invisível.
- Texto (.txt, .md): vira livro (ou páginas do tamanho da tela, em PDF).
"""
import html
import io
import os
import pathlib
import re
import shutil
import subprocess
import sys
import tempfile
import zipfile

from PIL import Image, ImageOps

try:
    import pymupdf as fitz
except ImportError:  # versões antigas do PyMuPDF
    import fitz

LARG, ALT = 600, 800                 # tela do Kindle 4, em pixels
DPI = 167                            # densidade da tela do Kindle 4
PT_L, PT_A = LARG * 72.0 / DPI, ALT * 72.0 / DPI   # página do PDF em pontos

IMAGENS = (".jpg", ".jpeg", ".png", ".gif", ".bmp", ".webp", ".tif", ".tiff")
TEXTOS = (".txt", ".md", ".markdown")
MERMAID = (".mmd", ".mermaid")
PRONTOS = (".azw", ".azw3", ".mobi", ".prc")      # o Kindle já lê: só envia
ACEITOS = IMAGENS + TEXTOS + MERMAID + PRONTOS + (".pdf", ".svg")

MODOS_PDF = {
    "original": "Original (manda o PDF sem mexer)",
    "ampliar": "Ampliar (cortar as margens)",
    "metades": "Dividir ao meio (ler com o Kindle deitado)",
    "texto": "Refazer como texto (só PDFs de texto; precisa do Calibre)",
}

FORMATOS = {
    "azw3": "AZW3 (recomendado)",
    "mobi": "MOBI (para firmwares antigos)",
    "pdf": "PDF",
}
EXT = {"azw3": ".azw3", "mobi": ".mobi", "pdf": ".pdf"}

SEM_JANELA = 0x08000000 if os.name == "nt" else 0


class ConversaoErro(Exception):
    pass


# ------------------------------------------------------------------ util
def recurso(nome):
    """Acha arquivos que vão junto com o programa (também dentro do .exe)."""
    bases = []
    if hasattr(sys, "_MEIPASS"):
        bases.append(sys._MEIPASS)
    bases.append(os.path.dirname(os.path.abspath(__file__)))
    for b in bases:
        for p in (os.path.join(b, nome), os.path.join(b, "vendor", nome), os.path.join(b, "kindle", nome)):
            if os.path.exists(p):
                return p
    raise ConversaoErro("Arquivo do programa não encontrado: " + nome)


def nome_saida(pasta, nome, ext=".pdf"):
    base = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "", nome).strip(" .") or "documento"
    destino = os.path.join(pasta, base + ext)
    n = 2
    while os.path.exists(destino):
        destino = os.path.join(pasta, "%s (%d)%s" % (base, n, ext))
        n += 1
    return destino


# ------------------------------------------------------------------ imagens
def preparar_pagina(img, girar=True, recortar=False):
    """Deixa uma imagem do jeito do Kindle: cinza, de pé e do tamanho da tela."""
    img = ImageOps.exif_transpose(img)
    if img.mode in ("RGBA", "LA", "P"):
        fundo = Image.new("RGBA", img.size, "white")
        fundo.alpha_composite(img.convert("RGBA"))
        img = fundo
    img = img.convert("L")
    if recortar:
        img = cortar_margens(img)
    if girar and img.width > img.height * 1.15:
        img = img.rotate(90, expand=True)       # deitada: gira para ocupar a tela
    k = min(LARG / img.width, ALT / img.height)  # encaixa na tela (amplia ou reduz)
    img = img.resize((max(1, round(img.width * k)), max(1, round(img.height * k))), Image.LANCZOS)
    baixo, alto = img.getextrema()
    if alto - baixo < 200:                      # foto apagada (ex.: papel): realça o contraste
        img = ImageOps.autocontrast(img, cutoff=(1, 3))
    pagina = Image.new("L", (LARG, ALT), 255)
    pagina.paste(img, ((LARG - img.width) // 2, (ALT - img.height) // 2))
    return pagina


def cortar_margens(img, folga=0.02):
    """Recorta o branco em volta do conteúdo."""
    cinza = img.convert("L")
    marca = ImageOps.invert(cinza).point(lambda p: 255 if p > 40 else 0)
    caixa = marca.getbbox()
    if not caixa:
        return img
    fx, fy = int(img.width * folga), int(img.height * folga)
    x0, y0, x1, y1 = caixa
    return img.crop((max(0, x0 - fx), max(0, y0 - fy),
                     min(img.width, x1 + fx), min(img.height, y1 + fy)))


def salvar_paginas(paginas, destino):
    """Grava uma sequência de imagens 600x800 como um PDF do tamanho da tela."""
    doc = fitz.open()
    total = 0
    for pag in paginas:
        buf = io.BytesIO()
        pag.save(buf, "PNG", optimize=True)
        p = doc.new_page(width=PT_L, height=PT_A)
        p.insert_image(p.rect, stream=buf.getvalue())
        total += 1
    if not total:
        raise ConversaoErro("Nada para converter.")
    doc.save(destino, garbage=3, deflate=True)
    doc.close()
    return destino


def imagens_para_livro(caminhos, destino, titulo="Imagens", formato="pdf"):
    def paginas():
        for c in caminhos:
            try:
                with Image.open(c) as im:
                    yield preparar_pagina(im)
            except OSError as e:
                raise ConversaoErro("Não consegui abrir a imagem %s (%s)." % (os.path.basename(c), e))
    return paginas_para_livro(paginas(), destino, titulo, formato)


def paginas_para_livro(paginas, destino, titulo, formato):
    """Páginas 600x800 -> PDF, ou livro AZW3/MOBI com uma imagem de tela cheia por página."""
    if formato == "pdf":
        return salvar_paginas(paginas, destino)
    with tempfile.TemporaryDirectory(prefix="kindleenvia-") as tmp:
        cbz = os.path.join(tmp, "paginas.cbz")
        total = 0
        with zipfile.ZipFile(cbz, "w") as z:
            for i, pag in enumerate(paginas, 1):
                buf = io.BytesIO()
                pag.save(buf, "PNG", optimize=True)
                z.writestr("%04d.png" % i, buf.getvalue())
                total = i
        if not total:
            raise ConversaoErro("Nada para converter.")
        _calibre([cbz, destino, "--no-process", "--dont-add-comic-pages-to-toc"], titulo, formato)
    return destino


# ------------------------------------------------------------------ PDF
def _pagina_em_imagem(pagina, largura_alvo=1400):
    k = largura_alvo / max(pagina.rect.width, 1)
    pix = pagina.get_pixmap(matrix=fitz.Matrix(k, k), colorspace=fitz.csGRAY, alpha=False)
    return Image.frombytes("L", (pix.width, pix.height), pix.samples)


def pdf_para_kindle(origem, destino, modo="ampliar", formato="pdf", titulo=""):
    if modo == "original":
        shutil.copy2(origem, destino)
        return destino
    if modo == "texto":
        if formato == "pdf":
            raise ConversaoErro("Para refazer o PDF como texto, escolha AZW3 ou MOBI na aba Kindle.")
        _calibre([origem, destino], titulo or os.path.splitext(os.path.basename(origem))[0], formato)
        return destino
    try:
        doc = fitz.open(origem)
    except Exception as e:  # noqa: BLE001
        raise ConversaoErro("Não consegui abrir o PDF (%s)." % e)
    if doc.needs_pass:
        raise ConversaoErro("Esse PDF tem senha. Tire a senha antes de converter.")

    def paginas():
        for pagina in doc:
            img = cortar_margens(_pagina_em_imagem(pagina))
            if modo == "metades" and img.height > img.width:
                meio, sobra = img.height // 2, int(img.height * 0.03)
                for parte in (img.crop((0, 0, img.width, meio + sobra)),
                              img.crop((0, meio - sobra, img.width, img.height))):
                    yield preparar_pagina(parte)            # fica deitada: gira sozinha
            else:
                yield preparar_pagina(img)

    try:
        return paginas_para_livro(paginas(), destino,
                                  titulo or os.path.splitext(os.path.basename(origem))[0], formato)
    finally:
        doc.close()


# ------------------------------------------------------------------ Calibre
def achar_calibre():
    """Caminho do ebook-convert do Calibre, ou None."""
    candidatos = []
    for var in ("PROGRAMFILES", "PROGRAMFILES(X86)", "LOCALAPPDATA"):
        raiz = os.environ.get(var)
        if raiz:
            candidatos += [os.path.join(raiz, "Calibre2", "ebook-convert.exe"),
                           os.path.join(raiz, "Calibre", "ebook-convert.exe"),
                           os.path.join(raiz, "Programs", "Calibre2", "ebook-convert.exe")]
    candidatos += [r"C:\Calibre Portable\Calibre\ebook-convert.exe",
                   "/Applications/calibre.app/Contents/MacOS/ebook-convert"]
    achado = shutil.which("ebook-convert")
    if achado:
        candidatos.insert(0, achado)
    for c in candidatos:
        if os.path.isfile(c):
            return c
    return None


def formato_real(formato):
    """AZW3/MOBI precisam do Calibre; sem ele, usa PDF."""
    if formato in ("azw3", "mobi") and not achar_calibre():
        return "pdf"
    return formato if formato in FORMATOS else "azw3"


def _calibre(args, titulo, formato, extras=()):
    exe = achar_calibre()
    if not exe:
        raise ConversaoErro("Não achei o Calibre. Instale em calibre-ebook.com ou escolha PDF na aba Kindle.")
    cmd = [exe] + list(args) + ["--output-profile", "kindle", "--title", titulo or "Documento",
                                "--authors", "Kindle Envia", "--language", "pt"] + list(extras)
    if formato == "mobi":
        cmd += ["--mobi-file-type", "old"]
    try:
        r = subprocess.run(cmd, capture_output=True, timeout=600, creationflags=SEM_JANELA)
    except subprocess.TimeoutExpired:
        raise ConversaoErro("O Calibre demorou demais para converter.")
    destino = args[1]
    if r.returncode != 0 or not os.path.exists(destino):
        saida = (r.stdout + r.stderr).decode("utf-8", "replace").strip().splitlines()
        raise ConversaoErro("O Calibre não conseguiu converter:\n" + "\n".join(saida[-6:]))
    return destino


CSS_LIVRO = """
body { font-family: serif; line-height: 1.35; }
h1 { font-size: 1.6em; margin: 0 0 .6em; page-break-before: always; }
h1.primeiro { page-break-before: avoid; }
h2 { font-size: 1.3em; margin: 1.2em 0 .4em; page-break-after: avoid; }
h3 { font-size: 1.1em; margin: 1em 0 .3em; page-break-after: avoid; }
p { margin: 0 0 .6em; text-indent: 0; }
li { margin-bottom: .3em; }
hr { border: 0; border-top: 1px solid #000; margin: 1em 0; }
.pequeno { font-size: .85em; }
.capa { text-align: center; margin-top: 30%; }
.capa h1 { font-size: 2em; page-break-before: avoid; }
code, pre { font-family: monospace; white-space: pre-wrap; }
"""


def html_para_livro(corpo_html, destino, titulo, formato):
    """HTML -> AZW3/MOBI (Calibre) ou PDF (Edge). O sumário usa os títulos h1 e h2."""
    if formato == "pdf":
        return html_para_pdf(corpo_html, destino, titulo)
    pagina = ("<!doctype html><html lang='pt-BR'><head><meta charset='utf-8'><title>%s</title>"
              "<style>%s</style></head><body>%s</body></html>"
              % (html.escape(titulo), CSS_LIVRO, corpo_html))
    with tempfile.TemporaryDirectory(prefix="kindleenvia-") as tmp:
        arq = os.path.join(tmp, "livro.html")
        with open(arq, "w", encoding="utf-8") as f:
            f.write(pagina)
        _calibre([arq, destino], titulo, formato,
                 ["--level1-toc", "//h:h1", "--level2-toc", "//h:h2", "--chapter", "//h:h1",
                  "--chapter-mark", "none", "--page-breaks-before", "/"])
    return destino


# ------------------------------------------------------------------ navegador
def achar_navegador():
    candidatos = []
    for var in ("PROGRAMFILES(X86)", "PROGRAMFILES", "LOCALAPPDATA"):
        raiz = os.environ.get(var)
        if raiz:
            candidatos += [os.path.join(raiz, "Microsoft", "Edge", "Application", "msedge.exe"),
                           os.path.join(raiz, "Google", "Chrome", "Application", "chrome.exe")]
    for nome in ("msedge", "chrome", "google-chrome", "chromium", "chromium-browser"):
        achado = shutil.which(nome)
        if achado:
            candidatos.append(achado)
    for c in candidatos:
        if os.path.isfile(c):
            return c
    raise ConversaoErro("Não achei o Microsoft Edge nem o Google Chrome. "
                        "Eles são usados para desenhar textos e diagramas.")


def _navegador(args, timeout=120):
    perfil = tempfile.mkdtemp(prefix="kindleenvia-")
    cmd = [achar_navegador(), "--headless=new", "--disable-gpu", "--no-first-run",
           "--no-default-browser-check", "--disable-extensions", "--hide-scrollbars",
           "--user-data-dir=" + perfil] + args
    if hasattr(os, "geteuid") and os.geteuid() == 0:
        cmd.insert(1, "--no-sandbox")
    try:
        r = subprocess.run(cmd, capture_output=True, timeout=timeout, creationflags=SEM_JANELA)
        _navegador.ultimo_erro = r.stderr.decode("utf-8", "replace").strip()[-500:]
        return r.stdout.decode("utf-8", "replace")
    except subprocess.TimeoutExpired:
        raise ConversaoErro("O navegador demorou demais para desenhar o arquivo.")
    finally:
        shutil.rmtree(perfil, ignore_errors=True)


def _url(caminho):
    return pathlib.Path(os.path.abspath(caminho)).as_uri()  # cuida de espaços e acentos


CSS = """
@page { size: 600px 800px; margin: 0; }
html, body { margin: 0; padding: 0; background: #fff; color: #000; }
body { font-family: Georgia, "Times New Roman", serif; font-size: 23px; line-height: 1.4;
       padding: 34px 36px; -webkit-print-color-adjust: exact; }
h1 { font-size: 34px; line-height: 1.15; margin: 0 0 14px; }
h2 { font-size: 28px; line-height: 1.2; margin: 26px 0 10px; break-after: avoid; }
h3 { font-size: 24px; margin: 20px 0 8px; break-after: avoid; }
p { margin: 0 0 12px; text-align: left; }
ul, ol { margin: 0 0 12px; padding-left: 30px; } li { margin-bottom: 6px; }
.pequeno { font-size: 18px; color: #333; }
.capa { display: flex; flex-direction: column; justify-content: center; height: 730px; }
.noticia { break-inside: avoid; margin-bottom: 18px; }
.fonte { font-family: Arial, sans-serif; font-size: 17px; color: #444; text-transform: uppercase;
         letter-spacing: 1px; border-bottom: 2px solid #000; padding-bottom: 4px; margin-top: 24px; }
hr { border: 0; border-top: 2px solid #000; margin: 18px 0; }
code, pre { font-family: Consolas, monospace; font-size: 18px; white-space: pre-wrap; }
.quebra { break-before: page; }
"""


def html_para_pdf(corpo_html, destino, titulo="Documento"):
    """Diagrama um HTML em páginas 600x800 usando o Edge/Chrome invisível."""
    pagina = ("<!doctype html><html lang='pt-BR'><head><meta charset='utf-8'><title>%s</title>"
              "<style>%s</style></head><body>%s</body></html>"
              % (html.escape(titulo), CSS, corpo_html))
    with tempfile.TemporaryDirectory(prefix="kindleenvia-") as tmp:
        arq = os.path.join(tmp, "doc.html")
        with open(arq, "w", encoding="utf-8") as f:
            f.write(pagina)
        saida = os.path.join(tmp, "doc.pdf")
        _navegador(["--no-pdf-header-footer", "--print-to-pdf-no-header",
                    "--print-to-pdf=" + saida, _url(arq)])
        if not os.path.exists(saida) or os.path.getsize(saida) < 200:
            raise ConversaoErro("O navegador (%s) não gerou o PDF. %s"
                                % (os.path.basename(achar_navegador()), getattr(_navegador, "ultimo_erro", "")))
        shutil.move(saida, destino)
    return destino


# ------------------------------------------------------------------ Mermaid e SVG
PAGINA_MERMAID = """<!doctype html><html><head><meta charset="utf-8">
<style>body{margin:0;background:#fff}</style></head><body>
<pre id="codigo" style="display:none">%s</pre><div id="saida"></div>
<script src="%s"></script>
<script>
(async () => {
  const saida = document.getElementById('saida');
  try {
    mermaid.initialize({startOnLoad: false, theme: 'neutral', securityLevel: 'strict',
                        flowchart: {htmlLabels: false}, fontFamily: 'Arial, sans-serif'});
    const codigo = document.getElementById('codigo').textContent;
    const r = await mermaid.render('diagrama', codigo);
    saida.innerHTML = '<div id="pronto">' + r.svg + '</div>';
  } catch (e) {
    saida.innerHTML = '<div id="erro">' + String(e && e.message || e)
      .replace(/&/g,'&amp;').replace(/</g,'&lt;') + '</div>';
  }
})();
</script></body></html>"""


def mermaid_para_svg(codigo):
    """Desenha o Mermaid e devolve o SVG (ConversaoErro com a mensagem, se o código tiver erro)."""
    with tempfile.TemporaryDirectory(prefix="kindleenvia-") as tmp:
        arq = os.path.join(tmp, "m.html")
        with open(arq, "w", encoding="utf-8") as f:
            f.write(PAGINA_MERMAID % (html.escape(codigo), _url(recurso("mermaid.min.js"))))
        dom = _navegador(["--virtual-time-budget=15000", "--allow-file-access-from-files",
                          "--dump-dom", _url(arq)])
    m = re.search(r'<div id="saida"><div id="erro">(.*?)</div>', dom, re.S)
    if m:
        raise ConversaoErro("Erro no diagrama: " + html.unescape(re.sub("<[^>]+>", "", m.group(1)))[:400])
    m = re.search(r'<div id="saida"><div id="pronto">(<svg.*</svg>)</div>', dom, re.S)
    if not m:
        raise ConversaoErro("O diagrama não foi desenhado (o navegador não respondeu a tempo).")
    return m.group(1)


def _tamanho_svg(svg):
    m = re.search(r'viewBox="\s*[-\d.]+[ ,]+[-\d.]+[ ,]+([\d.]+)[ ,]+([\d.]+)', svg)
    if m:
        return float(m.group(1)), float(m.group(2))
    w = re.search(r'\swidth="([\d.]+)', svg)
    h = re.search(r'\sheight="([\d.]+)', svg)
    return (float(w.group(1)) if w else 800.0), (float(h.group(1)) if h else 600.0)


def _pagina_svg(svg, titulo=""):
    """HTML de uma página 600x800 com o SVG encaixado (girado se for deitado)."""
    w, h = _tamanho_svg(svg)
    deitado = w > h * 1.15
    caixa_l, caixa_a = (ALT - 40, LARG - 40) if deitado else (LARG - 40, ALT - 40 - (50 if titulo else 0))
    k = min(caixa_l / w, caixa_a / h)
    abre = re.search(r"<svg\b[^>]*>", svg)
    if not abre:
        raise ConversaoErro("O desenho não é um SVG válido.")
    tag = re.sub(r'\s(width|height|style)="[^"]*"', "", abre.group(0))  # tira max-width do Mermaid
    if "viewBox" not in tag:
        tag = tag.replace("<svg", '<svg viewBox="0 0 %g %g"' % (w, h), 1)
    tag = tag.replace("<svg", '<svg width="%d" height="%d"' % (w * k, h * k), 1)
    svg = svg[:abre.start()] + tag + svg[abre.end():]
    giro = ("position:absolute;left:%dpx;top:%dpx;transform:rotate(-90deg);transform-origin:center;"
            % ((LARG - w * k) / 2, (ALT - h * k) / 2)) if deitado else ""
    cab = "<div style='font:bold 26px Arial,sans-serif;padding:20px 20px 0'>%s</div>" % html.escape(titulo) \
        if titulo and not deitado else ""
    corpo = ("<div style='position:relative;width:600px;height:800px;overflow:hidden'>%s"
             "<div style='%s%s'>%s</div></div>"
             % (cab, giro, "" if deitado else "display:flex;justify-content:center;padding-top:20px", svg))
    return "<style>body{padding:0!important;margin:0}</style>" + corpo


def svg_para_pdf(svg, destino, titulo=""):
    return html_para_pdf(_pagina_svg(svg, titulo), destino, titulo or "Desenho")


def svg_para_imagem(svg, titulo=""):
    """Desenha o SVG numa imagem 600x800 (para ir dentro do livro AZW3/MOBI)."""
    pagina = ("<!doctype html><html><head><meta charset='utf-8'><style>%s</style></head><body>%s</body></html>"
              % (CSS, _pagina_svg(svg, titulo)))
    with tempfile.TemporaryDirectory(prefix="kindleenvia-") as tmp:
        arq = os.path.join(tmp, "s.html")
        with open(arq, "w", encoding="utf-8") as f:
            f.write(pagina)
        png = os.path.join(tmp, "s.png")
        _navegador(["--window-size=600,800", "--screenshot=" + png, _url(arq)])
        if not os.path.exists(png):
            raise ConversaoErro("O navegador não desenhou a imagem. " + getattr(_navegador, "ultimo_erro", ""))
        with Image.open(png) as im:
            img = im.convert("L")
    if img.size != (LARG, ALT):
        img = img.resize((LARG, ALT), Image.LANCZOS)
    return img


def svgs_para_livro(svgs, destino, titulo, formato):
    """Vários SVGs (diagramas/desenhos) -> um arquivo, uma página por desenho."""
    if formato == "pdf":
        final = fitz.open()
        with tempfile.TemporaryDirectory(prefix="kindleenvia-") as tmp:
            for i, svg in enumerate(svgs):
                parcial = os.path.join(tmp, "%d.pdf" % i)
                svg_para_pdf(svg, parcial, titulo if i == 0 else "")
                with fitz.open(parcial) as d:
                    final.insert_pdf(d)
        final.save(destino, garbage=3, deflate=True)
        final.close()
        return destino
    return paginas_para_livro((svg_para_imagem(s, titulo if i == 0 else "") for i, s in enumerate(svgs)),
                              destino, titulo, formato)


# ------------------------------------------------------------------ texto
def _inline(t):
    t = html.escape(t)
    t = re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", t)
    t = re.sub(r"(?<![\*\w])\*(?!\s)(.+?)(?<!\s)\*(?!\w)", r"<i>\1</i>", t)
    t = re.sub(r"`(.+?)`", r"<code>\1</code>", t)
    return t


def markdown_para_html(texto):
    """Markdown simples (títulos, listas, negrito, itálico) para HTML."""
    saida, lista, par = [], None, []

    def fecha_par():
        if par:
            saida.append("<p>%s</p>" % "<br>".join(_inline(l) for l in par))
            par.clear()

    def fecha_lista():
        nonlocal lista
        if lista:
            saida.append("</%s>" % lista)
            lista = None

    for linha in texto.replace("\r\n", "\n").split("\n"):
        s = linha.strip()
        m_tit = re.match(r"^(#{1,3})\s+(.*)", s)
        m_ul = re.match(r"^([-*•]|\[[ xX]\])\s+(.*)", s)
        m_ol = re.match(r"^(\d+)[.)]\s+(.*)", s)
        if not s:
            fecha_par(); fecha_lista()
        elif re.match(r"^(-{3,}|\*{3,}|_{3,})$", s):
            fecha_par(); fecha_lista(); saida.append("<hr>")
        elif m_tit:
            fecha_par(); fecha_lista()
            n = len(m_tit.group(1))
            saida.append("<h%d>%s</h%d>" % (n, _inline(m_tit.group(2)), n))
        elif m_ul or m_ol:
            fecha_par()
            tipo = "ul" if m_ul else "ol"
            if lista != tipo:
                fecha_lista(); saida.append("<%s>" % tipo); lista = tipo
            saida.append("<li>%s</li>" % _inline((m_ul or m_ol).group(2)))
        else:
            fecha_lista(); par.append(s)
    fecha_par(); fecha_lista()
    return "\n".join(saida)


def texto_para_livro(texto, destino, titulo="", formato="pdf"):
    ja_tem_titulo = texto.lstrip().startswith("#")
    corpo = ("<h1>%s</h1>" % html.escape(titulo) if titulo and not ja_tem_titulo else "") \
        + markdown_para_html(texto)
    corpo = corpo.replace("<h1>", "<h1 class='primeiro'>", 1)
    return html_para_livro(corpo, destino, titulo or "Texto", formato)


# ------------------------------------------------------------------ entrada geral
def ler_texto(caminho):
    for cod in ("utf-8-sig", "cp1252", "latin-1"):
        try:
            with open(caminho, encoding=cod) as f:
                return f.read()
        except UnicodeDecodeError:
            continue
    raise ConversaoErro("Não consegui ler o texto de " + os.path.basename(caminho))


def converter(caminho, pasta_saida, modo_pdf="ampliar", formato="azw3"):
    """Converte um arquivo e devolve o caminho do resultado (pronto para o Kindle)."""
    formato = formato_real(formato)
    nome, ext = os.path.splitext(os.path.basename(caminho))
    ext = ext.lower()
    if ext in PRONTOS or (ext == ".pdf" and modo_pdf == "original"):
        destino = nome_saida(pasta_saida, nome, ext)
        shutil.copy2(caminho, destino)
        return destino
    destino = nome_saida(pasta_saida, nome, EXT[formato])
    if ext == ".pdf":
        return pdf_para_kindle(caminho, destino, modo_pdf, formato, nome)
    if ext in IMAGENS:
        return imagens_para_livro([caminho], destino, nome, formato)
    if ext == ".svg":
        return svgs_para_livro([ler_texto(caminho)], destino, nome, formato)
    if ext in MERMAID:
        return svgs_para_livro([mermaid_para_svg(ler_texto(caminho))], destino, nome, formato)
    if ext in TEXTOS:
        return texto_para_livro(ler_texto(caminho), destino, nome, formato)
    raise ConversaoErro("Formato não suportado: %s" % ext)
