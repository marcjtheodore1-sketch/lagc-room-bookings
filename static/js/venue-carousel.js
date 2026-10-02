/* A quiet venue-photo carousel, independent of the booking controls. */
document.addEventListener('DOMContentLoaded', () => {
    const carousel = document.getElementById('venue-carousel');
    if (!carousel) return;

    const slides = Array.from(carousel.querySelectorAll('.venue-photo-slide'));
    const controls = carousel.querySelector('.venue-photo-controls');
    const pauseButton = document.getElementById('venue-photo-pause');
    const name = document.getElementById('venue-photo-name');
    const status = document.getElementById('venue-photo-status');
    const reducedMotion = window.matchMedia('(prefers-reduced-motion: reduce)');
    let current = 0;
    let paused = reducedMotion.matches;
    let timer = null;
    let inView = true;

    function stop() {
        window.clearInterval(timer);
        timer = null;
    }

    function start() {
        stop();
        if (!paused && inView && !document.hidden) {
            timer = window.setInterval(() => showNext(1, false), 5000);
        }
    }

    function updatePauseButton() {
        pauseButton.textContent = paused ? 'Play' : 'Pause';
        pauseButton.setAttribute('aria-label', paused ? 'Play photo carousel' : 'Pause photo carousel');
    }

    function showNext(direction, manual) {
        let next = current;
        // Keep the current photo if another image is still loading or fails.
        for (let step = 1; step < slides.length; step++) {
            const candidate = (current + direction * step + slides.length) % slides.length;
            const image = slides[candidate].querySelector('img');
            if (image.complete && image.naturalWidth > 0) {
                next = candidate;
                break;
            }
        }
        if (next === current) return;
        slides[current].classList.remove('is-active');
        slides[current].setAttribute('aria-hidden', 'true');
        slides[next].classList.add('is-active');
        slides[next].setAttribute('aria-hidden', 'false');
        current = next;
        name.textContent = slides[current].dataset.caption;
        // Automatic changes are silent for screen readers.
        if (manual) {
            paused = true;
            stop();
            updatePauseButton();
            status.textContent = slides[current].dataset.caption + ', photo ' + (current + 1) + ' of ' + slides.length;
        }
    }

    document.getElementById('venue-photo-prev').addEventListener('click', () => showNext(-1, true));
    document.getElementById('venue-photo-next').addEventListener('click', () => showNext(1, true));
    pauseButton.addEventListener('click', () => {
        paused = !paused;
        updatePauseButton();
        start();
    });
    // Stop movement when someone starts exploring the controls by keyboard.
    carousel.addEventListener('focusin', event => {
        if (event.target.matches(':focus-visible')) {
            paused = true;
            stop();
            updatePauseButton();
        }
    });
    document.addEventListener('visibilitychange', start);
    reducedMotion.addEventListener('change', event => {
        if (event.matches) paused = true;
        updatePauseButton();
        start();
    });
    if ('IntersectionObserver' in window) {
        new IntersectionObserver(entries => {
            inView = entries[0].isIntersecting;
            start();
        }).observe(carousel);
    }
    controls.hidden = false;
    updatePauseButton();
    start();
});
