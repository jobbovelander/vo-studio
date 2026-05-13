#!/usr/bin/env python3
"""
VO Studio – server.py v4
Serie → Aflevering → Script structuur.
"""

import os, re, json, shutil, threading
from pathlib import Path
from datetime import datetime
from flask import Flask, jsonify, request, send_file, send_from_directory, abort

import database as db
from parser import (parse_script, tc_to_seconds, seconds_to_tc,
                    insert_take_into_text, remove_take_from_text)

# Gebruik live app-map van NAS als die beschikbaar is (directe sync), anders ingebakken
_app_live = Path(os.environ.get('VO_APP_DIR', ''))
_static   = str(_app_live / 'static') if _app_live.exists() else 'static'

app = Flask(__name__, static_folder=_static, static_url_path='')
app.config['MAX_CONTENT_LENGTH'] = 8 * 1024 * 1024 * 1024

BASE_DIR    = Path(__file__).parent
DATA_DIR    = Path(os.environ.get('VO_DATA_DIR', str(BASE_DIR / 'data')))
VIDEOS_DIR  = DATA_DIR / 'videos'
SCRIPTS_DIR = DATA_DIR / 'scripts'
OUTPUTS_DIR = DATA_DIR / 'outputs'

for d in [VIDEOS_DIR, SCRIPTS_DIR, OUTPUTS_DIR]:
    d.mkdir(parents=True, exist_ok=True)

db.DB_PATH = DATA_DIR / 'vo_studio.db'
db.init_db()

# ── Helpers ───────────────────────────────────────────────────────

def _script_path(filename):
    return SCRIPTS_DIR / Path(filename).name

def _output_dir(episode_id, script_id):
    d = OUTPUTS_DIR / str(episode_id) / str(script_id)
    d.mkdir(parents=True, exist_ok=True)
    return d

def _sync_takes(script_id, fps):
    """Parse scriptbestand en sync takes naar database."""
    with db.get_db() as conn:
        script = db.row_to_dict(conn.execute(
            "SELECT * FROM scripts WHERE id=?", (script_id,)).fetchone())
        if not script:
            return []
        path = _script_path(script['filename'])
        if not path.exists():
            return []

        parsed = parse_script(path.read_text(encoding='utf-8'), fps)

        # Haal bestaande takes op
        existing = {t['take_index']: t for t in db.rows_to_list(
            conn.execute("SELECT * FROM takes WHERE script_id=? AND displaced=0",
                         (script_id,)).fetchall())}

        for p in parsed:
            ex = existing.get(p['index'])
            if ex:
                # Update tijdcodes en tekst
                conn.execute("""UPDATE takes SET
                    timecode_in=?, timecode_out=?, seconds_in=?, seconds_out=?,
                    duration=?, auto_out=?, text=?, annotations=?, original_index=?
                    WHERE id=?""",
                    (p['timecode_in'], p.get('timecode_out'), p['seconds_in'],
                     p.get('seconds_out'), p.get('duration'),
                     1 if p.get('auto_out') else 0,
                     p['text'], json.dumps(p.get('annotations', [])),
                     p.get('original_index', p['index']), ex['id']))
            else:
                conn.execute("""INSERT INTO takes
                    (script_id, take_index, original_index, timecode_in, timecode_out,
                     seconds_in, seconds_out, duration, auto_out, text, annotations, status)
                    VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""",
                    (script_id, p['index'], p.get('original_index', p['index']),
                     p['timecode_in'], p.get('timecode_out'),
                     p['seconds_in'], p.get('seconds_out'), p.get('duration'),
                     1 if p.get('auto_out') else 0,
                     p['text'], json.dumps(p.get('annotations', [])), 'pending'))

        # Verwijder takes die niet meer in het script staan
        parsed_indices = {p['index'] for p in parsed}
        for idx, ex in existing.items():
            if idx not in parsed_indices:
                conn.execute("UPDATE takes SET displaced=1 WHERE id=?", (ex['id'],))

        return parsed

# ── Series ────────────────────────────────────────────────────────

@app.route('/api/series', methods=['GET'])
def list_series():
    include_archived = request.args.get('archived', 'false') == 'true'
    series = db.get_series_list(include_archived)
    for s in series:
        # FIX #5: toon alleen niet-gearchiveerde eps in de teller, tenzij archief-view
        eps = db.get_episodes(s['id'], include_archived)
        s['episode_count'] = len(eps)
        s['done_count']    = sum(1 for e in eps if e['status'] == 'done')
    return jsonify(series)

