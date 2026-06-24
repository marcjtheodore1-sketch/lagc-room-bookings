/**
 * Room Booking System - Admin Panel JavaScript
 */

// Tab navigation
function showTab(tabName) {
    // Update tab buttons
    document.querySelectorAll('.tab-btn').forEach(btn => {
        btn.classList.remove('active');
    });
    event.target.classList.add('active');
    
    // Update tab content
    document.querySelectorAll('.tab-content').forEach(content => {
        content.classList.remove('active');
    });
    document.getElementById(`tab-${tabName}`).classList.add('active');
    
    // Load data for the tab
    if (tabName === 'rooms') loadRooms();
    if (tabName === 'messages') loadMessageTemplate();
    if (tabName === 'bookings') loadAllBookings();
    if (tabName === 'announcements') loadAnnouncements();
    if (tabName === 'volunteers') loadVolunteers();
    if (tabName === 'yoga') loadYogaBookings();
    if (tabName === 'emailblast') loadEmailBlastDates();
    if (tabName === 'archive') loadArchivedBookings();
}

// ============================================
// YOGA BOOKINGS
// ============================================

async function loadYogaBookings() {
    const wrap = document.getElementById('yoga-admin-list');
    wrap.innerHTML = '<p class="loading">Loading yoga bookings...</p>';
    try {
        const res = await fetch('/api/admin/yoga-bookings');
        const data = await res.json();
        renderYogaBookings(data);
    } catch (e) {
        wrap.innerHTML = '<p class="error-text">Failed to load yoga bookings</p>';
    }
}

function yogaField(label, value) {
    if (!value) return '';
    return `<div class="yoga-field"><span class="yoga-field-label">${label}:</span> ${escapeHtml(value)}</div>`;
}

function renderYogaBookings(data) {
    const wrap = document.getElementById('yoga-admin-list');
    const sessions = data.sessions || [];
    if (!sessions.length) {
        wrap.innerHTML = '<p class="hint">No yoga sessions or bookings yet.</p>';
        return;
    }
    wrap.innerHTML = sessions.map(s => {
        const countClass = s.booked === 0 ? 'vol-count-zero' : (s.booked >= s.capacity ? 'vol-count-ok' : 'vol-count-low');
        const fullBadge = s.booked >= s.capacity ? '<span class="yoga-full-badge">FULL</span>' : '';
        const people = s.bookings.length
            ? s.bookings.map(b => `
                <div class="yoga-booking-card">
                    <div class="yoga-booking-top">
                        <strong>${escapeHtml(b.name)}</strong>
                        <button class="btn btn-danger btn-small" onclick="deleteYogaBooking(${b.id}, '${escapeHtml(b.name).replace(/'/g, "\\'")}')">Remove</button>
                    </div>
                    ${yogaField('Email', b.email)}
                    ${yogaField('Phone', b.phone)}
                    ${yogaField('Emergency contact', b.emergency_name + ' — ' + b.emergency_phone)}
                    ${yogaField('Done yoga before', b.experience)}
                    ${yogaField('Should know (safety)', b.health_info)}
                    ${yogaField('Avoid', b.avoid_info)}
                    ${yogaField('Experience / access needs', b.accessibility_info)}
                    ${yogaField('Consents to contact', b.consent_contact ? 'Yes' : 'No')}
                    <div class="yoga-booking-meta">Registered ${escapeHtml(b.created_at)}</div>
                </div>`).join('')
            : '<p class="vol-none">No bookings yet</p>';
        return `
            <div class="yoga-session-block${s.past ? ' yoga-session-past' : ''}">
                <div class="yoga-session-head">
                    <span class="yoga-session-date">${escapeHtml(s.display)}, ${escapeHtml(s.time)}${s.past ? ' (past)' : ''}</span>
                    <span class="vol-count ${countClass}">${s.booked} / ${s.capacity}${fullBadge ? ' ' : ''}</span>
                    ${fullBadge}
                </div>
                <div class="yoga-bookings">${people}</div>
            </div>`;
    }).join('');
}

async function deleteYogaBooking(id, name) {
    if (!confirm(`Remove ${name}'s yoga booking? This frees a place on that date.`)) return;
    try {
        const res = await fetch('/api/admin/yoga-bookings/' + id, { method: 'DELETE' });
        if (!res.ok) { alert('Failed to remove booking. Please try again.'); return; }
        loadYogaBookings();
    } catch (e) {
        alert('Failed to remove booking. Please try again.');
    }
}

// ============================================
// VOLUNTEER ROTA
// ============================================

let volunteerRota = { fridays: [], volunteers: [] };

