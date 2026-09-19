#!/usr/bin/env python3
"""
Bot Telegram para o app de Financas.
Roda em loop continuo (long polling), sem precisar de HTTPS/dominio.

Formato de mensagem aceito (linhas separadas por ENTER):
  Linha 1: Nome do gasto fixo OU descricao de um lancamento avulso
  Linha 2: Valor (aceita virgula ou ponto, com ou sem sinal)
  Linha 3 (opcional): Mes (ex: "agosto", "08/2026", ou vazio = mes atual)
  Linha 4 (opcional): Motivo/comentario (fica salvo e aparece no tooltip do site)

Se a Linha 1 bater com o nome de um gasto fixo ja cadastrado (do usuario
vinculado aquele chat_id), o valor eh aplicado como AJUSTE (soma/subtrai)
daquele gasto. Digite com sinal: -35.42 para subtrair, +35.42 ou 35.42
para somar.

Se nao bater com nenhum gasto fixo, cria um LANCAMENTO AVULSO novo com
essa descricao e o valor (sempre tratado como positivo/gasto).

Comandos:
  /start           - mensagem de boas-vindas
  /vincular CODIGO - vincula este chat ao usuario que gerou o CODIGO no site
  /desvincular     - remove o vinculo
  /ajuda           - mostra o formato de mensagem
"""
import os
import re
import time
import unicodedata
import requests
import mysql.connector
from datetime import datetime

# ── Carrega .env manualmente (sem dependencias extras) ──
ENV_PATH = os.path.join(os.path.dirname(__file__), ".env")
env = {}
with open(ENV_PATH) as f:
    for line in f:
        line = line.strip()
        if line and "=" in line and not line.startswith("#"):
            k, v = line.split("=", 1)
            env[k] = v

BOT_TOKEN = env.get("TELEGRAM_BOT_TOKEN", "")
API_URL = f"https://api.telegram.org/bot{BOT_TOKEN}"

MESES_PT = {
    "janeiro":1,"fevereiro":2,"marco":3,"março":3,"abril":4,"maio":5,"junho":6,
    "julho":7,"agosto":8,"setembro":9,"outubro":10,"novembro":11,"dezembro":12,
    "jan":1,"fev":2,"mar":3,"abr":4,"mai":5,"jun":6,"jul":7,"ago":8,"set":9,"out":10,"nov":11,"dez":12
}

def get_db():
    return mysql.connector.connect(
        host=env.get("DB_HOST","localhost"),
        user=env.get("DB_USER","financas"),
        password=env.get("DB_PASS",""),
        database=env.get("DB_NAME","financas"),
        autocommit=True
    )

def normalizar(s):
    s = s.strip().lower()
    s = ''.join(c for c in unicodedata.normalize('NFD', s) if unicodedata.category(c) != 'Mn')
    return s

def enviar_msg(chat_id, texto, teclado=None):
    try:
        payload = {"chat_id": chat_id, "text": texto, "parse_mode": "Markdown"}
        if teclado:
            payload["reply_markup"] = {"inline_keyboard": teclado}
        requests.post(f"{API_URL}/sendMessage", json=payload, timeout=10)
    except Exception as e:
        print(f"[erro ao enviar] {e}")

def responder_callback(callback_id):
    try:
        requests.post(f"{API_URL}/answerCallbackQuery", json={"callback_query_id": callback_id}, timeout=10)
    except Exception:
        pass

def buscar_usuario_por_chat(chat_id):
    db = get_db(); cur = db.cursor(dictionary=True)
    cur.execute("SELECT id, username, mes_inicio FROM usuarios WHERE telegram_chat_id=%s", (str(chat_id),))
    row = cur.fetchone(); cur.close(); db.close()
    return row

