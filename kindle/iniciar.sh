#!/bin/sh
#
# Kindle Envia - liga o servidor de livros e o painel da tela de descanso.
# É chamado sozinho no boot (por /etc/init.d/kindleenvia, instalado pelo instalar-boot.sh).
#
# Para testar na hora, pelo SSH:   sh /mnt/us/scripts/iniciar.sh agora
# Para desligar o início automático sem SSH: crie um arquivo chamado DESLIGAR
# nesta pasta (D:\scripts\DESLIGAR pelo USB).
#
PASTA=/mnt/us/scripts
LOG=$PASTA/iniciar.log
export PATH=/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin

[ -f $PASTA/DESLIGAR ] && exit 0

echo "`date` -- iniciar.sh $1" > $LOG

# No boot, espera o Kindle terminar de ligar (Wi-Fi, firewall, tela)
if [ "$1" != "agora" ] ; then
    sleep 45
fi

rodando() {
    pgrep -f "$1" > /dev/null 2>&1 && return 0
    ps w 2> /dev/null | grep "$1" | grep -v grep > /dev/null 2>&1
}

# Acha o Python 3 (o do NiLuJe nem sempre está no PATH)
PY=""
for p in /mnt/us/python3/bin/python3 /mnt/us/python3/bin/python3.9 /usr/bin/python3 /usr/local/bin/python3 ; do
    if [ -x "$p" ] ; then
        PY="$p"
        break
    fi
done
if [ -z "$PY" ] ; then
    echo "`date` ERRO: python3 nao encontrado" >> $LOG
    exit 1
fi
echo "`date` usando $PY" >> $LOG

for s in servidor painel ; do
    if [ ! -f $PASTA/$s.py ] ; then
        echo "`date` $s.py nao existe, pulando" >> $LOG
    elif rodando "scripts/$s.py" ; then
        echo "`date` $s ja estava rodando" >> $LOG
    else
        "$PY" $PASTA/$s.py --fundo >> $LOG 2>&1
        echo "`date` $s iniciado" >> $LOG
    fi
done
exit 0
