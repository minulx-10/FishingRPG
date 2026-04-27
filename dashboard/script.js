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
    mCoins: document.getElementById('edit-coins'),
    mRp: document.getElementById('edit-rating'),
    mBoat: document.getElementById('edit-boat'),
    mRod: document.getElementById('edit-rod'),
    mItemName: document.getElementById('edit-item-name'),
    mItemAmt: document.getElementById('edit-item-amount'),
    btnModalSave: document.getElementById('btn-save-user'),
    btnModalClose: document.getElementById('btn-close-modal'),
    btnModGive: document.getElementById('btn-give-item'),
    btnModTake: document.getElementById('btn-take-item'),

    // Market
    marketFish: document.getElementById('market-fish-str'),
    marketPrice: document.getElementById('market-price-input'),
    btnMarketUpdate: document.getElementById('btn-market-update'),
    marketTbody: document.getElementById('market-tbody'),
    marketSearch: document.getElementById('market-search'),

    // Server
    notiTitle: document.getElementById('noti-title'),
    notiContent: document.getElementById('noti-content'),
    notiColor: document.getElementById('noti-color'),
    notiThumb: document.getElementById('noti-thumb'),
    notiImage: document.getElementById('noti-image'),
    notiFooter: document.getElementById('noti-footer'),
    btnSendNoti: document.getElementById('btn-send-noti'),
    weatherSelect: document.getElementById('weather-select'),
    btnChangeWeather: document.getElementById('btn-change-weather'),

    // Global
    toastContainer: document.getElementById('toast-container'),
    fishListDatlist: document.getElementById('fish-list'),
    
    // New Elements
    checkAll: document.getElementById('check-all-users'),
    bulkBar: document.getElementById('bulk-action-bar'),
    bulkCount: document.getElementById('bulk-count'),
    btnBulkItem: document.getElementById('btn-bulk-item'),
    btnBulkDelete: document.getElementById('btn-bulk-delete'),
    
    confirmModal: document.getElementById('confirm-modal'),
    confirmTitle: document.getElementById('confirm-title'),
    confirmMsg: document.getElementById('confirm-msg'),
    btnConfirmOk: document.getElementById('btn-confirm-ok'),
    btnConfirmCancel: document.getElementById('btn-confirm-cancel'),
    
    previewTitle: document.getElementById('preview-title'),
    previewContent: document.getElementById('preview-content'),
    previewThumb: document.getElementById('preview-thumb'),
    previewImage: document.getElementById('preview-image'),
    previewFooter: document.getElementById('preview-footer'),
    embedPreview: document.getElementById('embed-preview')
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

/**
 * Safety Net: 확인 모달 도우미
 */
function confirmAction(title, message) {
    return new Promise((resolve) => {
        DOM.confirmTitle.innerText = title;
        DOM.confirmMsg.innerText = message;
        DOM.confirmModal.classList.remove('hidden');
        
        const okHandler = () => {
            DOM.confirmModal.classList.add('hidden');
            DOM.btnConfirmOk.removeEventListener('click', okHandler);
            DOM.btnConfirmCancel.removeEventListener('click', cancelHandler);
            resolve(true);
        };
        const cancelHandler = () => {
            DOM.confirmModal.classList.add('hidden');
            DOM.confirmModal.classList.add('hidden');
            DOM.btnConfirmOk.removeEventListener('click', okHandler);
            DOM.btnConfirmCancel.removeEventListener('click', cancelHandler);
            resolve(false);
        };
        
        DOM.btnConfirmOk.addEventListener('click', okHandler);
        DOM.btnConfirmCancel.addEventListener('click', cancelHandler);
    });
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
    
    if(targetId === 'panel-home') {
        loadStats();
        initCharts();
    }
    if(targetId === 'panel-users') loadUsers();
    if(targetId === 'panel-market') loadMarket();
}

let marketChart = null;
let economyChart = null;

