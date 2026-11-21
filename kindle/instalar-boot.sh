#!/bin/sh
#
# Kindle Envia - instala (ou remove) o início automático no boot do Kindle 4.
#
#   sh /mnt/us/scripts/instalar-boot.sh            instala
#   sh /mnt/us/scripts/instalar-boot.sh remover    remove
#
# Cria /etc/init.d/kindleenvia (um gatilho de poucas linhas) e o link
# /etc/rc5.d/S99kindleenvia, o último a rodar no boot. Toda a lógica fica em
# /mnt/us/scripts/iniciar.sh, que você pode editar pelo USB.
#
INIT=/etc/init.d/kindleenvia
LINK=/etc/rc5.d/S99kindleenvia

if [ ! -d /etc/rc5.d ] || [ ! -d /etc/init.d ] ; then
    echo "Este Kindle não usa /etc/rc5.d. Nada foi alterado."
    exit 1
fi

mntroot rw || { echo "Não consegui liberar o sistema para escrita (mntroot rw)."; exit 1; }

if [ "$1" = "remover" ] ; then
    rm -f $LINK $INIT
    mntroot ro
    echo "Início automático removido."
    exit 0
fi

cat > $INIT << 'FIM'
#!/bin/sh
# Kindle Envia: no boot, chama /mnt/us/scripts/iniciar.sh em segundo plano.
# Para desligar sem SSH, crie o arquivo D:\scripts\DESLIGAR pelo USB.
case "$1" in
    start)
        if [ -f /mnt/us/scripts/iniciar.sh ] && [ ! -f /mnt/us/scripts/DESLIGAR ] ; then
            /bin/sh /mnt/us/scripts/iniciar.sh < /dev/null > /dev/null 2>&1 &
        fi
        ;;
esac
exit 0
FIM
chmod 755 $INIT
ln -sf $INIT $LINK
sync
mntroot ro

if [ -x $INIT ] && [ -L $LINK ] ; then
    echo "Pronto! No próximo boot, o servidor e o painel ligam sozinhos (cerca de 1 minuto depois)."
    echo "Log: /mnt/us/scripts/iniciar.log"
else
    echo "Algo deu errado: confira $INIT e $LINK."
    exit 1
fi
