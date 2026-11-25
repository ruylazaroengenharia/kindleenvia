# -*- coding: utf-8 -*-
"""
Painel na tela de descanso do Kindle 4 (FW 4.x, jailbreak + ScreenSavers hack).

Quando o Kindle vai dormir, espera a imagem do screensaver aparecer e escreve
por cima, com o comando "eips": data, bateria, frase do dia e tarefas.

Arquivos que você edita (em D:\\scripts pelo USB, ou pelo servidor/SSH):
    frases.txt   uma frase por linha (troca uma por dia)
    tarefas.txt  uma tarefa por linha; linhas começando com "x " contam como feitas

Uso (pelo SSH):
    python3 /mnt/us/scripts/painel.py --teste     desenha agora, para conferir
    python3 /mnt/us/scripts/painel.py --fundo     roda em segundo plano (log em painel.log)
    pkill -f painel.py                            para
"""

import datetime
import os
import re
import signal
import subprocess
import sys
import textwrap
import threading
import time
import unicodedata

# ---------------------------------------------------------------- ajustes ---
# "faixa"  = rodapé por cima da imagem do screensaver (a imagem continua aparecendo)
# "painel" = apaga a imagem e usa a tela inteira
MODO = "faixa"
PASTA = os.path.dirname(os.path.abspath(__file__))
FRASES = os.path.join(PASTA, "frases.txt")
TAREFAS = os.path.join(PASTA, "tarefas.txt")
MAX_TAREFAS = 3 if MODO == "faixa" else 12
# Segundos depois de o Kindle começar a dormir em que a faixa é (re)desenhada.
# Redesenha algumas vezes porque a imagem do screensaver às vezes demora e cobre a faixa.
REDESENHOS = (2, 5, 9)
# Quando o Kindle acorda, pede para conectar no Wi-Fi (ele não conecta sozinho)
RECONECTAR_AO_ACORDAR = True
MOSTRAR_IP = True
EIPS = os.environ.get("EIPS", "eips")
COLUNAS, LINHAS = 50, 40  # grade de texto do eips no Kindle 4 (600x800)
# ----------------------------------------------------------------------------

DIAS = ["segunda", "terca", "quarta", "quinta", "sexta", "sabado", "domingo"]
MESES = ["jan", "fev", "mar", "abr", "mai", "jun", "jul", "ago", "set", "out", "nov", "dez"]


def ascii(texto):
    # a fonte do eips só tem ASCII: "ação" vira "acao"
    texto = unicodedata.normalize("NFKD", texto)
    return texto.encode("ascii", "ignore").decode("ascii")


