const API_BASE = '/api';
let token = localStorage.getItem('hq_token');

const DOM = {
    loginPage: document.getElementById('login-container'),
    dashPage: document.getElementById('dashboard-container'),
    loginBtn: document.getElementById('login-btn'),
    pwInput: document.getElementById('password-input'),
    loginError: document.getElementById('login-error'),
    logoutBtn: document.getElementById('logout-btn'),
    navLinks: document.querySelectorAll('.nav-links li'),
    panels: document.querySelectorAll('.panel'),
    
    // Stats
    sUsers: document.getElementById('stat-users'),
    sCoins: document.getElementById('stat-coins'),
    sPing: document.getElementById('stat-ping'),
    sWeather: document.getElementById('stat-weather'),
    
    // Users
    usersTbody: document.getElementById('users-tbody'),
    userModal: document.getElementById('user-modal'),
    mUserName: document.getElementById('modal-user-name'),
    mUserId: document.getElementById('modal-user-id'),
    mCoins: document.getElementById('mod-coins'),
    mRp: document.getElementById('mod-rp'),
    mBoat: document.getElementById('mod-boat'),
    mRod: document.getElementById('mod-rod'),
    mItemName: document.getElementById('mod-item-name'),
    mItemAmt: document.getElementById('mod-item-amt'),
    btnModalSave: document.getElementById('btn-modal-save'),
    btnModalClose: document.getElementById('btn-modal-close'),
    btnModGive: document.getElementById('btn-mod-give'),
    btnModTake: document.getElementById('btn-mod-take'),

    // Market
    marketFish: document.getElementById('market-fish-str'),
    marketPrice: document.getElementById('market-price-input'),
    btnMarketUpdate: document.getElementById('btn-market-update'),
    marketTbody: document.getElementById('market-tbody'),
    marketSearch: document.getElementById('market-search'),

    // Server
    notiTitle: document.getElementById('noti-title'),
    notiContent: document.getElementById('noti-content'),
    btnSendNoti: document.getElementById('btn-send-noti'),
    weatherSelect: document.getElementById('weather-select'),
    btnChangeWeather: document.getElementById('btn-change-weather'),

    // Global
    toastContainer: document.getElementById('toast-container'),
    fishListDatlist: document.getElementById('fish-list')
};

let currentUserEditing = null;
let globalMarketData = [];

function showToast(message, type="success") {
    const toast = document.createElement('div');
    toast.className = `toast ${type}`;
    toast.innerText = message;
    DOM.toastContainer.appendChild(toast);
    setTimeout(() => { toast.remove(); }, 3000);
}

function setLoading(btn, isLoading, originalText = '') {
    if (isLoading) {
        btn.dataset.originalText = btn.innerText;
        btn.classList.add('btn-loading');
    } else {
        btn.classList.remove('btn-loading');
        if (originalText) btn.innerText = originalText;
        else btn.innerText = btn.dataset.originalText || '';
    }
}

async function apiCall(endpoint, method = 'GET', body = null) {
    const headers = { 'Content-Type': 'application/json' };
    if (token) headers['Authorization'] = `Bearer ${token}`;
    
    const options = { method, headers };
    if (body) options.body = JSON.stringify(body);

    const res = await fetch(`${API_BASE}${endpoint}`, options);
    
    if (res.status === 401) {
        logout();
        throw new Error("Unauthorized");
    }
    return res.json();
}

function initAuth() {
    if (token) {
        DOM.loginPage.classList.add('hidden');
        DOM.dashPage.classList.remove('hidden');
        loadDashboard();
    } else {
        DOM.loginPage.classList.remove('hidden');
        DOM.dashPage.classList.add('hidden');
    }
}

async function login() {
    const pw = DOM.pwInput.value;
    try {
        const res = await fetch(`${API_BASE}/login`, {
            method: 'POST',
            headers: {'Content-Type':'application/json'},
            body: JSON.stringify({password: pw})
        });
        const data = await res.json();
        if (data.success) {
            token = data.token;
            localStorage.setItem('hq_token', token);
            initAuth();
            DOM.loginError.classList.add('hidden');
        } else {
            DOM.loginError.classList.remove('hidden');
        }
    } catch(e) {
        console.error(e);
        DOM.loginError.classList.remove('hidden');
    }
}

function logout() {
    token = null;
    localStorage.removeItem('hq_token');
    initAuth();
}

