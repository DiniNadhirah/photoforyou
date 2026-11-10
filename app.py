import os
import io
from flask import Flask, request, render_template_string, redirect, url_for, session, send_file
from werkzeug.security import generate_password_hash, check_password_hash
from supabase import create_client, Client

app = Flask(__name__)
app.secret_key = 'super-secret-key-photoforyou' 

SUPABASE_URL = os.environ.get("SUPABASE_URL")
SUPABASE_KEY = os.environ.get("SUPABASE_KEY")

supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)

BASE_HTML = """
<!doctype html>
<html>
<head>
    <title>PhotoForYou</title>
    <link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;600;700&display=swap" rel="stylesheet">
    <style>
        * { box-sizing: border-box; }
        body { font-family: 'Inter', sans-serif; margin: 0; color: #1e293b; background: #f8fafc url('data:image/svg+xml;utf8,<svg width="40" height="40" xmlns="http://www.w3.org/2000/svg"><path d="M 40 0 L 0 0 0 40" fill="none" stroke="rgba(0,0,0,0.03)" stroke-width="1"/></svg>'); }
        body::before { content: ""; position: fixed; top: -20%; left: 50%; transform: translateX(-50%); width: 800px; height: 800px; background: radial-gradient(circle, rgba(124,58,237,0.15) 0%, rgba(255,255,255,0) 70%); z-index: -1; }
        
        .navbar { background: rgba(255,255,255,0.8); backdrop-filter: blur(10px); padding: 15px 40px; display: flex; justify-content: space-between; box-shadow: 0 1px 3px rgba(0,0,0,0.05); }
        .navbar .brand { font-weight: 700; font-size: 20px; }
        .navbar a { text-decoration: none; color: #64748b; margin-left: 25px; font-weight: 600; font-size: 15px; }
        .navbar a:hover, .caption:hover { color: #4f46e5; }
        
        .container { max-width: 1000px; margin: 50px auto; padding: 20px; }
        .card { background: rgba(255,255,255,0.9); backdrop-filter: blur(10px); padding: 40px; border-radius: 16px; box-shadow: 0 10px 30px rgba(0,0,0,0.05); }
        h2 { margin-top: 0; }
        
        label { font-size: 14px; font-weight: 600; color: #334155; display: block; margin-bottom: 5px; }
        input[type="text"], input[type="password"], input[type="file"] { width: 100%; padding: 14px; margin-bottom: 20px; border: 1px solid #cbd5e1; border-radius: 10px; font-family: inherit; }
        input:focus { outline: none; border-color: #4f46e5; box-shadow: 0 0 0 3px rgba(79,70,229,0.1); }
        button, input[type="submit"] { background: #4f46e5; color: white; padding: 14px 28px; border: none; border-radius: 10px; cursor: pointer; font-weight: 600; font-size: 15px; text-decoration: none; box-shadow: 0 4px 6px rgba(79,70,229,0.2); }
        button:hover, input[type="submit"]:hover { background: #4338ca; }
        
        /* Header untuk setiap folder (Tajuk + Butang +) */
        .folder-header { display: flex; justify-content: space-between; align-items: center; border-bottom: 2px solid #e2e8f0; padding-bottom: 10px; margin: 30px 0 20px; }
        .folder-title { font-size: 22px; font-weight: 700; color: #4f46e5; margin: 0; }
        .btn-add-folder { background: #4f46e5; color: white; padding: 6px 12px; font-size: 13px; border-radius: 6px; text-decoration: none; font-weight: 600; display: inline-flex; align-items: center; gap: 5px; box-shadow: none;}
        .btn-add-folder:hover { background: #4338ca; transform: none; }

        .gallery-grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(220px, 1fr)); gap: 25px; }
        .gallery-item { background: white; border-radius: 12px; overflow: hidden; box-shadow: 0 4px 15px rgba(0,0,0,0.04); display: flex; flex-direction: column; border: 1px solid #e2e8f0; transition: transform 0.2s; }
        .gallery-item:hover { transform: translateY(-5px); }
        .gallery-item img { width: 100%; height: 180px; object-fit: cover; cursor: pointer; }
        
        .caption { padding: 12px; font-size: 13px; color: #64748b; text-align: center; font-weight: 600; cursor: pointer; border-bottom: 1px dashed transparent; }
        .caption:hover { border-bottom-color: #4f46e5; }
        
        .rename-input { width: 90%; padding: 8px; margin: 8px auto 4px; display: block; font-size: 13px; border: 1px solid #4f46e5; border-radius: 6px; text-align: center; }
        .btn-save, .btn-cancel { width: 90%; padding: 8px; font-size: 12px; border-radius: 6px; margin: 0 auto 4px; display: block; }
        .btn-save { background: #10b981; } .btn-cancel { background: #cbd5e1; color: #333; }
        
        .menu-container { position: relative; display: flex; justify-content: flex-end; padding: 8px; background: #f8fafc; border-top: 1px solid #f1f5f9; }
        .menu-btn { background: none; border: none; font-size: 24px; cursor: pointer; color: #64748b; padding: 0 10px; box-shadow: none; }
        .dropdown-menu { display: none; position: absolute; right: 10px; bottom: 45px; background: white; min-width: 140px; box-shadow: 0 4px 15px rgba(0,0,0,0.1); border-radius: 8px; border: 1px solid #e2e8f0; z-index: 10; }
        .dropdown-menu a { display: block; padding: 10px 15px; font-size: 13px; color: #334155; text-decoration: none; }
        .dropdown-menu a:hover { background: #f1f5f9; } .text-red { color: #ef4444 !important; }
        .show { display: block !important; }
        
        .modal { display: none; position: fixed; z-index: 1000; padding-top: 50px; left: 0; top: 0; width: 100%; height: 100%; background: rgba(15,23,42,0.95); }
        .modal-content { margin: auto; display: block; max-width: 90%; max-height: 80vh; border-radius: 8px; }
        .close { position: absolute; top: 20px; right: 40px; color: white; font-size: 40px; cursor: pointer; }
        .alert { padding: 15px; background: #fef2f2; color: #b91c1c; border-radius: 10px; margin-bottom: 20px; border: 1px solid #fecaca; }
    </style>
</head>
<body>
    {% if session.user_id %}
    <div class="navbar">
        <div class="brand">PhotoForYou</div>
        <div>
            <a href="/">Gallery</a>
            <a href="/upload">Upload</a>
            <a href="/logout" style="color: #ef4444;">Logout ({{ session.username }})</a>
        </div>
    </div>
    {% endif %}
    <div class="container"><div class="card">{{ content|safe }}</div></div>
    
    <div id="imageModal" class="modal"><span class="close">&times;</span><img class="modal-content" id="modalImg"></div>
    
    <script>
        var modal = document.getElementById("imageModal"), modalImg = document.getElementById("modalImg"), closeBtn = document.getElementsByClassName("close")[0];
        function openModal(src) { modal.style.display = "block"; modalImg.src = src; }
        closeBtn.onclick = function() { modal.style.display = "none"; }
        modal.onclick = function(e) { if (e.target == modal) modal.style.display = "none"; }

        function toggleMenu(id) {
            var menu = document.getElementById("menu-" + id);
            var allMenus = document.getElementsByClassName("dropdown-menu");
            for (var i = 0; i < allMenus.length; i++) { if (allMenus[i].id !== "menu-" + id) allMenus[i].classList.remove("show"); }
            menu.classList.toggle("show");
        }
        window.onclick = function(e) {
            if (!e.target.matches('.menu-btn')) {
                var d = document.getElementsByClassName("dropdown-menu");
                for (var i = 0; i < d.length; i++) d[i].classList.remove('show');
            }
        }

        function showRename(id, filename) {
            document.getElementById('caption-' + id).style.display = 'none';
            document.getElementById('form-' + id).style.display = 'block';
            var input = document.getElementById('input-' + id);
            input.value = filename.substring(0, filename.lastIndexOf('.')) || filename;
            input.focus();
        }
        function hideRename(id) {
            document.getElementById('form-' + id).style.display = 'none';
            document.getElementById('caption-' + id).style.display = 'block';
        }
    </script>
</body>
</html>
"""