async function loadVolunteers() {
    const coverage = document.getElementById('volunteer-coverage');
    const checkboxes = document.getElementById('vol-date-checkboxes');
    coverage.innerHTML = '<p class="loading">Loading rota...</p>';
    checkboxes.innerHTML = '<p class="loading">Loading dates...</p>';
    try {
        const res = await fetch('/api/admin/volunteers');
        volunteerRota = await res.json();
        renderVolunteerCheckboxes();
        renderVolunteerCoverage();
        renderVolunteerPast();
        renderVolunteerArchived();
    } catch (e) {
        coverage.innerHTML = '<p class="error-text">Failed to load the rota</p>';
        checkboxes.innerHTML = '<p class="error-text">Failed to load dates</p>';
    }
}

function volChips(people) {
    return people.length
        ? people.map(p => `<span class="vol-chip">${escapeHtml(p.name)}${p.note ? ` <em>(${escapeHtml(p.note)})</em>` : ''}</span>`).join('')
        : '<span class="vol-none">No one</span>';
}

function renderVolunteerPast() {
    const section = document.getElementById('volunteer-past-section');
    const wrap = document.getElementById('volunteer-past');
    const past = volunteerRota.past || [];
    if (!past.length) {
        section.style.display = 'none';
        wrap.innerHTML = '';
        return;
    }
    section.style.display = '';
    wrap.innerHTML = past.map(d => `
        <div class="vol-date-row">
            <div class="vol-date-head">
                <span class="vol-date-label">${escapeHtml(d.display)}</span>
                <button class="btn btn-secondary btn-small" onclick="archiveVolunteerDate('${d.date}')">Archive</button>
            </div>
            <div class="vol-chips">${volChips(d.volunteers)}</div>
        </div>`).join('');
}

function renderVolunteerArchived() {
    const section = document.getElementById('volunteer-archived-section');
    const wrap = document.getElementById('volunteer-archived');
    const archived = volunteerRota.archived || [];
    if (!archived.length) {
        section.style.display = 'none';
        wrap.innerHTML = '';
        return;
    }
    section.style.display = '';
    wrap.innerHTML = archived.map(d => `
        <div class="vol-date-row vol-archived-row">
            <div class="vol-date-head">
                <span class="vol-date-label">${escapeHtml(d.display)}</span>
                <button class="btn btn-secondary btn-small" onclick="unarchiveVolunteerDate('${d.date}')">Restore</button>
            </div>
            <div class="vol-chips">${volChips(d.volunteers)}</div>
        </div>`).join('');
}

async function archiveVolunteerDate(date) {
    try {
        const res = await fetch('/api/admin/volunteers/archive', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ date }),
        });
        if (!res.ok) { volunteerStatus('Failed to archive. Please try again.', true); return; }
        volunteerRota = await res.json();
        renderVolunteerPast();
        renderVolunteerArchived();
    } catch (e) {
        volunteerStatus('Failed to archive. Please try again.', true);
    }
}

async function unarchiveVolunteerDate(date) {
    try {
        const res = await fetch('/api/admin/volunteers/unarchive', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ date }),
        });
        if (!res.ok) { volunteerStatus('Failed to restore. Please try again.', true); return; }
        volunteerRota = await res.json();
        renderVolunteerPast();
        renderVolunteerArchived();
    } catch (e) {
        volunteerStatus('Failed to restore. Please try again.', true);
    }
}

function renderVolunteerCheckboxes() {
    const wrap = document.getElementById('vol-date-checkboxes');
    if (!volunteerRota.fridays.length) {
        wrap.innerHTML = '<p class="hint">No upcoming Fridays found.</p>';
        return;
    }
    wrap.innerHTML = volunteerRota.fridays.map(f => `
        <label class="vol-date-option">
            <input type="checkbox" class="vol-date-cb" value="${f.date}">
            <span>${escapeHtml(f.display)}</span>
        </label>
    `).join('');
}

function renderVolunteerCoverage() {
    const wrap = document.getElementById('volunteer-coverage');
    const { fridays, volunteers } = volunteerRota;
    if (!fridays.length) {
        wrap.innerHTML = '<p class="hint">No upcoming Fridays to show.</p>';
        return;
    }

    let html = fridays.map(f => {
        const available = volunteers.filter(v => v.dates.includes(f.date));
        const chips = available.length
            ? available.map(v => `<span class="vol-chip">${escapeHtml(v.name)}${v.note ? ` <em>(${escapeHtml(v.note)})</em>` : ''}</span>`).join('')
            : '<span class="vol-none">No one yet</span>';
        const countClass = available.length === 0 ? 'vol-count-zero' : (available.length === 1 ? 'vol-count-low' : 'vol-count-ok');
        return `
            <div class="vol-date-row">
                <div class="vol-date-head">
                    <span class="vol-date-label">${escapeHtml(f.display)}</span>
                    <span class="vol-count ${countClass}">${available.length} ${available.length === 1 ? 'volunteer' : 'volunteers'}</span>
                </div>
                <div class="vol-chips">${chips}</div>
            </div>`;
    }).join('');

    if (volunteers.length) {
        html += `<div class="vol-people">
            <h4>Volunteers</h4>
            ${volunteers.map(v => `
                <div class="vol-person">
                    <button class="btn btn-secondary btn-small" onclick="editVolunteer('${encodeURIComponent(v.name)}')">Edit</button>
                    <button class="btn btn-danger btn-small" onclick="removeVolunteer('${encodeURIComponent(v.name)}')">Remove</button>
                    <span class="vol-person-name">${escapeHtml(v.name)}</span>
                    <span class="vol-person-count">${v.dates.length} date${v.dates.length === 1 ? '' : 's'}</span>
                </div>
            `).join('')}
        </div>`;
    }

    wrap.innerHTML = html;
}