async function initCharts() {
    if (marketChart) marketChart.destroy();
    if (economyChart) economyChart.destroy();

    const ctxMarket = document.getElementById('marketChart').getContext('2d');
    const ctxEconomy = document.getElementById('economyChart').getContext('2d');

    // 통계 데이터 가져오기
    const statsRes = await apiCall('/stats/history');
    const chartData = statsRes.success ? statsRes.data : { labels: [], prices: [], coins: [] };

    marketChart = new Chart(ctxMarket, {
        type: 'line',
        data: {
            labels: chartData.labels,
            datasets: [{
                label: '주요 어종 평균 시세',
                data: chartData.prices,
                borderColor: '#06b6d4',
                backgroundColor: 'rgba(6, 182, 212, 0.1)',
                fill: true,
                tension: 0.4,
                pointRadius: 4,
                pointBackgroundColor: '#06b6d4'
            }]
        },
        options: { 
            responsive: true, 
            plugins: { legend: { labels: { color: '#f8fafc', font: { family: 'Inter' } } } }, 
            scales: { 
                y: { grid: { color: 'rgba(255,255,255,0.05)' }, ticks: { color: '#94a3b8' } }, 
                x: { grid: { display: false }, ticks: { color: '#94a3b8' } } 
            } 
        }
    });

    economyChart = new Chart(ctxEconomy, {
        type: 'doughnut',
        data: {
            labels: ['유통 중인 코인', '시스템 보유량'],
            datasets: [{
                data: [chartData.total_coins || 1, (chartData.total_coins || 1) * 0.25],
                backgroundColor: ['#06b6d4', '#1e293b'],
                borderWidth: 0,
                hoverOffset: 10
            }]
        },
        options: { 
            responsive: true, 
            cutout: '70%',
            plugins: { 
                legend: { position: 'bottom', labels: { color: '#f8fafc', padding: 20 } } 
            } 
        }
    });
}

async function loadStats() {
    try {
        const res = await apiCall('/stats');
        if(res.success) {
            DOM.sUsers.innerText = res.data.total_users + " 명";
            DOM.sCoins.innerText = res.data.total_coins.toLocaleString() + " C";
            DOM.sPing.innerText = res.data.bot_latency + " ms";
            DOM.sWeather.innerText = res.data.current_weather;
        }
    } catch(e) {}
}

async function loadUsers() {
    try {
        const res = await apiCall('/users');
        if(res.success) {
            DOM.usersTbody.innerHTML = '';
            res.data.forEach(u => {
                const tr = document.createElement('tr');
                const avatar = u.avatar ? `<img src="${u.avatar}" class="user-avatar">` : `<div class="user-avatar" style="display:inline-block; background:#334155"></div>`;
                tr.innerHTML = `
                    <td><input type="checkbox" class="user-check" data-id="${u.user_id}"></td>
                    <td><code>${u.user_id}</code></td>
                    <td>${avatar} <b>${u.name}</b></td>
                    <td><span style="color:#f59e0b">${u.rating}</span> RP</td>
                    <td><span style="color:#06b6d4">${u.coins.toLocaleString()}</span> C</td>
                    <td>Lv.${u.rod_tier} 🎣 / T.${u.boat_tier} ⛵</td>
                    <td><button class="action-btn" onclick='openModal(${JSON.stringify(u)})'>강제 개입</button></td>
                `;
                DOM.usersTbody.appendChild(tr);
            });
            updateBulkCount();
        }
    } catch(e) {}
}

function updateBulkCount() {
    const checked = document.querySelectorAll('.user-check:checked');
    if (checked.length > 0) {
        DOM.bulkBar.classList.remove('hidden');
        DOM.bulkCount.innerText = `${checked.length}명 선택됨`;
    } else {
        DOM.bulkBar.classList.add('hidden');
    }
}

DOM.usersTbody.addEventListener('change', (e) => {
    if (e.target.classList.contains('user-check')) updateBulkCount();
});

DOM.checkAll.onclick = () => {
    const checks = document.querySelectorAll('.user-check');
    checks.forEach(c => c.checked = DOM.checkAll.checked);
    updateBulkCount();
};

DOM.btnBulkDelete.onclick = () => {
    document.querySelectorAll('.user-check').forEach(c => c.checked = false);
    DOM.checkAll.checked = false;
    updateBulkCount();
};

