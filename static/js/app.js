/**
 * Room Booking System - Main Application JavaScript
 */

// State
let state = {
    rooms: [],
    fridays: [],
    timeSlots: [],
    yogaSessions: {},   // date -> yoga session info, so yoga shows as an option
    bookingType: 'room',  // 'room' or 'yoga' — yoga is booked through the same flow
    selectedYoga: null,
    selectedRoom: null,
    selectedDate: null,
    selectedSlots: [],
    availability: [],
    isDragging: false,
    dragStart: null
};

// DOM Elements
const elements = {
    roomGrid: document.getElementById('room-grid'),
    dateGrid: document.getElementById('date-grid'),
    timeSlots: document.getElementById('time-slots'),
    selectionInfo: document.getElementById('selection-info'),
    btnContinue: document.getElementById('btn-continue'),
    bookingSummary: document.getElementById('booking-summary'),
    firstNameInput: document.getElementById('first-name'),
    lastNameInput: document.getElementById('last-name'),
    emailInput: document.getElementById('email'),
    confirmationMessage: document.getElementById('confirmation-message'),
    myBookingsList: document.getElementById('my-bookings-list')
};

// Step navigation
const steps = {
    room: document.getElementById('step-room'),
    date: document.getElementById('step-date'),
    time: document.getElementById('step-time'),
    email: document.getElementById('step-email'),
    confirmation: document.getElementById('step-confirmation')
};

// ============================================
// INITIALIZATION
// ============================================

document.addEventListener('DOMContentLoaded', async () => {
    loadTimeSlots();
    await Promise.all([loadFridays(), loadYogaSessions()]);
    mergeYogaDatesIntoFridays();
    renderDates();

    // Check for email in URL (coming from cancel page)
    checkUrlForEmail();
});

// Yoga sometimes runs on a Friday with no rooms scheduled (September 2026 is
// exactly that). Those dates must still appear in Step 1, or yoga would be
// unbookable now that it is booked through this flow.
function mergeYogaDatesIntoFridays() {
    const known = new Set(state.fridays.map(f => f.date));
    Object.values(state.yogaSessions).forEach(s => {
        if (known.has(s.date)) return;
        const [y, m, d] = s.date.split('-').map(Number);
        state.fridays.push({
            date: s.date,
            // Match the server's "Friday, September 04, 2026" format
            display: new Date(y, m - 1, d).toLocaleDateString('en-US', {
                weekday: 'long', year: 'numeric', month: 'long', day: '2-digit'
            }),
            yoga_only: true
        });
    });
    state.fridays.sort((a, b) => a.date.localeCompare(b.date));
}

// Yoga sessions by date, so yoga can be offered alongside the rooms
async function loadYogaSessions() {
    try {
        const response = await fetch('/api/yoga/availability');
        const sessions = await response.json();
        state.yogaSessions = {};
        sessions.forEach(s => { state.yogaSessions[s.date] = s; });
    } catch (error) {
        console.error('Failed to load yoga sessions:', error);
    }
}

function checkUrlForEmail() {
    const urlParams = new URLSearchParams(window.location.search);
    const email = urlParams.get('email');
    
    if (email) {
        // Pre-fill the email field
        const myBookingsEmail = document.getElementById('my-bookings-email');
        if (myBookingsEmail) {
            myBookingsEmail.value = email;
            // Auto-load the bookings
            loadMyBookings();
            
            // Scroll to my bookings section if hash is present
            if (window.location.hash === '#my-bookings') {
                setTimeout(() => {
                    document.querySelector('.my-bookings-section').scrollIntoView({ behavior: 'smooth' });
                }, 500);
            }
        }
        
        // Clean up the URL
        window.history.replaceState({}, document.title, window.location.pathname);
    }
}

// ============================================
// DATA LOADING
// ============================================

async function loadRooms(date = null) {
    try {
        const url = date ? `/api/rooms?date=${date}` : '/api/rooms';
        const response = await fetch(url);
        state.rooms = await response.json();
        renderRooms();
    } catch (error) {
        elements.roomGrid.innerHTML = '<p class="error-text">Failed to load rooms</p>';
    }
}

async function loadFridays(roomId = null) {
    try {
        const url = roomId ? `/api/fridays?room_id=${roomId}` : '/api/fridays';
        const response = await fetch(url);
        state.fridays = await response.json();
    } catch (error) {
        console.error('Failed to load fridays:', error);
    }
}

async function loadTimeSlots() {
    try {
        const response = await fetch('/api/slots');
        state.timeSlots = await response.json();
    } catch (error) {
        console.error('Failed to load time slots:', error);
    }
}

async function loadAvailability() {
    if (!state.selectedRoom || !state.selectedDate) return;
    
    elements.timeSlots.innerHTML = '<p class="loading">Loading availability...</p>';
    
    try {
        const response = await fetch(`/api/availability/${state.selectedDate}/${state.selectedRoom.id}`);
        state.availability = await response.json();
        renderTimeSlots();
    } catch (error) {
        elements.timeSlots.innerHTML = '<p class="error-text">Failed to load availability</p>';
    }
}

