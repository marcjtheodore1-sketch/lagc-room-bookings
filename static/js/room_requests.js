/* Venue requests are separate from public room availability. */
let roomRequestOptions = null;
let roomRequestPeriod = null;
let roomRequestReview = null;
let roomRequestBusy = false;
let roomRequestGeneration = 0;
let roomRequestPendingSend = null;
let roomRequestPreviewSelection = null;
let roomRequestLoading = null;

function roomRequestDate(value) {
    const day = new Date(value + 'T12:00:00Z');
    const number = day.getUTCDate();
    const suffix = number >= 11 && number <= 13 ? 'th' : ({1: 'st', 2: 'nd', 3: 'rd'}[number % 10] || 'th');
    return day.toLocaleDateString('en-GB', {weekday: 'long', timeZone: 'UTC'}) + ' ' + number + suffix + ' ' +
        day.toLocaleDateString('en-GB', {month: 'long', year: 'numeric', timeZone: 'UTC'});
}

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

function invalidateRoomRequest() {
    cancelRoomRequestSend();
    roomRequestGeneration++;
    roomRequestReview = null;
    roomRequestPreviewSelection = null;
    document.getElementById('rr-preview').hidden = true;
    document.getElementById('rr-send-btn').disabled = true;
    document.getElementById('rr-status').textContent = '';
}

async function loadRoomRequests() {
    if (roomRequestLoading) return roomRequestLoading;
    roomRequestLoading = initialiseRoomRequests();
    try { await roomRequestLoading; } finally { roomRequestLoading = null; }
}

async function initialiseRoomRequests() {
    const status = document.getElementById('rr-status');
    try {
        if (!roomRequestOptions) {
            roomRequestOptions = await roomRequestFetch('options');
            for (const [id, value] of [['rr-start', roomRequestOptions.start_date], ['rr-end', roomRequestOptions.end_date]]) {
                document.getElementById(id).value = value;
                document.getElementById(id).min = roomRequestOptions.min_date;
            }
            document.getElementById('rr-arranged-summary').textContent = roomRequestOptions.arranged_through ?
                'Rooms are already arranged through ' + roomRequestDate(roomRequestOptions.arranged_through) +
                '. This form starts with the next Fridays, from ' + roomRequestDate(roomRequestOptions.start_date) + '.' :
                'Use this form for Fridays that haven’t been arranged yet.';
            document.getElementById('rr-test-target').innerHTML = '<option value="">Choose who receives the test</option>' +
                roomRequestOptions.test_recipients.map(person =>
                    `<option value="${escapeHtml(person.id)}">${escapeHtml(person.name)} only (${escapeHtml(person.email)})</option>`).join('') +
                '<option value="both">Chris and Florence</option>';
            toggleRoomRequestDelivery();
            buildRoomRequestChoices();
        }
        await loadRoomRequestHistory();
    } catch (error) { status.textContent = error.message; }
}

function roomRequestDeliverySelection() {
    const mode = document.getElementById('rr-delivery').value;
    const target = document.getElementById('rr-test-target').value;
    return {delivery_mode: mode, test_recipients: mode !== 'test' ? [] :
        target === 'both' ? ['chris', 'florence'] : target ? [target] : []};
}

function currentRoomRequestSelection() {
    return JSON.stringify({start_date: document.getElementById('rr-start').value,
        end_date: document.getElementById('rr-end').value, notes: document.getElementById('rr-notes').value,
        ...roomRequestDeliverySelection(), rooms: roomRequestOptions.rooms.map(room => ({id: room.id,
            mode: document.getElementById(`rr-mode-${room.id}`).value,
            count: document.getElementById(`rr-count-${room.id}`).value,
            dates: [...document.querySelectorAll(`input[name="rr-days-${room.id}"]:checked`)].map(input => input.value)}))});
}

function roomRequestRecipientsMatch(record) {
    const selection = roomRequestDeliverySelection();
    const expectedTo = selection.delivery_mode === 'test' ? selection.test_recipients.map(id =>
        roomRequestOptions.test_recipients.find(person => person.id === id)?.email).filter(Boolean) : roomRequestOptions.to;
    const expectedCc = selection.delivery_mode === 'test' ? [] : roomRequestOptions.cc;
    const same = (left, right) => JSON.stringify([...left].sort()) === JSON.stringify([...right].sort());
    return record.delivery_mode === selection.delivery_mode && same(record.to, expectedTo) && same(record.cc, expectedCc);
}

