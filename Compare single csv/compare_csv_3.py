from flask import Flask, request, render_template_string, send_file
import pandas as pd
import io

app = Flask(__name__)

# Temporary storage for the session's results
last_delta = {"f1_only": None, "f2_only": None}

HTML_TEMPLATE = """
<!DOCTYPE html>
<html>
<head>
    <title>CSV Delta Engine (Cleaned)</title>
    <style>
        body { font-family: 'Segoe UI', sans-serif; margin: 40px; background: #f0f2f5; color: #333; }
        .container { max-width: 1100px; margin: auto; background: white; padding: 30px; border-radius: 12px; box-shadow: 0 4px 20px rgba(0,0,0,0.08); }
        h2 { color: #1a73e8; border-bottom: 2px solid #e8f0fe; padding-bottom: 10px; margin-top: 0; }
        .file-section { display: flex; gap: 20px; margin-bottom: 20px; }
        .file-input { flex: 1; padding: 15px; border: 1px dashed #ccc; border-radius: 8px; background: #fafafa; }
        .btn-group { display: flex; gap: 10px; margin-bottom: 20px; }
        button, .download-btn { background: #1a73e8; color: white; border: none; padding: 12px 24px; border-radius: 6px; cursor: pointer; font-weight: bold; text-decoration: none; display: inline-block; }
        button:hover, .download-btn:hover { background: #1557b0; }
        .export-btn { background: #28a745; }
        .export-btn:hover { background: #218838; }
        .result-card { margin-top: 25px; padding: 15px; border-radius: 8px; border-left: 5px solid #ddd; overflow-x: auto; }
        .only-f1 { border-left-color: #dc3545; background: #fff5f5; } 
        .only-f2 { border-left-color: #28a745; background: #f4fff4; }
        table { width: 100%; border-collapse: collapse; margin-top: 10px; font-size: 0.85em; }
        th, td { border: 1px solid #dee2e6; padding: 8px; text-align: left; }
        th { background: #f8f9fa; }
    </style>
</head>
<body>
    <div class="container">
        <h2>CSV Delta Engine (NA Values Removed)</h2>
        <form method="POST" enctype="multipart/form-data">
            <div class="file-section">
                <div class="file-input">
                    <label><strong>Base File (CSV A):</strong></label><br><br>
                    <input type="file" name="file1" accept=".csv" required>
                </div>
                <div class="file-input">
                    <label><strong>New File (CSV B):</strong></label><br><br>
                    <input type="file" name="file2" accept=".csv" required>
                </div>
            </div>
            <button type="submit">Compare Files</button>
        </form>

        {% if results %}
            <hr style="margin: 30px 0; border: 0; border-top: 1px solid #eee;">
            <div class="btn-group">
                {% if results.has_deleted %}
                <a href="/export/deleted" class="download-btn export-btn">Download Deleted Rows</a>
                {% endif %}
                {% if results.has_added %}
                <a href="/export/added" class="download-btn" style="background:#007bff">Download Added Rows</a>
                {% endif %}
            </div>

            <div class="result-card only-f1">
                <h3>Rows in Base, MISSING in New (Deleted)</h3>
                {{ results.f1_only_html|safe }}
            </div>

            <div class="result-card only-f2">
                <h3>Rows in New, MISSING in Base (Added)</h3>
                {{ results.f2_only_html|safe }}
            </div>
        {% endif %}
    </div>
</body>
</html>
"""

@app.route('/', methods=['GET', 'POST'])
def index():
    results = {}
    if request.method == 'POST':
        f1 = request.files['file1']
        f2 = request.files['file2']
        
        if f1 and f2:
            # Load DataFrames
            df1 = pd.read_csv(io.StringIO(f1.stream.read().decode("UTF8")))
            df2 = pd.read_csv(io.StringIO(f2.stream.read().decode("UTF8")))

            # --- CLEANING STEP ---
            # 1. Drop rows that are entirely empty
            # 2. Fill individual NA cells with an empty string
            # 3. Convert everything to string and strip whitespace
            def clean_df(df):
                return df.dropna(how='all')\
                         .fillna('')\
                         .astype(str)\
                         .apply(lambda x: x.str.strip())

            df1_clean = clean_df(df1)
            df2_clean = clean_df(df2)

            # Symmetric Difference Logic
            merged = df1_clean.merge(df2_clean, how='outer', indicator=True)
            
            f1_only = merged[merged['_merge'] == 'left_only'].drop(columns=['_merge'])
            f2_only = merged[merged['_merge'] == 'right_only'].drop(columns=['_merge'])

            # Store for export
            last_delta['f1_only'] = f1_only
            last_delta['f2_only'] = f2_only

            results['f1_only_html'] = f1_only.to_html(index=False) if not f1_only.empty else "<p>No deleted rows found.</p>"
            results['f2_only_html'] = f2_only.to_html(index=False) if not f2_only.empty else "<p>No added rows found.</p>"
            results['has_deleted'] = not f1_only.empty
            results['has_added'] = not f2_only.empty

    return render_template_string(HTML_TEMPLATE, results=results)

@app.route('/export/<type>')
def export_csv(type):
    df = last_delta.get('f1_only' if type == 'deleted' else 'f2_only')
    if df is None or df.empty:
        return "No data", 404

    output = io.StringIO()
    df.to_csv(output, index=False)
    
    mem = io.BytesIO()
    mem.write(output.getvalue().encode('utf-8'))
    mem.seek(0)
    
    return send_file(
        mem,
        mimetype='text/csv',
        as_attachment=True,
        download_name=f"delta_{type}.csv"
    )

if __name__ == '__main__':
    app.run(debug=True)