@app.route('/api/series/<int:sid>/archived-episodes', methods=['GET'])
def list_archived_episodes(sid):
    # FIX #5: aparte route voor alleen gearchiveerde episodes
    return jsonify(db.get_archived_episodes(sid))

@app.route('/api/series', methods=['POST'])
def create_series():
    data = request.json
    with db.get_db() as conn:
        cur = conn.execute(
            "INSERT INTO series (name, year) VALUES (?,?)",
            (data['name'], data.get('year')))
        return jsonify({'ok': True, 'id': cur.lastrowid})

@app.route('/api/series/<int:sid>', methods=['PATCH'])
def update_series(sid):
    data = request.json
    allowed = ['name', 'year', 'archived']
    with db.get_db() as conn:
        for k, v in data.items():
            if k in allowed:
                conn.execute(f"UPDATE series SET {k}=? WHERE id=?", (v, sid))
    return jsonify({'ok': True})

@app.route('/api/series/<int:sid>', methods=['DELETE'])
def delete_series(sid):
    with db.get_db() as conn:
        conn.execute("DELETE FROM series WHERE id=?", (sid,))
    return jsonify({'ok': True})

# ── Afleveringen ──────────────────────────────────────────────────

@app.route('/api/series/<int:sid>/episodes', methods=['GET'])
def list_episodes(sid):
    include_archived = request.args.get('archived', 'false') == 'true'
    eps = db.get_episodes(sid, include_archived)
    for ep in eps:
        scripts = db.get_episode_progress(ep['id'])
        ep['scripts']      = scripts
        ep['total_takes']  = sum(s['total_takes'] for s in scripts)
        ep['done_takes']   = sum(s['done_takes']  for s in scripts)
        ep['progress_pct'] = (
            int(ep['done_takes'] / ep['total_takes'] * 100)
            if ep['total_takes'] else 0)
    return jsonify(eps)

@app.route('/api/episodes', methods=['POST'])
def create_episode():
    data = request.json
    with db.get_db() as conn:
        cur = conn.execute(
            "INSERT INTO episodes (series_id, code, title, video_file, fps) VALUES (?,?,?,?,?)",
            (data['series_id'], data['code'], data.get('title'),
             data.get('video_file'), int(data.get('fps', 25))))
        return jsonify({'ok': True, 'id': cur.lastrowid})

@app.route('/api/episodes/<int:eid>', methods=['GET'])
def get_episode(eid):
    with db.get_db() as conn:
        # FIX #9: include series_id voor jumpToTake in de frontend
        ep = db.row_to_dict(conn.execute(
            "SELECT e.*, e.series_id FROM episodes e WHERE e.id=?", (eid,)).fetchone())
    if not ep:
        abort(404)
    ep['scripts'] = db.get_episode_progress(eid)
    return jsonify(ep)

@app.route('/api/episodes/<int:eid>', methods=['PATCH'])
def update_episode(eid):
    data = request.json
    allowed = ['code', 'title', 'video_file', 'fps', 'status', 'archived', 'tc_offset']
    with db.get_db() as conn:
        for k, v in data.items():
            if k in allowed:
                conn.execute(f"UPDATE episodes SET {k}=? WHERE id=?", (v, eid))
    return jsonify({'ok': True})

@app.route('/api/episodes/<int:eid>/finalize', methods=['POST'])
def finalize_episode(eid):
    """
    Markeer aflevering als voltooid en start WAV-export op de achtergrond.
    Ontbrekende takes krijgen stilte op die positie.
    """
    with db.get_db() as conn:
        conn.execute("UPDATE episodes SET status='done' WHERE id=?", (eid,))
        scripts = db.rows_to_list(conn.execute(
            "SELECT * FROM scripts WHERE episode_id=?", (eid,)).fetchall())

    # Zet alle scripts op 'exporting'
    with db.get_db() as conn:
        for s in scripts:
            conn.execute("UPDATE scripts SET export_status='exporting' WHERE id=?", (s['id'],))

    # Start export op achtergrond thread
    def run_exports():
        for s in scripts:
            try:
                _export_script_wav(s['id'])
                with db.get_db() as conn:
                    conn.execute(
                        "UPDATE scripts SET export_status='done' WHERE id=?", (s['id'],))
            except Exception as exc:
                with db.get_db() as conn:
                    conn.execute(
                        "UPDATE scripts SET export_status=? WHERE id=?",
                        (f'error: {str(exc)[:200]}', s['id']))

    threading.Thread(target=run_exports, daemon=True).start()
    return jsonify({'ok': True, 'exporting': len(scripts)})