// ============================================
// RENDERING
// ============================================

function getRoomPhotoUrl(room) {
    const nameLower = room.name.toLowerCase();
    if (nameLower.includes('indigo') || nameLower.includes('4.2')) {
        return 'https://drive.google.com/thumbnail?id=1OAEDuaKUkZZMcmqeJcTKES_yfVrqkEBk&sz=w800';
    }
    if (nameLower.includes('rose') || nameLower.includes('4.4')) {
        return 'https://drive.google.com/thumbnail?id=1otwHG2nTYJk91a5wL02BSKQRO_nVYCA9&sz=w800';
    }
    if (nameLower.includes('clerkenwell') || nameLower.includes('4.7')) {
        return 'https://drive.google.com/thumbnail?id=1K44nSq3Wc-kOW4yU0WLkubhqcJUcnjRp&sz=w800';
    }
    if (nameLower.includes('loft')) {
        return 'https://drive.google.com/thumbnail?id=1tNkNIfCdPPyWiZQeV3ROF1YaQNwmo1fL&sz=w800';
    }
    if (nameLower.includes('farringdon') || nameLower.includes('4.6')) {
        return '/static/images/room-4-6-farringdon.jpg';
    }
    return '';
}

function renderRooms() {
    // Show which Friday these options are for
    const dateLabel = document.getElementById('room-step-date-label');
    if (dateLabel) {
        const dateDisplay = state.fridays.find(f => f.date === state.selectedDate)?.display;
        dateLabel.textContent = dateDisplay ? `Available on ${dateDisplay}:` : '';
    }
    const stepHeading = document.querySelector('#step-room h2');
    if (stepHeading) stepHeading.textContent = 'Step 2: Choose what you\'d like to book';

    // Note: don't bail out when there are no rooms — some Fridays have yoga
    // only, and the yoga card still needs to render below.

    // Add a special card for Peer Support Sessions
    const peerSupportCard = `
        <div class="room-card peer-support-room" onclick="selectPeerSupport()">
            <h3>🎓 Peer Support Sessions for Autistic University Students</h3>
            <p>Online or in-person (Room 4.4 "Rose")</p>
            <small class="room-hint">30 min sessions – Click for details</small>
        </div>
    `;

    const roomCards = state.rooms.map(room => {
        const typeBadge = room.room_type === 'open'
            ? '<span class="room-type-badge open">Open Booking</span>'
            : '<span class="room-type-badge slot">Time Slots</span>';
        const openHours = (room.override_start && room.override_end)
            ? `${room.override_start} - ${room.override_end}`
            : '9:30am - 5pm';
        const typeHint = room.room_type === 'open'
            ? `<small class="room-hint">${escapeHtml(openHours)}</small>`
            : '<small class="room-hint">30 min slots</small>';
        const photoUrl = getRoomPhotoUrl(room);
        const photoHtml = photoUrl
            ? `<div class="room-card-image"><img src="${escapeHtml(photoUrl)}" alt="${escapeHtml(room.name)}" loading="lazy"></div>`
            : '';

        // For shared open rooms, show how many people have booked so far
        let occupancyHtml = '';
        if (room.room_type === 'open' && typeof room.booking_count === 'number') {
            const count = room.booking_count;
            const label = count === 0
                ? '👥 No one booked yet — be the first!'
                : `👥 ${count} ${count === 1 ? 'person has' : 'people have'} booked this space so far`;
            occupancyHtml = `<p class="room-occupancy">${label}</p>`;
        }

        // Anything the team has flagged for this room on this date — shown
        // before the person picks the room, not just after booking
        const noteHtml = room.note
            ? `<p class="room-note">⚠️ ${escapeHtml(room.note)}</p>`
            : '';

        return `
        <div class="room-card${room.note ? ' has-note' : ''}" onclick="selectRoom(${room.id})">
            ${photoHtml}
            <h3>${escapeHtml(room.name)} ${typeBadge}</h3>
            <p>${escapeHtml(room.building_location)}</p>
            ${noteHtml}
            ${occupancyHtml}
            ${typeHint}
        </div>
    `}).join('');

    // If yoga is running on this Friday, offer it alongside the rooms.
    // Clicking goes to the yoga page's registration form.
    let yogaCard = '';
    const yoga = state.yogaSessions[state.selectedDate];
    if (yoga) {
        const placesLabel = yoga.full
            ? '<span class="room-type-badge yoga-full">FULL</span>'
            : `<span class="room-type-badge yoga">${yoga.remaining} place${yoga.remaining === 1 ? '' : 's'} left</span>`;
        // Yoga is booked through this same flow — picking it here leads to the
        // yoga questions at Step 4, rather than sending people to another page.
        yogaCard = `
        <div class="room-card yoga-room-card${yoga.full ? ' room-card-full' : ''}"
             ${yoga.full ? '' : 'onclick="selectYoga()"'}>
            <div class="room-card-image"><img src="/static/images/yoga-terrace-1.jpg" alt="Gentle yoga on the outdoor terrace" loading="lazy"></div>
            <h3>🧘 Gentle Yoga with Marlijn ${placesLabel}</h3>
            <p>Outdoor terrace — session starts at ${escapeHtml(yoga.time)}</p>
            <small class="room-hint">${yoga.full
                ? 'This session is full — please choose another Friday'
                : 'Gentle, neurodivergent-friendly — click to register'}</small>
        </div>
        `;
    }

    // Peer support is only relevant on days a room is actually open
    const cards = roomCards + yogaCard + (state.rooms.length ? peerSupportCard : '');
    elements.roomGrid.innerHTML = cards ||
        '<p>Nothing is available to book on this date.</p>';
}

