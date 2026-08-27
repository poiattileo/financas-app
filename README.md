========================================
  Planejamento Financeiro
  Stack: Nginx + FastAPI + MariaDB
========================================

INSTALAÇÃO RÁPIDA (Ubuntu 22.04 / 24.04)
─────────────────────────────────────────
1. Copie a pasta financas-app para a VM

2. Entre na pasta e rode o instalador:
   sudo bash instalar.sh

   O script vai:
   ✓ Instalar Nginx, MariaDB, Python 3
   ✓ Criar o banco e as tabelas
   ✓ Configurar o backend como serviço
   ✓ Configurar o Nginx como proxy
   ✓ Pedir para você criar seu usuário
   ✓ Mostrar o IP de acesso no final

APÓS INSTALAR
─────────────────────────────────────────
• Acesse: http://IP_DA_VM
• Login com o usuário que você criou

CRIAR MAIS USUÁRIOS (futuramente)
─────────────────────────────────────────
  sudo -u www-data \
    /opt/financas/venv/bin/python3 \
    /opt/financas/backend/criar_usuario.py

LOGS E STATUS
─────────────────────────────────────────
  Status do backend:
    systemctl status financas

  Logs em tempo real:
    journalctl -u financas -f

  Reiniciar:
    sudo systemctl restart financas

ARQUIVOS NA VM APÓS INSTALAÇÃO
─────────────────────────────────────────
  /opt/financas/
  ├── backend/
  │   ├── main.py          ← API Python
  │   ├── .env             ← senhas (geradas automaticamente)
  │   └── criar_usuario.py ← para criar novos usuários
  ├── frontend/
  │   └── index.html       ← o site
  └── venv/                ← ambiente Python