@app.route('/api/episodes/<int:eid>/export-status', methods=['GET'])
def episode_export_status(eid):
    """Geeft export-status per script terug (voor live polling in admin)."""
    with db.get_db() as conn:
        scripts = db.rows_to_list(conn.execute(
            """SELECT s.id, s.name, s.filename, s.export_status,
                      s.export_sample_rate, s.export_bit_depth,
                      (SELECT COUNT(*) FROM takes WHERE script_id=s.id AND displaced=0) as total,
                      (SELECT COUNT(*) FROM takes t WHERE t.script_id=s.id AND t.displaced=0
                       AND EXISTS (SELECT 1 FROM recordings r WHERE r.take_id=t.id AND r.displaced=0)
                      ) as done
               FROM scripts s WHERE s.episode_id=?""",
            (eid,)).fetchall())
    return jsonify(scripts)

@app.route('/api/episodes/<int:eid>/archive', methods=['POST'])
def archive_episode(eid):
    with db.get_db() as conn:
        conn.execute("UPDATE episodes SET archived=1 WHERE id=?", (eid,))
    return jsonify({'ok': True})

@app.route('/api/episodes/<int:eid>/unarchive', methods=['POST'])
def unarchive_episode(eid):
    with db.get_db() as conn:
        conn.execute("UPDATE episodes SET archived=0, status='in_progress' WHERE id=?", (eid,))
    return jsonify({'ok': True})

@app.route('/api/episodes/<int:eid>', methods=['DELETE'])
def delete_episode(eid):
    with db.get_db() as conn:
        conn.execute("DELETE FROM episodes WHERE id=?", (eid,))
    return jsonify({'ok': True})

# ── Scripts ───────────────────────────────────────────────────────

@app.route('/api/episodes/<int:eid>/scripts', methods=['GET'])
def list_scripts(eid):
    scripts = db.get_scripts(eid)
    for s in scripts:
        with db.get_db() as conn:
            s['total_takes'] = conn.execute(
                "SELECT COUNT(*) FROM takes WHERE script_id=? AND displaced=0",
                (s['id'],)).fetchone()[0]
            s['done_takes'] = conn.execute(
                """SELECT COUNT(DISTINCT t.id) FROM takes t
                   JOIN recordings r ON r.take_id=t.id AND r.displaced=0
                   WHERE t.script_id=? AND t.displaced=0""",
                (s['id'],)).fetchone()[0]
    return jsonify(scripts)

@app.route('/api/scripts', methods=['POST'])
def create_script():
    data = request.json
    episode_id = data['episode_id']
    name       = data['name']
    filename   = data.get('filename') or f"{name.lower().replace(' ', '_')}.txt"

    # Maak leeg scriptbestand aan als het nog niet bestaat
    path = _script_path(filename)
    if not path.exists():
        path.write_text('', encoding='utf-8')

    with db.get_db() as conn:
        ep = db.row_to_dict(conn.execute(
            "SELECT fps FROM episodes WHERE id=?", (episode_id,)).fetchone())
        fps = ep['fps'] if ep else 25
        cur = conn.execute(
            "INSERT INTO scripts (episode_id, name, filename) VALUES (?,?,?)",
            (episode_id, name, filename))
        sid = cur.lastrowid

    _sync_takes(sid, fps)
    return jsonify({'ok': True, 'id': sid, 'filename': filename})

@app.route('/api/scripts/<int:sid>', methods=['GET'])
def get_script(sid):
    with db.get_db() as conn:
        s = db.row_to_dict(conn.execute(
            "SELECT * FROM scripts WHERE id=?", (sid,)).fetchone())
    if not s:
        abort(404)
    return jsonify(s)

@app.route('/api/scripts/<int:sid>', methods=['PATCH'])
def update_script(sid):
    data = request.json
    allowed = ['name', 'export_sample_rate', 'export_bit_depth', 'export_channels']
    with db.get_db() as conn:
        for k, v in data.items():
            if k in allowed:
                conn.execute(f"UPDATE scripts SET {k}=? WHERE id=?", (v, sid))
    return jsonify({'ok': True})

