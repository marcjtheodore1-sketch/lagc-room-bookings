/* Room quantities and an editable email, reviewed before any sending. */
let roomRequestOptions = null;
let roomRequestReview = null;
let roomRequestBusy = false;
let roomRequestGeneration = 0;
let roomRequestPendingSend = null;
let roomRequestPreviewSelection = null;
let roomRequestLoading = null;

async function roomRequestFetch(path, options = {}) {
    const response = await fetch('/api/admin/room-requests/' + path, options);
    if (response.redirected) throw new Error('Your admin session has ended. Sign in again.');
    const data = await response.json();
    if (!response.ok) {
        const error = new Error(data.error || 'The request could not be completed.');
        error.record = data.request;
        throw error;
    }
    return data;
}

function cancelRoomRequestSend() {
    roomRequestPendingSend = null;
    const dialog = document.getElementById('rr-send-confirmation');
    if (dialog.open) dialog.close();
}

function invalidateRoomRequest() {
    cancelRoomRequestSend();
    roomRequestGeneration++;
    roomRequestReview = null;
    roomRequestPreviewSelection = null;
    document.getElementById('rr-preview').hidden = true;
    document.getElementById('rr-send-btn').disabled = true;
    document.getElementById('rr-status').textContent = '';
}

function changeRoomRequestChoices() {
    invalidateRoomRequest();
    document.getElementById('rr-editor').hidden = true;
}

async function loadRoomRequests() {
    if (roomRequestLoading) return roomRequestLoading;
    roomRequestLoading = initialiseRoomRequests();
    try { await roomRequestLoading; } finally { roomRequestLoading = null; }
}

async function initialiseRoomRequests() {
    try {
        if (!roomRequestOptions) {
            roomRequestOptions = await roomRequestFetch('options');
            document.getElementById('rr-rooms').innerHTML = roomRequestOptions.rooms.map(room => `
                <div class="room-request-row">
                    <label for="rr-count-${room.id}">${escapeHtml(room.label || room.name)}</label>
                    <input type="number" id="rr-count-${room.id}" min="0" max="52" step="1" value="0" required aria-label="Fridays for ${escapeHtml(room.label || room.name)}">
                </div>`).join('');
        }
        await loadRoomRequestHistory();
    } catch (error) { document.getElementById('rr-status').textContent = error.message; }
}

function roomRequestDeliveryChoices() {
    const mode = document.getElementById('rr-delivery').value;
    const target = document.getElementById('rr-test-target').value;
    return {delivery_mode: mode, test_recipients: mode === 'test' ?
        (target === 'both' ? ['chris', 'florence'] : target ? [target] : []) : []};
}

function toggleRoomRequestDelivery() {
    const test = document.getElementById('rr-delivery').value === 'test';
    document.getElementById('rr-test-options').hidden = !test;
    document.getElementById('rr-test-target').disabled = !test;
    document.getElementById('rr-test-target').required = test;
    changeRoomRequestChoices();
}

function roomRequestChoices() {
    return {request_id: roomRequestOptions.request_id, ...roomRequestDeliveryChoices(),
        rooms: roomRequestOptions.rooms.flatMap(room => {
            const count = Number(document.getElementById(`rr-count-${room.id}`).value);
            return count > 0 ? [{room_id: room.id, count}] : [];
        }), notes: document.getElementById('rr-notes').value, period: document.getElementById('rr-period').value};
}

function currentRoomRequestSelection() {
    return JSON.stringify({...roomRequestChoices(), subject: document.getElementById('rr-email-subject').value,
        body: document.getElementById('rr-email-body').value});
}

function roomRequestSelectionStillMatches() {
    return roomRequestReview !== null && roomRequestPreviewSelection !== null &&
        roomRequestPreviewSelection === currentRoomRequestSelection();
}

async function createRoomRequestEmail(event) {
    event.preventDefault();
    if (roomRequestBusy) return;
    invalidateRoomRequest();
    const generation = roomRequestGeneration;
    const button = document.getElementById('rr-create-btn');
    button.disabled = true;
    try {
        const record = await roomRequestFetch('preview', {method: 'POST', headers: {'Content-Type': 'application/json'},
            body: JSON.stringify(roomRequestChoices())});
        if (generation !== roomRequestGeneration) return;
        if (record.status !== 'draft') {
            showRoomRequestPreview(record, true);
            document.getElementById('rr-status').textContent = 'This request was already attempted. Check Previous emails. Use Start a new request for a different request.';
            return;
        }
        document.getElementById('rr-email-subject').value = record.subject;
        document.getElementById('rr-email-body').value = record.body;
        document.getElementById('rr-editor').hidden = false;
        document.getElementById('rr-editor-heading').scrollIntoView({block: 'start', behavior: 'smooth'});
        document.getElementById('rr-status').textContent = 'Your email is ready to edit. Nothing has been sent.';
    } catch (error) { if (generation === roomRequestGeneration) document.getElementById('rr-status').textContent = error.message; }
    finally { button.disabled = false; }
}

