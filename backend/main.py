from fastapi import FastAPI, HTTPException, Depends, status, UploadFile, File, Form
from fastapi.middleware.cors import CORSMiddleware
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from pydantic import BaseModel
from typing import Optional, List
import mysql.connector
import bcrypt
import jwt
import os
import uuid
import shutil
from datetime import datetime, timedelta

app = FastAPI(title="Financas API")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_credentials=True, allow_methods=["*"], allow_headers=["*"])

UPLOAD_DIR = "/opt/financas/uploads"
os.makedirs(UPLOAD_DIR, exist_ok=True)
app.mount("/uploads", StaticFiles(directory=UPLOAD_DIR), name="uploads")

JWT_SECRET = os.environ.get("JWT_SECRET", "troque-este-segredo")
JWT_EXPIRE_HOURS = 72
security = HTTPBearer()

def get_db():
    return mysql.connector.connect(
        host=os.environ.get("DB_HOST", "localhost"),
        user=os.environ.get("DB_USER", "financas"),
        password=os.environ.get("DB_PASS", ""),
        database=os.environ.get("DB_NAME", "financas"),
        autocommit=True
    )

def criar_token(user_id: int) -> str:
    payload = {"sub": user_id, "exp": datetime.utcnow() + timedelta(hours=JWT_EXPIRE_HOURS)}
    return jwt.encode(payload, JWT_SECRET, algorithm="HS256")

def verificar_token(credentials: HTTPAuthorizationCredentials = Depends(security)) -> dict:
    try:
        payload = jwt.decode(credentials.credentials, JWT_SECRET, algorithms=["HS256"])
        return {"id": payload["sub"], "role": payload.get("role", "user")}
    except jwt.ExpiredSignatureError:
        raise HTTPException(status_code=401, detail="Token expirado")
    except Exception:
        raise HTTPException(status_code=401, detail="Token inválido")

def require_admin(user=Depends(verificar_token)):
    if user["role"] != "admin":
        raise HTTPException(status_code=403, detail="Acesso restrito a administradores")
    return user

# ── MODELS ──
class LoginInput(BaseModel):
    username: str
    password: str

class SenhaInput(BaseModel):
    senha_atual: str
    senha_nova: str

class SalarioInput(BaseModel):
    salario: float

class ConfigInput(BaseModel):
    mes_inicio: str

class GastoInput(BaseModel):
    nome: str
    cat: str
    mes_inicio_idx: int
    mes_fim_idx: int
    valor: float

class GastoUpdate(BaseModel):
    nome: str
    cat: str

class ValorUpdate(BaseModel):
    idx: int
    valor: float

class ParcelaInput(BaseModel):
    nome: str
    cat: str
    total: float
    qtd: int
    mes_idx: int
    valor_parcela: float

class LancamentoInput(BaseModel):
    descricao: str
    valor: float
    cat: str
    local: Optional[str] = ""
    recorrencia: Optional[str] = "nunca"
    motivo: Optional[str] = ""
    mes_idx: Optional[int] = None
    tipo_ajuste: Optional[str] = None  # "subtrair" | "somar" | None (ajuste de fixo: só auditoria, não entra no total)

class MetaInput(BaseModel):
    nome: str
    valor_alvo: float
    cor: Optional[str] = "green"

class MetaAporteInput(BaseModel):
    valor: float

class CriarUsuarioInput(BaseModel):
    username: str
    password: str
    role: Optional[str] = "user"

class EditarUsuarioInput(BaseModel):
    username: Optional[str] = None
    role: Optional[str] = None

class AdminSenhaInput(BaseModel):
    senha_nova: str

class CategoriaInput(BaseModel):
    nome: str
    label: str
    emoji: str
    cor: str
    tipo: str  # "gasto" | "lancamento" | "ambos"

class HistoricoFecharInput(BaseModel):
    mes_idx: int
    mes_ref: str  # "YYYY-MM" absoluto, imune a troca de mes_inicio
    salario: float = 0
    fixos: float = 0
    parcelas: float = 0
    lancamentos: float = 0
    total: float = 0
    sobra: float = 0
    detalhes: Optional[str] = ""

class AnotacaoInput(BaseModel):
    titulo: str

class AnotacaoItemInput(BaseModel):
    nome: str
    valor_total: float
    qtd: int
    mes_ref: str  # "YYYY-MM" da 1ª parcela (absoluto)

class AnotacaoCheckInput(BaseModel):
    k: int  # 1..qtd (número da parcela)

# ── AUTH ──
@app.post("/api/login")
def login(data: LoginInput):
    db = get_db(); cur = db.cursor(dictionary=True)
    cur.execute("SELECT * FROM usuarios WHERE username = %s", (data.username,))
    user = cur.fetchone(); cur.close(); db.close()
    if not user or not bcrypt.checkpw(data.password.encode(), user["senha_hash"].encode()):
        raise HTTPException(status_code=401, detail="Usuário ou senha incorretos")
    payload = {"sub": user["id"], "role": user.get("role","user"), "exp": datetime.utcnow() + timedelta(hours=JWT_EXPIRE_HOURS)}
    token = jwt.encode(payload, JWT_SECRET, algorithm="HS256")
    return {"token": token, "username": user["username"], "role": user.get("role","user")}

