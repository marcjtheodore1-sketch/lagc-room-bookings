# Deploy to Render (Free Hosting)

## Quick Deploy Steps

### 1. Create a GitHub Repository
```bash
cd room_booking
git init
git add .
git commit -m "Initial commit"
# Create a new repo on GitHub, then:
git remote add origin https://github.com/YOUR_USERNAME/lagc-room-bookings.git
git push -u origin main
```

### 2. Sign up for Render
Go to https://render.com and sign up with your GitHub account.

### 3. Create New Web Service
1. Click "New +" → "Web Service"
2. Connect your GitHub repository
3. Use these settings:
   - **Name**: `lagc-room-bookings` (or any name you like)
   - **Environment**: Python 3
   - **Build Command**: `pip install -r requirements.txt`
   - **Start Command**: `gunicorn app:app`

4. Click "Create Web Service"

### 4. Add Environment Variables (Optional)
After deployment, go to Environment tab and add:
- `ADMIN_PASSWORD` = `Moonlight` (or your preferred password)
- `ENABLE_EMAIL` = `true` (if you want email notifications)
- `SMTP_HOST` = `smtp.gmail.com`
- `SMTP_PORT` = `587`
- `SMTP_USER` = `miles.lagc@gmail.com`
- `SMTP_PASSWORD` = `your-app-password`
- `SMTP_FROM` = `londonautismgroupcharity@gmail.com`

### 5. Add Persistent Disk (Important!)
The free tier doesn't include persistent storage by default. To keep your database:
1. Go to "Disks" in your service
2. Add a disk:
   - **Name**: `data`
   - **Mount Path**: `/var/lib/render`
   - **Size**: 1 GB (free tier allows this)

### 6. Your Site is Live!
Render will give you a URL like:
`https://lagc-room-bookings.onrender.com`

## Important Notes

- **Free tier**: Site sleeps after 15 minutes of inactivity (takes ~30 seconds to wake up)
- **Database**: SQLite will be reset on every deploy unless you add a persistent disk
- **Custom domain**: You can add your own domain later in the settings

## Alternative: PythonAnywhere (Also Free)

If Render doesn't work, try https://pythonanywhere.com - it's also free and very popular for Python/Flask apps.