def vincular_codigo(chat_id, codigo):
    db = get_db(); cur = db.cursor(dictionary=True)
    cur.execute("SELECT id, username FROM usuarios WHERE telegram_link_code=%s", (codigo,))
    row = cur.fetchone()
    if not row:
        cur.close(); db.close()
        return None
    cur.execute("UPDATE usuarios SET telegram_chat_id=%s, telegram_link_code=NULL WHERE id=%s",
        (str(chat_id), row["id"]))
    cur.close(); db.close()
    return row["username"]

def desvincular(chat_id):
    db = get_db(); cur = db.cursor()
    cur.execute("UPDATE usuarios SET telegram_chat_id=NULL WHERE telegram_chat_id=%s", (str(chat_id),))
    cur.close(); db.close()

def idx_do_mes(mes_inicio_str, ano, mes):
    if not mes_inicio_str:
        return 0
    y0, m0 = map(int, mes_inicio_str.split("-"))
    return (ano - y0) * 12 + (mes - m0)

def idx_hoje(mes_inicio_str):
    n = datetime.now()
    return idx_do_mes(mes_inicio_str, n.year, n.month)

# Mês de trabalho = calendário +1 (em setembro já se planeja outubro).
OFFSET_MES_TRABALHO = 1
def idx_trabalho(mes_inicio_str):
    return idx_hoje(mes_inicio_str) + OFFSET_MES_TRABALHO

def parse_mes(texto, mes_inicio_str):
    """Retorna o indice do mes a partir do texto (nome do mes ou MM/AAAA), ou None se vazio."""
    texto = texto.strip()
    if not texto:
        return None
    # formato MM/AAAA ou MM-AAAA
    m = re.match(r'^(\d{1,2})[/\-](\d{4})$', texto)
    if m:
        mes, ano = int(m.group(1)), int(m.group(2))
        return idx_do_mes(mes_inicio_str, ano, mes)
    # nome do mes (assume ano atual, ou proximo ano se mes ja passou muito)
    nome = normalizar(texto)
    for chave, num in MESES_PT.items():
        if nome.startswith(chave):
            ano = datetime.now().year
            # se o mes calculado for muito anterior ao atual, assume ano seguinte
            idx_candidato = idx_do_mes(mes_inicio_str, ano, num)
            if idx_candidato < idx_trabalho(mes_inicio_str) - 6:
                idx_candidato = idx_do_mes(mes_inicio_str, ano+1, num)
            return idx_candidato
    return None

def parse_valor(texto):
    """Extrai valor numerico (aceita virgula, ponto, sinal)."""
    texto = texto.strip().replace("R$","").replace(" ","")
    texto = texto.replace(".", "").replace(",", ".") if texto.count(",")==1 and texto.count(".")<=1 and "," in texto else texto.replace(",", ".")
    try:
        return float(texto)
    except ValueError:
        return None

