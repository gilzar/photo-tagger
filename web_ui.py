"""
Web UI for Photo/Video Tagger.
Provides browsing, searching, and review interface.
"""
import json
import logging
import os
import mimetypes
from flask import Flask, request, jsonify, send_file, render_template_string

import config
import database
import ai_analyzer

logger = logging.getLogger(__name__)

app = Flask(__name__)

HTML_TEMPLATE = """
<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Photo Tagger</title>
<style>
  :root {
    --bg: #0f1117;
    --surface: #1a1d27;
    --surface2: #242836;
    --border: #2d3348;
    --text: #e4e6f0;
    --text-dim: #8b8fa3;
    --accent: #6c8cff;
    --accent-hover: #5a7bff;
    --green: #4ade80;
    --red: #f87171;
    --orange: #fbbf24;
    --tag-bg: #2d3348;
  }
  * { margin: 0; padding: 0; box-sizing: border-box; }
  body { font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
         background: var(--bg); color: var(--text); min-height: 100vh; }

  /* Layout */
  .app { display: flex; min-height: 100vh; }
  .sidebar { width: 220px; background: var(--surface); border-right: 1px solid var(--border);
             padding: 20px 0; flex-shrink: 0; position: fixed; height: 100vh; overflow-y: auto; }
  .main { flex: 1; margin-left: 220px; padding: 24px 32px; }

  /* Sidebar */
  .logo { padding: 0 20px 20px; font-size: 18px; font-weight: 700; color: var(--accent); }
  .nav-item { display: flex; align-items: center; gap: 10px; padding: 10px 20px;
              color: var(--text-dim); cursor: pointer; transition: all 0.15s; font-size: 14px; }
  .nav-item:hover, .nav-item.active { background: var(--surface2); color: var(--text); }
  .nav-item .badge { background: var(--accent); color: #fff; font-size: 11px;
                     padding: 1px 7px; border-radius: 10px; margin-left: auto; }
  .nav-section { padding: 16px 20px 6px; font-size: 11px; text-transform: uppercase;
                 letter-spacing: 1px; color: var(--text-dim); }

  /* Search */
  .search-bar { display: flex; gap: 10px; margin-bottom: 24px; }
  .search-bar input { flex: 1; background: var(--surface); border: 1px solid var(--border);
    color: var(--text); padding: 10px 16px; border-radius: 8px; font-size: 14px; outline: none; }
  .search-bar input:focus { border-color: var(--accent); }
  .search-bar select { background: var(--surface); border: 1px solid var(--border);
    color: var(--text); padding: 10px 12px; border-radius: 8px; font-size: 14px; }
  .search-bar button { background: var(--accent); color: #fff; border: none;
    padding: 10px 20px; border-radius: 8px; cursor: pointer; font-size: 14px; font-weight: 500; }
  .search-bar button:hover { background: var(--accent-hover); }

  /* Stats cards */
  .stats-row { display: grid; grid-template-columns: repeat(auto-fit, minmax(160px, 1fr));
               gap: 12px; margin-bottom: 24px; }
  .stat-card { background: var(--surface); border: 1px solid var(--border);
               border-radius: 10px; padding: 16px; }
  .stat-card .label { font-size: 12px; color: var(--text-dim); margin-bottom: 4px; }
  .stat-card .value { font-size: 24px; font-weight: 700; }

  /* File grid */
  .file-grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(260px, 1fr));
               gap: 16px; }
  .file-card { background: var(--surface); border: 1px solid var(--border);
               border-radius: 10px; overflow: hidden; transition: transform 0.15s, border-color 0.15s;
               cursor: pointer; }
  .file-card:hover { transform: translateY(-2px); border-color: var(--accent); }
  .file-thumb { width: 100%; height: 180px; object-fit: cover; background: var(--surface2);
                display: flex; align-items: center; justify-content: center; }
  .file-thumb img { width: 100%; height: 100%; object-fit: cover; }
  .file-thumb .placeholder { color: var(--text-dim); font-size: 40px; }
  .file-info { padding: 12px; }
  .file-info .name { font-size: 13px; font-weight: 600; margin-bottom: 4px;
                     white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
  .file-info .desc { font-size: 12px; color: var(--text-dim); margin-bottom: 8px;
                     display: -webkit-box; -webkit-line-clamp: 2; -webkit-box-orient: vertical;
                     overflow: hidden; min-height: 32px; }
  .file-info .tags { display: flex; flex-wrap: wrap; gap: 4px; }
  .tag { background: var(--tag-bg); color: var(--text-dim); font-size: 11px;
         padding: 2px 8px; border-radius: 4px; cursor: pointer; }
  .tag:hover { background: var(--accent); color: #fff; }
  .file-badges { display: flex; gap: 6px; padding: 0 12px 8px; }
  .badge-dup { background: var(--orange); color: #000; font-size: 10px; padding: 2px 6px;
               border-radius: 4px; font-weight: 600; }
  .badge-junk { background: var(--red); color: #fff; font-size: 10px; padding: 2px 6px;
                border-radius: 4px; font-weight: 600; }
  .badge-unanalyzed { background: var(--border); color: var(--text-dim); font-size: 10px;
                      padding: 2px 6px; border-radius: 4px; }

  /* Detail modal */
  .modal-overlay { position: fixed; top: 0; left: 0; width: 100%; height: 100%;
                   background: rgba(0,0,0,0.7); z-index: 100; display: none;
                   align-items: center; justify-content: center; }
  .modal-overlay.show { display: flex; }
  .modal { background: var(--surface); border: 1px solid var(--border); border-radius: 12px;
           width: 90%; max-width: 800px; max-height: 90vh; overflow-y: auto; }
  .modal-header { display: flex; justify-content: space-between; align-items: center;
                  padding: 16px 20px; border-bottom: 1px solid var(--border); }
  .modal-header h2 { font-size: 16px; }
  .modal-close { background: none; border: none; color: var(--text-dim); font-size: 24px;
                 cursor: pointer; }
  .modal-body { padding: 20px; }
  .modal-img { width: 100%; max-height: 400px; object-fit: contain; border-radius: 8px;
               margin-bottom: 16px; background: var(--bg); }
  .detail-row { margin-bottom: 12px; }
  .detail-row label { font-size: 12px; color: var(--text-dim); display: block; margin-bottom: 4px; }
  .detail-row .value { font-size: 14px; }
  .detail-row input, .detail-row textarea {
    width: 100%; background: var(--surface2); border: 1px solid var(--border);
    color: var(--text); padding: 8px; border-radius: 6px; font-size: 14px; }
  .detail-row textarea { min-height: 60px; resize: vertical; }
  .btn { padding: 8px 16px; border-radius: 6px; border: none; cursor: pointer;
         font-size: 13px; font-weight: 500; }
  .btn-primary { background: var(--accent); color: #fff; }
  .btn-primary:hover { background: var(--accent-hover); }
  .btn-outline { background: transparent; border: 1px solid var(--border); color: var(--text); }
  .btn-group { display: flex; gap: 8px; margin-top: 16px; }

  /* Duplicates table */
  .dup-table { width: 100%; border-collapse: collapse; }
  .dup-table th, .dup-table td { text-align: left; padding: 10px 12px; font-size: 13px;
    border-bottom: 1px solid var(--border); }
  .dup-table th { color: var(--text-dim); font-weight: 500; font-size: 12px; }
  .dup-table tr:hover { background: var(--surface2); }

  /* Loading */
  .loading { text-align: center; padding: 40px; color: var(--text-dim); }
  .spinner { display: inline-block; width: 20px; height: 20px; border: 2px solid var(--border);
             border-top-color: var(--accent); border-radius: 50%; animation: spin 0.8s linear infinite; }
  @keyframes spin { to { transform: rotate(360deg); } }

  /* Empty state */
  .empty { text-align: center; padding: 60px 20px; color: var(--text-dim); }
  .empty h3 { margin-bottom: 8px; color: var(--text); }

  /* Tag cloud */
  .tag-cloud { display: flex; flex-wrap: wrap; gap: 8px; }
  .tag-cloud .tag { font-size: 13px; padding: 4px 12px; }
  .tag-count { font-size: 11px; color: var(--text-dim); margin-left: 4px; }

  /* Responsive */
  @media (max-width: 768px) {
    .sidebar { display: none; }
    .main { margin-left: 0; padding: 16px; }
    .file-grid { grid-template-columns: repeat(auto-fill, minmax(160px, 1fr)); }
  }
</style>
</head>
<body>
<div class="app">
  <div class="sidebar">
    <div class="logo">Photo Tagger</div>
    <div class="nav-item active" onclick="navigate('browse')">Browse All</div>
    <div class="nav-item" onclick="navigate('duplicates')">Duplicates <span class="badge" id="dup-count">0</span></div>
    <div class="nav-item" onclick="navigate('junk')">Junk Files <span class="badge" id="junk-count">0</span></div>
    <div class="nav-section">Tags</div>
    <div id="tag-nav"></div>
  </div>

  <div class="main">
    <div id="stats-area"></div>
    <div class="search-bar">
      <input type="text" id="search-input" placeholder="Search by description, tags, filename..."
             onkeydown="if(event.key==='Enter')doSearch()">
      <select id="type-filter">
        <option value="">All types</option>
        <option value="image">Images</option>
        <option value="video">Videos</option>
      </select>
      <button onclick="doSearch()">Search</button>
    </div>
    <div id="content-area"></div>
  </div>
</div>

<!-- Detail Modal -->
<div class="modal-overlay" id="detail-modal">
  <div class="modal">
    <div class="modal-header">
      <h2 id="modal-title">File Details</h2>
      <button class="modal-close" onclick="closeModal()">&times;</button>
    </div>
    <div class="modal-body" id="modal-body"></div>
  </div>
</div>

<script>
const API = '';
let currentView = 'browse';

async function api(path) {
  try {
    const r = await fetch(API + path);
    if (!r.ok) {
      console.error(`API error: ${r.status} ${r.statusText} for ${path}`);
      return null;
    }
    return await r.json();
  } catch (e) {
    console.error(`API fetch failed for ${path}:`, e);
    return null;
  }
}

async function init() {
  const stats = await api('/api/stats');
  if (stats) {
    document.getElementById('dup-count').textContent = stats.duplicates || 0;
    document.getElementById('junk-count').textContent = stats.junk || 0;

    document.getElementById('stats-area').innerHTML = `
      <div class="stats-row">
        <div class="stat-card"><div class="label">Total Files</div><div class="value">${stats.total_files}</div></div>
        <div class="stat-card"><div class="label">Images</div><div class="value">${stats.images}</div></div>
        <div class="stat-card"><div class="label">Videos</div><div class="value">${stats.videos}</div></div>
        <div class="stat-card"><div class="label">AI Analyzed</div><div class="value">${stats.analyzed}</div></div>
        <div class="stat-card"><div class="label">Total Size</div><div class="value">${formatSize(stats.total_size)}</div></div>
      </div>`;
  }

  const tags = await api('/api/tags');
  const nav = document.getElementById('tag-nav');
  if (tags) {
    nav.innerHTML = tags.slice(0, 20).map(([tag, count]) =>
      `<div class="nav-item" onclick="searchTag('${tag}')">${tag} <span class="badge">${count}</span></div>`
    ).join('');
  }

  doSearch();
}

function navigate(view) {
  currentView = view;
  document.querySelectorAll('.nav-item').forEach(el => el.classList.remove('active'));
  event.target.classList.add('active');

  if (view === 'browse') doSearch();
  else if (view === 'duplicates') loadDuplicates();
  else if (view === 'junk') loadJunk();
}

async function doSearch() {
  const q = document.getElementById('search-input').value;
  const t = document.getElementById('type-filter').value;
  const params = new URLSearchParams();
  if (q) params.set('q', q);
  if (t) params.set('type', t);

  document.getElementById('content-area').innerHTML = '<div class="loading"><div class="spinner"></div> Searching...</div>';
  const files = await api('/api/search?' + params);

  if (!files || !files.length) {
    document.getElementById('content-area').innerHTML =
      '<div class="empty"><h3>No files found</h3><p>Try a different search or scan your directory first.</p></div>';
    return;
  }

  const grid = files.map(f => {
    const tags = safeParseTags(f.tags);
    const badges = [];
    if (f.is_duplicate) badges.push('<span class="badge-dup">DUPLICATE</span>');
    if (f.is_junk) badges.push('<span class="badge-junk">JUNK</span>');
    if (!f.ai_analyzed) badges.push('<span class="badge-unanalyzed">Not analyzed</span>');

    return `
      <div class="file-card" onclick="openDetail(${f.id})">
        <div class="file-thumb">
          ${f.file_type === 'image'
            ? `<img src="/api/thumb/${f.id}" loading="lazy" onerror="this.parentElement.innerHTML='<div class=placeholder>&#128444;</div>'">`
            : '<div class="placeholder">&#127909;</div>'}
        </div>
        <div class="file-info">
          <div class="name" title="${esc(f.filename)}">${esc(f.filename)}</div>
          <div class="desc">${esc(f.description || 'No description yet')}</div>
          <div class="tags">${tags.slice(0, 5).map(t => `<span class="tag" onclick="event.stopPropagation();searchTag('${esc(t)}')">${esc(t)}</span>`).join('')}</div>
        </div>
        ${badges.length ? `<div class="file-badges">${badges.join('')}</div>` : ''}
      </div>`;
  }).join('');

  document.getElementById('content-area').innerHTML = `<div class="file-grid">${grid}</div>`;
}

function searchTag(tag) {
  document.getElementById('search-input').value = tag;
  doSearch();
}

async function loadDuplicates() {
  document.getElementById('content-area').innerHTML = '<div class="loading"><div class="spinner"></div> Loading...</div>';
  const dups = await api('/api/duplicates');

  if (!dups || !dups.length) {
    document.getElementById('content-area').innerHTML =
      '<div class="empty"><h3>No duplicates found</h3><p>Great! Your library looks clean.</p></div>';
    return;
  }

  const rows = dups.map(d => `
    <tr>
      <td><a href="#" onclick="openDetail(${d.id}); return false">${esc(d.filename)}</a></td>
      <td>${formatSize(d.file_size)}</td>
      <td>${esc(d.original_filename || 'N/A')}</td>
      <td style="max-width:300px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap"
          title="${esc(d.filepath)}">${esc(d.filepath)}</td>
    </tr>`).join('');

  document.getElementById('content-area').innerHTML = `
    <h2 style="margin-bottom:16px">Duplicate Files (${dups.length})</h2>
    <p style="color:var(--text-dim);margin-bottom:16px;font-size:14px">
      These files appear to be duplicates. No files have been deleted — review and decide which to keep.</p>
    <table class="dup-table">
      <thead><tr><th>File</th><th>Size</th><th>Original</th><th>Path</th></tr></thead>
      <tbody>${rows}</tbody>
    </table>`;
}

async function loadJunk() {
  document.getElementById('content-area').innerHTML = '<div class="loading"><div class="spinner"></div> Loading...</div>';
  const junk = await api('/api/junk');

  if (!junk || !junk.length) {
    document.getElementById('content-area').innerHTML =
      '<div class="empty"><h3>No junk files found</h3><p>Your library looks clean!</p></div>';
    return;
  }

  const rows = junk.map(j => `
    <tr>
      <td><a href="#" onclick="openDetail(${j.id}); return false">${esc(j.filename)}</a></td>
      <td>${formatSize(j.file_size)}</td>
      <td>${esc(j.junk_reason)}</td>
      <td style="max-width:300px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap"
          title="${esc(j.filepath)}">${esc(j.filepath)}</td>
    </tr>`).join('');

  document.getElementById('content-area').innerHTML = `
    <h2 style="margin-bottom:16px">Potential Junk Files (${junk.length})</h2>
    <p style="color:var(--text-dim);margin-bottom:16px;font-size:14px">
      These files may be junk. No files have been deleted — review and decide which to remove.</p>
    <table class="dup-table">
      <thead><tr><th>File</th><th>Size</th><th>Reason</th><th>Path</th></tr></thead>
      <tbody>${rows}</tbody>
    </table>`;
}

async function openDetail(id) {
  const f = await api('/api/file/' + id);
  if (!f || f.error) return;

  const tags = safeParseTags(f.tags);
  document.getElementById('modal-title').textContent = f.filename;

  document.getElementById('modal-body').innerHTML = `
    ${f.file_type === 'image'
      ? `<img class="modal-img" src="/api/thumb/${f.id}?full=1">`
      : `<div style="text-align:center;padding:30px;background:var(--bg);border-radius:8px;margin-bottom:16px">
           <div style="font-size:60px">&#127909;</div><p style="color:var(--text-dim);margin-top:8px">Video file</p></div>`}
    <div class="detail-row">
      <label>Path</label>
      <div class="value" style="word-break:break-all;font-size:12px;color:var(--text-dim)">${esc(f.filepath)}</div>
    </div>
    <div class="detail-row">
      <label>Description</label>
      <textarea id="edit-desc">${esc(f.description || '')}</textarea>
    </div>
    <div class="detail-row">
      <label>Tags (comma-separated)</label>
      <input id="edit-tags" value="${esc(tags.join(', '))}">
    </div>
    <div class="detail-row">
      <label>Rename File</label>
      <input id="edit-name" value="${esc(f.filename)}">
    </div>
    <div style="display:grid;grid-template-columns:1fr 1fr;gap:12px;margin-top:8px">
      <div class="detail-row"><label>Type</label><div class="value">${f.file_type}</div></div>
      <div class="detail-row"><label>Size</label><div class="value">${formatSize(f.file_size)}</div></div>
      <div class="detail-row"><label>Dimensions</label><div class="value">${f.width || '?'} × ${f.height || '?'}</div></div>
      <div class="detail-row"><label>Modified</label><div class="value">${f.modified_date || 'N/A'}</div></div>
    </div>
    <div class="btn-group">
      <button class="btn btn-primary" onclick="saveDetail(${f.id})">Save Changes</button>
      <button class="btn btn-primary" onclick="analyzeOne(${f.id})">Analyze with AI</button>
      <button class="btn btn-outline" onclick="closeModal()">Close</button>
    </div>`;

  document.getElementById('detail-modal').classList.add('show');
}

async function saveDetail(id) {
  const desc = document.getElementById('edit-desc').value;
  const tags = document.getElementById('edit-tags').value.split(',').map(t => t.trim()).filter(Boolean);
  const newName = document.getElementById('edit-name').value;

  try {
    const r = await fetch('/api/file/' + id, {
      method: 'PUT',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({description: desc, tags: tags, filename: newName})
    });
    if (!r.ok) { alert('Error: Server returned ' + r.status); return; }
    const result = await r.json();
    if (result.error) alert('Error: ' + result.error);
    else { closeModal(); doSearch(); init(); }
  } catch (e) {
    alert('Error saving: ' + e.message);
  }
}

async function analyzeOne(id) {
  const btn = event.target;
  btn.textContent = 'Analyzing...';
  btn.disabled = true;
  try {
    const r = await fetch('/api/analyze/' + id, {method: 'POST'});
    if (!r.ok) { btn.textContent = 'Error!'; btn.disabled = false; alert('Server error: ' + r.status); return; }
    const result = await r.json();
    btn.disabled = false;
    if (result.error) { btn.textContent = 'Error!'; alert(result.error); }
    else { openDetail(id); }
  } catch (e) {
    btn.textContent = 'Error!';
    btn.disabled = false;
    alert('Analysis failed: ' + e.message);
  }
}

function closeModal() {
  document.getElementById('detail-modal').classList.remove('show');
}

function safeParseTags(tagsStr) {
  if (!tagsStr) return [];
  try { const t = JSON.parse(tagsStr); return Array.isArray(t) ? t : []; }
  catch { return []; }
}

function formatSize(bytes) {
  if (!bytes) return '0 B';
  const units = ['B', 'KB', 'MB', 'GB'];
  let i = 0;
  while (bytes >= 1024 && i < units.length - 1) { bytes /= 1024; i++; }
  return bytes.toFixed(1) + ' ' + units[i];
}

function esc(s) {
  if (!s) return '';
  return String(s).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;');
}

document.getElementById('detail-modal').addEventListener('click', e => {
  if (e.target === document.getElementById('detail-modal')) closeModal();
});
document.addEventListener('keydown', e => { if (e.key === 'Escape') closeModal(); });

init();
</script>
</body>
</html>
"""