function roomRequestSelectionStillMatches() {
    return roomRequestReview !== null && roomRequestPreviewSelection !== null &&
        roomRequestPreviewSelection === currentRoomRequestSelection() && roomRequestRecipientsMatch(roomRequestReview);
}

function toggleRoomRequestDelivery() {
    const test = document.getElementById('rr-delivery').value === 'test';
    document.getElementById('rr-test-options').hidden = !test;
    document.getElementById('rr-test-target').disabled = !test;
    document.getElementById('rr-test-target').required = test;
    document.getElementById('rr-live-warning').hidden = test;
    invalidateRoomRequest();
}

function buildRoomRequestChoices() {
    if (!roomRequestOptions || roomRequestBusy) return;
    invalidateRoomRequest();
    const start = document.getElementById('rr-start').value;
    const end = document.getElementById('rr-end').value;
    const first = new Date(start + 'T12:00:00Z');
    const last = new Date(end + 'T12:00:00Z');
    const days = [];
    if (!start || !end || start < roomRequestOptions.min_date || last < first || (last - first) / 86400000 > 366) {
        roomRequestPeriod = null;
        document.getElementById('rr-status').textContent = 'Choose dates after the rooms already arranged, covering up to a year.';
        return;
    }
    for (const day = new Date(first); day <= last; day.setUTCDate(day.getUTCDate() + 1)) {
        if (day.getUTCDay() === 5) days.push(day.toISOString().slice(0, 10));
    }
    roomRequestPeriod = {start, end, days};
    document.getElementById('rr-period-summary').textContent = days.length ?
        `${days.length} Friday${days.length === 1 ? '' : 's'}: ${days.map(roomRequestDate).join('; ')}.` : 'This period has no Fridays. Choose another period.';
    document.getElementById('rr-rooms').innerHTML = days.length ? roomRequestOptions.rooms.map(room => `
        <fieldset class="room-request-room" data-room-id="${room.id}">
            <legend>${escapeHtml(room.label || room.name)}</legend>
            <label for="rr-mode-${room.id}">Dates for ${escapeHtml(room.label || room.name)}</label>
            <select id="rr-mode-${room.id}" onchange="toggleRoomRequestMode(${room.id})">
                <option value="none">Not requested</option><option value="exact">Choose the Fridays</option><option value="flexible">Let the venue choose which Fridays</option>
            </select>
            <div id="rr-exact-${room.id}" hidden>
                <button type="button" class="btn btn-secondary btn-small" onclick="selectAllRoomRequestDates(${room.id})">Every Friday in this period</button>
                <div class="room-request-days">${days.map(day => `<label><input type="checkbox" value="${day}" name="rr-days-${room.id}"> ${roomRequestDate(day)}</label>`).join('')}</div>
            </div>
            <div id="rr-flexible-${room.id}" hidden>
                <label for="rr-count-${room.id}">How many Fridays would you like this room? (up to ${days.length})</label>
                <input type="number" id="rr-count-${room.id}" min="1" max="${days.length}" value="1" disabled>
                <p class="hint">For example, choose 3 to ask for this room on any 3 Fridays in this period. Emma and Martha can offer the dates that are available.</p>
            </div>
        </fieldset>`).join('') : '';
}

function toggleRoomRequestMode(id) {
    const mode = document.getElementById(`rr-mode-${id}`).value;
    document.getElementById(`rr-exact-${id}`).hidden = mode !== 'exact';
    document.getElementById(`rr-flexible-${id}`).hidden = mode !== 'flexible';
    document.getElementById(`rr-count-${id}`).disabled = mode !== 'flexible';
    invalidateRoomRequest();
}

function selectAllRoomRequestDates(id) {
    document.querySelectorAll(`input[name="rr-days-${id}"]`).forEach(input => { input.checked = true; });
    invalidateRoomRequest();
}