def eips(*args):
    try:
        subprocess.call([EIPS] + [str(a) for a in args],
                        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except OSError:
        pass


def escrever(linha, texto):
    eips(0, linha, ascii(texto).ljust(COLUNAS)[:COLUNAS])


def ler_linhas(caminho):
    try:
        with open(caminho, encoding="utf-8", errors="replace") as f:
            return [l.strip() for l in f if l.strip() and not l.startswith("#")]
    except OSError:
        return []


def bateria():
    for cmd in (["lipc-get-prop", "com.lab126.powerd", "battLevel"], ["gasgauge-info", "-c"]):
        try:
            saida = subprocess.check_output(cmd, stderr=subprocess.DEVNULL).decode().strip()
            numero = "".join(c for c in saida if c.isdigit())
            if numero:
                return int(numero)
        except (OSError, subprocess.CalledProcessError):
            continue
    return None


def ip_wifi():
    """IP atual do Wi-Fi (ex.: 192.168.15.177), ou None."""
    try:
        saida = subprocess.check_output(["ifconfig", "wlan0"], stderr=subprocess.DEVNULL).decode("latin-1")
    except (OSError, subprocess.CalledProcessError):
        return None
    m = re.search(r"inet (?:addr:)?(\d+\.\d+\.\d+\.\d+)", saida)
    return m.group(1) if m else None


def _lipc(*args):
    try:
        r = subprocess.run(["lipc-" + args[0]] + list(args[1:]), stdout=subprocess.PIPE,
                           stderr=subprocess.STDOUT, timeout=15)
        return r.returncode, r.stdout.decode("utf-8", "replace").strip()
    except (OSError, subprocess.SubprocessError) as e:
        return -1, str(e)


def garantir_wifi():
    """Pede ao Kindle para conectar no Wi-Fi (as redes conhecidas), se ainda não estiver."""
    time.sleep(3)
    if ip_wifi():
        return
    for args in (("set-prop", "com.lab126.cmd", "ensureConnection", "wifi"),
                 ("set-prop", "com.lab126.wifid", "enable", "1")):
        codigo, saida = _lipc(*args)
        print("%s wifi: lipc-%s -> %s %s" % (time.strftime("%Y-%m-%d %H:%M:%S"), " ".join(args), codigo, saida))
        if codigo == 0:
            break
    for _ in range(20):                  # espera até 40 s para conectar
        time.sleep(2)
        if ip_wifi():
            print("%s wifi conectado: %s" % (time.strftime("%Y-%m-%d %H:%M:%S"), ip_wifi()))
            return


def vigiar_acordar():
    """Roda numa thread: a cada vez que o Kindle acorda, garante o Wi-Fi."""
    while True:
        inicio = time.time()
        subprocess.call(["lipc-wait-event", "com.lab126.powerd", "outOfScreenSaver"],
                        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        if time.time() - inicio < 0.5:
            time.sleep(30)
            continue
        try:
            garantir_wifi()
        except Exception as e:  # noqa: BLE001 - o painel não pode morrer por causa disso
            print("erro ao garantir o wifi: %s" % e)


def montar():
    hoje = datetime.date.today()
    linhas = []
    nivel = bateria()
    if nivel is None:
        bat = ""
    elif nivel <= 15:
        bat = "CARREGAR! [%s]" % ("#" * (nivel // 10)).ljust(10, "-")
    else:  # o eips não mostra o "%": usa uma barrinha
        bat = "bat [%s]" % ("#" * round(nivel / 10.0)).ljust(10, "-")
    data = "%s, %d %s" % (DIAS[hoje.weekday()], hoje.day, MESES[hoje.month - 1])
    linhas.append(data + bat.rjust(COLUNAS - 3 - len(data)))
    endereco = ip_wifi() if MOSTRAR_IP else None
    if endereco:
        linhas.append(("-- %s:8000 " % endereco).ljust(COLUNAS - 2, "-"))
    else:
        linhas.append("-" * (COLUNAS - 2))

    frases = ler_linhas(FRASES)
    if frases:
        frase = frases[hoje.toordinal() % len(frases)]
        largura = COLUNAS - 2
        limite = 2 if MODO == "faixa" else 6
        partes = textwrap.wrap(ascii(frase), largura)
        if len(partes) > limite:
            partes = partes[:limite]
            partes[-1] = partes[-1][:largura - 3] + "..."
        linhas.extend(partes)

    pendentes = [t for t in ler_linhas(TAREFAS) if not t.lower().startswith("x ")]
    if pendentes:
        linhas.append("")
        for t in pendentes[:MAX_TAREFAS]:
            linhas.append(("[ ] " + ascii(t))[:COLUNAS - 2])
        if len(pendentes) > MAX_TAREFAS:
            linhas.append("    + %d tarefa(s)" % (len(pendentes) - MAX_TAREFAS))
    return [" " + l for l in linhas]


def desenhar():
    linhas = montar()
    if MODO == "painel":
        eips("-c")
        inicio = 3
    else:
        inicio = LINHAS - len(linhas) - 2  # encosta no rodapé
        escrever(inicio - 1, "")            # linha em branco separando da imagem
    for i, texto in enumerate(linhas):
        escrever(inicio + i, texto)
    escrever(inicio + len(linhas), "")


def dormindo():
    """True = tela de descanso; False = acordado; None = não deu para saber."""
    try:
        saida = subprocess.check_output(["lipc-get-prop", "com.lab126.powerd", "status"],
                                        stderr=subprocess.DEVNULL).decode("utf-8", "replace").lower()
    except (OSError, subprocess.CalledProcessError):
        return None
    if "screen saver" in saida or "screensaver" in saida:
        return True
    if "active" in saida:
        return False
    return None


def desenhar_enquanto_dorme():
    """Desenha a faixa algumas vezes, mas para na hora se o Kindle acordar."""
    acordou = threading.Event()
    vigia = subprocess.Popen(["lipc-wait-event", "com.lab126.powerd", "outOfScreenSaver"],
                             stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    def esperar_acordar():
        vigia.wait()
        acordou.set()
    threading.Thread(target=esperar_acordar, daemon=True).start()
    inicio = time.time()
    try:
        for alvo in REDESENHOS:
            falta = alvo - (time.time() - inicio)
            if falta > 0:
                time.sleep(falta)
            if acordou.is_set() or dormindo() is False:
                break                      # acordou: não desenha por cima da tela de uso
            desenhar()
            print("%s painel desenhado (%ds)" % (time.strftime("%Y-%m-%d %H:%M:%S"), alvo))
    finally:
        if vigia.poll() is None:
            vigia.kill()


def esperar_dormir():
    # bloqueia até o Kindle entrar na tela de descanso
    subprocess.call(["lipc-wait-event", "com.lab126.powerd", "goingToScreenSaver"],
                    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


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
    if "--teste" in sys.argv:
        desenhar()
        return
    if "--fundo" in sys.argv:
        ir_para_fundo(os.path.join(PASTA, "painel.log"))
    print("%s painel iniciado (modo %s)" % (time.strftime("%Y-%m-%d %H:%M:%S"), MODO))
    if RECONECTAR_AO_ACORDAR:
        threading.Thread(target=vigiar_acordar, daemon=True).start()
    while True:
        inicio = time.time()
        esperar_dormir()
        if time.time() - inicio < 0.5:
            # lipc-wait-event saiu na hora: comando ausente ou com erro
            sys.stderr.write("lipc-wait-event falhou; o painel não consegue detectar o sono.\n")
            time.sleep(30)
            continue
        desenhar_enquanto_dorme()


if __name__ == "__main__":
    principal()