DOM.btnBulkItem.onclick = async () => {
    const checked = document.querySelectorAll('.user-check:checked');
    const ids = Array.from(checked).map(c => c.dataset.id);
    
    const itemName = prompt('지급할 아이템 이름을 입력하세요:');
    if (!itemName) return;
    const itemAmt = prompt('수량을 입력하세요:', '1');
    if (!itemAmt) return;

    if (await confirmAction('🎁 일괄 지급 확인', `선택한 ${ids.length}명에게 [${itemName}] ${itemAmt}개를 지급하시겠습니까?`)) {
        try {
            const res = await apiCall('/users/bulk/items', 'POST', {
                user_ids: ids,
                item_name: itemName,
                amount: itemAmt
            });
            if (res.success) showToast(`성공: ${res.success_count}명에게 아이템을 지급했습니다.`);
            else showToast(res.error, 'error');
        } catch(e) { showToast(e.message, 'error'); }
    }
};

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
            showToast('유저 정보가 업데이트되었습니다.', 'success');
            loadUsers();
            closeModal();
        } else showToast(res.error, "error");
    } catch(e) { showToast(e.message, "error"); }
    finally { setLoading(DOM.btnModalSave, false); }
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
        if(res.success) showToast(`아이템 [${action === 'give' ? '지급' : '회수'}] 완료`, 'success');
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
        }

        // 전체 아이템 리스트 (자동완성용) 가져오기
        const itemsRes = await apiCall('/items/all');
        if(itemsRes.success) {
            DOM.fishListDatlist.innerHTML = '';
            itemsRes.data.forEach(name => {
                const opt = document.createElement('option');
                opt.value = name;
                DOM.fishListDatlist.appendChild(opt);
            });
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
            <td><b style="color:#06b6d4">${f.market_price.toLocaleString()} C</b></td>
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

DOM.marketSearch.oninput = (e) => {
    const term = e.target.value.toLowerCase();
    const filtered = globalMarketData.filter(f => f.fish_name.toLowerCase().includes(term) || f.grade.includes(term));
    renderMarketTable(filtered);
};

async function updateMarket() {
    const fish = DOM.marketFish.value;
    const price = DOM.marketPrice.value;
    if(!fish || !price) return showToast('오류: 어종명과 가격을 입력하세요.', 'error');
    
    if (await confirmAction('⚖️ 시장 가격 개입', `[${fish}]의 가격을 ${price}C로 강제 변경하시겠습니까?`)) {
        try {
            const res = await apiCall('/market', 'POST', {fish_name: fish, price: price});
            if(res.success) {
                showToast(`${fish} 가격 변동 완료`, 'success');
                loadMarket();
            }
        } catch(e) {}
    }
}

async function sendBroadcast() {
    const title = DOM.notiTitle.value;
    const content = DOM.notiContent.value;
    if(!title || !content) return showToast('오류: 제목과 내용을 작성하세요.', 'error');
    
    const body = {
        title,
        content,
        color: DOM.notiColor.value,
        thumbnail: DOM.notiThumb.value,
        image: DOM.notiImage.value,
        footer: DOM.notiFooter.value
    };

    if (await confirmAction('📢 전역 공지 전송', '모든 서버에 이 무전을 송출하시겠습니까?')) {
        try {
            const res = await apiCall('/admin/broadcast', 'POST', body);
            if(res.success) {
                showToast(`송신 완료: ${res.channels_notified}개 서버`, 'success');
            } else showToast(res.error, 'error');
        } catch(e) {}
    }
}

function updatePreview() {
    DOM.previewTitle.innerText = DOM.notiTitle.value || '공지 제목';
    DOM.previewContent.innerText = DOM.notiContent.value || '내용 미리보기...';
    DOM.embedPreview.style.borderLeftColor = DOM.notiColor.value;
    
    if (DOM.notiThumb.value) {
        DOM.previewThumb.src = DOM.notiThumb.value;
        DOM.previewThumb.style.display = 'block';
    } else DOM.previewThumb.style.display = 'none';
    
    if (DOM.notiImage.value) {
        DOM.previewImage.src = DOM.notiImage.value;
        DOM.previewImage.style.display = 'block';
    } else DOM.previewImage.style.display = 'none';
    
    DOM.previewFooter.innerText = DOM.notiFooter.value || '';
    DOM.previewFooter.style.display = DOM.notiFooter.value ? 'block' : 'none';
}

DOM.notiTitle.oninput = updatePreview;
DOM.notiContent.oninput = updatePreview;
DOM.notiColor.oninput = updatePreview;
DOM.notiThumb.oninput = updatePreview;
DOM.notiImage.oninput = updatePreview;
DOM.notiFooter.oninput = updatePreview;

async function forceWeather() {
    const weather = DOM.weatherSelect.value;
    if (await confirmAction('🌡️ 기상 제어', `기상을 [${weather}]로 변경하시겠습니까?`)) {
        try {
            const res = await apiCall('/admin/weather', 'POST', {weather: weather});
            if(res.success) {
                showToast(`기상 변경 완료: ${weather}`, 'success');
                loadStats();
            }
        } catch(e) {}
    }
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
