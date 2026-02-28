/**
 * Room Booking System - Cancellation Page JavaScript
 */

let bookingData = null;

document.addEventListener('DOMContentLoaded', () => {
    loadBookingDetails();
});

async function loadBookingDetails() {
    const loadingEl = document.getElementById('loading-state');
    const detailsEl = document.getElementById('booking-details');
    const errorEl = document.getElementById('cancel-error');
    
    try {
        const response = await fetch(`/api/booking/${CANCEL_TOKEN}`);
        
        if (response.ok) {
            bookingData = await response.json();
            displayBookingDetails();
            loadingEl.classList.add('hidden');
            detailsEl.classList.remove('hidden');
        } else {
            const error = await response.json();
            loadingEl.classList.add('hidden');
            errorEl.classList.remove('hidden');
            document.getElementById('error-text').textContent = error.error || 'Booking not found';
        }
    } catch (error) {
        loadingEl.classList.add('hidden');
        errorEl.classList.remove('hidden');
        document.getElementById('error-text').textContent = 'Failed to load booking details';
    }
}

function displayBookingDetails() {
    document.getElementById('detail-room').textContent = bookingData.room_name;
    document.getElementById('detail-location').textContent = bookingData.building_location;
    document.getElementById('detail-date').textContent = bookingData.date_display;
    document.getElementById('detail-time').textContent = `${bookingData.start_time} - ${bookingData.end_time}`;
    document.getElementById('detail-email').textContent = bookingData.email;
}

async function confirmCancel() {
    const detailsEl = document.getElementById('booking-details');
    const successEl = document.getElementById('cancel-success');
    const errorEl = document.getElementById('cancel-error');
    
    try {
        const response = await fetch(`/api/cancel/${CANCEL_TOKEN}`, {
            method: 'POST'
        });
        
        const result = await response.json();
        
        if (response.ok) {
            detailsEl.classList.add('hidden');
            successEl.classList.remove('hidden');
            
            // Update the "Back to My Bookings" link with the email
            if (bookingData && bookingData.email) {
                const backLink = document.getElementById('back-to-bookings');
                backLink.href = `/?email=${encodeURIComponent(bookingData.email)}#my-bookings`;
            }
        } else {
            detailsEl.classList.add('hidden');
            errorEl.classList.remove('hidden');
            document.getElementById('error-text').textContent = result.error || 'Failed to cancel booking';
        }
    } catch (error) {
        detailsEl.classList.add('hidden');
        errorEl.classList.remove('hidden');
        document.getElementById('error-text').textContent = 'Network error. Please try again.';
    }
}