function switchPanel(targetId) {
    DOM.navLinks.forEach(l => l.classList.remove('active'));
    DOM.panels.forEach(p => p.classList.remove('active'));
    document.querySelector(`[data-target="${targetId}"]`).classList.add('active');
    document.getElementById(targetId).classList.add('active');
    
    if(targetId === 'panel-home') loadStats();
    if(targetId === 'panel-users') loadUsers();
    if(targetId === 'panel-market') loadMarket();
}

async function loadStats() {
    try {
        const res = await apiCall('/stats');
        if(res.success) {
            DOM.sUsers.innerText = res.data.total_users + " 명";
            DOM.sCoins.innerText = res.data.total_coins.toLocaleString() + " C";
            DOM.sPing.innerText = res.data.bot_latency + " ms";
            DOM.sWeather.innerText = res.data.current_weather;
        } else {
            showToast("통계 에러: " + res.error, "error");
        }
    } catch(e) { showToast("네트워크 오류: " + e.message, "error"); }
}

async function loadUsers() {
    try {
        const res = await apiCall('/users');
        if(res.success) {
            DOM.usersTbody.innerHTML = '';
            res.data.forEach(u => {
                const tr = document.createElement('tr');
                const avatar = u.avatar ? `<img src="${u.avatar}" class="user-avatar">` : `<div class="user-avatar" style="display:inline-block; background:#fff"></div>`;
                tr.innerHTML = `
                    <td><code>${u.user_id}</code></td>
                    <td>${avatar} <b>${u.name}</b></td>
                    <td><span style="color:var(--warn)">${u.rating}</span> RP</td>
                    <td><span style="color:var(--accent)">${u.coins.toLocaleString()}</span> C</td>
                    <td>Lv.${u.rod_tier} 🎣 / T.${u.boat_tier} ⛵</td>
                    <td><button class="action-btn" onclick='openModal(${JSON.stringify(u)})'>강제 개입</button></td>
                `;
                DOM.usersTbody.appendChild(tr);
            });
        } else {
            showToast("유저 목록 에러: " + res.error, "error");
        }
    } catch(e) { showToast("네트워크 오류: " + e.message, "error"); }
}

function openModal(user) {
    currentUserEditing = user;
    DOM.mUserName.innerText = user.name;
    DOM.mUserId.innerText = `ID: ${user.user_id}`;
    DOM.mCoins.value = user.coins;
    DOM.mRp.value = user.rating;
    DOM.mBoat.value = user.boat_tier;
    DOM.mRod.value = user.rod_tier;
    DOM.userModal.classList.remove('hidden');
}
function closeModal() { DOM.userModal.classList.add('hidden'); }

async function saveUserStats() {
    if(!currentUserEditing) return;
    setLoading(DOM.btnModalSave, true);
    
    const body = {
        coins: DOM.mCoins.value,
        rating: DOM.mRp.value,
        boat_tier: DOM.mBoat.value,
        rod_tier: DOM.mRod.value
    };
    try {
        const res = await apiCall(`/users/${currentUserEditing.user_id}`, 'POST', body);
        if(res.success) {
            showToast('히스토리 저장 완료 (스탯 적용됨)', 'success');
            
            // 낙관적 UI 업데이트 (리로드 없이 DOM 직접 변경)
            currentUserEditing.coins = parseInt(body.coins);
            currentUserEditing.rating = parseInt(body.rating);
            currentUserEditing.boat_tier = parseInt(body.boat_tier);
            currentUserEditing.rod_tier = parseInt(body.rod_tier);
            
            const trs = DOM.usersTbody.querySelectorAll('tr');
            for(let tr of trs) {
                if(tr.innerHTML.includes(currentUserEditing.user_id)) {
                    tr.cells[2].innerHTML = `<span style="color:var(--warn)">${currentUserEditing.rating}</span> RP`;
                    tr.cells[3].innerHTML = `<span style="color:var(--accent)">${currentUserEditing.coins.toLocaleString()}</span> C`;
                    tr.cells[4].innerHTML = `Lv.${currentUserEditing.rod_tier} 🎣 / T.${currentUserEditing.boat_tier} ⛵`;
                    break;
                }
            }
            closeModal();
        } else {
            showToast(res.error, "error");
        }
    } catch(e) { showToast(e.message, "error"); }
    finally {
        setLoading(DOM.btnModalSave, false, '변경사항 저장');
    }
}

