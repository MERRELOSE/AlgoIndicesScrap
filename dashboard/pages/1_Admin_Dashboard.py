import streamlit as st
import pandas as pd
import plotly.graph_objects as go
import json
from pathlib import Path
from datetime import datetime, timedelta
import sys

sys.path.append(str(Path(__file__).parent.parent))
from style import CUSTOM_CSS, metric_card, alert_card, section_header

st.set_page_config(page_title="Admin Dashboard", page_icon="📊", layout="wide")
st.markdown(CUSTOM_CSS, unsafe_allow_html=True)

if not st.session_state.get('admin_auth'):
    st.warning("Connectez-vous depuis la page d'accueil")
    st.stop()

MONITOR_DIR = Path(__file__).parent.parent.parent / 'data' / 'monitoring'
LICENSE_DB = Path(__file__).parent.parent.parent / 'MT5_EA' / 'license' / 'licenses_db.json'
AFFILIATE_DB = Path(__file__).parent.parent.parent / 'data' / 'affiliates.json'

PRICES = {3: 70, 6: 100, 12: 150}

def load_licenses():
    if LICENSE_DB.exists():
        with open(LICENSE_DB) as f:
            return json.load(f).get('licenses', [])
    return []

def load_affiliates():
    if AFFILIATE_DB.exists():
        with open(AFFILIATE_DB) as f:
            return json.load(f)
    return {"affiliates": [], "referrals": []}

def load_monitoring(symbol):
    safe = symbol.replace(' ', '_')
    fpath = MONITOR_DIR / f'{safe}_history.json'
    if fpath.exists():
        with open(fpath) as f:
            return json.load(f)
    return []

# ============================================================
# DATA
# ============================================================
licenses = load_licenses()
aff_db = load_affiliates()
referrals = aff_db.get('referrals', [])

now = datetime.now()
active = [l for l in licenses if l.get('status') == 'active' and (datetime.strptime(l['expiry'], '%Y.%m.%d') - now).days > 0]
expired = [l for l in licenses if l.get('status') == 'expired' or (l.get('status') == 'active' and (datetime.strptime(l['expiry'], '%Y.%m.%d') - now).days <= 0)]
expiring = [l for l in active if (datetime.strptime(l['expiry'], '%Y.%m.%d') - now).days <= 14]

# Revenue calculations
total_revenue = sum(PRICES.get(l.get('months', 3), 70) for l in licenses)
total_commissions = sum(r.get('commission', 0) for r in referrals)
net_revenue = total_revenue - total_commissions

# Monthly revenue
monthly_rev = {}
for l in licenses:
    month = l.get('created', '')[:7]
    if month:
        price = PRICES.get(l.get('months', 3), 70)
        monthly_rev[month] = monthly_rev.get(month, 0) + price

n_months = max(1, len(monthly_rev))
monthly_avg = total_revenue / n_months

# This month
this_month = now.strftime('%Y-%m')
this_month_rev = monthly_rev.get(this_month, 0)

# ============================================================
# HEADER + FILTERS
# ============================================================
col_title, col_filter = st.columns([3, 1])
with col_title:
    st.markdown('<div class="section-header" style="font-size:1.8em;border:none;">📊 Admin Dashboard</div>', unsafe_allow_html=True)
with col_filter:
    period_filter = st.selectbox("Periode", ["Tout", "Ce mois", "3 derniers mois", "6 derniers mois", "Cette annee"], label_visibility="collapsed")

# Filter licenses by period
if period_filter == "Ce mois":
    filtered = [l for l in licenses if l.get('created', '').startswith(this_month)]
elif period_filter == "3 derniers mois":
    cutoff = (now - timedelta(days=90)).strftime('%Y-%m')
    filtered = [l for l in licenses if l.get('created', '')[:7] >= cutoff]
elif period_filter == "6 derniers mois":
    cutoff = (now - timedelta(days=180)).strftime('%Y-%m')
    filtered = [l for l in licenses if l.get('created', '')[:7] >= cutoff]
