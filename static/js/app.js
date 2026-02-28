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
    nameInput: document.getElementById('name'),
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

async function loadFridays() {
    try {
        const response = await fetch('/api/fridays');
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

    elements.roomGrid.innerHTML = state.rooms.map(room => `
        <div class="room-card" onclick="selectRoom(${room.id})">
            <h3>${escapeHtml(room.name)}</h3>
            <p>${escapeHtml(room.building_location)}</p>
        </div>
    `).join('');
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
    const endTime = state.timeSlots[endSlot + 1]?.display || '17:30';
    
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

function selectRoom(roomId) {
    state.selectedRoom = state.rooms.find(r => r.id === roomId);
    
    // Update UI
    document.querySelectorAll('.room-card').forEach(card => {
        card.classList.remove('selected');
    });
    event.currentTarget.classList.add('selected');
    
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
    
    // Show next step and load availability
    showStep('time');
    loadAvailability();
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
    // Validate selection
    if (state.selectedSlots.length === 0) return;
    
    const sortedSlots = [...state.selectedSlots].sort((a, b) => a - b);
    const startSlot = sortedSlots[0];
    const endSlot = sortedSlots[sortedSlots.length - 1];
    
    // Build summary
    const startTime = state.timeSlots[startSlot]?.display;
    const endTime = state.timeSlots[endSlot + 1]?.display || '17:30';
    const dateDisplay = state.fridays.find(f => f.date === state.selectedDate)?.display;
    
    elements.bookingSummary.innerHTML = `
        <h3>Booking Summary</h3>
        <div class="summary-row">
            <span>Room:</span>
            <strong>${escapeHtml(state.selectedRoom.name)}</strong>
        </div>
        <div class="summary-row">
            <span>Location:</span>
            <span>${escapeHtml(state.selectedRoom.building_location)}</span>
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

function resetBooking() {
    state.selectedRoom = null;
    state.selectedDate = null;
    state.selectedSlots = [];
    elements.nameInput.value = '';
    elements.emailInput.value = '';
    showStep('room');
    renderRooms();
}

// ============================================
// BOOKING SUBMISSION
// ============================================

async function submitBooking() {
    const name = elements.nameInput.value.trim();
    const email = elements.emailInput.value.trim();
    
    if (!name) {
        alert('Please enter your name');
        return;
    }
    
    if (!email || !email.includes('@')) {
        alert('Please enter a valid email address');
        return;
    }
    
    const sortedSlots = [...state.selectedSlots].sort((a, b) => a - b);
    const startSlot = sortedSlots[0];
    const endSlot = sortedSlots[sortedSlots.length - 1] + 1; // Exclusive end
    
    const bookingData = {
        room_id: state.selectedRoom.id,
        date: state.selectedDate,
        name: name,
        email: email,
        start_slot: startSlot,
        end_slot: endSlot
    };
    
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
