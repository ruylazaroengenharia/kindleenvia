"""
Conversa com o servidor.py que roda no Kindle (pelo Wi-Fi).
Se o Kindle não responder, o arquivo vai para a fila de pendentes e é
reenviado depois (ao abrir o programa ou no modo automático).
"""
import concurrent.futures
import json
import os
import re
import shutil
import socket
import time
import uuid
import urllib.error
import urllib.parse
import urllib.request

import config


# O Kindle está na rede local: ignora proxies do sistema (comuns em redes de escritório)
_SEM_PROXY = urllib.request.build_opener(urllib.request.ProxyHandler({}))


class KindleErro(Exception):
    pass


class KindleOffline(KindleErro):
    """O Kindle não respondeu (dormindo, Wi-Fi desligado ou outra rede)."""


def _base(cfg):
    k = cfg["kindle"]
    if not k.get("senha"):
        raise KindleErro("Falta a senha do Kindle. Preencha na aba Kindle.")
    return "http://%s:%s" % (k["ip"].strip(), k.get("porta", 8000)), k["senha"]


def _meus_ips():
    """IPs deste PC nas redes locais (casa, escritório...)."""
    ips = set()
    try:
        for info in socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET):
            ips.add(info[4][0])
    except OSError:
        pass
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("10.255.255.255", 1))
        ips.add(s.getsockname()[0])
        s.close()
    except OSError:
        pass
    privado = re.compile(r"^(192\.168\.|10\.|172\.(1[6-9]|2\d|3[01])\.)")
    return sorted(ip for ip in ips if privado.match(ip))


def _porta_aberta(ip, porta):
    try:
        with socket.create_connection((ip, porta), timeout=0.5):
            return True
    except OSError:
        return False


def descobrir(cfg):
    """Procura o Kindle na rede local: porta do servidor aberta + resposta ao /ping com a senha.
    Devolve o IP encontrado ou None."""
    k = cfg["kindle"]
    porta, senha = int(k.get("porta", 8000)), k.get("senha", "")
    if not senha:
        return None
    candidatos = []
    for meu in _meus_ips():
        base = meu.rsplit(".", 1)[0]
        candidatos += ["%s.%d" % (base, i) for i in range(1, 255) if "%s.%d" % (base, i) != meu]
    if not candidatos:
        return None
    with concurrent.futures.ThreadPoolExecutor(max_workers=64) as ex:
        abertos = [ip for ip, ok in zip(candidatos, ex.map(lambda ip: _porta_aberta(ip, porta), candidatos)) if ok]
    for ip in abertos:
        url = "http://%s:%d/ping?%s" % (ip, porta, urllib.parse.urlencode({"k": senha, "formato": "json"}))
        try:
            with _SEM_PROXY.open(url, timeout=4) as r:
                if json.loads(r.read().decode("utf-8")).get("ok"):
                    return ip
        except (OSError, ValueError):
            continue
    return None


def _pedir(cfg, metodo, rota, params=None, corpo=None, tipo=None, timeout=20, procurar=True):
    """Faz o pedido ao Kindle. Se ele não responder no IP salvo, procura na rede e tenta de novo."""
    try:
        return _pedir_uma_vez(cfg, metodo, rota, params, corpo, tipo, timeout)
    except KindleOffline:
        if not procurar or not cfg["kindle"].get("procurar", True):
            raise
        novo = descobrir(cfg)
        if not novo or novo == cfg["kindle"]["ip"].strip():
            raise
        cfg["kindle"]["ip"] = novo           # achou em outro IP: guarda para as próximas vezes
        config.salvar(cfg)
        return _pedir_uma_vez(cfg, metodo, rota, params, corpo, tipo, timeout)


