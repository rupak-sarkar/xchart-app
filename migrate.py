"""migrate.py — Phase 1: Firebase Auth + Save Strategies + 15 Presets"""

import subprocess
import re
from pathlib import Path


def main():
    print("=" * 70)
    print("  PHASE 1 MIGRATION — Auth + Strategies + Presets")
    print("=" * 70)

    print("\n[1/5] Creating firebase-config.js...")
    create_firebase_config()

    print("\n[2/5] Creating auth.js...")
    create_auth()

    print("\n[3/5] Creating strategies.html...")
    create_strategies_page()

    print("\n[4/5] Patching index.html...")
    patch_index()

    print("\n[5/5] Patching backtest.js...")
    patch_backtest()

    print("\nStaging...")
    subprocess.run(["git", "add", "-A"], capture_output=True)

    print("\n" + "=" * 70)
    print("  MIGRATION COMPLETE")
    print("=" * 70)
    print("""
  Files Created:
    ✅ firebase-config.js    — Firebase project config
    ✅ auth.js               — Auth + Firestore CRUD + UI logic
    ✅ strategies.html       — My Strategies page

  Files Patched:
    ✅ index.html            — Firebase SDK, auth header, save modal
    ✅ backtest.js           — 15 presets, save button, indicator limit

  Test:
    1. Deploy to Cloudflare/GitHub Pages
    2. Open xchart.in → should see Login button
    3. Click Login → Google sign-in
    4. Run backtest → see Save Strategy button
    5. Open /strategies.html → see My Strategies page
""")


# ══════════════════════════════════════════════════════════════
# 1. FIREBASE CONFIG
# ══════════════════════════════════════════════════════════════

def create_firebase_config():
    content = """/**
 * firebase-config.js — xchart.in Firebase Configuration
 * This file is safe to expose — security is handled by Firestore rules
 */

var FIREBASE_CONFIG = {
  apiKey: "AIzaSyACdec5CvH-RGEzrnATNmqn5mxFqT0pDpI",
  authDomain: "xchart-app.firebaseapp.com",
  projectId: "xchart-app",
  storageBucket: "xchart-app.firebasestorage.app",
  messagingSenderId: "1059697743071",
  appId: "1:1059697743071:web:526a255c7d2a56f825c56a"
};
"""
    Path("firebase-config.js").write_text(content, encoding="utf-8")
    print("  ✅ firebase-config.js created")


# ══════════════════════════════════════════════════════════════
# 2. AUTH.JS — Auth + Firestore + UI State
# ══════════════════════════════════════════════════════════════