@app.get("/api/me")
def me(user=Depends(verificar_token)):
    db = get_db(); cur = db.cursor(dictionary=True)
    cur.execute("SELECT id, username, role FROM usuarios WHERE id = %s", (user["id"],))
    row = cur.fetchone(); cur.close(); db.close()
    if not row: raise HTTPException(status_code=404, detail="Não encontrado")
    return row

@app.put("/api/senha")
def trocar_senha(data: SenhaInput, user=Depends(verificar_token)):
    db = get_db(); cur = db.cursor(dictionary=True)
    cur.execute("SELECT senha_hash FROM usuarios WHERE id = %s", (user["id"],))
    row = cur.fetchone()
    if not row or not bcrypt.checkpw(data.senha_atual.encode(), row["senha_hash"].encode()):
        cur.close(); db.close(); raise HTTPException(status_code=400, detail="Senha atual incorreta")
    if len(data.senha_nova) < 6:
        cur.close(); db.close(); raise HTTPException(status_code=400, detail="Mínimo 6 caracteres")
    h = bcrypt.hashpw(data.senha_nova.encode(), bcrypt.gensalt()).decode()
    cur.execute("UPDATE usuarios SET senha_hash=%s WHERE id=%s", (h, user["id"]))
    cur.close(); db.close(); return {"ok": True}

# ── CONFIG ──
@app.get("/api/config")
def get_config(user=Depends(verificar_token)):
    db = get_db(); cur = db.cursor(dictionary=True)
    cur.execute("SELECT salario, mes_inicio FROM usuarios WHERE id = %s", (user["id"],))
    row = cur.fetchone(); cur.close(); db.close()
    return row or {"salario": 0, "mes_inicio": ""}

@app.put("/api/config/salario")
def update_salario(data: SalarioInput, user=Depends(verificar_token)):
    db = get_db(); cur = db.cursor()
    cur.execute("UPDATE usuarios SET salario=%s WHERE id=%s", (data.salario, user["id"]))
    cur.close(); db.close(); return {"ok": True}

@app.put("/api/config/mes-inicio")
def update_mes_inicio(data: ConfigInput, user=Depends(verificar_token)):
    import re
    if not re.match(r"^\d{4}-\d{2}$", data.mes_inicio or ""):
        raise HTTPException(status_code=400, detail="Formato inválido (YYYY-MM)")
    db = get_db(); cur = db.cursor(dictionary=True)
    cur.execute("SELECT mes_inicio FROM usuarios WHERE id = %s", (user["id"],))
    row = cur.fetchone()
    antigo = (row or {}).get("mes_inicio") or ""
    if not antigo or antigo == data.mes_inicio:
        cur.execute("UPDATE usuarios SET mes_inicio=%s WHERE id=%s", (data.mes_inicio, user["id"]))
        cur.close(); db.close(); return {"ok": True, "offset": 0}
    ya, ma = map(int, antigo.split("-")); yn, mn = map(int, data.mes_inicio.split("-"))
    offset = (yn - ya) * 12 + (mn - ma)
    if offset != 0:
        # Reposiciona gasto_valores preservando a data de calendário:
        # novo_idx = antigo_idx - offset (ex: base jan->fev, o que era idx1/agosto vira idx0)
        cur.execute("SELECT id FROM gastos WHERE user_id=%s", (user["id"],))
        gids = [r["id"] for r in cur.fetchall()]
        for gid in gids:
            cur.execute("SELECT idx, valor FROM gasto_valores WHERE gasto_id=%s", (gid,))
            vals = {r["idx"]: float(r["valor"]) for r in cur.fetchall()}
            novos = {}
            for old_idx, v in vals.items():
                ni = old_idx - offset
                if 0 <= ni < 48:
                    novos[ni] = v
            cur.execute("DELETE FROM gasto_valores WHERE gasto_id=%s", (gid,))
            for ni, v in novos.items():
                cur.execute("INSERT INTO gasto_valores (gasto_id,idx,valor) VALUES (%s,%s,%s)", (gid, ni, v))
        cur.execute("UPDATE parcelas SET mes_idx=mes_idx-%s WHERE user_id=%s", (offset, user["id"]))
        cur.execute("UPDATE lancamentos SET mes_idx=mes_idx-%s WHERE user_id=%s AND mes_idx IS NOT NULL", (offset, user["id"]))
    cur.execute("UPDATE usuarios SET mes_inicio=%s WHERE id=%s", (data.mes_inicio, user["id"]))
    cur.close(); db.close(); return {"ok": True, "offset": offset}

# ── TELEGRAM ──
@app.get("/api/telegram/status")
def telegram_status(user=Depends(verificar_token)):
    db = get_db(); cur = db.cursor(dictionary=True)
    cur.execute("SELECT telegram_chat_id FROM usuarios WHERE id=%s", (user["id"],))
    row = cur.fetchone(); cur.close(); db.close()
    vinculado = bool(row and row.get("telegram_chat_id"))
    return {"vinculado": vinculado}

