/**
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
