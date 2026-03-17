import os
import duckdb
import pandas as pd
import tkinter as tk
from tkinter import filedialog
from flask import Flask, render_template_string, request, jsonify
from datetime import datetime

app = Flask(__name__)

# --- UI DASHBOARD (Optimized for Large Data) ---
HTML_UI = """
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <title>Clinical Reconciler Pro</title>
    <link href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.0/dist/css/bootstrap.min.css" rel="stylesheet">
    <style>
        body { background-color: #f0f2f5; font-family: 'Segoe UI', sans-serif; padding: 30px; }
        .card { border-radius: 12px; border: none; box-shadow: 0 4px 15px rgba(0,0,0,0.08); margin-bottom: 20px; }
        .report-view { display: none; background: #ffffff; border-top: 1px solid #dee2e6; padding: 20px; font-family: monospace; font-size: 11px; overflow-x: auto; }
        .status-Identical { color: #198754; font-weight: bold; }
        .status-Mismatched { color: #d63384; font-weight: bold; }
        .status-Error { color: #dc3545; font-weight: bold; }
        .progress { height: 30px; border-radius: 15px; display: none; }
        .btn-browse { background: #6c757d; color: white; }
    </style>
</head>
<body>
    <div class="container">
        <div class="card p-4">
            <h3 class="text-primary mb-4">🧬 Clinical CSV Reconciler (SQL Engine)</h3>
            <div class="row g-3 mb-4">
                <div class="col-md-5">
                    <label class="fw-bold small">Source Folder (Latest)</label>
                    <div class="input-group">
                        <input type="text" id="path1" class="form-control" placeholder="Select drive...">
                        <button class="btn btn-browse" onclick="pickFolder('path1')">Browse</button>
                    </div>
                </div>
                <div class="col-md-5">
                    <label class="fw-bold small">Target Folder (Previous)</label>
                    <div class="input-group">
                        <input type="text" id="path2" class="form-control" placeholder="Select drive...">
                        <button class="btn btn-browse" onclick="pickFolder('path2')">Browse</button>
                    </div>
                </div>
                <div class="col-md-2 d-flex align-items-end">
                    <button onclick="startBatch()" class="btn btn-primary w-100 fw-bold">RUN COMPARE</button>
                </div>
            </div>
            <div class="progress" id="progCont">
                <div id="progBar" class="progress-bar progress-bar-striped progress-bar-animated bg-success" style="width: 0%">0%</div>
            </div>
        </div>

        <div id="exportArea" class="alert alert-info d-none justify-content-between align-items-center card p-3">
            <span>Process Complete. Reports ready for export.</span>
            <button class="btn btn-success btn-sm" onclick="exportResults()">📁 Export All Reports</button>
        </div>

        <div id="resTableArea">
            <table class="table table-hover bg-white card shadow-sm">
                <thead class="table-dark">
                    <tr><th>File Name</th><th>Status</th><th>Match Rate</th><th class="text-end pe-4">Action</th></tr>
                </thead>
                <tbody id="resTable"></tbody>
            </table>
        </div>
    </div>

    <script>
        let resultsStore = [];
        let targetDir = "";

        async function pickFolder(id) {
            const res = await fetch('/api/browse');
            const data = await res.json();
            if(data.path) document.getElementById(id).value = data.path;
        }

        async function startBatch() {
            const p1 = document.getElementById('path1').value;
            const p2 = document.getElementById('path2').value;
            targetDir = p2;
            const table = document.getElementById('resTable');
            const prog = document.getElementById('progBar');
            const progCont = document.getElementById('progCont');

            if(!p1 || !p2) return alert("Select both folders.");
            
            table.innerHTML = "";
            resultsStore = [];
            progCont.style.display = "flex";

            // Get List of matching files
            const listRes = await fetch('/api/list_files', {
                method: 'POST',
                headers: {'Content-Type': 'application/json'},
                body: JSON.stringify({ p1, p2 })
            });
            const files = await listRes.json();

            // Process One-by-One to prevent hanging
            for(let i=0; i < files.length; i++) {
                const filename = files[i];
                const pct = Math.round(((i + 1) / files.length) * 100);
                prog.style.width = pct + "%";
                prog.innerText = `Processing ${filename}...`;

                const res = await fetch('/api/compare_single', {
                    method: 'POST',
                    headers: {'Content-Type': 'application/json'},
                    body: JSON.stringify({ p1, p2, filename })
                });
                const item = await res.json();
                resultsStore.push(item);

                const sClass = `status-${item.status}`;
                table.innerHTML += `
                    <tr class="align-middle">
                        <td class="ps-3"><b>${item.filename}</b></td>
                        <td class="${sClass}">${item.status}</td>
                        <td><span class="badge bg-light text-dark border">${item.match_rate}</span></td>
                        <td class="text-end pe-3"><button class="btn btn-sm btn-outline-dark" onclick="toggle('${i}')">View Sample</button></td>
                    </tr>
                    <tr><td colspan="4" class="p-0 border-0"><div id="rep-${i}" class="report-view">${item.details}</div></td></tr>`;
            }
            prog.innerText = "Complete!";
            document.getElementById('exportArea').classList.replace('d-none', 'd-flex');
        }

        function toggle(id) {
            const el = document.getElementById('rep-' + id);
            el.style.display = (el.style.display === 'block') ? 'none' : 'block';
        }

        async function exportResults() {
            const res = await fetch('/api/export', {
                method: 'POST',
                headers: {'Content-Type': 'application/json'},
                body: JSON.stringify({ results: resultsStore, target: targetDir })
            });
            const d = await res.json();
            alert(d.message);
        }
    </script>
</body>
</html>
"""

