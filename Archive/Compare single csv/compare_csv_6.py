from flask import Flask, request, render_template_string, send_file
import pandas as pd
import io

app = Flask(__name__)

# In-memory storage for the dataframes and results
storage = {"df1": None, "df2": None, "f1_only": None, "f2_only": None, "names": ["", ""]}

HTML_TEMPLATE = """
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Delta CSV | Modern</title>
    <script src="https://unpkg.com/lucide@latest"></script>
    <style>
        :root { --primary: #4f46e5; --bg: #f8fafc; --card: #ffffff; --text: #1e293b; --danger: #ef4444; --success: #10b981; }
        body { font-family: 'Inter', sans-serif; background: var(--bg); color: var(--text); margin: 0; padding: 20px; }
        .container { max-width: 1000px; margin: 40px auto; }
        .header { text-align: center; margin-bottom: 30px; }
        .card { background: var(--card); padding: 24px; border-radius: 16px; box-shadow: 0 4px 6px -1px rgba(0,0,0,0.1); margin-bottom: 24px; }
        
        .file-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 20px; margin-bottom: 20px; }
        .drop-zone { 
            border: 2px dashed #e2e8f0; border-radius: 12px; padding: 25px; 
            text-align: center; position: relative; transition: all 0.2s; background: #fafafa;
        }
        .drop-zone:hover { border-color: var(--primary); background: #f5f3ff; }
        .drop-zone input { position: absolute; inset: 0; opacity: 0; cursor: pointer; }
        .file-name { display: block; margin-top: 8px; font-size: 0.85rem; color: var(--primary); font-weight: 600; }
        
        .key-selector { display: flex; flex-wrap: wrap; gap: 10px; margin: 15px 0; padding: 15px; background: #f1f5f9; border-radius: 8px; }
        .key-item { display: flex; align-items: center; gap: 8px; background: white; padding: 6px 12px; border-radius: 6px; border: 1px solid #cbd5e1; font-size: 0.85rem; cursor: pointer; }
        
        button { background: var(--primary); color: white; border: none; padding: 14px; border-radius: 10px; font-weight: 600; cursor: pointer; width: 100%; transition: opacity 0.2s; }
        button:hover { opacity: 0.9; }
        .btn-outline { background: transparent; border: 1px solid #cbd5e1; color: #64748b; margin-bottom: 10px; width: auto; padding: 6px 12px; font-size: 0.8rem; }
        .btn-outline:hover { background: #f8fafc; border-color: var(--primary); color: var(--primary); }
        
        .result-card { background: white; border-radius: 12px; border: 1px solid #e2e8f0; overflow: hidden; margin-bottom: 24px; }
        .result-header { padding: 12px 20px; display: flex; justify-content: space-between; align-items: center; border-bottom: 1px solid #e2e8f0; background: #f8fafc; }
        .table-container { overflow-x: auto; max-height: 400px; }
        table { width: 100%; border-collapse: collapse; font-size: 0.85rem; }
        th, td { padding: 12px 20px; border-top: 1px solid #f1f5f9; white-space: nowrap; text-align: left; }
        th { background: #f8fafc; color: #64748b; position: sticky; top: 0; }
        .badge { padding: 4px 10px; border-radius: 20px; font-size: 0.75rem; font-weight: 700; }
    </style>
</head>
<body>
    <div class="container">
        <div class="header">
            <h1>CSV Delta Engine</h1>
            <p>Compare specific variables between two versions.</p>
        </div>

        <div class="card">
            <form method="POST" enctype="multipart/form-data">
                {% if not cols %}
                <div class="file-grid">
                    <div class="drop-zone" id="dz1">
                        <i data-lucide="upload-cloud" style="margin-bottom:8px; color:#94a3b8"></i><br>
                        <strong>Base File (A)</strong>
                        <span class="file-name" id="name1">No file selected</span>
                        <input type="file" name="file1" accept=".csv" required onchange="updateName(this, 'name1')">
                    </div>
                    <div class="drop-zone" id="dz2">
                        <i data-lucide="upload-cloud" style="margin-bottom:8px; color:#94a3b8"></i><br>
                        <strong>New File (B)</strong>
                        <span class="file-name" id="name2">No file selected</span>
                        <input type="file" name="file2" accept=".csv" required onchange="updateName(this, 'name2')">
                    </div>
                </div>
                <button type="submit" name="action" value="upload">Analyze Structure</button>
                {% else %}
                <div style="margin-bottom: 10px; font-size: 0.9rem;">
                    Comparing: <code style="color:var(--primary)">{{ filenames[0] }}</code> vs <code style="color:var(--primary)">{{ filenames[1] }}</code>
                </div>
                <div style="margin-bottom: 15px;">
                    <strong>Select Key Variables:</strong>
                    <div style="margin-top: 10px; display:flex; gap:8px;">
                        <button type="button" class="btn-outline" onclick="toggleAll(true)">Select All</button>
                        <button type="button" class="btn-outline" onclick="toggleAll(false)">Deselect All</button>
                    </div>
                </div>
                <div class="key-selector" id="key-box">
                    {% for col in cols %}
                    <label class="key-item">
                        <input type="checkbox" name="keys" value="{{ col }}" checked> {{ col }}
                    </label>
                    {% endfor %}
                </div>
                <button type="submit" name="action" value="compare">Find Differences</button>
                <a href="/" style="display:block; text-align:center; margin-top:15px; font-size:0.8rem; color:#64748b; text-decoration:none;">← Upload New Files</a>
                {% endif %}
            </form>
        </div>

        {% if results %}
            <div class="result-card">
                <div class="result-header">
                    <span class="badge" style="background:#fee2e2; color:#ef4444;">Removed from {{ filenames[0] }}</span>
                    <a href="/export/deleted" style="color:var(--primary); text-decoration:none; font-size:0.85rem; font-weight:600;">Download .csv</a>
                </div>
                <div class="table-container">{{ results.f1_only_html|safe }}</div>
            </div>
            <div class="result-card">
                <div class="result-header">
                    <span class="badge" style="background:#dcfce7; color:#10b981;">Added in {{ filenames[1] }}</span>
                    <a href="/export/added" style="color:var(--primary); text-decoration:none; font-size:0.85rem; font-weight:600;">Download .csv</a>
                </div>
                <div class="table-container">{{ results.f2_only_html|safe }}</div>
            </div>
        {% endif %}
    </div>

    <script>
        lucide.createIcons();
        function updateName(input, targetId) {
            const fileName = input.files[0] ? input.files[0].name : "No file selected";
            document.getElementById(targetId).textContent = fileName;
        }
        function toggleAll(checked) {
            document.querySelectorAll('#key-box input[type="checkbox"]').forEach(cb => cb.checked = checked);
        }
    </script>
</body>
</html>
"""

