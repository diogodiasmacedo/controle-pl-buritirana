"""
Controle de Projetos de Lei - Prefeitura Municipal de Buritirana/MA
Versão Cloud: Supabase (banco + storage) + extração local gratuita
"""

import os, json, re, tempfile, time, uuid
from pathlib import Path
from flask import Flask, request, jsonify, send_from_directory
from flask_cors import CORS
from supabase import create_client, Client

app = Flask(__name__, static_folder="static")
CORS(app)

# ── Supabase ──────────────────────────────────────────────────────────────────
SUPABASE_URL = os.environ.get("SUPABASE_URL", "https://jpmhpldsiawjnaauernl.supabase.co")
SUPABASE_KEY = os.environ.get("SUPABASE_KEY", "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6ImpwbWhwbGRzaWF3am5hYXVlcm5sIiwicm9sZSI6ImFub24iLCJpYXQiOjE3NzY2MDYwNjgsImV4cCI6MjA5MjE4MjA2OH0.Z7W3PYvoq-4MhO3xjn6SPT0HK-fROGJtgjgX1zwzRtw")
STORAGE_BUCKET = "documentos-pl"

def get_sb() -> Client:
    return create_client(SUPABASE_URL, SUPABASE_KEY)

# ── Meses ─────────────────────────────────────────────────────────────────────
MESES = {
    "janeiro":"01","fevereiro":"02","março":"03","marco":"03",
    "abril":"04","maio":"05","junho":"06",
    "julho":"07","agosto":"08","setembro":"09",
    "outubro":"10","novembro":"11","dezembro":"12",
}

# ── Extração de texto ─────────────────────────────────────────────────────────
def extract_text_digital(pdf_path):
    try:
        import pdfplumber
        text = ""
        with pdfplumber.open(pdf_path) as pdf:
            for page in pdf.pages[:6]:
                t = page.extract_text()
                if t:
                    text += t + "\n"
        return text.strip()
    except Exception:
        return ""

def extract_text_ocr(pdf_path):
    try:
        import fitz
        import pytesseract
        from PIL import Image
        doc = fitz.open(pdf_path)
        text = ""
        for page in list(doc)[:6]:
            mat = fitz.Matrix(2.5, 2.5)
            pix = page.get_pixmap(matrix=mat)
            img = Image.frombytes("RGB", [pix.width, pix.height], pix.samples)
            text += pytesseract.image_to_string(img, lang="por") + "\n"
        return text.strip()
    except Exception:
        return ""

def get_pdf_text(pdf_path):
    text = extract_text_digital(pdf_path)
    if len(text) > 100:
        return text, "digital"
    text = extract_text_ocr(pdf_path)
    return text, "ocr"

# ── Parser de campos ──────────────────────────────────────────────────────────
def parse_fields(text):
    result = {"numero":"","tipo":"","data":"","autoria":"","ementa":""}
    if not text:
        return result
    upper = text.upper()

    # Tipo
    is_decreto = bool(re.search(r"DECRETO\s+LEGISLATIVO\s+N[Oº°\.]", upper))
    is_complementar = bool(re.search(
        r"(PROJETO\s+DE\s+LEI\s+COMPLEMENTAR|LEI\s+COMPLEMENTAR\s+N[Oº°\.]|\bPLC\s+N[Oº°\.])",
        upper,
    ))
    if is_decreto:
        result["tipo"] = "Decreto Legislativo"
    elif is_complementar:
        result["tipo"] = "Complementar"
    else:
        result["tipo"] = "Ordinário"

    # Número
    for pat in [
        r"PROJETO\s+DE\s+LEI(?:\s+COMPLEMENTAR)?\s+[Nº°N\.]+\s*([\d]+[\/\-]?\d*)",
        r"\bPL[C]?\s+[Nº°N\.]+\s*([\d]+[\/\-]?\d*)",
        r"LEI(?:\s+COMPLEMENTAR)?\s+[Nº°N\.]+\s*([\d]+[\/\-]?\d*)\s*,?\s*DE",
    ]:
        m = re.search(pat, upper)
        if m:
            raw = m.group(1).strip().rstrip("/- ")
            prefix = "PLC nº " if is_complementar else ("PDL nº " if is_decreto else "PL nº ")
            result["numero"] = prefix + raw
            break

    # Data — prioridade: título da lei > gabinete > última data
    def parse_date(d, mes, a):
        mes = mes.lower().strip()
        mes_norm = mes.replace("ã","a").replace("ç","c")
        num = MESES.get(mes) or MESES.get(mes_norm) or "00"
        return f"{int(d):02d}/{num}/{a}"

    m = re.search(
        r"(?:PROJETO\s+DE\s+LEI|LEI\s+COMPLEMENTAR|LEI\s+MUNICIPAL|LEI\s+ORDINÁRIA)"
        r"[^\n]{0,40}?[,\s]+DE\s+(\d{1,2})\s+DE\s+([A-ZÇÃa-zçã]+)\s+DE\s+(\d{4})",
        text, re.IGNORECASE,
    )
    if m:
        result["data"] = parse_date(m.group(1), m.group(2), m.group(3))
    else:
        m = re.search(
            r"(?:Gabinete|Palácio|Prefeitura)[^\n]{0,80}?(\d{1,2})\s+de\s+([A-ZÇÃa-zçã]+)\s+de\s+(\d{4})",
            text, re.IGNORECASE,
        )
        if m:
            result["data"] = parse_date(m.group(1), m.group(2), m.group(3))
        else:
            datas = re.findall(r"(\d{1,2})\s+de\s+([A-ZÇÃa-zçã]+)\s+de\s+(\d{4})", text, re.IGNORECASE)
            if datas:
                result["data"] = parse_date(*datas[-1])

    # Ementa
    m = re.search(r'[\u201c"](Disp[õo]e.*?)[\u201d"]', text, re.DOTALL|re.IGNORECASE)
    if not m:
        m = re.search(r'[\u201c"""](.*?)[\u201d"""]', text, re.DOTALL)
    if m:
        em = m.group(1).strip().replace("\n"," ")
        result["ementa"] = re.sub(r"\s{2,}"," ",em)[:500]
    else:
        m = re.search(r"(Disp[õo]e\s+sobre\s+.*?)(?:\n\n|Art\.\s*1)", text, re.DOTALL|re.IGNORECASE)
        if m:
            result["ementa"] = re.sub(r"\s{2,}"," ", m.group(1).strip().replace("\n"," "))[:500]

    # Autoria
    if re.search(r"PODER\s+EXECUTIVO|PREFEITO\s+MUNICIPAL|GABINETE\s+DO\s+PREFEITO", upper):
        result["autoria"] = "Poder Executivo"
    elif re.search(r"CÂMARA|VEREADOR|PODER\s+LEGISLATIVO", upper):
        result["autoria"] = "Poder Legislativo"
    else:
        result["autoria"] = "Poder Executivo"

    return result