function renderDates() {
    if (!state.fridays.length) {
        elements.dateGrid.innerHTML = `
            <div class="no-dates-message">
                <p>📅 There are no Friday sessions open for booking at the moment.</p>
                <p>Please check back soon — new dates are added regularly.</p>
            </div>`;
        return;
    }
    elements.dateGrid.innerHTML = state.fridays.map(friday => {
        return `
        <div class="date-card" onclick="selectDate('${friday.date}')">
            ${escapeHtml(friday.display)}
        </div>
    `}).join('');
}

function renderTimeSlots() {
    // Add instructions at the top
    const instructions = document.createElement('div');
    instructions.className = 'selection-instructions';
    instructions.innerHTML = `
        <div class="instruction-box">
            <h4>📋 How to select time slots:</h4>
            <ul>
                <li><strong>Click individually:</strong> Click on available slots one by one to build your booking</li>
                <li><strong>Drag to select:</strong> Click and hold on a slot, then drag to another slot to select a range</li>
                <li><strong>Max duration:</strong> You can book up to 3 hours (6 slots)</li>
                <li><strong>Consecutive only:</strong> All selected slots must be next to each other (no gaps)</li>
            </ul>
        </div>
    `;
    
    elements.timeSlots.innerHTML = '';
    elements.timeSlots.appendChild(instructions);
    
    const slotsContainer = document.createElement('div');
    slotsContainer.className = 'time-slots-grid';
    slotsContainer.id = 'slots-grid';
    
    slotsContainer.innerHTML = state.availability.map(slot => {
        const isSelected = state.selectedSlots.includes(slot.index);
        const isBooked = !slot.available;
        
        return `
            <div class="time-slot ${isSelected ? 'selected' : ''} ${isBooked ? 'booked' : ''}"
                 data-index="${slot.index}"
                 onmousedown="slotMouseDown(${slot.index}, event)"
                 onmouseenter="slotMouseEnter(${slot.index})"
                 onmouseup="slotMouseUp(event)">
                ${escapeHtml(slot.display)}
            </div>
        `;
    }).join('');
    
    elements.timeSlots.appendChild(slotsContainer);
    updateSelectionInfo();
}

// Track drag state
let dragState = {
    isDragging: false,
    hasMoved: false,
    startIndex: null,
    startX: 0,
    startY: 0
};

function slotClick(index) {
    const slot = state.availability.find(s => s.index === index);
    if (!slot || !slot.available) return;
    
    // Check if already selected
    const existingIndex = state.selectedSlots.indexOf(index);
    
    if (existingIndex > -1) {
        // Deselect this slot
        state.selectedSlots.splice(existingIndex, 1);
    } else {
        // Add to selection
        if (state.selectedSlots.length === 0) {
            state.selectedSlots.push(index);
        } else {
            // Check if this would create a valid consecutive selection
            const testSelection = [...state.selectedSlots, index].sort((a, b) => a - b);
            const isConsecutive = testSelection.every((s, i) => {
                if (i === 0) return true;
                return s === testSelection[i - 1] + 1;
            });
            
            if (isConsecutive) {
                state.selectedSlots.push(index);
                state.selectedSlots.sort((a, b) => a - b);
            } else {
                elements.selectionInfo.innerHTML = '<span class="error-text">⚠️ Cannot select this slot - it would create a gap. Please select consecutive slots.</span>';
                setTimeout(() => updateSelectionInfo(), 2000);
                return;
            }
        }
    }
    
    renderTimeSlots();
    updateSelectionInfo();
}

function slotMouseDown(index, event) {
    const slot = state.availability.find(s => s.index === index);
    if (!slot || !slot.available) return;
    
    dragState.isDragging = true;
    dragState.hasMoved = false;
    dragState.startIndex = index;
    dragState.startX = event.clientX;
    dragState.startY = event.clientY;
}

