const state = {
    token: localStorage.getItem('avtomail_token') || null,
    email: localStorage.getItem('avtomail_email') || '',
    conversations: [],
    scenarios: [],
    currentConversation: null,
    currentConversationId: null,
    selectedMessageId: null,
    filters: {
        search: '',
        status: '',
    },
    loading: {
        conversations: false,
        detail: false,
    },
    composeAttachments: [],
};

const elements = {
    app: document.getElementById('app'),
    loginDialog: document.getElementById('login-dialog'),
    loginForm: document.getElementById('login-form'),
    loginEmail: document.getElementById('login-email'),
    loginPassword: document.getElementById('login-password'),
    agentEmail: document.getElementById('agent-email'),
    logout: document.getElementById('logout-btn'),
    conversationPane: document.getElementById('conversation-pane'),
    conversationList: document.getElementById('conversation-list'),
    conversationLoading: document.getElementById('conversation-loading'),
    conversationEmpty: document.getElementById('conversation-empty'),
    conversationSearch: document.getElementById('conversation-search'),
    statusFilter: document.getElementById('status-filter'),
    detailView: document.getElementById('detail-view'),
    detailLoading: document.getElementById('detail-loading'),
    emptyState: document.getElementById('empty-state'),
    detailTopic: document.getElementById('detail-topic'),
    detailClient: document.getElementById('detail-client'),
    detailMeta: document.getElementById('detail-meta'),
    detailStatus: document.getElementById('detail-status'),
    closeConversation: document.getElementById('close-conversation'),
    scenarioPanel: document.getElementById('scenario-panel'),
    scenarioInfo: document.getElementById('scenario-info'),
    scenarioSteps: document.getElementById('scenario-steps'),
    scenarioPrev: document.getElementById('scenario-prev'),
    scenarioNext: document.getElementById('scenario-next'),
    scenarioComplete: document.getElementById('scenario-complete'),
    scenarioNotesInput: document.getElementById('scenario-notes-input'),
    scenarioSaveNotes: document.getElementById('scenario-save-notes'),
    scenarioSelect: document.getElementById('scenario-select'),
    assignScenario: document.getElementById('assign-scenario'),
    messageList: document.getElementById('message-list'),
    messageViewer: document.getElementById('message-viewer'),
    messageViewerBody: document.getElementById('message-viewer-body'),
    messageViewerEmpty: document.getElementById('message-viewer-empty'),
    messageContent: document.getElementById('message-content'),
    messageSubject: document.getElementById('message-subject'),
    messageSummary: document.getElementById('message-summary'),
    messageFrom: document.getElementById('message-from'),
    messageDate: document.getElementById('message-date'),
    messageTags: document.getElementById('message-tags'),
    replyButton: document.getElementById('reply-btn'),
    replyAllButton: document.getElementById('reply-all-btn'),
    forwardButton: document.getElementById('forward-btn'),
    composePanel: document.getElementById('compose-panel'),
    composeText: document.getElementById('compose-text'),
    aiDraft: document.getElementById('ai-draft'),
    sendApproveAI: document.getElementById('send-approve-ai'),
    sendManual: document.getElementById('send-manual'),
    logList: document.getElementById('log-list'),
    logSummary: document.getElementById('log-summary'),
    logContext: document.getElementById('log-context'),
    logAdd: document.getElementById('log-add'),
    reloadConversations: document.getElementById('reload-conversations'),
    refreshLogs: document.getElementById('refresh-logs'),
    toast: document.getElementById('toast'),
};

const API_BASE = '/api';
const STATUS_LABELS = {
    awaiting_response: 'Ожидает ответ',
    answered_by_llm: 'Ответил LLM',
    needs_human: 'Нужен оператор',
    closed: 'Закрыт',
};

const relativeTimeFormatter = new Intl.RelativeTimeFormat('ru', { numeric: 'auto' });
const dayLabelFormatter = new Intl.DateTimeFormat('ru-RU', {
    weekday: 'long',
    day: 'numeric',
    month: 'long',
});
const dateTimeFormatter = new Intl.DateTimeFormat('ru-RU', {
    day: '2-digit',
    month: 'short',
    hour: '2-digit',
    minute: '2-digit',
});

let toastTimer = null;
let searchTimer = null;
let detailAbortController = null;
let conversationsRefreshTimer = null;