@app.post("/api/telegram/gerar-codigo")
def telegram_gerar_codigo(user=Depends(verificar_token)):
    import random, string
    codigo = ''.join(random.choices(string.digits, k=6))
    db = get_db(); cur = db.cursor()
    cur.execute("UPDATE usuarios SET telegram_link_code=%s WHERE id=%s", (codigo, user["id"]))
    cur.close(); db.close()
    return {"codigo": codigo}

@app.post("/api/telegram/desvincular")
def telegram_desvincular(user=Depends(verificar_token)):
    db = get_db(); cur = db.cursor()
    cur.execute("UPDATE usuarios SET telegram_chat_id=NULL, telegram_link_code=NULL WHERE id=%s", (user["id"],))
    cur.close(); db.close()
    return {"ok": True}

# ── GASTOS ──
@app.get("/api/gastos")
def listar_gastos(user=Depends(verificar_token)):
    db = get_db(); cur = db.cursor(dictionary=True)
    cur.execute("SELECT * FROM gastos WHERE user_id=%s ORDER BY criado_em", (user["id"],))
    gastos = cur.fetchall()
    for g in gastos:
        cur.execute("SELECT idx, valor FROM gasto_valores WHERE gasto_id=%s ORDER BY idx", (g["id"],))
        vals = cur.fetchall(); valores = [0.0]*48
        for r in vals: valores[r["idx"]] = float(r["valor"])
        g["valores"] = valores
    cur.close(); db.close(); return gastos

@app.post("/api/gastos")
def criar_gasto(data: GastoInput, user=Depends(verificar_token)):
    db = get_db(); cur = db.cursor()
    cur.execute("INSERT INTO gastos (user_id,nome,cat) VALUES (%s,%s,%s)", (user["id"],data.nome,data.cat))
    gid = cur.lastrowid
    for i in range(data.mes_inicio_idx, min(data.mes_fim_idx+1,48)):
        if data.valor > 0:
            cur.execute("INSERT INTO gasto_valores (gasto_id,idx,valor) VALUES (%s,%s,%s)", (gid,i,data.valor))
    cur.close(); db.close(); return {"id": gid}

@app.put("/api/gastos/{gid}")
def atualizar_gasto(gid: int, data: GastoUpdate, user=Depends(verificar_token)):
    db = get_db(); cur = db.cursor()
    cur.execute("UPDATE gastos SET nome=%s,cat=%s WHERE id=%s AND user_id=%s", (data.nome,data.cat,gid,user["id"]))
    cur.close(); db.close(); return {"ok": True}

@app.put("/api/gastos/{gid}/valor")
def atualizar_valor(gid: int, data: ValorUpdate, user=Depends(verificar_token)):
    db = get_db(); cur = db.cursor()
    cur.execute("SELECT id FROM gastos WHERE id=%s AND user_id=%s", (gid,user["id"]))
    if not cur.fetchone(): cur.close(); db.close(); raise HTTPException(status_code=403)
    if data.valor and data.valor != 0:
        cur.execute("INSERT INTO gasto_valores (gasto_id,idx,valor) VALUES (%s,%s,%s) ON DUPLICATE KEY UPDATE valor=%s", (gid,data.idx,data.valor,data.valor))
    else:
        cur.execute("DELETE FROM gasto_valores WHERE gasto_id=%s AND idx=%s", (gid,data.idx))
    cur.close(); db.close(); return {"ok": True}

@app.delete("/api/gastos/{gid}")
def deletar_gasto(gid: int, user=Depends(verificar_token)):
    db = get_db(); cur = db.cursor()
    cur.execute("DELETE FROM gastos WHERE id=%s AND user_id=%s", (gid,user["id"]))
    cur.close(); db.close(); return {"ok": True}

# ── PARCELAS ──
@app.get("/api/parcelas")
def listar_parcelas(user=Depends(verificar_token)):
    db = get_db(); cur = db.cursor(dictionary=True)
    cur.execute("SELECT * FROM parcelas WHERE user_id=%s ORDER BY criado_em", (user["id"],))
    rows = cur.fetchall(); cur.close(); db.close()
    for r in rows:
        r["total"]=float(r["total"]); r["valor_parcela"]=float(r["valor_parcela"])
        r["mesIdx"]=r.pop("mes_idx"); r["valorParcela"]=r.pop("valor_parcela")
    return rows

@app.post("/api/parcelas")
def criar_parcela(data: ParcelaInput, user=Depends(verificar_token)):
    db = get_db(); cur = db.cursor()
    cur.execute("INSERT INTO parcelas (user_id,nome,cat,total,qtd,mes_idx,valor_parcela) VALUES (%s,%s,%s,%s,%s,%s,%s)",
        (user["id"],data.nome,data.cat,data.total,data.qtd,data.mes_idx,data.valor_parcela))
    pid = cur.lastrowid; cur.close(); db.close(); return {"id": pid}

@app.delete("/api/parcelas/{pid}")
def deletar_parcela(pid: int, user=Depends(verificar_token)):
    db = get_db(); cur = db.cursor()
    cur.execute("DELETE FROM parcelas WHERE id=%s AND user_id=%s", (pid,user["id"]))
    cur.close(); db.close(); return {"ok": True}