function volunteerStatus(msg, isError) {
    const el = document.getElementById('volunteer-status');
    if (!el) return;
    el.textContent = msg || '';
    el.className = 'form-status' + (msg ? (isError ? ' error' : ' success') : '');
}

function editVolunteer(encodedName) {
    const name = decodeURIComponent(encodedName);
    const v = volunteerRota.volunteers.find(x => x.name === name);
    if (!v) return;
    document.getElementById('vol-name').value = v.name;
    document.getElementById('vol-note').value = v.note || '';
    document.querySelectorAll('.vol-date-cb').forEach(cb => {
        cb.checked = v.dates.includes(cb.value);
    });
    document.querySelector('.volunteer-form').scrollIntoView({ behavior: 'smooth', block: 'start' });
    volunteerStatus(`Editing ${v.name}'s availability — make changes and save.`, false);
}

async function saveVolunteer() {
    const name = document.getElementById('vol-name').value.trim();
    const note = document.getElementById('vol-note').value.trim();
    const dates = [...document.querySelectorAll('.vol-date-cb:checked')].map(cb => cb.value);

    if (!name) {
        volunteerStatus('Please enter your name.', true);
        return;
    }

    try {
        const res = await fetch('/api/admin/volunteers', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ name, note, dates }),
        });
        if (!res.ok) {
            const err = await res.json().catch(() => ({}));
            volunteerStatus(err.error || 'Failed to save. Please try again.', true);
            return;
        }
        volunteerRota = await res.json();
        renderVolunteerCoverage();
        // Clear the form for the next person
        document.getElementById('vol-name').value = '';
        document.getElementById('vol-note').value = '';
        document.querySelectorAll('.vol-date-cb').forEach(cb => { cb.checked = false; });
        volunteerStatus(dates.length ? `Thanks ${name}! Your availability is saved.` : `${name}'s availability has been cleared.`, false);
    } catch (e) {
        volunteerStatus('Failed to save. Please try again.', true);
    }
}

async function removeVolunteer(encodedName) {
    const name = decodeURIComponent(encodedName);
    if (!confirm(`Remove ${name} from the upcoming rota?`)) return;
    try {
        const res = await fetch('/api/admin/volunteers/remove', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ name }),
        });
        if (!res.ok) { volunteerStatus('Failed to remove. Please try again.', true); return; }
        volunteerRota = await res.json();
        renderVolunteerCoverage();
        volunteerStatus(`${name} removed from the rota.`, false);
    } catch (e) {
        volunteerStatus('Failed to remove. Please try again.', true);
    }
}

// ============================================
// HOMEPAGE ANNOUNCEMENTS (NOTIFICATIONS)
// ============================================

let announcements = [];
let editingAnnId = null;

async function loadAnnouncements() {
    const container = document.getElementById('announcement-admin-list');
    container.innerHTML = '<p class="loading">Loading announcements...</p>';
    try {
        const res = await fetch('/api/admin/announcements');
        announcements = await res.json();
        renderAnnouncementList();
    } catch (e) {
        container.innerHTML = '<p class="error-text">Failed to load announcements</p>';
    }
}

function escapeHtml(str) {
    const div = document.createElement('div');
    div.textContent = str == null ? '' : str;
    return div.innerHTML;
}