function showRoomRequestPreview(record, readOnly = false) {
    cancelRoomRequestSend();
    roomRequestReview = readOnly ? null : record;
    const test = record.delivery_mode === 'test';
    document.getElementById('rr-preview-heading').textContent = test ? 'Check your test email' : 'Check your email';
    document.getElementById('rr-send-btn').textContent = test ? 'Send test email' : 'Send request to Emma and Martha';
    document.getElementById('rr-headers').innerHTML = [['To', record.to.join(', ')], ['Cc', record.cc.join(', ')]]
        .filter(([, value]) => value).map(([label, value]) => `<dt>${escapeHtml(label)}</dt><dd>${escapeHtml(value)}</dd>`).join('');
    document.getElementById('rr-subject').textContent = record.subject;
    document.getElementById('rr-body').textContent = record.body;
    const states = {draft: 'Nothing has been sent. Check the dates and rooms, then send when you are ready.',
        sent: 'This request has already been sent. It will not be sent again.',
        sending: 'This request is being sent, or needs a delivery check. Check the history and sent mailbox before doing anything further.',
        uncertain: 'Delivery is unclear. Check the sent mailbox before sending anything again.',
        failed: 'The email could not be sent. Preview the form again to retry.'};
    document.getElementById('rr-preview-state').textContent = test && record.status === 'draft' ?
        'Nothing has been sent. This test will go only to the recipients shown above.' : states[record.status] || record.status;
    document.getElementById('rr-send-btn').hidden = readOnly;
    document.getElementById('rr-send-btn').disabled = readOnly || record.status !== 'draft' || roomRequestBusy;
    if (readOnly) document.getElementById('rr-preview-state').textContent = 'Previous email, shown for reference. Use the form above to prepare a new email.';
    document.getElementById('rr-preview').hidden = false;
}

async function previewRoomRequest(event) {
    event.preventDefault();
    if (roomRequestBusy) return;
    const status = document.getElementById('rr-status');
    const start = document.getElementById('rr-start').value;
    const end = document.getElementById('rr-end').value;
    if (!roomRequestPeriod || roomRequestPeriod.start !== start || roomRequestPeriod.end !== end) {
        status.textContent = 'Choose Show Fridays for this period, then select your rooms.';
        return;
    }
    const rooms = roomRequestOptions.rooms.flatMap(room => {
        const mode = document.getElementById(`rr-mode-${room.id}`).value;
        if (mode === 'none') return [];
        return [{room_id: room.id, mode, ...(mode === 'exact' ?
            {dates: [...document.querySelectorAll(`input[name="rr-days-${room.id}"]:checked`)].map(input => input.value)} :
            {count: Number(document.getElementById(`rr-count-${room.id}`).value)})}];
    });
    invalidateRoomRequest();
    const selection = currentRoomRequestSelection();
    const generation = roomRequestGeneration;
    const button = document.getElementById('rr-preview-btn');
    button.disabled = true;
    status.textContent = 'Preparing your preview...';
    try {
        const record = await roomRequestFetch('preview', {method: 'POST', headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({start_date: start, end_date: end, rooms, notes: document.getElementById('rr-notes').value,
                ...roomRequestDeliverySelection()})});
        if (generation !== roomRequestGeneration || selection !== currentRoomRequestSelection()) return;
        if (!roomRequestRecipientsMatch(record)) throw new Error('The recipients do not match your choice. Preview the email again.');
        roomRequestPreviewSelection = selection;
        showRoomRequestPreview(record);
        status.textContent = 'Preview ready. Review the message below.';
        document.getElementById('rr-preview-heading').scrollIntoView({block: 'start', behavior: 'smooth'});
        await loadRoomRequestHistory();
    } catch (error) { if (generation === roomRequestGeneration) status.textContent = error.message; }
    finally { button.disabled = false; }
}

function editRoomRequest() {
    invalidateRoomRequest();
    document.getElementById('rr-start').focus();
}

function cancelRoomRequestSend() {
    roomRequestPendingSend = null;
    const dialog = document.getElementById('rr-send-confirmation');
    if (dialog.open) dialog.close();
}

