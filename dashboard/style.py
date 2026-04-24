"""Shared styles and components for the dashboard"""

CUSTOM_CSS = """
<style>
    /* Global */
    .stApp { background-color: #0a0e17; }
    section[data-testid="stSidebar"] { background-color: #0d1321; border-right: 1px solid #1a2332; }

    /* Cards */
    .metric-card {
        background: linear-gradient(135deg, #111827 0%, #1a2332 100%);
        border: 1px solid #1e2d3d;
        border-radius: 12px;
        padding: 20px;
        text-align: center;
        transition: all 0.3s;
    }
    .metric-card:hover { border-color: #00d4aa; transform: translateY(-2px); }
    .metric-card .value { font-size: 2em; font-weight: 700; margin: 5px 0; }
    .metric-card .label { font-size: 0.85em; color: #8892a4; text-transform: uppercase; letter-spacing: 1px; }
    .metric-card .delta { font-size: 0.8em; margin-top: 5px; }

    /* Colors */
    .green { color: #00d4aa; }
    .red { color: #ff4757; }
    .yellow { color: #ffa502; }
    .blue { color: #45b7d1; }
    .purple { color: #a29bfe; }
    .white { color: #e8eaed; }

    /* Section headers */
    .section-header {
        font-size: 1.3em;
        font-weight: 600;
        color: #e8eaed;
        margin: 30px 0 15px 0;
        padding-bottom: 8px;
        border-bottom: 2px solid #1e2d3d;
    }

    /* Alert cards */
    .alert-card {
        border-radius: 10px;
        padding: 15px 20px;
        margin: 8px 0;
        border-left: 4px solid;
    }
    .alert-success { background: #0d2818; border-color: #00d4aa; color: #00d4aa; }
    .alert-warning { background: #2d1f00; border-color: #ffa502; color: #ffa502; }
    .alert-danger { background: #2d0a0a; border-color: #ff4757; color: #ff4757; }
    .alert-info { background: #0a1929; border-color: #45b7d1; color: #45b7d1; }

    /* Table styling */
    .styled-table {
        background: #111827;
        border-radius: 10px;
        overflow: hidden;
    }

    /* License card */
    .license-card {
        background: linear-gradient(135deg, #0d2818 0%, #111827 100%);
        border: 1px solid #00d4aa33;
        border-radius: 15px;
        padding: 25px;
        margin: 10px 0;
    }
    .license-card.expired {
        background: linear-gradient(135deg, #2d0a0a 0%, #111827 100%);
        border-color: #ff475733;
    }

    /* Revenue card */
    .revenue-card {
        background: linear-gradient(135deg, #1a0a2e 0%, #111827 100%);
        border: 1px solid #a29bfe33;
        border-radius: 15px;
        padding: 25px;
        text-align: center;
    }
    .revenue-card .amount { font-size: 2.5em; font-weight: 700; color: #a29bfe; }

    /* Hero section */
    .hero {
        background: linear-gradient(135deg, #0d1321 0%, #1a0a2e 50%, #0a1929 100%);
        border-radius: 20px;
        padding: 40px;
        text-align: center;
        border: 1px solid #1e2d3d;
        margin-bottom: 30px;
    }
    .hero h1 { font-size: 2.5em; margin: 0; background: linear-gradient(90deg, #00d4aa, #45b7d1); -webkit-background-clip: text; -webkit-text-fill-color: transparent; }
    .hero p { color: #8892a4; font-size: 1.1em; }

    /* Signal badge */
    .signal-badge {
        display: inline-block;
        padding: 4px 12px;
        border-radius: 20px;
        font-size: 0.8em;
        font-weight: 600;
    }
    .badge-strong { background: #00d4aa22; color: #00d4aa; border: 1px solid #00d4aa44; }
    .badge-ok { background: #ffa50222; color: #ffa502; border: 1px solid #ffa50244; }
    .badge-weak { background: #ff475722; color: #ff4757; border: 1px solid #ff475744; }

    /* Pricing card */
    .pricing-card {
        background: linear-gradient(135deg, #111827 0%, #1a2332 100%);
        border: 1px solid #1e2d3d;
        border-radius: 15px;
        padding: 30px;
        text-align: center;
        transition: all 0.3s;
    }
    .pricing-card:hover { border-color: #00d4aa; }
    .pricing-card .price { font-size: 2.2em; font-weight: 700; color: #00d4aa; }
    .pricing-card .plan { font-size: 1.2em; color: #e8eaed; margin-bottom: 10px; }
    .pricing-card .period { color: #8892a4; }

    /* Hide streamlit branding */
    #MainMenu { visibility: hidden; }
    footer { visibility: hidden; }
    header { visibility: hidden; }
</style>
"""

def metric_card(label, value, delta="", color="green"):
    delta_html = f'<div class="delta {color}">{delta}</div>' if delta else ''
    return f"""
    <div class="metric-card">
        <div class="label">{label}</div>
        <div class="value {color}">{value}</div>
        {delta_html}
    </div>
    """

def alert_card(message, level="info"):
    return f'<div class="alert-card alert-{level}">{message}</div>'

def section_header(text):
    return f'<div class="section-header">{text}</div>'
