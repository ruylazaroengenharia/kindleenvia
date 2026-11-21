"""Configuração do Kindle Envia (fica em %APPDATA%\\KindleEnvia\\config.json)."""
import copy
import json
import os

FONTES_SUGERIDAS = [
    # nome, endereço do RSS, ligado?
    ["G1", "https://g1.globo.com/rss/g1/", True],
    ["BBC News Brasil", "https://feeds.bbci.co.uk/portuguese/rss.xml", True],
    ["Agência Brasil", "https://agenciabrasil.ebc.com.br/rss/ultimasnoticias/feed.xml", True],
    ["Folha - Em cima da hora", "https://feeds.folha.uol.com.br/emcimadahora/rss091.xml", False],
    ["Tecnoblog", "https://tecnoblog.net/feed/", False],
]

PADRAO = {
    "kindle": {"ip": "192.168.15.16", "porta": 8000, "senha": "", "formato": "azw3"},
    "arquivos": {"modo_pdf": "ampliar"},
    "caderno": {"modo": "texto"},
    "noticias": {
        "fontes": FONTES_SUGERIDAS,
        "por_fonte": 6,
        "resumo_ia": True,
        "manter_dias": 3,
        "auto": False,
        "ultimo_envio": "",
    },
}


def pasta_app():
    if os.name == "nt":
        base = os.environ.get("APPDATA") or os.path.expanduser("~")
    else:
        base = os.path.expanduser("~/.config")
    return os.path.join(base, "KindleEnvia")


def pasta_saida():
    """Onde ficam as cópias convertidas (para conferir ou mandar de novo)."""
    docs = os.path.join(os.path.expanduser("~"), "Documents")
    if not os.path.isdir(docs):
        docs = os.path.expanduser("~")
    p = os.path.join(docs, "KindleEnvia")
    os.makedirs(p, exist_ok=True)
    return p


def caminho():
    return os.path.join(pasta_app(), "config.json")


def _mesclar(base, novo):
    for k, v in novo.items():
        if isinstance(v, dict) and isinstance(base.get(k), dict):
            _mesclar(base[k], v)
        else:
            base[k] = v


def carregar():
    cfg = copy.deepcopy(PADRAO)
    try:
        with open(caminho(), encoding="utf-8") as f:
            _mesclar(cfg, json.load(f))
    except (OSError, ValueError):
        pass
    return cfg


def salvar(cfg):
    os.makedirs(pasta_app(), exist_ok=True)
    tmp = caminho() + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(cfg, f, ensure_ascii=False, indent=2)
    os.replace(tmp, caminho())
