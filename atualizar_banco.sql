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

-- Colunas telegram (usadas pela API/bot)
ALTER TABLE usuarios ADD COLUMN IF NOT EXISTS telegram_chat_id VARCHAR(50) DEFAULT NULL;
ALTER TABLE usuarios ADD COLUMN IF NOT EXISTS telegram_link_code VARCHAR(10) DEFAULT NULL;

-- Índices de mês como INT (suporta deslocamento p/ histórico e 48 meses)
ALTER TABLE gasto_valores MODIFY COLUMN idx INT NOT NULL;
ALTER TABLE parcelas MODIFY COLUMN mes_idx INT NOT NULL;
ALTER TABLE lancamentos MODIFY COLUMN mes_idx INT DEFAULT NULL;

-- Marca ajustes de gasto fixo (só auditoria: o efeito já está no valor do fixo,
-- então não entram nos totais de lançamentos)
ALTER TABLE lancamentos ADD COLUMN IF NOT EXISTS tipo_ajuste VARCHAR(20) DEFAULT NULL;

-- Backfill: ajustes antigos criados como "Desconto: X" / "Acréscimo: X"
UPDATE lancamentos SET tipo_ajuste='subtrair'
  WHERE tipo_ajuste IS NULL AND descricao LIKE 'Desconto:%';
UPDATE lancamentos SET tipo_ajuste='somar'
  WHERE tipo_ajuste IS NULL AND (descricao LIKE 'Acréscimo:%' OR descricao LIKE 'Acrescimo:%');

-- Histórico com snapshot congelado (mês fechado sai da tela principal)
CREATE TABLE IF NOT EXISTS historico_meses (
    id          INT AUTO_INCREMENT PRIMARY KEY,
    user_id     INT NOT NULL,
    mes_ref     VARCHAR(7) NOT NULL,
    mes_idx     INT NOT NULL DEFAULT 0,
    salario     DECIMAL(12,2) DEFAULT 0,
    fixos       DECIMAL(12,2) DEFAULT 0,
    parcelas    DECIMAL(12,2) DEFAULT 0,
    lancamentos DECIMAL(12,2) DEFAULT 0,
    total       DECIMAL(12,2) DEFAULT 0,
    sobra       DECIMAL(12,2) DEFAULT 0,
    detalhes    TEXT NULL,
    criado_em   DATETIME DEFAULT NOW(),
    UNIQUE KEY uq_hist_user_mes (user_id, mes_ref),
    FOREIGN KEY (user_id) REFERENCES usuarios(id) ON DELETE CASCADE
);

-- Anotações (controle paralelo: não entra em nenhum total)
CREATE TABLE IF NOT EXISTS anotacoes (
    id INT AUTO_INCREMENT PRIMARY KEY,
    user_id INT NOT NULL,
    titulo VARCHAR(100) NOT NULL,
    criado_em DATETIME DEFAULT NOW(),
    FOREIGN KEY (user_id) REFERENCES usuarios(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS anotacao_itens (
    id INT AUTO_INCREMENT PRIMARY KEY,
    anotacao_id INT NOT NULL,
    nome VARCHAR(100) NOT NULL,
    valor_total DECIMAL(12,2) NOT NULL,
    qtd INT NOT NULL,
    mes_ref VARCHAR(7) NOT NULL,
    FOREIGN KEY (anotacao_id) REFERENCES anotacoes(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS anotacao_checks (
    item_id INT NOT NULL,
    k INT NOT NULL,
    marcado_em DATETIME DEFAULT NOW(),
    PRIMARY KEY (item_id, k),
    FOREIGN KEY (item_id) REFERENCES anotacao_itens(id) ON DELETE CASCADE
);

-- A receber: valores customizados por mês (ex: Airbnb varia).
-- Só lembrete de cobrança — nunca entra em totais.
CREATE TABLE IF NOT EXISTS anotacao_valores (
    item_id INT NOT NULL,
    k INT NOT NULL,
    valor DECIMAL(12,2) NOT NULL,
    PRIMARY KEY (item_id, k),
    FOREIGN KEY (item_id) REFERENCES anotacao_itens(id) ON DELETE CASCADE
);

-- Vínculo do lançamento-espelho com o gasto fixo (p/ reverter ajuste de fixo)
ALTER TABLE lancamentos ADD COLUMN IF NOT EXISTS gasto_id INT DEFAULT NULL;