def create_auth():
    content = r"""/**
 * auth.js — xchart.in Authentication & Strategy Storage
 * Firebase Auth (Google + Email) + Firestore CRUD
 */

var XAuth = {
  user: null,
  tier: 'free',  // 'free' | 'analyst' | 'pro'
  strategies: [],
  maxIndicators: { free: 5, analyst: 7, pro: 10 },
  maxStrategies: { free: 0, analyst: 15, pro: 50 },
  db: null,
  ready: false
};

// ═══════════════════════════════════════════
// INIT
// ═══════════════════════════════════════════

function initAuth() {
  if (typeof firebase === 'undefined') {
    console.warn('Firebase SDK not loaded');
    updateAuthUI();
    return;
  }

  firebase.initializeApp(FIREBASE_CONFIG);
  XAuth.db = firebase.firestore();

  firebase.auth().onAuthStateChanged(function(user) {
    XAuth.user = user;
    XAuth.ready = true;

    if (user) {
      console.log('Logged in:', user.email);
      loadUserTier();
      loadStrategies();
    } else {
      console.log('Not logged in');
      XAuth.tier = 'free';
      XAuth.strategies = [];
    }
    updateAuthUI();
    updateIndicatorLimit();
  });
}

// ═══════════════════════════════════════════
// LOGIN / LOGOUT
// ═══════════════════════════════════════════

function loginWithGoogle() {
  var provider = new firebase.auth.GoogleAuthProvider();
  firebase.auth().signInWithPopup(provider).catch(function(err) {
    console.error('Google login error:', err);
    if (err.code === 'auth/popup-blocked') {
      alert('Popup blocked. Please allow popups for this site.');
    }
  });
}

function loginWithEmail(email, password, isSignUp) {
  if (isSignUp) {
    firebase.auth().createUserWithEmailAndPassword(email, password)
      .catch(function(err) { alert(err.message); });
  } else {
    firebase.auth().signInWithEmailAndPassword(email, password)
      .catch(function(err) { alert(err.message); });
  }
}

function logout() {
  firebase.auth().signOut();
}

// ═══════════════════════════════════════════
// TIER MANAGEMENT
// ═══════════════════════════════════════════

function loadUserTier() {
  if (!XAuth.user || !XAuth.db) return;

  XAuth.db.collection('users').doc(XAuth.user.uid).get()
    .then(function(doc) {
      if (doc.exists) {
        XAuth.tier = doc.data().tier || 'free';
        // Update last login
        XAuth.db.collection('users').doc(XAuth.user.uid).update({
          lastLogin: firebase.firestore.FieldValue.serverTimestamp()
        });
      } else {
        // New user — create profile
        XAuth.tier = 'free';
        XAuth.db.collection('users').doc(XAuth.user.uid).set({
          email: XAuth.user.email,
          displayName: XAuth.user.displayName || '',
          tier: 'free',
          createdAt: firebase.firestore.FieldValue.serverTimestamp(),
          lastLogin: firebase.firestore.FieldValue.serverTimestamp()
        });
      }
      updateAuthUI();
      updateIndicatorLimit();
    })
    .catch(function(err) { console.error('Tier load error:', err); });
}

function getMaxIndicators() {
  return XAuth.maxIndicators[XAuth.tier] || 5;
}

function getMaxStrategies() {
  return XAuth.maxStrategies[XAuth.tier] || 0;
}

// ═══════════════════════════════════════════
// STRATEGY CRUD
// ═══════════════════════════════════════════

function loadStrategies() {
  if (!XAuth.user || !XAuth.db) return;

  XAuth.db.collection('users').doc(XAuth.user.uid)
    .collection('strategies').orderBy('updatedAt', 'desc').get()
    .then(function(snap) {
      XAuth.strategies = [];
      snap.forEach(function(doc) {
        var d = doc.data();
        d.id = doc.id;
        XAuth.strategies.push(d);
      });
      console.log('Loaded', XAuth.strategies.length, 'strategies');
      // Update strategies page if on it
      if (typeof renderStrategiesList === 'function') renderStrategiesList();
    })
    .catch(function(err) { console.error('Load strategies error:', err); });
}

function saveStrategy(name, ticker, config, lastResult) {
  if (!XAuth.user) {
    showLoginModal();
    return Promise.reject('Not logged in');
  }

  var maxS = getMaxStrategies();
  if (maxS <= 0) {
    showUpgradeModal('save');
    return Promise.reject('Upgrade needed');
  }

  if (XAuth.strategies.length >= maxS) {
    showUpgradeModal('limit');
    return Promise.reject('Strategy limit reached');
  }

  var data = {
    name: name,
    ticker: ticker,
    mode: config.mode,
    majorityN: config.majorityN || 3,
    threshold: config.threshold || 20,
    period: config.period || '1y',
    slots: config.slots.map(function(s) {
      return {
        indId: s.indId,
        params: s.params,
        entryCond: s.entryCond,
        exitCond: s.exitCond,
        weight: s.weight
      };
    }),
    exitRules: config.exitRules,
    lastResult: lastResult || null,
    createdAt: firebase.firestore.FieldValue.serverTimestamp(),
    updatedAt: firebase.firestore.FieldValue.serverTimestamp()
  };

  return XAuth.db.collection('users').doc(XAuth.user.uid)
    .collection('strategies').add(data)
    .then(function(ref) {
      data.id = ref.id;
      XAuth.strategies.unshift(data);
      console.log('Strategy saved:', name);
      return ref.id;
    });
}

function deleteStrategy(stratId) {
  if (!XAuth.user || !XAuth.db) return Promise.reject('Not logged in');

  return XAuth.db.collection('users').doc(XAuth.user.uid)
    .collection('strategies').doc(stratId).delete()
    .then(function() {
      XAuth.strategies = XAuth.strategies.filter(function(s) { return s.id !== stratId; });
      console.log('Strategy deleted:', stratId);
    });
}

function updateStrategyResult(stratId, lastResult) {
  if (!XAuth.user || !XAuth.db) return;

  XAuth.db.collection('users').doc(XAuth.user.uid)
    .collection('strategies').doc(stratId).update({
      lastResult: lastResult,
      updatedAt: firebase.firestore.FieldValue.serverTimestamp()
    }).catch(function(err) { console.error('Update error:', err); });
}

// ═══════════════════════════════════════════
// UI STATE MANAGEMENT
// ═══════════════════════════════════════════

function updateAuthUI() {
  var loginBtn = document.getElementById('authLoginBtn');
  var userMenu = document.getElementById('authUserMenu');
  var userName = document.getElementById('authUserName');
  var tierBadge = document.getElementById('authTierBadge');

  if (!loginBtn || !userMenu) return;

  if (XAuth.user) {
    loginBtn.style.display = 'none';
    userMenu.style.display = 'flex';
    if (userName) {
      userName.textContent = XAuth.user.displayName || XAuth.user.email.split('@')[0];
    }
    if (tierBadge) {
      tierBadge.textContent = XAuth.tier === 'free' ? 'FREE' : XAuth.tier.toUpperCase();
      tierBadge.className = 'tier-badge tier-' + XAuth.tier;
    }
  } else {
    loginBtn.style.display = 'inline-flex';
    userMenu.style.display = 'none';
  }
}

function updateIndicatorLimit() {
  var max = getMaxIndicators();
  var addBtn = document.getElementById('btnAddInd');
  if (addBtn && typeof BT !== 'undefined') {
    var current = BT.slots ? BT.slots.length : 0;
    if (current >= max) {
      addBtn.disabled = true;
      addBtn.textContent = XAuth.tier === 'free'
        ? 'Upgrade for more indicators (max ' + max + ')'
        : 'Maximum ' + max + ' indicators';
    }
  }
}

// ═══════════════════════════════════════════
// MODALS
// ═══════════════════════════════════════════

function showLoginModal() {
  var m = document.getElementById('loginModal');
  if (m) m.classList.add('open');
}

function hideLoginModal() {
  var m = document.getElementById('loginModal');
  if (m) m.classList.remove('open');
}

function showSaveModal() {
  if (!XAuth.user) {
    showLoginModal();
    return;
  }
  var maxS = getMaxStrategies();
  if (maxS <= 0) {
    showUpgradeModal('save');
    return;
  }
  if (XAuth.strategies.length >= maxS) {
    showUpgradeModal('limit');
    return;
  }

  var m = document.getElementById('saveModal');
  if (!m) return;

  // Pre-fill
  var nameInput = document.getElementById('saveStratName');
  if (nameInput && typeof BT !== 'undefined' && BT.ticker) {
    var indNames = BT.slots.filter(function(s) { return s.indId; }).map(function(s) {
      return INDICATORS[s.indId] ? INDICATORS[s.indId].name : s.indId;
    });
    nameInput.value = indNames.join(' + ') + ' on ' + BT.ticker;
  }

  var infoEl = document.getElementById('saveStratInfo');
  if (infoEl && typeof BT !== 'undefined') {
    infoEl.innerHTML = '<strong>Ticker:</strong> ' + (BT.ticker || 'N/A') +
      ' · <strong>Mode:</strong> ' + (BT.mode || 'weighted').toUpperCase() +
      ' · <strong>Indicators:</strong> ' + BT.slots.filter(function(s) { return s.indId; }).length;
  }

  var slotsEl = document.getElementById('saveSlotsInfo');
  if (slotsEl) {
    slotsEl.textContent = XAuth.strategies.length + ' of ' + maxS + ' strategy slots used';
  }

  m.classList.add('open');
}

function hideSaveModal() {
  var m = document.getElementById('saveModal');
  if (m) m.classList.remove('open');
}

function doSaveStrategy() {
  var nameInput = document.getElementById('saveStratName');
  var name = nameInput ? nameInput.value.trim() : '';
  if (!name) { alert('Please enter a strategy name'); return; }
  if (!BT.ticker || !BT.ohlcv) { alert('Run a backtest first'); return; }

  var config = {
    mode: BT.mode,
    majorityN: BT.majorityN,
    threshold: parseInt(document.getElementById('entryThreshold').value) || 20,
    period: document.getElementById('period').value,
    slots: BT.slots.filter(function(s) { return s.indId; }),
    exitRules: {
      sl: { enabled: document.getElementById('x_sl').checked, value: parseFloat(document.getElementById('x_sl_val').value) || 3 },
      tp: { enabled: document.getElementById('x_tp').checked, value: parseFloat(document.getElementById('x_tp_val').value) || 8 },
      trail: { enabled: document.getElementById('x_trail').checked, value: parseFloat(document.getElementById('x_trail_val').value) || 2 },
      maxHold: { enabled: document.getElementById('x_maxhold').checked, value: parseInt(document.getElementById('x_maxhold_val').value) || 14 }
    }
  };

  // Get last result if available
  var lastResult = null;
  var kpiEls = document.querySelectorAll('.kpi-v');
  if (kpiEls.length >= 4) {
    lastResult = {
      trades: parseInt(kpiEls[0].textContent) || 0,
      winRate: parseFloat(kpiEls[1].textContent) || 0,
      profitFactor: parseFloat(kpiEls[2].textContent) || 0,
      totalReturn: parseFloat(kpiEls[3].textContent) || 0
    };
  }

  var btn = document.querySelector('#saveModal .save-confirm-btn');
  if (btn) { btn.disabled = true; btn.textContent = 'Saving...'; }

  saveStrategy(name, BT.ticker, config, lastResult)
    .then(function() {
      hideSaveModal();
      showToast('Strategy saved!');
      if (btn) { btn.disabled = false; btn.textContent = 'Save Strategy'; }
    })
    .catch(function(err) {
      console.error(err);
      if (btn) { btn.disabled = false; btn.textContent = 'Save Strategy'; }
    });
}

function showUpgradeModal(reason) {
  var m = document.getElementById('upgradeModal');
  if (!m) return;

  var msgEl = document.getElementById('upgradeMsg');
  if (msgEl) {
    if (reason === 'save') {
      msgEl.innerHTML = 'Saving strategies is an <strong>Analyst</strong> feature. Upgrade to save your best strategies and reuse them anytime.';
    } else if (reason === 'limit') {
      msgEl.innerHTML = 'You\'ve used all ' + getMaxStrategies() + ' strategy slots. Upgrade to save more strategies.';
    } else if (reason === 'indicators') {
      msgEl.innerHTML = 'You\'ve reached the ' + getMaxIndicators() + '-indicator limit. Upgrade for up to ' +
        (XAuth.tier === 'analyst' ? '10' : '7') + ' indicators per backtest.';
    }
  }
  m.classList.add('open');
}

function hideUpgradeModal() {
  var m = document.getElementById('upgradeModal');
  if (m) m.classList.remove('open');
}

function showToast(msg) {
  var t = document.createElement('div');
  t.className = 'toast-msg';
  t.textContent = msg;
  document.body.appendChild(t);
  setTimeout(function() { t.classList.add('show'); }, 10);
  setTimeout(function() {
    t.classList.remove('show');
    setTimeout(function() { t.remove(); }, 300);
  }, 2500);
}

// ═══════════════════════════════════════════
// LOAD STRATEGY INTO BACKTEST PAGE
// ═══════════════════════════════════════════

function loadStrategyIntoBacktest(strat) {
  if (typeof BT === 'undefined' || typeof INDICATORS === 'undefined') return;

  // Set mode
  if (typeof setMode === 'function') setMode(strat.mode || 'weighted');

  // Set majority
  if (strat.majorityN) {
    var majEl = document.getElementById('majorityN');
    if (majEl) { majEl.value = strat.majorityN; BT.majorityN = strat.majorityN; }
  }

  // Set threshold
  var threshEl = document.getElementById('entryThreshold');
  if (threshEl && strat.threshold) threshEl.value = strat.threshold;

  // Set period
  var perEl = document.getElementById('period');
  if (perEl && strat.period) perEl.value = strat.period;

  // Set exit rules
  if (strat.exitRules) {
    var er = strat.exitRules;
    if (er.sl) { document.getElementById('x_sl').checked = er.sl.enabled; document.getElementById('x_sl_val').value = er.sl.value; }
    if (er.tp) { document.getElementById('x_tp').checked = er.tp.enabled; document.getElementById('x_tp_val').value = er.tp.value; }
    if (er.trail) { document.getElementById('x_trail').checked = er.trail.enabled; document.getElementById('x_trail_val').value = er.trail.value; }
    if (er.maxHold) { document.getElementById('x_maxhold').checked = er.maxHold.enabled; document.getElementById('x_maxhold_val').value = er.maxHold.value; }
  }

  // Set indicator slots
  BT.slots = [];
  var slots = strat.slots || [];
  slots.forEach(function(s) {
    BT.slots.push({
      indId: s.indId,
      params: Object.assign({}, s.params),
      entryCond: s.entryCond,
      exitCond: s.exitCond,
      weight: s.weight
    });
  });

  if (typeof renderSlots === 'function') renderSlots();

  // Load ticker
  if (strat.ticker) {
    var searchEl = document.getElementById('tickerSearch');
    if (searchEl) {
      searchEl.value = strat.ticker;
      if (typeof loadOHLCV === 'function') loadOHLCV(strat.ticker);
    }
  }
}

// Init on load
document.addEventListener('DOMContentLoaded', function() {
  // Small delay to ensure Firebase SDK is loaded
  setTimeout(initAuth, 100);
});
"""
    Path("auth.js").write_text(content, encoding="utf-8")
    print("  ✅ auth.js created")

