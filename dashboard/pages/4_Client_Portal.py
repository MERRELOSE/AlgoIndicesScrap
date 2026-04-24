import streamlit as st
import pandas as pd
import json
from pathlib import Path
from datetime import datetime
import sys

sys.path.append(str(Path(__file__).parent.parent))
from style import CUSTOM_CSS, metric_card, alert_card, section_header

st.set_page_config(page_title="Espace Client", page_icon="👤", layout="wide")
st.markdown(CUSTOM_CSS, unsafe_allow_html=True)

LICENSE_DB = Path(__file__).parent.parent.parent / 'MT5_EA' / 'license' / 'licenses_db.json'
MONITOR_DIR = Path(__file__).parent.parent.parent / 'data' / 'monitoring'

def load_licenses():
    if LICENSE_DB.exists():
        with open(LICENSE_DB) as f:
            return json.load(f).get('licenses', [])
    return []

# ============================================================
# HEADER
# ============================================================
st.markdown("""
<div class="hero">
    <h1>⚡ CrashHunter</h1>
    <p>Espace Client</p>
</div>
""", unsafe_allow_html=True)

# ============================================================
# LICENSE INPUT
# ============================================================
key_input = st.text_input("🔑 Entrez votre cle de licence", placeholder="XXXX-XXXX-XXXX-XXXX")

if not key_input:
    # Show public info
    st.markdown(section_header("Performances Backtestees"), unsafe_allow_html=True)

    c1, c2, c3 = st.columns(3)
    with c1:
        st.markdown("""
        <div class="pricing-card">
            <div class="plan">Crash 1000</div>
            <div class="price">+740%</div>
            <div class="period">15 mois de backtest</div>
            <div style="margin-top:15px;color:#8892a4;">
                PF 1.89 | 87% mois rentables<br>
                Max DD 34% | Sharpe 2.84
            </div>
        </div>
        """, unsafe_allow_html=True)
    with c2:
        st.markdown("""
        <div class="pricing-card" style="border-color:#00d4aa44;">
            <div class="plan">Crash 900</div>
            <div class="price" style="color:#45b7d1;">+7,689%</div>
            <div class="period">19 mois de backtest</div>
            <div style="margin-top:15px;color:#8892a4;">
                PF 1.51 | 89% mois rentables<br>
                Sharpe 2.84 | Recovery 9.05
            </div>
        </div>
        """, unsafe_allow_html=True)
    with c3:
        st.markdown("""
        <div class="pricing-card">
            <div class="plan">Crash 500</div>
            <div class="price">+506%</div>
            <div class="period">12 mois de backtest</div>
            <div style="margin-top:15px;color:#8892a4;">
                PF 1.61 | 75% mois rentables<br>
                Win rate 47%
            </div>
        </div>
        """, unsafe_allow_html=True)

    st.markdown("")
    st.markdown(section_header("Abonnements"), unsafe_allow_html=True)

    c1, c2, c3 = st.columns(3)
    with c1:
        st.markdown("""
        <div class="pricing-card">
            <div class="plan">Starter</div>
            <div class="price">$70</div>
            <div class="period">3 mois</div>
            <div style="margin-top:15px;color:#8892a4;">
                1 EA au choix<br>
                Support par message<br>
                Mises a jour incluses
            </div>
        </div>
        """, unsafe_allow_html=True)
    with c2:
        st.markdown("""
        <div class="pricing-card" style="border-color:#00d4aa;">
            <div style="background:#00d4aa;color:#000;display:inline-block;padding:3px 12px;border-radius:10px;font-size:0.8em;font-weight:700;margin-bottom:10px;">POPULAIRE</div>
            <div class="plan">Pro</div>
            <div class="price">$100</div>
            <div class="period">6 mois</div>
            <div style="margin-top:15px;color:#8892a4;">
                Tous les EAs inclus<br>
                Support prioritaire<br>
                Mises a jour incluses
            </div>
        </div>
        """, unsafe_allow_html=True)
    with c3:
        st.markdown("""
        <div class="pricing-card">
            <div class="plan">Ultimate</div>
            <div class="price">$150</div>
            <div class="period">12 mois</div>
            <div style="margin-top:15px;color:#8892a4;">
                Tous les EAs inclus<br>
                Support VIP<br>
                Conseils personnalises
            </div>
        </div>
        """, unsafe_allow_html=True)

    st.markdown("")
    st.markdown(section_header("Contact"), unsafe_allow_html=True)
    st.markdown("""
    <div class="alert-card alert-info">
        📱 <strong>Pour obtenir votre licence :</strong><br>
        WhatsApp : +XX XXX XXX XXX<br>
        Telegram : @CrashHunterBot<br>
        Email : contact@crashhunter.com
    </div>
    """, unsafe_allow_html=True)

    st.markdown("""
    <div style="text-align:center;color:#8892a4;margin-top:30px;font-size:0.9em;">
        <em>Les performances passees ne garantissent pas les resultats futurs. Le trading comporte des risques.</em>
    </div>
    """, unsafe_allow_html=True)

    st.stop()

