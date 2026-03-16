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
    if (tabName === 'archive') loadArchivedBookings();
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