LOGIN_HTML = """<h2>Welcome Back</h2><p style="color: #64748b; margin-bottom: 25px;">Please log in to your account.</p><form method="post"><label>Username</label><input type="text" name="username" required><label>Password</label><input type="password" name="password" required><input type="submit" value="Login"></form><p style="margin-top: 25px; font-size: 14px; color: #64748b;">Don't have an account? <a href="/register" style="color: #4f46e5; text-decoration: none; font-weight: 600;">Sign up here</a></p>"""
REGISTER_HTML = """<h2>Create an Account</h2><p style="color: #64748b; margin-bottom: 25px;">Sign up to start saving your photos.</p><form method="post"><label>Username</label><input type="text" name="username" required><label>Password</label><input type="password" name="password" required><input type="submit" value="Sign Up"></form><p style="margin-top: 25px; font-size: 14px; color: #64748b;">Already have an account? <a href="/login" style="color: #4f46e5; text-decoration: none; font-weight: 600;">Login here</a></p>"""

UPLOAD_HTML = """
<h2>Upload a New Photo</h2>
<form method="post" enctype="multipart/form-data">
    <label>Folder Name</label>
    <!-- Value akan diisi secara automatik kalau datang dari butang + -->
    <input type="text" name="folder_name" value="{{ folder_name or '' }}" required>
    
    <label>Select Image</label>
    <input type="file" name="file" accept="image/*" required style="border: 2px dashed #cbd5e1; padding: 40px; text-align: center; cursor: pointer; background: #f8fafc;">
    <br><br>
    <input type="submit" value="Upload to PhotoForYou">
</form>
"""