# ============================================================
# FIND LICENSE
# ============================================================
licenses = load_licenses()
found = None
for lic in licenses:
    if lic['key'] == key_input:
        found = lic
        break

if not found:
    st.markdown(alert_card("❌ Cle de licence non trouvee. Verifiez votre cle.", "danger"), unsafe_allow_html=True)
    st.stop()

days_left = (datetime.strptime(found['expiry'], '%Y.%m.%d') - datetime.now()).days
is_active = found['status'] == 'active' and days_left > 0

# ============================================================
# LICENSE STATUS
# ============================================================
if is_active:
    card_class = "license-card"
    if days_left > 14:
        st.markdown(alert_card(f"✅ Licence <strong>active</strong> — Expire le {found['expiry']} ({days_left} jours restants)", "success"), unsafe_allow_html=True)
    elif days_left > 7:
        st.markdown(alert_card(f"⚠ Votre licence expire dans <strong>{days_left} jours</strong>. Pensez a renouveler !", "warning"), unsafe_allow_html=True)
    else:
        st.markdown(alert_card(f"🚨 URGENT : Votre licence expire dans <strong>{days_left} jour(s)</strong> ! Renouvelez maintenant.", "danger"), unsafe_allow_html=True)
else:
    card_class = "license-card expired"
    if found['status'] == 'revoked':
        st.markdown(alert_card("🔴 Votre licence a ete <strong>revoquee</strong>. Contactez l'administrateur.", "danger"), unsafe_allow_html=True)
    else:
        st.markdown(alert_card(f"🔴 Votre licence a <strong>expire</strong> le {found['expiry']}. Contactez l'administrateur pour renouveler.", "danger"), unsafe_allow_html=True)

# ============================================================
# LICENSE DETAILS
# ============================================================
st.markdown("")
c1, c2, c3, c4 = st.columns(4)
with c1:
    st.markdown(metric_card("Client", found.get('client', '-'), color="white"), unsafe_allow_html=True)
with c2:
    st.markdown(metric_card("Compte", str(found['account']), color="blue"), unsafe_allow_html=True)
with c3:
    color = "green" if days_left > 14 else "yellow" if days_left > 0 else "red"
    st.markdown(metric_card("Jours Restants", str(max(0, days_left)), found['expiry'], color), unsafe_allow_html=True)
with c4:
    st.markdown(metric_card("Abonnement", f"{found.get('months', 3)} mois", color="purple"), unsafe_allow_html=True)

# ============================================================
# SYSTEM HEALTH (limited view)
# ============================================================
st.markdown(section_header("Etat du Systeme"), unsafe_allow_html=True)

for symbol in ['Crash 1000 Index', 'Crash 900 Index']:
    safe = symbol.replace(' ', '_')
    fpath = MONITOR_DIR / f'{safe}_history.json'
    if fpath.exists():
        with open(fpath) as f:
            history = json.load(f)
        if history:
            signals = history[-1].get('signals', {})
            healthy = sum(1 for s in signals.values() if isinstance(s, dict) and s.get('status') in ['STRONG', 'OK'])
            total = sum(1 for s in signals.values() if isinstance(s, dict) and 'status' in s)

            if total > 0:
                pct = healthy / total * 100
                color = "green" if pct > 80 else "yellow" if pct > 60 else "red"
                icon = "🟢" if pct > 80 else "🟡" if pct > 60 else "🔴"
                st.markdown(f"""
                <div style="background:#111827;border:1px solid #1e2d3d;border-radius:10px;padding:15px 20px;margin:5px 0;display:flex;justify-content:space-between;align-items:center;">
                    <span style="color:#e8eaed;font-weight:600;">{icon} {symbol}</span>
                    <span class="signal-badge badge-{'strong' if pct>80 else 'ok' if pct>60 else 'weak'}">{pct:.0f}% signaux sains</span>
                </div>
                """, unsafe_allow_html=True)

# ============================================================
# FOOTER
# ============================================================
st.markdown("""
<div style="text-align:center;color:#8892a4;margin-top:40px;font-size:0.85em;">
    <em>CrashHunter — Trading algorithmique sur indices synthetiques Deriv</em><br>
    <em>Les performances passees ne garantissent pas les resultats futurs.</em>
</div>
""", unsafe_allow_html=True)
