#!/usr/bin/env python3
"""
Kindle Envia - converte arquivos, fotos do caderno (com IA) e notícias para o
Kindle 4 e envia pelo Wi-Fi, para o servidor.py que roda no Kindle.

    python kindle_envia.py                abre a janela
    python kindle_envia.py arquivo.pdf    abre a janela já com os arquivos
    python kindle_envia.py --auto         sem janela: jornal do dia + pendentes
                                          (é o que roda ao ligar o PC)
"""
import datetime
import os
import queue
import shutil
import subprocess
import sys
import threading
import time
import traceback

import config
import conversor
import kindle

VERSAO = "1.0"


# ====================================================================== modo automático
def _log(msg):
    linha = "%s  %s\n" % (time.strftime("%Y-%m-%d %H:%M:%S"), msg)
    try:
        os.makedirs(config.pasta_app(), exist_ok=True)
        caminho = os.path.join(config.pasta_app(), "auto.log")
        if os.path.exists(caminho) and os.path.getsize(caminho) > 200000:
            os.replace(caminho, caminho + ".old")
        with open(caminho, "a", encoding="utf-8") as f:
            f.write(linha)
    except OSError:
        pass
    if sys.stdout:
        try:
            print(linha, end="")
        except (OSError, ValueError):
            pass


def entregar_noticias(cfg, aviso=_log):
    """Gera o jornal (se ainda não foi gerado hoje) e manda. Devolve True se chegou ao Kindle."""
    import ia
    import noticias
    n = cfg["noticias"]
    hoje = datetime.date.today().isoformat()
    if n.get("ultimo_gerado") != hoje:
        pdf, erros = noticias.gerar(cfg, config.pasta_saida(), ia.carregar(), aviso,
                                    formato=cfg["kindle"].get("formato", "azw3"))
        for e in erros:
            aviso("Aviso: " + e)
        n["ultimo_gerado"] = hoje
        config.salvar(cfg)
        enviados, na_fila = kindle.enviar_ou_guardar(cfg, [pdf], noticias.PASTA_KINDLE)
        if na_fila:
            aviso("Kindle fora do ar: o jornal ficou na fila para enviar depois.")
            return False
        aviso("Jornal enviado: " + ", ".join(enviados))
        _depois_de_entregar(cfg, hoje, aviso)
        return True
    return n.get("ultimo_envio") == hoje


def _depois_de_entregar(cfg, hoje, aviso):
    import noticias
    cfg["noticias"]["ultimo_envio"] = hoje
    config.salvar(cfg)
    try:
        apagados = kindle.limpar_antigos(cfg, noticias.PASTA_KINDLE, int(cfg["noticias"].get("manter_dias", 0)))
        if apagados:
            aviso("Jornais antigos apagados do Kindle: %d" % apagados)
    except kindle.KindleErro as e:
        aviso("Não deu para apagar os jornais antigos: %s" % e)


def modo_auto(horas=4, intervalo=300):
    """Roda ao ligar o PC: entrega o jornal do dia e o que estiver pendente.
    Se o Kindle estiver dormindo, tenta de novo a cada 5 minutos por até 4 horas."""
    cfg = config.carregar()
    _log("Modo automático iniciado.")
    if cfg["noticias"].get("auto"):
        try:
            entregar_noticias(cfg)
        except Exception as e:  # noqa: BLE001
            _log("Erro ao montar o jornal: %s" % e)
    fim = time.time() + horas * 3600
    while kindle.pendentes():
        try:
            n = kindle.enviar_pendentes(cfg)
            _log("Pendentes enviados ao Kindle: %d" % n)
            hoje = datetime.date.today().isoformat()
            if cfg["noticias"].get("ultimo_gerado") == hoje and cfg["noticias"].get("ultimo_envio") != hoje:
                _depois_de_entregar(cfg, hoje, _log)
            break
        except kindle.KindleOffline:
            if time.time() > fim:
                _log("Desisti por hoje: o Kindle não apareceu na rede. Fica na fila.")
                break
            time.sleep(intervalo)
        except kindle.KindleErro as e:
            _log("Erro ao enviar: %s" % e)
            break
    _log("Modo automático terminado.")


# ====================================================================== iniciar com o Windows
def _pasta_inicializar():
    return os.path.join(os.environ.get("APPDATA", ""), "Microsoft", "Windows", "Start Menu",
                        "Programs", "Startup")


def _comando_programa():
    if getattr(sys, "frozen", False):
        return [sys.executable]
    exe = sys.executable
    sem_console = os.path.join(os.path.dirname(exe), "pythonw.exe")
    return [sem_console if os.path.exists(sem_console) else exe, os.path.abspath(__file__)]