function slotMouseEnter(index) {
    if (!dragState.isDragging || dragState.startIndex === null) return;
    
    dragState.hasMoved = true;
    
    const start = Math.min(dragState.startIndex, index);
    const end = Math.max(dragState.startIndex, index);
    
    state.selectedSlots = [];
    for (let i = start; i <= end; i++) {
        const slot = state.availability.find(s => s.index === i);
        if (slot && slot.available) {
            state.selectedSlots.push(i);
        }
    }
    
    renderTimeSlots();
}

function slotMouseUp(event) {
    if (!dragState.isDragging) return;
    
    // Check if we actually dragged or just clicked
    const distMoved = Math.abs(event.clientX - dragState.startX) + Math.abs(event.clientY - dragState.startY);
    
    if (!dragState.hasMoved && distMoved < 5) {
        // This was a click, not a drag - process as click
        slotClick(dragState.startIndex);
    }
    
    dragState.isDragging = false;
    dragState.hasMoved = false;
    dragState.startIndex = null;
    updateSelectionInfo();
}

// Global mouseup to catch releases outside slots
document.addEventListener('mouseup', (e) => {
    if (dragState.isDragging) {
        slotMouseUp(e);
    }
});

// Prevent text selection while dragging
document.addEventListener('selectstart', (e) => {
    if (dragState.isDragging) e.preventDefault();
});

function updateSelectionInfo() {
    if (state.selectedSlots.length === 0) {
        elements.selectionInfo.innerHTML = '<span class="hint">Select time slots using the options above</span>';
        elements.btnContinue.classList.add('hidden');
        return;
    }
    
    const sortedSlots = [...state.selectedSlots].sort((a, b) => a - b);
    const startSlot = sortedSlots[0];
    const endSlot = sortedSlots[sortedSlots.length - 1];
    const numSlots = endSlot - startSlot + 1;
    const hours = (numSlots * 30) / 60;
    
    // Check if selection is consecutive
    const isConsecutive = sortedSlots.every((slot, i) => {
        if (i === 0) return true;
        return slot === sortedSlots[i - 1] + 1;
    });
    
    if (!isConsecutive) {
        elements.selectionInfo.innerHTML = '<span class="error-text">⚠️ Please select consecutive time slots only (no gaps allowed)</span>';
        elements.btnContinue.classList.add('hidden');
        return;
    }
    
    if (numSlots > 6) {
        elements.selectionInfo.innerHTML = '<span class="error-text">⚠️ Maximum booking is 3 hours (6 slots)</span>';
        elements.btnContinue.classList.add('hidden');
        return;
    }
    
    const startTime = state.timeSlots[startSlot]?.display;
    const endTimeIndex = Math.min(endSlot + 1, state.timeSlots.length - 1);
    const endTime = state.timeSlots[endSlot + 1]?.display || state.timeSlots[state.timeSlots.length - 1]?.display || '5:00 PM';

    elements.selectionInfo.innerHTML = `
        <strong>✓ Selected:</strong> ${escapeHtml(startTime)} - ${escapeHtml(endTime)} 
        (${hours} hour${hours !== 1 ? 's' : ''})
        <br><small>Click individual slots to add/remove, or drag to select a range</small>
    `;
    elements.btnContinue.classList.remove('hidden');
}

// ============================================
// SELECTION HANDLERS
// ============================================

function selectPeerSupport() {
    // Redirect to peer support information page
    window.location.href = '/peer-support';
}

async function selectDate(date) {
    // Step 1: pick a Friday first
    state.selectedDate = date;
    state.selectedRoom = null;
    state.selectedSlots = [];

    // Update UI
    document.querySelectorAll('.date-card').forEach(card => {
        card.classList.remove('selected');
    });
    event.currentTarget.classList.add('selected');

    // Load the rooms available on this date, then show them
    elements.roomGrid.innerHTML = '<p class="loading">Loading rooms...</p>';
    showStep('room');
    await loadRooms(date);
}

// Step 2: choose the yoga session instead of a room. Yoga has no time slots
// (it always starts at 10am), so this goes straight to the details step, where
// the yoga questions are shown in place of the room ones.
function selectYoga() {
    const yoga = state.yogaSessions[state.selectedDate];
    if (!yoga || yoga.full) return;

    state.bookingType = 'yoga';
    state.selectedYoga = yoga;
    state.selectedRoom = null;
    state.selectedSlots = [];

    document.querySelectorAll('.room-card').forEach(c => c.classList.remove('selected'));
    if (typeof event !== 'undefined' && event && event.currentTarget) {
        event.currentTarget.classList.add('selected');
    }

    const subtitle = document.getElementById('booking-subtitle');
    if (subtitle) subtitle.classList.add('hidden');

    showEmailStep();
}