function escapeHtml(value) {
    if (!value) {
        return '';
    }
    return value
        .replace(/&/g, '&amp;')
        .replace(/</g, '&lt;')
        .replace(/>/g, '&gt;')
        .replace(/"/g, '&quot;')
        .replace(/'/g, '&#039;');
}

function normalizeText(value) {
    return (value || '').toString().trim().toLowerCase();
}

function scenarioStateToSummary(state) {
    if (!state || !state.scenario) {
        return null;
    }
    const activeStep = state.active_step;
    return {
        scenario: {
            id: state.scenario.id,
            name: state.scenario.name,
            subject: state.scenario.subject || null,
        },
        active_step_id: activeStep ? activeStep.id : null,
        active_step_title: activeStep ? activeStep.title || `Шаг ${activeStep.order_index}` : null,
    };
}

function updateConversationSummary(conversationId, updates) {
    let changed = false;
    state.conversations = state.conversations.map((conversation) => {
        if (conversation.id !== conversationId) {
            return conversation;
        }
        const patch = typeof updates === 'function' ? updates(conversation) : updates;
        if (!patch) {
            return conversation;
        }
        changed = true;
        return { ...conversation, ...patch };
    });
    if (changed) {
        renderConversations();
    }
}

function setCurrentConversation(conversation, options = {}) {
    const { preserveSelection = false } = options;
    state.currentConversation = conversation;
    state.currentConversationId = conversation ? conversation.id : null;
    if (!preserveSelection) {
        state.selectedMessageId = null;
    }
    if (conversation) {
        updateConversationSummary(conversation.id, () => {
            const latestMessage = (conversation.messages || []).slice(-1)[0];
            const latestTimestamp = latestMessage ? latestMessage.sent_at || latestMessage.received_at : null;
            const updates = {
                status: conversation.status,
                unread_count: 0,
                scenario: scenarioStateToSummary(conversation.scenario_state),
            };
            if (latestTimestamp) {
                updates.last_message_at = latestTimestamp;
            }
            return updates;
        });
    }
}

function stopConversationRefresh() {
    if (conversationsRefreshTimer) {
        clearInterval(conversationsRefreshTimer);
        conversationsRefreshTimer = null;
    }
}

function scheduleConversationRefresh() {
    stopConversationRefresh();
    if (!state.token) {
        return;
    }
    conversationsRefreshTimer = setInterval(() => {
        if (!state.token) {
            return;
        }
        loadConversations().catch((error) => {
            console.warn('Автообновление списка диалогов завершилось с ошибкой', error);
        });
    }, 60000);
}

function formatFileSize(bytes) {
    if (!Number.isFinite(bytes) || bytes < 0) {
        return '';
    }
    const units = ['Б', 'КБ', 'МБ', 'ГБ'];
    let size = bytes;
    let unitIndex = 0;
    while (size >= 1024 && unitIndex < units.length - 1) {
        size /= 1024;
        unitIndex += 1;
    }
    return `${size >= 10 || unitIndex === 0 ? Math.round(size) : size.toFixed(1)} ${units[unitIndex]}`;
}

function formatTimestamp(value) {
    if (!value) {
        return '';
    }
    try {
        return dateTimeFormatter.format(new Date(value));
    } catch (error) {
        console.warn('Failed to format timestamp', value, error);
        return '';
    }
}

function formatRelativeTime(value) {
    if (!value) {
        return '';
    }
    const now = Date.now();
    const target = new Date(value).getTime();
    if (Number.isNaN(target)) {
        return '';
    }
    const diffSeconds = Math.round((target - now) / 1000);
    const thresholds = [
        { limit: 60, divisor: 1, unit: 'second' },
        { limit: 3600, divisor: 60, unit: 'minute' },
        { limit: 86400, divisor: 3600, unit: 'hour' },
        { limit: 604800, divisor: 86400, unit: 'day' },
        { limit: 2629800, divisor: 604800, unit: 'week' },
        { limit: 31557600, divisor: 2629800, unit: 'month' },
        { limit: Infinity, divisor: 31557600, unit: 'year' },
    ];
    const absSeconds = Math.abs(diffSeconds);
    for (const threshold of thresholds) {
        if (absSeconds < threshold.limit) {
            const delta = Math.round(diffSeconds / threshold.divisor);
            return relativeTimeFormatter.format(delta, threshold.unit);
        }
    }
    return formatTimestamp(value);
}

function formatDayLabel(value) {
    if (!value) {
        return '';
    }
    try {
        const label = dayLabelFormatter.format(new Date(value));
        return label.charAt(0).toUpperCase() + label.slice(1);
    } catch (error) {
        console.warn('Failed to format day label', value, error);
        return '';
    }
}

function getMessageTimestamp(message) {
    if (!message) {
        return null;
    }
    return message.sent_at || message.received_at || null;
}

function getMessageSenderLabel(conversation, message) {
    if (!message) {
        return '';
    }
    if (message.sender_type === 'client') {
        const name = conversation?.client?.name || null;
        const email = conversation?.client?.email || null;
        if (name && email) {
            return `${name} <${email}>`;
        }
        return name || email || 'Клиент';
    }
    if (message.sender_type === 'assistant') {
        return 'Автоматический ответ';
    }
    if (message.sender_type === 'manager') {
        return state.email || 'Оператор';
    }
    return message.sender_type || 'Сообщение';
}

function extractPlainText(message) {
    if (message?.body_plain) {
        return message.body_plain;
    }
    if (message?.body_html) {
        const temp = document.createElement('div');
        temp.innerHTML = message.body_html;
        return temp.textContent || temp.innerText || '';
    }
    return '';
}

function formatMessagePreview(message) {
    const text = extractPlainText(message).replace(/\s+/g, ' ').trim();
    if (!text) {
        return '';
    }
    return text.length > 160 ? `${text.slice(0, 160)}…` : text;
}

function highlightSelectedMessage() {
    if (!elements.messageList) {
        return;
    }
    const items = elements.messageList.querySelectorAll('.message-item');
    items.forEach((item) => {
        const id = Number.parseInt(item.dataset.id, 10);
        item.classList.toggle('active', id === state.selectedMessageId);
    });
}

function showToast(message, type = 'info') {
    if (!elements.toast) {
        return;
    }
    elements.toast.textContent = message;
    elements.toast.classList.remove('hidden', 'error');
    if (type === 'error') {
        elements.toast.classList.add('error');
    } else {
        elements.toast.classList.remove('error');
    }
    if (toastTimer) {
        clearTimeout(toastTimer);
    }
    toastTimer = setTimeout(() => {
        elements.toast.classList.add('hidden');
    }, 3500);
}

function setAuth(token, email) {
    state.token = token;
    state.email = email;
    localStorage.setItem('avtomail_token', token);
    localStorage.setItem('avtomail_email', email);
    updateAuthUI();
}

function clearAuth() {
    state.token = null;
    state.email = '';
    localStorage.removeItem('avtomail_token');
    localStorage.removeItem('avtomail_email');
    stopConversationRefresh();
    if (detailAbortController) {
        detailAbortController.abort();
        detailAbortController = null;
    }
    state.conversations = [];
    state.currentConversation = null;
    state.currentConversationId = null;
    state.selectedMessageId = null;
    state.composeAttachments = [];
    renderComposeAttachments();
    updateAuthUI();
    renderConversations();
    if (elements.detailView && elements.emptyState) {
        elements.detailView.classList.add('hidden');
        elements.emptyState.classList.remove('hidden');
    }
}

function updateAuthUI() {
    if (!elements.loginDialog || !elements.app) {
        return;
    }
    if (state.token) {
        elements.loginDialog.style.display = 'none';
        elements.app.classList.remove('hidden');
        elements.agentEmail.textContent = state.email;
    } else {
        elements.loginDialog.style.display = 'flex';
        elements.app.classList.add('hidden');
        elements.agentEmail.textContent = '';
    }
}

async function apiFetch(path, options = {}) {
    const headers = options.headers ? new Headers(options.headers) : new Headers();
    if (state.token) {
        headers.set('Authorization', `Bearer ${state.token}`);
    }
    if (options.body && !(options.body instanceof FormData)) {
        headers.set('Content-Type', 'application/json');
    }
    const response = await fetch(`${API_BASE}${path}`, {
        ...options,
        headers,
    });
    if (response.status === 204) {
        return null;
    }
    if (!response.ok) {
        if (response.status === 401) {
            clearAuth();
        }
        const text = await response.text();
        throw new Error(text || response.statusText || 'Не удалось выполнить запрос');
    }
    const contentType = response.headers.get('Content-Type') || '';
    if (contentType.includes('application/json')) {
        return response.json();
    }
    return response.text();
}

function setLoading(section, isLoading) {
    state.loading[section] = isLoading;
    if (section === 'conversations') {
        elements.conversationLoading.classList.toggle('hidden', !isLoading);
        elements.conversationPane.classList.toggle('is-loading', isLoading);
    }
    if (section === 'detail' && elements.detailLoading) {
        elements.detailLoading.classList.toggle('hidden', !isLoading);
    }
}

function applyConversationFilters() {
    const search = normalizeText(state.filters.search);
    const status = state.filters.status;
    return state.conversations
        .filter((conversation) => {
            if (status && conversation.status !== status) {
                return false;
            }
            if (!search) {
                return true;
            }
            const haystack = [
                conversation.topic,
                conversation.client?.name,
                conversation.client?.email,
                conversation.scenario?.scenario?.name,
            ]
                .filter(Boolean)
                .map(normalizeText)
                .join(' ');
            return haystack.includes(search);
        })
        .sort((a, b) => {
            const left = new Date(a.last_message_at || 0).getTime();
            const right = new Date(b.last_message_at || 0).getTime();
            return right - left;
        });
}

function renderConversations() {
    if (!elements.conversationList) {
        return;
    }
    const filtered = applyConversationFilters();
    const markup = filtered
        .map((conversation) => {
            const classes = ['conversation-item'];
            if (state.currentConversationId === conversation.id) {
                classes.push('active');
            }
            const unreadBadge = conversation.unread_count
                ? `<span class="badge badge-warn">${conversation.unread_count}</span>`
                : '';
            const scenarioBadge = conversation.scenario
                ? `<span class="badge badge-status">${escapeHtml(conversation.scenario.scenario.name)}</span>`
                : '';
            const relative = formatRelativeTime(conversation.last_message_at) || '—';
            const client = escapeHtml(conversation.client?.name || conversation.client?.email || 'Без имени');
            const topic = escapeHtml(conversation.topic || 'Без темы');
            const statusLabel = STATUS_LABELS[conversation.status] || conversation.status;
            return `
                <div class="${classes.join(' ')}" data-id="${conversation.id}">
                    <div class="conversation-row">
                        <div class="conversation-topic">${topic}</div>
                        <div class="conversation-meta">
                            ${unreadBadge}
                            ${scenarioBadge}
                            <span class="status">${statusLabel}</span>
                        </div>
                    </div>
                    <div class="conversation-row secondary">
                        <span class="conversation-client">${client}</span>
                        <span class="conversation-time">${relative}</span>
                    </div>
                </div>
            `;
        })
        .join('');
    elements.conversationList.innerHTML = markup;

    const showEmpty = !filtered.length && !state.loading.conversations;
    elements.conversationEmpty.classList.toggle('hidden', !showEmpty);
}

function renderScenarioState(scenarioState) {
    if (!elements.scenarioInfo) {
        return;
    }
    if (!scenarioState) {
        elements.scenarioInfo.innerHTML = '<div class="hint">Сценарий не назначен. Выберите сценарий из списка и нажмите «Привязать».</div>';
        elements.scenarioSteps.innerHTML = '';
        elements.scenarioNotesInput.value = '';
        elements.scenarioPrev.disabled = true;
        elements.scenarioNext.disabled = true;
        elements.scenarioSaveNotes.disabled = true;
        elements.scenarioComplete.disabled = true;
        return;
    }

    const { scenario, active_step: activeStep, next_step: nextStep, notes } = scenarioState;
    const nextHint = nextStep ? `Следующий шаг: ${escapeHtml(nextStep.title || `Шаг ${nextStep.order_index}`)}` : 'Сценарий на последнем шаге';
    elements.scenarioInfo.innerHTML = `
        <div class="scenario-title"><strong>${escapeHtml(scenario.name)}</strong></div>
        ${scenario.subject ? `<div class="scenario-subject">${escapeHtml(scenario.subject)}</div>` : ''}
        <div class="hint">${nextHint}</div>
    `;
    elements.scenarioNotesInput.value = notes || '';

    const steps = (scenario.steps || [])
        .slice()
        .sort((a, b) => a.order_index - b.order_index)
        .map((step, index) => {
            const isActive = activeStep && step.id === activeStep.id;
            const indexLabel = index + 1;
            return `
                <div class="scenario-step ${isActive ? 'active' : ''}" data-step-id="${step.id}">
                    <div class="title">${escapeHtml(step.title || `Шаг ${indexLabel}`)}</div>
                    ${step.description ? `<div class="description">${escapeHtml(step.description)}</div>` : ''}
                    ${step.ai_instructions ? `<div class="instructions">Инструкция для ИИ: ${escapeHtml(step.ai_instructions)}</div>` : ''}
                    ${step.operator_hint ? `<div class="hint">Подсказка оператору: ${escapeHtml(step.operator_hint)}</div>` : ''}
                </div>
            `;
        })
        .join('');
    elements.scenarioSteps.innerHTML = steps;

    elements.scenarioPrev.disabled = !activeStep;
    elements.scenarioNext.disabled = !nextStep;
    elements.scenarioSaveNotes.disabled = false;
    elements.scenarioComplete.disabled = false;
}

function renderMessageBody(message) {
    if (message.body_html) {
        return message.body_html;
    }
    if (message.body_plain) {
        return escapeHtml(message.body_plain).replace(/\r?\n/g, '<br>');
    }
    return '<em>Текст отсутствует</em>';
}
    if (message.body_plain) {
        return escapeHtml(message.body_plain).replace(/
/g, '<br>');
    }
    return '<em>Текст отсутствует</em>';
}

function renderMessages(conversation) {
    if (!elements.messageList || !elements.messageViewer) {
        return;
    }
    const messages = conversation.messages || [];
    if (!messages.length) {
        elements.messageList.innerHTML = "<div class='empty'>Пока нет сообщений</div>";
        state.selectedMessageId = null;
        elements.messageViewerEmpty.classList.remove('hidden');
        elements.messageViewerBody.classList.add('hidden');
        elements.messageSubject.textContent = conversation.topic || 'Без темы';
        elements.messageSummary.textContent = 'Сообщений: 0';
        elements.messageFrom.textContent = '';
        elements.messageDate.textContent = '';
        elements.messageTags.innerHTML = '';
        elements.messageTags.classList.add('hidden');
        elements.messageContent.innerHTML = '';
        elements.aiDraft.textContent = '';
        elements.aiDraft.classList.remove('visible');
        return;
    }

    if (!messages.some((msg) => msg.id === state.selectedMessageId)) {
        state.selectedMessageId = messages[messages.length - 1].id;
    }

    const groups = [];
    messages.forEach((message) => {
        const timestamp = getMessageTimestamp(message);
        const dayKey = timestamp ? new Date(timestamp).toDateString() : 'unknown';
        let group = groups.find((item) => item.key === dayKey);
        if (!group) {
            group = {
                key: dayKey,
                label: timestamp ? formatDayLabel(timestamp) : 'Без даты',
                messages: [],
            };
            groups.push(group);
        }
        group.messages.push(message);
    });

    const listMarkup = groups
        .map((group) => {
            const items = group.messages
                .map((message) => {
                    const sender = getMessageSenderLabel(conversation, message);
                    const preview = formatMessagePreview(message) || 'Без текста';
                    const timestamp = getMessageTimestamp(message);
                    const timeLabel = timestamp ? formatRelativeTime(timestamp) : '';
                    const badges = [];
                    if (message.requires_attention) {
                        badges.push("<span class='message-flag warn'>!</span>");
                    }
                    if (message.is_draft) {
                        badges.push("<span class='message-flag draft'>Черновик</span>");
                    }
                    const directionLabel = message.direction === 'inbound' ? 'Входящее' : 'Исходящее';
                    badges.push(`<span class='message-flag subtle'>${directionLabel}</span>`);
                    const flags = badges.length ? `<div class='message-flags'>${badges.join('')}</div>` : '';
                    return `
                        <div class='message-item' data-id='${message.id}'>
                            <div class='message-item-row'>
                                <span class='message-author'>${escapeHtml(sender)}</span>
                                <span class='message-time'>${timeLabel}</span>
                            </div>
                            <div class='message-item-row subject'>
                                ${escapeHtml(message.subject || conversation.topic || 'Без темы')}
                            </div>
                            <div class='message-item-row preview'>
                                ${escapeHtml(preview)}
                            </div>
                            ${flags}
                        </div>
                    `;
                })
                .join('');
            return `
                <div class='message-group'>
                    <div class='message-group-label'>${group.label}</div>
                    <div class='message-group-items'>
                        ${items}
                    </div>
                </div>
            `;
        })
        .join('');

    elements.messageList.innerHTML = listMarkup;
    highlightSelectedMessage();
    const activeItem = elements.messageList.querySelector('.message-item.active');
    if (activeItem) {
        activeItem.scrollIntoView({ block: 'nearest' });
    }

    renderMessageViewer(conversation);

    const draft = messages.find((msg) => msg.is_draft && msg.body_plain);
    if (draft) {
        elements.aiDraft.textContent = draft.body_plain;
        elements.aiDraft.classList.add('visible');
    } else {
        elements.aiDraft.textContent = '';
        elements.aiDraft.classList.remove('visible');
    }
}

function renderMessageViewer(conversation) {
    if (!elements.messageViewerBody || !elements.messageViewerEmpty) {
        return;
    }
    const messages = conversation.messages || [];
    const message = messages.find((msg) => msg.id === state.selectedMessageId);
    if (!message) {
        elements.messageViewerEmpty.classList.remove('hidden');
        elements.messageViewerBody.classList.add('hidden');
        elements.messageSubject.textContent = conversation.topic || 'Без темы';
        elements.messageSummary.textContent = `Сообщений: ${messages.length}`;
        elements.messageFrom.textContent = '';
        elements.messageDate.textContent = '';
        elements.messageTags.innerHTML = '';
        elements.messageTags.classList.add('hidden');
        elements.messageContent.innerHTML = '';
        return;
    }

    elements.messageViewerEmpty.classList.add('hidden');
    elements.messageViewerBody.classList.remove('hidden');

    const timestamp = getMessageTimestamp(message);
    const senderLabel = getMessageSenderLabel(conversation, message);

    elements.messageSubject.textContent = message.subject || conversation.topic || 'Без темы';

    const summaryParts = [];
    if (timestamp) {
        summaryParts.push(formatRelativeTime(timestamp));
    }
    summaryParts.push(message.direction === 'inbound' ? 'Входящее' : 'Исходящее');
    elements.messageSummary.textContent = summaryParts.join(' · ');

    elements.messageFrom.textContent = senderLabel;
    elements.messageDate.textContent = timestamp ? formatTimestamp(timestamp) : '';
    const tags = [];
    if (message.requires_attention) {
        tags.push('<span class="message-tag warn">Требует внимания</span>');
    }
    if (message.is_draft) {
        tags.push('<span class="message-tag draft">Черновик ИИ</span>');
    }
    if (message.detected_language) {
        tags.push(`<span class="message-tag subtle">Язык: ${escapeHtml(message.detected_language.toUpperCase())}</span>`);
    }
        elements.messageTags.innerHTML = tags.join('');
        elements.messageTags.classList.toggle('hidden', tags.length === 0);
    renderMessageAttachments(message);
    elements.messageContent.innerHTML = renderMessageBody(message);
    elements.messageViewer.scrollTop = 0;
}

function renderMessageAttachments(message) {
    if (!elements.messageAttachments) {
        return;
    }
    const attachments = Array.isArray(message.attachments) ? message.attachments : [];
    if (!attachments.length) {
        elements.messageAttachments.innerHTML = '';
        elements.messageAttachments.classList.add('hidden');
        return;
    }
    const markup = attachments
        .map((attachment) => {
            const size = typeof attachment.file_size === 'number' ? formatFileSize(attachment.file_size) : '';
            const label = size ? ${escapeHtml(attachment.filename)} () : escapeHtml(attachment.filename);
            return <a href="" target="_blank" rel="noopener"></a>;
        })
        .join('');
    elements.messageAttachments.innerHTML = markup;
    elements.messageAttachments.classList.remove('hidden');
}

function renderComposeAttachments() {
    if (!elements.composeAttachmentsList) {
        return;
    }
    const attachments = state.composeAttachments || [];
    if (!attachments.length) {
        elements.composeAttachmentsList.innerHTML = '';
        elements.composeAttachmentsList.classList.add('hidden');
        return;
    }
    const items = attachments
        .map((file, index) => {
            const size = typeof file.size === 'number' ? formatFileSize(file.size) : '';
            const label = size ? ${escapeHtml(file.name)} () : escapeHtml(file.name);
            return <li><span></span><button type="button" class="attachment-remove" data-index="">×</button></li>;
        })
        .join('');
    elements.composeAttachmentsList.innerHTML = items;
    elements.composeAttachmentsList.classList.remove('hidden');
}

function handleAttachmentSelection(event) {
    const files = Array.from(event.target.files || []);
    if (!files.length) {
        return;
    }
    files.forEach((file) => {
        state.composeAttachments.push(file);
    });
    renderComposeAttachments();
    event.target.value = '';
}

function removeComposeAttachment(index) {
    if (index < 0 || index >= state.composeAttachments.length) {
        return;
    }
    state.composeAttachments.splice(index, 1);
    renderComposeAttachments();
}
function renderLogs(logs) {
    if (!elements.logList) {
        return;
    }
    const markup = (logs || [])
        .map((log) => `
            <div class="log-entry">
                <div class="meta">${formatTimestamp(log.created_at)} · ${escapeHtml(log.actor)} · ${escapeHtml(log.event_type)}</div>
                <div class="summary">${escapeHtml(log.summary)}</div>
                ${log.context ? `<div class="context">${escapeHtml(log.context)}</div>` : ''}
            </div>
        `)
        .join('');
    elements.logList.innerHTML = markup || '<div class="empty">Записей пока нет</div>';
}

function renderDetail(conversation, options = {}) {
    if (!elements.detailView) {
        return;
    }
    const { preserveDraft = false, preserveSelection = false } = options;
    setCurrentConversation(conversation, { preserveSelection });
    elements.emptyState.classList.add('hidden');
    elements.detailView.classList.remove('hidden');

    const client = conversation.client?.name || conversation.client?.email || 'Без имени';
    elements.detailTopic.textContent = conversation.topic || 'Без темы';
    elements.detailClient.textContent = client;

    const messages = conversation.messages || [];
    const lastMessage = messages[messages.length - 1];
    const lastTimestamp = getMessageTimestamp(lastMessage) || conversation.last_message_at;
    const metaParts = [];
    if (lastTimestamp) {
        metaParts.push(`Последнее сообщение: ${formatTimestamp(lastTimestamp)}`);
    }
    metaParts.push(`Сообщений: ${messages.length}`);
    elements.detailMeta.textContent = metaParts.join(' · ');

    const statusLabel = STATUS_LABELS[conversation.status] || conversation.status;
    elements.detailStatus.textContent = statusLabel;
    elements.detailStatus.dataset.status = conversation.status;

    renderScenarioState(conversation.scenario_state);
    renderMessages(conversation);
    renderLogs(conversation.logs || []);

    if (!preserveDraft) {
        elements.composeText.value = '';
        state.composeAttachments = [];
        if (elements.composeAttachmentsInput) {
            elements.composeAttachmentsInput.value = '';
        }
        renderComposeAttachments();
    }
}

async function loadConversations() {
    setLoading('conversations', true);
    try {
        const data = await apiFetch('/conversations');
        state.conversations = Array.isArray(data) ? data : [];

        if (state.currentConversationId) {
            const exists = state.conversations.some((conversation) => conversation.id === state.currentConversationId);
            if (!exists) {
                state.currentConversation = null;
                state.currentConversationId = null;
                state.selectedMessageId = null;
                if (elements.detailView && elements.emptyState) {
                    elements.detailView.classList.add('hidden');
                    elements.emptyState.classList.remove('hidden');
                }
            }
        }

        const shouldAutoSelect = !state.currentConversationId && state.conversations.length > 0;

        renderConversations();

        if (shouldAutoSelect) {
            await selectConversation(state.conversations[0].id);
        } else if (state.currentConversationId && state.currentConversation) {
            const summary = state.conversations.find((conversation) => conversation.id === state.currentConversationId);
            if (summary && summary.status && summary.status !== state.currentConversation.status) {
                state.currentConversation.status = summary.status;
                const statusLabel = STATUS_LABELS[summary.status] || summary.status;
                elements.detailStatus.textContent = statusLabel;
                elements.detailStatus.dataset.status = summary.status;
            }
        }
    } catch (error) {
        showToast(error.message || 'Не удалось загрузить диалоги', 'error');
    } finally {
        setLoading('conversations', false);
    }
}

async function loadScenarios() {
    try {
        const data = await apiFetch('/scenarios');
        state.scenarios = Array.isArray(data) ? data : [];
        const options = ['<option value="">— Выберите сценарий —</option>'];
        state.scenarios.forEach((scenario) => {
            options.push(`<option value="${scenario.id}">${escapeHtml(scenario.name)}</option>`);
        });
        elements.scenarioSelect.innerHTML = options.join('');
    } catch (error) {
        showToast(error.message || 'Не удалось загрузить сценарии', 'error');
    }
}

async function selectConversation(id) {
    if (!id) {
        return;
    }
    state.currentConversationId = id;
    state.selectedMessageId = null;
    renderConversations();

    if (detailAbortController) {
        detailAbortController.abort();
    }
    const controller = new AbortController();
    detailAbortController = controller;

    setLoading('detail', true);
    try {
        const detail = await apiFetch(`/conversations/${id}`, { signal: controller.signal });
        if (detailAbortController !== controller) {
            return;
        }
        renderDetail(detail);
    } catch (error) {
        if (error.name === 'AbortError') {
            return;
        }
        showToast(error.message || 'Не удалось загрузить диалог', 'error');
    } finally {
        if (detailAbortController === controller) {
            setLoading('detail', false);
            detailAbortController = null;
        }
    }
}

function quoteText(value) {
    return (value || '')
        .replace(/\r?\n/g, '\n')
        .split('\n')
        .map((line) => `> ${line}`)
        .join('\n');
}

function buildReplyTemplate(conversation, message, mode) {
    const sender = getMessageSenderLabel(conversation, message);
    const timestamp = formatTimestamp(getMessageTimestamp(message));
    const quoted = quoteText(extractPlainText(message));
    if (mode === 'forward') {
        return `Пересылаю сообщение:\n\nОт: ${sender}\nДата: ${timestamp}\n\n${quoted}\n`;
    }
    const greeting = 'Здравствуйте,\n\n';
    return `${greeting}${sender} писал(а) ${timestamp}:\n${quoted}\n`;
}

function handleReplyAction(mode) {
    if (!state.currentConversation) {
        return;
    }
    const messages = state.currentConversation.messages || [];
    if (!messages.length) {
        showToast('Нет сообщений для ответа', 'error');
        return;
    }
    const message = messages.find((item) => item.id === state.selectedMessageId) || messages[messages.length - 1];
    state.selectedMessageId = message.id;
    highlightSelectedMessage();
    renderMessageViewer(state.currentConversation);
    const template = buildReplyTemplate(state.currentConversation, message, mode);
    elements.composeText.value = template;
    elements.composeText.focus();
    let cursorPosition = template.indexOf('\r\n\r\n');
    if (cursorPosition >= 0) {
        cursorPosition += 4;
    } else {
        const fallback = template.indexOf('\n\n');
        cursorPosition = fallback >= 0 ? fallback + 2 : template.length;
    }
    elements.composeText.setSelectionRange(cursorPosition, cursorPosition);
    if (mode === 'reply-all') {
        showToast('Добавьте адресатов вручную, если нужно ответить всем.');
    }
}



async function handleSend(sendMode) {
    if (!state.currentConversation) {
        return;
    }
    const textValue = elements.composeText.value.trim();
    if (!textValue) {
        showToast('�������� ����� ������', 'error');
        return;
    }
    try {
        const formData = new FormData();
        formData.append('text', textValue);
        formData.append('send_mode', sendMode);
        formData.append('subject', '');
        (state.composeAttachments || []).forEach((file) => {
            formData.append('attachments', file);
        });
        const message = await apiFetch(/conversations//send, {
            method: 'POST',
            body: formData,
        });
        const messages = Array.isArray(state.currentConversation.messages)
            ? [...state.currentConversation.messages, message]
            : [message];
        const updatedConversation = {
            ...state.currentConversation,
            messages,
            status: 'answered_by_llm',
        };
        state.composeAttachments = [];
        if (elements.composeAttachmentsInput) {
            elements.composeAttachmentsInput.value = '';
        }
        renderComposeAttachments();
        elements.composeText.value = '';
        state.selectedMessageId = message.id;
        renderDetail(updatedConversation, { preserveSelection: true, preserveDraft: true });
        showToast('����� ���������');
        await loadConversations();
    } catch (error) {
        showToast(error.message || '�� ������� ��������� ���������', 'error');
    }
}