@app.route("/")
def index():
    return render_template_string(HTML_TEMPLATE)


@app.route("/api/stats")
def api_stats():
    with database.get_connection() as conn:
        return jsonify(database.get_stats(conn))


@app.route("/api/search")
def api_search():
    q = request.args.get("q", "")
    file_type = request.args.get("type", None)
    try:
        limit = int(request.args.get("limit", 200))
        offset = int(request.args.get("offset", 0))
    except (ValueError, TypeError):
        return jsonify({"error": "Invalid limit or offset parameter"}), 400

    with database.get_connection() as conn:
        rows = database.search_files(conn, q, file_type=file_type, limit=limit, offset=offset)
        return jsonify([dict(r) for r in rows])


@app.route("/api/tags")
def api_tags():
    with database.get_connection() as conn:
        return jsonify(database.get_all_tags(conn))


@app.route("/api/duplicates")
def api_duplicates():
    with database.get_connection() as conn:
        rows = database.get_duplicates(conn)
        return jsonify([dict(r) for r in rows])


@app.route("/api/junk")
def api_junk():
    with database.get_connection() as conn:
        rows = database.get_junk_files(conn)
        return jsonify([dict(r) for r in rows])


@app.route("/api/file/<int:file_id>")
def api_file(file_id):
    with database.get_connection() as conn:
        row = database.get_file_by_id(conn, file_id)
        if not row:
            return jsonify({"error": "Not found"}), 404
        return jsonify(dict(row))