function renderAnnouncementList() {
    const container = document.getElementById('announcement-admin-list');
    if (!announcements.length) {
        container.innerHTML = '<p class="hint">No announcements yet. Add one below — it will appear in the homepage banner.</p>';
        return;
    }
    container.innerHTML = announcements.map((a, i) => {
        const linkPreview = (a.link_url && a.link_text)
            ? ` <span class="ann-link-preview">🔗 ${escapeHtml(a.link_text)}</span>`
            : '';
        return `
        <div class="ann-row">
            <div class="ann-row-main">
                <div class="ann-row-text">
                    ${a.emoji ? `<span class="ann-emoji">${escapeHtml(a.emoji)}</span> ` : ''}
                    <strong>${escapeHtml(a.headline)}</strong>
                    ${a.details ? ` ${escapeHtml(a.details)}` : ''}
                    ${linkPreview}
                </div>
            </div>
            <div class="ann-row-actions">
                <button class="btn btn-secondary btn-small" onclick="moveAnnouncement(${i}, -1)" ${i === 0 ? 'disabled' : ''} aria-label="Move up">↑</button>
                <button class="btn btn-secondary btn-small" onclick="moveAnnouncement(${i}, 1)" ${i === announcements.length - 1 ? 'disabled' : ''} aria-label="Move down">↓</button>
                <button class="btn btn-secondary btn-small" onclick="editAnnouncement(${i})">Edit</button>
                <button class="btn btn-danger btn-small" onclick="deleteAnnouncement(${i})">Delete</button>
            </div>
        </div>`;
    }).join('');
}

function announcementStatus(msg, isError) {
    const el = document.getElementById('announcement-status');
    if (!el) return;
    el.textContent = msg || '';
    el.className = 'form-status' + (msg ? (isError ? ' error' : ' success') : '');
}

function readAnnouncementForm() {
    return {
        emoji: document.getElementById('ann-emoji').value.trim(),
        headline: document.getElementById('ann-headline').value.trim(),
        details: document.getElementById('ann-details').value.trim(),
        link_url: document.getElementById('ann-link-url').value.trim(),
        link_text: document.getElementById('ann-link-text').value.trim(),
    };
}

function resetAnnouncementForm() {
    editingAnnId = null;
    document.getElementById('ann-emoji').value = '';
    document.getElementById('ann-headline').value = '';
    document.getElementById('ann-details').value = '';
    document.getElementById('ann-link-url').value = '';
    document.getElementById('ann-link-text').value = '';
    document.getElementById('announcement-form-title').textContent = 'Add Announcement';
    document.getElementById('ann-save-btn').textContent = 'Add Announcement';
    document.getElementById('ann-cancel-btn').style.display = 'none';
}

function cancelAnnouncementEdit() {
    resetAnnouncementForm();
    announcementStatus('');
}

async function saveAnnouncement() {
    const item = readAnnouncementForm();
    if (!item.headline && !item.details && !item.emoji) {
        announcementStatus('Please add at least a headline.', true);
        return;
    }
    if ((item.link_url && !item.link_text) || (!item.link_url && item.link_text)) {
        announcementStatus('A link needs BOTH a URL and link text (or leave both blank).', true);
        return;
    }

    if (editingAnnId !== null) {
        announcements[editingAnnId] = item;
    } else {
        announcements.push(item);
    }
    await persistAnnouncements(editingAnnId !== null ? 'Announcement updated.' : 'Announcement added.');
    resetAnnouncementForm();
}

function editAnnouncement(index) {
    const a = announcements[index];
    editingAnnId = index;
    document.getElementById('ann-emoji').value = a.emoji || '';
    document.getElementById('ann-headline').value = a.headline || '';
    document.getElementById('ann-details').value = a.details || '';
    document.getElementById('ann-link-url').value = a.link_url || '';
    document.getElementById('ann-link-text').value = a.link_text || '';
    document.getElementById('announcement-form-title').textContent = 'Edit Announcement';
    document.getElementById('ann-save-btn').textContent = 'Save Changes';
    document.getElementById('ann-cancel-btn').style.display = '';
    document.getElementById('ann-headline').focus();
    document.getElementById('announcement-form-title').scrollIntoView({ behavior: 'smooth', block: 'center' });
}

async function deleteAnnouncement(index) {
    const a = announcements[index];
    const label = a.headline || a.details || 'this announcement';
    if (!confirm(`Delete "${label}"? This removes it from the homepage straight away.`)) return;
    announcements.splice(index, 1);
    if (editingAnnId !== null) resetAnnouncementForm();
    await persistAnnouncements('Announcement deleted.');
}

async function moveAnnouncement(index, dir) {
    const target = index + dir;
    if (target < 0 || target >= announcements.length) return;
    const tmp = announcements[index];
    announcements[index] = announcements[target];
    announcements[target] = tmp;
    await persistAnnouncements('Order updated.');
}

async function persistAnnouncements(successMsg) {
    try {
        const res = await fetch('/api/admin/announcements', {
            method: 'PUT',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ announcements }),
        });
        if (!res.ok) {
            const err = await res.json().catch(() => ({}));
            announcementStatus(err.error || 'Failed to save. Please try again.', true);
            await loadAnnouncements();
            return;
        }
        announcements = await res.json();
        renderAnnouncementList();
        announcementStatus(successMsg || 'Saved.', false);
    } catch (e) {
        announcementStatus('Failed to save. Please try again.', true);
    }
}

