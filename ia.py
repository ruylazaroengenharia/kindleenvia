"""
Integração com IA (vem do Quadro Branco, com os pedidos do Kindle Envia no fim).
Provedores: Ollama (local e grátis), Claude (Anthropic) e OpenAI ou compatível
(Groq, OpenRouter, LM Studio, Gemini etc.). Só usa a biblioteca padrão.
"""
import json
import os
import re
import urllib.error
import urllib.request

PROVEDORES = {
    "ollama": {"nome": "Ollama (grátis, roda no seu PC)",
               "url": "http://localhost:11434", "modelo": "qwen2.5:7b", "chave": False,
               "visao": "qwen2.5vl:7b"},
    "claude": {"nome": "Claude (Anthropic)",
               "url": "https://api.anthropic.com", "modelo": "claude-sonnet-5-5", "chave": True},
    "openai": {"nome": "OpenAI ou compatível (Groq, OpenRouter, LM Studio...)",
               "url": "https://api.openai.com/v1", "modelo": "gpt-4.1-mini", "chave": True},
}


class IAErro(Exception):
    pass


# ------------------------------------------------------------------ config
def _base_config():
    if os.name == "nt":
        return os.environ.get("APPDATA") or os.path.expanduser("~")
    return os.path.expanduser("~/.config")


def config_path():
    return os.path.join(_base_config(), "KindleEnvia", "ia.json")


def carregar():
    cfg = {"provedor": "ollama"}
    # na primeira vez, aproveita a IA já configurada no Quadro Branco
    for caminho in (config_path(), os.path.join(_base_config(), "QuadroBranco", "config.json")):
        try:
            with open(caminho, encoding="utf-8") as f:
                cfg.update(json.load(f))
            break
        except (OSError, ValueError):
            continue
    for p, d in PROVEDORES.items():
        c = cfg.setdefault(p, {})
        c.setdefault("url", d["url"])
        c.setdefault("modelo", d["modelo"])
        c.setdefault("chave", "")
        c.setdefault("visao", d.get("visao", ""))
    if cfg["provedor"] not in PROVEDORES:
        cfg["provedor"] = "ollama"
    return cfg


def salvar(cfg):
    path = config_path()
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(cfg, f, ensure_ascii=False, indent=2)