def processar_lancamento(user, linhas):
    nome_ou_desc = linhas[0].strip()
    valor_raw = linhas[1].strip() if len(linhas) > 1 else ""
    mes_raw = linhas[2].strip() if len(linhas) > 2 else ""
    motivo_raw = linhas[3].strip() if len(linhas) > 3 else ""

    valor = parse_valor(valor_raw)
    if valor is None:
        return "❌ Não consegui entender o valor. Use algo como `-35.42` ou `78,90`."

    mes_inicio = user.get("mes_inicio") or ""
    idx = parse_mes(mes_raw, mes_inicio)
    if idx is None:
        idx = idx_trabalho(mes_inicio)

    # busca gastos fixos do usuario
    db = get_db(); cur = db.cursor(dictionary=True)
    cur.execute("SELECT id, nome, cat FROM gastos WHERE user_id=%s", (user["id"],))
    gastos = cur.fetchall()

    nome_norm = normalizar(nome_ou_desc)
    gasto_match = None
    for g in gastos:
        if normalizar(g["nome"]) == nome_norm:
            gasto_match = g
            break

    if gasto_match:
        # AJUSTE de gasto fixo
        cur.execute("SELECT valor FROM gasto_valores WHERE gasto_id=%s AND idx=%s", (gasto_match["id"], idx))
        row = cur.fetchone()
        valor_atual = float(row["valor"]) if row else 0.0
        novo_valor = round(valor_atual + valor, 2)
        if novo_valor != 0:
            cur.execute("INSERT INTO gasto_valores (gasto_id,idx,valor) VALUES (%s,%s,%s) ON DUPLICATE KEY UPDATE valor=%s",
                (gasto_match["id"], idx, novo_valor, novo_valor))
        else:
            cur.execute("DELETE FROM gasto_valores WHERE gasto_id=%s AND idx=%s", (gasto_match["id"], idx))

        op = "Desconto" if valor < 0 else "Acréscimo"
        tipo_aj = "subtrair" if valor < 0 else "somar"
        motivo_final = motivo_raw if motivo_raw else "via Telegram"
        cur.execute(
            "INSERT INTO lancamentos (user_id,descricao,valor,cat,local_nome,recorrencia,motivo,mes_idx,tipo_ajuste) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)",
            (user["id"], f"{op}: {gasto_match['nome']}", abs(valor), gasto_match["cat"], "", "nunca", motivo_final, idx, tipo_aj)
        )
        cur.close(); db.close()

        sinal = "recebimento (valor negativo)" if novo_valor < 0 else "a pagar"
        resposta = (f"✅ *{gasto_match['nome']}* ajustado!\n"
                f"Valor anterior: R$ {valor_atual:.2f}\n"
                f"Ajuste: {'−' if valor<0 else '+'} R$ {abs(valor):.2f}\n"
                f"*Novo valor: R$ {novo_valor:.2f}* ({sinal})")
        if motivo_raw:
            resposta += f"\n💬 _{motivo_raw}_"
        return resposta
    else:
        # LANÇAMENTO AVULSO novo
        valor_abs = abs(valor)
        motivo_final = motivo_raw if motivo_raw else "via Telegram"
        cur.execute(
            "INSERT INTO lancamentos (user_id,descricao,valor,cat,local_nome,recorrencia,motivo,mes_idx) VALUES (%s,%s,%s,%s,%s,%s,%s,%s)",
            (user["id"], nome_ou_desc, valor_abs, "outros", "", "nunca", motivo_final, idx)
        )
        cur.close(); db.close()
        resposta = f"✅ Lançamento avulso registrado!\n*{nome_ou_desc}* — R$ {valor_abs:.2f}"
        if motivo_raw:
            resposta += f"\n💬 _{motivo_raw}_"
        return resposta

# ── RELATÓRIOS ──
def calc_totais_mes(user, idx):
    db = get_db(); cur = db.cursor(dictionary=True)
    cur.execute("SELECT salario FROM usuarios WHERE id=%s", (user["id"],))
    sal = float(cur.fetchone()["salario"] or 0)

    cur.execute("SELECT id, nome, cat FROM gastos WHERE user_id=%s", (user["id"],))
    gastos = cur.fetchall()
    total_fixos = 0.0
    detalhes_fixos = []
    for g in gastos:
        cur.execute("SELECT valor FROM gasto_valores WHERE gasto_id=%s AND idx=%s", (g["id"], idx))
        row = cur.fetchone()
        v = float(row["valor"]) if row else 0.0
        if v != 0:
            total_fixos += v
            detalhes_fixos.append((g["nome"], v))

    cur.execute("SELECT nome, total, qtd, mes_idx, valor_parcela FROM parcelas WHERE user_id=%s", (user["id"],))
    total_parc = 0.0
    for p in cur.fetchall():
        k = idx - p["mes_idx"]
        if 0 <= k < p["qtd"]:
            total_parc += float(p["valor_parcela"])

    # Lançamentos NÃO somam no total (só informam — o valor já está no fixo).
    # Total = fixos + parcelas. A lista abaixo serve só p/ conferência.
    cur.execute("SELECT descricao, valor FROM lancamentos WHERE user_id=%s AND mes_idx=%s", (user["id"], idx))
    total_lanc = 0.0
    detalhes_lanc = []
    for l in cur.fetchall():
        total_lanc += float(l["valor"])
        detalhes_lanc.append((l["descricao"], float(l["valor"])))

    cur.close(); db.close()
    total = round(total_fixos + total_parc, 2)
    sobra = round(sal - total, 2)
    return {
        "sal": sal, "fixos": round(total_fixos,2), "parcelas": round(total_parc,2),
        "lancamentos": round(total_lanc,2), "total": total, "sobra": sobra,
        "detalhes_fixos": detalhes_fixos, "detalhes_lanc": detalhes_lanc
    }