// Show the question set that matches what's being booked
function applyBookingTypeFields() {
    const isYoga = state.bookingType === 'yoga';
    const roomFields = document.getElementById('room-fields');
    const yogaFields = document.getElementById('yoga-fields');
    if (roomFields) roomFields.hidden = isYoga;
    if (yogaFields) yogaFields.hidden = !isYoga;

    const heading = document.querySelector('#step-email h2');
    if (heading) {
        heading.textContent = isYoga
            ? 'Step 4: Your Yoga Registration Details'
            : 'Step 4: Enter Your Details';
    }
}

function selectRoom(roomId) {
    // Step 2: pick a room available on the chosen Friday
    state.bookingType = 'room';
    state.selectedYoga = null;
    state.selectedRoom = state.rooms.find(r => r.id === roomId);
    state.selectedSlots = [];

    // Update UI
    document.querySelectorAll('.room-card').forEach(card => {
        card.classList.remove('selected');
    });
    event.currentTarget.classList.add('selected');

    // Show/hide subtitle based on room type
    const subtitle = document.getElementById('booking-subtitle');
    if (subtitle) {
        if (state.selectedRoom.room_type === 'open') {
            subtitle.classList.add('hidden');
        } else {
            subtitle.classList.remove('hidden');
        }
    }

    // Open rooms book the whole day, so skip time selection
    if (state.selectedRoom.room_type === 'open') {
        showEmailStepForOpenRoom();
    } else {
        showStep('time');
        loadAvailability();
    }
}



// ============================================
// STEP NAVIGATION
// ============================================

function showStep(stepName) {
    Object.keys(steps).forEach(key => {
        if (key === stepName) {
            steps[key].classList.remove('hidden');
        } else {
            steps[key].classList.add('hidden');
        }
    });
}

function backToDate() {
    state.selectedRoom = null;
    state.bookingType = 'room';
    state.selectedYoga = null;
    state.selectedSlots = [];

    // Reset subtitle visibility
    const subtitle = document.getElementById('booking-subtitle');
    if (subtitle) {
        subtitle.classList.remove('hidden');
    }

    showStep('date');
}

function backToRoom() {
    state.selectedSlots = [];
    showStep('room');
}

function showTimeStep() {
    showStep('time');
}

function showEmailStep() {
    // Yoga: fixed session, no time slots to summarise
    if (state.bookingType === 'yoga') {
        const yoga = state.selectedYoga;
        if (!yoga) return;
        const placesLeft = `${yoga.remaining} of ${yoga.capacity} place${yoga.remaining === 1 ? '' : 's'} left`;
        elements.bookingSummary.innerHTML = `
            <h3>Booking Summary</h3>
            <div class="summary-row">
                <span>Activity:</span>
                <strong>🧘 Gentle Yoga with Marlijn</strong>
            </div>
            <div class="summary-row">
                <span>Location:</span>
                <span>Outdoor terrace, Pan Macmillan</span>
            </div>
            <div class="summary-row">
                <span>Date:</span>
                <span>${escapeHtml(yoga.display)}</span>
            </div>
            <div class="summary-row">
                <span>Time:</span>
                <span>Arrive from 9:30am — session starts ${escapeHtml(yoga.time)}</span>
            </div>
            <div class="summary-row">
                <span>Availability:</span>
                <span>${escapeHtml(placesLeft)}</span>
            </div>
        `;
        applyBookingTypeFields();
        showStep('email');
        return;
    }

    // Validate selection for slot rooms
    if (state.selectedRoom.room_type === 'slot' && state.selectedSlots.length === 0) return;

    let startTime, endTime;
    
    // Special cases for Room 4.2 "Indigo" on specific dates
    const isMarch20th = state.selectedDate === '2026-03-20';
    const isApril10th = state.selectedDate === '2026-04-10';
    const isRoom4_2 = state.selectedRoom.name.includes('4.2') || state.selectedRoom.name.toLowerCase().includes('indigo');
    
    // Check for May 8th special case
    const isMay8th = state.selectedDate === '2026-05-08';
    const isRoom4_7 = state.selectedRoom.name.includes('4.7') || state.selectedRoom.name.toLowerCase().includes('clerkenwell');
    
    if (state.selectedRoom.room_type === 'open') {
        // Admin-set custom hours for this date take precedence
        if (state.selectedRoom.override_start && state.selectedRoom.override_end) {
            startTime = state.selectedRoom.override_start;
            endTime = state.selectedRoom.override_end;
        } else if (isMay8th && (isRoom4_2 || isRoom4_7)) {
            // May 8th: Rooms 4.2 and 4.7 start at 12:30pm
            startTime = state.timeSlots[3]?.display || '12:30 PM';
            endTime = '4:00 PM';
        } else if (isMarch20th && isRoom4_2) {
            startTime = state.timeSlots[0]?.display || '11:00 AM';
            endTime = '2:30 PM';
        } else if (isApril10th && isRoom4_2) {
            startTime = state.timeSlots[0]?.display || '11:00 AM';
            endTime = '1:30 PM';
        } else {
            // Open rooms reserve the full day: first slot to the last slot
            startTime = state.timeSlots[0]?.display || '9:30 AM';
            endTime = state.timeSlots[state.timeSlots.length - 1]?.display || '5:00 PM';
        }
    } else {
        // Slot rooms: use selected slots
        const sortedSlots = [...state.selectedSlots].sort((a, b) => a - b);
        const startSlot = sortedSlots[0];
        const endSlot = sortedSlots[sortedSlots.length - 1];
        startTime = state.timeSlots[startSlot]?.display;
        endTime = state.timeSlots[endSlot + 1]?.display || state.timeSlots[state.timeSlots.length - 1]?.display || '5:00 PM';
    }
    
    const dateDisplay = state.fridays.find(f => f.date === state.selectedDate)?.display;
    const roomTypeLabel = state.selectedRoom.room_type === 'open' ? 'Open Booking' : 'Time Slot Booking';
    
    // Determine if individual or shared use
    const isRoom4_4_Rose = state.selectedRoom.name.includes('4.4') || state.selectedRoom.name.toLowerCase().includes('rose');
    const useType = isRoom4_4_Rose ? 'Individual Use' : 'Shared Use';
    const useTypeClass = isRoom4_4_Rose ? 'individual-use' : 'shared-use';
    
    elements.bookingSummary.innerHTML = `
        <h3>Booking Summary</h3>
        <div class="summary-row">
            <span>Room:</span>
            <strong>${escapeHtml(state.selectedRoom.name)}</strong>
        </div>
        <div class="summary-row">
            <span>Use:</span>
            <span class="${useTypeClass}" style="font-weight: 600; color: ${isRoom4_4_Rose ? '#dc2626' : '#16a34a'};">${useType}</span>
        </div>
        <div class="summary-row">
            <span>Location:</span>
            <span>${escapeHtml(state.selectedRoom.building_location)}</span>
        </div>
        <div class="summary-row">
            <span>Type:</span>
            <span>${roomTypeLabel}</span>
        </div>
        <div class="summary-row">
            <span>Date:</span>
            <span>${escapeHtml(dateDisplay)}</span>
        </div>
        <div class="summary-row">
            <span>Time:</span>
            <span>${escapeHtml(startTime)} - ${escapeHtml(endTime)}</span>
        </div>
        ${state.selectedRoom.note ? `
        <div class="summary-note">
            <strong>⚠️ Please note about this date</strong>
            <p>${escapeHtml(state.selectedRoom.note)}</p>
        </div>` : ''}
    `;

    applyBookingTypeFields();
    showStep('email');
}