// ============================================
// ROOMS MANAGEMENT
// ============================================

async function loadRooms() {
    const container = document.getElementById('admin-room-list');
    container.innerHTML = '<p class="loading">Loading rooms...</p>';
    
    try {
        const response = await fetch('/api/admin/rooms');
        const rooms = await response.json();
        renderRooms(rooms);
    } catch (error) {
        container.innerHTML = '<p class="error-text">Failed to load rooms</p>';
    }
}

function renderRooms(rooms) {
    const container = document.getElementById('admin-room-list');
    
    if (rooms.length === 0) {
        container.innerHTML = '<p>No rooms configured</p>';
        return;
    }
    
    container.innerHTML = rooms.map(room => {
        const typeLabel = room.room_type === 'open' ? '📋 Open Booking' : '⏰ Time Slots';
        return `
        <div class="room-item ${room.is_active ? '' : 'inactive'}">
            <div class="room-item-info">
                <h4>${escapeHtml(room.name)} ${!room.is_active ? '<span class="badge">(Inactive)</span>' : ''}</h4>
                <p>${escapeHtml(room.building_location)}</p>
                <small class="room-type-label">${typeLabel}</small>
            </div>
            <div class="room-item-actions">
                <button class="btn btn-small btn-secondary" onclick="editRoom(${room.id}, '${escapeHtml(room.name)}', '${escapeHtml(room.building_location)}', '${room.room_type}', ${room.is_active})">Edit</button>
                <button class="btn btn-small btn-danger" onclick="deleteRoom(${room.id})">Delete</button>
            </div>
        </div>
    `}).join('');
}

async function addRoom() {
    const nameInput = document.getElementById('new-room-name');
    const locationInput = document.getElementById('new-room-location');
    const typeInput = document.getElementById('new-room-type');
    
    const name = nameInput.value.trim();
    const location = locationInput.value.trim();
    const roomType = typeInput.value;
    
    if (!name) {
        alert('Please enter a room name');
        return;
    }
    
    try {
        const response = await fetch('/api/admin/rooms', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                name: name,
                building_location: location,
                room_type: roomType,
                is_active: true
            })
        });
        
        if (response.ok) {
            nameInput.value = '';
            locationInput.value = '';
            typeInput.value = 'slot';
            loadRooms();
        } else {
            alert('Failed to add room');
        }
    } catch (error) {
        alert('Network error');
    }
}

async function editRoom(id, currentName, currentLocation, currentType, currentActive) {
    const name = prompt('Room name:', currentName);
    if (name === null) return;
    
    const location = prompt('Building location:', currentLocation);
    if (location === null) return;
    
    const typeOptions = currentType === 'open' 
        ? 'Select room type:\n1. Time Slot (30 min slots)\n2. Open Booking (11am - 4pm)\n\nEnter 1 or 2:'
        : 'Select room type:\n1. Time Slot (30 min slots) [current]\n2. Open Booking (11am - 4pm)\n\nEnter 1 or 2:';
    const typeChoice = prompt(typeOptions, currentType === 'open' ? '2' : '1');
    if (typeChoice === null) return;
    
    const roomType = typeChoice === '2' ? 'open' : 'slot';
    const isActive = confirm('Is this room active? (OK = Yes, Cancel = No)');
    
    try {
        const response = await fetch(`/api/admin/rooms/${id}`, {
            method: 'PUT',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                name: name || currentName,
                building_location: location || currentLocation,
                room_type: roomType,
                is_active: isActive
            })
        });
        
        if (response.ok) {
            loadRooms();
        } else {
            alert('Failed to update room');
        }
    } catch (error) {
        alert('Network error');
    }
}

async function deleteRoom(id) {
    if (!confirm('Are you sure you want to delete this room?')) return;
    
    try {
        const response = await fetch(`/api/admin/rooms/${id}`, {
            method: 'DELETE'
        });
        
        if (response.ok) {
            loadRooms();
        } else {
            alert('Failed to delete room');
        }
    } catch (error) {
        alert('Network error');
    }
}

// ============================================
// MESSAGE TEMPLATE
// ============================================

const DEFAULT_TEMPLATE = `Dear {{email}},

Your booking has been confirmed!

Room: {{room_name}}
Location: {{building_location}}
Date: {{date}}
Time: {{start_time}} - {{end_time}}

Thank you for using our booking system.

To cancel your booking, visit:
{{cancel_url}}
`;