GALLERY_HTML = """
<h2>Your Photo Gallery</h2>
{% if not photos %}
    <p style="color: #64748b;">No photos yet. Go ahead and <a href="/upload" style="color: #4f46e5; text-decoration: none; font-weight: 600;">upload</a> your first photo!</p>
{% else %}
    {% for folder, folder_photos in photos.items() %}
        <div class="folder-section">
            <!-- Butang + Add Photo di sebelah tajuk folder -->
            <div class="folder-header">
                <h3 class="folder-title">{{ folder }}</h3>
                <a href="/upload?folder={{ folder }}" class="btn-add-folder">+ Add Photo</a>
            </div>
            
            <div class="gallery-grid">
                {% for photo in folder_photos %}
                    {% set img_url = SUPABASE_URL + '/storage/v1/object/public/Photos/' + photo['filename'] %}
                    <div class="gallery-item">
                        <img src="{{ img_url }}" onclick="openModal('{{ img_url }}')">
                        
                        <div class="caption" id="caption-{{ photo['id'] }}" onclick="showRename('{{ photo['id'] }}', '{{ photo['filename'] }}')">
                            {{ photo['filename'] }}
                        </div>
                        
                        <form id="form-{{ photo['id'] }}" action="/rename" method="POST" style="display: none;">
                            <input type="hidden" name="photo_id" value="{{ photo['id'] }}">
                            <input type="hidden" name="old_filename" value="{{ photo['filename'] }}">
                            <input type="text" name="new_filename" id="input-{{ photo['id'] }}" class="rename-input" required>
                            <button type="submit" class="btn-save">Save</button>
                            <button type="button" class="btn-cancel" onclick="hideRename('{{ photo['id'] }}')">Cancel</button>
                        </form>

                        <div class="menu-container">
                            <button class="menu-btn" onclick="toggleMenu('{{ photo['id'] }}')">&#8942;</button>
                            <div id="menu-{{ photo['id'] }}" class="dropdown-menu">
                                <a href="{{ img_url }}" target="_blank">View</a>
                                <a href="/download/{{ photo['filename'] }}">Download</a>
                                <a href="{{ url_for('delete_file', photo_id=photo['id'], filename=photo['filename']) }}" class="text-red" onclick="return confirm('Delete this photo?')">Delete</a>
                            </div>
                        </div>
                    </div>
                {% endfor %}
            </div>
        </div>
    {% endfor %}
{% endif %}
"""

