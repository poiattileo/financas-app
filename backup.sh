#!/bin/bash
# ============================================================
#  Backup automático do banco MariaDB — Finanças Aryan
#  Instalação: sudo bash backup.sh --instalar
#  Manual:     sudo bash backup.sh
# ============================================================
BACKUP_DIR=/opt/financas/backups
MANTER_DIAS=30
ENV_FILE=/opt/financas/backend/.env

# Carrega variáveis do .env
if [ -f "$ENV_FILE" ]; then
    export $(grep -v '^#' "$ENV_FILE" | xargs)
fi

DB_HOST="${DB_HOST:-localhost}"
DB_USER="${DB_USER:-financas}"
DB_PASS="${DB_PASS:-}"
DB_NAME="${DB_NAME:-financas}"

fazer_backup() {
    mkdir -p "$BACKUP_DIR"
    ARQUIVO="$BACKUP_DIR/financas_$(date +%Y%m%d_%H%M%S).sql.gz"
    mysqldump -h"$DB_HOST" -u"$DB_USER" -p"$DB_PASS" "$DB_NAME" 2>/dev/null | gzip > "$ARQUIVO"
    if [ $? -eq 0 ] && [ -s "$ARQUIVO" ]; then
        echo "✓ Backup criado: $ARQUIVO ($(du -sh "$ARQUIVO" | cut -f1))"
        # Remove backups antigos
        find "$BACKUP_DIR" -name "*.sql.gz" -mtime +$MANTER_DIAS -delete
        QTD=$(ls "$BACKUP_DIR"/*.sql.gz 2>/dev/null | wc -l)
        echo "  Total de backups mantidos: $QTD"
    else
        echo "✗ Falha no backup!"
        rm -f "$ARQUIVO"
        exit 1
    fi
}

instalar_cron() {
    # Copia script para local permanente
    cp "$0" /opt/financas/backup.sh
    chmod +x /opt/financas/backup.sh
    # Adiciona ao cron do root (todo dia às 3h da manhã)
    CRON_LINE="0 3 * * * /opt/financas/backup.sh >> /var/log/financas-backup.log 2>&1"
    (crontab -l 2>/dev/null | grep -v financas-backup; echo "$CRON_LINE") | crontab -
    echo "✓ Backup automático instalado: todo dia às 03:00"
    echo "  Backups salvos em: $BACKUP_DIR"
    echo "  Log em: /var/log/financas-backup.log"
    echo "  Mantém últimos $MANTER_DIAS dias"
    echo ""
    echo "  Para restaurar um backup:"
    echo "  zcat $BACKUP_DIR/financas_XXXXXXXX.sql.gz | mysql -u$DB_USER -p $DB_NAME"
}

if [ "$1" = "--instalar" ]; then
    instalar_cron
    fazer_backup
else
    fazer_backup
fi