@app.route('/api/scripts/<int:sid>', methods=['DELETE'])
def delete_script_record(sid):
    with db.get_db() as conn:
        conn.execute("DELETE FROM scripts WHERE id=?", (sid,))
    return jsonify({'ok': True})

@app.route('/api/scripts/<int:sid>/content', methods=['GET'])
def get_script_content(sid):
    with db.get_db() as conn:
        s = db.row_to_dict(conn.execute(
            "SELECT * FROM scripts WHERE id=?", (sid,)).fetchone())
    if not s:
        abort(404)
    path = _script_path(s['filename'])
    return jsonify({'content': path.read_text(encoding='utf-8') if path.exists() else ''})

@app.route('/api/scripts/<int:sid>/content', methods=['POST'])
def save_script_content(sid):
    with db.get_db() as conn:
        s = db.row_to_dict(conn.execute(
            "SELECT s.*, e.fps FROM scripts s JOIN episodes e ON e.id=s.episode_id WHERE s.id=?",
            (sid,)).fetchone())
    if not s:
        abort(404)
    content = request.json.get('content', '')
    _script_path(s['filename']).write_text(content, encoding='utf-8')
    _sync_takes(sid, s['fps'])
    db.update_script_status(sid)
    db.update_episode_status(s['episode_id'])
    return jsonify({'ok': True})

@app.route('/api/scripts/<int:sid>/sync', methods=['POST'])
def sync_script(sid):
    """Herlaad takes uit scriptbestand."""
    with db.get_db() as conn:
        s = db.row_to_dict(conn.execute(
            "SELECT s.*, e.fps FROM scripts s JOIN episodes e ON e.id=s.episode_id WHERE s.id=?",
            (sid,)).fetchone())
    if not s:
        abort(404)
    takes = _sync_takes(sid, s['fps'])
    db.update_script_status(sid)
    return jsonify({'ok': True, 'total': len(takes)})

# ── Takes ─────────────────────────────────────────────────────────

@app.route('/api/scripts/<int:sid>/takes', methods=['GET'])
def get_takes(sid):
    with db.get_db() as conn:
        s = db.row_to_dict(conn.execute(
            "SELECT s.*, e.fps, e.id as episode_id FROM scripts s "
            "JOIN episodes e ON e.id=s.episode_id WHERE s.id=?", (sid,)).fetchone())
    if not s:
        abort(404)
    takes = db.get_takes(sid)
    for t in takes:
        t['annotations'] = json.loads(t['annotations'] or '[]')
    return jsonify({'takes': takes, 'fps': s['fps'], 'total': len(takes),
                    'script': s})

