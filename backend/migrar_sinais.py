#!/usr/bin/env python3
"""Inversão de convenção de sinais (rodar UMA vez no servidor):
    ANTES: positivo = a pagar, negativo = a receber
    DEPOIS: negativo = a pagar, positivo = a receber

    - gasto_valores.valor: inverte tudo
    - parcelas.total / valor_parcela: inverte (compra = dívida)
    - historico_meses.fixos/parcelas/total: inverte (sobra/salário não mudam)
    - historico_meses.detalhes (JSON por gasto): inverte cada valor
    - NÃO mexe: lancamentos (magnitudes), metas, anotações, usuários

    Idempotente via marcador: segunda execução não faz nada.
    Uso no servidor: sudo python3 backend/migrar_sinais.py
"""
import json
import os
import sys

CHAVE = "sinais_v2"

# .env: no servidor fica em /opt/financas/backend/.env
CANDIDATOS_ENV = [
    "/opt/financas/backend/.env",
    os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env"),
]
env = {}
for caminho in CANDIDATOS_ENV:
    if os.path.exists(caminho):
        with open(caminho) as f:
            for linha in f:
                linha = linha.strip()
                if linha and "=" in linha and not linha.startswith("#"):
                    k, v = linha.split("=", 1)
                    env[k] = v
        break

try:
    import mysql.connector
except ImportError:
    print("ERRO: mysql-connector não instalado.")
    sys.exit(1)

db = mysql.connector.connect(
    host=env.get("DB_HOST", "localhost"),
    user=env.get("DB_USER", "financas"),
    password=env.get("DB_PASS", ""),
    database=env.get("DB_NAME", "financas"),
    autocommit=True,
)
cur = db.cursor(dictionary=True)

cur.execute("CREATE TABLE IF NOT EXISTS _migracao (chave VARCHAR(50) PRIMARY KEY, aplicado_em DATETIME DEFAULT NOW())")
cur.execute("SELECT chave FROM _migracao WHERE chave=%s", (CHAVE,))
if cur.fetchone():
    print("Migração sinais_v2 já aplicada — nada a fazer.")
    cur.close(); db.close(); sys.exit(0)

cur2 = db.cursor()
cur2.execute("UPDATE gasto_valores SET valor = -valor")
n1 = cur2.rowcount
cur2.execute("UPDATE parcelas SET total = -total, valor_parcela = -valor_parcela")
n2 = cur2.rowcount
cur2.execute("UPDATE historico_meses SET fixos = -fixos, parcelas = -parcelas, total = -total")
n3 = cur2.rowcount

# detalhes JSON dos snapshots: inverte cada {nome,cat,valor}
cur.execute("SELECT id, detalhes FROM historico_meses")
n4 = 0
for h in cur.fetchall():
    try:
        det = json.loads(h.get("detalhes") or "[]")
    except Exception:
        continue
    mudou = False
    for d in det:
        try:
            if isinstance(d, dict) and "valor" in d:
                d["valor"] = round(-float(d["valor"] or 0), 2)
                mudou = True
        except Exception:
            pass
    if mudou:
        cur2.execute("UPDATE historico_meses SET detalhes=%s WHERE id=%s",
                     (json.dumps(det), h["id"]))
        n4 += 1

cur2.execute("INSERT INTO _migracao (chave) VALUES (%s)", (CHAVE,))
cur.close(); cur2.close(); db.close()
print(f"OK: gasto_valores={n1} parcelas={n2} snapshots={n3} detalhes_json={n4}")