function showEmailStepForOpenRoom() {
    // For open rooms, skip time selection and go straight to email step
    showEmailStep();
}

function showEmailStepBack() {
    // Yoga and open rooms both skip time selection, so go back to step 2
    // For slot rooms, go back to time selection (step 3)
    if (state.bookingType === 'yoga' || state.selectedRoom.room_type === 'open') {
        showStep('room');
    } else {
        showStep('time');
    }
}

function resetBooking() {
    state.selectedRoom = null;
    state.selectedDate = null;
    state.bookingType = 'room';
    state.selectedYoga = null;
    state.selectedSlots = [];
    elements.firstNameInput.value = '';
    elements.lastNameInput.value = '';
    elements.emailInput.value = '';
    resetAttendeeFields();

    // Reset subtitle visibility
    const subtitle = document.getElementById('booking-subtitle');
    if (subtitle) {
        subtitle.classList.remove('hidden');
    }

    showStep('date');
    renderDates();
}

// ============================================
// STEP 4 — WHO ELSE IS ATTENDING
// ============================================

function isBringingOthers() {
    const el = document.querySelector('input[name="bringing-others"]:checked');
    return !!el && el.value === 'yes';
}

function isCarerAttending() {
    const el = document.querySelector('input[name="carer-attending"]:checked');
    return !!el && el.value === 'yes';
}

// The carer questions only appear once someone says a carer/support worker is
// coming, so the form stays short for the common "just me" case.
function updateAttendeeFields() {
    const bringing = isBringingOthers();
    const companions = document.getElementById('companions-field');
    const carerSection = document.getElementById('carer-section');
    if (!companions || !carerSection) return;

    companions.hidden = !bringing;
    if (!bringing) {
        // Clear anything already entered so it can't be submitted invisibly
        document.getElementById('companion-names').value = '';
        const carerNo = document.querySelector('input[name="carer-attending"][value="no"]');
        if (carerNo) carerNo.checked = true;
    }

    const showCarer = bringing && isCarerAttending();
    carerSection.hidden = !showCarer;
    if (!showCarer) {
        ['carer-name', 'carer-organisation', 'carer-phone'].forEach(id => {
            document.getElementById(id).value = '';
        });
        document.getElementById('carer-supervision-agreed').checked = false;
    }
}

document.addEventListener('DOMContentLoaded', () => {
    document.querySelectorAll('input[name="bringing-others"], input[name="carer-attending"]')
        .forEach(radio => radio.addEventListener('change', updateAttendeeFields));
    updateAttendeeFields();
});