async function loadMessageTemplate() {
    const textarea = document.getElementById('confirmation-template');
    
    try {
        const response = await fetch('/api/admin/settings');
        const settings = await response.json();
        textarea.value = settings.confirmation_message || DEFAULT_TEMPLATE;
    } catch (error) {
        textarea.value = DEFAULT_TEMPLATE;
    }
}

async function saveMessageTemplate() {
    const template = document.getElementById('confirmation-template').value;
    
    try {
        const response = await fetch('/api/admin/settings', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ confirmation_message: template })
        });
        
        if (response.ok) {
            alert('Template saved successfully');
        } else {
            alert('Failed to save template');
        }
    } catch (error) {
        alert('Network error');
    }
}

function resetMessageTemplate() {
    if (confirm('Reset to default template?')) {
        document.getElementById('confirmation-template').value = DEFAULT_TEMPLATE;
    }
}

// ============================================
// ALL BOOKINGS
// ============================================

async function loadAllBookings() {
    const container = document.getElementById('bookings-by-date');
    container.innerHTML = '<p class="loading">Loading bookings...</p>';
    
    // Load both bookings and counts in parallel
    try {
        const [bookingsResponse, countsResponse] = await Promise.all([
            fetch('/api/admin/bookings'),
            fetch('/api/admin/booking-counts')
        ]);
        
        const bookings = await bookingsResponse.json();
        const counts = await countsResponse.json();
        
        renderBookingsByDate(bookings);
        renderBookingCounts(counts);
    } catch (error) {
        container.innerHTML = '<p class="error-text">Failed to load bookings</p>';
    }
}

async function loadArchivedBookings() {
    const container = document.getElementById('archive-bookings');
    container.innerHTML = '<p class="loading">Loading archived bookings...</p>';
    
    try {
        const response = await fetch('/api/admin/bookings/archive');
        const bookings = await response.json();
        
        renderArchivedBookings(bookings);
    } catch (error) {
        container.innerHTML = '<p class="error-text">Failed to load archived bookings</p>';
    }
}

function renderArchivedBookings(bookings) {
    const container = document.getElementById('archive-bookings');
    
    if (bookings.length === 0) {
        container.innerHTML = '<p class="no-bookings">No archived bookings found.</p>';
        return;
    }
    
    // Group bookings by date
    const byDate = {};
    bookings.forEach(booking => {
        if (!byDate[booking.date]) {
            byDate[booking.date] = {
                display: booking.date_display,
                bookings: []
            };
        }
        byDate[booking.date].bookings.push(booking);
    });
    
    // Sort dates (most recent first for archive)
    const sortedDates = Object.keys(byDate).sort().reverse();
    
    container.innerHTML = sortedDates.map((date, index) => {
        const dateData = byDate[date];
        const isExpanded = index === 0 ? 'expanded' : ''; // First date expanded by default
        
        return `
            <div class="date-booking-group ${isExpanded} archive">
                <div class="date-header" onclick="toggleDateGroup(this)">
                    <span class="toggle-icon">${isExpanded ? '▼' : '▶'}</span>
                    <h4>${escapeHtml(dateData.display)}</h4>
                    <span class="booking-count">(${dateData.bookings.length} booking${dateData.bookings.length !== 1 ? 's' : ''})</span>
                </div>
                <div class="date-bookings">
                    ${dateData.bookings.map(booking => `
                        <div class="booking-row">
                            <div class="booking-info">
                                <span class="room-name">${escapeHtml(booking.room_name)}</span>
                                <span class="booking-time">${escapeHtml(booking.start_time)} - ${escapeHtml(booking.end_time)}</span>
                            </div>
                            <div class="booking-user">
                                <span class="user-name">${escapeHtml(booking.user_name)}</span>
                                <span class="user-email">${escapeHtml(booking.user_email)}</span>
                            </div>
                        </div>
                    `).join('')}
                </div>
            </div>
        `;
    }).join('');
}

function renderBookingCounts(counts) {
    const container = document.getElementById('booking-counts');
    
    if (counts.length === 0) {
        container.innerHTML = '<p>No upcoming bookings</p>';
        return;
    }
    
    // Group by date
    const byDate = {};
    counts.forEach(item => {
        if (!byDate[item.date]) {
            byDate[item.date] = [];
        }
        byDate[item.date].push(item);
    });
    
    container.innerHTML = Object.keys(byDate).sort().map(date => {
        const dateItems = byDate[date];
        const total = dateItems.reduce((sum, item) => sum + item.count, 0);
        
        return `
            <div class="booking-count-date">
                <h4>${escapeHtml(dateItems[0].date_display)} <span class="total-count">(${total} total)</span></h4>
                <div class="room-counts">
                    ${dateItems.map(item => `
                        <span class="room-count-badge">
                            ${escapeHtml(item.room_name)}: <strong>${item.count}</strong>
                        </span>
                    `).join('')}
                </div>
            </div>
        `;
    }).join('');
}