function sendRoomRequest() {
    if (!roomRequestReview || roomRequestReview.status !== 'draft' || roomRequestBusy) return;
    if (!roomRequestSelectionStillMatches()) {
        invalidateRoomRequest();
        document.getElementById('rr-status').textContent = 'Your choices have changed. Choose Preview email again before sending.';
        return;
    }
    const review = roomRequestReview;
    const test = review.delivery_mode === 'test';
    roomRequestPendingSend = review.review_key;
    document.getElementById('rr-confirm-heading').textContent = test ? 'Send this test email?' : 'Send this room request?';
    document.getElementById('rr-confirm-summary').textContent = test ?
        'This is a test email. Only the people listed below will receive it. Emma and Martha will not be emailed.' :
        'This is a real room request to Pan Macmillan. It will be emailed to the people listed below.';
    document.getElementById('rr-confirm-recipients').innerHTML = [['To', review.to.join(', ')], ['Cc', review.cc.join(', ')]]
        .filter(([, value]) => value).map(([label, value]) => `<dt>${escapeHtml(label)}</dt><dd>${escapeHtml(value)}</dd>`).join('');
    document.getElementById('rr-confirm-subject').textContent = review.subject;
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
        document.getElementById('rr-status').textContent = 'Your choices have changed. Choose Preview email again before sending.';
        return;
    }
    const review = roomRequestReview;
    cancelRoomRequestSend();
    roomRequestBusy = true;
    document.getElementById('rr-send-btn').disabled = true;
    document.getElementById('rr-preview-btn').disabled = true;
    document.getElementById('room-request-form').inert = true;
    document.getElementById('rr-preview-state').textContent = 'Sending your reviewed request...';
    try {
        const result = await roomRequestFetch('send', {method: 'POST', headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({review_key: review.review_key, confirmed: true})});
        showRoomRequestPreview(result.request);
        document.getElementById('rr-preview-state').textContent = result.already_sent ?
            'This request was already sent. No second email was sent.' : result.request.delivery_mode === 'test' ?
                'Test email sent only to ' + result.request.to.join(', ') + '. Emma and Martha have not been emailed.' :
                'Request sent to Emma and Martha, with Florence copied. Replies go to Florence.';
    } catch (error) {
        if (error.record) showRoomRequestPreview(error.record);
        else { roomRequestReview = null; }
        document.getElementById('rr-preview-state').textContent = error.message + ' Check the history before trying again.';
    } finally {
        roomRequestBusy = false;
        document.getElementById('room-request-form').inert = false;
        document.getElementById('rr-preview-btn').disabled = false;
        document.getElementById('rr-send-btn').disabled = true;
        await loadRoomRequestHistory();
    }
}

async function loadRoomRequestHistory() {
    const container = document.getElementById('rr-history');
    try {
        const records = await roomRequestFetch('history');
        container.replaceChildren();
        const previous = records.filter(record => record.status !== 'draft');
        if (!previous.length) { container.textContent = 'No emails have been sent yet.'; return; }
        for (const record of previous) {
            const item = document.createElement('div'); item.className = 'room-request-history-item';
            const text = document.createElement('p');
            const labels = {draft: 'Unsent preview', sent: 'Sent', sending: 'Check delivery', uncertain: 'Check delivery', failed: 'Not sent'};
            text.textContent = `${record.subject} · ${labels[record.status] || record.status} · ` +
                new Date(record.sent_at || record.created_at).toLocaleString('en-GB', {timeZone: 'Europe/London'});
            const button = document.createElement('button'); button.type = 'button'; button.className = 'btn btn-secondary btn-small';
            button.textContent = 'View email'; button.addEventListener('click', () => {
                if (roomRequestBusy) return;
                roomRequestGeneration++;
                roomRequestPreviewSelection = null;
                showRoomRequestPreview(record, true);
                document.getElementById('rr-preview-heading').scrollIntoView({block: 'start', behavior: 'smooth'});
            });
            item.append(text, button); container.append(item);
        }
    } catch (error) { container.textContent = 'Request history could not be loaded: ' + error.message; }
}

document.getElementById('room-request-form').addEventListener('input', invalidateRoomRequest);
document.getElementById('room-request-form').addEventListener('change', invalidateRoomRequest);

document.getElementById('rr-send-confirmation').addEventListener('close', () => { roomRequestPendingSend = null; });