def relatorio_resumo_mes(user):
    idx = idx_trabalho(user.get("mes_inicio") or "")
    d = calc_totais_mes(user, idx)
    mes_nome = datetime.now().strftime("%B/%Y")
    txt = (f"📊 *Resumo — {mes_nome}*\n\n"
           f"💵 Salário: R$ {d['sal']:.2f}\n"
           f"🏠 Fixos: R$ {d['fixos']:.2f}\n"
           f"💳 Parcelas: R$ {d['parcelas']:.2f}\n"
           f"⚡ Lançamentos: R$ {d['lancamentos']:.2f}\n"
           f"➖➖➖➖➖➖➖\n"
           f"💸 Total saídas: R$ {d['total']:.2f}\n"
           f"{'✅' if d['sobra']>=0 else '⚠️'} *Sobra: R$ {d['sobra']:.2f}*")
    return txt

def relatorio_gastos_fixos(user):
    idx = idx_trabalho(user.get("mes_inicio") or "")
    d = calc_totais_mes(user, idx)
    if not d["detalhes_fixos"]:
        return "📋 Nenhum gasto fixo com valor neste mês."
    linhas = "\n".join([f"• {nome}: R$ {v:.2f}" for nome, v in sorted(d["detalhes_fixos"], key=lambda x:-x[1])])
    return f"📋 *Gastos fixos do mês:*\n\n{linhas}\n\n*Total: R$ {d['fixos']:.2f}*"

def relatorio_lancamentos_mes(user):
    idx = idx_trabalho(user.get("mes_inicio") or "")
    d = calc_totais_mes(user, idx)
    if not d["detalhes_lanc"]:
        return "⚡ Nenhum lançamento registrado neste mês ainda."
    linhas = "\n".join([f"• {desc}: R$ {v:.2f}" for desc, v in d["detalhes_lanc"]])
    return f"⚡ *Lançamentos do mês:*\n\n{linhas}\n\n*Total: R$ {d['lancamentos']:.2f}*"

def relatorio_metas(user):
    db = get_db(); cur = db.cursor(dictionary=True)
    cur.execute("SELECT nome, valor_alvo, valor_atual FROM metas WHERE user_id=%s", (user["id"],))
    metas = cur.fetchall(); cur.close(); db.close()
    if not metas:
        return "🎯 Nenhuma meta cadastrada ainda."
    linhas = []
    for m in metas:
        alvo = float(m["valor_alvo"]); atual = float(m["valor_atual"])
        pct = (atual/alvo*100) if alvo else 0
        linhas.append(f"• *{m['nome']}*: R$ {atual:.2f} / R$ {alvo:.2f} ({pct:.0f}%)")
    return "🎯 *Suas metas:*\n\n" + "\n".join(linhas)

def relatorio_historico(user):
    mes_inicio = user.get("mes_inicio") or ""
    ih = idx_trabalho(mes_inicio)
    if ih <= 0:
        return "📅 Nenhum mês no histórico ainda."
    linhas = []
    for i in range(max(0, ih-6), ih):
        d = calc_totais_mes(user, i)
        if not mes_inicio:
            continue
        y0, m0 = map(int, mes_inicio.split("-"))
        mes_total = (y0*12 + m0 - 1) + i
        ano = mes_total // 12
        mes = mes_total % 12 + 1
        nome_mes = ["jan","fev","mar","abr","mai","jun","jul","ago","set","out","nov","dez"][mes-1]
        emoji = "✅" if d["sobra"] >= 0 else "⚠️"
        linhas.append(f"{emoji} {nome_mes}/{ano}: sobra R$ {d['sobra']:.2f}")
    if not linhas:
        return "📅 Nenhum mês no histórico ainda."
    return "📅 *Histórico (últimos meses):*\n\n" + "\n".join(linhas)

