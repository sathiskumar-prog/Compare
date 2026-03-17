import os
import duckdb
import pandas as pd
import datacompy
import tkinter as tk
from tkinter import filedialog
from flask import Flask, render_template_string, request, jsonify
from datetime import datetime

app = Flask(__name__)

# --- UI VARIABLE (Same as before) ---
HTML_UI = """
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <title>Clinical Data Validator - DuckDB Engine</title>
    <link href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.0/dist/css/bootstrap.min.css" rel="stylesheet">
    <style>
        body { background-color: #f1f3f5; font-family: 'Inter', sans-serif; }
        .main-card { margin-top: 40px; border-radius: 15px; box-shadow: 0 10px 30px rgba(0,0,0,0.1); }
        .report-view { display: none; background: #1e1e1e; color: #dcdcdc; padding: 20px; border-radius: 8px; font-family: 'Consolas', monospace; font-size: 13px; white-space: pre-wrap; border-left: 5px solid #0d6efd; margin-top: 10px; }
        .status-Identical { color: #198754; font-weight: bold; }
        .status-Mismatched { color: #fd7e14; font-weight: bold; }
    </style>
</head>
<body class="p-4">
    <div class="container main-card bg-white p-5">
        <h2 class="text-primary mb-4">⚡ Clinical Reconciler <small class="text-muted" style="font-size: 0.5em;">DuckDB SQL Engine</small></h2>
        <div class="row g-3 p-4 bg-light rounded-4 border mb-4">
            <div class="col-md-5">
                <label class="fw-bold">Source Folder</label>
                <div class="input-group"><input type="text" id="path1" class="form-control"><button class="btn btn-secondary" onclick="pickFolder('path1')">Browse</button></div>
            </div>
            <div class="col-md-5">
                <label class="fw-bold">Target Folder</label>
                <div class="input-group"><input type="text" id="path2" class="form-control"><button class="btn btn-secondary" onclick="pickFolder('path2')">Browse</button></div>
            </div>
            <div class="col-md-2 d-flex align-items-end"><button onclick="runReconciliation()" class="btn btn-primary w-100 fw-bold">RUN FAST</button></div>
        </div>
        <div id="loader" class="text-center d-none py-4"><div class="spinner-border text-primary" role="status"></div><p class="mt-2 text-muted">DuckDB is executing SQL join...</p></div>
        <div id="exportArea" class="alert alert-info d-none justify-content-between align-items-center"><span>Process Complete</span><button class="btn btn-success btn-sm" onclick="exportReports()">📁 Export Reports</button></div>
        <table class="table mt-3"><tbody id="resTable"></tbody></table>
    </div>
    <script>
        let currentResults = []; let targetPath = "";
        async function pickFolder(id) { const res = await fetch('/api/browse'); const data = await res.json(); if(data.path) document.getElementById(id).value = data.path; }
        async function runReconciliation() {
            const p1 = document.getElementById('path1').value; const p2 = document.getElementById('path2').value; targetPath = p2;
            const table = document.getElementById('resTable'); const loader = document.getElementById('loader');
            if(!p1 || !p2) return alert("Select paths");
            table.innerHTML = ""; loader.classList.remove('d-none');
            const response = await fetch('/api/compare', { method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify({ p1, p2 }) });
            currentResults = await response.json(); loader.classList.add('d-none'); document.getElementById('exportArea').classList.replace('d-none', 'd-flex');
            currentResults.forEach((item, idx) => {
                const statusClass = item.status === 'Identical' ? 'text-success' : 'text-warning';
                table.innerHTML += `<tr><td class="fw-medium">${item.filename}</td><td class="${statusClass}">${item.status}</td><td>${item.match_rate}</td><td class="text-end"><button class="btn btn-sm btn-outline-dark" onclick="toggle('${idx}')">Report</button></td></tr>
                <tr><td colspan="4" class="p-0 border-0"><div id="rep-${idx}" class="report-view">${item.details}</div></td></tr>`;
            });
        }
        function toggle(id) { const el = document.getElementById('rep-' + id); el.style.display = (el.style.display === 'block') ? 'none' : 'block'; }
        async function exportReports() { const res = await fetch('/api/export', { method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify({ results: currentResults, target: targetPath }) }); const d = await res.json(); alert(d.message); }
    </script>
</body>
</html>
"""