# ── LANÇAMENTOS ──
@app.get("/api/lancamentos")
def listar_lancamentos(user=Depends(verificar_token)):
    db = get_db(); cur = db.cursor(dictionary=True)
    cur.execute("SELECT * FROM lancamentos WHERE user_id=%s ORDER BY criado_em DESC LIMIT 500", (user["id"],))
    rows = cur.fetchall(); cur.close(); db.close()
    for r in rows:
        r["valor"]=float(r["valor"])
        r["criado_em"]=r["criado_em"].isoformat()
        r["motivo"]=r.get("motivo","") or ""
        r["mes_idx"]=r.get("mes_idx")
        r["tipo_ajuste"]=r.get("tipo_ajuste")
    return rows

@app.post("/api/lancamentos")
def criar_lancamento(data: LancamentoInput, user=Depends(verificar_token)):
    db = get_db(); cur = db.cursor()
    cur.execute(
        "INSERT INTO lancamentos (user_id,descricao,valor,cat,local_nome,recorrencia,motivo,mes_idx,tipo_ajuste) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)",
        (user["id"],data.descricao,data.valor,data.cat,data.local or "",
         data.recorrencia or "nunca", data.motivo or "", data.mes_idx, data.tipo_ajuste)
    )
    lid = cur.lastrowid; cur.close(); db.close(); return {"id": lid}

@app.delete("/api/lancamentos/{lid}")
def deletar_lancamento(lid: int, user=Depends(verificar_token)):
    db = get_db(); cur = db.cursor()
    cur.execute("DELETE FROM lancamentos WHERE id=%s AND user_id=%s", (lid,user["id"]))
    cur.close(); db.close(); return {"ok": True}

# ── METAS ──
@app.get("/api/metas")
def listar_metas(user=Depends(verificar_token)):
    db = get_db(); cur = db.cursor(dictionary=True)
    cur.execute("SELECT * FROM metas WHERE user_id=%s ORDER BY criado_em", (user["id"],))
    rows = cur.fetchall(); cur.close(); db.close()
    for r in rows: r["valor_alvo"]=float(r["valor_alvo"]); r["valor_atual"]=float(r["valor_atual"])
    return rows

@app.post("/api/metas")
def criar_meta(data: MetaInput, user=Depends(verificar_token)):
    db = get_db(); cur = db.cursor()
    cur.execute("INSERT INTO metas (user_id,nome,valor_alvo,cor) VALUES (%s,%s,%s,%s)",
        (user["id"],data.nome,data.valor_alvo,data.cor or "green"))
    mid = cur.lastrowid; cur.close(); db.close(); return {"id": mid}

@app.put("/api/metas/{mid}/aportar")
def aportar_meta(mid: int, data: MetaAporteInput, user=Depends(verificar_token)):
    db = get_db(); cur = db.cursor()
    cur.execute("UPDATE metas SET valor_atual=valor_atual+%s WHERE id=%s AND user_id=%s", (data.valor,mid,user["id"]))
    cur.close(); db.close(); return {"ok": True}

@app.delete("/api/metas/{mid}")
def deletar_meta(mid: int, user=Depends(verificar_token)):
    db = get_db(); cur = db.cursor()
    cur.execute("DELETE FROM metas WHERE id=%s AND user_id=%s", (mid,user["id"]))
    cur.close(); db.close(); return {"ok": True}

# ── UPLOAD DE ANEXOS ──
@app.post("/api/lancamentos/{lid}/anexo")
async def upload_anexo(lid: int, arquivo: UploadFile = File(...), user=Depends(verificar_token)):
    db = get_db(); cur = db.cursor(dictionary=True)
    cur.execute("SELECT id FROM lancamentos WHERE id=%s AND user_id=%s", (lid, user["id"]))
    if not cur.fetchone():
        cur.close(); db.close()
        raise HTTPException(status_code=403, detail="Sem permissao")
    ext = os.path.splitext(arquivo.filename or "")[1].lower() or ".bin"
    nome_arquivo = f"{uuid.uuid4().hex}{ext}"
    caminho = os.path.join(UPLOAD_DIR, nome_arquivo)
    with open(caminho, "wb") as fh:
        shutil.copyfileobj(arquivo.file, fh)
    tamanho = os.path.getsize(caminho)
    cur.execute(
        "INSERT INTO lancamento_anexos (lancamento_id, nome_original, nome_arquivo, tipo, tamanho) VALUES (%s,%s,%s,%s,%s)",
        (lid, arquivo.filename, nome_arquivo, arquivo.content_type or "application/octet-stream", tamanho)
    )
    aid = cur.lastrowid; cur.close(); db.close()
    return {"id": aid, "nome_original": arquivo.filename, "nome_arquivo": nome_arquivo, "url": f"/uploads/{nome_arquivo}"}