def menu_relatorios():
    return [
        [{"text": "📊 Resumo do mês", "callback_data": "rel_resumo"}],
        [{"text": "📋 Gastos fixos", "callback_data": "rel_fixos"}],
        [{"text": "⚡ Lançamentos do mês", "callback_data": "rel_lancamentos"}],
        [{"text": "🎯 Metas", "callback_data": "rel_metas"}],
        [{"text": "📅 Histórico", "callback_data": "rel_historico"}],
    ]

# ── /LANCAR GUIADO (conversa por etapas) ──
CONVERSA_TIMEOUT = 15 * 60  # 15 min sem resposta = expira
conversas = {}  # chat_id -> {"tipo", "etapa", "dados", "inicio"}

def menu_lancar():
    return [
        [{"text": "⚡ Lançamento rápido", "callback_data": "lan_rapido"}],
        [{"text": "💳 Compra parcelada", "callback_data": "lan_parcelado"}],
    ]

def conversa_expirada(chat_id):
    est = conversas.get(chat_id)
    if not est:
        return True
    if time.time() - est.get("inicio", 0) > CONVERSA_TIMEOUT:
        conversas.pop(chat_id, None)
        return True
    return False

def _mes_ou_trabalho(t, mes_inicio):
    """Interpreta o mês digitado; '-' ou vazio = mês de trabalho."""
    t = (t or "").strip()
    if t in ("", "-", "pular"):
        return idx_trabalho(mes_inicio or "")
    return parse_mes(t, mes_inicio or "")

def buscar_gasto_por_nome(user_id, nome):
    db = get_db(); cur = db.cursor(dictionary=True)
    cur.execute("SELECT id, nome, cat FROM gastos WHERE user_id=%s", (user_id,))
    gastos = cur.fetchall()
    cur.close(); db.close()
    norm = normalizar(nome)
    for g in gastos:
        if normalizar(g["nome"]) == norm:
            return g
    return None

def nome_mes_idx(mes_inicio_str, idx):
    try:
        y0, m0 = map(int, mes_inicio_str.split("-"))
        tot = (y0 * 12 + m0 - 1) + idx
        ano, mes = tot // 12, tot % 12 + 1
        nomes = ["jan","fev","mar","abr","mai","jun","jul","ago","set","out","nov","dez"]
        return f"{nomes[mes-1]}/{ano}"
    except Exception:
        return f"mês {idx}"

