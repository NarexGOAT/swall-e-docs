from flask import Flask, request, jsonify, send_from_directory, send_file
import serial
import serial.tools.list_ports
import matplotlib
matplotlib.use("Agg")  # pas d'affichage fenêtre
import matplotlib.pyplot as plt
import numpy as np
import threading
import time
import io

app = Flask(__name__, static_folder="static")

ser = None
donnees_chargees = {}
sequence_en_cours = {}   # {seq_num: threading.Event}
sequence_statut = {}     # {seq_num: str}

# ─── Utilitaires ──────────────────────────────────────────────────────────────

def lire_txt_contenu(contenu):
    temps, angles = [], []
    for ligne in contenu.splitlines():
        ligne = ligne.strip()
        if not ligne or ligne.startswith("t"):
            continue
        parts = ligne.split(",")
        if len(parts) < 2:
            continue
        try:
            temps.append(int(parts[0].strip()))
            angles.append(int(parts[1].strip()))
        except ValueError:
            continue
    return np.array(temps), np.array(angles)


# ─── Utilitaire graphes matplotlib ───────────────────────────────────────────

COULEURS = ["#2196F3", "#F44336", "#4CAF50", "#FF9800"]

def _generer_image(data):
    fig, axes = plt.subplots(4, 2, figsize=(9, 9))
    fig.patch.set_facecolor("#FAFAFA")

    for i in range(1, 5):
        t, a = data[i]
        vitesse = np.gradient(a.astype(float), t.astype(float)) * 1000
        couleur = COULEURS[i - 1]

        ax_pos = axes[i-1][0]
        ax_vit = axes[i-1][1]

        ax_pos.plot(t, a, color=couleur, linewidth=2)
        ax_pos.set_title(f"Servo {i} — Position (°)", fontsize=14)
        ax_pos.set_ylabel("Angle (°)", fontsize=12)
        ax_pos.set_ylim(-10, 190)
        ax_pos.tick_params(labelsize=11)
        ax_pos.grid(True, alpha=0.3)

        ax_vit.plot(t, vitesse, color=couleur, linestyle="--", linewidth=2)
        ax_vit.set_title(f"Servo {i} — Vitesse (°/s)", fontsize=14)
        ax_vit.set_ylabel("Vitesse (°/s)", fontsize=12)
        ax_vit.set_xlabel("Temps (ms)", fontsize=12)
        ax_vit.tick_params(labelsize=11)
        ax_vit.grid(True, alpha=0.3)

    fig.tight_layout(pad=1.5)

    buf = io.BytesIO()
    fig.savefig(buf, format="png", dpi=120)
    plt.close(fig)
    buf.seek(0)
    return buf


# ─── Routes PWA ───────────────────────────────────────────────────────────────

@app.route("/")
def index():
    return send_from_directory("static", "index.html")

@app.route("/<path:filename>")
def static_files(filename):
    return send_from_directory("static", filename)


# ─── API Connexion ─────────────────────────────────────────────────────────────

@app.route("/api/ports")
def get_ports():
    ports = [p.device for p in serial.tools.list_ports.comports()]
    return jsonify(ports)

@app.route("/api/connect", methods=["POST"])
def connect():
    global ser
    data = request.json
    port = data.get("port", "COM7")
    try:
        if ser and ser.is_open:
            ser.close()
        ser = serial.Serial(port, 9600, timeout=1)
        return jsonify({"ok": True, "message": f"Connecté sur {port}"})
    except Exception as e:
        return jsonify({"ok": False, "message": str(e)}), 500

@app.route("/api/disconnect", methods=["POST"])
def disconnect():
    global ser
    if ser and ser.is_open:
        ser.close()
    return jsonify({"ok": True})

@app.route("/api/status")
def status():
    connected = ser is not None and ser.is_open
    return jsonify({
        "connected": connected,
        "port": ser.port if connected else None,
        "sequences": sequence_statut,
        "predefined": predef_statut
    })


# ─── Séquences prédéfinies ────────────────────────────────────────────────────

def _generer_predef():
    predef = {}

    # Séquence P1 — Position initiale : tous les servos reviennent à 90°
    t = np.linspace(0, 2000, 40, dtype=int)
    predef["P1"] = {
        1: (t, np.linspace(0, 90, 40, dtype=int)),
        2: (t, np.linspace(0, 90, 40, dtype=int)),
        3: (t, np.linspace(0, 90, 40, dtype=int)),
        4: (t, np.linspace(0, 90, 40, dtype=int)),
    }

    # Séquence P2 — Salutation : servo 2 fait un aller-retour (wave)
    t = np.linspace(0, 3000, 60, dtype=int)
    wave = np.concatenate([
        np.linspace(90, 135, 15, dtype=int),
        np.linspace(135, 45, 30, dtype=int),
        np.linspace(45, 90, 15, dtype=int),
    ])
    predef["P2"] = {
        1: (t, np.full(60, 90, dtype=int)),
        2: (t, wave),
        3: (t, np.full(60, 90, dtype=int)),
        4: (t, np.full(60, 45, dtype=int)),
    }

    return predef