def clean_df(df):
    return df.dropna(how='all').fillna('').astype(str).apply(lambda x: x.str.strip())

@app.route('/', methods=['GET', 'POST'])
def index():
    cols = None
    results = None
    
    if request.method == 'POST':
        action = request.form.get('action')
        
        if action == 'upload':
            f1, f2 = request.files['file1'], request.files['file2']
            if f1 and f2:
                storage['names'] = [f1.filename, f2.filename]
                storage['df1'] = clean_df(pd.read_csv(io.StringIO(f1.stream.read().decode("UTF8"))))
                storage['df2'] = clean_df(pd.read_csv(io.StringIO(f2.stream.read().decode("UTF8"))))
                cols = list(set(storage['df1'].columns) & set(storage['df2'].columns))
        
        elif action == 'compare':
            selected_keys = request.form.getlist('keys')
            df1, df2 = storage['df1'], storage['df2']
            
            if not selected_keys:
                selected_keys = list(df1.columns)

            merged = df1.merge(df2, on=selected_keys, how='outer', indicator=True, suffixes=('', '_new'))
            f1_only = merged[merged['_merge'] == 'left_only'].drop(columns=['_merge'])
            f2_only = merged[merged['_merge'] == 'right_only'].drop(columns=['_merge'])

            storage['f1_only'], storage['f2_only'] = f1_only, f2_only
            
            results = {
                'f1_only_html': f1_only.to_html(index=False) if not f1_only.empty else "<p style='padding:20px; color:#94a3b8;'>No records found.</p>",
                'f2_only_html': f2_only.to_html(index=False) if not f2_only.empty else "<p style='padding:20px; color:#94a3b8;'>No records found.</p>"
            }

    return render_template_string(HTML_TEMPLATE, cols=cols, results=results, filenames=storage['names'])

@app.route('/export/<type>')
def export_csv(type):
    df = storage.get('f1_only' if type == 'deleted' else 'f2_only')
    if df is None or df.empty: return "No data", 404
    proxy = io.StringIO()
    df.to_csv(proxy, index=False)
    mem = io.BytesIO()
    mem.write(proxy.getvalue().encode('utf-8'))
    mem.seek(0)
    return send_file(mem, mimetype='text/csv', as_attachment=True, download_name=f"delta_{type}.csv")

if __name__ == '__main__':
    app.run(debug=True)