# --- BACKEND LOGIC (High Performance SQL Engine) ---

def fast_sql_reconcile(p1, p2, filename):
    try:
        path_a = os.path.normpath(os.path.join(p1, filename))
        path_b = os.path.normpath(os.path.join(p2, filename))
        
        # Connect to DuckDB (Handles data larger than RAM)
        con = duckdb.connect(database=':memory:')
        
        # Load CSVs as string-only views (Zero conversion overhead)
        con.execute(f"CREATE VIEW v1 AS SELECT * FROM read_csv_auto('{path_a}', all_varchar=True)")
        con.execute(f"CREATE VIEW v2 AS SELECT * FROM read_csv_auto('{path_b}', all_varchar=True)")
        
        # Determine Keys and Schema
        cols1 = [c[0].upper() for c in con.execute("DESCRIBE v1").fetchall()]
        cols2 = [c[0].upper() for c in con.execute("DESCRIBE v2").fetchall()]
        common = sorted(list(set(cols1) & set(cols2)))
        common_sql = ", ".join([f'"{c}"' for c in common])
        
        keys = [k for k in ["STUDYID", "CDH_RECORDID", "USUBJID"] if k in common]
        
        if len(keys) < 2:
            return {"filename": filename, "status": "Error", "match_rate": "0%", "details": "Mandatory keys STUDYID/CDH_RECORDID not found."}

        # 1. Row Difference (Fast EXCEPT)
        diff_count = con.execute(f"SELECT count(*) FROM (SELECT {common_sql} FROM v1 EXCEPT SELECT {common_sql} FROM v2)").fetchone()[0]
        total_rows = con.execute("SELECT count(*) FROM v1").fetchone()[0]

        if diff_count == 0 and total_rows == con.execute("SELECT count(*) FROM v2").fetchone()[0]:
            return {"filename": filename, "status": "Identical", "match_rate": "100%", "details": "All shared records match exactly."}
        
        # 2. Get Discrepancy Sample
        # We only fetch mismatched rows to Python to save RAM
        diff_df = con.execute(f"(SELECT {common_sql}, 'SOURCE' as ORIGIN FROM v1 EXCEPT SELECT {common_sql}, 'SOURCE' as ORIGIN FROM v2) LIMIT 20").df()
        
        match_rate = f"{round(((total_rows - diff_count)/max(total_rows, 1))*100, 2)}%"
        
        report = f"RECONCILIATION SUMMARY\\n" + "="*40
        report += f"\\nTotal Records: {total_rows}\\nMismatched Records: {diff_count}\\nMatch Rate: {match_rate}"
        report += f"\\n\\nSAMPLE DISCREPANCIES (TOP 20):\\n{diff_df.to_string(index=False)}"
            
        return {"filename": filename, "status": "Mismatched", "match_rate": match_rate, "details": report}
    except Exception as e:
        return {"filename": filename, "status": "Error", "match_rate": "N/A", "details": str(e)}

# --- FLASK HANDLERS ---

@app.route('/')
def index(): return render_template_string(HTML_UI)

@app.route('/api/browse')
def browse():
    root = tk.Tk(); root.withdraw(); root.attributes("-topmost", True)
    path = filedialog.askdirectory(); root.destroy()
    return jsonify({"path": path})

@app.route('/api/list_files', methods=['POST'])
def list_files():
    d = request.json
    f1 = {f for f in os.listdir(d['p1']) if f.lower().endswith('.csv')}
    f2 = {f for f in os.listdir(d['p2']) if f.lower().endswith('.csv')}
    return jsonify(sorted(list(f1 & f2)))

@app.route('/api/compare_single', methods=['POST'])
def compare_single():
    d = request.json
    return jsonify(fast_sql_reconcile(d['p1'], d['p2'], d['filename']))

@app.route('/api/export', methods=['POST'])
def export():
    d = request.json
    ts = datetime.now().strftime('%Y%m%d_%H%M%S')
    folder = os.path.join(d['target'], f"Recon_Reports_{ts}")
    os.makedirs(folder, exist_ok=True)
    for item in d['results']:
        with open(os.path.join(folder, f"Report_{item['filename']}.txt"), 'w', encoding='utf-8') as f:
            f.write(item['details'].replace('\\n', '\n'))
    return jsonify({"message": f"Reports exported to:\\n{folder}"})

if __name__ == '__main__':
    # Usage: pip install duckdb pandas flask
    app.run(debug=True, threaded=True)