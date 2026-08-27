CREATE DATABASE IF NOT EXISTS financas CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
DROP USER IF EXISTS 'financas'@'localhost';
CREATE USER 'financas'@'localhost' IDENTIFIED VIA mysql_native_password USING PASSWORD('TROQUE_ESTA_SENHA');
GRANT ALL PRIVILEGES ON financas.* TO 'financas'@'localhost';
FLUSH PRIVILEGES;

USE financas;

CREATE TABLE IF NOT EXISTS usuarios (
    id          INT AUTO_INCREMENT PRIMARY KEY,
    username    VARCHAR(50) UNIQUE NOT NULL,
    senha_hash  VARCHAR(255) NOT NULL,
    salario     DECIMAL(12,2) DEFAULT 0,
    mes_inicio  VARCHAR(7) DEFAULT '',
    criado_em   DATETIME DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS gastos (
    id        INT AUTO_INCREMENT PRIMARY KEY,
    user_id   INT NOT NULL,
    nome      VARCHAR(100) NOT NULL,
    cat       VARCHAR(50) NOT NULL,
    criado_em DATETIME DEFAULT NOW(),
    FOREIGN KEY (user_id) REFERENCES usuarios(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS gasto_valores (
    gasto_id INT NOT NULL,
    idx      TINYINT NOT NULL,
    valor    DECIMAL(12,2) NOT NULL,
    PRIMARY KEY (gasto_id, idx),
    FOREIGN KEY (gasto_id) REFERENCES gastos(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS parcelas (
    id            INT AUTO_INCREMENT PRIMARY KEY,
    user_id       INT NOT NULL,
    nome          VARCHAR(100) NOT NULL,
    cat           VARCHAR(50) NOT NULL,
    total         DECIMAL(12,2) NOT NULL,
    qtd           TINYINT NOT NULL,
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
    cat         VARCHAR(50) NOT NULL DEFAULT 'outros',
    local_nome  VARCHAR(100) DEFAULT '',
    criado_em   DATETIME DEFAULT NOW(),
    FOREIGN KEY (user_id) REFERENCES usuarios(id) ON DELETE CASCADE
);
