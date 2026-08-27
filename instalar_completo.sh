#!/bin/bash
set -e
echo "======================================"
echo "  Instalador Finanças - Aryan Ferrari"
echo "======================================"

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
APP_DIR=/opt/financas
DB_NAME=financas
DB_USER=financas
DB_PASS=$(cat /dev/urandom | tr -dc 'A-Za-z0-9' | head -c 24)
JWT_SECRET=$(cat /dev/urandom | tr -dc 'A-Za-z0-9' | head -c 32)
PORT=80

# Se já existe .env, usa a senha existente
if [ -f "$APP_DIR/backend/.env" ]; then
    echo "→ Instalação existente detectada, mantendo senha do banco..."
    DB_PASS=$(grep DB_PASS $APP_DIR/backend/.env | cut -d= -f2)
    JWT_SECRET=$(grep JWT_SECRET $APP_DIR/backend/.env | cut -d= -f2)
fi

echo ""
echo "1. Instalando dependências do sistema..."
apt-get update -qq
apt-get install -y -qq python3 python3-pip python3-venv nginx mariadb-server curl

echo "2. Configurando MariaDB para UTF8MB4..."
tee /etc/mysql/mariadb.conf.d/99-utf8mb4.cnf > /dev/null << 'EOF'
[mysqld]
character-set-server = utf8mb4
collation-server = utf8mb4_unicode_ci
init-connect = 'SET NAMES utf8mb4'
[client]
default-character-set = utf8mb4
[mysql]
default-character-set = utf8mb4
EOF
systemctl restart mariadb
systemctl enable mariadb

echo "3. Criando banco de dados e usuário..."
mysql -u root << SQLEOF
CREATE DATABASE IF NOT EXISTS ${DB_NAME} CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
DROP USER IF EXISTS '${DB_USER}'@'localhost';
CREATE USER '${DB_USER}'@'localhost' IDENTIFIED VIA mysql_native_password USING PASSWORD('${DB_PASS}');
GRANT ALL PRIVILEGES ON ${DB_NAME}.* TO '${DB_USER}'@'localhost';
FLUSH PRIVILEGES;
SQLEOF