async function previewRoomRequest(event) {
    event.preventDefault();
    if (roomRequestBusy) return;
    invalidateRoomRequest();
    const generation = roomRequestGeneration;
    const selection = currentRoomRequestSelection();
    const button = document.getElementById('rr-preview-btn');
    button.disabled = true;
    try {
        const record = await roomRequestFetch('preview', {method: 'POST', headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({...roomRequestChoices(), subject: document.getElementById('rr-email-subject').value,
                body: document.getElementById('rr-email-body').value})});
        if (generation !== roomRequestGeneration || selection !== currentRoomRequestSelection()) return;
        let expectedSubject = document.getElementById('rr-email-subject').value.trim();
        if (roomRequestDeliveryChoices().delivery_mode === 'test' && !expectedSubject.startsWith('[TEST] ')) expectedSubject = '[TEST] ' + expectedSubject;
        if (record.status === 'draft' && (record.subject !== expectedSubject ||
                record.body !== document.getElementById('rr-email-body').value.trim())) {
            throw new Error('The email has changed. Review it again before sending.');
        }
        document.getElementById('rr-email-subject').value = record.subject;
        document.getElementById('rr-email-body').value = record.body;
        roomRequestPreviewSelection = currentRoomRequestSelection();
        showRoomRequestPreview(record);
        document.getElementById('rr-preview-heading').scrollIntoView({block: 'start', behavior: 'smooth'});
    } catch (error) { if (generation === roomRequestGeneration) document.getElementById('rr-status').textContent = error.message; }
    finally { button.disabled = false; }
}

function showRoomRequestPreview(record, readOnly = false) {
    cancelRoomRequestSend();
    roomRequestReview = readOnly ? null : record;
    const test = record.delivery_mode === 'test';
    document.getElementById('rr-send-btn').textContent = test ? 'Send test email' : 'Send request';
    document.getElementById('rr-headers').innerHTML = [['To', record.recipient_names.to.join(' and ')],
        ['Copy to', record.recipient_names.cc.join(' and ')]].filter(([, value]) => value)
        .map(([label, value]) => `<dt>${escapeHtml(label)}</dt><dd>${escapeHtml(value)}</dd>`).join('');
    document.getElementById('rr-subject').textContent = record.subject;
    document.getElementById('rr-body').textContent = record.body;
    const states = {draft: 'Nothing has been sent. Check your email, then choose Send request.',
        sent: 'This email has already been sent.', sending: 'Check delivery in the mailbox before trying again.',
        uncertain: 'Delivery is unclear. Check the mailbox before trying again.', failed: 'The email could not be sent. Review it again before retrying.'};
    document.getElementById('rr-preview-state').textContent = readOnly ? 'Previous email, shown for reference.' :
        test && record.status === 'draft' ? 'Nothing has been sent. This test will go only to the names shown above.' : states[record.status] || record.status;
    document.getElementById('rr-send-btn').hidden = readOnly;
    document.getElementById('rr-send-btn').disabled = readOnly || record.status !== 'draft' || roomRequestBusy;
    document.getElementById('rr-preview').hidden = false;
}

function editRoomRequestEmail() {
    invalidateRoomRequest();
    document.getElementById('rr-email-body').focus();
}

function sendRoomRequest() {
    if (!roomRequestReview || roomRequestReview.status !== 'draft' || roomRequestBusy) return;
    if (!roomRequestSelectionStillMatches()) {
        invalidateRoomRequest();
        document.getElementById('rr-status').textContent = 'Your email or room choices have changed. Choose Check before sending again.';
        return;
    }
    roomRequestPendingSend = roomRequestReview.review_key;
    const test = roomRequestReview.delivery_mode === 'test';
    document.getElementById('rr-confirm-heading').textContent = test ? 'Send this test email?' : 'Send this room request?';
    document.getElementById('rr-confirm-summary').textContent = test ?
        'This is a test. Emma and Martha will not receive it. Your email will go to:' : 'Your email will go to:';
    document.getElementById('rr-confirm-recipients').textContent = roomRequestReview.recipient_names.to.join(' and ') +
        (roomRequestReview.recipient_names.cc.length ? ', with ' + roomRequestReview.recipient_names.cc.join(' and ') + ' copied in.' : '.');
    document.getElementById('rr-confirm-subject').textContent = roomRequestReview.subject;
    const dialog = document.getElementById('rr-send-confirmation');
    if (!dialog.open) dialog.showModal();
    document.getElementById('rr-confirm-cancel').focus();
}