@app.route('/api/takes/<int:tid>/move', methods=['POST'])
def move_take(tid):
    """
    Verplaats een take naar een ander script.
    Past beide scriptbestanden aan en markeert de take als pending.
    """
    data          = request.json
    target_sid    = data.get('target_script_id')
    create_new    = data.get('create_new_script')

    with db.get_db() as conn:
        take = db.row_to_dict(conn.execute(
            "SELECT t.*, s.filename as src_filename, s.episode_id, e.fps "
            "FROM takes t "
            "JOIN scripts s ON s.id=t.script_id "
            "JOIN episodes e ON e.id=s.episode_id "
            "WHERE t.id=?", (tid,)).fetchone())
        if not take:
            abort(404)

        src_sid = take['script_id']

        # Nieuw script aanmaken indien gewenst
        if create_new:
            new_name     = data.get('new_script_name', 'Nieuw script')
            new_filename = re.sub(r'[^a-z0-9_.-]', '_',
                                  new_name.lower().replace(' ', '_')) + '.txt'
            cur = conn.execute(
                "INSERT INTO scripts (episode_id, name, filename) VALUES (?,?,?)",
                (take['episode_id'], new_name, new_filename))
            target_sid = cur.lastrowid
            _script_path(new_filename).write_text('', encoding='utf-8')

        # Haal doelscript op
        target = db.row_to_dict(conn.execute(
            "SELECT * FROM scripts WHERE id=?", (target_sid,)).fetchone())
        if not target:
            abort(404)

        fps = take['fps']

        # 1. Verwijder uit bronscript
        src_path = _script_path(take['src_filename'])
        if src_path.exists():
            new_src = remove_take_from_text(
                src_path.read_text(encoding='utf-8'),
                take['original_index'], take['timecode_in'])
            src_path.write_text(new_src, encoding='utf-8')

        # 2. Voeg toe aan doelscript
        dst_path = _script_path(target['filename'])
        dst_text = dst_path.read_text(encoding='utf-8') if dst_path.exists() else ''
        new_dst  = insert_take_into_text(dst_text, take, fps)
        dst_path.write_text(new_dst, encoding='utf-8')

        # 3. Markeer huidige take als displaced
        conn.execute("UPDATE takes SET displaced=1 WHERE id=?", (tid,))
        # Markeer eventuele opname als displaced
        conn.execute("UPDATE recordings SET displaced=1 WHERE take_id=?", (tid,))

        # 4. Voeg toe aan doelscript in DB
        conn.execute("""INSERT INTO takes
            (script_id, take_index, original_index, timecode_in, timecode_out,
             seconds_in, seconds_out, duration, auto_out, text, annotations, status)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""",
            (target_sid,
             conn.execute("SELECT COALESCE(MAX(take_index),0)+1 FROM takes WHERE script_id=? AND displaced=0",
                          (target_sid,)).fetchone()[0],
             take['original_index'], take['timecode_in'], take['timecode_out'],
             take['seconds_in'], take['seconds_out'], take['duration'],
             take['auto_out'], take['text'], take['annotations'], 'pending'))

    # FIX #2: sync alleen bronscript — doelscript wordt bij get_takes opnieuw geladen
    # _sync_takes op doelscript hier zou duplicate takes kunnen aanmaken
    _sync_takes(src_sid, take['fps'])
    db.update_script_status(src_sid)
    db.update_script_status(target_sid)
    db.update_episode_status(take['episode_id'])

    return jsonify({'ok': True, 'target_script_id': target_sid})

# ── Opnames ───────────────────────────────────────────────────────

@app.route('/api/takes/<int:tid>/recording', methods=['POST'])
def save_recording(tid):
    audio = request.files.get('audio')
    if not audio:
        abort(400)
    with db.get_db() as conn:
        take = db.row_to_dict(conn.execute(
            "SELECT t.*, s.episode_id, s.id as script_id "
            "FROM takes t JOIN scripts s ON s.id=t.script_id WHERE t.id=?",
            (tid,)).fetchone())
        if not take:
            abort(404)

        out_dir  = _output_dir(take['episode_id'], take['script_id'])
        tc_safe  = take['timecode_in'].replace(':', '-')
        filename = f"take_{take['take_index']:03d}_{tc_safe}.webm"
        audio.save(out_dir / filename)

        # Markeer vorige opname als displaced
        conn.execute("UPDATE recordings SET displaced=1 WHERE take_id=?", (tid,))
        conn.execute(
            "INSERT INTO recordings (take_id, filename) VALUES (?,?)",
            (tid, filename))
        conn.execute("UPDATE takes SET status='done' WHERE id=?", (tid,))

    db.update_script_status(take['script_id'])
    db.update_episode_status(take['episode_id'])
    return jsonify({'ok': True, 'file': filename})

@app.route('/api/takes/<int:tid>/recording', methods=['GET'])
def get_recording(tid):
    with db.get_db() as conn:
        rec = db.row_to_dict(conn.execute(
            "SELECT r.*, t.script_id, s.episode_id "
            "FROM recordings r JOIN takes t ON t.id=r.take_id "
            "JOIN scripts s ON s.id=t.script_id "
            "WHERE r.take_id=? AND r.displaced=0 ORDER BY r.id DESC LIMIT 1",
            (tid,)).fetchone())
    if not rec:
        abort(404)
    out_dir = _output_dir(rec['episode_id'], rec['script_id'])
    return send_from_directory(out_dir, rec['filename'])