@app.get("/api/lancamentos/{lid}/anexos")
def listar_anexos(lid: int, user=Depends(verificar_token)):
    db = get_db(); cur = db.cursor(dictionary=True)
    cur.execute("SELECT id FROM lancamentos WHERE id=%s AND user_id=%s", (lid, user["id"]))
    if not cur.fetchone():
        cur.close(); db.close(); raise HTTPException(status_code=403)
    cur.execute("SELECT * FROM lancamento_anexos WHERE lancamento_id=%s ORDER BY criado_em", (lid,))
    rows = cur.fetchall(); cur.close(); db.close()
    for r in rows:
        r["url"] = f"/uploads/{r['nome_arquivo']}"
        r["criado_em"] = r["criado_em"].isoformat()
        r["tamanho"] = int(r["tamanho"] or 0)
    return rows

@app.delete("/api/anexos/{aid}")
def deletar_anexo(aid: int, user=Depends(verificar_token)):
    db = get_db(); cur = db.cursor(dictionary=True)
    sql = "SELECT a.nome_arquivo FROM lancamento_anexos a JOIN lancamentos l ON a.lancamento_id=l.id WHERE a.id=%s AND l.user_id=%s"
    cur.execute(sql, (aid, user["id"]))
    row = cur.fetchone()
    if not row: cur.close(); db.close(); raise HTTPException(status_code=403)
    caminho = os.path.join(UPLOAD_DIR, row["nome_arquivo"])
    if os.path.exists(caminho): os.remove(caminho)
    cur.execute("DELETE FROM lancamento_anexos WHERE id=%s", (aid,))
    cur.close(); db.close(); return {"ok": True}

@app.get("/api/lancamentos-todos")
def listar_todos_lancamentos(user=Depends(verificar_token)):
    db = get_db(); cur = db.cursor(dictionary=True)
    cur.execute("SELECT * FROM lancamentos WHERE user_id=%s ORDER BY criado_em DESC LIMIT 1000", (user["id"],))
    lancs = cur.fetchall()
    for l in lancs:
        l["valor"] = float(l["valor"])
        l["criado_em"] = l["criado_em"].isoformat()
        l["motivo"] = l.get("motivo","") or ""
        l["mes_idx"] = l.get("mes_idx")
        l["tipo_ajuste"] = l.get("tipo_ajuste")
        cur.execute("SELECT id, nome_original, nome_arquivo, tipo, tamanho FROM lancamento_anexos WHERE lancamento_id=%s", (l["id"],))
        anexos = cur.fetchall()
        for a in anexos:
            a["url"] = f"/uploads/{a['nome_arquivo']}"
            a["tamanho"] = int(a["tamanho"] or 0)
        l["anexos"] = anexos
    cur.close(); db.close(); return lancs

# ── COMPARATIVO (só avulsos; ajustes de fixo já estão no valor do fixo) ──
@app.get("/api/comparativo")
def comparativo(user=Depends(verificar_token)):
    db = get_db(); cur = db.cursor(dictionary=True)
    cur.execute("""SELECT DATE_FORMAT(criado_em,'%Y-%m') as mes, cat, SUM(valor) as total
        FROM lancamentos WHERE user_id=%s AND tipo_ajuste IS NULL AND criado_em>=DATE_SUB(NOW(),INTERVAL 6 MONTH)
        GROUP BY mes,cat ORDER BY mes DESC""", (user["id"],))
    rows = cur.fetchall(); cur.close(); db.close()
    for r in rows: r["total"]=float(r["total"])
    return rows

# ── HISTÓRICO (snapshots congelados de meses fechados) ──
@app.get("/api/historico")
def listar_historico(user=Depends(verificar_token)):
    db = get_db(); cur = db.cursor(dictionary=True)
    cur.execute("SELECT * FROM historico_meses WHERE user_id=%s ORDER BY mes_ref", (user["id"],))
    rows = cur.fetchall(); cur.close(); db.close()
    for r in rows:
        for k in ("salario", "fixos", "parcelas", "lancamentos", "total", "sobra"):
            try: r[k] = float(r[k] or 0)
            except Exception: r[k] = 0.0
        try: r["criado_em"] = r["criado_em"].isoformat() if r.get("criado_em") else ""
        except Exception: r["criado_em"] = ""
    return rows

@app.post("/api/historico/fechar")
def fechar_mes(data: HistoricoFecharInput, user=Depends(verificar_token)):
    import re
    if not re.match(r"^\d{4}-\d{2}$", data.mes_ref or ""):
        raise HTTPException(status_code=400, detail="mes_ref inválido (YYYY-MM)")
    db = get_db(); cur = db.cursor()
    cur.execute(
        """INSERT INTO historico_meses (user_id,mes_ref,mes_idx,salario,fixos,parcelas,lancamentos,total,sobra,detalhes)
        VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
        ON DUPLICATE KEY UPDATE mes_idx=%s,salario=%s,fixos=%s,parcelas=%s,lancamentos=%s,total=%s,sobra=%s,detalhes=%s""",
        (user["id"], data.mes_ref, data.mes_idx, data.salario, data.fixos, data.parcelas,
         data.lancamentos, data.total, data.sobra, data.detalhes or "",
         data.mes_idx, data.salario, data.fixos, data.parcelas, data.lancamentos,
         data.total, data.sobra, data.detalhes or ""))
    hid = cur.lastrowid; cur.close(); db.close()
    return {"ok": True, "id": hid, "mes_ref": data.mes_ref}