async function handleAssignScenario() {
    if (!state.currentConversation) {
        return;
    }
    const scenarioId = parseInt(elements.scenarioSelect.value, 10);
    if (!scenarioId) {
        showToast('Выберите сценарий', 'error');
        return;
    }
    const notes = elements.scenarioNotesInput.value || null;
    try {
        const scenarioState = await apiFetch(`/conversations/${state.currentConversation.id}/scenario/assign`, {
            method: 'POST',
            body: JSON.stringify({ scenario_id: scenarioId, notes }),
        });
        const updatedConversation = {
            ...state.currentConversation,
            scenario_state: scenarioState,
        };
        renderDetail(updatedConversation, { preserveDraft: true, preserveSelection: true });
        showToast('Сценарий назначен');
        await loadConversations();
    } catch (error) {
        showToast(error.message || 'Не удалось назначить сценарий', 'error');
    }
}

async function handleAdvanceScenario(direction = null) {
    if (!state.currentConversation) {
        return;
    }
    const { scenario_state: scenarioState } = state.currentConversation;
    if (!scenarioState) {
        showToast('Сценарий не назначен', 'error');
        return;
    }
    const payload = {
        direction,
        step_id: null,
        notes: elements.scenarioNotesInput.value || null,
    };
    try {
        const nextState = await apiFetch(`/conversations/${state.currentConversation.id}/scenario/advance`, {
            method: 'POST',
            body: JSON.stringify(payload),
        });
        const updatedConversation = {
            ...state.currentConversation,
            scenario_state: nextState,
        };
        renderDetail(updatedConversation, { preserveDraft: true, preserveSelection: true });
        showToast('Сценарий обновлён');
    } catch (error) {
        showToast(error.message || 'Не удалось обновить сценарий', 'error');
    }
}

