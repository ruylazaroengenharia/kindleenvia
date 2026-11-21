# 📚 Kindle Envia

Dá vida nova a um **Kindle 4 (sem touch)**: o PC converte arquivos, **fotos do caderno** (com IA) e o **jornal do dia** para o formato do Kindle e envia **pelo Wi-Fi**, sem cabo. No Kindle, um servidor próprio recebe os livros, gerencia as **telas de descanso** e um **painel** escreve a data, a bateria e uma frase do dia por cima do screensaver.

| No PC (Kindle Envia) | No Kindle |
|---|---|
| **📄 Arquivos**: PDF, imagens, SVG, Mermaid, texto e livros → AZW3 | **Servidor de livros** no navegador do celular ou do PC: baixar e enviar |
| **📓 Caderno (IA)**: foto da página → texto, resumo, diagrama ou desenho | **Telas de descanso**: ver, enviar (já ajustadas) e apagar |
| **📰 Notícias**: canais RSS → *Jornal do dia* com resumo da IA, enviado ao ligar o PC | **Painel**: data, bateria e frase do dia no rodapé do screensaver |
| **📮 Fila**: se o Kindle estiver dormindo, envia depois | **Início automático**: tudo volta sozinho quando o Kindle reinicia |

---

## ✅ Requisitos

### Kindle
- **Kindle 4 sem touch** (2011/2012), firmware **4.x**, número de série começando com **B00E** (prata) ou **B023** (preto).
- **Jailbreak**.
- Pacotes do NiLuJe: **USBNetwork** (SSH pelo Wi-Fi), **Python 3** e **ScreenSavers Hack** (telas de descanso).
- Wi-Fi 2,4 GHz (WPA/WPA2).

Não precisa de KUAL nem de KOReader.

