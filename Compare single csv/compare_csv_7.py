import os
import io
import pandas as pd
from flask import Flask, request, render_template_string, send_file, jsonify

app = Flask(__name__)

# Session storage (Stored in memory; clears on Render restart)
storage = {
    "df1": None, "df2": None, 
    "removed": None, "added": None, "mismatches": None, 
    "names": ["", ""], "orig_cols": []
}

HTML_TEMPLATE = """
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Delta Engine | Amber Highlight</title>
    <script src="https://unpkg.com/lucide@latest"></script>
    <style>
        :root { 
            --primary: #4f46e5; --bg: #f8fafc; --card: #ffffff; 
            --text: #1e293b; --danger: #ef4444; --success: #10b981; 
            --amber: #f59e0b; /* Professional Amber */
        }
        body { font-family: system-ui, -apple-system, sans-serif; background: var(--bg); color: var(--text); padding: 20px; }
        .container { max-width: 1100px; margin: 2rem auto; }
        .card { background: white; padding: 2rem; border-radius: 16px; box-shadow: 0 4px 6px -1px rgba(0,0,0,0.1); border: 1px solid #e2e8f0; margin-bottom: 2rem; }
        .hidden { display: none; }
        
        /* File Grid */
        .file-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 20px; margin-bottom: 20px; }
        .drop-zone { border: 2px dashed #cbd5e1; padding: 30px; text-align: center; border-radius: 12px; background: #fafafa; cursor: pointer; position: relative; }
        .drop-zone input { position: absolute; inset: 0; opacity: 0; cursor: pointer; }
        
        /* Buttons */
        button { background: var(--primary); color: white; border: none; padding: 14px; border-radius: 10px; font-weight: 700; cursor: pointer; width: 100%; transition: 0.2s; }
        button:hover { filter: brightness(1.1); }
        .btn-xlsx { background: #10b981; color: white; padding: 6px 12px; font-size: 0.75rem; border-radius: 6px; text-decoration: none; display: inline-block; font-weight: 600; }

        /* Results */
        .table-wrap { overflow-x: auto; max-height: 450px; border: 1px solid #e2e8f0; border-radius: 12px; margin-top: 12px; }
        table { width: 100%; border-collapse: collapse; font-size: 0.85rem; }
        th { background: #f8fafc; padding: 12px; text-align: left; position: sticky; top: 0; border-bottom: 2px solid #e2e8f0; color: #64748b; }
        td { padding: 10px 12px; border-bottom: 1px solid #f1f5f9; white-space: nowrap; }
        
        /* THE AMBER HIGHLIGHT */
        .mismatch-highlight { 
            background: #fffbeb; /* Light amber bg */
            color: #b45309; /* Dark amber text */
            padding: 4px 8px; 
            border-radius: 6px; 
            font-weight: 700; 
            border: 1px solid #fde68a;
            display: inline-block;
        }
    </style>
</head>
<body>
    <div class="container">
        <h1 style="text-align:center; font-weight:900; letter-spacing:-0.05em; color:#111827;">Delta Engine Pro</h1>
        
        <div class="card">
            <form method="POST" enctype="multipart/form-data">
                {% if not cols %}
                <div class="file-grid">
                    <div class="drop-zone">
                        <strong>Base File (A)</strong><br><span id="n1" style="color:var(--primary); font-size:0.8rem">Upload CSV</span>
                        <input type="file" name="file1" accept=".csv" required onchange="document.getElementById('n1').innerText=this.files[0].name">
                    </div>
                    <div class="drop-zone">
                        <strong>New File (B)</strong><br><span id="n2" style="color:var(--primary); font-size:0.8rem">Upload CSV</span>
                        <input type="file" name="file2" accept=".csv" required onchange="document.getElementById('n2').innerText=this.files[0].name">
                    </div>
                </div>
                <button type="submit" name="action" value="upload">Analyze Columns</button>
                {% else %}
                <div style="margin-bottom:1rem"><strong>Select Anchor Keys:</strong></div>
                <div style="display:grid; grid-template-columns:repeat(auto-fill, minmax(180px, 1fr)); gap:10px; padding:15px; background:#f1f5f9; border-radius:12px; margin-bottom:20px">
                    {% for col in cols %}
                    <label style="background:white; padding:8px; border-radius:8px; border:1px solid #ddd; font-size:0.85rem; cursor:pointer; display:flex; align-items:center; gap:8px;">
                        <input type="checkbox" name="keys" value="{{ col }}" checked> {{ col }}
                    </label>
                    {% endfor %}
                </div>
                <button type="submit" name="action" value="compare">Run Deep Comparison</button>
                <a href="/" style="display:block; text-align:center; margin-top:15px; text-decoration:none; color:var(--primary); font-size:0.85rem">← Upload New Files</a>
                {% endif %}
            </form>
        </div>

        {% if results %}
        <div class="card">
            <div style="display:flex; justify-content:space-between; align-items:center">
                <h3 style="color:var(--danger); margin:0;">🔴 Removed Rows</h3>
                <a href="/export/removed" class="btn-xlsx">Export XLSX</a>
            </div>
            <div class="table-wrap">{{ results.del_h|safe }}</div>

            <div style="display:flex; justify-content:space-between; align-items:center; margin-top:40px">
                <h3 style="color:var(--success); margin:0;">🟢 Added Rows</h3>
                <a href="/export/added" class="btn-xlsx">Export XLSX</a>
            </div>
            <div class="table-wrap">{{ results.add_h|safe }}</div>

            <div style="display:flex; justify-content:space-between; align-items:center; margin-top:40px">
                <h3 style="color:var(--amber); margin:0;">🟡 Value Mismatches</h3>
                <a href="/export/mismatches" class="btn-xlsx">Export XLSX</a>
            </div>
            <div class="table-wrap">{{ results.mis_h|safe }}</div>
        </div>
        {% endif %}
    </div>
</body>
</html>
"""

