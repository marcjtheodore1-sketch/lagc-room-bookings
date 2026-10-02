# Reverting the October visual refresh

Chris approved publishing the visual refresh on 2nd October 2026, with the
previous appearance retained for rollback if the team prefers it.

## Saved previous release

- Git tag: `farringdon-before-visual-refresh-2026-10-02`
- Previous live commit: `f2a28b5c12b4b5445910512d63347cc13cd1b669`
- Visual commits, in reverse order: `64434db`, `d9349a8`
- Production checkout: `~/lagc-room-bookings` on MilesTheodore's PythonAnywhere account
- Site: https://milestheodore.pythonanywhere.com/

The visual commits change only the shared stylesheet, homepage markup, login
stylesheet include and venue-carousel script. Reverting those commits preserves
the booking, reminders, volunteer rota, email-blast and building-report features.
Do not restore an old database or reset the whole repository.

## Restore the previous appearance after Chris requests it

In the local repository, ensure main is current and the working tree is clean.
Then prepare and review the visual-only reversal:

```sh
git switch main
git pull --ff-only origin main
git revert --no-commit 64434db d9349a8
git diff --cached --check
git diff --cached --stat
```

If later edits cause conflicts, resolve and review them before proceeding.
Confirm no backend or database files are changed. Commit and publish the revert:

```sh
git commit -m "Restore previous Farringdon appearance"
git push origin main
```

In the existing PythonAnywhere console:

```sh
cd ~/lagc-room-bookings
git fetch origin main
git merge --ff-only origin/main
```

Then open PythonAnywhere's **Web** tab while signed in as MilesTheodore and click
**Reload MilesTheodore.pythonanywhere.com**. Use this reload button: touching the
WSGI file did not refresh the cached templates during this visual deployment.

Check the live homepage, booking page and reminders page. The new presentation
stylesheet and carousel should no longer be referenced. Do not send test emails.

The saved tag is a permanent reference, not an instruction to roll back the
database or remove newer functional changes.