echo "4. Criando schema do banco..."
mysql -u root ${DB_NAME} << 'SQLEOF'
CREATE TABLE IF NOT EXISTS usuarios (
    id         INT AUTO_INCREMENT PRIMARY KEY,
    username   VARCHAR(50) UNIQUE NOT NULL,
    senha_hash VARCHAR(200) NOT NULL,
    salario    DECIMAL(12,2) DEFAULT 0,
    mes_inicio VARCHAR(7) DEFAULT '',
    role       VARCHAR(20) DEFAULT 'user',
    criado_em  DATETIME DEFAULT NOW()
);
CREATE TABLE IF NOT EXISTS gastos (
    id        INT AUTO_INCREMENT PRIMARY KEY,
    user_id   INT NOT NULL,
    nome      VARCHAR(100) NOT NULL,
    cat       VARCHAR(50) DEFAULT 'outros',
    criado_em DATETIME DEFAULT NOW(),
    FOREIGN KEY (user_id) REFERENCES usuarios(id) ON DELETE CASCADE
);
CREATE TABLE IF NOT EXISTS gasto_valores (
    gasto_id INT NOT NULL,
    idx      TINYINT NOT NULL,
    valor    DECIMAL(12,2) DEFAULT 0,
    PRIMARY KEY (gasto_id, idx),
    FOREIGN KEY (gasto_id) REFERENCES gastos(id) ON DELETE CASCADE
);
CREATE TABLE IF NOT EXISTS parcelas (
    id            INT AUTO_INCREMENT PRIMARY KEY,
    user_id       INT NOT NULL,
    nome          VARCHAR(100) NOT NULL,
    cat           VARCHAR(50) DEFAULT 'outros',
    total         DECIMAL(12,2) NOT NULL,
    qtd           INT NOT NULL,
    mes_idx       TINYINT NOT NULL,
    valor_parcela DECIMAL(12,2) NOT NULL,
    criado_em     DATETIME DEFAULT NOW(),
    FOREIGN KEY (user_id) REFERENCES usuarios(id) ON DELETE CASCADE
);
CREATE TABLE IF NOT EXISTS lancamentos (
    id          INT AUTO_INCREMENT PRIMARY KEY,
    user_id     INT NOT NULL,
    descricao   VARCHAR(150) NOT NULL,
    valor       DECIMAL(12,2) NOT NULL,
    cat         VARCHAR(50) DEFAULT 'outros',
    local_nome  VARCHAR(100) DEFAULT '',
    recorrencia VARCHAR(20) DEFAULT 'nunca',
    motivo      VARCHAR(200) DEFAULT '',
    mes_idx     TINYINT DEFAULT NULL,
    criado_em   DATETIME DEFAULT NOW(),
    FOREIGN KEY (user_id) REFERENCES usuarios(id) ON DELETE CASCADE
);
CREATE TABLE IF NOT EXISTS lancamento_anexos (
    id            INT AUTO_INCREMENT PRIMARY KEY,
    lancamento_id INT NOT NULL,
    nome_original VARCHAR(255) CHARACTER SET utf8mb4 NOT NULL,
    nome_arquivo  VARCHAR(255) NOT NULL,
    tipo          VARCHAR(100) DEFAULT 'application/octet-stream',
    tamanho       INT DEFAULT 0,
    criado_em     DATETIME DEFAULT NOW(),
    FOREIGN KEY (lancamento_id) REFERENCES lancamentos(id) ON DELETE CASCADE
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
CREATE TABLE IF NOT EXISTS categorias (
    id    INT AUTO_INCREMENT PRIMARY KEY,
    nome  VARCHAR(50) UNIQUE NOT NULL,
    label VARCHAR(80) NOT NULL,
    emoji VARCHAR(10) CHARACTER SET utf8mb4 DEFAULT '',
    cor   VARCHAR(20) DEFAULT '#94a3b8',
    tipo  VARCHAR(20) DEFAULT 'ambos'
) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;

-- Categorias padrão
INSERT IGNORE INTO categorias (nome,label,emoji,cor,tipo) VALUES
('moradia','Moradia','🏠','#60a5fa','gasto'),
('transporte','Transporte','🚗','#fbbf24','ambos'),
('alimentacao','Alimentação','🍔','#f97316','ambos'),
('saude','Saúde','💊','#34d399','ambos'),
('educacao','Educação','📚','#f472b6','gasto'),
('assinaturas','Assinaturas','📱','#a78bfa','gasto'),
('financiamento','Financiamento','🏦','#f87171','gasto'),
('eletronicos','Eletrônicos','💻','#818cf8','gasto'),
('moveis','Móveis','🛋','#fb923c','gasto'),
('roupas','Roupas','👕','#e879f9','ambos'),
('lazer','Lazer','🎮','#c084fc','lancamento'),
('outros','Outros','💳','#94a3b8','ambos');

-- Torna o primeiro usuário admin (se existir)
UPDATE usuarios SET role='admin' ORDER BY id ASC LIMIT 1;
SQLEOF

echo "5. Criando estrutura de pastas..."
mkdir -p $APP_DIR/{backend,frontend,uploads}

echo "6. Copiando arquivos..."
cp "$SCRIPT_DIR/backend/main.py" $APP_DIR/backend/
cp "$SCRIPT_DIR/frontend/index.html" $APP_DIR/frontend/
cp "$SCRIPT_DIR/frontend/manifest.json" $APP_DIR/frontend/

echo "7. Criando .env..."
cat > $APP_DIR/backend/.env << ENVEOF
DB_HOST=localhost
DB_USER=${DB_USER}
DB_PASS=${DB_PASS}
DB_NAME=${DB_NAME}
JWT_SECRET=${JWT_SECRET}
ENVEOF

echo "8. Criando ambiente Python e instalando dependências..."
python3 -m venv $APP_DIR/venv
$APP_DIR/venv/bin/pip install --quiet fastapi uvicorn mysql-connector-python bcrypt pyjwt python-multipart

echo "9. Criando usuário admin..."
$APP_DIR/venv/bin/python3 << PYEOF
import sys
sys.path.insert(0, '$APP_DIR/backend')
import bcrypt, mysql.connector, os
from dotenv import load_dotenv
# lê .env manualmente
env = {}
with open('$APP_DIR/backend/.env') as f:
    for line in f:
        if '=' in line:
            k,v = line.strip().split('=',1)
            env[k] = v
db = mysql.connector.connect(host=env['DB_HOST'],user=env['DB_USER'],password=env['DB_PASS'],database=env['DB_NAME'])
cur = db.cursor()
# só cria se não existir
cur.execute("SELECT COUNT(*) FROM usuarios WHERE username='leonardo'")
if cur.fetchone()[0] == 0:
    h = bcrypt.hashpw(b'leonardo123', bcrypt.gensalt()).decode()
    cur.execute("INSERT INTO usuarios (username,senha_hash,role) VALUES ('leonardo',%s,'admin')", (h,))
    db.commit()
    print("Usuário 'leonardo' criado com senha 'leonardo123'")
else:
    print("Usuário 'leonardo' já existe")
cur.close(); db.close()
PYEOF

echo "10. Configurando serviço systemd..."
cat > /etc/systemd/system/financas.service << SVCEOF
[Unit]
Description=Financas Backend API
After=network.target mariadb.service financas-db-setup.service

[Service]
User=www-data
WorkingDirectory=${APP_DIR}/backend
EnvironmentFile=${APP_DIR}/backend/.env
ExecStart=${APP_DIR}/venv/bin/uvicorn main:app --host 127.0.0.1 --port 8000
Restart=always
RestartSec=3

[Install]
WantedBy=multi-user.target
SVCEOF

echo "11. Configurando auto-fix do banco MariaDB..."
cat > /usr/local/bin/financas-db-setup.sh << 'FIXEOF'
#!/bin/bash
sleep 3
if [ -f /opt/financas/backend/.env ]; then
    source /opt/financas/backend/.env
    mysql -u root -e "CREATE USER IF NOT EXISTS '${DB_USER}'@'localhost' IDENTIFIED VIA mysql_native_password USING PASSWORD('${DB_PASS}');" 2>/dev/null
    mysql -u root -e "GRANT ALL PRIVILEGES ON ${DB_NAME}.* TO '${DB_USER}'@'localhost';" 2>/dev/null
    mysql -u root -e "FLUSH PRIVILEGES;" 2>/dev/null
fi
FIXEOF
chmod +x /usr/local/bin/financas-db-setup.sh

cat > /etc/systemd/system/financas-db-setup.service << 'SVCEOF'
[Unit]
Description=Garante usuario MariaDB para Financas
After=mariadb.service
Before=financas.service
Requires=mariadb.service

[Service]
Type=oneshot
ExecStart=/usr/local/bin/financas-db-setup.sh
RemainAfterExit=yes

[Install]
WantedBy=multi-user.target
SVCEOF

echo "12. Configurando Nginx na porta ${PORT}..."
cat > /etc/nginx/sites-available/financas << NGINXEOF
server {
    listen ${PORT};
    server_name _;
    root ${APP_DIR}/frontend;
    index index.html;
    client_max_body_size 50M;

    location / {
        try_files \$uri \$uri/ /index.html;
    }
    location /api/ {
        proxy_pass         http://127.0.0.1:8000;
        proxy_set_header   Host \$host;
        proxy_set_header   X-Real-IP \$remote_addr;
        proxy_set_header   X-Forwarded-For \$proxy_add_x_forwarded_for;
        proxy_read_timeout 120s;
        client_max_body_size 50M;
    }
    location /uploads/ {
        alias ${APP_DIR}/uploads/;
    }
}
NGINXEOF

ln -sf /etc/nginx/sites-available/financas /etc/nginx/sites-enabled/financas
rm -f /etc/nginx/sites-enabled/default 2>/dev/null || true

echo "13. Configurando permissões..."
chown -R www-data:www-data $APP_DIR

echo "14. Configurando backup automático (3h da manhã)..."
cp "$SCRIPT_DIR/backup.sh" /opt/financas/backup.sh
chmod +x /opt/financas/backup.sh
(crontab -l 2>/dev/null | grep -v financas-backup; echo "0 3 * * * /opt/financas/backup.sh >> /var/log/financas-backup.log 2>&1") | crontab -

echo "15. Iniciando serviços..."
systemctl daemon-reload
systemctl enable financas-db-setup financas nginx
systemctl start financas-db-setup
systemctl restart financas nginx

echo ""
echo "======================================"
echo "  ✅ Instalação concluída!"
echo "======================================"
echo ""
echo "  🌐 Acesse: http://$(hostname -I | awk '{print $1}'):${PORT}"
echo "  👤 Usuário: leonardo"
echo "  🔑 Senha:   leonardo123"
echo ""
echo "  ⚠️  TROQUE A SENHA após o primeiro login!"
echo "======================================"