function renderBookingsByDate(bookings) {
    const container = document.getElementById('bookings-by-date');
    
    if (bookings.length === 0) {
        container.innerHTML = '<p class="no-bookings">No upcoming bookings</p>';
        return;
    }
    
    // Group bookings by date
    const byDate = {};
    bookings.forEach(booking => {
        if (!byDate[booking.date]) {
            byDate[booking.date] = {
                display: booking.date_display,
                bookings: []
            };
        }
        byDate[booking.date].bookings.push(booking);
    });
    
    // Sort dates
    const sortedDates = Object.keys(byDate).sort();
    
    container.innerHTML = sortedDates.map((date, index) => {
        const dateData = byDate[date];
        const isExpanded = index === 0 ? 'expanded' : ''; // First date expanded by default
        
        return `
            <div class="date-booking-group ${isExpanded}">
                <div class="date-header" onclick="toggleDateGroup(this)">
                    <span class="toggle-icon">${isExpanded ? '▼' : '▶'}</span>
                    <h4>${escapeHtml(dateData.display)}</h4>
                    <span class="booking-count">(${dateData.bookings.length} booking${dateData.bookings.length !== 1 ? 's' : ''})</span>
                </div>
                <div class="date-bookings">
                    ${dateData.bookings.map(booking => `
                        <div class="booking-row">
                            <div class="booking-info">
                                <span class="room-name">${escapeHtml(booking.room_name)}</span>
                                <span class="booking-time">${escapeHtml(booking.start_time)} - ${escapeHtml(booking.end_time)}</span>
                            </div>
                            <div class="booking-user">
                                <span class="user-name">${escapeHtml(booking.user_name)}</span>
                                <span class="user-email">${escapeHtml(booking.user_email)}</span>
                            </div>
                            <button class="btn btn-small btn-danger" onclick="deleteBooking(${booking.id})">Delete</button>
                        </div>
                    `).join('')}
                </div>
            </div>
        `;
    }).join('');
}

function toggleDateGroup(header) {
    const group = header.parentElement;
    const isExpanded = group.classList.contains('expanded');
    
    if (isExpanded) {
        group.classList.remove('expanded');
        header.querySelector('.toggle-icon').textContent = '▶';
    } else {
        group.classList.add('expanded');
        header.querySelector('.toggle-icon').textContent = '▼';
    }
}

// ============================================
// AVAILABILITY EMAIL BLAST
// ============================================

let emailBlastRecipients = [];
let emailBlastDate = null;

async function loadEmailBlastDates() {
    const container = document.getElementById('email-blast-dates');
    container.innerHTML = '<p class="loading">Loading dates...</p>';

    try {
        const [fridaysRes, statusRes] = await Promise.all([
            fetch('/api/fridays'),
            fetch('/api/admin/availability-email-status')
        ]);
        const fridays = await fridaysRes.json();
        const sentStatus = await statusRes.json();

        if (fridays.length === 0) {
            container.innerHTML = '<p>No upcoming Fridays are scheduled.</p>';
            return;
        }

        container.innerHTML = fridays.map(friday => {
            const sent = sentStatus[friday.date];
            if (sent) {
                const countText = (sent.count != null)
                    ? ` to ${sent.count} recipient${sent.count !== 1 ? 's' : ''}`
                    : '';
                const whenText = sent.sent_at_display ? ` on ${escapeHtml(sent.sent_at_display)}` : '';
                return `
                    <div class="email-date-row sent">
                        <span class="email-date-label">${escapeHtml(friday.display)}</span>
                        <span class="email-sent-badge">✅ Sent${whenText}${countText}</span>
                    </div>
                `;
            }
            return `
                <div class="email-date-row">
                    <span class="email-date-label">${escapeHtml(friday.display)}</span>
                    <button class="btn btn-primary btn-small" onclick="openEmailBlast('${friday.date}')">📧 Draft Email</button>
                </div>
            `;
        }).join('');
    } catch (error) {
        container.innerHTML = '<p class="error-text">Failed to load dates</p>';
    }
}

async function openEmailBlast(date) {
    try {
        const response = await fetch(`/api/admin/availability-email-draft/${date}`);
        const draft = await response.json();

        if (response.status === 409 && draft.error === 'already_sent') {
            const when = draft.sent && draft.sent.sent_at_display ? ` on ${draft.sent.sent_at_display}` : '';
            alert(`An availability email for this Friday has already been sent${when}. It can only be sent once per date.`);
            loadEmailBlastDates();
            return;
        }

        if (!response.ok) {
            alert(draft.error || 'Failed to draft email');
            return;
        }

        emailBlastDate = date;

        document.getElementById('email-blast-date-label').textContent =
            `Availability email for ${draft.date_display}. Review and edit before sending.`;
        document.getElementById('email-blast-subject').value = draft.subject;
        document.getElementById('email-blast-body').value = draft.body;

        emailBlastRecipients = draft.recipients;
        renderRecipients();

        const statusEl = document.getElementById('email-blast-status');
        statusEl.className = 'form-status';
        statusEl.textContent = '';

        document.getElementById('email-blast-modal').hidden = false;
        document.body.style.overflow = 'hidden';
    } catch (error) {
        alert('Network error. Please try again.');
    }
}

