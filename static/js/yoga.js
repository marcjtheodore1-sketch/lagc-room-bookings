/**
 * Gentle Yoga with Marlijn — registration page
 */
(function () {
    const form = document.getElementById('yoga-form');
    if (!form) return;

    const dateSelect = document.getElementById('yoga-date');
    const statusEl = document.getElementById('yoga-status');
    const submitBtn = document.getElementById('yoga-submit');

    function setStatus(msg, kind) {
        statusEl.textContent = msg || '';
        statusEl.className = 'form-status' + (msg ? ' ' + kind : '');
    }

    // Refresh availability so the dropdown reflects live spaces
    async function refreshAvailability(keepSelection) {
        try {
            const res = await fetch('/api/yoga/availability');
            const sessions = await res.json();
            const current = keepSelection ? dateSelect.value : '';
            dateSelect.innerHTML = '<option value="">— Select a date —</option>' +
                sessions.map(s => {
                    const label = s.full
                        ? `${s.display}, ${s.time} — FULL`
                        : `${s.display}, ${s.time} — ${s.remaining} of ${s.capacity} place${s.remaining === 1 ? '' : 's'} left`;
                    const selected = (s.date === current && !s.full) ? ' selected' : '';
                    return `<option value="${s.date}"${s.full ? ' disabled' : ''}${selected}>${label}</option>`;
                }).join('');
            if (!sessions.length) {
                setStatus('There are no upcoming sessions open for registration right now.', 'error');
            }
        } catch (e) {
            /* leave the server-rendered options in place */
        }
    }

    form.addEventListener('submit', async function (e) {
        e.preventDefault();
        setStatus('', '');

        const payload = {
            session_date: dateSelect.value,
            name: form.name.value.trim(),
            email: form.email.value.trim(),
            phone: form.phone.value.trim(),
            emergency_name: form.emergency_name.value.trim(),
            emergency_phone: form.emergency_phone.value.trim(),
            experience: (form.querySelector('input[name="experience"]:checked') || {}).value || '',
            health_info: form.health_info.value.trim(),
            avoid_info: form.avoid_info.value.trim(),
            accessibility_info: form.accessibility_info.value.trim(),
            agreed_safety: document.getElementById('yoga-agree').checked,
        };

        if (!payload.session_date) { setStatus('Please choose a session date.', 'error'); dateSelect.focus(); return; }
        if (!payload.name || !payload.email || !payload.phone || !payload.emergency_name || !payload.emergency_phone) {
            setStatus('Please fill in all the required fields marked with *.', 'error'); return;
        }
        if (!payload.experience) { setStatus('Please let us know if you have done yoga before.', 'error'); return; }
        if (!payload.agreed_safety) { setStatus('Please tick the box to confirm you understand the session is gentle and you can rest at any time.', 'error'); return; }

        submitBtn.disabled = true;
        submitBtn.textContent = 'Sending…';
        try {
            const res = await fetch('/api/yoga/book', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(payload),
            });
            const data = await res.json().catch(() => ({}));
            if (res.ok && data.success) {
                form.style.display = 'none';
                setStatus('', '');
                const done = document.createElement('div');
                done.className = 'notice-box success';
                done.innerHTML = `<p><strong>Thank you — your place is registered.</strong></p>
                    <p>We've reserved your spot for <strong>${data.date_display}</strong> at ${data.time}. A confirmation has been sent to your email.</p>
                    <p>Please bring your own mat and wear comfortable clothing. You can choose what to take part in and rest whenever you need to.</p>`;
                form.parentNode.appendChild(done);
                done.scrollIntoView({ behavior: 'smooth', block: 'center' });
                return;
            }
            if (data.full) {
                setStatus(data.error || 'Sorry, this session is now full. Please choose another date.', 'error');
                await refreshAvailability(false);
            } else {
                setStatus(data.error || 'Something went wrong. Please try again.', 'error');
            }
        } catch (e) {
            setStatus('Sorry, we could not submit your registration right now. Please try again.', 'error');
        } finally {
            submitBtn.disabled = false;
            submitBtn.textContent = 'Register for this session';
        }
    });

    refreshAvailability(true);
})();