# ====== ROUTES ======
@app.route('/')
def index():
    if 'user_id' not in session: return redirect(url_for('login'))
    response = supabase.table('photos').select('id, filename, folder_name').eq('user_id', session['user_id']).execute()
    folder_dict = {}
    for photo in response.data:
        folder = photo.get('folder_name') or 'Uncategorized'
        if folder not in folder_dict: folder_dict[folder] = []
        folder_dict[folder].append(photo)
    return render_template_string(BASE_HTML, content=render_template_string(GALLERY_HTML, photos=folder_dict, SUPABASE_URL=SUPABASE_URL))

@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        try:
            supabase.table('users').insert({'username': request.form['username'], 'password_hash': generate_password_hash(request.form['password'])}).execute()
            return redirect(url_for('login'))
        except:
            return render_template_string(BASE_HTML, content="<div class='alert'>Username already exists!</div>" + REGISTER_HTML)
    return render_template_string(BASE_HTML, content=REGISTER_HTML)

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        response = supabase.table('users').select('*').eq('username', request.form['username']).execute()
        if response.data and check_password_hash(response.data[0]['password_hash'], request.form['password']):
            session['user_id'] = response.data[0]['id']
            session['username'] = response.data[0]['username']
            return redirect(url_for('index'))
        return render_template_string(BASE_HTML, content="<div class='alert'>Incorrect Username or Password!</div>" + LOGIN_HTML)
    return render_template_string(BASE_HTML, content=LOGIN_HTML)

@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('login'))

@app.route('/upload', methods=['GET', 'POST'])
def upload():
    if 'user_id' not in session: return redirect(url_for('login'))
    
    # Ambil nama folder dari URL (kalau klik butang +)
    preset_folder = request.args.get('folder', '')

    if request.method == 'POST':
        file = request.files.get('file')
        folder_name = request.form.get('folder_name')
        
        if file:
            supabase.storage.from_('Photos').upload(file=file.read(), path=file.filename, file_options={"content-type": file.content_type})
            supabase.table('photos').insert({'user_id': session['user_id'], 'filename': file.filename, 'folder_name': folder_name}).execute()
            return redirect(url_for('index'))
            
    # Pass preset_folder ke template supaya kotak teks auto-fill
    return render_template_string(BASE_HTML, content=render_template_string(UPLOAD_HTML, folder_name=preset_folder))

@app.route('/rename', methods=['POST'])
def rename_file():
    if 'user_id' not in session: return redirect(url_for('login'))
    old_name = request.form['old_filename']
    new_name = request.form['new_filename'].strip()
    ext = os.path.splitext(old_name)[1]
    
    if not new_name.lower().endswith(ext.lower()): new_name += ext
    try:
        file_data = supabase.storage.from_('Photos').download(old_name)
        supabase.storage.from_('Photos').upload(file=file_data, path=new_name, file_options={"content-type": "image/jpeg", "upsert": "true"})
        supabase.table('photos').update({'filename': new_name}).eq('id', request.form['photo_id']).eq('user_id', session['user_id']).execute()
        if old_name != new_name: supabase.storage.from_('Photos').remove([old_name])
    except Exception as e: print("Error:", e)
    return redirect(url_for('index'))

@app.route('/download/<filename>')
def download_photo(filename):
    if 'user_id' not in session: return redirect(url_for('login'))
    return send_file(io.BytesIO(supabase.storage.from_('Photos').download(filename)), as_attachment=True, download_name=filename)

@app.route('/delete/<int:photo_id>/<filename>')
def delete_file(photo_id, filename):
    if 'user_id' not in session: return redirect(url_for('login'))
    supabase.storage.from_('Photos').remove([filename])
    supabase.table('photos').delete().eq('id', photo_id).eq('user_id', session['user_id']).execute()
    return redirect(url_for('index'))

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=True)