### PC (Windows)
- **Kindle Envia**: o `KindleEnvia.exe` ou o Python 3.9+.
- **[Calibre](https://calibre-ebook.com)**: gera os arquivos AZW3 (o programa acha o `ebook-convert` sozinho).
- **Microsoft Edge** (já vem no Windows) ou Google Chrome: desenha os diagramas, sem abrir janela.
- **IA** (opcional, para o Caderno e o resumo das notícias): Gemini, Claude, OpenAI ou Ollama (grátis, no próprio PC).

---

## 🛠️ Instalação

### Parte 1: o Kindle

> Os pacotes `.bin` são instalados todos do mesmo jeito: copie **um** `.bin` para a **raiz** do Kindle (pelo USB), ejete e vá em **Menu → Configurações → Menu → Atualizar seu Kindle**. Espere ele reiniciar antes de instalar o próximo.

#### 1. Jailbreak
Siga o guia do **[kindle4-revival](https://github.com/kxrz/kindle4-revival)** (passos de 1 a 3): copie `data.tar.gz`, `ENABLE_DIAGS` e a pasta `diagnostic_logs/` para a raiz, reinicie e escolha **D → R** na tela de diagnóstico. Quando aparecer o documento **"You are Jailbroken"**, deu certo.

#### 2. Pacotes do NiLuJe
Baixe na lista de pacotes do NiLuJe, seção *"Packages targeting the Kindle 2/DX/DXG/3/4"* ([tópico no MobileRead](https://www.mobileread.com/forums/showthread.php?t=225030)). Os arquivos são `.tar.xz`: abra com o **7-Zip** e use **só os `.bin` de K4**.

| Pacote | Arquivo para instalar | Para quê |
|---|---|---|
| **Python** (`kindle-python-*.tar.xz`) | `Update_python3_*_k4_install.bin` | roda o servidor e o painel |
| **ScreenSavers Hack** (`kindle-ss-*.tar.xz`) | `Update_ss_*_k4_install.bin` | telas de descanso próprias (pasta `linkss/screensavers`) |
| **USBNetwork** (`kindle-usbnetwork-*.tar.xz`) | `Update_usbnetwork_*_k4_install.bin` | SSH pelo Wi-Fi |

Guarde os `..._uninstall.bin` no PC: são os desinstaladores.

#### 3. SSH pelo Wi-Fi
Com o Kindle no USB (aqui como `D:`), no **PowerShell**:

```powershell
# chave SSH (só na primeira vez; aperte Enter nas 3 perguntas)
ssh-keygen -t ed25519

# coloca a chave no Kindle, com quebra de linha UNIX
$k = (Get-Content $env:USERPROFILE\.ssh\id_ed25519.pub -Raw).Trim()
[IO.File]::WriteAllText("D:\usbnet\etc\authorized_keys", "$k`n")

# liga o SSH sozinho no boot
New-Item D:\usbnet\auto -ItemType File
```

Em `D:\usbnet\etc\config` (edite com Notepad++ ou VS Code, mantendo **LF**), mude:
```sh
K3_WIFI="true"
K3_WIFI_SSHD_ONLY="true"
```

Ejete, reinicie o Kindle, ligue o Wi-Fi (sem modo avião) e teste: `ssh root@IP-DO-KINDLE`.

> Dica: reserve um IP fixo para o Kindle no roteador (Reserva de DHCP). Para não digitar o IP sempre, crie um atalho:
> `Add-Content $env:USERPROFILE\.ssh\config -Encoding ascii "`nHost kindle`n    HostName IP-DO-KINDLE`n    User root`n"` → depois é só `ssh kindle`.

#### 4. Scripts do Kindle Envia
1. Copie o conteúdo da pasta [`kindle/`](kindle/) para **`D:\scripts`**.
2. Abra `D:\scripts\servidor.py` e troque `SENHA = "troque-esta-senha"` por uma senha sua.
3. Pelo SSH, teste e depois instale o início automático:
   ```sh
   sh /mnt/us/scripts/iniciar.sh agora      # liga o servidor e o painel agora
   cat /mnt/us/scripts/iniciar.log          # deve dizer "servidor iniciado" e "painel iniciado"
   sh /mnt/us/scripts/instalar-boot.sh      # liga sozinho em todo boot
   ```
4. Abra **`http://IP-DO-KINDLE:8000`** no celular ou no PC e entre com a senha.

#### 5. Acertos finais
- **Hora:** se o `date` no SSH mostrar um fuso estranho (ex.: `GMT-00:44`), acerte a hora em **Menu → Configurações → Menu → Hora do dispositivo**.
- **Frases do painel:** edite `D:\scripts\frases.txt` (uma por linha) ou pela página **Telas de descanso** do servidor.

### Parte 2: o PC

1. Instale o **[Calibre](https://calibre-ebook.com)**.
2. Rode o Kindle Envia:
   - **pelo Python:** `pip install -r requirements.txt` e depois `python kindle_envia.py`;
   - **ou gere o `.exe`:** rode `construir.bat` (precisa do Python) e use o `KindleEnvia.exe`.
3. Aba **📖 Kindle**: IP, porta (`8000`) e a mesma senha do `servidor.py` → **Testar conexão**. Confira se aparece **"✔ Calibre encontrado"**.
4. Aba **🤖 IA** (opcional):

| IA | Como preencher |
|---|---|
| **Gemini** | *OpenAI ou compatível* · Endereço `https://generativelanguage.googleapis.com/v1beta/openai` · chave do [Google AI Studio](https://aistudio.google.com) · **Buscar modelos** → um *flash* · *Modelo p/ fotos* em branco |
| **Claude** | chave em [console.anthropic.com](https://console.anthropic.com) · *Modelo p/ fotos* em branco |
| **Ollama** (grátis) | instale em [ollama.com](https://ollama.com) e rode `ollama pull qwen2.5:7b` e `ollama pull qwen2.5vl:7b` |

Na primeira vez, o programa aproveita a IA já configurada no [Quadro Branco](https://github.com/ruylazaroengenharia/quadrobranco), se houver.

---

## 📖 Como usar

### 📄 Arquivos
Adicione os arquivos e clique em **Converter e enviar ao Kindle**. O formato de saída é escolhido na aba **📖 Kindle**:

- **AZW3 (recomendado)**: o texto se ajusta à tela, dá para mudar a letra, o dicionário funciona e as páginas viram rápido. Fotos e diagramas viram páginas de tela cheia.
- **MOBI**: o mesmo, para firmwares antigos.
- **PDF**: páginas no tamanho exato da tela (600×800). É mais pesado no Kindle 4.

Para **PDFs** que você manda, há 4 modos: *Original*, *Ampliar* (corta as margens), *Dividir ao meio* (cada página vira duas, para ler com o Kindle deitado) e *Refazer como texto* (o Calibre transforma em livro; só para PDFs de texto). Imagens e diagramas deitados são girados para ocupar a tela.

### 📓 Caderno (IA)
1. Adicione as fotos das páginas e escolha: **texto** (transcreve a letra), **resumo organizado**, **diagrama** ou **desenho limpo**.
2. **Ler com IA**: o resultado aparece para você revisar e corrigir.
3. **Criar e enviar**.

### 📰 Notícias
Escolha os canais RSS (dois cliques ligam e desligam). **Gerar agora e enviar** cria o *Jornal do dia*, com capa, sumário, resumo da IA e as manchetes de cada fonte. Os jornais ficam na pasta `Noticias` do Kindle, e os mais velhos que o número de dias escolhido são apagados.

Marque **"Gerar e enviar sozinho quando o PC ligar"** para rodar `KindleEnvia --auto` ao iniciar o Windows. Ele monta o jornal uma vez por dia e, se o Kindle estiver dormindo, tenta de novo a cada 5 minutos por até 4 horas. O registro fica em `%APPDATA%\KindleEnvia\auto.log`.

### 🖱️ Enviar para > Kindle
Na aba **📖 Kindle**, ligue a opção do menu **Enviar para**. Depois é só clicar com o botão direito num arquivo no Explorador → **Enviar para** → **Kindle**.

### 🖼️ No Kindle: servidor, telas e painel
Em **`http://IP-DO-KINDLE:8000`**:
- **📚 Livros**: lista, baixa e envia livros (AZW3, MOBI, PDF, TXT).
- **🖼️ Telas de descanso**: mostra as imagens do ScreenSavers Hack, envia novas (o navegador ajusta para 600×800 em cinza, com opção de deixar o rodapé livre para o painel), apaga, edita as frases do painel e reinicia o Kindle.

O **painel** escreve a data, a bateria e a frase do dia no rodapé sempre que o Kindle dorme. A troca de frase é diária, em sequência.

---

## 🔌 API do servidor

Qualquer programa pode enviar para o Kindle:

```powershell
curl.exe -F "livro=@C:\caminho\arquivo.azw3" "http://IP-DO-KINDLE:8000/enviar?k=SENHA&formato=json"
```

| Rota | O que faz |
|---|---|
| `POST /enviar?k=SENHA&formato=json[&pasta=Nome]` | recebe arquivos no campo `livro` (multipart) → `{"enviados": [...], "recusados": [...]}` |
| `GET /listar?k=SENHA` | lista os livros em JSON (`arquivo`, `tamanho`, `modificado`) |
| `POST /apagar?k=SENHA&f=caminho/relativo.pdf` | apaga um arquivo (e as anotações `.sdr` dele) |
| `POST /telas/enviar?k=SENHA&formato=json` | recebe telas de descanso no campo `imagem` (PNG/JPG, 600×800) |
| `GET /ping?k=SENHA` | teste de conexão e espaço livre |

---

## 🩺 Problemas comuns

| Sintoma | O que fazer |
|---|---|
| O PC não acha o Kindle | O Kindle desliga o Wi-Fi quando dorme. Acorde o Kindle e confira o Wi-Fi. Os arquivos ficam na **fila** e são enviados depois. |
| O IP mudou depois de reiniciar | Reserve o IP no roteador e atualize na aba **📖 Kindle** e no `.ssh\config`. |
| O servidor ou o painel não voltaram depois do boot | `cat /mnt/us/scripts/iniciar.log`. Para desligar o início automático sem SSH, crie um arquivo vazio `D:\scripts\DESLIGAR`. Para remover de vez: `sh /mnt/us/scripts/instalar-boot.sh remover`. |
| `ps` não mostra os scripts | O `ps` do Kindle 4 é antigo e corta o nome. Use `pgrep -f servidor.py`. |
| `nohup: not found` | Normal no Kindle 4: os scripts usam `--fundo` no lugar do `nohup`. |
| A imagem do screensaver cobre a faixa | O painel redesenha aos 2, 5 e 9 segundos (`REDESENHOS` no `painel.py`). Aumente os tempos se precisar. |
| "Address already in use" | O servidor já está rodando (pode ter sido o início automático). |
| Diagramas não saem | O Edge é usado para desenhar. Veja a mensagem de erro (ela mostra o que o Edge respondeu). |

---

## 📁 Arquivos

| Arquivo | Para quê |
|---|---|
| `kindle_envia.py` | janela e modo automático (`--auto`) |
| `conversor.py` | conversões (AZW3/MOBI pelo Calibre, PDF, imagens, Mermaid, SVG) |
| `caderno.py` | fotos do caderno com IA |
| `noticias.py` | canais RSS e Jornal do dia |
| `kindle.py` | envio, fila e limpeza no Kindle |
| `ia.py` | provedores de IA (vem do Quadro Branco) |
| `config.py` | configuração em `%APPDATA%\KindleEnvia` |
| `kindle/servidor.py` | **vai para o Kindle**: servidor de livros, telas de descanso e frases |
| `kindle/painel.py` | **vai para o Kindle**: faixa com data, bateria e frase no screensaver |
| `kindle/frases.txt` | **vai para o Kindle**: frases do painel |
| `kindle/iniciar.sh` | **vai para o Kindle**: liga o servidor e o painel |
| `kindle/instalar-boot.sh` | **vai para o Kindle**: instala/remove o início automático (`/etc/rc5.d/S99kindleenvia`) |

## 🙏 Créditos

- **NiLuJe** e comunidade do [MobileRead](https://www.mobileread.com/forums/): jailbreak, USBNetwork, Python e ScreenSavers Hack para os Kindles antigos.
- **[kindle4-revival](https://github.com/kxrz/kindle4-revival)**: guia atualizado do jailbreak do Kindle 4.
- **[Calibre](https://calibre-ebook.com)**, **[Mermaid](https://mermaid.js.org/)**, **[Pillow](https://python-pillow.org/)** e **[PyMuPDF](https://pymupdf.readthedocs.io/)**.

## Licença

MIT. O Mermaid (em `vendor/`) é MIT. O PyMuPDF é AGPL: se for distribuir o `.exe`, veja a licença dele.
