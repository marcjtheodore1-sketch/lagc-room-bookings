/**
 * Room Booking System - Main Application JavaScript
 */

// State
let state = {
    rooms: [],
    fridays: [],
    timeSlots: [],
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

document.addEventListener('DOMContentLoaded', () => {
    loadRooms();
    loadFridays();
    loadTimeSlots();
    
    // Check for email in URL (coming from cancel page)
    checkUrlForEmail();
});

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

async function loadRooms() {
    try {
        const response = await fetch('/api/rooms');
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

function renderRooms() {
    if (state.rooms.length === 0) {
        elements.roomGrid.innerHTML = '<p>No rooms available</p>';
        return;
    }

    elements.roomGrid.innerHTML = state.rooms.map(room => {
        const typeBadge = room.room_type === 'open' 
            ? '<span class="room-type-badge open">Open Booking</span>' 
            : '<span class="room-type-badge slot">Time Slots</span>';
        const typeHint = room.room_type === 'open'
            ? '<small class="room-hint">11am - 4pm</small>'
            : '<small class="room-hint">30 min slots</small>';
        
        return `
        <div class="room-card" onclick="selectRoom(${room.id})">
            <h3>${escapeHtml(room.name)} ${typeBadge}</h3>
            <p>${escapeHtml(room.building_location)}</p>
            ${typeHint}
        </div>
    `}).join('');
}

function renderDates() {
    elements.dateGrid.innerHTML = state.fridays.map(friday => `
        <div class="date-card" onclick="selectDate('${friday.date}')">
            ${escapeHtml(friday.display)}
        </div>
    `).join('');
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
    const endTime = state.timeSlots[endSlot + 1]?.display || '16:00';
    
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

async function selectRoom(roomId) {
    state.selectedRoom = state.rooms.find(r => r.id === roomId);
    
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
    
    // Load available dates for this specific room
    await loadFridays(roomId);
    
    // Show next step
    showStep('date');
    renderDates();
}

function selectDate(date) {
    state.selectedDate = date;
    state.selectedSlots = [];
    
    // Update UI
    document.querySelectorAll('.date-card').forEach(card => {
        card.classList.remove('selected');
    });
    event.currentTarget.classList.add('selected');
    
    // Check room type - open rooms skip time selection
    if (state.selectedRoom.room_type === 'open') {
        // For open rooms, auto-select full day (11am-4pm)
        showEmailStepForOpenRoom();
    } else {
        // For slot rooms, show time selection
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

function resetRoom() {
    state.selectedRoom = null;
    state.selectedDate = null;
    state.selectedSlots = [];
    
    // Reset subtitle visibility
    const subtitle = document.getElementById('booking-subtitle');
    if (subtitle) {
        subtitle.classList.remove('hidden');
    }
    
    showStep('room');
    renderRooms();
}

function resetDate() {
    state.selectedDate = null;
    state.selectedSlots = [];
    showStep('date');
}

function showTimeStep() {
    showStep('time');
}

function showEmailStep() {
    // Validate selection for slot rooms
    if (state.selectedRoom.room_type === 'slot' && state.selectedSlots.length === 0) return;
    
    let startTime, endTime;
    
    // Special case: Room 4.2 "Indigo" on March 20th, 2026 - only available until 2:30pm
    const isMarch20th = state.selectedDate === '2026-03-20';
    const isRoom4_2 = state.selectedRoom.name.includes('4.2') || state.selectedRoom.name.toLowerCase().includes('indigo');
    
    if (state.selectedRoom.room_type === 'open') {
        // Open rooms: full day (or until 2:30pm for Room 4.2 on March 20th)
        startTime = state.timeSlots[0]?.display || '11:00 AM';
        if (isMarch20th && isRoom4_2) {
            endTime = '2:30 PM';
        } else {
            endTime = '4:00 PM';
        }
    } else {
        // Slot rooms: use selected slots
        const sortedSlots = [...state.selectedSlots].sort((a, b) => a - b);
        const startSlot = sortedSlots[0];
        const endSlot = sortedSlots[sortedSlots.length - 1];
        startTime = state.timeSlots[startSlot]?.display;
        endTime = state.timeSlots[endSlot + 1]?.display || '16:00';
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
    `;
    
    showStep('email');
}

function showEmailStepForOpenRoom() {
    // For open rooms, skip time selection and go straight to email step
    showEmailStep();
}

function showEmailStepBack() {
    // For open rooms, go back to date selection (step 2)
    // For slot rooms, go back to time selection (step 3)
    if (state.selectedRoom.room_type === 'open') {
        showStep('date');
    } else {
        showStep('time');
    }
}

function resetBooking() {
    state.selectedRoom = null;
    state.selectedDate = null;
    state.selectedSlots = [];
    elements.firstNameInput.value = '';
    elements.lastNameInput.value = '';
    elements.emailInput.value = '';
    
    // Reset subtitle visibility
    const subtitle = document.getElementById('booking-subtitle');
    if (subtitle) {
        subtitle.classList.remove('hidden');
    }
    
    showStep('room');
    renderRooms();
}

// ============================================
// BOOKING SUBMISSION
// ============================================

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
    
    const bookingData = {
        room_id: state.selectedRoom.id,
        date: state.selectedDate,
        name: name,
        email: email
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
                emailStatus = '\n\n✉️ A confirmation email has been sent to your inbox.';
            } else {
                emailStatus = '\n\n⚠️ Note: Email delivery is not configured. Please save your confirmation details.';
            }
            
            elements.confirmationMessage.textContent = result.confirmation_message + emailStatus;
            showStep('confirmation');
        } else {
            alert(result.error || 'Failed to create booking');
        }
    } catch (error) {
        alert('Network error. Please try again.');
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