@app.delete("/api/historico/{hid}")
def reabrir_mes(hid: int, user=Depends(verificar_token)):
    db = get_db(); cur = db.cursor()
    cur.execute("DELETE FROM historico_meses WHERE id=%s AND user_id=%s", (hid, user["id"]))
    cur.close(); db.close(); return {"ok": True}

# ── ANOTAÇÕES (controle paralelo: não entra em nenhum total) ──
@app.get("/api/anotacoes")
def listar_anotacoes(user=Depends(verificar_token)):
    db = get_db(); cur = db.cursor(dictionary=True)
    cur.execute("SELECT * FROM anotacoes WHERE user_id=%s ORDER BY criado_em DESC", (user["id"],))
    notas = cur.fetchall()
    for n in notas:
        n["criado_em"] = n["criado_em"].isoformat() if n.get("criado_em") else ""
        cur.execute("SELECT * FROM anotacao_itens WHERE anotacao_id=%s ORDER BY id", (n["id"],))
        itens = cur.fetchall()
        for it in itens:
            it["valor_total"] = float(it["valor_total"] or 0)
            cur.execute("SELECT k FROM anotacao_checks WHERE item_id=%s", (it["id"],))
            it["pagas"] = sorted([r["k"] for r in cur.fetchall()])
        n["itens"] = itens
    cur.close(); db.close(); return notas

@app.post("/api/anotacoes")
def criar_anotacao(data: AnotacaoInput, user=Depends(verificar_token)):
    titulo = (data.titulo or "").strip()
    if not titulo:
        raise HTTPException(status_code=400, detail="Informe o título")
    db = get_db(); cur = db.cursor()
    cur.execute("INSERT INTO anotacoes (user_id,titulo) VALUES (%s,%s)", (user["id"], titulo))
    nid = cur.lastrowid; cur.close(); db.close(); return {"id": nid}

@app.delete("/api/anotacoes/{nid}")
def deletar_anotacao(nid: int, user=Depends(verificar_token)):
    db = get_db(); cur = db.cursor()
    cur.execute("DELETE FROM anotacoes WHERE id=%s AND user_id=%s", (nid, user["id"]))
    cur.close(); db.close(); return {"ok": True}

@app.post("/api/anotacoes/{nid}/itens")
def criar_anotacao_item(nid: int, data: AnotacaoItemInput, user=Depends(verificar_token)):
    import re
    nome = (data.nome or "").strip()
    if not nome:
        raise HTTPException(status_code=400, detail="Informe o nome")
    if not data.valor_total or data.valor_total <= 0:
        raise HTTPException(status_code=400, detail="Valor inválido")
    if not 1 <= (data.qtd or 0) <= 120:
        raise HTTPException(status_code=400, detail="Parcelas de 1 a 120")
    if not re.match(r"^\d{4}-\d{2}$", data.mes_ref or ""):
        raise HTTPException(status_code=400, detail="Mês inválido (YYYY-MM)")
    db = get_db(); cur = db.cursor(dictionary=True)
    cur.execute("SELECT id FROM anotacoes WHERE id=%s AND user_id=%s", (nid, user["id"]))
    if not cur.fetchone():
        cur.close(); db.close(); raise HTTPException(status_code=403)
    cur.execute("INSERT INTO anotacao_itens (anotacao_id,nome,valor_total,qtd,mes_ref) VALUES (%s,%s,%s,%s,%s)",
        (nid, nome, data.valor_total, data.qtd, data.mes_ref))
    iid = cur.lastrowid; cur.close(); db.close(); return {"id": iid}

@app.delete("/api/anotacoes/itens/{iid}")
def deletar_anotacao_item(iid: int, user=Depends(verificar_token)):
    db = get_db(); cur = db.cursor()
    cur.execute("""DELETE ai FROM anotacao_itens ai
        JOIN anotacoes a ON ai.anotacao_id=a.id
        WHERE ai.id=%s AND a.user_id=%s""", (iid, user["id"]))
    cur.close(); db.close(); return {"ok": True}

@app.post("/api/anotacoes/itens/{iid}/check")
def alternar_anotacao_check(iid: int, data: AnotacaoCheckInput, user=Depends(verificar_token)):
    db = get_db(); cur = db.cursor(dictionary=True)
    cur.execute("""SELECT ai.qtd FROM anotacao_itens ai
        JOIN anotacoes a ON ai.anotacao_id=a.id
        WHERE ai.id=%s AND a.user_id=%s""", (iid, user["id"]))
    row = cur.fetchone()
    if not row:
        cur.close(); db.close(); raise HTTPException(status_code=403)
    if not 1 <= (data.k or 0) <= int(row["qtd"]):
        cur.close(); db.close(); raise HTTPException(status_code=400, detail="Parcela inválida")
    cur.execute("SELECT k FROM anotacao_checks WHERE item_id=%s AND k=%s", (iid, data.k))
    if cur.fetchone():
        cur.execute("DELETE FROM anotacao_checks WHERE item_id=%s AND k=%s", (iid, data.k))
        pago = False
    else:
        cur.execute("INSERT INTO anotacao_checks (item_id,k) VALUES (%s,%s)", (iid, data.k))
        pago = True
    cur.close(); db.close(); return {"ok": True, "pago": pago}