elif period_filter == "Cette annee":
    filtered = [l for l in licenses if l.get('created', '').startswith(str(now.year))]
else:
    filtered = licenses

filtered_rev = sum(PRICES.get(l.get('months', 3), 70) for l in filtered)
filtered_commissions = sum(r.get('commission', 0) for r in referrals if period_filter == "Tout" or True)

# ============================================================
# 3 BIG CARDS (top)
# ============================================================
st.markdown("")

c1, c2, c3 = st.columns(3)

with c1:
    st.markdown(f"""
    <div style="background:linear-gradient(135deg, #0a1929 0%, #1a2332 100%);border:1px solid #45b7d133;border-radius:15px;padding:30px;text-align:center;">
        <div style="color:#8892a4;font-size:0.9em;text-transform:uppercase;letter-spacing:2px;">Licences Actives</div>
        <div style="font-size:3.5em;font-weight:800;color:#45b7d1;margin:10px 0;">{len(active)}</div>
        <div style="display:flex;justify-content:space-around;margin-top:15px;">
            <div>
                <div style="color:#8892a4;font-size:0.8em;">Total</div>
                <div style="color:#e8eaed;font-size:1.2em;font-weight:600;">{len(licenses)}</div>
            </div>
            <div>
                <div style="color:#8892a4;font-size:0.8em;">Expirees</div>
                <div style="color:#ff4757;font-size:1.2em;font-weight:600;">{len(expired)}</div>
            </div>
            <div>
                <div style="color:#8892a4;font-size:0.8em;">Expirent bientot</div>
                <div style="color:#ffa502;font-size:1.2em;font-weight:600;">{len(expiring)}</div>
            </div>
        </div>
    </div>
    """, unsafe_allow_html=True)

with c2:
    st.markdown(f"""
    <div style="background:linear-gradient(135deg, #1a0a2e 0%, #1a2332 100%);border:1px solid #a29bfe33;border-radius:15px;padding:30px;text-align:center;">
        <div style="color:#8892a4;font-size:0.9em;text-transform:uppercase;letter-spacing:2px;">Revenue Total</div>
        <div style="font-size:3.5em;font-weight:800;color:#a29bfe;margin:10px 0;">${total_revenue}</div>
        <div style="display:flex;justify-content:space-around;margin-top:15px;">
            <div>
                <div style="color:#8892a4;font-size:0.8em;">Brut</div>
                <div style="color:#a29bfe;font-size:1.2em;font-weight:600;">${total_revenue}</div>
            </div>
            <div>
                <div style="color:#8892a4;font-size:0.8em;">Commissions</div>
                <div style="color:#ff4757;font-size:1.2em;font-weight:600;">-${total_commissions:.0f}</div>
            </div>
            <div>
                <div style="color:#8892a4;font-size:0.8em;">Net</div>
                <div style="color:#00d4aa;font-size:1.2em;font-weight:600;">${net_revenue:.0f}</div>
            </div>
        </div>
    </div>
    """, unsafe_allow_html=True)

with c3:
    st.markdown(f"""
    <div style="background:linear-gradient(135deg, #0d2818 0%, #1a2332 100%);border:1px solid #00d4aa33;border-radius:15px;padding:30px;text-align:center;">
        <div style="color:#8892a4;font-size:0.9em;text-transform:uppercase;letter-spacing:2px;">Revenue Mensuel</div>
        <div style="font-size:3.5em;font-weight:800;color:#00d4aa;margin:10px 0;">${monthly_avg:.0f}</div>
        <div style="display:flex;justify-content:space-around;margin-top:15px;">
            <div>
                <div style="color:#8892a4;font-size:0.8em;">Ce mois</div>
                <div style="color:#e8eaed;font-size:1.2em;font-weight:600;">${this_month_rev}</div>
            </div>
            <div>
                <div style="color:#8892a4;font-size:0.8em;">Moyenne</div>
                <div style="color:#00d4aa;font-size:1.2em;font-weight:600;">${monthly_avg:.0f}</div>
            </div>
            <div>
                <div style="color:#8892a4;font-size:0.8em;">Meilleur mois</div>
                <div style="color:#00d4aa;font-size:1.2em;font-weight:600;">${max(monthly_rev.values()) if monthly_rev else 0}</div>
            </div>
        </div>
    </div>
    """, unsafe_allow_html=True)