@app.route("/api/file/<int:file_id>", methods=["PUT"])
def api_update_file(file_id):
    data = request.json
    if not data:
        return jsonify({"error": "Invalid or missing JSON body"}), 400
    with database.get_connection() as conn:
        row = database.get_file_by_id(conn, file_id)
        if not row:
            return jsonify({"error": "Not found"}), 404

        update = {"filepath": row["filepath"]}

        if "description" in data:
            update["description"] = data["description"]
        if "tags" in data:
            update["tags"] = data["tags"]

        database.upsert_file(conn, update)

        # Handle rename
        if "filename" in data and data["filename"] != row["filename"]:
            result = ai_analyzer.rename_file(conn, file_id, data["filename"])
            if "error" in result:
                return jsonify(result)

        return jsonify({"success": True})


@app.route("/api/analyze/<int:file_id>", methods=["POST"])
def api_analyze(file_id):
    conn = database.init_db()
    try:
        result = ai_analyzer.analyze_file(conn, file_id)
        return jsonify(result)
    finally:
        conn.close()


@app.route("/api/thumb/<int:file_id>")
def api_thumb(file_id):
    """Serve image thumbnail."""
    with database.get_connection() as conn:
        row = database.get_file_by_id(conn, file_id)
        if not row or not os.path.exists(row["filepath"]):
            return "", 404

        if row["file_type"] != "image":
            return "", 404

        filepath = row["filepath"]
        mime = mimetypes.guess_type(filepath)[0] or "image/jpeg"

        # For full-size view
        if request.args.get("full"):
            return send_file(filepath, mimetype=mime)

        # Generate thumbnail on the fly
        try:
            from PIL import Image
            import io
            img = Image.open(filepath)
            if img.mode in ("RGBA", "P"):
                img = img.convert("RGB")
            img.thumbnail((400, 400))
            buf = io.BytesIO()
            img.save(buf, format="JPEG", quality=80)
            buf.seek(0)
            return send_file(buf, mimetype="image/jpeg")
        except (OSError, Image.UnidentifiedImageError, ValueError) as e:
            logger.warning("Thumbnail generation failed for %s: %s", filepath, e)
            return send_file(filepath, mimetype=mime)


if __name__ == "__main__":
    database.init_db()
    app.run(host=config.WEB_HOST, port=config.WEB_PORT, debug=True)