@app.on_event("startup")
def garantir_tabela_historico():
    try:
        db = get_db(); cur = db.cursor()
        cur.execute("""CREATE TABLE IF NOT EXISTS historico_meses (
            id INT AUTO_INCREMENT PRIMARY KEY,
            user_id INT NOT NULL,
            mes_ref VARCHAR(7) NOT NULL,
            mes_idx INT NOT NULL DEFAULT 0,
            salario DECIMAL(12,2) DEFAULT 0,
            fixos DECIMAL(12,2) DEFAULT 0,
            parcelas DECIMAL(12,2) DEFAULT 0,
            lancamentos DECIMAL(12,2) DEFAULT 0,
            total DECIMAL(12,2) DEFAULT 0,
            sobra DECIMAL(12,2) DEFAULT 0,
            detalhes TEXT NULL,
            criado_em DATETIME DEFAULT NOW(),
            UNIQUE KEY uq_hist_user_mes (user_id, mes_ref),
            FOREIGN KEY (user_id) REFERENCES usuarios(id) ON DELETE CASCADE
        )""")
        cur.execute("ALTER TABLE lancamentos ADD COLUMN IF NOT EXISTS tipo_ajuste VARCHAR(20) DEFAULT NULL")
        cur.execute("""CREATE TABLE IF NOT EXISTS anotacoes (
            id INT AUTO_INCREMENT PRIMARY KEY,
            user_id INT NOT NULL,
            titulo VARCHAR(100) NOT NULL,
            criado_em DATETIME DEFAULT NOW(),
            FOREIGN KEY (user_id) REFERENCES usuarios(id) ON DELETE CASCADE
        )""")
        cur.execute("""CREATE TABLE IF NOT EXISTS anotacao_itens (
            id INT AUTO_INCREMENT PRIMARY KEY,
            anotacao_id INT NOT NULL,
            nome VARCHAR(100) NOT NULL,
            valor_total DECIMAL(12,2) NOT NULL,
            qtd INT NOT NULL,
            mes_ref VARCHAR(7) NOT NULL,
            FOREIGN KEY (anotacao_id) REFERENCES anotacoes(id) ON DELETE CASCADE
        )""")
        cur.execute("""CREATE TABLE IF NOT EXISTS anotacao_checks (
            item_id INT NOT NULL,
            k INT NOT NULL,
            marcado_em DATETIME DEFAULT NOW(),
            PRIMARY KEY (item_id, k),
            FOREIGN KEY (item_id) REFERENCES anotacao_itens(id) ON DELETE CASCADE
        )""")
        cur.close(); db.close()
    except Exception:
        pass

# ── ADMIN: USUÁRIOS ──
@app.get("/api/admin/usuarios")
def admin_listar_usuarios(user=Depends(require_admin)):
    db = get_db(); cur = db.cursor(dictionary=True)
    cur.execute("SELECT id, username, role, salario, criado_em FROM usuarios ORDER BY criado_em")
    rows = cur.fetchall(); cur.close(); db.close()
    for r in rows:
        r["salario"] = float(r["salario"] or 0)
        r["criado_em"] = r["criado_em"].isoformat() if r["criado_em"] else ""
    return rows

@app.post("/api/admin/usuarios")
def admin_criar_usuario(data: CriarUsuarioInput, user=Depends(require_admin)):
    if len(data.password) < 6:
        raise HTTPException(status_code=400, detail="Senha deve ter pelo menos 6 caracteres")
    h = bcrypt.hashpw(data.password.encode(), bcrypt.gensalt()).decode()
    db = get_db(); cur = db.cursor()
    try:
        cur.execute("INSERT INTO usuarios (username,senha_hash,role) VALUES (%s,%s,%s)",
            (data.username, h, data.role or "user"))
        uid = cur.lastrowid
    except Exception:
        cur.close(); db.close(); raise HTTPException(status_code=400, detail="Usuário já existe")
    cur.close(); db.close(); return {"id": uid}

@app.put("/api/admin/usuarios/{uid}")
def admin_editar_usuario(uid: int, data: EditarUsuarioInput, user=Depends(require_admin)):
    if uid == user["id"]:
        raise HTTPException(status_code=400, detail="Não é possível editar o próprio perfil aqui")
    db = get_db(); cur = db.cursor()
    if data.username:
        cur.execute("UPDATE usuarios SET username=%s WHERE id=%s", (data.username, uid))
    if data.role:
        cur.execute("UPDATE usuarios SET role=%s WHERE id=%s", (data.role, uid))
    cur.close(); db.close(); return {"ok": True}

@app.put("/api/admin/usuarios/{uid}/senha")
def admin_trocar_senha(uid: int, data: AdminSenhaInput, user=Depends(require_admin)):
    if len(data.senha_nova) < 6:
        raise HTTPException(status_code=400, detail="Mínimo 6 caracteres")
    h = bcrypt.hashpw(data.senha_nova.encode(), bcrypt.gensalt()).decode()
    db = get_db(); cur = db.cursor()
    cur.execute("UPDATE usuarios SET senha_hash=%s WHERE id=%s", (h, uid))
    cur.close(); db.close(); return {"ok": True}