async function confirmRoomRequestSend() {
    const dialog = document.getElementById('rr-send-confirmation');
    if (!dialog.open || !roomRequestReview || roomRequestReview.status !== 'draft' || roomRequestBusy ||
            roomRequestPendingSend !== roomRequestReview.review_key) return;
    if (!roomRequestSelectionStillMatches()) {
        invalidateRoomRequest();
        document.getElementById('rr-status').textContent = 'Your email or room choices have changed. Choose Check before sending again.';
        return;
    }
    const review = roomRequestReview;
    cancelRoomRequestSend();
    roomRequestBusy = true;
    document.getElementById('rr-send-btn').disabled = true;
    document.getElementById('room-request-form').inert = true;
    document.getElementById('rr-editor-form').inert = true;
    document.getElementById('rr-preview-state').textContent = 'Sending your reviewed email...';
    try {
        const result = await roomRequestFetch('send', {method: 'POST', headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({review_key: review.review_key, confirmed: true})});
        showRoomRequestPreview(result.request);
        document.getElementById('rr-preview-state').textContent = result.already_sent ?
            'This email was already sent. No second email was sent.' : result.request.delivery_mode === 'test' ?
                'Test email sent only to ' + result.request.recipient_names.to.join(' and ') + '. Emma and Martha have not been emailed.' :
                'Sent to Emma and Martha, with Florence copied in. Replies go to Florence.';
    } catch (error) {
        if (error.record) showRoomRequestPreview(error.record);
        else roomRequestReview = null;
        document.getElementById('rr-preview-state').textContent = error.message + ' Check Previous emails before trying again.';
    } finally {
        roomRequestBusy = false;
        document.getElementById('room-request-form').inert = false;
        document.getElementById('rr-editor-form').inert = false;
        document.getElementById('rr-send-btn').disabled = true;
        await loadRoomRequestHistory();
    }
}

async function startNewRoomRequest() {
    if (roomRequestBusy) return;
    changeRoomRequestChoices();
    roomRequestOptions = null;
    document.getElementById('rr-notes').value = '';
    document.getElementById('rr-period').value = '';
    document.getElementById('rr-delivery').value = 'test';
    document.getElementById('rr-test-target').value = '';
    toggleRoomRequestDelivery();
    await loadRoomRequests();
    document.getElementById('room-request-form').scrollIntoView({block: 'start', behavior: 'smooth'});
}

async function loadRoomRequestHistory() {
    const container = document.getElementById('rr-history');
    try {
        const records = (await roomRequestFetch('history')).filter(record => record.status !== 'draft');
        container.replaceChildren();
        if (!records.length) { container.textContent = 'No emails have been sent yet.'; return; }
        for (const record of records) {
            const item = document.createElement('div'); item.className = 'room-request-history-item';
            const text = document.createElement('p');
            const labels = {sent: 'Sent', sending: 'Check delivery', uncertain: 'Check delivery', failed: 'Not sent'};
            text.textContent = `${record.subject} · ${labels[record.status] || record.status} · ` +
                new Date(record.sent_at || record.created_at).toLocaleString('en-GB', {timeZone: 'Europe/London'});
            const button = document.createElement('button'); button.type = 'button'; button.className = 'btn btn-secondary btn-small';
            button.textContent = 'View email'; button.addEventListener('click', () => {
                if (roomRequestBusy) return;
                invalidateRoomRequest();
                showRoomRequestPreview(record, true);
                document.getElementById('rr-preview-heading').scrollIntoView({block: 'start', behavior: 'smooth'});
            });
            item.append(text, button); container.append(item);
        }
    } catch (error) { container.textContent = 'Previous emails could not be loaded: ' + error.message; }
}

for (const event of ['input', 'change']) {
    document.getElementById('room-request-form').addEventListener(event, changeRoomRequestChoices);
    document.getElementById('rr-editor-form').addEventListener(event, invalidateRoomRequest);
}
document.getElementById('rr-send-confirmation').addEventListener('close', () => { roomRequestPendingSend = null; });
