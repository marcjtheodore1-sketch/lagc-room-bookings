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
    
    container.innerHTML = rooms.map(room => `
        <div class="room-item ${room.is_active ? '' : 'inactive'}">
            <div class="room-item-info">
                <h4>${escapeHtml(room.name)} ${!room.is_active ? '<span class="badge">(Inactive)</span>' : ''}</h4>
                <p>${escapeHtml(room.building_location)}</p>
            </div>
            <div class="room-item-actions">
                <button class="btn btn-small btn-secondary" onclick="editRoom(${room.id}, '${escapeHtml(room.name)}', '${escapeHtml(room.building_location)}', ${room.is_active})">Edit</button>
                <button class="btn btn-small btn-danger" onclick="deleteRoom(${room.id})">Delete</button>
            </div>
        </div>
    `).join('');
}

async function addRoom() {
    const nameInput = document.getElementById('new-room-name');
    const locationInput = document.getElementById('new-room-location');
    
    const name = nameInput.value.trim();
    const location = locationInput.value.trim();
    
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
                is_active: true
            })
        });
        
        if (response.ok) {
            nameInput.value = '';
            locationInput.value = '';
            loadRooms();
        } else {
            alert('Failed to add room');
        }
    } catch (error) {
        alert('Network error');
    }
}

async function editRoom(id, currentName, currentLocation, currentActive) {
    const name = prompt('Room name:', currentName);
    if (name === null) return;
    
    const location = prompt('Building location:', currentLocation);
    if (location === null) return;
    
    const isActive = confirm('Is this room active? (OK = Yes, Cancel = No)');
    
    try {
        const response = await fetch(`/api/admin/rooms/${id}`, {
            method: 'PUT',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                name: name || currentName,
                building_location: location || currentLocation,
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
    const tbody = document.querySelector('#admin-bookings-table tbody');
    tbody.innerHTML = '<tr><td colspan="4" class="loading">Loading bookings...</td></tr>';
    
    try {
        const response = await fetch('/api/admin/bookings');
        const bookings = await response.json();
        renderBookingsTable(bookings);
    } catch (error) {
        tbody.innerHTML = '<tr><td colspan="4" class="error-text">Failed to load bookings</td></tr>';
    }
}

function renderBookingsTable(bookings) {
    const tbody = document.querySelector('#admin-bookings-table tbody');
    
    if (bookings.length === 0) {
        tbody.innerHTML = '<tr><td colspan="4" style="text-align:center;padding:2rem;">No upcoming bookings</td></tr>';
        return;
    }
    
    tbody.innerHTML = bookings.map(booking => `
        <tr>
            <td>${escapeHtml(booking.room_name)}</td>
            <td>${escapeHtml(booking.date_display)}</td>
            <td>${escapeHtml(booking.start_time)} - ${escapeHtml(booking.end_time)}</td>
            <td>${escapeHtml(booking.user_name)}</td>
            <td>${escapeHtml(booking.user_email)}</td>
            <td>
                <button class="btn btn-small btn-danger" onclick="deleteBooking(${booking.id})">Delete</button>
            </td>
        </tr>
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