def iniciar_com_windows(ligar):
    if os.name != "nt":
        return
    vbs = os.path.join(_pasta_inicializar(), "KindleEnvia.vbs")
    if not ligar:
        if os.path.exists(vbs):
            os.remove(vbs)
        return
    partes = " ".join('""%s""' % p for p in _comando_programa()) + " --auto"
    with open(vbs, "w", encoding="utf-16") as f:
        f.write('CreateObject("WScript.Shell").Run "%s", 0, False\r\n' % partes)


def menu_enviar_para(ligar):
    """Cria "Enviar para > Kindle" no botão direito do Windows Explorer."""
    if os.name != "nt":
        return
    bat = os.path.join(os.environ.get("APPDATA", ""), "Microsoft", "Windows", "SendTo", "Kindle.bat")
    if not ligar:
        if os.path.exists(bat):
            os.remove(bat)
        return
    cmd = " ".join('"%s"' % p for p in _comando_programa())
    with open(bat, "w", encoding="cp1252", errors="replace") as f:
        f.write('@echo off\r\nstart "" %s %%*\r\n' % cmd)


# ====================================================================== janela
def janela(arquivos_iniciais):
    import tkinter as tk
    from tkinter import filedialog, messagebox, ttk

    import caderno
    import ia
    import noticias

    if os.name == "nt":
        try:
            import ctypes
            ctypes.windll.shcore.SetProcessDpiAwareness(1)
        except Exception:  # noqa: BLE001
            pass

    cfg = config.carregar()
    root = tk.Tk()
    root.title("Kindle Envia")
    root.minsize(620, 560)
    VERDE, VERMELHO, CINZA = "#15803d", "#b91c1c", "#555"

    # ------------------------------------------------------------ trabalho em segundo plano
    avisos = queue.Queue()
    ocupado = [False]
    status = tk.StringVar(value="Pronto.")

    def aviso(msg):
        avisos.put(msg)

    def ler_avisos():
        teve = False
        while not avisos.empty():
            status.set(avisos.get())
            teve = True
        if teve:
            atualizar_pendentes()
        root.after(150, ler_avisos)

    def tarefa(func, pronto=None, msg="Trabalhando..."):
        if ocupado[0]:
            messagebox.showinfo("Kindle Envia", "Espere a tarefa atual terminar.")
            return
        ocupado[0] = True
        status.set(msg)
        root.configure(cursor="watch")
        res = {}

        def rodar():
            try:
                res["v"] = func()
            except Exception as e:  # noqa: BLE001
                res["e"] = e
                if not isinstance(e, (kindle.KindleErro, conversor.ConversaoErro, ia.IAErro)):
                    traceback.print_exc()
        t = threading.Thread(target=rodar, daemon=True)
        t.start()

        def esperar():
            if t.is_alive():
                root.after(200, esperar)
                return
            ocupado[0] = False
            root.configure(cursor="")
            while not avisos.empty():  # descarta avisos atrasados para não cobrir o resultado
                avisos.get()
            atualizar_pendentes()
            if "e" in res:
                status.set("Erro: %s" % res["e"])
                messagebox.showerror("Kindle Envia", str(res["e"]))
            elif pronto:
                pronto(res.get("v"))
        esperar()

    def resultado_envio(enviados, na_fila, extra=""):
        if na_fila:
            msg = ("O Kindle não respondeu (dormindo, Wi-Fi desligado ou o servidor.py parado).\n"
                   "O arquivo ficou na fila e vai ser enviado depois.")
            status.set("Na fila: o Kindle não respondeu.")
            messagebox.showwarning("Kindle Envia", msg + extra)
        else:
            status.set("✔ Enviado ao Kindle: " + ", ".join(enviados))

    def abrir_pasta(p):
        if os.name == "nt":
            os.startfile(p)  # noqa: S606
        else:
            subprocess.Popen(["xdg-open", p])

    # ------------------------------------------------------------ layout
    topo = ttk.Frame(root, padding=(14, 12, 14, 0))
    topo.pack(fill="x")
    ttk.Label(topo, text="📚 Kindle Envia", font=("Segoe UI", 16, "bold")).pack(side="left")
    pend_lbl = ttk.Label(topo, foreground=CINZA)
    pend_lbl.pack(side="right")

    nb = ttk.Notebook(root)
    nb.pack(fill="both", expand=True, padx=14, pady=10)
    ttk.Label(root, textvariable=status, foreground=CINZA, wraplength=600, justify="left",
              padding=(14, 0, 14, 10)).pack(fill="x")

    def atualizar_pendentes():
        n = len(kindle.pendentes())
        pend_lbl.configure(text=("📮 %d na fila para o Kindle" % n) if n else "")

    def lista_com_botoes(pai, altura=7):
        caixa = ttk.Frame(pai)
        lb = tk.Listbox(caixa, height=altura, selectmode="extended", activestyle="none")
        sb = ttk.Scrollbar(caixa, orient="vertical", command=lb.yview)
        lb.configure(yscrollcommand=sb.set)
        lb.pack(side="left", fill="both", expand=True)
        sb.pack(side="right", fill="y")
        return caixa, lb

    # ================================================================ aba Arquivos
    arq = ttk.Frame(nb, padding=12)
    nb.add(arq, text="  📄 Arquivos  ")
    ttk.Label(arq, text="PDF, imagens (JPG, PNG...), SVG, Mermaid (.mmd), texto (.txt, .md) "
                        "ou livros AZW3/MOBI:", wraplength=560).pack(anchor="w")
    caixa, lista_arq = lista_com_botoes(arq, 9)
    caixa.pack(fill="both", expand=True, pady=6)

    def add_arquivos(caminhos):
        atuais = set(lista_arq.get(0, "end"))
        for c in caminhos:
            if c.lower().endswith(conversor.ACEITOS) and c not in atuais:
                lista_arq.insert("end", c)

    def escolher_arquivos():
        tipos = [("Arquivos aceitos", " ".join("*" + e for e in conversor.ACEITOS)), ("Todos", "*.*")]
        add_arquivos(filedialog.askopenfilenames(title="Escolha os arquivos", filetypes=tipos))

    linha = ttk.Frame(arq)
    linha.pack(fill="x")
    ttk.Button(linha, text="Adicionar arquivos...", command=escolher_arquivos).pack(side="left")
    ttk.Button(linha, text="Remover", command=lambda: [lista_arq.delete(i) for i in
                                                       reversed(lista_arq.curselection())]).pack(side="left", padx=6)
    ttk.Button(linha, text="Limpar", command=lambda: lista_arq.delete(0, "end")).pack(side="left")

    opc = ttk.Frame(arq)
    opc.pack(fill="x", pady=(10, 0))
    ttk.Label(opc, text="PDFs:").grid(row=0, column=0, sticky="w")
    modos = list(conversor.MODOS_PDF)
    modo_pdf = ttk.Combobox(opc, state="readonly", width=44, values=[conversor.MODOS_PDF[m] for m in modos])
    modo_pdf.current(modos.index(cfg["arquivos"].get("modo_pdf", "ampliar")))
    modo_pdf.grid(row=0, column=1, sticky="w", padx=6)
    juntar = tk.BooleanVar(value=False)
    ttk.Checkbutton(opc, text="Juntar as imagens num arquivo só, com o nome:", variable=juntar).grid(
        row=1, column=0, columnspan=2, sticky="w", pady=(6, 0))
    nome_junto = ttk.Entry(opc, width=30)
    nome_junto.insert(0, "Fotos")
    nome_junto.grid(row=2, column=1, sticky="w", padx=6)

    def converter_lista(enviar):
        caminhos = list(lista_arq.get(0, "end"))
        if not caminhos:
            messagebox.showinfo("Kindle Envia", "Adicione pelo menos um arquivo.")
            return
        modo = modos[modo_pdf.current()]
        cfg["arquivos"]["modo_pdf"] = modo
        config.salvar(cfg)
        pasta = config.pasta_saida()
        formato = conversor.formato_real(cfg["kindle"].get("formato", "azw3"))
        junta = juntar.get()
        nome = nome_junto.get().strip() or "Fotos"
        local = dict(cfg)

        def trabalho():
            prontos = []
            imagens = [c for c in caminhos if c.lower().endswith(conversor.IMAGENS)]
            if junta and len(imagens) > 1:
                aviso("Juntando %d imagens..." % len(imagens))
                prontos.append(conversor.imagens_para_livro(
                    imagens, conversor.nome_saida(pasta, nome, conversor.EXT[formato]), nome, formato))
                caminhos_restantes = [c for c in caminhos if c not in imagens]
            else:
                caminhos_restantes = caminhos
            for i, c in enumerate(caminhos_restantes, 1):
                aviso("Convertendo %d de %d: %s" % (i, len(caminhos_restantes), os.path.basename(c)))
                prontos.append(conversor.converter(c, pasta, modo, formato))
            if not enviar:
                return prontos, None
            aviso("Enviando ao Kindle...")
            return prontos, kindle.enviar_ou_guardar(local, prontos)

        def pronto(r):
            prontos, envio = r
            if envio is None:
                status.set("✔ Convertidos: %d arquivo(s) em %s" % (len(prontos), pasta))
                abrir_pasta(pasta)
            else:
                resultado_envio(*envio)
                lista_arq.delete(0, "end")
        tarefa(trabalho, pronto, "Convertendo...")

    linha2 = ttk.Frame(arq)
    linha2.pack(fill="x", pady=(12, 0))
    ttk.Button(linha2, text="📤 Converter e enviar ao Kindle",
               command=lambda: converter_lista(True)).pack(side="left")
    ttk.Button(linha2, text="Só converter", command=lambda: converter_lista(False)).pack(side="left", padx=6)
    ttk.Button(linha2, text="Abrir pasta dos convertidos",
               command=lambda: abrir_pasta(config.pasta_saida())).pack(side="right")

    # ================================================================ aba Caderno
    cad = ttk.Frame(nb, padding=12)
    nb.add(cad, text="  📓 Caderno (IA)  ")
    ttk.Label(cad, text="Fotos das páginas do caderno (na ordem):").pack(anchor="w")
    caixa, lista_fotos = lista_com_botoes(cad, 3)
    caixa.pack(fill="x", pady=4)
    lf = ttk.Frame(cad)
    lf.pack(fill="x")
    ttk.Button(lf, text="Adicionar fotos...", command=lambda: [
        lista_fotos.insert("end", c) for c in filedialog.askopenfilenames(
            title="Fotos do caderno", filetypes=[("Imagens", "*.jpg *.jpeg *.png *.webp *.bmp")])]
    ).pack(side="left")
    ttk.Button(lf, text="Limpar", command=lambda: lista_fotos.delete(0, "end")).pack(side="left", padx=6)

    g = ttk.Frame(cad)
    g.pack(fill="x", pady=(8, 0))
    g.columnconfigure(1, weight=1)
    modos_cad = list(ia.MODOS_CADERNO)
    ttk.Label(g, text="Transformar em:").grid(row=0, column=0, sticky="w")
    modo_cad = ttk.Combobox(g, state="readonly", values=[ia.MODOS_CADERNO[m] for m in modos_cad])
    modo_cad.current(modos_cad.index(cfg["caderno"].get("modo", "texto")))
    modo_cad.grid(row=0, column=1, sticky="we", padx=6, pady=2)
    ttk.Label(g, text="Título:").grid(row=1, column=0, sticky="w")
    titulo_cad = ttk.Entry(g)
    titulo_cad.insert(0, "Caderno " + datetime.date.today().strftime("%d-%m-%Y"))
    titulo_cad.grid(row=1, column=1, sticky="we", padx=6, pady=2)
    ttk.Label(g, text="Instruções extras:").grid(row=2, column=0, sticky="w")
    extra_cad = ttk.Entry(g)
    extra_cad.grid(row=2, column=1, sticky="we", padx=6, pady=2)

    ttk.Label(cad, text="Resultado da IA (pode corrigir antes de criar o arquivo):").pack(anchor="w", pady=(8, 2))
    tx_frame = ttk.Frame(cad)
    tx_frame.pack(fill="both", expand=True)
    texto_cad = tk.Text(tx_frame, height=8, wrap="word", font=("Consolas", 10), undo=True)
    sb = ttk.Scrollbar(tx_frame, orient="vertical", command=texto_cad.yview)
    texto_cad.configure(yscrollcommand=sb.set)
    texto_cad.pack(side="left", fill="both", expand=True)
    sb.pack(side="right", fill="y")

    def ler_com_ia():
        fotos = list(lista_fotos.get(0, "end"))
        if not fotos:
            messagebox.showinfo("Kindle Envia", "Adicione a foto do caderno.")
            return
        modo = modos_cad[modo_cad.current()]
        cfg["caderno"]["modo"] = modo
        config.salvar(cfg)
        extra = extra_cad.get()
        ia_cfg = ia.carregar()

        def pronto(conteudo):
            texto_cad.delete("1.0", "end")
            texto_cad.insert("1.0", conteudo)
            status.set("✔ A IA terminou. Confira o resultado e clique em Criar e enviar.")
        tarefa(lambda: caderno.ler_fotos(fotos, modo, extra, ia_cfg, aviso), pronto, "Lendo com a IA...")

    def criar_pdf_caderno(enviar):
        conteudo = texto_cad.get("1.0", "end").strip()
        if not conteudo:
            messagebox.showinfo("Kindle Envia", "Primeiro clique em \"Ler com IA\" (ou escreva o texto).")
            return
        modo = modos_cad[modo_cad.current()]
        titulo = titulo_cad.get().strip()
        local = dict(cfg)

        formato = cfg["kindle"].get("formato", "azw3")

        def trabalho():
            aviso("Criando o arquivo...")
            pdf = caderno.gerar(conteudo, modo, titulo, config.pasta_saida(), formato)
            return pdf, (kindle.enviar_ou_guardar(local, [pdf]) if enviar else None)

        def pronto(r):
            pdf, envio = r
            if envio is None:
                status.set("✔ Arquivo criado: " + pdf)
                abrir_pasta(os.path.dirname(pdf))
            else:
                resultado_envio(*envio)
        tarefa(trabalho, pronto, "Criando o arquivo...")

    bc = ttk.Frame(cad)
    bc.pack(fill="x", pady=(8, 0))
    ttk.Button(bc, text="1. ✨ Ler com IA", command=ler_com_ia).pack(side="left")
    ttk.Button(bc, text="2. 📤 Criar e enviar", command=lambda: criar_pdf_caderno(True)).pack(side="left", padx=6)
    ttk.Button(bc, text="Só criar o arquivo", command=lambda: criar_pdf_caderno(False)).pack(side="left")

    # ================================================================ aba Notícias
    noti = ttk.Frame(nb, padding=12)
    nb.add(noti, text="  📰 Notícias  ")
    ttk.Label(noti, text="Canais (RSS). Dê dois cliques para ligar ou desligar:").pack(anchor="w")
    arv = ttk.Treeview(noti, columns=("on", "nome", "url"), show="headings", height=7)
    for col, txt, larg in (("on", "", 34), ("nome", "Canal", 170), ("url", "Endereço do RSS", 360)):
        arv.heading(col, text=txt)
        arv.column(col, width=larg, stretch=(col == "url"), anchor="center" if col == "on" else "w")
    arv.pack(fill="both", expand=True, pady=4)

    def mostrar_fontes():
        arv.delete(*arv.get_children())
        for nome, url, ligado in cfg["noticias"]["fontes"]:
            arv.insert("", "end", values=("✔" if ligado else "—", nome, url))

    def alternar(_e=None):
        sel = arv.selection()
        if not sel:
            return
        i = arv.index(sel[0])
        cfg["noticias"]["fontes"][i][2] = not cfg["noticias"]["fontes"][i][2]
        config.salvar(cfg)
        mostrar_fontes()
        arv.selection_set(arv.get_children()[i])
    arv.bind("<Double-1>", alternar)
    mostrar_fontes()

    nova = ttk.Frame(noti)
    nova.pack(fill="x")
    ttk.Label(nova, text="Nome:").pack(side="left")
    nome_f = ttk.Entry(nova, width=16)
    nome_f.pack(side="left", padx=4)
    ttk.Label(nova, text="RSS:").pack(side="left")
    url_f = ttk.Entry(nova)
    url_f.pack(side="left", fill="x", expand=True, padx=4)

    def adicionar_fonte():
        nome, url = nome_f.get().strip(), url_f.get().strip()
        if not nome or not url.startswith("http"):
            messagebox.showinfo("Kindle Envia", "Preencha o nome e o endereço do RSS (começando com http).")
            return

        def pronto(itens):
            cfg["noticias"]["fontes"].append([nome, url, True])
            config.salvar(cfg)
            mostrar_fontes()
            nome_f.delete(0, "end")
            url_f.delete(0, "end")
            status.set("✔ Canal adicionado: %s (%d notícias no RSS agora)" % (nome, len(itens)))
        tarefa(lambda: noticias.ler_feed(noticias.baixar(url), nome), pronto, "Testando o canal...")

    def remover_fonte():
        for item in reversed(arv.selection()):
            del cfg["noticias"]["fontes"][arv.index(item)]
        config.salvar(cfg)
        mostrar_fontes()

    ttk.Button(nova, text="Adicionar", command=adicionar_fonte).pack(side="left")
    ttk.Button(nova, text="Remover", command=remover_fonte).pack(side="left", padx=(4, 0))

    op = ttk.Frame(noti)
    op.pack(fill="x", pady=(10, 0))
    por_fonte = tk.IntVar(value=int(cfg["noticias"].get("por_fonte", 6)))
    manter = tk.IntVar(value=int(cfg["noticias"].get("manter_dias", 3)))
    resumo = tk.BooleanVar(value=bool(cfg["noticias"].get("resumo_ia", True)))
    auto = tk.BooleanVar(value=bool(cfg["noticias"].get("auto", False)))
    ttk.Label(op, text="Notícias por canal:").grid(row=0, column=0, sticky="w")
    ttk.Spinbox(op, from_=1, to=20, width=4, textvariable=por_fonte).grid(row=0, column=1, sticky="w", padx=6)
    ttk.Label(op, text="Manter no Kindle (dias):").grid(row=0, column=2, sticky="w", padx=(16, 0))
    ttk.Spinbox(op, from_=0, to=30, width=4, textvariable=manter).grid(row=0, column=3, sticky="w", padx=6)
    ttk.Checkbutton(op, text="Resumo do dia feito pela IA (além das manchetes)", variable=resumo).grid(
        row=1, column=0, columnspan=4, sticky="w", pady=(6, 0))
    ttk.Checkbutton(op, text="Gerar e enviar sozinho quando o PC ligar", variable=auto).grid(
        row=2, column=0, columnspan=4, sticky="w")

    def guardar_noticias():
        n = cfg["noticias"]
        try:
            n["por_fonte"], n["manter_dias"] = int(por_fonte.get()), int(manter.get())
        except (tk.TclError, ValueError):
            pass
        n["resumo_ia"], n["auto"] = resumo.get(), auto.get()
        config.salvar(cfg)
        try:
            iniciar_com_windows(n["auto"])
        except OSError as e:
            messagebox.showerror("Kindle Envia", "Não deu para configurar o início automático: %s" % e)

    for var in (por_fonte, manter, resumo, auto):
        var.trace_add("write", lambda *_: guardar_noticias())

    def jornal(enviar):
        guardar_noticias()
        local = dict(cfg)
        ia_cfg = ia.carregar()

        def trabalho():
            pdf, erros = noticias.gerar(local, config.pasta_saida(), ia_cfg, aviso,
                                        formato=local["kindle"].get("formato", "azw3"))
            local["noticias"]["ultimo_gerado"] = datetime.date.today().isoformat()
            config.salvar(local)
            envio = None
            if enviar:
                aviso("Enviando ao Kindle...")
                envio = kindle.enviar_ou_guardar(local, [pdf], noticias.PASTA_KINDLE)
                if not envio[1]:
                    _depois_de_entregar(local, datetime.date.today().isoformat(), aviso)
            return pdf, erros, envio

        def pronto(r):
            pdf, erros, envio = r
            extra = ("\n\nAvisos:\n" + "\n".join(erros)) if erros else ""
            if envio is None:
                status.set("✔ Jornal criado: " + pdf)
                abrir_pasta(os.path.dirname(pdf))
            else:
                resultado_envio(*envio, extra=extra)
            if erros and (envio is None or not envio[1]):
                messagebox.showwarning("Kindle Envia", "O jornal saiu, mas com avisos:" + extra)
        tarefa(trabalho, pronto, "Montando o jornal...")

    bn = ttk.Frame(noti)
    bn.pack(fill="x", pady=(10, 0))
    ttk.Button(bn, text="📤 Gerar agora e enviar", command=lambda: jornal(True)).pack(side="left")
    ttk.Button(bn, text="Só gerar (abrir a pasta)", command=lambda: jornal(False)).pack(side="left", padx=6)

    # ================================================================ aba Kindle
    kin = ttk.Frame(nb, padding=12)
    nb.add(kin, text="  📖 Kindle  ")
    gk = ttk.Frame(kin)
    gk.pack(fill="x")
    ttk.Label(gk, text="IP do Kindle:").grid(row=0, column=0, sticky="w", pady=2)
    ip_k = ttk.Entry(gk, width=18)
    ip_k.insert(0, cfg["kindle"]["ip"])
    ip_k.grid(row=0, column=1, sticky="w", padx=6)
    ttk.Label(gk, text="Porta:").grid(row=0, column=2, sticky="w")
    porta_k = ttk.Entry(gk, width=7)
    porta_k.insert(0, str(cfg["kindle"].get("porta", 8000)))
    porta_k.grid(row=0, column=3, sticky="w", padx=6)
    ttk.Label(gk, text="Senha do servidor:").grid(row=1, column=0, sticky="w", pady=2)
    senha_k = ttk.Entry(gk, width=28, show="•")
    senha_k.insert(0, cfg["kindle"]["senha"])
    senha_k.grid(row=1, column=1, columnspan=3, sticky="w", padx=6)
    ttk.Label(gk, text="Formato dos arquivos:").grid(row=2, column=0, sticky="w", pady=2)
    formatos = list(conversor.FORMATOS)
    formato_k = ttk.Combobox(gk, state="readonly", width=30, values=[conversor.FORMATOS[f] for f in formatos])
    formato_k.current(formatos.index(cfg["kindle"].get("formato", "azw3")))
    formato_k.grid(row=2, column=1, columnspan=3, sticky="w", padx=6)
    cal = conversor.achar_calibre()
    ttk.Label(kin, wraplength=560, justify="left", foreground=VERDE if cal else VERMELHO, text=(
        "✔ Calibre encontrado: AZW3 e MOBI disponíveis." if cal else
        "⚠ Calibre não encontrado: sem ele, os arquivos saem em PDF. Instale em calibre-ebook.com "
        "e abra o programa de novo.")).pack(anchor="w", pady=(6, 0))

    def troca_formato(_e=None):
        cfg["kindle"]["formato"] = formatos[formato_k.current()]
        config.salvar(cfg)
    formato_k.bind("<<ComboboxSelected>>", troca_formato)
    k_st = ttk.Label(kin, wraplength=560, justify="left")
    k_st.pack(anchor="w", pady=(8, 0))

    def salvar_kindle():
        cfg["kindle"]["ip"] = ip_k.get().strip()
        cfg["kindle"]["senha"] = senha_k.get().strip()
        try:
            cfg["kindle"]["porta"] = int(porta_k.get())
        except ValueError:
            cfg["kindle"]["porta"] = 8000
        config.salvar(cfg)

    def testar_kindle():
        salvar_kindle()
        k_st.configure(text="Testando...", foreground=CINZA)

        def ok(msg):
            k_st.configure(text="✔ " + msg, foreground=VERDE)
            status.set(msg)
        tarefa(lambda: kindle.testar(cfg), ok, "Procurando o Kindle...")

    def enviar_fila():
        salvar_kindle()
        if not kindle.pendentes():
            k_st.configure(text="A fila está vazia.", foreground=CINZA)
            return
        tarefa(lambda: kindle.enviar_pendentes(cfg),
               lambda n: k_st.configure(text="✔ %d arquivo(s) da fila enviados." % n, foreground=VERDE),
               "Enviando a fila...")

    bk = ttk.Frame(kin)
    bk.pack(fill="x", pady=(8, 0))
    ttk.Button(bk, text="Salvar", command=lambda: (salvar_kindle(), status.set("✔ Salvo."))).pack(side="left")
    ttk.Button(bk, text="Testar conexão", command=testar_kindle).pack(side="left", padx=6)
    ttk.Button(bk, text="Enviar a fila agora", command=enviar_fila).pack(side="left")

    ttk.Separator(kin).pack(fill="x", pady=12)
    enviar_para = tk.BooleanVar(value=os.path.exists(os.path.join(
        os.environ.get("APPDATA", ""), "Microsoft", "Windows", "SendTo", "Kindle.bat")))
    ttk.Checkbutton(kin, text='Botão direito > "Enviar para" > Kindle no Explorador de Arquivos',
                    variable=enviar_para, command=lambda: menu_enviar_para(enviar_para.get())).pack(anchor="w")

    def copiar_servidor():
        destino = filedialog.askdirectory(title="Escolha a pasta scripts do Kindle (ex.: D:\\scripts)")
        if destino:
            shutil.copy2(conversor.recurso("servidor.py"), os.path.join(destino, "servidor.py"))
            messagebox.showinfo("Kindle Envia", "servidor.py copiado. Abra o arquivo e troque a SENHA "
                                                "(a mesma desta aba), depois reinicie o servidor no Kindle.")
    ttk.Button(kin, text="Copiar o servidor.py atualizado para o Kindle (USB)...",
               command=copiar_servidor).pack(anchor="w", pady=(8, 0))
    ttk.Label(kin, foreground=CINZA, wraplength=560, justify="left", text=(
        "No Kindle, o servidor precisa estar ligado (pelo SSH):\n"
        "    python3 /mnt/us/scripts/servidor.py --fundo\n"
        "O Kindle precisa estar acordado e no mesmo Wi-Fi. Se não estiver, os arquivos "
        "ficam na fila e são enviados depois.")).pack(anchor="w", pady=(10, 0))

    # ================================================================ aba IA
    iaf = ttk.Frame(nb, padding=12)
    nb.add(iaf, text="  🤖 IA  ")
    AJUDA = {
        "ollama": "Grátis e privado: roda neste PC. Instale em ollama.com e rode no PowerShell:\n"
                  "    ollama pull qwen2.5:7b      (texto e notícias)\n"
                  "    ollama pull qwen2.5vl:7b    (fotos do caderno)",
        "claude": "Melhor para ler letra de mão. Pago por uso: crie a chave em console.anthropic.com. "
                  "O mesmo modelo lê as fotos (deixe \"Modelo p/ fotos\" em branco).",
        "openai": "OpenAI (platform.openai.com) ou compatíveis: Groq, OpenRouter, Gemini, LM Studio. "
                  "Para as fotos, o modelo precisa aceitar imagens.",
    }
    ia_cfg = ia.carregar()
    provs = list(ia.PROVEDORES)
    ttk.Label(iaf, text="IA usada no Caderno e no resumo das notícias:").pack(anchor="w")
    prov = ttk.Combobox(iaf, state="readonly", values=[ia.PROVEDORES[p]["nome"] for p in provs])
    prov.pack(fill="x", pady=(4, 8))
    gi = ttk.Frame(iaf)
    gi.pack(fill="x")
    gi.columnconfigure(1, weight=1)
    campos = {}
    for i, (chave_c, rotulo) in enumerate((("modelo", "Modelo:"), ("chave", "Chave da API:"),
                                           ("url", "Endereço:"), ("visao", "Modelo p/ fotos:"))):
        ttk.Label(gi, text=rotulo).grid(row=i, column=0, sticky="w", padx=(0, 6), pady=2)
        w = ttk.Entry(gi, show="•") if chave_c == "chave" else (
            ttk.Combobox(gi) if chave_c in ("modelo", "visao") else ttk.Entry(gi))
        w.grid(row=i, column=1, sticky="we", pady=2)
        campos[chave_c] = w
    ajuda = ttk.Label(iaf, wraplength=560, justify="left", foreground=CINZA)
    ajuda.pack(anchor="w", pady=8)
    ia_st = ttk.Label(iaf, wraplength=560, justify="left")
    atual = [ia_cfg["provedor"]]

    def set_campo(nome, valor):
        w = campos[nome]
        w.configure(state="normal")
        w.delete(0, "end")
        w.insert(0, valor)

    def guarda_ia():
        p = atual[0]
        c = ia_cfg[p]
        c["modelo"] = campos["modelo"].get().strip() or ia.PROVEDORES[p]["modelo"]
        c["url"] = campos["url"].get().strip() or ia.PROVEDORES[p]["url"]
        c["visao"] = campos["visao"].get().strip()
        if ia.PROVEDORES[p]["chave"]:
            c["chave"] = campos["chave"].get().strip()

    def mostra_ia(p):
        atual[0] = p
        for nome in ("modelo", "url", "visao", "chave"):
            set_campo(nome, ia_cfg[p][nome])
        campos["chave"].configure(state="normal" if ia.PROVEDORES[p]["chave"] else "disabled")
        ajuda.configure(text=AJUDA[p])
        ia_st.configure(text="")

    def salvar_ia():
        guarda_ia()
        ia_cfg["provedor"] = atual[0]
        ia.salvar(ia_cfg)
        ia_st.configure(text="✔ Salvo.", foreground=VERDE)

    def testar_ia():
        salvar_ia()
        teste = ia.carregar()
        tarefa(lambda: ia.chat("Responda somente com a palavra ok.",
                               [{"role": "user", "content": "Teste. Responda apenas: ok"}], teste, timeout=120),
               lambda _r: ia_st.configure(text="✔ Funcionando! A IA respondeu.", foreground=VERDE),
               "Testando a IA...")

    def buscar_modelos():
        guarda_ia()
        p = atual[0]
        c = dict(ia_cfg[p])

        def pronto(nomes):
            if atual[0] != p or not nomes:
                ia_st.configure(text="Nenhum modelo encontrado.", foreground=VERMELHO)
                return
            campos["modelo"].configure(values=nomes)
            campos["visao"].configure(values=[""] + nomes)
            ia_st.configure(text="%d modelos. Escolha na setinha e clique em Salvar." % len(nomes),
                            foreground=VERDE)
        tarefa(lambda: ia.listar_modelos(p, c["url"], c["chave"]), pronto, "Buscando modelos...")

    bi = ttk.Frame(iaf)
    bi.pack(fill="x")
    ttk.Button(bi, text="Salvar", command=salvar_ia).pack(side="left")
    ttk.Button(bi, text="Testar conexão", command=testar_ia).pack(side="left", padx=6)
    ttk.Button(bi, text="Buscar modelos", command=buscar_modelos).pack(side="left")
    ia_st.pack(anchor="w", pady=(8, 0))

    def troca_ia(_e=None):
        guarda_ia()
        mostra_ia(provs[prov.current()])
    prov.bind("<<ComboboxSelected>>", troca_ia)
    prov.current(provs.index(ia_cfg["provedor"]))
    mostra_ia(ia_cfg["provedor"])

    # ------------------------------------------------------------ início
    if arquivos_iniciais:
        add_arquivos(arquivos_iniciais)
        nb.select(arq)
    elif not cfg["kindle"].get("senha"):
        nb.select(kin)
        k_st.configure(text="Comece por aqui: preencha o IP e a senha do servidor do Kindle.",
                       foreground=CINZA)
    atualizar_pendentes()
    ler_avisos()

    # manda o que ficou na fila, em silêncio, se o Kindle estiver por perto
    def fila_silenciosa():
        try:
            if kindle.pendentes() and cfg["kindle"].get("senha"):
                n = kindle.enviar_pendentes(cfg)
                aviso("✔ %d arquivo(s) da fila chegaram ao Kindle." % n)
        except kindle.KindleErro:
            pass
    threading.Thread(target=fila_silenciosa, daemon=True).start()

    root.mainloop()


def main():
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    if "--auto" in sys.argv:
        modo_auto()
        return
    janela([os.path.abspath(a) for a in args if os.path.isfile(a)])


if __name__ == "__main__":
    main()