# ── ROTAS ─────────────────────────────────────────────────────────────────────

@app.route("/api/extract", methods=["POST"])
def extract():
    if "file" not in request.files:
        return jsonify({"error": "Nenhum arquivo enviado."}), 400
    file = request.files["file"]
    if not file.filename.lower().endswith(".pdf"):
        return jsonify({"error": "O arquivo deve ser um PDF."}), 400
    with tempfile.NamedTemporaryFile(delete=False, suffix=".pdf") as tmp:
        file.save(tmp.name)
        tmp_path = tmp.name
    try:
        text, method = get_pdf_text(tmp_path)
        if not text or len(text) < 30:
            return jsonify({"error": "Não foi possível extrair texto do PDF."}), 422
        data = parse_fields(text)
        data["_method"] = method
        return jsonify({"ok": True, "data": data})
    except Exception as e:
        return jsonify({"error": str(e)}), 500
    finally:
        os.unlink(tmp_path)


@app.route("/api/registros", methods=["GET"])
def get_registros():
    try:
        sb = get_sb()
        res = sb.table("registros").select("*").order("created_at", desc=True).execute()
        return jsonify(res.data)
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/registros", methods=["POST"])
def create_registro():
    rec = request.json
    if not rec:
        return jsonify({"error": "Dados inválidos."}), 400
    try:
        sb = get_sb()
        res = sb.table("registros").insert(rec).execute()
        return jsonify({"ok": True, "record": res.data[0]}), 201
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/registros/<rid>", methods=["PUT"])
def update_registro(rid):
    updates = request.json
    try:
        sb = get_sb()
        sb.table("registros").update(updates).eq("id", rid).execute()
        return jsonify({"ok": True})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/registros/<rid>", methods=["DELETE"])
def delete_registro(rid):
    try:
        sb = get_sb()
        # Apaga documentos associados do storage
        docs = sb.table("documentos").select("storage_path").eq("registro_id", rid).execute()
        for doc in docs.data:
            try:
                sb.storage.from_(STORAGE_BUCKET).remove([doc["storage_path"]])
            except Exception:
                pass
        sb.table("documentos").delete().eq("registro_id", rid).execute()
        sb.table("registros").delete().eq("id", rid).execute()
        return jsonify({"ok": True})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


# ── Documentos ────────────────────────────────────────────────────────────────

@app.route("/api/registros/<rid>/documentos", methods=["GET"])
def get_documentos(rid):
    try:
        sb = get_sb()
        res = sb.table("documentos").select("*").eq("registro_id", rid).order("created_at").execute()
        return jsonify(res.data)
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/registros/<rid>/documentos", methods=["POST"])
def upload_documento(rid):
    if "file" not in request.files:
        return jsonify({"error": "Nenhum arquivo enviado."}), 400
    file = request.files["file"]
    descricao = request.form.get("descricao", file.filename)
    ext = Path(file.filename).suffix.lower()
    storage_path = f"{rid}/{uuid.uuid4()}{ext}"
    try:
        sb = get_sb()
        conteudo = file.read()
        content_type = file.content_type or "application/octet-stream"
        sb.storage.from_(STORAGE_BUCKET).upload(
            storage_path, conteudo,
            file_options={"content-type": content_type}
        )
        url = sb.storage.from_(STORAGE_BUCKET).get_public_url(storage_path)
        doc = {
            "registro_id": rid,
            "nome": file.filename,
            "descricao": descricao,
            "storage_path": storage_path,
            "url": url,
            "tamanho": len(conteudo),
            "tipo": ext.lstrip(".").upper(),
        }
        res = sb.table("documentos").insert(doc).execute()
        return jsonify({"ok": True, "documento": res.data[0]}), 201
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/documentos/<did>", methods=["DELETE"])
def delete_documento(did):
    try:
        sb = get_sb()
        doc = sb.table("documentos").select("storage_path").eq("id", did).execute()
        if doc.data:
            sb.storage.from_(STORAGE_BUCKET).remove([doc.data[0]["storage_path"]])
        sb.table("documentos").delete().eq("id", did).execute()
        return jsonify({"ok": True})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/")
def index():
    return send_from_directory("static", "index.html")


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    print(f"\n{'='*55}")
    print("  Controle de PLs — Prefeitura de Buritirana/MA")
    print(f"  Acesse: http://localhost:{port}")
    print(f"{'='*55}\n")
    app.run(host="0.0.0.0", port=port, debug=False)
