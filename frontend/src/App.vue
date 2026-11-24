<script setup>
import { ref, reactive, computed, watch, nextTick, onBeforeUnmount, onMounted } from "vue";
import { apiFetch, clearSession, getSession, saveSession } from "./lib/api";

const BUDGET_CAP = 0.25;
const HERO_PHOTO = "";
const STEPS = ["Describe", "Review", "Results"];

/* ---------- entry gate, auth & workspace navigation ---------- */
const session = ref(getSession());
const user = computed(() => session.value?.user || null);
const guestSkipped = ref(sessionStorage.getItem("sieve_guest_skipped") === "1");
const showAuthGate = computed(() => !user.value && !guestSkipped.value);

const authMode = ref("login"); // 'login' | 'register'
const authLoading = ref(false);
const authError = ref("");
const loginForm = reactive({ name: "", email: "", password: "", company: "" });
const showAccountMenu = ref(false);

const activeTab = ref("discover"); // 'discover' | 'profiles' | 'history'
const sidebarOpen = ref(false);

const profiles = ref([]);
const activeProfileId = ref(null);
const newProfile = reactive({
  name: "",
  industry: "",
  size: "",
  region: "",
  maxLeads: 5,
  query: "",
});

const runHistory = ref([]);

function skipAuthForNow() {
  guestSkipped.value = true;
  sessionStorage.setItem("sieve_guest_skipped", "1");
  authError.value = "";
}

function openAuthScreen(mode = "login") {
  authMode.value = mode;
  authError.value = "";
  guestSkipped.value = false;
  sessionStorage.removeItem("sieve_guest_skipped");
  showAccountMenu.value = false;
}

async function fetchProfiles() {
  if (!session.value?.access_token) {
    profiles.value = [];
    return;
  }
  try {
    const rows = await apiFetch("/profiles");
    profiles.value = Array.isArray(rows) ? rows : [];
  } catch {
    if (!getSession()?.access_token) {
      session.value = null;
      profiles.value = [];
    }
  }
}

async function fetchHistory() {
  if (!session.value?.access_token) {
    runHistory.value = [];
    return;
  }
  try {
    const rows = await apiFetch("/history");
    runHistory.value = Array.isArray(rows) ? rows : [];
  } catch {
    if (!getSession()?.access_token) {
      session.value = null;
      runHistory.value = [];
    }
  }
}

onMounted(async () => {
  session.value = getSession();
  if (session.value?.access_token) {
    await Promise.all([fetchProfiles(), fetchHistory()]);
  }
});

function switchTab(tab) {
  activeTab.value = tab;
  sidebarOpen.value = false;
  window.scrollTo({ top: 0, behavior: "smooth" });
}

async function handleAuthSubmit() {
  authError.value = "";
  authLoading.value = true;
  const endpoint = authMode.value === "register" ? "/auth/register" : "/auth/login";
  const body =
    authMode.value === "register"
      ? {
          name: loginForm.name.trim(),
          email: loginForm.email.trim(),
          password: loginForm.password,
          company: loginForm.company.trim(),
        }
      : {
          email: loginForm.email.trim(),
          password: loginForm.password,
        };

  try {
    const data = await apiFetch(endpoint, {
      method: "POST",
      body: JSON.stringify(body),
    });
    saveSession(data);
    session.value = getSession();
    guestSkipped.value = false;
    sessionStorage.removeItem("sieve_guest_skipped");
    Object.assign(loginForm, { name: "", email: "", password: "", company: "" });
    await Promise.all([fetchProfiles(), fetchHistory()]);
  } catch (err) {
    authError.value = err.message || "Authentication failed";
  } finally {
    authLoading.value = false;
  }
}

function logout() {
  clearSession();
  session.value = null;
  guestSkipped.value = false;
  sessionStorage.removeItem("sieve_guest_skipped");
  showAccountMenu.value = false;
  profiles.value = [];
  runHistory.value = [];
  activeProfileId.value = null;
  reset();
}

async function saveNewProfile() {
  if (!newProfile.name.trim() || !newProfile.query.trim()) return;
  if (!session.value?.access_token) {
    openAuthScreen("login");
    authError.value = "Sign in or create an account to save customer profiles.";
    return;
  }
  try {
    const created = await apiFetch("/profiles", {
      method: "POST",
      body: JSON.stringify({
        name: newProfile.name.trim(),
        industry: newProfile.industry.trim() || "General B2B",
        size: newProfile.size.trim() || "Any size",
        region: newProfile.region.trim() || "Global",
        max_leads: Number(newProfile.maxLeads) || 5,
        query: newProfile.query.trim(),
      }),
    });
    profiles.value.unshift(created);
    Object.assign(newProfile, { name: "", industry: "", size: "", region: "", maxLeads: 5, query: "" });
  } catch (err) {
    error.value = err.message;
  }
}

function saveCurrentAsProfile() {
  if (!session.value?.access_token) {
    openAuthScreen("register");
    authError.value = "Create a free account to save reusable customer profiles.";
    return;
  }
  newProfile.query = icpQuery.value;
  newProfile.maxLeads = maxLeads.value;
  newProfile.name = icpQuery.value.slice(0, 32) + (icpQuery.value.length > 32 ? "..." : "");
  switchTab("profiles");
}

function loadProfile(p) {
  icpQuery.value = p.query;
  maxLeads.value = p.maxLeads || p.max_leads || 5;
  activeProfileId.value = p.id;
  switchTab("discover");
}

async function deleteProfile(id) {
  try {
    await apiFetch(`/profiles/${id}`, { method: "DELETE" });
    profiles.value = profiles.value.filter((p) => p.id !== id);
    if (activeProfileId.value === id) activeProfileId.value = null;
  } catch (err) {
    error.value = err.message;
  }
}

async function clearRunHistory() {
  try {
    await apiFetch("/history", { method: "DELETE" });
    runHistory.value = [];
  } catch (err) {
    error.value = err.message;
  }
}

/* ---------- core agent state ---------- */
const icpQuery = ref("");
const maxLeads = ref(5);
const loading = ref(false);
const loadingMsg = ref("");
const error = ref("");

const runId = ref(null);
const status = ref("idle");
const budgetSpent = ref(0);
const icpPlan = ref(null);
const pendingLeads = ref([]);
const selectedDomains = ref([]);
const scoredLeads = ref([]);

const filter = ref("all");
const open = ref(null);
const stamp = ref("");
const showRaw = ref(false);
const ringsReady = ref(false);
const broken = reactive(new Set());

/* ---------- derived ---------- */
const statusLabel = computed(
  () =>
    ({
      idle: "Ready",
      running: "Working",
      awaiting_approval: "Needs your review",
      completed: "Complete",
      rejected: "Rejected",
    })[status.value] || status.value
);
const step = computed(() => {
  if (status.value === "completed" || status.value === "rejected") return 2;
  if (status.value === "awaiting_approval") return 1;
  return 0;
});
const budgetPct = computed(() => Math.min(100, (budgetSpent.value / BUDGET_CAP) * 100));
const sortedLeads = computed(() => [...scoredLeads.value].sort((a, b) => (b.score ?? -1) - (a.score ?? -1)));
const visibleLeads = computed(() =>
  sortedLeads.value.filter((l) => filter.value === "all" || tier(l.score) === filter.value)
);
const counts = computed(() => {
  const c = { all: scoredLeads.value.length, hot: 0, warm: 0, cold: 0 };
  scoredLeads.value.forEach((l) => c[tier(l.score)]++);
  return c;
});
const heroStyle = computed(() =>
  HERO_PHOTO ? { backgroundImage: `linear-gradient(rgba(15,26,58,.55),rgba(15,26,58,.55)),url(${HERO_PHOTO})` } : {}
);

