from flask import Flask, request, render_template_string, send_file
import pandas as pd
import io

app = Flask(__name__)

# Temporary storage for the session's results
last_delta = {"f1_only": None, "f2_only": None}

HTML_TEMPLATE = """
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Delta CSV</title>
    <script src="https://unpkg.com/lucide@latest"></script>
    <style>
        :root {
            --primary: #4f46e5;
            --bg: #f8fafc;
            --card: #ffffff;
            --text: #1e293b;
            --danger: #ef4444;
            --success: #10b981;
        }
        body { font-family: 'Inter', system-ui, sans-serif; background: var(--bg); color: var(--text); margin: 0; padding: 20px; }
        .container { max-width: 1000px; margin: 40px auto; }
        
        .header { text-align: center; margin-bottom: 40px; }
        .header h1 { font-size: 2rem; font-weight: 800; color: #0f172a; margin-bottom: 8px; }
        .header p { color: #64748b; }

        .upload-card { 
            background: var(--card); padding: 32px; border-radius: 16px; 
            box-shadow: 0 4px 6px -1px rgba(0,0,0,0.1), 0 2px 4px -2px rgba(0,0,0,0.1);
        }
        
        .file-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 24px; margin-bottom: 24px; }
        @media (max-width: 600px) { .file-grid { grid-template-columns: 1fr; } }

        .drop-zone {
            border: 2px dashed #e2e8f0; border-radius: 12px; padding: 20px;
            text-align: center; transition: all 0.2s; position: relative;
        }
        .drop-zone:hover { border-color: var(--primary); background: #f5f3ff; }
        .drop-zone input { position: absolute; inset: 0; opacity: 0; cursor: pointer; }
        .drop-zone label { font-weight: 600; font-size: 0.9rem; color: #475569; }

        button {
            width: 100%; background: var(--primary); color: white; border: none;
            padding: 14px; border-radius: 10px; font-weight: 600; cursor: pointer;
            transition: opacity 0.2s; font-size: 1rem;
        }
        button:hover { opacity: 0.9; }

        .section-title { font-size: 1.1rem; font-weight: 700; margin: 32px 0 16px; display: flex; align-items: center; gap: 8px; }
        
        .result-card { 
            background: white; border-radius: 12px; border: 1px solid #e2e8f0; 
            overflow: hidden; margin-bottom: 24px; box-shadow: 0 1px 3px rgba(0,0,0,0.05);
        }
        .result-header { 
            padding: 12px 20px; display: flex; justify-content: space-between; align-items: center;
            border-bottom: 1px solid #e2e8f0;
        }
        .badge { padding: 4px 10px; border-radius: 20px; font-size: 0.75rem; font-weight: 700; text-transform: uppercase; }
        .badge-red { background: #fee2e2; color: var(--danger); }
        .badge-green { background: #dcfce7; color: var(--success); }

        .download-link { font-size: 0.85rem; color: var(--primary); text-decoration: none; font-weight: 600; }
        .table-container { overflow-x: auto; max-height: 400px; }
        
        table { width: 100%; border-collapse: collapse; text-align: left; font-size: 0.85rem; }
        th { background: #f8fafc; padding: 12px 20px; color: #64748b; font-weight: 600; position: sticky; top: 0; }
        td { padding: 12px 20px; border-top: 1px solid #f1f5f9; white-space: nowrap; }
    </style>
</head>
<body>
    <div class="container">
        <div class="header">
            <h1>CSV Delta Engine</h1>
            <p>Upload two files to find additions and removals instantly.</p>
        </div>

        <div class="upload-card">
            <form method="POST" enctype="multipart/form-data">
                <div class="file-grid">
                    <div class="drop-zone">
                        <i data-lucide="file-text" style="color: #94a3b8; margin-bottom: 8px;"></i><br>
                        <label>Base File (A)</label>
                        <input type="file" name="file1" accept=".csv" required>
                    </div>
                    <div class="drop-zone">
                        <i data-lucide="file-plus" style="color: #94a3b8; margin-bottom: 8px;"></i><br>
                        <label>New File (B)</label>
                        <input type="file" name="file2" accept=".csv" required>
                    </div>
                </div>
                <button type="submit">Compare Files</button>
            </form>
        </div>

        {% if results %}
            <div class="section-title"><i data-lucide="bar-chart-2"></i> Analysis Results</div>

            <div class="result-card">
                <div class="result-header">
                    <span class="badge badge-red">Deleted from B</span>
                    {% if results.has_deleted %}
                    <a href="/export/deleted" class="download-link">Download .csv</a>
                    {% endif %}
                </div>
                <div class="table-container">
                    {{ results.f1_only_html|safe }}
                </div>
            </div>

            <div class="result-card">
                <div class="result-header">
                    <span class="badge badge-green">New in B</span>
                    {% if results.has_added %}
                    <a href="/export/added" class="download-link">Download .csv</a>
                    {% endif %}
                </div>
                <div class="table-container">
                    {{ results.f2_only_html|safe }}
                </div>
            </div>
        {% endif %}
    </div>

    <script>lucide.createIcons();</script>
</body>
</html>
"""

@app.route('/', methods=['GET', 'POST'])
def index():
    results = {}
    if request.method == 'POST':
        f1, f2 = request.files['file1'], request.files['file2']
        if f1 and f2:
            def clean_csv(file):
                df = pd.read_csv(io.StringIO(file.stream.read().decode("UTF8")))
                return df.dropna(how='all').fillna('').astype(str).apply(lambda x: x.str.strip())

            df1 = clean_csv(f1)
            df2 = clean_csv(f2)

            merged = df1.merge(df2, how='outer', indicator=True)
            f1_only = merged[merged['_merge'] == 'left_only'].drop(columns=['_merge'])
            f2_only = merged[merged['_merge'] == 'right_only'].drop(columns=['_merge'])

            last_delta['f1_only'], last_delta['f2_only'] = f1_only, f2_only

            results['f1_only_html'] = f1_only.to_html(index=False) if not f1_only.empty else "<p style='padding:20px; color:#94a3b8;'>No rows deleted.</p>"
            results['f2_only_html'] = f2_only.to_html(index=False) if not f2_only.empty else "<p style='padding:20px; color:#94a3b8;'>No new rows added.</p>"
            results['has_deleted'] = not f1_only.empty
            results['has_added'] = not f2_only.empty

    return render_template_string(HTML_TEMPLATE, results=results)

@app.route('/export/<type>')
def export_csv(type):
    df = last_delta.get('f1_only' if type == 'deleted' else 'f2_only')
    if df is None or df.empty: return "No data", 404
    
    proxy = io.StringIO()
    df.to_csv(proxy, index=False)
    mem = io.BytesIO()
    mem.write(proxy.getvalue().encode('utf-8'))
    mem.seek(0)
    return send_file(mem, mimetype='text/csv', as_attachment=True, download_name=f"delta_{type}.csv")

if __name__ == '__main__':
    app.run(debug=True)