def _pedir_uma_vez(cfg, metodo, rota, params=None, corpo=None, tipo=None, timeout=20):
    base, senha = _base(cfg)
    q = {"k": senha, "formato": "json"}
    q.update(params or {})
    req = urllib.request.Request(base + rota + "?" + urllib.parse.urlencode(q),
                                 data=corpo, method=metodo)
    if tipo:
        req.add_header("Content-Type", tipo)
    try:
        with _SEM_PROXY.open(req, timeout=timeout) as r:
            return json.loads(r.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        if e.code == 403:
            raise KindleErro("O Kindle recusou a senha. Confira na aba Kindle.")
        if e.code == 404 and rota in ("/listar", "/ping", "/apagar"):
            raise KindleErro("O servidor do Kindle é antigo. Copie o servidor.py novo para D:\\scripts.")
        raise KindleErro("O Kindle respondeu com erro %d." % e.code)
    except (urllib.error.URLError, OSError) as e:
        raise KindleOffline("O Kindle não respondeu em %s e não foi achado na rede (%s). Ele está "
                            "acordado, no Wi-Fi e com o servidor.py ligado?" % (base, getattr(e, "reason", e)))
    except ValueError:
        raise KindleErro("Resposta estranha do Kindle. O servidor.py está atualizado?")


def testar(cfg):
    ip_antes = cfg["kindle"]["ip"].strip()
    r = _pedir(cfg, "GET", "/ping", timeout=8)
    achado = "" if cfg["kindle"]["ip"] == ip_antes else " (achado na rede em %s)" % cfg["kindle"]["ip"]
    return "Conectado%s! Espaço livre no Kindle: %.0f MB" % (achado, r.get("livre", 0) / 1048576.0)


def listar(cfg):
    return _pedir(cfg, "GET", "/listar")


def apagar(cfg, rel):
    return _pedir(cfg, "POST", "/apagar", {"f": rel}, corpo=b"")


def enviar(cfg, arquivos, pasta=""):
    """Envia uma lista de arquivos. Devolve a lista de nomes salvos no Kindle."""
    fronteira = "----KindleEnvia" + uuid.uuid4().hex
    partes = []
    for caminho in arquivos:
        nome = os.path.basename(caminho).replace('"', "'")
        with open(caminho, "rb") as f:
            dados = f.read()
        partes.append(("--%s\r\nContent-Disposition: form-data; name=\"livro\"; filename=\"%s\"\r\n"
                       "Content-Type: application/octet-stream\r\n\r\n"
                       % (fronteira, nome)).encode("utf-8") + dados + b"\r\n")
    corpo = b"".join(partes) + ("--%s--\r\n" % fronteira).encode()
    params = {"pasta": pasta} if pasta else {}
    tempo = 30 + len(corpo) // 50000  # o Wi-Fi do Kindle 4 é lento
    r = _pedir(cfg, "POST", "/enviar", params, corpo,
               "multipart/form-data; boundary=" + fronteira, timeout=tempo)
    if r.get("recusados"):
        raise KindleErro("O Kindle recusou: %s" % ", ".join(r["recusados"]))
    return r.get("enviados", [])


# ------------------------------------------------------------------ pendentes
def _pasta_pendentes():
    p = os.path.join(config.pasta_app(), "pendentes")
    os.makedirs(p, exist_ok=True)
    return p


def enviar_ou_guardar(cfg, arquivos, pasta=""):
    """Tenta enviar; se o Kindle estiver fora do ar, guarda para depois.
    Devolve (enviados, guardou_na_fila)."""
    try:
        return enviar(cfg, arquivos, pasta), False
    except KindleOffline:
        destino = os.path.join(_pasta_pendentes(), pasta or "_")
        os.makedirs(destino, exist_ok=True)
        for a in arquivos:
            shutil.copy2(a, os.path.join(destino, os.path.basename(a)))
        return [], True


def pendentes():
    lista = []
    raiz = _pasta_pendentes()
    for sub in sorted(os.listdir(raiz)):
        d = os.path.join(raiz, sub)
        if os.path.isdir(d):
            for a in sorted(os.listdir(d)):
                lista.append(("" if sub == "_" else sub, os.path.join(d, a)))
    return lista


def enviar_pendentes(cfg):
    """Manda o que ficou na fila. Devolve quantos foram enviados (KindleOffline se não der)."""
    total = 0
    for pasta, caminho in pendentes():
        enviar(cfg, [caminho], pasta)
        os.remove(caminho)
        total += 1
    return total


def limpar_antigos(cfg, pasta, dias):
    """Apaga do Kindle os arquivos de uma subpasta mais velhos que N dias."""
    if not dias or dias <= 0:
        return 0
    limite = time.time() - dias * 86400
    apagados = 0
    for item in listar(cfg):
        rel = item["arquivo"].replace("\\", "/")
        if rel.startswith(pasta + "/") and item.get("modificado", limite) < limite:
            apagar(cfg, rel)
            apagados += 1
    return apagados