@app.route('/api/takes/<int:tid>/recording', methods=['DELETE'])
def delete_recording(tid):
    with db.get_db() as conn:
        rec = db.row_to_dict(conn.execute(
            "SELECT r.*, t.script_id, s.episode_id "
            "FROM recordings r JOIN takes t ON t.id=r.take_id "
            "JOIN scripts s ON s.id=t.script_id "
            "WHERE r.take_id=? AND r.displaced=0",
            (tid,)).fetchone())
        if rec:
            out_dir = _output_dir(rec['episode_id'], rec['script_id'])
            fp = out_dir / rec['filename']
            if fp.exists():
                fp.unlink()
            conn.execute("DELETE FROM recordings WHERE take_id=? AND displaced=0", (tid,))
        conn.execute("UPDATE takes SET status='pending' WHERE id=?", (tid,))
        take = db.row_to_dict(conn.execute(
            "SELECT t.script_id, s.episode_id FROM takes t "
            "JOIN scripts s ON s.id=t.script_id WHERE t.id=?", (tid,)).fetchone())
    if take:
        db.update_script_status(take['script_id'])
        db.update_episode_status(take['episode_id'])
    return jsonify({'ok': True})

# ── Zoeken ────────────────────────────────────────────────────────

@app.route('/api/search')
def search():
    q = request.args.get('q', '').strip()
    if len(q) < 2:
        return jsonify([])
    pattern = f'%{q}%'
    with db.get_db() as conn:
        rows = db.rows_to_list(conn.execute("""
            SELECT
                t.id as take_id, t.take_index, t.timecode_in, t.text,
                t.status, t.script_id,
                s.name as script_name, s.episode_id,
                e.code as episode_code, e.title as episode_title,
                sr.name as series_name
            FROM takes t
            JOIN scripts s ON s.id=t.script_id
            JOIN episodes e ON e.id=s.episode_id
            JOIN series sr ON sr.id=e.series_id
            WHERE t.displaced=0 AND t.text LIKE ?
            ORDER BY sr.name, e.code, t.take_index
            LIMIT 100
        """, (pattern,)).fetchall())
    return jsonify(rows)

# ── Video & bestanden ─────────────────────────────────────────────

@app.route('/api/video/<path:filename>')
def serve_video(filename):
    return send_from_directory(VIDEOS_DIR, filename)

@app.route('/api/files/videos')
def list_videos():
    exts = {'.mp4', '.mov', '.avi', '.mkv', '.webm'}
    files = [{'name': f.name, 'size': f.stat().st_size}
             for f in VIDEOS_DIR.iterdir()
             if f.is_file() and f.suffix.lower() in exts]
    return jsonify(sorted(files, key=lambda x: x['name']))

@app.route('/api/files/scripts')
def list_script_files():
    files = [{'name': f.name, 'size': f.stat().st_size}
             for f in SCRIPTS_DIR.iterdir()
             if f.is_file() and f.suffix.lower() in {'.txt', '.md'}]
    return jsonify(sorted(files, key=lambda x: x['name']))

@app.route('/api/upload/video', methods=['POST'])
def upload_video():
    f = request.files.get('file')
    if not f: abort(400)
    safe = Path(f.filename).name
    f.save(VIDEOS_DIR / safe)
    return jsonify({'ok': True, 'name': safe})

@app.route('/api/upload/script', methods=['POST'])
def upload_script():
    f = request.files.get('file')
    if not f: abort(400)
    safe = Path(f.filename).name
    f.save(SCRIPTS_DIR / safe)
    return jsonify({'ok': True, 'name': safe})

@app.route('/scripts/<path:filename>')
def serve_script_file(filename):
    return send_from_directory(SCRIPTS_DIR, filename, mimetype='text/plain')

# ── WAV export ────────────────────────────────────────────────────