def fast_sql_compare(path_a, path_b):
    """Uses DuckDB SQL to find mismatches in seconds, then DataCompy for reporting."""
    con = duckdb.connect(database=':memory:')
    
    # 1. Load CSVs as strings into DuckDB (Fastest possible load)
    con.execute(f"CREATE VIEW v1 AS SELECT * FROM read_csv_auto('{path_a}', all_varchar=True)")
    con.execute(f"CREATE VIEW v2 AS SELECT * FROM read_csv_auto('{path_b}', all_varchar=True)")
    
    # Normalize headers
    cols = [c[0].upper() for c in con.execute("DESCRIBE v1").fetchall()]
    keys = [k for k in ["STUDYID", "CDH_RECORDID", "USUBJID"] if k in cols]
    
    # 2. Find Rows with any difference using SQL EXCEPT
    # This identifies exactly which rows are dirty without looping in Python
    mismatched_rows_query = f"SELECT * FROM v1 EXCEPT SELECT * FROM v2"
    diff_df = con.execute(mismatched_rows_query).df()
    
    if diff_df.empty and con.execute("SELECT count(*) FROM v1").fetchone()[0] == con.execute("SELECT count(*) FROM v2").fetchone()[0]:
        return "Identical", "100%", "No differences found."

    # 3. Only if mismatches exist, use DataCompy for a detailed report
    # We load the data for DataCompy only for the final summary
    df1 = con.execute("SELECT * FROM v1").df()
    df2 = con.execute("SELECT * FROM v2").df()
    
    # Normalize values for DataCompy
    for df in [df1, df2]:
        df.columns = [c.upper() for c in df.columns]
        for col in df.columns:
            df[col] = df[col].astype(str).str.strip().str.lower()

    comparison = datacompy.Compare(df1, df2, join_columns=keys)
    
    match_rate = f"{round((1 - (len(diff_df)/len(df1)))*100, 2)}%"
    return "Mismatched", match_rate, comparison.report()

def run_reconciliation(p1, p2):
    files = sorted(list(set(os.listdir(p1)) & set(os.listdir(p2))))
    results = []
    for f in files:
        if f.lower().endswith('.csv'):
            try:
                status, rate, report = fast_sql_compare(os.path.join(p1, f), os.path.join(p2, f))
                results.append({"filename": f, "status": status, "match_rate": rate, "details": report})
            except Exception as e:
                results.append({"filename": f, "status": "Error", "match_rate": "N/A", "details": str(e)})
    return results

# --- FLASK ROUTES --- (Same as previous, using DuckDB logic)
@app.route('/')
def index(): return render_template_string(HTML_UI)

@app.route('/api/browse')
def api_browse():
    root = tk.Tk(); root.withdraw(); root.attributes("-topmost", True)
    path = filedialog.askdirectory(); root.destroy()
    return jsonify({"path": path})

@app.route('/api/compare', methods=['POST'])
def api_compare():
    d = request.json
    return jsonify(run_reconciliation(d['p1'], d['p2']))

@app.route('/api/export', methods=['POST'])
def api_export():
    d = request.json
    export_path = os.path.join(d['target'], f"Reports_{datetime.now().strftime('%Y%m%d_%H%M%S')}")
    os.makedirs(export_path, exist_ok=True)
    for item in d['results']:
        with open(os.path.join(export_path, f"{item['filename']}.txt"), 'w', encoding='utf-8') as f:
            f.write(item['details'])
    return jsonify({"message": f"Exported to {export_path}"})

if __name__ == '__main__':
    # You may need: pip install duckdb flask pandas datacompy
    app.run(debug=True)