# ══════════════════════════════════════════════════════════════
# 3. STRATEGIES.HTML — My Strategies Page
# ══════════════════════════════════════════════════════════════

def create_strategies_page():
    content = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1.0">
<title>My Strategies | xchart.in</title>
<meta name="description" content="Manage your saved backtesting strategies on xchart.in. Load, run, and refine your trading rules.">
<meta name="robots" content="noindex">
<link rel="canonical" href="https://xchart.in/strategies.html" />
<style>
*{margin:0;padding:0;box-sizing:border-box}
:root{
  --bg:#F8F9FB;--white:#FFFFFF;--card:#FFFFFF;--card2:#F3F4F6;
  --border:#E5E7EB;--text:#1F2937;--text2:#6B7280;--text3:#9CA3AF;
  --accent:#2563EB;--accent-bg:rgba(37,99,235,0.06);
  --bull:#16A34A;--bear:#DC2626;
  --shadow:0 1px 3px rgba(0,0,0,0.06);
  --radius:10px
}
body{font-family:'Inter',system-ui,-apple-system,sans-serif;background:var(--bg);color:var(--text);min-height:100vh}
a{color:var(--accent);text-decoration:none}

/* Header */
.hdr{background:var(--white);border-bottom:1px solid var(--border);padding:10px 20px;display:flex;align-items:center;justify-content:space-between;position:sticky;top:0;z-index:100;box-shadow:var(--shadow)}
.logo{font-size:20px;font-weight:800;color:var(--text);cursor:pointer;text-decoration:none}
.logo span{color:var(--accent)}
.ver{font-size:8px;background:var(--accent);color:#fff;padding:2px 7px;border-radius:10px;margin-left:6px;vertical-align:middle;font-weight:700}
.nav{display:flex;align-items:center;gap:16px;font-size:12px;font-weight:500}
.nav a{color:var(--text2)}
.nav a:hover{color:var(--accent)}
.nav a.active{color:var(--accent);font-weight:700}

/* Auth in header */
.auth-area{display:flex;align-items:center;gap:10px}
.login-btn{padding:6px 16px;background:var(--accent);color:#fff;border:none;border-radius:6px;font-size:11px;font-weight:600;cursor:pointer}
.user-menu{display:none;align-items:center;gap:8px;font-size:11px}
.user-avatar{width:28px;height:28px;border-radius:50%;background:var(--accent);color:#fff;display:flex;align-items:center;justify-content:center;font-weight:700;font-size:11px}
.tier-badge{font-size:8px;padding:2px 6px;border-radius:8px;font-weight:700;text-transform:uppercase}
.tier-free{background:var(--card2);color:var(--text3)}
.tier-analyst{background:rgba(37,99,235,0.1);color:var(--accent)}
.tier-pro{background:rgba(217,119,6,0.1);color:#D97706}
.logout-btn{color:var(--text3);cursor:pointer;font-size:10px;border:none;background:none}
.logout-btn:hover{color:var(--bear)}

/* Main */
.main{max-width:900px;margin:0 auto;padding:24px 20px}
.page-title{font-size:22px;font-weight:800;margin-bottom:4px}
.page-sub{font-size:12px;color:var(--text2);margin-bottom:20px}

/* Login prompt */
.login-prompt{text-align:center;padding:60px 24px;background:var(--white);border:1px solid var(--border);border-radius:var(--radius);margin-top:20px}
.login-prompt h2{font-size:18px;margin-bottom:8px}
.login-prompt p{font-size:13px;color:var(--text2);margin-bottom:20px;max-width:400px;margin-left:auto;margin-right:auto}
.google-btn{padding:10px 24px;background:var(--white);border:1.5px solid var(--border);border-radius:8px;font-size:13px;font-weight:600;cursor:pointer;display:inline-flex;align-items:center;gap:8px;transition:all 0.2s}
.google-btn:hover{border-color:var(--accent);background:var(--accent-bg)}

/* Strategy Cards */
.strat-grid{display:flex;flex-direction:column;gap:10px}
.strat-card{background:var(--white);border:1px solid var(--border);border-radius:var(--radius);padding:16px 18px;box-shadow:var(--shadow);transition:all 0.2s}
.strat-card:hover{box-shadow:0 4px 12px rgba(0,0,0,0.08)}
.sc-top{display:flex;justify-content:space-between;align-items:flex-start;margin-bottom:8px}
.sc-name{font-size:15px;font-weight:700;color:var(--text)}
.sc-ticker{font-size:11px;background:var(--accent-bg);color:var(--accent);padding:2px 8px;border-radius:4px;font-weight:600}
.sc-meta{font-size:11px;color:var(--text2);line-height:1.8;margin-bottom:10px}
.sc-meta strong{color:var(--text)}
.sc-result{display:flex;gap:12px;flex-wrap:wrap;margin-bottom:12px}
.sc-kpi{font-size:11px;font-weight:600}
.sc-kpi.good{color:var(--bull)}
.sc-kpi.bad{color:var(--bear)}
.sc-kpi.neutral{color:var(--text2)}
.sc-actions{display:flex;gap:6px}
.sc-btn{padding:6px 14px;border-radius:6px;font-size:11px;font-weight:600;cursor:pointer;border:1px solid var(--border);background:var(--white);color:var(--text);transition:all 0.15s}
.sc-btn:hover{border-color:var(--accent);color:var(--accent)}
.sc-btn.primary{background:var(--accent);color:#fff;border-color:var(--accent)}
.sc-btn.primary:hover{background:#1D4ED8}
.sc-btn.danger{color:var(--bear)}
.sc-btn.danger:hover{background:rgba(220,38,38,0.06);border-color:var(--bear)}

/* Empty state */
.empty-state{text-align:center;padding:40px 20px;color:var(--text2)}
.empty-state h3{font-size:16px;color:var(--text);margin-bottom:8px}
.empty-state p{font-size:12px;max-width:350px;margin:0 auto 16px}
.empty-state a{font-weight:600}

/* Upgrade banner */
.upgrade-banner{background:linear-gradient(135deg,rgba(37,99,235,0.04),rgba(79,70,229,0.04));border:1px solid rgba(37,99,235,0.15);border-radius:var(--radius);padding:16px 20px;margin-top:16px;display:flex;align-items:center;justify-content:space-between;flex-wrap:wrap;gap:12px}
.ub-text{font-size:12px;color:var(--text)}
.ub-text strong{color:var(--accent)}
.ub-btn{padding:8px 20px;background:var(--accent);color:#fff;border:none;border-radius:6px;font-size:11px;font-weight:700;cursor:pointer}

/* Slots counter */
.slots-bar{display:flex;align-items:center;justify-content:space-between;margin-bottom:16px;padding:10px 14px;background:var(--white);border:1px solid var(--border);border-radius:8px}
.slots-label{font-size:12px;color:var(--text2)}
.slots-count{font-size:14px;font-weight:700;color:var(--accent)}

/* Footer */
.ftr{background:var(--white);border-top:1px solid var(--border);padding:16px 24px;font-size:10px;color:var(--text2);text-align:center;line-height:1.8;margin-top:40px}

@media(max-width:600px){
  .main{padding:16px 12px}
  .sc-result{gap:8px}
  .sc-actions{flex-wrap:wrap}
}
</style>
</head>
<body>

<!-- Header -->
<div class="hdr">
  <a href="/" class="logo">x<span>chart</span>.in<span class="ver">BETA</span></a>
  <div class="nav">
    <a href="/">Backtest</a>
    <a href="/strategies.html" class="active">My Strategies</a>
    <a href="/disclaimer.html">Disclaimer</a>
    <div class="auth-area">
      <button class="login-btn" id="authLoginBtn" onclick="showLoginModal()">Login</button>
      <div class="user-menu" id="authUserMenu">
        <div class="user-avatar" id="authUserAvatar">?</div>
        <span id="authUserName"></span>
        <span class="tier-badge tier-free" id="authTierBadge">FREE</span>
        <button class="logout-btn" onclick="logout()">Logout</button>
      </div>
    </div>
  </div>
</div>

<!-- Main Content -->
<div class="main">
  <div class="page-title">My Strategies</div>
  <div class="page-sub">Save, manage, and quickly reload your best backtesting configurations</div>

  <!-- Login required prompt (shown when not logged in) -->
  <div id="loginPrompt" class="login-prompt">
    <h2>🔐 Login to View Your Strategies</h2>
    <p>Sign in to save your backtesting configurations and reload them anytime with one click.</p>
    <button class="google-btn" onclick="loginWithGoogle()">
      <svg width="16" height="16" viewBox="0 0 24 24"><path fill="#4285F4" d="M22.56 12.25c0-.78-.07-1.53-.2-2.25H12v4.26h5.92a5.06 5.06 0 01-2.2 3.32v2.77h3.57c2.08-1.92 3.28-4.74 3.28-8.1z"/><path fill="#34A853" d="M12 23c2.97 0 5.46-.98 7.28-2.66l-3.57-2.77c-.98.66-2.23 1.06-3.71 1.06-2.86 0-5.29-1.93-6.16-4.53H2.18v2.84C3.99 20.53 7.7 23 12 23z"/><path fill="#FBBC05" d="M5.84 14.09c-.22-.66-.35-1.36-.35-2.09s.13-1.43.35-2.09V7.07H2.18C1.43 8.55 1 10.22 1 12s.43 3.45 1.18 4.93l2.85-2.22.81-.62z"/><path fill="#EA4335" d="M12 5.38c1.62 0 3.06.56 4.21 1.64l3.15-3.15C17.45 2.09 14.97 1 12 1 7.7 1 3.99 3.47 2.18 7.07l3.66 2.84c.87-2.6 3.3-4.53 6.16-4.53z"/></svg>
      Continue with Google
    </button>
  </div>

  <!-- Strategies list (shown when logged in) -->
  <div id="strategiesContent" style="display:none">
    <div class="slots-bar">
      <span class="slots-label">Strategy Slots</span>
      <span class="slots-count"><span id="slotsUsed">0</span> / <span id="slotsMax">0</span></span>
    </div>

    <div class="strat-grid" id="stratGrid">
      <!-- Cards rendered by JS -->
    </div>

    <div id="emptyState" class="empty-state" style="display:none">
      <h3>No saved strategies yet</h3>
      <p>Run a backtest on the <a href="/">Backtest page</a>, then click "Save Strategy" to save your configuration here.</p>
    </div>

    <div id="upgradeBanner" class="upgrade-banner" style="display:none">
      <div class="ub-text">
        🔓 Want to save more strategies? <strong>Upgrade to Analyst</strong> for 15 slots, CSV export, and strategy history.
      </div>
      <button class="ub-btn" onclick="window.location.href='/#pricing'">Upgrade — ₹149/mo</button>
    </div>
  </div>
</div>

<!-- Footer -->
<div class="ftr">
  <strong>⚠️ Disclaimer:</strong> xchart.in is an analytical tool for educational purposes.
  All results are based on historical data and user-configured rules. Past performance does not guarantee future results.
  This is not investment advice. Not SEBI registered.<br>
  © 2026 xchart.in · <a href="/disclaimer.html">Full Disclaimer</a>
</div>

<!-- Login Modal (reused from index) -->
<div class="modal-overlay" id="loginModal">
  <div class="modal-box" style="max-width:380px">
    <div class="modal-hdr">
      <span>Login to xchart.in</span>
      <button class="modal-close" onclick="hideLoginModal()">✕</button>
    </div>
    <div style="padding:20px;text-align:center">
      <p style="font-size:12px;color:var(--text2);margin-bottom:16px">Sign in to save strategies and access premium features</p>
      <button class="google-btn" onclick="loginWithGoogle()" style="width:100%;justify-content:center;padding:12px">
        <svg width="16" height="16" viewBox="0 0 24 24"><path fill="#4285F4" d="M22.56 12.25c0-.78-.07-1.53-.2-2.25H12v4.26h5.92a5.06 5.06 0 01-2.2 3.32v2.77h3.57c2.08-1.92 3.28-4.74 3.28-8.1z"/><path fill="#34A853" d="M12 23c2.97 0 5.46-.98 7.28-2.66l-3.57-2.77c-.98.66-2.23 1.06-3.71 1.06-2.86 0-5.29-1.93-6.16-4.53H2.18v2.84C3.99 20.53 7.7 23 12 23z"/><path fill="#FBBC05" d="M5.84 14.09c-.22-.66-.35-1.36-.35-2.09s.13-1.43.35-2.09V7.07H2.18C1.43 8.55 1 10.22 1 12s.43 3.45 1.18 4.93l2.85-2.22.81-.62z"/><path fill="#EA4335" d="M12 5.38c1.62 0 3.06.56 4.21 1.64l3.15-3.15C17.45 2.09 14.97 1 12 1 7.7 1 3.99 3.47 2.18 7.07l3.66 2.84c.87-2.6 3.3-4.53 6.16-4.53z"/></svg>
        Continue with Google
      </button>
    </div>
  </div>
</div>

<style>
.modal-overlay{display:none;position:fixed;inset:0;background:rgba(0,0,0,0.4);backdrop-filter:blur(4px);z-index:500;align-items:center;justify-content:center}
.modal-overlay.open{display:flex}
.modal-box{background:var(--white);border-radius:14px;box-shadow:0 20px 60px rgba(0,0,0,0.15);border:1px solid var(--border);overflow:hidden}
.modal-hdr{display:flex;align-items:center;justify-content:space-between;padding:14px 18px;border-bottom:1px solid var(--border);font-size:14px;font-weight:700}
.modal-close{background:none;border:1px solid var(--border);border-radius:50%;width:28px;height:28px;cursor:pointer;font-size:14px;display:flex;align-items:center;justify-content:center;color:var(--text2)}
.modal-close:hover{background:rgba(220,38,38,0.06);border-color:var(--bear);color:var(--bear)}
</style>

<!-- Firebase SDK -->
<script src="https://www.gstatic.com/firebasejs/10.12.0/firebase-app-compat.js"></script>
<script src="https://www.gstatic.com/firebasejs/10.12.0/firebase-auth-compat.js"></script>
<script src="https://www.gstatic.com/firebasejs/10.12.0/firebase-firestore-compat.js"></script>
<script src="firebase-config.js"></script>
<script src="auth.js"></script>

<script>
function renderStrategiesList() {
  var prompt = document.getElementById('loginPrompt');
  var content = document.getElementById('strategiesContent');
  var grid = document.getElementById('stratGrid');
  var empty = document.getElementById('emptyState');
  var banner = document.getElementById('upgradeBanner');
  var slotsUsed = document.getElementById('slotsUsed');
  var slotsMax = document.getElementById('slotsMax');

  if (!XAuth.user) {
    prompt.style.display = '';
    content.style.display = 'none';
    return;
  }

  prompt.style.display = 'none';
  content.style.display = '';

  var maxS = getMaxStrategies();
  slotsUsed.textContent = XAuth.strategies.length;
  slotsMax.textContent = maxS > 0 ? maxS : '0 (upgrade to save)';

  if (maxS <= 0) {
    banner.style.display = '';
    banner.querySelector('.ub-text').innerHTML = '🔓 Saving strategies is an <strong>Analyst</strong> feature. Upgrade to save your backtesting configurations.';
  } else if (XAuth.strategies.length >= maxS * 0.8) {
    banner.style.display = '';
  } else {
    banner.style.display = 'none';
  }

  if (XAuth.strategies.length === 0) {
    grid.innerHTML = '';
    empty.style.display = '';
    return;
  }
  empty.style.display = 'none';

  var html = '';
  XAuth.strategies.forEach(function(s) {
    var inds = (s.slots || []).map(function(sl) { return sl.indId; }).join(', ');
    var lr = s.lastResult || {};
    var retColor = (lr.totalReturn || 0) >= 0 ? 'good' : 'bad';
    var wrColor = (lr.winRate || 0) >= 50 ? 'good' : (lr.winRate || 0) > 0 ? 'bad' : 'neutral';
    var pfColor = (lr.profitFactor || 0) >= 1 ? 'good' : (lr.profitFactor || 0) > 0 ? 'bad' : 'neutral';

    html += '<div class="strat-card">';
    html += '<div class="sc-top"><div class="sc-name">' + (s.name || 'Unnamed') + '</div>';
    html += '<span class="sc-ticker">' + (s.ticker || '—') + '</span></div>';
    html += '<div class="sc-meta"><strong>Mode:</strong> ' + (s.mode || 'weighted').toUpperCase();
    html += ' · <strong>Indicators:</strong> ' + inds;
    html += ' · <strong>Period:</strong> ' + (s.period || '1y').toUpperCase() + '</div>';

    if (lr.trades !== undefined) {
      html += '<div class="sc-result">';
      html += '<span class="sc-kpi neutral">' + (lr.trades || 0) + ' trades</span>';
      html += '<span class="sc-kpi ' + wrColor + '">Win ' + (lr.winRate || 0).toFixed(1) + '%</span>';
      html += '<span class="sc-kpi ' + pfColor + '">PF ' + (lr.profitFactor || 0).toFixed(2) + '</span>';
      html += '<span class="sc-kpi ' + retColor + '">' + ((lr.totalReturn || 0) >= 0 ? '+' : '') + (lr.totalReturn || 0).toFixed(1) + '%</span>';
      html += '</div>';
    }

    html += '<div class="sc-actions">';
    html += '<button class="sc-btn primary" onclick="loadAndRun(\'' + s.id + '\')">▶ Run Now</button>';
    html += '<button class="sc-btn danger" onclick="confirmDelete(\'' + s.id + '\',\'' + (s.name || '').replace(/'/g, '') + '\')">🗑️ Delete</button>';
    html += '</div></div>';
  });
  grid.innerHTML = html;
}

function loadAndRun(stratId) {
  var strat = XAuth.strategies.find(function(s) { return s.id === stratId; });
  if (!strat) return;
  // Store in sessionStorage and redirect to backtest page
  sessionStorage.setItem('xchart_load_strategy', JSON.stringify(strat));
  window.location.href = '/';
}

function confirmDelete(stratId, name) {
  if (confirm('Delete strategy "' + name + '"? This cannot be undone.')) {
    deleteStrategy(stratId).then(function() {
      renderStrategiesList();
      showToast('Strategy deleted');
    });
  }
}

// Update avatar
function updateAuthUI() {
  var loginBtn = document.getElementById('authLoginBtn');
  var userMenu = document.getElementById('authUserMenu');
  var userName = document.getElementById('authUserName');
  var tierBadge = document.getElementById('authTierBadge');
  var avatar = document.getElementById('authUserAvatar');

  if (XAuth.user) {
    loginBtn.style.display = 'none';
    userMenu.style.display = 'flex';
    userName.textContent = XAuth.user.displayName || XAuth.user.email.split('@')[0];
    tierBadge.textContent = XAuth.tier === 'free' ? 'FREE' : XAuth.tier.toUpperCase();
    tierBadge.className = 'tier-badge tier-' + XAuth.tier;
    avatar.textContent = (XAuth.user.displayName || XAuth.user.email)[0].toUpperCase();
  } else {
    loginBtn.style.display = '';
    userMenu.style.display = 'none';
  }
  renderStrategiesList();
}
</script>

</body>
</html>"""
    Path("strategies.html").write_text(content, encoding="utf-8")
    print("  ✅ strategies.html created")

# ══════════════════════════════════════════════════════════════
# 4. PATCH INDEX.HTML
# ══════════════════════════════════════════════════════════════

def patch_index():
    fp = Path("index.html")
    if not fp.exists():
        print("  ERROR: index.html not found!")
        return

    c = fp.read_text(encoding="utf-8")
    orig = c
    n = 0

    # ── 1. Add Firebase SDK + auth.js before </body> ──
    if 'firebase-app-compat.js' not in c:
        sdk_block = """
<!-- Firebase SDK -->
<script src="https://www.gstatic.com/firebasejs/10.12.0/firebase-app-compat.js"></script>
<script src="https://www.gstatic.com/firebasejs/10.12.0/firebase-auth-compat.js"></script>
<script src="https://www.gstatic.com/firebasejs/10.12.0/firebase-firestore-compat.js"></script>
<script src="firebase-config.js"></script>
<script src="auth.js"></script>
"""
        c = c.replace('</body>', sdk_block + '</body>')
        n += 1
        print("  Added Firebase SDK + auth.js")

    # ── 2. Add auth UI to header ──
    # Find the header nav area and add auth buttons
    if 'authLoginBtn' not in c:
        auth_html = """<div class="auth-area">
      <button class="login-btn" id="authLoginBtn" onclick="showLoginModal()" aria-label="Login">Login</button>
      <div class="user-menu" id="authUserMenu" style="display:none">
        <div class="user-avatar" id="authUserAvatar">?</div>
        <span id="authUserName" style="font-size:11px;font-weight:600"></span>
        <span class="tier-badge tier-free" id="authTierBadge">FREE</span>
        <button class="logout-btn" onclick="logout()" style="font-size:10px;color:var(--text3);background:none;border:none;cursor:pointer">Logout</button>
      </div>
    </div>"""

        # Try to insert before closing </div> of header right area or before </nav>
        # Look for Disclaimer link as anchor
        if 'Disclaimer</a>' in c:
            c = c.replace('Disclaimer</a>', 'Disclaimer</a>\n    ' + auth_html)
            n += 1
            print("  Added auth UI to header")
        elif '</nav>' in c:
            c = c.replace('</nav>', auth_html + '\n</nav>')
            n += 1
            print("  Added auth UI before </nav>")

    # ── 3. Add auth CSS ──
    if '.login-btn' not in c and '</style>' in c:
        auth_css = """
/* Auth */
.auth-area{display:flex;align-items:center;gap:8px;margin-left:12px}
.login-btn{padding:6px 16px;background:var(--accent);color:#fff;border:none;border-radius:6px;font-size:11px;font-weight:600;cursor:pointer;transition:all 0.2s}
.login-btn:hover{background:#1D4ED8}
.user-menu{display:flex;align-items:center;gap:8px}
.user-avatar{width:26px;height:26px;border-radius:50%;background:var(--accent);color:#fff;display:flex;align-items:center;justify-content:center;font-weight:700;font-size:10px}
.tier-badge{font-size:8px;padding:2px 6px;border-radius:8px;font-weight:700}
.tier-free{background:var(--card2);color:var(--text3)}
.tier-analyst{background:rgba(37,99,235,0.1);color:var(--accent)}
.tier-pro{background:rgba(217,119,6,0.1);color:#D97706}
.logout-btn:hover{color:var(--bear)!important}
/* Modals */
.modal-overlay{display:none;position:fixed;inset:0;background:rgba(0,0,0,0.4);backdrop-filter:blur(4px);z-index:500;align-items:center;justify-content:center;padding:16px}
.modal-overlay.open{display:flex}
.modal-box{background:var(--white);border-radius:14px;box-shadow:0 20px 60px rgba(0,0,0,0.15);border:1px solid var(--border);overflow:hidden;width:100%;max-width:440px}
.modal-hdr{display:flex;align-items:center;justify-content:space-between;padding:14px 18px;border-bottom:1px solid var(--border);font-size:14px;font-weight:700}
.modal-close{background:none;border:1px solid var(--border);border-radius:50%;width:28px;height:28px;cursor:pointer;font-size:14px;display:flex;align-items:center;justify-content:center;color:var(--text2)}
.modal-close:hover{background:rgba(220,38,38,0.06);border-color:var(--bear);color:var(--bear)}
.google-btn{padding:10px 24px;background:var(--white);border:1.5px solid var(--border);border-radius:8px;font-size:13px;font-weight:600;cursor:pointer;display:inline-flex;align-items:center;gap:8px;transition:all 0.2s;width:100%;justify-content:center}
.google-btn:hover{border-color:var(--accent);background:var(--accent-bg)}
.save-confirm-btn{width:100%;padding:10px;background:var(--accent);color:#fff;border:none;border-radius:8px;font-size:13px;font-weight:700;cursor:pointer;margin-top:12px}
.save-confirm-btn:hover{background:#1D4ED8}
.save-input{width:100%;padding:10px 12px;border:1.5px solid var(--border);border-radius:6px;font-size:12px;margin-top:8px}
.save-input:focus{border-color:var(--accent);outline:none}
/* Toast */
.toast-msg{position:fixed;bottom:-50px;left:50%;transform:translateX(-50%);background:#1F2937;color:#fff;padding:10px 24px;border-radius:8px;font-size:12px;font-weight:600;z-index:600;transition:bottom 0.3s;box-shadow:0 4px 12px rgba(0,0,0,0.15)}
.toast-msg.show{bottom:24px}
"""
        c = c.replace('</style>', auth_css + '</style>')
        n += 1
        print("  Added auth + modal CSS")

    # ── 4. Add modals before </body> ──
    if 'loginModal' not in c:
        modals_html = """
<!-- Login Modal -->
<div class="modal-overlay" id="loginModal">
  <div class="modal-box" style="max-width:380px">
    <div class="modal-hdr"><span>Login to xchart.in</span><button class="modal-close" onclick="hideLoginModal()">✕</button></div>
    <div style="padding:24px;text-align:center">
      <p style="font-size:12px;color:var(--text2);margin-bottom:16px">Sign in to save strategies and access premium features</p>
      <button class="google-btn" onclick="loginWithGoogle()">
        <svg width="16" height="16" viewBox="0 0 24 24"><path fill="#4285F4" d="M22.56 12.25c0-.78-.07-1.53-.2-2.25H12v4.26h5.92a5.06 5.06 0 01-2.2 3.32v2.77h3.57c2.08-1.92 3.28-4.74 3.28-8.1z"/><path fill="#34A853" d="M12 23c2.97 0 5.46-.98 7.28-2.66l-3.57-2.77c-.98.66-2.23 1.06-3.71 1.06-2.86 0-5.29-1.93-6.16-4.53H2.18v2.84C3.99 20.53 7.7 23 12 23z"/><path fill="#FBBC05" d="M5.84 14.09c-.22-.66-.35-1.36-.35-2.09s.13-1.43.35-2.09V7.07H2.18C1.43 8.55 1 10.22 1 12s.43 3.45 1.18 4.93l2.85-2.22.81-.62z"/><path fill="#EA4335" d="M12 5.38c1.62 0 3.06.56 4.21 1.64l3.15-3.15C17.45 2.09 14.97 1 12 1 7.7 1 3.99 3.47 2.18 7.07l3.66 2.84c.87-2.6 3.3-4.53 6.16-4.53z"/></svg>
        Continue with Google
      </button>
      <div style="margin:16px 0;font-size:10px;color:var(--text3)">— or —</div>
      <input type="email" id="emailInput" class="save-input" placeholder="Email address" style="margin-top:0">
      <input type="password" id="passwordInput" class="save-input" placeholder="Password">
      <button class="save-confirm-btn" onclick="loginWithEmail(document.getElementById('emailInput').value,document.getElementById('passwordInput').value,false)">Login with Email</button>
      <div style="margin-top:8px;font-size:10px;color:var(--text3)">No account? <a href="#" onclick="loginWithEmail(document.getElementById('emailInput').value,document.getElementById('passwordInput').value,true);return false" style="color:var(--accent);font-weight:600">Sign up</a></div>
    </div>
  </div>
</div>

<!-- Save Strategy Modal -->
<div class="modal-overlay" id="saveModal">
  <div class="modal-box">
    <div class="modal-hdr"><span>💾 Save Strategy</span><button class="modal-close" onclick="hideSaveModal()">✕</button></div>
    <div style="padding:20px">
      <label style="font-size:11px;font-weight:600;color:var(--text2)">Strategy Name</label>
      <input type="text" id="saveStratName" class="save-input" placeholder="e.g. RSI + BB Reversal on RELIANCE">
      <div id="saveStratInfo" style="font-size:11px;color:var(--text2);margin-top:10px;line-height:1.8"></div>
      <button class="save-confirm-btn" onclick="doSaveStrategy()">💾 Save Strategy</button>
      <div id="saveSlotsInfo" style="font-size:10px;color:var(--text3);text-align:center;margin-top:8px"></div>
    </div>
  </div>
</div>

<!-- Upgrade Modal -->
<div class="modal-overlay" id="upgradeModal">
  <div class="modal-box">
    <div class="modal-hdr"><span>🔓 Upgrade to Analyst</span><button class="modal-close" onclick="hideUpgradeModal()">✕</button></div>
    <div style="padding:20px">
      <p id="upgradeMsg" style="font-size:12px;color:var(--text2);line-height:1.8;margin-bottom:16px"></p>
      <div style="background:var(--card2);border-radius:8px;padding:14px;margin-bottom:16px;font-size:11px;line-height:2">
        <strong>Analyst Plan — ₹149/month</strong><br>
        ✅ Save 15 strategies<br>
        ✅ 7 indicators per backtest<br>
        ✅ Strategy history (last 3 runs)<br>
        ✅ CSV export<br>
        ✅ Cross-stock testing (3 stocks)
      </div>
      <div style="text-align:center;font-size:11px;color:var(--text3)">Payment integration coming soon.<br>Email <strong>info@xchart.in</strong> for early access.</div>
    </div>
  </div>
</div>
"""
        c = c.replace('</body>', modals_html + '</body>')
        n += 1
        print("  Added login/save/upgrade modals")

    # ── 5. Update nav — add My Strategies, hide Dashboard ──
    if 'strategies.html' not in c:
        # Add strategies link before disclaimer
        if 'disclaimer.html' in c:
            c = c.replace(
                '<a href="/disclaimer.html"',
                '<a href="/strategies.html">My Strategies</a>\n    <a href="/disclaimer.html"'
            )
            n += 1
            print("  Added My Strategies nav link")
            # Also try relative path
            c = c.replace(
                '<a href="disclaimer.html"',
                '<a href="strategies.html">My Strategies</a>\n    <a href="disclaimer.html"'
            )

    # Remove dashboard link
    if 'dashboard.html' in c:
        c = re.sub(r'<a[^>]*href="[^"]*dashboard\.html"[^>]*>[^<]*</a>\s*', '', c)
        n += 1
        print("  Removed dashboard from nav")

    # ── 6. Add strategy loader from sessionStorage ──
    if 'xchart_load_strategy' not in c:
        loader_script = """
<script>
// Load strategy from My Strategies page
document.addEventListener('DOMContentLoaded', function() {
  var stored = sessionStorage.getItem('xchart_load_strategy');
  if (stored) {
    sessionStorage.removeItem('xchart_load_strategy');
    try {
      var strat = JSON.parse(stored);
      // Wait for ticker list to load
      var checkReady = setInterval(function() {
        if (typeof BT !== 'undefined' && BT.tickers && BT.tickers.length > 0) {
          clearInterval(checkReady);
          loadStrategyIntoBacktest(strat);
        }
      }, 200);
    } catch(e) { console.error('Strategy load error:', e); }
  }
});
</script>
"""
        c = c.replace('</body>', loader_script + '</body>')
        n += 1
        print("  Added strategy loader from sessionStorage")

    if c != orig:
        fp.write_text(c, encoding="utf-8")
        print("\n  ✅ index.html patched (" + str(n) + " changes)")
    else:
        print("  No changes needed")


# ══════════════════════════════════════════════════════════════
# 5. PATCH BACKTEST.JS — 15 Presets + Save Button + Indicator Limit
# ══════════════════════════════════════════════════════════════

def patch_backtest():
    fp = Path("backtest.js")
    if not fp.exists():
        print("  ERROR: backtest.js not found!")
        return

    c = fp.read_text(encoding="utf-8")
    orig = c
    n = 0

    # ── 1. Replace PRESETS object with 15 presets ──
    old_presets_start = "var PRESETS = {"
    old_presets_end = "};\n\nfunction loadPreset"

    if old_presets_start in c:
        start_idx = c.find(old_presets_start)
        end_idx = c.find(old_presets_end)
        if start_idx >= 0 and end_idx >= 0:
            new_presets = """var PRESETS = {
  // ── Momentum ──
  rsiRecovery: {
    name: 'RSI Recovery', cat: 'Momentum',
    mode: 'weighted',
    slots: [
      { indId:'rsi', params:{period:14,oversold:30,overbought:70}, entryCond:'cross_above_os', exitCond:'cross_above_ob', weight:60 },
      { indId:'volumeSpike', params:{lookback:20,threshold:2}, entryCond:'spike_with_up', exitCond:'volume_dries', weight:40 }
    ]
  },
  macdMomentum: {
    name: 'MACD Momentum', cat: 'Momentum',
    mode: 'weighted',
    slots: [
      { indId:'macd', params:{fast:12,slow:26,signal:9}, entryCond:'cross_above_signal', exitCond:'cross_below_signal', weight:40 },
      { indId:'adx', params:{period:14,threshold:25}, entryCond:'adx_rising', exitCond:'adx_below_threshold', weight:30 },
      { indId:'priceSMA', params:{period:200}, entryCond:'is_above', exitCond:'cross_below', weight:30 }
    ]
  },
  stochRsiReversal: {
    name: 'Stoch RSI Reversal', cat: 'Momentum',
    mode: 'weighted',
    slots: [
      { indId:'stochRsi', params:{rsiPeriod:14,stochPeriod:14,kSmooth:3,dSmooth:3,oversold:20,overbought:80}, entryCond:'k_cross_above_d', exitCond:'k_cross_below_d', weight:55 },
      { indId:'bb', params:{period:20,upperSigma:2,lowerSigma:2}, entryCond:'bounce_from_lower', exitCond:'cross_above_mid', weight:45 }
    ]
  },
  // ── Trend Following ──
  goldenCross: {
    name: 'Golden Cross', cat: 'Trend',
    mode: 'weighted',
    slots: [
      { indId:'smaCross', params:{fast:50,slow:200}, entryCond:'fast_cross_above_slow', exitCond:'fast_cross_below_slow', weight:50 },
      { indId:'volumeSpike', params:{lookback:20,threshold:1.5}, entryCond:'spike_with_up', exitCond:'volume_dries', weight:25 },
      { indId:'adx', params:{period:14,threshold:20}, entryCond:'adx_rising', exitCond:'adx_below_threshold', weight:25 }
    ]
  },
  supertrendRider: {
    name: 'SuperTrend Rider', cat: 'Trend',
    mode: 'weighted',
    slots: [
      { indId:'supertrend', params:{atrPeriod:10,multiplier:3}, entryCond:'turns_bullish', exitCond:'turns_bearish', weight:40 },
      { indId:'emaCross', params:{fast:9,slow:21}, entryCond:'fast_cross_above_slow', exitCond:'fast_cross_below_slow', weight:35 },
      { indId:'adx', params:{period:14,threshold:25}, entryCond:'adx_rising', exitCond:'adx_below_threshold', weight:25 }
    ]
  },
  ichimokuBreakout: {
    name: 'Ichimoku Breakout', cat: 'Trend',
    mode: 'weighted',
    slots: [
      { indId:'ichimoku', params:{tenkan:9,kijun:26,senkou:52}, entryCond:'tenkan_cross_above_kijun', exitCond:'price_below_cloud', weight:50 },
      { indId:'volumeSpike', params:{lookback:20,threshold:2}, entryCond:'spike_with_up', exitCond:'volume_dries', weight:25 },
      { indId:'priceSMA', params:{period:200}, entryCond:'is_above', exitCond:'cross_below', weight:25 }
    ]
  },
  // ── Mean Reversion ──
  bbBounce: {
    name: 'BB Bounce', cat: 'Mean Reversion',
    mode: 'weighted',
    slots: [
      { indId:'bb', params:{period:20,upperSigma:2,lowerSigma:2}, entryCond:'bounce_from_lower', exitCond:'cross_above_mid', weight:40 },
      { indId:'rsi', params:{period:14,oversold:35,overbought:65}, entryCond:'cross_above_os', exitCond:'cross_above_ob', weight:35 },
      { indId:'obv', params:{lookback:20}, entryCond:'obv_above_sma', exitCond:'obv_below_sma', weight:25 }
    ]
  },
  keltnerSqueeze: {
    name: 'Keltner Squeeze', cat: 'Mean Reversion',
    mode: 'weighted',
    slots: [
      { indId:'keltner', params:{emaPeriod:20,atrPeriod:10,multiplier:2}, entryCond:'bounce_from_lower', exitCond:'cross_above_mid', weight:35 },
      { indId:'bb', params:{period:20,upperSigma:2,lowerSigma:2}, entryCond:'bounce_from_lower', exitCond:'cross_above_upper', weight:35 },
      { indId:'macd', params:{fast:12,slow:26,signal:9}, entryCond:'hist_positive', exitCond:'hist_negative', weight:30 }
    ]
  },
  cciOversold: {
    name: 'CCI Oversold', cat: 'Mean Reversion',
    mode: 'weighted',
    slots: [
      { indId:'cci', params:{period:20,oversold:-100,overbought:100}, entryCond:'cross_above_os', exitCond:'cross_above_ob', weight:40 },
      { indId:'priceSMA', params:{period:50}, entryCond:'is_above', exitCond:'cross_below', weight:30 },
      { indId:'volumeSpike', params:{lookback:20,threshold:1.5}, entryCond:'spike_with_up', exitCond:'volume_dries', weight:30 }
    ]
  },
  // ── Breakout ──
  donchianBreakout: {
    name: 'Donchian Breakout', cat: 'Breakout',
    mode: 'weighted',
    slots: [
      { indId:'donchian', params:{period:20}, entryCond:'break_above_upper', exitCond:'break_below_lower', weight:40 },
      { indId:'adx', params:{period:14,threshold:20}, entryCond:'adx_rising', exitCond:'adx_below_threshold', weight:30 },
      { indId:'volumeSpike', params:{lookback:20,threshold:2}, entryCond:'spike_with_up', exitCond:'volume_dries', weight:30 }
    ]
  },
  atrExpansion: {
    name: 'ATR Expansion', cat: 'Breakout',
    mode: 'weighted',
    slots: [
      { indId:'atrBreakout', params:{period:14,multiplier:2}, entryCond:'cross_above_upper', exitCond:'returns_to_basis', weight:35 },
      { indId:'macd', params:{fast:12,slow:26,signal:9}, entryCond:'cross_above_signal', exitCond:'cross_below_signal', weight:35 },
      { indId:'supertrend', params:{atrPeriod:10,multiplier:3}, entryCond:'price_above', exitCond:'price_below', weight:30 }
    ]
  },
  pivotBounce: {
    name: 'Pivot Bounce', cat: 'Breakout',
    mode: 'weighted',
    slots: [
      { indId:'pivots', params:{}, entryCond:'bounce_s1', exitCond:'reaches_r1', weight:40 },
      { indId:'rsi', params:{period:14,oversold:40,overbought:60}, entryCond:'cross_above_os', exitCond:'cross_above_ob', weight:30 },
      { indId:'emaCross', params:{fast:9,slow:21}, entryCond:'fast_cross_above_slow', exitCond:'fast_cross_below_slow', weight:30 }
    ]
  },
  // ── Conservative ──
  tripleConfirmation: {
    name: 'Triple Confirmation', cat: 'Conservative',
    mode: 'and',
    slots: [
      { indId:'rsi', params:{period:14,oversold:35,overbought:65}, entryCond:'cross_above_os', exitCond:'cross_above_ob', weight:34 },
      { indId:'macd', params:{fast:12,slow:26,signal:9}, entryCond:'cross_above_signal', exitCond:'cross_below_signal', weight:33 },
      { indId:'smaCross', params:{fast:9,slow:22}, entryCond:'fast_cross_above_slow', exitCond:'fast_cross_below_slow', weight:33 }
    ]
  },
  vwapValue: {
    name: 'VWAP Value', cat: 'Conservative',
    mode: 'weighted',
    slots: [
      { indId:'vwap', params:{}, entryCond:'is_below', exitCond:'is_above', weight:35 },
      { indId:'rsi', params:{period:14,oversold:35,overbought:65}, entryCond:'cross_above_os', exitCond:'cross_above_ob', weight:35 },
      { indId:'bb', params:{period:20,upperSigma:2,lowerSigma:2}, entryCond:'bounce_from_lower', exitCond:'cross_above_mid', weight:30 }
    ]
  },
  slowSteady: {
    name: 'Slow & Steady', cat: 'Conservative',
    mode: 'weighted',
    slots: [
      { indId:'emaCross', params:{fast:50,slow:200}, entryCond:'fast_cross_above_slow', exitCond:'fast_cross_below_slow', weight:40 },
      { indId:'adx', params:{period:14,threshold:25}, entryCond:'adx_rising', exitCond:'adx_below_threshold', weight:30 },
      { indId:'obv', params:{lookback:20}, entryCond:'obv_above_sma', exitCond:'obv_below_sma', weight:30 }
    ]
  }
};"""
            c = c[:start_idx] + new_presets + c[end_idx:]
            n += 1
            print("  Replaced PRESETS with 15 strategies (5 categories)")

    # ── 2. Update loadPreset to support category ──
    old_loadpreset = "function loadPreset(presetId) {"
    new_loadpreset = """function loadPreset(presetId) {
  // Check indicator limit
  var preset = PRESETS[presetId];
  if (!preset) return;
  var maxInd = (typeof getMaxIndicators === 'function') ? getMaxIndicators() : 5;
  if (preset.slots.length > maxInd) {
    if (typeof showUpgradeModal === 'function') {
      showUpgradeModal('indicators');
      return;
    }
  }"""
    if old_loadpreset in c and 'getMaxIndicators' not in c:
        c = c.replace(old_loadpreset, new_loadpreset)
        n += 1
        print("  Updated loadPreset with indicator limit check")

    # ── 3. Update addIndicatorSlot with tier limit ──
    old_addslot = "function addIndicatorSlot() {\n  if (BT.slots.length >= 5) return;"
    new_addslot = """function addIndicatorSlot() {
  var maxInd = (typeof getMaxIndicators === 'function') ? getMaxIndicators() : 5;
  if (BT.slots.length >= maxInd) {
    if (typeof showUpgradeModal === 'function' && maxInd < 10) showUpgradeModal('indicators');
    return;
  }"""
    if old_addslot in c:
        c = c.replace(old_addslot, new_addslot)
        n += 1
        print("  Updated addIndicatorSlot with tier limit")

    # Also update the renderSlots button text
    old_btn_limit = "document.getElementById('btnAddInd').disabled = BT.slots.length >= 5;"
    new_btn_limit = """var maxInd = (typeof getMaxIndicators === 'function') ? getMaxIndicators() : 5;
  document.getElementById('btnAddInd').disabled = BT.slots.length >= maxInd;"""
    if old_btn_limit in c:
        c = c.replace(old_btn_limit, new_btn_limit)
        n += 1
        print("  Updated indicator button limit")

    old_btn_text = "document.getElementById('btnAddInd').textContent = BT.slots.length >= 5 ? 'Maximum 5 indicators' : '+ Add Indicator';"
    new_btn_text = """document.getElementById('btnAddInd').textContent = BT.slots.length >= maxInd ? (maxInd < 10 ? 'Upgrade for more (max ' + maxInd + ')' : 'Maximum ' + maxInd + ' indicators') : '+ Add Indicator';"""
    if old_btn_text in c:
        c = c.replace(old_btn_text, new_btn_text)
        n += 1
        print("  Updated indicator button text")

    # ── 4. Add Save Strategy button in addDownloadButton ──
    old_download_wrap = "wrap.id = 'downloadWrap';"
    save_btn_code = """wrap.id = 'downloadWrap';

  // Save Strategy button
  var btnSave = document.createElement('button');
  btnSave.textContent = '\\uD83D\\uDCBE Save Strategy';
  btnSave.style.cssText = 'padding:10px 20px;background:#7C3AED;color:#fff;border:none;border-radius:8px;font-size:12px;font-weight:700;cursor:pointer;transition:all 0.2s;box-shadow:0 2px 8px rgba(124,58,237,0.25)';
  btnSave.onclick = function() { if (typeof showSaveModal === 'function') showSaveModal(); };
  wrap.appendChild(btnSave);"""
    if old_download_wrap in c and 'Save Strategy' not in c:
        c = c.replace(old_download_wrap, save_btn_code)
        n += 1
        print("  Added Save Strategy button")

    if c != orig:
        fp.write_text(c, encoding="utf-8")
        print("\n  ✅ backtest.js patched (" + str(n) + " changes)")
    else:
        print("  No changes needed")


if __name__ == "__main__":
    main()
