/* Venue requests are separate from public room availability. */
let roomRequestOptions = null;
let roomRequestPeriod = null;
let roomRequestReview = null;
let roomRequestBusy = false;
let roomRequestGeneration = 0;

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
    roomRequestGeneration++;
    roomRequestReview = null;
    document.getElementById('rr-preview').hidden = true;
    document.getElementById('rr-send-btn').disabled = true;
    document.getElementById('rr-status').textContent = '';
}

async function loadRoomRequests() {
    const status = document.getElementById('rr-status');
    try {
        if (!roomRequestOptions) {
            roomRequestOptions = await roomRequestFetch('options');
            for (const [id, value] of [['rr-start', roomRequestOptions.start_date], ['rr-end', roomRequestOptions.end_date]]) {
                document.getElementById(id).value = value;
                document.getElementById(id).min = roomRequestOptions.min_date;
            }
            buildRoomRequestChoices();
        }
        await loadRoomRequestHistory();
    } catch (error) { status.textContent = error.message; }
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
        document.getElementById('rr-status').textContent = 'Choose a future period of up to one year.';
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
            <legend>${escapeHtml(room.name)}</legend>
            <label for="rr-mode-${room.id}">Dates for ${escapeHtml(room.name)}</label>
            <select id="rr-mode-${room.id}" onchange="toggleRoomRequestMode(${room.id})">
                <option value="none">Not requested</option><option value="exact">Choose exact Fridays</option><option value="flexible">Flexible dates</option>
            </select>
            <div id="rr-exact-${room.id}" hidden>
                <button type="button" class="btn btn-secondary btn-small" onclick="selectAllRoomRequestDates(${room.id})">Select all Fridays</button>
                <div class="room-request-days">${days.map(day => `<label><input type="checkbox" value="${day}" name="rr-days-${room.id}"> ${roomRequestDate(day)}</label>`).join('')}</div>
            </div>
            <div id="rr-flexible-${room.id}" hidden>
                <label for="rr-count-${room.id}">How many of these ${days.length} Fridays?</label>
                <input type="number" id="rr-count-${room.id}" min="1" max="${days.length}" value="1" disabled>
                <p class="hint">Emma and Martha can suggest which Fridays work for this room.</p>
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

function showRoomRequestPreview(record) {
    roomRequestReview = record;
    document.getElementById('rr-headers').innerHTML = [['From', record.from_email], ['To', record.to.join(', ')],
        ['Cc', record.cc.join(', ')], ['Replies go to', record.reply_to], ['Contract requested for Chris at', record.contract_to]]
        .map(([label, value]) => `<dt>${escapeHtml(label)}</dt><dd>${escapeHtml(value)}</dd>`).join('');
    document.getElementById('rr-subject').textContent = record.subject;
    document.getElementById('rr-body').textContent = record.body;
    const states = {draft: 'Nothing has been sent. Check the dates and rooms, then send when you are ready.',
        sent: 'This request has already been sent. It will not be sent again.',
        sending: 'This request is being sent, or needs a delivery check. Check the history and sent mailbox before doing anything further.',
        uncertain: 'Delivery is unclear. Check the sent mailbox before sending anything again.',
        failed: 'The email could not be sent. Preview the form again to retry.'};
    document.getElementById('rr-preview-state').textContent = states[record.status] || record.status;
    document.getElementById('rr-send-btn').disabled = record.status !== 'draft' || roomRequestBusy;
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
    const generation = roomRequestGeneration;
    const button = document.getElementById('rr-preview-btn');
    button.disabled = true;
    status.textContent = 'Preparing your preview...';
    try {
        const record = await roomRequestFetch('preview', {method: 'POST', headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({start_date: start, end_date: end, rooms, notes: document.getElementById('rr-notes').value})});
        if (generation !== roomRequestGeneration) return;
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

async function sendRoomRequest() {
    if (!roomRequestReview || roomRequestReview.status !== 'draft' || roomRequestBusy) return;
    const review = roomRequestReview;
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
            'This request was already sent. No second email was sent.' : 'Request sent to Emma and Martha, with Florence copied. Replies go to Florence.';
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
        if (!records.length) { container.textContent = 'No room requests yet.'; return; }
        for (const record of records) {
            const item = document.createElement('div'); item.className = 'room-request-history-item';
            const text = document.createElement('p');
            const labels = {draft: 'Unsent preview', sent: 'Sent', sending: 'Check delivery', uncertain: 'Check delivery', failed: 'Not sent'};
            text.textContent = `${record.subject} · ${labels[record.status] || record.status} · ` +
                new Date(record.sent_at || record.created_at).toLocaleString('en-GB', {timeZone: 'Europe/London'});
            const button = document.createElement('button'); button.type = 'button'; button.className = 'btn btn-secondary btn-small';
            button.textContent = 'View email'; button.addEventListener('click', () => {
                if (roomRequestBusy) return;
                roomRequestGeneration++;
                showRoomRequestPreview(record);
                document.getElementById('rr-preview-heading').scrollIntoView({block: 'start', behavior: 'smooth'});
            });
            item.append(text, button); container.append(item);
        }
    } catch (error) { container.textContent = 'Request history could not be loaded: ' + error.message; }
}

document.getElementById('room-request-form').addEventListener('input', invalidateRoomRequest);