function closeEmailBlast() {
    document.getElementById('email-blast-modal').hidden = true;
    document.body.style.overflow = '';
}

function renderRecipients() {
    const chips = document.getElementById('recipient-chips');
    const count = document.getElementById('recipient-count');

    count.textContent = `(${emailBlastRecipients.length})`;

    if (emailBlastRecipients.length === 0) {
        chips.innerHTML = '<p class="hint">No recipients — add at least one email below.</p>';
        return;
    }

    chips.innerHTML = emailBlastRecipients.map((email, i) => `
        <span class="recipient-chip">
            ${escapeHtml(email)}
            <button type="button" class="chip-remove" onclick="removeRecipient(${i})" aria-label="Remove ${escapeHtml(email)}">&times;</button>
        </span>
    `).join('');
}

function removeRecipient(index) {
    emailBlastRecipients.splice(index, 1);
    renderRecipients();
}

function addRecipient() {
    const input = document.getElementById('new-recipient-email');
    const email = input.value.trim().toLowerCase();

    if (!email || !email.includes('@')) {
        alert('Please enter a valid email address');
        return;
    }
    if (emailBlastRecipients.includes(email)) {
        alert('That email is already in the recipient list');
        return;
    }

    emailBlastRecipients.push(email);
    input.value = '';
    renderRecipients();
}

async function sendEmailBlast() {
    const subject = document.getElementById('email-blast-subject').value.trim();
    const body = document.getElementById('email-blast-body').value.trim();
    const statusEl = document.getElementById('email-blast-status');
    const sendBtn = document.getElementById('send-email-blast-btn');

    if (!subject || !body) {
        alert('Subject and message are both required');
        return;
    }
    if (emailBlastRecipients.length === 0) {
        alert('Please add at least one recipient');
        return;
    }

    if (!confirm(`Send this email to ${emailBlastRecipients.length} recipient${emailBlastRecipients.length !== 1 ? 's' : ''}?`)) {
        return;
    }

    sendBtn.disabled = true;
    sendBtn.textContent = 'Sending…';
    statusEl.className = 'form-status';
    statusEl.textContent = '';

    try {
        const response = await fetch('/api/admin/availability-email/send', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                subject: subject,
                body: body,
                recipients: emailBlastRecipients,
                date: emailBlastDate
            })
        });

        const result = await response.json();

        if (response.ok) {
            statusEl.className = 'form-status success';
            statusEl.textContent = `✅ Email sent to ${result.sent_to} recipient${result.sent_to !== 1 ? 's' : ''}.`;
            setTimeout(() => { closeEmailBlast(); loadEmailBlastDates(); }, 2500);
        } else {
            statusEl.className = 'form-status error';
            statusEl.textContent = result.error || 'Failed to send email';
            // If it was already sent (e.g. another admin just did it), refresh the list
            if (result.already_sent) {
                setTimeout(() => { closeEmailBlast(); loadEmailBlastDates(); }, 2500);
            }
        }
    } catch (error) {
        statusEl.className = 'form-status error';
        statusEl.textContent = 'Network error. Please try again.';
    } finally {
        sendBtn.disabled = false;
        sendBtn.textContent = 'Send Email';
    }
}

// ============================================
// UTILITIES
// ============================================

function escapeHtml(text) {
    if (!text) return '';
    const div = document.createElement('div');
    div.textContent = text;
    return div.innerHTML;
}

// ============================================
// DELETE BOOKING
// ============================================

async function deleteBooking(bookingId) {
    if (!confirm('Are you sure you want to delete this booking?\n\nThe user will be notified by email that their booking has been cancelled.')) {
        return;
    }
    
    try {
        const response = await fetch(`/api/admin/bookings/${bookingId}`, {
            method: 'DELETE'
        });
        
        const result = await response.json();
        
        if (response.ok) {
            alert('Booking deleted successfully. The user has been notified by email.');
            loadAllBookings(); // Refresh the list
        } else {
            alert(result.error || 'Failed to delete booking');
        }
    } catch (error) {
        alert('Network error. Please try again.');
    }
}

// Load rooms on page load
document.addEventListener('DOMContentLoaded', () => {
    loadRooms();
});