function resetAttendeeFields() {
    const justMe = document.querySelector('input[name="bringing-others"][value="no"]');
    if (justMe) justMe.checked = true;
    ['accessibility-needs', 'other-info'].forEach(id => {
        const el = document.getElementById(id);
        if (el) el.value = '';
    });
    updateAttendeeFields();
    resetYogaFields();
}

function resetYogaFields() {
    ['yoga-phone', 'yoga-ec-name', 'yoga-ec-phone', 'yoga-health', 'yoga-avoid', 'yoga-access']
        .forEach(id => {
            const el = document.getElementById(id);
            if (el) el.value = '';
        });
    ['yoga-agree', 'yoga-reuse'].forEach(id => {
        const el = document.getElementById(id);
        if (el) el.checked = false;
    });
    document.querySelectorAll('input[name="yoga-experience"]').forEach(r => { r.checked = false; });
}

// ============================================
// BOOKING SUBMISSION
// ============================================

async function submitYogaBooking(name, email) {
    const val = (id) => (document.getElementById(id).value || '').trim();
    const experienceEl = document.querySelector('input[name="yoga-experience"]:checked');

    const payload = {
        session_date: state.selectedDate,
        name: name,
        email: email,
        phone: val('yoga-phone'),
        emergency_name: val('yoga-ec-name'),
        emergency_phone: val('yoga-ec-phone'),
        experience: experienceEl ? experienceEl.value : '',
        health_info: val('yoga-health'),
        avoid_info: val('yoga-avoid'),
        accessibility_info: val('yoga-access'),
        agreed_safety: document.getElementById('yoga-agree').checked,
        reuse_previous: document.getElementById('yoga-reuse').checked
    };

    if (!payload.phone) { alert('Please enter a phone number.'); document.getElementById('yoga-phone').focus(); return; }
    if (!payload.emergency_name) { alert('Please enter an emergency contact name.'); document.getElementById('yoga-ec-name').focus(); return; }
    if (!payload.emergency_phone) { alert('Please enter an emergency contact phone number.'); document.getElementById('yoga-ec-phone').focus(); return; }
    if (!payload.experience) { alert('Please let us know if you have done yoga before.'); return; }
    if (!payload.agreed_safety) { alert('Please tick the box to confirm you understand the session is gentle and you can rest at any time.'); document.getElementById('yoga-agree').focus(); return; }

    const confirmBtn = document.getElementById('btn-confirm-booking');
    if (confirmBtn) { confirmBtn.disabled = true; confirmBtn.textContent = 'Booking…'; }

    try {
        const response = await fetch('/api/yoga/book', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(payload)
        });
        const data = await response.json().catch(() => ({}));

        if (response.ok && data.success) {
            elements.confirmationMessage.textContent =
                `Thank you ${name}, your place is registered.\n\n` +
                `🧘 Gentle Yoga with Marlijn\n` +
                `${data.date_display}\n` +
                `The terrace is available from 9:30am, so you're welcome to arrive any time from then. The session starts at ${data.time}.\n` +
                `Where: Outdoor terrace, Pan Macmillan, 6 Briset Street, London, EC1M 5NR\n\n` +
                `Please bring your own yoga mat and wear loose, comfortable clothing.\n\n` +
                `✉️ A confirmation email is on its way — if it hasn't arrived in a few minutes, please check your spam/junk folder. Your place is safe either way.`;
            showStep('confirmation');
            loadYogaSessions();   // refresh remaining places
        } else if (data.full) {
            alert(data.error || 'Sorry, this session is now full. Please choose another date.');
            await loadYogaSessions();
            showStep('room');
            renderRooms();
        } else {
            alert(data.error || 'Something went wrong. Please try again.');
        }
    } catch (error) {
        alert('Something went wrong while confirming. Your place may still have been registered — please contact us before trying again.');
    } finally {
        if (confirmBtn) { confirmBtn.disabled = false; confirmBtn.textContent = 'Confirm Booking'; }
    }
}