def processar_parcelado(user, linhas):
    """Mensagem única de parcelado (5 linhas). Se o nome bater com um gasto
    fixo, soma as parcelas nele mês a mês; senão cria compra parcelada nova."""
    nome = linhas[0].strip()
    total = parse_valor(linhas[1]) if len(linhas) > 1 else None
    m = re.match(r"(\d+)", linhas[2]) if len(linhas) > 2 else None
    qtd = int(m.group(1)) if m else 0
    mes_raw = linhas[3] if len(linhas) > 3 else ""
    motivo = linhas[4].strip() if len(linhas) > 4 else ""
    if not nome:
        return "❌ Faltou o nome do gasto."
    if total is None or total <= 0:
        return "❌ Não entendi o valor total. Use algo como `1200`."
    if not 1 <= qtd <= 48:
        return "❌ Quantidade inválida. Manda de 1 a 48 (ex: `12` ou `12x`)."
    mes_inicio = user.get("mes_inicio") or ""
    idx_ini = _mes_ou_trabalho(mes_raw, mes_inicio)
    if idx_ini is None:
        return "❌ Não entendi o mês. Manda tipo `agosto`, `08/2026` ou deixa em branco."
    total = abs(total)
    vp = round(total / qtd, 2)
    gasto = buscar_gasto_por_nome(user["id"], nome)
    if gasto:
        db = get_db(); cur = db.cursor(dictionary=True)
        feitas = 0
        for k in range(qtd):
            idx = idx_ini + k
            if idx >= 48:
                break
            cur.execute("SELECT valor FROM gasto_valores WHERE gasto_id=%s AND idx=%s", (gasto["id"], idx))
            row = cur.fetchone()
            novo = round((float(row["valor"]) if row else 0.0) + vp, 2)
            cur.execute("INSERT INTO gasto_valores (gasto_id,idx,valor) VALUES (%s,%s,%s) ON DUPLICATE KEY UPDATE valor=%s",
                (gasto["id"], idx, novo, novo))
            feitas += 1
        cur.close(); db.close()
        resp = (f"✅ *{gasto['nome']}* atualizado!\n"
                f"{feitas}x de R$ {vp:.2f} somadas mês a mês\n"
                f"📅 {nome_mes_idx(mes_inicio, idx_ini)} → {nome_mes_idx(mes_inicio, idx_ini + feitas - 1)}")
        if feitas < qtd:
            resp += f"\n⚠️ {qtd - feitas} parcela(s) além de 48 meses ignoradas."
        if motivo:
            resp += f"\n💬 _{motivo}_"
        return resp
    db = get_db(); cur = db.cursor()
    cur.execute(
        "INSERT INTO parcelas (user_id,nome,cat,total,qtd,mes_idx,valor_parcela) VALUES (%s,%s,'outros',%s,%s,%s,%s)",
        (user["id"], nome, round(total, 2), qtd, idx_ini, vp))
    cur.close(); db.close()
    resp = (f"✅ Parcelado registrado!\n*{nome}* — {qtd}x de R$ {vp:.2f} "
            f"(total R$ {total:.2f})\n"
            f"📅 {nome_mes_idx(mes_inicio, idx_ini)} → {nome_mes_idx(mes_inicio, idx_ini + qtd - 1)}")
    if motivo:
        resp += f"\n💬 _{motivo}_"
    return resp

def processar_conversa(chat_id, user, texto):
    """Após escolher o tipo no /lancar, o usuário manda TUDO em uma mensagem."""
    if conversa_expirada(chat_id):
        return "⏰ A conversa expirou. Mande /lancar para começar de novo."
    est = conversas[chat_id]
    linhas = [l.strip() for l in texto.strip().split("\n") if l.strip()]
    if est["tipo"] == "rapido":
        if len(linhas) < 2:
            return ("⚠️ Formato incompleto. Envie tudo em uma mensagem assim:\n"
                    "```\nDescrição\nValor\nMês (opcional)\nMotivo (opcional)\n```")
        try:
            resp = processar_lancamento(user, linhas)
        except Exception as e:
            return f"❌ Erro ao processar: {e}"
        conversas.pop(chat_id, None)
        return resp
    if len(linhas) < 3:
        return ("⚠️ Formato incompleto. Envie tudo em uma mensagem assim:\n"
                "```\nNome do gasto\nValor total\nQuantas parcelas\nMês início (opcional)\nMotivo (opcional)\n```")
    try:
        resp = processar_parcelado(user, linhas)
    except Exception as e:
        return f"❌ Erro ao processar: {e}"
    # em erro de validação (❌) mantém a conversa p/ reenviar corrigido
    if resp.startswith("✅"):
        conversas.pop(chat_id, None)
    return resp