/* ---------- helpers ---------- */
const fmt = (n) => Number(n || 0).toFixed(n > 0 && n < 0.1 ? 5 : 2);
const tier = (s) => (s >= 75 ? "hot" : s >= 50 ? "warm" : "cold");
const logoUrl = (d) => `https://www.google.com/s2/favicons?domain=${encodeURIComponent(d || "")}&sz=64`;
const initials = (n = "") =>
  n.split(/\s+/).filter(Boolean).slice(0, 2).map((w) => w[0].toUpperCase()).join("") || "?";
const hue = (s = "") => [...s].reduce((a, c) => (a * 31 + c.charCodeAt(0)) % 360, 7);
const label = (k) => k.replace(/_/g, " ").replace(/^./, (c) => c.toUpperCase());
const isList = (v) => Array.isArray(v);

const displayBudget = ref(0);
let raf = 0;
watch(budgetSpent, (to) => {
  cancelAnimationFrame(raf);
  const from = displayBudget.value;
  const t0 = performance.now();
  const stepFn = (t) => {
    const p = Math.min(1, (t - t0) / 700);
    displayBudget.value = from + (to - from) * (1 - Math.pow(1 - p, 3));
    if (p < 1) raf = requestAnimationFrame(stepFn);
  };
  raf = requestAnimationFrame(stepFn);
});

let ticker = null;
function startTicker(msgs) {
  stopTicker();
  let i = 0;
  loadingMsg.value = msgs[0];
  ticker = setInterval(() => {
    i = Math.min(i + 1, msgs.length - 1);
    loadingMsg.value = msgs[i];
  }, 2600);
}
function stopTicker() {
  clearInterval(ticker);
  ticker = null;
}
onBeforeUnmount(() => {
  stopTicker();
  cancelAnimationFrame(raf);
});

watch(scoredLeads, async () => {
  ringsReady.value = false;
  await nextTick();
  setTimeout(() => (ringsReady.value = true), 80);
});

function scrollTo(id) {
  nextTick(() => document.getElementById(id)?.scrollIntoView({ behavior: "smooth", block: "start" }));
}

/* ---------- API ---------- */
async function startRun() {
  if (!icpQuery.value.trim()) {
    error.value = "Enter what kind of companies or leads you are looking for.";
    return;
  }

  loading.value = true;
  error.value = "";
  scoredLeads.value = [];
  pendingLeads.value = [];
  selectedDomains.value = [];
  icpPlan.value = null;
  runId.value = null;
  status.value = "running";
  startTicker(["Reading your description", "Searching for matching companies", "Filtering weak fits before enrichment"]);

  try {
    const data = await apiFetch("/runs", {
      method: "POST",
      body: JSON.stringify({
        icp_query: icpQuery.value.trim(),
        max_leads: Number(maxLeads.value) || 5,
      }),
    });
    const leads = data.prefiltered_leads || data.pending_leads || data.leads || data.candidates || [];

    runId.value = data.run_id;
    status.value = data.status || "awaiting_approval";
    budgetSpent.value = data.budget_spent_usd || 0;
    icpPlan.value = data.icp_plan || null;
    pendingLeads.value = leads;
    selectedDomains.value = leads.map((l) => l.domain).filter(Boolean);
    scoredLeads.value = data.scored_leads || [];
    if (session.value?.access_token) await fetchHistory();
    scrollTo(status.value === "awaiting_approval" ? "review" : "results");
  } catch (err) {
    error.value = err.message;
    status.value = "idle";
  } finally {
    loading.value = false;
    stopTicker();
  }
}

async function handleDecision(approved) {
  if (!runId.value) return;
  loading.value = true;
  error.value = "";
  filter.value = "all";
  startTicker(approved ? ["Enriching approved leads", "Scoring fit", "Generating outreach angles"] : ["Closing the run"]);

  const keep = pendingLeads.value.filter((l) => selectedDomains.value.includes(l.domain));
  try {
    const data = await apiFetch(`/runs/${runId.value}/approve`, {
      method: "POST",
      body: JSON.stringify({
        approved,
        approved_domains: approved ? selectedDomains.value : [],
        approved_leads: approved ? keep : [],
      }),
    });
    stamp.value = approved ? "Approved" : "Rejected";
    setTimeout(() => (stamp.value = ""), 1500);
    status.value = data.status || (approved ? "completed" : "rejected");
    if (data.budget_spent_usd !== undefined) budgetSpent.value = data.budget_spent_usd;
    scoredLeads.value = data.scored_leads || [];

    if (session.value?.access_token) {
      await fetchHistory();
    } else {
      runHistory.value.unshift({
        id: runId.value,
        query: icpQuery.value.trim(),
        date: new Date().toLocaleDateString(),
        leadsCount: scoredLeads.value.length,
        spent: budgetSpent.value,
        status: status.value,
      });
    }
    scrollTo("results");
  } catch (err) {
    error.value = err.message;
  } finally {
    loading.value = false;
    stopTicker();
  }
}