def get_safe_df(df, target_cols):
    """Ensures we only select columns that actually exist to avoid KeyErrors."""
    existing = [c for c in target_cols if c in df.columns]
    return df[existing]

@app.route('/', methods=['GET', 'POST'])
def index():
    cols, results = None, None
    if request.method == 'POST':
        action = request.form.get('action')
        
        if action == 'upload':
            f1, f2 = request.files['file1'], request.files['file2']
            df1 = pd.read_csv(f1).fillna('').astype(str).apply(lambda x: x.str.strip())
            df2 = pd.read_csv(f2).fillna('').astype(str).apply(lambda x: x.str.strip())
            storage.update({"df1": df1, "df2": df2, "orig_cols": list(df1.columns)})
            cols = [c for c in df1.columns if c in df2.columns]
            
        elif action == 'compare':
            keys = request.form.getlist('keys')
            df1, df2, orig_cols = storage['df1'], storage['df2'], storage['orig_cols']
            
            merged = df1.merge(df2, on=keys, how='outer', indicator=True, suffixes=('_old', '_new'))
            
            # 1. Removed (Retain File A order)
            res_del = get_safe_df(merged[merged['_merge'] == 'left_only'], orig_cols)
            
            # 2. Added (Retain File B order)
            res_add = merged[merged['_merge'] == 'right_only'].rename(columns={c+'_new': c for c in df2.columns if c not in keys})
            res_add = get_safe_df(res_add, list(df2.columns))
            
            # 3. Mismatches Logic
            both = merged[merged['_merge'] == 'both']
            others = [c for c in orig_cols if c not in keys]
            mis_ui, mis_raw = [], []
            
            for _, r in both.iterrows():
                row_ui, row_raw, diff = {}, {}, False
                for c in others:
                    v1, v2 = r.get(c+'_old', ''), r.get(c+'_new', '')
                    if v1 != v2:
                        # UI Highlight in Amber
                        row_ui[c] = f'<span class="mismatch-highlight">{v1} → {v2}</span>'
                        # Excel friendly Side-by-Side
                        row_raw[c] = f"{v1} >> {v2}"
                        diff = True
                    else: 
                        row_ui[c] = row_raw[c] = v1
                if diff:
                    for k in keys: row_ui[k] = row_raw[k] = r[k]
                    mis_ui.append(row_ui); mis_raw.append(row_raw)
            
            res_mis_raw = pd.DataFrame(mis_raw)
            if not res_mis_raw.empty: res_mis_raw = get_safe_df(res_mis_raw, orig_cols)
            
            storage.update({"removed": res_del, "added": res_add, "mismatches": res_mis_raw})
            results = {
                "del_h": res_del.to_html(index=False) if not res_del.empty else "No records.",
                "add_h": res_add.to_html(index=False) if not res_add.empty else "No records.",
                "mis_h": pd.DataFrame(mis_ui).to_html(index=False, escape=False) if mis_ui else "No mismatches found."
            }
            
    return render_template_string(HTML_TEMPLATE, cols=cols, results=results)

@app.route('/export/<type>')
def export(type):
    df = storage.get(type if type != "mismatches" else "mismatches")
    if df is None or (isinstance(df, pd.DataFrame) and df.empty): return "No data", 404
    
    output = io.BytesIO()
    with pd.ExcelWriter(output, engine='openpyxl') as writer:
        df.to_excel(writer, index=False, sheet_name='Comparison Results')
    output.seek(0)
    return send_file(output, as_attachment=True, download_name=f"delta_{type}.xlsx")

if __name__ == '__main__':
    port = int(os.environ.get("PORT", 5000))
    app.run(host='0.0.0.0', port=port)