def processar_callback(chat_id, callback_data):
    user = buscar_usuario_por_chat(chat_id)
    if not user:
        return "⚠️ Você não está vinculado a nenhuma conta."
    if callback_data == "lan_rapido" or callback_data == "lan_parcelado":
        tipo = "rapido" if callback_data == "lan_rapido" else "parcelado"
        conversas[chat_id] = {"tipo": tipo, "inicio": time.time()}
        if tipo == "rapido":
            return ("⚡ *Lançamento rápido*\n"
                    "Envie tudo em uma mensagem assim:\n"
                    "```\nDescrição\nValor\nMês (opcional)\nMotivo (opcional)\n```\n"
                    "• Se bater com um gasto fixo → ajusta ele (use `-` p/ subtrair)\n"
                    "• Se não bater → cria avulso\n\n"
                    "*Exemplo:*\n```\nCoxinha\n12,50\noutubro\nLanche da tarde\n```")
        return ("💳 *Compra parcelada*\n"
                "Envie assim:\n"
                "```\nNome do gasto\nValor total\nQuantas parcelas\nMês início (opcional)\nMotivo (opcional)\n```\n"
                "• Se o Nome bater com um gasto fixo já cadastrado → soma as parcelas nele, mês a mês\n"
                "• Se não bater → cria uma compra parcelada nova e separada\n\n"
                "*Exemplo:*\n```\nCartão Nubank\n1200\n12x\nagosto\nTV nova\n```")
    mapa = {
        "rel_resumo": relatorio_resumo_mes,
        "rel_fixos": relatorio_gastos_fixos,
        "rel_lancamentos": relatorio_lancamentos_mes,
        "rel_metas": relatorio_metas,
        "rel_historico": relatorio_historico,
    }
    fn = mapa.get(callback_data)
    if not fn:
        return "❌ Opção inválida."
    try:
        return fn(user)
    except Exception as e:
        return f"❌ Erro ao gerar relatório: {e}"

def processar_mensagem(chat_id, texto):
    texto = texto.strip()

    if texto.startswith("/cancelar"):
        if chat_id in conversas:
            conversas.pop(chat_id, None)
            return "🚫 Conversa cancelada. Use /lancar para começar de novo."
        return "Nada em andamento. Use /lancar para registrar."

    if texto.startswith("/") and chat_id in conversas:
        # outro comando no meio da conversa: abandona e segue o comando
        conversas.pop(chat_id, None)

    if texto.startswith("/start"):
        return ("👋 Olá! Eu sou o bot de lançamentos do seu app de Finanças.\n\n"
                "Para me vincular à sua conta, vá em *Configurações* no site, "
                "gere um código e me envie:\n`/vincular 123456`\n\n"
                "Depois use /lancar para registrar guiado, ou mande direto no formato:\n"
                "```\nNome do gasto\nValor\nMês (opcional)\nMotivo (opcional)\n```\n\n"
                "Digite /relatorios para ver relatórios rápidos!")

    if texto.startswith("/ajuda"):
        return ("📋 *Formato da mensagem:*\n```\nNome do gasto\nValor\nMês (opcional)\nMotivo (opcional)\n```\n\n"
                "• Se o *Nome* bater com um gasto fixo já cadastrado → ajusta esse gasto (use sinal: -35.42 ou +50)\n"
                "• Se não bater → cria um lançamento avulso novo\n"
                "• *Mês* pode ser tipo `agosto` ou `08/2026`. Se não informar, usa o mês atual.\n"
                "• *Motivo* fica salvo e aparece quando você passar o mouse no valor, no site.\n\n"
                "*Exemplo:*\n```\nMelody\n-35.42\njulho\nFulano pagou a parte dele\n```\n\n"
                "Para parcelado, use /lancar → 💳 (nome bate com fixo = soma nele, senão cria separado).\n\n"
                "Digite /relatorios para ver relatórios rápidos!\n\n"
                "Ou use /lancar para o registro guiado (rápido ou parcelado).")

    if texto.startswith("/lancar"):
        user = buscar_usuario_por_chat(chat_id)
        if not user:
            return ("⚠️ Você ainda não está vinculado a nenhuma conta.\n"
                    "Vá em Configurações no site, gere um código, e me envie:\n`/vincular 123456`")
        return "escolher_lancar"  # sinal especial tratado no loop principal

    # conversa do /lancar em andamento?
    if chat_id in conversas:
        user = buscar_usuario_por_chat(chat_id)
        if not user:
            conversas.pop(chat_id, None)
            return ("⚠️ Você ainda não está vinculado a nenhuma conta.\n"
                    "Vá em Configurações no site, gere um código, e me envie:\n`/vincular 123456`")
        try:
            return processar_conversa(chat_id, user, texto)
        except Exception as e:
            return f"❌ Erro ao processar: {e}"

    if texto.startswith("/vincular"):
        partes = texto.split()
        if len(partes) < 2:
            return "❌ Use assim: `/vincular 123456`"
        codigo = partes[1].strip()
        username = vincular_codigo(chat_id, codigo)
        if username:
            return f"✅ Vinculado com sucesso à conta *{username}*! Agora pode mandar seus lançamentos."
        return "❌ Código inválido ou expirado. Gere um novo no site."

    if texto.startswith("/desvincular"):
        desvincular(chat_id)
        return "🔓 Desvinculado. Use /vincular para conectar novamente."

    if texto.startswith("/relatorios") or texto.startswith("/relatorio"):
        user = buscar_usuario_por_chat(chat_id)
        if not user:
            return ("⚠️ Você ainda não está vinculado a nenhuma conta.\n"
                    "Vá em Configurações no site, gere um código, e me envie:\n`/vincular 123456`")
        return "escolher_relatorio"  # sinal especial tratado no loop principal

    # mensagem normal = tentativa de lançamento
    user = buscar_usuario_por_chat(chat_id)
    if not user:
        return ("⚠️ Você ainda não está vinculado a nenhuma conta.\n"
                "Vá em Configurações no site, gere um código, e me envie:\n`/vincular 123456`")

    linhas = [l for l in texto.split("\n") if l.strip()]
    if len(linhas) < 2:
        return ("⚠️ Formato incompleto. Envie assim:\n```\nNome do gasto\nValor\nMês (opcional)\nMotivo (opcional)\n```\n"
                "Digite /ajuda para mais detalhes.")

    try:
        return processar_lancamento(user, linhas)
    except Exception as e:
        return f"❌ Erro ao processar: {e}"