# ------------------------------------------------------------------ HTTP
def _req(url, body=None, headers=None, timeout=300):
    data = json.dumps(body).encode() if body is not None else None
    h = {"Content-Type": "application/json"}
    h.update(headers or {})
    req = urllib.request.Request(url, data=data, headers=h)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return json.loads(r.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        txt = e.read().decode("utf-8", "replace")
        try:
            j = json.loads(txt)
            err = j.get("error")
            txt = (err.get("message") if isinstance(err, dict) else err) or txt
        except ValueError:
            pass
        if e.code in (401, 403):
            raise IAErro("A chave da API foi recusada. Confira a chave na aba IA do programa.")
        if e.code == 404 and "model" in str(txt).lower():
            raise IAErro(f"Modelo não encontrado: {txt}")
        raise IAErro(f"A IA respondeu com erro {e.code}: {str(txt)[:300]}")
    except urllib.error.URLError as e:
        raise IAErro(f"Não consegui conectar em {url} ({e.reason}).")
    except TimeoutError:
        raise IAErro("A IA demorou demais para responder.")


def _com_imagem(p, msg, imagem):
    """Anexa a imagem (PNG em base64) à mensagem no formato de cada provedor."""
    texto = msg["content"]
    if p == "ollama":
        return {"role": "user", "content": texto, "images": [imagem]}
    if p == "claude":
        return {"role": "user", "content": [
            {"type": "image", "source": {"type": "base64", "media_type": "image/png", "data": imagem}},
            {"type": "text", "text": texto}]}
    return {"role": "user", "content": [
        {"type": "text", "text": texto},
        {"type": "image_url", "image_url": {"url": "data:image/png;base64," + imagem}}]}


def chat(system, mensagens, cfg=None, timeout=300, imagem=None):
    cfg = cfg or carregar()
    p = cfg["provedor"]
    c = cfg[p]
    url = c["url"].rstrip("/")
    modelo = c["modelo"].strip()
    if imagem:
        modelo = (c.get("visao") or "").strip() or modelo
        mensagens = [_com_imagem(p, mensagens[0], imagem)] + mensagens[1:]
    chave = c["chave"].strip()
    if PROVEDORES[p]["chave"] and not chave:
        raise IAErro("Falta a chave da API. Abra a aba IA do programa e cole a chave.")

    try:
        return _chat(p, url, modelo, chave, system, mensagens, timeout)
    except IAErro as e:
        if imagem and re.search(r"image|vision|visão|multimodal", str(e), re.I):
            dica = " Rode no PowerShell: ollama pull qwen2.5vl:7b" if p == "ollama" else ""
            raise IAErro(f"O modelo {modelo} não entende imagens. Na aba IA do programa, "
                         f"escolha um modelo de visão para rabiscos.{dica}")
        raise


def _chat(p, url, modelo, chave, system, mensagens, timeout):
    if p == "ollama":
        try:
            r = _req(url + "/api/chat", {
                "model": modelo, "stream": False, "options": {"temperature": 0.3},
                "messages": [{"role": "system", "content": system}] + mensagens,
            }, timeout=timeout)
        except IAErro as e:
            if "conectar" in str(e):
                raise IAErro("O Ollama não está aberto neste computador. Instale em ollama.com "
                             f"e rode no PowerShell: ollama pull {modelo}")
            if "not found" in str(e).lower():
                raise IAErro(f"O modelo {modelo} não está instalado. Rode no PowerShell: "
                             f"ollama pull {modelo}")
            raise
        return r.get("message", {}).get("content", "")

    if p == "claude":
        r = _req(url + "/v1/messages", {
            "model": modelo, "max_tokens": 8000, "system": system, "messages": mensagens,
        }, {"x-api-key": chave, "anthropic-version": "2023-06-01"}, timeout=timeout)
        return "".join(b.get("text", "") for b in r.get("content", []) if b.get("type") == "text")

    r = _req(url + "/chat/completions", {
        "model": modelo,
        "messages": [{"role": "system", "content": system}] + mensagens,
    }, {"Authorization": "Bearer " + chave}, timeout=timeout)
    try:
        return r["choices"][0]["message"]["content"] or ""
    except (KeyError, IndexError):
        raise IAErro("Resposta inesperada da IA.")


def modelos_ollama(url):
    r = _req(url.rstrip("/") + "/api/tags", timeout=5)
    return [m["name"] for m in r.get("models", [])]


def _get(url, headers):
    req = urllib.request.Request(url, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=20) as r:
            return json.loads(r.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        if e.code in (401, 403):
            raise IAErro("A chave da API foi recusada. Confira a chave.")
        raise IAErro(f"O provedor respondeu com erro {e.code} ao listar os modelos.")
    except urllib.error.URLError as e:
        raise IAErro(f"Não consegui conectar em {url} ({e.reason}).")


def listar_modelos(p, url, chave):
    """Lista os modelos disponíveis para a chave (os mais úteis primeiro)."""
    url = url.rstrip("/")
    if p == "ollama":
        return modelos_ollama(url)
    if not chave:
        raise IAErro("Cole a chave da API antes de buscar os modelos.")
    if p == "claude":
        r = _get(url + "/v1/models?limit=100",
                 {"x-api-key": chave, "anthropic-version": "2023-06-01"})
    else:
        r = _get(url + "/models", {"Authorization": "Bearer " + chave})
    ids = []
    for m in r.get("data", []):
        i = str(m.get("id", ""))
        if i.startswith("models/"):
            i = i[len("models/"):]
        if i and i not in ids:
            ids.append(i)
    # esconde modelos que não servem para conversar (imagem, voz, embeddings...)
    fora = ("embed", "tts", "audio", "image", "imagen", "veo", "whisper", "dall-e",
            "moderation", "transcribe", "realtime", "live", "aqa", "banana", "lyria")
    uteis = [i for i in ids if not any(f in i.lower() for f in fora)]
    return sorted(uteis or ids, key=lambda i: ("lite" not in i.lower(), "preview" in i.lower(), i))


# ------------------------------------------------------------------ prompts
SYS = {
    "diagrama": """Você cria diagramas em código Mermaid para um quadro branco.
Responda SOMENTE com o código Mermaid, sem explicações e sem cercas ```.
Escolha o tipo de diagrama mais adequado ao pedido:
- organograma, hierarquia ou árvore: flowchart TD
- fluxograma ou processo: flowchart TD (ou flowchart LR se for uma sequência longa)
- mapa mental: mindmap
- troca de mensagens entre participantes: sequenceDiagram
- linha do tempo: timeline
- cronograma de projeto: gantt
- estados: stateDiagram-v2
- classes: classDiagram; entidades e relacionamentos: erDiagram
- proporções: pie
Regras: textos em português, curtos e claros. Use IDs simples (A, B, C1...) e coloque
os rótulos entre aspas duplas, ex.: A["Diretoria (RH)"]. Não use estilos, cores,
classDef, comentários nem a palavra 'end' como ID.""",

    "texto": """Você escreve textos para um quadro branco.
Responda SOMENTE com o texto, em português, sem Markdown (não use #, ** nem tabelas).
Use frases curtas. Para listas, comece cada linha com "• ".
Seja conciso: no máximo umas 15 linhas, a menos que o pedido diga outra coisa.""",

    "desenho": """Você cria ilustrações em SVG para um quadro branco.
Responda SOMENTE com um único elemento <svg>...</svg> completo, sem explicações e sem cercas ```.
Use xmlns="http://www.w3.org/2000/svg", viewBox="0 0 800 600", width="800" e height="600",
fundo transparente, estilo de desenho simples e limpo, contornos com stroke-width entre 3 e 6
e cores sólidas. Não use imagens externas, fontes externas, scripts, animações nem
<foreignObject>. Se houver texto, use <text> com font-family="sans-serif".""",
}

NOMES = {"diagrama": "diagrama Mermaid", "texto": "texto", "desenho": "desenho SVG"}

RABISCO = {
    "diagrama": "A imagem é um rabisco feito à mão em um quadro branco. Transforme-o em um "
                "diagrama Mermaid limpo e fiel ao rabisco: mantenha as mesmas caixas, os textos "
                "escritos nelas, as ligações e o sentido das setas. Respeite o formato das "
                "formas (retângulo A[\"...\"], losango de decisão A{\"...\"}, círculo A((\"...\"))) "
                "e a direção predominante (flowchart TD de cima para baixo ou flowchart LR da "
                "esquerda para a direita). Textos escritos ao lado das setas viram rótulos da "
                "seta: A -->|\"texto\"| B. Não invente elementos que não estão no rabisco. "
                "Se algum texto estiver difícil de ler, use a leitura mais provável.",
    "texto": "A imagem mostra texto escrito à mão em um quadro branco. Transcreva o texto "
             "fielmente, corrigindo apenas a ortografia e mantendo as quebras de linha e as listas.",
    "desenho": "A imagem é um rabisco feito à mão em um quadro branco. Redesenhe-o como uma "
               "ilustração SVG limpa e caprichada, mantendo a mesma composição, os mesmos "
               "elementos e as mesmas posições relativas.",
}


def limpar(modo, txt):
    txt = re.sub(r"<think>.*?</think>", "", txt or "", flags=re.S).strip()
    m = re.search(r"```[a-zA-Z]*\s*\n(.*?)```", txt, flags=re.S)
    if m and modo != "texto":
        txt = m.group(1).strip()
    if modo == "desenho":
        m = re.search(r"<svg\b.*</svg>", txt, flags=re.S | re.I)
        if not m:
            raise IAErro("A IA não devolveu um desenho válido. Tente de novo.")
        txt = m.group(0)
    elif modo == "diagrama":
        txt = re.sub(r"^\s*mermaid\s*\n", "", txt)
    if not txt.strip():
        raise IAErro("A IA devolveu uma resposta vazia. Tente de novo.")
    return txt.strip()


def gerar(modo, pedido, atual=None, codigo=None, erro=None, cfg=None, imagem=None):
    if modo not in SYS:
        raise IAErro("Tipo de criação desconhecido.")
    pedido = (pedido or "").strip()
    if not pedido and not imagem:
        raise IAErro("Escreva o que você quer criar.")
    nome = NOMES[modo]
    if imagem:
        txt = RABISCO[modo] + (f"\nInstruções extras de quem desenhou: {pedido}" if pedido else "")
        msgs = [{"role": "user", "content": txt}]
    elif atual:
        msgs = [{"role": "user", "content":
                 f"Este é o {nome} atual:\n\n{atual}\n\nAltere conforme o pedido abaixo e "
                 f"responda com a versão completa.\nPedido: {pedido}"}]
    else:
        msgs = [{"role": "user", "content": pedido}]
    if codigo and erro:
        msgs += [{"role": "assistant", "content": codigo},
                 {"role": "user", "content":
                  f"Esse {nome} deu erro ao ser desenhado:\n{erro[:500]}\n"
                  "Corrija e responda somente com a versão completa corrigida."}]
    return limpar(modo, chat(SYS[modo], msgs, cfg, imagem=imagem))


# ------------------------------------------------------------------ Kindle Envia
CADERNO = {
    "texto": ("Você transcreve anotações de caderno para ler num leitor de e-book.",
              "A imagem é uma foto de uma página de caderno com anotações à mão. Transcreva o "
              "conteúdo fielmente, em português, corrigindo só a ortografia. Organize em Markdown "
              "simples: # para o título (se houver), ## para subtítulos, '- ' para listas e "
              "**negrito** para o que estiver destacado. Não invente nada que não esteja escrito. "
              "Se um trecho estiver ilegível, escreva [ilegível]. Responda só com o texto."),
    "resumo": ("Você organiza anotações de caderno para estudar num leitor de e-book.",
               "A imagem é uma foto de uma página de caderno. Leia as anotações e escreva uma "
               "versão organizada e resumida em Markdown simples (# título, ## seções, '- ' listas, "
               "**negrito** para conceitos-chave), em português. Mantenha todas as ideias "
               "importantes, sem inventar informação. Responda só com o texto."),
    "diagrama": (SYS["diagrama"], RABISCO["diagrama"].replace("em um quadro branco", "em um caderno")),
    "desenho": (SYS["desenho"], RABISCO["desenho"].replace("em um quadro branco", "em um caderno")),
}

MODOS_CADERNO = {
    "texto": "Texto (transcrever a letra)",
    "resumo": "Texto resumido e organizado",
    "diagrama": "Diagrama (Mermaid)",
    "desenho": "Desenho limpo (SVG)",
}


def caderno(modo, imagem_b64, extra="", cfg=None, codigo=None, erro=None):
    """Converte a foto de uma página de caderno. Devolve texto Markdown, Mermaid ou SVG."""
    if modo not in CADERNO:
        raise IAErro("Modo desconhecido.")
    sistema, pedido = CADERNO[modo]
    if extra.strip():
        pedido += "\nInstruções extras: " + extra.strip()
    msgs = [{"role": "user", "content": pedido}]
    if codigo and erro:
        msgs += [{"role": "assistant", "content": codigo},
                 {"role": "user", "content": "Esse diagrama deu erro ao ser desenhado:\n%s\n"
                  "Corrija e responda somente com o código completo corrigido." % erro[:500]}]
    txt = chat(sistema, msgs, cfg, imagem=imagem_b64)
    return limpar("texto" if modo == "resumo" else modo, txt)


RESUMO_NOTICIAS = """Você é editor de um jornal diário curto para ler num e-reader.
Receberá manchetes e trechos de várias fontes. Escreva em português do Brasil, em Markdown simples:
- comece com "## Destaques do dia": 3 a 5 tópicos de uma ou duas frases com o mais importante;
- depois, uma seção "## <Tema>" para cada assunto (ex.: Brasil, Mundo, Economia, Tecnologia,
  Esportes), com tópicos curtos ("- ") que juntam notícias repetidas de fontes diferentes;
- seja factual e neutro, sem opinião e sem inventar nada que não esteja nos trechos;
- no máximo umas 700 palavras. Não use links nem tabelas."""


def resumir_noticias(texto, cfg=None):
    txt = chat(RESUMO_NOTICIAS, [{"role": "user", "content": texto}], cfg, timeout=600)
    return limpar("texto", txt)
