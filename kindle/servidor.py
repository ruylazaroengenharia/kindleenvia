# -*- coding: utf-8 -*-
"""
Servidor de livros para Kindle 4 (FW 4.x com jailbreak + Python 3 do NiLuJe).

Abra no navegador do celular ou do PC, na mesma rede Wi-Fi:
    http://IP-DO-KINDLE:8000

- Lista e baixa os livros do Kindle
- Envia livros para o Kindle (vão para documents/ e aparecem na biblioteca)
- Telas de descanso: vê, envia (já ajustadas para 600x800 em cinza) e apaga
- Edita as frases do painel (frases.txt)

Para programas (ex.: Kindle Envia no PC), acrescente &formato=json:
    POST /enviar?k=SENHA&formato=json[&pasta=Noticias]  campo "livro" (multipart)
    GET  /listar?k=SENHA                                 lista em JSON
    POST /apagar?k=SENHA&f=caminho/relativo.pdf          apaga um arquivo
    POST /telas/enviar?k=SENHA&formato=json              campo "imagem" (PNG/JPG 600x800)

Uso (pelo SSH):
    python3 /mnt/us/scripts/servidor.py           roda na tela (Ctrl+C para parar)
    python3 /mnt/us/scripts/servidor.py --fundo   roda em segundo plano (log em servidor.log)
    pkill -f servidor.py                          para
"""

import html
import json
import os
import re
import shutil
import signal
import subprocess
import sys
from http.server import BaseHTTPRequestHandler, HTTPServer
from urllib.parse import parse_qs, quote, urlparse

# ---------------------------------------------------------------- ajustes ---
PORTA = 8000
# Troque por uma senha sua. Quem estiver na mesma rede só entra com ela.
SENHA = "troque-esta-senha"
PASTA_LIVROS = os.environ.get("KINDLE_DOCS", "/mnt/us/documents")
# Tipos que o leitor da Amazon do Kindle 4 abre (EPUB não, por isso fica de fora)
EXTENSOES = (".azw", ".azw3", ".mobi", ".prc", ".pdf", ".txt")
# Pasta do ScreenSavers Hack e frases do painel
PASTA_TELAS = os.environ.get("KINDLE_TELAS", "/mnt/us/linkss/screensavers")
FRASES = os.path.join(os.path.dirname(os.path.abspath(__file__)), "frases.txt")
# ----------------------------------------------------------------------------

IMAGENS = (".png", ".jpg", ".jpeg")


def inicio_automatico():
    return os.path.exists("/etc/rc5.d/S99kindleenvia")
TIPOS_IMG = {".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg"}

BLOCO = 64 * 1024