def main():
    if not BOT_TOKEN:
        print("[ERRO] TELEGRAM_BOT_TOKEN não configurado no .env")
        return
    print("[bot] iniciado, aguardando mensagens...")
    offset = None
    while True:
        try:
            params = {"timeout": 30}
            if offset:
                params["offset"] = offset
            r = requests.get(f"{API_URL}/getUpdates", params=params, timeout=35)
            data = r.json()
            for update in data.get("result", []):
                offset = update["update_id"] + 1

                # botão clicado (callback query)
                cq = update.get("callback_query")
                if cq:
                    chat_id = cq["message"]["chat"]["id"]
                    callback_data = cq.get("data", "")
                    print(f"[callback] chat={chat_id}: {callback_data}")
                    responder_callback(cq["id"])
                    resposta = processar_callback(chat_id, callback_data)
                    enviar_msg(chat_id, resposta)
                    continue

                msg = update.get("message")
                if not msg or "text" not in msg:
                    continue
                chat_id = msg["chat"]["id"]
                texto = msg["text"]
                print(f"[recebido] chat={chat_id}: {texto[:50]}")
                resposta = processar_mensagem(chat_id, texto)
                if resposta == "escolher_relatorio":
                    enviar_msg(chat_id, "📈 *Escolha o relatório:*", teclado=menu_relatorios())
                elif resposta == "escolher_lancar":
                    enviar_msg(chat_id, "🧾 *O que vai ser?*", teclado=menu_lancar())
                else:
                    enviar_msg(chat_id, resposta)
        except Exception as e:
            print(f"[erro no loop] {e}")
            time.sleep(5)

if __name__ == "__main__":
    main()