st.markdown("")

# ============================================================
# 3 SMALL CARDS (below)
# ============================================================
c4, c5, c6 = st.columns(3)
with c4:
    st.markdown(metric_card("Clients Uniques", len(set(l.get('account') for l in licenses)), color="blue"), unsafe_allow_html=True)
with c5:
    affiliates_count = len(aff_db.get('affiliates', []))
    st.markdown(metric_card("Partenaires", affiliates_count, f"{len(referrals)} parrainages", "purple"), unsafe_allow_html=True)
with c6:
    pending_pay = sum(r.get('commission', 0) for r in referrals if not r.get('paid'))
    st.markdown(metric_card("Commissions a Payer", f"${pending_pay:.0f}", color="yellow"), unsafe_allow_html=True)

# ============================================================
# ALERTS
# ============================================================
st.markdown(section_header("Alertes"), unsafe_allow_html=True)

has_alerts = False

if expiring:
    for l in expiring:
        days = (datetime.strptime(l['expiry'], '%Y.%m.%d') - now).days
        st.markdown(alert_card(
            f"⚠ <strong>{l.get('client', 'Client')}</strong> (compte {l['account']}) — expire dans <strong>{days} jours</strong>",
            "warning"), unsafe_allow_html=True)
        has_alerts = True

for symbol in ['Crash 1000 Index', 'Crash 900 Index', 'Crash 500 Index']:
    history = load_monitoring(symbol)
    if history:
        for a in history[-1].get('alerts', []):
            level = "danger" if a['level'] == 'CRITICAL' else "warning"
            st.markdown(alert_card(f"[{symbol}] {a['message']}", level), unsafe_allow_html=True)
            has_alerts = True

if not has_alerts:
    st.markdown(alert_card("✅ Aucune alerte — Tous les systemes sont operationnels", "success"), unsafe_allow_html=True)

# ============================================================
# SIGNAL HEALTH
# ============================================================
st.markdown(section_header("Sante des Signaux"), unsafe_allow_html=True)

for symbol in ['Crash 1000 Index', 'Crash 900 Index', 'Crash 500 Index']:
    history = load_monitoring(symbol)
    if not history:
        st.markdown(f"""
        <div style="background:#111827;border:1px solid #1e2d3d;border-radius:10px;padding:12px 20px;margin:5px 0;">
            <span style="color:#8892a4;">⚪ {symbol} — Pas de donnees. Lancez le re-entrainement.</span>
        </div>
        """, unsafe_allow_html=True)
        continue

    signals = history[-1].get('signals', {})
    meta = signals.get('_meta', {})

    st.markdown(f"**{symbol}**")
    cols = st.columns(6)
    sigs = ['post_crash_recovery', 'rsi_oversold_bounce', 'squeeze_uptrend', 'ema_cross', 'rsi_momentum']
    labs = ['Post-Crash', 'RSI OS', 'Squeeze+Up', 'EMA Cross', 'RSI Mom']

    for i, (sig, lab) in enumerate(zip(sigs, labs)):
        with cols[i]:
            if sig in signals:
                rate = signals[sig]['rate']
                status = signals[sig]['status']
                color = "green" if status == "STRONG" else "yellow" if status == "OK" else "red"
                st.markdown(metric_card(lab, f"{rate:.1f}%", f"N={signals[sig]['n']}", color), unsafe_allow_html=True)
            else:
                st.markdown(metric_card(lab, "N/A", "", "white"), unsafe_allow_html=True)

    with cols[5]:
        if meta:
            h = meta.get('hurst', 0.5)
            color = "green" if h > 0.6 else "yellow" if h > 0.55 else "red"
            st.markdown(metric_card("Hurst", f"{h:.3f}", "Trending" if h > 0.55 else "Random", color), unsafe_allow_html=True)

    st.markdown("")