def rodar(cmd):
    """Roda um comando do sistema, sem quebrar se ele não existir (ex.: no PC)."""
    try:
        return subprocess.call(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except OSError:
        return -1


def abrir_porta():
    rodar(["iptables", "-A", "INPUT", "-p", "tcp", "--dport", str(PORTA), "-j", "ACCEPT"])


def fechar_porta():
    rodar(["iptables", "-D", "INPUT", "-p", "tcp", "--dport", str(PORTA), "-j", "ACCEPT"])


def atualizar_biblioteca():
    # Faz o leitor da Amazon perceber os livros novos sem reiniciar
    rodar(["dbus-send", "--system", "/default", "com.lab126.powerd.resuming", "int32:1"])


def nome_seguro(nome):
    nome = nome.replace("\\", "/").split("/")[-1]
    nome = re.sub(r'[\x00-\x1f<>:"|?*]', "", nome).strip(" .")
    return nome[:150]


def pasta_segura(nome):
    """Só aceita uma subpasta simples dentro de documents (ex.: "Noticias")."""
    nome = re.sub(r'[\x00-\x1f<>:"|?*/\\]', "", nome or "").strip(" .")
    if not nome:
        return PASTA_LIVROS
    pasta = os.path.join(PASTA_LIVROS, nome[:60])
    os.makedirs(pasta, exist_ok=True)
    return pasta


def dentro_dos_livros(rel):
    base = os.path.realpath(PASTA_LIVROS)
    alvo = os.path.realpath(os.path.join(base, rel))
    return alvo if alvo.startswith(base + os.sep) else None


def caminho_livre(pasta, nome):
    base, ext = os.path.splitext(nome)
    destino = os.path.join(pasta, nome)
    n = 2
    while os.path.exists(destino):
        destino = os.path.join(pasta, "%s (%d)%s" % (base, n, ext))
        n += 1
    return destino


def listar_livros():
    livros = []
    for raiz, pastas, arquivos in os.walk(PASTA_LIVROS):
        pastas[:] = sorted(p for p in pastas if not p.endswith(".sdr") and not p.startswith("."))
        for a in sorted(arquivos):
            if a.lower().endswith(EXTENSOES):
                completo = os.path.join(raiz, a)
                rel = os.path.relpath(completo, PASTA_LIVROS)
                livros.append((rel, os.path.getsize(completo), int(os.path.getmtime(completo))))
    return livros


def tamanho(n):
    for unidade in ("B", "KB", "MB", "GB"):
        if n < 1024 or unidade == "GB":
            return ("%.0f %s" if unidade == "B" else "%.1f %s") % (n, unidade)
        n /= 1024.0


ESTILO = """
body{font-family:system-ui,sans-serif;max-width:640px;margin:0 auto;padding:16px;color:#222}
h1{font-size:1.4em} h2{font-size:1.1em;margin-top:1.6em}
.caixa{border:1px solid #ccc;border-radius:8px;padding:12px;margin:12px 0}
ul{list-style:none;padding:0} li{padding:8px 0;border-bottom:1px solid #eee}
li small{color:#777} a{color:#0645ad;word-break:break-word}
button,input[type=submit]{font-size:1em;padding:8px 16px;margin-top:8px}
.ok{background:#e8f5e9;border-color:#a5d6a7} .erro{background:#ffebee;border-color:#ef9a9a}
nav a{margin-right:14px} select,textarea{font-size:1em;max-width:100%}
.grade{display:flex;flex-wrap:wrap;gap:10px} .tela{width:120px;text-align:center;font-size:.8em}
.tela img,.mini{width:120px;height:160px;border:1px solid #999;display:block;margin-bottom:4px}
.tela form{display:inline} .tela button{font-size:.85em;padding:2px 8px;margin:0}
#previa{display:flex;flex-wrap:wrap;gap:8px;margin-top:8px}
"""


def listar_telas():
    try:
        return sorted(a for a in os.listdir(PASTA_TELAS) if a.lower().endswith(IMAGENS))
    except OSError:
        return []


TELAS_JS = r"""
<script>
const K = '__K__';
const fila = [];
function opcoes() {
  return {encaixe: document.getElementById('encaixe').value,
          rodape: document.getElementById('rodape').checked};
}
function carregar(arq) {
  return new Promise((ok, erro) => {
    const img = new Image();
    img.onload = () => ok(img);
    img.onerror = () => erro(new Error('não consegui abrir ' + arq.name));
    img.src = URL.createObjectURL(arq);
  });
}
async function preparar(arq) {
  const img = await carregar(arq);
  const o = opcoes();
  const c = document.createElement('canvas');
  c.width = 600; c.height = 800;
  const g = c.getContext('2d');
  g.fillStyle = '#fff'; g.fillRect(0, 0, 600, 800);
  let w = img.naturalWidth, h = img.naturalHeight;
  const deitada = w > h * 1.15;
  const areaA = o.rodape ? 650 : 800;           // deixa o rodapé livre para a frase do painel
  g.save();
  if (o.encaixe === 'girar' && deitada) {        // gira 90° para ocupar a tela
    g.translate(300, areaA / 2); g.rotate(-Math.PI / 2); g.translate(-areaA / 2, -300);
    const k = Math.max(areaA / w, 600 / h);
    g.drawImage(img, (areaA - w * k) / 2, (600 - h * k) / 2, w * k, h * k);
  } else {
    const k = o.encaixe === 'inteira' ? Math.min(600 / w, areaA / h) : Math.max(600 / w, areaA / h);
    g.beginPath(); g.rect(0, 0, 600, areaA); g.clip();
    g.drawImage(img, (600 - w * k) / 2, (areaA - h * k) / 2, w * k, h * k);
  }
  g.restore();
  const d = g.getImageData(0, 0, 600, 800), p = d.data;
  for (let i = 0; i < p.length; i += 4) {        // tons de cinza
    const y = 0.299 * p[i] + 0.587 * p[i + 1] + 0.114 * p[i + 2];
    p[i] = p[i + 1] = p[i + 2] = y;
  }
  g.putImageData(d, 0, 0);
  URL.revokeObjectURL(img.src);
  return c;
}
async function escolher(ev) {
  const prev = document.getElementById('previa');
  prev.innerHTML = ''; fila.length = 0;
  for (const arq of ev.target.files) {
    try {
      const c = await preparar(arq);
      const nome = arq.name.replace(/\.[^.]+$/, '') + '.png';
      fila.push({nome, c});
      c.className = 'mini'; c.title = nome;
      prev.appendChild(c);
    } catch (e) { alert(e.message); }
  }
  document.getElementById('enviar').disabled = !fila.length;
}
async function refazer() {
  const ent = document.getElementById('arquivos');
  if (ent.files.length) await escolher({target: ent});
}
async function enviar() {
  const st = document.getElementById('estado');
  document.getElementById('enviar').disabled = true;
  for (let i = 0; i < fila.length; i++) {
    st.textContent = 'Enviando ' + (i + 1) + ' de ' + fila.length + '...';
    const blob = await new Promise(ok => fila[i].c.toBlob(ok, 'image/png'));
    const fd = new FormData(); fd.append('imagem', blob, fila[i].nome);
    const r = await fetch('/telas/enviar?formato=json&k=' + encodeURIComponent(K), {method: 'POST', body: fd});
    if (!r.ok) { st.textContent = 'Erro ao enviar ' + fila[i].nome; return; }
  }
  location.href = '/telas?ok=1&k=' + encodeURIComponent(K);
}
</script>
"""


def pagina(titulo, corpo):
    return ("<!doctype html><html lang='pt-BR'><head><meta charset='utf-8'>"
            "<meta name='viewport' content='width=device-width,initial-scale=1'>"
            "<title>%s</title><style>%s</style></head><body>%s</body></html>"
            % (html.escape(titulo), ESTILO, corpo)).encode("utf-8")


class Kindle(BaseHTTPRequestHandler):
    server_version = "KindleLivros/1.0"

    def log_message(self, formato, *args):
        sys.stderr.write("%s - %s\n" % (self.address_string(), formato % args))

    # ------------------------------------------------------------ util ---
    def responder(self, codigo, conteudo, tipo="text/html; charset=utf-8"):
        self.send_response(codigo)
        self.send_header("Content-Type", tipo)
        self.send_header("Content-Length", str(len(conteudo)))
        self.end_headers()
        self.wfile.write(conteudo)

    def json(self, codigo, dados):
        self.responder(codigo, json.dumps(dados, ensure_ascii=False).encode("utf-8"),
                       "application/json; charset=utf-8")

    def menu(self):
        k = quote(SENHA)
        return ("<nav><a href='/?k=%s'>📚 Livros</a><a href='/telas?k=%s'>🖼️ Telas de descanso</a></nav>"
                % (k, k))

    def senha_ok(self, consulta):
        return consulta.get("k", [""])[0] == SENHA

    def tela_senha(self, erro=False):
        aviso = "<p class='caixa erro'>Senha errada.</p>" if erro else ""
        corpo = ("<h1>📚 Kindle</h1>%s<form method='get' action='/'>"
                 "<input type='password' name='k' placeholder='Senha' autofocus> "
                 "<input type='submit' value='Entrar'></form>" % aviso)
        self.responder(403 if erro else 200, pagina("Kindle", corpo))

    # ------------------------------------------------------------- GET ---
    def do_GET(self):
        url = urlparse(self.path)
        consulta = parse_qs(url.query)
        if not self.senha_ok(consulta):
            if url.path in ("/listar", "/ping"):
                return self.json(403, {"erro": "senha errada"})
            return self.tela_senha(erro="k" in consulta)
        if url.path == "/ping":
            livre = shutil.disk_usage(PASTA_LIVROS).free
            return self.json(200, {"ok": True, "livre": livre})
        if url.path == "/listar":
            return self.json(200, [{"arquivo": r, "tamanho": t, "modificado": m}
                                   for r, t, m in listar_livros()])
        if url.path == "/baixar":
            return self.baixar(consulta.get("f", [""])[0])
        if url.path == "/telas":
            return self.telas(consulta)
        if url.path == "/telas/img":
            return self.imagem_tela(consulta.get("f", [""])[0])
        return self.inicio(consulta)

    # ---------------------------------------------------- telas de descanso ---
    def telas(self, consulta, mensagem=""):
        k = quote(SENHA)
        if consulta.get("ok"):
            mensagem = ("<p class='caixa ok'>✅ Enviado! As imagens novas aparecem depois que o "
                        "Kindle reiniciar.</p>")
        if consulta.get("salvo"):
            mensagem = "<p class='caixa ok'>✅ Frases salvas. Valem a partir do próximo sono do Kindle.</p>"
        nomes = listar_telas()
        if not os.path.isdir(PASTA_TELAS):
            grade = "<p class='caixa erro'>Não achei a pasta %s. O ScreenSavers Hack está instalado?</p>" \
                    % html.escape(PASTA_TELAS)
        else:
            grade = "<div class='grade'>%s</div>" % ("".join(
                "<div class='tela'><img loading='lazy' src='/telas/img?k=%s&f=%s' alt=''>%s<br>"
                "<form method='post' action='/telas/apagar?k=%s&f=%s' "
                "onsubmit=\"return confirm('Apagar esta imagem do Kindle?')\">"
                "<button>Apagar</button></form></div>"
                % (k, quote(n), html.escape(n), k, quote(n)) for n in nomes) or "<p>Nenhuma imagem.</p>")
        try:
            with open(FRASES, encoding="utf-8") as f:
                frases = f.read()
        except OSError:
            frases = ""
        corpo = (
            self.menu() + "<h1>🖼️ Telas de descanso</h1>%s"
            "<div class='caixa'><h2 style='margin-top:0'>Enviar imagens</h2>"
            "<p><small>As fotos são ajustadas aqui no navegador: 600×800, em tons de cinza.</small></p>"
            "<label>Encaixe: <select id='encaixe' onchange='refazer()'>"
            "<option value='preencher'>Preencher a tela (corta as sobras)</option>"
            "<option value='inteira'>Imagem inteira (com faixas brancas)</option>"
            "<option value='girar'>Girar as deitadas e preencher</option></select></label><br>"
            "<label><input type='checkbox' id='rodape' onchange='refazer()' checked> "
            "Deixar o rodapé livre para a frase do painel</label><br><br>"
            "<input type='file' id='arquivos' accept='image/*' multiple onchange='escolher(event)'>"
            "<div id='previa'></div>"
            "<button id='enviar' disabled onclick='enviar()'>Enviar ao Kindle</button> "
            "<span id='estado'></span></div>"
            "<h2>No Kindle (%d)</h2><p><small>Mostradas em ordem alfabética, uma por vez a cada sono. "
            "Imagens novas ou apagadas só valem depois de reiniciar o Kindle.</small></p>%s"
            "<form method='post' action='/reiniciar?k=%s' onsubmit=\"return confirm("
            "'Reiniciar o Kindle agora? %s')\">"
            "<button>🔄 Reiniciar o Kindle</button></form>"
            "<div class='caixa'><h2 style='margin-top:0'>Frases do painel</h2>"
            "<form method='post' action='/frases?k=%s'>"
            "<textarea name='texto' rows='8' style='width:100%%'>%s</textarea><br>"
            "<small>Uma frase por linha. O painel troca uma por dia.</small><br>"
            "<button>Salvar frases</button></form></div>"
            % (mensagem, len(nomes), grade, k,
               "O servidor e o painel voltam sozinhos." if inicio_automatico()
               else "O servidor e o painel param e precisam ser ligados de novo pelo SSH.",
               k, html.escape(frases))
        ) + TELAS_JS.replace("__K__", SENHA.replace("\\", "\\\\").replace("'", "\\'"))
        self.responder(200, pagina("Telas de descanso", corpo))

    def imagem_tela(self, nome):
        nome = os.path.basename(nome)
        alvo = os.path.join(PASTA_TELAS, nome)
        if not nome.lower().endswith(IMAGENS) or not os.path.isfile(alvo):
            return self.responder(404, pagina("Kindle", "<p>Imagem não encontrada.</p>"))
        with open(alvo, "rb") as f:
            dados = f.read()
        self.responder(200, dados, TIPOS_IMG[os.path.splitext(nome)[1].lower()])

    def inicio(self, consulta, mensagem=""):
        k = quote(SENHA)
        itens = "".join(
            "<li><a href='/baixar?k=%s&f=%s'>%s</a><br><small>%s</small></li>"
            % (k, quote(rel), html.escape(rel), tamanho(t))
            for rel, t, _m in listar_livros()
        ) or "<li>Nenhum livro encontrado.</li>"
        corpo = (
            self.menu() +
            "<h1>📚 Kindle</h1>%s"
            "<div class='caixa'><h2 style='margin-top:0'>Enviar para o Kindle</h2>"
            "<form method='post' action='/enviar?k=%s' enctype='multipart/form-data'>"
            "<input type='file' name='livro' multiple accept='%s'><br>"
            "<input type='submit' value='Enviar'></form>"
            "<small>Formatos: %s. EPUB não abre no leitor da Amazon: converta no Calibre antes.</small></div>"
            "<h2>Livros no Kindle</h2><ul>%s</ul>"
            % (mensagem, k, ",".join(EXTENSOES), " ".join(EXTENSOES), itens)
        )
        self.responder(200, pagina("Kindle", corpo))

    def baixar(self, rel):
        alvo = dentro_dos_livros(rel)
        if not alvo or not os.path.isfile(alvo):
            return self.responder(404, pagina("Kindle", "<p>Arquivo não encontrado.</p>"))
        nome = os.path.basename(alvo)
        self.send_response(200)
        self.send_header("Content-Type", "application/octet-stream")
        self.send_header("Content-Length", str(os.path.getsize(alvo)))
        self.send_header("Content-Disposition", "attachment; filename*=UTF-8''%s" % quote(nome))
        self.end_headers()
        with open(alvo, "rb") as f:
            while True:
                dados = f.read(BLOCO)
                if not dados:
                    break
                self.wfile.write(dados)

    # ------------------------------------------------------------ POST ---
    def do_POST(self):
        url = urlparse(self.path)
        consulta = parse_qs(url.query)
        em_json = consulta.get("formato", [""])[0] == "json"
        if not self.senha_ok(consulta):
            if em_json or url.path == "/apagar":
                return self.json(403, {"erro": "senha errada"})
            return self.tela_senha(erro=True)
        if url.path == "/apagar":
            return self.apagar(consulta.get("f", [""])[0])
        if url.path == "/telas/apagar":
            return self.apagar_tela(consulta)
        if url.path == "/frases":
            return self.salvar_frases(consulta)
        if url.path == "/reiniciar":
            volta = ("O servidor e o painel voltam sozinhos em cerca de 2 minutos." if inicio_automatico()
                     else "Depois ligue o servidor e o painel de novo pelo SSH.")
            corpo = self.menu() + "<p class='caixa ok'>🔄 Reiniciando o Kindle... %s</p>" % volta
            self.responder(200, pagina("Kindle", corpo))
            subprocess.Popen(["sh", "-c", "sleep 3; reboot"])
            return
        if url.path not in ("/enviar", "/telas/enviar"):
            return self.responder(404, pagina("Kindle", "<p>Não encontrado.</p>"))
        tipo = self.headers.get("Content-Type", "")
        m = re.search(r'boundary="?([^";]+)"?', tipo)
        if "multipart/form-data" not in tipo or not m:
            if em_json:
                return self.json(400, {"erro": "envio inválido"})
            return self.responder(400, pagina("Kindle", "<p>Envio inválido.</p>"))
        try:
            if url.path == "/telas/enviar":
                os.makedirs(PASTA_TELAS, exist_ok=True)
                pasta, tipos = PASTA_TELAS, IMAGENS
            else:
                pasta, tipos = pasta_segura(consulta.get("pasta", [""])[0]), EXTENSOES
            salvos, recusados = self.receber(m.group(1).encode("latin-1"), pasta, tipos)
        except Exception as e:  # noqa: BLE001 - mostrar qualquer falha na página
            if em_json:
                return self.json(500, {"erro": str(e)})
            msg = "<p class='caixa erro'>Erro no envio: %s</p>" % html.escape(str(e))
            return self.inicio(consulta, msg)
        if salvos and url.path == "/enviar":
            atualizar_biblioteca()
        if em_json:
            return self.json(200, {"enviados": salvos, "recusados": recusados})
        partes = []
        if salvos:
            partes.append("<p class='caixa ok'>✅ Enviado: %s</p>"
                          % ", ".join(html.escape(s) for s in salvos))
        if recusados:
            partes.append("<p class='caixa erro'>Ignorado (formato não aceito): %s</p>"
                          % ", ".join(html.escape(r) for r in recusados))
        self.inicio(consulta, "".join(partes))

    def apagar(self, rel):
        alvo = dentro_dos_livros(rel)
        if not alvo or not os.path.isfile(alvo):
            return self.json(404, {"erro": "arquivo não encontrado"})
        os.remove(alvo)
        sdr = os.path.splitext(alvo)[0] + ".sdr"  # anotações do leitor da Amazon
        if os.path.isdir(sdr):
            shutil.rmtree(sdr, ignore_errors=True)
        atualizar_biblioteca()
        return self.json(200, {"apagado": rel})

    def apagar_tela(self, consulta):
        nome = os.path.basename(consulta.get("f", [""])[0])
        alvo = os.path.join(PASTA_TELAS, nome)
        if nome.lower().endswith(IMAGENS) and os.path.isfile(alvo):
            os.remove(alvo)
        self.redirecionar("/telas?k=%s" % quote(SENHA))

    def salvar_frases(self, consulta):
        tamanho_corpo = int(self.headers.get("Content-Length", 0))
        if tamanho_corpo > 200000:
            return self.responder(413, pagina("Kindle", "<p>Texto grande demais.</p>"))
        dados = parse_qs(self.rfile.read(tamanho_corpo).decode("utf-8", "replace"))
        texto = dados.get("texto", [""])[0].replace("\r\n", "\n").strip() + "\n"
        with open(FRASES, "w", encoding="utf-8") as f:
            f.write(texto)
        self.redirecionar("/telas?salvo=1&k=%s" % quote(SENHA))

    def redirecionar(self, destino):
        self.send_response(303)
        self.send_header("Location", destino)
        self.send_header("Content-Length", "0")
        self.end_headers()

    def receber(self, boundary, pasta, tipos=EXTENSOES):
        """Lê o multipart direto do socket para o disco (sem usar a /tmp pequena do Kindle)."""
        restante = int(self.headers.get("Content-Length", 0))

        def ler():
            nonlocal restante
            if restante <= 0:
                return b""
            dados = self.rfile.read(min(BLOCO, restante))
            restante -= len(dados)
            return dados

        sep = b"\r\n--" + boundary
        guarda = len(sep) - 1
        buf = b"\r\n"
        salvos, recusados = [], []

        # pula até o primeiro separador
        while True:
            i = buf.find(sep)
            if i >= 0:
                buf = buf[i + len(sep):]
                break
            dados = ler()
            if not dados:
                return salvos, recusados
            buf = buf[-guarda:] + dados

        while True:
            while len(buf) < 2:
                dados = ler()
                if not dados:
                    return salvos, recusados
                buf += dados
            if buf[:2] == b"--":  # fim do envio
                return salvos, recusados

            while b"\r\n\r\n" not in buf:
                dados = ler()
                if not dados:
                    return salvos, recusados
                buf += dados
                if len(buf) > 32768:
                    raise ValueError("cabeçalho grande demais")
            fim = buf.index(b"\r\n\r\n")
            cabecalho = buf[2:fim].decode("utf-8", "replace")
            buf = buf[fim + 4:]

            m = re.search(r'filename="([^"]*)"', cabecalho)
            nome = nome_seguro(m.group(1)) if m else ""
            saida, temp, destino = None, None, None
            if nome:
                if nome.lower().endswith(tipos):
                    destino = caminho_livre(pasta, nome)
                    temp = destino + ".parcial"
                    saida = open(temp, "wb")
                else:
                    recusados.append(nome)

            try:
                while True:
                    i = buf.find(sep)
                    if i >= 0:
                        if saida:
                            saida.write(buf[:i])
                        buf = buf[i + len(sep):]
                        break
                    if len(buf) > guarda:
                        if saida:
                            saida.write(buf[:-guarda])
                        buf = buf[-guarda:]
                    dados = ler()
                    if not dados:
                        raise ValueError("envio interrompido")
                    buf += dados
            except Exception:
                if saida:
                    saida.close()
                    os.remove(temp)
                raise
            if saida:
                saida.close()
                os.rename(temp, destino)
                salvos.append(os.path.basename(destino))


def ir_para_fundo(log):
    """Roda em segundo plano sem depender do nohup (que o Kindle 4 não tem)."""
    if os.fork() > 0:
        os._exit(0)
    os.setsid()
    if os.fork() > 0:
        os._exit(0)
    signal.signal(signal.SIGHUP, signal.SIG_IGN)
    saida = os.open(log, os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o644)
    nulo = os.open(os.devnull, os.O_RDONLY)
    os.dup2(nulo, 0)
    os.dup2(saida, 1)
    os.dup2(saida, 2)
    sys.stdout = os.fdopen(1, "w", buffering=1)
    sys.stderr = os.fdopen(2, "w", buffering=1)


def principal():
    if SENHA == "troque-esta-senha":
        print("Aviso: troque a SENHA no começo do arquivo antes de usar na rede do trabalho.")
    os.makedirs(PASTA_LIVROS, exist_ok=True)
    if "--fundo" in sys.argv:
        ir_para_fundo(os.path.join(os.path.dirname(os.path.abspath(__file__)), "servidor.log"))
    abrir_porta()

    def sair(*_):
        raise KeyboardInterrupt

    signal.signal(signal.SIGTERM, sair)
    servidor = HTTPServer(("0.0.0.0", PORTA), Kindle)
    print("Servidor no ar: http://IP-DO-KINDLE:%d  (Ctrl+C para parar)" % PORTA)
    try:
        servidor.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        servidor.server_close()
        fechar_porta()
        print("Servidor parado.")


if __name__ == "__main__":
    principal()