def _export_script_wav(sid, sample_rate=None, bit_depth=None, channels=None):
    """
    Exporteer WAV voor één script. Ontbrekende takes = stilte.
    Gooit een Exception bij ffmpeg-fouten.
    """
    import subprocess, tempfile

    with db.get_db() as conn:
        s = db.row_to_dict(conn.execute(
            "SELECT s.*, e.fps, e.video_file, e.id as episode_id "
            "FROM scripts s JOIN episodes e ON e.id=s.episode_id WHERE s.id=?",
            (sid,)).fetchone())
    if not s:
        raise ValueError(f'Script {sid} niet gevonden')

    sample_rate = sample_rate or s.get('export_sample_rate', 48000)
    bit_depth   = bit_depth   or s.get('export_bit_depth', 24)
    channels    = channels    or s.get('export_channels', 1)
    codec       = {16:'pcm_s16le', 24:'pcm_s24le', 32:'pcm_s32le'}.get(bit_depth, 'pcm_s24le')
    sample_fmt  = {16:'s16', 24:'s32', 32:'s32'}.get(bit_depth, 's32')

    takes = db.get_takes(sid)
    if not takes:
        raise ValueError('Geen inzetten gevonden')

    # Videoduur ophalen
    video_dur = None
    if s.get('video_file'):
        try:
            r = subprocess.run(
                ['ffprobe', '-v', 'error', '-show_entries', 'format=duration',
                 '-of', 'default=noprint_wrappers=1:nokey=1',
                 str(VIDEOS_DIR / s['video_file'])],
                capture_output=True, text=True, timeout=30)
            video_dur = float(r.stdout.strip())
        except Exception:
            pass

    total_dur = video_dur or (
        max((t['seconds_out'] or t['seconds_in'] + 5) for t in takes) + 1)

    out_dir  = _output_dir(s['episode_id'], sid)
    tmp_dir  = Path(tempfile.mkdtemp())
    out_name = f"{Path(s['filename']).stem}_{sample_rate//1000}k_{bit_depth}bit.wav"
    out_path = out_dir / out_name

    try:
        inputs, filters = [], []
        for t in takes:
            idx = len(filters)
            if t['recorded_file']:
                src = out_dir / t['recorded_file']
                if src.exists():
                    wav = tmp_dir / f'take_{t["take_index"]:03d}.wav'
                    subprocess.run(
                        ['ffmpeg', '-y', '-i', str(src),
                         '-ar', str(sample_rate), '-ac', str(channels),
                         '-sample_fmt', sample_fmt, str(wav)],
                        capture_output=True, timeout=120)
                    inputs += ['-i', str(wav)]
                    delay_ms = int(t['seconds_in'] * 1000)
                    filters.append(f'[{idx}]adelay={delay_ms}|{delay_ms}[d{t["take_index"]}]')
                    continue

            # Ontbrekende take → genereer stilte met anull
            dur = t['duration'] or 2.0
            inputs += ['-f', 'lavfi', '-i', f'anullsrc=r={sample_rate}:cl={"mono" if channels==1 else "stereo"}']
            delay_ms = int(t['seconds_in'] * 1000)
            filters.append(
                f'[{idx}]atrim=duration={dur:.3f},adelay={delay_ms}|{delay_ms}[d{t["take_index"]}]')

        if not filters:
            raise ValueError('Geen audio om te exporteren')

        mix = ''.join(f'[d{t["take_index"]}]' for t in takes)
        filters.append(f'{mix}amix=inputs={len(takes)}:normalize=0[out]')

        result = subprocess.run(
            ['ffmpeg', '-y'] + inputs + [
                '-filter_complex', ';'.join(filters),
                '-map', '[out]',
                '-ar', str(sample_rate), '-ac', str(channels),
                '-c:a', codec, '-t', str(total_dur), str(out_path)],
            capture_output=True, text=True, timeout=600)
        if result.returncode != 0:
            raise RuntimeError(f'ffmpeg fout: {result.stderr[-300:]}')
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)

    return out_path, out_name

@app.route('/api/scripts/<int:sid>/export-wav', methods=['GET'])
def export_wav(sid):
    import subprocess, tempfile

    sample_rate = int(request.args.get('sample_rate', 48000))
    bit_depth   = int(request.args.get('bit_depth', 24))
    channels    = int(request.args.get('channels', 1))
    try:
        out_path, out_name = _export_script_wav(sid, sample_rate, bit_depth, channels)
    except ValueError as e:
        return jsonify({'error': str(e)}), 400
    except RuntimeError as e:
        return jsonify({'error': str(e)}), 500
    return send_file(str(out_path), as_attachment=True,
                     download_name=out_name, mimetype='audio/wav')

# ── Foutafhandeling ───────────────────────────────────────────────

@app.errorhandler(413)
def too_large(e):
    return jsonify({'error': 'Bestand te groot (max 8 GB)'}), 413

@app.errorhandler(404)
def not_found(e):
    return jsonify({'error': 'Niet gevonden'}), 404

# ── Statische pagina's ────────────────────────────────────────────

@app.route('/')
def studio():
    return send_from_directory('static', 'index.html')

@app.route('/admin')
def admin_page():
    return send_from_directory('static', 'admin.html')

if __name__ == '__main__':
    print('\n🎙  VO Studio  →  http://0.0.0.0:5000')
    print('⚙️   Admin      →  http://0.0.0.0:5000/admin\n')
    app.run(host='0.0.0.0', port=5000, debug=False)