async function submitBooking() {
    const firstName = elements.firstNameInput.value.trim();
    const lastName = elements.lastNameInput.value.trim();
    const email = elements.emailInput.value.trim();
    
    if (!firstName) {
        alert('Please enter your first name');
        return;
    }
    
    if (!lastName) {
        alert('Please enter your last name');
        return;
    }
    
    const name = `${firstName} ${lastName}`;
    
    if (!email || !email.includes('@')) {
        alert('Please enter a valid email address');
        return;
    }

    // Yoga registrations go to the yoga endpoint, which enforces the 8-place
    // capacity and stores the safety answers against the session
    if (state.bookingType === 'yoga') {
        await submitYogaBooking(name, email);
        return;
    }

    const bringingOthers = isBringingOthers();
    const carerAttending = bringingOthers && isCarerAttending();
    const companionNames = document.getElementById('companion-names').value.trim();
    const carerName = document.getElementById('carer-name').value.trim();
    const carerOrganisation = document.getElementById('carer-organisation').value.trim();
    const carerPhone = document.getElementById('carer-phone').value.trim();
    const carerAgreed = document.getElementById('carer-supervision-agreed').checked;

    // Mirror the server-side checks so people get an immediate, specific prompt
    if (bringingOthers && !companionNames) {
        alert('Please give the first name(s) of who is coming with you, so we can plan numbers.');
        document.getElementById('companion-names').focus();
        return;
    }
    if (carerAttending) {
        if (!carerName) {
            alert("Please enter the carer or support worker's full name.");
            document.getElementById('carer-name').focus();
            return;
        }
        if (!carerOrganisation) {
            alert("Please enter the carer or support worker's agency or organisation (or write 'Independent' or 'Family').");
            document.getElementById('carer-organisation').focus();
            return;
        }
        if (!carerPhone) {
            alert("Please enter a mobile number for the carer or support worker, so we can contact them on the day.");
            document.getElementById('carer-phone').focus();
            return;
        }
        if (!carerAgreed) {
            alert('Please tick the box to confirm the carer or support worker remains responsible for supervision.');
            document.getElementById('carer-supervision-agreed').focus();
            return;
        }
    }

    const bookingData = {
        room_id: state.selectedRoom.id,
        date: state.selectedDate,
        name: name,
        email: email,
        accessibility_needs: document.getElementById('accessibility-needs').value.trim(),
        bringing_others: bringingOthers,
        companion_names: companionNames,
        other_info: document.getElementById('other-info').value.trim(),
        carer_attending: carerAttending,
        carer_name: carerName,
        carer_organisation: carerOrganisation,
        carer_phone: carerPhone,
        carer_supervision_agreed: carerAgreed
    };

    // Only add slots for slot-type rooms
    if (state.selectedRoom.room_type === 'slot') {
        if (state.selectedSlots.length === 0) {
            alert('Please select time slots');
            return;
        }
        const sortedSlots = [...state.selectedSlots].sort((a, b) => a - b);
        bookingData.start_slot = sortedSlots[0];
        bookingData.end_slot = sortedSlots[sortedSlots.length - 1] + 1; // Exclusive end
    }
    
    const confirmBtn = document.getElementById('btn-confirm-booking');
    if (confirmBtn) {
        confirmBtn.disabled = true;
        confirmBtn.textContent = 'Booking…';
    }

    try {
        const response = await fetch('/api/book', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(bookingData)
        });

        const result = await response.json();

        if (response.ok) {
            let emailStatus = '';
            if (result.email_sent) {
                emailStatus = '\n\n✉️ A confirmation email is on its way to your inbox — if it hasn\'t arrived in a few minutes, please check your spam/junk folder. Your booking is confirmed either way.';
            } else {
                emailStatus = '\n\n⚠️ Note: Email delivery is not configured. Please save your confirmation details.';
            }

            elements.confirmationMessage.textContent = result.confirmation_message + emailStatus;
            showStep('confirmation');
        } else {
            alert(result.error || 'Failed to create booking');
        }
    } catch (error) {
        alert('Something went wrong while confirming. Your booking may still have been saved — please check "My Bookings" at the bottom of the page (using your email) before trying again.');
    } finally {
        if (confirmBtn) {
            confirmBtn.disabled = false;
            confirmBtn.textContent = 'Confirm Booking';
        }
    }
}

// ============================================
// MY BOOKINGS
// ============================================

async function loadMyBookings() {
    const email = document.getElementById('my-bookings-email').value.trim();
    
    if (!email) {
        alert('Please enter your email address');
        return;
    }
    
    try {
        const response = await fetch('/api/my-bookings', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ email })
        });
        
        const bookings = await response.json();
        
        if (response.ok) {
            renderMyBookings(bookings);
        } else {
            elements.myBookingsList.innerHTML = `<p class="error-text">${bookings.error}</p>`;
        }
    } catch (error) {
        elements.myBookingsList.innerHTML = '<p class="error-text">Failed to load bookings</p>';
    }
}

function renderMyBookings(bookings) {
    if (bookings.length === 0) {
        elements.myBookingsList.innerHTML = '<p>No upcoming bookings found</p>';
        return;
    }
    
    elements.myBookingsList.innerHTML = bookings.map(booking => `
        <div class="booking-item">
            <div class="booking-item-info">
                <h4>${escapeHtml(booking.room_name)}</h4>
                <p>${escapeHtml(booking.date_display)} | ${escapeHtml(booking.start_time)} - ${escapeHtml(booking.end_time)}</p>
                <small>Booked by: ${escapeHtml(booking.name)}</small>
            </div>
            <a href="/cancel/${booking.cancel_token}" class="btn btn-small btn-danger">Cancel</a>
        </div>
    `).join('');
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