/* ---------- actions ---------- */
function toggleAll(on) {
  selectedDomains.value = on ? pendingLeads.value.map((l) => l.domain) : [];
}
async function copy(text) {
  try {
    await navigator.clipboard.writeText(text);
  } catch {}
}
function exportCsv() {
  const cols = ["company_name", "domain", "email", "score", "angle"];
  const cell = (v) => {
    v = v == null ? "" : String(v);
    if (/^[=+\-@]/.test(v)) v = "'" + v;
    return /[",\n]/.test(v) ? `"${v.replace(/"/g, '""')}"` : v;
  };
  const csv = [cols.join(","), ...sortedLeads.value.map((l) => cols.map((c) => cell(l[c])).join(","))].join("\n");
  const a = document.createElement("a");
  a.href = URL.createObjectURL(new Blob([csv], { type: "text/csv" }));
  a.download = "leads.csv";
  a.click();
  setTimeout(() => URL.revokeObjectURL(a.href), 1000);
}
function reset() {
  status.value = "idle";
  runId.value = null;
  icpPlan.value = null;
  pendingLeads.value = [];
  scoredLeads.value = [];
  budgetSpent.value = 0;
  window.scrollTo({ top: 0, behavior: "smooth" });
}
</script>

<template>
  <!-- ==================== FIRST-SCREEN LOGIN / REGISTER + SKIP GATE ==================== -->
  <div v-if="showAuthGate" class="auth-gate">
    <div class="auth-gate-card">
      <div class="auth-gate-brand">
        <svg width="34" height="34" viewBox="0 0 26 26" aria-hidden="true">
          <circle cx="13" cy="13" r="12" fill="none" stroke="currentColor" stroke-width="2" />
          <path d="M5 9h16M7 13h12M10 17h6" stroke="#2F3DF5" stroke-width="2.4" stroke-linecap="round" />
        </svg>
        <div>
          <b>Sieve</b>
          <small>B2B Lead Intelligence Platform</small>
        </div>
      </div>

      <div class="auth-tabs">
        <button
          type="button"
          :class="['auth-tab', { active: authMode === 'login' }]"
          @click="authMode = 'login'; authError = ''"
        >
          Sign In
        </button>
        <button
          type="button"
          :class="['auth-tab', { active: authMode === 'register' }]"
          @click="authMode = 'register'; authError = ''"
        >
          Create Account
        </button>
      </div>

      <p class="muted" style="margin: 0 0 14px">
        {{
          authMode === "register"
            ? "Create an account to save customer profiles and persist your lead history."
            : "Sign in to load your saved customer profiles and run history."
        }}
      </p>

      <p v-if="authError" class="error" style="margin: 0 0 12px; padding: 10px">{{ authError }}</p>

      <form class="profile-form" @submit.prevent="handleAuthSubmit">
        <label v-if="authMode === 'register'" class="field">
          Full Name
          <input v-model="loginForm.name" placeholder="Enter your full name" required />
        </label>
        <label class="field">
          Email Address
          <input v-model="loginForm.email" type="email" placeholder="you@company.com" required />
        </label>
        <label class="field">
          Password
          <input v-model="loginForm.password" type="password" minlength="4" placeholder="Enter password" required />
        </label>
        <label v-if="authMode === 'register'" class="field">
          Company / Workspace
          <input v-model="loginForm.company" placeholder="Your company or team" />
        </label>
        <button type="submit" class="btn primary" :disabled="authLoading">
          {{ authLoading ? "Please wait..." : authMode === "register" ? "Create Account & Continue" : "Sign In & Continue" }}
        </button>
      </form>

      <div class="auth-divider"><span>or</span></div>

      <button type="button" class="btn skip-btn" @click="skipAuthForNow">
        Skip for now — Continue as Guest
      </button>
      <small class="muted" style="display: block; text-align: center; margin-top: 8px">
        Guest mode lets you discover and export leads immediately. Sign in anytime to save profiles.
      </small>
    </div>
  </div>

  <!-- ==================== MAIN WORKSPACE ==================== -->
  <div v-else class="app-shell">
    <!-- STICKY HEADER -->
    <header class="app-header">
      <div class="header-left">
        <button class="menu-toggle" aria-label="Toggle sidebar" @click="sidebarOpen = !sidebarOpen">
          ☰
        </button>
        <div class="brand" @click="switchTab('discover')">
          <svg width="28" height="28" viewBox="0 0 26 26" aria-hidden="true">
            <circle cx="13" cy="13" r="12" fill="none" stroke="currentColor" stroke-width="2" />
            <path d="M5 9h16M7 13h12M10 17h6" stroke="#2F3DF5" stroke-width="2.4" stroke-linecap="round" />
          </svg>
          <div>
            <b>Sieve</b>
            <small>Lead Intelligence</small>
          </div>
        </div>
      </div>

      <div class="header-right">
        <span :class="['badge', 'st-' + status]"><i></i>{{ statusLabel }}</span>

        <div class="budget" :title="`Run budget cap: $${BUDGET_CAP}`">
          <div class="budget-row">
            <span>Spent</span><b>${{ fmt(displayBudget) }}</b><span class="cap">/${{ BUDGET_CAP.toFixed(2) }}</span>
          </div>
          <div class="meter"><i :class="{ warn: budgetPct > 70 }" :style="{ width: budgetPct + '%' }"></i></div>
        </div>

        <div class="auth-wrap">
          <div v-if="!user" class="row-gap">
            <span class="guest-pill">Guest</span>
            <button class="btn small primary" @click="openAuthScreen('login')">Sign in</button>
          </div>
          <div v-else class="user-menu">
            <button class="avatar-btn" @click="showAccountMenu = !showAccountMenu">
              <span class="avatar-circle">{{ initials(user.name) }}</span>
              <span class="avatar-name">{{ user.name }}</span>
            </button>
            <div v-if="showAccountMenu" class="dropdown">
              <div class="dropdown-head">
                <strong>{{ user.name }}</strong>
                <small class="muted">{{ user.email }}</small>
                <small v-if="user.company" class="muted">{{ user.company }}</small>
              </div>
              <button class="dropdown-item" @click="switchTab('profiles'); showAccountMenu = false">
                Customer Profiles
              </button>
              <button class="dropdown-item" @click="switchTab('history'); showAccountMenu = false">
                Run History
              </button>
              <button class="dropdown-item danger" @click="logout">Sign out</button>
            </div>
          </div>
        </div>
      </div>
    </header>

    <!-- BODY: SIDEBAR + SCROLLABLE MAIN -->
    <div class="app-body">
      <div v-if="sidebarOpen" class="sidebar-backdrop" @click="sidebarOpen = false"></div>

      <!-- LEFT SIDEBAR -->
      <aside :class="['sidebar', { open: sidebarOpen }]">
        <div class="side-section">
          <div class="side-label">Workspace</div>
          <nav class="side-nav" aria-label="Sidebar navigation">
            <button :class="['side-link', { active: activeTab === 'discover' }]" @click="switchTab('discover')">
              <span>Discover Leads</span>
            </button>
            <button :class="['side-link', { active: activeTab === 'profiles' }]" @click="switchTab('profiles')">
              <span>Customer Profiles</span>
              <span class="nav-count">{{ profiles.length }}</span>
            </button>
            <button :class="['side-link', { active: activeTab === 'history' }]" @click="switchTab('history')">
              <span>Run History</span>
              <span v-if="runHistory.length" class="nav-count">{{ runHistory.length }}</span>
            </button>
          </nav>
        </div>

        <div class="side-section">
          <div class="side-label">Saved Profiles</div>
          <div class="side-profiles">
            <button
              v-for="p in profiles.slice(0, 5)"
              :key="p.id"
              :class="['side-profile-btn', { active: activeProfileId === p.id }]"
              @click="loadProfile(p)"
            >
              <strong>{{ p.name }}</strong>
              <small>{{ p.region }} · {{ p.maxLeads || p.max_leads || 5 }} leads</small>
            </button>
            <div v-if="!profiles.length" class="muted" style="padding: 0 8px; font-size: 12.5px">
              {{ user ? "No saved profiles yet." : "Sign in to save profiles." }}
            </div>
          </div>
        </div>

        <div class="side-footer-card">
          <div class="side-label">Account Status</div>
          <div class="api-pill">
            <i :class="user ? 'dot-ok' : 'dot-guest'"></i>
            {{ user ? user.email : "Guest Session" }}
          </div>
          <button
            v-if="!user"
            type="button"
            class="link"
            style="margin-top: 6px; display: inline-block"
            @click="openAuthScreen('register')"
          >
            Create account to save data →
          </button>
        </div>
      </aside>

      <!-- SCROLLABLE CONTENT + FOOTER -->
      <div class="main-wrap">
        <main class="main-content">
          <!-- TAB 1: DISCOVER -->
          <template v-if="activeTab === 'discover'">
            <div v-if="!user" class="guest-banner">
              <span>You are browsing in <b>Guest mode</b>. Runs work normally, and you can sign in anytime to save history &amp; profiles.</span>
              <button class="btn small primary" @click="openAuthScreen('login')">Sign in / Register</button>
            </div>

            <div v-if="activeProfileId" class="active-profile-bar">
              <span>Active Customer Profile: <b>{{ profiles.find((p) => p.id === activeProfileId)?.name }}</b></span>
              <button class="link" @click="activeProfileId = null">Clear</button>
            </div>

            <!-- Hero + Composer -->
            <section class="hero">
              <div class="hero-copy">
                <h1>Find the right companies, then choose who is worth the spend.</h1>
                <p>
                  Enter any target market, industry, region, or buyer signal you want. Review candidates before paid
                  enrichment runs, and control every cent of API spend.
                </p>

                <form class="composer" @submit.prevent="startRun">
                  <textarea
                    v-model="icpQuery"
                    rows="3"
                    placeholder="Describe the companies or leads you want to find (any industry, stage, or region)..."
                    required
                    aria-label="Lead search description"
                  ></textarea>
                  <div class="chips">
                    <button type="button" class="chip save-chip" @click="saveCurrentAsProfile">
                      + Save as Profile
                    </button>
                  </div>
                  <div class="composer-row">
                    <label class="num">
                      Up to
                      <input v-model.number="maxLeads" type="number" min="1" max="25" />
                      leads
                    </label>
                    <button class="btn primary" :disabled="loading">
                      {{ loading ? "Agent is working" : "Start lead discovery" }}
                    </button>
                  </div>
                </form>
              </div>

              <div class="hero-art" :class="{ photo: HERO_PHOTO }" :style="heroStyle" aria-hidden="true">
                <div class="sieve big">
                  <span v-for="n in 5" :key="'g' + n" class="gate" :class="{ amber: n === 4 }"></span>
                  <i
                    v-for="n in 22"
                    :key="'d' + n"
                    class="dot"
                    :class="{ fall: n % 3 === 0 }"
                    :style="{ '--d': n * 0.42 + 's', '--y': ((n * 37) % 70) + 12 + '%' }"
                  ></i>
                </div>
                <div class="art-labels"><span>Discover</span><span>Prefilter</span><span>Your review</span><span>Score</span></div>
              </div>
            </section>

            <!-- Overview Cards -->
            <section v-if="status === 'idle' && !loading" class="overview-grid">
              <div class="overview-card">
                <span class="step-num">01</span>
                <h3>Query-Driven Discovery</h3>
                <p class="muted">Searches matching companies for whatever custom query you enter—never locked to one preset.</p>
              </div>
              <div class="overview-card">
                <span class="step-num">02</span>
                <h3>Human-in-the-Loop Gate</h3>
                <p class="muted">Pauses before enrichment so you select the exact companies worth spending budget on.</p>
              </div>
              <div class="overview-card">
                <span class="step-num">03</span>
                <h3>Scored Outreach &amp; CSV</h3>
                <p class="muted">Ranks approved leads 0–100 with tailored outreach hooks and one-click CSV export.</p>
              </div>
            </section>

            <div v-if="error" class="error" role="alert">
              <b>The run stopped.</b> {{ error }}
            </div>

            <!-- Progress -->
            <ol v-if="step > 0 || loading" class="steps" aria-label="Progress">
              <li v-for="(s, i) in STEPS" :key="s" :class="{ done: i < step, on: i === step }">
                <span>{{ i < step ? "✓" : i + 1 }}</span>{{ s }}
              </li>
            </ol>

            <!-- Working -->
            <section v-if="loading" class="card working" aria-live="polite">
              <div class="sieve">
                <span v-for="n in 5" :key="'g' + n" class="gate" :class="{ amber: n === 4 }"></span>
                <i
                  v-for="n in 16"
                  :key="'d' + n"
                  class="dot"
                  :class="{ fall: n % 3 === 0 }"
                  :style="{ '--d': n * 0.3 + 's', '--y': ((n * 41) % 70) + 12 + '%' }"
                ></i>
              </div>
              <p class="working-msg">{{ loadingMsg }}</p>
              <p class="muted">Working through your query and budget guardrails.</p>
            </section>

            <!-- ICP Plan -->
            <section v-if="icpPlan" class="card">
              <div class="card-head">
                <h2>Parsed search criteria</h2>
                <button class="link" type="button" @click="showRaw = !showRaw">{{ showRaw ? "Hide raw JSON" : "Show raw JSON" }}</button>
              </div>
              <pre v-if="showRaw" class="json">{{ JSON.stringify(icpPlan, null, 2) }}</pre>
              <dl v-else class="plan">
                <template v-for="(v, k) in icpPlan" :key="k">
                  <dt>{{ label(k) }}</dt>
                  <dd>
                    <template v-if="isList(v)"><span v-for="x in v" :key="x" class="tag">{{ x }}</span></template>
                    <template v-else>{{ v }}</template>
                  </dd>
                </template>
              </dl>
            </section>

            <!-- Review Gate -->
            <section v-if="status === 'awaiting_approval'" id="review" class="card gate-card">
              <div class="card-head">
                <div>
                  <h2>Review {{ pendingLeads.length }} candidates</h2>
                  <p class="muted">Uncheck any company you do not want to enrich or score.</p>
                </div>
                <div class="row-gap">
                  <button type="button" class="btn small" @click="toggleAll(true)">Select all</button>
                  <button type="button" class="btn small" @click="toggleAll(false)">Clear</button>
                </div>
              </div>

              <TransitionGroup name="rise" tag="div" class="leads">
                <label
                  v-for="(l, i) in pendingLeads"
                  :key="l.domain"
                  class="lead"
                  :class="{ off: !selectedDomains.includes(l.domain) }"
                  :style="{ '--i': i }"
                >
                  <input v-model="selectedDomains" type="checkbox" :value="l.domain" />
                  <span class="logo" :style="{ '--h': hue(l.domain) }">
                    <b>{{ initials(l.company_name) }}</b>
                    <img v-if="!broken.has(l.domain)" :src="logoUrl(l.domain)" alt="" loading="lazy" @error="broken.add(l.domain)" />
                  </span>
                  <span class="lead-body">
                    <strong>{{ l.company_name }}</strong>
                    <span class="muted"> {{ l.domain }}</span>
                    <span v-if="l.description" class="desc">{{ l.description }}</span>
                  </span>
                </label>
              </TransitionGroup>

              <div class="decide">
                <span>{{ selectedDomains.length }} of {{ pendingLeads.length }} selected</span>
                <div class="row-gap">
                  <button class="btn ghost" :disabled="loading" @click="handleDecision(false)">Reject run</button>
                  <button class="btn go" :disabled="loading || !selectedDomains.length" @click="handleDecision(true)">
                    {{ loading ? "Enriching and scoring" : `Approve ${selectedDomains.length} ${selectedDomains.length === 1 ? "lead" : "leads"}` }}
                  </button>
                </div>
              </div>
            </section>

            <!-- Results -->
            <section v-if="status === 'completed' || status === 'rejected'" id="results" class="card">
              <template v-if="status === 'rejected'">
                <h2>Run rejected</h2>
                <p class="muted">No enrichment was run. Spent ${{ fmt(budgetSpent) }}.</p>
                <button class="btn primary" @click="reset">Start another run</button>
              </template>

              <template v-else-if="!scoredLeads.length">
                <h2>No scored leads returned</h2>
                <p class="muted">Try another query or select candidates at the review step.</p>
                <button class="btn primary" @click="reset">Start another run</button>
              </template>

              <template v-else>
                <div class="card-head">
                  <div>
                    <h2 class="big">{{ counts.all }} {{ counts.all === 1 ? "lead" : "leads" }} scored, {{ counts.hot }} hot.</h2>
                    <p class="muted">
                      Spent ${{ fmt(budgetSpent) }} of ${{ BUDGET_CAP.toFixed(2) }}, about ${{ fmt(budgetSpent / counts.all) }} per lead. Hot is 75 or more.
                    </p>
                  </div>
                  <div class="row-gap">
                    <button class="btn small" @click="exportCsv">Download CSV</button>
                    <button class="btn small" @click="reset">New run</button>
                  </div>
                </div>

                <div class="dist" role="img" :aria-label="`${counts.hot} hot, ${counts.warm} warm, ${counts.cold} cold`">
                  <span class="hot" :style="{ width: (counts.hot / counts.all) * 100 + '%' }"></span>
                  <span class="warm" :style="{ width: (counts.warm / counts.all) * 100 + '%' }"></span>
                  <span class="cold" :style="{ width: (counts.cold / counts.all) * 100 + '%' }"></span>
                </div>

                <div class="chips tabs">
                  <button
                    v-for="f in ['all', 'hot', 'warm', 'cold']"
                    :key="f"
                    class="chip"
                    :class="{ on: filter === f }"
                    :aria-pressed="filter === f"
                    @click="filter = f"
                  >
                    {{ f[0].toUpperCase() + f.slice(1) }} {{ counts[f] }}
                  </button>
                </div>

                <TransitionGroup name="rise" tag="ol" class="results">
                  <li v-for="(l, i) in visibleLeads" :key="l.domain" :style="{ '--i': i }">
                    <button class="res" :aria-expanded="open === l.domain" @click="open = open === l.domain ? null : l.domain">
                      <span class="rank">{{ i + 1 }}</span>
                      <span class="logo" :style="{ '--h': hue(l.domain) }">
                        <b>{{ initials(l.company_name) }}</b>
                        <img v-if="!broken.has(l.domain)" :src="logoUrl(l.domain)" alt="" loading="lazy" @error="broken.add(l.domain)" />
                      </span>
                      <span class="res-main">
                        <strong>{{ l.company_name }}</strong>
                        <span class="muted">{{ l.domain }}</span>
                      </span>
                      <svg class="ring" :class="tier(l.score)" viewBox="0 0 44 44" role="img" :aria-label="`Score ${l.score} out of 100`">
                        <circle cx="22" cy="22" r="18" class="track" />
                        <circle
                          cx="22"
                          cy="22"
                          r="18"
                          class="arc"
                          :style="{ strokeDasharray: (ringsReady ? (l.score || 0) * 1.131 : 0) + ' 113.1' }"
                        />
                        <text x="22" y="26.5" text-anchor="middle">{{ l.score }}</text>
                      </svg>
                    </button>
                    <div v-show="open === l.domain" class="more">
                      <p v-if="l.angle"><b>Outreach angle.</b> {{ l.angle }}</p>
                      <p v-if="l.email" class="mail">
                        {{ l.email }}
                        <button class="link" @click="copy(l.email)">Copy email</button>
                      </p>
                      <p v-else class="muted">No contact email returned for this lead.</p>
                    </div>
                  </li>
                </TransitionGroup>
              </template>
            </section>
          </template>

          <!-- TAB 2: CUSTOMER PROFILES -->
          <template v-else-if="activeTab === 'profiles'">
            <section v-if="!user" class="card" style="margin-top: 0">
              <h2>Sign in to save Customer Profiles</h2>
              <p class="muted" style="margin: 8px 0 14px">
                Customer profiles are stored privately per user in PostgreSQL. Sign in or create a free account to save and reuse search templates.
              </p>
              <div class="row-gap">
                <button class="btn primary" @click="openAuthScreen('login')">Sign In</button>
                <button class="btn" @click="openAuthScreen('register')">Create Account</button>
              </div>
            </section>

            <template v-else>
              <section class="card" style="margin-top: 0">
                <div class="card-head">
                  <div>
                    <h2>Create Customer Profile</h2>
                    <p class="muted">Save reusable target queries to your account in PostgreSQL.</p>
                  </div>
                </div>
                <form class="profile-form" @submit.prevent="saveNewProfile">
                  <div class="grid-2">
                    <label class="field">
                      Profile Name
                      <input v-model="newProfile.name" placeholder="Target segment name" required />
                    </label>
                    <label class="field">
                      Industry
                      <input v-model="newProfile.industry" placeholder="Industry or vertical" />
                    </label>
                    <label class="field">
                      Company Size
                      <input v-model="newProfile.size" placeholder="Employee range" />
                    </label>
                    <label class="field">
                      Region
                      <input v-model="newProfile.region" placeholder="Country or region" />
                    </label>
                  </div>
                  <label class="field">
                    Search Query
                    <textarea v-model="newProfile.query" rows="2" placeholder="Describe the companies you want to discover..." required></textarea>
                  </label>
                  <div class="composer-row">
                    <label class="num">
                      Default max leads
                      <input v-model.number="newProfile.maxLeads" type="number" min="1" max="25" />
                    </label>
                    <button type="submit" class="btn primary">Save Profile</button>
                  </div>
                </form>
              </section>

              <section class="card">
                <h2>Saved Profiles ({{ profiles.length }})</h2>
                <div v-if="!profiles.length" class="muted" style="margin-top: 10px">No saved profiles for this account yet.</div>
                <div v-else class="profile-grid">
                  <article v-for="p in profiles" :key="p.id" class="profile-card">
                    <div class="profile-top">
                      <strong>{{ p.name }}</strong>
                      <span class="tag">{{ p.industry }}</span>
                    </div>
                    <p class="muted profile-meta">{{ p.size }} · {{ p.region }} · Max {{ p.maxLeads || p.max_leads || 5 }} leads</p>
                    <p class="profile-query">"{{ p.query }}"</p>
                    <div class="row-gap" style="margin-top: 12px">
                      <button class="btn small primary" @click="loadProfile(p)">Load into Search</button>
                      <button class="btn small" @click="deleteProfile(p.id)">Delete</button>
                    </div>
                  </article>
                </div>
              </section>
            </template>
          </template>

          <!-- TAB 3: RUN HISTORY -->
          <template v-else-if="activeTab === 'history'">
            <section class="card" style="margin-top: 0">
              <div class="card-head">
                <div>
                  <h2>Run History</h2>
                  <p class="muted">
                    {{ user ? "Your account's saved search runs in PostgreSQL." : "Session runs (sign in to save runs permanently across sessions)." }}
                  </p>
                </div>
                <button v-if="runHistory.length && user" class="btn small" @click="clearRunHistory">Clear history</button>
              </div>
              <div v-if="!runHistory.length" class="muted">No runs recorded yet.</div>
              <div v-else class="leads">
                <div v-for="h in runHistory" :key="h.id" class="history-row">
                  <div>
                    <strong>{{ h.query }}</strong>
                    <div class="muted">{{ h.date }} · {{ h.leadsCount ?? h.leads_count ?? 0 }} leads · Spent ${{ fmt(h.spent ?? h.spent_usd) }}</div>
                  </div>
                  <span :class="['badge', 'st-' + h.status]"><i></i>{{ h.status }}</span>
                </div>
              </div>
            </section>
          </template>
        </main>

        <!-- FOOTER -->
        <footer class="app-footer">
          <div class="footer-left">
            <b>Sieve</b>
            <span class="muted">Lead Intelligence Platform with Human-in-the-Loop Budget Control.</span>
          </div>
          <div class="footer-links">
            <button class="link" @click="switchTab('discover')">Discover</button>
            <button class="link" @click="switchTab('profiles')">Profiles</button>
            <button class="link" @click="switchTab('history')">History</button>
          </div>
          <div class="footer-stack">
            <span class="tag">LangGraph</span>
            <span class="tag">Gemini</span>
            <span class="tag">FastAPI</span>
            <span class="tag">PostgreSQL</span>
          </div>
        </footer>
      </div>
    </div>

    <Transition name="stamp">
      <div v-if="stamp" class="stamp" :class="stamp.toLowerCase()" aria-hidden="true">{{ stamp }}</div>
    </Transition>
  </div>
</template>

<style>
@import url("https://fonts.googleapis.com/css2?family=Bricolage+Grotesque:opsz,wght@12..96,500;12..96,800&family=Public+Sans:wght@400;500;600&display=swap");

:root {
  --paper: #edf0f5;
  --surface: #fff;
  --ink: #0f1a3a;
  --muted: #5b6586;
  --line: #d5dae6;
  --ultra: #2f3df5;
  --ultra-soft: #e4e7ff;
  --flame: #f2542d;
  --amber: #e6a700;
  --cold: #8a93ad;
  --ok: #0e9f6e;
  --head: "Bricolage Grotesque", "Segoe UI", system-ui, sans-serif;
  --body: "Public Sans", "Segoe UI", system-ui, sans-serif;
  --header-h: 64px;
  --sidebar-w: 250px;
}

body {
  display: flex;
  justify-content: center;
  align-items: center;
  min-height: 100vh;
  min-width: 0;
  margin: 0;
  background: var(--paper);
  color: var(--ink);
  font: 400 15px/1.5 var(--body);
  -webkit-font-smoothing: antialiased;
}
#app {
  display: flex;
  justify-content: center;
  align-items: center;
  min-height: 100vh;
  width: 100%;
  max-width: none;
  margin: 0;
  padding: 0;
  text-align: left;
}
*, *::before, *::after { box-sizing: border-box; }
button, input, textarea { font: inherit; color: inherit; }
:focus-visible { outline: 2px solid var(--ultra); outline-offset: 2px; }
h1, h2, h3 { font-family: var(--head); margin: 0; letter-spacing: -0.01em; }
.muted { color: var(--muted); font-size: 0.9rem; }

/* ==================== FIRST-SCREEN LOGIN + SKIP GATE ==================== */
.auth-gate {
  min-height: 100vh;
  width: 100%;
  display: grid;
  place-items: center;
  padding: 24px 16px;
  background: radial-gradient(circle at top right, #dde2ff 0%, var(--paper) 55%);
}
.auth-gate-card {
  width: 100%;
  max-width: 440px;
  background: var(--surface);
  border: 1px solid var(--line);
  border-radius: 20px;
  padding: 28px;
  box-shadow: 0 24px 60px rgba(15, 26, 58, 0.12);
}
.auth-gate-brand {
  display: flex;
  align-items: center;
  gap: 12px;
  margin-bottom: 20px;
}
.auth-gate-brand b { display: block; font: 800 24px/1 var(--head); letter-spacing: -0.02em; }
.auth-gate-brand small { color: var(--muted); font-size: 13px; }
.auth-tabs {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 6px;
  background: var(--paper);
  padding: 4px;
  border-radius: 12px;
  margin-bottom: 14px;
}
.auth-tab {
  border: 0;
  background: transparent;
  padding: 8px 12px;
  border-radius: 9px;
  font-weight: 600;
  font-size: 14px;
  color: var(--muted);
  cursor: pointer;
}
.auth-tab.active {
  background: var(--surface);
  color: var(--ultra);
  box-shadow: 0 2px 6px rgba(15, 26, 58, 0.08);
}
.auth-divider {
  display: flex;
  align-items: center;
  gap: 10px;
  margin: 16px 0 12px;
  color: var(--muted);
  font-size: 12.5px;
}
.auth-divider::before,
.auth-divider::after {
  content: "";
  flex: 1;
  height: 1px;
  background: var(--line);
}
.skip-btn {
  width: 100%;
  background: var(--paper);
  border-color: var(--line);
  color: var(--ink);
}
.skip-btn:hover {
  border-color: var(--ultra);
  color: var(--ultra);
}
.guest-pill {
  background: var(--paper);
  border: 1px solid var(--line);
  color: var(--muted);
  font-size: 12px;
  font-weight: 600;
  padding: 4px 10px;
  border-radius: 99px;
}
.guest-banner {
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: 12px;
  flex-wrap: wrap;
  background: var(--surface);
  border: 1px solid var(--line);
  border-radius: 12px;
  padding: 10px 14px;
  font-size: 13.5px;
  margin-bottom: 18px;
}

/* ==================== APP SHELL ==================== */
.app-shell {
  min-height: 100vh;
  width: 100%;
  display: flex;
  flex-direction: column;
}

.app-header {
  position: sticky;
  top: 0;
  z-index: 35;
  height: var(--header-h);
  background: rgba(255, 255, 255, 0.92);
  backdrop-filter: blur(10px);
  border-bottom: 1px solid var(--line);
  padding: 0 20px;
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: 14px;
}
.header-left, .header-right { display: flex; align-items: center; gap: 14px; }
.menu-toggle {
  display: none;
  background: var(--paper);
  border: 1px solid var(--line);
  border-radius: 8px;
  padding: 4px 10px;
  font-size: 18px;
  cursor: pointer;
}
.brand { display: flex; align-items: center; gap: 10px; cursor: pointer; }
.brand b { display: block; font: 800 20px/1 var(--head); letter-spacing: -0.02em; }
.brand small { color: var(--muted); font-size: 12px; }

.app-body {
  display: flex;
  flex: 1;
  align-items: stretch;
}

.sidebar {
  width: var(--sidebar-w);
  flex-shrink: 0;
  background: var(--surface);
  border-right: 1px solid var(--line);
  padding: 20px 14px;
  display: flex;
  flex-direction: column;
  gap: 22px;
  position: sticky;
  top: var(--header-h);
  height: calc(100vh - var(--header-h));
  overflow-y: auto;
}
.side-label {
  font-size: 11px;
  font-weight: 700;
  text-transform: uppercase;
  letter-spacing: 0.06em;
  color: var(--muted);
  margin-bottom: 8px;
  padding: 0 8px;
}
.side-nav { display: flex; flex-direction: column; gap: 4px; }
.side-link {
  width: 100%;
  display: flex;
  justify-content: space-between;
  align-items: center;
  background: transparent;
  border: 0;
  padding: 9px 12px;
  border-radius: 10px;
  font-size: 14px;
  font-weight: 600;
  color: var(--muted);
  cursor: pointer;
  text-align: left;
}
.side-link:hover { background: var(--paper); color: var(--ink); }
.side-link.active { background: var(--ultra-soft); color: var(--ultra); }
.nav-count {
  background: var(--surface);
  color: var(--ultra);
  font-size: 11px;
  padding: 1px 7px;
  border-radius: 99px;
  border: 1px solid var(--line);
}

.side-profiles { display: flex; flex-direction: column; gap: 6px; }
.side-profile-btn {
  width: 100%;
  text-align: left;
  background: #fafbfe;
  border: 1px solid var(--line);
  border-radius: 10px;
  padding: 8px 10px;
  cursor: pointer;
}
.side-profile-btn:hover { border-color: var(--ultra); }
.side-profile-btn.active { border-color: var(--ultra); background: var(--ultra-soft); }
.side-profile-btn strong { display: block; font-size: 13px; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.side-profile-btn small { color: var(--muted); font-size: 11.5px; }

.side-footer-card {
  margin-top: auto;
  background: var(--paper);
  border: 1px solid var(--line);
  border-radius: 12px;
  padding: 12px;
}
.api-pill { display: flex; align-items: center; gap: 7px; font-size: 13px; font-weight: 600; word-break: break-all; }
.dot-ok { width: 8px; height: 8px; border-radius: 50%; background: var(--ok); display: inline-block; flex-shrink: 0; }
.dot-guest { width: 8px; height: 8px; border-radius: 50%; background: var(--amber); display: inline-block; flex-shrink: 0; }

.main-wrap {
  flex: 1;
  min-width: 0;
  display: flex;
  flex-direction: column;
}
.main-content {
  flex: 1;
  width: 100%;
  max-width: 1020px;
  margin: 0 auto;
  padding: 28px clamp(16px, 3.5vw, 36px) 56px;
}

.active-profile-bar {
  display: flex;
  justify-content: space-between;
  align-items: center;
  background: var(--ultra-soft);
  border: 1px solid #c7ceff;
  color: var(--ink);
  padding: 8px 14px;
  border-radius: 10px;
  font-size: 13.5px;
  margin-bottom: 18px;
}

.overview-grid {
  display: grid;
  grid-template-columns: repeat(3, 1fr);
  gap: 14px;
  margin-top: 28px;
}
.overview-card {
  background: var(--surface);
  border: 1px solid var(--line);
  border-radius: 14px;
  padding: 18px;
}
.overview-card h3 { font-size: 16px; margin: 8px 0 6px; }
.overview-card p { margin: 0; font-size: 13.5px; }
.step-num {
  display: inline-block;
  font: 800 12px var(--head);
  color: var(--ultra);
  background: var(--ultra-soft);
  padding: 2px 8px;
  border-radius: 99px;
}

.app-footer {
  border-top: 1px solid var(--line);
  background: var(--surface);
  padding: 20px clamp(16px, 3.5vw, 36px);
  display: flex;
  justify-content: space-between;
  align-items: center;
  flex-wrap: wrap;
  gap: 14px;
}
.footer-left { display: flex; flex-direction: column; gap: 2px; }
.footer-links, .footer-stack { display: flex; align-items: center; gap: 12px; flex-wrap: wrap; }

.auth-wrap { position: relative; }
.avatar-btn { display: inline-flex; align-items: center; gap: 8px; background: var(--paper); border: 1px solid var(--line); border-radius: 99px; padding: 4px 12px 4px 4px; cursor: pointer; font-size: 13.5px; font-weight: 600; }
.avatar-circle { width: 28px; height: 28px; border-radius: 50%; background: var(--ultra); color: #fff; display: grid; place-items: center; font: 700 12px var(--head); }
.dropdown { position: absolute; right: 0; top: calc(100% + 8px); width: 220px; background: var(--surface); border: 1px solid var(--line); border-radius: 12px; box-shadow: 0 12px 30px rgba(15, 26, 58, 0.14); padding: 8px; z-index: 50; }
.dropdown-head { padding: 8px; border-bottom: 1px solid var(--line); margin-bottom: 6px; display: flex; flex-direction: column; }
.dropdown-item { width: 100%; text-align: left; background: none; border: 0; padding: 8px; border-radius: 8px; cursor: pointer; font-size: 13.5px; }
.dropdown-item:hover { background: var(--paper); }
.dropdown-item.danger { color: var(--flame); }

.profile-form { display: flex; flex-direction: column; gap: 12px; }
.grid-2 { display: grid; grid-template-columns: 1fr 1fr; gap: 12px; }
.field { display: flex; flex-direction: column; gap: 5px; font-size: 13.5px; font-weight: 600; }
.field input, .field textarea { border: 1px solid var(--line); border-radius: 10px; padding: 9px 12px; background: var(--paper); font-weight: 400; }
.profile-grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(260px, 1fr)); gap: 12px; margin-top: 14px; }
.profile-card { border: 1px solid var(--line); border-radius: 12px; padding: 14px; background: #fafbfe; }
.profile-top { display: flex; justify-content: space-between; align-items: flex-start; gap: 8px; }
.profile-meta { font-size: 12.5px; margin: 6px 0; }
.profile-query { font-size: 13.5px; margin: 0; color: var(--ink); }
.history-row { display: flex; justify-content: space-between; align-items: center; gap: 12px; padding: 12px 14px; border: 1px solid var(--line); border-radius: 12px; }
.save-chip { border-style: dashed; border-color: var(--ultra); color: var(--ultra); background: transparent; }

.badge { display: inline-flex; align-items: center; gap: 8px; padding: 5px 12px; border-radius: 99px; background: var(--paper); border: 1px solid var(--line); font-size: 13px; font-weight: 500; }
.badge i { width: 8px; height: 8px; border-radius: 50%; background: var(--cold); }
.badge.st-running i { background: var(--ultra); animation: pulse 1.2s infinite; }
.badge.st-awaiting_approval i { background: var(--amber); animation: pulse 1.6s infinite; }
.badge.st-completed i { background: var(--ok); }
.badge.st-rejected i { background: var(--flame); }
@keyframes pulse { 50% { transform: scale(1.6); opacity: 0.5; } }
.budget { min-width: 150px; }
.budget-row { display: flex; align-items: baseline; gap: 5px; font-size: 12.5px; color: var(--muted); }
.budget-row b { color: var(--ink); font: 700 14px var(--head); font-variant-numeric: tabular-nums; }
.budget .cap { margin-left: auto; }
.meter { height: 5px; border-radius: 99px; background: var(--line); margin-top: 4px; overflow: hidden; }
.meter i { display: block; height: 100%; background: var(--ultra); border-radius: 99px; transition: width 0.7s cubic-bezier(0.2, 0.8, 0.2, 1), background 0.3s; }
.meter i.warn { background: var(--flame); }

.hero { display: grid; grid-template-columns: minmax(0, 1.15fr) minmax(0, 0.85fr); gap: clamp(20px, 3vw, 36px); align-items: center; }
.hero h1 { font-size: clamp(28px, 3.8vw, 44px); line-height: 1.06; font-weight: 800; }
.hero p { color: var(--muted); max-width: 54ch; margin: 12px 0 18px; }
.composer { background: var(--surface); border: 1px solid var(--line); border-radius: 16px; padding: 8px 8px 8px 18px; transition: border-color 0.15s, box-shadow 0.15s; }
.composer:focus-within { border-color: var(--ultra); box-shadow: 0 0 0 3px var(--ultra-soft); }
.composer textarea { width: 100%; border: 0; outline: none; resize: none; background: none; padding: 10px 0 6px; font-size: 16px; line-height: 1.4; }
.chips { display: flex; flex-wrap: wrap; gap: 6px; padding-right: 10px; }
.chip { border: 1px solid var(--line); background: var(--paper); border-radius: 99px; padding: 4px 12px; font-size: 12.5px; cursor: pointer; }
.chip:hover { border-color: var(--ultra); color: var(--ultra); }
.chip.on { background: var(--ink); border-color: var(--ink); color: #fff; }
.composer-row { display: flex; justify-content: space-between; align-items: center; flex-wrap: wrap; gap: 10px; padding: 10px 6px 4px 0; }
.num { display: flex; align-items: center; gap: 8px; color: var(--muted); font-size: 14px; }
.num input { width: 60px; border: 1px solid var(--line); border-radius: 8px; padding: 6px 8px; background: var(--paper); }

.btn { border: 1px solid var(--line); background: var(--surface); border-radius: 10px; padding: 10px 18px; cursor: pointer; font-weight: 600; font-size: 14px; }
.btn:hover:not(:disabled) { border-color: var(--ink); }
.btn.small { padding: 6px 12px; font-size: 13px; }
.btn.primary { background: var(--ultra); border-color: var(--ultra); color: #fff; }
.btn.primary:hover:not(:disabled) { background: #1f2de0; border-color: #1f2de0; }
.btn.ghost { background: transparent; color: #fff; border-color: rgba(255, 255, 255, 0.3); }
.btn.go { background: #fff; color: var(--ink); border-color: #fff; }
.btn:disabled { opacity: 0.5; cursor: not-allowed; }
.link { background: none; border: 0; padding: 0; color: var(--ultra); cursor: pointer; font-size: 13px; text-decoration: underline; }

.hero-art { background: var(--surface); border: 1px solid var(--line); border-radius: 18px; padding: 18px 16px 12px; background-size: cover; background-position: center; }
.sieve { position: relative; height: 150px; display: flex; justify-content: space-around; overflow: hidden; }
.sieve.big { height: 230px; }
.sieve .gate { width: 3px; height: 100%; background: linear-gradient(to bottom, var(--ink) 0 38%, transparent 38% 62%, var(--ink) 62% 100%); opacity: 0.85; }
.sieve .gate.amber { width: 5px; background: linear-gradient(to bottom, var(--amber) 0 42%, transparent 42% 58%, var(--amber) 58% 100%); }
.dot { position: absolute; left: -3%; top: var(--y); width: 8px; height: 8px; border-radius: 50%; background: var(--ultra); opacity: 0; animation: flow 6.5s linear var(--d) infinite; }
.dot.fall { animation-name: flowfall; }
@keyframes flow { 0% { left: -3%; opacity: 0; } 8% { opacity: 1; } 92% { opacity: 1; background: var(--flame); } 100% { left: 103%; opacity: 0; background: var(--flame); } }
@keyframes flowfall { 0% { left: -3%; top: var(--y); opacity: 0; } 8% { opacity: 1; } 52% { left: 50%; top: var(--y); opacity: 1; } 75% { left: 56%; top: calc(var(--y) + 45%); opacity: 0; } 100% { opacity: 0; } }
.art-labels { display: flex; justify-content: space-around; font-size: 12.5px; color: var(--muted); padding-top: 8px; border-top: 1px solid var(--line); }

.error { margin-top: 22px; background: #fff1ef; border: 1px solid var(--flame); color: #7a1f0b; border-radius: 12px; padding: 14px 16px; }
.error .hint { display: block; color: #9a4a37; font-size: 13px; margin-top: 4px; }
.steps { list-style: none; display: flex; gap: 8px; margin: 30px 0 0; padding: 0; flex-wrap: wrap; }
.steps li { display: flex; align-items: center; gap: 8px; font-size: 14px; color: var(--muted); padding-right: 18px; }
.steps li span { width: 24px; height: 24px; border-radius: 50%; display: grid; place-items: center; font-size: 12px; font-weight: 700; border: 1.5px solid var(--line); background: var(--surface); }
.steps li.on { color: var(--ink); font-weight: 600; }
.steps li.on span { border-color: var(--ultra); background: var(--ultra); color: #fff; }
.steps li.done span { border-color: var(--ink); background: var(--ink); color: #fff; }
.card { background: var(--surface); border: 1px solid var(--line); border-radius: 16px; padding: 22px; margin-top: 18px; position: relative; }
.card h2 { font-size: 22px; font-weight: 800; }
.card h2.big { font-size: clamp(24px, 3.2vw, 32px); line-height: 1.1; }
.card-head { display: flex; justify-content: space-between; align-items: flex-start; gap: 14px; flex-wrap: wrap; margin-bottom: 16px; }
.card-head p { margin: 6px 0 0; }
.row-gap { display: flex; gap: 8px; flex-wrap: wrap; }
.working { text-align: center; }
.working-msg { font: 700 18px var(--head); margin: 10px 0 2px; }
.json { background: var(--paper); border-radius: 10px; padding: 14px; overflow-x: auto; font-size: 12.5px; margin: 0; }
.plan { display: grid; grid-template-columns: max-content 1fr; gap: 10px 22px; margin: 0; }
.plan dt { color: var(--muted); font-size: 14px; padding-top: 3px; }
.plan dd { margin: 0; display: flex; flex-wrap: wrap; gap: 6px; align-items: center; }
.tag { background: var(--ultra-soft); color: #1a25b8; border-radius: 99px; padding: 2px 11px; font-size: 12px; font-weight: 500; }

.gate-card { border-color: var(--amber); box-shadow: 0 0 0 4px #fff4d1; }
.leads { display: flex; flex-direction: column; gap: 8px; }
.lead { display: grid; grid-template-columns: 22px 46px 1fr; gap: 14px; align-items: center; padding: 12px 14px; border: 1px solid var(--line); border-radius: 12px; cursor: pointer; transition: opacity 0.2s, background 0.2s; }
.lead:hover { background: #f7f8fc; }
.lead.off { opacity: 0.45; }
.lead input { width: 18px; height: 18px; accent-color: var(--ultra); margin: 0; }
.lead-body strong { font-weight: 600; }
.desc { display: block; font-size: 13.5px; color: var(--muted); margin-top: 2px; }
.logo { position: relative; width: 46px; height: 46px; border-radius: 12px; display: grid; place-items: center; overflow: hidden; background: hsl(var(--h) 70% 90%); color: hsl(var(--h) 55% 28%); font: 800 15px var(--head); border: 1px solid var(--line); }
.logo img { position: absolute; inset: 0; width: 100%; height: 100%; object-fit: contain; padding: 9px; background: #fff; }
.decide { position: sticky; bottom: 14px; margin-top: 16px; background: var(--ink); color: #fff; border-radius: 14px; padding: 12px 14px 12px 20px; display: flex; justify-content: space-between; align-items: center; flex-wrap: wrap; gap: 12px; box-shadow: 0 10px 30px rgba(15, 26, 58, 0.25); }
.decide > span { font-size: 14px; opacity: 0.85; }

.dist { display: flex; height: 14px; border-radius: 99px; overflow: hidden; background: var(--line); max-width: 560px; margin-bottom: 16px; }
.dist span { transition: width 0.9s cubic-bezier(0.2, 0.8, 0.2, 1); }
.dist .hot { background: var(--flame); }
.dist .warm { background: var(--amber); }
.dist .cold { background: var(--cold); }
.tabs { margin-bottom: 12px; }
.results { list-style: none; padding: 0; margin: 0; border: 1px solid var(--line); border-radius: 14px; overflow: hidden; }
.results li + li { border-top: 1px solid var(--line); }
.res { display: grid; grid-template-columns: 26px 46px 1fr 56px; gap: 14px; align-items: center; width: 100%; text-align: left; background: none; border: 0; padding: 13px 16px; cursor: pointer; }
.res:hover { background: #f7f8fc; }
.rank { font: 700 15px var(--head); color: var(--muted); }
.res-main strong { display: block; font-weight: 600; }
.ring { width: 52px; height: 52px; transform: rotate(-90deg); }
.ring text { transform: rotate(90deg); transform-origin: 22px 22px; font: 800 13px var(--head); fill: var(--ink); }
.ring .track { fill: none; stroke: var(--paper); stroke-width: 4; }
.ring .arc { fill: none; stroke-width: 4; stroke-linecap: round; transition: stroke-dasharray 1s cubic-bezier(0.2, 0.8, 0.2, 1); }
.ring.hot .arc { stroke: var(--flame); }
.ring.warm .arc { stroke: var(--amber); }
.ring.cold .arc { stroke: var(--cold); }
.more { padding: 2px 16px 16px 102px; font-size: 14px; }
.more p { margin: 8px 0; max-width: 70ch; }
.mail { display: flex; gap: 12px; align-items: center; flex-wrap: wrap; }

.rise-enter-active { transition: opacity 0.35s ease, transform 0.35s ease; transition-delay: calc(var(--i, 0) * 45ms); }
.rise-enter-from { opacity: 0; transform: translateY(8px); }
.stamp { position: fixed; left: 50%; top: 38%; transform: translate(-50%, -50%) rotate(-9deg); font: 800 clamp(44px, 9vw, 84px) var(--head); padding: 4px 30px; border: 6px solid var(--ok); color: var(--ok); border-radius: 12px; background: rgba(255, 255, 255, 0.9); pointer-events: none; z-index: 50; }
.stamp.rejected { border-color: var(--flame); color: var(--flame); }
.stamp-enter-active { transition: transform 0.35s cubic-bezier(0.2, 0.9, 0.3, 1.2), opacity 0.2s; }
.stamp-leave-active { transition: opacity 0.4s; }
.stamp-enter-from { opacity: 0; transform: translate(-50%, -50%) rotate(-9deg) scale(1.9); }
.stamp-leave-to { opacity: 0; }

.sidebar-backdrop { display: none; }
@media (max-width: 960px) {
  .menu-toggle { display: inline-block; }
  .sidebar {
    position: fixed;
    left: 0;
    top: var(--header-h);
    z-index: 45;
    transform: translateX(-100%);
    transition: transform 0.25s ease;
    box-shadow: 10px 0 30px rgba(15, 26, 58, 0.15);
  }
  .sidebar.open { transform: translateX(0); }
  .sidebar-backdrop {
    display: block;
    position: fixed;
    inset: var(--header-h) 0 0 0;
    background: rgba(15, 26, 58, 0.35);
    z-index: 40;
  }
  .hero, .overview-grid, .grid-2 { grid-template-columns: 1fr; }
  .hero-art { order: -1; }
  .sieve.big { height: 170px; }
  .more { padding-left: 16px; }
  .plan { grid-template-columns: 1fr; gap: 4px; }
}
@media (max-width: 600px) {
  .budget, .badge { display: none; }
}
</style>