async function modifyItem(action) {
    if(!currentUserEditing) return;
    const item = DOM.mItemName.value;
    const amt = DOM.mItemAmt.value;
    if(!item || amt < 1) return showToast("오류: 올바른 아이템명과 수량을 입력하세요.", "error");
    
    try {
        const res = await apiCall(`/users/${currentUserEditing.user_id}/items`, 'POST', {
            item_name: item,
            amount: amt,
            action: action
        });
        if(res.success) showToast(`시스템: 해상 물품 [${action === 'give' ? '지급' : '회수'}] 완료`, 'success');
        else showToast(res.error, 'error');
    } catch(e) { showToast(e.message, 'error'); }
}

// Market Logic
async function loadMarket() {
    try {
        const res = await apiCall('/market');
        if(res.success) {
            globalMarketData = res.data;
            renderMarketTable(globalMarketData);
            
            // 데이터리스트 전역 갱신 (자동완성 용도)
            DOM.fishListDatlist.innerHTML = '';
            res.data.forEach(f => {
                const opt = document.createElement('option');
                opt.value = f.fish_name;
                DOM.fishListDatlist.appendChild(opt);
            });
        } else {
            showToast("시장 정보 에러: " + res.error, "error");
        }
    } catch(e) {}
}

function renderMarketTable(data) {
    DOM.marketTbody.innerHTML = '';
    data.forEach(f => {
        const tr = document.createElement('tr');
        tr.innerHTML = `
            <td><b>${f.fish_name}</b></td>
            <td><span style="color:var(--text-muted)">${f.grade}</span></td>
            <td>${f.element}</td>
            <td>${f.base_price.toLocaleString()} C</td>
            <td><b style="color:var(--accent)">${f.market_price.toLocaleString()} C</b></td>
            <td><button class="action-btn" onclick="openMarketEdit('${f.fish_name}', ${f.market_price})">개입</button></td>
        `;
        DOM.marketTbody.appendChild(tr);
    });
}

function openMarketEdit(fishName, currentPrice) {
    DOM.marketFish.value = fishName;
    DOM.marketPrice.value = currentPrice;
    window.scrollTo({top: 0, behavior: 'smooth'});
    DOM.marketPrice.focus();
}

DOM.marketSearch.addEventListener('input', (e) => {
    const term = e.target.value.toLowerCase();
    const filtered = globalMarketData.filter(f => f.fish_name.toLowerCase().includes(term) || f.grade.includes(term));
    renderMarketTable(filtered);
});

async function updateMarket() {
    const fish = DOM.marketFish.value;
    const price = DOM.marketPrice.value;
    if(!fish || !price) return showToast('오류: 어종명과 가격을 입력하세요.', 'error');
    
    try {
        const res = await apiCall('/market', 'POST', {fish_name: fish, price: price});
        if(res.success) {
            showToast(`[시장 통제 알림] ${fish} 가격이 ${price}C 로 변동되었습니다.`, 'success');
            loadMarket(); // 표 갱신
        }
        else showToast('데이터를 찾을 수 없습니다.', 'error');
    } catch(e) { showToast(e.message, 'error'); }
}

async function sendBroadcast() {
    const title = DOM.notiTitle.value;
    const content = DOM.notiContent.value;
    if(!title || !content) return showToast('오류: 제목과 내용을 작성하세요.', 'error');
    
    try {
        const res = await apiCall('/admin/broadcast', 'POST', {title, content});
        if(res.success) {
            showToast(`통신 완료: 총 ${res.channels_notified}개의 서버에 무전을 송출했습니다.`, 'success');
            DOM.notiTitle.value = ''; DOM.notiContent.value = '';
        } else showToast(res.error, 'error');
    } catch(e) { showToast(e.message, 'error'); }
}

async function forceWeather() {
    const weather = DOM.weatherSelect.value;
    try {
        const res = await apiCall('/admin/weather', 'POST', {weather: weather});
        if(res.success) showToast(`강제 기상 제어 완료: [${weather}]`, 'success');
        else showToast(res.error, 'error');
    } catch(e) { showToast(e.message, 'error'); }
}

// Events
DOM.loginBtn.onclick = login;
DOM.pwInput.onkeypress = (e) => { if (e.key === 'Enter') login(); }
DOM.logoutBtn.onclick = logout;
DOM.navLinks.forEach(l => l.onclick = () => switchPanel(l.dataset.target));
DOM.btnModalClose.onclick = closeModal;
DOM.btnModalSave.onclick = saveUserStats;
DOM.btnModGive.onclick = () => modifyItem('give');
DOM.btnModTake.onclick = () => modifyItem('take');
DOM.btnMarketUpdate.onclick = updateMarket;
DOM.btnSendNoti.onclick = sendBroadcast;
DOM.btnChangeWeather.onclick = forceWeather;

function loadDashboard() {
    switchPanel('panel-home');
}

initAuth();
