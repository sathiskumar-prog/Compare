import os
import duckdb
import tkinter as tk
from tkinter import filedialog
from flask import Flask, render_template_string, request, jsonify
from datetime import datetime

app = Flask(__name__)

# --- UI (Optimized for Streamed Results) ---
HTML_UI = """
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <title>Clinical SQL Reconciler</title>
    <link href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.0/dist/css/bootstrap.min.css" rel="stylesheet">
    <style>
        body { background-color: #f4f7f6; font-family: 'Segoe UI', sans-serif; }
        .report-view { display: none; background: #1e1e1e; color: #00ff41; padding: 20px; border-radius: 8px; font-family: monospace; white-space: pre-wrap; font-size: 12px; border-left: 5px solid #dc3545; }
        .progress { height: 20px; display: none; margin-bottom: 20px; }
        .stat-card { border-radius: 10px; border: none; box-shadow: 0 2px 10px rgba(0,0,0,0.05); }
    </style>
</head>
<body class="p-4">
    <div class="container bg-white p-5 shadow rounded stat-card">
        <h2 class="text-primary mb-4">⚡ High-Speed SQL Reconciler</h2>
        <div class="row g-3 mb-4 bg-light p-3 rounded border">
            <div class="col-md-5"><label class="fw-bold small">Latest Path</label><input type="text" id="p1" class="form-control"><button class="btn btn-sm btn-link" onclick="pickFolder('p1')">Browse</button></div>
            <div class="col-md-5"><label class="fw-bold small">Previous Path</label><input type="text" id="p2" class="form-control"><button class="btn btn-sm btn-link" onclick="pickFolder('p2')">Browse</button></div>
            <div class="col-md-2 d-flex align-items-end"><button onclick="startBatch()" class="btn btn-danger w-100 fw-bold">RUN RECON</button></div>
        </div>
        <div class="progress" id="progBarCont"><div id="progBar" class="progress-bar progress-bar-striped progress-bar-animated bg-success" style="width: 0%"></div></div>
        <table class="table align-middle"><thead class="table-dark"><tr><th>File</th><th>Status</th><th>Drift</th><th>Action</th></tr></thead><tbody id="resTable"></tbody></table>
    </div>
    <script>
        async function pickFolder(id) { const res = await fetch('/api/browse'); const data = await res.json(); if(data.path) document.getElementById(id).value = data.path; }
        async function startBatch() {
            const p1 = document.getElementById('p1').value; const p2 = document.getElementById('p2').value;
            const table = document.getElementById('resTable'); const prog = document.getElementById('progBar');
            table.innerHTML = ""; document.getElementById('progBarCont').style.display = "block";

            const listRes = await fetch('/api/list_files', { method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify({ p1, p2 }) });
            const files = await listRes.json();

            for(let i=0; i < files.length; i++) {
                const filename = files[i];
                prog.style.width = Math.round(((i + 1) / files.length) * 100) + "%";
                prog.innerText = filename;

                const res = await fetch('/api/compare_sql', { method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify({ p1, p2, filename }) });
                const item = await res.json();

                const sClass = item.status === 'Identical' ? 'text-success' : 'text-danger';
                table.innerHTML += `<tr><td><b>${item.filename}</b></td><td class="${sClass}">${item.status}</td><td>${item.drift}</td><td class="text-end"><button class="btn btn-sm btn-outline-dark" onclick="toggle('${i}')">View Diffs</button></td></tr>
                <tr><td colspan="4"><div id="rep-${i}" class="report-view">${item.details}</div></td></tr>`;
            }
            prog.innerText = "Reconciliation Finished";
        }
        function toggle(id) { const el = document.getElementById('rep-' + id); el.style.display = (el.style.display === 'block') ? 'none' : 'block'; }
    </script>
</body>
</html>
"""

# --- BACKEND (PURE SQL ENGINE) ---

def process_sql_only(p1, p2, filename):
    try:
        path_a = os.path.normpath(os.path.join(p1, filename))
        path_b = os.path.normpath(os.path.join(p2, filename))
        
        # SQL-Only Connection (Does not load into Pandas RAM)
        con = duckdb.connect(database=':memory:')
        
        # Load as string views
        con.execute(f"CREATE VIEW v1 AS SELECT * FROM read_csv_auto('{path_a}', all_varchar=True)")
        con.execute(f"CREATE VIEW v2 AS SELECT * FROM read_csv_auto('{path_b}', all_varchar=True)")
        
        # Column Intersection
        cols1 = [c[0].upper() for c in con.execute("DESCRIBE v1").fetchall()]
        cols2 = [c[0].upper() for c in con.execute("DESCRIBE v2").fetchall()]
        common = sorted(list(set(cols1) & set(cols2)))
        common_sql = ", ".join([f'"{c}"' for c in common])
        
        # Keys
        keys = [k for k in ["STUDYID", "CDH_RECORDID", "USUBJID"] if k in common]
        key_join = " AND ".join([f"a.{k} = b.{k}" for k in keys])
        
        # 1. Check for Row Integrity (Fast EXCEPT)
        diff_count = con.execute(f"SELECT count(*) FROM (SELECT {common_sql} FROM v1 EXCEPT SELECT {common_sql} FROM v2)").fetchone()[0]
        total_rows = con.execute("SELECT count(*) FROM v1").fetchone()[0]

        if diff_count == 0:
            return {"filename": filename, "status": "Identical", "drift": "0%", "details": "No mismatches in common columns."}
        
        # 2. Find specific changed values (Pure SQL logic)
        # We look for rows that exist in both but have different data
        mismatched_values_report = "FILE DISCREPANCY REPORT\\n" + "-"*30 + "\\n"
        
        # Sample the first 10 discrepancies to avoid UI lag
        sql_diff = f"""
            SELECT a.*, 'MISS' as DIFF_STATUS 
            FROM v1 a 
            LEFT JOIN v2 b ON {key_join}
            WHERE b.{keys[0]} IS NULL
            LIMIT 5
        """
        missing_in_target = con.execute(sql_diff).df()
        
        report = f"Mismatched Rows: {diff_count} / {total_rows}\\n"
        if not missing_in_target.empty:
            report += "\\nSAMPLE ROWS IN SOURCE BUT NOT IN TARGET:\\n"
            report += missing_in_target.to_string()
            
        return {
            "filename": filename, 
            "status": "Mismatched", 
            "drift": f"{round((diff_count/total_rows)*100, 2)}%", 
            "details": report
        }
    except Exception as e:
        return {"filename": filename, "status": "Error", "drift": "N/A", "details": str(e)}

@app.route('/')
def index(): return render_template_string(HTML_UI)

@app.route('/api/browse')
def api_browse():
    root = tk.Tk(); root.withdraw(); root.attributes("-topmost", True)
    path = filedialog.askdirectory(); root.destroy()
    return jsonify({"path": path})

@app.route('/api/list_files', methods=['POST'])
def list_files():
    d = request.json
    f1 = {f for f in os.listdir(d['p1']) if f.lower().endswith('.csv')}
    f2 = {f for f in os.listdir(d['p2']) if f.lower().endswith('.csv')}
    return jsonify(sorted(list(f1 & f2)))

@app.route('/api/compare_sql', methods=['POST'])
def compare_sql():
    d = request.json
    return jsonify(process_sql_only(d['p1'], d['p2'], d['filename']))

if __name__ == '__main__':
    app.run(debug=True, threaded=True)