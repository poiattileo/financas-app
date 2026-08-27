#!/bin/bash
# ============================================================
#  Instalador automático — Planejamento Financeiro Aryan
#  Ubuntu 22.04 / 24.04
#  Rode com: sudo bash instalar.sh
# ============================================================
set -e

RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'; NC='\033[0m'
ok()  { echo -e "${GREEN}✓ $1${NC}"; }
info(){ echo -e "${YELLOW}→ $1${NC}"; }
err() { echo -e "${RED}✗ $1${NC}"; exit 1; }

[ "$EUID" -ne 0 ] && err "Rode como root: sudo bash instalar.sh"

# ── 1. Variáveis ──────────────────────────────────────────
APP_DIR=/opt/financas
DB_NAME=financas
DB_USER=financas
DB_PASS=$(openssl rand -base64 18 | tr -dc 'a-zA-Z0-9' | head -c 24)
JWT_SECRET=$(openssl rand -base64 32 | tr -dc 'a-zA-Z0-9' | head -c 48)

info "Atualizando pacotes..."
apt-get update

# ── 2. Nginx ──────────────────────────────────────────────
info "Instalando Nginx..."
apt-get install -y nginx
ok "Nginx instalado"

# ── 3. MariaDB ────────────────────────────────────────────
info "Instalando MariaDB..."
apt-get install -y mariadb-server
systemctl enable mariadb
systemctl start mariadb
ok "MariaDB instalado"

# ── 4. Python ─────────────────────────────────────────────
info "Instalando Python 3 e pip..."
apt-get install -y python3 python3-pip python3-venv
ok "Python instalado"

# ── 5. Estrutura de pastas ────────────────────────────────
info "Criando estrutura em $APP_DIR..."
mkdir -p $APP_DIR/backend
mkdir -p $APP_DIR/frontend
ok "Pastas criadas"

# ── 6. Copia arquivos ─────────────────────────────────────
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

info "Copiando backend..."
cp "$SCRIPT_DIR/backend/main.py"          $APP_DIR/backend/
cp "$SCRIPT_DIR/backend/requirements.txt" $APP_DIR/backend/
cp "$SCRIPT_DIR/backend/schema.sql"       $APP_DIR/backend/
cp "$SCRIPT_DIR/backend/criar_usuario.py" $APP_DIR/backend/

info "Copiando frontend..."
cp "$SCRIPT_DIR/frontend/index.html" $APP_DIR/frontend/
cp "$SCRIPT_DIR/frontend/manifest.json" $APP_DIR/frontend/
ok "Arquivos copiados"

# ── 7. Banco de dados ─────────────────────────────────────
# No Ubuntu 24 o MariaDB usa unix_socket por padrão.
# Criamos o banco e o usuário via root (socket) e depois
# configuramos autenticação por senha para o usuário da app.
info "Configurando banco MariaDB..."

mysql << SQLEOF
CREATE DATABASE IF NOT EXISTS ${DB_NAME} CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;

-- Remove usuário anterior se existir (para reinstalações)
DROP USER IF EXISTS '${DB_USER}'@'localhost';

-- Cria com autenticação por senha nativa (funciona no Ubuntu 24)
CREATE USER '${DB_USER}'@'localhost' IDENTIFIED VIA mysql_native_password USING PASSWORD('${DB_PASS}');
GRANT ALL PRIVILEGES ON ${DB_NAME}.* TO '${DB_USER}'@'localhost';
FLUSH PRIVILEGES;

USE ${DB_NAME};

CREATE TABLE IF NOT EXISTS usuarios (
    id          INT AUTO_INCREMENT PRIMARY KEY,
    username    VARCHAR(50) UNIQUE NOT NULL,
    senha_hash  VARCHAR(255) NOT NULL,
    salario     DECIMAL(12,2) DEFAULT 0,
    mes_inicio  VARCHAR(7) DEFAULT '',
    criado_em   DATETIME DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS gastos (
    id          INT AUTO_INCREMENT PRIMARY KEY,
    user_id     INT NOT NULL,
    nome        VARCHAR(100) NOT NULL,
    cat         VARCHAR(50) NOT NULL,
    criado_em   DATETIME DEFAULT NOW(),
    FOREIGN KEY (user_id) REFERENCES usuarios(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS gasto_valores (
    gasto_id    INT NOT NULL,
    idx         TINYINT NOT NULL,
    valor       DECIMAL(12,2) NOT NULL,
    PRIMARY KEY (gasto_id, idx),
    FOREIGN KEY (gasto_id) REFERENCES gastos(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS parcelas (
    id              INT AUTO_INCREMENT PRIMARY KEY,
    user_id         INT NOT NULL,
    nome            VARCHAR(100) NOT NULL,
    cat             VARCHAR(50) NOT NULL,
    total           DECIMAL(12,2) NOT NULL,
    qtd             TINYINT NOT NULL,
    mes_idx         TINYINT NOT NULL,
    valor_parcela   DECIMAL(12,2) NOT NULL,
    criado_em       DATETIME DEFAULT NOW(),
    FOREIGN KEY (user_id) REFERENCES usuarios(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS lancamentos (
    id          INT AUTO_INCREMENT PRIMARY KEY,
    user_id     INT NOT NULL,
    descricao   VARCHAR(150) NOT NULL,
    valor       DECIMAL(12,2) NOT NULL,
    cat         VARCHAR(50) NOT NULL DEFAULT 'outros',
    local_nome  VARCHAR(100) DEFAULT '',
    recorrencia VARCHAR(20) DEFAULT 'nunca',
    criado_em   DATETIME DEFAULT NOW(),
    FOREIGN KEY (user_id) REFERENCES usuarios(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS metas (
    id          INT AUTO_INCREMENT PRIMARY KEY,
    user_id     INT NOT NULL,
    nome        VARCHAR(100) NOT NULL,
    valor_alvo  DECIMAL(12,2) NOT NULL,
    valor_atual DECIMAL(12,2) DEFAULT 0,
    cor         VARCHAR(20) DEFAULT 'green',
    criado_em   DATETIME DEFAULT NOW(),
    FOREIGN KEY (user_id) REFERENCES usuarios(id) ON DELETE CASCADE
);
SQLEOF

ok "Banco criado: $DB_NAME / usuário: $DB_USER"

# ── 8. Ambiente Python ────────────────────────────────────
info "Criando virtualenv e instalando dependências..."
python3 -m venv /opt/financas/venv
/opt/financas/venv/bin/pip install --upgrade pip
/opt/financas/venv/bin/pip install -r $APP_DIR/backend/requirements.txt
ok "Dependências Python instaladas"

# ── 9. Arquivo .env ───────────────────────────────────────
info "Criando .env..."
cat > $APP_DIR/backend/.env << ENV
DB_HOST=localhost
DB_USER=${DB_USER}
DB_PASS=${DB_PASS}
DB_NAME=${DB_NAME}
JWT_SECRET=${JWT_SECRET}
ENV
chmod 600 $APP_DIR/backend/.env
ok ".env criado com senhas geradas automaticamente"

# ── 10. Serviço systemd ───────────────────────────────────
info "Configurando serviço systemd..."
cat > /etc/systemd/system/financas.service << SERVICE
[Unit]
Description=Financas Backend API
After=network.target mariadb.service

[Service]
User=www-data
WorkingDirectory=${APP_DIR}/backend
EnvironmentFile=${APP_DIR}/backend/.env
ExecStart=/opt/financas/venv/bin/uvicorn main:app --host 127.0.0.1 --port 8000
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
SERVICE

chown -R www-data:www-data $APP_DIR
systemctl daemon-reload
systemctl enable financas
systemctl start financas
sleep 2
systemctl is-active financas && ok "Serviço backend rodando" || err "Falha ao iniciar backend — rode: journalctl -u financas -n 30"

# ── 11. Nginx ─────────────────────────────────────────────
info "Configurando Nginx..."
cat > /etc/nginx/sites-available/financas << NGINX
server {
    listen 80;
    server_name _;

    root ${APP_DIR}/frontend;
    index index.html;

    location / {
        try_files \$uri \$uri/ /index.html;
    }

    location /api/ {
        proxy_pass         http://127.0.0.1:8000;
        proxy_set_header   Host \$host;
        proxy_set_header   X-Real-IP \$remote_addr;
        proxy_set_header   X-Forwarded-For \$proxy_add_x_forwarded_for;
        proxy_read_timeout 60s;
    }
}
NGINX

rm -f /etc/nginx/sites-enabled/default
ln -sf /etc/nginx/sites-available/financas /etc/nginx/sites-enabled/financas
nginx -t
systemctl reload nginx
ok "Nginx configurado"

# ── 12. Firewall ──────────────────────────────────────────
if command -v ufw &>/dev/null; then
  info "Liberando firewall..."
  ufw allow 80/tcp
  ufw allow 22/tcp
  ok "Firewall configurado"
fi

# ── 13. Criar usuário admin ───────────────────────────────
echo ""
echo -e "${YELLOW}══════════════════════════════════════════${NC}"
echo -e "${YELLOW}  Criando seu usuário de acesso           ${NC}"
echo -e "${YELLOW}══════════════════════════════════════════${NC}"

DB_HOST=localhost DB_USER=${DB_USER} DB_PASS=${DB_PASS} DB_NAME=${DB_NAME} \
  /opt/financas/venv/bin/python3 $APP_DIR/backend/criar_usuario.py

# ── Fim ───────────────────────────────────────────────────
IP=$(hostname -I | awk '{print $1}')
echo ""
echo -e "${GREEN}══════════════════════════════════════════${NC}"
echo -e "${GREEN}  Instalação concluída!                   ${NC}"
echo -e "${GREEN}══════════════════════════════════════════${NC}"
echo ""
echo -e "  Acesse: ${YELLOW}http://$IP${NC}"
echo ""
echo -e "  Para criar mais usuários no futuro:"
echo -e "  ${YELLOW}sudo DB_HOST=localhost DB_USER=${DB_USER} DB_PASS=${DB_PASS} DB_NAME=${DB_NAME} /opt/financas/venv/bin/python3 /opt/financas/backend/criar_usuario.py${NC}"
echo ""
echo -e "  Logs do backend:  ${YELLOW}journalctl -u financas -f${NC}"
echo ""