SEQUENCES_PREDEF = _generer_predef()
predef_statut = {"P1": "pret", "P2": "pret"}
predef_en_cours = {}


def _run_predef(nom, stop_event):
    data = SEQUENCES_PREDEF[nom]
    temps = data[1][0]
    nb_pas = len(temps)
    for i in range(nb_pas):
        if stop_event.is_set():
            break
        a1, a2, a3, a4 = (data[j][1][i] for j in range(1, 5))
        try:
            ser.write(f"{a1},{a2},{a3},{a4}\n".encode())
        except Exception:
            break
        if i < nb_pas - 1:
            ecart = (temps[i+1] - temps[i]) / 1000.0
            time.sleep(ecart)
    predef_statut[nom] = "arretee" if stop_event.is_set() else "terminee"


@app.route("/api/predefined/<nom>/launch", methods=["POST"])
def launch_predef(nom):
    if nom not in SEQUENCES_PREDEF:
        return jsonify({"ok": False, "message": "Séquence inconnue"}), 404
    if not ser or not ser.is_open:
        return jsonify({"ok": False, "message": "Arduino non connecté"}), 400

    if nom in predef_en_cours:
        predef_en_cours[nom].set()

    stop_event = threading.Event()
    predef_en_cours[nom] = stop_event
    predef_statut[nom] = "en_cours"

    threading.Thread(target=_run_predef, args=(nom, stop_event), daemon=True).start()
    return jsonify({"ok": True, "message": f"Séquence {nom} lancée"})


@app.route("/api/predefined/<nom>/stop", methods=["POST"])
def stop_predef(nom):
    if nom in predef_en_cours:
        predef_en_cours[nom].set()
    predef_statut[nom] = "arretee"
    return jsonify({"ok": True, "message": f"Séquence {nom} arrêtée"})


# ─── API Séquences ────────────────────────────────────────────────────────────

@app.route("/api/sequences/<int:n>/upload", methods=["POST"])
def upload_sequence(n):
    fichiers = {}
    for i in range(1, 5):
        key = f"servo{i}"
        if key not in request.files:
            return jsonify({"ok": False, "message": f"Fichier servo{i} manquant"}), 400
        f = request.files[key]
        contenu = f.read().decode("utf-8", errors="ignore")
        t, a = lire_txt_contenu(contenu)
        if len(t) == 0:
            return jsonify({"ok": False, "message": f"Fichier servo{i} vide ou invalide"}), 400
        fichiers[i] = (t, a)

    donnees_chargees[n] = fichiers
    sequence_statut[n] = "chargee"
    return jsonify({"ok": True, "message": f"Séquence {n} chargée"})


@app.route("/api/sequences/<int:n>/launch", methods=["POST"])
def launch_sequence(n):
    if n not in donnees_chargees:
        return jsonify({"ok": False, "message": "Séquence non chargée"}), 400
    if not ser or not ser.is_open:
        return jsonify({"ok": False, "message": "Arduino non connecté"}), 400

    # Arrêter si déjà en cours
    if n in sequence_en_cours:
        sequence_en_cours[n].set()

    stop_event = threading.Event()
    sequence_en_cours[n] = stop_event
    sequence_statut[n] = "en_cours"

    def run():
        data = donnees_chargees[n]
        temps = data[1][0]
        nb_pas = len(temps)
        for i in range(nb_pas):
            if stop_event.is_set():
                break
            a1, a2, a3, a4 = (data[j][1][i] for j in range(1, 5))
            try:
                ser.write(f"{a1},{a2},{a3},{a4}\n".encode())
            except Exception:
                break
            if i < nb_pas - 1:
                ecart = (temps[i+1] - temps[i]) / 1000.0
                time.sleep(ecart)
        sequence_statut[n] = "arretee" if stop_event.is_set() else "terminee"

    threading.Thread(target=run, daemon=True).start()
    return jsonify({"ok": True, "message": f"Séquence {n} lancée"})


@app.route("/api/sequences/<int:n>/stop", methods=["POST"])
def stop_sequence(n):
    if n in sequence_en_cours:
        sequence_en_cours[n].set()
    sequence_statut[n] = "arretee"
    return jsonify({"ok": True, "message": f"Séquence {n} arrêtée"})


# ─── API Graphes matplotlib ───────────────────────────────────────────────────

@app.route("/api/sequences/<int:n>/graph.png")
def get_sequence_graph(n):
    if n not in donnees_chargees:
        return jsonify({"ok": False, "message": "Séquence non chargée"}), 404
    buf = _generer_image(donnees_chargees[n])
    return send_file(buf, mimetype="image/png")

@app.route("/api/predefined/<nom>/graph.png")
def get_predef_graph(nom):
    if nom not in SEQUENCES_PREDEF:
        return jsonify({"ok": False, "message": "Séquence inconnue"}), 404
    buf = _generer_image(SEQUENCES_PREDEF[nom])
    return send_file(buf, mimetype="image/png")


if __name__ == "__main__":
    print("Serveur PWA démarré → http://0.0.0.0:5000")
    print("Ouvrez http://<IP-PC>:5000 sur votre smartphone (même réseau Wi-Fi)")
    app.run(host="0.0.0.0", port=5000, debug=False)