@app.delete("/api/admin/usuarios/{uid}")
def admin_deletar_usuario(uid: int, user=Depends(require_admin)):
    if uid == user["id"]:
        raise HTTPException(status_code=400, detail="Não é possível remover a si mesmo")
    db = get_db(); cur = db.cursor()
    cur.execute("DELETE FROM usuarios WHERE id=%s", (uid,))
    cur.close(); db.close(); return {"ok": True}

# ── ADMIN: CATEGORIAS ──
@app.get("/api/categorias")
def listar_categorias(user=Depends(verificar_token)):
    db = get_db(); cur = db.cursor(dictionary=True)
    cur.execute("SELECT * FROM categorias ORDER BY tipo, label")
    rows = cur.fetchall(); cur.close(); db.close()
    return rows

@app.post("/api/admin/categorias")
def criar_categoria(data: CategoriaInput, user=Depends(require_admin)):
    db = get_db(); cur = db.cursor()
    try:
        cur.execute("INSERT INTO categorias (nome,label,emoji,cor,tipo) VALUES (%s,%s,%s,%s,%s)",
            (data.nome,data.label,data.emoji,data.cor,data.tipo))
        cid = cur.lastrowid
    except Exception:
        cur.close(); db.close(); raise HTTPException(status_code=400, detail="Categoria já existe")
    cur.close(); db.close(); return {"id": cid}

@app.put("/api/admin/categorias/{cid}")
def editar_categoria(cid: int, data: CategoriaInput, user=Depends(require_admin)):
    db = get_db(); cur = db.cursor()
    cur.execute("UPDATE categorias SET nome=%s,label=%s,emoji=%s,cor=%s,tipo=%s WHERE id=%s",
        (data.nome,data.label,data.emoji,data.cor,data.tipo,cid))
    cur.close(); db.close(); return {"ok": True}

@app.delete("/api/admin/categorias/{cid}")
def deletar_categoria(cid: int, user=Depends(require_admin)):
    db = get_db(); cur = db.cursor()
    cur.execute("DELETE FROM categorias WHERE id=%s", (cid,))
    cur.close(); db.close(); return {"ok": True}

# ── AJUSTE DE GASTO FIXO (adicionar ou subtrair valor de um mês específico) ──
class AjusteGastoInput(BaseModel):
    gasto_id: int
    idx: int          # índice do mês
    delta: float      # positivo = adiciona, negativo = subtrai

@app.post("/api/gastos/ajuste")
def ajustar_gasto(data: AjusteGastoInput, user=Depends(verificar_token)):
    db = get_db(); cur = db.cursor(dictionary=True)
    cur.execute("SELECT id FROM gastos WHERE id=%s AND user_id=%s", (data.gasto_id, user["id"]))
    if not cur.fetchone(): cur.close(); db.close(); raise HTTPException(status_code=403)
    # busca valor atual
    cur.execute("SELECT valor FROM gasto_valores WHERE gasto_id=%s AND idx=%s", (data.gasto_id, data.idx))
    row = cur.fetchone()
    valor_atual = float(row["valor"]) if row else 0.0
    novo_valor = round(valor_atual + data.delta, 2)  # permite negativo (a receber)
    if novo_valor != 0:
        cur.execute("INSERT INTO gasto_valores (gasto_id,idx,valor) VALUES (%s,%s,%s) ON DUPLICATE KEY UPDATE valor=%s",
            (data.gasto_id, data.idx, novo_valor, novo_valor))
    else:
        cur.execute("DELETE FROM gasto_valores WHERE gasto_id=%s AND idx=%s", (data.gasto_id, data.idx))
    cur.close(); db.close()
    return {"ok": True, "novo_valor": novo_valor}

# ── PARCELA VINCULADA A GASTO EXISTENTE ──
class ParcelaVinculadaInput(BaseModel):
    gasto_id: int
    total: float
    qtd: int
    mes_idx: int

@app.post("/api/gastos/{gasto_id}/parcela")
def adicionar_parcela_em_gasto(gasto_id: int, data: ParcelaVinculadaInput, user=Depends(verificar_token)):
    """Soma as parcelas mês a mês no gasto fixo existente."""
    db = get_db(); cur = db.cursor(dictionary=True)
    cur.execute("SELECT id FROM gastos WHERE id=%s AND user_id=%s", (gasto_id, user["id"]))
    if not cur.fetchone(): cur.close(); db.close(); raise HTTPException(status_code=403)
    valor_parcela = round(data.total / data.qtd, 2)
    for k in range(data.qtd):
        idx = data.mes_idx + k
        if idx >= 48: break
        cur.execute("SELECT valor FROM gasto_valores WHERE gasto_id=%s AND idx=%s", (gasto_id, idx))
        row = cur.fetchone()
        novo = round((float(row["valor"]) if row else 0.0) + valor_parcela, 2)
        cur.execute("INSERT INTO gasto_valores (gasto_id,idx,valor) VALUES (%s,%s,%s) ON DUPLICATE KEY UPDATE valor=%s",
            (gasto_id, idx, novo, novo))
    cur.close(); db.close()
    return {"ok": True, "valor_parcela": valor_parcela}
