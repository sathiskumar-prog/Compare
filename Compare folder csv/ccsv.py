import os
import hashlib
import pandas as pd
import datacompy
from flask import Flask, render_template_string, request, jsonify

app = Flask(__name__)

# --- Logic: The Comparator Engine ---
def get_file_hash(filepath):
    hasher = hashlib.md5()
    with open(filepath, 'rb') as f:
        while chunk := f.read(8192):
            hasher.update(chunk)
    return hasher.hexdigest()

def compare_logic(p1, p2, join_col):
    files1 = {f for f in os.listdir(p1) if f.lower().endswith('.csv')}
    files2 = {f for f in os.listdir(p2) if f.lower().endswith('.csv')}
    common = sorted(list(files1.intersection(files2)))

    results = []
    for filename in common:
        path_a = os.path.join(p1, filename)
        path_b = os.path.join(p2, filename)
        
        # Level 1: Quick Hash Match
        h1, h2 = get_file_hash(path_a), get_file_hash(path_b)
        if h1 == h2:
            results.append({
                "filename": filename,
                "status": "Identical",
                "match_rate": "100%",
                "details": "Binary MD5 match. No data drift detected."
            })
            continue

        # Level 2: DataCompy Deep Dive
        try:
            df1, df2 = pd.read_csv(path_a), pd.read_csv(path_b)
            comparison = datacompy.Compare(df1, df2, join_columns=[join_col])
            
            # Calculate a simple match percentage
            match_pct = (comparison.intersect_rows.shape[0] - len(comparison.intersect_columns_unequal)) / max(comparison.intersect_rows.shape[0], 1) * 100
            
            results.append({
                "filename": filename,
                "status": "Mismatched" if len(comparison.intersect_columns_unequal) > 0 else "Structural Diff",
                "match_rate": f"{max(0, round(match_pct, 2))}%",
                "details": comparison.report()
            })
        except Exception as e:
            results.append({"filename": filename, "status": "Error", "match_rate": "N/A", "details": str(e)})
            
    return results

# --- UI: The Web Dashboard ---
HTML_TEMPLATE = """
<!DOCTYPE html>
<html>
<head>
    <title>CSV Compare Web</title>
    <link href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.0/dist/css/bootstrap.min.css" rel="stylesheet">
    <style>
        .report-box { display: none; background: #212529; color: #39FF14; padding: 15px; border-radius: 5px; font-family: monospace; font-size: 12px; white-space: pre-wrap; margin-top: 10px; }
        .status-Identical { color: green; font-weight: bold; }
        .status-Mismatched { color: orange; font-weight: bold; }
    </style>
</head>
<body class="bg-light p-5">
    <div class="container bg-white p-4 shadow rounded">
        <h2 class="mb-4">📂 Bulk CSV Comparator</h2>
        <div class="row g-3 mb-4">
            <div class="col-md-5"><input type="text" id="p1" class="form-control" placeholder="Folder A Path"></div>
            <div class="col-md-5"><input type="text" id="p2" class="form-control" placeholder="Folder B Path"></div>
            <div class="col-md-2"><input type="text" id="jc" class="form-control" placeholder="Join Col" value="id"></div>
            <div class="col-12"><button onclick="runCompare()" class="btn btn-primary w-100">Compare Folders</button></div>
        </div>

        <table class="table table-hover">
            <thead class="table-dark">
                <tr><th>File Name</th><th>Status</th><th>Match Rate</th><th>Action</th></tr>
            </thead>
            <tbody id="resTable"></tbody>
        </table>
    </div>

    <script>
        async function runCompare() {
            const table = document.getElementById('resTable');
            table.innerHTML = "<tr><td colspan='4' class='text-center'>Processing...</td></tr>";
            
            const res = await fetch('/api/compare', {
                method: 'POST',
                headers: {'Content-Type': 'application/json'},
                body: JSON.stringify({p1: document.getElementById('p1').value, p2: document.getElementById('p2').value, jc: document.getElementById('jc').value})
            });
            const data = await res.json();
            table.innerHTML = "";

            data.forEach((item, idx) => {
                table.innerHTML += `
                    <tr>
                        <td>${item.filename}</td>
                        <td class="status-${item.status}">${item.status}</td>
                        <td>${item.match_rate}</td>
                        <td><button class="btn btn-sm btn-outline-secondary" onclick="toggle('${idx}')">View Report</button></td>
                    </tr>
                    <tr id="report-${idx}" class="report-box-row"><td colspan="4"><div id="box-${idx}" class="report-box">${item.details}</div></td></tr>
                `;
            });
        }
        function toggle(id) {
            const el = document.getElementById('box-' + id);
            el.style.display = el.style.display === 'block' ? 'none' : 'block';
        }
    </script>
</body>
</html>
"""

@app.route('/')
def index(): return render_template_string(HTML_TEMPLATE)

@app.route('/api/compare', methods=['POST'])
def api():
    d = request.json
    return jsonify(compare_logic(d['p1'], d['p2'], d['jc']))

if __name__ == '__main__':
    app.run(debug=True, port=5000)