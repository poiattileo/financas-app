USE financas;

-- Adiciona coluna role nos usuários (admin ou user)
ALTER TABLE usuarios ADD COLUMN IF NOT EXISTS role VARCHAR(20) DEFAULT 'user';

-- Torna o primeiro usuário cadastrado admin
UPDATE usuarios SET role='admin' ORDER BY id ASC LIMIT 1;

-- Tabela de lançamentos (já pode existir)
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
ALTER TABLE lancamentos ADD COLUMN IF NOT EXISTS recorrencia VARCHAR(20) DEFAULT 'nunca';

-- Tabela de metas (já pode existir)
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

-- Tabela de categorias customizáveis
CREATE TABLE IF NOT EXISTS categorias (
    id       INT AUTO_INCREMENT PRIMARY KEY,
    nome     VARCHAR(50) UNIQUE NOT NULL,
    label    VARCHAR(80) NOT NULL,
    emoji    VARCHAR(10) DEFAULT '💳',
    cor      VARCHAR(20) DEFAULT '#94a3b8',
    tipo     VARCHAR(20) DEFAULT 'ambos'
);

-- Categorias padrão (ignora se já existirem)
INSERT IGNORE INTO categorias (nome,label,emoji,cor,tipo) VALUES
('moradia',     'Moradia',      '🏠','#60a5fa','gasto'),
('transporte',  'Transporte',   '🚗','#fbbf24','ambos'),
('alimentacao', 'Alimentação',  '🍔','#f97316','ambos'),
('saude',       'Saúde',        '💊','#34d399','ambos'),
('educacao',    'Educação',     '📚','#f472b6','gasto'),
('assinaturas', 'Assinaturas',  '📱','#a78bfa','gasto'),
('financiamento','Financiamento','🏦','#f87171','gasto'),
('eletronicos', 'Eletrônicos',  '💻','#818cf8','gasto'),
('moveis',      'Móveis',       '🛋️','#fb923c','gasto'),
('roupas',      'Roupas',       '👕','#e879f9','ambos'),
('lazer',       'Lazer',        '🎮','#c084fc','lancamento'),
('outros',      'Outros',       '💳','#94a3b8','ambos');

-- Adicionar colunas motivo e mes_idx na tabela lancamentos
ALTER TABLE lancamentos ADD COLUMN IF NOT EXISTS motivo VARCHAR(200) DEFAULT '';
ALTER TABLE lancamentos ADD COLUMN IF NOT EXISTS mes_idx TINYINT DEFAULT NULL;

-- Tabela de anexos dos lançamentos
CREATE TABLE IF NOT EXISTS lancamento_anexos (
    id              INT AUTO_INCREMENT PRIMARY KEY,
    lancamento_id   INT NOT NULL,
    nome_original   VARCHAR(255) NOT NULL,
    nome_arquivo    VARCHAR(255) NOT NULL,
    tipo            VARCHAR(100) DEFAULT 'application/octet-stream',
    tamanho         INT DEFAULT 0,
    criado_em       DATETIME DEFAULT NOW(),
    FOREIGN KEY (lancamento_id) REFERENCES lancamentos(id) ON DELETE CASCADE
);

-- Adicionar colunas motivo e mes_idx se não existirem (caso ainda não foram adicionadas)
ALTER TABLE lancamentos ADD COLUMN IF NOT EXISTS motivo VARCHAR(200) DEFAULT '';
ALTER TABLE lancamentos ADD COLUMN IF NOT EXISTS mes_idx TINYINT DEFAULT NULL;
