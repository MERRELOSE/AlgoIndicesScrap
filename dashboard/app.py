import streamlit as st
import sys
from pathlib import Path
sys.path.append(str(Path(__file__).parent))
from style import CUSTOM_CSS

st.set_page_config(page_title="CrashHunter", page_icon="⚡", layout="wide")
st.markdown(CUSTOM_CSS, unsafe_allow_html=True)

ADMIN_PASSWORD = "crashhunter2026"

if 'admin_auth' not in st.session_state:
    st.session_state['admin_auth'] = False

# ============================================================
# HERO
# ============================================================
st.markdown("""
<div class="hero">
    <h1>⚡ CrashHunter</h1>
    <p>Systeme de Trading Algorithmique sur Indices Synthetiques Deriv</p>
    <p style="margin-top:15px;">
        <span class="signal-badge badge-strong">Crash 1000 : +740%</span>&nbsp;
        <span class="signal-badge badge-strong">Crash 900 : +7,689%</span>&nbsp;
        <span class="signal-badge badge-ok">Crash 500 : +506%</span>
    </p>
</div>
""", unsafe_allow_html=True)

# ============================================================
# AUTH
# ============================================================
if st.session_state['admin_auth']:
    st.markdown("""
    <div class="alert-card alert-success">
        ✅ <strong>Connecte en tant qu'Admin</strong> — Utilisez le menu a gauche pour naviguer
    </div>
    """, unsafe_allow_html=True)

    st.markdown("")

    c1, c2, c3, c4 = st.columns(4)
    with c1:
        st.markdown("""
        <div class="metric-card">
            <div class="label">📊 Dashboard</div>
            <div class="value white" style="font-size:1.2em">Vue d'ensemble</div>
            <div class="delta" style="color:#8892a4">KPIs, alertes, revenus</div>
        </div>
        """, unsafe_allow_html=True)
    with c2:
        st.markdown("""
        <div class="metric-card">
            <div class="label">🔑 Licences</div>
            <div class="value white" style="font-size:1.2em">Gestion</div>
            <div class="delta" style="color:#8892a4">Creer, revoquer, renouveler</div>
        </div>
        """, unsafe_allow_html=True)
    with c3:
        st.markdown("""
        <div class="metric-card">
            <div class="label">📡 Signaux</div>
            <div class="value white" style="font-size:1.2em">Monitoring</div>
            <div class="delta" style="color:#8892a4">Sante, evolution, alertes</div>
        </div>
        """, unsafe_allow_html=True)
    with c4:
        st.markdown("""
        <div class="metric-card">
            <div class="label">👤 Client</div>
            <div class="value white" style="font-size:1.2em">Portail</div>
            <div class="delta" style="color:#8892a4">Vue client, performances</div>
        </div>
        """, unsafe_allow_html=True)

    st.markdown("")
    if st.button("🔓 Se deconnecter"):
        st.session_state['admin_auth'] = False
        st.rerun()

else:
    col1, col2 = st.columns(2)

    with col1:
        st.markdown("""
        <div class="metric-card" style="padding:30px;">
            <div class="label">🔐 Espace Admin</div>
            <div class="value white" style="font-size:1.2em;margin-top:15px">Gestion complete</div>
            <div class="delta" style="color:#8892a4">Licences, signaux, revenus</div>
        </div>
        """, unsafe_allow_html=True)

        pwd = st.text_input("Mot de passe", type="password", key="pwd")
        if st.button("Se connecter", type="primary", use_container_width=True):
            if pwd == ADMIN_PASSWORD:
                st.session_state['admin_auth'] = True
                st.rerun()
            else:
                st.error("Mot de passe incorrect")

    with col2:
        st.markdown("""
        <div class="metric-card" style="padding:30px;">
            <div class="label">👤 Espace Client</div>
            <div class="value white" style="font-size:1.2em;margin-top:15px">Votre licence</div>
            <div class="delta" style="color:#8892a4">Statut, performances, renouvellement</div>
        </div>
        """, unsafe_allow_html=True)

        st.markdown("")
        st.markdown("Allez sur **Client Portal** dans le menu a gauche")
