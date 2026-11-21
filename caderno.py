"""Foto do caderno -> IA -> texto, diagrama ou desenho -> PDF para o Kindle."""
import base64
import io

from PIL import Image, ImageOps

import conversor
import ia

SEPARADOR = "\n\n=== próxima página ===\n\n"


def foto_para_b64(caminho, lado=1500):
    """Reduz e passa a foto para cinza (letra de mão continua legível e a IA recebe menos dados)."""
    with Image.open(caminho) as im:
        im = ImageOps.exif_transpose(im).convert("L")
        im.thumbnail((lado, lado), Image.LANCZOS)
        im = ImageOps.autocontrast(im, cutoff=(1, 2))
        buf = io.BytesIO()
        im.save(buf, "PNG", optimize=True)
    return base64.b64encode(buf.getvalue()).decode("ascii")


def ler_fotos(caminhos, modo, extra="", cfg=None, aviso=None):
    """Manda cada foto para a IA. Devolve o conteúdo (Markdown, Mermaid ou SVG) para revisar."""
    partes = []
    for i, c in enumerate(caminhos, 1):
        if aviso:
            aviso("Lendo a foto %d de %d com a IA..." % (i, len(caminhos)))
        b64 = foto_para_b64(c)
        resultado = ia.caderno(modo, b64, extra, cfg)
        if modo == "diagrama":                      # confere se o diagrama desenha; se não, pede correção
            for _tentativa in range(2):
                try:
                    conversor.mermaid_para_svg(resultado)
                    break
                except conversor.ConversaoErro as e:
                    if aviso:
                        aviso("O diagrama veio com erro; pedindo correção à IA...")
                    resultado = ia.caderno(modo, b64, extra, cfg, codigo=resultado, erro=str(e))
        partes.append(resultado.strip())
    return SEPARADOR.join(partes)


def gerar(conteudo, modo, titulo, pasta_saida, formato="azw3"):
    """Transforma o conteúdo (já revisado) num arquivo para o Kindle (AZW3, MOBI ou PDF)."""
    formato = conversor.formato_real(formato)
    destino = conversor.nome_saida(pasta_saida, titulo or "Caderno", conversor.EXT[formato])
    if modo in ("texto", "resumo"):
        texto = conteudo.replace(SEPARADOR.strip(), "---")
        return conversor.texto_para_livro(texto, destino, titulo, formato)
    blocos = [b.strip() for b in conteudo.split(SEPARADOR.strip()) if b.strip()]
    if not blocos:
        raise conversor.ConversaoErro("Não há nada para converter.")
    svgs = [conversor.mermaid_para_svg(b) if modo == "diagrama" else b for b in blocos]
    return conversor.svgs_para_livro(svgs, destino, titulo or "Caderno", formato)