async function handleSaveNotes() {
    await handleAdvanceScenario(null);
}

async function handleAddLog() {
    if (!state.currentConversation) {
        return;
    }
    const summary = elements.logSummary.value.trim();
    if (!summary) {
        showToast('Добавьте краткое описание', 'error');
        return;
    }
    const context = elements.logContext.value.trim() || null;
    try {
        const entry = await apiFetch(`/conversations/${state.currentConversation.id}/logs/notes`, {
            method: 'POST',
            body: JSON.stringify({ summary, context, details: null }),
        });
        elements.logSummary.value = '';
        elements.logContext.value = '';
        const logs = Array.isArray(state.currentConversation.logs)
            ? [...state.currentConversation.logs, entry]
            : [entry];
        state.currentConversation = {
            ...state.currentConversation,
            logs,
        };
        renderLogs(logs);
        showToast('Комментарий добавлен');
    } catch (error) {
        showToast(error.message || 'Не удалось добавить запись', 'error');
    }
}

async function refreshCurrentLogs() {
    if (!state.currentConversation) {
        return;
    }
    try {
        const logs = await apiFetch(`/conversations/${state.currentConversation.id}/logs`);
        state.currentConversation = {
            ...state.currentConversation,
            logs,
        };
        renderLogs(logs);
    } catch (error) {
        showToast(error.message || 'Не удалось обновить журнал', 'error');
    }
}