# ============================================================
# REVENUE CHART
# ============================================================
st.markdown(section_header("Evolution du Revenue"), unsafe_allow_html=True)

if monthly_rev:
    c1, c2 = st.columns([3, 1])
    with c1:
        rev_df = pd.DataFrame(sorted(monthly_rev.items()), columns=['Mois', 'Revenue'])
        rev_df['Cumul'] = rev_df['Revenue'].cumsum()

        fig = go.Figure()
        fig.add_trace(go.Bar(x=rev_df['Mois'], y=rev_df['Revenue'],
                             name='Mensuel', marker_color='#a29bfe', marker_line_width=0))
        fig.add_trace(go.Scatter(x=rev_df['Mois'], y=rev_df['Cumul'],
                                  name='Cumule', line=dict(color='#00d4aa', width=3), yaxis='y2'))

        fig.update_layout(
            plot_bgcolor='rgba(0,0,0,0)', paper_bgcolor='rgba(0,0,0,0)',
            font_color='#8892a4', height=350,
            margin=dict(l=0, r=0, t=10, b=0),
            yaxis=dict(gridcolor='#1e2d3d', title='Mensuel ($)'),
            yaxis2=dict(title='Cumule ($)', overlaying='y', side='right', showgrid=False),
            legend=dict(orientation='h', y=1.1),
        )
        st.plotly_chart(fig, use_container_width=True)

    with c2:
        st.markdown(f"""
        <div class="revenue-card">
            <div style="color:#8892a4;font-size:0.85em;text-transform:uppercase;">Revenue Net</div>
            <div class="amount">${net_revenue:.0f}</div>
            <div style="color:#8892a4;margin-top:15px;font-size:0.9em;">
                {len(licenses)} ventes<br>
                ${monthly_avg:.0f}/mois moyen<br>
                <span style="color:#ff4757;">-${total_commissions:.0f} commissions</span>
            </div>
        </div>
        """, unsafe_allow_html=True)

# ============================================================
# RECENT LICENSES
# ============================================================
st.markdown(section_header("Dernieres Licences"), unsafe_allow_html=True)

for lic in sorted(licenses, key=lambda x: x.get('created', ''), reverse=True)[:8]:
    days = (datetime.strptime(lic['expiry'], '%Y.%m.%d') - now).days
    if lic.get('status') == 'revoked':
        badge = '<span class="signal-badge badge-weak">Revoquee</span>'
    elif days <= 0:
        badge = '<span class="signal-badge badge-weak">Expiree</span>'
    elif days <= 7:
        badge = '<span class="signal-badge badge-ok">Expire bientot</span>'
    else:
        badge = '<span class="signal-badge badge-strong">Active</span>'

    price = PRICES.get(lic.get('months', 3), 70)

    st.markdown(f"""
    <div style="background:#111827;border:1px solid #1e2d3d;border-radius:10px;padding:12px 20px;margin:5px 0;display:flex;justify-content:space-between;align-items:center;">
        <span style="color:#e8eaed;width:25%;"><strong>{lic.get('client', 'Client')}</strong></span>
        <span style="color:#8892a4;width:15%;">Compte {lic['account']}</span>
        <span style="color:#a29bfe;width:10%;">${price}</span>
        <span style="color:#8892a4;width:20%;">{lic['expiry']} ({days}j)</span>
        <span style="width:15%;text-align:right;">{badge}</span>
    </div>
    """, unsafe_allow_html=True)