function handleConversationSearch(event) {
function handleConversationSearch(event) {
    const value = event.target.value;
    if (searchTimer) {
        clearTimeout(searchTimer);
    }
    searchTimer = setTimeout(() => {
        state.filters.search = value;
        renderConversations();
    }, 200);
}

function handleStatusFilterChange(event) {
    state.filters.status = event.target.value;
    renderConversations();
}

function initEventListeners() {
    if (elements.messageList) {
        elements.messageList.addEventListener('click', (event) => {
            const item = event.target.closest('.message-item');
            if (!item) {
                return;
            }
            const id = Number.parseInt(item.dataset.id, 10);
            if (Number.isNaN(id) || !state.currentConversation) {
                return;
            }
            state.selectedMessageId = id;
            highlightSelectedMessage();
            renderMessageViewer(state.currentConversation);
        });
    }

    if (elements.replyButton) {
        elements.replyButton.addEventListener('click', () => {
            handleReplyAction('reply');
        });
    }
    if (elements.replyAllButton) {
        elements.replyAllButton.addEventListener('click', () => {
            handleReplyAction('reply-all');
        });
    }
    if (elements.forwardButton) {
        elements.forwardButton.addEventListener('click', () => {
            handleReplyAction('forward');
        });
    }

    elements.conversationList.addEventListener('click', (event) => {
        const item = event.target.closest('.conversation-item');
        if (!item) {
            return;
        }
        const id = parseInt(item.dataset.id, 10);
        if (Number.isNaN(id)) {
            return;
        }
        selectConversation(id).catch((error) => showToast(error.message, 'error'));
    });

    elements.loginForm.addEventListener('submit', async (event) => {
        event.preventDefault();
        const formData = new URLSearchParams();
        formData.append('username', elements.loginEmail.value.trim());
        formData.append('password', elements.loginPassword.value);
        try {
            const response = await fetch(`${API_BASE}/auth/token`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
                body: formData,
            });
            if (!response.ok) {
                const text = await response.text();
                throw new Error(text || 'Ошибка авторизации');
            }
            const data = await response.json();
            setAuth(data.access_token, elements.loginEmail.value.trim());
            showToast('Вы вошли в систему');
            await Promise.all([loadConversations(), loadScenarios()]);
            scheduleConversationRefresh();
        } catch (error) {
            showToast(error.message || 'Не удалось войти', 'error');
        }
    });

    [elements.sendApproveAI, elements.sendManual].forEach((button) => {
        button.addEventListener('click', () => {
            const mode = button === elements.sendApproveAI ? 'approve_ai' : 'manual';
            handleSend(mode).catch((error) => showToast(error.message, 'error'));
        });
    });

        if (elements.composeAttachmentsBtn && elements.composeAttachmentsInput) {
        elements.composeAttachmentsBtn.addEventListener('click', () => {
            elements.composeAttachmentsInput.click();
        });
        elements.composeAttachmentsInput.addEventListener('change', handleAttachmentSelection);
    }

    if (elements.composeAttachmentsList) {
        elements.composeAttachmentsList.addEventListener('click', (event) => {
            const button = event.target.closest('.attachment-remove');
            if (!button) {
                return;
            }
            const index = Number.parseInt(button.dataset.index, 10);
            if (Number.isNaN(index)) {
                return;
            }
            removeComposeAttachment(index);
        });
    }

    elements.assignScenario.addEventListener('click', () => {
        handleAssignScenario().catch((error) => showToast(error.message, 'error'));
    });

    elements.scenarioPrev.addEventListener('click', () => {
        handleAdvanceScenario('previous').catch((error) => showToast(error.message, 'error'));
    });

    elements.scenarioNext.addEventListener('click', () => {
        handleAdvanceScenario('next').catch((error) => showToast(error.message, 'error'));
    });

    elements.scenarioSaveNotes.addEventListener('click', () => {
        handleSaveNotes().catch((error) => showToast(error.message, 'error'));
    });

    elements.scenarioComplete.addEventListener('click', () => {
        showToast('Дождитесь последнего шага сценария и сохраните заметки.', 'info');
    });

    elements.logAdd.addEventListener('click', () => {
        handleAddLog().catch((error) => showToast(error.message, 'error'));
    });

    elements.closeConversation.addEventListener('click', async () => {
        if (!state.currentConversation) {
            return;
        }
        if (!window.confirm('Закрыть диалог?')) {
            return;
        }
        try {
            await apiFetch(`/conversations/${state.currentConversation.id}/close`, { method: 'POST' });
            showToast('Диалог закрыт');
            await loadConversations();
            state.currentConversation = null;
            state.selectedMessageId = null;
            state.currentConversationId = null;
            renderConversations();
            if (elements.detailView && elements.emptyState) {
                elements.detailView.classList.add('hidden');
                elements.emptyState.classList.remove('hidden');
            }
        } catch (error) {
            showToast(error.message || 'Не удалось закрыть диалог', 'error');
        }
    });

    elements.reloadConversations.addEventListener('click', () => {
        loadConversations().catch((error) => showToast(error.message, 'error'));
    });

    elements.refreshLogs.addEventListener('click', () => {
        refreshCurrentLogs().catch((error) => showToast(error.message, 'error'));
    });

    elements.logout.addEventListener('click', () => {
        clearAuth();
    });

    elements.conversationSearch.addEventListener('input', handleConversationSearch);
    elements.conversationSearch.addEventListener('search', handleConversationSearch);
    elements.statusFilter.addEventListener('change', handleStatusFilterChange);
    renderComposeAttachments();
}

async function init() {
    updateAuthUI();
    if (state.token) {
        await Promise.all([loadConversations(), loadScenarios()]);
        scheduleConversationRefresh();
    }
}

initEventListeners();
init().catch((error) => showToast(error.message || 'Не удалось инициализировать приложение', 'error'));


